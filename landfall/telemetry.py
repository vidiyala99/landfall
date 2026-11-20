"""Amplitude events for the agent-run funnel (HTTP V2 API). No key -> events go to runs/events.jsonl only."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import httpx

from landfall import env  # noqa: F401  (loads .env)

_LOG = Path(__file__).resolve().parent.parent / "runs" / "events.jsonl"
_DEVICE = "landfall-factory"


def track(event: str, props: dict) -> bool:
    rec = {"event_type": event, "device_id": _DEVICE, "time": int(time.time() * 1000),
           "insert_id": str(uuid.uuid4()), "event_properties": props}
    _LOG.parent.mkdir(parents=True, exist_ok=True)
    with _LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    key = os.environ.get("AMPLITUDE_API_KEY")
    if not key:
        return False
    try:
        r = httpx.post("https://api2.amplitude.com/2/httpapi", json={"api_key": key, "events": [rec]}, timeout=5)
        return r.status_code == 200
    except httpx.HTTPError:
        return False
