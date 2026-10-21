# Hosting, automation and production activation

## Hosting

Create **one dedicated Netlify site/project** through your authorized account, then set `NETLIFY_SITE_ID` and `NETLIFY_AUTH_TOKEN`. No project per business is needed. The adapter POSTs a real ZIP archive to the existing project's deploy endpoint with `draft=true`, then polls the actual deploy ID. It records only the returned immutable HTTPS deployment URL, never a constructed guessed link. Each site version has its own deployment.

Source HTML, CSS, JavaScript, metadata and version are stored in PostgreSQL. A timeout after deployment submission leaves `deploy_pending`; later runs search that site's deploy history by deterministic title. Once an ID is known, polling and verification resume safely. If a submitted deployment cannot be reconciled, it is held for investigation rather than automatically creating repeated deployments.

Successful verification requires HTML content type, no download attachment, expected concept identity, assets, and Chromium rendering at 375px and 1280px with working section navigation. The browser renders fetched deployment assets with additional network access blocked. This is a real rendering check, not Lighthouse or a Core Web Vitals measurement.

Previews have no forms, payments, tracking, external fonts, or third-party imagery. Original CSS artwork avoids licensing uncertainty. A visible unofficial/independent banner, noindex directives, CSP, and safe reviewed JavaScript are included. Business statements remain exact source quotations; model-generated arbitrary scripts are never executed.

Netlify retention and account limits can remove old deploys; configure adequate retention for active offers and check your plan. The agent re-verifies previews before every send. The application cannot guarantee that a URL will remain available forever. It does not create sites, upgrade plans, enable billing, or purchase capacity. Reference: [Netlify deploy API](https://docs.netlify.com/api-and-cli-guides/api-guides/get-started-with-api/).

## UK-only schedules

The **UK Website Agent** runs the single workflow twice daily on `main`, at **15:00 and 21:00 Asia/Kolkata** (UTC crons `30 9 * * *` and `30 15 * * *`). Research/local-contact windows use `Europe/London` and GB holiday calendars. GitHub scheduled starts may be delayed or skipped. Manual one-click runs have no input fields.

Both scheduled and manual invocations restrict business discovery, the persisted queue, audit, generation, draft processing and initial outreach to the United Kingdom (`GB`). Old non-UK prospects and the old worldwide discovery checkpoint remain stored without deletion but are never processed by this workflow. Local contact legal requirements remain independent and must be reviewed; the sole `GB` policy is still disabled.

The workflow uses existing `agent-runtime` GitHub Secrets, bounded AI/Netlify limits, PostgreSQL state and a single concurrency lock. Customer replies and followups remain owner-managed, not automated.

## Standalone Gmail history and legally reviewed outreach

This repository has no connection to or audience assignment requirement from any other platform. Gmail's existing **Sent** and **Inbox** are checked live for each recipient immediately before sending; durable opt-outs and prior-contact suppressions are also checked.

Optional bulk synchronization and manual independent history imports can further improve the suppression list. They are not mandatory gates for this agent:

```bash
uv run website-agent import-gmail
# Only if the owner has an authorized, vendor-neutral historical opt-out export:
uv run website-agent import-history --file private/history.json
uv run website-agent validate-history --file private/validation.json
```

Never upload private contact exports to GitHub or public Actions artifacts. These imports do not certify sending permission.

A qualified reviewer must confirm current United Kingdom law and populate the sole `GB` entry in `config/country-policies.yml` with accurately reviewed rules. This UK policy template remains disabled until reviewed. Record actual per-prospect contact basis, evidence and expiry in `config/eligibility.example.json`, then use:

```bash
uv run website-agent import-eligibility --file private/eligibility.json
```

Confirm the sender's identity, physical address, Gmail OAuth, model/hosting quotas, verified business mailbox and independent HTTPS demo. Real initial sends require the approved jurisdiction and recipient to pass the existing safety gates; the technical workflow switches alone do not make a business eligible.

Autonomous messages use factual-claim-free multilingual catalog copy, the observed business name, and a verified preview. Gemini prepares suggested content, but arbitrary suggestions cannot become promises or prices in automatic sends. If a trusted operator deliberately edits database copy, the exact changed digest must be approved with `approve-copy --message-id ID --digest SHA256 --reviewer NAME`. This is an optional customization path, not a per-email requirement for catalog messages. Use `export-drafts` to inspect private copy/digests.

Every outbound attempt rechecks suppression, prior external Gmail correspondence, incoming mail, local eligibility and the preview. The existing Gmail draft is consumed through `drafts.send`, with the validated MIME content supplied in the send request; an already-sent draft is not left behind. Pending draft creation can be reconciled by its Message-ID. Changing a verified recipient or sender identity/address after draft creation blocks sending until the draft is regenerated. Followups are due only after five local business days, at most two, and stop on any reply. An API timeout after send reserves the attempt as `uncertain`; **no automatic resend** occurs. `reconcile` searches Gmail by the stable RFC Message-ID and records verified sent evidence. Unresolved uncertain states need mailbox investigation; do not manually reset them just to make a job pass.

Owner notifications are durable `owner_notification` database events with Gmail thread IDs; Actions publishes aggregate counts only. Enable GitHub Actions notifications for this repository. The implementation does not send a separate owner-notification email.

## Discovery readiness before any activation

The feature replaces all seven old workflow definitions with one master workflow, preserving operational commands, four schedules, local windows and database/external-operation safety. PR #8 registers the replacement on main; the old main definitions remain until PR #6 is separately approved. Keep schedules disabled throughout transition. See [migration order](docs/WORKFLOW_MIGRATION.md).

For read-only account/database diagnostics and separately approved US discovery, follow [the manual guide](docs/MANUAL_LIVE_VERIFICATION.md). The public credential-free probe remains available through `scripts/probe_discovery.py`; its candidates are not verified prospects. See [FINAL_READINESS.md](docs/FINAL_READINESS.md) for live-test limitations and owner actions.
