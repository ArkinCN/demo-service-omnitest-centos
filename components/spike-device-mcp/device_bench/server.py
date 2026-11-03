"""device-bench MCP server。

工具按三层分组，组名写在每个工具的 meta.group 上，前端据此画工具菜单：
  connection  连接层   connect / status / disconnect
  observation 观测层   read_fg / read_pwm / capture_scope / tail_log
  action      动作层   start / stop / estop / write_param / export / archive

动作层六个工具全部受人工确认闸口约束（device_bench/confirm.py），
无 confirm_token 一律拒绝执行，只返回一张待人工批准的凭据。

两种传输：
    python -m device_bench.server --transport stdio
    python -m device_bench.server --transport streamable-http --port 8032
"""
from __future__ import annotations

import argparse
import math
import os
import re
import time
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import config
from .backend import BenchBackend, LocalVisaBackend
from .confirm import GUARDED_ACTIONS, REGISTRY
from .dll_bridge import DllBridgeError, get_client

ALLOW_MOCK = os.environ.get("BENCH_ALLOW_MOCK", "1") != "0"
# 观测层两条路二选一：ssh（默认，SSH 到工控机跑客户 exe）/ local（本机直连示波器发 SCPI）。
LOCAL_MODE = config.BENCH_BACKEND == "local"
BENCH = BenchBackend(config.BENCH, allow_mock=ALLOW_MOCK)
LOCAL_SCOPE = LocalVisaBackend() if LOCAL_MODE else None

server = MCPServer(
    name="device-bench",
    title="峰岹台架设备",
    version="0.1.0",
    instructions=(
        "把峰岹电机测试台架当成一台 MCP 设备来用。\n"
        "观测层随便调；动作层六个工具（start/stop/estop/write_param/export/archive）"
        "有物理后果，必须先拿到人工批准过的 confirm_token 才会执行。\n"
        "任何返回里的 mode 字段若为 mock，数据就是合成的，不得当作实测结果上报。"
    ),
)


# ---------- 公共 ----------

def _envelope(mode: str, **kw: Any) -> dict:
    """统一返回信封。mode 永远在，mock 永不冒充 live。"""
    env = {"mode": mode, "ts": time.time(), "device_id": "bench"}
    if mode == "mock":
        env["mock_warning"] = "合成数据，非台架实测，不得作为测试结论的证据"
    env.update(kw)
    return env


def _guard(tool: str, args: dict, confirm_token: str | None) -> dict | None:
    """动作层闸口。返回非 None 就代表拒绝执行，把它原样当结果返回。"""
    clean = {k: v for k, v in args.items() if k != "confirm_token"}
    if not confirm_token:
        t = REGISTRY.issue(tool, clean, GUARDED_ACTIONS[tool])
        return {
            "status": "confirmation_required",
            "executed": False,
            "reason": "红线动作，未带 confirm_token，已拒绝执行",
            "how_to_proceed": (
                "把下面这张凭据交给人：前端在 C 区看板弹出确认条，"
                "人点确认后调桥的 POST /confirmations/{token}/approve，"
                "再带着同一个 confirm_token 和同一组参数重调本工具。"
            ),
            **t.public(),
        }
    try:
        REGISTRY.redeem(confirm_token, tool, clean)
    except (PermissionError, KeyError) as exc:
        return {
            "status": "confirmation_invalid",
            "executed": False,
            "reason": str(exc),
            "tool": tool,
        }
    return None


# ---------- 连接层 ----------

@server.tool(
    name="connect",
    title="连接台架",
    description="连接设备。本机直连模式下直连示波器（pyvisa-py），SSH 模式下 SSH 到工控机。",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    meta={"group": "connection", "layer": "连接层", "guarded": False},
)
def connect(force_mock: bool = False) -> dict:
    """建立连接。local 模式直连示波器；ssh 模式 SSH 到工控机（连不上降级 mock）。"""
    if LOCAL_MODE:
        snap = LOCAL_SCOPE.connect(force_mock=force_mock)
    else:
        snap = BENCH.connect(force_mock=force_mock)
    return _envelope(snap.pop("mode"), status="ok", **snap)


