#!/usr/bin/env python3
"""Generate the HabitFlame public site from scripts/pages.json and
scripts/template.html, so every page shares one header, footer, stylesheet
and structured data shape.

Run from anywhere:  python3 scripts/build-pages.py

Outputs (all at the repo root):
  index.html                 the landing page
  <slug>/index.html          one guide page per entry in pages.json "pages"
  sitemap.xml                landing, guides and the three policy pages
  robots.txt
  <site.verification_file>   the Google Search Console ownership file

Rendering is deterministic: the same pages.json and template give the same
bytes. The only date is the sitemap lastmod, which is site.lastmod in
pages.json, so a rebuild on another day changes nothing.
"""
import datetime
import html
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
CONFIG = json.loads((SCRIPTS / "pages.json").read_text(encoding="utf-8"))
TEMPLATE = (SCRIPTS / "template.html").read_text(encoding="utf-8")

SITE = CONFIG["site"]
FACTS = CONFIG["facts"]
LANDING = CONFIG["landing"]
PAGES = CONFIG["pages"]

BASE = SITE["base_url"].rstrip("/")
YEAR = "2026"
POLICY_PAGES = ["support.html", "privacy-policy.html", "terms-of-service.html"]

STORE_BUTTON_TEXT = "Get HabitFlame on the App Store"
STORE_NOTE = "Free to download for iPhone and iPad. Premium is a one-time $9.99 purchase."
CTA_HEADING = "Start with one habit and one person"
CTA_TEXT = "Download HabitFlame, add a habit, and send one invite link."
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
LEDGER = [
    ("You", ["lit", "lit", "lit", "lit", "lit", "lit", "open"]),
    ("Sam", ["lit", "lit", "lit", "lit", "lit", "lit", "lit"]),
]
LEDGER_LABEL = ("A week of habits side by side. Sam has a flame on every day. "
                "You have a flame on every day except Sunday, which is still open.")


def esc(text: str) -> str:
    """Escape text for an HTML text node or a double quoted attribute."""
    return html.escape(text, quote=True)


# Inline link form for copy in pages.json: [link text](path), where path is a
# file or directory on this site, relative to base_url. Everything else in the
# string is escaped; structured data gets the link text only.
LINK = re.compile(r"\[([^\[\]]+)\]\(([a-z0-9][a-z0-9./-]*(?:#[a-z0-9-]+)?)\)")


def rich(text: str) -> str:
    """Escaped HTML with the inline link form turned into site links."""
    out, pos = [], 0
    for m in LINK.finditer(text):
        out.append(esc(text[pos:m.start()]))
        out.append(f'<a href="{esc(BASE + "/" + m.group(2))}">{esc(m.group(1))}</a>')
        pos = m.end()
    out.append(esc(text[pos:]))
    return "".join(out)


def plain(text: str) -> str:
    """The text a reader sees: the inline link form reduced to its link text."""
    return LINK.sub(r"\1", text)


def page_url(page: dict | None) -> str:
    """Canonical URL: the landing is base_url + "/", a guide is base_url + "/<slug>/"."""
    return f"{BASE}/" if page is None else f"{BASE}/{page['slug']}/"


# ---- Shared fragments --------------------------------------------------------

def store_button() -> str:
    return f'<a class="store" href="{esc(SITE["app_store_url"])}">{esc(STORE_BUTTON_TEXT)}</a>'


def store_note() -> str:
    return f'<p class="store-note">{esc(STORE_NOTE)}</p>'


def cta_section() -> str:
    return (
        '<section class="cta">\n'
        f"<h2>{esc(CTA_HEADING)}</h2>\n"
        f"<p>{esc(CTA_TEXT)}</p>\n"
        f"{store_button()}\n"
        "</section>"
    )


def guides_list(pages: list[dict]) -> str:
    items = "\n".join(
        f'<li><a href="{esc(page_url(p))}">{esc(p["title"])}</a>\n<p>{esc(p["description"])}</p></li>'
        for p in pages
    )
    return f'<ul class="guides">\n{items}\n</ul>'


def faq_list(entries: list[dict]) -> str:
    rows = "\n".join(f"<dt>{esc(e['q'])}</dt>\n<dd>{rich(e['a'])}</dd>" for e in entries)
    return f"<dl>\n{rows}\n</dl>"


# ---- Landing -----------------------------------------------------------------

