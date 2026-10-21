from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from website_agent.analysis import inspect_site
from website_agent.compliance import eligible
from website_agent.database import CountryPolicy, LocationQueue, Prospect, get_config, set_config, suppress
from website_agent.discovery import Business, SearchProvider, api_get
from website_agent.generation import render, validate
from website_agent.imports import import_history, validate_history
from website_agent.scheduler import business_due, contact_time, rotate
from website_agent.security import Blocked, domain, email_address, public_addresses


def enable(session, settings, prospect):
    settings.enable_sending = True
    prospect.eligibility = {
        "basis": "consent",
        "contact_type": "corporate",
        "evidence_reference": "signed permission",
        "reviewed_by": "reviewer",
        "valid_until": "2027-01-01",
    }
    session.add(
        CountryPolicy(
            country="US",
            policy={
                "enabled": True,
                "reviewed_by": "reviewer",
                "legal_reference": "reviewed policy",
                "valid_until": "2027-01-01",
                "allowed_bases": ["consent"],
                "allowed_contact_types": ["corporate"],
                "contact_hours": [9, 17],
            },
        )
    )
    session.commit()


def test_standalone_eligibility_needs_no_external_history_import(
    session, settings, prospect
):
    # An independently qualified business can pass without old platform tokens,
    # audience attestations, or mandatory bulk contact history imports.
    enable(session, settings, prospect)
    assert get_config(session, "production_readiness") == {}
    assert get_config(session, "gmail_history_import") == {}
    allowed, reasons = eligible(
        session, prospect, settings, datetime(2026, 10, 20, 15, tzinfo=UTC)
    )
    assert allowed and not reasons
    # Stored opt-outs must still block this otherwise eligible recipient.
    suppress(session, prospect.email, "unsubscribe", "verified customer request")
    allowed, reasons = eligible(
        session, prospect, settings, datetime(2026, 10, 20, 15, tzinfo=UTC)
    )
    assert not allowed and "suppressed" in reasons


def test_normalization():
    assert domain("https://WWW.Example.COM:443/path") == "example.com"
    assert email_address(" INFO@EXAMPLE.COM ") == "info@example.com"
    with pytest.raises(ValueError):
        email_address("x@example.com\r\nBcc:bad@example.com")


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "http://user:pass@example.com", "https://example.com:444"]
)
def test_bad_urls(url):
    with pytest.raises(Blocked):
        public_addresses(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "100.64.0.1"])
def test_private_networks(monkeypatch, address):
    monkeypatch.setattr(
        "website_agent.security.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (address, 443))]
    )
    with pytest.raises(Blocked):
        public_addresses("https://example.com")


def test_source_audit(fakes):
    result = inspect_site(fakes.web, "https://sample.example")
    assert 0 <= result["score"] < 55
    assert result["contact"]["email"] == "contact@sample.example"
    assert result["lighthouse_ran"] is False
    assert result["findings"]


def test_country_rules_fail_closed(session, settings, prospect):
    okay, reasons = eligible(session, prospect, settings, datetime(2026, 10, 20, 15, tzinfo=UTC))
    assert not okay
    assert "sending_disabled" in reasons and "unverified_country_policy" in reasons


def test_country_rules_and_suppression(session, settings, prospect):
    enable(session, settings, prospect)
    at = datetime(2026, 10, 20, 15, tzinfo=UTC)
    assert eligible(session, prospect, settings, at) == (True, [])
    prospect.eligibility = {**prospect.eligibility, "basis": "public_email"}
    assert not eligible(session, prospect, settings, at)[0]
    prospect.eligibility = {**prospect.eligibility, "basis": "consent"}
    suppress(session, prospect.domain, "optout", "record")
    assert "suppressed" in eligible(session, prospect, settings, at)[1]


def test_expired_policy_and_individual(session, settings, prospect):
    enable(session, settings, prospect)
    prospect.eligibility = {**prospect.eligibility, "contact_type": "sole_trader"}
    assert not eligible(session, prospect, settings, datetime(2026, 10, 20, 15, tzinfo=UTC))[0]
    assert not eligible(session, prospect, settings, datetime(2027, 2, 1, 15, tzinfo=UTC))[0]


def test_business_days_and_dst():
    at = datetime(2026, 10, 29, 14, tzinfo=UTC)
    due = business_due(at, "US", "America/New_York", "NY")
    # New York observes Election Day on November 3.
    assert due.date().isoformat() == "2026-11-06"
    assert due.hour == 10
    assert due.utcoffset() == timedelta(hours=-5)
    assert not contact_time(datetime(2026, 12, 25, 15, tzinfo=UTC), "US", "America/New_York", [9, 17])


def test_rotation_fair_and_no_repeat(session, config):
    config.research_hours = [0, 24]
    seen = []
    at = datetime(2026, 10, 20, 10, tzinfo=UTC)
    eligible_locations = [
        loc
        for loc in config.locations
        if contact_time(at, loc.country, loc.timezone, [0, 24], loc.subdivision)
    ]
    config.locations = eligible_locations
    for _ in range(len(eligible_locations)):
        row, loc = rotate(session, config, at=at)
        seen.append(loc.country)
    assert len(set(seen)) == len(eligible_locations)
    row, loc = rotate(session, config, country="US", at=at)
    assert loc.country == "US"
    assert len(session.scalars(select(LocationQueue)).all()) == len(eligible_locations) * 12


