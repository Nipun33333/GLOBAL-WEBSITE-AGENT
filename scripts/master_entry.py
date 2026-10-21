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


def classify_database_error(exc):
    """Return only fixed safe identifiers; never expose PostgreSQL's error message."""
    from website_agent import live_verification as live

    if isinstance(exc, live.CheckFailed) and exc.reason:
        return exc.reason
    original = getattr(exc, "orig", None) or exc
    state = getattr(original, "sqlstate", None)
    if state in {"28P01", "28000"}:
        return "authentication_rejected"
    if state in {"3D000", "42P01", "42703"}:
        return "database_or_schema_missing"
    if state in {"53300", "53100", "53200"}:
        return "database_capacity_unavailable"
    # Match only known network/security patterns; NEVER publish the actual exception.
    description = str(original).lower()
    if any(t in description for t in (
        "certificate verify failed", "certificate has expired",
        "unable to get local issuer certificate", "self-signed certificate",
        "certificate is not trusted", "hostname mismatch", "certificate verify",
    )):
        return "tls_certificate_verification_failed"
    if any(t in description for t in (
        "could not translate host name", "name or service not known",
        "nodename nor servname", "temporary failure in name resolution",
    )):
        return "database_dns_resolution_failed"
    if any(t in description for t in (
        "network is unreachable", "no route to host", "address family not supported",
        "cannot assign requested address",
    )):
        return "database_network_or_ipv6_unreachable"
    if any(t in description for t in ("connection timed out", "timeout expired")):
        return "database_connection_timed_out"
    if "connection refused" in description:
        return "database_connection_refused"
    if "password authentication failed" in description:
        return "authentication_rejected"
    if "tenant or user not found" in description or "invalid tenant" in description:
        return "pooler_tenant_or_user_unavailable"
    return "connection_tls_or_configuration_unavailable"


