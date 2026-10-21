# Setup guide

Use only this repository and dedicated infrastructure for this agent. Do not reuse or change Base44's database or workflows.

## 1. Persistent PostgreSQL

Create a dedicated PostgreSQL database, for example in Supabase, using your own account. The application never provisions or purchases it. Use a direct connection or **session-mode** pooler. Transaction-mode poolers are incompatible with the session-level advisory lock and must not be used.

Configure `DATABASE_URL` as a SQLAlchemy psycopg URL:

```text
postgresql+psycopg://USER:URL_ENCODED_PASSWORD@HOST:5432/DATABASE?sslmode=verify-full
```

Use your provider's CA configuration where necessary. Production requires PostgreSQL; SQLite is accepted only by explicit test construction. The migration command creates the fourteen application tables plus `schema_migrations`, with unique keys, foreign keys and indexes. Every SQL migration is checksummed; previously applied migrations cannot be silently changed. Back up the database before future migrations.

```bash
uv run website-agent migrate
```

Run migrations with a dedicated migration role if possible. Restrict the runtime role to application tables and schema usage. Never expose these tables through a public Supabase API. Configure RLS/network access and backups according to your deployment. The application is server-side and does not need Supabase's public anon key.

## 2. Gemini

Create an authorized Gemini API key and configure `GEMINI_API_KEY`. The official Google GenAI SDK calls model metadata before generation. The requested default is `gemini-3.8-flash`; access to this model has **not** been verified with your account. `GEMINI_ADVANCED_MODEL=gemini-4-argon` is reserved configuration, not automatically invoked. Set `GEMINI_MODEL` to it explicitly to request that model for a run. Set `GEMINI_FALLBACK_MODELS` to a comma-separated list only if you deliberately authorize those models. Unavailable models do not trigger guessed substitutions. Rate-limit errors do not trigger fallback as a quota bypass.

Enter verified current prices for each enabled model in `config/settings.yml`:

```yaml
model_prices:
  YOUR_VERIFIED_MODEL:
    input_per_million: YOUR_CURRENT_INPUT_PRICE
    output_per_million: YOUR_CURRENT_OUTPUT_PRICE
```

Use numeric values, not the placeholders. An explicit `0.0` is appropriate only if you have confirmed free usage for your actual account and workload. Costs include reported input, output and thinking tokens; an in-flight reservation remains charged to the local cap when actual billing is unknown. The ledger is an estimate, not a replacement for provider billing alerts. Long inputs and output sizes are bounded. Successful structured requests are cached in PostgreSQL.

