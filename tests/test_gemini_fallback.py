"""Fallback uses synthetic account metadata; no credentials or model generation requests."""

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from google.genai import errors
from pydantic import ValidationError
from sqlalchemy import select

from website_agent.ai import EmailCopy, Gemini
from website_agent.database import CostUsage, get_config, now, set_config
from website_agent.security import Blocked, CapacityDeferred
from website_agent.settings import GeminiPolicy


def metadata(**changes):
    return SimpleNamespace(
        **{
            "supported_actions": ["generateContent"],
            "input_token_limit": 1048576,
            "output_token_limit": 65536,
            **changes,
        }
    )


def response(text=None):
    return SimpleNamespace(
        text=text or json.dumps({"subject": "Hi", "opening": "Hello", "invitation": "Interested?"}),
        model_version="gemini-3.6-flash-001",
        usage_metadata=SimpleNamespace(
            prompt_token_count=10, candidates_token_count=20, thoughts_token_count=5
        ),
    )


@pytest.fixture
def ai_case(session, settings, config, monkeypatch):
    client = Mock()
    client.models.get.return_value = metadata()
    client.models.generate_content.return_value = response()
    config.model_prices = {
        m: {"input_per_million": 0, "output_per_million": 0} for m in config.gemini.capabilities
    }
    monkeypatch.setattr("website_agent.ai.time.sleep", Mock())
    return Gemini(settings, config, session, client), client


def test_primary_preference_and_persistent_provenance(ai_case, session):
    ai, client = ai_case
    assert ai.generate("draft", {}, EmailCopy).subject == "Hi"
    assert client.models.generate_content.call_args.kwargs["model"] == "gemini-3.8-flash"
    assert ai.last_provenance["reported_model_version"] == "gemini-3.6-flash-001"
    resumed = Gemini(ai.settings, ai.config, session, client)
    assert resumed.generate("draft", {}, EmailCopy).subject == "Hi"
    assert resumed.last_provenance == ai.last_provenance
    assert client.models.generate_content.call_count == 1
    assert session.scalar(select(CostUsage)).units["status"] == "validated"


@pytest.mark.parametrize("code", [404, 500, 502, 503, 504])
def test_generation_failure_falls_back_after_bounded_retries(ai_case, session, code):
    ai, client = ai_case
    count = 1 if code == 404 else 3
    client.models.generate_content.side_effect = [
        errors.APIError(code, {"error": {"message": "private"}})
    ] * count + [response()]
    ai.generate("draft", {}, EmailCopy)
    assert ai.model == "gemini-3.6-flash"
    assert client.models.generate_content.call_count == count + 1
    assert get_config(session, "gemini_health:gemini-3.8-flash")["until"]
    assert "private" not in str([row.units for row in session.scalars(select(CostUsage))])


@pytest.mark.parametrize("code", [400, 401, 403, 429])
def test_no_hopping_on_invalid_request_permissions_or_quota(ai_case, code):
    ai, client = ai_case
    client.models.generate_content.side_effect = errors.APIError(code, {"error": {"message": "secret"}})
    with pytest.raises(Blocked):
        ai.generate("draft", {}, EmailCopy)
    assert client.models.generate_content.call_count == 1


def test_retry_after_503_persists_global_pause(ai_case, session):
    ai, client = ai_case
    exc = errors.APIError(503, {"error": {"message": "private"}})
    exc.response = httpx.Response(503, headers={"Retry-After": "172800"})
    client.models.generate_content.side_effect = exc
    with pytest.raises(CapacityDeferred):
        ai.generate("draft", {}, EmailCopy)
    assert get_config(session, "gemini_quota_pause")["until"] > (now() + timedelta(hours=47)).isoformat()
    client.models.get.reset_mock()
    with pytest.raises(CapacityDeferred):
        Gemini(ai.settings, ai.config, session, client).generate("draft", {}, EmailCopy)
    client.models.get.assert_not_called()


@pytest.mark.parametrize("change", ["structured", "deprecated", "expired", "context", "output", "method"])
def test_incompatible_primary_uses_reviewed_lower_model(ai_case, change):
    ai, client = ai_case
    cap = ai.policy.capabilities[ai.settings.gemini_model]
    if change == "structured":
        cap.structured_output = False
    if change == "deprecated":
        cap.active = False
    if change == "expired":
        cap.review_expires_on = now().date() - timedelta(days=1)
    if change in {"context", "output", "method"}:
        client.models.get.side_effect = [
            metadata(
                **{
                    "context": {"input_token_limit": 1},
                    "output": {"output_token_limit": 1},
                    "method": {"supported_actions": ["embedContent"]},
                }[change]
            ),
            metadata(),
        ]
    ai.generate("draft", {}, EmailCopy)
    assert ai.model == "gemini-3.6-flash"


def test_37_alias_not_an_independent_fallback(ai_case):
    ai, client = ai_case
    ai.settings.gemini_model = "gemini-3.7-flash"
    ai.generate("draft", {}, EmailCopy)
    assert ai.model == "gemini-3.6-flash"
    assert all(c.kwargs["model"] != "gemini-3.7-flash" for c in client.models.get.call_args_list)


