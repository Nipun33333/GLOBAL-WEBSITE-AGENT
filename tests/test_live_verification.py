"""Offline security boundaries for the separately owner-dispatched live workflow."""

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import httpx
import pytest
import yaml

from website_agent import live_verification as live


def approved_env():
    return dict(
        GITHUB_REPOSITORY="Nipun33333/GLOBAL-WEBSITE-AGENT",
        GITHUB_REF="refs/heads/feature/free-overture-discovery",
        GITHUB_ACTOR="Nipun33333",
        GITHUB_TRIGGERING_ACTOR="Nipun33333",
        GITHUB_RUN_ATTEMPT="1",
        GITHUB_RUN_ID="fixture",
        GITHUB_EVENT_NAME="workflow_dispatch",
        FREE_LIMITS_REVIEWED="true",
        DATABASE_REVIEWED="true",
        ENABLE_SENDING="false",
        ENABLE_ROUTINE_REPLIES="false",
        AUTOMATION_ENABLED="false",
        VERIFY_MODE="diagnostics",
        REVIEWED_COMMIT="a" * 40,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"VERIFY_MODE": "daily"},
        {"VERIFY_MODE": "discover"},
        {"GITHUB_RUN_ATTEMPT": "2"},
        {"GITHUB_ACTOR": "other"},
        {"GITHUB_TRIGGERING_ACTOR": "other"},
        {"GITHUB_REPOSITORY": "Nipun33333/other"},
        {"GITHUB_REF": "refs/heads/unreviewed"},
        {"ENABLE_SENDING": "true"},
        {"ENABLE_ROUTINE_REPLIES": "true"},
        {"AUTOMATION_ENABLED": "true"},
        {"FREE_LIMITS_REVIEWED": "false"},
        {"DATABASE_REVIEWED": "false"},
        {"REVIEWED_COMMIT": "b" * 40},
    ],
)
def test_preflight_blocks_before_credentials_or_apis(monkeypatch, changes):
    monkeypatch.setattr(live.subprocess, "check_output", Mock(return_value="a" * 40))
    with pytest.raises(live.CheckFailed):
        live.guard({**approved_env(), **changes})


def test_exact_owner_approval_and_revision(monkeypatch):
    monkeypatch.setattr(live.subprocess, "check_output", Mock(return_value="a" * 40))
    live.guard(approved_env())
    live.guard({**approved_env(), "VERIFY_MODE": "discover", "WRITE_APPROVAL": live.APPROVAL})


def test_database_connection_forces_readonly_tls_and_rolls_back(monkeypatch, settings):
    settings.database_url = "postgresql+psycopg://fixture:secret@db.example:5432/postgres?sslmode=disable"
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.scalar.return_value = "on"
    factory = Mock(return_value=engine)
    monkeypatch.setattr(live, "create_engine", factory)
    with live.readonly_database(settings) as conn:
        assert conn is connection
    args = factory.call_args.kwargs["connect_args"]
    assert args["sslmode"] == "verify-full" and "default_transaction_read_only=on" in args["options"]
    assert str(connection.execute.call_args.args[0]) == "SET TRANSACTION READ ONLY"
    connection.commit.assert_not_called()
    connection.rollback.assert_called_once()
    engine.dispose.assert_called_once()


def test_transaction_pooler_rejected_without_connection(monkeypatch, settings):
    settings.database_url = "postgresql+psycopg://fixture:secret@db.example:6543/postgres"
    factory = Mock()
    monkeypatch.setattr(live, "create_engine", factory)
    with pytest.raises(live.CheckFailed):
        with live.readonly_database(settings):
            pass
    factory.assert_not_called()


@pytest.mark.parametrize("case", ["missing", "checksum", "capacity", "ready"])
def test_database_checks_never_apply_migrations(monkeypatch, settings, config, case):
    conn = Mock()
    digest = hashlib.sha256(
        Path("database/migrations/001_initial.sql").read_text(encoding="utf-8").encode()
    ).hexdigest()
    conn.scalar.side_effect = [
        "wrong" if case == "checksum" else digest,
        999_000_000 if case == "capacity" else 1000,
    ]

    @contextmanager
    def database(_):
        yield conn

    monkeypatch.setattr(live, "readonly_database", database)
    monkeypatch.setattr(live, "schema_matches", lambda _: True)
    monkeypatch.setattr(
        live,
        "inspect",
        lambda _: SimpleNamespace(
            get_table_names=lambda: (
                [] if case == "missing" else list(live.Base.metadata.tables) + ["schema_migrations"]
            )
        ),
    )
    result = live.database_check(settings, config)
    assert result["discovery_ready"] == (case == "ready")
    assert all(str(call.args[0]).startswith("SELECT ") for call in conn.scalar.call_args_list)
    conn.commit.assert_not_called()


def test_account_checks_use_only_metadata_site_token_and_profile(settings):
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.host == "generativelanguage.googleapis.com":
            assert request.method == "GET" and "key" not in request.url.params
            return httpx.Response(200, json={"supportedGenerationMethods": ["generateContent"]})
        if request.url.host == "api.netlify.com":
            return httpx.Response(200, json={"id": settings.netlify_site_id, "private_info": "never print"})
        if request.url.host == "oauth2.googleapis.com":
            assert request.method == "POST"
            return httpx.Response(200, json={"access_token": "private-token", "scope": " ".join(live.SCOPES)})
        assert request.method == "GET" and request.url.path.endswith("/profile")
        return httpx.Response(200, json={"emailAddress": settings.sender_email})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        results = [
            live.gemini_check(settings, client),
            live.netlify_check(settings, client),
            live.gmail_check(settings, client),
        ]
    assert all(r["status"].startswith("verified") for r in results)
    raw = json.dumps(results)
    assert "private-token" not in raw and settings.sender_email not in raw and "never print" not in raw
    assert sum(method == "POST" for method, _ in calls) == 1
    assert len(calls) == 9


