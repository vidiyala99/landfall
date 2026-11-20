"""Fix: turn a scan into an owner-ready fix package and apply it to a copy of the mirror.

    python -m landfall.fix runs/<slug>

Reads runs/<slug>/scan.json (and runs/<slug>/mirror/ if present). Writes:
    runs/<slug>/fixes/        jsonld.json, llms.txt, robots.txt, agent.json, form-labels.md,
                              alt-text.md, facts-text.md, needs-owner.md, CHANGES.md
    runs/<slug>/mirror-fixed/ copy of the mirror with the fixes applied

Rule: never invent a fact. Every business value comes from scan.json facts or the mirrored page;
anything unknown is left out and asked in needs-owner.md.
"""
from __future__ import annotations

import argparse
import html as htmlmod
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

AGENT_UAS = ("Claude-User", "ChatGPT-User", "PerplexityBot", "OAI-SearchBot")

# --------------------------------------------------------------------------- page text

class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []  # (href, text)
        self._skip = 0
        self._a: list | None = None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self._skip += 1
        if tag == "a":
            self._a = [dict(attrs).get("href") or "", ""]

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template") and self._skip:
            self._skip -= 1
        if tag == "a" and self._a is not None:
            self.links.append((self._a[0], self._a[1].strip()))
            self._a = None

    def handle_data(self, data):
        if self._skip:
            return
        self.parts.append(data)
        if self._a is not None:
            self._a[1] += data


def page_text_and_links(html: str) -> tuple[str, list[tuple[str, str]]]:
    p = _Text()
    try:
        p.feed(html)
    except Exception:
        pass
    text = re.sub(r"\s+", " ", " ".join(p.parts)).strip()
    return text, p.links


# --------------------------------------------------------------------------- business type

SUBTYPES = [  # (schema type, keywords) first match wins, ordered most specific first
    ("Bakery", ["bakery", "bakeries", "bakeshop", "patisserie", "pâtisserie", "boulangerie", "donut", "doughnut", "cupcake"]),
    ("CafeOrCoffeeShop", ["coffee shop", "coffeehouse", "espresso", "café", "cafe ", "coffee"]),
    ("IceCreamShop", ["ice cream", "gelato", "creamery"]),
    ("BarOrPub", ["brewery", "brewpub", "taproom", "pub ", "tavern", "cocktail bar", "wine bar"]),
    ("HairSalon", ["hair salon", "barbershop", "barber shop"]),
    ("BeautySalon", ["beauty salon", "nail salon", "spa "]),
    ("Dentist", ["dentist", "dental"]),
    ("AutoRepair", ["auto repair", "mechanic", "oil change"]),
    ("Florist", ["florist", "flower shop"]),
    ("Restaurant", ["restaurant", "pizzeria", "pizza", "diner", "bistro", "grill", "eatery", "taqueria", "kitchen"]),
]


def pick_subtype(name: str, text: str) -> str:
    """Best LocalBusiness subtype from the business name first, then page text by frequency."""
    n = (name or "").lower() + " "
    for t, kws in SUBTYPES:
        if any(k in n for k in kws):
            return t
    low = " " + (text or "").lower() + " "
    best, best_count = "LocalBusiness", 0
    for t, kws in SUBTYPES:
        c = sum(low.count(k) for k in kws)
        if c > best_count:
            best, best_count = t, c
    return best if best_count >= 2 else "LocalBusiness"


# --------------------------------------------------------------------------- hours parsing

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_DAY_ALIASES = {
    "mon": 0, "monday": 0, "mo": 0,
    "tue": 1, "tues": 1, "tuesday": 1, "tu": 1,
    "wed": 2, "weds": 2, "wednesday": 2, "we": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "th": 3,
    "fri": 4, "friday": 4, "fr": 4,
    "sat": 5, "saturday": 5, "sa": 5,
    "sun": 6, "sunday": 6, "su": 6,
}
_DAY_TOKEN = r"(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:s|nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\.?"
_TIME = r"(?:\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?|noon|midnight)"
_RANGE_SEP = r"\s*(?:-|–|—|to|until|till)\s*"


def _parse_time(tok: str) -> tuple[int, int, str | None]:
    t = tok.strip().lower().replace(".", "").replace(" ", "")
    if t == "noon":
        return 12, 0, "pm"
    if t == "midnight":
        return 0, 0, "am"
    m = re.match(r"(\d{1,2})(?::(\d{2}))?(am|pm)?$", t)
    if not m:
        raise ValueError(tok)
    return int(m.group(1)), int(m.group(2) or 0), m.group(3)


def _to24(h: int, mi: int, mer: str | None) -> tuple[int, int]:
    if mer == "am":
        h = 0 if h == 12 else h
    elif mer == "pm":
        h = h if h == 12 else h + 12
    return h, mi