@server.tool(
    name="status",
    title="台架状态",
    description="返回连接状态、真实/mock 模式、主机名、在线时长与最近一次错误。C 区画布节点靠它显示连接徽章。",
    annotations=ToolAnnotations(readOnlyHint=True),
    meta={"group": "connection", "layer": "连接层", "guarded": False},
)
def status() -> dict:
    snap = (LOCAL_SCOPE if LOCAL_MODE else BENCH).snapshot()
    pending = REGISTRY.list()
    return _envelope(
        snap.pop("mode"),
        status="ok",
        pending_confirmations=len(pending),
        pending_tokens=[p["confirm_token"] for p in pending],
        **snap,
    )


@server.tool(
    name="disconnect",
    title="断开台架",
    description="关闭 SSH 会话，释放通道。",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    meta={"group": "connection", "layer": "连接层", "guarded": False},
)
def disconnect() -> dict:
    snap = (LOCAL_SCOPE if LOCAL_MODE else BENCH).disconnect()
    return _envelope(snap.pop("mode"), status="ok", **snap)


# ---------- 观测层 ----------

_FG_RE = re.compile(r"FG(\d)=([0-9.eE+\-]+)")


def _parse_visa_float(raw: str) -> float | None:
    """解析 SCPI 查询返回的数值；哨兵值 / 非数值 → None（表示「无有效测量」）。"""
    txt = raw.strip()
    m = re.search(r"([0-9.eE+\-]+)", txt)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    if abs(v) >= config.VISA_NAN / 10:
        return None
    return v


def _ensure_local_scope() -> LocalVisaBackend:
    """本机直连模式下确保示波器已连接（未连则尝试连一次）。"""
    if LOCAL_SCOPE is None:
        raise RuntimeError("非本机直连模式")
    if not LOCAL_SCOPE.connected:
        LOCAL_SCOPE.connect()
    return LOCAL_SCOPE


@server.tool(
    name="read_fg",
    title="读转速反馈",
    description=(
        "读 FG1（电气转速方波）与 FG2（红外机械转速，1 脉冲/转）的频率，"
        "并换算转速与 FG1/FG2 比值（极对数 2，理论应为 2.0）。"
        "台架上跑的是 C:\\fc_pull\\FgPoll.exe。"
    ),
    annotations=ToolAnnotations(readOnlyHint=True),
    meta={"group": "observation", "layer": "观测层", "guarded": False,
          "signals": ["FG1", "FG2"]},
)
def read_fg(samples: int = 1, interval_s: float = 1.0) -> dict:
    """采 samples 次 FG 频率。

    Args:
        samples: 采样次数，1 到 10。
        interval_s: 两次之间间隔秒数。
    """
    samples = max(1, min(int(samples), 10))
    if LOCAL_MODE:
        return _read_fg_local(samples, interval_s)

    rows: list[dict] = []
    mode = BENCH.mode
    for i in range(samples):
        if i:
            time.sleep(max(0.0, min(interval_s, 5.0)))
        r = BENCH.exec(config.FGPOLL)
        mode = r.mode
        found = {f"FG{g}": float(v) for g, v in _FG_RE.findall(r.out)}
        fg1, fg2 = found.get("FG1"), found.get("FG2")
        valid = lambda v: v is not None and v < config.VISA_NAN / 10  # noqa: E731
        row = {
            "i": i,
            "fg1_hz": fg1 if valid(fg1) else None,
            "fg2_hz": fg2 if valid(fg2) else None,
            "raw": r.out.strip(),
            "elapsed_ms": r.elapsed_ms,
        }
        if row["fg2_hz"]:
            row["rpm"] = round(row["fg2_hz"] * 60, 1)
        if row["fg1_hz"] and row["fg2_hz"]:
            row["fg1_over_fg2"] = round(row["fg1_hz"] / row["fg2_hz"], 3)
        if row["fg1_hz"] is None and row["fg2_hz"] is None:
            row["note"] = (
                "示波器返回 9.9E37（VISA 无有效测量哨兵值）：电机未转或探头未接，"
                "不是通信故障"
            )
        rows.append(row)
    ok = [r for r in rows if r.get("rpm")]
    return _envelope(
        mode,
        status="ok",
        samples=rows,
        rpm_mean=round(sum(r["rpm"] for r in ok) / len(ok), 1) if ok else None,
        motor_spinning=bool(ok),
    )


