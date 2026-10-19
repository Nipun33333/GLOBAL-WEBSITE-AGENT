import hashlib
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    select,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


def now():
    return datetime.now(UTC)


def aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Prospect(Record, Base):
    __tablename__ = "prospects"
    domain: Mapped[str] = mapped_column(String(253), unique=True)
    name: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    country: Mapped[str] = mapped_column(String(2))
    city: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text)
    subdivision: Mapped[str | None] = mapped_column(Text)
    niche: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="discovered", index=True)
    email: Mapped[str | None] = mapped_column(Text, index=True)
    contact_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    eligibility: Mapped[dict] = mapped_column(JSON, default=dict)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported: Mapped[bool] = mapped_column(Boolean, default=False)


class BusinessSource(Record, Base):
    __tablename__ = "business_sources"
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id"), index=True)
    provider: Mapped[str] = mapped_column(Text)
    provider_id: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("provider", "provider_id"),)


class Audit(Record, Base):
    __tablename__ = "website_audits"
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id"), unique=True)
    score: Mapped[int] = mapped_column(Integer)
    evidence: Mapped[dict] = mapped_column(JSON)
    research: Mapped[dict] = mapped_column(JSON, default=dict)


class Site(Record, Base):
    __tablename__ = "generated_sites"
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(Text, default="generated", index=True)
    files: Mapped[dict] = mapped_column(JSON)
    metadata_json: Mapped[dict] = mapped_column(JSON)
    deploy_id: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("prospect_id", "version"),)


class Message(Record, Base):
    __tablename__ = "outreach_messages"
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id"), index=True)
    kind: Mapped[str] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True)
    rfc_message_id: Mapped[str] = mapped_column(Text, unique=True)
    state: Mapped[str] = mapped_column(Text, default="prepared", index=True)
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    recipient: Mapped[str] = mapped_column(Text)
    draft_id: Mapped[str | None] = mapped_column(Text)
    gmail_id: Mapped[str | None] = mapped_column(Text, unique=True)
    thread_id: Mapped[str | None] = mapped_column(Text, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("prospect_id", "kind", "sequence"),)


class GmailThread(Record, Base):
    __tablename__ = "gmail_threads"
    thread_id: Mapped[str] = mapped_column(Text, unique=True)
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id"), index=True)
    seen_ids: Mapped[list] = mapped_column(JSON, default=list)


class Followup(Record, Base):
    __tablename__ = "followups"
    prospect_id: Mapped[str] = mapped_column(ForeignKey("prospects.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    message_id: Mapped[str | None] = mapped_column(ForeignKey("outreach_messages.id"))
    status: Mapped[str] = mapped_column(Text, default="pending")
    __table_args__ = (UniqueConstraint("prospect_id", "sequence"),)


class Suppression(Record, Base):
    __tablename__ = "suppressions"
    key: Mapped[str] = mapped_column(Text, unique=True)
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text)


class CountryPolicy(Record, Base):
    __tablename__ = "country_policies"
    country: Mapped[str] = mapped_column(String(2), unique=True)
    policy: Mapped[dict] = mapped_column(JSON)


class LocationQueue(Record, Base):
    __tablename__ = "location_queue"
    country: Mapped[str] = mapped_column(String(2), index=True)
    city: Mapped[str] = mapped_column(Text)
    niche: Mapped[str] = mapped_column(Text)
    last_search: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    searches: Mapped[int] = mapped_column(Integer, default=0)
    relevant: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("country", "city", "niche"),)


class WorkflowRun(Record, Base):
    __tablename__ = "workflow_runs"
    run_key: Mapped[str] = mapped_column(Text, unique=True)
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="running")
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class Event(Record, Base):
    __tablename__ = "run_events"
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    event: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON)


class Configuration(Record, Base):
    __tablename__ = "configuration"
    key: Mapped[str] = mapped_column(Text, unique=True)
    value: Mapped[dict] = mapped_column(JSON)


class CostUsage(Record, Base):
    __tablename__ = "cost_usage"
    provider: Mapped[str] = mapped_column(Text)
    operation: Mapped[str] = mapped_column(Text)
    key: Mapped[str] = mapped_column(Text, unique=True)
    reserved_usd: Mapped[float] = mapped_column(Float, default=0)
    actual_usd: Mapped[float | None] = mapped_column(Float)
    units: Mapped[dict] = mapped_column(JSON, default=dict)


def engine_for(url, *, test=False):
    if not test and not url.startswith("postgresql+psycopg://"):
        raise ValueError("Production requires postgresql+psycopg:// persistent PostgreSQL")
    return create_engine(url, pool_pre_ping=True)


LOCK_KEY = int.from_bytes(hashlib.sha256(b"global-website-agent-v1").digest()[:8], "big", signed=True)


@contextmanager
def locked_session(engine):
    """One session-level PostgreSQL lock shared by every mutating CLI command."""
    with engine.connect() as conn:
        pg = engine.dialect.name == "postgresql"
        if pg and not conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar():
            raise RuntimeError("Another agent workflow holds the database lock")
        conn.commit()
        try:
            with Session(bind=conn, expire_on_commit=False) as session:
                yield session
        finally:
            conn.rollback()
            if pg:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
                conn.commit()


def get_config(session, key):
    row = session.scalar(select(Configuration).where(Configuration.key == key))
    return row.value if row else {}


def assert_lock(session):
    """Detect a reconnected PostgreSQL session that lost its session-level lock."""
    if session.bind.dialect.name == "postgresql":
        held = session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' "
                "AND pid=pg_backend_pid() AND granted AND classid=:hi AND objid=:lo)"
            ),
            {"hi": (LOCK_KEY & 0xFFFFFFFFFFFFFFFF) >> 32, "lo": LOCK_KEY & 0xFFFFFFFF},
        )
        if not held:
            raise RuntimeError("Database ownership lost; refusing external action")


def set_config(session, key, value):
    row = session.scalar(select(Configuration).where(Configuration.key == key))
    if row:
        row.value = value
    else:
        session.add(Configuration(key=key, value=value))
    session.commit()


def suppress(session, key, reason, evidence):
    key = key.strip().lower()
    if not session.scalar(select(Suppression).where(Suppression.key == key)):
        session.add(Suppression(key=key, reason=reason, evidence=evidence))
    session.commit()