def _resolve_range(a: str, b: str) -> tuple[str, str]:
    oh, om, omer = _parse_time(a)
    ch, cm, cmer = _parse_time(b)
    if oh > 12:
        omer = None
    if ch > 12:
        cmer = None
    if oh <= 12 and omer is None:
        if cmer == "pm":
            omer = "am" if (ch == 12 or oh > ch) else "pm"
            if oh == 12:
                omer = "pm"
        elif cmer == "am":
            omer = "pm" if oh > ch else "am"
        else:
            omer = "pm" if oh == 12 or oh < 5 else "am"
    o = _to24(oh, om, omer) if oh <= 12 else (oh, om)
    if ch <= 12 and cmer is None:
        am = _to24(ch, cm, "am")
        cmer = "am" if (am[0] * 60 + am[1]) > (o[0] * 60 + o[1]) and ch != 12 else "pm"
    c = _to24(ch, cm, cmer) if ch <= 12 else (ch, cm)
    return f"{o[0]:02d}:{o[1]:02d}", f"{c[0]:02d}:{c[1]:02d}"


def _parse_days(s: str) -> list[int]:
    s = s.lower().strip()
    if re.search(r"\b(daily|every\s*day|7 days|seven days|mon(?:day)?\s*(?:-|–|to)\s*sun(?:day)?)\b", s):
        if re.search(r"\b(daily|every\s*day|7 days|seven days)\b", s):
            return list(range(7))
    days: list[int] = []
    for chunk in re.split(r",|&|\band\b|/", s):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = re.match(rf"({_DAY_TOKEN}){_RANGE_SEP}({_DAY_TOKEN})$", chunk)
        if m:
            a = _DAY_ALIASES[m.group(1).rstrip(".")]
            b = _DAY_ALIASES[m.group(2).rstrip(".")]
            i = a
            while True:
                days.append(i)
                if i == b:
                    break
                i = (i + 1) % 7
            continue
        m = re.match(rf"({_DAY_TOKEN})$", chunk)
        if m:
            days.append(_DAY_ALIASES[m.group(1).rstrip(".")])
    return days


def parse_hours(text: str) -> list[dict]:
    """Parse free-text hours into schema.org OpeningHoursSpecification dicts.

    "Mon-Fri 7am-3pm, Sat 8-2" -> Mon..Fri 07:00-15:00, Saturday 08:00-14:00.
    Days marked closed are skipped. Unparseable segments are ignored (caller reports them).
    """
    if not text:
        return []
    s = text.replace("–", "-").replace("—", "-")
    day_group = rf"(?:daily|every\s*day|{_DAY_TOKEN}(?:\s*(?:-|–|to|,|&|and|/)\s*{_DAY_TOKEN})*)"
    pat = re.compile(
        rf"(?P<days>{day_group})\s*:?\s*(?P<open>{_TIME}){_RANGE_SEP}(?P<close>{_TIME})",
        re.IGNORECASE,
    )
    by_range: dict[tuple[str, str], list[int]] = {}
    order: list[tuple[str, str]] = []
    seen_days: set[int] = set()
    for m in pat.finditer(s):
        days = _parse_days(m.group("days"))
        try:
            o, c = _resolve_range(m.group("open"), m.group("close"))
        except ValueError:
            continue
        key = (o, c)
        if key not in by_range:
            by_range[key] = []
            order.append(key)
        for d in days:
            if d not in seen_days:
                by_range[key].append(d)
                seen_days.add(d)
    specs = []
    for key in order:
        ds = sorted(by_range[key])
        if not ds:
            continue
        specs.append({
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": [DAYS[d] for d in ds],
            "opens": key[0],
            "closes": key[1],
        })
    return specs


# --------------------------------------------------------------------------- address

_US_ADDR = re.compile(
    r"^\s*(?P<street>.+?),\s*(?P<city>[A-Za-z .'-]+?),?\s+(?P<region>[A-Z]{2})\.?\s+(?P<zip>\d{5}(?:-\d{4})?)\s*(?:,?\s*(?P<country>USA|US|United States))?\s*$"
)


def parse_address(addr: str) -> dict:
    """PostalAddress from an address string. Only substrings of the input are used."""
    if not addr:
        return {}
    a = re.sub(r"\s+", " ", addr).strip()
    m = _US_ADDR.match(a)
    if not m:
        return {"@type": "PostalAddress", "streetAddress": a}
    out = {
        "@type": "PostalAddress",
        "streetAddress": m.group("street").strip(),
        "addressLocality": m.group("city").strip(),
        "addressRegion": m.group("region"),
        "postalCode": m.group("zip"),
    }
    if m.group("country"):
        out["addressCountry"] = m.group("country")
    return out


# --------------------------------------------------------------------------- links from the page

def find_links(links: list[tuple[str, str]], base: str, words: tuple[str, ...]) -> list[str]:
    out = []
    for href, text in links:
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        hay = (href + " " + text).lower()
        if any(w in hay for w in words):
            u = urljoin(base, href)
            if u not in out:
                out.append(u)
    return out


# --------------------------------------------------------------------------- JSON-LD

