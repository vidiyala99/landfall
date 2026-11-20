"""Which AI assistants can get through the front door? GET the homepage as each assistant identifies itself.

Read-only (one GET per identity). Receipt: runs/<slug>/access.json with status codes and the exact user-agent strings.
Limit: real assistants also come from their own IP ranges; this tests the user-agent rule, which is how the blocks we
have seen (CloudFront 403 on Floranext florists) are applied.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import httpx

CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
AGENTS = [
    ("ChatGPT", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ChatGPT-User/1.0; +https://openai.com/bot)"),
    ("ChatGPT search", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)"),
    ("Claude", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; +Claude-User@anthropic.com)"),
    ("Perplexity", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user)"),
    ("Meta AI", "meta-externalfetcher/1.1 (+https://developers.facebook.com/docs/sharing/webmasters/crawler)"),
    ("A normal browser", CHROME),
]
BLOCK_MARKERS = ("request blocked", "the request could not be satisfied", "attention required", "access denied",
                 "verify you are human", "cf-chl", "captcha")


def check(url: str, timeout: float = 15) -> list[dict]:
    rows = []
    for name, ua in AGENTS:
        row = {"assistant": name, "user_agent": ua}
        try:
            r = httpx.get(url, headers={"User-Agent": ua}, timeout=timeout, follow_redirects=True)
            body = r.text[:4000].lower()
            blocked = r.status_code in (401, 403, 429, 503) or any(m in body for m in BLOCK_MARKERS)
            row.update(status=r.status_code, allowed=not blocked, bytes=len(r.content),
                       server=r.headers.get("server"), note=None)
        except httpx.HTTPError as e:
            row.update(status=None, allowed=False, bytes=0, server=None, note=f"request failed: {type(e).__name__}")
        rows.append(row)
    return rows


def summarize(rows: list[dict]) -> str:
    """'Muse and Claude get in; ChatGPT and Perplexity are turned away (HTTP 403).'"""
    agents = [r for r in rows if r["assistant"] != "A normal browser"]
    blocked = [r for r in agents if not r["allowed"]]
    if not blocked:
        return "Every AI assistant we tried can open your website."
    codes = sorted({str(r["status"]) for r in blocked if r["status"]})
    allowed = [r["assistant"] for r in agents if r["allowed"]]
    s = f"{', '.join(r['assistant'] for r in blocked)} {'is' if len(blocked) == 1 else 'are'} turned away"
    s += f" (HTTP {'/'.join(codes)})" if codes else ""
    if allowed:
        s += f"; {', '.join(allowed)} {'gets' if len(allowed) == 1 else 'get'} in"
    return s + "."


def run(url: str, run_dir: Path) -> dict:
    rows = check(url)
    out = {"url": url, "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "results": rows, "summary": summarize(rows)}
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "access.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    out = run(argv[0], Path(argv[1]))
    for r in out["results"]:
        print(f"{r['assistant']:<18} {r['status']}  {'in' if r['allowed'] else 'BLOCKED'}")
    print(out["summary"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
