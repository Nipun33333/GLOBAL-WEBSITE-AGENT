"""Offline fault matrix. All businesses below are explicitly synthetic fixtures."""

import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from website_agent.database import BusinessSource, Prospect, get_config, suppress
from website_agent.discovery_datasets import RangeFile, osm_query, overture_query
from website_agent.discovery_engine import DiscoveryEngine, areas
from website_agent.discovery_support import (
    BoundedHTTP,
    Budget,
    DiscoveryFault,
    atomic_json,
    resource,
    schema,
    unavailable,
)
from website_agent.security import Page
from website_agent.settings import DiscoveryConfig, Location, Settings

AT = datetime(2026, 10, 20, 15, tzinfo=UTC)


def record(**changes):
    return {
        "provider": "overture",
        "provider_id": "fixture-1",
        "name": "Fixture Salon",
        "url": "https://fixture.example/",
        "country": "US",
        "city": "New York",
        "category": "hair_salon",
        "lat": 40.75,
        "lon": -73.95,
        "release": "2026-09-23.1",
        "license": "fixture-only",
        "attribution": "Synthetic test fixture",
        "sources": [],
        **changes,
    }


def batch(records=None, **kw):
    return {"records": records or [], "cursor": {}, "exhausted": True, "release": "2026-09-23.1", **kw}


class FixtureWeb:
    def fetch(self, url):
        return Page(
            url,
            200,
            {"content-type": "text/html"},
            "<title>Fixture Salon</title><h1>Fixture Salon</h1><p>New York and London</p>"
            + f'<a href="mailto:contact@{urlsplit(url).hostname}">Contact</a>',
        )


@pytest.fixture
def discovery_setup(config, tmp_path):
    cfg = config.model_copy(deep=True)
    cfg.locations = cfg.locations[:1]
    cfg.niches = ["salons"]
    cfg.discovery.taxonomy_path = str(Path("config/discovery-taxonomy.yml").resolve())
    cfg.discovery.radius_steps_km = [3]
    cfg.discovery.max_radius_km = 3
    cfg.discovery.max_cities = 1
    cfg.discovery.max_queries = 32
    cfg.discovery.cache_hours = 0
    cfg.discovery.osm_license_review_reference = "offline-test-review"
    cfg.discovery.osm_database_obligations_accepted = True

    def engine(session, settings, reader, **kw):
        def selector(*args, **kwargs):
            visited = kwargs.get("exclude_cities", set())
            loc = next((x for x in cfg.locations if (x.country, x.city) not in visited), None)
            return (SimpleNamespace(niche="salons"), loc) if loc else None

        result = DiscoveryEngine(
            session, settings, cfg, reader=reader, web=FixtureWeb(), clock=lambda: AT, selector=selector, **kw
        )
        result.cache = tmp_path / "cache"
        return result

    return cfg, engine


@pytest.mark.parametrize("bad", [[], [record(category="museum")], [record(url="")]])
def test_overture_empty_irrelevant_or_no_website_falls_back(session, settings, discovery_setup, bad):
    _, make = discovery_setup
    calls = []

    def reader(c, q, b):
        calls.append(q["source"])
        return batch(
            bad if q["source"] == "overture" else [record(provider="osm", category="shop=hairdresser")]
        )

    outcome = make(session, settings, reader).run()
    assert outcome["accepted"] == 1
    assert "osm_extract" in calls
    assert session.scalar(select(Prospect)).niche == "shop=hairdresser"


def test_aws_outage_azure_succeeds(session, settings, discovery_setup):
    _, make = discovery_setup
    endpoints = []

    def reader(c, q, b):
        endpoints.append(q["endpoint"])
        if q["endpoint"] == "aws":
            raise unavailable("offline-aws-outage")
        return batch([record()])

    outcome = make(session, settings, reader).run()
    assert outcome["accepted"] == 1 and endpoints[:2] == ["aws", "azure"]


def test_both_overture_endpoints_fail_osm_extract_succeeds(session, settings, discovery_setup):
    _, make = discovery_setup

    def reader(c, q, b):
        if q["source"] == "overture":
            raise unavailable("outage")
        return batch([record(provider="osm", category="shop=hairdresser")])

    result = make(session, settings, reader).run()
    assert result["accepted"] == 1
    assert result["status"] == "deferred_provider_unavailable"  # Partial results are not full success.


