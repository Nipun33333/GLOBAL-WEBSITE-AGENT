# Known limitations and production blockers

**Current unified-workflow update:** PR #8 registers Global Website Agent; PR #6 contains the single-workflow implementation and remains unmerged. All automation/sending controls remain disabled. Gemini has bounded exact-model fallback with empty account authorization/pricing maps, so live generation remains blocked. See [current readiness](FINAL_READINESS.md), [control panel](UNIFIED_WORKFLOW.md), [Gemini policy](GEMINI_FALLBACK.md) and [migration sequence](WORKFLOW_MIGRATION.md). Older workflow inventories and validation counts below are historical, not current activation instructions.


This is an implemented application, not a claim of verified production operation.

## Requires external setup

- The 12 required GitHub Secret names are present, but live diagnostics have not been dispatched. Quota/destination confirmation and explicit owner approval remain outstanding; no local credential copy is required. Credentialed discovery/persistence, model access/generation, deployment, OAuth refresh and Gmail drafts cannot be reported as passed. Real public Overture range queries have now returned source candidates; see [LIVE_READINESS_REPORT.md](LIVE_READINESS_REPORT.md). Candidates have not been verified or admitted.
- No country policy has been legally verified for this sender/audience. Every shipped country is draft-only. A reviewer must determine applicable law, contact types, consent or other basis, identification/unsubscribe requirements, retention and evidence validity. Configuration templates are not legal advice or blanket permission.
- The agent is standalone. It protects existing suppression records and checks Gmail Sent/Inbox live before each send. Optional owner-supplied contact exports may add suppressions; separate-platform audience attestations are not required.
- Provider storage and outreach-use rights, Gemini prices/model access, Gmail consent publishing, hosting retention and service quotas need account-specific checks. Free plans may be insufficient. No additional resources are bought automatically.

## Intentional bounds

- The audit is static HTML plus a bounded link sample and measured HTTP fetch duration. It does not run Lighthouse, browser rendering of arbitrary prospect sites, full accessibility evaluation, visual grading, JavaScript-app crawling, or exhaustive broken-link scans. It can miss high-quality client-rendered sites; review score evidence before scaling.
- Gemini uses structured content/design schemas, not unrestricted generated JavaScript. The renderer provides complete HTML/CSS/JS with controlled layouts. Business facts are extractive quotations; factual translation or creative claims require editorial review. UI labels and trusted email copy support multilingual operation, including RTL. Copy catalog languages are English, Hindi, Arabic, German, French and Japanese; other languages currently use English email catalog copy.
- Preview browser checks render the HTTP-fetched deployed assets in Chromium with network interception. This verifies mobile/desktop layout and navigation, but not all real-device/browser behavior or network performance. There is no accessibility certification claim.
- Public research collects role-based same-domain `mailto:` addresses. It does not infer private personal contacts. Some valid businesses will be marked `no_contact`; verified contacts can be imported.
- Gmail aliases are not supported. Reply-to must be the authenticated monitored mailbox. Automatic owner notification is through database/Actions summaries, not a separate notification email.
- Two systems without shared campaign ownership cannot provide absolute duplicate prevention. Gmail search is eventually consistent. Ambiguous send/draft/deployment results can require operator reconciliation, intentionally sacrificing liveness to avoid duplicates.
- Default countries/cities are examples, not exhaustive geographic coverage. Holiday coverage comes from the pinned library and configured subdivision; local exceptions/contact windows require policy review. The scheduler waits for underserved countries, so a holiday/weekend can defer a daily search.
- Source/AI cache and full preview files are stored in PostgreSQL. Monitor storage; add a reviewed retention policy before high-volume operation. Database size is checked against the configured cap. Hosting account billing/bandwidth counters are not normalized into a universal quota API; provider 429/errors and local deployment limits are enforced, and account dashboards remain authoritative.
- No web admin dashboard is included: configuration, CLI commands, GitHub Actions and PostgreSQL are the operational interface. This repository implements an automation service rather than a visual admin dashboard.

## Before enabling production

- [ ] Live database migration and connection verified; backups and restricted access configured.
- [ ] Direct/session pooler used; actual multi-session lock test passes.
- [ ] Model metadata and structured generation work for the configured account; prices and caps reviewed.
- [ ] Discovery agreement authorizes the actual storage/marketing use; real candidate tested.
- [ ] One dedicated hosting project configured; actual HTTPS/mobile smoke verification passed.
- [ ] Gmail sender/reply-to identity, OAuth refresh, draft creation and sent verification reviewed.
- [ ] Physical address and owner details are accurate.
- [ ] Gmail Sent/Inbox access tested and prior-contact checks verified; existing opt-out suppressions retained.
- [ ] Country policies and per-business legal/contact evidence reviewed and current.
- [ ] Draft contents, unsubscribe handling, reply polling and followup timing verified.
- [ ] Actions secrets/variables configured; scheduled and manual draft-only runs pass.
- [ ] Provider account limits, storage/retention, notification settings and billing alerts reviewed.
- [ ] Only then enable sending, with both environment and invocation gates.

## Zero-key discovery

The default discovery path does not require a search API key. OSM fallback remains permission-gated. Bounded scans can legitimately defer with no results; strict name/locality/own-domain contact verification rejects incomplete records. Local caches do not survive fresh Actions runners, but PostgreSQL checkpoints and pending candidates do. Detailed limits and recovery procedures are in [DISCOVERY.md](DISCOVERY.md). Historical verification records above do not claim live verification of the new discovery path.

STAC is now a common metadata dependency for AWS and Azure. A catalog outage can block both mirrors; only an applicable verified query cache or separately configured lawful source can help. An incomplete/paged catalog fails closed and requires reader support rather than guessing omitted files. At the inspected release, 16 item documents suffice; future index growth consumes the same request/time/byte budget. Exact locality and own-domain contact requirements remain conservative and can reject genuine businesses. Only the measured New York dataset subset was tested live; other configured countries and actual outage-triggered failover are not live-verified. A new bounded Azure probe now confirms full candidate decoding for the same New York subset as AWS. Whole-row-group column decoding and resumed row groups can re-read data; cursors prevent repeated admissions, not all repeated transfer. Website DNS/read calls have bounded transport timeouts but no kernel-enforced wall-clock deadline. No resource bound guarantees 30 prospects.

Current evidence and the single consolidated owner-action checklist: [FINAL_READINESS.md](FINAL_READINESS.md). New schema reflection is tested with real SQLite inspection and drift fixtures; it is not current Supabase/PostgreSQL proof. Database identity still depends on owner confirmation of the stored connection destination; a successful connection/checksum cannot distinguish two identically provisioned databases. TLS relies on the provided CA bundle and can fail closed when a provider requires a different trusted CA.
