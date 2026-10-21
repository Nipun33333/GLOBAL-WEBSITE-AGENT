from datetime import UTC, datetime
from unittest.mock import Mock

from sqlalchemy import select
from test_core import enable

from website_agent.database import Message
from website_agent.outreach import prepare
from website_agent.pipeline import Pipeline


def test_demo_copy_never_calls_ai_and_preserves_existing_drafts(session, settings, prospect, site):
    ai = Mock()
    ai.generate.side_effect = AssertionError("Email copy must not need a provider")
    message = prepare(session, prospect, site, settings, ai)
    assert message.subject == "A website demo for your business"
    assert site.url in message.body and "paid website redesign" in message.body
    assert settings.sender_name in message.body and settings.sender_postal_address in message.body
    assert "unsubscribe" in message.body and settings.reply_to in message.body
    assert "not affiliated" in message.body
    assert message.details["copy_source"] == "trusted_catalog"
    assert message.details["catalog_version"] == 2
    message.subject = "Previously reviewed subject"
    session.commit()
    assert prepare(session, prospect, site, settings) is message
    assert message.subject == "Previously reviewed subject"
    ai.generate.assert_not_called()


def test_verified_demo_can_be_drafted_without_gemini_or_authorization_secret(
    session, settings, config, prospect, site, fakes
):
    settings.gemini_api_key = ""
    settings.outreach_authorization_json = ""
    pipe = Pipeline(session, settings, config, gmail=fakes.gmail)
    pipe.start("daily", "demo-draft-without-ai")
    pipe.initial_outreach(prospect, site)
    assert pipe._ai is None
    assert fakes.gmail.drafts == 1 and fakes.gmail.sends == 0
    assert prospect.status == "draft_ready"
    assert pipe.run.summary["email_drafted"] == 1


def test_eligible_demo_send_works_without_gemini_and_remains_idempotent(
    session, settings, config, prospect, site, fakes, monkeypatch
):
    enable(session, settings, prospect)
    settings.gemini_api_key = ""
    monkeypatch.setattr("website_agent.outreach.now", lambda: datetime(2026, 10, 20, 15, tzinfo=UTC))
    verifier = Mock(return_value={"desktop": True, "mobile": True})
    pipe = Pipeline(session, settings, config, gmail=fakes.gmail, verifier=verifier)
    pipe.start("daily", "demo-send-without-ai")
    pipe.initial_outreach(prospect, site)
    assert fakes.gmail.sends == 1 and prospect.status == "contacted" and pipe._ai is None
    assert pipe.run.summary["email_sent"] == 1
    assert session.scalar(select(Message)).state == "sent"
    pipe.initial_outreach(prospect, site)
    assert fakes.gmail.sends == 1


def test_missing_policy_reports_block_instead_of_claiming_delivery(
    session, settings, config, prospect, site, fakes
):
    settings.enable_sending = True
    pipe = Pipeline(session, settings, config, gmail=fakes.gmail)
    pipe.start("daily", "demo-blocked-policy")
    pipe.initial_outreach(prospect, site)
    assert fakes.gmail.drafts == 1 and fakes.gmail.sends == 0
    assert pipe.run.summary["outreach_blocked"] == 1
    assert "email_sent" not in pipe.run.summary
    assert "unverified_country_policy" in session.scalar(select(Message)).details["blocked_reasons"]
