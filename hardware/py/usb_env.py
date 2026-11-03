"""USB/VISA 依赖环境预置（2026-10-08 新增）。

背景（实测根因）：
- 示波器 USB-TMC 走 pyvisa-py 的 USB 后端，底层是 pyusb。
- pyusb 通过 `ctypes.util.find_library("libusb-1.0")` 定位 libusb-1.0.dll。
- 在 Windows + conda 环境里，libusb-1.0.dll 位于 `<env>\Library\bin\`，**默认不在 PATH**。
- 一旦找不到该 DLL，pyusb 会**静默退化**到旧的 libusb0 后端（libusb0.dll），
  用错 USB API 导致 `claim_interface` 失败 → 表现为「能枚举到设备却打不开」。
- pyvisa_py.usb 在 **import 时**就探测并固定后端，因此本函数**必须在 import pyvisa 之前**调用。

解决：在 import pyvisa/pyusb 之前，
  ① 尝试 `import libusb_package`（自带 libusb-1.0.dll，最可靠）；
  ② 否则把 conda `<env>\Library\bin`（或系统常见路径）前置进 os.environ["PATH"]。

幂等、无副作用；失败时不抛错（由上层如实报枚举错误）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_APPLIED = False


def _candidate_dll_dirs() -> list[str]:
    """libusb-1.0.dll 可能所在的目录（按可靠性排序）。"""
    dirs: list[str] = []
    # conda 环境：<env>\Library\bin（pyusb/win 版 libusb 常在此）
    exe_dir = Path(sys.executable).resolve().parent
    dirs.append(str(exe_dir / "Library" / "bin"))
    # venv 的 Scripts 同级 Library\bin（部分布局）
    dirs.append(str(exe_dir.parent / "Library" / "bin"))
    # 常见系统位置
    dirs.append(r"C:\Windows\System32")
    return dirs


def _try_libusb_package() -> bool:
    """优先用 libusb_package（自带 DLL，无需改 PATH）。成功返回 True。"""
    try:
        import libusb_package  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def ensure_usb_backend() -> str:
    """确保 pyusb 能加载 libusb-1.0 后端。返回采取的策略名，便于日志。

    必须在 `import pyvisa` / `import usb.core` **之前**调用。
    策略顺序：libusb_package > PATH 前置 > 无（由上层报错）。
    """
    global _APPLIED
    if _APPLIED:
        return "already"
    _APPLIED = True

    if os.name != "nt":
        # Linux 不走 DLL 查找：libusb-1.0 由 apt 的 libusb-1.0-0 提供，
        # pyusb 通过 ctypes.util.find_library("usb-1.0") 直接命中 .so。
        # ⚠️ 此处**不要提前 import usb.core**——那会在调用方之前初始化 libusb，
        #    使随后的 detach_kernel_drivers() 拿不到正确的后端句柄。
        try:
            import ctypes.util

            so = ctypes.util.find_library("usb-1.0") or ctypes.util.find_library("usb")
            return f"linux:libusb={so or 'not-found'}"
        except Exception:  # noqa: BLE001
            return "linux:probe-failed"

    if _try_libusb_package():
        # libusb_package 存在时，pyvisa_py 0.8+ 与 pyusb 均可经其加载 DLL；
        # 再把其目录也前置进 PATH，兼容仍走 find_library 的旧路径。
        try:
            import libusb_package
            lib = libusb_package.get_library_path()
            d = os.path.dirname(lib)
            if d and d not in os.environ.get("PATH", ""):
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
        except Exception:  # noqa: BLE001
            pass
        return "libusb_package"

    for d in _candidate_dll_dirs():
        if Path(d).is_dir() and d not in os.environ.get("PATH", ""):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            # 命中即止：首个含 libusb-1.0.dll 的目录已足够
            if any(Path(d).glob("libusb-1.0.dll")):
                return f"path:{d}"
    return "none"


def detach_kernel_drivers(vendor_id: int, product_id: int, max_ifaces: int = 8) -> int:
    """把指定 USB 设备从**内核驱动**手里解绑，交给 libusb 独占。

    为什么必需（2026-10-11 Linux 实测）：
      RIGOL DS1104Z 的 USB-TMC 接口（class 0xFE / subclass 0x03 / proto 0x01）会被
      内核 `usbtmc` 驱动自动绑定。pyvisa-py 的 USB 通路走 pyusb/libusb，
      **不接管内核已绑定的接口** → `usb.core.Device.set_configuration()` 直接抛
      `USBError [Errno 19] No such device`，表现为「枚举得到、就是打不开」。

      显式 `detach_kernel_driver(iface)` 后 libusb 才能 claim 该接口
      （实测 claim 成功、可枚举出 USB0::6833::1230::DS1ZC…::INSTR）。

    与 Windows 的关系：Windows 无 usbtmc 内核驱动（走 WinUSB / 厂商驱动），
    该函数在 nt 上是 no-op。

    幂等：设备未绑定内核驱动时循环内异常被吞，返回 0。
    返回成功解绑的接口数（便于日志判断是否生效）。
    """
    if os.name == "nt":
        return 0
    try:
        import usb.core
    except Exception:  # noqa: BLE001
        return 0
    try:
        dev = usb.core.find(idVendor=vendor_id, idProduct=product_id)
    except Exception:  # noqa: BLE001
        return 0
    if dev is None:
        return 0

    detached = 0
    for iface in range(max_ifaces):
        try:
            if dev.is_kernel_driver_active(iface):
                dev.detach_kernel_driver(iface)
                detached += 1
        except Exception:  # noqa: BLE001
            # 该接口不存在 / 未绑定 / 权限不足——继续试下一个
            continue
    return detached


# RIGOL DS1104Z 的 USB 控制器在一次异常传输后会卡死：设备仍能被枚举、能 claim，
# 但对任何 SCPI 命令都不再应答（表现为 write/read 全部 [Errno 110] timeout）。
# 实测（2026-10-11）对 /sys/bus/usb/devices/<bus>-<port>/authorized 做 0→1 翻转
# （等价于「USB 软复位」，不需要物理拔插）即可让它恢复正常应答。
#
# ⚠️ 该操作需要宿主机 root 写 sysfs，容器内无权限，故由宿主侧脚本调用；
#    Python 侧仅检测「打开成功但通信超时」并抛出可识别的错误，由上层决定是否复位。
USBTMC_STUCK_HINT = "scope link stuck: USB controller not responding"


def is_timeout_error(exc: BaseException) -> bool:
    """判断异常是否属于「设备卡死型超时」（Errno 110 / VI_ERROR_TMO）。"""
    text = f"{type(exc).__name__}: {exc}"
    return any(k in text for k in ("Errno 110", "timed out", "VI_ERROR_TMO", "-1073807339"))


def find_usb_sysfs_path(vendor_id: int, product_id: int) -> str | None:
    """在宿主机 sysfs 里定位设备的 `bus-port` 目录名（如 `1-8`）。

    供「USB 软复位」脚本使用；找不到返回 None。
    """
    import glob

    base = "/sys/bus/usb/devices"
    for vid_file in glob.glob(f"{base}/*/idVendor"):
        try:
            with open(vid_file) as fh:
                if int(fh.read().strip(), 16) != vendor_id:
                    continue
            pid_file = vid_file.replace("idVendor", "idProduct")
            with open(pid_file) as fh:
                if int(fh.read().strip(), 16) != product_id:
                    continue
        except Exception:  # noqa: BLE001
            continue
        return os.path.basename(os.path.dirname(vid_file))
    return None
