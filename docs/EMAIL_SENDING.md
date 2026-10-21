# Real UK business email sending

This repository uses your existing Gmail OAuth connection, including a personal
Gmail mailbox. No paid email provider has been added. The API can create real drafts
and send real messages, but a configured API connection is not permission to contact
every discovered business.

Email preparation now uses the trusted demo-offer template directly. Gemini remains
in use for research/design; a model outage no longer prevents preparing an email for
an already verified demo. Existing drafts keep their original content and digest.

## What the setup can and cannot fix

`OUTREACH_AUTHORIZATION_JSON` is an **optional application configuration**, not a
government certificate, a Gmail credential, or a guarantee of compliance. Existing
policy-file/database imports remain supported. Do not invent consent, reviewer
details or references just to make a send check pass.

Under [ICO's UK B2B guidance](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/business-to-business-marketing/),
corporate subscribers and sole traders have different rules; personal data also
raises UK GDPR obligations. Separately, [Gmail's program policy](https://support.google.com/mail/answer/16734397)
prohibits spam and unsolicited commercial mail. A corporate UK policy record does
not override Gmail's provider terms. An unsolicited first-contact offer cannot be
made provider-compliant simply by changing a flag or sending it manually.

This PR repairs preparation and reporting; it does not claim live, compliant cold
outreach has been activated. Actual delivery and recipient permission have not been
verified. The one-email-per-run limit is an operational cap, not a legal exemption.

The daily workflow already uses the real Gmail API with sending enabled. Gmail
credentials alone do not authorize a recipient. The checked-in GB policy is
disabled, and discovered public addresses do not create recipient eligibility.

## One-time private configuration

Use this optional route only when you already have real reviewed records. You do
not need this secret to connect Gmail or prepare a demo draft.

Keep the existing Gmail and sender secrets. Add `OUTREACH_AUTHORIZATION_JSON` in
the repository's Actions secrets or the `agent-runtime` environment. The JSON
contains your actual reviewed policy and individual recipient evidence. Never
commit the populated JSON. Do not use placeholders as evidence.

```json
{
  "country": "GB",
  "policy": {
    "enabled": true,
    "reviewed_by": "REPLACE_WITH_ACTUAL_REVIEWER",
    "legal_reference": "REPLACE_WITH_ACTUAL_REVIEW_RECORD",
    "valid_until": "2026-12-31",
    "allowed_bases": ["REPLACE_WITH_REVIEWED_BASIS"],
    "allowed_contact_types": ["corporate"],
    "contact_hours": [9, 17]
  },
  "recipients": [
    {
      "domain": "business.example",
      "verified_email": "contact@business.example",
      "email_evidence_reference": "REPLACE_WITH_VERIFICATION_RECORD",
      "basis": "REPLACE_WITH_REVIEWED_BASIS",
      "evidence_reference": "REPLACE_WITH_RECIPIENT_REVIEW_RECORD",
      "reviewed_by": "REPLACE_WITH_ACTUAL_REVIEWER",
      "valid_until": "2026-12-31",
      "contact_type": "corporate"
    }
  ]
}
```

Choose real validity dates from the review. Configuration accepts at most 500
distinct business domains and 48,000 UTF-8 bytes (within GitHub's secret budget).
Malformed configuration stops the run with a generic error; private validation
input is never logged. An absent secret preserves the existing policy-file and
database-import setup. An empty recipient list permits no new sends through this
private-configuration path.

The private policy replaces GB's checked-in policy during normal CLI policy sync.
Only matching, already-discovered GB businesses can use the supplied evidence.
The list does not import leads, assert that a business qualified, or skip preview
generation. Evidence is checked again on every send attempt, including existing
drafts. A changed draft recipient requires manual review; it is not silently
retargeted. Removing a recipient from the configured list prevents new sends to
that domain. Removing the entire secret restores the disabled checked-in policy
on the next run. Existing audit/evidence records are retained in the database.

## Execution and verification

After merging the code and configuring real evidence, the existing UK Website
Agent schedule continues at 15:00 and 21:00 India time. Owner manual dispatch
uses the same daily pipeline. Research and sending still respect UK local hours.

A business must qualify, have a verified preview and mailbox, pass the current
policy/expiry/contact-window checks, and have no prior external Gmail contact or
opt-out. Trusted email copy, sender identity, send reconciliation and the maximum
of one new initial email per run remain enforced. A blocked draft no longer
prevents later drafts within the configured inspection batch from being checked.

Inspect `agent-result-<run>-1` / the run summary:

- `sending_enabled` indicates the switch, not successful delivery.
- `outreach_readiness` identifies the policy source, policy switch and private
  recipient count without exposing addresses or review records.
- `run_diagnostics.stage_event_counts.outreach_blocked` counts policy-blocked
  send attempts. `run_diagnostics.outreach_block_reasons` lists fixed reason codes
  and counts for this run without recipient data. `unverified_country_policy`
  means policy configuration is incomplete; `insufficient_legal_basis` means a
  recipient record is missing/incompatible; `outside_local_contact_window`
  means the recipient's configured local sending window is closed.
- `run_diagnostics.stage_event_counts.email_sent` records sends in that run;
  `aggregate_counts.sent` covers the last day and can include other runs.

A Gmail `SENT` result confirms acceptance into the sender's Sent folder, not
recipient inbox placement. Zero sends can also mean no qualified leads, a closed
contact window, or a provider failure. Do not remove these checks to force a send.

## Current observed baseline

Run `39678398678` on 21 October 2026 had sending enabled, zero qualified leads,
zero previews and zero messages; discovery deferred outside the local research
window. Repository secret metadata contained Gmail/sender credentials but no
private policy/recipient configuration. This is not a successful live send test.
