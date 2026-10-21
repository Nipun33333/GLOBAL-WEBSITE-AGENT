# Hosting, automation and production activation

## Hosting

Create **one dedicated Netlify site/project** through your authorized account, then set `NETLIFY_SITE_ID` and `NETLIFY_AUTH_TOKEN`. No project per business is needed. The adapter POSTs a real ZIP archive to the existing project's deploy endpoint with `draft=true`, then polls the actual deploy ID. It records only the returned immutable HTTPS deployment URL, never a constructed guessed link. Each site version has its own deployment.

Source HTML, CSS, JavaScript, metadata and version are stored in PostgreSQL. A timeout after deployment submission leaves `deploy_pending`; later runs search that site's deploy history by deterministic title. Once an ID is known, polling and verification resume safely. If a submitted deployment cannot be reconciled, it is held for investigation rather than automatically creating repeated deployments.

Successful verification requires HTML content type, no download attachment, expected concept identity, assets, and Chromium rendering at 375px and 1280px with working section navigation. The browser renders fetched deployment assets with additional network access blocked. This is a real rendering check, not Lighthouse or a Core Web Vitals measurement.

Previews have no forms, payments, tracking, external fonts, or third-party imagery. Original CSS artwork avoids licensing uncertainty. A visible unofficial/independent banner, noindex directives, CSP, and safe reviewed JavaScript are included. Business statements remain exact source quotations; model-generated arbitrary scripts are never executed.

