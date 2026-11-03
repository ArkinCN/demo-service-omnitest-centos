"""解析助手 SSE 响应，核对六事件与检索结果（验证用）。

用法：
    curl.exe -s -N ... > out.txt
    python scripts/parse_sse.py out.txt
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    p = Path(sys.argv[1])
    text = p.read_text(encoding="utf-8", errors="replace")

    events: list[dict] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            events.append(json.loads(line[5:].strip()))
        except json.JSONDecodeError:
            pass

    kinds = [e.get("type") for e in events]
    print("事件数:", len(events))
    print("类型序列:", kinds[:10], "..." if len(kinds) > 10 else "")

    for e in events:
        t = e.get("type")
        if t == "tool_call":
            args = json.dumps(e.get("args"), ensure_ascii=False)
            print(f"  tool_call  {e.get('name')}  args={args[:90]}")
        elif t == "tool_result":
            print(f"  tool_result  {e.get('resultSummary')}  ({e.get('durationMs')} ms)")
        elif t == "evidence":
            items = e.get("items") or []
            print(f"  evidence  {len(items)} 条")
            for it in items[:3]:
                print("    -", json.dumps(it, ensure_ascii=False)[:130])
        elif t == "done":
            print(f"  done  reason={e.get('reason')}  msg={(e.get('message') or '')[:70]}")

    body = "".join(e.get("delta", "") for e in events if e.get("type") == "message_delta")
    print("\n--- 助手回答前 260 字 ---")
    print(body[:260])
    return 0


if __name__ == "__main__":
    sys.exit(main())
