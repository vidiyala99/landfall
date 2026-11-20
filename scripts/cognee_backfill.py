"""Backfill runs/*/result.json into Cognee Cloud, then run one recall. Prints no secrets.

Usage: python scripts/cognee_backfill.py [--wait 180] [--recall-only]
"""
from __future__ import annotations

import json
import sys
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from landfall import cognee_backend  # noqa: E402

QUESTION = "Which platforms block AI agents for small businesses?"


def targets() -> dict:
    p = ROOT / "sites" / "targets.toml"
    if not p.exists():
        return {}
    return {s["slug"]: s for s in tomllib.loads(p.read_text(encoding="utf-8")).get("site", [])}


def main() -> int:
    wait = int(sys.argv[sys.argv.index("--wait") + 1]) if "--wait" in sys.argv else 180
    meta = targets()
    n = 0
    files = [] if "--recall-only" in sys.argv else sorted((ROOT / "runs").glob("*/result.json"))
    for f in files:
        result = json.loads(f.read_text(encoding="utf-8"))
        slug = result.get("slug") or f.parent.name
        ok = cognee_backend.remember(slug, result, meta.get(slug))
        print(f"remember {slug}: {'ok' if ok else 'FAILED'}")
        n += ok
    print(f"remembered {n} audits into dataset {cognee_backend.DATASET}")
    deadline = time.time() + wait
    while True:
        rows = cognee_backend.recall(QUESTION)
        if rows or time.time() > deadline:
            break
        print("recall empty (cognify still running?); retrying in 15s")
        time.sleep(15)
    print(f"\nQ: {QUESTION}")
    for r in rows:
        print("-", r["text"])
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