def safe_discovery_details(value):
    """Allowlist public run metrics; never include customer names, URLs, or mailboxes."""
    from datetime import datetime

    from website_agent import live_verification as live

    if not isinstance(value, dict):
        return {}
    out = {}
    if value.get("status") in live.STATUSES:
        out["status"] = value["status"]
    reason = value.get("reason")
    if isinstance(reason, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", reason):
        out["reason"] = reason
    next_at = value.get("next_at")
    if isinstance(next_at, str) and len(next_at) < 64:
        try:
            datetime.fromisoformat(next_at)
            out["next_at"] = next_at
        except ValueError:
            pass
    for name in (
        "accepted", "accepted_in_task", "unverified", "requests", "bytes",
        "queries", "records_scanned", "candidate_verifications",
        "official_websites_verified", "businesses_inserted",
        "remaining_queries", "pending_candidates",
    ):
        item = value.get(name)
        if type(item) is int and 0 <= item <= 10**12:
            out[name] = item
    layers = value.get("fallback_layers_attempted")
    if isinstance(layers, list):
        out["fallback_layers_attempted"] = [
            name for name in layers[:8] if isinstance(name, str) and name in live.LAYERS
        ]
    return out


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


def bootstrap_empty_agent_schema(settings, selected):
    """Initialize a dedicated blank database once; never repair or overwrite live schema."""
    # Only the already-validated repository owner's fresh manual one-click run may
    # initialize an empty schema. Cron, reruns and other commands cannot do this.
    if (
        selected["mode"] != "daily"
        or selected["scheduled"]
        or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or os.environ.get("GITHUB_ACTOR") != "Nipun33333"
        or os.environ.get("GITHUB_TRIGGERING_ACTOR") != "Nipun33333"
        or os.environ.get("GITHUB_RUN_ATTEMPT") != "1"
        or not os.environ.get("GITHUB_SHA") == selected["revision"]
    ):
        return "bootstrap_not_authorized"
    try:
        from sqlalchemy import inspect

        from website_agent import live_verification as live
        from website_agent.cli import migrate
        from website_agent.database import engine_for

        # Protect existing Supabase public tables and partially applied migrations.
        # A dedicated first-time agent schema must be completely empty.
        with live.readonly_database(settings) as conn:
            existing = set(inspect(conn).get_table_names(schema="public"))
        if existing:
            return "bootstrap_requires_review_nonempty_public_schema"

        session_url = (
            live.postgres_session_url(settings.database_url)
            .update_query_dict(
                {"sslmode": "verify-full", "sslrootcert": live.database_sslrootcert()}
            )
            .render_as_string(hide_password=False)
        )
        engine = engine_for(session_url)
        try:
            migrate(engine)
        finally:
            engine.dispose()
        return "schema_initialized"
    except Exception:
        # The error might include credentials, hostnames or SQL. Do not log it.
        return "bootstrap_failed_requires_schema_review"


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
    try:
        settings = Settings(_env_file=None)
        config = settings.config()
    except Exception:
        live.publish({"status": "blocked_application_config", "mode": mode})
        return 2
    if selected["country"] and selected["country"] not in {loc.country for loc in config.locations}:
        raise ValueError("Country is not configured")
    # Preserve useful provider-neutral diagnostics without exposing URLs or SQL errors.
    if not settings.database_url:
        check = {"status": "missing_database_url", "discovery_ready": False}
    else:
        try:
            check = live.database_check(settings, config)
        except Exception as exc:
            check = {"status": classify_database_error(exc), "discovery_ready": False}
    bootstrap_status = None
    if check.get("status") == "blocked_missing_migrations":
        bootstrap_status = bootstrap_empty_agent_schema(settings, selected)
        if bootstrap_status == "schema_initialized":
            try:
                check = live.database_check(settings, config)
            except Exception as exc:
                check = {
                    "status": classify_database_error(exc),
                    "discovery_ready": False,
                }
    if not check.get("discovery_ready"):
        result = {"status": "blocked_database_preflight", "mode": mode, "database": check}
        if bootstrap_status:
            result["schema_bootstrap"] = bootstrap_status
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
    env["DATABASE_URL"] = (
        live.postgres_session_url(settings.database_url)
        .update_query_dict({"sslmode": "verify-full", "sslrootcert": live.database_sslrootcert()})
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
    run_diagnostics = {}
    try:
        with live.readonly_database(settings) as connection:
            exact_run = connection.execute(
                select(WorkflowRun.id, WorkflowRun.status).where(
                    WorkflowRun.run_key == (
                        f"{mode}:{os.environ.get('GITHUB_RUN_ID', '')}:"
                        f"{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
                    )
                )
            ).first()
            if exact_run:
                allowed = {
                    "completed", "completed_with_results", "completed_no_qualified_results",
                    "deferred_resource_limit", "deferred_provider_unavailable",
                    "blocked_permission_or_license", "failed_requires_operator",
                    "failed", "partial",
                }
                run_diagnostics["persisted_status"] = (
                    exact_run.status if exact_run.status in allowed else "unrecognized_status"
                )
                outcome = connection.execute(
                    select(Event.details)
                    .where(
                        Event.run_id == exact_run.id,
                        Event.event == "discovery_outcome",
                    )
                    .order_by(Event.created_at.desc())
                    .limit(1)
                ).scalar()
                if outcome:
                    run_diagnostics["discovery"] = safe_discovery_details(outcome)
            # Recovery journals also record why a fully bounded run deferred.
            from website_agent.database import Configuration

            recovery = connection.execute(
                select(Configuration.value).where(
                    Configuration.key == "discovery_task:worldwide"
                )
            ).scalar()
            if recovery:
                run_diagnostics["recovery"] = safe_discovery_details(recovery)
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
    # A documented, persisted future retry is NOT the same as an execution crash.
    # Keep the original CLI exit_code visible, but don't make GitHub's job red for
    # an intentional, resumable discovery cooldown. Missing persistence evidence
    # or stage failures must still produce a nonzero workflow exit code.
    recovered = run_diagnostics.get("discovery", {})
    normal_defer = (
        mode == "daily"
        and code == 2
        and run_diagnostics.get("persisted_status") in {
            "deferred_resource_limit", "deferred_provider_unavailable"
        }
        and recovered.get("status") in {
            "deferred_resource_limit", "deferred_provider_unavailable"
        }
        and recovered.get("next_at")
        and counts.get("failed_stages") == 0
    )
    if normal_defer:
        status = "deferred_retry_scheduled"
        print("::notice title=Discovery deferred::Safe retry is persisted; see sanitized run_diagnostics.")
    live.publish(
        {
            "status": status,
            "mode": mode,
            "exit_code": code,
            "revision": selected["revision"],
            "sending_enabled": selected["sending"],
            "schema_bootstrap": bootstrap_status or "not_needed",
            "run_diagnostics": run_diagnostics,
            "aggregate_counts": counts,
        }
    )
    return 0 if normal_defer else code


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