def _read_fg_local(samples: int, interval_s: float) -> dict:
    """本机直连：用 pyvisa 发频率测量 SCPI 读 FG1/FG2（CH2/CH3）。"""
    try:
        scope = _ensure_local_scope()
    except RuntimeError as exc:
        return _envelope("unknown", status="unavailable", samples=[], rpm_mean=None,
                         motor_spinning=False, note=str(exc))
    if not scope.connected:
        return _envelope(
            scope.mode, status="unavailable", samples=[], rpm_mean=None,
            motor_spinning=False, note=scope.snapshot().get("last_error"),
        )

    rows: list[dict] = []
    for i in range(samples):
        if i:
            time.sleep(max(0.0, min(interval_s, 5.0)))
        try:
            fg1_raw = scope.query(f":MEASure:FREQuency? CHANnel{config.CH_FG1}")
            fg2_raw = scope.query(f":MEASure:FREQuency? CHANnel{config.CH_FG2}")
            fg1 = _parse_visa_float(fg1_raw)
            fg2 = _parse_visa_float(fg2_raw)
        except Exception as exc:  # noqa: BLE001 —— 读失败如实报，不编数
            return _envelope(
                scope.mode, status="unavailable", samples=rows, rpm_mean=None,
                motor_spinning=False, note=f"读 FG 频率失败：{type(exc).__name__}: {exc}",
            )
        row = {
            "i": i,
            "fg1_hz": fg1,
            "fg2_hz": fg2,
            "raw": f"FG1={fg1_raw.strip()} FG2={fg2_raw.strip()}",
            "elapsed_ms": None,
        }
        if fg2:
            row["rpm"] = round(fg2 * 60, 1)
        if fg1 and fg2:
            row["fg1_over_fg2"] = round(fg1 / fg2, 3)
        if fg1 is None and fg2 is None:
            row["note"] = "示波器未测到有效频率：电机未转或探头未接（哨兵值，非通信故障）"
        rows.append(row)
    ok = [r for r in rows if r.get("rpm")]
    return _envelope(
        scope.mode,
        status="ok",
        samples=rows,
        rpm_mean=round(sum(r["rpm"] for r in ok) / len(ok), 1) if ok else None,
        motor_spinning=bool(ok),
    )


@server.tool(
    name="read_pwm",
    title="读 PWM 占空比",
    description=(
        "读 PWM1（驱动被测电机）的占空比。实现方式是取一段 CH4 采样、"
        "按高于中点的采样占比算占空比——低采样率混叠下该比例仍准确（实测零偏差），"
        "载波形状则需要 capture_scope 单独高速短抓。"
    ),
    annotations=ToolAnnotations(readOnlyHint=True),
    meta={"group": "observation", "layer": "观测层", "guarded": False,
          "signals": ["PWM1"]},
)
def read_pwm(channel: int = 4) -> dict:
    """读一路 PWM 的占空比。

    Args:
        channel: 示波器通道号，PWM1 接在 CH4。
    """
    if LOCAL_MODE:
        return _read_pwm_local(channel)

    r = BENCH.exec(f'{config.SCOPECTL} q ":MEAS:ITEM? PDUTy,CHAN{channel}"')
    txt = r.out.strip()
    duty = None
    m = re.search(r"([0-9.eE+\-]+)", txt)
    if m:
        try:
            v = float(m.group(1))
            if v < config.VISA_NAN / 10:
                duty = round(v, 2)
        except ValueError:
            duty = None
    if r.mode == "mock" and duty is None:
        duty = 50.0
        txt = "MOCK duty 50.0"
    note = None
    if duty is None:
        note = (
            "未取到占空比。已知成因两类：一是 C:\\fc_pull 下的 .exe 会变坏档（ScopeCtl "
            "返回 OPEN_FAIL），需在台架机用 csc /platform:x64 当场重编；"
            "二是示波器被 MotorDebug 或遗留 powershell 独占。"
        )
    return _envelope(
        r.mode,
        status="ok" if duty is not None else "unavailable",
        channel=channel,
        signal="PWM1" if channel == 4 else f"CH{channel}",
        duty_percent=duty,
        raw=txt,
        note=note,
    )


