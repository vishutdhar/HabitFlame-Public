#!/usr/bin/env python3
"""Read-only checks over the GitHub Pages mirror of the HabitFlame site.
Prints every failure and exits 1 if there is any.

  python3 scripts/verify-pages.py                  checks this repository
  python3 scripts/verify-pages.py --source DIR     also compares every page
                                                   byte for byte with a
                                                   habitflame-web checkout
  python3 scripts/verify-pages.py --live           also compares every page
                                                   with the live custom domain

The canonical HabitFlame site is https://habitflame.vishutdhar.com, built from
the habitflame-web repository. This repository only keeps the old GitHub Pages
addresses working (App Store Connect still links its support and privacy
pages): every page here is a byte for byte copy of the custom domain page,
whose canonical link and og:url already point at the custom domain, so search
engines fold the two copies into one.

Checks: the mirror map, the manifest hashes, canonical and og:url on the
custom domain, links that never point back at GitHub Pages, no sitemap, the
robots file, the Search Console verification file, the truthful privacy
policy, retired false sentences, stale files and prose hygiene.
"""
import argparse
import codecs
import hashlib
import html as htmlmod
import json
import pathlib
import re
import sys
import unicodedata
import urllib.request
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parent.parent
CANONICAL_BASE = "https://habitflame.vishutdhar.com"
MIRROR_BASE = "https://vishutdhar.github.io/HabitFlame-Public"
VERIFICATION_FILE = "googled95610149d8bb2dd.html"
ROBOTS = "User-agent: *\nAllow: /\n"
CONTACT = "support@freedom-terminal.com"

# Mirror path here -> (file in habitflame-web, canonical URL). Pinned so the
# old GitHub Pages addresses cannot silently disappear.
MIRROR = {
    "index.html": ("index.html", f"{CANONICAL_BASE}/"),
    "accountability-partner-habit-tracker/index.html": ("accountability-partner-habit-tracker.html", f"{CANONICAL_BASE}/accountability-partner-habit-tracker"),
    "streak-tracker-app/index.html": ("streak-tracker-app.html", f"{CANONICAL_BASE}/streak-tracker-app"),
    "pomodoro-habit-app/index.html": ("pomodoro-habit-app.html", f"{CANONICAL_BASE}/pomodoro-habit-app"),
    "habit-app-for-couples/index.html": ("habit-app-for-couples.html", f"{CANONICAL_BASE}/habit-app-for-couples"),
    "daily-habit-tracker-with-reminders/index.html": ("daily-habit-tracker-with-reminders.html", f"{CANONICAL_BASE}/daily-habit-tracker-with-reminders"),
    "habitflame-vs-habitshare/index.html": ("habitflame-vs-habitshare.html", f"{CANONICAL_BASE}/habitflame-vs-habitshare"),
    "support.html": ("support.html", f"{CANONICAL_BASE}/support"),
    "privacy-policy.html": ("privacy-policy.html", f"{CANONICAL_BASE}/privacy-policy"),
    "terms-of-service.html": ("terms-of-service.html", f"{CANONICAL_BASE}/terms-of-service"),
}
MANIFEST = ROOT / "scripts" / "mirror.json"

# Sentences from the retired policies, false about what the app does. Kept in
# step with the list in habitflame-web's verifier.
RETIRED_POLICY_SENTENCES = (
    "We do not collect any personal information", "do not use analytics", "do not have servers",
    "does not integrate with any third-party analytics",
    "the names of shared habits, completion events, milestones, streak counts, nudges, reactions, and your display name are relayed",
    "It never leaves your device and is never sent to any server",
    "An anonymous identity key that represents your account without revealing who you are",
    "Health values stay on your device", "Session replay is turned on", "never individual habits",
)
# The support page answers the questions App Store reviewers and partners
# arrive with, and gives the contact address as a link.
SUPPORT_MUST = ("How do I add an accountability partner?", "I have an invite code. Where do I enter it?",
                "How do I restore my purchase?", "Restore Purchases", f'href="mailto:{CONTACT}"')
