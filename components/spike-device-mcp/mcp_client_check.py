"""用官方 MCP 客户端走一遍两种传输，证明这确实是个合规的 MCP server，
而不只是桥后面的一堆普通函数。

    python mcp_client_check.py stdio
    python mcp_client_check.py http        # 需先起 --transport streamable-http
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys

# stdio 传输时 server 跑在子进程；paramiko 的连接日志会混进本脚本的输出，
# 压掉它，保证 stdout 是干净的 JSON。
logging.getLogger("paramiko").setLevel(logging.WARNING)


def _text(res) -> str:
    sc = getattr(res, "structuredContent", None)
    if isinstance(sc, dict):
        return json.dumps(sc, ensure_ascii=False)
    for b in getattr(res, "content", []) or []:
        if getattr(b, "text", None):
            return b.text
    return str(res)


async def probe(session) -> dict:
    await session.initialize()
    tools = (await session.list_tools()).tools
    out: dict = {
        "tool_count": len(tools),
        "tools": [{"name": t.name, "group": (t.meta or {}).get("group"),
                   "guarded": bool((t.meta or {}).get("guarded"))} for t in tools],
    }
    out["connect"] = json.loads(_text(await session.call_tool("connect", {})))
    out["status"] = json.loads(_text(await session.call_tool("status", {})))
    out["read_fg"] = json.loads(_text(await session.call_tool("read_fg", {"samples": 2})))
    out["start_without_token"] = json.loads(
        _text(await session.call_tool("start", {"duty_percent": 40, "duration_s": 10})))
    return out


async def via_stdio() -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    import os
    # SDK 默认只给子进程一套最小环境，会把私钥路径这类变量滤掉，
    # 结果 server 连不上台架、静默降级 mock。这里显式把需要的几个传进去。
    passthru = {k: v for k, v in os.environ.items()
                if k.startswith(("FORTIOR_", "BENCH_", "MCP_"))
                or k in ("PATH", "HOME", "LANG", "PYTHONPATH")}
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "device_bench.server", "--transport", "stdio"],
        env=passthru)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            return await probe(s)


async def via_http(url: str) -> dict:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    async with streamable_http_client(url) as (r, w):
        async with ClientSession(r, w) as s:
            return await probe(s)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    port = sys.argv[2] if len(sys.argv) > 2 else "8032"
    res = asyncio.run(via_stdio() if which == "stdio"
                      else via_http(f"http://127.0.0.1:{port}/mcp"))
    print(json.dumps({"transport": which, **res}, ensure_ascii=False, indent=2))
