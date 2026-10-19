import base64
from email.message import EmailMessage
from email.utils import formataddr, getaddresses

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from website_agent.discovery import api_get
from website_agent.security import Blocked, email_address

SCOPES = ["https://www.googleapis.com/auth/gmail.compose", "https://www.googleapis.com/auth/gmail.readonly"]


def mime_message(settings, recipient, subject, body, message_id, reply_id=None):
    msg = EmailMessage()
    msg["From"] = formataddr((settings.sender_name, email_address(settings.sender_email)))
    msg["To"] = email_address(recipient)
    msg["Reply-To"] = email_address(settings.reply_to)
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg["List-Unsubscribe"] = f"<mailto:{email_address(settings.reply_to)}?subject=unsubscribe>"
    if reply_id:
        msg["In-Reply-To"] = reply_id
        msg["References"] = reply_id
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def headers(message):
    return {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}


def text_body(message):
    def walk(part):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            raw = part["body"]["data"]
            return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", errors="replace")[
                :12000
            ]
        return "\n".join(walk(p) for p in part.get("parts", []))[:12000]

    return walk(message.get("payload", {})) or message.get("snippet", "")[:12000]


class Gmail:
    def __init__(self, settings, client=None, credentials=None):
        settings.require("gmail_client_id", "gmail_client_secret", "gmail_refresh_token", "sender_email")
        self.settings = settings
        self.credentials = credentials or Credentials(
            token=None,
            refresh_token=settings.gmail_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.gmail_client_id,
            client_secret=settings.gmail_client_secret,
            scopes=SCOPES,
        )
        self.client = client or httpx.Client(
            base_url="https://gmail.googleapis.com/gmail/v1/users/me/", timeout=30
        )

    def auth(self):
        if not self.credentials.valid:
            self.credentials.refresh(Request())
        return {"Authorization": "Bearer " + self.credentials.token}

    def get(self, path, **params):
        return api_get(self.client, path, headers=self.auth(), params=params).json()

    def post(self, path, body):
        # Gmail has no general idempotency token. NEVER blindly retry POST.
        response = self.client.post(path, json=body, headers=self.auth())
        response.raise_for_status()
        return response.json()

    def verify_sender(self):
        profile = self.get("profile")
        if profile["emailAddress"].lower() != email_address(self.settings.sender_email):
            raise Blocked("OAuth mailbox and sender identity differ; aliases are intentionally disabled")
        if email_address(self.settings.reply_to) != email_address(self.settings.sender_email):
            raise Blocked("Reply-to must use the monitored mailbox to enforce opt-outs")
        return profile

    def messages(self, query, *, max_pages=100):
        token = None
        for _ in range(max_pages):
            params = {"q": query, "maxResults": 100, "includeSpamTrash": "true"}
            if token:
                params["pageToken"] = token
            result = self.get("messages", **params)
            for msg in result.get("messages", []):
                yield self.get("messages/" + msg["id"], format="full")
            token = result.get("nextPageToken")
            if not token:
                return
        raise Blocked("Gmail pagination limit reached; scan is incomplete")

    def draft(self, raw, thread_id=None):
        message = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id
        result = self.post("drafts", {"message": message})
        if not result.get("id") or not result.get("message", {}).get("id"):
            raise Blocked("Gmail draft response lacks IDs")
        verified = self.get("drafts/" + result["id"], format="full")
        if verified.get("id") != result["id"]:
            raise Blocked("Draft verification failed")
        return result

    def send(self, raw, thread_id=None):
        body = {"raw": raw}
        if thread_id:
            body["threadId"] = thread_id
        result = self.post("messages/send", body)
        if not result.get("id"):
            raise Blocked("Gmail send response lacks ID")
        return self.verify_sent(result["id"])

    def verify_sent(self, message_id):
        result = self.get("messages/" + message_id, format="full")
        if "SENT" not in result.get("labelIds", []) or not result.get("threadId"):
            raise Blocked("Gmail message not verified as sent")
        return result

    def reconcile(self, rfc_message_id):
        results = list(self.messages("in:sent rfc822msgid:" + rfc_message_id.strip("<>")))
        matches = [m for m in results if headers(m).get("message-id", "").strip() == rfc_message_id]
        if len(matches) > 1:
            raise Blocked("Duplicate Gmail Message-ID; manual reconciliation required")
        return self.verify_sent(matches[0]["id"]) if matches else None

    def prior_contact(self, address, own_ids):
        query = "in:sent to:" + email_address(address)
        return any(m["id"] not in own_ids for m in self.messages(query))

    def incoming(self, address):
        return self.messages("from:" + email_address(address))


def recipients(message):
    hdr = headers(message)
    return [
        email_address(a)
        for _, a in getaddresses([hdr.get(k, "") for k in ("to", "cc", "bcc")])
        if a and "@" in a
    ]
