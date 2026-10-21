# Implementation handover — updated 21 October 2026

**Current unified-workflow update:** PR #8 registers Global Website Agent; PR #6 contains the single-workflow implementation and remains unmerged. All automation/sending controls remain disabled. Gemini has bounded exact-model fallback with empty account authorization/pricing maps, so live generation remains blocked. See [current readiness](FINAL_READINESS.md), [control panel](UNIFIED_WORKFLOW.md), [Gemini policy](GEMINI_FALLBACK.md) and [migration sequence](WORKFLOW_MIGRATION.md). Older workflow inventories and validation counts below are historical, not current activation instructions.


Implemented and committed in **Nipun33333/GLOBAL-WEBSITE-AGENT** only. The Base44 system and other repositories were not accessed or modified. No live business emails were sent, no real deployment URLs were invented, and no paid resources or billing were activated.

The current feature-branch follow-up is documented in [LIVE_READINESS_REPORT.md](LIVE_READINESS_REPORT.md): spatial STAC selection, real bounded Parquet reads, recovery fixes and current validation. The historical results below remain historical. PR #6 remains unmerged.

## Current follow-up

Registration PR #7 is merged; the manual workflow is registered with zero live runs. All 12 required secret names are present at repository scope, and DISCOVERY_API_KEY is optional. No credentials need to be recreated locally. See [FINAL_READINESS.md](FINAL_READINESS.md) for current tests, public retrieval evidence, security fixes and owner actions. PR #6 remains open. The older integration/setup statements below describe the historical delivery, not missing GitHub Secrets today.

## Historical delivery status

The application, migration, integration adapters, configuration, security controls, tests and GitHub Actions workflows are implemented. **It is not yet verified as production-operational.** Service credentials, legal/provider authorization and Base44 history were not supplied. The defaults remain draft-only, and scheduled runtime jobs are gated by `AUTOMATION_ENABLED`.

## Historical verification record

These results record implementation verification before automated test, lint and dependency-audit workflows were removed. Tests and development tools remain available locally.

