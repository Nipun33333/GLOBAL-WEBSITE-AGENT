import os
from pathlib import Path

import pytest
import yaml
from sqlalchemy import inspect, text

from website_agent.cli import migrate
from website_agent.database import LOCK_KEY, Base, assert_lock, engine_for, locked_session


@pytest.mark.postgres
def test_postgresql_migrations_and_cross_runner_lock():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL unavailable; actual PostgreSQL concurrency not locally verified")
    engine = engine_for(url)
    migrate(engine)
    migrate(engine)  # Repeat application is safe.
    assert set(Base.metadata.tables) <= set(inspect(engine).get_table_names())
    with locked_session(engine) as first:
        assert first.scalar(text("SELECT 1")) == 1
        first.commit()
        assert_lock(first)
        with pytest.raises(RuntimeError, match="Another agent"):
            with locked_session(engine):
                pass
    with locked_session(engine) as second:
        assert second.scalar(text("SELECT 1")) == 1
        second.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
        second.commit()
        with pytest.raises(RuntimeError, match="ownership lost"):
            assert_lock(second)
    engine.dispose()


def test_required_workflows_and_safety():
    root = Path(".github/workflows")
    required = [
        "global-daily-pipeline",
        "gmail-reply-checker",
        "followup-processor",
        "weekly-report",
        "manual-production-run",
    ]
    assert not (root / "tests.yml").exists()
    for name in required:
        data = yaml.load((root / (name + ".yml")).read_text(), Loader=yaml.BaseLoader)
        assert data["permissions"]["contents"] == "read"
        assert "workflow_dispatch" in data["on"]
    shared = yaml.load((root / "_agent-runtime.yml").read_text(), Loader=yaml.BaseLoader)
    assert shared["jobs"]["agent"]["concurrency"]["cancel-in-progress"] == "false"
    assert "secrets.GMAIL_REFRESH_TOKEN" in shared["jobs"]["agent"]["env"]["GMAIL_REFRESH_TOKEN"]
    manual = yaml.load((root / "manual-production-run.yml").read_text(), Loader=yaml.BaseLoader)
    assert manual["on"]["workflow_dispatch"]["inputs"]["production"]["default"] == "false"
    for step in shared["jobs"]["agent"]["steps"]:
        if "uses" in step:
            assert len(step["uses"].split("@")[1]) == 40


def test_all_country_templates_disabled():
    data = yaml.safe_load(Path("config/country-policies.yml").read_text())
    assert len(data) == 11
    assert all(not p["enabled"] for p in data.values())
