"""Run locally once. Writes a private token file; never prints refresh tokens."""

import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from website_agent.gmail import SCOPES


def main():
    client_file = os.environ["GMAIL_OAUTH_CLIENT_FILE"]
    flow = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    Path("private").mkdir(exist_ok=True)
    target = Path("private/gmail-token.json")
    target.write_text(creds.to_json(), encoding="utf-8")
    target.chmod(0o600)
    print(
        "Saved private/gmail-token.json. Store its refresh_token in GMAIL_REFRESH_TOKEN, then securely remove the file."
    )


if __name__ == "__main__":
    main()
