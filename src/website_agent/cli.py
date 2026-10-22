import argparse
import hashlib
import json
import os
from pathlib import Path

import yaml
from sqlalchemy import select, text

from website_agent.compliance import Policy
from website_agent.database import (
    CountryPolicy,
    Message,
    engine_for,
    get_config,
    locked_session,
    now,
)
from website_agent.imports import import_eligibility, import_gmail_history, import_history, validate_history
from website_agent.outreach_authorization import load_authorization
from website_agent.pipeline import Pipeline
from website_agent.reporting import report
from website_agent.security import Blocked, CapacityDeferred
from website_agent.settings import Settings


def migrate(engine):
    with locked_session(engine) as session:
        session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL)"
            )
        )
        session.commit()
        for path in sorted(Path("database/migrations").glob("*.sql")):
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            previous = session.execute(
                text("SELECT checksum FROM schema_migrations WHERE version=:v"), {"v": path.name}
            ).scalar()
            if previous:
                if previous != checksum:
                    raise Blocked("Previously applied migration changed")
                continue
            # Driver multi-statement simple-query execution; migrations are trusted repository source.
            session.connection().exec_driver_sql(sql)
            session.execute(
                text("INSERT INTO schema_migrations(version,checksum) VALUES (:v,:c)"),
                {"v": path.name, "c": checksum},
            )
            session.commit()


def sync_policies(session, path, authorization=None):
    policies = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if authorization is not None:
        policies[authorization.country] = authorization.policy.model_dump()
    for country, value in policies.items():
        validated = Policy.model_validate(value).model_dump()
        row = session.scalar(select(CountryPolicy).where(CountryPolicy.country == country))
        if row:
            row.policy = validated
        else:
            session.add(CountryPolicy(country=country, policy=validated))
    # Removing a policy from configuration disables it in the database.
    for row in session.scalars(select(CountryPolicy)).all():
        if row.country not in policies:
            row.policy = Policy().model_dump()
    session.commit()


def doctor(settings, live=False):
    required = [
        "database_url",
        "gemini_api_key",
        "netlify_auth_token",
        "netlify_site_id",
        "gmail_client_id",
        "gmail_client_secret",
        "gmail_refresh_token",
        "sender_name",
        "sender_email",
        "reply_to",
        "sender_postal_address",
        "owner_email",
    ]
    if settings.config().discovery_provider != "open_data":
        required.append("discovery_api_key")
    result = {name.upper(): "configured" if getattr(settings, name) else "MISSING" for name in required}
    result["external_verification"] = "NOT RUN"
    if live:
        engine = engine_for(settings.database_url)
        with locked_session(engine) as session:
            pipeline = Pipeline(session, settings, settings.config())
            session.execute(text("SELECT 1"))
            result["gemini_model"] = pipeline.ai.available_model()
            pipeline.gmail.verify_sender()
            pipeline.hosting.client.get("sites/" + settings.netlify_site_id).raise_for_status()
            result["external_verification"] = (
                "read-only DB, model metadata, Gmail identity and hosting project checked; no discovery/generation/deployment/send test"
            )
    print(json.dumps(result, indent=2))
    return all(result[k.upper()] == "configured" for k in required)


def parser():
    p = argparse.ArgumentParser(description="Global Website Agent (draft-only unless explicitly enabled)")
    p.add_argument(
        "command",
        choices=[
            "migrate",
            "doctor",
            "daily",
            "discover",
            "replies",
            "followups",
            "report",
            "import-history",
            "import-gmail",
            "validate-history",
            "import-eligibility",
            "approve-copy",
            "reconcile",
            "export-drafts",
            "live-smoke",
        ],
    )
    p.add_argument("--file")
    p.add_argument("--country")
    p.add_argument("--scheduled", action="store_true")
    p.add_argument("--live", action="store_true")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--message-id")
    p.add_argument("--digest")
    p.add_argument("--reviewer")
    p.add_argument(
        "--production",
        action="store_true",
        help="Additional required switch for sending; ENABLE_SENDING must also be true",
    )
    return p


