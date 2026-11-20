"""Digital worker: list my products for AI assistants.

Many shop platforms (Floranext/Magento, Knockout `data-bind="text: price"`) send product names in the HTML
but fill in prices by script. Assistants that read the raw page see "price not displayed". This module
renders the shop in a real browser (GET only), reads the product cards a shopper would see, and writes them
out as schema.org JSON-LD, a plain list for llms.txt, and a static HTML page.

Never invent: a product is listed only if its name AND price were both seen on the rendered page.

Usage: python -m landfall.products <url> --out runs/<slug>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

PRICE_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
SKIP = {"script", "style", "noscript", "template", "svg"}
CATEGORY_WORDS = ("sympathy", "birthday", "anniversary", "love", "romance", "best-sellers", "bestsellers",
                  "occasion", "flowers", "bouquet", "arrangement", "shop", "collection", "category", "products",
                  "menu", "plants", "gifts", "get-well", "new-baby", "thank")
NOT_CATEGORY_RE = re.compile(r"(cart|checkout|account|customer|login|wishlist|compare|contact|about|"
                             r"privacy|terms|policy|blog)", re.I)
BOT_WALL_RE = re.compile(r"(just a moment|verify you are human|attention required|access denied|captcha|"
                         r"checking your browser|are you a robot)", re.I)


# --------------------------------------------------------------------------- tiny DOM
class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.children, self.parent = tag, attrs, [], parent

    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def text(self) -> str:
        out: list[str] = []
        stack = [self]
        while stack:
            n = stack.pop()
            if isinstance(n, str):
                out.append(n)
            elif n.tag not in SKIP:
                stack.extend(reversed(n.children))
        return re.sub(r"\s+", " ", " ".join(out)).strip()

    def iter(self):
        stack = [self]
        while stack:
            n = stack.pop()
            if isinstance(n, Node):
                yield n
                if n.tag not in SKIP:
                    stack.extend(reversed(n.children))

    def find(self, pred):
        for n in self.iter():
            if n is not self and pred(n):
                return n
        return None


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, {k: (v or "") for k, v in attrs}, self.cur)
        self.cur.children.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, {k: (v or "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        if data.strip():
            self.cur.children.append(data)


def _dom(html: str) -> Node:
    b = _Builder()
    b.feed(html or "")
    b.close()
    return b.root


# --------------------------------------------------------------------------- parsing
def _price(s: str) -> str | None:
    m = PRICE_RE.search(s or "")
    return f"${m.group(1)}" if m else None


def _img(card: Node, base: str) -> str | None:
    im = card.find(lambda n: n.tag == "img")
    if not im:
        return None
    src = im.attrs.get("src") or im.attrs.get("data-src") or ""
    if not src or src.startswith("data:"):
        return None
    return urljoin(base, src)


def _clean_name(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return PRICE_RE.sub("", s).strip(" -|:") if len(s) > 1 else s


def _microdata(root: Node, base: str) -> list[dict]:
    out = []
    for n in root.iter():
        if "schema.org/Product" not in (n.attrs.get("itemtype") or ""):
            continue
        nm = n.find(lambda x: x.attrs.get("itemprop") == "name")
        pr = n.find(lambda x: x.attrs.get("itemprop") == "price")
        if not nm or not pr:
            continue
        name = nm.attrs.get("content") or nm.text()
        ptxt = pr.text() or ""
        price = _price(ptxt)
        if not price and pr.attrs.get("content"):
            # content="95.00" is seen on the page; keep it only if the visible text agrees or is empty
            c = pr.attrs["content"]
            if re.fullmatch(r"\d+(?:\.\d{2})?", c):
                price = f"${c}"
        u = n.find(lambda x: x.attrs.get("itemprop") == "url") or n.find(lambda x: x.tag == "a" and x.attrs.get("href"))
        href = (u.attrs.get("href") or u.attrs.get("content")) if u else ""
        if name and price:
            out.append({"name": _clean_name(name), "price": price, "url": urljoin(base, href) if href else base,
                        "image": _img(n, base), "source": "microdata"})
    return out


def _magento(root: Node, base: str) -> list[dict]:
    out = []
    for card in root.iter():
        cls = card.classes()
        if "product-item" not in cls and "product-item-info" not in cls:
            continue
        if "product-item" in cls and card.find(lambda x: "product-item-info" in x.classes()):
            continue  # let the inner info box be the card
        link = card.find(lambda x: x.tag == "a" and "product-item-link" in x.classes()) \
            or card.find(lambda x: "product-item-name" in x.classes())
        if not link:
            continue
        a = link if link.tag == "a" else link.find(lambda x: x.tag == "a")
        name = link.text()
        final = card.find(lambda x: x.attrs.get("data-price-type") == "finalPrice")
        pnode = (final.find(lambda x: "price" in x.classes()) if final else None) \
            or card.find(lambda x: "price" in x.classes() and _price(x.text()))
        price = _price(pnode.text()) if pnode else None
        href = a.attrs.get("href") if a else ""
        if name and price:
            out.append({"name": _clean_name(name), "price": price, "url": urljoin(base, href) if href else base,
                        "image": _img(card, base), "source": "product-card"})
    return out


def _generic(root: Node, base: str) -> list[dict]:
    """A node whose own text holds one $ price; climb a few levels to the card holding one product link."""
    out = []
    for n in root.iter():
        own = " ".join(c for c in n.children if isinstance(c, str))
        price = _price(own)
        if not price:
            continue
        card = n
        for _ in range(6):
            card = card.parent
            if card is None or card.tag in ("body", "#root", "html"):
                break
            links = [x for x in card.iter() if x.tag == "a" and x.attrs.get("href")
                     and not x.attrs["href"].startswith(("#", "javascript:", "mailto:", "tel:"))]
            hrefs = {urljoin(base, x.attrs["href"]) for x in links}
            prices = set(PRICE_RE.findall(card.text()))
            if len(prices) > 2:
                break  # climbed into a grid of many products
            if len(hrefs) == 1:
                head = card.find(lambda x: x.tag in ("h2", "h3", "h4", "h5") and x.text())
                named = [x for x in links if _clean_name(x.text())]
                name = (head.text() if head else (named[0].text() if named else ""))
                name = _clean_name(name)
                if name and len(name) <= 120:
                    out.append({"name": name, "price": price, "url": hrefs.pop(), "image": _img(card, base),
                                "source": "price-near-link"})
                break
    return out


def parse_products(html: str, base_url: str) -> list[dict]:
    """Product {name, price, url, image} pairs actually present in this (rendered) HTML. Deduped by url."""
    root = _dom(html)
    seen: set = set()
    out: list[dict] = []
    for found in (_microdata(root, base_url), _magento(root, base_url), _generic(root, base_url)):
        for p in found:
            key = p["url"] if p["url"] != base_url else f"{base_url}#{p['name']}"
            if key in seen or (p["name"].lower(), p["price"]) in seen:
                continue
            seen.update({key, (p["name"].lower(), p["price"])})
            out.append(p)
    return out


def category_links(html: str, base_url: str, limit: int = 2) -> list[str]:
    host = urlparse(base_url).netloc
    root = _dom(html)
    nav_first = [n for n in root.iter() if n.tag in ("nav", "header")] + [root]
    out: list[str] = []
    for scope in nav_first:
        for a in scope.iter():
            if a.tag != "a":
                continue
            href = a.attrs.get("href") or ""
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            u = urljoin(base_url, href).split("#")[0]
            pu = urlparse(u)
            if pu.netloc.removeprefix("www.") != host.removeprefix("www.") or u.rstrip("/") == base_url.rstrip("/") or pu.query:
                continue
            if NOT_CATEGORY_RE.search(pu.path + " " + a.text()):
                continue
            hay = (pu.path + " " + a.text()).lower()
            if any(w in hay for w in CATEGORY_WORDS) and u not in out:
                out.append(u)
            if len(out) >= limit:
                return out
    return out


# --------------------------------------------------------------------------- outputs
def _num(price: str) -> float | None:
    m = PRICE_RE.search(price or "")
    return float(m.group(1).replace(",", "")) if m else None


def to_jsonld(products: list[dict], business: str = "") -> dict:
    items = []
    for i, p in enumerate(products, 1):
        n = _num(p.get("price") or "")
        if n is None or not p.get("name"):
            continue  # never list a product without a seen price
        prod = {"@type": "Product", "name": p["name"], "url": p.get("url"),
                "offers": {"@type": "Offer", "price": n, "priceCurrency": "USD", "url": p.get("url")}}
        if p.get("image"):
            prod["image"] = p["image"]
        items.append({"@type": "ListItem", "position": len(items) + 1, "item": prod})
    ld = {"@context": "https://schema.org", "@type": "ItemList",
          "name": f"{business} products and prices".strip(), "numberOfItems": len(items), "itemListElement": items}
    return ld


def to_text(products: list[dict]) -> str:
    return "\n".join(f"- {p['name']}: {p['price']} ({p['url']})" for p in products if p.get("name") and p.get("price"))


def to_html_section(products: list[dict]) -> str:
    lis = "\n".join(f'  <li><a href="{escape(p["url"], quote=True)}">{escape(p["name"])}</a>: {escape(p["price"])}</li>'
                    for p in products if p.get("name") and p.get("price"))
    return ('<section id="landfall-products" data-landfall="1">\n<h2>Our arrangements and prices</h2>\n'
            f"<ul>\n{lis}\n</ul>\n</section>\n")


def to_html_page(products: list[dict], business: str = "") -> str:
    title = escape(f"{business} products and prices".strip())
    ld = json.dumps(to_jsonld(products, business), indent=2, ensure_ascii=False).replace("</", "<\\/")
    return (f"<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><title>{title}</title>\n"
            f'<script type="application/ld+json">\n{ld}\n</script>\n</head><body>\n{to_html_section(products)}</body></html>\n')


# --------------------------------------------------------------------------- browser
def extract(url: str, out_dir: str | Path, max_pages: int = 3) -> list[dict]:
    """Render the homepage + up to max_pages-1 category pages (GET only) and read the product cards."""
    from landfall.scan import BROWSER_UA

    out_dir = Path(out_dir)
    shots = out_dir / "receipts" / "products"
    shots.mkdir(parents=True, exist_ok=True)
    pages: list[dict] = []
    products: list[dict] = []
    note = ""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(user_agent=BROWSER_UA, viewport={"width": 1280, "height": 900})
                todo, done = [url], []
                while todo and len(done) < max_pages:
                    u = todo.pop(0)
                    rec = {"url": u, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                    try:
                        resp = page.goto(u, wait_until="domcontentloaded", timeout=30000)
                        rec["status"] = resp.status if resp else None
                        try:
                            page.wait_for_load_state("networkidle", timeout=8000)
                        except Exception:
                            pass
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(4000)
                        page.evaluate("window.scrollTo(0, 0)")
                        page.wait_for_timeout(2000)
                        html = page.content()
                        shot = shots / f"page-{len(done) + 1}.png"
                        try:
                            page.screenshot(path=str(shot), full_page=True, timeout=15000)
                        except Exception:
                            page.screenshot(path=str(shot), timeout=15000)
                        rec["screenshot"] = str(shot.relative_to(out_dir)).replace("\\", "/")
                        title = page.title() or ""
                        if BOT_WALL_RE.search(title) or (rec.get("status") in (403, 429, 503) and len(html) < 20000):
                            rec["bot_wall"] = True
                            note = f"Bot wall on {u} (status {rec.get('status')}, title {title!r}); no products read."
                            pages.append(rec)
                            if not done:
                                break
                            done.append(u)
                            continue
                        found = parse_products(html, page.url)
                        for f in found:
                            f["page"] = u
                        rec["found"] = len(found)
                        products.extend(found)
                        if not done:
                            todo.extend(category_links(html, page.url, limit=max_pages - 1))
                    except Exception as e:  # noqa: BLE001
                        rec["error"] = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
                    pages.append(rec)
                    done.append(u)
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001
        note = f"Browser failed: {type(e).__name__}: {str(e).splitlines()[0][:200]}"

    seen, uniq = set(), []
    for p in products:  # same product often appears on several pages (and under a category path)
        key = p["url"] if p["url"].rstrip("/") != p["page"].rstrip("/") else f"{p['page']}#{p['name']}"
        if key not in seen and (p["name"].lower(), p["price"]) not in seen:
            seen.update({key, (p["name"].lower(), p["price"])})
            uniq.append(p)
    if any(r.get("bot_wall") for r in pages) and not uniq:
        uniq = []
    rec = {"url": url, "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "rule": "Only name+price pairs seen on the rendered page; nothing invented.",
           "note": note or ("" if uniq else "No product cards with a visible price were found."),
           "pages": pages, "count": len(uniq), "products": uniq}
    (out_dir / "products.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return uniq


def load(run_dir: str | Path) -> dict | None:
    p = Path(run_dir) / "products.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="landfall.products", description="List a shop's products for AI assistants.")
    ap.add_argument("url")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-pages", type=int, default=3)
    a = ap.parse_args(argv)
    got = extract(a.url, a.out, a.max_pages)
    print(json.dumps({"count": len(got), "sample": [{"name": p["name"], "price": p["price"]} for p in got[:5]]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
