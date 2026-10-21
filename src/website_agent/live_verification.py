"""Owner-dispatched diagnostics; no generation, deployment, mailbox mutation or billing APIs."""

import hashlib
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import certifi
import httpx
from sqlalchemy import UniqueConstraint, create_engine, inspect, select, text
from sqlalchemy.engine import make_url

from website_agent.database import Base, Event, WorkflowRun, now
from website_agent.gmail import SCOPES
from website_agent.scheduler import contact_time
from website_agent.settings import Settings

APPROVAL = "APPROVE_US_DISCOVERY_WRITES"
SECRET_NAMES = (
    "DATABASE_URL GEMINI_API_KEY NETLIFY_AUTH_TOKEN NETLIFY_SITE_ID GMAIL_CLIENT_ID "
    "GMAIL_CLIENT_SECRET GMAIL_REFRESH_TOKEN SENDER_NAME SENDER_EMAIL REPLY_TO "
    "SENDER_POSTAL_ADDRESS OWNER_EMAIL"
).split()
STATUSES = {
    "completed_with_results",
    "completed_no_qualified_results",
    "deferred_provider_unavailable",
    "deferred_resource_limit",
    "blocked_permission_or_license",
    "failed_requires_operator",
}
METRICS = (
    "accepted accepted_in_task unverified requests bytes queries files_examined row_groups_read "
    "records_scanned candidates_identified candidate_verifications already_known_duplicates "
    "official_websites_verified businesses_inserted elapsed_seconds remaining_queries pending_candidates"
).split()
PROVIDER_CODES = {
    "invalid_grant",
    "invalid_client",
    "unauthorized_client",
    "access_denied",
    "invalid_request",
    "temporarily_unavailable",
    "RESOURCE_EXHAUSTED",
    "PERMISSION_DENIED",
    "UNAUTHENTICATED",
    "NOT_FOUND",
    "INVALID_ARGUMENT",
    "UNAVAILABLE",
}
REJECTIONS = set(
    (
        "duplicate_domain duplicate_source_id suppressed_domain_or_mailbox unverified_geography "
        "unverified_coordinates unverified_outside_radius unverified_category unverified_url "
        "unverified_listing_url excluded_directory_domain unverified_website_cooldown "
        "unverified_website_rate_or_availability_limit unverified_canonical_url "
        "unverified_business_website_association invalid_candidate_or_website_access"
    ).split()
)
LAYERS = {"overture", "overture_aws", "overture_azure", "verified_cache", "osm_extract", "overpass"}


class CheckFailed(Exception):
    """Never display provider exception text or connection strings."""

    def __init__(self, http_status=None, provider_code=None):
        self.http_status = http_status
        self.provider_code = provider_code if provider_code in PROVIDER_CODES else None


def guard(environ):
    if (
        environ.get("GITHUB_REPOSITORY") != "Nipun33333/GLOBAL-WEBSITE-AGENT"
        or environ.get("GITHUB_REF") not in {"refs/heads/feature/free-overture-discovery", "refs/heads/main"}
        or environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or environ.get("GITHUB_ACTOR") != "Nipun33333"
        or environ.get("GITHUB_TRIGGERING_ACTOR") != "Nipun33333"
        or environ.get("GITHUB_RUN_ATTEMPT") != "1"
        or any(environ.get(k) != "true" for k in ("FREE_LIMITS_REVIEWED", "DATABASE_REVIEWED"))
        or any(
            environ.get(k) != "false"
            for k in ("ENABLE_SENDING", "ENABLE_ROUTINE_REPLIES", "AUTOMATION_ENABLED")
        )
        or environ.get("VERIFY_MODE") not in {"diagnostics", "discover"}
        or (environ.get("VERIFY_MODE") == "discover" and environ.get("WRITE_APPROVAL") != APPROVAL)
    ):
        raise CheckFailed()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if (
        not re.fullmatch(r"[0-9a-f]{40}", environ.get("REVIEWED_COMMIT", ""))
        or sha != environ["REVIEWED_COMMIT"]
    ):
        raise CheckFailed()


@contextmanager
def readonly_database(settings):
    url = make_url(settings.database_url)
    # Supabase transaction-pooler port 6543 cannot preserve session advisory locks.
    if url.drivername != "postgresql+psycopg" or url.port not in {None, 5432} or not url.host:
        raise CheckFailed()
    engine = create_engine(
        url,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 10,
            "sslmode": "verify-full",
            "sslrootcert": certifi.where(),
            "options": "-c default_transaction_read_only=on -c statement_timeout=10000",
        },
    )
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            if conn.scalar(text("SHOW transaction_read_only")) != "on":
                raise CheckFailed()
            yield conn
            conn.rollback()
    finally:
        engine.dispose()


