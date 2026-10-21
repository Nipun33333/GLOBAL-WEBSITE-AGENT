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
    assert sorted(p.name for p in root.glob("*.y*ml")) == ["global-website-agent.yml"]
    data = yaml.load((root / "global-website-agent.yml").read_text(), Loader=yaml.BaseLoader)
    assert data["permissions"] == {"contents": "read"}
    assert "workflow_dispatch" in data["on"]
    job = data["jobs"]["agent"]
    assert job["concurrency"]["cancel-in-progress"] == "false"
    assert data["on"]["workflow_dispatch"]["inputs"]["request_sending"]["default"] == "false"
    for step in job["steps"]:
        if "uses" in step:
            assert len(step["uses"].split("@")[1]) == 40


def test_all_country_templates_disabled():
    data = yaml.safe_load(Path("config/country-policies.yml").read_text())
    assert len(data) == 11
    assert all(not p["enabled"] for p in data.values())
