# Unified workflow and Gemini fallback readiness — 21 October 2026

## Delivered architecture

The feature branch consolidates seven workflow files into one: `.github/workflows/global-website-agent.yml` (**Global Website Agent**). It contains manual diagnostics/discover/daily/replies/followups/report/reconcile/live-smoke and all four original UTC schedules, with one shared concurrency group and no reusable workflow dependency. The entire Python test suite remains. No test workflow was recreated.

Removed from the feature: `_agent-runtime.yml`, `global-daily-pipeline.yml`, `gmail-reply-checker.yml`, `followup-processor.yml`, `weekly-report.yml`, `manual-production-run.yml`, `manual-live-verification.yml`. Existing Python CLI commands, database migrations, discovery budgets, provider integrations and disabled country policies remain. Automatic migration before every Actions command was replaced with read-only schema preflight; actual migrations need separate owner approval.

Side effects are separate: generation, Netlify deployment and Gmail drafts default false, as do sending and routine replies. New gates run before creating draft/deploy pending states. Customer replies remain owner-controlled. A deferred model/budget/permission stage does not advance daily completion; its persisted work resumes on a later authorized tick.

## GitHub deployment status

Registration [PR #8](https://github.com/Nipun33333/GLOBAL-WEBSITE-AGENT/pull/8) was explicitly owner-approved and merged after checks. Registration commit `6b31f4da9c5250fcee7e07807a9bd80508cffd54`; main merge `a1222fb8f791787ff0eea70eff51e9c1258459b6`. Only the new workflow was added to main. Actions lists ID `391903326`, zero runs. The feature adds a further inline revision check before invoking its repository validator.

[PR #6](https://github.com/Nipun33333/GLOBAL-WEBSITE-AGENT/pull/6) remains open and unmerged on `feature/free-overture-discovery`. Main has eight definitions temporarily, including the registered replacement; the feature's final tree has one. Both automation activation variables are absent/false, so no duplicate automatic production execution is enabled. Only a separately approved PR #6 merge retires old definitions on main. [Migration plan and audited responsibility mapping](WORKFLOW_MIGRATION.md).

No workflow was dispatched, no secret value retrieved/copied, no database record or schema changed, no model generation, deployment, Gmail draft/send, billing activation or Base44 access occurred in this implementation task.

## Gemini fallback

Public documentation supports the default exact candidate order: 3.8 Flash → 3.6 Flash → 3.5 Flash-Lite → 2.5 Flash → 2.5 Flash-Lite. 3.7 Flash routes to 3.8 and is excluded as an independent fallback. 2.5 models require existing account eligibility. The reserved Argon model is not silently added. The catalog, token constraints, dates and official references are documented in [GEMINI_FALLBACK.md](GEMINI_FALLBACK.md).

Account-verified models: **none**. Account generation/free-tier access: **CONFIGURED BUT UNTESTED**. Authorization/pricing maps remain empty, so actual generation is **BLOCKED**. Default allow_paid_fallback is false; missing prices or account-tier review cannot imply free use.

Automatic model selection and failures: **VERIFIED OFFLINE ONLY**. Tests cover exact-ID/pinning/free preference, missing capability/token limits, deprecated/unreviewed IDs, lower-family choices, 404/5xx/network failures, jitter/retry bounds, persistent cooldown, quota/Retry-After pause, no 400/401/403 or safety bypass, unknown/paid pricing, malformed output, ledger reservations and cached provenance. Pydantic/site quotation/render/deployment checks remain mandatory. Metadata success does not prove real structured generation.

## Preserved integrations and actual live evidence

Supabase schema, migrations, session locks, unique records, discovery checkpoints, exclusions and history are preserved; the live database is **CONFIGURED BUT UNTESTED**. The real PostgreSQL test is skipped without a separately authorized test database. No migration was applied.

Overture AWS/Azure, validated cache, authorized OSM architecture, expansion/recovery and strict website verification are preserved. Prior anonymous probes returned the same 120 source candidates on both mirrors; independently verified businesses and inserts were zero. Those earlier results remain [historical evidence](READINESS_BEFORE_UNIFICATION.md), not new live tests of this workflow. OSM remains **BLOCKED** pending actual authorization/source staging.

Netlify and Gmail account access are **CONFIGURED BUT UNTESTED**. Existing immutable-preview validation, ambiguous POST reconciliation, duplicate-mail controls, opt-outs and followup rules passed offline regression tests. Base44 import/suppression controls remain **VERIFIED OFFLINE ONLY**; current history and exclusive audience evidence still require owner input. Base44 was untouched.

## Validation

Latest full suite: **279 passed, 0 failed, 1 skipped; 81% coverage in 55.26 seconds**. Real local Chromium mobile/desktop fixture rendering and Parquet/XML parsing ran. Provider/account responses and fallback faults used mocks. The skip is the real PostgreSQL migration/cross-runner lock test. Coverage excludes child-worker statements and the standalone master script (its decision/execution paths have direct tests).

Ruff lint/format passed. actionlint 1.7.12 passed (official release archive SHA-256 checked). YAML parsing, unique cron mapping, owner/event/SHA/rerun gates, sole workflow inventory, per-capability permissions and absence of implicit migrations passed. Locked runtime dependency audit found no known vulnerabilities; no dependencies were added or lockfile changed.

```bash
uv run pytest -q --cov=website_agent --cov-report=term --junitxml=artifacts/unified-fallback-tests.xml
uv run ruff check src scripts tests
uv run ruff format --check src scripts tests
actionlint .github/workflows/global-website-agent.yml
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file artifacts/audit-requirements.txt
uv run pip-audit -r artifacts/audit-requirements.txt --no-deps --disable-pip
```

## One owner-action checklist

1. Registration is complete; no further registration merge is needed. Keep PR #6 open until you separately approve the implementation. Keep AUTOMATION_ENABLED, UNIFIED_WORKFLOW_ENABLED, ENABLE_SENDING and routine replies disabled.
2. Before any live run, confirm included Actions capacity (up to 45 Linux minutes plus small one-day artifacts), provider usage and the intended Supabase destination/TLS/schema/backup. The existing token cannot establish account-wide free quota; do not broaden it or activate billing. Review in GitHub Billing and licensing, Supabase Connect/Usage, AI Studio usage and Netlify usage. This review changes no data.
3. Review PR #6's current full SHA and explicitly launch **Global Website Agent → diagnostics** on the feature branch, both review checkboxes true only after step 2, no write phrase or capability permissions. This is separate runtime approval. No diagnostic run has been authorized by merely merging registration.
4. If diagnostics pass, approve US discovery writes separately using APPROVE_US_DISCOVERY_WRITES during the configured local window. Generation/deployment/drafts remain independent and require real account-tier/pricing review and specific approvals; these operations can consume quota or create external resources. Resolve only actual credential errors through the provider and existing GitHub secret settings, never by revealing values here.
5. After live verification and separate approval, merge PR #6 and verify main has exactly one workflow. Manual operation does not require scheduled activation. To authorize schedules later, review and configure only the needed SCHEDULED_MODES and per-capability variables following [UNIFIED_WORKFLOW.md](UNIFIED_WORKFLOW.md). Never enable unified schedules while legacy definitions remain. Sending additionally requires history/audience, recipient and country/legal review and a separate sending instruction.

## Operational verdict

The single-workflow implementation and bounded Gemini fallback are **VERIFIED OFFLINE ONLY**. Workflow registration is **VERIFIED LIVE** through GitHub metadata. Persisted discovery, live preview generation/deployment and owner-draft preparation remain **BLOCKED** pending the corresponding account checks and explicit runtime approvals. No integration is claimed live-operational simply because its secret exists.
