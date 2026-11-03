#!/usr/bin/env python3
"""示波器链路最小探测（Linux/Windows 通用）。

用途：改任何采集逻辑**之前**先跑这个，确认「硬件 → 驱动 → 协议」三层哪一层通。
不依赖项目其它模块，可单独执行。

    python scope_link_probe.py

退出码：0=通；1=枚举不到；2=枚举到但打不开；3=通信超时。
"""
from __future__ import annotations

import os
import sys
import time

# 与 scope_visa.py 保持一致
RIGOL_VID = 0x1AB1
DS1000Z_PID = 0x04CE

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usb_env  # noqa: E402


def _rule(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def main() -> int:
    _rule("① 环境")
    print(f"平台        : {sys.platform}")
    print(f"Python      : {sys.version.split()[0]}")
    print(f"libusb 策略 : {usb_env.ensure_usb_backend()}")

    try:
        import usb.core
    except ImportError:
        print("✗ 未安装 pyusb，无法走 USB 通路")
        return 1

    _rule("② 设备枚举（libusb / sysfs）")
    found = False
    for dev in usb.core.find(find_all=True):
        try:
            vid, pid = dev.idVendor, dev.idProduct
        except Exception:  # noqa: BLE001
            continue
        if (vid, pid) == (RIGOL_VID, DS1000Z_PID):
            print(f"✓ 找到 RIGOL 示波器: {dev}")
            found = True
        elif (vid, pid) == (0x1A86, 0x7523):
            print(f"· 风扇 CH340 也在: {dev}")
    if not found:
        print("✗ 未枚举到 RIGOL DS1104Z（VID 1ab1 / PID 04ce）")
        print("  检查：lsusb | grep 1ab1 ；设备是否插好；容器是否挂了 /dev/bus/usb")
        return 1

    _rule("③ 内核驱动解绑（libusb 独占的前提）")
    detached = usb_env.detach_kernel_drivers(RIGOL_VID, DS1000Z_PID)
    print(f"解绑接口数: {detached}")
    if detached == 0:
        print("· 无内核驱动占用或已解绑（Windows 正常；Linux 若为 0 可能已被手动解绑）")

    _rule("④ VISA 资源枚举")
    try:
        import pyvisa
    except ImportError:
        print("✗ 未安装 pyvisa")
        return 1
    try:
        rm = pyvisa.ResourceManager(os.environ.get("SCOPE_VISA_BACKEND", "@py"))
    except Exception as e:  # noqa: BLE001
        print(f"✗ ResourceManager 创建失败: {e}")
        return 2
    resources = list(rm.list_resources())
    if not resources:
        print("✗ 枚举结果为空")
        return 1
    for r in resources:
        print(f"  · {r}")
    usb_res = [r for r in resources if r.upper().startswith("USB")]
    if not usb_res:
        print("✗ 只有串口资源，没有 USB → 示波器未被识别")
        return 1
    target = usb_res[0]
    print(f"\n选用资源: {target}")

    _rule("⑤ 打开会话")
    try:
        inst = rm.open_resource(target)
        inst.timeout = 8000
        inst.read_termination = None
        inst.write_termination = "\n"
        print("✓ 已打开")
    except Exception as e:  # noqa: BLE001
        print(f"✗ 打开失败: {type(e).__name__}: {e}")
        rm.close()
        return 2

    _rule("⑥ SCPI 通信（*IDN?）")
    try:
        inst.clear()
    except Exception:  # noqa: BLE001
        pass
    try:
        idn = inst.query("*IDN?").strip()
        print(f"✓ *IDN? → {idn}")
    except Exception as e:  # noqa: BLE001
        print(f"✗ 通信失败: {type(e).__name__}: {e}")
        if not usb_env.is_timeout_error(e):
            print("  非超时类错误，按驱动/权限问题排查")
        else:
            port = usb_env.find_usb_sysfs_path(RIGOL_VID, DS1000Z_PID)
            print("  设备卡死（USB 控制器不响应）。执行软复位后重试：")
            print(f"    sudo bash /srv/omnitest/c/hardware/py/usb_reset.sh {port or '<bus-port>'}")
        try:
            inst.close()
        except Exception:  # noqa: BLE001
            pass
        rm.close()
        return 3

    _rule("⑦ 常用子命令抽查")
    for cmd in (":MODEL?", ":FIRMWARE?", "*OPC?"):
        try:
            print(f"  {cmd:<12} → {inst.query(cmd).strip()}")
        except Exception as e:  # noqa: BLE001
            print(f"  {cmd:<12} ✗ {type(e).__name__}")
        time.sleep(0.05)

    try:
        inst.close()
    except Exception:  # noqa: BLE001
        pass
    rm.close()
    print("\n✓ 示波器链路完全可用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