def _read_pwm_local(channel: int) -> dict:
    """本机直连：用 pyvisa 发占空比测量 SCPI 读 PWM（默认 CH4）。"""
    try:
        scope = _ensure_local_scope()
    except RuntimeError as exc:
        return _envelope("unknown", status="unavailable", channel=channel,
                         duty_percent=None, raw="", note=str(exc))
    if not scope.connected:
        return _envelope(
            scope.mode, status="unavailable", channel=channel, duty_percent=None,
            raw="", note=scope.snapshot().get("last_error"),
        )
    try:
        raw = scope.query(f":MEASure:PDUTy? CHANnel{channel}")
    except Exception as exc:  # noqa: BLE001
        return _envelope(
            scope.mode, status="unavailable", channel=channel, duty_percent=None,
            raw="", note=f"读占空比失败：{type(exc).__name__}: {exc}",
        )
    duty = _parse_visa_float(raw)
    return _envelope(
        scope.mode,
        status="ok" if duty is not None else "unavailable",
        channel=channel,
        signal="PWM1" if channel == 4 else f"CH{channel}",
        duty_percent=round(duty, 2) if duty is not None else None,
        raw=raw,
        note=None if duty is not None else "示波器未测到有效占空比（无信号或探头未接）",
    )


@server.tool(
    name="capture_scope",
    title="抓示波器波形",
    description=(
        "从示波器深存储读逐点时序（电流 CH1 / FG1 CH2 / FG2 CH3 / PWM1 CH4）。"
        "默认只做 dry_run 返回计划与预估，不真抓——真抓一次约 20 到 25 秒、出约 100 MB CSV，"
        "且会独占示波器，必须由调用方显式把 dry_run 置 false。"
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False),
    meta={"group": "observation", "layer": "观测层", "guarded": False,
          "signals": ["CH1", "FG1", "FG2", "PWM1"]},
)
def capture_scope(
    channels: list[int] | None = None,
    time_per_div_s: float = 10.0,
    dry_run: bool = True,
) -> dict:
    """抓一段深存储波形。

    Args:
        channels: 要抓的通道，默认四通道全抓。
        time_per_div_s: 时基，10 秒每格对应 120 秒窗口、约 25 kSa/s。
        dry_run: 默认 true，只返回计划不真抓。
    """
    chans = channels or [1, 2, 3, 4]
    window_s = time_per_div_s * 12
    depth = 3_000_000
    plan = {
        "channels": chans,
        "time_per_div_s": time_per_div_s,
        "window_s": window_s,
        "assumed_depth_points": depth,
        "effective_sample_rate_sa_s": round(depth / window_s, 1),
        "tool": "pyvisa SCPI 直连" if LOCAL_MODE else config.DEEPCAPTURE4,
        "expected_csv_mb": round(depth * len(chans) * 8 / 1e6),
        "caveat": (
            "PWM 载波约 25 kHz，在 25 kSa/s 下只有 1 点/周期，看不了波形形状；"
            "要看载波须另开 1 ms/div 的高速短抓。"
        ),
    }
    if LOCAL_MODE:
        mode = LOCAL_SCOPE.mode
        if dry_run:
            return _envelope(mode, status="planned", executed=False, plan=plan)
        return _capture_scope_local(chans, plan)

    if dry_run:
        return _envelope(BENCH.mode, status="planned", executed=False, plan=plan)
    r = BENCH.exec(config.DEEPCAPTURE4, timeout=180)
    return _envelope(
        r.mode,
        status="ok" if r.rc == 0 else "failed",
        executed=True,
        plan=plan,
        rc=r.rc,
        stdout_tail=r.out[-2000:],
        stderr_tail=r.err[-1000:],
        elapsed_ms=r.elapsed_ms,
    )


