# Final engineering and operational readiness — 21 October 2026

**Archived before workflow consolidation and Gemini fallback.** See [current readiness](FINAL_READINESS.md) for the latest implementation and validation.

Work was limited to `Nipun33333/GLOBAL-WEBSITE-AGENT`. No other system was accessed. No credential value was retrieved, exported, printed or copied. No account diagnostic, production database write, migration, Gmail draft/send, model generation, deployment or billing activation was performed. Public dataset reads and offline tests are explicitly distinguished below.

## 1. GitHub

- Registration [PR #7](https://github.com/Nipun33333/GLOBAL-WEBSITE-AGENT/pull/7): **MERGED**, following the owner's conditional authorization and passing safety review. Merge commit `b5de26dcba3314d6b4b5980d082fcceaa7dee017`; original registration commit `08f32beb5d397b74e98f9ed73b6b44fd7a55ffd9`. The registration diff contained only `.github/workflows/manual-live-verification.yml` (97 lines).
- Actions now lists **Manual live verification**, ID `391552084`, with **zero runs**. Its Git blob matches the reviewed feature workflow.
- Feature [PR #6](https://github.com/Nipun33333/GLOBAL-WEBSITE-AGENT/pull/6): open, unmerged, auto-merge disabled. Continuing work is on `feature/free-overture-discovery`; its current head SHA is shown on the PR.
- All six original production workflows match pre-registration main `369c5328d4df5154cdb5b32586c82cb85c536355`: `_agent-runtime.yml`, `global-daily-pipeline.yml`, `gmail-reply-checker.yml`, `followup-processor.yml`, `weekly-report.yml`, `manual-production-run.yml`. Schedules and their inputs remain unchanged. `tests.yml` remains absent.
- The repository/environment have no overrides for AUTOMATION_ENABLED, ENABLE_SENDING or ENABLE_ROUTINE_REPLIES; existing false defaults apply. The manual workflow hardcodes all three false. All 11 country policies remain disabled.

Current engineering changes are confined to AI model/price validation; Gmail send-disable defense; parent-domain suppression; owner-handled reply behavior; preview asset validation; optional Overpass DNS pinning; read-only schema and sanitized diagnostics; related regression tests and documentation. No settings, lockfile, migration SQL or production workflow was changed by this follow-up.

Files changed in this follow-up (22 total):

- Application (9): `src/website_agent/ai.py`, `compliance.py`, `discovery_datasets.py`, `discovery_support.py`, `gmail.py`, `hosting.py`, `live_verification.py`, `pipeline.py`, `security.py`.
- Tests (4): `tests/test_integrations.py`, `test_live_verification.py`, `test_recovery.py`, `test_readiness_security.py`.
- Documentation (9): `README.md`, `SETUP_GUIDE.md`, `DEPLOYMENT_GUIDE.md`, `docs/DISCOVERY.md`, `HANDOVER.md`, `LIMITATIONS.md`, `LIVE_READINESS_REPORT.md`, `MANUAL_LIVE_VERIFICATION.md`, `FINAL_READINESS.md`.


## 2. Business discovery

Both probes used the unchanged release `2026-09-23.1`, US/New York/salons and bbox `-74.03 40.70 -73.95 40.78`:

```bash
uv run python scripts/probe_discovery.py --country US --city "New York" --niche salons --bbox -74.03 40.70 -73.95 40.78
uv run python scripts/probe_discovery.py --country US --city "New York" --niche salons --endpoint azure --bbox -74.03 40.70 -73.95 40.78
```

| Measurement | AWS | Azure |
|---|---:|---:|
| Dataset files / row groups read | 1 / 3 | 1 / 3 |
| Rows inspected | 48,474 | 48,474 |
| Candidates returned | 120 | 120 |
| Requests | 28 | 28 |
| Payload bytes | 8,227,416 | 8,227,416 |
| Elapsed seconds | 150.270 | 151.382 |
| Independently verified websites | 0 | 0 |
| PostgreSQL prospect inserts | 0 | 0 |
| Outcome | dataset_probe_only | dataset_probe_only |

The two source-ID sets are identical: **120 distinct source candidates, not 240 leads**. Each contained 113 exact New York locality labels and seven other locality labels, illustrating the need for the unchanged independent geography/identity checks. Categories: 67 hair salons, 51 beauty salons, one blow-dry/blow-out service, one hair stylist. Cursor: file 0 / group 12 / row 7020, not exhausted. These are live source reads; site visits, admission rejections, duplicate/suppression checks and database checkpoint writes were not performed by these probes. Earlier 53.334-second AWS results remain historical and were not substituted for the new slower measurement.

AWS retrieval and Azure decoding: **VERIFIED LIVE** for this subset. Actual outage-triggered mirror switching, shared 429/Retry-After circuits, validated cache, geographic/category/city expansion, persistent recovery, atomic admissions and crash rollback: **VERIFIED OFFLINE ONLY**. No other country is claimed live-verified. STAC remains a shared metadata dependency of both mirrors.

OSM: **BLOCKED**. No regional extract, reviewed license-obligation attestation or authorized private/contracted endpoint is configured. The previously inspected Geofabrik New York PBF was 474 MB, beyond current budgets and incompatible with the XML-node reader. Rechecking its web page timed out during this review; no data was downloaded or permission inferred. A bounded owner-reviewed XML extract plus explicit runner staging remains necessary; ignored local files do not appear on hosted runners. A new extractor cannot establish ODbL obligations, staging permission or included compute by itself, so no automatic downloader or authorization flag was added. See [OSM licensing](https://www.openstreetmap.org/copyright) and [existing setup](DISCOVERY.md).

The optional Overpass implementation previously checked DNS before an HTTP client resolved it again. It now uses the DNS-pinned public client, rejects redirects, preserves byte/request limits and bounded backoff, and honors provider pauses. This fix is offline-tested; it does not authorize an endpoint or enable OSM.

## 3. Database

Supabase connection, production schema, capacity, current history and checkpoints: **CONFIGURED BUT UNTESTED**. Existing GitHub secret names are confirmed, not their values or validity. No local credential recreation is needed.

Diagnostics enforce TLS certificate/hostname checking, direct/session-mode port 5432, read-only transactions, rollback and statement/connect timeouts. They now inspect required columns/nullability, primary/foreign/unique constraints and indexes in addition to migration checksums, required tables and the existing 400 MiB size threshold. Missing/drifted schema blocks discovery; diagnostics do not repair it. Owner confirmation still establishes the intended project: two identically provisioned databases cannot be distinguished by schema checks alone. Included Supabase storage/egress and a provider-specific CA remain account prerequisites.

`001_initial.sql` was reviewed: fourteen application tables plus the migration ledger, unique domain/provider/message keys, foreign keys and indexes; no DROP, TRUNCATE or DELETE statements. Existing migration checksums remain unchanged. Any real schema preparation needs a verified restorable backup and separate owner approval. Session advisory locks and lock-loss safeguards remain in place. SQLite uniqueness/rollback/schema-reflection tests passed; the current real PostgreSQL integration test was **skipped**, because no separately authorized TEST_DATABASE_URL was available. Historical CI PostgreSQL evidence is retained in HANDOVER.md and is not current Supabase verification.

Database-write approval: **BLOCKED** pending separate explicit `APPROVE_US_DISCOVERY_WRITES` approval after successful diagnostics. No approval was invented or submitted.

## 4. Gemini

The official documentation currently lists both [gemini-3.8-flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash) and [gemini-4-argon](https://ai.google.dev/gemini-api/docs/models/gemini-4-argon), including structured outputs. Flash documents 1,048,576 input tokens and 65,536 output tokens; the application's 8,192-token output cap is smaller. These public specifications do not prove account access or a successful schema-generation request.

Account metadata and generation: **CONFIGURED BUT UNTESTED**. Structured-output/cache/quota behavior: **VERIFIED OFFLINE ONLY**. Primary/fallback model checks now reject missing generation capability rather than assuming it. Nonfinite/negative token prices cannot bypass the cost budget. Diagnostic reports include bounded token-limit integers when returned; failed API calls expose only approved error codes, never descriptions or arbitrary bodies.

[Official pricing](https://ai.google.dev/gemini-api/docs/pricing) lists limited free standard Flash use; Argon has no free tier. No model was silently substituted, and no paid fallback was enabled. `model_prices: {}` remains unchanged and blocks generation until actual account eligibility/prices are reviewed. No neutral generation test was authorized or performed.

## 5. Netlify and previews

Account/site access, included quotas and actual deployment: **CONFIGURED BUT UNTESTED**. No deployment was attempted. Existing immutable draft-deploy URL checks, uncertain-POST reconciliation and persistence were reviewed and exercised with mocked APIs.

Preview rendering: **VERIFIED OFFLINE ONLY**, including real local Chromium at 375px and 1280px, navigation, overflow checks and error monitoring. Preview verification now fetches each asset once, validates the exact reviewed interaction script before browser execution and blocks other browser network requests. Generated facts remain source quotations, with an explicit independent/unofficial disclaimer, noindex, no collection form or payment flow. Mock design fixtures do not prove live Gemini output quality or every real-device accessibility requirement. A neutral deployment requires separate approval and verified included usage.

## 6. Gmail and owner conversations

OAuth refresh, mailbox identity and returned scopes: **CONFIGURED BUT UNTESTED**. Required scopes remain gmail.compose and gmail.readonly. An absent scope response is not treated as confirmed permission. New diagnostics preserve known codes such as `invalid_grant` or `invalid_client` while discarding provider descriptions and tokens; no actual authorization failure is claimed before a live diagnostic.

MIME/draft behavior, idempotency, ambiguous sends, opt-outs, DSNs and thread handling: **VERIFIED OFFLINE ONLY**. `Gmail.send` now refuses a disabled sending flag before refreshing a token or making a POST. Production and test sending remain distinct; only mock fixtures explicitly enable the flag.

With routine replies disabled, the pipeline now creates no automatic acknowledgment drafts and makes no acknowledgment-generation call. Interested replies remain recorded with owner-action notifications; follow-ups stop after a reply/opt-out. The owner handles conversations. **Zero real emails sent and zero real drafts created.**

Google's external OAuth Testing status normally limits refresh tokens for Gmail scopes to seven days. Publishing, verification and reauthorization requirements must be resolved in the account, not bypassed; publishing is not a guarantee of permanent tokens. See [Google's token-expiration guidance](https://developers.google.com/identity/protocols/oauth2#expiration).

## 7. Historical suppression safeguards

History imports, domain/mailbox exclusions, prior-contact checks and unsubscribe propagation through imports: **VERIFIED OFFLINE ONLY**. A newly found gap allowed pre-send eligibility to consider only the exact domain; it now also checks parent-domain suppressions, preventing a discovered subdomain from escaping a domain opt-out.

At the time of this archived review, full mailbox history and applicable sending permissions were unverified. Discovery checks all known suppressions; unknown external history does not grant permission to contact anyone. Current code relies on Gmail live prior-contact checks and jurisdiction-specific legal evidence, not an external-platform partition.

## 8. Automation and permissions

Scheduling, country/local windows, fair rotation, independent queued stages and recovery: **VERIFIED OFFLINE ONLY**. Existing scheduled production definitions are unchanged and inactive through their false defaults. Registered manual workflow visibility: **VERIFIED LIVE** through GitHub metadata, not a runtime execution.

Diagnostics, discovery writes, generation, deployment, draft creation, sending and reply monitoring remain separate authorization decisions. A discovery approval cannot enable sending. The current US location uses New York's weekday/holiday-aware 08:00–20:00 research window; discovery rechecks it at runtime. No daily pipeline was used as a substitute.

## 9. Testing and security

Latest full suite: **194 passed, 0 failed, 1 skipped; 81% coverage in 34.25 seconds**, Python 3.13.14. The single skip is the real PostgreSQL migration/multi-session lock test. Real local Chromium and Parquet/XML parsing ran; external account APIs, production database and outage scenarios use fixtures. Worker subprocess coverage is not included in parent-process coverage.

```bash
uv run pytest -q --cov=website_agent --cov-report=term --junitxml=artifacts/final-readiness-tests.xml
uv run ruff check src scripts tests
uv run ruff format --check src scripts tests
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file artifacts/audit-requirements.txt
uv run pip-audit -r artifacts/audit-requirements.txt --no-deps --disable-pip
git diff --check
```

Ruff/formatting and dependency audit passed; no known locked runtime vulnerabilities found. All seven workflow YAML files and local reusable-workflow references passed validation; production Git blobs are unchanged. No test workflow was recreated. Security regression coverage includes disabled direct sends, parent-domain opt-outs, owner-handled replies, untrusted preview scripts, model-capability/price failures, schema drift, safe provider errors and DNS-pinned configured endpoints.

Review also covered existing SQL parameterization, advisory-lock ownership, fixed API origins, DNS/redirect/private-address checks, range validation, Parquet decoder bounds, OSM XML/path/hash validation, cache signatures, cursor/transaction recovery, AI prompt/data separation, HTML escaping, Gmail POST reconciliation and artifact boundaries. These are bounded engineering checks, not a claim of exhaustive penetration testing or provider/legal certification. Existing secret names were validated without retrieving values; no environment dump was created.

## 10. One consolidated owner-action checklist

1. **Confirm included usage before any Actions dispatch.** Open [GitHub Settings → Billing and licensing](https://github.com/settings/billing), inspect Actions usage, artifact storage and Budgets/alerts. Ensure at least 15 included standard Linux minutes plus small one-day artifact headroom, considering concurrent account use, and confirm no paid overage is permitted. The billing API returned 404/insufficient existing scope; this repository's 20 artifacts total 566,380 bytes, which does not establish account-wide remaining allowance. This review is read-only and costs nothing; do not raise budgets or activate billing. Check the existing Supabase Usage, Google AI Studio project Usage/rate limits and Netlify team Usage/billing pages as well. A secret's existence is not proof of free quota.
2. **Confirm the intended database.** In the existing Supabase project's Connect dialog and database settings, confirm this agent's dedicated project and direct/session-mode connection on 5432, capacity, TLS trust and backups. Do not reveal or copy the password here. Confirm the originally stored DATABASE_URL belongs to this project; if that is unknown, do not attest to the destination. Review only: no data change or cost. Missing schema requires a separately approved migration after a verified backup; no such approval is included here.
3. **Explicitly approve/run diagnostics only.** Review the current PR #6 head (`gh pr view 6 --repo Nipun33333/GLOBAL-WEBSITE-AGENT --json headRefOid --jq .headRefOid`). Open Actions → Manual live verification → Run workflow as Nipun33333. Select feature/free-overture-discovery, mode diagnostics, the reviewed full feature SHA, and set the two review booleans true only after items 1–2 are satisfied. Leave write_approval empty. This is the required separate explicit diagnostic approval. It reads metadata, refreshes OAuth and writes only sanitized reports; it does not change database records or mailboxes. It consumes Actions allowance and limited provider requests, so no zero-cost claim is made until quotas are confirmed. Re-run jobs is deliberately blocked; use a fresh reviewed dispatch. Inspect the summary and download its one-day artifact promptly.
4. **Resolve only actual diagnostic failures.** For DATABASE_URL failures, use the same Supabase project's connection/TLS settings. For GEMINI_API_KEY errors, review the existing Google AI Studio project key restrictions and access; do not enable paid billing. For NETLIFY_AUTH_TOKEN/NETLIFY_SITE_ID, review the existing Netlify user application token and site configuration. For Gmail invalid_grant/invalid_client, open Google Cloud → Google Auth Platform → Audience/Clients/Data Access, resolve publishing/test-user/scope issues, then securely reauthorize with the existing helper and update only the affected repository secret under Settings → Secrets and variables → Actions. Never paste values into chat. These are conditional account changes, not requests to recreate all credentials; rotation/reauthorization requires owner action and should not add paid services.
5. **Approve discovery writes separately, after diagnostics.** Confirm the US local research window, included capacity and imported exclusions. Only then explicitly authorize `APPROVE_US_DISCOVERY_WRITES` in a new discover dispatch using the reviewed SHA. This writes verified prospects, provenance and checkpoint/run records; it consumes included runner/database/network resources. No write test has been authorized or run. Inspect sanitized inserts/rejections/fallbacks/retry time and, through authorized read-only database inspection, persisted source evidence and checkpoints before retrying. Do not clear suppressions or reset uncertain outcomes.
6. **Before later previews/drafts/outreach:** confirm free account generation/deployment allowances and separately approve one neutral generation/deployment and, if desired, one owner-addressed draft. These create external resources and may incur charges if allowances are insufficient; keep them blocked until verified. For OSM, review ODbL/provider obligations and bounded file staging before enabling it. For any future prospect sending, complete sender/country/legal review and confirm Gmail Sent/Inbox plus suppression checks, and issue a separate sending instruction. These actions are not prerequisites to finish this offline engineering work and are not authorized by merging PR #7. Keep PR #6 unmerged until you separately approve it.

## 11. Independent final verdict

| Capability | Status | Operational verdict |
|---|---|---|
| Public AWS/Azure candidate retrieval | VERIFIED LIVE | Bounded subset retrieval works; not verified-lead admission |
| Persisted discovery-only operation | BLOCKED | Awaiting destination/quotas, diagnostics and explicit write approval |
| Website auditing and qualified selection | VERIFIED OFFLINE ONLY | Live site identity and admission still untested |
| Non-sending website generation | BLOCKED | Account metadata/free tier/prices and generation approval outstanding |
| Netlify demo deployment | BLOCKED | Account access/free quota and separate deployment approval outstanding |
| Owner-reviewed Gmail draft creation | BLOCKED | OAuth/scopes/identity and separate draft approval outstanding |
| Future legally authorized outreach | BLOCKED | Sending disabled in this archived review; account, legal, and Gmail history verification outstanding |

The project is prepared for an owner-reviewed diagnostics run once its prerequisites are confirmed. It is not yet ready to claim safe persisted discovery, live preview generation/deployment, owner draft creation or automated emailing. Registration and all independently executable engineering/testing work in this review are complete; no unavailable live test is presented as a success.
