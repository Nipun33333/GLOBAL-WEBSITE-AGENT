import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy import select
from test_core import enable

from website_agent.ai import EmailCopy, Gemini
from website_agent.database import Audit, Prospect, Suppression, get_config, set_config
from website_agent.gmail import Gmail
from website_agent.imports import import_history, validate_history
from website_agent.outreach import create_draft, prepare, send_controlled
from website_agent.pipeline import Pipeline
from website_agent.security import Blocked, PublicWeb


def test_draft_send_consumes_existing_container(settings):
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "POST":
            assert request.url.path.endswith("drafts/send")
            assert json.loads(request.content) == {
                "id": "draft-id",
                "message": {"raw": "checked-content", "threadId": "t1"},
            }
            return httpx.Response(200, json={"id": "sent-id"})
        return httpx.Response(200, json={"id": "sent-id", "threadId": "t1", "labelIds": ["SENT"]})

    gmail = Gmail(
        settings,
        httpx.Client(
            base_url="https://gmail.googleapis.com/gmail/v1/users/me/", transport=httpx.MockTransport(handler)
        ),
        Mock(valid=True, token="test"),
    )
    assert gmail.send("checked-content", "t1", draft_id="draft-id")["id"] == "sent-id"
    assert len(requests) == 2


def test_pending_draft_reconciliation_never_posts_twice(session, settings, prospect, site, fakes):
    msg = prepare(session, prospect, site, settings, fakes.ai)
    msg.state = "draft_pending"
    session.commit()
    fakes.gmail.find_draft = Mock(
        return_value={"id": "existing-draft", "message": {"id": "existing-message"}}
    )
    create_draft(session, fakes.gmail, settings, msg)
    assert msg.state == "drafted" and msg.draft_id == "existing-draft"
    assert fakes.gmail.drafts == 0


def test_gmail_pagination_and_incomplete_scan(settings):
    gmail = Gmail(settings, Mock(), Mock(valid=True, token="test"))
    gmail.get = Mock(
        side_effect=[
            {"messages": [{"id": "1"}], "nextPageToken": "next"},
            {"id": "1"},
            {"messages": [{"id": "2"}]},
            {"id": "2"},
        ]
    )
    assert [m["id"] for m in gmail.messages("in:sent")] == ["1", "2"]
    assert gmail.get.call_args_list[2].kwargs["pageToken"] == "next"
    gmail.get = Mock(return_value={"nextPageToken": "forever"})
    with pytest.raises(Blocked, match="incomplete"):
        list(gmail.messages("in:sent", max_pages=1))


def test_gmail_sender_mismatch_and_missing_sent_label(settings):
    gmail = Gmail(settings, Mock(), Mock(valid=True, token="test"))
    gmail.get = Mock(return_value={"emailAddress": "other@example.net"})
    with pytest.raises(Blocked):
        gmail.verify_sender()
    gmail.get = Mock(return_value={"id": "m", "threadId": "t", "labelIds": ["DRAFT"]})
    with pytest.raises(Blocked):
        gmail.verify_sent("m")


def test_missing_ai_does_not_block_later_unsubscribe(session, settings, config, prospect, fakes):
    settings.gemini_api_key = ""
    fakes.gmail.incoming_messages = [
        {
            "id": "question",
            "threadId": "t",
            "snippet": "Could you explain this?",
            "payload": {"headers": [{"name": "From", "value": prospect.email}]},
        },
        {
            "id": "optout",
            "threadId": "t",
            "snippet": "Unsubscribe",
            "payload": {"headers": [{"name": "From", "value": prospect.email}]},
        },
    ]
    pipe = Pipeline(session, settings, config, gmail=fakes.gmail)
    pipe.start("replies", "reply-test")
    pipe.replies()
    assert prospect.status == "unsubscribed"
    assert session.scalar(select(Suppression).where(Suppression.key == prospect.email))
    assert not get_config(session, "reply_checkpoint")
    assert pipe.run.summary["failure"] == 1


