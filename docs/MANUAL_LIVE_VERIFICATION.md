# Owner-controlled live verification

This workflow uses the existing repository secrets through `agent-runtime`. Do not copy secrets into chat or a local `.env`. It has not been dispatched. PR #6 stays open and unmerged. The six existing production workflows, their schedules, sending permissions and settings remain unchanged; `tests.yml` remains absent.

## Confirmed configuration and remaining prerequisites

Read-only GitHub inspection on 21 October 2026 confirmed this repository is private, Actions is enabled, and `agent-runtime` exists. All 12 required repository secret names are present: DATABASE_URL, GEMINI_API_KEY, NETLIFY_AUTH_TOKEN, NETLIFY_SITE_ID, GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN, SENDER_NAME, SENDER_EMAIL, REPLY_TO, SENDER_POSTAL_ADDRESS and OWNER_EMAIL. Secret values were neither retrieved nor changed. `DISCOVERY_API_KEY` is unnecessary for Overture.

The environment currently has no required-reviewer protection rules. The implemented approval gates are an owner-only manual dispatch, explicit review inputs, the exact reviewed feature SHA, and a separate discovery approval phrase. Do not mistake these for a configured environment approval queue. Existing environment settings were not changed.

Before **each** dispatch, the owner must check:

1. **Included usage:** in GitHub account Settings → Billing and licensing → Usage, confirm at least 15 included standard Linux runner minutes and sufficient artifact storage remain, including competing account usage. Review existing spending controls so this run cannot cause paid overage; do not activate billing. Private repository Actions usage is account-wide and plan-dependent. The billing usage API was unavailable to the current authentication, so remaining allowance has **not** been independently verified. No new token/scope is requested. Artifacts are two small sanitized reports retained for one day; this workflow does not create an Actions cache. [GitHub billing documentation](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
2. **Database:** confirm the existing `DATABASE_URL` targets this agent's intended Supabase database, with `postgresql+psycopg://`, a direct or session-mode connection on port 5432, and sufficient included database/egress capacity. Transaction pooling on 6543 is rejected. TLS hostname/certificate verification is enforced using the CA bundle. The runtime verifies read-only transactions, required tables, migration checksums and database size below the existing 400 MiB application ceiling. That ceiling does not prove the account's free quota or the intended database identity; the owner must confirm both. Missing migrations block discovery; this workflow never applies migrations.
3. **Account quotas:** check the existing Gemini project, Netlify site/team, Gmail account and Supabase allowances without enabling paid services. Account-specific remaining quotas are not generally established by the metadata APIs used here. There is no Gemini generation, Netlify deployment, Gmail draft/send or billing API call. Diagnostics make at most five configured-model metadata GETs, one existing-site GET, one OAuth refresh and one Gmail profile GET, without retries. [Gemini model metadata](https://ai.google.dev/api/models), [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing), [Netlify API](https://docs.netlify.com/api-and-cli-guides/api-guides/get-started-with-api/), [Gmail quotas](https://developers.google.com/workspace/gmail/api/reference/quota).
4. **Research window:** diagnostics report the current US local-window status without visiting prospect websites. Discovery rechecks the existing configured local weekday/holiday-aware 08:00–20:00 window before launching. The current US location uses `America/New_York`; daylight-saving changes are handled by the timezone database. A closed window blocks discovery rather than overriding the schedule. No schedule or window setting changes are needed.

## Register the workflow without merging PR #6

GitHub requires the workflow file on the default branch before `workflow_dispatch` can launch it on another branch. A feature-only push does **not** make this new workflow runnable. [Official manual-run instructions](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow?tool=webui).

The owner should separately review and register **only** `.github/workflows/manual-live-verification.yml` on `main`. One explicit GitHub UI route is:

1. Open that file on `feature/free-overture-discovery`, inspect it and copy its full contents.
2. Switch to `main`, choose **Add file → Create new file**, enter `.github/workflows/manual-live-verification.yml`, and paste those exact contents.
3. Choose **Create a new branch for this commit and start a pull request**. Confirm its diff contains only this new workflow, then review/merge that registration PR. Do not merge PR #6 or copy any of its application changes to main.
4. Verify **Manual live verification** appears under Actions. The application code is checked out from `feature/free-overture-discovery`; selecting `main` for a run causes the job to be skipped.

No registration commit, registration PR, merge or dispatch has been performed by the agent. Creating/merging that narrowly scoped registration is an owner action, separate from approving prospect writes.

## Launch diagnostics first

Review the feature changes in PR #6 and obtain its full 40-character head SHA, for example:

```bash
gh pr view 6 --repo Nipun33333/GLOBAL-WEBSITE-AGENT --json headRefOid --jq .headRefOid
```

As the `Nipun33333` owner, open **Actions → Manual live verification → Run workflow**. Select branch `feature/free-overture-discovery`, mode `diagnostics`, enter that reviewed SHA, tick `free_limits_reviewed` and `database_reviewed` only after the checks above, and leave `write_approval` empty. Then click **Run workflow** yourself.

Equivalent owner command (replace `REVIEWED_40_CHARACTER_SHA`):

```bash
gh workflow run manual-live-verification.yml --repo Nipun33333/GLOBAL-WEBSITE-AGENT --ref feature/free-overture-discovery -f mode=diagnostics -f reviewed_commit=REVIEWED_40_CHARACTER_SHA -f free_limits_reviewed=true -f database_reviewed=true
```

Inspect the job summary and the `live-verification-<run-id>-1` artifact. Only `live-verification.json` and `live-verification.md` are uploaded. The database uses read-only transactions and rolls back; there are no prospect, model-state or migration writes. The existing `doctor --live` command is deliberately not called because it persists model-check state. OAuth refresh obtains an access token but does not mutate the mailbox.

`verified_metadata` for Gemini means the configured primary model advertises generation support, not successful generation or free quota. Netlify verifies access to the existing site, not deployment. Gmail verifies refresh, mailbox identity and returned required scopes; missing/unreturned scopes are reported as blocked, not assumed valid. OAuth publishing status and long-term token validity still require owner review. A green diagnostic result is not permission to activate production.

## Separately approve discovery writes

Only after reviewing diagnostics and confirming the database destination, included capacity and research window, start a **new** dispatch on the same reviewed feature revision. Select mode `discover`, repeat the review inputs, and type exactly **`APPROVE_US_DISCOVERY_WRITES`** in `write_approval`. Submitting this separate dispatch is the owner's explicit approval to insert verified prospects and persist discovery run/checkpoint records in the existing database.

Equivalent owner command:

```bash
gh workflow run manual-live-verification.yml --repo Nipun33333/GLOBAL-WEBSITE-AGENT --ref feature/free-overture-discovery -f mode=discover -f reviewed_commit=REVIEWED_40_CHARACTER_SHA -f free_limits_reviewed=true -f database_reviewed=true -f write_approval=APPROVE_US_DISCOVERY_WRITES
```

Diagnostics run again first. A failed database preflight prevents discovery. Gemini/Gmail/Netlify failures remain visible but do not prevent the isolated discovery command, which does not depend on them. The wrapper invokes exactly the Python CLI equivalent of `website-agent discover --country US`, strips account credentials from that child except its required database URL, and forces sending/routine replies/automation false. There is no `daily`, generation, deployment, outreach, mailbox mutation or billing action.

The existing discovery budgets remain unchanged: 30 accepted records, 120 candidates, 160 requests, 64,000,000 payload bytes, 128,000,000 managed file bytes, 512 MiB worker RSS and 300 seconds. The wrapper bounds the child to 420 seconds and the job to 15 minutes; limits do not guarantee results. Shared runtime concurrency and the CLI's existing database advisory lock serialize work. Discovery persists partial progress and may defer; a timeout means inserts may already have occurred and requires checkpoint inspection, not a claim of zero writes.

Reports export only allowlisted aggregate counters from this invocation, such as `official_websites_verified`, `businesses_inserted`, requests, bytes and outcome. They exclude business names, contacts, URLs, tokens, database addresses and arbitrary exception text. Normal historical reports are not uploaded and the child's GitHub summary output is disabled. No workflow run has yet produced real counts; do not interpret offline fixture counts as live results.

Changed branch tips fail the reviewed-SHA check before credentials load. Re-runs using GitHub's **Re-run jobs** button are blocked; every attempt requires a fresh owner dispatch. A deferred result is not success. Inspect the sanitized status and, through authorized database administration, its persistent checkpoint before approving a later retry. Never erase suppression/history state or reset ambiguous operations. Keep PR #6 open until the authorized verification has been evaluated.

## OSM fallback investigation

OSM is **not currently operational**: `osm_extracts` is empty, the license-review reference is empty, database-obligation acceptance is false, and no authorized private/contracted Overpass endpoint is configured. No provider authorization has been inferred or granted.

The [Geofabrik New York download page](https://download.geofabrik.de/north-america/us/new-york.html), inspected on 21 October 2026, listed a 474 MB PBF state extract. That exceeds the current transfer and managed-file budgets; the existing reader accepts bounded XML nodes, not PBF. No extract was downloaded. Regional download availability alone does not establish the appropriate license compliance, commercial backend permission or free compute for conversion.

A feasible next setup is an owner-prepared, geographically bounded XML extract with eligible business nodes, required address/website/name fields, real release date, SHA-256, and provenance, supplied through a separately reviewed staging mechanism to the Actions runner. A file in local ignored `private/` will not automatically exist on GitHub-hosted runners. Follow the existing [OSM configuration schema](DISCOVERY.md); do not mark the license/obligation flags accepted until the owner has reviewed the intended use. ODbL requires attribution and has database redistribution obligations; see [OpenStreetMap licensing](https://www.openstreetmap.org/copyright). This report does not grant rights or resolve a particular derived-database licensing question.

Alternatively configure a private/contracted endpoint only with actual documented authorization and acceptable resource limits. Shared community Overpass infrastructure is not assumed to authorize an unattended commercial discovery backend; see the [operator's commons guidance](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html). No endpoint, provider permissions or fallback settings were changed. Overture AWS/Azure and validated-cache paths remain the implemented zero-key discovery paths while OSM setup is pending.
