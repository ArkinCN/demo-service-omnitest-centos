#!/usr/bin/env python3
"""Talk to the three ATH MCP stubs directly over stdio, without DSH in the way.

Use it to tell a broken stub apart from a broken harness mount: if this passes
and the model still cannot reach a tool, the fault is in cordis.patch.yml or in
the harness, not in the server.

    .venv/bin/python tools_smoke_mcp.py
"""
import asyncio
import pathlib

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = pathlib.Path(__file__).resolve().parent
PY = str(ROOT / ".venv/bin/python")
EXE = "/opt/ath/bin/AsicCliDebugger.exe"

CASES = [
    ("motor", "motor_mcp.py", [
        ("motor_start", {"debugger_exe": EXE, "current_limit_a": 8.0}),
        ("motor_read_omega", {"debugger_exe": EXE}),
        ("motor_read_udc", {"debugger_exe": EXE}),
        ("motor_stop", {"debugger_exe": EXE}),
    ]),
    ("scope", "scope_mcp.py", [
        ("rigol_connect", {}),
        ("rigol_measure", {"measurement_type": "VPP", "channel": 3}),
        ("rigol_capture", {"channels": [1, 3]}),
    ]),
    ("report", "report_mcp.py", [
        ("fill_report", {"template": "coolingfan-startup.xlsm", "images": [],
                         "csv": str(ROOT / "data/faithful_norm1200.csv"),
                         "verdict": "wiring rehearsal"}),
    ]),
]


async def main() -> None:
    for name, script, calls in CASES:
        params = StdioServerParameters(command=PY, args=[str(ROOT / "mcp" / script)])
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                print(f"### {name}: {[t.name for t in tools.tools]}")
                for tool_name, args in calls:
                    res = await session.call_tool(tool_name, args)
                    text = res.content[0].text if res.content else ""
                    print(f"  {tool_name} -> {' '.join(text.split())[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
