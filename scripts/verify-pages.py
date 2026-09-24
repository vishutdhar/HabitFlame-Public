#!/usr/bin/env python3
"""Read-only checks over the generated HabitFlame site. Prints every failure
and exits 1 if there is any.

  python3 scripts/verify-pages.py

Checks: committed output equals a fresh render, deployment facts, numbers and
Premium claims agree with the facts in pages.json, banned and negated phrases,
the competitor rule, links, metadata, word counts, prose hygiene, the sitemap
and stale page directories.
"""
import codecs
import datetime
import html as htmlmod
import json
import pathlib
import re
import sys
import types
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN_PATH = ROOT / "scripts" / "build-pages.py"

# Execute the generator's source directly rather than importing it: an import
# goes through the bytecode cache, keyed by mtime at one second resolution, so
# an edit made within a second of the last run would verify stale code.
gen = types.ModuleType("gen")
gen.__file__ = str(GEN_PATH)
exec(compile(GEN_PATH.read_text(encoding="utf-8"), gen.__file__, "exec"), gen.__dict__)

SITE, FACTS, LANDING, PAGES, BASE = gen.SITE, gen.FACTS, gen.LANDING, gen.PAGES, gen.BASE

# Deployment facts, pinned here so a typo in pages.json cannot move the site,
# the store link or the product name without this file changing too.
PINNED_BASE_URL = "https://vishutdhar.github.io/HabitFlame-Public"
PINNED_APP_STORE_URL = "https://apps.apple.com/us/app/habit-flame-streak-tracker/id6756961710"
PINNED_NAME = "HabitFlame"
BRAND_URL = "https://freedom-terminal.com/"
BRAND_TEXT = "A Freedom Terminal product"
# Numbers allowed in copy that are not a fact value: the footer year and the
# small counts the copy uses in prose (2 sessions, 3 times a week, a set of 4).
EXTRA_ALLOWED_NUMBERS = {"2026", "2", "3", "4"}
GUIDE_TABLE_HEAD = ["", "Free", "Premium"]

failures: list[str] = []
notes: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


# ---- A small DOM, enough to pull visible text out of our own markup ---------

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
INLINE = {"a", "b", "strong", "em", "i", "span", "small", "abbr", "code"}
HIDDEN = {"script", "style", "head", "title", "template", "noscript"}


class Node:
    def __init__(self, tag: str, attrs: dict, parent: "Node | None"):
        self.tag, self.attrs, self.parent, self.children = tag, attrs, parent, []

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.walk()

    def find_all(self, pred):
        return [n for n in self.walk() if pred(n)]

    def ancestors(self):
        n = self.parent
        while n is not None:
            yield n
            n = n.parent

    def text(self, skip=lambda n: False) -> str:
        """Visible text; block boundaries become spaces, inline tags do not."""
        out: list[str] = []

        def rec(node: Node) -> None:
            for c in node.children:
                if isinstance(c, str):
                    out.append(c)
                elif c.tag in HIDDEN or skip(c):
                    continue
                else:
                    sep = "" if c.tag in INLINE else " "
                    out.append(sep)
                    rec(c)
                    out.append(sep)

        rec(self)
        return re.sub(r"\s+", " ", "".join(out)).strip()


class Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, dict(attrs), self.cur))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is None:
            failures.append(f"unmatched </{tag}>")
            return
        self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def parse(text: str) -> Node:
    b = Builder()
    b.feed(text)
    b.close()
    return b.root


def by_tag(root: Node, tag: str) -> list[Node]:
    return root.find_all(lambda n: n.tag == tag)


def first(root: Node, pred) -> "Node | None":
    found = root.find_all(pred)
    return found[0] if found else None


def meta(root: Node, key: str, value: str) -> "str | None":
    n = first(root, lambda n: n.tag == "meta" and n.attrs.get(key) == value)
    return None if n is None else n.attrs.get("content")


def whole(phrase: str) -> re.Pattern:
    return re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", re.I)


def whole_or_plural(phrase: str) -> re.Pattern:
    """The phrase as a whole word or phrase, also with a trailing s or es."""
    return re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?:es|s)?(?!\w)", re.I)


# A sentence ends at . ! or ? followed by an optional closing quote or bracket
# and whitespace, so a closing quotation mark never glues two sentences.
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|(?<=[.!?][\"')\]\u201d\u2019])\s+")


def sentences(text: str) -> list[str]:
    return [s for s in SENTENCE_END.split(text) if s]


def words_with_spans(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0).lower(), m.start(), m.end()) for m in re.finditer(r"[A-Za-z0-9$']+(?:\.[0-9]+)?", text)]


def table_head(table: Node) -> list[str]:
    thead = first(table, lambda n: n.tag == "thead")
    return [th.text() for th in by_tag(thead, "th")] if thead else []


