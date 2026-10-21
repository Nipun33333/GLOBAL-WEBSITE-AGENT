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

**Owner-authorized automation is now enabled in the workflow on main.** Both UTC cron entries launch the normal `daily` pipeline automatically. No GitHub Actions variables, repeated approval forms, or false billing/database review attestations are required for scheduled dispatch. GitHub Actions may delay or skip a scheduled run, and included Actions, database, Gemini and Netlify capacity are finite. The code still enforces bounded daily model requests, one new business per invocation, two daily previews, up to two initial emails per day, Free-Tier-only Gemini fallback, and safe persisted retries.

To stop automatic work, use **GitHub → Actions → Global Website Agent → ⋯ → Disable workflow**. This does not erase checkpoints or contact suppression records. Automatic customer replies and follow-up emails are intentionally disabled, since the owner handles customer responses.

## Capability safety and costs

**Production technical capabilities are enabled for both owner manual and twice-daily scheduled runs:** Gemini generation, Netlify draft deployment, Gmail draft preparation, and initial email sending. No paid Gemini fallback was enabled. The agent uses existing GitHub Secrets and never uploads credential or recipient content to its public run artifact.

**These capabilities do not establish that any prospect is legally eligible for cold email.** Sending remains fail-closed until a real verified business mailbox, independently approved jurisdiction rule, current case-specific legal basis, documented Base44 audience separation/history import, suppression checks, approved copy and a verified Netlify demo all exist. All 11 country rules are still disabled, so recipient emails are currently blocked even though the technical switches are on. Do not invent compliance evidence or overwrite opt-outs to force a send. Existing or pending drafts may still be generated, but this is not evidence of a sent email. Gmail OAuth may expire and provider quotas may be exhausted.

The reviewed operating limits are in `config/settings.yml`: one discovery target/inspection/qualified business per run; at most two previews and two initial outreach messages per day; maximum 12 AI requests per day; no automatic followups, no routine replies. Control exceptional costs by monitoring GitHub Actions, Supabase, Gemini and Netlify allowances, or temporarily disabling the workflow.

**Owner review 22 October 2026:** Google AI Studio's `Default Gemini Project` Free tier shows nonzero RPM/TPM/RPD quotas for Gemini 3.8 Flash, 3.6 Flash, 3.5 Flash-Lite and 3.1 Flash-Lite. Public Google pricing lists no charge for their standard Free-tier text usage. Exact-model usage authorizations in `config/settings.yml` expire **21 November 2026**; daily AI request cap is **12**, paid fallback remains disabled. Availability/rate limits must still be enforced by the provider and can be exhausted. Overture discovery does not need `DISCOVERY_API_KEY`. OSM remains unconfigured until license and dataset obligations are satisfied.

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

### First owner-run: safe initialization of an empty database

If the dedicated Supabase database accepts the verified SSL session connection but has **no public tables yet**, the fresh repository-owner **Run workflow** invocation will now execute the checked-in `database/migrations/001_initial.sql` once, through the existing `website-agent migrate` implementation, to create its application schema and record the migration checksum. It then performs the same read-only schema verification before running `daily`. **This is a real PostgreSQL schema write**, not a mock. It is allowed only for a fresh owner-dispatched run, never by schedules or reruns.

If **any public table already exists** (including a partially migrated agent schema), the bootstrap deliberately refuses to write and emits `schema_bootstrap=bootstrap_requires_review_nonempty_public_schema`. Do not automatically drop or alter existing tables. Review and back up existing records before planning recovery. A schema-write failure is sanitized as `bootstrap_failed_requires_schema_review`; a second run will not automatically overwrite partial schema.

On a fresh database, the bootstrap may succeed but business discovery may subsequently defer because of location business-hour windows, free-resource budgets, source availability, missing business facts, or disabled generation/deployment/sending permissions. Database readiness alone does not authorize contacting any customer.

### Account diagnostics on a blocked manual run

A one-click manual run attempts a bounded, credentialed database/schema preflight before any prospect writes. If the database is unavailable, it now publishes a sanitized database status such as `authentication_rejected`, `database_or_schema_missing`, `connection_tls_or_configuration_unavailable`, or `missing_database_url`. It also performs read-only Gemini model-metadata, Netlify existing-site access and Gmail mailbox-identity checks, using existing GitHub Secrets. No model generation, site deployment, Gmail draft creation or email sending occurs in these checks.

