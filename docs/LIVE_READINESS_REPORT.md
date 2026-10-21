# Live readiness — 21 October 2026

**Historical public-probe report.** The original measurements and workflow inventory below describe the pre-unification implementation. For current workflow registration, Gemini fallback, tests and owner launch steps, use [FINAL_READINESS.md](FINAL_READINESS.md) and [UNIFIED_WORKFLOW.md](UNIFIED_WORKFLOW.md). Existing GitHub Secrets are reused; no local copy is needed. No live account diagnostic or discovery-write run has occurred.

The public dataset measurements below are the earlier completed probes; no credentialed business verification, database insert or account-connection result has been added. The original local-credential limitation is superseded by the GitHub Secrets route, not by a claim that live verification succeeded.

## Configuration and scope

- Repository: `Nipun33333/GLOBAL-WEBSITE-AGENT`; branch: `feature/free-overture-discovery`; base inspected: `369c5328d4df5154cdb5b32586c82cb85c536355`. Previous feature revision: `d9b79bf83fa5d8b97d7b445bdf96ffc29ea65a30`.
- `open_data`, pinned release `2026-09-23.1`, 11 configured countries, 12 niches. No mandatory discovery API key. All 23 configured Overture category IDs were checked against the official published September taxonomy CSV; the reviewed subset and full-source SHA-256 are retained in the repository.
- Limits unchanged: 30 accepted/invocation, 120 candidate checks, 160 request attempts, 64,000,000 payload bytes, 128,000,000 managed cache/worker bytes, 512 MiB worker RSS, 300 seconds, 8 dataset chunks and 8 files/chunk.
- Local sending/routine flags are false. Repository variables and the three automation/sending gates in `agent-runtime` had no overrides; the existing workflow defaults keep them disabled. No secrets were retrieved or changed. No workflow was dispatched. All 11 country policies remain disabled.
- All six production YAML files match `origin/main` byte-for-byte: `_agent-runtime.yml`, `global-daily-pipeline.yml`, `gmail-reply-checker.yml`, `followup-processor.yml`, `weekly-report.yml`, `manual-production-run.yml`. Schedules and manual inputs are unchanged. `tests.yml` remains absent.
- No Base44 access, other repository access, prospect emails, Gmail drafts, model generation, deployments, billing activation, production-data changes or migrations were performed.

## Defects fixed

1. Global file-order scanning wasted budget on unrelated geography. The reader now validates the official STAC collection/item index, selects intersecting file bounds, then prunes Parquet row groups. A missing item, changed/paged index or unexpected asset origin fails closed. All metadata calls count against the same budget. STAC is a shared dependency of both mirrors.
2. Reading every nested leaf separately consumed many HTTP requests. Adjacent selected-column ranges are coalesced with bounded gaps/spans; responses still require exact HTTP 206 and Content-Range. No whole global file is downloaded.
3. Several old category names had no current match. Examples: `barber_shop`/`barbershop` → `barber`, `dentist` → `dental_clinic`, `medical_clinic` → `primary_care_or_general_clinic`, `doctor` → `doctors_office`, `auto_repair` → `automotive_repair`, `tax_preparation` → `tax_service`. Reviewed hierarchy descendants are eligible while the actual primary category is retained. Unrelated/inconsistent hierarchies are rejected. Nullable names and zero-confidence/closed records are excluded.
4. An invocation reaching its accepted-record target discarded pending candidates. The durable batch now survives. Resume checkpoints cannot move backward when a row-group reread or prefetch is interrupted. City rotation and task-plan creation now commit atomically.
5. Exited workers without an output checkpoint could hide unknown transfers. Their remaining allowance is conservatively reserved and explicitly labeled an upper bound. Received over-limit chunks are counted before the limit fault.
6. Cache used to precede healthy primary reads. The order is now AWS → Azure on a genuine transient fault without Retry-After → valid cache after availability failure. A shared rate-limit circuit prevents mirror hopping; cache may serve while that circuit is paused. Permission/schema failures do not use cache to bypass the failure.
7. Suppression checks no longer materialize every suppression row in Python per candidate. Database-side domain/mailbox matching retains subdomain exclusions. Reports separate duplicate and suppression reasons, dataset work, verification work, accepted writes, fallback attempts and remaining work.

Readers, cache keys and task signatures use version 2. Old global-list cursors are intentionally invalidated; existing businesses, provenance, suppression/history and outreach state are preserved. Source parsing and scheduling changed; Gemini, Netlify, Gmail, rendering, outreach integrations, migration SQL, secrets, production workflows and account settings did not.

## Real public-data evidence

