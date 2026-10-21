# Zero-key discovery and recovery

`discovery_provider: open_data` is the default. No discovery API key, Gemini call, Gmail access or Netlify access is needed for `website-agent discover`. A persistent PostgreSQL/Supabase connection remains necessary. This change does not enable automation or sending, alter secrets, modify production workflows or restore the removed test workflow.

## Source and search sequence

1. **Overture Places**: anonymous HTTPS byte ranges against the official AWS distribution. The default release is `2026-09-23.1`, verified against Overture's published catalog on 21 October 2026. `release: latest` resolves the official STAC root. Readers support both legacy `categories.primary` and current `taxonomy.primary`; unsupported structures fail closed. The official STAC collection and every indexed item are checked for completeness; per-file bounds select overlapping GeoParquet assets before footer reads. Matching row groups and selected column chunks are read with coalesced HTTP ranges (at most 64 KiB gaps, 8 MB merged ranges). No S3/Azure global object listing is scanned. Paged/inconsistent STAC indexes fail closed rather than silently truncating coverage. Each scan has a persistent file/group/row cursor.
2. **Official Azure distribution**: used when AWS has a transient outage after bounded retries. A 429 or explicit Retry-After opens a shared Overture circuit instead of changing mirrors. After transient AWS/Azure failure, valid, checksummed, unexpired query caches can serve records. An active rate-limit circuit skips network attempts and may use an applicable cache; permission/schema failures cannot be bypassed with cache. They contain source records, not automatically trusted website verification.
3. **Licensed OSM fallback**: a locally staged, SHA-256-verified regional `.osm` XML extract, or an explicitly authorized private/contracted Overpass endpoint. No public server defaults, server discovery, IP rotation, account rotation or automated global extract downloads.
4. **Geographic fallback**: grow the bounded radius through configured steps, clipped to the named city's search envelope. Optional named `nearby_areas` must stay within the maximum distance and same country. Actual source locality/country and coordinates must match the searched area; a nearby district retains its own name.
5. **Related category fallback**: exact, conservative category IDs and their published taxonomy descendants in `config/discovery-taxonomy.yml`. IDs were checked against the official September taxonomy CSV; a reviewed subset is retained under tests/fixtures and the full-source digest is recorded in the mapping. No substring or model-driven category expansion. The source's actual category is retained in `prospects.niche`; requested niche is recorded separately. A narrow mapping can yield no results.
6. **Next eligible city**: use the existing country-fair scheduler and local working windows, within `max_cities`. Unfinished work is persisted for a subsequent scheduled invocation. Normal pagination progress resets the consecutive no-progress retry counter.

Sources follow `source_priority` for each bounded area/category combination. An empty source result automatically advances the plan. Reaching a resource cap defers the remaining plan rather than pretending it searched everything. New discovery outcomes do not prevent the daily pipeline from processing already queued audits, generation/deployment work and drafts when those operations are safe and configured.

## Verification before admission

Each accepted record needs a stable provider identity, nonempty business name, approved category or published descendant, finite coordinates, matching actual city/country, a valid public HTTPS website, visible name in its title/headings, visible matching locality, and an observed contact link using that website's own domain. Safe canonical redirects are fetched through the existing DNS-pinned, robots-aware client and checked again. Known directories/social/marketplace hosts and search/listing URLs are refused. Missing evidence is `unverified`, counted and skipped; it is never promoted to a prospect just to reach a target.

Domains and provider identities are deduplicated against persisted prospects/sources. Domain and mailbox-domain suppressions from Base44/history imports are checked before website access and again before admission. Unknown audience assignment is **not** invented: the existing per-prospect exclusive Base44 assignment and legal-basis requirements still block email. A discovery identity match is an evidence heuristic, not a legal ownership certification or permission to contact anyone. Subsequent audit/qualification still runs separately.

`business_sources.evidence` stores the actual source ID/provider, dataset release, retrieval and verification times, category, country/city evidence, coordinates, canonical/source URLs, source attribution/license information and original source metadata. No AI invents business records or grants permission.

## Defaults and resource bounds

| Limit | Default |
|---|---:|
| Accepted businesses per invocation | Up to 30, also capped by `limits.discovered` |
| Candidate verifications | 120 |
| Dataset query chunks | 8 |
| Parquet files per query chunk | 8 |
| Data/website HTTP request budget | 160 |
| Discovery response-payload budget | 64,000,000 bytes |
| Managed cache + worker-file capacity | 128,000,000 bytes, split equally |
| Worker RSS threshold | 512 MiB |
| Discovery elapsed-time budget | 300 seconds |
| Source GET attempts | 3, exponential backoff plus jitter |
| Circuit cooldown | At least 1 hour; longer Retry-After respected |
| Empty completed search retry | 24 hours |
| Consecutive retry cycles without progress | 7, then operator review |
| Cities per task / maximum radius | 2 / 25 km |
| Local cache TTL | 168 hours |

