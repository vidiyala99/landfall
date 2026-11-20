"""Static "can AI agents read this website" scan.

Usage: python -m landfall scan <url> --out runs/<slug>

Writes runs/<slug>/scan.json plus receipts under runs/<slug>/receipts/.
Read-only: GET requests only, one homepage render, robots/llms/sitemap, and up to
3 same-site links that look like menu/services/hours pages. Page content is
treated as untrusted data: it is parsed, never executed outside the browser
sandbox, never followed as instructions.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

TIMEOUT = 20.0
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
AGENT_UA = "Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)"

# Bot -> (what it is in owner words, user_facing?)
AI_BOTS = {
    "GPTBot": ("OpenAI's training crawler", False),
    "ClaudeBot": ("Anthropic's training crawler", False),
    "Claude-User": ("Claude fetching pages for a person who asked", True),
    "PerplexityBot": ("Perplexity's search/answer engine", True),
    "Google-Extended": ("Google's AI training (Gemini) opt-out token", False),
    "OAI-SearchBot": ("ChatGPT search", True),
    "Meta-ExternalAgent": ("Meta's AI crawler", False),
}

SEVERITY_WEIGHT = {"high": 3, "med": 2, "low": 1}

LOCAL_BUSINESS_TYPES = {
    "localbusiness", "organization", "bakery", "restaurant", "cafeorcoffeeshop", "foodestablishment",
    "barorpub", "brewery", "winery", "distillery", "fastfoodrestaurant", "icecreamshop", "store",
    "grocerystore", "clothingstore", "bookstore", "florist", "hardwarestore", "petstore", "furniturestore",
    "jewelrystore", "liquorstore", "shoestore", "sportinggoodsstore", "toystore", "homeandconstructionbusiness",
    "plumber", "electrician", "hvacbusiness", "roofingcontractor", "generalcontractor", "locksmith",
    "movingcompany", "housepainter", "automotivebusiness", "autorepair", "autodealer", "autobodyshop",
    "healthandbeautybusiness", "hairsalon", "beautysalon", "nailsalon", "dayspa", "tattooparlor",
    "medicalbusiness", "dentist", "physician", "optician", "pharmacy", "medicalclinic", "veterinarycare",
    "professionalservice", "legalservice", "attorney", "accountingservice", "financialservice",
    "realestateagent", "insuranceagency", "lodgingbusiness", "hotel", "motel", "bedandbreakfast",
    "sportsactivitylocation", "exercisegym", "healthclub", "entertainmentbusiness", "childcare",
    "drycleaningorlaundry", "emergencyservice", "employmentagency", "travelagency", "selfstorage",
    "animalshelter", "library", "educationalorganization", "corporation", "ngo", "onlinestore",
}
BUSINESS_SUFFIXES = ("business", "store", "restaurant", "shop", "salon", "service", "clinic", "agency")
OFFER_TYPES = {"menu", "menuitem", "menusection", "product", "offer", "aggregateoffer", "service",
               "offercatalog", "foodservice"}
OFFER_KEYS = ("hasMenu", "menu", "makesOffer", "hasOfferCatalog", "offers", "hasMenuSection", "hasMenuItem")

PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]\d{4}(?!\d)")
ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+(?:[A-Z0-9][\w.'-]*\s+){1,5}"
    r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Ln|Lane|Way|Ct|Court|Pl|Place|Pkwy|Parkway|"
    r"Hwy|Highway|Sq|Square|Ter|Terrace|Cir|Circle|Pike|Route|Rte)\b\.?[^\n]{0,60}"
)
HOURS_RE = re.compile(
    r"\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?\b[^\n]{0,40}?\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)",
    re.I,
)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PRICE_RE = re.compile(r"[$£€]\s?\d+(?:[.,]\d{2})?")
FACT_LINK_RE = re.compile(r"menu|price|pricing|special|catering|services|rates|order|cake|flavors", re.I)
FACT_FILE_RE = re.compile(r"\.(pdf|jpe?g|png|gif|webp)(?:$|[?#])", re.I)
SUBPAGE_RE = re.compile(r"menu|services|pricing|prices|hours|order|catering|contact|about|visit|location", re.I)

CHALLENGE_MARKERS = (
    "just a moment...", "cf-chl", "challenge-platform", "attention required! | cloudflare",
    "cf-browser-verification", "_incapsula_resource", "px-captcha", "captcha-delivery", "datadome",
    "access denied", "verify you are human", "are you a robot", "g-recaptcha", "h-captcha", "hcaptcha",
)


# ---------------------------------------------------------------- HTML parsing

BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
              "section", "article", "header", "footer", "nav", "main", "aside", "address", "table", "form",
              "dd", "dt", "blockquote", "pre", "hr", "option", "label", "figure", "figcaption"}
SKIP_TAGS = {"script", "style", "template", "svg", "head", "iframe", "object"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Doc(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.jsonld: list[str] = []
        self.links: list[tuple[str, str]] = []  # (href, anchor text)
        self.imgs: list[dict] = []
        self.fields: list[dict] = []
        self.label_for: set[str] = set()
        self.title = ""
        self.meta: dict[str, str] = {}
        self.form_count = 0
        self._skip = 0
        self._in_title = False
        self._jsonld_buf: list[str] | None = None
        self._label_depth = 0
        self._link: list | None = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key:
                self.meta[key] = a.get("content", "")
        if tag == "script" and "ld+json" in a.get("type", "").lower():
            self._jsonld_buf = []
        if tag in SKIP_TAGS and tag not in VOID_TAGS:
            self._skip += 1
        if tag in BLOCK_TAGS:
            self.text_parts.append("\n")
        if tag == "a":
            self._link = [a.get("href", ""), []]
        if tag == "img":
            self.imgs.append(a)
        if tag == "label":
            self._label_depth += 1
            if a.get("for"):
                self.label_for.add(a["for"])
        if tag == "form":
            self.form_count += 1
        if tag in ("input", "select", "textarea"):
            itype = a.get("type", "text").lower() if tag == "input" else tag
            if itype not in ("hidden", "submit", "button", "image", "reset"):
                f = dict(a)
                f["_tag"] = tag
                f["_wrapped"] = self._label_depth > 0
                self.fields.append(f)
        if tag in ("td", "th"):
            self.text_parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._jsonld_buf is not None:
            self.jsonld.append("".join(self._jsonld_buf))
            self._jsonld_buf = None
        if tag in SKIP_TAGS and self._skip > 0:
            self._skip -= 1
        if tag in BLOCK_TAGS:
            self.text_parts.append("\n")
        if tag == "a" and self._link is not None:
            self.links.append((self._link[0], " ".join("".join(self._link[1]).split())))
            self._link = None
        if tag == "label" and self._label_depth > 0:
            self._label_depth -= 1

    def handle_data(self, data):
        if self._jsonld_buf is not None:
            self._jsonld_buf.append(data)
            return
        if self._in_title:
            self.title += data
        if self._skip:
            return
        self.text_parts.append(data)
        if self._link is not None:
            self._link[1].append(data)

    @property
    def text(self) -> str:
        raw = "".join(self.text_parts)
        lines = [" ".join(line.split()) for line in raw.split("\n")]
        return "\n".join(line for line in lines if line)


def parse_html(html: str) -> Doc:
    d = Doc()
    try:
        d.feed(html or "")
        d.close()
    except Exception:  # malformed markup: keep what we got
        pass
    return d


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text or "")


# ---------------------------------------------------------------- robots.txt

def parse_robots(text: str) -> list[dict]:
    """Return groups: [{"agents": [..lower..], "rules": [(kind, path, lineno, line)]}]."""
    groups: list[dict] = []
    cur = None
    last_was_agent = False
    for i, line in enumerate((text or "").splitlines(), 1):
        stripped = line.split("#", 1)[0].strip()
        if not stripped or ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        key, val = key.strip().lower(), val.strip()
        if key == "user-agent":
            if cur is None or not last_was_agent:
                cur = {"agents": [], "rules": [], "agent_lines": []}
                groups.append(cur)
            cur["agents"].append(val.lower())
            cur["agent_lines"].append((i, line.strip()))
            last_was_agent = True
        elif key in ("allow", "disallow"):
            if cur is not None:
                cur["rules"].append((key, val, i, line.strip()))
            last_was_agent = False
        else:
            last_was_agent = False
    return groups


def robots_verdict(text: str, bot: str) -> dict:
    """Is `bot` blocked from the homepage? Uses the most specific matching group (or *)."""
    groups = parse_robots(text)
    b = bot.lower()
    specific = [g for g in groups if any(a and a != "*" and (a in b or b in a) for a in g["agents"])]
    matched = specific or [g for g in groups if "*" in g["agents"]]
    via = "specific" if specific else ("*" if matched else None)
    blocked = False
    lines: list[str] = []
    for g in matched:
        disallow_root = [r for r in g["rules"] if r[0] == "disallow" and r[1] == "/"]
        allow_root = [r for r in g["rules"] if r[0] == "allow" and r[1] in ("/", "/$")]
        if disallow_root and not allow_root:
            blocked = True
            for ln, txt in g["agent_lines"]:
                lines.append(f"line {ln}: {txt}")
            for r in disallow_root:
                lines.append(f"line {r[2]}: {r[3]}")
    return {"bot": bot, "blocked": blocked, "via": via, "lines": lines}


# ---------------------------------------------------------------- JSON-LD

def _type_names(entity: dict) -> list[str]:
    t = entity.get("@type")
    ts = t if isinstance(t, list) else [t]
    out = []
    for x in ts:
        if isinstance(x, str):
            out.append(re.split(r"[/:#]", x)[-1].lower())
    return out


def jsonld_entities(blocks: list[str]) -> list[dict]:
    """Every dict with an @type anywhere in the JSON-LD blocks (handles @graph, lists, nesting)."""
    found: list[dict] = []

    def walk(node, depth=0):
        if depth > 12:
            return
        if isinstance(node, dict):
            if "@type" in node:
                found.append(node)
            for v in node.values():
                walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node:
                walk(v, depth + 1)

    for raw in blocks:
        raw = (raw or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw, strict=False)
        except ValueError:
            # common breakage: trailing commas or HTML comments around the JSON
            cleaned = re.sub(r",\s*([}\]])", r"\1", raw.replace("<!--", "").replace("-->", ""))
            try:
                data = json.loads(cleaned, strict=False)
            except ValueError:
                continue
        walk(data)
    return found


def is_business(entity: dict) -> bool:
    for t in _type_names(entity):
        if t in LOCAL_BUSINESS_TYPES or t.endswith(BUSINESS_SUFFIXES) and t not in ("service",):
            return True
    return False


def _address_str(addr) -> str | None:
    if isinstance(addr, list) and addr:
        addr = addr[0]
    if isinstance(addr, str):
        return addr.strip() or None
    if isinstance(addr, dict):
        parts = [addr.get(k) for k in ("streetAddress", "addressLocality", "addressRegion", "postalCode")]
        s = ", ".join(str(p).strip() for p in parts if p)
        return s or None
    return None


def business_fields(entity: dict) -> dict:
    addr = entity.get("address")
    if not addr and isinstance(entity.get("location"), dict):
        addr = entity["location"].get("address")
    return {
        "name": entity.get("name") if isinstance(entity.get("name"), str) else None,
        "address": _address_str(addr),
        "telephone": entity.get("telephone") if isinstance(entity.get("telephone"), str) else None,
    }


def best_business(entities: list[dict]) -> dict | None:
    biz = [e for e in entities if is_business(e)]
    if not biz:
        return None

    def rank(e):
        f = business_fields(e)
        local = any(t != "organization" for t in _type_names(e))
        return (sum(1 for v in f.values() if v), local)

    return max(biz, key=rank)


def _has_price(node, depth=0) -> bool:
    if depth > 10:
        return False
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("price", "lowPrice", "highPrice") and v not in (None, ""):
                return True
            if k == "priceSpecification" and v:
                return True
            if _has_price(v, depth + 1):
                return True
    elif isinstance(node, list):
        return any(_has_price(v, depth + 1) for v in node)
    return False


# ---------------------------------------------------------------- facts

def _norm_digits(s: str) -> str:
    d = re.sub(r"\D", "", s)
    return d[-10:]


def find_phone(text: str) -> str | None:
    m = PHONE_RE.search(text or "")
    return m.group(0).strip() if m else None


def find_address(text: str) -> str | None:
    m = ADDRESS_RE.search(text or "")
    return m.group(0).strip() if m else None


def find_hours(text: str) -> str | None:
    lines = [ln for ln in (text or "").split("\n") if HOURS_RE.search(ln)]
    return " | ".join(ln.strip()[:120] for ln in lines[:7]) or None


def offer_snippets(text: str, limit: int = 10) -> list[str]:
    out = []
    for ln in (text or "").split("\n"):
        if PRICE_RE.search(ln) and len(ln) < 300:
            s = ln.strip()[:120]
            if s not in out:
                out.append(s)
        if len(out) >= limit:
            break
    return out


def extract_facts(rendered_text: str, entities: list[dict], doc: Doc | None = None) -> dict:
    biz = best_business(entities)
    bf = business_fields(biz) if biz else {"name": None, "address": None, "telephone": None}
    name = bf["name"]
    if not name and doc is not None:
        name = doc.meta.get("og:site_name") or (doc.title.split("|")[0].split(" - ")[0].strip() or None)
    phone = bf["telephone"] or find_phone(rendered_text)
    if not phone and doc is not None:
        tel = [h for h, _ in doc.links if h.lower().startswith("tel:")]
        phone = tel[0][4:].strip() if tel else None
    hours = None
    if biz:
        oh = biz.get("openingHours")
        if oh:
            hours = " | ".join(oh) if isinstance(oh, list) else str(oh)
    hours = hours or find_hours(rendered_text)
    return {
        "name": name,
        "phone": phone,
        "address": bf["address"] or find_address(rendered_text),
        "hours_text": hours,
        "offer_snippets": offer_snippets(rendered_text),
    }


# ---------------------------------------------------------------- check helpers

def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _clip(s, n=300):
    if s is None:
        return None
    s = str(s)
    return s if len(s) <= n else s[: n - 3] + "..."


def check(cid, title, status, severity, detail, receipt, fixable, fix_id):
    return {
        "id": cid, "title": title, "status": status, "severity": severity, "detail": detail,
        "receipt": {
            "kind": receipt.get("kind", "html"),
            "path": receipt.get("path"),
            "excerpt": _clip(receipt.get("excerpt")),
            "url": receipt.get("url", ""),
        },
        "fixable": fixable, "fix_id": fix_id if fixable else None,
    }


def score(checks: list[dict]) -> dict:
    total_w = 0.0
    got = 0.0
    for c in checks:
        w = SEVERITY_WEIGHT[c["severity"]]
        total_w += w
        if c["status"] == "pass":
            got += w
        elif c["status"] == "warn":
            got += w / 2
    read = round(100 * got / total_w) if total_w else 0
    return {"read": int(read), "passed": sum(1 for c in checks if c["status"] == "pass"), "total": len(checks)}


def validate(scan: dict) -> None:
    """Core rule: no finding without a receipt."""
    for c in scan["checks"]:
        if c["status"] not in ("pass", "fail", "warn"):
            raise ValueError(f"{c['id']}: bad status {c['status']}")
        if c["severity"] not in SEVERITY_WEIGHT:
            raise ValueError(f"{c['id']}: bad severity")
        r = c["receipt"]
        if c["status"] == "fail" and not (r.get("path") or r.get("excerpt")):
            raise ValueError(f"{c['id']}: fail without a receipt")


# ---------------------------------------------------------------- checks

def check_robots(robots: dict, base: str) -> dict:
    url = urljoin(base, "/robots.txt")
    rec = {"kind": "file", "path": "receipts/robots.txt" if robots.get("saved") else None, "url": url}
    if robots.get("status") != 200:
        rec["kind"] = "http"
        rec["excerpt"] = f"GET /robots.txt -> HTTP {robots.get('status')}"
        return check("robots_ai", "AI assistants are allowed to read the site", "pass", "high",
                     f"No robots.txt (HTTP {robots.get('status')}), so no AI agent is blocked.", rec, False, None)
    text = robots.get("text", "")
    verdicts = [robots_verdict(text, b) for b in AI_BOTS]
    blocked = [v for v in verdicts if v["blocked"]]
    user_blocked = [v for v in blocked if AI_BOTS[v["bot"]][1]]
    rec["excerpt"] = "; ".join(f"{v['bot']}: {' / '.join(v['lines'])}" for v in blocked) or None
    if user_blocked:
        parts = [f"{v['lines'][-1]} for {v['bot']} blocks {AI_BOTS[v['bot']][0]}" for v in user_blocked]
        return check("robots_ai", "AI assistants are allowed to read the site", "fail", "high",
                     "robots.txt " + "; ".join(parts) + ". People asking an AI assistant about this business "
                     "will get no answer from the site.", rec, True, "robots_patch")
    if blocked:
        names = ", ".join(v["bot"] for v in blocked)
        return check("robots_ai", "AI assistants are allowed to read the site", "warn", "high",
                     f"robots.txt blocks AI training crawlers ({names}) but not assistants acting for a person. "
                     f"That is a legitimate choice; it can reduce how often AI tools know the business.",
                     rec, True, "robots_patch")
    rec["excerpt"] = rec.get("excerpt") or _clip(text, 200)
    return check("robots_ai", "AI assistants are allowed to read the site", "pass", "high",
                 "robots.txt does not block any of the 7 AI agents checked.", rec, False, None)


def check_llms(llms: dict, base: str) -> dict:
    url = urljoin(base, "/llms.txt")
    body = (llms.get("text") or "").lstrip()
    ok = llms.get("status") == 200 and body and not body.startswith("<") and "html" not in llms.get("ctype", "")
    rec = {"kind": "http", "path": "receipts/llms.txt" if ok else None, "url": url,
           "excerpt": _clip(body, 200) if ok else f"GET /llms.txt -> HTTP {llms.get('status')}"
           + (" (an HTML page, not a text file)" if llms.get("status") == 200 else "")}
    if ok:
        return check("llms_txt", "Has an llms.txt guide for AI agents", "pass", "low",
                     "/llms.txt exists and is plain text.", rec, False, None)
    return check("llms_txt", "Has an llms.txt guide for AI agents", "fail", "low",
                 f"No /llms.txt (HTTP {llms.get('status')}). This short text file tells AI agents what the "
                 f"business is and where the key facts live.", rec, True, "llms_txt")


def check_jsonld_business(entities: list[dict], url: str, n_blocks: int) -> dict:
    biz = best_business(entities)
    rec = {"kind": "html", "path": "receipts/rendered.html", "url": url}
    title = "Business name, address and phone are machine-readable (schema.org)"
    if not biz:
        types = sorted({t for e in entities for t in _type_names(e)})
        rec["excerpt"] = (f"{n_blocks} JSON-LD block(s); types found: {', '.join(types)}" if n_blocks
                          else "No <script type=\"application/ld+json\"> on the page")
        return check("jsonld_business", title, "fail", "high",
                     "No schema.org LocalBusiness (or Organization) data. Agents have to guess the business "
                     "name, address and phone from page text.", rec, True, "jsonld_business")
    f = business_fields(biz)
    rec["excerpt"] = json.dumps({"@type": biz.get("@type"), **f})
    missing = [k for k, v in f.items() if not v]
    if missing:
        return check("jsonld_business", title, "warn", "high",
                     f"schema.org {'/'.join(_type_names(biz))} found but missing: {', '.join(missing)}.",
                     rec, True, "jsonld_business")
    return check("jsonld_business", title, "pass", "high",
                 f"schema.org {'/'.join(_type_names(biz))} has name, address and telephone.", rec, False, None)


def check_jsonld_hours(entities: list[dict], url: str) -> dict:
    rec = {"kind": "html", "path": "receipts/rendered.html", "url": url}
    title = "Opening hours are machine-readable"
    for e in entities:
        for k in ("openingHours", "openingHoursSpecification"):
            if e.get(k):
                rec["excerpt"] = json.dumps({k: e[k]})
                return check("jsonld_hours", title, "pass", "med", f"schema.org {k} is present.", rec, False, None)
    rec["excerpt"] = "No openingHours or openingHoursSpecification in any JSON-LD on the page"
    return check("jsonld_hours", title, "fail", "med",
                 "Hours are not in structured data, so an agent asked \"are they open Saturday?\" has to guess.",
                 rec, True, "jsonld_hours")


def check_jsonld_offers(entities: list[dict], url: str) -> dict:
    rec = {"kind": "html", "path": "receipts/rendered.html", "url": url}
    title = "Menu, products or services (with prices) are machine-readable"
    offers = [e for e in entities if set(_type_names(e)) & OFFER_TYPES or any(e.get(k) for k in OFFER_KEYS)]
    if not offers:
        rec["excerpt"] = "No Menu, Product, Offer or Service entities (or hasMenu/makesOffer) in JSON-LD"
        return check("jsonld_offers", title, "fail", "med",
                     "What the business sells is not in structured data; agents cannot compare or quote prices.",
                     rec, True, "jsonld_offers")
    priced = [e for e in offers if _has_price(e)]
    names = sorted({t for e in offers for t in _type_names(e)})
    if priced:
        rec["excerpt"] = _clip(json.dumps(priced[0]), 300)
        return check("jsonld_offers", title, "pass", "med",
                     f"Structured offers found ({', '.join(names)}) with prices.", rec, False, None)
    menu_link = next((e.get("hasMenu") or e.get("menu") for e in offers if isinstance(e.get("hasMenu") or e.get("menu"), str)), None)
    rec["excerpt"] = _clip(json.dumps(offers[0]), 300)
    return check("jsonld_offers", title, "warn", "med",
                 f"Structured offers found ({', '.join(names)}) but no prices"
                 + (f"; hasMenu only points to {menu_link}" if menu_link else "") + ".",
                 rec, True, "jsonld_offers")


def check_nojs(raw_text: str, rendered_text: str, url: str, render_error: str | None,
               raw_challenged: str | None = None) -> dict:
    title = "Key information is visible without JavaScript"
    rw, rd = len(words(raw_text)), len(words(rendered_text))
    if render_error:
        rec = {"kind": "html", "path": "receipts/raw.html", "url": url,
               "excerpt": f"Render failed: {render_error}"}
        return check("nojs_content", title, "warn", "high",
                     f"Could not render the page in a browser ({_clip(render_error, 120)}); compared nothing.",
                     rec, False, None)
    ratio = rw / rd if rd else 1.0
    js_only = []
    rp = find_phone(rendered_text)
    if rp and _norm_digits(rp) not in re.sub(r"\D", "", raw_text):
        js_only.append(f"phone {rp}")
    ra = find_address(rendered_text)
    if ra and ra[:20] not in raw_text:
        js_only.append(f"address '{ra[:60]}'")
    rh = HOURS_RE.search(rendered_text or "")
    if rh and not HOURS_RE.search(raw_text or ""):
        js_only.append(f"hours '{rh.group(0)[:60]}'")
    excerpt = (f"raw HTML text: {rw} words; rendered page text: {rd} words (ratio {ratio:.0%})."
               + (f" Only after JavaScript: {', '.join(js_only)}." if js_only else "")
               + f" Raw starts: {' '.join(raw_text.split())[:120]!r}")
    rec = {"kind": "html", "path": "receipts/raw.html", "url": url, "excerpt": excerpt}
    if raw_challenged and (ratio < 0.3 or js_only):
        return check("nojs_content", title, "warn", "high",
                     f"The plain HTML request got a bot challenge ({raw_challenged}), so an agent without a full "
                     f"browser sees only {ratio:.0%} of the page text ({rw} of {rd} words). The cause is the bot wall "
                     f"(see bot_challenge), so whether the content itself needs JavaScript could not be measured.",
                     rec, False, None)
    if ratio < 0.3 or js_only:
        why = []
        if ratio < 0.3:
            why.append(f"without JavaScript the page shows only {ratio:.0%} of its text ({rw} of {rd} words)")
        if js_only:
            why.append(f"{', '.join(js_only)} appear only after JavaScript runs")
        return check("nojs_content", title, "fail", "high",
                     _cap("; ".join(why)) + ". Many AI agents read the raw HTML and never run JavaScript.",
                     rec, True, "static_facts")
    return check("nojs_content", title, "pass", "high",
                 f"Raw HTML carries {ratio:.0%} of the rendered text ({rw} of {rd} words); key facts are present "
                 f"without JavaScript.", rec, False, None)


def classify_response(resp: dict) -> str | None:
    """Return a reason string if the response looks like a block/challenge, else None."""
    if resp.get("error"):
        return f"request failed: {resp['error']}"
    status = resp.get("status") or 0
    headers = {k.lower(): v for k, v in (resp.get("headers") or {}).items()}
    body = (resp.get("text") or "")[:60000].lower()
    if headers.get("cf-mitigated", "").lower() == "challenge":
        return f"HTTP {status} with cf-mitigated: challenge (Cloudflare bot challenge)"
    if status in (403, 429, 503):
        marker = next((m for m in CHALLENGE_MARKERS if m in body), None)
        return f"HTTP {status}" + (f" with challenge page marker '{marker}'" if marker else "")
    if status >= 400:
        return f"HTTP {status}"
    small = len(resp.get("text") or "") < 15000
    strong = ("just a moment...", "cf-chl", "challenge-platform", "_incapsula_resource", "px-captcha",
              "captcha-delivery", "verify you are human", "cf-browser-verification")
    marker = next((m for m in strong if m in body), None)
    if marker and small:
        return f"HTTP {status} but the body is a challenge page (marker '{marker}')"
    return None


def check_bot(agent_resp: dict, browser_resp: dict, url: str, rendered_ok: bool = False) -> dict:
    title = "AI agents are not blocked by a bot wall"
    a, b = classify_response(agent_resp), classify_response(browser_resp)
    excerpt = (f"ClaudeBot UA -> HTTP {agent_resp.get('status')}" + (f" ({a})" if a else "")
               + f"; Chrome UA -> HTTP {browser_resp.get('status')}" + (f" ({b})" if b else ""))
    rec = {"kind": "http", "path": "receipts/headers.json", "url": url, "excerpt": excerpt}
    if a and b:
        return check("bot_challenge", title, "fail", "high",
                     f"Both an AI-agent request and a plain browser-like request are blocked or challenged ({a})"
                     + ("; only a full browser running JavaScript got through. Agents that fetch pages directly "
                        "cannot read the site." if rendered_ok else ". Agents cannot read the site at all."),
                     rec, False, None)
    if a:
        return check("bot_challenge", title, "fail", "high",
                     f"A request identifying as an AI agent is blocked ({a}) while a normal browser gets in. "
                     f"Assistants acting for customers are turned away.", rec, False, None)
    if b:
        return check("bot_challenge", title, "warn", "high",
                     f"The browser-like request was challenged ({b}) but the agent one was not.", rec, False, None)
    return check("bot_challenge", title, "pass", "high",
                 "An AI-agent request and a normal browser request both get the page.", rec, False, None)


def _field_label(f: dict, label_for: set[str]) -> str:
    if f.get("aria-label", "").strip() or f.get("aria-labelledby") or f.get("title", "").strip():
        return "label"
    if f.get("_wrapped") or (f.get("id") and f["id"] in label_for):
        return "label"
    if f.get("placeholder", "").strip():
        return "placeholder"
    return "none"


def check_forms(doc: Doc, url: str) -> dict:
    title = "Form fields are labeled so agents know what to type"
    if not doc.fields:
        rec = {"kind": "html", "path": "receipts/rendered.html", "url": url,
               "excerpt": f"{doc.form_count} form(s), 0 fillable fields on the homepage"}
        return check("form_labels", title, "pass", "med", "No form fields on the homepage to label.", rec, False, None)
    kinds = [(_field_label(f, doc.label_for), f) for f in doc.fields]
    none = [f for k, f in kinds if k == "none"]
    ph = [f for k, f in kinds if k == "placeholder"]

    def desc(f):
        return f"<{f['_tag']} name='{f.get('name', '')}' type='{f.get('type', '')}'>"

    rec = {"kind": "html", "path": "receipts/rendered.html", "url": url,
           "excerpt": f"{len(doc.fields)} fields; unlabeled: " + (", ".join(desc(f) for f in none[:5]) or "none")
           + (f"; placeholder-only: {', '.join(desc(f) for f in ph[:3])}" if ph else "")}
    if none:
        return check("form_labels", title, "fail", "med",
                     f"{len(none)} of {len(doc.fields)} form fields have no label, aria-label or placeholder "
                     f"(e.g. {desc(none[0])}). An agent filling the form has to guess.", rec, True, "form_labels")
    if ph:
        return check("form_labels", title, "warn", "med",
                     f"{len(ph)} of {len(doc.fields)} fields rely on placeholder text instead of a real label.",
                     rec, True, "form_labels")
    return check("form_labels", title, "pass", "med", f"All {len(doc.fields)} form fields are labeled.",
                 rec, False, None)


def _meaningful_img(i: dict) -> bool:
    if i.get("role") == "presentation" or i.get("aria-hidden") == "true":
        return False
    for dim in ("width", "height"):
        v = re.sub(r"\D", "", i.get(dim, "") or "")
        if v and int(v) <= 2:
            return False
    src = i.get("src", "") or i.get("data-src", "")
    if not src or src.startswith("data:image/gif") or "pixel" in src.lower() or "spacer" in src.lower():
        return False
    return True


def check_img_alt(doc: Doc, url: str) -> dict:
    title = "Images have text descriptions (alt text)"
    imgs = [i for i in doc.imgs if _meaningful_img(i)]
    rec = {"kind": "html", "path": "receipts/rendered.html", "url": url}
    if not imgs:
        rec["excerpt"] = "No meaningful <img> elements on the homepage"
        return check("img_alt", title, "pass", "low", "No content images to describe.", rec, False, None)
    missing = [i for i in imgs if "alt" not in i]
    factual = [i for i in missing if FACT_LINK_RE.search((i.get("src", "") + " " + i.get("class", "")))]
    share = len(missing) / len(imgs)
    rec["excerpt"] = (f"{len(missing)} of {len(imgs)} images lack alt. Examples: "
                      + ", ".join(urljoin(url, i.get("src", ""))[-80:] for i in (factual or missing)[:3]))
    if factual:
        return check("img_alt", title, "fail", "low",
                     f"{len(factual)} menu/price image(s) have no alt text (e.g. {urljoin(url, factual[0].get('src', ''))}"
                     f"); the facts in them are invisible to agents.", rec, True, "img_alt")
    if share > 0.5:
        return check("img_alt", title, "fail", "low",
                     f"{len(missing)} of {len(imgs)} images ({share:.0%}) have no alt text.", rec, True, "img_alt")
    if share > 0.2:
        return check("img_alt", title, "warn", "low",
                     f"{len(missing)} of {len(imgs)} images ({share:.0%}) have no alt text.", rec, True, "img_alt")
    return check("img_alt", title, "pass", "low",
                 f"{len(imgs) - len(missing)} of {len(imgs)} images have alt text.", rec, False, None)


def check_contact(doc: Doc, text: str, url: str) -> dict:
    title = "Phone, address and email are easy for agents to pick up"
    tel = [h for h, _ in doc.links if h.lower().startswith("tel:")]
    mail = [h for h, _ in doc.links if h.lower().startswith("mailto:")]
    phone = find_phone(text)
    addr = find_address(text)
    email = mail[0][7:].split("?")[0] if mail else (EMAIL_RE.search(text).group(0) if EMAIL_RE.search(text) else None)
    got = []
    got.append(f"tel: link {tel[0]}" if tel else (f"phone in text {phone} (no tel: link)" if phone else "no phone"))
    got.append(f"address '{addr[:60]}'" if addr else "no street address in text")
    got.append(f"email {email}" if email else "no email")
    rec = {"kind": "html", "path": "receipts/rendered.html", "url": url, "excerpt": "; ".join(got)}
    if not (tel or phone or email):
        return check("contact_machine_readable", title, "fail", "med",
                     "No phone number or email anywhere on the homepage.", rec, True, "contact_links")
    if tel and (addr or email):
        return check("contact_machine_readable", title, "pass", "med", "; ".join(got) + ".", rec, False, None)
    return check("contact_machine_readable", title, "warn", "med", "; ".join(got) + ".", rec, True, "contact_links")


def check_sitemap(sm: dict, robots_text: str, base: str) -> dict:
    title = "Has a sitemap so agents can find every page"
    url = urljoin(base, "/sitemap.xml")
    body = (sm.get("text") or "")[:5000].lower()
    ok = sm.get("status") == 200 and ("<urlset" in body or "<sitemapindex" in body)
    declared = [ln.strip() for ln in (robots_text or "").splitlines() if ln.lower().startswith("sitemap:")]
    rec = {"kind": "http", "path": None, "url": url,
           "excerpt": f"GET /sitemap.xml -> HTTP {sm.get('status')}"
           + (" (valid XML sitemap)" if ok else "") + (f"; robots.txt declares {declared[0]}" if declared else "")}
    if ok or declared:
        return check("sitemap", title, "pass", "low",
                     "Sitemap found" + (" at /sitemap.xml" if ok else f" via robots.txt ({declared[0]})") + ".",
                     rec, False, None)
    return check("sitemap", title, "fail", "low",
                 f"No /sitemap.xml (HTTP {sm.get('status')}) and none declared in robots.txt.", rec, True, "sitemap")


def check_facts_in_files(links: list[tuple[str, str]], base: str) -> dict:
    title = "Menu and prices are not locked inside PDFs or pictures"
    host = urlparse(base).netloc
    hits = []
    for href, text in links:
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        absu = urljoin(base, href)
        if FACT_FILE_RE.search(absu) and (FACT_LINK_RE.search(absu) or FACT_LINK_RE.search(text or "")):
            if absu not in hits:
                hits.append(absu)
    rec = {"kind": "html", "path": "receipts/raw.html", "url": base,
           "excerpt": ("Linked files: " + ", ".join(hits[:4])) if hits else f"No menu/price links to PDF or image files ({host})"}
    if hits:
        return check("facts_in_images_or_pdf", title, "fail", "med",
                     f"{len(hits)} menu/price link(s) go to PDF or image files (e.g. {hits[0]}). Many agents cannot "
                     f"read those, so they cannot tell customers what is offered or what it costs.",
                     rec, True, "facts_text")
    return check("facts_in_images_or_pdf", title, "pass", "med",
                 "Menu/price links point to web pages, not PDFs or pictures.", rec, False, None)


# ---------------------------------------------------------------- analysis (pure)

def analyze(data: dict) -> dict:
    """Run all checks from collected data. Pure function: no network. Used by tests with fixtures.

    data keys: url, slug, raw_html, rendered_html, rendered_text (optional), render_error, robots{status,text,saved},
    llms{status,text,ctype}, sitemap{status,text}, agent_resp, browser_resp, extra_pages[{url, html}]
    """
    url = data["url"]
    raw_doc = parse_html(data.get("raw_html", ""))
    rendered_html = data.get("rendered_html") or data.get("raw_html", "")
    ren_doc = parse_html(rendered_html)
    rendered_text = data.get("rendered_text") or ren_doc.text
    extra_docs = [parse_html(p.get("html", "")) for p in data.get("extra_pages", [])]

    blocks = ren_doc.jsonld or raw_doc.jsonld
    entities = jsonld_entities(blocks)
    all_entities = entities + [e for d in extra_docs for e in jsonld_entities(d.jsonld)]
    links = ren_doc.links + raw_doc.links + [l for d in extra_docs for l in d.links]
    robots = data.get("robots", {})

    checks = [
        check_robots(robots, url),
        check_llms(data.get("llms", {}), url),
        check_jsonld_business(all_entities, url, len(blocks)),
        check_jsonld_hours(all_entities, url),
        check_jsonld_offers(all_entities, url),
        check_nojs(raw_doc.text, rendered_text, url, data.get("render_error"),
                   classify_response(data.get("browser_resp", {})) if data.get("browser_resp") else None),
        check_bot(data.get("agent_resp", {}), data.get("browser_resp", {}), url,
                  rendered_ok=bool(data.get("rendered_html")) and not data.get("render_error")),
        check_forms(ren_doc, url),
        check_img_alt(ren_doc, url),
        check_contact(ren_doc, rendered_text, url),
        check_sitemap(data.get("sitemap", {}), robots.get("text", "") if robots.get("status") == 200 else "", url),
        check_facts_in_files(links, url),
    ]
    extra_text = "\n".join(d.text for d in extra_docs)
    facts = extract_facts(rendered_text + "\n" + extra_text, all_entities, ren_doc)
    result = {
        "url": url,
        "slug": data.get("slug", ""),
        "fetched_at": data.get("fetched_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checks": checks,
        "score": score(checks),
        "facts": facts,
    }
    validate(result)
    return result


# ---------------------------------------------------------------- collection (network)

def http_get(client, url: str, ua: str) -> dict:
    try:
        r = client.get(url, headers={"User-Agent": ua, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                                     "Accept-Language": "en-US,en;q=0.9"})
        return {"status": r.status_code, "headers": dict(r.headers), "text": r.text, "final_url": str(r.url),
                "ctype": r.headers.get("content-type", "")}
    except Exception as e:  # network errors become data, not crashes
        return {"status": None, "headers": {}, "text": "", "final_url": url, "ctype": "", "error": f"{type(e).__name__}: {e}"}


def render(url: str, out_dir: Path) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        return {"error": f"playwright not installed: {e}"}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(user_agent=BROWSER_UA, viewport={"width": 1280, "height": 900})
                page.goto(url, wait_until="domcontentloaded", timeout=int(TIMEOUT * 1000))
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                html = page.content()
                text = page.inner_text("body")
                try:
                    page.screenshot(path=str(out_dir / "rendered.png"), full_page=True, timeout=15000)
                except Exception:
                    page.screenshot(path=str(out_dir / "rendered.png"), timeout=15000)
                return {"html": html, "text": text}
            finally:
                browser.close()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"}


def pick_subpages(doc: Doc, base: str, limit: int = 3) -> list[str]:
    host = urlparse(base).netloc
    out: list[str] = []
    for href, text in doc.links:
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absu = urljoin(base, href).split("#")[0]
        pu = urlparse(absu)
        if pu.scheme not in ("http", "https") or pu.netloc != host or FACT_FILE_RE.search(absu):
            continue
        if absu.rstrip("/") == base.rstrip("/"):
            continue
        if SUBPAGE_RE.search(pu.path) or SUBPAGE_RE.search(text or ""):
            if absu not in out:
                out.append(absu)
        if len(out) >= limit:
            break
    return out


def collect(url: str, out: Path, slug: str) -> dict:
    import httpx

    rec_dir = out / "receipts"
    rec_dir.mkdir(parents=True, exist_ok=True)
    data: dict = {"url": url, "slug": slug,
                  "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        browser_resp = http_get(client, url, BROWSER_UA)
        agent_resp = http_get(client, url, AGENT_UA)
        base = browser_resp.get("final_url") or url
        robots = http_get(client, urljoin(base, "/robots.txt"), BROWSER_UA)
        llms = http_get(client, urljoin(base, "/llms.txt"), BROWSER_UA)
        sitemap = http_get(client, urljoin(base, "/sitemap.xml"), BROWSER_UA)
        raw_doc = parse_html(browser_resp.get("text", ""))
        extra = []
        for i, sub in enumerate(pick_subpages(raw_doc, base), 1):
            r = http_get(client, sub, BROWSER_UA)
            if r.get("status") == 200 and "html" in r.get("ctype", ""):
                (rec_dir / f"page{i}.html").write_text(r["text"], encoding="utf-8")
                extra.append({"url": sub, "html": r["text"], "path": f"receipts/page{i}.html"})

    (rec_dir / "raw.html").write_text(browser_resp.get("text", ""), encoding="utf-8")
    robots_saved = robots.get("status") == 200
    if robots_saved:
        (rec_dir / "robots.txt").write_text(robots["text"], encoding="utf-8")
    if llms.get("status") == 200 and not (llms.get("text") or "").lstrip().startswith("<"):
        (rec_dir / "llms.txt").write_text(llms["text"], encoding="utf-8")

    def meta(r):
        return {"status": r.get("status"), "final_url": r.get("final_url"), "headers": r.get("headers"),
                "error": r.get("error"), "body_start": (r.get("text") or "")[:300]}

    (rec_dir / "headers.json").write_text(json.dumps({
        "browser_ua": BROWSER_UA, "agent_ua": AGENT_UA,
        "homepage_browser": meta(browser_resp), "homepage_agent": meta(agent_resp),
        "robots": {"status": robots.get("status")}, "llms": {"status": llms.get("status")},
        "sitemap": {"status": sitemap.get("status")},
        "subpages": [p["url"] for p in extra],
    }, indent=2), encoding="utf-8")

    r = render(base, rec_dir)
    if r.get("error"):
        data["render_error"] = r["error"]
        (rec_dir / "rendered.html").write_text(browser_resp.get("text", ""), encoding="utf-8")
    else:
        (rec_dir / "rendered.html").write_text(r["html"], encoding="utf-8")
        data["rendered_html"] = r["html"]
        data["rendered_text"] = r["text"]

    data.update({
        "url": url, "raw_html": browser_resp.get("text", ""),
        "robots": {"status": robots.get("status"), "text": robots.get("text", ""), "saved": robots_saved},
        "llms": {"status": llms.get("status"), "text": llms.get("text", ""), "ctype": llms.get("ctype", "")},
        "sitemap": {"status": sitemap.get("status"), "text": sitemap.get("text", "")},
        "agent_resp": agent_resp, "browser_resp": browser_resp, "extra_pages": extra,
    })
    return data


def slug_for(url: str) -> str:
    host = urlparse(url if "://" in url else "https://" + url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return re.sub(r"[^a-z0-9]+", "-", host).strip("-") or "site"


def run_scan(url: str, out: str | Path | None = None) -> dict:
    if "://" not in url:
        url = "https://" + url
    out = Path(out) if out else Path("runs") / slug_for(url)
    slug = out.name
    out.mkdir(parents=True, exist_ok=True)
    data = collect(url, out, slug)
    result = analyze(data)
    (out / "scan.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def summarize(result: dict) -> str:
    s = result["score"]
    lines = [f"{result['url']}  read score {s['read']}/100  ({s['passed']}/{s['total']} passed)"]
    for c in result["checks"]:
        lines.append(f"  [{c['status'].upper():4}] {c['severity']:4} {c['id']}: {c['detail'][:140]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="landfall scan", description="Static AI-agent readability scan")
    ap.add_argument("url")
    ap.add_argument("--out", help="run directory (default runs/<slug>)")
    args = ap.parse_args(argv)
    result = run_scan(args.url, args.out)
    try:
        print(summarize(result))
    except UnicodeEncodeError:
        print(summarize(result).encode("ascii", "replace").decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
