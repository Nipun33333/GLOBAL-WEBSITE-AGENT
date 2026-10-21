# Architecture

## Code map

`src/website_agent/` is one installable Python package, with modules corresponding to the requested architecture areas:

| Module | Responsibility |
|---|---|
| `settings.py` | Validated environment/YAML configuration |
| `database.py` | Fourteen ORM tables, session lock, timestamps, suppression/config helpers |
| `discovery_engine.py`, `discovery_datasets.py`, `discovery_worker.py`, `discovery_verify.py`, `discovery_support.py` | Bounded zero-key readers, source fallback, supervised decoding, evidence checks and persistent recovery |
| `discovery.py` | Provider protocol, Brave/authorized JSON integrations, read retries |
| `security.py` | DNS-pinned public fetcher, robots, URL/email validation |
| `analysis.py` | Weighted static audit with evidence, source snippets, contact research |
| `ai.py` | Official GenAI SDK, model metadata checks, structured schemas, caching/cost ledger |
| `generation.py` | Verified quotation rendering, responsive designs, source validation |
| `hosting.py` | Netlify ZIP deployment/reconciliation, HTTPS and Chromium verification |
| `gmail.py` | OAuth refresh, MIME, drafts, sends, sent/thread/history/reply APIs |
| `compliance.py` | Country and prospect eligibility, local-hour/suppression enforcement |
| `scheduler.py` | Worldwide country/city/niche fairness, holidays/business days |
| `copy.py` | Trusted multilingual copy catalog, no fabricated commercial claims |
| `outreach.py` | Message state machine, sends, followups, reply classification/suppression |
| `imports.py` | Optional external history, Gmail Sent history, eligibility and review imports |
| `pipeline.py` | Durable vertical slice, retry/resume stages, owner events |
| `reporting.py` | Per-run/weekly summaries and Actions output |
| `cli.py` | Operational commands, migration application, safe error boundary |
| `smoke.py` | Explicit live generation/deploy/owner-draft verification |

## Persistence and state

Required tables: `prospects`, `business_sources`, `website_audits`, `generated_sites`, `outreach_messages`, `gmail_threads`, `followups`, `suppressions`, `country_policies`, `location_queue`, `workflow_runs`, `run_events`, `configuration`, `cost_usage`. `schema_migrations` records applied checksums separately.

Normalized domains, provider identifier pairs, prospect/site versions, message kind/sequence pairs, message idempotency keys, Gmail IDs, suppression keys, and location/niche combinations have uniqueness constraints. Every table has creation/update timestamps. The initial SQL migration is a static schema snapshot; future changes require a new migration file.

Prospects progress through discovered → audited → qualified → draft_ready → contacted, or stop in disqualified/no_contact/previous_contact/replied/interested/needs_information/rejected/unsubscribed/delivery_failure states. No-contact previews remain saved for later authorized review. An existing draft does not consume the next run's generation selection window.

Sites progress generated → deploy_pending → deploying → verified. Source is committed before deployment, deployment IDs before polling, and verification evidence before outreach. A unique site UUID is embedded in the actual page. Draft creation progresses prepared → draft_pending → drafted. Sends progress drafted → sending → sent or uncertain. Uncertain sends are never retried automatically. A received reply is persisted before model classification, stopping followups even if AI is unavailable.

The global PostgreSQL lock serializes pipeline, reply, followup, import, migration and reconciliation commands. That makes daily reservations global across scheduled and manual runs. Database commit boundaries prevent external success from being implied by transaction state. There is no atomic transaction spanning Gmail and PostgreSQL; therefore exactly-once network delivery cannot be guaranteed. Conservative uncertain states and provider reconciliation minimize duplicates without pretending this limitation is solved.

## Audit and content evidence

The score sums deterministic weights for viewport metadata, HTTPS, title/description, h1, navigation landmark, image alternatives, document language, contact path, observed HTTP fetch latency, sampled links and content length. Each check stores its evidence and limitations. Strong sites (55 or more by default) are disqualified before Gemini generation. This is a transparent static heuristic, not a comprehensive quality diagnosis.

Gemini verifies candidate relevance against retrieved snippets, summarizes research, selects quotes/layout/color/direction, localizes UI labels and prepares email suggestions/classification. Exact-source membership is required for generated business text. This prevents invented ratings, prices and testimonials but deliberately limits creative factual rewriting. The English independent-concept notice is mandatory even when UI labels are localized. Templates contain no copied imagery.

## Retry and reconciliation

Idempotent provider GETs retry transport/5xx errors three times with backoff. Gemini retries server errors with separate durable cost reservations; quota exhaustion persists a pause through the next UTC day. Gmail POSTs and Netlify deployment POSTs are never blindly retried. Known deployment IDs resume polling. Pending deploy titles and Gmail draft identities can be reconciled. Missing send results require Gmail Message-ID reconciliation. A separate discovery checkpoint avoids rediscovering on every downstream recovery heartbeat. Configured capacity exhaustion returns a deferred status, not a completed daily cycle. Other failed/deferred daily work remains durable for subsequent runs.

Reply processing isolates classification failures per message. One unavailable model call cannot prevent a later deterministic opt-out or structured delivery-status report from being processed. The reply checkpoint advances only after a clean sweep; failed sweeps stop followups. Acknowledgment work remains disabled in the master workflow; the owner handles conversations. Deferred classifications keep the reply checkpoint unchanged and pause followups.

Detailed local reports contain stage counters, selected locations, audit scores, verified URLs, actual draft/send/followup counts, reply categories, owner notifications, cost reservations, database size and sanitized error types. They do not include OAuth tokens or raw email bodies. Full evidence lives in the restricted database.

Zero-key discovery uses existing `configuration` rows for `discovery_task:*`, provider circuits and checkpoints; no migration or separate queue service is required. `business_sources.evidence` retains release, category, coordinates, verification and license provenance. See [DISCOVERY.md](DISCOVERY.md).

## Unified execution and model policy

`global-website-agent.yml` owns manual and scheduled triggers; `scripts/master_entry.py` validates event/owner/SHA and independent permissions before credentials load, then dispatches one fixed argv command after read-only database preflight. No reusable workflow or automatic migration remains. [Control panel](UNIFIED_WORKFLOW.md), [migration](WORKFLOW_MIGRATION.md).

`GeminiPolicy` validates a bounded exact model catalog, expiry, tier authorizations and retry limits. Account metadata, public structured-output review and price authorization are separate gates. Per-model cooldowns, global quota pauses, durable cost reservations and validated cache/provenance use existing configuration/cost tables. Model-generated site/audit/message metadata includes provenance; no schema migration is needed. Invalid requests, credentials and safety blocks do not trigger model rotation. [Fallback details](GEMINI_FALLBACK.md).

Generation/deployment/draft permissions are enforced before provider mutations and before creating ambiguous draft/deploy state. Capacity/authorization deferrals now produce a deferred run status and do not advance the daily completion checkpoint. Detailed reports remain local/restricted; Actions uploads only allowlisted aggregate results, without customer URLs or Gmail thread IDs.
