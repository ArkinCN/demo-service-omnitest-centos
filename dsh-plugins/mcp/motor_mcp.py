#![源] bin/env python3
"""motor-mcp — stub MCP server for ASIC motor control (stdio transport).

Contract source of truth (copied, not invented):
  [源] tools/types.rs
  [源] tools/motor.rs

Four tools, all taking the required string `debugger_exe` (absolute path to
the ASIC CLI debugger executable), exactly as the Rust MotorDebuggerArgs struct
and the TOOL_MOTOR_* JSON Schemas define them:

  motor_start       -> text   "Motor started successfully"
  motor_stop        -> text   "Motor stopped successfully"
  motor_read_omega  -> json   {"omega_rpm": <float>}
  motor_read_udc    -> json   {"udc_voltage": <float>}

ONE DELIBERATE EXTENSION beyond the Rust contract: motor_start also accepts an
optional number `current_limit_a` (commanded phase-current limit, amperes).
The Rust handler has no such parameter. It exists here so the PreToolUse safety
hook has an argument to inspect; see README.md section "Contract deviations".
"""
from __future__ import annotations

import random

from mcp.server.mcpserver import MCPServer

from _common import log

SERVER = "motor"
TAG = "[ATH-MCP][Motor]"

mcp = MCPServer("motor")

# Stub machine state. A fresh process starts with the motor at rest.
_STATE = {"running": False, "omega_rpm": 0.0}

# Nominal cooling-fan operating point used by the stub, taken from the
# bench note "FG2 > 10000 rpm counts as started" in the startup-check skill.
_NOMINAL_RPM = 12_480.0
_NOMINAL_UDC = 24.0


@mcp.tool()
def motor_start(debugger_exe: str, current_limit_a: float | None = None) -> str:
    """Launch the motor debugger and start rotation.

    Args:
        debugger_exe: Absolute path to the motor debugger executable.
        current_limit_a: Optional commanded phase-current limit in amperes
            (ATH extension, not present in the Rust contract).
    """
    log(SERVER, TAG, "INFO", "starting motor",
        debugger_exe=debugger_exe, current_limit_a=current_limit_a)
    _STATE["running"] = True
    _STATE["omega_rpm"] = _NOMINAL_RPM + random.uniform(-60.0, 60.0)
    log(SERVER, TAG, "INFO", "motor started", omega_rpm=_STATE["omega_rpm"])
    return "Motor started successfully"


@mcp.tool()
def motor_stop(debugger_exe: str) -> str:
    """Stop the motor.

    Args:
        debugger_exe: Absolute path to the motor debugger executable.
    """
    log(SERVER, TAG, "INFO", "stopping motor", debugger_exe=debugger_exe)
    _STATE["running"] = False
    _STATE["omega_rpm"] = 0.0
    log(SERVER, TAG, "INFO", "motor stopped")
    return "Motor stopped successfully"


@mcp.tool()
def motor_read_omega(debugger_exe: str) -> dict:
    """Read the current motor angular velocity, in RPM.

    Args:
        debugger_exe: Absolute path to the motor debugger executable.
    """
    rpm = round(_STATE["omega_rpm"], 1) if _STATE["running"] else 0.0
    log(SERVER, TAG, "INFO", "read omega", debugger_exe=debugger_exe, omega_rpm=rpm)
    return {"omega_rpm": rpm}


@mcp.tool()
def motor_read_udc(debugger_exe: str) -> dict:
    """Read the motor DC bus voltage.

    Args:
        debugger_exe: Absolute path to the motor debugger executable.
    """
    udc = round(_NOMINAL_UDC + random.uniform(-0.15, 0.15), 3)
    log(SERVER, TAG, "INFO", "read Udc", debugger_exe=debugger_exe, udc_voltage=udc)
    return {"udc_voltage": udc}


if __name__ == "__main__":
    mcp.run(transport="stdio")
