# Automatic salon demo emails

The UK workflow discovers salons/parlors from public business sources, audits their
websites, uses Gemini for qualification and design, deploys a Netlify demo, verifies
it, then creates and sends a Gmail message with its link. It uses the existing
personal Gmail OAuth connection. No recipient needs to be typed into a workflow form.
Gemini does not invent addresses: email must be published on the business website.

## Active sending mode

The owner-requested workflow sets `OUTREACH_POLICY_MODE=operator_managed`.
This makes legal/provider review an operator responsibility outside the application;
it does not create consent, a corporate-subscriber classification or a legal review.
There is no required `OUTREACH_AUTHORIZATION_JSON` secret in this mode.

The following checks still run before sending:

- GB business in the configured salon category and a qualifying website audit.
- Public same-domain role mailbox (such as info/contact/bookings), observed in a
  mailto link on the business website. Named/personal addresses are not guessed.
- Verified HTTPS demo, freshly checked again immediately before sending.
- Complete sender identity/address; OAuth mailbox must match From and Reply-To.
- No suppression, stopped/imported prospect, prior reply or prior external Gmail contact.
- UK business hours 09:00-17:00, excluding weekends and relevant public holidays.
- Trusted offer copy, sender details and a reply-to-unsubscribe instruction.
- One initial send per invocation, two per day, and no automatic followups/replies.
- Durable Message-ID reconciliation: an ambiguous send is never blindly retried.

These are technical checks, not proof of permission. A public role address does not
prove that a salon is a corporate subscriber. [ICO guidance](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/business-to-business-marketing/)
distinguishes corporate subscribers from sole traders and some partnerships.
[Gmail's policy](https://support.google.com/mail/answer/16734397) prohibits unsolicited
commercial mail; this code setting does not override that policy or guarantee delivery.

## Optional reviewed-record mode

For deployments that require review records enforced by software, set
`OUTREACH_POLICY_MODE=reviewed`. This remains the default for standalone CLI use and
`.env.example`. Configure real country-policy and per-recipient evidence using the
existing policy/import commands, or the optional `OUTREACH_AUTHORIZATION_JSON` bundle.
Never fill placeholder records merely to pass a check. The checked-in policy is
disabled, so reviewed mode remains blocked until genuine records are supplied.
A configured authorization bundle still restricts recipients in either mode; remove
it when intentionally using only automatic observed-contact evidence.

## Run and verify

Use **Actions -> UK Website Agent -> Run workflow** on main. The same pipeline runs
at 15:00 and 21:00 India time, subject to GitHub scheduling delays. Research and
sending respect UK local windows; the evening slot can prepare a draft for the next
open contact window. Candidates are researched in batches of three; at most one
qualifying demo and one initial message are selected per invocation.

Email preparation uses a trusted template directly and no longer depends on Gemini.
An unavailable model can still defer research/design, but cannot prevent preparing
an email for an already verified demo. Contact pages are prioritized within the
three-page fetch budget so navigation links do not hide the published mailbox.

Inspect the run summary and `agent-result-<run>-1` artifact:

- `outreach_readiness.source=operator_managed` identifies the active setting;
  `legal_review_verified=false` explicitly avoids claiming a legal review.
- `sending_enabled=true` is a switch, not evidence that any message was sent.
- `run_diagnostics.stage_event_counts.email_sent` counts confirmed sends in that run.
- `run_diagnostics.outreach_block_reasons` contains fixed reason codes without
  publishing recipient details. Examples: `not_public_business_mailbox`,
  `outside_local_contact_window`, `suppressed`.
- `aggregate_counts.sent` is a rolling-day total and can include other runs.

Gmail SENT verification confirms the sender's Sent-folder record, not inbox placement.
Zero sends can mean no qualifying website, no observed email, a closed window,
capacity exhaustion or a provider failure. See the actual run result before claiming
live sending works. Unit tests use mocks and never send emails.
