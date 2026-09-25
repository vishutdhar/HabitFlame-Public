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
import urllib.error
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
    "There is currently no switch in the app to turn analytics off", "a random identifier for your installation",
    "one evening alert when a streak", "an evening streak-at-risk alert goes", "an evening warning when a streak",
    "once a day in the evening, a streak-at-risk alert",
    "is invisible to your partner", "Anything not shared is invisible", "Habits you do not share are never sent",
    "every habit you share and complete is sent", "each of your shared completions instantly",
    "Every shared completion as it happens",
    "A habit completed from a widget is not sent to your partner", "counts for your streak but is not sent",
    "so the message on Tuesday is not the message from Monday", "wording changes from day to day",
    "The wording varies from day to day", "keeps a small record of that code",
    "never a habit name.", "Weekly and monthly charts", "so a habit set to weekdays does not ring on Saturday.",
    "nothing your partner can see beyond what you chose to share.",
    "Analytics receives only the type of a habit", "and its record is removed 30 days after it expires",
    "marked as removed, and deleted 30 days later",
)
# The support page answers the questions App Store reviewers and partners
# arrive with, and gives the contact address as a link.
SUPPORT_MUST = ("How do I add an accountability partner?", "I have an invite code. Where do I enter it?",
                "How do I restore my purchase?", "Restore Purchases",
                "Open the Partners tab and send an invite link", "choose Have a code and type the 6 character code",
                "An invite expires after 7 days")
POLICY_MUST = ("PostHog", "pairing service", "push notification", "Apple Health", "Screen recordings",
               "weekly count", "Nudges and reactions", CONTACT,
               "Session replay is turned off", "in your private iCloud database", "one-way hash of the habit's identifier",
               "eligible for deletion 30 days later", "Share usage analytics", "when the app is started in the evening",
               "automatically through your iCloud account", "request counters for each IP address, pairing and device",
               "for a reaction the name of the habit you reacted to", "For every invite, the pairing service also keeps a permanent record",
               "Analytics never receives Health measurements")

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


class MainText(HTMLParser):
    """Visible text and links inside <main>: comments are not text, and
    script and style contents are skipped."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.hidden, self.text, self.links = 0, 0, [], []

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.depth += 1
        elif self.depth and tag in ("script", "style"):
            self.hidden += 1
        if self.depth and tag == "a":
            self.links.append(dict(attrs).get("href", ""))

    def handle_endtag(self, tag):
        if tag == "main":
            self.depth -= 1
        elif self.depth and tag in ("script", "style"):
            self.hidden -= 1

    def handle_data(self, data):
        if self.depth and not self.hidden:
            self.text.append(data)


def visible_main(text: str) -> tuple[str, list]:
    p = MainText()
    p.feed(text)
    p.close()
    return unicodedata.normalize("NFKC", re.sub(r"\s+", " ", " ".join(p.text))), p.links


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
policy, policy_links = visible_main(pages.get("privacy-policy.html", ""))
check(f"mailto:{CONTACT}" in policy_links, "privacy-policy.html: no visible mailto link to the contact address")
for must in POLICY_MUST:
    check(must in policy, f"privacy-policy.html: missing {must!r}")

# Parsed visible text only: the JSON-LD in the head repeats the questions,
# and commented out markup is not on the page.
support, support_links = visible_main(pages.get("support.html", ""))
check(f"mailto:{CONTACT}" in support_links, "support.html: no visible mailto link to the contact address")
for must in SUPPORT_MUST:
    check(must in support, f"support.html: missing {must!r} from the visible page")

# 6. Byte equality with the canonical copy, when asked.
if args.source:
    for rel, (source, _url) in MIRROR.items():
        src = args.source / source
        check(src.is_file() and rel in pages and src.read_bytes() == pages[rel].encode("utf-8"),
              f"{rel}: not byte equal to {src}")
def fetch(url: str, want_type: str = "text/html") -> "bytes | None":
    """The body of a 200 response whose content type is want_type, else None
    with a failure recorded: an error page served as HTML is not the asset."""
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
            body = r.read()
            if r.status != 200 or ctype != want_type:
                failures.append(f"{url}: status {r.status}, content type {ctype!r}, want 200 and {want_type!r}")
                return None
            return body
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
    # The files this repository keeps, and the sitemap it no longer serves.
    for name, want in (("robots.txt", ROBOTS), (VERIFICATION_FILE, f"google-site-verification: {VERIFICATION_FILE}\n")):
        body = fetch(f"{MIRROR_BASE}/{name}", "text/plain" if name.endswith(".txt") else "text/html")
        check(body is None or body.decode("utf-8", "replace") == want, f"{MIRROR_BASE}/{name}: served content differs")
    try:
        with urllib.request.urlopen(f"{MIRROR_BASE}/sitemap.xml", timeout=30) as r:
            failures.append(f"{MIRROR_BASE}/sitemap.xml: still served (status {r.status})")
    except urllib.error.HTTPError as e:
        check(e.code == 404, f"{MIRROR_BASE}/sitemap.xml: status {e.code}, want 404")
    except OSError as e:
        failures.append(f"fetching {MIRROR_BASE}/sitemap.xml failed: {e}")
    assets = sorted({v for text in pages.values() for tag, a in tags(text) if tag == "link"
                     for v in [a.get("href", "")] if v.startswith(CANONICAL_BASE + "/") and a.get("rel") in ("stylesheet", "icon")})
    for url in assets:
        want = "text/css" if ".css" in url else "image/png"
        body = fetch(url, want)
        if body is None:
            continue
        if want == "image/png":
            check(body.startswith(b"\x89PNG\r\n\x1a\n"), f"{url}: not a PNG image")
        else:
            # The page asks for site.css?v=<first 12 hex of its SHA-256>, so
            # the served file must hash to exactly that version.
            version = url.split("?v=", 1)[-1]
            check(sha256(body)[:12] == version, f"{url}: served stylesheet hashes to {sha256(body)[:12]}, not {version}")

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