@pytest.mark.parametrize("scope,expected", [(None, "not_returned"), ("openid", "missing_required_scope")])
def test_gmail_scope_is_not_assumed(settings, scope, expected):
    def handler(request):
        if request.method == "POST":
            data = {"access_token": "private"}
            if scope is not None:
                data["scope"] = scope
            return httpx.Response(200, json=data)
        return httpx.Response(200, json={"emailAddress": settings.sender_email})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = live.gmail_check(settings, client)
    assert result["required_scopes"] == expected
    assert result["status"] == "blocked_scope_verification"
    assert result["mailbox_identity_matches"] is True


def test_provider_failure_reports_code_without_body_or_retry():
    handler = Mock(return_value=httpx.Response(429, text="private-token customer@example.com"))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = live.run_check(lambda: live.api_json(client, "GET", "https://example.com"))
    assert result == {"status": "failed_or_unavailable", "http_status": 429}
    handler.assert_called_once()
    assert live.run_check(lambda: (_ for _ in ()).throw(RuntimeError("password=private"))) == {
        "status": "failed_or_unavailable"
    }


@pytest.mark.parametrize("exit_code", [0, 1])
def test_discovery_isolated_argv_secrets_and_aggregate_output(monkeypatch, settings, config, exit_code):
    for key, value in {
        **approved_env(),
        **dict.fromkeys(live.SECRET_NAMES, "secret"),
        "GITHUB_STEP_SUMMARY": "private-summary",
    }.items():
        monkeypatch.setenv(key, value)
    settings.database_url = "postgresql+psycopg://fixture:secret@db.example/postgres"
    monkeypatch.setattr(live, "window_check", lambda _: {"us_window_open": True})
    runner = Mock(return_value=SimpleNamespace(returncode=exit_code))
    monkeypatch.setattr(live.subprocess, "run", runner)
    conn = Mock()
    conn.execute.return_value.scalar.return_value = {
        "status": "completed_with_results",
        "businesses_inserted": 3,
        "official_websites_verified": 3,
        "private_email": "customer@example.com",
        "next_at": "private-token",
        "rejection_reasons": {"duplicate_domain": 2, "customer@example.com": 99},
        "fallback_layers_attempted": ["overture_aws", "private-token"],
    }

    @contextmanager
    def database(_):
        yield conn

    monkeypatch.setattr(live, "readonly_database", database)
    result = live.discover(settings, config)
    assert runner.call_args.args[0][-3:] == ["discover", "--country", "US"]
    env = runner.call_args.kwargs["env"]
    assert not set(live.SECRET_NAMES[1:]) & set(env)
    assert "GITHUB_STEP_SUMMARY" not in env and env["ENABLE_SENDING"] == "false"
    assert runner.call_args.kwargs["stdout"] == live.subprocess.DEVNULL
    assert "private" not in json.dumps(result) and result["businesses_inserted"] == 3
    assert result["rejection_reasons"] == {"duplicate_domain": 2}
    assert result["fallback_layers_attempted"] == ["overture_aws"]
    assert result["status"] == (
        "completed_with_results" if exit_code == 0 else "failed_after_discovery_check_checkpoint"
    )


def test_closed_window_never_starts_discovery(monkeypatch, settings, config):
    monkeypatch.setattr(live, "window_check", lambda _: {"us_window_open": False})
    runner = Mock()
    monkeypatch.setattr(live.subprocess, "run", runner)
    assert live.discover(settings, config)["status"] == "blocked_local_research_window"
    runner.assert_not_called()


def test_diagnostics_mode_never_invokes_discovery(monkeypatch, tmp_path, settings, config):
    monkeypatch.setenv("VERIFY_MODE", "diagnostics")
    monkeypatch.setenv("REVIEWED_COMMIT", "a" * 40)
    monkeypatch.setattr(live, "guard", lambda _: None)
    monkeypatch.setattr(live, "Settings", lambda **kw: settings)
    monkeypatch.setattr(type(settings), "config", lambda _: config)
    monkeypatch.setattr(live, "window_check", lambda _: {"us_window_open": False})
    for name in ["database_check", "gemini_check", "netlify_check", "gmail_check"]:
        monkeypatch.setattr(live, name, Mock(return_value={"status": "verified_fixture"}))
    discovery = Mock(side_effect=AssertionError("not authorized"))
    monkeypatch.setattr(live, "discover", discovery)
    monkeypatch.chdir(tmp_path)
    assert live.main() == 0
    discovery.assert_not_called()
    data = json.loads(Path("artifacts/live-verification.json").read_text())
    assert data["mode"] == "diagnostics"


def test_workflow_owner_commit_approval_and_no_secret_install():
    path = Path(".github/workflows/global-website-agent.yml")
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch", "schedule"}
    assert workflow["on"]["workflow_dispatch"]["inputs"]["mode"]["default"] == "diagnostics"
    job = workflow["jobs"]["agent"]
    assert "github.triggering_actor == github.repository_owner" in job["if"]
    assert "github.run_attempt == 1" in job["if"]
    assert job["environment"] == "agent-runtime"
    assert job["concurrency"]["group"] == "global-website-agent-runtime"
    assert all("secrets." not in value for value in job["env"].values())
    for step in job["steps"]:
        if "secrets." in str(step):
            assert step["run"] == "uv run python scripts/master_entry.py"
        assert "website-agent migrate" not in str(step)
    assert job["steps"][-1]["with"]["path"].splitlines() == [
        "artifacts/live-verification.json",
        "artifacts/live-verification.md",
    ]
    assert job["steps"][-1]["with"]["retention-days"] == "1"