def ledger() -> str:
    head = '<div class="ledger-row days" aria-hidden="true"><span></span>' + "".join(
        f"<span>{d}</span>" for d in DAYS) + "</div>"
    rows = [head]
    for name, states in LEDGER:
        cells = "".join(f'<div class="flame {s}"></div>' for s in states)
        rows.append(f'<div class="ledger-row"><span class="ledger-name">{esc(name)}</span>{cells}</div>')
    grid = "\n".join(rows)
    return (
        '<div class="ledger">\n'
        f'<div class="ledger-grid" role="img" aria-label="{esc(LEDGER_LABEL)}">\n{grid}\n</div>\n'
        '<p class="ledger-nudge"><b>Sam</b> nudged you: still time for your walk.</p>\n'
        f'<p class="ledger-caption">{esc(LANDING["ledger_caption"])}</p>\n'
        "</div>"
    )


def landing_main() -> str:
    parts = [
        '<section class="hero">\n'
        '<div class="hero-copy">\n'
        f"<h1>{esc(LANDING['headline'])}</h1>\n"
        f'<p class="deck">{esc(LANDING["deck"])}</p>\n'
        f"{store_button()}\n"
        f"{store_note()}\n"
        "</div>\n"
        f"{ledger()}\n"
        "</section>"
    ]
    for section in LANDING["sections"]:
        items = "\n".join(
            f"<li><h3>{esc(title)}</h3>\n<p>{rich(body)}</p></li>" for title, body in section["items"]
        )
        parts.append(f"<section>\n<h2>{esc(section['heading'])}</h2>\n<ul class=\"rows\">\n{items}\n</ul>\n</section>")
    premium = LANDING["premium"]
    price = esc(FACTS["price"])
    body = esc(premium["body"]).replace(price, f'<span class="price">{price}</span>')
    parts.append(
        f"<section>\n<h2>{esc(premium['heading'])}</h2>\n"
        f'<div class="premium-band">\n<p>{body}</p>\n</div>\n</section>'
    )
    parts.append(
        '<section id="guides">\n'
        f"<h2>{esc(LANDING['guides_heading'])}</h2>\n"
        f'<p class="section-intro">{esc(LANDING["guides_intro"])}</p>\n'
        f"{guides_list(PAGES)}\n"
        "</section>"
    )
    parts.append(f'<section class="faq">\n<h2>Questions</h2>\n{faq_list(LANDING["faq"])}\n</section>')
    parts.append(cta_section())
    return "\n".join(parts)


# ---- Guide pages -------------------------------------------------------------

def render_block(block: dict, page: dict) -> str:
    if len(block) != 1:
        raise ValueError(f"{page['slug']}: a block must have exactly one key, got {sorted(block)}")
    kind, value = next(iter(block.items()))
    if kind == "h2":
        return f"<h2>{esc(value)}</h2>"
    if kind == "p":
        return f"<p>{rich(value)}</p>"
    if kind == "ul":
        return "<ul>\n" + "\n".join(f"<li>{rich(item)}</li>" for item in value) + "\n</ul>"
    if kind == "table":
        head = "".join(f'<th scope="col">{esc(c)}</th>' for c in value["head"])
        body = "\n".join(
            f'<tr><th scope="row">{esc(row[0])}</th>' + "".join(f"<td>{esc(c)}</td>" for c in row[1:]) + "</tr>"
            for row in value["rows"]
        )
        return f'<table class="compare">\n<thead><tr>{head}</tr></thead>\n<tbody>\n{body}\n</tbody>\n</table>'
    if kind == "faq":
        return f'<section class="faq">\n<h2>{esc(page["faq_heading"])}</h2>\n{faq_list(value)}\n</section>'
    raise ValueError(f"{page['slug']}: unknown block type {kind!r}")


def page_faq(page: dict) -> list[dict]:
    return [e for b in page["blocks"] if "faq" in b for e in b["faq"]]


def article_main(page: dict) -> str:
    blocks = "\n".join(render_block(b, page) for b in page["blocks"])
    others = [p for p in PAGES if p["slug"] != page["slug"]]
    return (
        '<div class="guide">\n'
        '<header class="article-head">\n'
        f"<h1>{esc(page['h1'])}</h1>\n"
        f'<p class="deck">{esc(page["deck"])}</p>\n'
        f"{store_button()}\n"
        f"{store_note()}\n"
        "</header>\n"
        f'<div class="article-body">\n{blocks}\n</div>\n'
        '<section class="related">\n<h2>More guides</h2>\n'
        f"{guides_list(others)}\n"
        "</section>\n"
        f"{cta_section()}\n"
        "</div>"
    )


