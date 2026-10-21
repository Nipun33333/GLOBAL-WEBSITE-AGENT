"""Credential-free dispatch validation, followed by a bounded authorized runtime.

This script uses only the standard library until after preflight. Inputs are argv/env
values, never shell source. External side-effect permissions are independent.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

CRONS = {
    "30 9 * * *": "daily",   # 15:00 IST
    "30 15 * * *": "daily",  # 21:00 IST
}
MODES = {"diagnostics", "discover", "daily", "replies", "followups", "report", "reconcile", "live-smoke"}
CAPABILITIES = {
    "daily": {"generation", "deployment", "drafts", "sending"},
    "replies": {"generation"},
    "followups": {"generation", "drafts", "sending"},
    "live-smoke": {"generation", "deployment", "drafts"},
}


def plan(env, actual_sha):
    if (
        env.get("GITHUB_REPOSITORY") != "Nipun33333/GLOBAL-WEBSITE-AGENT"
        or env.get("GITHUB_RUN_ATTEMPT") != "1"
    ):
        raise ValueError("Repository/rerun rejected")
    event = env.get("GITHUB_EVENT_NAME")
    scheduled = event == "schedule"
    one_click = event == "workflow_dispatch" and env.get("ONE_CLICK_MODE") == "true"
    if event not in {"schedule", "workflow_dispatch"}:
        raise ValueError("Unsupported event")
    if not re.fullmatch(r"[0-9a-f]{40}", actual_sha) or env.get("GITHUB_SHA") != actual_sha:
        raise ValueError("Dispatch revision changed")
    if scheduled:
        if env.get("GITHUB_REF") != "refs/heads/main" or any(
            env.get(k) != "true" for k in ("AUTOMATION_ENABLED", "UNIFIED_WORKFLOW_ENABLED")
        ):
            raise ValueError("Scheduled automation disabled")
        mode = CRONS.get(env.get("AGENT_CRON"))
        approved = (env.get("SCHEDULED_MODES") or "daily").split(",")
        if mode not in approved:
            raise ValueError("Scheduled mode not owner approved")
        country = ""
    else:
        permitted_refs = ({"refs/heads/main"} if one_click else {
            "refs/heads/main", "refs/heads/feature/free-overture-discovery"
        })
        if env.get("GITHUB_REF") not in permitted_refs:
            raise ValueError("Unreviewed branch")
        if any(env.get(k) != "Nipun33333" for k in ("GITHUB_ACTOR", "GITHUB_TRIGGERING_ACTOR")):
            raise ValueError("Owner dispatch required")
        if not one_click and env.get("REVIEWED_COMMIT") != actual_sha:
            raise ValueError("Reviewed revision mismatch")
        mode = "daily" if one_click else env.get("AGENT_MODE")
        country = "" if one_click else env.get("AGENT_COUNTRY", "").strip().upper()
        if country and not re.fullmatch(r"[A-Z]{2}", country):
            raise ValueError("Country must be an ISO code")
    if mode not in MODES:
        raise ValueError("Unsupported mode")
    if not one_click and any(env.get(k) != "true" for k in ("FREE_LIMITS_REVIEWED", "DATABASE_REVIEWED")):
        raise ValueError("Quota and database review required")
    if not scheduled and not one_click and mode != "diagnostics":
        phrase = (
            "APPROVE_US_DISCOVERY_WRITES"
            if mode == "discover"
            else f"APPROVE_{mode.upper().replace('-', '_')}_WRITES"
        )
        if env.get("WRITE_APPROVAL") != phrase:
            raise ValueError("Separate write approval required")
    if country and mode not in {"daily", "diagnostics", "discover"}:
        raise ValueError("Country filtering is supported only for daily/discover")
    if mode in {"diagnostics", "discover"} and country not in {"", "US"}:
        raise ValueError("Initial verification supports US only")
    allowed = CAPABILITIES.get(mode, set())
    capabilities = {
        k: k in allowed and env.get("ALLOW_" + k.upper()) == "true"
        for k in ("generation", "deployment", "drafts", "sending")
    }
    capabilities["sending"] = capabilities["sending"] and env.get("ENABLE_SENDING") == "true"
    if mode == "live-smoke" and not all(capabilities[k] for k in ("generation", "deployment", "drafts")):
        raise ValueError("Live smoke requires generation, deployment and draft approvals")
    return {"mode": mode, "country": country, "scheduled": scheduled, "revision": actual_sha, **capabilities}


def safe_readonly_account_checks(settings):
    """Metadata/identity only; no generation, deployment, draft or mail mutation."""
    if (
        os.getenv("LIVE_ACCOUNT_DIAGNOSTICS") != "true"
        or os.getenv("GITHUB_EVENT_NAME") != "workflow_dispatch"
    ):
        return {}
    import httpx

    from website_agent import live_verification as live

    checks = {}
    try:
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            for name, fn in (
                ("gemini", live.gemini_check),
                ("netlify", live.netlify_check),
                ("gmail", live.gmail_check),
            ):
                checks[name] = live.run_check(lambda fn=fn: fn(settings, client))
    except Exception:
        checks["status"] = "account_metadata_unavailable"
    return checks


def execute(selected):
    from website_agent import live_verification as live
    from website_agent.settings import Settings

    # Reassert restrictions in the credentialed step, independent of YAML defaults.
    os.environ.update(
        ENABLE_GENERATION=str(selected["generation"]).lower(),
        ENABLE_DEPLOYMENT=str(selected["deployment"]).lower(),
        ENABLE_DRAFTS=str(selected["drafts"]).lower(),
        ENABLE_SENDING=str(selected["sending"]).lower(),
        ENABLE_ROUTINE_REPLIES="false",
        AUTOMATION_ENABLED="false",
    )
    mode = selected["mode"]
    if mode in {"diagnostics", "discover"}:
        os.environ.update(VERIFY_MODE=mode, REVIEWED_COMMIT=selected["revision"])
        return live.main()
    settings = Settings(_env_file=None)
    config = settings.config()
    if selected["country"] and selected["country"] not in {loc.country for loc in config.locations}:
        raise ValueError("Country is not configured")
    # Preserve useful provider-neutral diagnostics without exposing URLs or SQL errors.
    if not settings.database_url:
        check = {"status": "missing_database_url", "discovery_ready": False}
    else:
        try:
            check = live.database_check(settings, config)
        except Exception as exc:
            # PostgreSQL SQLSTATE conveys a safe class of failure, not secret values.
            original = getattr(exc, "orig", None)
            state = getattr(original, "sqlstate", None)
            if state in {"28P01", "28000"}:
                reason = "authentication_rejected"
            elif state in {"3D000", "42P01", "42703"}:
                reason = "database_or_schema_missing"
            elif state in {"53300", "53100", "53200"}:
                reason = "database_capacity_unavailable"
            else:
                reason = "connection_tls_or_configuration_unavailable"
            check = {"status": reason, "discovery_ready": False}
    if not check.get("discovery_ready"):
        result = {"status": "blocked_database_preflight", "mode": mode, "database": check}
        result.update(safe_readonly_account_checks(settings))
        live.publish(result)
        return 2
    args = [sys.executable, "-m", "website_agent.cli", mode]
    if selected["country"]:
        args += ["--country", selected["country"]]
    if selected["scheduled"] and mode == "daily":
        args.append("--scheduled")
    if selected["sending"]:
        args.append("--production")
    env = dict(os.environ)
    env.pop("GITHUB_STEP_SUMMARY", None)
    # Apply the same verified TLS settings to the write connection as to preflight.
    import certifi
    from sqlalchemy.engine import make_url

    env["DATABASE_URL"] = (
        make_url(settings.database_url)
        .update_query_dict({"sslmode": "verify-full", "sslrootcert": certifi.where()})
        .render_as_string(hide_password=False)
    )
    env["PGCONNECT_TIMEOUT"] = "10"
    try:
        result = subprocess.run(
            args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2400
        )
        code = result.returncode
        status = "completed" if code == 0 else "deferred" if code == 2 else "failed_check_persistent_state"
    except subprocess.TimeoutExpired:
        code, status = 2, "interrupted_unknown_progress_check_checkpoint"
    # Never upload the historical CLI report containing customer URLs/thread identifiers.
    from datetime import timedelta

    from sqlalchemy import func, select

    from website_agent.database import CostUsage, Event, Message, Site, WorkflowRun, now

    counts = {}
    try:
        with live.readonly_database(settings) as connection:
            since = now() - timedelta(days=7 if mode == "report" else 1)
            for label, table in (("runs", WorkflowRun), ("sites", Site), ("messages", Message)):
                counts[label] = connection.scalar(
                    select(func.count()).select_from(table).where(table.created_at >= since)
                )
            counts["sent"] = connection.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.sent_at >= since, Message.state == "sent")
            )
            counts["drafts_created"] = connection.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.created_at >= since, Message.draft_id.is_not(None))
            )
            counts["followups_sent"] = connection.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.sent_at >= since, Message.state == "sent", Message.kind == "followup")
            )
            counts["owner_notifications"] = connection.scalar(
                select(func.count())
                .select_from(Event)
                .where(Event.created_at >= since, Event.event == "owner_notification")
            )
            counts["failed_stages"] = connection.scalar(
                select(func.count())
                .select_from(Event)
                .where(Event.created_at >= since, Event.event == "failure")
            )
            counts["deferred_stages"] = connection.scalar(
                select(func.count())
                .select_from(Event)
                .where(Event.created_at >= since, Event.event == "capacity_deferred")
            )
            amount = connection.scalar(
                select(func.sum(func.coalesce(CostUsage.actual_usd, CostUsage.reserved_usd))).where(
                    CostUsage.provider == "gemini", CostUsage.created_at >= since
                )
            )
            counts["gemini_tracked_or_reserved_usd"] = float(amount or 0)

    except Exception:
        counts = {"status": "aggregate_read_unavailable"}
    live.publish(
        {
            "status": status,
            "mode": mode,
            "exit_code": code,
            "revision": selected["revision"],
            "sending_enabled": selected["sending"],
            "aggregate_counts": counts,
        }
    )
    return code


def main():
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        selected = plan(os.environ, sha)
        if "--preflight" in sys.argv:
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
                handle.write("browser=" + str(selected["deployment"]).lower() + "\n")
            print("Validated owner/schedule, revision and independent permissions; no credentials loaded.")
            return 0
        return execute(selected)
    except Exception:
        # Never stringify exceptions/settings/provider data.
        Path("artifacts").mkdir(exist_ok=True)
        Path("artifacts/live-verification.json").write_text(
            json.dumps({"status": "blocked_or_failed_master_preflight"}), encoding="utf-8"
        )
        print("Operation blocked or failed; no private exception details exported.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
