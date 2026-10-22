from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from website_agent.analysis import inspect_site
from website_agent.compliance import eligible
from website_agent.database import BusinessSource, Message, suppress
from website_agent.outreach_authorization import authorization_readiness
from website_agent.pipeline import Pipeline
from website_agent.security import Blocked, Page

AT = datetime(2026, 10, 22, 12, tzinfo=UTC)


def configure(settings, config, prospect):
    settings.enable_sending = True
    settings.outreach_policy_mode = "operator_managed"
    config.operating_country = prospect.country = "GB"
    prospect.timezone = "Europe/London"
    prospect.subdivision = "ENG"
    prospect.contact_evidence = {
        "observed": True, "email": prospect.email,
        "url": prospect.url, "method": "public_role_mailto",
    }


def test_operator_mode_sends_verified_demo_without_inventing_review(
    session, settings, config, prospect, site, fakes, monkeypatch
):
    configure(settings, config, prospect)
    session.commit()
    monkeypatch.setattr("website_agent.outreach.now", lambda: AT)
    pipe = Pipeline(session, settings, config, gmail=fakes.gmail, verifier=Mock(return_value={}))
    pipe.start("daily", "operator-demo")
    pipe.initial_outreach(prospect, site)
    assert fakes.gmail.sends == 1
    assert session.scalar(select(Message)).state == "sent"
    assert prospect.eligibility == {}
    assert authorization_readiness(settings)["legal_review_verified"] is False
    pipe.initial_outreach(prospect, site)
    assert fakes.gmail.sends == 1


@pytest.mark.parametrize("case,reason", [
    ("disabled", "sending_disabled"),
    ("suppressed", "suppressed"),
    ("parent_suppressed", "suppressed"),
    ("replied", "reply_received"),
    ("stopped", "prospect_stopped"),
    ("unobserved", "contact_not_verified"),
    ("named_mailbox", "not_public_business_mailbox"),
    ("wrong_source", "not_public_business_mailbox"),
    ("wrong_email", "not_public_business_mailbox"),
    ("no_source", "not_public_business_mailbox"),
    ("foreign", "outside_operating_country"),
    ("night", "outside_local_contact_window"),
    ("weekend", "outside_local_contact_window"),
    ("sender", "missing_sender_postal_address"),
])
def test_operator_mode_preserves_send_checks(session, settings, config, prospect, case, reason):
    configure(settings, config, prospect)
    at = AT
    if case == "disabled":
        settings.enable_sending = False
    elif case == "suppressed":
        suppress(session, prospect.email, "unsubscribe", "test")
    elif case == "parent_suppressed":
        suppress(session, "sample.example", "unsubscribe", "test")
        prospect.domain = "branch.sample.example"
    elif case == "replied":
        prospect.replied_at = AT
    elif case == "stopped":
        prospect.status = "unsubscribed"
    elif case == "unobserved":
        prospect.contact_evidence["observed"] = False
    elif case == "named_mailbox":
        prospect.email = "jane@sample.example"
        prospect.contact_evidence["email"] = prospect.email
    elif case == "wrong_source":
        prospect.contact_evidence["url"] = "https://unrelated.example/contact"
    elif case == "wrong_email":
        prospect.contact_evidence["email"] = "info@sample.example"
    elif case == "no_source":
        prospect.contact_evidence = {"observed": True}
    elif case == "foreign":
        prospect.country, prospect.subdivision = "US", "NY"
    elif case == "night":
        at = AT.replace(hour=23)
    elif case == "weekend":
        at = AT.replace(day=24)
    elif case == "sender":
        settings.sender_postal_address = ""
    ok, reasons = eligible(session, prospect, settings, at)
    assert not ok and reason in reasons


def test_default_still_requires_review(session, settings, prospect):
    assert settings.outreach_policy_mode == "reviewed"
    assert "unverified_country_policy" in eligible(session, prospect, settings, AT)[1]


def test_out_of_scope_category_never_contacts(session, settings, config, prospect, site, fakes):
    configure(settings, config, prospect)
    prospect.niche = "dentists"
    pipe = Pipeline(session, settings, config, gmail=fakes.gmail)
    with pytest.raises(Blocked, match="business categories"):
        pipe.initial_outreach(prospect, site)
    assert fakes.gmail.sends == fakes.gmail.drafts == 0


def test_dataset_category_from_salon_search_remains_in_scope(
    session, settings, config, prospect, site, fakes, monkeypatch
):
    configure(settings, config, prospect)
    prospect.niche = "beauty_salon"
    prospect.status = "draft_ready"
    session.add(BusinessSource(
        prospect_id=prospect.id, provider="overture", provider_id="fixture",
        evidence={"requested_niche": "salons", "category": "beauty_salon"},
    ))
    session.commit()
    monkeypatch.setattr("website_agent.outreach.now", lambda: AT)
    pipe = Pipeline(session, settings, config, gmail=fakes.gmail, verifier=Mock(return_value={}))
    pipe.discover = Mock(side_effect=AssertionError("Saved draft must be selected first"))
    pipe.start("daily", "legacy-salon-category")
    pipe.daily()
    assert fakes.gmail.sends == 1
    pipe.discover.assert_not_called()


def test_dataset_category_queued_salon_reaches_audit(session, settings, config, prospect, fakes):
    configure(settings, config, prospect)
    prospect.niche, prospect.status = "hair_salon", "discovered"
    session.add(BusinessSource(
        prospect_id=prospect.id, provider="overture", provider_id="queued-fixture",
        evidence={"requested_niche": "salons", "category": "hair_salon"},
    ))
    session.commit()
    pipe = Pipeline(session, settings, config, gmail=fakes.gmail)
    pipe.discover = Mock(side_effect=AssertionError("Saved lead must be selected first"))
    pipe.audit = Mock()
    pipe.start("daily", "queued-salon-category")
    pipe.daily()
    pipe.audit.assert_called_once_with(prospect)
    pipe.discover.assert_not_called()


def test_contact_page_after_navigation_is_inspected_within_budget():
    web = Mock()
    home = '<h1>Salon</h1>' + ''.join(f'<a href="/{p}">{p}</a>' for p in ["a", "b", "c", "contact"])
    def fetch(url):
        body = '<a href="mailto:hello@salon.example">Email</a>' if url.endswith("/contact") else home
        return Page(url, 200, {"content-type": "text/html"}, body)
    web.fetch.side_effect = fetch
    result = inspect_site(web, "https://salon.example/")
    assert result["contact"]["email"] == "hello@salon.example"
    assert web.fetch.call_count == 4
    assert web.fetch.call_args_list[1].args == ("https://salon.example/contact",)


def test_contact_redirect_to_unrelated_domain_does_not_supply_email():
    web = Mock()
    web.fetch.side_effect = [
        Page("https://salon.example/", 200, {"content-type": "text/html"}, '<a href="/contact">Contact</a>'),
        Page("https://unrelated.example/", 200, {"content-type": "text/html"}, '<a href="mailto:info@salon.example">Email</a>'),
    ]
    assert inspect_site(web, "https://salon.example/")["contact"] == {}