def schema_matches(inspector):
    """Compare structural invariants; a stored migration checksum alone cannot detect drift."""
    for table in Base.metadata.sorted_tables:
        columns = {c["name"]: c for c in inspector.get_columns(table.name)}
        if any(c.name not in columns or columns[c.name]["nullable"] != c.nullable for c in table.columns):
            return False
        if set(inspector.get_pk_constraint(table.name)["constrained_columns"]) != {
            c.name for c in table.primary_key.columns
        }:
            return False
        unique = {tuple(c["column_names"]) for c in inspector.get_unique_constraints(table.name)}
        required = {
            tuple(c.name for c in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        if not required <= unique:
            return False
        indexes = {tuple(i["column_names"]) for i in inspector.get_indexes(table.name)}
        if not {tuple(c.name for c in i.columns) for i in table.indexes} <= indexes:
            return False
        foreign = {
            (tuple(f["constrained_columns"]), f["referred_table"], tuple(f["referred_columns"]))
            for f in inspector.get_foreign_keys(table.name)
        }
        for fk in table.foreign_key_constraints:
            expected = (
                tuple(c.name for c in fk.columns),
                fk.referred_table.name,
                tuple(e.column.name for e in fk.elements),
            )
            if expected not in foreign:
                return False
    return True


def database_check(settings, config):
    with readonly_database(settings) as conn:
        inspector = inspect(conn)
        if not set(Base.metadata.tables) | {"schema_migrations"} <= set(inspector.get_table_names()):
            return {"status": "blocked_missing_migrations", "discovery_ready": False}
        for path in Path("database/migrations").glob("*.sql"):
            checksum = conn.scalar(
                text("SELECT checksum FROM schema_migrations WHERE version=:v"), {"v": path.name}
            )
            if checksum != hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest():
                return {"status": "blocked_migration_mismatch", "discovery_ready": False}
        if not schema_matches(inspector):
            return {"status": "blocked_schema_drift", "discovery_ready": False}
        size = conn.scalar(text("SELECT pg_database_size(current_database())"))
        within = size < config.limits.database_max_mb * 1024 * 1024
        return {
            "status": "verified_read_only" if within else "blocked_storage_limit",
            "discovery_ready": within,
            "database_bytes": size,
            "tls_verified": True,
            "schema_constraints_and_indexes": "verified",
            "session_pooling": "owner_attested_not_independently_proven",
        }


def api_json(client, method, url, **kwargs):
    # Fixed endpoints, no redirects or retries, bounded body; response bodies never enter reports.
    with client.stream(method, url, **kwargs) as response:
        raw = bytearray()
        for chunk in response.iter_bytes():
            raw.extend(chunk)
            if len(raw) > 200_000:
                raise CheckFailed(response.status_code)
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise CheckFailed(response.status_code) from None
        if response.status_code != 200:
            error = value.get("error") if isinstance(value, dict) else None
            code = error.get("status") if isinstance(error, dict) else error
            raise CheckFailed(response.status_code, code if isinstance(code, str) else None)
        if not isinstance(value, dict):
            raise CheckFailed()
        return value


def gemini_check(settings, client):
    results = {}
    limits = {}
    explicit = [s.strip() for s in settings.gemini_fallback_models.split(",") if s.strip()]
    models = list(
        dict.fromkeys(
            [settings.gemini_model, settings.gemini_advanced_model]
            + (explicit or settings.config().gemini.fallback_models)
        )
    )
    if len(models) > 8:
        raise CheckFailed()
    for i, model in enumerate(models):
        label = "primary" if i == 0 else "advanced_reserved" if i == 1 else f"fallback_{i - 1}"
        try:
            if not settings.gemini_api_key or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", model):
                raise CheckFailed()
            data = api_json(
                client,
                "GET",
                "https://generativelanguage.googleapis.com/v1beta/models/" + model,
                headers={"x-goog-api-key": settings.gemini_api_key},
            )
            results[label] = (
                "metadata_available"
                if "generateContent" in data.get("supportedGenerationMethods", [])
                else "generation_not_supported"
            )
            limits[label] = {
                k: data[k]
                for k in ("inputTokenLimit", "outputTokenLimit")
                if type(data.get(k)) is int and 0 < data[k] < 10_000_000
            }
        except Exception:
            results[label] = "unavailable_or_request_failed"
    return {
        "status": "verified_metadata"
        if results.get("primary") == "metadata_available"
        else "blocked_primary_model",
        "configured_models": results,
        "reported_token_limits": limits,
        "structured_output": "requires_authorized_generation_test",
        "generation": "not_attempted",
        "free_generation_quota": "not_verified",
    }


def netlify_check(settings, client):
    if not settings.netlify_auth_token or not re.fullmatch(r"[A-Za-z0-9-]{1,100}", settings.netlify_site_id):
        raise CheckFailed()
    data = api_json(
        client,
        "GET",
        "https://api.netlify.com/api/v1/sites/" + settings.netlify_site_id,
        headers={"Authorization": "Bearer " + settings.netlify_auth_token},
    )
    if data.get("id") != settings.netlify_site_id:
        raise CheckFailed()
    return {
        "status": "verified_existing_site_access",
        "deployment": "not_attempted",
        "free_deploy_quota": "not_verified",
    }


def gmail_check(settings, client):
    settings.require(
        "gmail_client_id",
        "gmail_client_secret",
        "gmail_refresh_token",
        "sender_email",
        "reply_to",
        "owner_email",
    )
    token = api_json(
        client,
        "POST",
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": settings.gmail_client_id,
            "client_secret": settings.gmail_client_secret,
            "refresh_token": settings.gmail_refresh_token,
            "grant_type": "refresh_token",
        },
    )
    access = token.get("access_token")
    if not isinstance(access, str) or not access:
        raise CheckFailed()
    profile = api_json(
        client,
        "GET",
        "https://gmail.googleapis.com/gmail/v1/users/me/profile",
        headers={"Authorization": "Bearer " + access},
    )
    email = profile.get("emailAddress", "").casefold()
    identity = bool(email) and email == settings.sender_email.casefold() == settings.reply_to.casefold()
    scope = token.get("scope")
    scopes = (
        "not_returned"
        if scope is None
        else "matched"
        if set(SCOPES) <= set(scope.split())
        else "missing_required_scope"
    )
    return {
        "status": "blocked_identity_mismatch"
        if not identity
        else "verified_mailbox_identity"
        if scopes == "matched"
        else "blocked_scope_verification",
        "mailbox_identity_matches": identity,
        "required_scopes": scopes,
        "owner_is_mailbox": bool(email) and email == settings.owner_email.casefold(),
        "publishing_status_and_token_longevity": "not_verified",
        "drafts_and_sending": "not_attempted",
    }


def run_check(fn):
    try:
        return fn()
    except CheckFailed as exc:
        result = {"status": "failed_or_unavailable"}
        if type(exc.http_status) is int and 100 <= exc.http_status <= 599:
            result["http_status"] = exc.http_status
        if exc.provider_code:
            result["provider_code"] = exc.provider_code
        return result
    except Exception:
        return {"status": "failed_or_unavailable"}


def window_check(config):
    at = now()
    locations = [loc for loc in config.locations if loc.country == "US"]
    return {
        "checked_at_utc": at.isoformat(),
        "us_window_open": any(
            contact_time(at, loc.country, loc.timezone, config.research_hours, loc.subdivision)
            for loc in locations
        ),
        "new_york_local_time": at.astimezone(ZoneInfo("America/New_York")).isoformat(),
    }


def discover(settings, config):
    if not window_check(config)["us_window_open"]:
        return {"status": "blocked_local_research_window"}
    if config.discovery_provider != "open_data":
        return {"status": "blocked_provider_configuration"}
    child_env = dict(os.environ)
    for name in [n for n in SECRET_NAMES if n != "DATABASE_URL"] + [
        "GITHUB_STEP_SUMMARY",
        "DISCOVERY_API_KEY",
    ]:
        child_env.pop(name, None)
    child_env.update(ENABLE_SENDING="false", ENABLE_ROUTINE_REPLIES="false", AUTOMATION_ENABLED="false")
    # Match verified TLS for the subsequent production connection without modifying the stored secret.
    child_env.update(PGSSLMODE="verify-full", PGSSLROOTCERT=certifi.where(), PGCONNECT_TIMEOUT="10")
    url = make_url(settings.database_url).update_query_dict(
        {"sslmode": "verify-full", "sslrootcert": certifi.where()}
    )
    child_env["DATABASE_URL"] = url.render_as_string(hide_password=False)
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "website_agent.cli", "discover", "--country", "US"],
            env=child_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=420,
        )
    except subprocess.TimeoutExpired:
        return {"status": "interrupted_unknown_progress_check_checkpoint"}
    result = {"status": "no_discovery_outcome", "exit_code": completed.returncode}
    # Read only the aggregate outcome from this invocation; never export the normal historical report.
    run_key = f"discover:{os.environ['GITHUB_RUN_ID']}:{os.environ['GITHUB_RUN_ATTEMPT']}"
    with readonly_database(settings) as conn:
        details = conn.execute(
            select(Event.details)
            .join(WorkflowRun, Event.run_id == WorkflowRun.id)
            .where(WorkflowRun.run_key == run_key, Event.event == "discovery_outcome")
        ).scalar()
        if isinstance(details, dict):
            result["status"] = (
                details.get("status") if details.get("status") in STATUSES else "unknown_outcome"
            )
            for key in METRICS:
                value = details.get(key)
                if type(value) in {int, float} and 0 <= value < 1e12:
                    result[key] = value
            result["transfer_counts_are_upper_bounds"] = (
                details.get("transfer_counts_are_upper_bounds") is True
            )
            rejected = details.get("rejection_reasons", {})
            if isinstance(rejected, dict):
                result["rejection_reasons"] = {
                    k: v for k, v in rejected.items() if k in REJECTIONS and type(v) is int and 0 <= v < 1e12
                }
            layers = details.get("fallback_layers_attempted", [])
            if isinstance(layers, list):
                result["fallback_layers_attempted"] = [
                    v for v in layers[:20] if isinstance(v, str) and v in LAYERS
                ]
            try:
                next_at = datetime.fromisoformat(details.get("next_at", ""))
                if next_at.tzinfo is not None:
                    result["next_at"] = next_at.isoformat()
            except (ValueError, TypeError):
                pass
    if completed.returncode != 0 and result["status"].startswith("completed"):
        result["status"] = "failed_after_discovery_check_checkpoint"
    return result


