"""动作层真下发·失败路径验证脚本。

无真机 / 无 dll-bridge.exe 时，动作层必须如实报错，**绝不 mode=mock 假装「电机已转」**。
本脚本不碰真机，只验三条契约：
  1. 红线闸口：无 confirm_token 拒绝、假 confirm_token 拒绝。
  2. 无 dll-bridge.exe 时 start 如实返回 status=failed + mode=unknown + 可查 reason。
  3. write_param 如实标「现场层待接」（FTGeneralUtils.dll 无运行时写单参数接口）。

运行（需 bridge 环境，因 server.py 依赖 mcp）：
    cd c/components/spike-device-mcp
    <bridge python> -m device_bench._verify_action
"""
from __future__ import annotations

import sys

from . import config
from . import dll_bridge
from . import server
from .confirm import REGISTRY

_FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        _FAILED.append(name)


def _approve(tool: str, args: dict) -> str:
    """签发并人工批准一张凭据，返回 confirm_token。"""
    t = REGISTRY.issue(tool, args, f"验证 {tool}")
    REGISTRY.approve(t.token, "verify-script", "human_pin")
    return t.token


def main() -> int:
    # 1. 红线闸口：无 token 拒绝执行
    r = server.start(duty_percent=50.0, duration_s=30.0)
    check(
        "start 无 confirm_token 拒绝执行",
        r.get("status") == "confirmation_required" and r.get("executed") is False,
        f"status={r.get('status')} executed={r.get('executed')}",
    )

    # 2. 红线闸口：假 token 拒绝执行
    r = server.start(duty_percent=50.0, duration_s=30.0, confirm_token="ct_forged")
    check("start 假 confirm_token 拒绝执行", r.get("status") == "confirmation_invalid",
          f"status={r.get('status')}")

    # 3. 无 dll-bridge.exe 时 start 如实报 failed/unknown
    saved_exe = config.DLL_BRIDGE_EXE
    dll_bridge._CLIENT = None  # 重置单例，让它下次用临时 config 重建
    config.DLL_BRIDGE_EXE = r"Z:\nonexistent\dll-bridge.exe"
    try:
        tok = _approve("start", {"duty_percent": 50.0, "duration_s": 30.0})
        r = server.start(duty_percent=50.0, duration_s=30.0, confirm_token=tok)
        check("无 exe 时 start 如实报 failed", r.get("status") == "failed",
              f"status={r.get('status')}")
        check("无 exe 时 mode=unknown（不降级 mock）", r.get("mode") == "unknown",
              f"mode={r.get('mode')}")
        check("无 exe 时 reason 指名缺 dll-bridge.exe", "dll-bridge.exe" in str(r.get("reason", "")),
              f"reason={r.get('reason')}")
        check("无 exe 时 executed=True（确实尝试了，不是假成功）",
              r.get("executed") is True, f"executed={r.get('executed')}")
    finally:
        config.DLL_BRIDGE_EXE = saved_exe
        dll_bridge._CLIENT = None

    # 4. write_param 如实标现场层（DLL 无写单参数接口）
    tok = _approve("write_param", {"key": "ALIGN_CURRENT", "value": 0.6})
    r = server.write_param(key="ALIGN_CURRENT", value=0.6, confirm_token=tok)
    check("write_param 如实标现场层待接", r.get("status") == "failed",
          f"status={r.get('status')}")
    check("write_param reason 指明无运行时写单参数接口",
          "无运行时写单参数" in str(r.get("reason", "")), f"reason={r.get('reason')}")

    # 5. DllBridgeClient 直接：无 exe 时 _ensure_started 抛 DllBridgeError（不静默）
    from .dll_bridge import DllBridgeClient, DllBridgeError
    try:
        DllBridgeClient(exe_path=r"Z:\nonexistent\dll-bridge.exe")._ensure_started()
        check("DllBridgeClient 无 exe 抛 DllBridgeError", False, "未抛异常")
    except DllBridgeError as exc:
        check("DllBridgeClient 无 exe 抛 DllBridgeError", "dll-bridge.exe" in str(exc),
              f"exc={exc}")

    print()
    if _FAILED:
        print(f"FAILED {len(_FAILED)} 项：{', '.join(_FAILED)}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
