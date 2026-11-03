#![源] bin/env python3
"""scope-mcp — stub MCP server for the RIGOL oscilloscope (stdio transport).

Contract source of truth for tool names and parameter names:
  [源] tools/types.rs
  (TOOL_RIGOL_CONNECT / TOOL_RIGOL_MEASURE and their JSON Schemas)

Tools:
  rigol_connect(device_path?)                 -> json  connection record
  rigol_capture(channels?, window_s?)         -> json  window statistics per channel
  rigol_measure(measurement_type, channel?)   -> json  one measurement value

HONESTY BOUNDARY, read this before quoting any number this server returns.
Two different kinds of value come out of here and they are labelled as such in
every payload by a `source` field:

  source = "faithful_norm1200.csv"
      Computed for real from the bench capture
      `data/faithful_norm1200.csv` (1200 samples, t = -12.00 .. +11.98 s,
      20 ms sample spacing; columns time_s, ch1_current_V, ch2_fg1_V,
      ch3_fg2_V, ch4_pwm1_V). Amplitude statistics (VMAX, VMIN, VPP, VAVG,
      VRMS) are honest numbers from that file.

  source = "stub"
      Fabricated by this stub. The 1200-point record is decimated far below
      the FG pulse rate, so it carries no recoverable frequency content: a
      rising-edge count over the whole 24 s window yields zero crossings on
      every channel. Any rotational figure (FG frequency, RPM, FG1/FG2 ratio)
      is therefore a placeholder for wiring the agent loop, NOT a measurement.
      Replace it with a deep-storage capture before any of it is reported.
"""
from __future__ import annotations

import csv
import os
import pathlib
import statistics

from mcp.server.mcpserver import MCPServer

from _common import log

SERVER = "scope"
TAG = "[ATH-MCP][Rigol]"

DATA_CSV = pathlib.Path(
    os.environ.get(
        "ATH_SCOPE_CSV",
        pathlib.Path(__file__).resolve().parent.parent / "data" / "faithful_norm1200.csv",
    )
)

CHANNEL_COLUMNS = {
    1: ("ch1_current_V", "phase current sense"),
    2: ("ch2_fg1_V", "FG1 tacho"),
    3: ("ch3_fg2_V", "FG2 tacho"),
    4: ("ch4_pwm1_V", "PWM1 drive"),
}

# Stubbed rotational operating point. See the HONESTY BOUNDARY docstring above.
_STUB_FG2_RPM = 12_480.0
_STUB_FG1_OVER_FG2 = 2.00  # 2 pole pairs, per the bench signal definition

mcp = MCPServer("scope")

_STATE = {"connected": False, "device_path": None}


def _load():
    with DATA_CSV.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _column(rows, channel: int) -> list[float]:
    col, _ = CHANNEL_COLUMNS[channel]
    return [float(r[col]) for r in rows]


def _stats(values: list[float]) -> dict:
    mean = statistics.fmean(values)
    return {
        "vmax": round(max(values), 4),
        "vmin": round(min(values), 4),
        "vpp": round(max(values) - min(values), 4),
        "vavg": round(mean, 4),
        "vrms": round((sum(v * v for v in values) / len(values)) ** 0.5, 4),
    }


@mcp.tool()
def rigol_connect(device_path: str | None = None) -> dict:
    """Connect to a RIGOL oscilloscope.

    Args:
        device_path: VISA resource string; omit to auto-discover.
    """
    resolved = device_path or "USB0::0x1AB1::0x04CE::DS1ZA000000000::INSTR"
    _STATE.update(connected=True, device_path=resolved)
    log(SERVER, TAG, "INFO", "connected", device_path=resolved)
    return {
        "connected": True,
        "device_path": resolved,
        "identity": "RIGOL TECHNOLOGIES,DS1104Z,STUB,00.04.04",
        "source": "stub",
        "note": "No instrument is contacted; this stub replays data/faithful_norm1200.csv.",
    }


@mcp.tool()
def rigol_capture(channels: list[int] | None = None, window_s: float | None = None) -> dict:
    """Capture a waveform window and return per-channel statistics.

    Args:
        channels: Channel numbers to capture (1-4). Defaults to all four.
        window_s: Capture window in seconds, centred on t = 0. Defaults to the
            full record (24 s).
    """
    chans = channels or [1, 2, 3, 4]
    rows = _load()
    if window_s:
        half = window_s / 2.0
        rows = [r for r in rows if -half <= float(r["time_s"]) <= half] or rows
    t = [float(r["time_s"]) for r in rows]

    per_channel = {}
    for ch in chans:
        col, role = CHANNEL_COLUMNS[ch]
        st = _stats(_column(rows, ch))
        st.update(column=col, role=role, source="faithful_norm1200.csv")
        per_channel[f"ch{ch}"] = st

    result = {
        "csv_path": str(DATA_CSV),
        "sample_count": len(rows),
        "t_start_s": round(t[0], 4),
        "t_end_s": round(t[-1], 4),
        "sample_interval_s": round(t[1] - t[0], 6) if len(t) > 1 else None,
        "channels": per_channel,
        "derived": {
            "fg2_rpm": _STUB_FG2_RPM,
            "fg1_rpm": _STUB_FG2_RPM * _STUB_FG1_OVER_FG2,
            "fg1_over_fg2": _STUB_FG1_OVER_FG2,
            "fault_flag": False,
            "source": "stub",
            "why_stub": (
                "This 1200-sample record is decimated to 20 ms spacing, far below the "
                "FG pulse rate; a rising-edge count over the full window returns zero "
                "crossings on every channel, so no frequency or RPM can be recovered "
                "from it. These rotational figures are placeholders, not measurements."
            ),
        },
    }
    log(SERVER, TAG, "INFO", "capture", channels=chans, samples=len(rows))
    return result


@mcp.tool()
def rigol_measure(measurement_type: str, channel: int = 1) -> dict:
    """Perform one measurement on a channel.

    Args:
        measurement_type: One of FREQ, VMAX, VMIN, VPP, VAVG, VRMS.
        channel: Channel number 1-4. Defaults to 1.
    """
    mtype = measurement_type.strip().upper()
    if channel not in CHANNEL_COLUMNS:
        log(SERVER, TAG, "WARN", "bad channel", channel=channel)
        raise ValueError(f"rigol_measure: channel must be 1-4, got {channel}")

    col, role = CHANNEL_COLUMNS[channel]
    rows = _load()

    if mtype == "FREQ":
        # Honest answer: the decimated record carries no recoverable pulse rate.
        value = _STUB_FG2_RPM / 60.0 if channel == 3 else None
        payload = {
            "measurement_type": mtype,
            "channel": channel,
            "column": col,
            "role": role,
            "value": value,
            "unit": "Hz",
            "source": "stub",
            "note": (
                "FREQ is not recoverable from the 1200-sample decimated record "
                "(zero rising-edge crossings over the 24 s window). Value is a stub."
            ),
        }
    else:
        st = _stats(_column(rows, channel))
        key = mtype.lower()
        if key not in st:
            raise ValueError(
                f"rigol_measure: unsupported measurement_type {measurement_type!r}; "
                "expected one of FREQ, VMAX, VMIN, VPP, VAVG, VRMS"
            )
        payload = {
            "measurement_type": mtype,
            "channel": channel,
            "column": col,
            "role": role,
            "value": st[key],
            "unit": "V",
            "source": "faithful_norm1200.csv",
        }

    log(SERVER, TAG, "INFO", "measure", measurement_type=mtype, channel=channel,
        value=payload["value"])
    return payload


if __name__ == "__main__":
    mcp.run(transport="stdio")
