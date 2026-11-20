"""Landfall as a remote MCP server: add it as a custom connector in Claude, Muse, Grok or ChatGPT.

Tools:
  make_agent_ready(url, goal, visibility_query?) -> starts a job, returns job id + report link
  job_status(slug)                                -> stage-by-stage progress
  get_report(slug)                                -> scores before/after, top problems, fixes, owner questions
  quick_check(url)                                -> static agent-readability scan only (~30 s)
  list_products_for_ai(url)                       -> products + prices as JSON-LD / llms.txt list (read-only render)

Run:  python -m landfall.mcp_server --port 8765   (streamable HTTP at /mcp, reports at /reports/<slug>)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response

from landfall import env  # noqa: F401
from landfall.pipeline import RUNS, ROOT, Job, slugify, summarize

PUBLIC_URL = os.environ.get("LANDFALL_PUBLIC_URL", "http://127.0.0.1:8765").rstrip("/")

mcp = FastMCP(
    "Landfall",
    instructions=(
        "Landfall checks whether AI agents can find, read and use a small business's website, then builds the "
        "fixes and proves them with a before/after rerun. Use make_agent_ready for a full job (several minutes; "
        "poll job_status), quick_check for a 30-second read-only scan. Landfall is read-only on real websites: it "
        "never submits forms, books or buys. Share the report link with the business owner. "
        "STYLE FOR YOUR REPLY: the person is a busy small-business owner. Answer in at most 5 short lines: lead with "
        "the tool's `owner_summary` (which assistants can and cannot get in, then the biggest problem), then the before -> after numbers on one "
        "line, then one next step, then the report link. No tables, no headings, no jargon. Offer details only if asked."
    ),
    stateless_http=True,
)

_jobs: dict[str, threading.Thread] = {}
MAX_JOBS = int(os.environ.get("LANDFALL_MAX_JOBS", "2"))


def _domain(u: str) -> str:
    from urllib.parse import urlparse
    h = urlparse(u if "://" in u else "https://" + u).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def existing_run(url_or_slug: str) -> str | None:
    """Slug of a finished run for this site (matched by slug or by the scanned URL's domain), if any."""
    if (RUNS / url_or_slug / "result.json").exists():
        return url_or_slug
    want = _domain(url_or_slug)
    for p in sorted(RUNS.glob("*/result.json")):
        try:
            if _domain(json.loads(p.read_text(encoding="utf-8")).get("url") or "") == want:
                return p.parent.name
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _report_link(slug: str) -> str:
    return f"{PUBLIC_URL}/reports/{slug}"


@mcp.tool()
def make_agent_ready(url: str, goal: str = "", visibility_query: str = "", business_name: str = "",
                     run_agent_tasks: bool = True, rerun: bool = False) -> dict:
    """Make a small business's website agent-ready.

    url: the business website. goal: what customers should be able to do (e.g. "order a birthday cake for
    Saturday pickup"). visibility_query: what a customer would ask their agent (e.g. "bakery near Akron that does
    custom cakes"); used to test whether agents recommend this business. Returns a job id (slug) and report link.
    """
    done = existing_run(url)
    if done and not rerun:
        res = get_report(done)
        res["status"] = "finished earlier (pass rerun=true for a fresh check)"
        return res
    slug = slugify(url)
    t = _jobs.get(slug)
    if t and t.is_alive():
        return {"slug": slug, "status": "already running", "report": _report_link(slug)}
    if sum(1 for th in _jobs.values() if th.is_alive()) >= MAX_JOBS:
        return {"status": "busy", "message": f"Landfall is running {MAX_JOBS} jobs; try again in a few minutes."}
    job = Job(url, goal or None, None, visibility_query or None, name=business_name or None, slug=slug,
              run_tasks=run_agent_tasks)
    th = threading.Thread(target=job.run, daemon=True)
    th.start()
    _jobs[slug] = th
    return {"slug": slug, "status": "started", "report": _report_link(slug),
            "next": "Call job_status with this slug every minute or so; a full job takes 5-15 minutes."}


@mcp.tool()
def job_status(slug: str) -> dict:
    """Progress of a Landfall job, stage by stage (scan, find, do, mirror, fix, rescan, redo)."""
    p = RUNS / slug / "job.json"
    if not p.exists():
        return {"slug": slug, "status": "unknown"}
    return json.loads(p.read_text(encoding="utf-8"))


def owner_summary(res: dict) -> str:
    """Three plain lines for a busy owner, built from the run's own numbers (no new claims)."""
    probs = res.get("top_problems") or []
    top = probs[0]["detail"] if probs else "Assistants could read your basic facts."
    if res.get("assistant_access"):
        top = res["assistant_access"]["summary"] + (" " + top if probs and probs[0]["id"] != "bot_challenge" else "")
    rd = res.get("read") or {}
    fe = (res.get("do_fetch") or {})
    b, a = (fe.get("before") or (res.get("do") or {}).get("before")), (fe.get("after") or (res.get("do") or {}).get("after"))
    line2 = f"Readable by assistants: {rd.get('before')} -> {rd.get('after')} of 100."
    if b and a:
        line2 += f" Customer tasks an assistant could finish: {b.get('done')} -> {a.get('done')} of {b.get('total')}."
    found = res.get("visible")
    line3 = ("When a customer asked an assistant, you were recommended." if found else
             "When a customer asked an assistant, you were not recommended." if found is False else "")
    return " ".join(x for x in (top, line2, line3) if x)


@mcp.tool()
def get_report(slug: str) -> dict:
    """Before/after scores, the top problems agents hit (each with a receipt), and the fix package summary.
    slug: a Landfall job id or the business website URL."""
    slug = existing_run(slug) or slug
    d = RUNS / slug
    if not (d / "scan.json").exists():
        return {"slug": slug, "status": "no results yet"}
    res = summarize(d)
    res["report"] = _report_link(slug)
    if res.get("url"):  # live, read-only: one GET per assistant identity, so this part is always current
        from landfall import access
        acc = access.run(res["url"], d)
        res["assistant_access"] = {"summary": acc["summary"], "checked_at": acc["checked_at"],
                                   "results": [{k: r[k] for k in ("assistant", "status", "allowed")} for r in acc["results"]]}
    res["owner_summary"] = owner_summary(res)
    owner = d / "fixes" / "needs-owner.md"
    if owner.exists():
        res["questions_for_owner"] = owner.read_text(encoding="utf-8")[:1500]
    return res


@mcp.tool()
def quick_check(url: str) -> dict:
    """Read-only 30-second scan: can AI agents read this website? Returns score and failed checks with receipts."""
    slug = slugify(url)
    out = RUNS / slug
    p = subprocess.run([sys.executable, "-m", "landfall", "scan", url, "--out", str(out)], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace")
    if p.returncode != 0 or not (out / "scan.json").exists():
        return {"error": p.stderr[-400:] or "scan failed"}
    scan = json.loads((out / "scan.json").read_text(encoding="utf-8"))
    return {"slug": slug, "score": scan["score"],
            "failed": [{"title": c["title"], "detail": c["detail"], "severity": c["severity"]}
                       for c in scan["checks"] if c["status"] == "fail"],
            "report": _report_link(slug)}


@mcp.tool()
def list_products_for_ai(url: str) -> dict:
    """Digital worker: read the shop's products and prices the way a shopper sees them (real browser, read-only)
    and write them out so assistants that don't run JavaScript can see them. Only seen name+price pairs."""
    from landfall import products
    slug = slugify(url)
    out = RUNS / slug
    out.mkdir(parents=True, exist_ok=True)
    got = products.extract(url if "://" in url else "https://" + url, out)
    rec = products.load(out) or {}
    files = ["products.json"]
    if got:
        name = ""
        try:
            name = (json.loads((out / "scan.json").read_text(encoding="utf-8")).get("facts") or {}).get("name") or ""
        except (OSError, json.JSONDecodeError):
            pass
        fx = out / "fixes"
        fx.mkdir(exist_ok=True)
        from landfall.fix import inject_jsonld
        (fx / "products.jsonld.html").write_text(inject_jsonld("", products.to_jsonld(got, name)), encoding="utf-8")
        (fx / "products.md").write_text("# Products and prices\n\n" + products.to_text(got) + "\n", encoding="utf-8")
        files += ["fixes/products.jsonld.html", "fixes/products.md"]
    return {"slug": slug, "count": len(got),
            "sample": [{"name": p["name"], "price": p["price"]} for p in got[:5]],
            "files": [f"{PUBLIC_URL}/reports/{slug}/files/{f}" for f in files],
            "note": rec.get("note") or ("Paste products.jsonld.html into your site's head; the list stays correct only "
                                        "if you re-run this after price changes")}


@mcp.tool()
def what_has_the_factory_seen(question: str) -> dict:
    """Ask Landfall's memory (Cognee) what it has learned across all the small-business sites it has audited,
    e.g. "Which website platforms block AI assistants?" or "What stops assistants from seeing prices?"."""
    from landfall import memory
    hits = memory.recall(question)
    return {"question": question, "answers": [h.get("text", "") for h in hits][:5],
            "source": "Landfall audit memory (Cognee)" if os.environ.get("COGNEE_API_KEY") else "local audit log"}


@mcp.custom_route("/crew", methods=["GET"])
async def crew_page(request: Request) -> Response:
    from landfall import crew
    return HTMLResponse(crew.render(request.query_params.get("slug") or "small-town-blooms"))


@mcp.custom_route("/reports/{slug}", methods=["GET"])
async def report_page(request: Request) -> Response:
    slug = request.path_params["slug"]
    page = RUNS / slug / "report.html"
    try:
        from landfall import report
        html = report.render(RUNS / slug, variant=request.query_params.get("v") or "harbor-a")
        from landfall import crew as _crew
        import re as _re
        html = _re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + _crew.toggle(slug, inside=False), html, count=1)
        return HTMLResponse(html)
    except Exception as e:  # noqa: BLE001
        if page.exists():
            return FileResponse(page)
        return JSONResponse({"slug": slug, "status": "report not ready", "error": str(e)[:200]})


@mcp.custom_route("/reports/{slug}/files/{path:path}", methods=["GET"])
async def report_file(request: Request) -> Response:
    slug, rel = request.path_params["slug"], request.path_params["path"]
    base = (RUNS / slug).resolve()
    target = (base / rel).resolve()
    if base not in target.parents or not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(target)


@mcp.custom_route("/static/{path:path}", methods=["GET"])
async def static_file(request: Request) -> Response:
    base = (Path(__file__).resolve().parent / "static").resolve()
    target = (base / request.path_params["path"]).resolve()
    if base not in target.parents or not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(target, headers={"Cache-Control": "public, max-age=300"})


@mcp.custom_route("/healthz", methods=["GET"])
async def health(_: Request) -> Response:
    return JSONResponse({"ok": True})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    mcp.settings.host, mcp.settings.port = a.host, a.port
    from urllib.parse import urlparse
    from mcp.server.transport_security import TransportSecuritySettings
    public_host = urlparse(PUBLIC_URL).netloc
    # Behind the Agent37 edge the Host header is the container's internal IP, so host checks can't work there;
    # the unguessable public URL is the credential. Locally (127.0.0.1) the protection stays on.
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=a.host in ("127.0.0.1", "localhost"),
        allowed_hosts=[public_host, f"127.0.0.1:{a.port}", f"localhost:{a.port}"],
        allowed_origins=[f"https://{public_host}", "https://claude.ai", "https://claude.com"],
    )
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