def row_cells(tr: Node) -> list[Node]:
    return [c for c in tr.children if isinstance(c, Node) and c.tag in {"th", "td"}]


# ---- 4. Deployment facts ----------------------------------------------------

check(SITE["base_url"] == PINNED_BASE_URL, f"site.base_url is {SITE['base_url']!r}, pinned {PINNED_BASE_URL!r}")
check(BASE == PINNED_BASE_URL, f"generator base is {BASE!r}, pinned {PINNED_BASE_URL!r}")
check(SITE["app_store_url"] == PINNED_APP_STORE_URL, f"site.app_store_url is {SITE['app_store_url']!r}, pinned {PINNED_APP_STORE_URL!r}")
check(SITE["name"] == PINNED_NAME, f"site.name is {SITE['name']!r}, pinned {PINNED_NAME!r}")

# ---- 3. The one date --------------------------------------------------------

def iso_date(value) -> bool:
    """Exactly YYYY-MM-DD and a real date. fromisoformat alone also accepts
    forms such as 20260924 and 2026-W39-4."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        datetime.date.fromisoformat(value)
        return True
    except ValueError:
        return False


check(iso_date(SITE.get("lastmod")), f"site.lastmod {SITE.get('lastmod')!r} is not a YYYY-MM-DD date")

# ---- 5. Facts and the number allowlist --------------------------------------

allowed_numbers = set(FACTS["allowed_numbers"])
fact_numbers = {FACTS["price"].lstrip("$"), FACTS["free_habit_limit"], FACTS["free_nudges_per_month"],
                FACTS["pomodoro_work_minutes"], FACTS["pomodoro_short_break_minutes"],
                FACTS["pomodoro_long_break_minutes"], FACTS["achievement_badges"],
                *FACTS["streak_milestones"], *FACTS["multi_checkin_range"]}
for n in sorted(fact_numbers - allowed_numbers, key=float):
    failures.append(f"facts value {n} is missing from facts.allowed_numbers")
for n in sorted(allowed_numbers - fact_numbers - EXTRA_ALLOWED_NUMBERS, key=float):
    failures.append(f"facts.allowed_numbers has {n}, which is neither a fact value nor a listed extra")
check(re.fullmatch(r"\$\d+\.\d\d", FACTS["price"]) is not None, f"facts.price {FACTS['price']!r} is not a dollar amount")

# ---- Rendering ---------------------------------------------------------------

try:
    FRESH = gen.outputs()
except Exception as e:  # a malformed lastmod raises here; report and stop
    print(f"FAIL   generator raised {type(e).__name__}: {e}")
    for f in failures:
        print(f"FAIL   {f}")
    sys.exit(1)

# a. Committed output is byte-identical to a fresh render.
for rel, text in FRESH.items():
    path = ROOT / rel
    if not path.exists():
        failures.append(f"{rel}: missing, run scripts/build-pages.py")
        continue
    check(path.read_bytes() == text.encode("utf-8"), f"{rel}: differs from a fresh render, run scripts/build-pages.py")

# 8. Any page directory that is not a configured slug is a stale page.
SLUGS = {p["slug"] for p in PAGES}
for d in sorted(ROOT.iterdir()):
    if d.is_dir() and d.name not in {".git", "scripts"} and (d / "index.html").exists() and d.name not in SLUGS:
        failures.append(f"{d.name}/index.html: page directory is not a configured slug (stale output?)")

HTML_PAGES = [(None, "index.html")] + [(p, f"{p['slug']}/index.html") for p in PAGES]


def page_text_units(root: Node) -> list[str]:
    """Blocks of visible text outside tables, used to judge Premium claims."""
    units = []
    for n in root.find_all(lambda n: n.tag in {"p", "li", "dt", "dd", "h1", "h2", "h3"}):
        if any(a.tag in HIDDEN or a.tag == "table" for a in n.ancestors()):
            continue
        units.append(n.text())
    return units


def visible_units(root: Node) -> list[tuple[str, Node, "Node | None"]]:
    """All visible text exactly once, as (text, owner, table): owner is the
    nearest block element; inside a table each cell is its own unit."""
    units: list = []

    def rec(node: Node, table) -> None:
        buf: list[str] = []

        def flush() -> None:
            t = re.sub(r"\s+", " ", "".join(buf)).strip()
            if t:
                units.append((t, node, table))
            buf.clear()

        for c in node.children:
            if isinstance(c, str):
                buf.append(c)
            elif c.tag in HIDDEN:
                continue
            elif c.tag in INLINE:
                buf.append(c.text())
            else:
                flush()
                rec(c, c if c.tag == "table" else table)
        flush()

    rec(root, None)
    return units


premium_word = whole("Premium")
free_word = whole("free")
TIMER_MINUTES = {FACTS["pomodoro_work_minutes"], FACTS["pomodoro_short_break_minutes"], FACTS["pomodoro_long_break_minutes"]}
# A number no binding claims must be a streak milestone, part of the multi
# check-in range or a listed extra.
UNBOUND_OK = set(FACTS["streak_milestones"]) | set(FACTS["multi_checkin_range"]) | EXTRA_ALLOWED_NUMBERS
PERIOD_WORDS = {"month", "monthly", "year", "yearly", "annual", "week"}
TOKEN = re.compile(r"\$?\d+(?:\.\d+)?|[A-Za-z']+")
premium_free_forms = {f.lower(): 0 for f in FACTS.get("premium_free_forms", [])}


def bind_numbers(text: str, ctx: "dict | None") -> list[tuple[str, "str | None"]]:
    """Each number in text with the problem its context finds, or None.
    ctx is {"label": row label, "col": column head} for a table cell."""
    toks = list(TOKEN.finditer(text))
    free_ctx = bool(free_word.search(text)) or bool(ctx and ctx["col"] == "Free")
    nudge_ctx = bool(re.search(r"\bnudges?\b", text, re.I)) or bool(ctx and re.search(r"nudge", ctx["label"], re.I))
    habit_cell = bool(ctx and re.fullmatch(r"habits?", ctx["label"], re.I))
    out = []
    for i, m in enumerate(toks):
        s = m.group(0)
        if not (s[0].isdigit() or s[0] == "$"):
            continue
        num = s.lstrip("$")
        nxt = [x.group(0).lower() for x in toks[i + 1:i + 5]]
        if s.startswith("$"):
            if s != FACTS["price"]:
                out.append((num, f"amount {s} is not facts.price {FACTS['price']}"))
            elif any(w in PERIOD_WORDS for w in nxt[:4]):
                out.append((num, f"amount {s} is followed by a billing period"))
            else:
                out.append((num, None))
        elif any(w in ("minute", "minutes") for w in nxt[:2]):
            out.append((num, None if num in TIMER_MINUTES else f"'{num} minute' is not a timer value {sorted(TIMER_MINUTES, key=int)}"))
        elif any(w in ("achievement", "achievements", "badge", "badges") for w in nxt[:2]):
            out.append((num, None if num == FACTS["achievement_badges"] else f"'{num} badges' is not facts.achievement_badges {FACTS['achievement_badges']}"))
        elif any(w in ("nudge", "nudges") for w in nxt[:2]) or (nudge_ctx and nxt[:2] == ["a", "month"]):
            out.append((num, None if num == FACTS["free_nudges_per_month"] else f"'{num}' nudges is not facts.free_nudges_per_month {FACTS['free_nudges_per_month']}"))
        elif any(w in ("habit", "habits") for w in nxt[:2]) and (free_ctx or "limit" in nxt[:2]):
            out.append((num, None if num == FACTS["free_habit_limit"] else f"'{num} habits' about the free tier is not facts.free_habit_limit {FACTS['free_habit_limit']}"))
        elif habit_cell and free_ctx and text.strip() == s:
            out.append((num, None if num == FACTS["free_habit_limit"] else f"Habits under Free is {num}, not facts.free_habit_limit {FACTS['free_habit_limit']}"))
        elif num in UNBOUND_OK:
            out.append((num, None))
        else:
            out.append((num, f"number {num} is not bound to a fact and is not a milestone, the multi check-in range or a listed extra"))
    return out
premium_phrases = [(p, whole(p)) for p in FACTS["premium_only"]]
banned = [(p, whole_or_plural(p)) for p in FACTS["banned_phrases"]]
negated = [(p, whole_or_plural(p)) for p in FACTS.get("negated_only", [])]
negated_forms = [(f, whole(f)) for f in FACTS.get("negated_forms", [])]
negated_forms_used = {f: 0 for f, _ in negated_forms}
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
DOLLAR = re.compile(r"\$\d+(?:\.\d+)?")
HABIT_COUNT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?) habits?(?!\w)", re.I)
NUDGE_COUNT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?) nudges?(?!\w)", re.I)
EMAIL = re.compile(r"(?:\"[^\"\r\n<>]+\"|[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+)@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


def emails_in(text: str) -> set[str]:
    """Addresses in the raw source and in its entity-decoded form."""
    return set(EMAIL.findall(text)) | set(EMAIL.findall(htmlmod.unescape(text)))

word_counts: list[tuple[str, int]] = []

for page, rel in HTML_PAGES:
    raw = FRESH[rel]
    root = parse(raw)
    body = first(root, lambda n: n.tag == "body")
    main = first(root, lambda n: n.tag == "main")
    footer = first(root, lambda n: n.tag == "footer")
    title_node = first(root, lambda n: n.tag == "title")
    title = title_node.text() if title_node else ""
    description = meta(root, "name", "description") or ""
    want_title = LANDING["title"] if page is None else page["title"]
    want_desc = LANDING["description"] if page is None else page["description"]
    url = gen.page_url(page)
    footer_copy = first(root, lambda n: "foot-copy" in n.classes)

    ld_nodes = root.find_all(lambda n: n.tag == "script" and n.attrs.get("type") == "application/ld+json")
    ld_raw = "".join(c for n in ld_nodes for c in n.children if isinstance(c, str))
    try:
        graph = json.loads(ld_raw)["@graph"]
    except (ValueError, KeyError, TypeError) as e:
        failures.append(f"{rel}: JSON-LD does not parse: {e}")
        graph = []

    # Every piece of text a reader or a crawler sees, as sentence sized units,
    # each marked with whether the competitor rule exempts it. On a page with
    # "competitor", a competitor phrase or number may appear only in a sentence
    # naming the competitor, in the row label or the competitor's own column of
    # a table whose head names it, or in the page's own title, description and
    # JSON-LD page name or description. The h1 is never exempt.
    competitor = page.get("competitor") if page else None
    comp_rx = whole(competitor) if competitor else None
    comp_phrases = {p.lower() for p in page.get("competitor_phrases", [])} if page else set()
    comp_numbers = set(page.get("competitor_numbers", [])) if page else set()

    def names_competitor(text: str) -> bool:
        return bool(comp_rx and comp_rx.search(text))

    units: list[tuple[str, bool, str]] = []  # (text, exempt, where)
    number_units: list[tuple[str, bool, str, "dict | None"]] = []
    for text, node, table in visible_units(body) if body else []:
        if table is not None and node.tag in {"th", "td"}:
            head = table_head(table)
            tr = node.parent
            col = row_cells(tr).index(node) if tr is not None and node in row_cells(tr) else -1
            in_body = any(a.tag == "tbody" for a in node.ancestors())
            exempt = bool(competitor) and in_body and competitor in head and (col == 0 or (0 <= col < len(head) and head[col] == competitor))
            label = f"table cell (column {head[col]!r})" if 0 <= col < len(head) else "table cell"
            parts = [(text, exempt, label)]
            cell_ctx = {"label": row_cells(tr)[0].text() if tr is not None else "", "col": head[col] if 0 <= col < len(head) else ""}
        elif node.tag == "h1":
            parts = [(s, False, "h1") for s in sentences(text)]
            cell_ctx = None
        else:
            parts = [(s, names_competitor(s), node.tag) for s in sentences(text)]
            cell_ctx = None
        units += parts
        if node is not footer_copy:
            number_units += [(*u, cell_ctx) for u in parts]
    for text, where in [(title, "title"), (description, "meta description")]:
        units.append((text, bool(competitor), where))
        number_units.append((text, bool(competitor), where, None))
    for key, value in [("og:title", meta(root, "property", "og:title")), ("og:description", meta(root, "property", "og:description")),
                       ("twitter:title", meta(root, "name", "twitter:title")), ("twitter:description", meta(root, "name", "twitter:description"))]:
        if value:
            units.append((value, bool(competitor) and value in (title, description), key))
    for n in root.walk():
        for attr in ("aria-label", "alt"):
            if n.attrs.get(attr):
                units += [(s, names_competitor(s), attr) for s in sentences(n.attrs[attr])]

    def ld_strings(obj):
        if isinstance(obj, dict):
            page_node = obj.get("@type") in ("WebPage", "ListItem")
            for k, v in obj.items():
                if isinstance(v, str):
                    if k in ("@type", "@id", "@context", "url", "item"):
                        continue
                    if page_node and k in ("name", "description"):
                        yield v, bool(competitor), f"JSON-LD {obj.get('@type')} {k}"
                    else:
                        for s in sentences(v):
                            yield s, names_competitor(s), f"JSON-LD {k}"
                else:
                    yield from ld_strings(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from ld_strings(v)
    units += list(ld_strings(graph))

    # b. Every number is an allowed fact, and bound to the right fact by its
    #    context: minutes, badges, nudges, free habits and dollar amounts.
    #    Competitor numbers pass only where the competitor rule exempts them.
    for text, exempt, where, ctx in number_units:
        for num in NUMBER.findall(text):
            if num in allowed_numbers or (num in comp_numbers and exempt):
                continue
            extra = " (a competitor number outside the places the competitor rule allows)" if num in comp_numbers else ""
            failures.append(f"{rel}: number {num} is not in facts.allowed_numbers{extra}, in {where}: {text!r}")
        for num, problem in bind_numbers(text, ctx):
            if problem and not (num in comp_numbers and exempt):
                failures.append(f"{rel}: {problem}, in {where}: {text!r}")
    if footer_copy is not None:
        check(footer_copy.text() == f"© {gen.YEAR} HabitFlame", f"{rel}: footer copyright line changed: {footer_copy.text()!r}")

    # c. Premium-only features are only ever named next to the word Premium.
    #    A sentence with the word "free" and a Premium-only feature fails
    #    unless it is, word for word, one of facts.premium_free_forms.
    def premium_free(sentence: str, where: str) -> None:
        if free_word.search(sentence) and any(rx.search(sentence) for _, rx in premium_phrases):
            key = re.sub(r"\s+", " ", sentence).strip().lower()
            if key in premium_free_forms:
                premium_free_forms[key] += 1
            else:
                failures.append(f"{rel}: {where} has 'free' and a Premium-only feature and is not in facts.premium_free_forms: {sentence!r}")

    for unit in page_text_units(root) + [title, description]:
        for sentence in sentences(unit):
            for phrase, rx in premium_phrases:
                if rx.search(sentence) and not premium_word.search(sentence):
                    kind = "free sentence" if free_word.search(sentence) else "sentence"
                    failures.append(f"{rel}: {kind} names Premium-only '{phrase}' without 'Premium': {sentence!r}")
            premium_free(sentence, "sentence")
    for table in by_tag(root, "table"):
        head = table_head(table)
        comp_heads = [["", competitor, "HabitFlame"], ["", "HabitFlame", competitor]] if competitor else []
        for tr in by_tag(first(table, lambda n: n.tag == "tbody") or table, "tr"):
            for c in row_cells(tr):
                premium_free(c.text(), "table cell")
        if head == GUIDE_TABLE_HEAD:
            free_col = head.index("Free")
            for tr in by_tag(first(table, lambda n: n.tag == "tbody") or table, "tr"):
                cells = [c.text() for c in row_cells(tr)]
                if free_col < len(cells) and any(rx.search(cells[free_col]) for _, rx in premium_phrases):
                    failures.append(f"{rel}: Free column cell names a Premium-only feature: {cells[free_col]!r}")
                if any(rx.search(cells[0]) for _, rx in premium_phrases) or cells[0].lower() in {p.lower() for p in FACTS["premium_only"]}:
                    check(free_col < len(cells) and cells[free_col].lower() in {"no", "not included"},
                          f"{rel}: table row {cells[0]!r} marks a Premium-only feature as available under Free")
        elif head in comp_heads:
            for tr in by_tag(first(table, lambda n: n.tag == "tbody") or table, "tr"):
                row = " ".join(c.text() for c in row_cells(tr))
                if any(rx.search(row) for _, rx in premium_phrases) and not premium_word.search(row):
                    failures.append(f"{rel}: table row names a Premium-only feature without 'Premium': {row!r}")
        else:
            failures.append(f"{rel}: table head {head!r} is neither {GUIDE_TABLE_HEAD!r} nor a competitor head {comp_heads!r}")

    # d. Banned phrases (whole phrase, or with a trailing s or es), anywhere a
    #    reader or a crawler sees text. A negated-only phrase must sit inside
    #    one of the exact facts.negated_forms.
    for text, exempt, where in units:
        for phrase, rx in banned:
            if rx.search(text) and not (phrase.lower() in comp_phrases and exempt):
                failures.append(f"{rel}: banned phrase '{phrase}' in {where}: {text!r}")
        form_spans = []
        for form, frx in negated_forms:
            for fm in frx.finditer(text):
                form_spans.append((fm.start(), fm.end()))
                negated_forms_used[form] += 1
        for phrase, rx in negated:
            for m in rx.finditer(text):
                if any(s <= m.start() and m.end() <= e for s, e in form_spans):
                    continue
                if phrase.lower() in comp_phrases and exempt:
                    continue
                failures.append(f"{rel}: '{phrase}' outside every facts.negated_forms entry, in {where}: {text!r}")

    # e. Links, store link, brand footer, contact email. Internal hrefs are
    #    resolved as a browser would; a path with an empty or dot segment fails
    #    outright, and the result must sit under base_url and map to a file.
    for n in root.walk():
        for attr in ("href", "src"):
            href = n.attrs.get(attr)
            if href is None or href.startswith(("mailto:", "tel:")):
                continue
            split = urlsplit(href)
            if split.scheme or split.netloc:
                if not href.startswith(BASE + "/") and href != BASE:
                    continue  # external
            path = split.path
            if "//" in path or "/./" in path or "/../" in path or path.startswith(("./", "../")) or path.endswith(("/.", "/..")) or path in (".", ".."):
                failures.append(f"{rel}: link {href!r} has an empty or dot path segment")
                continue
            target_url = urljoin(url, href)
            if not target_url.startswith(BASE + "/"):
                failures.append(f"{rel}: link {href!r} resolves to {target_url}, outside {BASE}/")
                continue
            path_part, _, frag = target_url[len(BASE):].partition("#")
            path_part = path_part.split("?", 1)[0].lstrip("/")
            fpath = ROOT / path_part
            if path_part == "" or path_part.endswith("/") or fpath.is_dir():
                fpath = fpath / "index.html"
            if not fpath.is_file():
                failures.append(f"{rel}: link {href!r} does not resolve to a file ({fpath.relative_to(ROOT)})")
                continue
            if frag:
                trel = str(fpath.relative_to(ROOT))
                ttext = FRESH.get(trel) or fpath.read_text(encoding="utf-8", errors="replace")
                check(re.search(r'\bid="' + re.escape(frag) + '"', ttext) is not None,
                      f"{rel}: link {href!r} points at #{frag}, which {trel} does not have")
    check(raw.count(PINNED_APP_STORE_URL) >= 2, f"{rel}: App Store URL appears {raw.count(PINNED_APP_STORE_URL)} times, want 2 or more")
    store_buttons = root.find_all(lambda n: n.tag == "a" and "store" in n.classes and n.attrs.get("href") == PINNED_APP_STORE_URL)
    check(len(store_buttons) >= 1, f"{rel}: no App Store button")
    brand = footer and first(footer, lambda n: n.tag == "a" and n.attrs.get("href") == BRAND_URL)
    check(bool(brand) and brand.text() == BRAND_TEXT, f"{rel}: footer lacks <a href=\"{BRAND_URL}\">{BRAND_TEXT}</a>")
    check("nofollow" not in raw.lower(), f"{rel}: contains nofollow")
    emails = emails_in(raw)
    check(emails <= {SITE["contact_email"]}, f"{rel}: unexpected email addresses {sorted(emails - {SITE['contact_email']})}")
    check(SITE["contact_email"] in emails, f"{rel}: contact email missing")

    # f. Metadata.
    check(title == want_title, f"{rel}: <title> is {title!r}, want {want_title!r}")
    if len(title) > 60:
        over = len(title) - 60
        notes.append(f"{rel}: title is {len(title)} chars ({over} over 60)")
        check(over <= 5, f"{rel}: title is {len(title)} chars, more than 5 over the 60 limit")
    check(description == want_desc, f"{rel}: meta description differs from pages.json")
    check(len(description) <= 160, f"{rel}: description is {len(description)} chars, limit 160")
    check(meta(root, "property", "og:title") == title, f"{rel}: og:title differs from title")
    check(meta(root, "name", "twitter:title") == title, f"{rel}: twitter:title differs from title")
    check(meta(root, "property", "og:description") == description, f"{rel}: og:description differs from description")
    check(meta(root, "name", "twitter:description") == description, f"{rel}: twitter:description differs from description")
    canon = first(root, lambda n: n.tag == "link" and n.attrs.get("rel") == "canonical")
    check(canon is not None and canon.attrs.get("href") == url, f"{rel}: canonical is not {url}")
    check(meta(root, "property", "og:url") == url, f"{rel}: og:url is not {url}")
    robots = (meta(root, "name", "robots") or "index").lower()
    check("noindex" not in robots and "none" not in robots, f"{rel}: robots meta blocks indexing: {robots}")
    check(len(by_tag(root, "h1")) == 1, f"{rel}: expected exactly one h1")
    dts = [n.text() for n in by_tag(root, "dt")]
    dds = [n.text() for n in by_tag(root, "dd")]
    faqs = [g for g in graph if g.get("@type") == "FAQPage"]
    if dts:
        check(len(faqs) == 1, f"{rel}: visible FAQ but {len(faqs)} FAQPage nodes")
        if faqs:
            ents = faqs[0].get("mainEntity", [])
            check([e.get("name") for e in ents] == dts, f"{rel}: FAQPage questions differ from the visible questions")
            check([e.get("acceptedAnswer", {}).get("text") for e in ents] == dds, f"{rel}: FAQPage answers differ from the visible answers")
    else:
        check(not faqs, f"{rel}: FAQPage without a visible FAQ")
    for bad in ("AggregateRating", "ratingValue", "reviewCount"):
        check(bad.lower() not in raw.lower(), f"{rel}: contains {bad}")
    types_present = [g.get("@type") for g in graph]
    want_types = {"WebPage"} | ({"WebSite", "SoftwareApplication"} if page is None else {"BreadcrumbList"})
    check(want_types <= set(types_present), f"{rel}: JSON-LD types {types_present} lack {sorted(want_types - set(types_present))}")
    for g in graph:
        if g.get("@type") == "WebPage":
            check(g.get("name") == title and g.get("description") == description and g.get("url") == url,
                  f"{rel}: WebPage name, description or url differs from the page")
        if g.get("@type") in ("WebSite", "SoftwareApplication"):
            check(g.get("name") == PINNED_NAME, f"{rel}: JSON-LD {g.get('@type')} name is {g.get('name')!r}, pinned {PINNED_NAME!r}")
        if g.get("@type") == "SoftwareApplication":
            check(g.get("url") == PINNED_APP_STORE_URL, f"{rel}: SoftwareApplication url is not the pinned App Store URL")
            check("review" not in g and "aggregateRating" not in g, f"{rel}: SoftwareApplication carries ratings")

    # g. Word counts.
    if page is None:
        n_words = len(re.findall(r"\S*[A-Za-z0-9]\S*", main.text() if main else ""))
        word_counts.append((rel + " (main)", n_words))
        check(n_words >= 500, f"{rel}: main has {n_words} words, want at least 500")
    else:
        art = first(root, lambda n: "article-body" in n.classes)
        n_words = len(re.findall(r"\S*[A-Za-z0-9]\S*", art.text() if art else ""))
        word_counts.append((rel + " (article-body)", n_words))
        check(900 <= n_words <= 1500, f"{rel}: article body has {n_words} words, want 900 to 1500")

# 9. Every allowed negated form is one the copy actually uses.
for form, count in negated_forms_used.items():
    check(count > 0, f"facts.negated_forms has {form!r}, which no page uses (remove it)")

# c. Every allowlisted free and Premium sentence is one the copy uses.
for form, count in premium_free_forms.items():
    check(count > 0, f"facts.premium_free_forms has {form!r}, which no page uses (remove it)")

# l. Text colors in styles.css meet 4.5:1 in both themes.
CSS = (ROOT / "styles.css").read_text(encoding="utf-8")


def css_vars(block: str) -> dict[str, str]:
    return {k: v.strip() for k, v in re.findall(r"--([\w-]+):\s*([^;]+);", block)}


def css_rule(selector: str) -> dict[str, str]:
    m = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    return {k.strip(): v.strip() for k, v in re.findall(r"([\w-]+)\s*:\s*([^;]+);", m.group(1))} if m else {}


def css_color(value: str, env: dict[str, str]) -> str:
    for _ in range(5):
        m = re.fullmatch(r"var\(--([\w-]+)\)", value.strip())
        if not m:
            break
        value = env[m.group(1)]
    value = value.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3}", value):
        value = "#" + "".join(ch * 2 for ch in value[1:])
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError(f"not a hex color: {value!r}")
    return value


def contrast(a: str, b: str) -> float:
    def lum(h: str) -> float:
        rgb = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        rgb = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


dark_m = re.search(r"(?m)^:root\s*\{([^}]*)\}", CSS)
light_m = re.search(r'@media \(prefers-color-scheme: light\)\s*\{\s*:root:not\(\[data-theme="dark"\]\)\s*\{([^}]*)\}', CSS)
check(bool(dark_m and light_m), "styles.css: cannot find the dark :root block or the light theme block")
contrast_lines = []
if dark_m and light_m:
    dark_env = css_vars(dark_m.group(1))
    themes = {"dark": dark_env, "light": {**dark_env, **css_vars(light_m.group(1))}}
    store, hover = css_rule(".store"), css_rule(".store:hover")
    for theme, env in themes.items():
        pairs = [(f"--{t} on --{b}", env[t], env[b]) for t in ("ink", "ink-2", "ink-3", "link") for b in ("bg", "bg-2")]
        pairs += [("store button", store.get("color", ""), store.get("background", "")),
                  ("store button hover", hover.get("color", ""), hover.get("background", ""))]
        worst = []
        for name, fg, bg in pairs:
            try:
                ratio = contrast(css_color(fg, env), css_color(bg, env))
            except (KeyError, ValueError) as e:
                failures.append(f"styles.css {theme}: {name}: {e}")
                continue
            worst.append((ratio, name))
            check(ratio >= 4.5, f"styles.css {theme}: {name} is {ratio:.2f}:1, below 4.5:1")
        if worst:
            r, name = min(worst)
            contrast_lines.append(f"contrast {theme}: lowest {r:.2f}:1 ({name}) of {len(worst)} pairs")

# h. Prose hygiene.
DASHES = {0x2012, 0x2013, 0x2014, 0x2015, 0x2212}
PICTO_RANGES = [(0x1F000, 0x10FFFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF), (0x2300, 0x23FF), (0x2190, 0x21FF),
                (0xFE00, 0xFE0F), (0x200D, 0x200D), (0x20D0, 0x20FF), (0x3030, 0x3030), (0x303D, 0x303D), (0x3297, 0x3297), (0x3299, 0x3299)]


def pictographic(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in PICTO_RANGES)


# The only list, stored rot13 so this file never spells the names it bans.
TOOL_NAMES = {codecs.decode(w, "rot13") for w in ("pynhqr", "pbqrk", "tcg", "naguebcvp", "bcranv")}
tool_rx = [(w, whole(w)) for w in sorted(TOOL_NAMES)]

hygiene_files = {
    "scripts/pages.json": (ROOT / "scripts/pages.json").read_text(encoding="utf-8"),
    "scripts/template.html": (ROOT / "scripts/template.html").read_text(encoding="utf-8"),
    "styles.css": (ROOT / "styles.css").read_text(encoding="utf-8"),
    "scripts/build-pages.py": GEN_PATH.read_text(encoding="utf-8"),
    "scripts/verify-pages.py": pathlib.Path(__file__).read_text(encoding="utf-8"),
    "privacy-policy.html": (ROOT / "privacy-policy.html").read_text(encoding="utf-8"),
}
hygiene_files.update(FRESH)
for name, text in hygiene_files.items():
    for lineno, line in enumerate(text.splitlines(), 1):
        for ch in line:
            cp = ord(ch)
            if cp in DASHES:
                failures.append(f"{name}:{lineno}: dash character U+{cp:04X}")
            elif pictographic(cp):
                failures.append(f"{name}:{lineno}: pictographic character U+{cp:04X}")
        for w, rx in tool_rx:
            if rx.search(line):
                failures.append(f"{name}:{lineno}: tool name '{w}'")


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)


for s in strings(gen.CONFIG):
    if " - " in s:
        failures.append(f"scripts/pages.json: spaced hyphen in {s[:80]!r}")

# i. Sitemap lists exactly the landing, the guides and the policy pages, each
#    dated site.lastmod.
sitemap = FRESH["sitemap.xml"]
locs = [htmlmod.unescape(u) for u in re.findall(r"<loc>([^<]*)</loc>", sitemap)]
want_locs = [f"{BASE}/"] + [f"{BASE}/{p['slug']}/" for p in PAGES] + [f"{BASE}/{n}" for n in gen.POLICY_PAGES]
check(len(locs) == len(set(locs)), f"sitemap.xml: duplicate URLs {sorted({u for u in locs if locs.count(u) > 1})}")
check(set(locs) == set(want_locs), f"sitemap.xml: lists {sorted(set(locs) ^ set(want_locs))} unexpectedly or misses them")
check(len(locs) == 1 + len(PAGES) + len(gen.POLICY_PAGES), f"sitemap.xml: {len(locs)} URLs")
lastmods = re.findall(r"<lastmod>([^<]*)</lastmod>", sitemap)
check(len(lastmods) == len(locs) and set(lastmods) == {SITE.get("lastmod")},
      f"sitemap.xml: lastmod values {sorted(set(lastmods))} differ from site.lastmod {SITE.get('lastmod')!r}")
for u in locs:
    rel = u[len(BASE) + 1:] if u.startswith(BASE + "/") else None
    if rel is None:
        failures.append(f"sitemap.xml: {u} is outside the site")
        continue
    f = ROOT / (rel + "index.html" if rel == "" or rel.endswith("/") else rel)
    check(f.is_file(), f"sitemap.xml: {u} does not resolve to a file")
# j. The privacy policy (hand written, not generated) says what the app does.
POLICY = (ROOT / "privacy-policy.html").read_text(encoding="utf-8")
for must in ("PostHog", "pairing service", "push notification", "Apple Health", "Screen recordings", "weekly count", SITE["contact_email"]):
    check(must in POLICY, f"privacy-policy.html: missing {must!r}")
for stale in ("We do not collect any personal information", "do not use analytics", "do not have servers",
              "does not integrate with any third-party analytics"):
    check(stale.lower() not in POLICY.lower(), f"privacy-policy.html: still says {stale!r}")
policy_emails = emails_in(POLICY)
check(policy_emails == {SITE["contact_email"]}, f"privacy-policy.html: email addresses {sorted(policy_emails)}")

# k. The inline link form in pages.json never reaches a page unrendered.
for rel, text in FRESH.items():
    for m in re.finditer(r"\[[^\[\]\n]+\]\([^)\s]*\)", text):
        failures.append(f"{rel}: inline link markup left unrendered: {m.group(0)!r}")

check(FRESH["robots.txt"] == f"User-agent: *\nAllow: /\nSitemap: {PINNED_BASE_URL}/sitemap.xml\n", "robots.txt: content changed")

# ---- Report ------------------------------------------------------------------
print(f"sitemap lastmod {SITE.get('lastmod')}")
for line in contrast_lines:
    print(line)
for name, n in word_counts:
    print(f"words  {n:5d}  {name}")
for note in notes:
    print(f"note   {note}")
if failures:
    for f in failures:
        print(f"FAIL   {f}")
    print(f"{len(failures)} failure(s)")
    sys.exit(1)
print(f"OK: {len(HTML_PAGES)} pages, {len(FRESH)} generated files, 0 failures")