def _capture_scope_local(chans: list[int], plan: dict) -> dict:
    """本机直连：逐通道用 pyvisa 读 RIGOL 深存储波形（RAW/BYTE 格式 + preamble）。

    RIGOL DS1000Z 波形读取序列：SOURce → MODE RAW → FORMat BYTE → PREamble? → DATA?。
    返回每通道的 preamble 与数据字节；数据量大（3M 点×4 通道≈12MB），真机到场后
    再按实际性能决定是否限制点数或落 CSV。本函数只做「读回来」，不落盘。
    """
    try:
        scope = _ensure_local_scope()
    except RuntimeError as exc:
        return _envelope("unknown", status="failed", executed=True, plan=plan, note=str(exc))
    if not scope.connected:
        return _envelope(
            scope.mode, status="failed", executed=True, plan=plan,
            note=scope.snapshot().get("last_error"),
        )

    results: list[dict] = []
    for ch in chans:
        try:
            scope.query(f":WAVeform:SOURce CHANnel{ch}")
            scope.query(":WAVeform:MODE RAW")
            scope.query(":WAVeform:FORMat BYTE")
            pre_raw = scope.query(":WAVeform:PREamble?")
            pre = [p for p in pre_raw.split(",")]
            data = _read_waveform_bytes(scope)
            results.append({
                "channel": ch,
                "preamble_raw": pre_raw,
                "points": len(data),
                "bytes": len(data),
            })
        except Exception as exc:  # noqa: BLE001
            results.append({
                "channel": ch,
                "error": f"{type(exc).__name__}: {exc}",
            })
    ok = all("error" not in r for r in results)
    return _envelope(
        scope.mode,
        status="ok" if ok else "failed",
        executed=True,
        plan=plan,
        channels=results,
        note="本机直连读取深存储波形；数据未落 CSV（落盘属报告/文件单元）",
    )


def _read_waveform_bytes(scope: LocalVisaBackend) -> bytes:
    """读 :WAVeform:DATA? 的返回，剥掉 IEEE488.2 #<n><len><bytes> 头，返回纯数据字节。"""
    return scope.query_binary(":WAVeform:DATA?")



@server.tool(
    name="tail_log",
    title="读软件运行日志",
    description=(
        "读台架机上 MotorDebug（原 Altior）的后端运行日志尾部。"
        "节点执行的真相在这里：预设命令完成、RIGOL 截图保存、SCPI 下发都会留痕。"
        "整屏只有 save_workflow_autosave 则说明工作流根本没在跑。"
    ),
    annotations=ToolAnnotations(readOnlyHint=True),
    meta={"group": "observation", "layer": "观测层", "guarded": False},
)
def tail_log(lines: int = 40, date: str | None = None) -> dict:
    """读日志尾部。

    Args:
        lines: 取最后多少行，1 到 500。
        date: 形如 2026-09-11；留空则取该目录下最新的一份。
    """
    n = max(1, min(int(lines), 500))
    if LOCAL_MODE:
        return _tail_log_local(n, date)
    if date:
        pick = f'$f=Get-Item -LiteralPath "{config.MOTORDEBUG_LOG_DIR}\\motordebug.{date}.log"'
    else:
        pick = (
            f'$f=Get-ChildItem -LiteralPath "{config.MOTORDEBUG_LOG_DIR}" -Filter *.log '
            f'| Sort-Object LastWriteTime -Descending | Select-Object -First 1'
        )
    # 日志正文是 UTF-8，但 Windows 控制台是 GBK，直接回显必乱码。
    # 办法是在远端把内容 base64 起来当纯 ASCII 传回，本地再解码，彻底绕开控制台编码。
    ps = (
        '$ProgressPreference="SilentlyContinue"; ' + pick + '; '
        'Write-Output ("LOGFILE:"+$f.FullName); '
        f'$t=(Get-Content -LiteralPath $f.FullName -Tail {n} -Encoding UTF8) -join "`n"; '
        'Write-Output ("B64:"+[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($t)))'
    )
    import base64
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    r = BENCH.exec(f"powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand {enc}")

    logfile, body = None, []
    for ln in r.out.splitlines():
        if ln.startswith("LOGFILE:"):
            logfile = ln[len("LOGFILE:"):].strip()
        elif ln.startswith("B64:"):
            try:
                body = base64.b64decode(ln[4:].strip()).decode("utf-8", "replace").splitlines()
            except Exception:  # noqa: BLE001
                body = [ln]
        elif r.mode == "mock":
            body.append(ln)
    return _envelope(
        r.mode,
        status="ok" if r.rc == 0 and body else "unavailable",
        logfile=logfile,
        line_count=len(body),
        lines=body,
        stderr_tail=r.err[-500:] or None,
    )