POLICY_MUST = ("PostHog", "pairing service", "push notification", "Apple Health", "Screen recordings",
               "weekly count", "Nudges and reactions", CONTACT)

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


class Tags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    handle_startendtag = handle_starttag


def tags(text: str) -> list[tuple[str, dict]]:
    p = Tags()
    p.feed(text)
    p.close()
    return p.tags


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def flat(text: str) -> str:
    return unicodedata.normalize("NFKC", re.sub(r"\s+", " ", htmlmod.unescape(text))).lower()


parser = argparse.ArgumentParser()
parser.add_argument("--source", type=pathlib.Path, help="a habitflame-web checkout to compare with")
parser.add_argument("--live", action="store_true", help="compare with the live custom domain")
args = parser.parse_args()

# 1. Manifest: exactly the mirror map, and every file matches its hash.
try:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
except (OSError, ValueError) as e:
    manifest = {}
    failures.append(f"scripts/mirror.json: {e}")
check(manifest.get("canonical_base") == CANONICAL_BASE, f"scripts/mirror.json: canonical_base is {manifest.get('canonical_base')!r}")
entries = manifest.get("files", {})
check(sorted(entries) == sorted(MIRROR), f"scripts/mirror.json: files {sorted(set(entries) ^ set(MIRROR))} differ from the mirror map")

pages: dict[str, str] = {}
for rel, (source, url) in MIRROR.items():
    path = ROOT / rel
    if not path.is_file():
        failures.append(f"{rel}: missing, run scripts/sync-mirror.py")
        continue
    data = path.read_bytes()
    pages[rel] = data.decode("utf-8")
    entry = entries.get(rel, {})
    check(entry.get("source") == source, f"scripts/mirror.json: {rel} source is {entry.get('source')!r}, want {source!r}")
    check(entry.get("sha256") == sha256(data), f"{rel}: differs from the manifest, run scripts/sync-mirror.py")

    # 2. Canonical and og:url: one canonical, on the custom domain, the page's
    #    own clean URL, and og:url byte equal to it.
    t = tags(pages[rel])
    canons = [a.get("href") for tag, a in t if tag == "link" and a.get("rel") == "canonical"]
    check(canons == [url], f"{rel}: canonical links {canons}, want [{url!r}]")
    og = [a.get("content") for tag, a in t if tag == "meta" and a.get("property") == "og:url"]
    check(og == [url], f"{rel}: og:url {og}, want [{url!r}]")

    # 3. No link, script, stylesheet or image points back at GitHub Pages or
    #    at a relative path, which would resolve to the GitHub Pages copy.
    for tag, a in t:
        for attr in ("href", "src"):
            v = a.get(attr)
            if v is None or v.startswith(("mailto:", "tel:", "#")):
                continue
            check(v.startswith("https://"), f"{rel}: {tag} {attr} {v!r} is not an absolute https URL")
            check("github.io" not in v, f"{rel}: {tag} {attr} {v!r} points at GitHub Pages")

    # 4. Retired false policy sentences never appear.
    body = flat(pages[rel])
    for stale in RETIRED_POLICY_SENTENCES:
        check(stale.lower() not in body, f"{rel}: still says {stale!r}")

# 5. The privacy page is the truthful policy.
policy = pages.get("privacy-policy.html", "")
policy = policy.split("<main", 1)[1] if "<main" in policy else ""
for must in POLICY_MUST:
    check(must in policy, f"privacy-policy.html: missing {must!r}")

# Visible markup only: the JSON-LD in the head repeats the questions, so a
# page whose visible answers were gone would still match the raw source.
support = re.sub(r"<script\b.*?</script>", "", pages.get("support.html", ""), flags=re.S)
support = support.split("<main", 1)[1] if "<main" in support else ""
for must in SUPPORT_MUST:
    check(must in support, f"support.html: missing {must!r} from the visible page")

