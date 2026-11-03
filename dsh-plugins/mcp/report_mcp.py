#!/usr/bin/env python3
"""report-mcp — stub MCP server for test-report generation (stdio transport).

One tool:
  fill_report(template, images, csv, verdict?, notes?) -> json {output_path, ...}

The production report product is a macro-enabled Excel workbook (.xlsm); this
stub writes nothing but a small JSON manifest under `reports/` and returns its
path, so the agent loop can be validated without the reporting toolchain. The
returned `output_path` names a file that really exists on disk after the call.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib

from mcp.server.mcpserver import MCPServer

from _common import log

SERVER = "report"
TAG = "[ATH-MCP][Report]"

REPORT_DIR = pathlib.Path(
    os.environ.get(
        "ATH_REPORT_DIR",
        pathlib.Path(__file__).resolve().parent.parent / "reports",
    )
)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

mcp = MCPServer("report")


@mcp.tool()
def fill_report(
    template: str,
    images: list[str] | None = None,
    csv: str | None = None,
    verdict: str | None = None,
    notes: str | None = None,
) -> dict:
    """Fill a test-report template and write the report to disk.

    Args:
        template: Report template name or path, e.g. "coolingfan-startup.xlsm".
        images: Paths of figures or oscilloscope screenshots to embed.
        csv: Path of the measurement CSV backing the report.
        verdict: Overall pass/fail conclusion to stamp on the report.
        notes: Free-text remarks appended to the report.
    """
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPORT_DIR / f"report-{stamp}.json"
    manifest = {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "template": template,
        "images": images or [],
        "csv": csv,
        "verdict": verdict,
        "notes": notes,
        "format": "json-manifest (stub)",
        "production_format": ".xlsm macro-enabled Excel workbook",
    }
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log(SERVER, TAG, "INFO", "report written", output_path=str(out), template=template)
    return {
        "output_path": str(out),
        "template": template,
        "embedded_images": len(images or []),
        "csv": csv,
        "verdict": verdict,
        "source": "stub",
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
