"""Bounded discovery primitives; no outbound messaging or model dependencies."""

import hashlib
import json
import os
import random
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
import psutil
import urllib3


class DiscoveryFault(Exception):
    def __init__(self, status, reason, retry_after=0):
        super().__init__(reason)
        self.status, self.reason, self.retry_after = status, reason, retry_after


def resource(reason):
    return DiscoveryFault("deferred_resource_limit", reason)


def unavailable(reason, retry_after=0):
    return DiscoveryFault("deferred_provider_unavailable", reason, retry_after)


def permission(reason):
    return DiscoveryFault("blocked_permission_or_license", reason)


def schema(reason="dataset_schema_changed"):
    return DiscoveryFault("failed_requires_operator", reason)


class Budget:
    def __init__(self, config, *, clock=time.monotonic):
        self.config, self.clock = config, clock
        self.started = clock()
        self.requests = self.bytes = self.queries = self.candidates = 0

    def check(self):
        if self.clock() - self.started >= self.config.max_seconds:
            raise resource("discovery_deadline")
        if psutil.Process().memory_info().rss > self.config.max_memory_mb * 1024 * 1024:
            raise resource("memory_budget")

    def request(self):
        self.check()
        if self.requests >= self.config.max_requests:
            raise resource("request_budget")
        self.requests += 1

    def consume(self, size):
        self.check()
        self.bytes += size
        if self.bytes > self.config.max_download_bytes:
            raise resource("network_byte_budget")

    def query(self):
        self.check()
        if self.queries >= self.config.max_queries:
            raise resource("query_budget")
        self.queries += 1

    def candidate(self):
        self.check()
        if self.candidates >= self.config.max_candidates:
            raise resource("candidate_budget")
        self.candidates += 1


def retry_delay(value, now=None):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        try:
            return max(0, (parsedate_to_datetime(value) - (now or datetime.now(UTC))).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 0


class BoundedHTTP:
    """Fixed authorized data origins only. No redirects, proxy or endpoint rotation."""

    def __init__(self, budget, client=None, *, sleep=time.sleep, jitter=random.random):
        self.budget = budget
        self.client = client or httpx.Client(timeout=15, follow_redirects=False, trust_env=False)
        self.sleep, self.jitter = sleep, jitter

    def get_pinned(self, url, *, cap, params):
        """Operator-configured endpoints need DNS pinning, unlike fixed official dataset origins."""
        from website_agent.security import Blocked, PublicWeb

        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.query or parsed.fragment:
            raise permission("configured_endpoint_requires_plain_https")
        web = PublicWeb(max_bytes=cap, discovery_budget=self.budget)
        for attempt in range(self.budget.config.max_attempts):
            try:
                response = web.fetch(url + "?" + urlencode(params), robots=False, redirects=False)
                if response.status == 429 or (response.status >= 500 and response.headers.get("retry-after")):
                    raise unavailable(
                        "provider_rate_limited", max(3600, retry_delay(response.headers.get("retry-after")))
                    )
                if response.status in {401, 403}:
                    raise permission("provider_access_denied")
                if response.status >= 500:
                    raise OSError("transient")
                if response.status != 200:
                    raise schema("provider_http_permanent_error")
                return response.text.encode(), response.headers
            except Blocked:
                raise permission("configured_endpoint_safety_check_failed") from None
            except (OSError, urllib3.exceptions.HTTPError):
                if attempt + 1 == self.budget.config.max_attempts:
                    raise unavailable("transport_retries_exhausted") from None
                self.budget.check()
                self.sleep(self.budget.config.retry_base_seconds * 2**attempt + self.jitter())
        raise unavailable("transport_retries_exhausted")

    def get(self, url, *, cap=None, headers=None, params=None):
        p = urlsplit(url)
        if p.scheme != "https" or p.username or p.password or p.port not in {None, 443}:
            raise permission("data_endpoint_requires_public_https")
        available = self.budget.config.max_download_bytes - self.budget.bytes
        if available <= 0 or (cap is not None and cap > available):
            raise resource("network_byte_budget")
        cap = min(cap or available, available)
        for attempt in range(self.budget.config.max_attempts):
            self.budget.request()
            try:
                with self.client.stream(
                    "GET", url, params=params, headers={"Accept-Encoding": "identity", **(headers or {})}
                ) as r:
                    if r.status_code == 429:
                        raise unavailable(
                            "provider_rate_limited", max(3600, retry_delay(r.headers.get("retry-after")))
                        )
                    if r.status_code in {401, 403}:
                        raise permission("provider_access_denied")
                    if r.status_code >= 500:
                        if r.headers.get("retry-after"):
                            raise unavailable("provider_retry_after", retry_delay(r.headers["retry-after"]))
                        raise httpx.ConnectError("transient")
                    if r.status_code not in {200, 206}:
                        raise schema("provider_http_permanent_error")
                    if "Range" in (headers or {}) and r.status_code != 206:
                        raise schema("range_requests_not_supported")
                    if int(r.headers.get("content-length", 0)) > cap:
                        raise resource("response_byte_budget")
                    if r.headers.get("content-encoding", "identity") != "identity":
                        raise schema("unexpected_compressed_transport")
                    data = bytearray()
                    for chunk in r.iter_raw():
                        # Count failed/partial attempts as well as successful downloads.
                        self.budget.consume(len(chunk))
                        if len(data) + len(chunk) > cap:
                            raise resource("response_byte_budget")
                        data.extend(chunk)
                    if r.headers.get("content-length") and len(data) != int(r.headers["content-length"]):
                        raise httpx.ReadError("partial")
                    return bytes(data), dict(r.headers)
            except httpx.TransportError:
                if attempt + 1 == self.budget.config.max_attempts:
                    raise unavailable("transport_retries_exhausted") from None
                delay = self.budget.config.retry_base_seconds * 2**attempt + self.jitter()
                self.budget.check()
                self.sleep(delay)
        raise unavailable("transport_retries_exhausted")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def atomic_json(path, value, max_bytes):
    path = Path(path)
    raw = json.dumps(value, ensure_ascii=True).encode()
    if len(raw) > max_bytes:
        raise resource("disk_budget")
    path.parent.mkdir(parents=True, exist_ok=True)
    used = sum(p.stat().st_size for p in path.parent.iterdir() if p.is_file())
    if used + len(raw) > max_bytes:
        raise resource("disk_budget")
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def token(value):
    return re.sub(r"[\W_]+", " ", str(value).casefold()).strip()


def inside(bbox, lon, lat):
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


def category_matches(category, hierarchy, allowed):
    # Only exact reviewed category IDs, including their published descendants.
    return category in allowed or bool(
        hierarchy and hierarchy[-1] == category and set(hierarchy) & set(allowed)
    )
