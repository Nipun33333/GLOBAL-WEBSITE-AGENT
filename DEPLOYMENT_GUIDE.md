# Hosting, automation and production activation

## Hosting

Create **one dedicated Netlify site/project** through your authorized account, then set `NETLIFY_SITE_ID` and `NETLIFY_AUTH_TOKEN`. No project per business is needed. The adapter POSTs a real ZIP archive to the existing project's deploy endpoint with `draft=true`, then polls the actual deploy ID. It records only the returned immutable HTTPS deployment URL, never a constructed guessed link. Each site version has its own deployment.

Source HTML, CSS, JavaScript, metadata and version are stored in PostgreSQL. A timeout after deployment submission leaves `deploy_pending`; later runs search that site's deploy history by deterministic title. Once an ID is known, polling and verification resume safely. If a submitted deployment cannot be reconciled, it is held for investigation rather than automatically creating repeated deployments.

Successful verification requires HTML content type, no download attachment, expected concept identity, assets, and Chromium rendering at 375px and 1280px with working section navigation. The browser renders fetched deployment assets with additional network access blocked. This is a real rendering check, not Lighthouse or a Core Web Vitals measurement.

Previews have no forms, payments, tracking, external fonts, or third-party imagery. Original CSS artwork avoids licensing uncertainty. A visible unofficial/independent banner, noindex directives, CSP, and safe reviewed JavaScript are included. Business statements remain exact source quotations; model-generated arbitrary scripts are never executed.

Netlify retention and account limits can remove old deploys; configure adequate retention for active offers and check your plan. The agent re-verifies previews before every send. The application cannot guarantee that a URL will remain available forever. It does not create sites, upgrade plans, enable billing, or purchase capacity. Reference: [Netlify deploy API](https://docs.netlify.com/api-and-cli-guides/api-guides/get-started-with-api/).

## Schedules

The single Global Website Agent workflow retains UTC schedules `17 * * * *` (daily), `7,37 * * * *` (replies), `42 * * * *` (followups), and `23 4 * * 1` (weekly report). Application checkpoints and local country windows remain authoritative. Both `AUTOMATION_ENABLED` and `UNIFIED_WORKFLOW_ENABLED` must be explicitly enabled after [migration](docs/WORKFLOW_MIGRATION.md); all schedule modes and side effects also require separate approval variables. They remain disabled.

GitHub can delay/drop events or replace a pending concurrency job. Persistent queues/checkpoints resume on later ticks. One shared concurrency group plus the PostgreSQL advisory lock serializes mutations; no exact-minute guarantee is made.

## Manual runs

Open **Actions → Global Website Agent → Run workflow**. Follow [the mode/approval table](docs/UNIFIED_WORKFLOW.md), review the exact SHA and quotas/database first, then select the intended operation. Start with diagnostics. Country filtering applies to discovery selection in daily/discover only; existing queued prospects retain individual country windows.

The workflow uses agent-runtime, installs locked runtime dependencies, installs Chromium only for daily/live-smoke, and uploads aggregate allowlisted reports for one day. It never applies migrations. Generation, deployment, Gmail drafts and sending have independent permissions; all default disabled. Routine customer replies remain disabled and owner-controlled.

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
9. Set `ENABLE_SENDING=true`, then request production mode. The master control panel always disables routine customer replies.

Autonomous messages use factual-claim-free multilingual catalog copy, the observed business name, and a verified preview. Gemini prepares suggested content, but arbitrary suggestions cannot become promises or prices in automatic sends. If a trusted operator deliberately edits database copy, the exact changed digest must be approved with `approve-copy --message-id ID --digest SHA256 --reviewer NAME`. This is an optional customization path, not a per-email requirement for catalog messages. Use `export-drafts` to inspect private copy/digests.

Every outbound attempt rechecks suppression, prior external Gmail correspondence, incoming mail, local eligibility and the preview. The existing Gmail draft is consumed through `drafts.send`, with the validated MIME content supplied in the send request; an already-sent draft is not left behind. Pending draft creation can be reconciled by its Message-ID. Changing a verified recipient or sender identity/address after draft creation blocks sending until the draft is regenerated. Followups are due only after five local business days, at most two, and stop on any reply. An API timeout after send reserves the attempt as `uncertain`; **no automatic resend** occurs. `reconcile` searches Gmail by the stable RFC Message-ID and records verified sent evidence. Unresolved uncertain states need mailbox investigation; do not manually reset them just to make a job pass.

Owner notifications are durable `owner_notification` database events with Gmail thread IDs; Actions publishes aggregate counts only. Enable GitHub Actions notifications for this repository. The implementation does not send a separate owner-notification email.

## Discovery readiness before any activation

The feature replaces all seven old workflow definitions with one master workflow, preserving operational commands, four schedules, local windows and database/external-operation safety. PR #8 registers the replacement on main; the old main definitions remain until PR #6 is separately approved. Keep schedules disabled throughout transition. See [migration order](docs/WORKFLOW_MIGRATION.md).

For read-only account/database diagnostics and separately approved US discovery, follow [the manual guide](docs/MANUAL_LIVE_VERIFICATION.md). The public credential-free probe remains available through `scripts/probe_discovery.py`; its candidates are not verified prospects. See [FINAL_READINESS.md](docs/FINAL_READINESS.md) for live-test limitations and owner actions.
