import hashlib
import json
from pathlib import Path

from sqlalchemy import select

from website_agent.database import GmailThread, Prospect, get_config, now, set_config, suppress
from website_agent.gmail import recipients
from website_agent.security import Blocked, domain, email_address


def import_history(session, path):
    """Import external records conservatively: all prior contacts become suppression keys."""
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    if (
        not data.get("exported_at")
        or not data.get("source")
        or "contacts" not in data
        or "opt_outs" not in data
    ):
        raise ValueError("History JSON requires source, exported_at, contacts, opt_outs")
    # Validate entire file before applying records; malformed input cannot mark import complete.
    normalized = []
    for record in [*data["contacts"], *data["opt_outs"]]:
        address = email_address(record["email"]) if record.get("email") else None
        host = domain(record["domain"]) if record.get("domain") else None
        if not address and not host:
            raise ValueError("Every history record requires email or domain")
        normalized.append((record, address, host))
    for record, address, host in normalized:
        reason = "imported_opt_out" if record in data["opt_outs"] else "previous_contact"
        for key in [address, host]:
            if key:
                suppress(session, key, reason, data["source"])
        prospect = session.scalar(select(Prospect).where(Prospect.domain == host)) if host else None
        if not prospect and host:
            prospect = Prospect(
                domain=host,
                name=record.get("name", host),
                url="https://" + host,
                country=record.get("country", "ZZ"),
                city=record.get("city", "unknown"),
                timezone="UTC",
                language="en",
                niche="historical",
                email=address,
                imported=True,
                status="previous_contact",
            )
            session.add(prospect)
            session.flush()
        if prospect:
            prospect.imported = True
            prospect.status = "previous_contact"
            if thread_id := record.get("gmail_thread_id"):
                if not session.scalar(select(GmailThread).where(GmailThread.thread_id == thread_id)):
                    session.add(GmailThread(thread_id=thread_id, prospect_id=prospect.id, seen_ids=[]))
    digest = hashlib.sha256(raw).hexdigest()
    set_config(
        session,
        "history_import",
        {"digest": digest, "count": len(normalized), "at": now().isoformat(), "source": data["source"]},
    )
    return len(normalized)


def import_gmail_history(session, gmail):
    gmail.verify_sender()
    count = 0
    own = set()
    from website_agent.database import Message

    own.update(m.gmail_id for m in session.scalars(select(Message)) if m.gmail_id)
    for message in gmail.messages("in:sent", max_pages=1000):
        if message["id"] in own:
            continue
        for address in recipients(message):
            suppress(session, address, "verified_gmail_history", "gmail:" + message["id"])
            count += 1
            prospect = session.scalar(select(Prospect).where(Prospect.email == address))
            if prospect and not session.scalar(
                select(GmailThread).where(GmailThread.thread_id == message["threadId"])
            ):
                session.add(
                    GmailThread(
                        thread_id=message["threadId"], prospect_id=prospect.id, seen_ids=[message["id"]]
                    )
                )
    set_config(session, "gmail_history_import", {"completed": True, "count": count, "at": now().isoformat()})
    return count


def validate_history(session, path):
    attestation = json.loads(Path(path).read_text(encoding="utf-8"))
    imported = get_config(session, "history_import")
    gmail = get_config(session, "gmail_history_import")
    required = [
        "reviewed_by",
        "suppression_export_complete",
        "history_export_complete",
    ]
    if (
        not imported.get("digest")
        or not gmail.get("completed")
        or any(not attestation.get(k) for k in required)
        or attestation.get("suppression_export_complete") is not True
        or attestation.get("history_export_complete") is not True
    ):
        raise Blocked("Optional history validation needs completed imports and an owner-reviewed export")
    if attestation.get("import_digest") != imported["digest"]:
        raise Blocked("Attestation must reference exact history import SHA-256")
    set_config(
        session, "external_history_review", {**attestation, "validated": True, "validated_at": now().isoformat()}
    )


def import_eligibility(session, path):
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    for data in records:
        prospect = session.scalar(select(Prospect).where(Prospect.domain == domain(data["domain"])))
        if not prospect:
            raise ValueError("Eligibility refers to unknown prospect domain")
        allowed = {
            "basis",
            "evidence_reference",
            "reviewed_by",
            "valid_until",
            "contact_type",
            "routine_reply_authorized",
        }
        prospect.eligibility = {k: v for k, v in data.items() if k in allowed}
        # Explicit verified business address can be provided if role-mailto discovery found none.
        if data.get("verified_email") and data.get("email_evidence_reference"):
            prospect.email = email_address(data["verified_email"])
            prospect.contact_evidence = {
                "observed": True,
                "method": "reviewed_import",
                "reference": data["email_evidence_reference"],
            }
    session.commit()