def test_one_initial_send_per_run_guard_does_not_call_integrations(session, settings, config, prospect, site):
    from unittest.mock import Mock

    from website_agent.pipeline import Pipeline

    pipe = Pipeline(session, settings, config)
    pipe.initial_sends_this_run = 1
    pipe.log = Mock()
    pipe.initial_outreach(prospect, site)
    pipe.log.assert_called_once_with(
        "outreach_deferred", prospect_id=prospect.id, reason="one_initial_send_per_run"
    )
    assert pipe._gmail is None and pipe._ai is None and pipe._hosting is None


def test_owner_reviewed_free_gemini_models_are_bounded(settings):
    from datetime import date

    cfg = settings.config()
    assert cfg.limits.ai_requests_daily == 12
    assert not cfg.gemini.allow_paid_fallback
    exact_models = {
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    }
    assert set(cfg.gemini.usage_authorizations) == exact_models
    for model, authorization in cfg.gemini.usage_authorizations.items():
        assert authorization.tier == "free"
        assert authorization.expires_on == date(2026, 11, 21)
        assert cfg.model_prices[model] == {
            "input_per_million": 0.0, "output_per_million": 0.0
        }


def test_single_opportunity_configuration_and_two_ist_slots():
    from pathlib import Path

    import yaml

    data = yaml.safe_load(Path("config/settings.yml").read_text(encoding="utf-8"))
    assert data["limits"]["discovered"] == 1
    assert data["limits"]["inspected"] == 3
    assert data["limits"]["qualified"] == 1
    assert data["limits"]["max_followups"] == 0
    assert data["schedule_timezone"] == "Asia/Kolkata"
    assert data["schedule_hours"] == [15, 21]


def test_global_rotation_skips_closed_timezones_when_another_country_is_open(session, config):
    from website_agent.database import LocationQueue

    config.research_hours = [9, 17]
    config.niches = ["salons"]
    config.locations = [
        next(loc for loc in config.locations if loc.country == "US"),
        next(loc for loc in config.locations if loc.country == "IN"),
    ]
    # New York is open at 09:00 on this UTC afternoon; Mumbai is closed at 18:30.
    # An underserved closed country must not freeze worldwide discovery.
    at = datetime(2026, 10, 20, 13, tzinfo=UTC)
    session.add(LocationQueue(country="US", city="New York", niche="salons", searches=1))
    session.commit()
    chosen = rotate(session, config, at=at)
    assert chosen is not None
    assert chosen[1].country == "US"


def test_transaction_uniqueness(session, prospect):
    session.add(
        Prospect(
            domain=prospect.domain,
            name="Duplicate",
            url=prospect.url,
            country="US",
            city="NY",
            timezone="UTC",
            language="en",
            niche="salons",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    assert len(session.scalars(select(Prospect)).all()) == 1


def test_provider_authorization_and_parsing(settings, config):
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, json={"web": {"results": [{"url": "https://example.com", "title": "Salon"}]}}
            )
        )
    )
    provider = SearchProvider(settings, config, client)
    with pytest.raises(Blocked):
        provider.discover(config.locations[0], "salons", 2)
    config.storage_and_outreach_use_authorized = True
    config.provider_agreement_reference = "licensed contract"
    results = provider.discover(config.locations[0], "salons", 2)
    assert len(results) == 1 and isinstance(results[0], Business)
    with pytest.raises(ValidationError):
        Business(provider_id="1", name="x", url="javascript:alert(1)")


def test_retry_and_quota(monkeypatch):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(503 if count == 1 else 200, json={})

    monkeypatch.setattr(api_get.retry, "sleep", lambda seconds: None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert api_get(client, "https://example.com").status_code == 200 and count == 2
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    with pytest.raises(Blocked):
        api_get(client, "https://example.com")


def test_generated_source_escaping(fakes):
    from website_agent.ai import Design

    design = fakes.ai.generate("", {}, Design)
    evidence = {"snippets": ["Sample Salon", "Haircuts"]}
    files = render(design, evidence, "https://sample.example", "site-id")
    assert "unofficial" in files["index.html"] and validate(files)
    design.hero_quote = '<script>alert("x")</script>'
    with pytest.raises(Blocked):
        render(design, evidence, "https://sample.example", "id")
    evidence["snippets"].append(design.hero_quote)
    files = render(design, evidence, "https://sample.example", "id")
    assert "&lt;script&gt;" in files["index.html"]
    files["app.js"] += "fetch('https://evil.example')"
    with pytest.raises(Blocked):
        validate(files)


def test_imports_require_complete_attestation(session, tmp_path):
    import json

    file = tmp_path / "history.json"
    file.write_text(
        json.dumps(
            {
                "source": "manually reviewed old contacts",
                "exported_at": "2026-10-20",
                "contacts": [{"email": "info@example.com"}],
                "opt_outs": [],
            }
        )
    )
    assert import_history(session, file) == 1
    data = get_config(session, "history_import")
    set_config(session, "gmail_history_import", {"completed": True})
    file.write_text(
        json.dumps(
            {
                "reviewed_by": "Owner",
                "import_digest": data["digest"],
                "history_export_complete": True,
                "suppression_export_complete": True,
            }
        )
    )
    validate_history(session, file)
    assert get_config(session, "external_history_review")["validated"]
    file.write_text("{}")
    with pytest.raises(Blocked):
        validate_history(session, file)


def test_no_sqlite_production():
    from website_agent.database import engine_for

    with pytest.raises(ValueError):
        engine_for("sqlite:///prod.db")