def _tail_log_local(n: int, date: str | None) -> dict:
    """本机直连：直接读本机 MotorDebug 日志文件（不经 SSH PowerShell）。"""
    import glob

    log_dir = config.MOTORDEBUG_LOG_DIR
    if date:
        target = f"{log_dir}\\motordebug.{date}.log"
    else:
        candidates = sorted(
            glob.glob(f"{log_dir}\\motordebug.*.log"),
            key=lambda p: __import__("os").path.getmtime(p),
            reverse=True,
        )
        target = candidates[0] if candidates else None
    if not target or not __import__("os").path.isfile(target):
        return _envelope(
            "unknown", status="unavailable", logfile=None, line_count=0, lines=[],
            stderr_tail=None,
            note=f"本机日志目录 {log_dir} 无日志文件（客户 MotorDebug 软件未在本机运行或路径不同）",
        )
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            body = f.read().splitlines()[-n:]
    except OSError as exc:
        return _envelope(
            "unknown", status="unavailable", logfile=target, line_count=0, lines=[],
            stderr_tail=None, note=f"读日志失败：{exc}",
        )
    return _envelope(
        "live", status="ok" if body else "unavailable",
        logfile=target, line_count=len(body), lines=body, stderr_tail=None,
    )


# ---------- 动作层（六个红线动作） ----------

def _action_result(tool: str, mode: str, detail: dict) -> dict:
    return _envelope(mode, status="ok", executed=True, tool=tool, **detail)


def _dispatch_dll(call):
    """执行一次 dll-bridge 真动作，返回 {"mode", "data"|"error"|"note"}。

    三态：
      - live   ：真下发成功，data 是 dll-bridge 的原始返回；
      - mock   ：DLL_BRIDGE_ALLOW_MOCK=1，返回合成反馈（仅演示，勿用于真机）；
      - unknown：缺文件 / 子进程启动失败 / DLL 调用失败，error 是一句可查的人话。
    绝不把失败静默降级成「电机已转」。
    """
    if config.DLL_BRIDGE_ALLOW_MOCK:
        return {
            "mode": "mock",
            "note": "DLL_BRIDGE_ALLOW_MOCK=1，动作层返回合成反馈（仅演示，勿用于真机）",
        }
    try:
        return {"mode": "live", "data": call()}
    except DllBridgeError as exc:
        return {"mode": "unknown", "error": str(exc)}


def _dll_failure(tool: str, args: dict, reason: str) -> dict:
    """动作层真下发失败/待接的统一返回：executed 仍为 True（确实尝试执行了），
    但 status=failed、mode=unknown，把「为什么没成」讲清楚。"""
    return _envelope(
        "unknown",
        status="failed",
        executed=True,
        tool=tool,
        args=args,
        reason=reason,
        how_to_proceed=(
            "真机测试需：① dll-bridge.exe 与 FTGeneralUtils.dll 就位；"
            "② 电机板经 SWD/HID 连本机；③ 板内固件已烧好（否则需现场提供 hex 走 download-code）。"
        ),
    )