def test_osm_terms_prohibited_never_calls_provider(session, settings, discovery_setup):
    cfg, make = discovery_setup
    cfg.discovery.source_priority = ["osm_extract"]
    cfg.discovery.osm_database_obligations_accepted = False
    reader = Mock()
    result = make(session, settings, reader).run()
    assert result["status"] == "blocked_permission_or_license"
    reader.assert_not_called()


def test_every_source_unavailable_persists_retry_and_circuit(session, settings, discovery_setup):
    _, make = discovery_setup
    reader = Mock(side_effect=unavailable("outage"))
    result = make(session, settings, reader).run()
    assert result["status"] == "deferred_provider_unavailable"
    assert get_config(session, "discovery_task:worldwide")["next_at"]
    count = reader.call_count
    again = make(session, settings, reader).run()
    assert again["accepted"] == 0 and reader.call_count == count


@pytest.mark.parametrize(
    "changes",
    [
        {"url": "javascript:alert(1)"},
        {"url": "https://facebook.com/fixture"},
        {"url": "https://fixture.example/search?q=salon"},
        {"url": "https://user:pass@fixture.example"},
        {"city": "Paris"},
        {"country": "FR"},
        {"lat": 10},
        {"lat": float("nan")},
        {"name": ""},
    ],
)
def test_invalid_or_mismatched_records_are_unverified(session, settings, discovery_setup, changes):
    cfg, make = discovery_setup
    cfg.discovery.source_priority = ["overture"]
    result = make(session, settings, lambda *a: batch([record(**changes)])).run()
    assert result["accepted"] == 0 and result["unverified"] > 0
    assert result["status"] == "completed_no_qualified_results"
    assert session.scalar(select(Prospect)) is None


def test_duplicates_across_sources_and_provider_ids(session, settings, discovery_setup):
    _, make = discovery_setup

    def reader(c, q, b):
        return batch(
            [
                record(
                    provider="overture" if q["source"] == "overture" else "osm", category=q["categories"][0]
                ),
                record(url="https://other.example/", category=q["categories"][0]),
            ]
        )

    make(session, settings, reader).run()
    assert len(session.scalars(select(Prospect)).all()) == 1


def test_related_niche_fallback(session, settings, discovery_setup):
    cfg, make = discovery_setup
    cfg.discovery.source_priority = ["overture"]

    def reader(c, q, b):
        return batch([record(category="barber_shop")]) if q["related"] else batch()

    result = make(session, settings, reader).run()
    assert result["accepted"] == 1
    assert session.scalar(select(Prospect)).niche == "barber_shop"


def test_geographic_radius_fallback(session, settings, discovery_setup):
    cfg, make = discovery_setup
    cfg.discovery.source_priority = ["overture"]
    cfg.discovery.max_radius_km = 15
    cfg.discovery.radius_steps_km = [3, 8]

    def reader(c, q, b):
        return batch([record(lon=-73.87)]) if q["bbox"][2] > -73.87 else batch()

    result = make(session, settings, reader).run()
    assert result["accepted"] == 1
    assert session.scalar(select(Prospect)).city == "New York"


def test_next_city_fallback(session, settings, discovery_setup):
    cfg, make = discovery_setup
    cfg.discovery.source_priority = ["overture"]
    cfg.discovery.max_cities = 2
    cfg.locations.append(
        Location(
            country="GB", city="London", timezone="Europe/London", language="en", bbox=[-0.2, 51.4, 0.0, 51.6]
        )
    )

    def reader(c, q, b):
        return (
            batch([record(country="GB", city="London", lon=-0.1, lat=51.5)])
            if q["city"] == "London"
            else batch()
        )

    result = make(session, settings, reader).run()
    assert result["accepted"] == 1
    assert session.scalar(select(Prospect)).country == "GB"


def test_query_budget_and_resumed_checkpoint(session, settings, discovery_setup):
    cfg, make = discovery_setup
    cfg.discovery.max_queries = 1
    calls = []

    def reader(c, q, b):
        calls.append(q["source"])
        return batch()

    result = make(session, settings, reader).run()
    assert result["status"] == "deferred_resource_limit"
    second = make(session, settings, reader)
    second.clock = lambda: AT + timedelta(hours=2)
    second.run()
    assert calls[:2] == ["overture", "osm_extract"]


