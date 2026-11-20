"""Load Landfall/.env into os.environ (stdlib; never prints values)."""
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def load() -> None:
    p = _ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load()