@server.tool(
    name="start",
    title="启动电机（需人工确认）",
    description="启动被测电机。红线动作：无人工批准过的 confirm_token 一律拒绝执行。",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False),
    meta={"group": "action", "layer": "动作层", "guarded": True,
          "human_gate": "confirm_token", "risk": "物理后果：台架会真的转起来"},
)
def start(duty_percent: float = 50.0, duration_s: float = 30.0,
          confirm_token: str | None = None) -> dict:
    """启动电机（FreeRun）。duty_percent/duration_s 为前端遗留语义，DLL 无运行时
    写参数接口，真下发不消费它们（由固件内部控制），这里只如实记录。

    Args:
        duty_percent: PWM 占空比百分比（记录用，真下发走 FreeRun）。
        duration_s: 持续秒数（记录用）。
        confirm_token: 人工批准过的一次性凭据；没有就拒绝执行。
    """
    args = {"duty_percent": duty_percent, "duration_s": duration_s}
    blocked = _guard("start", args, confirm_token)
    if blocked:
        return blocked
    result = _dispatch_dll(lambda: get_client().free_run())
    if result["mode"] != "live":
        return _dll_failure("start", args, result.get("error") or result.get("note"))
    return _action_result("start", "live", {
        "args": args,
        "dispatch": {
            "target": "dll-bridge free-run",
            "main_addr": hex(config.DLL_BRIDGE_MAIN_ADDR),
            "sequence": "SetBreakPoint → EnterDebugMode → FreeRun",
            "ipc": result["data"],
            "note": (
                "FreeRun 已真下发，电机启动（FreeRun 在 dll-bridge worker 线程持续阻塞，"
                "直到收到 break-run）。duty_percent/duration_s 无法运行时下发"
                "（FTGeneralUtils.dll 无写单参数接口），由固件内部控制；如需按参数运行须"
                "走 GeneralMakeFiles→DownloadCode 编译烧录链（现场层，需固件工程 + hex）。"
            ),
        },
        "approved_token": confirm_token,
    })


@server.tool(
    name="stop",
    title="停止电机（需人工确认）",
    description="正常停止被测电机。红线动作，需人工批准过的 confirm_token。",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True),
    meta={"group": "action", "layer": "动作层", "guarded": True,
          "human_gate": "confirm_token", "risk": "改变被测对象运行状态"},
)
def stop(confirm_token: str | None = None) -> dict:
    blocked = _guard("stop", {}, confirm_token)
    if blocked:
        return blocked
    result = _dispatch_dll(lambda: get_client().break_run())
    if result["mode"] != "live":
        return _dll_failure("stop", {}, result.get("error") or result.get("note"))
    return _action_result("stop", "live", {
        "dispatch": {"target": "dll-bridge break-run", "ipc": result["data"]},
        "approved_token": confirm_token,
    })


@server.tool(
    name="estop",
    title="急停（需人工确认）",
    description=(
        "急停：立即切断驱动输出。红线动作，需人工批准过的 confirm_token。"
        "注意急停在权限模型里独立于常规三档权限，落地时应另有一条物理急停回路，"
        "软件急停只是补充、不能作为唯一手段。"
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True),
    meta={"group": "action", "layer": "动作层", "guarded": True,
          "human_gate": "confirm_token", "risk": "立即切断输出",
          "note": "软件急停不替代物理急停回路"},
)
def estop(reason: str = "", confirm_token: str | None = None) -> dict:
    """急停（软件急停 = BreakRun 立即中断 FreeRun）。

    Args:
        reason: 急停理由，会写进凭据历史。
        confirm_token: 人工批准过的一次性凭据。
    """
    args = {"reason": reason}
    blocked = _guard("estop", args, confirm_token)
    if blocked:
        return blocked
    result = _dispatch_dll(lambda: get_client().break_run())
    if result["mode"] != "live":
        return _dll_failure("estop", args, result.get("error") or result.get("note"))
    return _action_result("estop", "live", {
        "args": args,
        "dispatch": {
            "target": "dll-bridge break-run",
            "ipc": result["data"],
            "note": "软件急停已真下发（BreakRun）。物理急停回路另由现场保证，不由此软件接口承担。",
        },
        "approved_token": confirm_token,
    })