@pytest.mark.parametrize("fault", [KeyboardInterrupt, SystemExit])
def test_interrupted_job_resumes_pending_candidates(session, settings, discovery_setup, fault):
    cfg, make = discovery_setup
    cfg.discovery.source_priority = ["overture"]
    reader = Mock(
        return_value=batch([record(), record(provider_id="fixture-2", url="https://second.example")])
    )
    first = make(session, settings, reader)
    original = first.web.fetch
    calls = 0

    def fetch(url):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise fault()
        return original(url)

    first.web.fetch = fetch
    with pytest.raises(fault):
        first.run()
    state = get_config(session, "discovery_task:worldwide")
    assert state["pending"]["index"] == 1
    session.expunge_all()
    next_run = make(session, settings, reader)
    next_run.run()
    assert len(session.scalars(select(Prospect)).all()) == 2
    assert reader.call_count == 2  # second call is the related-category step, not lost primary work


def test_db_write_failure_rolls_back_admission_and_resume(session, settings, discovery_setup, monkeypatch):
    cfg, make = discovery_setup
    cfg.discovery.source_priority = ["overture"]
    first = make(session, settings, lambda *a: batch([record()]))
    commit = session.commit

    def failing_commit():
        if session.scalar(select(BusinessSource)) is not None:
            raise OperationalError("fixture", {}, Exception("db down"))
        return commit()

    monkeypatch.setattr(session, "commit", failing_commit)
    with pytest.raises(OperationalError):
        first.run()
    session.rollback()
    monkeypatch.setattr(session, "commit", commit)
    assert session.scalar(select(Prospect)) is None
    make(session, settings, lambda *a: batch()).run()
    assert session.scalar(select(Prospect)).name == "Fixture Salon"


def test_provider_429_does_not_rotate_mirrors(session, settings, discovery_setup):
    cfg, make = discovery_setup
    cfg.discovery.source_priority = ["overture"]
    reader = Mock(side_effect=unavailable("provider_rate_limited", 7200))
    result = make(session, settings, reader).run()
    assert reader.call_count == 1
    assert result["status"] == "deferred_provider_unavailable"
    assert datetime.fromisoformat(result["next_at"]) >= AT + timedelta(hours=2)


def test_schema_error_requires_operator_without_infinite_retry(session, settings, discovery_setup):
    cfg, make = discovery_setup
    cfg.discovery.source_priority = ["overture"]
    reader = Mock(side_effect=schema())
    result = make(session, settings, reader).run()
    assert result["status"] == "failed_requires_operator"
    next_run = make(session, settings, reader)
    next_run.clock = lambda: AT + timedelta(days=2)
    next_run.run()
    assert reader.call_count == 1


@pytest.mark.parametrize(
    "reason", ["memory_budget", "disk_budget", "network_byte_budget", "discovery_deadline"]
)
def test_resource_failures_defer(session, settings, discovery_setup, reason):
    _, make = discovery_setup
    result = make(session, settings, Mock(side_effect=resource(reason))).run()
    assert result["status"] == "deferred_resource_limit" and result["accepted"] == 0


@pytest.mark.parametrize("key", ["fixture.example", "contact@fixture.example"])
def test_base44_exclusions_apply_before_network(session, settings, discovery_setup, key):
    _, make = discovery_setup
    suppress(session, key, "previous_contact", "Base44 fixture")
    engine = make(session, settings, lambda *a: batch([record()]))
    engine.web.fetch = Mock(side_effect=AssertionError("must not fetch"))
    assert engine.run()["accepted"] == 0
    engine.web.fetch.assert_not_called()


def test_all_website_verifications_fail_returns_empty(session, settings, discovery_setup):
    _, make = discovery_setup
    engine = make(session, settings, lambda *a: batch([record()]))
    engine.web.fetch = lambda url: Page(
        url, 200, {"content-type": "text/html"}, "<title>Other business</title>"
    )
    result = engine.run()
    assert result["status"] == "completed_no_qualified_results" and result["accepted"] == 0


