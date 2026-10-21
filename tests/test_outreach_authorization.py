import json
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from website_agent.cli import sync_policies
from website_agent.compliance import eligible
from website_agent.database import CountryPolicy, Prospect, Site, suppress
from website_agent.outreach import create_draft, prepare, send_controlled
from website_agent.outreach_authorization import (
    apply_recipient_evidence,
    authorization_readiness,
    load_authorization,
)
from website_agent.pipeline import Pipeline
from website_agent.security import Blocked

AT = datetime(2026, 10, 20, 10, tzinfo=UTC)


@pytest.fixture
def authorization(settings, prospect, config):
    prospect.country, prospect.timezone, prospect.subdivision = "GB", "Europe/London", None
    config.operating_country = "GB"
    settings.enable_sending = True
    data = {
        "country": "GB",
        "policy": {
            "enabled": True,
            "reviewed_by": "fixture reviewer",
            "legal_reference": "private-policy-fixture",
            "valid_until": "2027-01-01",
            "allowed_bases": ["consent"],
            "allowed_contact_types": ["corporate"],
            "contact_hours": [9, 17],
        },
        "recipients": [
            {
                "domain": prospect.domain,
                "verified_email": prospect.email,
                "email_evidence_reference": "private-mailbox-fixture",
                "basis": "consent",
                "evidence_reference": "private-recipient-fixture",
                "reviewed_by": "fixture reviewer",
                "valid_until": "2027-01-01",
                "contact_type": "corporate",
            }
        ],
    }
    settings.outreach_authorization_json = json.dumps(data)
    return data


def test_private_config_enables_mocked_real_send_path(
    session, settings, config, prospect, site, fakes, authorization
):
    bundle = load_authorization(settings)
    sync_policies(session, settings.policy_path, bundle)
    apply_recipient_evidence(session, prospect, bundle)
    msg = prepare(session, prospect, site, settings, fakes.ai)
    create_draft(session, fakes.gmail, settings, msg)
    verifier = Mock()
    assert send_controlled(session, fakes.gmail, settings, config, msg, verifier, at=AT)
    assert fakes.gmail.sends == 1 and msg.state == "sent" and prospect.status == "contacted"
    verifier.assert_called_once_with(site)
    assert not send_controlled(session, fakes.gmail, settings, config, msg, verifier, at=AT)
    assert fakes.gmail.sends == 1


@pytest.mark.parametrize("guard", ["expired", "suppressed", "outside_hours", "disabled"])
def test_evidence_never_bypasses_existing_guards(session, settings, prospect, authorization, guard):
    if guard == "expired":
        authorization["recipients"][0]["valid_until"] = "2020-01-01"
    if guard == "disabled":
        authorization["policy"]["enabled"] = False
    settings.outreach_authorization_json = json.dumps(authorization)
    bundle = load_authorization(settings)
    sync_policies(session, settings.policy_path, bundle)
    apply_recipient_evidence(session, prospect, bundle)
    if guard == "suppressed":
        suppress(session, prospect.email, "unsubscribe", "fixture")
    at = AT.replace(hour=23) if guard == "outside_hours" else AT
    allowed, reasons = eligible(session, prospect, settings, at)
    assert not allowed
    expected = {
        "expired": "eligibility_expired",
        "suppressed": "suppressed",
        "outside_hours": "outside_local_contact_window",
        "disabled": "unverified_country_policy",
    }
    assert expected[guard] in reasons


def test_removing_recipient_blocks_cached_eligibility_and_existing_draft(
    session, settings, config, prospect, site, fakes, authorization
):
    bundle = load_authorization(settings)
    sync_policies(session, settings.policy_path, bundle)
    apply_recipient_evidence(session, prospect, bundle)
    msg = prepare(session, prospect, site, settings, fakes.ai)
    create_draft(session, fakes.gmail, settings, msg)
    authorization["recipients"] = []
    settings.outreach_authorization_json = json.dumps(authorization)
    with pytest.raises(Blocked, match="No matching recipient"):
        send_controlled(session, fakes.gmail, settings, config, msg, Mock(), at=AT)
    assert fakes.gmail.sends == 0


def test_changed_verified_mailbox_does_not_retarget_draft(
    session, settings, config, prospect, site, fakes, authorization
):
    bundle = load_authorization(settings)
    sync_policies(session, settings.policy_path, bundle)
    apply_recipient_evidence(session, prospect, bundle)
    msg = prepare(session, prospect, site, settings, fakes.ai)
    create_draft(session, fakes.gmail, settings, msg)
    authorization["recipients"][0]["verified_email"] = "changed@sample.example"
    settings.outreach_authorization_json = json.dumps(authorization)
    with pytest.raises(Blocked, match="recipient no longer matches"):
        send_controlled(session, fakes.gmail, settings, config, msg, Mock(), at=AT)
    assert fakes.gmail.sends == 0


@pytest.mark.parametrize("bad", ["json", "country", "duplicate", "review", "basis", "extra"])
def test_invalid_private_config_fails_without_leaking_input(settings, authorization, bad):
    if bad == "country":
        authorization["country"] = "US"
    elif bad == "duplicate":
        authorization["recipients"] *= 2
    elif bad == "review":
        authorization["policy"]["reviewed_by"] = ""
    elif bad == "basis":
        authorization["recipients"][0]["basis"] = "unreviewed"
    elif bad == "extra":
        authorization["recipients"][0]["unexpected_private_data"] = "sensitive"
    settings.outreach_authorization_json = (
        "secret invalid json" if bad == "json" else json.dumps(authorization)
    )
    with pytest.raises(Blocked) as error:
        load_authorization(settings)
    assert str(error.value) == "Invalid OUTREACH_AUTHORIZATION_JSON; check the private setup guide"
    assert "private-recipient-fixture" not in repr(settings)


def test_secret_removal_restores_disabled_policy_and_redacted_readiness(session, settings, authorization):
    sync_policies(session, settings.policy_path, load_authorization(settings))
    report = authorization_readiness(settings)
    assert report == {"source": "authorization_secret", "policy_enabled": True, "recipient_records": 1}
    settings.outreach_authorization_json = ""
    sync_policies(session, settings.policy_path, load_authorization(settings))
    assert not session.scalar(select(CountryPolicy).where(CountryPolicy.country == "GB")).policy["enabled"]
    assert authorization_readiness(settings)["policy_enabled"] is False


def test_blocked_first_draft_does_not_starve_next_and_stops_after_one_send(
    session, settings, config, prospect, site
):
    prospect.status = "draft_ready"
    site.status = "verified"
    for index in range(2):
        p = Prospect(
            domain=f"next{index}.example",
            name="Next",
            url=f"https://next{index}.example",
            country=prospect.country,
            city=prospect.city,
            timezone=prospect.timezone,
            language="en",
            niche="salons",
            status="draft_ready",
        )
        session.add(p)
        session.flush()
        session.add(Site(prospect_id=p.id, files={}, metadata_json={}, status="verified"))
    session.commit()
    pipe = Pipeline(session, settings, config)
    pipe.start("daily", "queue-regression")
    visited = []

    def outreach(p, s):
        visited.append(p.id)
        if p.id != prospect.id:
            pipe.initial_sends_this_run += 1

    pipe.initial_outreach = outreach
    pipe.discover = Mock(side_effect=AssertionError("Should stop after sending"))
    pipe.daily()
    assert len(visited) == 2 and visited[0] == prospect.id
    assert pipe.initial_sends_this_run == 1
