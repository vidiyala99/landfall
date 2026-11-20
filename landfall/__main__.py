"""CLI dispatch: python -m landfall <command> [args...]

To add a command, add one line to COMMANDS mapping the name to a module that exposes
main(argv: list[str]) -> int. Modules are imported lazily, so a broken module only
breaks its own command.
"""
from __future__ import annotations

import importlib
import sys

COMMANDS = {
    "scan": "landfall.scan",            # static agent-readability scan
    "agent-run": "landfall.agent_run",  # browser agent task run
    "fix": "landfall.fix",              # generate fix package
    "mirror": "landfall.mirror",        # local mirror of a site
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in COMMANDS:
        if argv and argv[0] not in ("-h", "--help"):
            print(f"unknown command: {argv[0]}", file=sys.stderr)
        print("usage: python -m landfall <command> [args]\ncommands: " + ", ".join(COMMANDS), file=sys.stderr)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    try:
        mod = importlib.import_module(COMMANDS[argv[0]])
    except ImportError as e:
        print(f"command '{argv[0]}' is not available yet ({e})", file=sys.stderr)
        return 2
    return int(mod.main(argv[1:]) or 0)


if __name__ == "__main__":
    sys.exit(main())
