"""Machine-readable progress for the GUI.

When S57TOTPK_PROGRESS=1 (the GUI sets it for its child process), each
report() prints one line ``##progress {json}`` to stdout. Otherwise it does
nothing, so the command line output stays as it is.
"""
from __future__ import annotations

import json
import os
import sys

ENABLED = os.environ.get("S57TOTPK_PROGRESS") == "1"
PREFIX = "##progress "


def report(stage: str, done: float, total: float, **extra) -> None:
    if not ENABLED:
        return
    msg = {"stage": stage, "done": done, "total": total, **extra}
    sys.stdout.write(PREFIX + json.dumps(msg) + "\n")
    sys.stdout.flush()


def event(kind: str, **data) -> None:
    """One-off events: 'selection' (area picked on the map), 'result' (files written), 'error'."""
    if not ENABLED:
        return
    sys.stdout.write(PREFIX + json.dumps({"event": kind, **data}) + "\n")
    sys.stdout.flush()


def parse(line: str):
    """For the GUI: the dict carried by a progress line, else None."""
    if line.startswith(PREFIX):
        try:
            return json.loads(line[len(PREFIX):])
        except ValueError:
            return None
    return None
