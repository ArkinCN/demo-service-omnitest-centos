#!/usr/bin/env python3
"""PreToolUse safety gate: refuse a motor start above the bench current limit.

Wired through @deepseek-ai/dsh-hooks-claude-code, which feeds one JSON object on
stdin and reads the exit code:

    exit 0  -> allow the tool call (any non-2 code is non-blocking)
    exit 2  -> block the tool call; stderr becomes the model-visible reason

Payload fields used: `hook_event_name`, `tool_name`, `tool_input`.
The Claude Code bridge passes the real tool arguments through as `tool_input`
(dsh-hooks-claude-code lib/index.js: `tool_input: exec.arguments`), so the
commanded current is visible here. The Codex bridge does NOT: it flattens
`tool_input` to `{ command }`, so this gate cannot be built on that bridge.
See hooks/codex_payload_probe.py, which demonstrates the difference.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import sys

LIMIT_A = 20.0
GUARDED_SUFFIX = "motor_start"

LOG_PATH = pathlib.Path(
    os.environ.get("ATH_LOG_DIR", pathlib.Path(__file__).resolve().parent.parent / "logs")
) / "hook.log"


def audit(**fields) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fields["ts"] = _dt.datetime.now().isoformat(timespec="milliseconds")
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields, ensure_ascii=False) + "\n")


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as exc:
        audit(hook="pretooluse_motor_current", decision="allow",
              reason=f"unparseable payload: {exc}")
        return 0

    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}

    if not tool_name.endswith(GUARDED_SUFFIX):
        return 0

    raw = tool_input.get("current_limit_a")
    if raw is None:
        audit(hook="pretooluse_motor_current", tool_name=tool_name,
              decision="allow", reason="no current_limit_a in tool_input",
              tool_input=tool_input)
        return 0

    try:
        current = float(raw)
    except (TypeError, ValueError):
        audit(hook="pretooluse_motor_current", tool_name=tool_name,
              decision="allow", reason=f"non-numeric current_limit_a: {raw!r}")
        return 0

    if current > LIMIT_A:
        reason = (
            f"Blocked by the bench safety gate: {tool_name} was called with "
            f"current_limit_a = {current} A, above the {LIMIT_A} A limit for this "
            "cooling-fan fixture. Above that the winding and the shunt are outside "
            "their rated range. Re-run at 20 A or less, or have the bench owner "
            "raise the limit in hooks/pretooluse_motor_current.py."
        )
        audit(hook="pretooluse_motor_current", tool_name=tool_name,
              decision="block", current_limit_a=current, limit_a=LIMIT_A)
        print(reason, file=sys.stderr)
        return 2

    audit(hook="pretooluse_motor_current", tool_name=tool_name,
          decision="allow", current_limit_a=current, limit_a=LIMIT_A)
    return 0


if __name__ == "__main__":
    sys.exit(main())
