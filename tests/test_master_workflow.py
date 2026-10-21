"""Exercise real dispatch decisions without GitHub credentials or production writes."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from website_agent import live_verification as live
from website_agent.gmail import Gmail
from website_agent.hosting import Netlify
from website_agent.outreach import create_draft
from website_agent.pipeline import Pipeline
from website_agent.security import Blocked

spec = importlib.util.spec_from_file_location("master_entry", "scripts/master_entry.py")
master = importlib.util.module_from_spec(spec)
spec.loader.exec_module(master)
SHA = "a" * 40


def env(**changes):
    return {
        "GITHUB_REPOSITORY": "Nipun33333/GLOBAL-WEBSITE-AGENT",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/feature/free-overture-discovery",
        "GITHUB_ACTOR": "Nipun33333",
        "GITHUB_TRIGGERING_ACTOR": "Nipun33333",
        "GITHUB_SHA": SHA,
        "REVIEWED_COMMIT": SHA,
        "AGENT_MODE": "diagnostics",
        "FREE_LIMITS_REVIEWED": "true",
        "DATABASE_REVIEWED": "true",
        **changes,
    }


@pytest.mark.parametrize("mode", sorted(master.MODES))
def test_every_mode_requires_explicit_writes_and_separate_capabilities(mode):
    phrase = (
        "APPROVE_US_DISCOVERY_WRITES"
        if mode == "discover"
        else "APPROVE_" + mode.upper().replace("-", "_") + "_WRITES"
    )
    e = env(AGENT_MODE=mode, WRITE_APPROVAL=phrase)
    if mode == "live-smoke":
        e.update(ALLOW_GENERATION="true", ALLOW_DEPLOYMENT="true", ALLOW_DRAFTS="true")
    result = master.plan(e, SHA)
    assert result["mode"] == mode and not result["sending"]
    if mode != "diagnostics":
        with pytest.raises(ValueError):
            master.plan({**e, "WRITE_APPROVAL": ""}, SHA)


@pytest.mark.parametrize(
    "change",
    [
        {"GITHUB_RUN_ATTEMPT": "2"},
        {"GITHUB_ACTOR": "other"},
        {"GITHUB_TRIGGERING_ACTOR": "other"},
        {"GITHUB_REPOSITORY": "Nipun33333/other"},
        {"GITHUB_REF": "refs/heads/other"},
        {"GITHUB_EVENT_NAME": "pull_request"},
        {"GITHUB_SHA": "b" * 40},
        {"REVIEWED_COMMIT": "b" * 40},
        {"REVIEWED_COMMIT": "$(echo bad)"},
        {"AGENT_MODE": "migrate"},
        {"AGENT_MODE": "daily; curl bad"},
        {"AGENT_COUNTRY": "US; x"},
        {"FREE_LIMITS_REVIEWED": "false"},
        {"DATABASE_REVIEWED": "false"},
        {"AGENT_MODE": "discover", "AGENT_COUNTRY": "GB", "WRITE_APPROVAL": "APPROVE_US_DISCOVERY_WRITES"},
    ],
)
def test_rejected_preflight(change):
    with pytest.raises(ValueError):
        master.plan(env(**change), SHA)


@pytest.mark.parametrize("cron,mode", master.CRONS.items())
def test_exact_cron_routing_and_disabled_automation(cron, mode):
    e = env(
        GITHUB_EVENT_NAME="schedule",
        GITHUB_REF="refs/heads/main",
        AGENT_CRON=cron,
        AUTOMATION_ENABLED="true",
        UNIFIED_WORKFLOW_ENABLED="true",
        SCHEDULED_MODES=mode,
    )
    result = master.plan(e, SHA)
    assert result["mode"] == mode and result["scheduled"] and not result["sending"]
    for key in (
        "AUTOMATION_ENABLED",
        "UNIFIED_WORKFLOW_ENABLED",
        "FREE_LIMITS_REVIEWED",
        "DATABASE_REVIEWED",
        "SCHEDULED_MODES",
    ):
        with pytest.raises(ValueError):
            master.plan({**e, key: "false"}, SHA)
    with pytest.raises(ValueError):
        master.plan({**e, "AGENT_CRON": "* * * * *"}, SHA)


def test_readonly_and_discover_cannot_inherit_side_effect_permissions():
    for mode in ("diagnostics", "discover"):
        result = master.plan(
            env(
                AGENT_MODE=mode,
                WRITE_APPROVAL="APPROVE_US_DISCOVERY_WRITES",
                ENABLE_SENDING="true",
                ALLOW_SENDING="true",
                ALLOW_GENERATION="true",
                ALLOW_DEPLOYMENT="true",
                ALLOW_DRAFTS="true",
            ),
            SHA,
        )
        assert not any(result[k] for k in ("generation", "deployment", "drafts", "sending"))


def test_sending_requires_both_independent_controls():
    e = env(AGENT_MODE="daily", WRITE_APPROVAL="APPROVE_DAILY_WRITES", ALLOW_SENDING="true")
    assert not master.plan(e, SHA)["sending"]
    assert master.plan({**e, "ENABLE_SENDING": "true"}, SHA)["sending"]


def test_single_definition_crons_dependencies_and_secret_boundary():
    root = Path(".github/workflows")
    assert [p.name for p in root.iterdir()] == ["global-website-agent.yml"]
    w = yaml.load((root / "global-website-agent.yml").read_text(), Loader=yaml.BaseLoader)
    crons = [x["cron"] for x in w["on"]["schedule"]]
    assert set(crons) == set(master.CRONS) and len(crons) == len(set(crons))
    assert len(w["on"]["workflow_dispatch"]["inputs"]) == 10
    job = w["jobs"]["agent"]
    assert job["concurrency"] == {"group": "global-website-agent-runtime", "cancel-in-progress": "false"}
    assert "UNIFIED_WORKFLOW_ENABLED" in job["if"]
    assert "uses" not in job and w["permissions"] == {"contents": "read"}
    steps = job["steps"]
    pre = next(i for i, s in enumerate(steps) if s.get("id") == "preflight")
    secret_steps = [i for i, s in enumerate(steps) if "secrets." in str(s)]
    assert secret_steps == [len(steps) - 2] and secret_steps[0] > pre
    for s in steps:
        assert "${{ inputs." not in s.get("run", "")
        assert "migrate" not in s.get("run", "")
    assert any(s.get("if") == "steps.preflight.outputs.browser == 'true'" for s in steps)
    assert steps[0]["with"]["persist-credentials"] == "false"


def test_runtime_diagnostics_forces_flags_false(monkeypatch):
    selected = master.plan(env(), SHA)
    monkeypatch.setenv("ENABLE_GENERATION", "true")
    monkeypatch.setattr(live, "main", Mock(return_value=0))
    assert master.execute(selected) == 0
    import os

    assert all(
        os.environ[k] == "false"
        for k in [
            "ENABLE_GENERATION",
            "ENABLE_DEPLOYMENT",
            "ENABLE_DRAFTS",
            "ENABLE_SENDING",
            "ENABLE_ROUTINE_REPLIES",
            "AUTOMATION_ENABLED",
        ]
    )


def test_runtime_db_block_prevents_cli(monkeypatch, settings, config):
    from website_agent import settings as settings_module

    monkeypatch.setattr(settings_module, "Settings", lambda **_: settings)
    monkeypatch.setattr(
        live, "database_check", lambda *_: {"status": "blocked_schema", "discovery_ready": False}
    )
    monkeypatch.setattr(live, "publish", Mock())
    run = Mock()
    monkeypatch.setattr(master.subprocess, "run", run)
    assert (
        master.execute(master.plan(env(AGENT_MODE="report", WRITE_APPROVAL="APPROVE_REPORT_WRITES"), SHA))
        == 2
    )
    run.assert_not_called()


@pytest.mark.parametrize("mode", ["daily", "replies", "followups", "report", "reconcile"])
def test_runtime_safe_argv_no_migration_and_sanitized_output(monkeypatch, settings, mode):
    from website_agent import settings as settings_module

    settings.database_url = "postgresql+psycopg://fixture:private@db.example:5432/postgres"
    monkeypatch.setattr(settings_module, "Settings", lambda **_: settings)
    monkeypatch.setattr(live, "database_check", lambda *_: {"discovery_ready": True})
    monkeypatch.setattr(live, "readonly_database", Mock(side_effect=RuntimeError("offline fixture")))
    publish = Mock()
    monkeypatch.setattr(live, "publish", publish)
    run = Mock(return_value=SimpleNamespace(returncode=2))
    monkeypatch.setattr(master.subprocess, "run", run)
    selected = master.plan(env(AGENT_MODE=mode, WRITE_APPROVAL="APPROVE_" + mode.upper() + "_WRITES"), SHA)
    assert master.execute(selected) == 2
    args = run.call_args.args[0]
    assert args[2:] == ["website_agent.cli", mode] and "--production" not in args
    assert "GITHUB_STEP_SUMMARY" not in run.call_args.kwargs["env"]
    assert run.call_args.kwargs["stdout"] == master.subprocess.DEVNULL
    assert "private" not in json.dumps(publish.call_args.args[0])


def test_draft_gate_precedes_auth_and_state(session, settings):
    settings.enable_drafts = False
    client, credentials = Mock(), Mock(valid=False)
    with pytest.raises(Blocked):
        Gmail(settings, client, credentials).draft("private")
    with pytest.raises(Blocked):
        create_draft(session, Mock(), settings, Mock())
    credentials.refresh.assert_not_called()
    client.post.assert_not_called()
    assert not session.new


def test_deploy_gate_precedes_uncertain_state(session, settings, config, site):
    settings.enable_deployment = False
    client = Mock()
    with pytest.raises(Blocked):
        Netlify(settings, client).create({}, "fixture")
    client.post.assert_not_called()
    site.status = "generated"
    with pytest.raises(Blocked):
        Pipeline(session, settings, config).deploy(site)
    assert site.status == "generated" and not site.deploy_id


@pytest.mark.parametrize("actual,reviewed", [(SHA, "b" * 40), ("b" * 40, SHA)])
def test_inline_revision_gate_blocks_before_repository_python(monkeypatch, actual, reviewed):
    workflow = yaml.load(
        Path(".github/workflows/global-website-agent.yml").read_text(), Loader=yaml.BaseLoader
    )
    steps = workflow["jobs"]["agent"]["steps"]
    inline = steps[1]["run"]
    assert "subprocess" in inline and steps[2]["id"] == "preflight"
    code = inline.split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("REVIEWED_COMMIT", reviewed)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setattr(master.subprocess, "check_output", Mock(return_value=actual))
    with pytest.raises(SystemExit):
        exec(compile(code, "workflow revision guard", "exec"), {})


@pytest.mark.parametrize(
    "status,expected", [("deferred_resource_limit", 2), ("failed", 1), ("completed", 0), ("raised", 2)]
)
def test_cli_exit_status_preserves_deferred_and_failure(monkeypatch, session, settings, status, expected):
    from contextlib import contextmanager

    from website_agent import cli

    @contextmanager
    def locked(_):
        yield session

    pipe = Mock()
    pipe.start.return_value = True
    pipe.run.status = status
    if status == "raised":
        from website_agent.security import CapacityDeferred

        pipe.daily.side_effect = CapacityDeferred("Fixture quota pause")
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    settings.database_url = "sqlite:///:memory:"
    monkeypatch.setattr(cli, "engine_for", lambda _: object())
    monkeypatch.setattr(cli, "locked_session", locked)
    monkeypatch.setattr(cli, "Pipeline", lambda *_: pipe)
    monkeypatch.setattr(cli, "sync_policies", Mock())
    monkeypatch.setattr(cli, "report", Mock(return_value="aggregate fixture"))
    monkeypatch.setattr(master.sys, "argv", ["website-agent", "daily"])
    if expected:
        with pytest.raises(SystemExit) as result:
            cli.run_cli()
        assert result.value.code == expected
    else:
        cli.run_cli()
    pipe.daily.assert_called_once_with(None, False)


def test_deferred_reply_keeps_checkpoint_and_stops_followups(session, settings, config, prospect, fakes):
    from website_agent.database import get_config
    from website_agent.security import CapacityDeferred

    fakes.gmail.incoming_messages = [
        {
            "id": "pending-reply",
            "threadId": "thread-1",
            "snippet": "Tell me more about this",
            "payload": {"headers": [{"name": "From", "value": prospect.email}]},
        }
    ]
    ai = Mock()
    ai.generate.side_effect = CapacityDeferred("Gemini cooldown")
    pipe = Pipeline(session, settings, config, ai=ai, gmail=fakes.gmail)
    pipe.start("followups", "deferred-reply-fixture")
    with pytest.raises(CapacityDeferred, match="classification deferred"):
        pipe.followups()
    assert not get_config(session, "reply_checkpoint")
    assert pipe.run.summary["capacity_deferred"] == 1
    assert fakes.gmail.sends == 0 and fakes.gmail.drafts == 0