The native Parquet reader runs in a disposable child process with metadata size limits, row-group preflight checks, small batches and an RSS/deadline watchdog. A killed reader conservatively consumes its remaining network/request allowance. RSS polling and payload limits are not a kernel-level guarantee against every allocation spike or OS socket buffer. Host/Actions termination can still occur; durable state is the recovery mechanism. Windows workers use hidden processes. Cache writes use fsync and atomic replacement; incomplete temporary files are never treated as completed datasets.

Large row groups, incomplete or oversized STAC indexes, exhausted bytes/disk, unsupported schemas, missing city metadata, blocked robots, or websites without own-domain contact evidence can yield fewer than 30 or zero results. No full global dataset scan is promised within the default budget. XML extracts currently support geolocated nodes; ways/relations without verified centers are skipped. Overpass supports supplied node coordinates/way centers, but still requires actual address locality/country. PBF extraction is not implemented; prepare a bounded XML regional extract with an authorized external tool if needed.

## Persistent recovery and truthful outcomes

The existing database `configuration` table stores `discovery_task:<country-or-worldwide>` plans, next retry times, pending source records, candidate index, scan cursors and provider circuits. Candidate admission and its index advance commit together. City selection and the resulting search plan commit together. Hitting the invocation target preserves unconsumed pending records. Reader version 2 invalidates old global-file cursors/caches; existing prospects, sources and suppressions remain intact. A restart replays the last committed work; domain/source uniqueness prevents duplicate admissions. Partial dataset transfers do not enter the cache. Provider health is shared across Overture mirrors; regional extract failures are scoped by city. Unexpired permitted caches are revalidated for integrity before reuse, and candidate websites are reverified.

The six outcomes are:

- `completed_with_results`: verified records were admitted and the configured scope finished, or the invocation's upper target was met.
- `completed_no_qualified_results`: the accessible configured scope finished with no admissible business. This is an accurate empty result, not a fabricated success count.
- `deferred_provider_unavailable`: temporary source failure, cooldown, or no eligible local research window; persistent next eligible time retained.
- `deferred_resource_limit`: bounded work remains; cursors/pending candidates retained.
- `blocked_permission_or_license`: no available source could legally/operationally run under its configured authorization.
- `failed_requires_operator`: permanent schema/configuration problem or exhausted no-progress retry cycles.

Reports retain partial accepted counts even when the outcome is deferred. They separate dataset files/row groups/records scanned, candidates identified, verification attempts, rejection reasons, known duplicates, inserted businesses, attempted fallback layers, remaining queries/candidates, request/payload usage and elapsed seconds. Cache reuse does not count as a new dataset scan. After an unaccounted worker crash, transfer counters are explicitly labeled conservative upper bounds. Deferred CLI runs return exit code 2; blocked/operator/failure outcomes return nonzero. An optional unconfigured OSM source can be skipped when Overture completely searches the configured scope; the result describes that scope, not unavailable sources. HTTP 429 does not trigger an immediate retry or endpoint substitution.

Provider errors are isolated from other stages. A database outage cannot safely be hidden: the operation stops without acknowledging an uncommitted candidate. If PostgreSQL cannot persist any event, only the sanitized CLI failure and previous committed checkpoint remain. Restore connectivity; rerun the same country scope. The shared advisory lock must be reacquired by a new invocation after connection/ownership loss.

Unknown schemas and repeated failures need an operator to correct the source configuration/schema support. Editing the discovery configuration or reviewed taxonomy creates a fresh task signature. Preserve suppressions, imported history and outreach state. Do not clear those tables to retry discovery. Cached data on an ephemeral Actions runner may disappear; PostgreSQL pending records/cursors survive. Automation still requires the existing `AUTOMATION_ENABLED` gate; this implementation does not turn it on.

## Configure optional OSM access

OSM authorization is independent of its open data license. Set `osm_database_obligations_accepted: true` and a genuine `osm_license_review_reference` only after reviewing attribution, provider terms and ODbL database/share-alike obligations for the intended use. Public availability alone is not that review.

Example extract entry (replace every placeholder with real evidence):