Netlify retention and account limits can remove old deploys; configure adequate retention for active offers and check your plan. The agent re-verifies previews before every send. The application cannot guarantee that a URL will remain available forever. It does not create sites, upgrade plans, enable billing, or purchase capacity. Reference: [Netlify deploy API](https://docs.netlify.com/api-and-cli-guides/api-guides/get-started-with-api/).

## Schedules

All GitHub cron expressions are UTC. Set `AUTOMATION_ENABLED=true` only after configuring the services. Without it, scheduled workflows skip their runtime jobs.

| Workflow | UTC schedule | Behavior |
|---|---|---|
| `global-daily-pipeline.yml` | Hourly at minute 17 | Runs one successful daily discovery cycle after the configured local schedule hour; retries deferred/missed work |
| `gmail-reply-checker.yml` | Minutes 7 and 37 | Polls replies, suppresses withdrawals, records owner notifications and acknowledgment drafts |
| `followup-processor.yml` | Hourly at minute 42 | Processes replies first, then eligible followups |
| `weekly-report.yml` | Monday 04:23 UTC | Seven-day digest |
| `manual-production-run.yml` | Manual only | Explicit command, country and production-mode controls |

The daily eligibility threshold is `schedule_hour` in `schedule_timezone` in YAML (default 03:00 UTC). Hourly polling lets an underserved country's own local research window open without permanently preferring countries awake at one fixed UTC time. Country search counts enforce fairness; oldest city/niche combinations win, with a bounded relevance preference. Public holidays, subdivisions, local weekends and time zones use the pinned `holidays`/`tzdata` packages. Missing calendars fail closed. Manual country selection bypasses country balancing, not the local time checks.

GitHub can delay or drop schedule events. A durable checkpoint allows the next heartbeat to catch up without replaying all missed days or creating a burst of emails. Manual runs do not alter checkpoint configuration or scheduled workflow files. All mutating CLI jobs share a PostgreSQL advisory lock, in addition to GitHub concurrency controls. GitHub may replace a pending concurrency job; the next heartbeat resumes durable work. The system does not promise exact-minute execution.

## Manual runs

In this repository, open **Actions → Manual Production Run → Run workflow**. Choose `daily`, `replies`, `followups`, `report`, `reconcile`, or `live-smoke`. Leave `production` false during setup. Leave `country` empty for worldwide rotation, or use an ISO code such as `IN` or `GB`.

The workflow uses `agent-runtime`, applies migrations, installs locked dependencies and Chromium, runs the command, and retains a sanitized report for 14 days. It never changes schedules. Production requires **both** `production=true` in the invocation and `ENABLE_SENDING=true` in variables; every per-prospect gate still applies.

Equivalent local commands:

```bash
uv run website-agent daily --country IN
uv run website-agent replies
uv run website-agent followups
uv run website-agent reconcile
# Only after all production checks:
uv run website-agent daily --production
```

## Base44 migration and sending activation

1. Keep sending disabled. Export previously contacted businesses, thread IDs and opt-outs from Base44 using your own authorized access. This project never reads or changes Base44.
2. Save the export in `private/history.json` following `config/history.example.json`. The loader records addresses/domains as suppressions and imports associated threads where a business domain is available. Do not commit the export.
3. Run the completed-history scans:

```bash
uv run website-agent import-history --file private/history.json
uv run website-agent import-gmail
uv run website-agent replies
```

4. Establish a documented audience partition excluding this agent's prospects from Base44. A history snapshot alone cannot eliminate a race with an independent system that continues contacting the same prospects. This application's database lock cannot lock Base44. Keep this project's production disabled if an exclusive audience cannot be established.
5. Copy `config/history-validation.example.json` to `private/validation.json`. Supply the exact import SHA-256, reviewer, complete-export confirmations and real audience-exclusion reference. Then run:

```bash
uv run website-agent validate-history --file private/validation.json
```

6. Have a qualified reviewer configure current country rules in `config/country-policies.yml`: permitted legal bases/contact types, source reference, reviewer, expiry and local hours. **All eleven templates are deliberately disabled.** No country is assumed to allow unsolicited email. Public availability is not consent. Policy configuration is auditable in Git and synchronized to PostgreSQL on every run.
7. Import per-business evidence using `config/eligibility.example.json`: genuine legal basis, contact type, review validity, source evidence and exclusive Base44 audience assignment. Where needed, include a verified business email and its evidence.

```bash
uv run website-agent import-eligibility --file private/eligibility.json
```

8. Confirm sender identity, physical address, OAuth permissions, model costs, provider rights, preview hosting and applicable local requirements. Inspect generated drafts. Use the live smoke test and a real draft-only daily run before any sending activation.
9. Set `ENABLE_SENDING=true`, then request production mode. Routine acknowledgments also need `ENABLE_ROUTINE_REPLIES=true` and prospect-specific `routine_reply_authorized=true`.

Autonomous messages use factual-claim-free multilingual catalog copy, the observed business name, and a verified preview. Gemini prepares suggested content, but arbitrary suggestions cannot become promises or prices in automatic sends. If a trusted operator deliberately edits database copy, the exact changed digest must be approved with `approve-copy --message-id ID --digest SHA256 --reviewer NAME`. This is an optional customization path, not a per-email requirement for catalog messages. Use `export-drafts` to inspect private copy/digests.

Every outbound attempt rechecks suppression, prior external Gmail correspondence, incoming mail, local eligibility and the preview. The existing Gmail draft is consumed through `drafts.send`, with the validated MIME content supplied in the send request; an already-sent draft is not left behind. Pending draft creation can be reconciled by its Message-ID. Changing a verified recipient or sender identity/address after draft creation blocks sending until the draft is regenerated. Followups are due only after five local business days, at most two, and stop on any reply. An API timeout after send reserves the attempt as `uncertain`; **no automatic resend** occurs. `reconcile` searches Gmail by the stable RFC Message-ID and records verified sent evidence. Unresolved uncertain states need mailbox investigation; do not manually reset them just to make a job pass.

Owner notifications are durable `owner_notification` events in the Actions summary/weekly digest, with Gmail thread IDs. Enable GitHub Actions notifications for this repository. The implementation does not send a separate owner-notification email.

## Discovery readiness before any activation

The six production workflows, schedules, reusable-workflow references and sending controls are unchanged. The removed test workflow remains absent. Use the local `uv run website-agent discover --country US` command after secure PostgreSQL setup/migration, during the configured local window, to test discovery without initializing other integrations. This command forces sending and routine replies off, including when `--production` is supplied. Check persisted pending records, cursors, source/license evidence and the report; wait until `next_at` before retrying. Do not clear history/suppressions to resume.

The public dataset diagnostic does not need credentials: `uv run python scripts/probe_discovery.py`. It writes only ignored local diagnostic output and never visits business websites or accepts prospects. Its success does not authorize scheduled activation. The current go/no-go evidence and free-tier blockers are in [LIVE_READINESS_REPORT.md](docs/LIVE_READINESS_REPORT.md). No workflow was dispatched during this verification.
