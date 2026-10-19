import hashlib
import json
from html import escape

from bs4 import BeautifulSoup

from website_agent.analysis import quote_in_evidence
from website_agent.security import Blocked

JS = """'use strict';
const toggle = document.querySelector('[data-menu]');
const nav = document.querySelector('#navigation');
toggle.addEventListener('click', () => {
  const open = toggle.getAttribute('aria-expanded') === 'true';
  toggle.setAttribute('aria-expanded', String(!open));
  nav.classList.toggle('open', !open);
});
"""

CSS = """*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:#16212c;background:#fbfaf7;font:18px/1.65 system-ui,sans-serif}a{color:inherit}a:focus-visible,button:focus-visible{outline:3px solid #e79d22;outline-offset:5px}.notice{padding:12px 5%;background:#16212c;color:#fff;font-size:14px;text-align:center}.skip{position:absolute;left:-9999px}.skip:focus{left:1rem;top:1rem;background:white;z-index:10}header{display:flex;gap:24px;align-items:center;justify-content:space-between;padding:24px 6%;border-bottom:1px solid #ccc}.brand{font-weight:800;max-width:60%;overflow-wrap:anywhere}nav{display:flex;gap:24px}button{display:none;padding:12px;border:1px solid;background:white;color:#16212c}main{max-width:1240px;margin:auto;padding:0 6%}section{padding:80px 0}h1{font-size:clamp(2.2rem,6vw,4.8rem);line-height:1.1;letter-spacing:-.04em;max-width:18ch;overflow-wrap:anywhere}h2{font-size:2.3rem;line-height:1.2}p{max-width:64ch;overflow-wrap:anywhere}.hero{border-bottom:1px solid #ccc;background:radial-gradient(ellipse at 95% 20%,var(--tint),transparent 60%)}.eyebrow{letter-spacing:.1em;text-transform:uppercase;font-size:14px;font-weight:700;color:var(--accent)}.cta{display:inline-block;background:var(--accent);color:white;padding:14px 26px;border-radius:8px;text-decoration:none;font-weight:700}.services{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:20px}.card{padding:28px;border:1px solid #ccc;border-radius:12px;background:#fff}.editorial .services{display:block}.editorial .card{margin:16px 0;border-radius:0;border-width:0 0 1px}footer{padding:40px 6%;background:#16212c;color:#fff;font-size:14px}footer p{margin:auto}@media(max-width:640px){header{flex-wrap:wrap}.brand{max-width:75%}button{display:block}nav{display:none;width:100%;flex-direction:column}nav.open{display:flex}section{padding:48px 0}}@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}"""


def render(design, evidence, original_url, site_key):
    for quote in [design.title_quote, design.hero_quote, *design.service_quotes]:
        if not quote_in_evidence(quote, evidence["snippets"]):
            raise Blocked("Generated business statement is not supported by a source quotation")
    colors = {
        "ocean": ("#164b65", "#d7e9ee"),
        "forest": ("#24533b", "#dce9d9"),
        "plum": ("#603b65", "#eedfed"),
        "slate": ("#364757", "#dce3e8"),
    }
    accent, tint = colors[design.theme]
    e = escape
    cards = "".join(f'<article class="card"><p>{e(s)}</p></article>' for s in design.service_quotes)
    html = f'''<!doctype html>
<html lang="{e(design.language)}" dir="{design.direction}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex,nofollow">
<meta name="concept-id" content="{e(site_key)}"><meta name="description" content="Independent, unofficial website redesign concept.">
<title>{e(design.title_quote)} — Unofficial concept</title><link rel="stylesheet" href="style.css">
<script src="app.js" defer></script></head><body class="{design.layout}">
<div class="notice">Independent, unofficial redesign concept. Not affiliated with this business. {e(design.concept_label)}</div>
<a class="skip" href="#main">Skip to content</a><header><a class="brand" href="#main">{e(design.title_quote)}</a>
<button type="button" data-menu aria-controls="navigation" aria-expanded="false">{e(design.navigation_label)}</button>
<nav id="navigation" aria-label="Main"><a href="#services">{e(design.services_label)}</a><a href="#contact">{e(design.contact_label)}</a></nav></header>
<main id="main"><section class="hero"><p class="eyebrow">Independent design concept</p><h1>{e(design.title_quote)}</h1><p>{e(design.hero_quote)}</p>
<a class="cta" href="#services">{e(design.services_label)}</a></section>
<section id="services"><h2>{e(design.services_label)}</h2><div class="services">{cards}</div></section>
<section id="contact"><h2>{e(design.contact_label)}</h2><p>This preview does not accept bookings, payments or personal information.</p>
<a class="cta" href="{e(original_url, quote=True)}" rel="noopener noreferrer">Official business website</a></section></main>
<footer><p>Unofficial concept. Business text is quoted from <a href="{e(original_url, quote=True)}">the source website</a>. No endorsement is implied.</p></footer></body></html>'''
    files = {
        "index.html": html,
        "style.css": f":root{{--accent:{accent};--tint:{tint}}}" + CSS,
        "app.js": JS,
        "robots.txt": "User-agent: *\nDisallow: /\n",
        "_headers": "/*\n  Content-Security-Policy: default-src 'none'; style-src 'self'; script-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: no-referrer\n  X-Robots-Tag: noindex, nofollow\n",
    }
    validate(files)
    return files


def validate(files):
    soup = BeautifulSoup(files["index.html"], "html.parser")
    ids = {tag.get("id") for tag in soup.select("[id]")}
    for tag in soup.find_all(True):
        if any(attr.lower().startswith("on") for attr in tag.attrs):
            raise Blocked("Inline event handler rejected")
        if tag.name in {"iframe", "object", "embed", "form", "base"}:
            raise Blocked("Unsafe HTML component")
        for attr in ("src", "href"):
            value = tag.get(attr, "")
            if value.startswith("#") and value[1:] not in ids:
                raise Blocked("Broken fragment")
            if value and not value.startswith(("#", "https://", "http://")) and value not in files:
                raise Blocked("Unapproved link or missing asset")
    scripts = soup.find_all("script")
    if (
        len(scripts) != 1
        or scripts[0].get("src") != "app.js"
        or scripts[0].get_text()
        or files["app.js"] != JS
    ):
        raise Blocked("Only the reviewed interaction script is allowed")
    if not soup.select_one('meta[name="viewport"]') or not soup.main or not soup.html.get("lang"):
        raise Blocked("Missing accessible page structure")
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
