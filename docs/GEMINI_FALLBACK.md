# Gemini selection, authorization and recovery

## Verified public catalog (21 October 2026)

The default exact-ID preference is `gemini-3.8-flash`, then `gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-2.5-flash`, `gemini-2.5-flash-lite`. Google documents structured outputs and input/output limits of 1,048,576 / 65,536 for these models. The application caps output at 8,192 and conservatively bounds input using UTF-8 bytes including system instructions and JSON Schema. Every chosen model must also advertise generateContent and sufficient limits through account metadata.

Official sources: [3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash), [3.6 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash), [3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite), [2.5 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash), [2.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite), [structured outputs](https://ai.google.dev/gemini-api/docs/structured-output), [model metadata](https://ai.google.dev/api/models).

The current [lifecycle documentation](https://ai.google.dev/gemini-api/docs/deprecations) says 3.7 Flash routes to 3.8 Flash; 3.5 Flash routes to 3.6 Flash. They are intentionally excluded as independent recovery alternatives. Gemini 2.5 access is restricted to existing users; inclusion in the catalog does not establish eligibility. Unknown IDs, wildcard IDs, inactive/expired reviews and missing required capabilities fail closed. Public capability reviews expire on 19 January 2027 and require renewed official review. No arbitrary family wildcard is ever sent to Google.

**Account-verified models: none in this task. Actual generations: zero.** Existing GitHub Secrets were not retrieved. Authorized manual diagnostics check configured exact IDs with bounded metadata GETs (at most eight), including the reserved advanced model, without generation or database model-state writes. A successful GET is not proof of structured generation or free allowance. Argon remains reserved configuration, is not in the default fallback catalog, and has no free tier.

## Configuration and pinning

`config/settings.yml` has a Pydantic-validated `gemini` policy:

```yaml
gemini:
  automatic_fallback: true
  prefer_free_tier: true
  allow_paid_fallback: false
  max_model_attempts: 3
  retries_per_model: 2
  cooldown_seconds: 900
  max_output_tokens: 8192
  fallback_models: [gemini-3.6-flash, gemini-3.5-flash-lite, gemini-2.5-flash, gemini-2.5-flash-lite]
  usage_authorizations: {}
model_prices: {}
```

`GEMINI_MODEL` pins the preferred primary. Set `automatic_fallback: false` for strict single-model operation. A nonempty comma-separated `GEMINI_FALLBACK_MODELS` replaces the YAML fallback order. Stable order is retained within a tier; confirmed free authorizations are preferred over paid/unknown authorizations. Metadata inspection is capped at eight candidates per call; at most three compatible authorized models can be generated against by default. Skipped unavailable/ineligible models do not consume generation attempts. Earlier 2.5 models can be explicitly selected when their existing account access is verified.

The capability catalog lives in `GeminiPolicy.capabilities` and may be overridden with exact IDs, structured_output, input_tokens, output_tokens, active, official review_reference and review_expires_on. This is an explicit reviewed configuration, not a claim that the model-list API exposes structured-output or pricing eligibility. Adding a model requires current official documentation and an authorized account check; expired or unknown support blocks it.

## Free-first budget enforcement

[Google pricing](https://ai.google.dev/gemini-api/docs/pricing) describes limited free tiers, not unlimited usage or this account's eligibility. Before generation, the owner must review actual account usage in AI Studio and supply each model's `usage_authorizations` entry with `tier: free` or `paid`, a non-secret `review_reference`, and `expires_on`, plus verified `model_prices` input_per_million/output_per_million. Do not record secrets or customer information in review references.

The shipped authorization and pricing maps are empty: generation is blocked until reviewed. Free authorization requires both prices explicitly zero. Paid authorization is rejected unless allow_paid_fallback is separately approved and true. Zero prices on an account configured as paid do not count as a free authorization. No prices are inferred from API success, and no billing is enabled. Metadata alone cannot independently measure remaining free quota.

The existing daily request and dollar limits remain global across retries/models. Each attempt commits a conservative cost reservation before the request; ambiguous interruptions retain it. Returned prompt/output/thinking usage updates actual cost. Failed requests still consume the request budget. Budget exhaustion defers work without clearing pending prospect state.

## Fallback and refusal rules

- Missing model (404), missing reviewed capability/context/output limit, expired/deprecated catalog entries: try the next eligible exact ID.
- Generation 500/502/503/504 and transport failures: at most two retries with exponential backoff and jitter, then a model cooldown and another eligible model. Each attempt remains charged/reserved in the ledger. Metadata failures are bounded and saved separately.
- 429 or any Retry-After response: persist an account-wide pause, never rotate models to escape it. A 429 pauses until at least next UTC day; longer Retry-After wins. Header dates/seconds are honored.
- 400/401/403: stop; no credential, permission, billing or malformed-request bypass. Safety/recitation/prohibited-content refusals also stop without fallback.
- Invalid/incomplete structured output: reject, retry within the same bounded attempt budget and then consider another compatible model. Pydantic validation, source quotation checks, safe rendering and preview validation remain mandatory. No invalid result becomes a deployed site or sent proposal.

`configuration` stores per-model sanitized health reasons/cooldowns, account pause, validated cache and provenance. `cost_usage` stores every attempted model and usage/reservation. Site/audit/message metadata links successful generation provenance, including requested exact ID, provider-reported model version when available, cache key and ledger ID. Model aliases can change provider versions, so reported versions are retained separately. Cached output is revalidated; schema/system changes invalidate its key. Unknown calls are never described as successful generations.

Model-based stages deferred by quota/authorization keep daily work resumable and return deferred status rather than advancing the daily completion checkpoint. Gmail/Netlify POST reconciliation remains separate: model switching cannot authorize repeated deployments or sends.
