from website_agent.ai import Design
from website_agent.database import now, uid
from website_agent.generation import render
from website_agent.gmail import mime_message


def live_smoke(pipeline):
    """Explicit integration smoke test; draft only, addressed to the configured owner."""
    pipeline.settings.require("owner_email")
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
    key = uid()
    files = render(design, {"snippets": snippets}, "https://example.com", key)
    deployed = pipeline.hosting.create(files, "gwa-smoke-" + key)
    url = pipeline.hosting.ready(deployed["id"])
    verified = pipeline.verifier(pipeline.web, url, key)
    pipeline.gmail.verify_sender()
    raw = mime_message(
        pipeline.settings,
        pipeline.settings.owner_email,
        "Website Agent integration verification",
        "Internal verification only. No prospect has been contacted.\n" + url,
        f"<gwa-smoke-{key}@{pipeline.settings.sender_email.split('@')[-1]}>",
    )
    draft = pipeline.gmail.draft(raw)
    pipeline.log(
        "live_smoke_verified", preview=url, draft_id=draft["id"], browser=verified, at=now().isoformat()
    )
