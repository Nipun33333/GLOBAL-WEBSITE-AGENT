import json
import os
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from website_agent.database import CostUsage, Event, Message, Site, WorkflowRun, get_config, now


def event(session, run, name, **details):
    # Callers pass only allowlisted metadata, never exceptions, email bodies, URLs with keys or credentials.
    session.add(Event(run_id=run.id, event=name, details=details))
    counts = dict(run.summary)
    counts[name] = counts.get(name, 0) + 1
    run.summary = counts
    session.commit()


def report(session, days=1):
    since = now() - timedelta(days=days)
    runs = list(session.scalars(select(WorkflowRun).where(WorkflowRun.created_at >= since)))
    costs = list(session.scalars(select(CostUsage).where(CostUsage.created_at >= since)))
    sites = list(session.scalars(select(Site).where(Site.created_at >= since)))
    events = list(session.scalars(select(Event).where(Event.created_at >= since)))
    sent = list(session.scalars(select(Message).where(Message.state == "sent", Message.sent_at >= since)))
    drafted = list(
        session.scalars(select(Message).where(Message.draft_id.is_not(None), Message.created_at >= since))
    )
    uncertain = list(
        session.scalars(select(Message).where(Message.state.in_(["sending", "uncertain", "draft_pending"])))
    )
    estimated = sum(c.actual_usd if c.actual_usd is not None else c.reserved_usd for c in costs)
    lines = [
        f"# Global Website Agent — {days}-day report",
        "",
        f"Recorded runs: {len(runs)}",
        f"Verified Gmail drafts created: {len(drafted)}",
        f"Verified new outreach sent: {sum(m.kind == 'initial' for m in sent)}",
        f"Verified followups sent: {sum(m.kind == 'followup' for m in sent)}",
        f"Verified acknowledgments sent: {sum(m.kind == 'acknowledgment' for m in sent)}",
        f"Unresolved external outcomes requiring reconciliation: {len(uncertain)}",
        f"Gemini quota pause record: {json.dumps(get_config(session, 'gemini_quota_pause'))}",
        f"Gemini tracked/reserved cost: ${estimated:.6f} (configured prices; not a provider invoice)",
        "",
        "| Run | Status | Counters |",
        "|---|---|---|",
    ]
    for run in runs:
        lines.append(f"| {run.kind} | {run.status} | {json.dumps(run.summary, sort_keys=True)} |")
    lines += ["", "## Preview deployments", ""]
    for site in sites:
        lines.append(
            f"- `{site.id}`: {site.status}" + (f" — {site.url}" if site.status == "verified" else "")
        )
    lines += ["", "## Events and owner notifications", ""]
    for item in events:
        details = (
            json.dumps(item.details, ensure_ascii=True)
            .replace("`", "'")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        lines.append(f"- {item.event}: `{details}`")
    content = "\n".join(lines) + "\n"
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/report.md").write_text(content, encoding="utf-8")
    if path := os.getenv("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(content)
    return content
