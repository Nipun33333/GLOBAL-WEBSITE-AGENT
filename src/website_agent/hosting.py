import io
import time
import zipfile
from urllib.parse import urlsplit

import httpx
from playwright.sync_api import sync_playwright

from website_agent.discovery import api_get
from website_agent.generation import validate
from website_agent.security import Blocked, html_page


class Netlify:
    """Unique immutable draft deploys within one existing, dedicated Netlify project."""

    def __init__(self, settings, client=None):
        settings.require("netlify_auth_token", "netlify_site_id")
        self.settings = settings
        self.site_id = settings.netlify_site_id
        self.client = client or httpx.Client(
            base_url="https://api.netlify.com/api/v1/",
            timeout=60,
            headers={"Authorization": f"Bearer {settings.netlify_auth_token}"},
            follow_redirects=False,
        )

    def find(self, title):
        for page in range(1, 11):
            items = api_get(
                self.client, f"sites/{self.site_id}/deploys", params={"page": page, "per_page": 100}
            ).json()
            for item in items:
                if item.get("title") == title:
                    return item
            if len(items) < 100:
                return None
        raise Blocked("Deployment reconciliation exceeded pagination bound; manual review required")

    def create(self, files, title):
        if not self.settings.enable_deployment:
            raise Blocked("Netlify deployment is disabled")
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for path, content in files.items():
                z.writestr(path, content)
        response = self.client.post(
            f"sites/{self.site_id}/deploys",
            params={"draft": "true", "title": title},
            headers={"Content-Type": "application/zip"},
            content=archive.getvalue(),
        )
        response.raise_for_status()  # No automatic retry of deployment POST.
        result = response.json()
        if not result.get("id"):
            raise Blocked("Hosting response missing deployment ID")
        return result

    def ready(self, deploy_id):
        for _ in range(12):
            result = api_get(self.client, f"deploys/{deploy_id}").json()
            if result.get("state") == "error":
                raise Blocked("Hosting deployment failed")
            if result.get("state") == "ready":
                url = result.get("deploy_ssl_url", "")
                host = urlsplit(url).hostname or ""
                if (
                    not url.startswith("https://")
                    or not host.endswith(".netlify.app")
                    or not host.startswith(deploy_id + "--")
                ):
                    raise Blocked("Hosting did not return an immutable HTTPS deploy URL")
                return url
            time.sleep(2)
        raise Blocked("Deployment still pending; next workflow can resume verification")


def verify_preview(web, url, site_key):
    page = web.fetch(url, robots=False)
    html_page(page)
    if (
        f'content="{site_key}"' not in page.text
        or "Independent, unofficial redesign concept" not in page.text
    ):
        raise Blocked("Deployed content identity mismatch")
    checks = []
    # Browser receives only the already fetched static assets. All other network is blocked.
    # This avoids DNS rebinding and arbitrary browser subrequests; HTTP content is verified above.
    asset_map = {url.rstrip("/") + "/": ("text/html", page.text)}
    files = {"index.html": page.text}
    for asset, content_type in (("style.css", "text/css"), ("app.js", "application/javascript")):
        response = web.fetch(url.rstrip("/") + "/" + asset, robots=False)
        if response.status != 200 or "attachment" in response.headers.get("content-disposition", ""):
            raise Blocked("Deployed asset unavailable")
        files[asset] = response.text
        asset_map[url.rstrip("/") + "/" + asset] = (content_type, response.text)
    validate(files)  # Reject altered executable content before opening Chromium.
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for width in (375, 1280):
                context = browser.new_context(
                    viewport={"width": width, "height": 900}, service_workers="block"
                )

                def route(request_route):
                    target = request_route.request.url.split("#")[0]
                    if target in asset_map:
                        typ, body = asset_map[target]
                        request_route.fulfill(status=200, content_type=typ, body=body)
                    else:
                        request_route.abort()

                context.route("**/*", route)
                tab = context.new_page()
                errors = []
                tab.on("pageerror", lambda error, target=errors: target.append(type(error).__name__))
                tab.goto(url.rstrip("/") + "/", wait_until="networkidle", timeout=30000)
                tab.locator("main h1").wait_for(state="visible")
                overflow = tab.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
                if overflow or errors:
                    raise Blocked("Browser verification failed")
                if width == 375:
                    tab.locator("[data-menu]").click()
                    if tab.locator("[data-menu]").get_attribute("aria-expanded") != "true":
                        raise Blocked("Mobile navigation failed")
                for section in ("#services", "#contact"):
                    tab.locator(f'nav a[href="{section}"]').click()
                    if not tab.url.endswith(section):
                        raise Blocked("Navigation route failed")
                checks.append({"width": width, "horizontal_overflow": False, "navigation": "passed"})
                context.close()
        finally:
            browser.close()
    return {
        "http_html": True,
        "identity": True,
        "assets": True,
        "browser": checks,
        "browser_mode": "Chromium renders fetched deployment assets with network intercepted",
    }
