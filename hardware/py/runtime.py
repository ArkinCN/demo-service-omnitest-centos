"""配置校验 + 事件/state 原子发布（Python 重写，对应原 src/Runtime.psm1）。

与原 PowerShell 版行为对齐点：
- Read-ExperimentConfig：逐字段校验（schemaVersion/serial/experiment/output/scope），
  校验口径与原 Runtime.psm1 **逐条对应**，一个字都不放松（除串口端口正则跨平台放宽）。
- Write-RunEvent：事件行同时写 events.jsonl（追加，权威）与 stdout；
  state.json 用临时文件 + 原子替换（os.replace）。
- 所有 JSON 用 UTF-8 无 BOM；时间戳 ISO8601 UTC（含微秒）。

跨平台改动（唯一）：
- serial.port 原强制 `^COM[1-9][0-9]*$`（Windows 专属）。改为平台感知：
  Windows 允许 COMx；POSIX 允许 /dev/tty*；同时保留对原 COM 式的兼容。
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 时间戳：对齐 DateTimeOffset.UtcNow.ToString("o")（含微秒、+00:00）
# ---------------------------------------------------------------------------
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 端口名校验（跨平台）
# ---------------------------------------------------------------------------
_COM_RE = re.compile(r"^COM[1-9][0-9]*$")
_POSIX_SERIAL_RE = re.compile(r"^/dev/(tty(USB|ACM|S|AMA)\d*|serial/by-id/[^/]+|serial/by-path/[^/]+)$")


def is_valid_serial_port(port: str) -> bool:
    """串口端口名是否合法（跨平台）。

    Windows：COM1..COMn；POSIX：/dev/ttyUSB0、/dev/ttyACM0、/dev/serial/by-id/... 等。
    同时为测试/演示保留对纯占位端口（如 COM1）的兼容。
    """
    if not port or not isinstance(port, str):
        return False
    if _COM_RE.match(port):
        return True
    if _POSIX_SERIAL_RE.match(port):
        return True
    # 允许 Windows 上 pyserial 接受的 '\\.\COM10' 形式
    if port.startswith("\\\\.\\COM") or port.startswith("//./COM"):
        return True
    return False


# ---------------------------------------------------------------------------
# 配置读取与校验
# ---------------------------------------------------------------------------
@dataclass
class LoadedConfig:
    config: dict
    path: str
    output_root: str


class ConfigError(ValueError):
    """配置不合法（对应原 PowerShell 的 throw）。"""


# ---------------------------------------------------------------------------
# overlay 合并（2026-10-07 新增）
#
# 目的：主配置只维护「跨机器不变」的公共字段（实验计划/通道定义/探头倍率等），
# 随机器变化的少数字段（serial.port / scope.resource）留空，由 overlay 文件
# 按环境覆盖。切换只需设环境变量 FAN_CONFIG_PATH 指向对应 overlay。
#
# 生效范围（重要）：overlay **只在调用方未显式指定配置路径时**生效（即走默认
# 主配置的场景）。显式传 -ConfigPath 的调用完全按该文件走，不叠加 overlay——
# 这样 run_scope.py 的「写入临时配置再读」隔离测试不会被 FAN_CONFIG_PATH 污染。
#
# 合并优先级（后者覆盖前者，深合并）：
#   默认主配置 acceptance.json  <  overlay(FAN_CONFIG_PATH)  <  精细环境变量
# 精细环境变量：FAN_SERIAL_PORT / FAN_SCOPE_RESOURCE（临时救急，优先级最高）。
# ---------------------------------------------------------------------------
def _deep_merge(base: Any, overlay: Any) -> Any:
    """递归深合并：dict 逐键递归，其余类型 overlay 值直接覆盖 base 值。"""
    if isinstance(base, dict) and isinstance(overlay, dict):
        merged = dict(base)
        for key, value in overlay.items():
            if key in merged:
                merged[key] = _deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged
    # 非 dict（含 overlay 显式置 null/空串）→ 以 overlay 为准
    return overlay


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _apply_overlay(cfg: dict, overlay_path: str) -> dict:
    """把 overlay 文件深合并进主配置（只在默认路径场景调用）。"""
    overlay = _read_json(overlay_path)
    return _deep_merge(cfg, overlay)


def _apply_env_overrides(cfg: dict) -> dict:
    """精细环境变量覆盖：优先级最高，用于现场临时救急（不改文件）。"""
    port = os.environ.get("FAN_SERIAL_PORT")
    if port:
        cfg.setdefault("serial", {})["port"] = port
    resource = os.environ.get("FAN_SCOPE_RESOURCE")
    if resource is not None and resource != "":
        cfg.setdefault("scope", {})["resource"] = resource
    return cfg


def _assert_bool(value: Any, name: str) -> None:
    if not isinstance(value, bool):
        raise ConfigError(f"{name} must be JSON true or false.")


def _assert_number(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} must be a JSON number.")
    if value != value or value in (float("inf"), float("-inf")):  # NaN/Inf
        raise ConfigError(f"{name} must be finite.")


def _get(d: dict, key: str, where: str) -> Any:
    if not isinstance(d, dict) or key not in d:
        raise ConfigError(f"{where}.{key} is required.")
    return d[key]


def read_experiment_config(path: str | os.PathLike[str], *, allow_overlay: bool = True) -> LoadedConfig:
    """读并校验配置。校验口径对应原 Read-ExperimentConfig，逐条对应。

    allow_overlay（2026-10-07 新增）：是否允许叠加 overlay。
    - 调用方**未显式传 -ConfigPath**（走默认主配置）时，保持 True：
      主配置 → 深合并 FAN_CONFIG_PATH 指向的 overlay → 应用 FAN_SERIAL_PORT /
      FAN_SCOPE_RESOURCE 环境变量 → 再校验。
    - 调用方**显式传路径**（含 run_scope.py 的临时隔离配置）时，调用点传
      allow_overlay=False，完全按该文件走，不被环境变量污染。

    合并发生在校验**之前**，因此主配置可把随机器变化的 serial.port /
    scope.resource 留空，由 overlay/环境变量补齐后再过校验。
    """
    resolved = os.path.realpath(os.fspath(path))
    cfg = _read_json(resolved)
    if allow_overlay:
        overlay_path = os.environ.get("FAN_CONFIG_PATH")
        if overlay_path:
            overlay_resolved = os.path.realpath(overlay_path)
            # 防呆：overlay 与主配置是同一文件时不重复合并
            if overlay_resolved != resolved and os.path.isfile(overlay_resolved):
                cfg = _apply_overlay(cfg, overlay_resolved)
        cfg = _apply_env_overrides(cfg)

    if cfg.get("schemaVersion") != "1.0":
        raise ConfigError("Unsupported config schemaVersion.")

    serial = cfg.get("serial") or {}
    _assert_bool(serial.get("wiringConfirmed"), "serial.wiringConfirmed")
    _assert_number(serial.get("baud"), "serial.baud")

    exp = cfg.get("experiment") or {}
    for key in ("cycles", "holdSeconds", "settleSeconds"):
        _assert_number(_get(exp, key, "experiment"), f"experiment.{key}")
    duties = exp.get("dutiesPercent")
    if not isinstance(duties, list) or len(duties) == 0:
        raise ConfigError("dutiesPercent must be a nonempty JSON array.")
    for d in duties:
        _assert_number(d, "dutiesPercent item")
    # 每档连续采集次数与采集间隔（2026-10-09 新增，可选）。
    # 为什么需要：真机原先每档只采 1 次 → 一轮仅 4 个样本点，趋势图上点间连成
    # 斜线、看不出随时间变化。改为每档连续采多次后，样本沿真实时间轴铺开。
    # 兼容性：为**可选**字段，缺省用默认值（5 / 0.5），旧配置不改也能加载。
    cps = exp.get("capturesPerStep", 5)
    if not isinstance(cps, (int, float)) or isinstance(cps, bool) or cps < 1 or cps != int(cps) or cps > 1000:
        raise ConfigError("capturesPerStep must be an integer 1..1000.")
    cis = exp.get("captureIntervalSeconds", 0.5)
    if not isinstance(cis, (int, float)) or isinstance(cis, bool) or cis < 0 or cis > 3600:
        raise ConfigError("captureIntervalSeconds must be a number 0..3600.")

    scope = cfg.get("scope") or {}
    _assert_bool(scope.get("enabled"), "scope.enabled")

    output = cfg.get("output") or {}
    root = output.get("root")
    if not isinstance(root, str) or not root:
        raise ConfigError("output.root must be a nonempty path.")

    # 串口端口（跨平台放宽）+ 波特率/身份（与原口径一致，身份固定）
    # 支持「主配置留空 + overlay/环境变量补齐」范式：合并后仍为空则报错，
    # 错误信息明确提示该设 FAN_CONFIG_PATH 或 FAN_SERIAL_PORT，便于现场定位。
    port = serial.get("port")
    if not port:
        raise ConfigError(
            "serial.port is empty after overlay merge; set FAN_CONFIG_PATH to an "
            "overlay (acceptance.windows.json / acceptance.linux.json) or set "
            "FAN_SERIAL_PORT (e.g. COM3 on Windows, /dev/ttyUSB0 on Linux)."
        )
    if not is_valid_serial_port(port):
        raise ConfigError(
            "serial.port must be COMx (Windows) or /dev/tty* (POSIX); got: %r" % (port,)
        )
    if serial.get("baud") != 115200:
        raise ConfigError("Only the verified UNO_FAN_V2 115200 transport is supported.")
    if serial.get("expectedIdentity") != "READY UNO_FAN_V2 25000":
        raise ConfigError("Only the verified UNO_FAN_V2 115200 transport is supported.")
    if not serial.get("wiringConfirmed"):
        raise ConfigError("Confirm physical wiring in config before opening serial.")

    cyc = exp.get("cycles")
    if cyc < 0 or cyc != int(cyc) or cyc > 1000000:
        raise ConfigError("cycles must be an integer 0..1000000; 0 means continuous.")
    hold = exp.get("holdSeconds")
    settle = exp.get("settleSeconds")
    if hold < 0.1 or hold > 3600 or settle < 0 or settle >= hold:
        raise ConfigError("Invalid hold or settle timing.")
    for d in duties:
        if d < 0 or d > 100 or d != int(d):
            raise ConfigError("Duty values must be integer percentages 0..100.")

    if scope.get("enabled"):
        for key in ("inputImpedanceOhm", "pwmTimebaseSecondsPerDiv", "triggerLevelV"):
            _assert_number(_get(scope, key, "scope"), f"scope.{key}")
        # scope.resource 允许为空串：空 = 触发 ScopeDevice 自动枚举（按 VID/PID 匹配）。
        # 这样 Linux 上（pyvisa-py 枚举格式与 Windows 不同）无需写死资源名，
        # 避免「换个机器资源名就变」的坑；非空则严格按该资源名打开。
        if (
            not scope.get("expectedIdentity")
            or scope.get("inputImpedanceOhm") != 1000000
        ):
            raise ConfigError("Scope identity and fixed 1MOhm setting are required.")
        if scope["pwmTimebaseSecondsPerDiv"] <= 0 or scope["pwmTimebaseSecondsPerDiv"] > 0.00005:
            raise ConfigError("PWM capture timebase must retain 25kHz detail.")

        seen: list[int] = []
        chans = scope.get("channels") or {}
        for role in ("current", "voltage", "pwm"):
            ch = _get(chans, role, "scope.channels")
            for key in ("channel", "probeRatio", "scaleVoltsPerDiv", "offsetV"):
                _assert_number(_get(ch, key, "channels"), f"{role}.{key}")
            _assert_bool(ch.get("physicalProbeRatioConfirmed"), f"{role}.physicalProbeRatioConfirmed")
            c = ch["channel"]
            if c < 1 or c > 4 or c != int(c) or c in seen:
                raise ConfigError("Channel mapping must contain unique channel numbers 1..4.")
            seen.append(c)
            if ch.get("coupling") != "DC" or ch.get("probeRatio") not in (1, 10, 100) or ch["scaleVoltsPerDiv"] <= 0:
                raise ConfigError("Invalid channel coupling/probe ratio/scale.")
        if chans["current"]["probeRatio"] != 1:
            raise ConfigError("Current clamp raw voltage requires scope probeRatio 1.")

        cc = scope.get("currentConversion") or {}
        for key in ("enabled", "lowRangeConfirmed", "zeroConfirmed", "singleConductorConfirmed"):
            _assert_bool(_get(cc, key, "currentConversion"), f"currentConversion.{key}")
        for key in ("gainAmpsPerVolt", "turns", "minimumSpecifiedCurrentA"):
            _assert_number(_get(cc, key, "currentConversion"), f"currentConversion.{key}")
        if cc["enabled"] and (
            not cc["lowRangeConfirmed"]
            or not cc["zeroConfirmed"]
            or not cc["singleConductorConfirmed"]
            or cc["turns"] < 1
            or cc["turns"] != int(cc["turns"])
            or cc["gainAmpsPerVolt"] <= 0
        ):
            raise ConfigError(
                "Current conversion requires valid turns/gain and range/zero/single-conductor confirmation."
            )

        t = scope.get("tach") or {}
        for key in ("enabled", "wiringConfirmed", "physicalProbeRatioConfirmed"):
            _assert_bool(_get(t, key, "tach"), f"tach.{key}")
        if t["enabled"]:
            for key in (
                "channel", "supplyVoltageV", "outputVoltageV", "probeRatio",
                "timebaseSecondsPerDiv", "scaleVoltsPerDiv", "triggerLevelV",
            ):
                _assert_number(_get(t, key, "tach"), f"tach.{key}")
            if t["channel"] != int(t["channel"]) or t["supplyVoltageV"] <= 0:
                raise ConfigError("Tach channel must be integer and supplyVoltageV must be positive.")
            if t.get("pulsesPerRevolution") is not None:
                _assert_number(t["pulsesPerRevolution"], "tach.pulsesPerRevolution")
            if (
                t["channel"] < 1 or t["channel"] > 4 or t["channel"] in seen
                or not t["wiringConfirmed"] or not t["physicalProbeRatioConfirmed"]
                or not t.get("sensorModel") or not t.get("signalWire") or not t.get("outputType")
                or t["supplyVoltageV"] is None or t["outputVoltageV"] is None
                or t["outputVoltageV"] <= 0 or t["probeRatio"] not in (1, 10, 100)
                or t["scaleVoltsPerDiv"] <= 0 or t["triggerLevelV"] is None
                # ⚠️ 2026-10-12 下限从 0.01 放宽到 0.005（10ms/div → 5ms/div）：
                #   原因：Linux + NI-VISA(@ivi) 下实测 **≥10ms/div 一律读不到波形**
                #   （preamble 全 0；NORM/PEAK/AVERages/HRESolution 四种采集模式、
                #   NORM/MAXimum/RAW 三种波形模式、多种触发电平与触发源都试过全失败）。
                #   时基扫描实测：0.1~5ms/div 全部可读，10/20/50ms/div 全部 0 点。
                #   故可用上限是 5ms/div —— 原下限 0.01 会让 tach 配置**永远无法通过校验**，
                #   转速与 CH4 波形永远没有数据（这正是用户反馈的问题）。
                #   代价：窗口从 0.6s（50ms/div×12）缩到 0.06s（5ms/div×12），
                #   低转速档（周期 >30ms）可能装不满一个周期 → 由 PULSE_MIN_COUNT 放宽配合。
                #   历史对照：Windows + 同版 NI-VISA 下 50ms/div 曾正常
                #   （probe_ch4_008 实测 rpm=2142.86、21 个脉冲），故属 Linux 特有约束。
                or t["timebaseSecondsPerDiv"] < 0.005 or t["timebaseSecondsPerDiv"] > 0.1
            ):
                raise ConfigError(
                    "Tach requires verified sensor wiring/output/probe settings and an "
                    "independent 5..100ms/div capture (下限 5ms/div：Linux 下更慢的时基"
                    "无法通过 USB 读出波形，详见 runtime.py 注释)."
                )
            if t.get("pulsesPerRevolution") is not None and (
                t["pulsesPerRevolution"] <= 0 or t["pulsesPerRevolution"] != int(t["pulsesPerRevolution"])
            ):
                raise ConfigError("PPR must be positive integer or null (frequency only).")

    # output.root：绝对则取绝对，相对则相对配置文件目录解析
    if os.path.isabs(root):
        output_root = os.path.realpath(root)
    else:
        output_root = os.path.realpath(os.path.join(os.path.dirname(resolved), root))

    return LoadedConfig(config=cfg, path=resolved, output_root=output_root)


# ---------------------------------------------------------------------------
# 事件发布（对齐 Write-RunEvent）
# ---------------------------------------------------------------------------
_state_lock = threading.Lock()


def write_run_event(
    run_id: str,
    directory: str | os.PathLike[str],
    sequence: int,
    event_type: str,
    state: str,
    data: Any,
) -> dict:
    """写一条事件：append events.jsonl（权威）+ stdout；state.json 原子更新。"""
    directory = os.fspath(directory)
    event = {
        "schemaVersion": "1.0",
        "runId": run_id,
        "sequence": sequence,
        "timestampUtc": utc_now_iso(),
        "type": event_type,
        "state": state,
        "data": data,
    }
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(directory, "events.jsonl"), "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")
    try:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except Exception:  # stdout 消费者不可用不致命，events.jsonl 才是权威
        sys.stderr.write("stdout consumer unavailable; events.jsonl remains authoritative.\n")

    # state.json 原子替换（对齐原 File.Replace/Move 重试语义）
    state_path = os.path.join(directory, "state.json")
    with _state_lock:
        fd, tmp = tempfile.mkstemp(prefix="state.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(line)
            os.replace(tmp, state_path)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"Could not update derived state.json: {e}\n")
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
    return event
