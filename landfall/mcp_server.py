"""Landfall as a remote MCP server: add it as a custom connector in Claude, Muse, Grok or ChatGPT.

Tools:
  make_agent_ready(url, goal, visibility_query?) -> starts a job, returns job id + report link
  job_status(slug)                                -> stage-by-stage progress
  get_report(slug)                                -> scores before/after, top problems, fixes, owner questions
  quick_check(url)                                -> static agent-readability scan only (~30 s)

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
        "never submits forms, books or buys. Share the report link with the business owner."
    ),
    stateless_http=True,
)

_jobs: dict[str, threading.Thread] = {}
MAX_JOBS = int(os.environ.get("LANDFALL_MAX_JOBS", "2"))


def _report_link(slug: str) -> str:
    return f"{PUBLIC_URL}/reports/{slug}"


@mcp.tool()
def make_agent_ready(url: str, goal: str = "", visibility_query: str = "", business_name: str = "",
                     run_agent_tasks: bool = True) -> dict:
    """Make a small business's website agent-ready.

    url: the business website. goal: what customers should be able to do (e.g. "order a birthday cake for
    Saturday pickup"). visibility_query: what a customer would ask their agent (e.g. "bakery near Akron that does
    custom cakes"); used to test whether agents recommend this business. Returns a job id (slug) and report link.
    """
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


@mcp.tool()
def get_report(slug: str) -> dict:
    """Before/after scores, the top problems agents hit (each with a receipt), and the fix package summary."""
    d = RUNS / slug
    if not (d / "scan.json").exists():
        return {"slug": slug, "status": "no results yet"}
    res = summarize(d)
    res["report"] = _report_link(slug)
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


@mcp.custom_route("/reports/{slug}", methods=["GET"])
async def report_page(request: Request) -> Response:
    slug = request.path_params["slug"]
    page = RUNS / slug / "report.html"
    if page.exists():
        return FileResponse(page)
    try:
        from landfall import report
        html = report.render(RUNS / slug)
        return HTMLResponse(html)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"slug": slug, "status": "report not ready", "error": str(e)[:200]})


@mcp.custom_route("/reports/{slug}/files/{path:path}", methods=["GET"])
async def report_file(request: Request) -> Response:
    slug, rel = request.path_params["slug"], request.path_params["path"]
    base = (RUNS / slug).resolve()
    target = (base / rel).resolve()
    if base not in target.parents or not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(target)


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
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[public_host, f"127.0.0.1:{a.port}", f"localhost:{a.port}"],
        allowed_origins=[f"https://{public_host}", "https://claude.ai", "https://claude.com"],
    )
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
