"""Shared helpers for the three ATH MCP stub servers.

ATH = Agentic Test Harness, the Fortior plugin set built on top of
DeepSeek Harness (DSH). These servers are STUBS: they perform no real
hardware I/O. They reproduce the tool names, parameter names and return
shapes of the production Rust implementation in
`平台代码-脱敏版/app/src-tauri/src/vibe_testing_mcp/tools/` so that the
agent-side wiring can be validated before the hardware bridge exists.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib

LOG_DIR = pathlib.Path(
    os.environ.get("ATH_LOG_DIR", pathlib.Path(__file__).resolve().parent.parent / "logs")
)
LOG_DIR.mkdir(parents=True, exist_ok=True)


def log(server: str, tag: str, level: str, message: str, **fields) -> None:
    """Append one JSON line to logs/<server>.log.

    Mirrors the production `append_rust_log("INFO", "[VibeTesting-MCP][Motor] ...")`
    convention, but machine-readable so the end-to-end transcript can be replayed.
    """
    record = {
        "ts": _dt.datetime.now().isoformat(timespec="milliseconds"),
        "level": level,
        "tag": tag,
        "msg": message,
    }
    record.update(fields)
    with (LOG_DIR / f"{server}.log").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