def test_no_api_keys_needed_and_no_sending_enabled(session, discovery_setup):
    _, make = discovery_setup
    settings = Settings(_env_file=None)
    result = make(session, settings, lambda *a: batch([record()])).run()
    assert result["accepted"] == 1
    assert (
        not settings.discovery_api_key and not settings.enable_sending and not settings.enable_routine_replies
    )
    source = session.scalar(select(BusinessSource))
    assert source.evidence["verified_business"] and source.evidence["dataset_release"]
    assert source.evidence["license"] and source.evidence["attribution"] and source.evidence["retrieved_at"]
    assert session.scalar(select(Prospect)).eligibility == {}


def test_no_businesses_anywhere_is_accurate_empty_result(session, settings, discovery_setup):
    _, make = discovery_setup
    result = make(session, settings, lambda *a: batch()).run()
    assert result["status"] == "completed_no_qualified_results" and result["accepted"] == 0


def test_valid_cache_reused_offline(session, settings, discovery_setup):
    cfg, make = discovery_setup
    cfg.discovery.cache_hours = 24
    reader = Mock(return_value=batch([record()]))
    engine = make(session, settings, reader)
    query = engine.plan(None)[0]
    engine.query(query)
    engine.reader = Mock(side_effect=AssertionError("cached query must not call network"))
    assert engine.query(query)["records"][0]["name"] == "Fixture Salon"


def response(status, content=b"", headers=None):
    return httpx.Response(status, stream=httpx.ByteStream(content), headers=headers or {})


def test_transport_retries_exponential_bounded_and_partial_download():
    cfg = DiscoveryConfig(max_attempts=3, retry_base_seconds=1)
    calls = []
    waits = []

    def handler(req):
        calls.append(req)
        raise httpx.ReadTimeout("fixture")

    http = BoundedHTTP(
        Budget(cfg),
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=waits.append,
        jitter=lambda: 0,
    )
    with pytest.raises(DiscoveryFault, match="transport_retries_exhausted"):
        http.get("https://fixture.example")
    assert len(calls) == 3 and waits == [1, 2]


