"""Mirror: save a faithful, offline-renderable copy of a site's homepage.

    python -m landfall.mirror <url> --out runs/<slug>/mirror [--keep-js]

Read-only on the real site: GET requests only (Playwright page load plus plain GETs for
robots.txt, sitemap.xml, llms.txt). Nothing is clicked, typed or submitted.

Output layout:
    index.html        rendered DOM, asset URLs rewritten to assets/...
    assets/           CSS, images, fonts (and JS with --keep-js), named <hash8>-<original-basename>
    robots.txt, sitemap.xml, llms.txt   copied if the real site serves them
    manifest.json     {"url", "fetched_at", "assets": {local_path: original_url}, "root_files": [...]}
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, unquote

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 Landfall-mirror"
ROOT_FILES = ("robots.txt", "sitemap.xml", "llms.txt")
ASSET_TYPES = {"stylesheet", "image", "font", "media", "script"}
CT_EXT = {
    "text/css": ".css", "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
    "image/webp": ".webp", "image/svg+xml": ".svg", "image/avif": ".avif", "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico", "font/woff2": ".woff2", "font/woff": ".woff", "font/ttf": ".ttf",
    "font/otf": ".otf", "application/font-woff": ".woff", "application/font-woff2": ".woff2",
    "application/javascript": ".js", "text/javascript": ".js", "application/x-javascript": ".js",
    "video/mp4": ".mp4",
}


# ---------------------------------------------------------------- naming / rewriting (pure, tested)

def local_name(url: str, content_type: str = "") -> str:
    """Stable local filename for an asset URL: <hash8>-<sanitized basename><ext>."""
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    path = unquote(urlsplit(url).path)
    base = os.path.basename(path.rstrip("/")) or "asset"
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)[:60]
    stem, ext = os.path.splitext(base)
    ct = (content_type or "").split(";")[0].strip().lower()
    if not ext or len(ext) > 6:
        ext = CT_EXT.get(ct, ext if ext and len(ext) <= 6 else "")
        base = stem
    else:
        base = stem
    return f"{h}-{base}{ext}"


def _norm(url: str) -> str:
    """Normalize for lookup: drop fragment, unescape &amp;."""
    url = url.replace("&amp;", "&").strip()
    return url.split("#", 1)[0]


def _lookup(raw: str, base_url: str, url_map: dict[str, str], prefix: str) -> str | None:
    raw_s = raw.strip()
    if not raw_s or raw_s.startswith(("data:", "javascript:", "mailto:", "tel:", "#", "blob:")):
        return None
    absu = _norm(urljoin(base_url, _norm(raw_s)))
    local = url_map.get(absu)
    if local is None:
        return None
    return prefix + local


_ATTR_RE = re.compile(
    r"""(?P<pre>\s(?:src|href|data-src|data-original|poster|data-bg|data-background)\s*=\s*)(?P<q>["'])(?P<val>.*?)(?P=q)""",
    re.IGNORECASE | re.DOTALL,
)
_SRCSET_RE = re.compile(
    r"""(?P<pre>\s(?:srcset|data-srcset|imagesrcset)\s*=\s*)(?P<q>["'])(?P<val>.*?)(?P=q)""",
    re.IGNORECASE | re.DOTALL,
)
_CSS_URL_RE = re.compile(r"""url\(\s*(?P<q>["']?)(?P<val>[^"')]+?)(?P=q)\s*\)""", re.IGNORECASE)
_CSS_IMPORT_RE = re.compile(r"""@import\s+(?P<q>["'])(?P<val>[^"']+)(?P=q)""", re.IGNORECASE)


def rewrite_css(css: str, css_url: str, url_map: dict[str, str], prefix: str = "") -> str:
    """Rewrite url(...) and @import inside CSS. Relative to the CSS file's own URL."""
    def sub_url(m):
        new = _lookup(m.group("val"), css_url, url_map, prefix)
        return f'url("{new}")' if new else m.group(0)

    def sub_imp(m):
        new = _lookup(m.group("val"), css_url, url_map, prefix)
        return f'@import "{new}"' if new else m.group(0)

    return _CSS_IMPORT_RE.sub(sub_imp, _CSS_URL_RE.sub(sub_url, css))


def rewrite_html(html: str, base_url: str, url_map: dict[str, str], prefix: str = "assets/") -> str:
    """Rewrite asset references in HTML (attributes, srcset, inline style url()) to local files.

    url_map maps absolute asset URL -> local filename (inside the assets dir). URLs not in the
    map are left untouched. A <base> tag would break relative local paths, so it is removed.
    """
    m = re.search(r"<base\s[^>]*href\s*=\s*[\"']([^\"']+)[\"']", html, re.IGNORECASE)
    if m:
        base_url = urljoin(base_url, m.group(1))
        html = re.sub(r"<base\s[^>]*>", "", html, flags=re.IGNORECASE)

    def sub_attr(m):
        new = _lookup(m.group("val"), base_url, url_map, prefix)
        return f'{m.group("pre")}{m.group("q")}{new}{m.group("q")}' if new else m.group(0)

    def sub_srcset(m):
        parts = []
        changed = False
        for cand in m.group("val").split(","):
            bits = cand.strip().split()
            if not bits:
                continue
            new = _lookup(bits[0], base_url, url_map, prefix)
            if new:
                bits[0] = new
                changed = True
            parts.append(" ".join(bits))
        if not changed:
            return m.group(0)
        return f'{m.group("pre")}{m.group("q")}{", ".join(parts)}{m.group("q")}'

    html = _ATTR_RE.sub(sub_attr, html)
    html = _SRCSET_RE.sub(sub_srcset, html)
    html = _CSS_URL_RE.sub(
        lambda m: (lambda n: f"url('{n}')" if n else m.group(0))(_lookup(m.group("val"), base_url, url_map, prefix)),
        html,
    )
    return html


def strip_scripts(html: str) -> str:
    """Remove executable <script> blocks (keep JSON-LD and other data scripts) and inline handlers."""
    def keep(m):
        tag = m.group(1)
        t = re.search(r"type\s*=\s*[\"']([^\"']+)", tag, re.IGNORECASE)
        if t and t.group(1).strip().lower() in ("application/ld+json", "application/json", "text/template"):
            return m.group(0)
        return ""

    html = re.sub(r"<script\b([^>]*)>.*?</script\s*>", keep, html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<link\b[^>]*rel\s*=\s*[\"'](?:modulepreload|preload)[\"'][^>]*as\s*=\s*[\"']script[\"'][^>]*>", "", html, flags=re.IGNORECASE)
    return html


# ---------------------------------------------------------------- capture (network, Playwright)

def _get(url: str, timeout: float = 15.0) -> tuple[int, str, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, "", b""
    except Exception:
        return 0, "", b""


def fetch_root_files(url: str, out: Path) -> list[str]:
    """GET robots.txt / sitemap.xml / llms.txt from the real site; save those that exist."""
    saved = []
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    for name in ROOT_FILES:
        status, ct, body = _get(f"{origin}/{name}")
        if status != 200 or not body:
            continue
        head = body[:300].lower()
        if b"<html" in head or b"<!doctype html" in head:  # soft 404 served as HTML
            continue
        (out / name).write_bytes(body)
        saved.append(name)
    return saved


def capture(url: str, out: str | Path, keep_js: bool = False, timeout_ms: int = 45000) -> dict:
    """Load url in headless Chromium (GET only), save rendered DOM + assets to out."""
    from playwright.sync_api import sync_playwright

    out = Path(out)
    assets_dir = out / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    bodies: dict[str, tuple[str, bytes]] = {}

    def on_response(resp):
        try:
            req = resp.request
            if req.method != "GET" or req.resource_type not in ASSET_TYPES:
                return
            if resp.status != 200:
                return
            bodies[_norm(resp.url)] = (resp.headers.get("content-type", ""), resp.body())
        except Exception:
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 900})
        page = ctx.new_page()

        # Read-only guard: abort any non-GET request the page tries to make.
        def guard(route):
            if route.request.method not in ("GET", "HEAD"):
                return route.abort()
            return route.continue_()

        page.route("**/*", guard)
        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        # Scroll to trigger lazy images.
        page.evaluate(
            """async () => { for (let y = 0; y < document.body.scrollHeight; y += 700) {
                 window.scrollTo(0, y); await new Promise(r => setTimeout(r, 120)); } window.scrollTo(0, 0); }"""
        )
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        final_url = page.url
        html = page.content()
        browser.close()

    url_map: dict[str, str] = {}
    for aurl, (ct, _body) in bodies.items():
        if not keep_js and "javascript" in ct.lower():
            continue
        url_map[aurl] = local_name(aurl, ct)

    manifest_assets = {}
    for aurl, local in url_map.items():
        ct, body = bodies[aurl]
        if "text/css" in ct.lower() or local.endswith(".css"):
            css = body.decode("utf-8", errors="replace")
            body = rewrite_css(css, aurl, url_map, prefix="").encode("utf-8")
        (assets_dir / local).write_bytes(body)
        manifest_assets[f"assets/{local}"] = aurl

    if not keep_js:
        html = strip_scripts(html)
    html = rewrite_html(html, final_url, url_map, prefix="assets/")
    (out / "index.html").write_text(html, encoding="utf-8")

    root_files = fetch_root_files(final_url, out)
    manifest = {
        "url": url,
        "final_url": final_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "keep_js": keep_js,
        "assets": manifest_assets,
        "root_files": root_files,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


# ---------------------------------------------------------------- serve

class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".txt": "text/plain; charset=utf-8", ".xml": "application/xml", ".json": "application/json",
        ".woff2": "font/woff2", ".woff": "font/woff", ".svg": "image/svg+xml", ".webp": "image/webp",
    }

    def log_message(self, *args):
        pass


def serve(directory: str | Path, port: int = 8765, background: bool = True):
    """Serve a mirror dir (index.html, assets/, /robots.txt, /llms.txt, /sitemap.xml, /.well-known/...).

    background=True returns the running ThreadingHTTPServer (call .shutdown() when done);
    background=False blocks.
    """
    handler = functools.partial(_QuietHandler, directory=str(directory))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    if not background:
        print(f"serving {directory} at http://127.0.0.1:{httpd.server_address[1]}/")
        httpd.serve_forever()
        return httpd
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="landfall.mirror", description="Mirror a homepage for offline use (GET only).")
    ap.add_argument("url", nargs="?")
    ap.add_argument("--out", help="output dir, e.g. runs/<slug>/mirror")
    ap.add_argument("--keep-js", action="store_true", help="keep and localize JavaScript (default strips it)")
    ap.add_argument("--serve", metavar="DIR", help="serve an existing mirror dir instead of capturing")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    if a.serve:
        serve(a.serve, a.port, background=False)
        return 0
    if not a.url or not a.out:
        ap.error("url and --out are required (or use --serve DIR)")
    m = capture(a.url, a.out, keep_js=a.keep_js)
    print(f"mirrored {m['final_url']} -> {a.out} ({len(m['assets'])} assets; root files: {', '.join(m['root_files']) or 'none'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
