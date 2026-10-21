# Global Website Agent — one-click operation

The single GitHub Actions workflow is `.github/workflows/global-website-agent.yml`.

## Manually launch

Open **Actions → Global Website Agent → Run workflow**, leave the branch on **main**, then press **Run workflow**. There are **no required input fields** and no country, mode, SHA, or approval phrase to paste.

A manual launch performs one `daily` pipeline invocation. It selects an eligible configured country/city through persistent fair rotation; it does **not** search every country at the same instant. Business category and website checks remain required. One newly selected prospect may be audited and qualified per invocation, and at most one new initial email may be sent per invocation, subject to all recipient and sending gates. The app can still resume an existing verified draft from the queue.

The live invocation is not a mock. It uses GitHub Actions Secrets stored in this repository's `agent-runtime` environment. A real database and correct migrations are required. Only the repository owner can manually dispatch; the checked-out Git SHA must match the workflow event. Credential values are never requested in the form or uploaded in artifacts.

## Daily schedule (Asia/Kolkata)

| India time | UTC schedule |
|---|---|
| 3:00 PM IST | `30 9 * * *` |
| 9:00 PM IST | `30 15 * * *` |

These are separate daily checkpoint slots. GitHub Actions scheduled starts may be delayed or skipped by the platform, so exact-to-the-minute execution is not guaranteed.

Scheduled execution remains **disabled until the owner reviews quotas and the destination database**. To activate it *once* under repository **Settings → Secrets and variables → Actions → Variables**, review and set:
- `AUTOMATION_ENABLED=true`
- `UNIFIED_WORKFLOW_ENABLED=true`
- `FREE_LIMITS_REVIEWED=true` only after actually checking available included Actions/provider usage
- `DATABASE_REVIEWED=true` only after confirming the dedicated Supabase project, connection, backups and quota
- `SCHEDULED_MODES=daily` (optional; daily is the only scheduled mode)

These are one-time repository settings, not repeated Run workflow inputs. Do **not** set the review flags without performing the reviews.

## Capability safety and costs

The owner may authorize independent capabilities through existing repository variables **only after verifying account usage and source rights**:

- `ALLOW_GENERATION=true` requires valid and current Gemini model capabilities, model pricing, and explicit free/authorized usage records.
- `ALLOW_DEPLOYMENT=true` requires included Netlify capacity and valid site permissions.
- `ALLOW_DRAFTS=true` permits creating Gmail drafts and requires working OAuth credentials.
- `ALLOW_SENDING=true` **and** `ENABLE_SENDING=true` are both required even to consider real sends.

These flags alone **cannot** bypass the existing country policy, legal-basis evidence, observed business mailbox, unsubscribe suppression, Base44 audience partition, review of email copy, recipient hours, Gmail identity or daily sending limits. Every country policy remains disabled until independently reviewed. Never mark a country or contact eligible without actual permission/evidence.

Automatic follow-up sends and automatic customer replies are disabled. Customer conversations remain owner-handled.

Current Gemini `model_prices` and `usage_authorizations` are empty; AI generation will defer safely until actual current model eligibility and pricing have been reviewed. Overture discovery does not need `DISCOVERY_API_KEY`. OSM remains unconfigured until license and dataset obligations are satisfied.

### Supabase connection setup for GitHub-hosted runners

The database preflight keeps `sslmode=verify-full` and requires a session-persistent PostgreSQL connection (session advisory locks are used). GitHub-hosted runners may not have the IPv6 routing needed for a Supabase **direct** database endpoint. The supported IPv4-friendly alternative is the **Session pooler** URL from the existing Supabase project's **Connect → Session pooler**, using port **5432** and username `postgres.[PROJECT_REF]`. The **Transaction pooler** on port **6543** is intentionally rejected. Copy the exact connection details from Supabase; do not guess the pooler hostname or expose the password. Update the existing `DATABASE_URL` only through **GitHub → repository Settings → Secrets and variables → Actions**, not in chat.

Supabase recommends your project's trusted database root certificate for verified TLS. Obtain it in the project's **Database settings → SSL configuration → Download certificate**. If the runner cannot verify its TLS certificate with the normal public CA bundle, add a **repository or `agent-runtime` environment Secret** named `SUPABASE_CA_CERT_PEM` containing the certificate's complete PEM text. The workflow writes the certificate to a temporary `0600` file and deletes it after the command. The CA certificate is public trust material, but storing it as a Secret avoids accidental log exposure. Never disable TLS verification to bypass a certificate error.

Sanitized `database.status` may be one of:
- `tls_certificate_verification_failed` — check the project's verified root certificate and hostname.
- `database_network_or_ipv6_unreachable` — use the project's Session pooler when direct IPv6 access is unavailable.
- `database_dns_resolution_failed` — check the host copied from the project's Connect page.
- `database_connection_timed_out` / `database_connection_refused` — check running project, availability and network.
- `authentication_rejected` / `pooler_tenant_or_user_unavailable` — check account credentials and session-pooler username; rotate **only** the affected database secret if necessary.
- `transaction_pooler_not_supported` / `database_url_missing_required_parts` / `unsupported_database_driver` — replace an unsuitable URL with a permitted Session pooler or reachable direct URL.
- `blocked_missing_migrations` / `blocked_schema_drift` — requires a separately authorized schema migration review.

A stored Secret is intentionally unreadable from GitHub. None of these checks reveals secret values. The GitHub workflow remains disabled for automatic production execution until its existing account/cost gates are reviewed.

### Account diagnostics on a blocked manual run

A one-click manual run attempts a bounded, credentialed database/schema preflight before any prospect writes. If the database is unavailable, it now publishes a sanitized database status such as `authentication_rejected`, `database_or_schema_missing`, `connection_tls_or_configuration_unavailable`, or `missing_database_url`. It also performs read-only Gemini model-metadata, Netlify existing-site access and Gmail mailbox-identity checks, using existing GitHub Secrets. No model generation, site deployment, Gmail draft creation or email sending occurs in these checks.

These provider probes run only for an owner-initiated manual invocation when the database preflight is blocked, not on the two scheduled ticks. Missing or invalid account credentials are not retrievable from GitHub; rotate only the affected secret through its provider and GitHub Settings. A model listed in public Google documentation still requires separate proof of free account allowance and a current `gemini.usage_authorizations` entry.

The **21 October 2026** live workflow run [#39649523233](https://github.com/Nipun33333/GLOBAL-WEBSITE-AGENT/actions/runs/39649523233) passed GitHub checkout, SHA validation and dependency installation, but exited in `Execute approved operation` without publishing the underlying problem. The improved error-status reports were committed **after that run** and have not yet been exercised in a new live GitHub Actions run.

### What a failed or deferred run means

Read the job summary and the sanitized `agent-result-...` artifact. Status `blocked_database_preflight` means database connection/schema/migration requirements remain unsatisfied. `deferred` means persistent capacity/source recovery conditions need attention. A successful provider dataset query is not proof of a verified business, deployment or sent email.

Rerunning an old failed job is deliberately blocked; launch a **new** manual run when appropriate. Do not clear database checkpoints, history, suppressed contacts or ambiguous send/deploy records to force success.

### Important operational limitations

The workflow and application code can now start through one button. **A functioning end-to-end real send is not yet verified.** Real Supabase/Gemini/Netlify/Gmail tests and source/recipient eligibility must succeed independently; GitHub Secrets cannot be read back or assumed valid merely because their names exist. This project cannot guarantee a qualifying business or a completed email at every execution.
