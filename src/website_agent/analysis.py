import re
import time
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from website_agent.security import Blocked, domain, email_address, html_page

ROLE_MAILBOXES = {
    "info",
    "contact",
    "hello",
    "office",
    "enquiries",
    "inquiries",
    "sales",
    "reception",
    "bookings",
    "admin",
    "support",
}


def inspect_site(web, url):
    start = time.monotonic()
    page = web.fetch(url)
    elapsed = round((time.monotonic() - start) * 1000)
    html_page(page)
    soup = BeautifulSoup(page.text, "html.parser")
    findings = []

    def check(label, passed, weight, evidence):
        findings.append({"check": label, "passed": bool(passed), "weight": weight, "evidence": evidence})

    check("viewport", soup.find("meta", attrs={"name": "viewport"}), 15, "Presence of viewport meta tag")
    check("https", page.url.startswith("https://"), 10, "Final URL scheme")
    check("title", soup.title and soup.title.get_text(strip=True), 5, "Nonempty title element")
    check(
        "description",
        soup.find("meta", attrs={"name": "description", "content": True}),
        5,
        "Description meta tag",
    )
    check("main_heading", soup.h1, 10, "Presence of h1")
    check("navigation", soup.nav or soup.find(attrs={"role": "navigation"}), 10, "Navigation landmark")
    images = soup.find_all("img")
    check(
        "image_alternatives",
        all(i.has_attr("alt") for i in images),
        10,
        f"{sum(i.has_attr('alt') for i in images)}/{len(images)} images have alt attributes",
    )
    check("document_language", soup.html and soup.html.get("lang"), 5, "HTML language attribute")
    links = [urljoin(page.url, a["href"]) for a in soup.select("a[href]")]
    contact_links = [u for u in links if "contact" in u.lower() or u.startswith(("mailto:", "tel:"))]
    check("contact_path", contact_links, 10, "Contact, mailto or tel link present")
    check(
        "fetch_latency",
        elapsed < 3000,
        5,
        f"HTTP fetch including robots/DNS: {elapsed} ms; not browser/Lighthouse performance",
    )
    broken = []
    tested = []
    contact_pages = [(page.url, soup)]
    for link in dict.fromkeys(links):
        if len(tested) >= 3:
            break
        if not link.startswith(("https://", "http://")) or domain(link) != domain(page.url) or "#" in link:
            continue
        try:
            other = web.fetch(link)
            tested.append({"url": link, "status": other.status})
            if other.status >= 400:
                broken.append(link)
            if (
                other.status == 200
                and "contact" in link.lower()
                and "text/html" in other.headers.get("content-type", "")
            ):
                contact_pages.append((other.url, BeautifulSoup(other.text, "html.parser")))
        except (Blocked, OSError):
            tested.append({"url": link, "status": "unavailable"})
            broken.append(link)
    check("sampled_links", not broken, 5, {"sample": tested, "broken": broken})
    for node in soup(["script", "style", "noscript", "iframe"]):
        node.decompose()
    text = " ".join(soup.stripped_strings)[:18000]
    check("substantive_content", len(text) >= 200, 10, f"Visible text characters: {len(text)} (bounded)")
    contact = {}
    for source_url, doc in contact_pages:
        for a in doc.select('a[href^="mailto:"]'):
            try:
                address = email_address(unquote(a["href"][7:].split("?")[0]))
            except ValueError:
                continue
            if address.split("@")[0] in ROLE_MAILBOXES and domain(address.split("@")[1]) == domain(page.url):
                contact = {
                    "email": address,
                    "url": source_url,
                    "method": "public_role_mailto",
                    "observed": True,
                }
                break
    snippets = [" ".join(n.stripped_strings) for n in soup.select("h1,h2,h3,p,li")]
    snippets = list(dict.fromkeys(s for s in snippets if 3 <= len(s) <= 400))[:60]
    return {
        "score": sum(f["weight"] for f in findings if f["passed"]),
        "findings": findings,
        "final_url": page.url,
        "text": text,
        "snippets": snippets,
        "contact": contact,
        "lighthouse_ran": False,
        "browser_audit_ran": False,
        "limitations": "Static HTML heuristic, not a full accessibility, visual-design or Core Web Vitals audit.",
    }


def quote_in_evidence(quote, snippets):
    def normalize(s):
        return re.sub(r"\s+", " ", s).strip()

    return bool(quote) and any(normalize(quote) in normalize(s) for s in snippets)