References: [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output), [available models](https://ai.google.dev/gemini-api/docs/models).

## 3. Discovery authorization

The default `discovery_provider: open_data` requires **no paid discovery key**. Overture reads the verified pinned public Places release from its official AWS/Azure distribution. Optional OSM regional extracts and a private/contracted Overpass endpoint require explicit license/provider-use configuration. See [zero-key discovery](docs/DISCOVERY.md) for resource budgets, provenance, verification, recovery and a discovery-only command.

The existing optional paid adapters remain available when explicitly selected:

- **Brave Search API**: authorized HTTPS calls to the web-search endpoint with country/search/limit configuration. Results are candidates; the business website must still be independently researched and qualified.
- **Licensed JSON API**: an authenticated HTTPS GET endpoint of your authorized provider using `q`, `country`, `city`, and `limit`. Response contract:

```json
{"businesses": [{"provider_id": "stable-authorized-id", "name": "Business name", "url": "https://business.example"}]}
```

For these optional paid adapters only, set `DISCOVERY_API_KEY` and select `brave` or `licensed_json` in YAML. For `licensed_json`, supply `discovery_endpoint`. Both adapters require `storage_and_outreach_use_authorized: true` and a nonempty `provider_agreement_reference` after checking your agreement. This attestation is an operational gate, not an automatic legal review.

Brave's standard offering does not universally grant result-storage rights, and its terms restrict certain unsolicited mass-email uses. Do not enable this adapter merely because you have an API key. Obtain the necessary rights or use an appropriately licensed provider. See [Brave API storage FAQ](https://brave.com/search/api/) and [provider terms](https://api-dashboard.search.brave.com/documentation/resources/terms-of-service).

Public research honors robots.txt, refuses restricted/private network addresses, caps response size, samples at most three same-domain links, and collects observed same-domain role mailboxes. Personal names are not used to guess addresses. A reviewer can import a verified business mailbox with its evidence reference when automatic role-mailbox detection cannot find one.

## 4. Gmail OAuth

Enable Gmail API in your own Google Cloud project and configure an OAuth consent screen. Use a Desktop OAuth client for the local authorization helper. Add only the sender account as a test user when appropriate. For an external consent screen in Testing, Google normally expires refresh tokens after seven days unless only basic identity scopes are requested; this application requests Gmail scopes, so that exception does not apply. Move to the appropriate publishing status, complete Google's applicable sensitive/restricted-scope verification requirements, then reauthorize securely when required. Publishing alone does not guarantee token permanence: revocation, inactivity and account policies can also invalidate it. Do not automate repeated reauthorization or paste tokens into chat. [Google refresh-token expiration rules](https://developers.google.com/identity/protocols/oauth2#expiration).

Requested scopes:

```text
https://www.googleapis.com/auth/gmail.compose
https://www.googleapis.com/auth/gmail.readonly
```

Compose permits drafts and sending; readonly is necessary for identity, sent verification, prior-contact scans, replies, and suppression. The application does not request full mailbox deletion access. No credentials are printed.

Download the OAuth client JSON into the ignored `private/` directory. Set `GMAIL_OAUTH_CLIENT_FILE` to that file's path, then run:

```bash
uv run python scripts/gmail_oauth.py
```

The helper opens Google's authorization flow and saves `private/gmail-token.json`. Put the client ID, client secret, and returned refresh token into GitHub Secrets. Never paste them into issues, logs, or committed files. Protect or remove the local private copies after saving them securely.

The configured sender must exactly match Gmail's `users.getProfile` mailbox. Reply-to must use this same monitored mailbox; aliases are intentionally unsupported. Populate the actual verified postal address and display name. Set the mailbox/identity fields as secrets even though some will appear legitimately in outgoing email.

References: [Gmail API](https://developers.google.com/workspace/gmail/api/reference/rest), [sending messages](https://developers.google.com/workspace/gmail/api/guides/sending).

## 5. Exact GitHub secrets and variables

Configure the repository's `agent-runtime` GitHub Environment (or repository secrets inherited by that environment). None were present during implementation.

| Secret | Purpose |
|---|---|
| `DATABASE_URL` | Dedicated persistent PostgreSQL connection |
| `GEMINI_API_KEY` | Authorized Gemini API access |
| `DISCOVERY_API_KEY` | Optional paid discovery provider; unused in default `open_data` mode |
| `NETLIFY_AUTH_TOKEN` | Deployment access to the dedicated hosting project |
| `NETLIFY_SITE_ID` | Existing dedicated Netlify project ID |
| `GMAIL_CLIENT_ID` | Google OAuth client |
| `GMAIL_CLIENT_SECRET` | Google OAuth client secret |
| `GMAIL_REFRESH_TOKEN` | Sender's authorized offline access |
| `SENDER_NAME` | Honest sender display name |
| `SENDER_EMAIL` | Actual OAuth mailbox |
| `REPLY_TO` | Same monitored sender mailbox |
| `SENDER_POSTAL_ADDRESS` | Verified physical business postal address |
| `OWNER_EMAIL` | Owner identity / internal smoke draft recipient |

Repository variables: `AUTOMATION_ENABLED` (default unset/false), `ENABLE_SENDING` (default false), `ENABLE_ROUTINE_REPLIES` (default false), `GEMINI_MODEL`, `GEMINI_ADVANCED_MODEL`, `GEMINI_FALLBACK_MODELS`.

Local configuration reads `.env`; copy `.env.example`, then populate values securely. Do not place real secrets in workflow YAML.

## 6. Verification sequence

```bash
uv run website-agent doctor
uv run website-agent migrate
uv run website-agent doctor --live
uv run website-agent live-smoke
uv run website-agent daily
uv run website-agent report --days 7
```

Read-only doctor checks do not verify generation, quota affordability, provider rights, or successful deployments. The live smoke test invokes paid/quota-bearing APIs only when explicitly run after configuration. It drafts to the owner, never sends. `daily` runs the actual discovery-to-draft pipeline. Check PostgreSQL and the run report; AI assertions are never deployment/send proof.

## Current live setup prerequisite

See [LIVE_READINESS_REPORT.md](docs/LIVE_READINESS_REPORT.md) for measured evidence. GitHub Secrets cannot be read back and are not downloaded by this task. Configure existing credentials directly in the ignored local `.env` file using your own secure process. Never paste credentials in chat or commit the file. Discovery-only needs `DATABASE_URL`; model, hosting and Gmail checks separately need their existing settings. Keep `AUTOMATION_ENABLED=false`, `ENABLE_SENDING=false`, and `ENABLE_ROUTINE_REPLIES=false`. Do not activate billing. Confirm actual account free usage before `live-smoke`; a configured API key alone does not establish that.
