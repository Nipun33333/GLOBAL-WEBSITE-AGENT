import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import certifi
import urllib3


class Blocked(RuntimeError):
    """An operation is unavailable or intentionally fail-closed."""


class CapacityDeferred(Blocked):
    """A configured capacity is exhausted; unfinished work remains durable."""


def domain(url):
    host = urlsplit(url if "://" in url else "https://" + url).hostname or ""
    host = host.rstrip(".").encode("idna").decode("ascii").lower()
    return host.removeprefix("www.")


def email_address(value):
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+", value):
        raise ValueError("Invalid email address")
    return value


def public_addresses(url):
    p = urlsplit(url)
    if p.scheme not in {"https", "http"} or not p.hostname or p.username or p.password:
        raise Blocked("Only public HTTP(S) URLs without credentials are permitted")
    if p.port not in {None, 80, 443}:
        raise Blocked("Nonstandard port")
    addresses = sorted(
        {
            a[4][0]
            for a in socket.getaddrinfo(
                p.hostname, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM
            )
        }
    )
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise Blocked("Private, reserved, or mixed public/private address")
    return addresses


@dataclass
class Page:
    url: str
    status: int
    headers: dict
    text: str


class PublicWeb:
    """Pins checked DNS addresses at connection time, including every redirect."""

    def __init__(self, user_agent="GlobalWebsiteConceptBot/1.0", max_bytes=1_000_000):
        self.user_agent = user_agent
        self.max_bytes = max_bytes
        self.robots = {}

    def fetch(self, url, *, robots=True):
        for _ in range(5):
            p = urlsplit(url)
            addresses = public_addresses(url)
            origin = urlunsplit((p.scheme, p.netloc, "", "", ""))
            if robots:
                if origin not in self.robots:
                    rp = RobotFileParser()
                    response = self.fetch(origin + "/robots.txt", robots=False)
                    if response.status == 404:
                        rp.parse([])
                    elif response.status == 200:
                        rp.parse(response.text.splitlines())
                    else:
                        raise Blocked("robots.txt unavailable; research paused")
                    self.robots[origin] = rp
                if not self.robots[origin].can_fetch(self.user_agent, url):
                    raise Blocked("robots.txt disallows research")
            kwargs = {
                "host": addresses[0],
                "port": p.port or (443 if p.scheme == "https" else 80),
                "timeout": urllib3.Timeout(connect=8, read=15),
                "retries": False,
            }
            if p.scheme == "https":
                pool = urllib3.HTTPSConnectionPool(
                    **kwargs,
                    server_hostname=p.hostname,
                    assert_hostname=p.hostname,
                    cert_reqs="CERT_REQUIRED",
                    ca_certs=certifi.where(),
                )
            else:
                pool = urllib3.HTTPConnectionPool(**kwargs)
            try:
                response = pool.request(
                    "GET",
                    urlunsplit(("", "", p.path or "/", p.query, "")),
                    headers={"Host": p.netloc, "User-Agent": self.user_agent, "Accept-Encoding": "identity"},
                    preload_content=False,
                    redirect=False,
                )
                try:
                    if response.status in {301, 302, 303, 307, 308}:
                        url = urljoin(url, response.headers["Location"])
                        continue
                    content = response.read(self.max_bytes + 1, decode_content=True)
                    if len(content) > self.max_bytes:
                        raise Blocked("Page exceeds research size limit")
                    return Page(
                        url,
                        response.status,
                        {k.lower(): v for k, v in response.headers.items()},
                        content.decode("utf-8", errors="replace"),
                    )
                finally:
                    response.close()
            finally:
                pool.close()
        raise Blocked("Too many redirects")


def html_page(page):
    if page.status != 200 or "text/html" not in page.headers.get("content-type", "").lower():
        raise Blocked("Expected successful HTML response")
    if "attachment" in page.headers.get("content-disposition", "").lower():
        raise Blocked("HTML offered as download")