- Local Python 3.13: **59 passed, 1 skipped**. The local skip is the real PostgreSQL integration test because no PostgreSQL service is installed locally. Chromium desktop/mobile verification actually ran.
- GitHub Actions verification of final code revision `1c0a803bbc0c26736979260556786c32f7482dc8`: **60 passed in 8.88 seconds, 77% coverage**, including real PostgreSQL migrations, competing-session lock exclusion and lock-loss detection, Chromium, terminal opt-out status, subject-only unsubscribe and report accuracy. [Successful CI run](https://github.com/Nipun33333/GLOBAL-WEBSITE-AGENT/actions/runs/39311419759). This handover is a subsequent documentation-only commit.
- Ruff lint and formatting: passed.
- Dependency advisory audit: **No known vulnerabilities found** in the locked runtime dependencies. This is an advisory scan, not a security certification.
- Actual credentialed discovery, Gemini generation/model access, Netlify deployment, Gmail OAuth/draft/sending, and production database access: **BLOCKED / NOT RUN**, not passed.
- Manual production and scheduled service runs with real integrations: **BLOCKED** by the missing configuration. Production workflow definitions are present.

## Integration implementation

| Integration | Implemented and tested behavior | Live account status |
|---|---|---|
| PostgreSQL / Supabase-compatible | Schema migration, constraints, state persistence, global advisory locks and recovery | Real PostgreSQL verified in CI; production database missing |
| Official Google GenAI SDK | Model metadata checks, explicit fallback, Pydantic outputs, cache, retries, quota pause and token cost ledger | API key/model access/prices unverified |
| Brave Search / licensed JSON provider | Country-aware API discovery, provider rights gate, stable identifiers and dedupe | Key and reviewed usage/storage rights missing |
| Public website research | DNS-pinned requests, robots, bounded link sampling, static audit evidence and observed business mailboxes | Tested with fixtures; no live prospect research performed |
| Website generation | Complete responsive HTML/CSS/JS, source-quotation validation, safe rendering, RTL/UI localization | Source and real Chromium tested; live Gemini generation blocked |
| Netlify | ZIP draft deployment, provider ID polling, immutable HTTPS URLs, reconciliation, HTML/assets/mobile verification | Existing project/token missing; no real preview deployment claimed |
| Gmail | Official REST API, OAuth refresh, identity check, MIME drafts, draft-consuming sends, sent verification, pagination, reply/DSN processing | OAuth credentials and sender details missing |
| Outreach controls | Consent/policy/history checks, suppressions, Base44 audience exclusion, budgets, idempotency, business-day followups | Defaults deny sending; policies and imports unvalidated |
| GitHub Actions | Five production entry workflows plus shared runtime | Production automation gated |

## Exact GitHub Secrets

```text
DATABASE_URL
GEMINI_API_KEY
DISCOVERY_API_KEY
NETLIFY_AUTH_TOKEN
NETLIFY_SITE_ID
GMAIL_CLIENT_ID
GMAIL_CLIENT_SECRET
GMAIL_REFRESH_TOKEN
SENDER_NAME
SENDER_EMAIL
REPLY_TO
SENDER_POSTAL_ADDRESS
OWNER_EMAIL
```

Add secrets to this repository or its `agent-runtime` environment. Do not put credentials into chat, source files, issues or logs. Variables are `AUTOMATION_ENABLED`, `ENABLE_SENDING`, `ENABLE_ROUTINE_REPLIES`, `GEMINI_MODEL`, `GEMINI_ADVANCED_MODEL`, and `GEMINI_FALLBACK_MODELS`. Configuration defaults and exact setup steps are in [SETUP_GUIDE.md](../SETUP_GUIDE.md).

The requested model default is `gemini-3.8-flash`; `gemini-4-argon` is an optional explicitly selected model. Neither is claimed to be accessible to your account. Model pricing must be entered from verified current account information. A missing model or unconfigured price fails closed.

## Schedules and manual execution

| Workflow | Schedule / trigger |
|---|---|
| `global-daily-pipeline.yml` | Hourly at minute 17 UTC; durable daily checkpoint, configured local due hour, fair country-window deferral |
| `gmail-reply-checker.yml` | Minutes 7 and 37 UTC |
| `followup-processor.yml` | Hourly at minute 42 UTC |
| `weekly-report.yml` | Monday at 04:23 UTC |
| `manual-production-run.yml` | `workflow_dispatch` |

`config/settings.yml` defaults to a daily eligibility time of 03:00 UTC, research windows of 08:00–20:00 local time, eleven countries and twelve niches. All sending policies remain disabled with default contact windows of 09:00–17:00. Country/city/niche lists and global limits are configurable. Default capacity is 30 discoveries / 10 inspections / 5 selections per run, 2 new previews and 2 new outreach messages per UTC day, and at most 2 followups after at least 5 business days each.

For a manual run, use **Actions → Manual Production Run → Run workflow → command `daily` → production unchecked**. Set a country code or leave empty for worldwide rotation. After credentials are configured, `live-smoke` verifies actual generation/deployment/browser behavior and creates an internal draft to the owner; it cannot send. Production needs both the explicit production switch and `ENABLE_SENDING=true`, plus all policy/history/identity checks.

## Hosting configuration

Use one existing dedicated Netlify project. Each prospect version is a real draft deployment within that project, with a unique immutable provider-returned HTTPS URL. Source and metadata persist in PostgreSQL. The adapter verifies HTML content type, lack of download disposition, concept identity, assets and Chromium presentation before allowing drafts/sends containing the URL. Configure account retention and hosting quotas yourself; the application does not provision projects, buy capacity or change plans.

## Activation checklist and blockers

- [ ] Dedicated production PostgreSQL configured, migrated, restricted and backed up; direct/session-mode connection used.
- [ ] Gemini key, selected model access and current prices verified.
- [ ] Overture source/license notices reviewed and real discovery-only persistence verified; optional OSM source separately configured and authorized. No search key is required in open_data mode.
- [ ] Dedicated Netlify project/token configured and real HTTPS preview smoke test passed.
- [ ] Gmail OAuth refresh and sender identity verified; real postal address/reply-to configured.
- [ ] Existing Base44 contact/thread/opt-out exports imported and validated against Gmail.
- [ ] Exclusive audience assignment documented so the running Base44 agent cannot contact the same prospects.
- [ ] Current country policies and prospect-specific legal-basis/contact evidence reviewed and imported.
- [ ] Draft-only real pipeline, replies, opt-outs and followup timing verified.
- [ ] GitHub scheduled/manual runtime configured and tested; account quotas and owner notification settings reviewed.
- [ ] Only then activate production sending with both required controls.

Full operational instructions: [DEPLOYMENT_GUIDE.md](../DEPLOYMENT_GUIDE.md). Full readiness checklist and limitations: [docs/LIMITATIONS.md](LIMITATIONS.md).

## Material limits

Static website scoring is not Lighthouse or an exhaustive accessibility/visual audit. Facts remain source quotations and safe templates constrain generated code; arbitrary model JavaScript is intentionally excluded. Email catalog languages are English, Hindi, Arabic, German, French and Japanese; other languages fall back to English catalog email text. There is no admin web dashboard. Owner notifications are stored in the database and Actions summaries, not sent as separate emails. Hosting billing/retention remains account-specific. External ambiguous actions can require operator reconciliation. An independent Base44 system cannot be locked by this repository: documented audience separation remains necessary.

## Original tracked project structure (before discovery follow-up)

```text
GLOBAL-WEBSITE-AGENT/
├── .env.example
├── .gitattributes
├── .gitignore
├── .github/
│   ├── dependabot.yml
│   └── workflows/
│       ├── _agent-runtime.yml
│       ├── global-daily-pipeline.yml
│       ├── gmail-reply-checker.yml
│       ├── followup-processor.yml
│       ├── weekly-report.yml
│       └── manual-production-run.yml
├── pyproject.toml
├── uv.lock
├── README.md
├── SETUP_GUIDE.md
├── DEPLOYMENT_GUIDE.md
├── SECURITY.md
├── config/
│   ├── settings.yml
│   ├── country-policies.yml
│   ├── history.example.json
│   ├── history-validation.example.json
│   └── eligibility.example.json
├── database/migrations/001_initial.sql
├── docs/
│   ├── ARCHITECTURE.md
│   ├── LIMITATIONS.md
│   └── HANDOVER.md
├── scripts/
│   ├── action_entry.py
│   └── gmail_oauth.py
├── src/website_agent/
│   ├── __init__.py
│   ├── settings.py
│   ├── database.py
│   ├── discovery.py
│   ├── security.py
│   ├── analysis.py
│   ├── ai.py
│   ├── generation.py
│   ├── hosting.py
│   ├── gmail.py
│   ├── compliance.py
│   ├── scheduler.py
│   ├── copy.py
│   ├── outreach.py
│   ├── imports.py
│   ├── pipeline.py
│   ├── reporting.py
│   ├── cli.py
│   └── smoke.py
└── tests/
    ├── conftest.py
    ├── test_core.py
    ├── test_integrations.py
    ├── test_postgres_workflows.py
    └── test_recovery.py
```

The module-to-requirement mapping and all fourteen table names are documented in [ARCHITECTURE.md](ARCHITECTURE.md). Private data and runner artifacts are deliberately not tracked.
