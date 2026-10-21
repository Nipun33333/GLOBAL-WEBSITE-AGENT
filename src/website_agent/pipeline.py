from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text

from website_agent.ai import Design, Gemini, Research
from website_agent.analysis import inspect_site, quote_in_evidence
from website_agent.database import (
    Audit,
    BusinessSource,
    Followup,
    LocationQueue,
    Message,
    Prospect,
    Site,
    Suppression,
    WorkflowRun,
    assert_lock,
    get_config,
    now,
    set_config,
)
from website_agent.discovery import SearchProvider
from website_agent.generation import render, validate
from website_agent.gmail import Gmail
from website_agent.hosting import Netlify, verify_preview
from website_agent.outreach import create_draft, followup_eligible, prepare, process_reply, send_controlled
from website_agent.reporting import event
from website_agent.scheduler import business_due, rotate
from website_agent.security import Blocked, CapacityDeferred, PublicWeb, domain


class Pipeline:
    def __init__(
        self,
        session,
        settings,
        config,
        *,
        ai=None,
        discovery=None,
        hosting=None,
        gmail=None,
        web=None,
        verifier=None,
    ):
        self.session, self.settings, self.config = session, settings, config
        self._ai, self.discovery, self._hosting, self._gmail = ai, discovery, hosting, gmail
        self.web = web or PublicWeb(settings.research_user_agent)
        self.verifier = verifier or verify_preview
        self.run = None
        self.discovery_outcome = None
        self.initial_sends_this_run = 0  # Strictly one new outreach message per workflow run.

    @property
    def ai(self):
        if self._ai is None:
            self._ai = Gemini(self.settings, self.config, self.session)
        return self._ai

    @property
    def gmail(self):
        if self._gmail is None:
            self._gmail = Gmail(self.settings)
        return self._gmail

    @property
    def hosting(self):
        if self._hosting is None:
            self._hosting = Netlify(self.settings)
        return self._hosting

    def log(self, name, **details):
        event(self.session, self.run, name, **details)

    def generate_reply_classification(self, task, data, schema):
        return self.ai.generate(task, data, schema)

    def step(self, name, fn, prospect=None):
        try:
            return fn()
        except CapacityDeferred as exc:
            self.session.rollback()
            self.log(
                "capacity_deferred",
                stage=name,
                reason=str(exc),
                prospect_id=prospect.id if prospect else None,
            )
            return None
        except Exception as exc:
            self.session.rollback()
            # Never persist arbitrary exception text: requests may include secrets/PII.
            self.log(
                "failure",
                stage=name,
                error_type=type(exc).__name__,
                reason=str(exc) if isinstance(exc, Blocked) else "See doctor and stage configuration",
                prospect_id=prospect.id if prospect else None,
            )
            return None

    def start(self, kind, run_key):
        self.run = self.session.scalar(select(WorkflowRun).where(WorkflowRun.run_key == run_key))
        if self.run and self.run.status.startswith("completed"):
            return False
        if not self.run:
            self.run = WorkflowRun(kind=kind, run_key=run_key, summary={})
            self.session.add(self.run)
        else:
            self.run.status = "running"
        self.session.commit()
        return True

    def schedule_slot(self):
        """A durable local-time slot; each approved daily slot may run once."""
        local = now().astimezone(ZoneInfo(self.config.schedule_timezone))
        if self.config.schedule_hours:
            due = [hour for hour in self.config.schedule_hours if hour <= local.hour]
            if not due:
                return None
            return f"{local.date().isoformat()}@{max(due):02d}"
        return local.date().isoformat() if local.hour >= self.config.schedule_hour else None

    def scheduled_due(self):
        slot = self.schedule_slot()
        checkpoint = get_config(self.session, "daily_checkpoint")
        return bool(slot) and checkpoint.get("slot", checkpoint.get("date")) != slot

    def verify(self, site):
        result = self.verifier(self.web, site.url, site.id)
        site.verification, site.verified_at, site.status = result, now(), "verified"
        self.session.commit()
        return result

    def database_capacity(self):
        if self.session.bind.dialect.name == "postgresql":
            size = self.session.scalar(text("SELECT pg_database_size(current_database())"))
            self.log("database_quota", used_bytes=size, configured_max_mb=self.config.limits.database_max_mb)
            if size >= self.config.limits.database_max_mb * 1024 * 1024:
                raise Blocked("Configured database storage cap reached")

    def discover(self, country=None):
        if self.config.discovery_provider == "open_data" and self.discovery is None:
            from website_agent.discovery_engine import DiscoveryEngine

            self.discovery_outcome = DiscoveryEngine(self.session, self.settings, self.config).run(country)
            self.log("discovery_outcome", **self.discovery_outcome)
            return self.discovery_outcome["status"].startswith("completed")
        selected = rotate(self.session, self.config, country)
        if not selected:
            self.log("location_deferred", reason="no eligible local research window")
            return False
        queue, location = selected
        self.log("location_searched", country=location.country, city=location.city, niche=queue.niche)
        provider = self.discovery or SearchProvider(self.settings, self.config)
        results = provider.discover(location, queue.niche, self.config.limits.discovered)
        for item in results:
            host = domain(str(item.url))
            if not host or self.session.scalar(select(Prospect).where(Prospect.domain == host)):
                continue
            if self.session.scalar(select(Suppression).where(Suppression.key == host)):
                continue
            if self.session.scalar(
                select(BusinessSource).where(
                    BusinessSource.provider == self.config.discovery_provider,
                    BusinessSource.provider_id == item.provider_id,
                )
            ):
                continue
            prospect = Prospect(
                domain=host,
                name=item.name,
                url=str(item.url),
                country=location.country,
                city=location.city,
                timezone=location.timezone,
                subdivision=location.subdivision,
                language=location.language,
                niche=queue.niche,
            )
            self.session.add(prospect)
            self.session.flush()
            self.session.add(
                BusinessSource(
                    prospect_id=prospect.id,
                    provider=self.config.discovery_provider,
                    provider_id=item.provider_id,
                    evidence={
                        "agreement": self.config.provider_agreement_reference,
                        "discovered_at": now().isoformat(),
                        "verified_business": False,
                    },
                )
            )
            self.session.commit()
            self.log("discovered", prospect_id=prospect.id)
        return True

    def audit(self, prospect):
        audit = self.session.scalar(select(Audit).where(Audit.prospect_id == prospect.id))
        if not audit:
            data = inspect_site(self.web, prospect.url)
            audit = Audit(prospect_id=prospect.id, score=data["score"], evidence=data, research={})
            self.session.add(audit)
            prospect.email = data["contact"].get("email")
            prospect.contact_evidence = data["contact"]
            prospect.status = "audited"
            self.session.commit()
            self.log("inspected", prospect_id=prospect.id, score=audit.score)
        if audit.score >= self.config.limits.threshold:
            prospect.status = "disqualified"
            self.session.commit()
            self.log("strong_website_disqualified", prospect_id=prospect.id, score=audit.score)
            return
        research = self.ai.generate(
            "Determine if the evidence is an actual local business website, not a directory. "
            "Summarize business services and relevance. Quote the actual business name and supporting evidence verbatim from snippets.",
            {"snippets": audit.evidence["snippets"], "location": prospect.city, "niche": prospect.niche},
            Research,
        )
        if (
            not research.is_local_business
            or not research.evidence_quotes
            or not all(
                quote_in_evidence(q, audit.evidence["snippets"])
                for q in [research.business_name_quote, *research.evidence_quotes]
            )
        ):
            prospect.status = "disqualified"
        else:
            prospect.name = research.business_name_quote
            prospect.status = "qualified"
            source = self.session.scalar(
                select(BusinessSource).where(BusinessSource.prospect_id == prospect.id)
            )
            discovery_evidence = source.evidence if source else {}
            queue = self.session.scalar(
                select(LocationQueue).where(
                    LocationQueue.country == prospect.country,
                    LocationQueue.city == discovery_evidence.get("rotation_city", prospect.city),
                    LocationQueue.niche == discovery_evidence.get("requested_niche", prospect.niche),
                )
            )
            if queue:
                queue.relevant += 1
        audit.research = {**research.model_dump(), "gemini": getattr(self.ai, "last_provenance", {})}
        self.session.commit()
        self.log(prospect.status, prospect_id=prospect.id, score=audit.score)

    def generate(self, prospect):
        existing = self.session.scalar(select(Site).where(Site.prospect_id == prospect.id))
        if existing:
            return existing
        today = now().replace(hour=0, minute=0, second=0, microsecond=0)
        count = self.session.scalar(select(func.count()).select_from(Site).where(Site.created_at >= today))
        if count >= self.config.limits.previews_daily:
            raise CapacityDeferred("Global daily preview cap reached")
        audit = self.session.scalar(select(Audit).where(Audit.prospect_id == prospect.id))
        design = self.ai.generate(
            "Plan a modern, accessible responsive website. All title, hero and service quotes must be "
            "verbatim excerpts from supplied snippets. Use source language for business text. Localize navigation/UI labels "
            "to the requested language. Choose theme, layout and text direction. Concept label must say unofficial independent concept.",
            {"snippets": audit.evidence["snippets"], "language": prospect.language},
            Design,
        )
        site = Site(
            prospect_id=prospect.id,
            version=1,
            files={},
            metadata_json={
                "design": design.model_dump(),
                "source": prospect.url,
                "gemini": getattr(self.ai, "last_provenance", {}),
            },
        )
        self.session.add(site)
        self.session.flush()
        site.files = render(design, audit.evidence, prospect.url, site.id)
        site.metadata_json = {**site.metadata_json, "sha256": validate(site.files)}
        self.session.commit()
        self.log("website_generated", prospect_id=prospect.id, site_id=site.id)
        return site

    def deploy(self, site):
        if site.status == "verified":
            return site
        if not self.settings.enable_deployment:
            raise CapacityDeferred("Netlify deployment requires separate approval")
        title = "gwa-" + site.id
        if not site.deploy_id:
            if site.status == "deploy_pending":
                result = self.hosting.find(title)
                if not result:
                    raise Blocked("Uncertain deploy submission; manual reconciliation required")
            else:
                site.status = "deploy_pending"
                self.session.commit()
                assert_lock(self.session)
                result = self.hosting.create(site.files, title)
            site.deploy_id = result["id"]
            site.status = "deploying"
            self.session.commit()
        site.url = self.hosting.ready(site.deploy_id)
        self.session.commit()
        self.verify(site)
        self.log("deployment_verified", site_id=site.id, url=site.url)
        return site

    def initial_outreach(self, prospect, site):
        if self.initial_sends_this_run >= 1:
            self.log("outreach_deferred", prospect_id=prospect.id, reason="one_initial_send_per_run")
            return
        if not prospect.email or not prospect.contact_evidence.get("observed"):
            prospect.status = "no_contact"
            self.session.commit()
            self.log(
                "outreach_deferred", prospect_id=prospect.id, reason="no verified public business mailbox"
            )
            return
        self.settings.require("sender_name", "sender_email", "reply_to", "sender_postal_address")
        message = prepare(self.session, prospect, site, self.settings, self.ai)
        old = message.state
        create_draft(self.session, self.gmail, self.settings, message)
        if message.state == "drafted":
            prospect.status = "draft_ready"
            self.session.commit()
        if old == "prepared" and message.state == "drafted":
            self.log("email_drafted", prospect_id=prospect.id, message_id=message.id)
        if self.settings.enable_sending:
            if send_controlled(self.session, self.gmail, self.settings, self.config, message, self.verify):
                self.initial_sends_this_run += 1
                self.log("email_sent", prospect_id=prospect.id, gmail_id=message.gmail_id)

    def daily(self, country=None, scheduled=False):
        if scheduled and not self.scheduled_due():
            self.log("schedule_not_due")
            return
        self.database_capacity()
        # Existing drafts don't occupy the generation selection window.
        for prospect in self.session.scalars(
            select(Prospect).where(Prospect.status == "draft_ready").order_by(Prospect.created_at).limit(1)
        ).all():
            site = self.session.scalar(
                select(Site).where(Site.prospect_id == prospect.id, Site.status == "verified")
            )
            if site:
                self.step("outreach", lambda p=prospect, s=site: self.initial_outreach(p, s), prospect)
        if self.initial_sends_this_run:
            return  # Never contact two different businesses in one invocation.
        schedule_date = now().astimezone(ZoneInfo(self.config.schedule_timezone)).date().isoformat()
        schedule_slot = self.schedule_slot() if scheduled else None
        discovery_checkpoint = get_config(self.session, "discovery_checkpoint")
        # Work through previously verified Overture prospects before spending
        # another bounded scan (which may consume five minutes and defer).
        # This is also important when the next provider retry is in the future.
        queued_business = self.session.scalar(
            select(Prospect.id)
            .where(Prospect.status.in_(["discovered", "audited", "qualified"]))
            .limit(1)
        )
        if queued_business is not None:
            discovered_location = False
            self.log("discovery_skipped", reason="existing_business_queue_has_priority")
        elif scheduled and discovery_checkpoint.get("slot", discovery_checkpoint.get("date")) == schedule_slot:
            discovered_location = True
        else:
            discovered_location = self.step("discovery", lambda: self.discover(country))
            if scheduled and discovered_location:
                set_config(self.session, "discovery_checkpoint", {"date": schedule_date, "slot": schedule_slot})
        query = (
            select(Prospect)
            .where(Prospect.status.in_(["discovered", "audited"]))
            .order_by(Prospect.created_at)
            .limit(self.config.limits.inspected)
        )
        for prospect in self.session.scalars(query).all():
            self.step("audit", lambda p=prospect: self.audit(p), prospect)
        query = (
            select(Prospect)
            .where(Prospect.status == "qualified")
            .order_by(Prospect.created_at)
            .limit(self.config.limits.qualified)
        )
        for prospect in self.session.scalars(query).all():
            site = self.step("generation", lambda p=prospect: self.generate(p), prospect)
            if not site:
                continue
            deployed = self.step("deployment", lambda s=site: self.deploy(s), prospect)
            if deployed:
                self.step("outreach", lambda p=prospect, s=site: self.initial_outreach(p, s), prospect)
        if (
            scheduled
            and discovered_location
            and not any(self.run.summary.get(k) for k in ("failure", "capacity_deferred"))
        ):
            set_config(
                self.session,
                "daily_checkpoint",
                {"date": schedule_date, "slot": schedule_slot},
            )

    def replies(self):
        self.gmail.verify_sender()
        # Two-day overlap and stable message IDs make checkpoint replay safe. Full history on first run.
        cursor = get_config(self.session, "reply_checkpoint")
        began = now()
        query = "-in:sent -in:drafts"
        if cursor.get("at"):
            from datetime import datetime

            since = datetime.fromisoformat(cursor["at"]) - timedelta(days=2)
            query += " after:" + str(int(since.timestamp()))
        from email.utils import parseaddr

        from website_agent.database import GmailThread
        from website_agent.gmail import failed_recipients, headers

        for incoming in self.gmail.messages(query):
            sender = parseaddr(headers(incoming).get("from", ""))[1].lower()
            prospect = self.session.scalar(select(Prospect).where(Prospect.email == sender))
            if not prospect and (failed := failed_recipients(incoming)):
                prospect = self.session.scalar(select(Prospect).where(Prospect.email.in_(failed)))
            if not prospect:
                thread = self.session.scalar(
                    select(GmailThread).where(GmailThread.thread_id == incoming["threadId"])
                )
                prospect = self.session.get(Prospect, thread.prospect_id) if thread else None
            if not prospect:
                # Keep opt-outs even if the business hasn't been discovered yet.
                from website_agent.database import suppress
                from website_agent.gmail import text_body
                from website_agent.outreach import STOP_PATTERNS

                if sender and STOP_PATTERNS.search(
                    headers(incoming).get("subject", "") + "\n" + text_body(incoming)
                ):
                    suppress(self.session, sender, "unsubscribe", "gmail:" + incoming["id"])
                continue
            # Defer Gemini initialization until classification truly needs it; opt-outs must
            # work even when the model/key is unavailable.
            category = self.step(
                "reply_classification",
                lambda p=prospect, msg=incoming: process_reply(self.session, p, msg, self),
                prospect,
            )
            if category:
                self.log("reply_classified", prospect_id=prospect.id, category=category)
                if category == "Unsubscribe":
                    self.log("unsubscribe", prospect_id=prospect.id)
                if category in {"Interested", "Needs Information"}:
                    self.log(
                        "owner_notification",
                        prospect_id=prospect.id,
                        category=category,
                        gmail_thread=incoming["threadId"],
                        action="Review Gmail thread; owner handles the conversation",
                    )
        # Retry saved acknowledgment work independently of already-classified messages.
        for prospect in self.session.scalars(
            select(Prospect).where(Prospect.status.in_(["interested", "needs_information"]))
        ).all():
            self.step("acknowledgment", lambda p=prospect: self.acknowledge(p), prospect)
        if not any(self.run.summary.get(k) for k in ("failure", "capacity_deferred")):
            set_config(self.session, "reply_checkpoint", {"at": began.isoformat()})

    def acknowledge(self, prospect):
        if not self.settings.enable_routine_replies:
            return  # Owner handles conversations; do not generate or create automatic reply drafts.
        site = self.session.scalar(
            select(Site).where(Site.prospect_id == prospect.id, Site.status == "verified")
        )
        if not site:
            return
        ack = prepare(self.session, prospect, site, self.settings, self.ai, "acknowledgment")
        create_draft(self.session, self.gmail, self.settings, ack)
        if self.settings.enable_routine_replies:
            send_controlled(self.session, self.gmail, self.settings, self.config, ack, self.verify)

    def followups(self):
        self.replies()  # Must complete successfully before ANY followup processing.
        if self.run.summary.get("failure"):
            raise Blocked("Reply synchronization incomplete; followups paused")
        if self.run.summary.get("capacity_deferred"):
            raise CapacityDeferred("Reply classification deferred; followups paused")
        for prospect in self.session.scalars(select(Prospect).where(Prospect.status == "contacted")).all():
            for sequence in range(1, self.config.limits.max_followups + 1):
                if not followup_eligible(self.session, prospect, self.config, now(), sequence):
                    continue
                site = self.session.scalar(
                    select(Site).where(Site.prospect_id == prospect.id, Site.status == "verified")
                )
                if not site:
                    continue
                message = prepare(self.session, prospect, site, self.settings, self.ai, "followup", sequence)
                row = self.session.scalar(
                    select(Followup).where(Followup.prospect_id == prospect.id, Followup.sequence == sequence)
                )
                if not row:
                    previous = self.session.scalar(
                        select(Message).where(
                            Message.prospect_id == prospect.id,
                            Message.kind == ("initial" if sequence == 1 else "followup"),
                            Message.sequence == sequence - 1,
                        )
                    )
                    row = Followup(
                        prospect_id=prospect.id,
                        sequence=sequence,
                        due_at=business_due(
                            previous.sent_at, prospect.country, prospect.timezone, prospect.subdivision
                        ),
                        message_id=message.id,
                    )
                    self.session.add(row)
                    self.session.commit()
                create_draft(self.session, self.gmail, self.settings, message)
                if send_controlled(
                    self.session, self.gmail, self.settings, self.config, message, self.verify
                ):
                    row.status = "sent"
                    self.session.commit()
                    self.log("followup_sent", prospect_id=prospect.id, sequence=sequence)

    def finish(self):
        if self.run.summary.get("failure"):
            self.run.status = "partial"
        elif self.run.summary.get("capacity_deferred"):
            self.run.status = "deferred_resource_limit"
        elif self.discovery_outcome and (
            self.run.kind == "discover" or not self.discovery_outcome["status"].startswith("completed")
        ):
            self.run.status = self.discovery_outcome["status"]
        else:
            self.run.status = "completed"
        self.session.commit()
