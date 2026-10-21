"""Conservative deterministic identity checks before any discovery admission."""

import math
from datetime import datetime, timedelta
from email.utils import parseaddr
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import or_, select

from website_agent.database import BusinessSource, Prospect, Suppression, get_config, now, set_config
from website_agent.discovery_support import category_matches, fingerprint, inside, retry_delay, token
from website_agent.security import Blocked, domain, html_page

DIRECTORIES = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "youtube.com",
    "yelp.com",
    "tripadvisor.com",
    "google.com",
    "bing.com",
    "yellowpages.com",
    "justdial.com",
    "foursquare.com",
    "booking.com",
    "amazon.com",
    "ebay.com",
    "etsy.com",
}


class Candidate(BaseModel):
    provider: str = Field(min_length=1, max_length=30)
    provider_id: str = Field(min_length=1, max_length=1000)
    name: str = Field(min_length=2, max_length=300)
    url: HttpUrl
    country: str = Field(pattern=r"^[A-Z]{2}$")
    city: str = Field(min_length=1, max_length=300)
    category: str = Field(min_length=1, max_length=200)
    category_hierarchy: list[str] = Field(default_factory=list, max_length=30)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    release: str = Field(min_length=1, max_length=100)
    license: str = Field(min_length=1, max_length=500)
    attribution: str = Field(min_length=1, max_length=1000)
    sources: list = Field(default_factory=list, max_length=30)
    address: dict = Field(default_factory=dict)


def excluded_host(host):
    return any(host == bad or host.endswith("." + bad) for bad in DIRECTORIES)


def exclusion_reason(session, candidate, host):
    if session.scalar(select(Prospect.id).where(Prospect.domain == host)):
        return "duplicate_domain"
    if session.scalar(
        select(BusinessSource.id).where(
            BusinessSource.provider == candidate.provider, BusinessSource.provider_id == candidate.provider_id
        )
    ):
        return "duplicate_source_id"
    # Imported Base44 domains AND mailbox-only historical exclusions apply.
    parts = host.split(".")
    suffixes = [".".join(parts[i:]) for i in range(len(parts))]
    if session.scalar(
        select(Suppression.id)
        .where(
            or_(
                Suppression.key.in_(suffixes),
                *(Suppression.key.endswith("@" + suffix, autoescape=True) for suffix in suffixes),
            )
        )
        .limit(1)
    ):
        return "suppressed_domain_or_mailbox"
    return None


def duplicate_or_suppressed(session, candidate, host):
    return exclusion_reason(session, candidate, host) is not None


def verify_candidate(candidate, query, web, session):
    if candidate.country != query["country"] or token(candidate.city) != token(query["city"]):
        raise Blocked("unverified_geography")
    if not inside(query["bbox"], candidate.lon, candidate.lat):
        raise Blocked("unverified_coordinates")
    if query.get("center"):
        lon, lat = query["center"]
        distance = math.hypot(
            (candidate.lon - lon) * 111.32 * math.cos(math.radians(lat)), (candidate.lat - lat) * 111.32
        )
        if distance > query["radius_km"]:
            raise Blocked("unverified_outside_radius")
    if not category_matches(candidate.category, candidate.category_hierarchy, query["categories"]):
        raise Blocked("unverified_category")
    url = str(candidate.url)
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
        raise Blocked("unverified_url")
    url = "https://" + parsed.netloc.removesuffix(":80") + (parsed.path or "/")
    # No search/query endpoints or social/directory profiles as an official website.
    if parsed.query or any(
        part in parsed.path.casefold().split("/") for part in ("search", "listing", "listings")
    ):
        raise Blocked("unverified_listing_url")
    host = domain(url)
    if excluded_host(host):
        raise Blocked("excluded_directory_domain")
    if reason := exclusion_reason(session, candidate, host):
        raise Blocked(reason)
    pause_key = "discovery_website_pause:" + fingerprint(host)
    pause = get_config(session, pause_key)
    if pause.get("next_at") and datetime.fromisoformat(pause["next_at"]) > now():
        raise Blocked("unverified_website_cooldown")
    page = web.fetch(url)
    if page.status in {429, 503}:
        delay = max(3600, retry_delay(page.headers.get("retry-after")))
        set_config(session, pause_key, {"next_at": (now() + timedelta(seconds=delay)).isoformat()})
        raise Blocked("unverified_website_rate_or_availability_limit")
    html_page(page)
    canonical_host = domain(page.url)
    if urlsplit(page.url).scheme != "https" or excluded_host(canonical_host):
        raise Blocked("unverified_canonical_url")
    if reason := exclusion_reason(session, candidate, canonical_host):
        raise Blocked(reason)
    soup = BeautifulSoup(page.text, "html.parser")
    # Model output cannot authorize a match. Both visible identity and locality must agree.
    identity = token(" ".join(n.get_text(" ", strip=True) for n in soup.select("title,h1,h2")))
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    text = token(soup.get_text(" ", strip=True))
    business_identity = f" {token(candidate.name)} " in f" {identity} "
    locality_evidence = f" {token(candidate.city)} " in f" {text} "
    official_contact = any(
        domain("https://" + parseaddr(a.get("href", "")[7:])[1].split("@")[-1]) == canonical_host
        for a in soup.select('a[href^="mailto:"]')
        if "@" in a.get("href", "")
    )
    if not business_identity or not locality_evidence or not official_contact:
        raise Blocked("unverified_business_website_association")
    return page.url, {
        "verified_business": True,
        "method": "provider_identity_visible_name_locality_and_own_domain_contact",
        "name_quote": candidate.name,
        "city_quote": candidate.city,
        "source_url": str(candidate.url),
        "canonical_url": page.url,
        "country": candidate.country,
        "coordinates": [candidate.lon, candidate.lat],
        "category": candidate.category,
        "category_hierarchy": candidate.category_hierarchy,
        "audience_status": "history_suppressions_checked_exclusive_assignment_still_required",
    }
