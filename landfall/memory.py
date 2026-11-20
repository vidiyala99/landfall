"""Factory memory across audits: what broke, which fixes moved the score, by business category.

Backend: Cognee (remember / recall) when configured; always also appends to runs/memory.jsonl so recall works
offline. Cognee wiring is filled in once the Cognee Cloud key is in .env.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from landfall import env  # noqa: F401

_LOG = Path(__file__).resolve().parent.parent / "runs" / "memory.jsonl"


def remember_audit(slug: str, result: dict) -> None:
    _LOG.parent.mkdir(parents=True, exist_ok=True)
    with _LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"slug": slug, **result}) + "\n")
    if os.environ.get("COGNEE_API_KEY"):
        try:
            from landfall import cognee_backend
            cognee_backend.remember(slug, result)
        except Exception:
            pass


def recall(question: str) -> list[dict]:
    if os.environ.get("COGNEE_API_KEY"):
        try:
            from landfall import cognee_backend
            return cognee_backend.recall(question)
        except Exception:
            pass
    if not _LOG.exists():
        return []
    rows = [json.loads(l) for l in _LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    words = {w for w in question.lower().split() if len(w) > 3}
    return [r for r in rows if words & set(json.dumps(r).lower().split())][-10:]