def test_explicit_lower_family_and_pinning(ai_case):
    ai, client = ai_case
    ai.settings.gemini_model = "gemini-2.5-flash-lite"
    ai.policy.automatic_fallback = False
    assert ai.available_model() == "gemini-2.5-flash-lite"
    client.models.generate_content.side_effect = errors.APIError(404, {"error": {}})
    with pytest.raises(CapacityDeferred):
        ai.generate("draft", {}, EmailCopy)
    assert client.models.generate_content.call_count == 1


@pytest.mark.parametrize(
    "case", ["unknown_price", "no_auth", "expired", "paid", "zero_on_paid", "paid_price_free_auth"]
)
def test_no_unapproved_cost(ai_case, case):
    ai, client = ai_case
    ai.policy.automatic_fallback = False
    model = ai.settings.gemini_model
    if case == "unknown_price":
        ai.config.model_prices = {}
    if case == "no_auth":
        ai.policy.usage_authorizations = {}
    if case == "expired":
        ai.policy.usage_authorizations[model].expires_on = now().date() - timedelta(days=1)
    if case in {"paid", "zero_on_paid"}:
        ai.policy.usage_authorizations[model].tier = "paid"
    if case in {"paid", "paid_price_free_auth"}:
        ai.config.model_prices[model]["input_per_million"] = 1
    with pytest.raises(CapacityDeferred):
        ai.generate("draft", {}, EmailCopy)
    client.models.generate_content.assert_not_called()


def test_free_preferred_to_explicit_paid_primary(ai_case):
    ai, client = ai_case
    ai.policy.allow_paid_fallback = True
    ai.policy.usage_authorizations[ai.settings.gemini_model].tier = "paid"
    ai.config.model_prices[ai.settings.gemini_model]["input_per_million"] = 1
    ai.generate("draft", {}, EmailCopy)
    assert ai.model == "gemini-3.6-flash"


def test_validation_exhaustion_never_caches_invalid_output(ai_case, session):
    ai, client = ai_case
    client.models.generate_content.return_value = response('{"subject":"incomplete"}')
    with pytest.raises(CapacityDeferred):
        ai.generate("draft", {}, EmailCopy)
    assert client.models.generate_content.call_count == 9
    assert all(r.units["status"] == "invalid_structured_output" for r in session.scalars(select(CostUsage)))
    assert ai.last_provenance == {}


def test_budget_reservations_survive_unknown_network_outcome(ai_case, session):
    ai, client = ai_case
    ai.config.limits.ai_requests_daily = 2
    client.models.generate_content.side_effect = httpx.ReadTimeout("private")
    with pytest.raises(CapacityDeferred, match="budget"):
        ai.generate("draft", {}, EmailCopy)
    rows = list(session.scalars(select(CostUsage)))
    assert len(rows) == 2 and all(r.actual_usd is None for r in rows)


def test_cooldown_survives_restart(ai_case, session):
    ai, client = ai_case
    set_config(
        session, "gemini_health:gemini-3.8-flash", {"until": (now() + timedelta(minutes=15)).isoformat()}
    )
    ai.generate("draft", {}, EmailCopy)
    assert ai.model == "gemini-3.6-flash"
    assert client.models.get.call_args_list[0].kwargs["model"] == ai.model


@pytest.mark.parametrize("model", ["3.x", "gemini-3.*", "gemini-3.8;echo", "models/gemini-3.8-flash"])
def test_wildcards_and_untrusted_ids_rejected(model):
    with pytest.raises(ValidationError):
        GeminiPolicy(fallback_models=[model])


def test_disabled_generation_no_metadata_or_post(ai_case):
    ai, client = ai_case
    ai.settings.enable_generation = False
    with pytest.raises(Blocked):
        ai.generate("draft", {}, EmailCopy)
    client.models.get.assert_not_called()
    client.models.generate_content.assert_not_called()


def test_provider_safety_refusal_never_switches_models(ai_case):
    ai, client = ai_case
    item = response()
    item.candidates = [SimpleNamespace(finish_reason="SAFETY")]
    client.models.generate_content.return_value = item
    with pytest.raises(Blocked, match="safety"):
        ai.generate("draft", {}, EmailCopy)
    assert client.models.generate_content.call_count == 1


def test_account_metadata_403_does_not_probe_alternatives(ai_case):
    ai, client = ai_case
    client.models.get.side_effect = errors.APIError(403, {"error": {}})
    with pytest.raises(Blocked, match="permission"):
        ai.generate("draft", {}, EmailCopy)
    assert client.models.get.call_count == 1
    client.models.generate_content.assert_not_called()


def test_explicit_zero_requires_real_owner_attestation_default():
    policy = GeminiPolicy()
    assert policy.usage_authorizations == {} and not policy.allow_paid_fallback


def test_unspecified_safety_feedback_is_not_a_refusal(ai_case):
    ai, client = ai_case
    item = response()
    item.prompt_feedback = SimpleNamespace(block_reason="BLOCK_REASON_UNSPECIFIED")
    client.models.generate_content.return_value = item
    assert ai.generate("draft", {}, EmailCopy).subject == "Hi"


def test_zero_prices_on_paid_tier_rejected_even_if_paid_allowed(ai_case):
    ai, client = ai_case
    ai.policy.automatic_fallback = False
    ai.policy.allow_paid_fallback = True
    ai.policy.usage_authorizations[ai.settings.gemini_model].tier = "paid"
    with pytest.raises(CapacityDeferred):
        ai.generate("draft", {}, EmailCopy)
    client.models.generate_content.assert_not_called()