def test_http_429_retry_after_no_immediate_retry():
    handler = Mock(return_value=response(429, headers={"retry-after": "7200"}))
    http = BoundedHTTP(Budget(DiscoveryConfig()), httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(DiscoveryFault) as exc:
        http.get("https://fixture.example")
    assert exc.value.retry_after == 7200 and handler.call_count == 1


def test_http_503_recovers_without_unbounded_retries():
    replies = iter([response(503), response(200, b"ok")])
    http = BoundedHTTP(
        Budget(DiscoveryConfig()),
        httpx.Client(transport=httpx.MockTransport(lambda r: next(replies))),
        sleep=lambda _: None,
    )
    assert http.get("https://fixture.example")[0] == b"ok"


def test_partial_range_download_never_accepted():
    http = Mock()
    http.get.return_value = (b"abc", {"content-range": "bytes 0-9/10"})
    with pytest.raises(DiscoveryFault, match="invalid_or_partial_range"):
        RangeFile(http, "https://fixture.example", 10).read(10)


def test_atomic_cache_failure_keeps_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "cache.json"
    atomic_json(path, {"old": True}, 10000)
    import website_agent.discovery_support as support

    monkeypatch.setattr(support.os, "replace", Mock(side_effect=OSError("interrupted")))
    with pytest.raises(OSError):
        atomic_json(path, {"new": True}, 10000)
    assert json.loads(path.read_text()) == {"old": True}
    assert not path.with_suffix(".json.tmp").exists()


def test_actual_parquet_range_reader_with_offline_http(monkeypatch):
    row = {
        "id": "fixture-1",
        "names": {"primary": "Fixture Salon"},
        "taxonomy": {"primary": "hair_salon"},
        "bbox": {"xmin": -73.95, "xmax": -73.95, "ymin": 40.75, "ymax": 40.75},
        "addresses": [{"country": "US", "locality": "New York"}],
        "websites": ["https://fixture.example"],
    }
    output = io.BytesIO()
    pq.write_table(pa.Table.from_pylist([row]), output)
    raw = output.getvalue()

    def handler(req):
        start, end = map(int, req.headers["range"].removeprefix("bytes=").split("-"))
        return response(206, raw[start : end + 1], {"content-range": f"bytes {start}-{end}/{len(raw)}"})

    import website_agent.discovery_datasets as ds

    monkeypatch.setattr(ds, "objects", lambda *a: [("https://fixture.example/file.parquet", len(raw))])
    cfg = DiscoveryConfig()
    http = BoundedHTTP(Budget(cfg), httpx.Client(transport=httpx.MockTransport(handler)))
    data = overture_query(
        cfg, {"endpoint": "aws", "bbox": [-74, 40, -73, 41], "categories": ["hair_salon"]}, http
    )
    assert data["exhausted"] and data["records"][0]["provider_id"] == "fixture-1"


def test_osm_regional_extract_real_parser_and_integrity(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("private").mkdir()
    raw = b'<osm><node id="1" lon="-73.95" lat="40.75"><tag k="name" v="Fixture Salon"/><tag k="website" v="https://fixture.example"/><tag k="shop" v="hairdresser"/><tag k="addr:city" v="New York"/><tag k="addr:country" v="US"/></node></osm>'
    Path("private/region.osm").write_bytes(raw)
    cfg = DiscoveryConfig(
        osm_license_review_reference="fixture",
        osm_database_obligations_accepted=True,
        osm_extracts=[
            {
                "path": "private/region.osm",
                "country": "US",
                "city": "New York",
                "release": "fixture-release",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "commercial_use_authorized": True,
                "agreement_reference": "fixture",
            }
        ],
    )
    q = {
        "source": "osm_extract",
        "country": "US",
        "city": "New York",
        "bbox": [-74, 40, -73, 41],
        "categories": ["shop=hairdresser"],
    }
    data = osm_query(cfg, q, BoundedHTTP(Budget(cfg)))
    assert data["records"][0]["provider_id"] == "node/1"
    assert data["records"][0]["license"] == "ODbL-1.0"
    cfg.osm_extracts[0]["sha256"] = "wrong"
    with pytest.raises(DiscoveryFault, match="integrity"):
        osm_query(cfg, q, BoundedHTTP(Budget(cfg)))


def test_nearby_district_preserves_name_and_limits(config):
    from website_agent.settings import SearchArea

    loc = config.locations[0].model_copy(deep=True)
    loc.nearby_areas = [
        SearchArea(city="Nearby Fixture", country="US", bbox=[-73.96, 40.76, -73.94, 40.78]),
        SearchArea(city="Far Fixture", country="US", bbox=[0, 40, 1, 41]),
    ]
    result = areas(loc, config.discovery)
    assert any(a["city"] == "Nearby Fixture" for a in result)
    assert all(a["city"] != "Far Fixture" for a in result)


def test_retry_cycles_eventually_require_operator(session, settings, discovery_setup):
    cfg, make = discovery_setup
    cfg.discovery.max_retry_cycles = 1
    reader = Mock(side_effect=unavailable("outage"))
    make(session, settings, reader).run()
    for i in (1, 2):
        engine = make(session, settings, reader)
        engine.clock = lambda i=i: AT + timedelta(days=i)
        result = engine.run()
    assert result["status"] == "failed_requires_operator"
    assert result["reason"] == "retry_cycles_exhausted"


def test_pending_page_continuation_preserved_across_sessions(session, settings, discovery_setup):
    cfg, make = discovery_setup
    cfg.discovery.source_priority = ["overture"]

    def reader(c, q, b):
        if q.get("related"):
            return batch()
        if q.get("cursor"):
            assert q["cursor"]["file"] == 8
            return batch([record(provider_id="next", url="https://next.example")])
        return batch([record()], exhausted=False, cursor={"file": 8, "group": 0, "row": 0})

    first = make(session, settings, reader).run()
    assert first["status"] == "deferred_resource_limit" and first["accepted"] == 1
    session.expunge_all()
    engine = make(session, settings, reader)
    engine.clock = lambda: AT + timedelta(days=1)
    assert engine.run()["accepted"] == 1
    assert len(session.scalars(select(Prospect)).all()) == 2


def test_discovery_failure_does_not_stop_queued_pipeline_work(
    session, settings, config, prospect, fakes, monkeypatch
):
    from website_agent.pipeline import Pipeline

    pipe = Pipeline(session, settings, config, ai=fakes.ai, gmail=fakes.gmail, web=fakes.web)

    def unavailable_discovery(country):
        pipe.discovery_outcome = {"status": "deferred_provider_unavailable"}
        return False

    monkeypatch.setattr(pipe, "discover", unavailable_discovery)
    generate = Mock(return_value=None)
    monkeypatch.setattr(pipe, "generate", generate)
    pipe.start("daily", "discovery-outage-fixture")
    pipe.daily()
    pipe.finish()
    generate.assert_called_once_with(prospect)
    assert pipe.run.status == "deferred_provider_unavailable"
    assert fakes.gmail.sends == 0


def test_no_eligible_city_is_deferred_again_not_false_success(session, settings, discovery_setup):
    _, make = discovery_setup
    engine = make(session, settings, Mock())
    engine.selector = lambda *a, **k: None
    assert engine.run()["status"] == "deferred_provider_unavailable"
    engine = make(session, settings, Mock())
    engine.selector = lambda *a, **k: None
    engine.clock = lambda: AT + timedelta(days=1)
    assert engine.run()["status"] == "deferred_provider_unavailable"


def test_permission_revocation_blocks_cached_overpass(session, settings, discovery_setup):
    cfg, make = discovery_setup
    cfg.discovery.source_priority = ["overpass"]
    cfg.discovery.cache_hours = 24
    cfg.discovery.overpass_private_or_contracted = True
    cfg.discovery.overpass_commercial_use_authorized = True
    cfg.discovery.overpass_agreement_reference = "fixture"
    cfg.discovery.overpass_endpoint = "https://fixture.example/api"
    engine = make(session, settings, lambda *a: batch())
    q = engine.plan(None)[0]
    engine.query(q)
    cfg.discovery.overpass_commercial_use_authorized = False
    engine.reader = Mock(side_effect=AssertionError("must not query"))
    with pytest.raises(DiscoveryFault, match="not_authorized"):
        engine.query(q)


def test_direct_budget_enforcement(tmp_path, monkeypatch):
    cfg = DiscoveryConfig(max_requests=1, max_download_bytes=1024)
    budget = Budget(cfg)
    budget.request()
    with pytest.raises(DiscoveryFault, match="request_budget"):
        budget.request()
    with pytest.raises(DiscoveryFault, match="network_byte_budget"):
        budget.consume(1025)
    with pytest.raises(DiscoveryFault, match="disk_budget"):
        atomic_json(tmp_path / "too-big.json", {"value": "x" * 2000}, 1024)
    import website_agent.discovery_support as support

    monkeypatch.setattr(
        support.psutil, "Process", lambda: SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=2**40))
    )
    with pytest.raises(DiscoveryFault, match="memory_budget"):
        budget.check()