The official STAC collection was HTTP 200, reported 16 Places files and 81,455,423 rows. Item `00006` intersects the probe bbox; its AWS asset size is 729,007,835 bytes. Actual footer inspection reported 5,137,402 rows, 256 row groups, and current `taxonomy`/`basic_category` columns. Fourteen row groups overlap the probe bbox; the candidate cap was reached after reading three. Initial footer inspection transferred 1,647,026 bytes in two requests. No full-file/global download was attempted.

Final reproducible data probe:

```bash
uv run python scripts/probe_discovery.py --country US --city "New York" --niche salons --bbox -74.03 40.70 -73.95 40.78
```

| Measurement | Actual result |
|---|---:|
| Parquet files examined | 1 |
| Row groups read | 3 |
| Rows scanned | 48,474 |
| Dataset candidates identified | 120 |
| Source locality exactly New York | 113 |
| Other source locality labels | 7 |
| Website verification attempts / verified websites | 0 / 0 |
| Accepted businesses inserted | 0 |
| Candidate rejection / known-duplicate checks | NOT RUN |
| Dataset requests | 28 |
| Payload bytes | 8,227,416 |
| Elapsed time | 53.334 seconds |
| Final diagnostic status | `dataset_probe_only` |
| Remaining cursor | file 0, group 12, row 7020; not exhausted |
| Fallback layers used | AWS primary only |

Categories were 67 hair salons, 51 beauty salons, one blow-dry/blow-out service and one hair stylist. These are real source records, **not 120 verified leads**. Source locality mismatches and questionable name/website associations illustrate why verification must remain strict. Candidates are saved only in ignored `private/discovery-probe-aws.json`; no public report contains recipient data. An earlier exploratory probe returned 120 candidates in 63.67 seconds, 28 requests and 8,061,782 bytes before hierarchy/confidence refinements; it is not combined with the final measurement.

Azure was independently checked with a single 8-byte footer request to the corresponding official asset: HTTP 206 Content-Range and `PAR1` trailer matched. This proves range accessibility, not full Azure candidate decoding or a real automatic outage failover. Automatic failover was tested offline.

**`uv run website-agent discover --country US` was NOT run.** At the earlier probe, there was no local `DATABASE_URL`, authorized test database or PostgreSQL/container executable available. Existing GitHub Secrets now provide an owner-controlled route; the new workflow is still unlaunched. The US website-research window was also closed (approximately 03:21 New York / 12:51 India at the prerequisite check). Public dataset diagnostics do not visit business websites and do not substitute for this required persistence/verification run. No production checkpoint, accepted-source evidence, storage quota or actual suppression history was inspected.

## Readiness by component

| Component | Status | Evidence / remaining requirement |
|---|---|---|
| Overture AWS dataset retrieval | VERIFIED LIVE | Real bounded STAC, footer and candidate reads above; not website admission |
| Azure range endpoint | VERIFIED LIVE | One exact footer range; full decoding/failover is VERIFIED OFFLINE ONLY |
| Verified cache | VERIFIED OFFLINE ONLY | Integrity, corruption, permission revocation and cooldown tests; no production cache populated |
| OSM extract / Overpass | BLOCKED | `osm_extracts: []`, obligations false, license reference empty; no permitted private/contracted endpoint. XML reader tested offline only |
| Worldwide city rotation | VERIFIED OFFLINE ONLY | Fair rotation, windows, geographic bounds and atomic rollback tested; only US dataset subset queried live |
| Website identity verification | VERIFIED OFFLINE ONLY | HTTPS, robots, DNS, visible name/locality, own-domain contact, deduplication and suppression tests; no live site visits |
| Persistent discovery recovery | VERIFIED OFFLINE ONLY | SQLite transactions, restart/cursors, pending-target preservation, fault/circuit and worker tests |
| Supabase / PostgreSQL | AWAITING OWNER RUN | GitHub DATABASE_URL name confirmed. Read-only TLS/schema/checksum/storage checks prepared; live connection, writes and advisory locks unverified. Local TEST_DATABASE_URL remains unavailable |
| Gemini | AWAITING OWNER RUN | GitHub key name confirmed; configured model IDs unchanged. Metadata checks prepared, no call made; generation and account free quota remain unverified |
| Netlify | AWAITING OWNER RUN | GitHub token/site ID names confirmed. Existing-site GET prepared; no lookup or deployment made, quota unknown |
| Gmail | AWAITING OWNER RUN | GitHub OAuth/sender secret names confirmed. Refresh/profile/scope checks prepared; no credentialed check, draft or send made |
| Base44 overlap controls | VERIFIED OFFLINE ONLY | Imported suppressions and exclusive-assignment gates tested; actual history/partition unvalidated, Base44 untouched |
| Country legal compliance | BLOCKED | All policies disabled; sender/audience-specific review and evidence still required |
| Resource budgets | VERIFIED LIVE | Final AWS probe within unchanged bounds; enforcement/crash cases tested offline; no hard OS memory/time guarantee |
| GitHub Actions definitions | VERIFIED OFFLINE ONLY | Six production workflows preserved; new manual-only verification workflow added with owner/revision/write approval gates. Default-branch registration completed via PR #7; owner dispatch pending |
| Scheduled automation | BLOCKED | Deliberately disabled/unset; activation is not part of this task |

