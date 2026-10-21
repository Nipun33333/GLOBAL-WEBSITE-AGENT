"""Offline regression coverage for operational readiness review findings."""

from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy import inspect
from test_core import enable

from website_agent import live_verification as live
from website_agent.ai import Design, EmailCopy, Gemini
from website_agent.compliance import eligible
from website_agent.database import Base, now, suppress
from website_agent.discovery_support import BoundedHTTP, Budget, DiscoveryFault
from website_agent.generation import render
from website_agent.gmail import Gmail
from website_agent.hosting import verify_preview
from website_agent.pipeline import Pipeline
from website_agent.security import Blocked, Page, PublicWeb


@pytest.mark.parametrize("draft_id", [None, "draft"])
def test_disabled_gmail_send_never_authenticates_or_posts(settings, draft_id):
    client, credentials = Mock(), Mock(valid=False)
    gmail = Gmail(settings, client, credentials)
    with pytest.raises(Blocked, match="disabled"):
        gmail.send("untrusted", draft_id=draft_id)
    credentials.refresh.assert_not_called()
    client.post.assert_not_called()


def test_parent_domain_suppression_blocks_previously_eligible_subdomain(session, settings, prospect):
    enable(session, settings, prospect)
    prospect.domain = "branch.sample.example"
    suppress(session, "sample.example", "unsubscribe", "fixture")
    allowed, reasons = eligible(session, prospect, settings, now())
    assert not allowed and "suppressed" in reasons


def test_owner_handled_replies_never_initialize_ai_or_gmail(session, settings, config, prospect, site):
    pipeline = Pipeline(session, settings, config)
    pipeline.acknowledge(prospect)
    assert not session.new
    # A verified site exists, but routine replies must not initialize real provider clients.


@pytest.mark.parametrize("actions", [None, [], ["embedContent"]])
def test_gemini_missing_generation_capability_fails_closed(session, settings, config, actions):
    client = Mock()
    client.models.get.return_value = SimpleNamespace(supported_actions=actions)
    with pytest.raises(Blocked, match="unavailable"):
        Gemini(settings, config, session, client).generate("fixture", {}, EmailCopy)
    client.models.generate_content.assert_not_called()


@pytest.mark.parametrize("price", [float("nan"), float("inf"), -1])
def test_nonfinite_or_negative_model_price_never_generates(session, settings, config, price):
    client = Mock()
    client.models.get.return_value = SimpleNamespace(supported_actions=["generateContent"])
    config.model_prices = {settings.gemini_model: {"input_per_million": price, "output_per_million": 0}}
    with pytest.raises(Blocked, match="prices"):
        Gemini(settings, config, session, client).generate("fixture", {}, EmailCopy)
    client.models.generate_content.assert_not_called()


@pytest.mark.parametrize("drift", [None, "column", "nullable", "primary", "unique", "index", "foreign"])
def test_schema_drift_detection_uses_real_reflection(session, drift):
    inspector = inspect(session.bind)
    if drift:
        methods = {
            "column": "get_columns",
            "nullable": "get_columns",
            "primary": "get_pk_constraint",
            "unique": "get_unique_constraints",
            "index": "get_indexes",
            "foreign": "get_foreign_keys",
        }
        name = methods[drift]
        actual = getattr(inspector, name)

        def altered(table):
            value = actual(table)
            if drift == "column":
                return [c for c in value if c["name"] != "id"]
            if drift == "nullable":
                return [{**c, "nullable": True} if c["name"] == "id" else c for c in value]
            if drift == "primary":
                return {"constrained_columns": []}
            return []

        setattr(inspector, name, altered)
    assert live.schema_matches(inspector) == (drift is None)
    assert len(Base.metadata.tables) == 14


@pytest.mark.parametrize(
    "error,code",
    [
        ("invalid_grant", "invalid_grant"),
        ("private-secret", None),
        ({"status": "PERMISSION_DENIED", "message": "private-secret"}, "PERMISSION_DENIED"),
    ],
)
def test_api_failures_report_only_known_codes(error, code):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                400, json={"error": error, "error_description": "private-secret customer@example.com"}
            )
        )
    ) as client:
        result = live.run_check(lambda: live.api_json(client, "GET", "https://example.com"))
    assert result.get("provider_code") == code
    assert result["http_status"] == 400
    assert "private" not in str(result) and "@" not in str(result)


def test_preview_altered_script_rejected_before_browser(fakes, monkeypatch):
    files = render(
        fakes.ai.generate("", {}, Design),
        {"snippets": ["Sample Salon", "Haircuts"]},
        "https://sample.example",
        "fixture",
    )
    files["app.js"] = "fetch('https://attacker.invalid')"
    calls = []

    class Web:
        def fetch(self, url, **kwargs):
            calls.append(url)
            name = url.rsplit("/", 1)[-1] or "index.html"
            return Page(url, 200, {"content-type": "text/html"}, files[name])

    browser = Mock(side_effect=AssertionError("browser must not execute altered script"))
    monkeypatch.setattr("website_agent.hosting.sync_playwright", browser)
    with pytest.raises(Blocked, match="reviewed interaction"):
        verify_preview(Web(), "https://fixture--example.netlify.app/", "fixture")
    assert len(calls) == len(set(calls)) == 3
    browser.assert_not_called()


@pytest.mark.parametrize("status", [200, 429, 503, 403])
def test_configured_data_endpoint_uses_pinned_client_without_redirects(config, monkeypatch, status):
    fetch = Mock(return_value=Page("https://approved.example/api", status, {"retry-after": "7200"}, "{}"))
    monkeypatch.setattr("website_agent.security.PublicWeb.fetch", fetch)
    unpinned = Mock()
    http = BoundedHTTP(Budget(config.discovery), unpinned)
    if status == 200:
        assert http.get_pinned("https://approved.example/api", cap=1024, params={"data": "a&b"})[0] == b"{}"
    else:
        with pytest.raises(DiscoveryFault) as err:
            http.get_pinned("https://approved.example/api", cap=1024, params={"data": "a&b"})
        assert err.value.status == (
            "blocked_permission_or_license" if status == 403 else "deferred_provider_unavailable"
        )
        if status != 403:
            assert err.value.retry_after == 7200
    fetch.assert_called_once_with("https://approved.example/api?data=a%26b", robots=False, redirects=False)
    unpinned.stream.assert_not_called()


def test_pinned_endpoint_redirect_is_rejected_before_second_resolution(monkeypatch):
    resolve = Mock(return_value=["93.184.216.34"])
    monkeypatch.setattr("website_agent.security.public_addresses", resolve)
    response = Mock(status=302, headers={"Location": "https://127.0.0.1/private"})
    pool = Mock()
    pool.request.return_value = response
    monkeypatch.setattr("website_agent.security.urllib3.HTTPSConnectionPool", Mock(return_value=pool))
    with pytest.raises(Blocked, match="Redirects are disabled"):
        PublicWeb().fetch("https://approved.example/api", robots=False, redirects=False)
    resolve.assert_called_once_with("https://approved.example/api")
    pool.request.assert_called_once()
    response.close.assert_called_once()
