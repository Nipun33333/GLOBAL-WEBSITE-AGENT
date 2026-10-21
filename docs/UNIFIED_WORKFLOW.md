# One operations control panel

Target workflow: `.github/workflows/global-website-agent.yml`, displayed as **Global Website Agent**. It replaces seven definitions and has no reusable-workflow dependency. Follow [the migration sequence](WORKFLOW_MIGRATION.md) before activation. Registration alone never enables production.

## Manual operation

Open Actions → Global Website Agent → Run workflow. Select `feature/free-overture-discovery` during review, or `main` only after the full implementation is merged. As repository owner, enter the full reviewed branch-tip SHA. Both quota and intended-database review checkboxes must be true based on actual review. All other approvals default false/empty. Git checkout, event SHA and reviewed SHA must match; changing the branch after dispatch fails closed. Re-run jobs is blocked; use a new reviewed dispatch.

| Mode | Operation | Write approval | Additional independent permissions |
|---|---|---|---|
| diagnostics | Read-only database/schema and account metadata, OAuth refresh | None; leave empty | None; generation/deploy/drafts/sending forced off |
| discover | Isolated US discovery with persistent prospects/checkpoints | `APPROVE_US_DISCOVERY_WRITES` | US local research window, database preflight; other integrations cannot mutate |
| daily | Existing discovery/audit/qualification/preview/outreach stages | `APPROVE_DAILY_WRITES` | Generation, deployment, drafts and sending each require their own permission |
| replies | Read Gmail, persist replies/suppression/owner events | `APPROVE_REPLIES_WRITES` | Generation only if model-based classification is desired; deterministic opt-outs work without it |
| followups | Synchronize replies, process eligible followups | `APPROVE_FOLLOWUPS_WRITES` | Generation/drafts/sending separately; never deployment |
| report | Persist run/policy state; publish aggregate seven-day counts | `APPROVE_REPORT_WRITES` | No model/deploy/mail mutation |
| reconcile | Read Gmail to resolve uncertain sends; persist verified outcomes | `APPROVE_RECONCILE_WRITES` | No new send/draft |
| live-smoke | Neutral page generation/deployment and owner-addressed draft | `APPROVE_LIVE_SMOKE_WRITES` | Generation, deployment AND drafts must all be approved; sending forced off |

`country` filters discovery selection in daily mode. Blank means global rotation; it does not limit processing of already queued prospects, which retain their own local windows. Initial isolated discovery accepts US or blank only, preserving the established US write approval. Other operational modes reject country input rather than pretending they filter mailboxes/reports. Diagnostics report the US window.

All application mutations first require read-only schema/checksum/capacity preflight. No mode applies migrations. Missing schema requires a separately reviewed backup/migration operation. `doctor --live` is not used for diagnostics because it writes model-check state.

Generation uses `ENABLE_GENERATION`, deployment uses `ENABLE_DEPLOYMENT`, and drafts use `ENABLE_DRAFTS`; all default false outside explicitly authorized runs. Workflow inputs set only the permissions relevant to the selected mode. `request_sending` additionally requires repository/environment `ENABLE_SENDING=true` and all existing country, consent, history, audience, quota, identity and copy gates. Keep it false. `ENABLE_ROUTINE_REPLIES` is always false in this control panel; the owner handles customer conversations.

## Scheduled operation — initially disabled

| UTC cron | Mode |
|---|---|
| `17 * * * *` | daily (existing daily checkpoint and local research/business windows) |
| `7,37 * * * *` | replies |
| `42 * * * *` | followups (includes reply synchronization as a safety prerequisite) |
| `23 4 * * 1` | report |

These are the exact original schedules, each once. Only a schedule event on main can use this route. The event's cron maps to one allowlisted command, never an entire daily pipeline for a report/reply tick. Discovery failures leave unrelated saved stages resumable.

After the owner separately approves activation, use repository Settings → Secrets and variables → Actions → Variables to set `UNIFIED_WORKFLOW_ENABLED=true`, `AUTOMATION_ENABLED=true`, reviewed `FREE_LIMITS_REVIEWED=true`, reviewed `DATABASE_REVIEWED=true`, and `SCHEDULED_MODES` to the explicitly approved comma-separated subset of `daily,replies,followups,report` (no spaces). Those variables constitute standing authorization for the named modes' database writes, not other side effects. A review must be renewed when destination or quota assumptions change.

`ALLOW_GENERATION`, `ALLOW_DEPLOYMENT`, `ALLOW_DRAFTS`, and `ALLOW_SENDING` independently grant relevant scheduled capabilities; absent values deny them. Sending still additionally requires `ENABLE_SENDING`. Never enable both old and new schedules during migration. No variable has been enabled by this implementation. Manual modes do not require scheduled automation to be enabled.

## Execution, resources and recovery

All modes use `agent-runtime`, `contents: read`, pinned action commits and concurrency group `global-website-agent-runtime` with cancellation of active runs disabled. Mutating CLI operations retain the PostgreSQL session advisory lock, run IDs, unique constraints and durable state machines. GitHub can replace a pending concurrency job; later ticks resume persistent work, so exact-minute execution is not guaranteed. Do not clear history/checkpoints to retry.

Only the runtime step receives existing secrets, after credential-free preflight. Dependencies use `uv sync --frozen --no-dev`; Chromium binaries are installed only for daily/live-smoke modes that can verify previews. Runtime packages still include common import dependencies; this is not a claim of a fully split lightweight wheel. The job is bounded to 45 minutes, the operational child to 40 minutes, and isolated discovery retains its unchanged 300-second internal/420-second wrapper budgets. Quota review must therefore reserve up to 45 included Linux minutes plus storage headroom per master run.

Only `artifacts/live-verification.json` and `.md` are uploaded, for one day. Diagnostics contain allowlisted metadata and discovery counters; other modes include exit status and aggregate run/site/message/sent/draft/followup/owner-notification/failure/deferral counts and tracked Gemini cost for one day (seven for report). Historical detailed reports with URLs/thread IDs are not uploaded. Owner conversation details remain in the restricted database/Gmail; the control panel does not send owner notification emails. Timeout means progress may already exist: inspect saved state before retrying. Exit 2 means deferred/blocked; exit 1 means failure; neither is reported as success.

## Safe first dispatch

After registration and review, select mode `diagnostics`, current full feature SHA, both genuinely reviewed checkboxes, no write approval and no capability permissions. Inspect the summary/artifact. This consumes included runner/provider resources but does not generate, deploy, draft, send, migrate or write prospect records. Do not run `daily` as a substitute. Discovery requires a later separate explicit US write approval.
