"""Persistent bounded fallback orchestration; configuration table is the recovery journal."""

import copy
import json
import math
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import psutil
import urllib3
import yaml
from pydantic import ValidationError
from sqlalchemy import select

from website_agent.database import (
    BusinessSource,
    Configuration,
    Prospect,
    assert_lock,
    get_config,
    now,
)
from website_agent.discovery_support import (
    Budget,
    DiscoveryFault,
    atomic_json,
    fingerprint,
    permission,
    resource,
    schema,
    unavailable,
)
from website_agent.discovery_verify import Candidate, duplicate_or_suppressed, verify_candidate
from website_agent.scheduler import contact_time, rotate
from website_agent.security import Blocked, PublicWeb, domain


def run_reader(config, query, budget):
    """Bound native decoding by preflight size checks plus a disposable RSS/time watchdog."""
    root = Path("private/discovery-worker")
    root.mkdir(parents=True, exist_ok=True)
    invocation = uuid.uuid4().hex
    spec, output = root / (invocation + ".input.json"), root / (invocation + ".output.json")
    output.unlink(missing_ok=True)
    remaining = config.model_copy(
        update={
            "max_requests": config.max_requests - budget.requests,
            "max_download_bytes": config.max_download_bytes - budget.bytes,
            "max_seconds": max(1, int(config.max_seconds - (budget.clock() - budget.started))),
        }
    )
    if remaining.max_requests <= 0 or remaining.max_download_bytes < 1024:
        raise resource("request_or_network_budget")
    atomic_json(spec, {"config": remaining.model_dump(), "query": query}, config.max_disk_bytes // 2)
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    with subprocess.Popen(
        [sys.executable, "-m", "website_agent.discovery_worker", str(spec), str(output)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    ) as process:
        try:
            while process.poll() is None:
                budget.check()
                try:
                    if psutil.Process(process.pid).memory_info().rss > config.max_memory_mb * 1024 * 1024:
                        raise resource("worker_memory_budget")
                except psutil.NoSuchProcess:
                    pass
                time.sleep(0.05)
            if not output.exists():
                raise resource("worker_terminated_without_checkpoint")
            if output.stat().st_size > config.max_disk_bytes:
                raise resource("worker_output_budget")
            result = json.loads(output.read_text())
            budget.requests += result["requests"]
            budget.bytes += result["bytes"]
            if "fault" in result:
                raise DiscoveryFault(**result["fault"])
            return result["data"]
        except BaseException:
            if process.poll() is None:
                process.kill()
                process.wait()
                # Unknown partial transfer: conservatively reserve the remaining allowance.
                budget.bytes, budget.requests = config.max_download_bytes, config.max_requests
            raise
        finally:
            spec.unlink(missing_ok=True)
            output.unlink(missing_ok=True)


def areas(location, config):
    if not location.bbox:
        raise permission("location_bbox_not_configured")
    w, s, e, n = location.bbox
    lon, lat = (w + e) / 2, (s + n) / 2
    result = []
    for radius in sorted(set(config.radius_steps_km + [config.max_radius_km])):
        dx, dy = radius / (111.32 * max(0.05, math.cos(math.radians(lat)))), radius / 111.32
        bbox = [max(w, lon - dx), max(s, lat - dy), min(e, lon + dx), min(n, lat + dy)]
        if not result or result[-1]["bbox"] != bbox:
            result.append(
                {
                    "city": location.city,
                    "country": location.country,
                    "bbox": bbox,
                    "center": [lon, lat],
                    "radius_km": radius,
                }
            )
    for area in location.nearby_areas[:4]:
        aw, a_s, ae, an = area.bbox
        # Every corner must remain within the configured distance from the original center.
        distance = max(
            math.hypot((x - lon) * 111.32 * math.cos(math.radians(lat)), (y - lat) * 111.32)
            for x in (aw, ae)
            for y in (a_s, an)
        )
        if area.country == location.country and distance <= config.max_radius_km:
            result.append({**area.model_dump(), "center": [lon, lat], "radius_km": config.max_radius_km})
    return result


class DiscoveryEngine:
    def __init__(self, session, settings, config, *, web=None, reader=run_reader, clock=now, selector=rotate):
        self.session, self.settings, self.config = session, settings, config
        self.options = config.discovery
        self.budget = Budget(self.options)
        self.web = web or PublicWeb(
            settings.research_user_agent, max_bytes=500_000, discovery_budget=self.budget
        )
        self.reader, self.clock, self.selector = reader, clock, selector
        self.cache = Path("private/discovery-cache")
        self.accepted = self.unverified = 0

    def save(self, key, state, *, commit=True):
        assert_lock(self.session)
        row = self.session.scalar(select(Configuration).where(Configuration.key == key))
        if row:
            row.value = json.loads(json.dumps(state))
        else:
            self.session.add(Configuration(key=key, value=json.loads(json.dumps(state))))
        if commit:
            self.session.commit()

    def plan(self, country):
        taxonomy = yaml.safe_load(Path(self.options.taxonomy_path).read_text(encoding="utf-8"))
        if not taxonomy.get("review_reference"):
            raise permission("taxonomy_review_required")
        entries, visited = [], set()
        for _ in range(self.options.max_cities):
            selected = self.selector(
                self.session, self.config, country, at=self.clock(), exclude_cities=visited
            )
            if not selected:
                break
            queue, location = selected
            visited.add((location.country, location.city))
            mapping = taxonomy.get("niches", {}).get(queue.niche)
            if not mapping:
                raise permission("niche_taxonomy_not_reviewed")
            location_areas = areas(location, self.options)
            # Exact category and providers first, geographic expansion next, related categories last.
            for related in (False, True):
                for area in location_areas:
                    for source in self.options.source_priority:
                        if source == "overture" and not self.options.overture_enabled:
                            continue
                        categories = mapping.get("related" if related else "primary", {}).get(
                            "overture" if source == "overture" else "osm", []
                        )
                        if not categories:
                            continue
                        entries.append(
                            {
                                **area,
                                "source": source,
                                "categories": categories,
                                "related": related,
                                "niche": queue.niche,
                                "rotation_city": location.city,
                                "timezone": location.timezone,
                                "language": location.language,
                                "subdivision": location.subdivision,
                                "cursor": {},
                                "done": False,
                            }
                        )
        return entries

    def health_key(self, source, query=None):
        # Overture mirrors share a rate-limit circuit; Azure is never used to evade a 429.
        scope = {"source": source, "options": self.options.model_dump()}
        if source == "osm_extract" and query:
            scope["region"] = [query["country"], query["city"]]
        return "discovery_health:" + fingerprint(scope)

    def query(self, query):
        source = query["source"]
        if source in {"osm_extract", "overpass"}:
            from website_agent.discovery_datasets import osm_allowed

            osm_allowed(self.options)
            if source == "overpass" and not (
                self.options.overpass_private_or_contracted
                and self.options.overpass_commercial_use_authorized
                and self.options.overpass_agreement_reference
                and self.options.overpass_endpoint
            ):
                raise permission("overpass_commercial_endpoint_not_authorized")
        health_key = self.health_key(source, query)
        health = get_config(self.session, health_key)
        cache_key = fingerprint(
            {
                "query": {k: v for k, v in query.items() if k not in {"fault", "done"}},
                "release": self.options.release,
                "license": self.options.osm_license_review_reference,
                "extracts": self.options.osm_extracts,
            }
        )
        cache_path = self.cache / (cache_key + ".json")
        if (
            self.options.cache_hours
            and cache_path.exists()
            and cache_path.stat().st_size <= self.options.max_disk_bytes
        ):
            try:
                saved = json.loads(cache_path.read_text())
                if (
                    saved["digest"] == fingerprint(saved["data"])
                    and datetime.fromisoformat(saved["expires"]) > self.clock()
                ):
                    return saved["data"]
            except (ValueError, KeyError):
                pass
        if health.get("permanent"):
            raise DiscoveryFault(health["status"], health["reason"])
        if health.get("next_at") and datetime.fromisoformat(health["next_at"]) > self.clock():
            raise DiscoveryFault(
                health["status"],
                health["reason"],
                (datetime.fromisoformat(health["next_at"]) - self.clock()).total_seconds(),
            )
        self.budget.query()
        try:
            try:
                data = self.reader(self.options, {**query, "endpoint": "aws"}, self.budget)
            except DiscoveryFault as exc:
                if source != "overture" or exc.status != "deferred_provider_unavailable" or exc.retry_after:
                    raise
                data = self.reader(self.options, {**query, "endpoint": "azure"}, self.budget)
            if data.get("fault"):
                fault = data["fault"]
                self.save(
                    health_key,
                    {
                        **fault,
                        "failures": health.get("failures", 0) + 1,
                        "permanent": fault["status"] == "failed_requires_operator",
                        "next_at": (
                            self.clock()
                            + timedelta(
                                seconds=max(self.options.cooldown_seconds, fault.get("retry_after", 0))
                            )
                        ).isoformat(),
                    },
                )
            else:
                self.save(
                    health_key, {"status": "healthy", "last_success": self.clock().isoformat(), "failures": 0}
                )
            if self.options.cache_hours and not data.get("fault"):
                try:
                    atomic_json(
                        cache_path,
                        {
                            "data": data,
                            "digest": fingerprint(data),
                            "expires": (self.clock() + timedelta(hours=self.options.cache_hours)).isoformat(),
                        },
                        self.options.max_disk_bytes // 2,
                    )
                except (DiscoveryFault, OSError):
                    # A verified response remains usable when optional caching is full.
                    pass
            return data
        except DiscoveryFault as exc:
            if exc.status != "deferred_resource_limit":
                self.save(
                    health_key,
                    {
                        "status": exc.status,
                        "reason": exc.reason,
                        "failures": health.get("failures", 0) + 1,
                        "permanent": exc.status == "failed_requires_operator",
                        "next_at": (
                            self.clock()
                            + timedelta(seconds=max(self.options.cooldown_seconds, exc.retry_after))
                        ).isoformat(),
                    },
                )
            raise

    def admit(self, raw, query, state, key):
        self.budget.candidate()
        try:
            candidate = Candidate.model_validate(raw)
            url, evidence = verify_candidate(candidate, query, self.web, self.session)
        except (
            ValidationError,
            Blocked,
            ValueError,
            OSError,
            urllib3.exceptions.HTTPError,
            httpx.TransportError,
        ):
            self.unverified += 1
            return False
        host = domain(url)
        if duplicate_or_suppressed(self.session, candidate, host):
            return False
        prospect = Prospect(
            name=candidate.name,
            domain=host,
            url=url,
            country=candidate.country,
            city=candidate.city,
            niche=candidate.category,
            timezone=query["timezone"],
            language=query["language"],
            subdivision=query["subdivision"],
        )
        self.session.add(prospect)
        self.session.flush()
        self.session.add(
            BusinessSource(
                prospect_id=prospect.id,
                provider=candidate.provider,
                provider_id=candidate.provider_id,
                evidence={
                    **evidence,
                    "dataset_release": candidate.release,
                    "retrieved_at": state["pending"]["retrieved_at"],
                    "verified_at": self.clock().isoformat(),
                    "license": candidate.license,
                    "attribution": candidate.attribution,
                    "sources": candidate.sources,
                    "address": candidate.address,
                    "requested_niche": query["niche"],
                    "rotation_city": query.get("rotation_city", query["city"]),
                },
            )
        )
        state["accepted"] += 1
        state["cycles"] = 0
        # Admission and pending cursor advancement commit in the SAME transaction.
        state["pending"]["index"] += 1
        self.save(key, state)
        self.accepted += 1
        return True

    def run(self, country=None):
        key = "discovery_task:" + (country or "worldwide")
        signature = fingerprint(
            {
                "options": self.options.model_dump(),
                "locations": [x.model_dump() for x in self.config.locations],
                "niches": self.config.niches,
                "taxonomy": Path(self.options.taxonomy_path).read_text(),
            }
        )
        state = copy.deepcopy(get_config(self.session, key))
        if state.get("signature") != signature:
            state = {}
        if state.get("next_at") and datetime.fromisoformat(state["next_at"]) > self.clock():
            return {
                "status": state["status"],
                "reason": "waiting_for_persisted_retry",
                "accepted": 0,
                "next_at": state["next_at"],
            }
        if state.get("status") == "failed_requires_operator":
            return {"status": state["status"], "reason": state.get("reason"), "accepted": 0}
        if not state or state.get("complete") or not state.get("plan"):
            try:
                plan = self.plan(country)
                if not plan:
                    raise unavailable("no_eligible_local_research_window", 3600)
            except DiscoveryFault as exc:
                state = {"signature": signature, "plan": [], "accepted": 0, "cycles": 0, "complete": True}
                return self.finish(key, state, exc.status, exc.reason, exc.retry_after)
            state = {
                "signature": signature,
                "plan": plan,
                "index": 0,
                "accepted": 0,
                "cycles": 0,
                "status": "running",
                "pending": None,
            }
            self.save(key, state)
        else:
            if state.get("reason") not in {
                "outside_local_research_window",
                "no_eligible_local_research_window",
            }:
                state["cycles"] = state.get("cycles", 0) + 1
            if state["cycles"] > self.options.max_retry_cycles:
                return self.finish(key, state, "failed_requires_operator", "retry_cycles_exhausted")
            self.save(key, state)
        try:
            while state["index"] < len(state["plan"]):
                self.budget.check()
                query = state["plan"][state["index"]]
                if query.get("done"):
                    state["index"] += 1
                    continue
                if not contact_time(
                    self.clock(),
                    query["country"],
                    query["timezone"],
                    self.config.research_hours,
                    query["subdivision"],
                ):
                    query["fault"] = {
                        "status": "deferred_provider_unavailable",
                        "reason": "outside_local_research_window",
                        "retry_after": 3600,
                    }
                    if state.get("pending"):
                        return self.finish(
                            key, state, "deferred_provider_unavailable", "outside_local_research_window", 3600
                        )
                    state["index"] += 1
                    self.save(key, state)
                    continue
                if not state.get("pending"):
                    try:
                        data = self.query(query)
                        if not isinstance(data.get("records"), list):
                            raise schema("invalid_reader_result")
                        state["pending"] = {
                            "data": data,
                            "index": 0,
                            "retrieved_at": self.clock().isoformat(),
                        }
                        self.save(key, state)
                    except DiscoveryFault as exc:
                        query["fault"] = {
                            "status": exc.status,
                            "reason": exc.reason,
                            "retry_after": exc.retry_after,
                        }
                        if exc.status == "deferred_resource_limit":
                            raise
                        state["index"] += 1
                        self.save(key, state)
                        continue
                pending = state["pending"]
                while pending["index"] < len(pending["data"]["records"]):
                    if self.accepted >= min(30, self.config.limits.discovered):
                        return self.finish(key, state, "completed_with_results", "run_target_reached")
                    raw = pending["data"]["records"][pending["index"]]
                    if not self.admit(raw, query, state, key):
                        pending["index"] += 1
                        self.save(key, state)
                    if self.accepted >= min(30, self.config.limits.discovered):
                        return self.finish(key, state, "completed_with_results", "run_target_reached")
                new_cursor = pending["data"].get("cursor", {})
                if new_cursor != query.get("cursor") or pending["data"]["exhausted"]:
                    state["cycles"] = 0
                query["cursor"] = new_cursor
                query["resolved_release"] = pending["data"].get("release")
                query["done"] = bool(pending["data"]["exhausted"])
                if pending["data"].get("fault"):
                    query["fault"] = pending["data"]["fault"]
                else:
                    query.pop("fault", None)
                state["pending"] = None
                state["index"] += 1
                self.save(key, state)
            incomplete = [q for q in state["plan"] if not q["done"]]
            faults = [q["fault"] for q in incomplete if q.get("fault")]
            for status in ("failed_requires_operator", "deferred_provider_unavailable"):
                fault = next((f for f in faults if f["status"] == status), None)
                if fault:
                    return self.finish(
                        key, state, status, fault["reason"], max(f.get("retry_after", 0) for f in faults)
                    )
            if any(
                not q.get("fault") or q["fault"]["status"] == "deferred_resource_limit" for q in incomplete
            ):
                return self.finish(key, state, "deferred_resource_limit", "bounded_scan_has_remaining_pages")
            if faults and not any(q["done"] for q in state["plan"]):
                return self.finish(key, state, "blocked_permission_or_license", faults[0]["reason"])
            status = "completed_with_results" if state["accepted"] else "completed_no_qualified_results"
            return self.finish(key, state, status, "configured_search_scope_exhausted")
        except DiscoveryFault as exc:
            return self.finish(key, state, exc.status, exc.reason, exc.retry_after)
        except MemoryError:
            return self.finish(key, state, "deferred_resource_limit", "memory_budget")
        # Database errors and hard termination propagate: no false success, previous commit survives.

    def finish(self, key, state, status, reason, retry_after=0):
        complete = status.startswith("completed")
        delay = (
            self.options.empty_retry_hours * 3600
            if complete
            else max(self.options.cooldown_seconds, retry_after)
        )
        state.update(
            status=status,
            reason=reason,
            complete=complete,
            next_at=(self.clock() + timedelta(seconds=delay)).isoformat(),
        )
        if state.get("index", 0) >= len(state["plan"]):
            state["index"] = 0
        self.save(key, state)
        return {
            "status": status,
            "reason": reason,
            "accepted": self.accepted,
            "accepted_in_task": state["accepted"],
            "unverified": self.unverified,
            "next_at": state["next_at"],
            "requests": self.budget.requests,
            "bytes": self.budget.bytes,
            "queries": self.budget.queries,
        }