def build_jsonld(scan: dict, page_text: str = "", links: list | None = None) -> tuple[dict, list[str]]:
    """Return (jsonld, owner_questions). Uses only values present in scan facts / page links."""
    facts = scan.get("facts") or {}
    url = scan.get("url") or ""
    links = links or []
    questions: list[str] = []
    name = (facts.get("name") or "").strip()
    ld: dict = {"@context": "https://schema.org", "@type": pick_subtype(name, page_text)}
    if name:
        ld["name"] = name
    else:
        questions.append("What is the exact business name customers should see?")
    if url:
        ld["url"] = url
    phone = (facts.get("phone") or "").strip()
    if phone:
        ld["telephone"] = phone
    else:
        questions.append("What phone number should customers and agents call? (none found on the page)")
    addr = (facts.get("address") or "").strip()
    if addr:
        ld["address"] = parse_address(addr)
    else:
        questions.append("What is the street address (or service area, if you have no storefront)?")
    hours_text = (facts.get("hours_text") or "").strip()
    specs = parse_hours(hours_text)
    if specs:
        ld["openingHoursSpecification"] = specs
        covered = {d for s in specs for d in s["dayOfWeek"]}
        missing = [d for d in DAYS if d not in covered]
        if missing:
            questions.append(
                f"Hours found: \"{hours_text}\". Are you closed on {', '.join(missing)}? (we left those days out)"
            )
    elif hours_text:
        questions.append(f"We found hours text \"{hours_text}\" but could not parse it reliably; please confirm day-by-day hours.")
    else:
        questions.append("What are your opening hours, day by day?")
    menus = find_links(links, url, ("menu",))
    if menus:
        ld["hasMenu"] = menus[0]
    offers = [o.strip() for o in (facts.get("offer_snippets") or []) if o and o.strip()]
    if offers:
        ld["makesOffer"] = [
            {"@type": "Offer", "itemOffered": {"@type": "Thing", "name": o}} for o in offers[:20]
        ]
    if not menus and not offers:
        questions.append("Do you have a menu or product list page we should link (hasMenu)?")
    questions.append("Prices are not included. Do you want prices listed for agents? If so, which items and amounts?")
    questions.append("Do you have a logo or storefront photo URL to include as the business image?")
    return ld, questions


def jsonld_leaf_strings(obj) -> list[str]:
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("@context", "@type"):
                continue
            out += jsonld_leaf_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            out += jsonld_leaf_strings(v)
    elif isinstance(obj, str):
        out.append(obj)
    return out


# --------------------------------------------------------------------------- llms.txt

def build_llms_txt(scan: dict, ld: dict, links: list) -> str:
    f = scan.get("facts") or {}
    url = scan.get("url") or ""
    name = f.get("name") or urlsplit(url).netloc
    kind = {"LocalBusiness": "local business", "CafeOrCoffeeShop": "cafe / coffee shop", "BarOrPub": "bar / pub",
            "IceCreamShop": "ice cream shop", "AutoRepair": "auto repair shop", "HairSalon": "hair salon",
            "BeautySalon": "beauty salon"}.get(ld["@type"], ld["@type"].lower())
    lines = [f"# {name}", ""]
    summary = f"> {name} is a {kind}"
    if f.get("address"):
        summary += f" at {f['address']}"
    lines += [summary + ".", ""]
    lines += ["## Basics", ""]
    if f.get("address"):
        lines.append(f"- Address: {f['address']}")
    if f.get("phone"):
        lines.append(f"- Phone: {f['phone']}")
    if f.get("hours_text"):
        lines.append(f"- Hours: {f['hours_text']}")
    if url:
        lines.append(f"- Website: {url}")
    lines.append("")
    offers = f.get("offer_snippets") or []
    if offers:
        lines += ["## What we offer", ""] + [f"- {o}" for o in offers] + [""]
    order = find_links(links, url, ("order", "book", "reserv", "appointment", "schedule", "catering", "cake"))
    menus = find_links(links, url, ("menu",))
    lines += ["## How to order or book", ""]
    if order:
        lines += [f"- {u}" for u in order[:5]]
    if menus:
        lines += [f"- Menu: {u}" for u in menus[:3]]
    if f.get("phone"):
        lines.append(f"- Call {f['phone']}")
    if not order and not f.get("phone"):
        lines.append("- (not stated on the website)")
    lines += ["", "## Contact", ""]
    if f.get("phone"):
        lines.append(f"- Phone: {f['phone']}")
    if url:
        lines.append(f"- Website: {url}")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- robots.txt

def _robots_groups(text: str) -> list[tuple[list[str], list[str]]]:
    """[(user_agents_lowercase, rule_lines)] in file order."""
    groups: list[tuple[list[str], list[str]]] = []
    cur_ua: list[str] = []
    cur_rules: list[str] = []
    last_was_ua = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        if k.lower() == "user-agent":
            if not last_was_ua and (cur_ua or cur_rules):
                groups.append((cur_ua, cur_rules))
                cur_ua, cur_rules = [], []
            cur_ua.append(v.lower())
            last_was_ua = True
        else:
            if k.lower() in ("allow", "disallow"):
                cur_rules.append(f"{k.lower()}:{v}")
            last_was_ua = False
    if cur_ua or cur_rules:
        groups.append((cur_ua, cur_rules))
    return groups