def test_interrupted_download_counts_bytes_and_never_returns_partial():
    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"partial"
            raise httpx.ReadError("interrupted fixture")

    cfg = DiscoveryConfig(max_attempts=2)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=BrokenStream())))
    http = BoundedHTTP(Budget(cfg), client, sleep=lambda _: None)
    with pytest.raises(DiscoveryFault, match="transport_retries_exhausted"):
        http.get("https://fixture.example")
    assert http.budget.requests == 2


def test_supervised_worker_actual_local_osm_read(tmp_path, monkeypatch):
    from website_agent.discovery_engine import run_reader

    monkeypatch.chdir(tmp_path)
    Path("private").mkdir()
    path = Path("private/region.osm")
    path.write_text('<osm version="0.6"></osm>')
    cfg = DiscoveryConfig(
        osm_license_review_reference="fixture",
        osm_database_obligations_accepted=True,
        osm_extracts=[
            {
                "path": str(path.resolve()),
                "city": "New York",
                "country": "US",
                "release": "fixture",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "agreement_reference": "fixture",
                "commercial_use_authorized": True,
            }
        ],
    )
    data = run_reader(
        cfg,
        {
            "source": "osm_extract",
            "city": "New York",
            "country": "US",
            "bbox": [-74, 40, -73, 41],
            "categories": ["shop=hairdresser"],
        },
        Budget(cfg),
    )
    assert data["exhausted"] and data["records"] == []
    assert not list(Path("private/discovery-worker").glob("*.json"))