These provider probes run only for an owner-initiated manual invocation when the database preflight is blocked, not on the two scheduled ticks. Missing or invalid account credentials are not retrievable from GitHub; rotate only the affected secret through its provider and GitHub Settings. A model listed in public Google documentation still requires separate proof of free account allowance and a current `gemini.usage_authorizations` entry.

The **21 October 2026** live workflow run [#39649523233](https://github.com/Nipun33333/GLOBAL-WEBSITE-AGENT/actions/runs/39649523233) passed GitHub checkout, SHA validation and dependency installation, but exited in `Execute approved operation` without publishing the underlying problem. The improved error-status reports were committed **after that run** and have not yet been exercised in a new live GitHub Actions run.

### Verified discovery cooldown behavior (October 22, 2026)

The real [Run #39661666331](https://github.com/Nipun33333/GLOBAL-WEBSITE-AGENT/actions/runs/39661666331) confirmed an intentionally persisted recovery deadline, not a database or SSL fault. Its sanitized report showed `persisted_status=deferred_resource_limit`, `discovery.reason=waiting_for_persisted_retry`, an earlier `recovery.reason=discovery_deadline`, and `recovery.accepted=2`. It had **zero verified deployments and zero sent mail**.

The worldwide discovery target is now **one newly verified business per invocation**. Existing discovered businesses, checkpoint cursors, cooldowns and suppression data are preserved. Do not clear or manually bypass the stored `next_at` (the above historical example was `2026-10-21T20:16:35Z`, which is **22 October 2026 at 1:46 AM IST**).

A recognized, safely persisted discovery cooldown without failed stages returns GitHub job success with a **notice**, but the run artifact truthfully says `status=deferred_retry_scheduled`, `exit_code=2` (the application CLI), and provides the recovery timestamp. This is **not** a successful deployment, verified new prospect email, or completed website generation. Unexpected crashes, missing checkpoint evidence, stage failures and permissions errors still fail the job. Scheduled follow-up remains subject to the owner-reviewed automation setting.

### What a green run with zero emails means

An actual [owner run on 21 October 2026](https://github.com/Nipun33333/GLOBAL-WEBSITE-AGENT/actions/runs/39670203638) reported `sending_enabled=true` and one independently verified discovery candidate, but `sites=0`, `messages=0`, `drafts_created=0`, and `sent=0`. Technical sending enablement was **not** the missing step: no preview or Gmail draft existed to send. Actual diagnosis must distinguish missing audit qualification from verified previews with non-eligible recipients.

A fresh run now audits **up to 3** already-verified business candidates to select **at most 1** qualified demo (before this change it only checked 1). Safe run reports also include `run_diagnostics.stage_event_counts` for that exact run (e.g. `inspected`, `qualified`, `strong_website_disqualified`, `website_generated`, `email_drafted`) and aggregate `run_diagnostics.business_funnel` grouped by prospect status. These counts have no customer names, mailbox addresses, or website URLs. If all candidates have sufficiently good websites, unverifiable local-business evidence or no observed business mailbox, a correct run may generate no demo or send nothing rather than fabricate a lead.

The project still has **11 disabled country sending policies** and lacks verified Base44 contact-history/exclusive-audience readiness. These are independently blocking legal/recipient checks even if Gemini, Netlify, and Gmail work technically. They are not automatically enabled or marked approved; obtain genuine country-specific compliance and audience evidence before contacting people.

### What a failed or deferred run means

Read the job summary and the sanitized `agent-result-...` artifact. Status `blocked_database_preflight` means database connection/schema/migration requirements remain unsatisfied. `deferred` means persistent capacity/source recovery conditions need attention. A successful provider dataset query is not proof of a verified business, deployment or sent email.

Rerunning an old failed job is deliberately blocked; launch a **new** manual run when appropriate. Do not clear database checkpoints, history, suppressed contacts or ambiguous send/deploy records to force success.

### Important operational limitations

The workflow and application code can now start through one button. **A functioning end-to-end real send is not yet verified.** Real Supabase/Gemini/Netlify/Gmail tests and source/recipient eligibility must succeed independently; GitHub Secrets cannot be read back or assumed valid merely because their names exist. This project cannot guarantee a qualifying business or a completed email at every execution.