@server.tool(
    name="write_param",
    title="写回参数（需人工确认）",
    description="把控制参数写回驱动板。红线动作，需人工批准过的 confirm_token。",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False),
    meta={"group": "action", "layer": "动作层", "guarded": True,
          "human_gate": "confirm_token", "risk": "改变被测对象行为，且可能不可逆"},
)
def write_param(key: str, value: float, confirm_token: str | None = None) -> dict:
    """写一个参数。**如实说明**：FTGeneralUtils.dll 没有运行时「写单参数/寄存器」的
    导出函数（12 个导出函数里只有 ReadMemValue 读内存，无写寄存器），所以这个动作
    无法像 start/stop 那样单命令下发。参数变更只能走「改源码 → GeneralMakeFiles 编译 →
    DownloadCode 烧录 → FreeRun」整条链，需要固件工程与 hex —— 属现场层硬阻塞。

    这里不做假：返回「现场层待接」并讲清缺口，而不是 mode=mock 冒充「参数已写回」。

    Args:
        key: 参数名。
        value: 新值。
        confirm_token: 人工批准过的一次性凭据。
    """
    args = {"key": key, "value": value}
    blocked = _guard("write_param", args, confirm_token)
    if blocked:
        return blocked
    return _envelope(
        "unknown",
        status="failed",
        executed=True,
        tool="write_param",
        args=args,
        reason=(
            "FTGeneralUtils.dll 无运行时写单参数接口（12 个导出函数里只有 ReadMemValue 读内存，"
            "没有写寄存器函数），无法单命令写回。"
        ),
        how_to_proceed=(
            "参数变更需走 GeneralMakeFiles→DownloadCode 编译烧录链：需现场提供固件工程与 hex。"
            "代码层已就绪（dll-bridge 支持 download-code），只差固件产物；在此之前本动作如实待接。"
        ),
        approved_token=confirm_token,
    )


@server.tool(
    name="export",
    title="导出产物（需人工确认）",
    description="把本轮产物导出成对外交付文件。红线动作，需人工批准过的 confirm_token。",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False),
    meta={"group": "action", "layer": "动作层", "guarded": True,
          "human_gate": "confirm_token", "risk": "落盘成对外交付物"},
)
def export(run_id: str, fmt: str = "xlsx", confirm_token: str | None = None) -> dict:
    """导出一轮产物。真实报告文件由后端报告链路生成（write-file-rust.exe），
    桥的 export 不再重复造一份，如实指向报告下载端点。

    Args:
        run_id: 轮次标识。
        fmt: 导出格式。
        confirm_token: 人工批准过的一次性凭据。
    """
    args = {"run_id": run_id, "fmt": fmt}
    blocked = _guard("export", args, confirm_token)
    if blocked:
        return blocked
    return _action_result("export", "live", {
        "args": args,
        "dispatch": {
            "target": "后端报告链路（write-file-rust.exe）",
            "download": f"GET /api/reports/{run_id}/download",
            "note": (
                "报告文件由后端 reports.py 真调用 write-file-rust.exe 生成，"
                "下载走报告端点；桥的 export 不再重复落盘一份。"
            ),
        },
        "approved_token": confirm_token,
    })


@server.tool(
    name="archive",
    title="归档本轮（需人工确认）",
    description="把本轮结果写入存档。红线动作，需人工批准过的 confirm_token。",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False),
    meta={"group": "action", "layer": "动作层", "guarded": True,
          "human_gate": "confirm_token", "risk": "写入不可随意回退的存档"},
)
def archive(run_id: str, note: str = "", confirm_token: str | None = None) -> dict:
    """归档一轮结果。真实归档由知识库链路负责（kb_convert_service 落 kb_entries），
    桥的 archive 仅做标记，不重复写库。

    Args:
        run_id: 轮次标识。
        note: 归档备注。
        confirm_token: 人工批准过的一次性凭据。
    """
    args = {"run_id": run_id, "note": note}
    blocked = _guard("archive", args, confirm_token)
    if blocked:
        return blocked
    return _action_result("archive", "live", {
        "args": args,
        "dispatch": {
            "target": "知识库归档链路（kb_convert_service → kb_entries）",
            "note": "归档由知识库链路落库，桥的 archive 仅做标记，不重复写库。",
        },
        "approved_token": confirm_token,
    })


# ---------- 入口 ----------

def main() -> None:
    ap = argparse.ArgumentParser(description="device-bench MCP server")
    ap.add_argument("--transport", default="stdio",
                    choices=["stdio", "streamable-http", "sse"])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("MCP_HTTP_PORT", "8032")))
    a = ap.parse_args()
    if a.transport == "stdio":
        server.run(transport="stdio")
    else:
        # mcp 2.x 把 host/port 作为 run 的关键字参数传，不再挂在 settings 上
        server.run(transport=a.transport, host=a.host, port=a.port)


if __name__ == "__main__":
    main()