def test_discovery_only_cli_isolated_and_deferred_exit_code(session, settings, monkeypatch):
    from contextlib import nullcontext

    from website_agent import cli

    settings.database_url = "postgresql+psycopg://unused-fixture"
    settings.enable_sending = True
    settings.enable_routine_replies = True
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "engine_for", lambda _: None)
    monkeypatch.setattr(cli, "locked_session", lambda _: nullcontext(session))
    monkeypatch.setattr(cli, "sync_policies", Mock(side_effect=AssertionError("do not change policies")))
    monkeypatch.setattr(cli, "report", lambda *a: "offline fixture report")
    monkeypatch.setattr("sys.argv", ["website-agent", "discover", "--country", "US", "--production"])

    def discover(self, country):
        assert country == "US"
        assert not settings.enable_sending and not settings.enable_routine_replies
        assert self._ai is self._gmail is self._hosting is None
        self.discovery_outcome = {"status": "deferred_resource_limit", "accepted": 0}

    monkeypatch.setattr(cli.Pipeline, "discover", discover)
    with pytest.raises(SystemExit) as exc:
        cli.run_cli()
    assert exc.value.code == 2


def test_radius_corner_outside_configured_circle_is_rejected(session, settings, discovery_setup):
    cfg, make = discovery_setup
    cfg.discovery.source_priority = ["overture"]
    # Inside the square 3km search bbox, but outside its 3km radius.
    engine = make(session, settings, lambda *a: batch([record(lon=-73.92, lat=40.775)]))
    result = engine.run()
    assert result["accepted"] == 0


def test_partial_429_result_opens_shared_circuit(session, settings, discovery_setup):
    _, make = discovery_setup
    reader = Mock(
        return_value=batch(
            [record()],
            exhausted=False,
            cursor={"file": 1, "group": 0, "row": 0},
            fault={
                "status": "deferred_provider_unavailable",
                "reason": "provider_rate_limited",
                "retry_after": 7200,
            },
        )
    )
    engine = make(session, settings, reader)
    queries = engine.plan(None)
    engine.query(queries[0])
    with pytest.raises(DiscoveryFault, match="provider_rate_limited"):
        engine.query({**queries[0], "cursor": {"file": 1, "group": 0, "row": 0}})
    assert reader.call_count == 1


def test_website_rate_limit_is_persisted_before_retry(session, settings, discovery_setup):
    _, make = discovery_setup
    engine = make(session, settings, lambda *a: batch([record()]))
    engine.web.fetch = Mock(return_value=Page("https://fixture.example/", 429, {"retry-after": "7200"}, ""))
    result = engine.run()
    assert result["accepted"] == 0
    engine.web.fetch.assert_called_once()


def test_closed_local_window_does_not_exhaust_retry_cycles(session, settings, discovery_setup):
    cfg, make = discovery_setup
    cfg.discovery.source_priority = ["overture"]
    cfg.discovery.max_retry_cycles = 1
    make(
        session, settings, lambda *a: batch([], exhausted=False, cursor={"file": 1, "group": 0, "row": 0})
    ).run()
    # Overnight New York: persist a window deferral without burning repeated provider retries.
    for hours in (12, 13, 14):
        engine = make(session, settings, Mock(side_effect=AssertionError("outside window")))
        engine.clock = lambda hours=hours: AT + timedelta(hours=hours)
        result = engine.run()
        assert result["status"] == "deferred_provider_unavailable"


def test_actual_category_preserves_scheduler_relevance(session, settings, config, prospect, fakes):
    from website_agent.database import LocationQueue
    from website_agent.pipeline import Pipeline

    prospect.niche = "hair_salon"
    queue = LocationQueue(country=prospect.country, city=prospect.city, niche="salons")
    session.add(queue)
    session.add(
        BusinessSource(
            prospect_id=prospect.id,
            provider="overture",
            provider_id="fixture",
            evidence={"requested_niche": "salons", "rotation_city": prospect.city},
        )
    )
    session.commit()
    pipe = Pipeline(session, settings, config, ai=fakes.ai, web=fakes.web)
    pipe.start("daily", "relevance-fixture")
    pipe.audit(prospect)
    assert queue.relevant == 1 and prospect.niche == "hair_salon"
