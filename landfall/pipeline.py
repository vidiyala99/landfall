"""One Landfall job: scan -> find -> do -> mirror -> fix -> rescan fixed mirror -> (do on mirror) -> result.json.

Stages call the module CLIs as subprocesses so each lane's code stays independent. Every stage records
its status in runs/<slug>/job.json so the MCP server can report progress while a job runs.
"""
from __future__ import annotations

import datetime as dt
import functools
import http.server
import json
import re
import socket
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
PY = sys.executable


def slugify(url: str) -> str:
    host = urlparse(url if "://" in url else "https://" + url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return re.sub(r"[^a-z0-9]+", "-", host).strip("-") or "site"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class Job:
    def __init__(self, url: str, goal: str | None, tasks: list[str] | None, query: str | None,
                 name: str | None = None, slug: str | None = None, run_tasks: bool = True):
        self.url = url if "://" in url else "https://" + url
        self.slug = slug or slugify(self.url)
        self.goal = goal
        self.tasks = tasks or default_tasks(goal)
        self.query = query
        self.name = name
        self.run_tasks = run_tasks
        self.dir = RUNS / self.slug
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state = {"slug": self.slug, "url": self.url, "goal": goal, "started_at": _now(), "stages": {},
                      "status": "running"}
        self._save()

    def _save(self):
        (self.dir / "job.json").write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def stage(self, name: str, status: str, note: str | None = None):
        self.state["stages"][name] = {"status": status, "at": _now(), **({"note": note} if note else {})}
        self._save()
        try:
            from landfall import telemetry
            telemetry.track("landfall_stage", {"slug": self.slug, "stage": name, "status": status})
        except Exception:
            pass

    def _cli(self, name: str, args: list[str], timeout: int = 600) -> bool:
        self.stage(name, "running")
        try:
            p = subprocess.run([PY, "-m", *args], cwd=str(ROOT), capture_output=True, text=True,
                               timeout=timeout, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            self.stage(name, "failed", f"timeout {timeout}s")
            return False
        (self.dir / f"{name}.log").write_text(p.stdout + "\n--- stderr ---\n" + p.stderr, encoding="utf-8")
        ok = p.returncode == 0
        self.stage(name, "done" if ok else "failed", None if ok else p.stderr.strip()[-300:])
        return ok

    def run(self) -> dict:
        from landfall import agent_run

        self._cli("scan", ["landfall", "scan", self.url, "--out", str(self.dir)])
        if self.query and not (self.dir / "find.json").exists():
            self.stage("find", "running")
            try:
                agent_run.run_find(self.url, self.query, self.name, self.dir)
                self.stage("find", "done")
            except Exception as e:  # noqa: BLE001
                self.stage("find", "failed", str(e)[:300])
        if self.run_tasks and self.tasks and not (self.dir / "do.json").exists():
            self.stage("do", "running")
            try:
                agent_run.run_do(self.url, self.tasks, self.dir)
                self.stage("do", "done")
            except Exception as e:  # noqa: BLE001
                self.stage("do", "failed", str(e)[:300])
        self._cli("mirror", ["landfall.mirror", self.url, "--out", str(self.dir / "mirror")])
        self._cli("fix", ["landfall.fix", str(self.dir)])
        fixed = self.dir / "mirror-fixed"
        if fixed.exists():
            port, stop = serve_dir(fixed)
            try:
                after = self.dir / "after"
                after.mkdir(exist_ok=True)
                self._cli("rescan", ["landfall", "scan", f"http://127.0.0.1:{port}/", "--out", str(after)])
                if self.run_tasks and self.tasks:
                    self.stage("redo", "running")
                    try:
                        agent_run.run_do(f"http://127.0.0.1:{port}/", self.tasks, after)
                        self.stage("redo", "done")
                    except Exception as e:  # noqa: BLE001
                        self.stage("redo", "failed", str(e)[:300])
            finally:
                stop()
        result = summarize(self.dir)
        (self.dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        self.state["status"] = "done"
        self.state["finished_at"] = _now()
        self._save()
        try:
            from landfall import memory
            memory.remember_audit(self.slug, result)
        except Exception:
            pass
        return result


def default_tasks(goal: str | None) -> list[str]:
    base = ["Find this business's opening hours for Saturday",
            "Find the phone number and street address",
            "Find what they sell or offer, with at least one price"]
    if goal:
        base.insert(0, f"Find out how a customer would do this, and stop before submitting anything: {goal}")
    return base


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve_dir(path: Path):
    port = _free_port()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(path))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return port, httpd.shutdown


def _load(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def summarize(run_dir: Path) -> dict:
    before, after = _load(run_dir / "scan.json"), _load(run_dir / "after" / "scan.json")
    do_b, do_a = _load(run_dir / "do.json"), _load(run_dir / "after" / "do.json")
    find = _load(run_dir / "find.json")
    fails = [c for c in (before or {}).get("checks", []) if c.get("status") == "fail"]
    return {
        "slug": run_dir.name,
        "url": (before or {}).get("url"),
        "read": {"before": (before or {}).get("score", {}).get("read"),
                 "after": (after or {}).get("score", {}).get("read")},
        "do": {"before": (do_b or {}).get("score"), "after": (do_a or {}).get("score")},
        "visible": (find or {}).get("visible"),
        "visibility_query": (find or {}).get("query"),
        "top_problems": [{"id": c["id"], "title": c["title"], "detail": c["detail"], "severity": c["severity"]}
                         for c in sorted(fails, key=lambda c: {"high": 0, "med": 1, "low": 2}[c["severity"]])][:6],
        "fixes": (run_dir / "fixes" / "CHANGES.md").exists(),
        "needs_owner": (run_dir / "fixes" / "needs-owner.md").exists(),
    }