def test_quota_pause_survives_new_process(session, settings, config):
    set_config(session, "gemini_quota_pause", {"until": (datetime.now(UTC) + timedelta(hours=1)).isoformat()})
    client = Mock()
    client.models.get.return_value = SimpleNamespace(supported_actions=["generateContent"])
    with pytest.raises(Blocked, match="pause"):
        Gemini(settings, config, session, client).generate("hello", {}, EmailCopy)
    client.models.generate_content.assert_not_called()


def test_daily_schedule_checkpoint_and_catchup(session, settings, config, monkeypatch):
    config.schedule_timezone, config.schedule_hour = "Asia/Kolkata", 8
    pipe = Pipeline(session, settings, config)
    monkeypatch.setattr("website_agent.pipeline.now", lambda: datetime(2026, 10, 20, 2, tzinfo=UTC))
    assert not pipe.scheduled_due()
    monkeypatch.setattr("website_agent.pipeline.now", lambda: datetime(2026, 10, 20, 8, tzinfo=UTC))
    assert pipe.scheduled_due()
    set_config(session, "daily_checkpoint", {"date": "2026-10-20"})
    assert not pipe.scheduled_due()
    monkeypatch.setattr("website_agent.pipeline.now", lambda: datetime(2026, 10, 22, 8, tzinfo=UTC))
    assert pipe.scheduled_due()


def test_preview_cap_and_ambiguous_deployment(session, settings, config, prospect, site, fakes):
    config.limits.previews_daily = 1
    other = Prospect(
        domain="other.example",
        name="Other",
        url="https://other.example",
        country="US",
        city="NY",
        timezone="UTC",
        language="en",
        niche="salons",
        status="qualified",
    )
    session.add(other)
    session.commit()
    pipe = Pipeline(session, settings, config, ai=fakes.ai)
    assert pipe.generate(prospect).id == site.id
    with pytest.raises(Blocked, match="cap"):
        pipe.generate(other)
    hosting = Mock()
    hosting.find.return_value = None
    pipe._hosting = hosting
    site.status = "deploy_pending"
    with pytest.raises(Blocked, match="Uncertain"):
        pipe.deploy(site)
    hosting.create.assert_not_called()


def test_global_send_cap(session, settings, config, prospect, site, fakes):
    enable(session, settings, prospect)
    config.limits.outreach_daily = 0
    msg = prepare(session, prospect, site, settings, fakes.ai)
    create_draft(session, fakes.gmail, settings, msg)
    with pytest.raises(Blocked, match="cap"):
        send_controlled(
            session,
            fakes.gmail,
            settings,
            config,
            msg,
            lambda s: True,
            datetime(2026, 10, 20, 15, tzinfo=UTC),
        )
    assert fakes.gmail.sends == 0


def test_imported_threads_survive_empty_database(session, tmp_path):
    path = tmp_path / "history.json"
    path.write_text(
        json.dumps(
            {
                "source": "Base44",
                "exported_at": "2026-10-20",
                "contacts": [
                    {"domain": "old.example", "email": "info@old.example", "gmail_thread_id": "old-thread"}
                ],
                "opt_outs": [],
            }
        )
    )
    import_history(session, path)
    from website_agent.database import GmailThread

    assert session.scalar(select(GmailThread)).thread_id == "old-thread"
    assert session.scalar(select(Prospect)).imported
    set_config(session, "gmail_history_import", {"completed": True})
    path.write_text(
        json.dumps(
            {
                "reviewed_by": "owner",
                "base44_audience_exclusion_reference": "reference",
                "history_export_complete": "false",
                "suppression_export_complete": "false",
            }
        )
    )
    with pytest.raises(Blocked):
        validate_history(session, path)


