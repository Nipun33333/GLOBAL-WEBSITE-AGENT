from sqlalchemy import func, select

from website_agent.ai import Design
from website_agent.database import Message, Prospect, Site, now
from website_agent.generation import render, validate
from website_agent.outreach import create_draft
from website_agent.security import Blocked


def live_smoke(pipeline):
    """Explicit integration test; all source/draft state is durable, no sending path."""
    pipeline.settings.require("owner_email", "sender_name", "sender_postal_address")
    session = pipeline.session
    today = now().replace(hour=0, minute=0, second=0, microsecond=0)
    count = session.scalar(select(func.count()).select_from(Site).where(Site.created_at >= today))
    if count >= pipeline.config.limits.previews_daily:
        raise Blocked("Global preview cap reached, including verification previews")
    prospect = session.scalar(select(Prospect).where(Prospect.domain == "agent-verification.invalid"))
    if not prospect:
        prospect = Prospect(
            domain="agent-verification.invalid",
            name="Website Agent Verification",
            url="https://example.com",
            country="ZZ",
            city="internal",
            timezone="UTC",
            language="en",
            niche="internal verification",
            status="internal",
        )
        session.add(prospect)
        session.commit()
    version = (session.scalar(select(func.max(Site.version)).where(Site.prospect_id == prospect.id)) or 0) + 1
    snippets = [
        "Website Agent Verification",
        "An independent demonstration of responsive website design.",
        "Accessible navigation",
        "Responsive layouts",
    ]
    design = pipeline.ai.generate(
        "Design a responsive page using only these exact quotations. Use English labels.",
        {"snippets": snippets},
        Design,
    )
    site = Site(prospect_id=prospect.id, version=version, files={}, metadata_json={"internal_smoke": True})
    session.add(site)
    session.flush()
    site.files = render(design, {"snippets": snippets}, "https://example.com", site.id)
    site.metadata_json = {"internal_smoke": True, "sha256": validate(site.files)}
    session.commit()
    pipeline.deploy(site)
    message = Message(
        prospect_id=prospect.id,
        kind="internal_smoke",
        sequence=version,
        idempotency_key="smoke:" + site.id,
        rfc_message_id=f"<gwa-smoke-{site.id}@{pipeline.settings.sender_email.split('@')[-1]}>",
        recipient=pipeline.settings.owner_email,
        subject="Website Agent integration verification",
        body="Internal verification only. No prospect has been contacted.\n" + site.url,
        details={},
    )
    session.add(message)
    session.commit()
    create_draft(session, pipeline.gmail, pipeline.settings, message)
    pipeline.log(
        "live_smoke_verified", preview=site.url, draft_id=message.draft_id, browser=site.verification
    )
