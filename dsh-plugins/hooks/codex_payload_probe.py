#!/usr/bin/env python3
"""Non-blocking probe that records what the Codex hook bridge actually delivers.

Mounted through @deepseek-ai/dsh-hooks-codex purely as evidence: that bridge
builds a Codex-shaped payload whose `tool_input` is `{ command }` — the tool's
`command` argument when present, otherwise the empty string — so a non-shell
tool's real arguments never reach the hook. This probe never blocks; it writes
the payload it received to logs/hook-codex-probe.log and exits 0.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import sys

LOG_PATH = pathlib.Path(
    os.environ.get("ATH_LOG_DIR", pathlib.Path(__file__).resolve().parent.parent / "logs")
) / "hook-codex-probe.log"

raw = sys.stdin.read()
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
with LOG_PATH.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({
        "ts": _dt.datetime.now().isoformat(timespec="milliseconds"),
        "bridge": "dsh-hooks-codex",
        "raw_payload": raw,
    }, ensure_ascii=False) + "\n")
sys.exit(0)
