from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import select

from website_agent.database import CountryPolicy, Suppression
from website_agent.scheduler import contact_time
from website_agent.security import domain, email_address

SEND_BLOCK_REASONS = frozenset({
    "sending_disabled", "missing_sender_name", "missing_sender_email", "missing_reply_to",
    "missing_sender_postal_address", "missing_owner_email", "no_verified_business_email",
    "contact_not_verified", "suppressed", "prospect_stopped", "reply_received",
    "unverified_country_policy", "insufficient_legal_basis", "eligibility_expired",
    "eligibility_expiry_required", "contact_type_not_permitted", "invalid_contact_hours",
    "outside_local_contact_window",
})


class Policy(BaseModel):
    enabled: bool = False
    reviewed_by: str = ""
    legal_reference: str = ""
    valid_until: str = ""
    allowed_bases: list[str] = Field(default_factory=list)
    allowed_contact_types: list[str] = Field(default_factory=list)
    contact_hours: list[int] = Field(default_factory=lambda: [9, 17], min_length=2, max_length=2)


def eligible(session, prospect, settings, at, *, routine=False):
    reasons = []
    if not settings.enable_sending:
        reasons.append("sending_disabled")
    for field in ("sender_name", "sender_email", "reply_to", "sender_postal_address", "owner_email"):
        if not getattr(settings, field):
            reasons.append("missing_" + field)
    try:
        address = email_address(prospect.email or "")
    except ValueError:
        return False, reasons + ["no_verified_business_email"]
    if not prospect.contact_evidence.get("observed"):
        reasons.append("contact_not_verified")
    # A parent-domain opt-out also covers a subsequently discovered subdomain.
    parts = domain(prospect.domain).split(".")
    excluded = [address, *(".".join(parts[i:]) for i in range(len(parts)))]
    if session.scalar(select(Suppression).where(Suppression.key.in_(excluded))):
        reasons.append("suppressed")
    if prospect.imported or prospect.status in {
        "rejected",
        "unsubscribed",
        "delivery_failure",
        "disqualified",
    }:
        reasons.append("prospect_stopped")
    if prospect.replied_at and not routine:
        reasons.append("reply_received")
    # Suppression records are durable; send_controlled performs a fresh Gmail
    # Sent + inbound scan per recipient immediately before any Gmail send.
    # Optional bulk history imports are never a precondition for this agent.
    row = session.scalar(select(CountryPolicy).where(CountryPolicy.country == prospect.country))
    policy = Policy.model_validate(row.policy if row else {})
    try:
        policy_valid = datetime.fromisoformat(policy.valid_until).date() >= at.date()
    except ValueError:
        policy_valid = False
    if not (policy.enabled and policy.reviewed_by and policy.legal_reference and policy_valid):
        reasons.append("unverified_country_policy")
    evidence = prospect.eligibility
    if (
        evidence.get("basis") not in policy.allowed_bases
        or not evidence.get("evidence_reference")
        or not evidence.get("reviewed_by")
    ):
        reasons.append("insufficient_legal_basis")
    try:
        if datetime.fromisoformat(evidence.get("valid_until", "")).date() < at.date():
            reasons.append("eligibility_expired")
    except ValueError:
        reasons.append("eligibility_expiry_required")
    if evidence.get("contact_type") not in policy.allowed_contact_types:
        reasons.append("contact_type_not_permitted")
    if not 0 <= policy.contact_hours[0] < policy.contact_hours[1] <= 24:
        reasons.append("invalid_contact_hours")
    elif not contact_time(
        at, prospect.country, prospect.timezone, policy.contact_hours, prospect.subdivision
    ):
        reasons.append("outside_local_contact_window")
    return not reasons, reasons