def run_cli():
    args = parser().parse_args()
    settings = Settings()
    # Both an environment control AND explicit invocation are required for actual sends.
    settings.enable_sending = settings.enable_sending and args.production
    if args.command == "doctor":
        raise SystemExit(0 if doctor(settings, args.live) else 2)
    settings.require("database_url")
    engine = engine_for(settings.database_url)
    if args.command == "migrate":
        migrate(engine)
        print("Database migrations applied.")
        return
    with locked_session(engine) as session:
        config = settings.config()
        pipeline = Pipeline(session, settings, config)
        if args.command == "import-history":
            print("Imported records:", import_history(session, args.file))
            print("Import SHA-256:", get_config(session, "history_import")["digest"])
            return
        if args.command == "import-gmail":
            print("Imported Gmail recipients:", import_gmail_history(session, pipeline.gmail))
            return
        if args.command == "validate-history":
            validate_history(session, args.file)
            return
        if args.command == "import-eligibility":
            import_eligibility(session, args.file)
            return
        if args.command == "approve-copy":
            message = session.get(Message, args.message_id)
            if (
                not message
                or not args.reviewer
                or args.digest != hashlib.sha256((message.subject + message.body).encode()).hexdigest()
            ):
                raise Blocked("Reviewer and exact current message digest required")
            message.details = {
                **message.details,
                "approved_digest": args.digest,
                "copy_reviewer": args.reviewer,
                "approved_at": now().isoformat(),
            }
            session.commit()
            return
        if args.command == "export-drafts":
            Path("private").mkdir(exist_ok=True)
            rows = [
                {
                    "id": m.id,
                    "recipient": m.recipient,
                    "subject": m.subject,
                    "body": m.body,
                    "digest": hashlib.sha256((m.subject + m.body).encode()).hexdigest(),
                    "state": m.state,
                }
                for m in session.scalars(
                    select(Message).where(Message.state.in_(["drafted", "draft_pending", "prepared"]))
                )
            ]
            Path("private/drafts.json").write_text(
                json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print("Wrote private/drafts.json (contains contact data; never commit).")
            return
        if args.command != "discover":
            sync_policies(session, settings.policy_path, load_authorization(settings))
        run_key = f"{args.command}:{os.getenv('GITHUB_RUN_ID', now().isoformat())}:{os.getenv('GITHUB_RUN_ATTEMPT', '1')}"
        if not pipeline.start(args.command, run_key):
            return
        try:
            if args.command == "discover":
                # Discovery-only cannot initialize Gmail, Gemini or Netlify or enable sending.
                settings.enable_sending = False
                settings.enable_routine_replies = False
                pipeline.database_capacity()
                pipeline.discover(args.country)
            elif args.command == "daily":
                pipeline.daily(args.country, args.scheduled)
            elif args.command == "replies":
                pipeline.replies()
            elif args.command == "followups":
                pipeline.followups()
            elif args.command == "reconcile":
                from website_agent.outreach import record_sent

                for msg in session.scalars(
                    select(Message).where(Message.state.in_(["sending", "uncertain"]))
                ):
                    result = pipeline.gmail.reconcile(msg.rfc_message_id)
                    if result:
                        record_sent(session, msg, result)
                        pipeline.log("send_reconciled", message_id=msg.id)
                    else:
                        pipeline.log("manual_reconciliation_required", message_id=msg.id)
            elif args.command == "live-smoke":
                # Intentionally no prospect sends: generates/deploys a neutral page and drafts to owner.
                from website_agent.smoke import live_smoke

                live_smoke(pipeline)
            pipeline.finish()
        except CapacityDeferred as exc:
            session.rollback()
            pipeline.log("capacity_deferred", stage=args.command, reason=str(exc))
            pipeline.run.status = "deferred_resource_limit"
            session.commit()
        except Exception as exc:
            session.rollback()
            pipeline.log("failure", stage=args.command, error_type=type(exc).__name__)
            pipeline.run.status = "failed"
            session.commit()
        finally:
            print(report(session, args.days if args.command == "report" else 1))
        if pipeline.run.status not in {
            "completed",
            "completed_with_results",
            "completed_no_qualified_results",
        }:
            raise SystemExit(2 if pipeline.run.status.startswith("deferred") else 1)


def main():
    try:
        run_cli()
    except Exception as exc:
        # Provider/SQL exception strings can include passwords, raw queries or message content.
        print(f"Operation failed ({type(exc).__name__}). Use doctor and sanitized run events to diagnose.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