## Verification commands and results

```bash
uv run pytest -q --cov=website_agent --cov-report=term --junitxml=artifacts/live-verification-tests.xml
uv run ruff check src scripts tests
uv run ruff format --check src scripts tests
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file artifacts/audit-requirements.txt
uv run pip-audit -r artifacts/audit-requirements.txt --no-deps --disable-pip
git diff --check
uv run website-agent doctor
```

Final suite: **168 passed, 0 failed, 1 skipped, 80% coverage in 35.18 seconds**, Python 3.13.14. The only skip requires `TEST_DATABASE_URL` for actual PostgreSQL migration/lock testing. Real Chromium desktop/mobile tests ran locally; they used fixture deployment content, not a live Netlify deployment. The worker subprocess actually runs in its fixture test but its statements are not included in parent-process coverage. No failure was removed or assertion weakened; taxonomy fixtures were updated to assert the actual new category ID.

The manual-verification module has 29 offline tests covering owner/revision/approval gates, read-only transactions, metadata-only account requests, scope uncertainty, secret/report isolation and failure reporting. No fixture result is claimed as a live account result.

Ruff and formatting passed. Locked runtime dependency audit: **no known vulnerabilities found** (advisory scan, not certification). Workflow YAML/ref/blob checks and disabled country-policy checks passed. The earlier local `doctor` reported missing credentials; that result does not describe GitHub Secrets. Secret names are now confirmed at repository scope, but credentialed checks remain NOT RUN.

## Safe next steps and recovery

1. Follow [manual live verification](MANUAL_LIVE_VERIFICATION.md) using the existing GitHub Secrets. Registration is complete via merged PR #7; leave PR #6 unmerged. Review included account quotas and the database destination, then dispatch diagnostics on the reviewed feature SHA. No secret recreation or local `.env` is required.
2. Keep `AUTOMATION_ENABLED=false`, `ENABLE_SENDING=false`, `ENABLE_ROUTINE_REPLIES=false` and country policies disabled. The new workflow hardcodes these gates and does not alter production settings.
3. Review sanitized database and account diagnostics. Missing schema/migration checksums or storage headroom block discovery; any necessary database preparation requires separate owner authorization. This workflow does not run migrations. Account metadata does not prove free generation/deployment quota or long-term OAuth token validity.
4. Only after explicit owner approval via a separate discover dispatch, execute isolated US discovery during its configured research window. Never substitute `daily`. Inspect aggregate inserts, verified websites, resource counters and status. Deferred/timeout outcomes require checkpoint inspection before another fresh approval; do not erase history/suppressions or reset ambiguous operations.
5. OSM remains blocked pending a real bounded XML extract and runner staging, reviewed ODbL obligations, or an actually authorized private/contracted endpoint. The investigated 474 MB Geofabrik New York PBF exceeds current limits and is not directly supported by the XML reader. See the launch guide's source-linked investigation; no provider permission or setting was changed.
6. The new diagnostics use read-only database transactions. Existing `doctor --live` persists model-check state and is not used. No generation, deployment, draft or mail send is included in this workflow. Account-specific free-tier and billing controls must be verified by the owner before dispatch.
7. Gmail external OAuth Testing normally expires refresh tokens after seven days for these Gmail scopes. Review publishing status and applicable sensitive/restricted-scope verification, then reauthorize securely as required. Publishing does not guarantee permanent tokens; revocation/account policy can still require owner recovery. No prospect sending or routine replies may be enabled without separate authorization and validated Base44 history/audience separation and legal-basis evidence.

The default Gemini monetary cap is an existing upper bound, not proof of free usage. Hosting, Supabase storage and Actions allowances are account-specific; this task activated no billing and bought nothing. Dataset budgets are per invocation, not a promise of result count or unlimited daily free infrastructure. The operational verdict remains blocked until owner review and authorized live verification are completed.

Primary references: [official Overture distribution/catalog](https://docs.overturemaps.org/getting-data/cloud-sources/), [Places schema](https://docs.overturemaps.org/schema/reference/places/place/), [taxonomy CSV](https://docs.overturemaps.org/taxonomy/2026-09-23.0/taxonomy.csv), [source attribution](https://docs.overturemaps.org/attribution/), [Google OAuth refresh-token expiration](https://developers.google.com/identity/protocols/oauth2#expiration). [PR #6](https://github.com/Nipun33333/GLOBAL-WEBSITE-AGENT/pull/6) contains the final commit and validation record.