# ---- Structured data ---------------------------------------------------------

def jsonld(page: dict | None) -> str:
    url = page_url(page)
    title = LANDING["title"] if page is None else page["title"]
    description = LANDING["description"] if page is None else page["description"]
    faq = LANDING["faq"] if page is None else page_faq(page)
    graph: list[dict] = []
    if page is None:
        graph.append({
            "@type": "WebSite",
            "@id": f"{BASE}/#website",
            "name": SITE["name"],
            "url": f"{BASE}/",
        })
        graph.append({
            "@type": "SoftwareApplication",
            "name": SITE["name"],
            "operatingSystem": "iOS",
            "applicationCategory": "HealthApplication",
            "url": SITE["app_store_url"],
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
        })
    graph.append({
        "@type": "WebPage",
        "@id": f"{url}#webpage",
        "name": title,
        "description": description,
        "url": url,
        "isPartOf": {"@id": f"{BASE}/#website"},
    })
    if page is not None:
        graph.append({
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{BASE}/"},
                {"@type": "ListItem", "position": 2, "name": page["title"], "item": url},
            ],
        })
    if faq:
        graph.append({
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": e["q"],
                 "acceptedAnswer": {"@type": "Answer", "text": plain(e["a"])}}
                for e in faq
            ],
        })
    text = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False, indent=1)
    # A literal "</" would end the script element early; "<\/" is the same JSON string.
    return text.replace("</", "<\\/")


# ---- Page assembly -----------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def fill(values: dict[str, str]) -> str:
    """Single pass substitution, so content can never be re-read as a placeholder."""
    missing = set(_PLACEHOLDER.findall(TEMPLATE)) - set(values)
    if missing:
        raise KeyError(f"template placeholders without a value: {sorted(missing)}")
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], TEMPLATE)


def render(page: dict | None) -> str:
    """Render the landing (page is None) or one guide page."""
    title = LANDING["title"] if page is None else page["title"]
    description = LANDING["description"] if page is None else page["description"]
    return fill({
        "title": esc(title),
        "description": esc(description),
        "url": esc(page_url(page)),
        "base": esc(BASE),
        "css_version": esc(SITE["css_version"]),
        "jsonld": jsonld(page),
        "body_class": "landing" if page is None else "article",
        "main": landing_main() if page is None else article_main(page),
        "app_store_url": esc(SITE["app_store_url"]),
        "contact_email": esc(SITE["contact_email"]),
        "brand_url": esc(SITE["brand_url"]),
        "brand_footer": esc(SITE["brand_footer"]),
        "year": YEAR,
    })


def sitemap_urls() -> list[str]:
    return [f"{BASE}/"] + [page_url(p) for p in PAGES] + [f"{BASE}/{name}" for name in POLICY_PAGES]


def render_sitemap() -> str:
    date = SITE["lastmod"]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError(f"site.lastmod must be YYYY-MM-DD, got {date!r}")
    datetime.date.fromisoformat(date)  # and a real date
    entries = "\n".join(f"  <url>\n    <loc>{esc(u)}</loc>\n    <lastmod>{date}</lastmod>\n  </url>"
                        for u in sitemap_urls())
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{entries}\n</urlset>\n")


def render_robots() -> str:
    return f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n"


def render_verification() -> str:
    return f"google-site-verification: {SITE['verification_file']}\n"


def outputs() -> dict[str, str]:
    """Every generated file, keyed by its path relative to the repo root."""
    files = {"index.html": render(None)}
    for page in PAGES:
        files[f"{page['slug']}/index.html"] = render(page)
    files["sitemap.xml"] = render_sitemap()
    files["robots.txt"] = render_robots()
    files[SITE["verification_file"]] = render_verification()
    return files


def main() -> None:
    slugs = [p["slug"] for p in PAGES]
    if len(set(slugs)) != len(slugs) or any(not re.fullmatch(r"[a-z0-9-]+", s) for s in slugs):
        raise SystemExit(f"slugs must be unique lowercase words joined by hyphens: {slugs}")
    for rel, text in outputs().items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {rel}")


if __name__ == "__main__":
    main()