def test_dns_address_pinned_to_connection(monkeypatch):
    monkeypatch.setattr("website_agent.security.public_addresses", lambda url: ["93.184.216.34"])
    response = Mock(status=200, headers={"content-type": "text/html"})
    response.read.return_value = b"<html>test</html>"
    pool = Mock()
    pool.request.return_value = response
    factory = Mock(return_value=pool)
    monkeypatch.setattr("website_agent.security.urllib3.HTTPSConnectionPool", factory)
    assert PublicWeb().fetch("https://example.com", robots=False).status == 200
    assert factory.call_args.kwargs["host"] == "93.184.216.34"
    assert factory.call_args.kwargs["server_hostname"] == "example.com"
    assert pool.request.call_args.kwargs["headers"]["Host"] == "example.com"


def test_strong_site_never_calls_gemini(session, prospect, settings, config):
    session.add(Audit(prospect_id=prospect.id, score=95, evidence={}, research={}))
    session.commit()
    ai = Mock()
    pipe = Pipeline(session, settings, config, ai=ai)
    pipe.start("daily", "strong-site")
    pipe.audit(prospect)
    assert prospect.status == "disqualified"
    ai.generate.assert_not_called()


@pytest.mark.parametrize("change", ["recipient", "sender"])
def test_stale_draft_identity_is_blocked(session, settings, config, prospect, site, fakes, change):
    enable(session, settings, prospect)
    msg = prepare(session, prospect, site, settings, fakes.ai)
    create_draft(session, fakes.gmail, settings, msg)
    if change == "recipient":
        prospect.email = "different@sample.example"
    else:
        settings.sender_postal_address = "Changed address"
    with pytest.raises(Blocked):
        send_controlled(
            session,
            fakes.gmail,
            settings,
            config,
            msg,
            lambda s: True,
            datetime(2026, 10, 20, 15, tzinfo=UTC),
        )
    assert fakes.gmail.sends == 0


def test_structured_bounce_stops_followups_without_ai(session, settings, config, prospect, fakes):
    import base64

    settings.gemini_api_key = ""
    status = f"Final-Recipient: rfc822; {prospect.email}\r\nAction: failed\r\nStatus: 5.1.1"
    fakes.gmail.incoming_messages = [
        {
            "id": "bounce",
            "threadId": "new-bounce-thread",
            "payload": {
                "mimeType": "multipart/report",
                "headers": [{"name": "From", "value": "mailer-daemon@example.net"}],
                "parts": [
                    {
                        "mimeType": "message/delivery-status",
                        "body": {"data": base64.urlsafe_b64encode(status.encode()).decode()},
                    }
                ],
            },
        }
    ]
    pipe = Pipeline(session, settings, config, gmail=fakes.gmail)
    pipe.start("replies", "bounce-test")
    pipe.replies()
    assert prospect.status == "delivery_failure"
    assert session.scalar(select(Suppression).where(Suppression.key == prospect.email))


def test_capacity_is_deferred_not_workflow_failure(session, settings, config):
    from website_agent.security import CapacityDeferred

    pipe = Pipeline(session, settings, config)
    pipe.start("daily", "capacity-test")

    def limited():
        raise CapacityDeferred("Configured daily cap")

    pipe.step("generation", limited)
    pipe.finish()
    assert pipe.run.status == "completed"
    assert pipe.run.summary["capacity_deferred"] == 1


def test_late_reply_cannot_revive_optout(session, prospect, fakes):
    from website_agent.outreach import process_reply

    prospect.status = "unsubscribed"
    message = {
        "id": "late",
        "threadId": "late-thread",
        "snippet": "Interested",
        "payload": {"headers": [{"name": "From", "value": prospect.email}]},
    }
    assert process_reply(session, prospect, message, fakes.ai) is None
    assert prospect.status == "unsubscribed" and prospect.replied_at


def test_report_distinguishes_draft_and_actual_send(
    session, settings, config, prospect, site, fakes, tmp_path, monkeypatch
):
    from website_agent.reporting import report

    monkeypatch.chdir(tmp_path)
    msg = prepare(session, prospect, site, settings, fakes.ai)
    create_draft(session, fakes.gmail, settings, msg)
    result = report(session)
    assert "Verified Gmail drafts created: 1" in result
    assert "Verified new outreach sent: 0" in result
    assert prospect.email not in result