def publish(result):
    root = Path("artifacts")
    root.mkdir(exist_ok=True)
    raw = json.dumps(result, indent=2, allow_nan=False)
    (root / "live-verification.json").write_text(raw + "\n", encoding="utf-8")
    report = (
        "# Manual live verification\n\nOnly aggregate, allowlisted results. No credentials, recipients or customer records.\n\n```json\n"
        + raw
        + "\n```\n"
    )
    (root / "live-verification.md").write_text(report, encoding="utf-8")
    if path := os.getenv("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(report)
    print("Sanitized live-verification report written.")


def main():
    result = {
        "status": "blocked_preflight",
        "prospect_outreach": "disabled",
        "free_limits": "owner_review_required_not_independently_verified",
    }
    exit_code = 1
    try:
        guard(os.environ)
        settings = Settings(_env_file=None)
        config = settings.config()
        result.update(
            mode=os.environ["VERIFY_MODE"], revision=os.environ["REVIEWED_COMMIT"], **window_check(config)
        )
        result["database"] = run_check(lambda: database_check(settings, config))
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            result["gemini"] = run_check(lambda: gemini_check(settings, client))
            result["netlify"] = run_check(lambda: netlify_check(settings, client))
            result["gmail"] = run_check(lambda: gmail_check(settings, client))
        result["osm"] = {
            "status": "blocked_setup_or_license_review"
            if not config.discovery.osm_extracts
            else "configured_not_verified"
        }
        if os.environ["VERIFY_MODE"] == "discover":
            result["discovery"] = (
                run_check(lambda: discover(settings, config))
                if result["database"].get("discovery_ready")
                else {"status": "blocked_database_preflight"}
            )
            exit_code = 0 if result["discovery"]["status"].startswith("completed") else 2
        else:
            exit_code = (
                0
                if all(
                    result[k]["status"].startswith("verified")
                    for k in ("database", "gemini", "netlify", "gmail")
                )
                else 2
            )
        result["status"] = "checks_completed" if exit_code == 0 else "checks_have_blockers"
    except Exception:
        # Do not stringify exceptions, provider payloads, settings or DB URLs.
        result["status"] = "blocked_or_failed_preflight"
    publish(result)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