# 6. Byte equality with the canonical copy, when asked.
if args.source:
    for rel, (source, _url) in MIRROR.items():
        src = args.source / source
        check(src.is_file() and rel in pages and src.read_bytes() == pages[rel].encode("utf-8"),
              f"{rel}: not byte equal to {src}")
def fetch(url: str) -> "bytes | None":
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.read()
    except OSError as e:
        failures.append(f"fetching {url} failed: {e}")
        return None


if args.live:
    # Both published copies: the custom domain page and this repository's
    # GitHub Pages address (the one App Store Connect links), plus the
    # stylesheet and icon the pages load from the custom domain.
    for rel, (_source, url) in MIRROR.items():
        mirror_url = f"{MIRROR_BASE}/{rel[:-len('index.html')] if rel.endswith('index.html') else rel}"
        for where in (url, mirror_url):
            live = fetch(where)
            if live is not None:
                check(rel in pages and live == pages[rel].encode("utf-8"), f"{rel}: not byte equal to {where}")
    assets = sorted({v for text in pages.values() for tag, a in tags(text) if tag == "link"
                     for v in [a.get("href", "")] if v.startswith(CANONICAL_BASE + "/") and a.get("rel") in ("stylesheet", "icon")})
    for url in assets:
        check(fetch(url) is not None, f"{url}: not served")

# 7. No sitemap: a sitemap lists canonical URLs only, and those are the custom
#    domain's, listed in its own sitemap. robots.txt stays, without one.
check(not (ROOT / "sitemap.xml").exists(), "sitemap.xml: the mirror must not carry a sitemap")
robots = ROOT / "robots.txt"
check(robots.is_file() and robots.read_text(encoding="utf-8") == ROBOTS, "robots.txt: content changed")

# 8. The Search Console ownership file for the GitHub Pages property stays.
vf = ROOT / VERIFICATION_FILE
check(vf.is_file() and vf.read_text(encoding="utf-8") == f"google-site-verification: {VERIFICATION_FILE}\n",
      f"{VERIFICATION_FILE}: missing or changed")

# 9. Nothing stale: every HTML file is a mirror page or the verification file,
#    and the retired generator and stylesheet are gone.
allowed_html = set(MIRROR) | {VERIFICATION_FILE}
for f in sorted(ROOT.rglob("*.html")):
    rel = str(f.relative_to(ROOT))
    if rel.split("/")[0] in {".git"}:
        continue
    check(rel in allowed_html, f"{rel}: an HTML file outside the mirror map (stale?)")
for gone in ("scripts/build-pages.py", "scripts/pages.json", "scripts/template.html", "styles.css"):
    check(not (ROOT / gone).exists(), f"{gone}: retired; the site is built in habitflame-web")

# 10. Prose hygiene in the files this repository owns.
DASHES = {0x2012, 0x2013, 0x2014, 0x2015, 0x2212}
# Stored rot13 so this file never spells the names it bans.
TOOL_NAMES = {codecs.decode(w, "rot13") for w in ("pynhqr", "pbqrk", "tcg", "naguebcvp", "bcranv")}
for name in ("README.md", "scripts/sync-mirror.py", "scripts/verify-pages.py", "scripts/mirror.json", "robots.txt"):
    p = ROOT / name
    if not p.is_file():
        failures.append(f"{name}: missing")
        continue
    for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        for ch in line:
            if ord(ch) in DASHES or ord(ch) >= 0x1F000:
                failures.append(f"{name}:{lineno}: dash or pictographic character U+{ord(ch):04X}")
        for w in TOOL_NAMES:
            if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", line, re.I):
                failures.append(f"{name}:{lineno}: tool name '{w}'")

if failures:
    for f in failures:
        print(f"FAIL   {f}")
    print(f"{len(failures)} failure(s)")
    sys.exit(1)
extra = (" byte equal to " + str(args.source) if args.source else "") + (" and to the live site" if args.live else "")
print(f"OK: {len(MIRROR)} mirror pages{extra}, 0 failures")
