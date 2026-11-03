"""依赖检查（对应原 check-dependencies.ps1）。

检查：Python 版本、可用串口、pyvisa/pyvisa-py 可加载、pyvisa-py 能否枚举资源。
输出单行 JSON（对齐原字段：ready/missing/availableSerialPorts/configuredPort 等）。
不做任何硬件打开动作（只探测）。

2026-10-07 修复：
- 默认配置路径由不存在的 hardware/py/config/experiment.json 改为
  hardware/v0.6/config/acceptance.json（与后端 fan_executor.py 一致），
  并在输出里回显实际使用的 configPath 与 overlay 状态。
- 新增 showAllResources 双后端诊断：除默认 @py 后端外，额外尝试 @ivi（NI-VISA），
  便于判断「示波器枚举不到」是驱动/后端问题还是资源名问题。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import usb_env  # noqa: E402

# 必须在任何 import pyvisa / pyusb 之前预置 libusb 后端
usb_env.ensure_usb_backend()

import runtime  # noqa: E402
import scope_visa  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(os.path.dirname(HERE), "v0.6", "config", "acceptance.json")


def _enum_backend(backend: str) -> dict:
    """枚举单个 VISA 后端（@py / @ivi）的可见资源，返回诊断信息不抛错。"""
    info: dict = {"backend": backend, "ok": False, "resources": [], "error": None}
    try:
        import pyvisa
        rm = pyvisa.ResourceManager(backend)
        try:
            info["resources"] = list(rm.list_resources())
        finally:
            rm.close()
        info["ok"] = True
    except Exception as e:  # noqa: BLE001
        info["error"] = str(e)
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-ConfigPath", "--config", default="")
    args = ap.parse_args()
    explicit = bool(args.config)
    config_path = args.config or DEFAULT_CONFIG

    missing: list[str] = []
    ports: list[str] = []
    visa_loadable = False
    visa_resources: list[str] = []
    configured_port = None
    configured_resource = None
    scope_enabled = None

    try:
        import serial.tools.list_ports as list_ports
        ports = [p.device for p in list_ports.comports()]
    except Exception as e:  # noqa: BLE001
        missing.append(f"pyserial not available: {e}")

    # 默认后端按平台判定（2026-10-08 改）：Windows=@ivi(NI-VISA) / 其它=@py(pyvisa-py)。
    # 与 scope_visa._default_backend() 保持一致，避免此处诊断口径与实际采集不符。
    backend = os.environ.get("SCOPE_VISA_BACKEND") or scope_visa._default_backend()
    try:
        import pyvisa
        rm = pyvisa.ResourceManager(backend)
        visa_loadable = True
        try:
            visa_resources = list(rm.list_resources())
        finally:
            rm.close()
    except Exception as e:  # noqa: BLE001
        missing.append(f"pyvisa/pyvisa-py not loadable: {e}")

    # 双后端诊断：默认后端枚举不到任何 USB 资源时，追加另一后端的结果，便于定位。
    backends_diag = [_enum_backend(backend)]
    if not any(str(r).upper().startswith("USB") for r in visa_resources):
        other = "@ivi" if backend != "@ivi" else "@py"
        backends_diag.append(_enum_backend(other))

    try:
        loaded = runtime.read_experiment_config(config_path, allow_overlay=not explicit)
        configured_port = loaded.config["serial"]["port"]
        configured_resource = loaded.config["scope"].get("resource") or ""
        scope_enabled = loaded.config["scope"]["enabled"]
    except Exception as e:  # noqa: BLE001
        missing.append(f"config invalid: {e}")

    if configured_port and ports and configured_port not in ports:
        missing.append("Configured serial port absent; confirm COM/device path and driver")

    result = {
        "schemaVersion": "1.0",
        "action": "dependency_check",
        "ready": len(missing) == 0,
        "pythonVersion": sys.version.split()[0],
        "is64Bit": sys.maxsize > 2**32,
        "configPath": os.path.realpath(config_path),
        "overlayApplied": (not explicit) and bool(os.environ.get("FAN_CONFIG_PATH")),
        "visaBackend": backend,
        "usbEnvStrategy": usb_env.ensure_usb_backend(),
        "availableSerialPorts": ports,
        "configuredPort": configured_port,
        "configuredScopeResource": configured_resource,
        "pyvisaLoadable": visa_loadable,
        "visaResources": visa_resources,
        "visaBackends": backends_diag,
        "scopeEnabled": scope_enabled,
        "missing": missing,
        "hardwareOpened": False,
        "note": ("Presence check only; does not identify board or verify scope/wiring. "
                 "Empty configuredScopeResource means auto-enumerate by VID/PID at runtime."),
    }
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
