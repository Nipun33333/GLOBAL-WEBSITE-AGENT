"""Load private, reviewed outreach evidence without inventing recipient permission."""

import json
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from website_agent.compliance import Policy
from website_agent.security import Blocked, domain, email_address


class RecipientEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, str_strip_whitespace=True)

    domain: str
    verified_email: str
    email_evidence_reference: str = Field(min_length=1)
    basis: str = Field(min_length=1)
    evidence_reference: str = Field(min_length=1)
    reviewed_by: str = Field(min_length=1)
    valid_until: date
    contact_type: str = Field(min_length=1)

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value):
        normalized = domain(value)
        if not normalized or "." not in normalized:
            raise ValueError("A business domain is required")
        return normalized

    @field_validator("verified_email")
    @classmethod
    def normalize_email(cls, value):
        return email_address(value)


class ReviewedPolicy(Policy):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, str_strip_whitespace=True)


class OutreachAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    country: str = Field(pattern="^GB$")
    policy: ReviewedPolicy
    recipients: list[RecipientEvidence] = Field(max_length=500)

    @model_validator(mode="after")
    def reviewed_policy(self):
        p = self.policy
        if p.enabled:
            if not all(v.strip() for v in (p.reviewed_by, p.legal_reference, p.valid_until)):
                raise ValueError("Enabled policy requires review and expiry")
            date.fromisoformat(p.valid_until)
            if not p.allowed_bases or not p.allowed_contact_types:
                raise ValueError("Enabled policy requires permitted bases and contact types")
        if not 0 <= p.contact_hours[0] < p.contact_hours[1] <= 24:
            raise ValueError("Invalid contact hours")
        if len({r.domain for r in self.recipients}) != len(self.recipients):
            raise ValueError("Duplicate recipient domains")
        if any(
            r.basis not in p.allowed_bases or r.contact_type not in p.allowed_contact_types
            for r in self.recipients
        ):
            raise ValueError("Recipient evidence is outside the reviewed policy")
        return self


def load_authorization(settings):
    raw = settings.outreach_authorization_json
    if not raw:
        return None
    try:
        if len(raw.encode("utf-8")) > 48_000:
            raise ValueError("Authorization exceeds secret size budget")
        return OutreachAuthorization.model_validate(json.loads(raw))
    except Exception:
        # Validation errors can contain complete private evidence and addresses.
        raise Blocked("Invalid OUTREACH_AUTHORIZATION_JSON; check the private setup guide") from None


def apply_recipient_evidence(session, prospect, authorization):
    """Match an actual discovered business; never create leads or clear suppressions."""
    if authorization is None:
        return
    record = next((r for r in authorization.recipients if r.domain == prospect.domain), None)
    if prospect.country != authorization.country or record is None:
        raise Blocked("No matching recipient in OUTREACH_AUTHORIZATION_JSON")
    prospect.eligibility = record.model_dump(
        mode="json", exclude={"domain", "verified_email", "email_evidence_reference"}
    )
    prospect.email = record.verified_email
    prospect.contact_evidence = {
        "observed": True,
        "method": "reviewed_import",
        "reference": record.email_evidence_reference,
    }
    session.commit()


def authorization_readiness(settings):
    authorization = load_authorization(settings)
    if authorization is None:
        policies = yaml.safe_load(Path(settings.policy_path).read_text(encoding="utf-8"))
        policy = Policy.model_validate(policies.get("GB", {}))
        return {
            "source": "policy_file_and_database",
            "authorization_secret": "not_configured",
            "policy_enabled": policy.enabled,
        }
    return {
        "source": "authorization_secret",
        "policy_enabled": authorization.policy.enabled,
        "recipient_records": len(authorization.recipients),
    }