def _star_rule_lines(text: str) -> list[str]:
    out, in_star, last_ua = [], False, False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        kl = k.lower()
        if kl == "user-agent":
            in_star = (in_star or v == "*") if last_ua else v == "*"
            last_ua = True
            continue
        last_ua = False
        if in_star and kl in ("allow", "disallow") and v and not (kl == "disallow" and v == "/"):
            out.append(f"{k.capitalize()}: {v}")
    return out


def link_phone(html: str, phone: str) -> tuple[str, bool]:
    """Wrap the first plain-text occurrence of the phone in a tel: link (if the page has none)."""
    if not phone or "tel:" in html.lower():
        return html, False
    body = re.search(r"<body\b[^>]*>", html, re.IGNORECASE)
    start = body.end() if body else 0
    digits = re.sub(r"[^\d+]", "", phone)
    skip_until = -1
    for tm in re.finditer(r"<(/?)(script|style|a)\b[^>]*>|([^<]+)", html[start:], re.IGNORECASE):
        if tm.group(2):  # tag: skip text inside script/style/a
            if tm.group(1) == "":
                skip_until = 1
            else:
                skip_until = -1
            continue
        if skip_until == 1:
            continue
        text = tm.group(3)
        i = text.find(phone)
        if i >= 0:
            pos = start + tm.start(3) + i
            link = f'<a href="tel:{digits}">{phone}</a>'
            return html[:pos] + link + html[pos + len(phone):], True
    return html, False


def patch_robots(existing: str, sitemap_url: str | None = None) -> tuple[str, list[str], list[str]]:
    """Return (new_robots, agents_added, owner_blocked_agents).

    Keeps every existing line verbatim. Adds an Allow group for user-facing agents that the owner
    has not named. If the owner explicitly blocked one of them, we do not override it (owner question).
    """
    existing = existing or ""
    groups = _robots_groups(existing)
    named = {ua for uas, _ in groups for ua in uas}
    blocked = []
    add = []
    for agent in AGENT_UAS:
        a = agent.lower()
        if a in named:
            rules = [r for uas, rs in groups if a in uas for r in rs]
            if "disallow:/" in rules:
                blocked.append(agent)
            continue
        add.append(agent)
    out = existing.rstrip("\n")
    if add:
        block = ["", "# Added by Landfall: let user-facing AI agents read the site when a customer asks them to."]
        block += [f"User-agent: {a}" for a in add]
        # A named group replaces the * group for these agents, so carry the owner's * rules over
        # (minus a blanket "Disallow: /", which is the thing being fixed).
        for raw in _star_rule_lines(existing):
            block.append(raw)
        block += ["Allow: /", ""]
        out = (out + "\n" if out else "") + "\n".join(block).lstrip("\n") if not out else out + "\n" + "\n".join(block)
    if sitemap_url and "sitemap:" not in existing.lower():
        out = out.rstrip("\n") + f"\n\nSitemap: {sitemap_url}\n"
    if not out.endswith("\n"):
        out += "\n"
    return out, add, blocked


# --------------------------------------------------------------------------- forms and images

