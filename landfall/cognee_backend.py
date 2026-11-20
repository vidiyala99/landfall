"""Cognee Cloud backend for factory memory (remember / recall over the documented HTTP API).

Docs: https://docs.cognee.ai/cognee-cloud/http-api
  - auth: headers X-Api-Key + X-Tenant-Id
  - POST /api/v1/remember  (multipart: raw_data, datasetName, run_in_background) = add + cognify in one call
    https://docs.cognee.ai/cognee-cloud/functionality/data-ingestion
  - POST /api/v1/recall    (JSON: query, datasets) auto-routed search
    https://docs.cognee.ai/cognee-cloud/functionality/search-and-recall

Never raises to callers; failures go to stderr (without secrets) and return False / [].
"""
from __future__ import annotations

import json
import os
import sys

from landfall import env  # noqa: F401  (loads .env)

DATASET = "landfall_audits"
TIMEOUT = 20.0


def _cfg() -> tuple[str, dict] | None:
    key = os.environ.get("COGNEE_API_KEY")
    base = os.environ.get("COGNEE_BASE_URL", "").rstrip("/")
    if not key or not base:
        return None
    headers = {"X-Api-Key": key}
    tenant = os.environ.get("COGNEE_TENANT_ID")
    if tenant:
        headers["X-Tenant-Id"] = tenant
    return base, headers


def _log(msg: str) -> None:
    print(f"[cognee] {msg}", file=sys.stderr)


def _client():
    import httpx
    return httpx.Client(timeout=TIMEOUT)


def summarize(slug: str, result: dict, meta: dict | None = None) -> str:
    """Short plain-English audit memory for one site."""
    meta = meta or {}
    name = meta.get("name") or slug
    where = ", ".join(x for x in (meta.get("category"), meta.get("city"), meta.get("state")) if x)
    head = f"{name} ({where})" if where else name
    parts = [f"Landfall audit of {head}, {result.get('url', '')}."]
    if meta.get("builder"):
        parts.append(f"Website platform: {meta['builder']}.")
    probs = result.get("top_problems") or []
    if probs:
        parts.append("Problems found: " + "; ".join(
            f"[{p.get('severity', '?')}] {p.get('detail') or p.get('title') or p.get('id')}" for p in probs) + ".")
    rd = result.get("read") or {}
    if "before" in rd:
        parts.append(f"Agent read score {rd.get('before')} -> {rd.get('after')} after fixes.")
    for label, k in (("browser-agent tasks", "do"), ("no-JS fetch tasks", "do_fetch")):
        d = result.get(k) or {}
        b, a = d.get("before") or {}, d.get("after") or {}
        if b:
            parts.append(f"{label} done {b.get('done')}/{b.get('total')} -> {a.get('done', '?')}/{a.get('total', '?')}.")
    if "visible" in result:
        parts.append(("Visible" if result["visible"] else "Not visible")
                     + f" in AI search for: \"{result.get('visibility_query', '')}\".")
    if result.get("needs_owner"):
        parts.append("Some fixes need the owner (e.g. hosting/CDN bot settings).")
    return " ".join(parts)


def _target_meta(slug: str) -> dict | None:
    try:
        import tomllib
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / "sites" / "targets.toml"
        for s in tomllib.loads(p.read_text(encoding="utf-8")).get("site", []):
            if s.get("slug") == slug:
                return s
    except Exception:  # noqa: BLE001
        pass
    return None


def remember(slug: str, result: dict, meta: dict | None = None) -> bool:
    cfg = _cfg()
    if not cfg:
        return False
    base, headers = cfg
    if meta is None:
        meta = _target_meta(slug)
    text = summarize(slug, result, meta)
    try:
        with _client() as c:
            r = c.post(f"{base}/api/v1/remember", headers=headers,
                       data={"datasetName": DATASET, "run_in_background": "true"},
                       files=[("raw_data", (None, text))])
        if r.status_code >= 400:
            _log(f"remember {slug}: HTTP {r.status_code} {r.text[:200]}")
            return False
        return True
    except Exception as e:  # noqa: BLE001
        _log(f"remember {slug}: {type(e).__name__}: {e}")
        return False


def _texts(payload) -> list[dict]:
    out: list[dict] = []

    def add(item):
        if isinstance(item, str):
            if item.strip():
                out.append({"text": item})
        elif isinstance(item, dict):
            if item.get("source") == "system":  # e.g. status "memory_warming_up": cognify not finished
                _log(f"recall: {item.get('status')}")
                return
            for k in ("search_result", "text", "answer", "result", "content"):
                if k in item and item[k]:
                    v = item[k]
                    if isinstance(v, (list, dict)):
                        add(v)
                    else:
                        row = {"text": str(v)}
                        if "score" in item:
                            row["score"] = item["score"]
                        if item.get("dataset_name"):
                            row["dataset"] = item["dataset_name"]
                        out.append(row)
                    return
            out.append({"text": json.dumps(item)[:1000]})
        elif isinstance(item, list):
            for x in item:
                add(x)

    add(payload)
    return out


def recall(question: str) -> list[dict]:
    cfg = _cfg()
    if not cfg:
        return []
    base, headers = cfg
    try:
        with _client() as c:
            r = c.post(f"{base}/api/v1/recall", headers={**headers, "Content-Type": "application/json"},
                       json={"query": question, "datasets": [DATASET]})
        if r.status_code >= 400:
            _log(f"recall: HTTP {r.status_code} {r.text[:200]}")
            return []
        return _texts(r.json())
    except Exception as e:  # noqa: BLE001
        _log(f"recall: {type(e).__name__}: {e}")
        return []