```yaml
osm_extracts:
  - country: US
    city: New York
    path: private/regions/new-york.osm
    sha256: '<verified full-file SHA-256>'
    release: '<actual extract date/version>'
    commercial_use_authorized: true
    agreement_reference: '<reviewed provider terms/reference>'
```

For Overpass, explicitly include `overpass` in `source_priority` and configure all of `overpass_endpoint`, `overpass_private_or_contracted`, `overpass_commercial_use_authorized`, and `overpass_agreement_reference`. There is only one configured endpoint, with small bounded queries. Do not point unattended prospecting at community public instances. Supplying the attestations falsely does not grant permission.

Retain `Â© OpenStreetMap contributors`, the ODbL link and original release/source records. Do not distribute derived OSM databases or public products until their obligations have been reviewed. Overture Places carries permissive source licenses; preserve original source provenance and applicable CDLA, Apache and CC0 license/notice requirements when redistributing. This application stores provenance and keeps OSM disabled until review; it does not automatically establish compliance for every future publication.

Primary references: [Overture cloud catalog and official endpoints](https://docs.overturemaps.org/getting-data/cloud-sources/), [Places schema and licenses](https://docs.overturemaps.org/guides/places/), [Overture attribution](https://docs.overturemaps.org/attribution/), [OSM copyright and ODbL](https://www.openstreetmap.org/copyright), [Overpass shared-server usage](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html).

## Safe discovery-only live test

1. Leave `AUTOMATION_ENABLED`, `ENABLE_SENDING` and `ENABLE_ROUTINE_REPLIES` false/unset. Keep country sending policies disabled. No credential changes are required beyond an existing authorized database connection.
2. Install the committed lockfile: `uv sync --frozen --extra dev`. Apply migrations only after read-only diagnosis, a verified backup and separate owner approval for database changes. No new schema migration is introduced by this change.
3. Review one configured city envelope, category mapping, source license provenance and small budgets. Imported Base44 history/suppressions should already be present; they are not fetched from Base44 by this command.
4. In that city's eligible local research window, run `uv run website-agent discover --country US` (or another configured ISO country). This invokes only discovery/database/report code. Do **not** substitute `daily` or `live-smoke`, which involve other integrations.
5. Inspect `artifacts/report.md`, `workflow_runs`, `run_events`, `business_sources.evidence` and `configuration` task/circuit records. Fewer results, an empty result, or a documented deferral are legitimate. Do not weaken verification to achieve 30.
6. Rerun after the persisted next eligible time to inspect recovery. Keep automatic sending disabled. Production workflow files remain unchanged; a manual local discovery-only command is provided through the separately approved manual-only verification workflow, registered by PR #7. Discovery writes still require explicit owner approval.

## Verification

Deterministic offline tests cover the 30 requested failure categories, including primary/secondary source emptiness/outages, irrelevant and missing websites, geographic/niche/city fallback, permission denial, 429/503, partial transfers, schema drift, quota exhaustion, interruptions, DB-write rollback, persisted resume, duplicate/Base44 suppression and sending-off behavior. They include a real PyArrow Parquet parser over mocked HTTP ranges, a real streaming XML parser, and a real supervised child-process invocation using only local fixture data. No fixture represents a claimed live business.

Current verification and live dataset measurements are recorded in [LIVE_READINESS_REPORT.md](LIVE_READINESS_REPORT.md). The credentialed `website-agent discover --country US` command and real website verification have **not** run: GitHub-hosted execution awaits owner quota/destination review and explicit dispatch/write approvals; local credentials need not be copied. Public dataset probes are real reads, but do not establish verified prospects or production readiness.

For a reproducible, credential-free dataset diagnostic (no website visits, database writes, AI, hosting or mail), run:

```bash
uv run python scripts/probe_discovery.py --country US --city "New York" --niche salons --bbox -74.03 40.70 -73.95 40.78
```

It runs the supervised production data reader with unchanged budgets, prints aggregate metrics and retains source candidates only in ignored `private/discovery-probe-aws.json`. `dataset_probe_only` is explicitly not a discovery/admission success. `--endpoint azure` is available for a deliberate diagnostic; automatic production fallback remains outage-only. Do not use diagnostics to circumvent Retry-After. No new test workflow is created.

The latest public dataset-only probes decoded the same 120 source IDs from AWS and Azure within unchanged bounds. This is not a production failover test or verified-lead admission. Optional configured Overpass requests now use the DNS-pinned public client with redirects refused and bounded retries; OSM remains disabled. See [FINAL_READINESS.md](FINAL_READINESS.md) for measurements and outstanding approvals.