class _Elems(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inputs: list[dict] = []
        self.imgs: list[dict] = []
        self.label_for: set[str] = set()
        self.label_depth = 0
        self.labelled_ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        d = {k.lower(): (v or "") for k, v in attrs}
        pos = self.getpos()
        if tag == "label":
            self.label_depth += 1
            if d.get("for"):
                self.label_for.add(d["for"])
        elif tag in ("input", "select", "textarea"):
            if tag == "input" and d.get("type", "text").lower() in ("hidden", "submit", "button", "reset", "image"):
                return
            self.inputs.append({"tag": tag, "attrs": d, "in_label": self.label_depth > 0, "pos": pos})
        elif tag == "img":
            self.imgs.append({"attrs": d, "pos": pos})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag == "label":
            self.label_depth = max(0, self.label_depth - 1)

    def handle_endtag(self, tag):
        if tag == "label":
            self.label_depth = max(0, self.label_depth - 1)


def _humanize(s: str) -> str:
    s = re.sub(r"[\[\]_\-.]+", " ", s)
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    return re.sub(r"\s+", " ", s).strip().capitalize()


def unlabeled_inputs(html: str) -> list[dict]:
    p = _Elems()
    try:
        p.feed(html)
    except Exception:
        pass
    out = []
    for inp in p.inputs:
        a = inp["attrs"]
        if inp["in_label"] or a.get("aria-label") or a.get("aria-labelledby") or a.get("title"):
            continue
        if a.get("id") and a["id"] in p.label_for:
            continue
        sugg = a.get("placeholder") or (_humanize(a["name"]) if a.get("name") else "")
        out.append({"tag": inp["tag"], "attrs": a, "suggested": sugg, "line": inp["pos"][0]})
    return out


_HASHY = re.compile(r"^(img|dsc|image|photo|screenshot|untitled|pxl)?[\s_-]*\d+$|^[0-9a-f]{12,}$", re.IGNORECASE)


def suggest_alt(src: str, manifest_assets: dict) -> str:
    orig = manifest_assets.get(src) or src
    base = urlsplit(orig).path.rsplit("/", 1)[-1]
    base = re.sub(r"^[0-9a-f]{8}-", "", base)  # mirror hash prefix
    stem = base.rsplit(".", 1)[0]
    stem = re.sub(r"\+", " ", stem)
    stem = re.sub(r"(?i)(-|_)?(\d{2,4}x\d{2,4}|scaled|min|copy|final|v\d+)$", "", stem)
    words = _humanize(stem)
    alpha = re.findall(r"[A-Za-z]{3,}", words)
    if len(alpha) < 2 or _HASHY.match(stem.replace(" ", "")):
        return ""
    return words


def missing_alt_images(html: str, manifest_assets: dict) -> list[dict]:
    p = _Elems()
    try:
        p.feed(html)
    except Exception:
        pass
    out = []
    for img in p.imgs:
        a = img["attrs"]
        if "alt" in a:
            continue  # alt="" is a deliberate decorative marker
        src = a.get("src") or a.get("data-src") or ""
        out.append({"src": src, "suggested": suggest_alt(src, manifest_assets), "line": img["pos"][0]})
    return out


def _add_attr_to_tag(html: str, tag_re: str, attr: str, value: str) -> tuple[str, bool]:
    m = re.search(tag_re, html, re.IGNORECASE | re.DOTALL)
    if not m:
        return html, False
    tag = m.group(0)
    new = re.sub(r"\s*/?>$", lambda e: f' {attr}="{htmlmod.escape(value, quote=True)}"' + e.group(0), tag, count=1)
    return html[: m.start()] + new + html[m.end():], True


def apply_labels(html: str, items: list[dict]) -> tuple[str, int]:
    n = 0
    for it in items:
        if not it["suggested"]:
            continue
        a = it["attrs"]
        key = None
        for k in ("id", "name", "placeholder"):
            if a.get(k):
                key = (k, a[k])
                break
        if not key:
            continue
        tag_re = rf"<{it['tag']}\b(?![^>]*aria-label)[^>]*\b{key[0]}\s*=\s*[\"']{re.escape(key[1])}[\"'][^>]*>"
        html, ok = _add_attr_to_tag(html, tag_re, "aria-label", it["suggested"])
        n += ok
    return html, n


def apply_alts(html: str, items: list[dict]) -> tuple[str, int]:
    n = 0
    for it in items:
        if not it["suggested"] or not it["src"]:
            continue
        tag_re = rf"<img\b(?![^>]*\balt\s*=)[^>]*\bsrc\s*=\s*[\"']{re.escape(it['src'])}[\"'][^>]*>"
        html, ok = _add_attr_to_tag(html, tag_re, "alt", it["suggested"])
        n += ok
    return html, n


# --------------------------------------------------------------------------- facts locked in PDFs / images

def extract_locked_facts(check: dict, run_dir: Path) -> tuple[str, str]:
    """Return (markdown, status) where status is 'extracted' | 'not-extractable'."""
    r = check.get("receipt") or {}
    src = r.get("url") or r.get("path") or ""
    md = [f"## Source: {src or '(no receipt)'}", ""]
    if src.lower().split("?")[0].endswith(".pdf"):
        data = None
        local = run_dir / r["path"] if r.get("path") else None
        if local and local.exists():
            data = local.read_bytes()
        elif r.get("url"):
            try:
                import urllib.request
                req = urllib.request.Request(r["url"], headers={"User-Agent": "Landfall-fix"}, method="GET")
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = resp.read()
            except Exception:
                data = None
        if data:
            try:
                import io
                from pypdf import PdfReader
                text = "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(data)).pages).strip()
            except Exception:
                text = ""
            if text:
                md += ["Text extracted from the PDF (verbatim, review before publishing as an HTML page):", "", "```", text[:8000], "```", ""]
                return "\n".join(md), "extracted"
        md += ["Could not extract text from this PDF (scanned image or download failed). Owner: please type these facts into a normal web page.", ""]
        return "\n".join(md), "not-extractable"
    md += ["This looks like an image. We do not OCR images (results are unreliable); please put the text from this "
           "image (hours, menu, prices) on the page as real text.", ""]
    if r.get("excerpt"):
        md += [f"Scanner note: {r['excerpt']}", ""]
    return "\n".join(md), "not-extractable"


# --------------------------------------------------------------------------- agent card

def build_agent_card(scan: dict, ld: dict, links: list) -> dict:
    f = scan.get("facts") or {}
    url = scan.get("url") or ""
    caps = []
    if ld.get("openingHoursSpecification") or f.get("hours_text"):
        caps.append({"id": "view_hours", "description": "Read opening hours", "how": "schema.org openingHoursSpecification in the homepage JSON-LD; /llms.txt"})
    if ld.get("hasMenu") or ld.get("makesOffer"):
        cap = {"id": "view_menu", "description": "See what is offered", "how": "makesOffer / hasMenu in JSON-LD"}
        if ld.get("hasMenu"):
            cap["url"] = ld["hasMenu"]
        caps.append(cap)
    if f.get("phone"):
        digits = re.sub(r"[^\d+]", "", f["phone"])
        caps.append({"id": "call", "description": "Call the business", "url": f"tel:{digits}"})
    for u in find_links(links, url, ("order", "book", "reserv", "appointment"))[:3]:
        caps.append({"id": "order_or_book", "description": "Order or book (customer completes it; agents should stop before payment)", "url": u})
    return {
        "status": "proposal",
        "note": "Proposed by Landfall; not a ratified standard. Review before publishing at /.well-known/agent.json.",
        "name": f.get("name") or "",
        "url": url,
        "description": f"{f.get('name') or 'This business'} ({ld['@type']})",
        "capabilities": caps,
        "read_only_by_default": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# --------------------------------------------------------------------------- platform hints

def detect_platform(html: str) -> str:
    low = html.lower()
    if "squarespace" in low:
        return "Squarespace"
    if "wix.com" in low or "wixstatic" in low:
        return "Wix"
    if "wp-content" in low or "wordpress" in low:
        return "WordPress"
    if "shopify" in low:
        return "Shopify"
    if "godaddy" in low or "img1.wsimg.com" in low:
        return "GoDaddy"
    return "unknown"


PASTE_HINTS = {
    "jsonld": {
        "Squarespace": "Settings > Advanced > Code Injection > Header: paste the whole `<script type=\"application/ld+json\">` block.",
        "Wix": "Settings > Custom Code > + Add Custom Code: paste the script block, place it in Head, apply to the Home page.",
        "WordPress": "Use a header-code plugin (e.g. WPCode > Header & Footer > Header) or your theme's header.php, inside <head>.",
        "Shopify": "Online Store > Themes > Edit code > theme.liquid: paste before </head>.",
        "GoDaddy": "Website builder > Settings > Site-wide code (Head HTML), if your plan has it; otherwise ask support.",
        "other": "Paste the script block inside the <head> of your homepage.",
    },
    "rootfile": {
        "Squarespace": "Squarespace does not let you upload root files; robots.txt is managed by Squarespace (Settings > Crawlers lets you allow AI crawlers). For llms.txt, ask support or use a redirect.",
        "Wix": "Wix: SEO > Robots.txt editor for robots.txt. llms.txt cannot be uploaded to the root on Wix today.",
        "WordPress": "Upload to your site root (same folder as wp-config.php) via your host's file manager/SFTP, or use an SEO plugin's robots.txt editor.",
        "other": "Upload to the root of your website (so it opens at yoursite.com/<file>).",
    },
}


def _hint(kind: str, platform: str) -> str:
    h = PASTE_HINTS[kind]
    if platform in h:
        return h[platform]
    return h["other"]


# --------------------------------------------------------------------------- orchestration

FIX_OF = {  # check id -> fix kind
    "jsonld_business": "jsonld", "jsonld_hours": "jsonld", "jsonld_offers": "jsonld",
    "contact_machine_readable": "contact", "llms_txt": "llms", "robots_ai": "robots", "sitemap": "sitemap",
    "form_labels": "labels", "img_alt": "alts", "contact_links": "contact", "facts_in_images_or_pdf": "locked", "nojs_content": "llms",
}


def _receipt_link(r: dict) -> str:
    if not r:
        return "(no receipt)"
    if r.get("url"):
        return f"[{r['url']}]({r['url']})"
    if r.get("path"):
        return f"`{r['path']}`"
    return "(no receipt)"


def build_sitemap(url: str) -> str:
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n"
            f"  <url><loc>{htmlmod.escape(url)}</loc></url>\n</urlset>\n")


def inject_jsonld(html: str, ld: dict) -> str:
    block = ('<script type="application/ld+json" data-landfall="1">\n'
             + json.dumps(ld, indent=2, ensure_ascii=False).replace("</", "<\\/") + "\n</script>\n")
    m = re.search(r"</head\s*>", html, re.IGNORECASE)
    if m:
        return html[: m.start()] + block + html[m.start():]
    return block + html


def run(run_dir: str | Path) -> dict:
    run_dir = Path(run_dir)
    scan = json.loads((run_dir / "scan.json").read_text(encoding="utf-8"))
    mirror = run_dir / "mirror"
    fixes = run_dir / "fixes"
    fixed = run_dir / "mirror-fixed"
    fixes.mkdir(parents=True, exist_ok=True)

    html = ""
    manifest_assets: dict = {}
    if (mirror / "index.html").exists():
        html = (mirror / "index.html").read_text(encoding="utf-8", errors="replace")
        if (mirror / "manifest.json").exists():
            manifest_assets = json.loads((mirror / "manifest.json").read_text(encoding="utf-8")).get("assets", {})
    text, links = page_text_and_links(html)
    platform = detect_platform(html)
    url = scan.get("url") or ""
    origin = f"{urlsplit(url).scheme}://{urlsplit(url).netloc}" if url else ""

    checks = scan.get("checks") or []
    failing = [c for c in checks if c.get("status") in ("fail", "warn")]
    fixable = [c for c in failing if c.get("fixable")]

    # Always generate the core package; CHANGES.md explains which scan finding each answers.
    ld, questions = build_jsonld(scan, text, links)
    (fixes / "jsonld.json").write_text(json.dumps(ld, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (fixes / "jsonld.html").write_text(inject_jsonld("", ld), encoding="utf-8")
    llms = build_llms_txt(scan, ld, links)
    (fixes / "llms.txt").write_text(llms, encoding="utf-8")
    existing_robots = (mirror / "robots.txt").read_text(encoding="utf-8", errors="replace") if (mirror / "robots.txt").exists() else ""
    has_sitemap = (mirror / "sitemap.xml").exists()
    robots, added, blocked = patch_robots(existing_robots, f"{origin}/sitemap.xml" if origin else None)
    (fixes / "robots.txt").write_text(robots, encoding="utf-8")
    for b in blocked:
        questions.append(f"Your robots.txt blocks {b} (a user-facing agent). Customers asking that agent about you get nothing. Keep the block?")
    card = build_agent_card(scan, ld, links)
    (fixes / "agent.json").write_text(json.dumps(card, indent=2) + "\n", encoding="utf-8")
    sitemap = None if has_sitemap or not url else build_sitemap(url)
    if sitemap:
        (fixes / "sitemap.xml").write_text(sitemap, encoding="utf-8")

    labels = unlabeled_inputs(html)
    lab_md = ["# Form labels (suggested, owner to confirm)", ""]
    for it in labels:
        ident = it["attrs"].get("id") or it["attrs"].get("name") or it["attrs"].get("placeholder") or f"line {it['line']}"
        lab_md.append(f"- `<{it['tag']}>` `{ident}` (index.html line {it['line']}): "
                      + (f"aria-label=\"{it['suggested']}\"" if it["suggested"] else "no hint on the page; owner to name this field"))
    if not labels:
        lab_md.append("No unlabeled inputs found on the mirrored homepage.")
    (fixes / "form-labels.md").write_text("\n".join(lab_md) + "\n", encoding="utf-8")

    alts = missing_alt_images(html, manifest_assets)
    alt_md = ["# Image alt text (suggested, owner to confirm)", "",
              "Suggestions come from the image file name only. Replace them with a real description.", ""]
    for it in alts:
        alt_md.append(f"- `{manifest_assets.get(it['src'], it['src'])}`: "
                      + (f"\"{it['suggested']}\" (suggested, owner to confirm)" if it["suggested"] else "owner to describe (file name gives no hint)"))
    if not alts:
        alt_md.append("No images without alt text found on the mirrored homepage.")
    (fixes / "alt-text.md").write_text("\n".join(alt_md) + "\n", encoding="utf-8")

    locked_checks = [c for c in failing if c.get("id") == "facts_in_images_or_pdf"]
    locked_status = []
    if locked_checks:
        parts = ["# Facts locked in PDFs or images", ""]
        for c in locked_checks:
            md, st = extract_locked_facts(c, run_dir)
            parts.append(md)
            locked_status.append(st)
        (fixes / "facts-text.md").write_text("\n".join(parts), encoding="utf-8")

    # ---- apply to mirror-fixed
    applied: list[str] = []
    if (mirror / "index.html").exists():
        if fixed.exists():
            shutil.rmtree(fixed)
        shutil.copytree(mirror, fixed)
        fhtml = (fixed / "index.html").read_text(encoding="utf-8", errors="replace")
        fhtml = inject_jsonld(fhtml, ld)
        applied.append("JSON-LD injected into index.html <head>")
        fhtml, linked = link_phone(fhtml, (scan.get("facts") or {}).get("phone") or "")
        if linked:
            applied.append("phone number made a tap-to-call tel: link")
        fhtml, nl = apply_labels(fhtml, labels)
        if nl:
            applied.append(f"aria-label added to {nl} input(s)")
        fhtml, na = apply_alts(fhtml, alts)
        if na:
            applied.append(f"suggested alt added to {na} image(s)")
        (fixed / "index.html").write_text(fhtml, encoding="utf-8")
        (fixed / "llms.txt").write_text(llms, encoding="utf-8")
        (fixed / "robots.txt").write_text(robots, encoding="utf-8")
        if sitemap:
            (fixed / "sitemap.xml").write_text(sitemap, encoding="utf-8")
        (fixed / ".well-known").mkdir(exist_ok=True)
        (fixed / ".well-known" / "agent.json").write_text(json.dumps(card, indent=2) + "\n", encoding="utf-8")
        if (fixes / "facts-text.md").exists():
            shutil.copy(fixes / "facts-text.md", fixed / "facts-text.md")
        applied.append("llms.txt, robots.txt, .well-known/agent.json written to the mirror root"
                       + (", sitemap.xml generated" if sitemap else ""))
    else:
        applied.append("No mirror found; fix files generated but not applied (run landfall.mirror first).")

    # ---- needs-owner
    nq = ["# Questions for the owner", "",
          "We only used facts we found on your website. Answer these and we will add them.", ""]
    nq += [f"{i}. {q}" for i, q in enumerate(questions, 1)]
    if any(it["suggested"] == "" for it in alts):
        nq.append(f"{len(questions) + 1}. Some images need a description from you (see alt-text.md).")
    (fixes / "needs-owner.md").write_text("\n".join(nq) + "\n", encoding="utf-8")

    # ---- CHANGES.md
    desc = {
        "jsonld": ("Added schema.org JSON-LD ({t}) with the business facts from your page.".format(t=ld["@type"]),
                   "fixes/jsonld.html", _hint("jsonld", platform)),
        "llms": ("Wrote llms.txt: a plain summary agents can read without running JavaScript.", "fixes/llms.txt", _hint("rootfile", platform)),
        "robots": ("Patched robots.txt: kept every rule you had, added an Allow group for "
                   + (", ".join(added) if added else "no new agents (all already named)") + ".",
                   "fixes/robots.txt", _hint("rootfile", platform)),
        "sitemap": ("Generated a minimal sitemap.xml listing your homepage." if sitemap else "Sitemap already exists; robots.txt now points to it.",
                    "fixes/sitemap.xml" if sitemap else "fixes/robots.txt", _hint("rootfile", platform)),
        "labels": (f"Suggested labels for {len(labels)} unlabeled form field(s) (suggested, owner to confirm).", "fixes/form-labels.md",
                   "Add each label in your site editor's form settings (field label / placeholder / accessibility name)."),
        "alts": (f"Suggested alt text for {len(alts)} image(s) (suggested, owner to confirm).", "fixes/alt-text.md",
                 "In your site editor, select the image > alt text / image description."),
        "locked": ("Text version of facts found in PDFs/images: "
                   + (", ".join(locked_status) if locked_status else "nothing to extract") + ".",
                   "fixes/facts-text.md", "Publish the text as a normal page section (e.g. an Hours or Menu text block)."),
        "contact": ("Phone (and address, if found) added to the JSON-LD as telephone/PostalAddress; "
                    "the phone number on the page made a tap-to-call link (tel:).",
                    "fixes/jsonld.html", _hint("jsonld", platform) + " For the tap-to-call link, edit the phone text "
                    "in your site editor and link it to tel:<number>."),
        "manual": ("Not fixed automatically; see the detail above.", "-", "-"),
    }
    ch = [f"# What we changed for {scan.get('facts', {}).get('name') or url}", "",
          f"Site: {url}  ", f"Scanned: {scan.get('fetched_at', '?')}  ", f"Platform detected: {platform}", "",
          f"Score before: {scan.get('score', {}).get('passed', '?')}/{scan.get('score', {}).get('total', '?')} checks passed.", "",
          "## Fixes", ""]
    for c in fixable:
        kind = FIX_OF.get(c.get("id"), None) or FIX_OF.get(c.get("fix_id") or "", "manual")
        what, file, where = desc[kind]
        ch += [f"### {c.get('title') or c.get('id')} (`{c.get('id')}`, {c.get('severity', '?')})", "",
               f"- **What was wrong:** {c.get('detail', '')}",
               f"- **Receipt:** {_receipt_link(c.get('receipt') or {})}",
               f"- **What we changed:** {what}",
               f"- **File:** `{file}`",
               f"- **Where to paste:** {where}", ""]
    manual = [c for c in failing if not c.get("fixable")]
    if manual:
        ch += ["## Needs you (not fixable by a file)", ""]
        for c in manual:
            ch.append(f"- **{c.get('title') or c.get('id')}** (`{c.get('id')}`): {c.get('detail', '')} Receipt: {_receipt_link(c.get('receipt') or {})}")
        ch.append("")
    ch += ["## Also included", "",
           "- `fixes/agent.json`: a proposed agent card (what an agent can do here). Proposal only; not a standard yet.",
           "- `fixes/needs-owner.md`: questions only you can answer. We left those facts out rather than guess.", "",
           "## Applied to the local preview (mirror-fixed/)", ""] + [f"- {a}" for a in applied] + [""]
    (fixes / "CHANGES.md").write_text("\n".join(ch), encoding="utf-8")

    return {"fixes": str(fixes), "mirror_fixed": str(fixed) if fixed.exists() else None,
            "fixable_fails": [c["id"] for c in fixable], "applied": applied, "questions": len(questions)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="landfall.fix", description="Generate and apply the fix package for a scanned run.")
    ap.add_argument("run_dir", help="runs/<slug> (must contain scan.json)")
    a = ap.parse_args(argv)
    res = run(a.run_dir)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
