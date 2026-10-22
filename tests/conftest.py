from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from website_agent.ai import Design, EmailCopy, ReplyClassification, Research
from website_agent.database import Base, Prospect, Site, engine_for
from website_agent.security import Page
from website_agent.settings import Settings


@pytest.fixture
def session():
    engine = engine_for("sqlite:///:memory:", test=True)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as value:
        yield value
    engine.dispose()


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        gemini_api_key="test",
        enable_generation=True,  # Explicit permission for isolated mocked fixtures.
        enable_deployment=True,
        enable_drafts=True,
        discovery_api_key="test",
        netlify_auth_token="test",
        netlify_site_id="site-1",
        gmail_client_id="test",
        gmail_client_secret="test",
        gmail_refresh_token="test",
        sender_email="owner@example.net",
        reply_to="owner@example.net",
        sender_name="Example Studio",
        sender_postal_address="Verified business address",
        owner_email="owner@example.net",
    )


@pytest.fixture
def config(settings):
    from website_agent.settings import ModelAuthorization

    cfg = settings.config()
    cfg.weak_websites_only = True  # Historical quality-filter fixtures opt in explicitly.
    # Historical test fixtures intentionally use invented US/IN addresses.
    # Production settings and the actual GitHub Actions workflow remain GB-only.
    from website_agent.settings import Location

    cfg.operating_country = "US"  # Fixture override, never a production setting.
    cfg.locations = [
        Location(
            country="US", city="New York", timezone="America/New_York",
            language="en", subdivision="NY", bbox=[-74.05, 40.65, -73.85, 40.85],
        ),
        Location(
            country="IN", city="Mumbai", timezone="Asia/Kolkata",
            language="hi", subdivision="MH", bbox=[72.78, 18.9, 72.98, 19.2],
        ),
    ]
    cfg.gemini.usage_authorizations = {
        model: ModelAuthorization(tier="free", review_reference="offline fixture", expires_on="2099-01-01")
        for model in cfg.gemini.capabilities
    }
    return cfg


@pytest.fixture
def prospect(session):
    p = Prospect(
        name="Sample Salon",
        domain="sample.example",
        url="https://sample.example/",
        country="US",
        city="New York",
        timezone="America/New_York",
        subdivision="NY",
        language="en",
        niche="salons",
        email="contact@sample.example",
        contact_evidence={"observed": True},
        status="qualified",
    )
    session.add(p)
    session.commit()
    return p


@pytest.fixture
def site(session, prospect):
    s = Site(
        prospect_id=prospect.id,
        files={},
        metadata_json={},
        status="verified",
        url="https://deploy--sample.netlify.app",
        verified_at=datetime(2026, 10, 20, tzinfo=UTC),
    )
    session.add(s)
    session.commit()
    return s


class FakeAI:
    def generate(self, task, data, schema):
        if schema is Research:
            return Research(
                is_local_business=True,
                business_name_quote="Sample Salon",
                summary="Salon",
                relevance_reason="Local business",
                evidence_quotes=["Haircuts"],
                language="en",
            )
        if schema is Design:
            return Design(
                title_quote="Sample Salon",
                hero_quote="Haircuts",
                service_quotes=["Haircuts"],
                theme="forest",
                layout="cards",
                language="en",
                direction="ltr",
                navigation_label="Menu",
                services_label="Services",
                contact_label="Contact",
                concept_label="Independent unofficial concept",
            )
        if schema is EmailCopy:
            return EmailCopy(
                subject="An independent website concept",
                opening="I prepared an independent website concept.",
                invitation="Would you like to discuss it?",
            )
        return ReplyClassification(category="Interested", reason="Asked for information")


class FakeWeb:
    def fetch(self, url, **kwargs):
        return Page(
            url,
            200,
            {"content-type": "text/html"},
            '<html><body><h1>Sample Salon</h1><p>Haircuts</p><a href="mailto:contact@sample.example">Contact</a></body></html>',
        )


class FakeGmail:
    def __init__(self):
        self.drafts = 0
        self.sends = 0
        self.incoming_messages = []
        self.external = False
        self.raise_send = False
        self.found = None

    def verify_sender(self):
        return {"emailAddress": "owner@example.net"}

    def draft(self, raw, thread_id=None):
        self.drafts += 1
        return {"id": "draft-1", "message": {"id": "draft-message-1"}}

    def send(self, raw, thread_id=None, draft_id=None):
        self.sends += 1
        if self.raise_send:
            raise TimeoutError()
        import base64
        from email import message_from_bytes

        msg = message_from_bytes(base64.urlsafe_b64decode(raw))
        return {
            "id": "sent-1",
            "threadId": "thread-1",
            "labelIds": ["SENT"],
            "internalDate": str(int(datetime(2026, 10, 20, 15, tzinfo=UTC).timestamp() * 1000)),
            "payload": {"headers": [{"name": "Message-ID", "value": msg["Message-ID"]}]},
        }

    def reconcile(self, message_id):
        return self.found

    def prior_contact(self, address, own_ids):
        return self.external

    def incoming(self, address):
        return iter(self.incoming_messages)

    def messages(self, query):
        return iter(self.incoming_messages)


@pytest.fixture
def fakes():
    return SimpleNamespace(ai=FakeAI(), gmail=FakeGmail(), web=FakeWeb())
