# Unified workflow migration plan

Audit baseline: seven definitions at `fb67c643969f8cfdfb8692e6d1fabb30b1790c65` plus merged registration PR #7. Four scheduled callers shared `_agent-runtime.yml`; manual production also called it. Manual live verification duplicated installation but had stricter owner/SHA/approval gates. The shared runtime implicitly migrated the database and installed Chromium for every command. The new runtime performs read-only schema preflight, never automatic migrations, and installs Chromium only for daily/live-smoke work.

| Existing entry point | Responsibility / UTC cron | Replacement mode |
|---|---|---|
| global-daily-pipeline.yml | `17 * * * *`; application daily checkpoint/local windows | daily |
| gmail-reply-checker.yml | `7,37 * * * *` | replies |
| followup-processor.yml | `42 * * * *`; synchronizes replies before followups | followups |
| weekly-report.yml | `23 4 * * 1` | report |
| manual-production-run.yml | manual operational commands | same manual modes |
| manual-live-verification.yml | read-only diagnostics / approved US discovery | diagnostics / discover |
| _agent-runtime.yml | shared environment/install/lock/report | one inline job |

All four cron strings are distinct and retained once. The daily pipeline does not substitute for lightweight reply/report operations. Followup reply synchronization remains a deliberate safety check. Existing database locks, run keys, deferred queues, daily/local checkpoints and ambiguous external-operation reconciliation are preserved.

## Deployment sequence (owner approval required)

Registration [PR #8](https://github.com/Nipun33333/GLOBAL-WEBSITE-AGENT/pull/8) was explicitly owner-approved and merged at `a1222fb8f791787ff0eea70eff51e9c1258459b6`. Actions ID: `391903326`, zero runs. The steps below distinguish completed registration from future activation.

1. Keep `AUTOMATION_ENABLED`, `ENABLE_SENDING`, `ENABLE_ROUTINE_REPLIES` disabled. Do not dispatch while quota/database review is outstanding. Leave new `UNIFIED_WORKFLOW_ENABLED` absent/false.
2. Registration is complete. It added the registration version of the new workflow to main without removing the old diagnostic entry point. New schedules are inert behind `UNIFIED_WORKFLOW_ENABLED`; existing schedules remain disabled by `AUTOMATION_ENABLED`. No application code is copied into registration main.
3. After registration, review the feature SHA and dispatch the new control panel against `feature/free-overture-discovery`, diagnostics only, with explicit owner approval. Main cannot execute the new script until the full implementation is merged; the old diagnostic remains in main during transition; the feature switches to the newly registered control panel once its deletions are pushed.
4. Evaluate diagnostics and separately approved live tests. Only then separately approve merging PR #6. The feature includes main's registration ancestry so all seven old definitions are explicit deletions. The latest main registration commit is integrated into the feature; verify the PR's resulting tree contains exactly one workflow before merging.
5. Verify main has only `global-website-agent.yml`, inspect its YAML, and confirm no old schedules remain. Manual operation works without enabling schedules. Only after a separate production review may the owner configure the schedule and per-capability approvals described in UNIFIED_WORKFLOW.md. Never enable unified scheduling while old schedules remain.

Nothing in registration or PR merge approves database writes, migrations, generation, deployment, drafts or sending. Only PR #8 was merged after explicit owner approval; PR #6 remains unmerged. Reverting during disabled operation is possible via an owner-reviewed revert; disable automation before any rollback to avoid duplicate schedules.
