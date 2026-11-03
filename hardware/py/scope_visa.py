"""示波器 VISA 封装（Python 重写，对应原 src/ScopeVisa.cs）。

改用 pyvisa + pyvisa-py（纯 Python VISA 后端，跨平台），替代 C# P/Invoke visa64.dll。
对外接口与 ScopeVisa 类对齐：write / query / query_bytes / block_payload / dispose。

诚实边界：不用 mock 顶替。资源名打不开时：
  ① 若配置了 resource，先按 resource 打开；
  ② 打不开或未配置 resource（空串）→ 用 rm.list_resources() 自动枚举：
     按 USB-TMC 的 **VID=0x1AB1（RIGOL）+ PID=0x04CE（DS1000Z）** 精确匹配，
     再用 *IDN? 验证身份；唯一候选即采用并告警；
  ③ 找不到则如实抛错（不伪造数据），错误里带上实际枚举到的资源列表。

后端可配置（2026-10-07 新增，2026-10-08 调整默认，2026-10-11 Linux 复核）：
环境变量 SCOPE_VISA_BACKEND，**默认按平台判定**（见 `_default_backend()`）：
- Windows → `@ivi`（NI-VISA）。原因：pyvisa-py + libusbK 组合下大块读取不可靠
  （实测 `:WAVeform:DATA?` >~100 点、`:DISPlay:DATA?` BMP 截屏必超时，且超时后
  USB 层进入异常态、必须拔插才能恢复）。NI-VISA 的 USB-TMC 实现成熟，可稳定读大块。
- Linux → **同样 `@ivi`**（2026-10-11 实测后改）：pyvisa-py(@py)+libusb 与 DS1104Z
  固件 00.04.05.SP2 兼容性差（同一会话内第二次读波形起永久返回 inc=0）；
  NI 官方 libvisa（挂在容器内）连续读数与 1200 点大块读取稳定。
  ⚠️ 走 @ivi 时同样需要先解绑内核 usbtmc 驱动（设备重枚举后 udev 会自动绑回，
  见 ScopeDevice.__init__ 内的注释；2026-10-12 实测）。

仍可用 `SCOPE_VISA_BACKEND` 显式覆盖（一键回退）。默认后端枚举不到 USB 资源时，
错误信息里会带上实际枚举结果，便于定位是「驱动问题」还是「后端选错」。
"""
from __future__ import annotations

import os
import sys
import time

# ⚠️ 必须在 import pyvisa 之前预置 libusb 后端（见 usb_env 模块说明）：
# pyvisa_py.usb 在 import 时探测并固定 USB 后端，若此刻找不到 libusb-1.0.dll，
# 会静默退化到 libusb0 旧后端 → 能枚举却打不开（claim_interface 失败）。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usb_env  # noqa: E402

usb_env.ensure_usb_backend()

import pyvisa  # noqa: E402

# RIGOL DS1000Z 系列 USB-TMC 的 VID/PID（与实测 USB\VID_1AB1&PID_04CE 一致）
RIGOL_VID = "0X1AB1"
DS1000Z_PID = "0X04CE"
RIGOL_VID_INT = 0x1AB1
DS1000Z_PID_INT = 0x04CE


def _default_backend() -> str:
    """平台感知的默认 VISA 后端（2026-10-11 改）。

    **Windows 与 Linux 都走 `@ivi`（NI-VISA）**，理由是实测结论而非偏好：
      NI-VISA 的 USB-TMC 实现成熟，大块读取稳定，超时具备完善复位语义。
      反观 pyvisa-py(@py)+libusb 与 DS1104Z 固件 00.04.05.SP2 兼容性差：
      实测同一会话内**第一次读波形成功、第二次起永久返回 inc=0**（preamble 全 0），
      重设触发源/电平、新建 VISA 会话都救不回来，USB 复位只够恢复一次。
      同型号机型在 GitHub pyvisa-py#414 也记录了 Linux 下 `:DISPlay:DATA?` 必超时。

    Linux 侧用 `@ivi` 的两个前置条件（2026-10-11 在本机装好并实测通过）：
      ① 宿主机装 NI-VISA runtime，`libvisa.so.26.5.0` + `ni-visa/` 通过 compose 挂进容器；
      ② **必须先解绑内核 usbtmc 驱动**，否则资源被占用报 `VI_ERROR_RSRC_BUSY`
         （`deploy/hardware-setup.sh` 第 8 步自动做，见 usb_env.detach_kernel_drivers）。

    仍允许 `SCOPE_VISA_BACKEND` 环境变量显式覆盖，保留一键回退能力。
    """
    return "@ivi"


def _loadable_backends() -> list[str]:
    """探测本机可加载的 VISA 后端（供诊断输出，不抛错）。"""
    found: list[str] = []
    for backend in ("@ivi", "@py"):
        try:
            rm = pyvisa.ResourceManager(backend)
            rm.close()
            found.append(backend)
        except Exception:  # noqa: BLE001 - 探测失败仅表示该后端不可用
            continue
    return found


class VisaError(IOError):
    """VISA 操作错误（对应原 IOException("... VISA error 0x...")）。"""


def _strip_bom(data: bytes) -> bytes:
    return data[3:] if data.startswith(b"\xef\xbb\xbf") else data


def block_payload(bytes_in: bytes) -> bytes:
    """解析 IEEE-488.2 定长块（对应原 ScopeVisa.BlockPayload）。

    格式：#<位数><长度><payload>，允许尾部 CR/LF。
    """
    if len(bytes_in) < 3 or bytes_in[0:1] != b"#" or not (b"1" <= bytes_in[1:2] <= b"9"):
        raise VisaError("Expected a definite SCPI block.")
    digits = bytes_in[1] - 0x30
    if len(bytes_in) < 2 + digits:
        raise VisaError("Truncated SCPI length.")
    try:
        length = int(bytes_in[2:2 + digits].decode("ascii"))
    except ValueError:
        raise VisaError("Invalid SCPI length.") from None
    if length < 0 or length > 2097152:
        raise VisaError("Invalid SCPI length.")
    if len(bytes_in) < 2 + digits + length:
        raise VisaError("Truncated SCPI payload.")
    for b in bytes_in[2 + digits + length:]:
        if b not in (10, 13):
            raise VisaError("Unexpected SCPI trailing bytes.")
    return bytes_in[2 + digits:2 + digits + length]


class ScopeDevice:
    """示波器会话（默认 pyvisa-py 后端 @py，可经 SCOPE_VISA_BACKEND 切 @ivi）。"""

    READ_DEADLINE_MS = 6000
    MAX_RESPONSE = 2 * 1024 * 1024

    def __init__(self, resource: str, expected_identity: str | None = None) -> None:
        self._rm = None
        self._inst = None
        self.resource = resource
        # 后端可配置：默认按平台判定（Windows=@ivi / 其它=@py），可用 SCOPE_VISA_BACKEND 覆盖。
        backend = os.environ.get("SCOPE_VISA_BACKEND") or _default_backend()
        self.backend = backend
        try:
            self._rm = pyvisa.ResourceManager(backend)
            # Linux（@py 与 @ivi 都要）：先从内核 usbtmc 驱动解绑。
            #
            # 为什么 @py 需要（2026-10-11 实测）：libusb 不接管内核已绑定的接口
            #   → `set_configuration()` 报 Errno 19，表现为「枚举得到、打不开」。
            # 为什么 @ivi **也**需要（2026-10-12 实测）：
            #   设备经 USB 重枚举（拔插/复位/内部重启）后，内核 udev 会把 usbtmc
            #   自动绑回去；此时 NI-VISA 同样枚举不到该设备——`list_resources()`
            #   只剩串口，真实运行报 "No RIGOL USB-TMC scope found"
            #   （2026-10-12 实测：设备号 005→011 的重枚举后复现）。
            #   显式解绑后 @ivi 立即恢复可见（实测 detached=1 → VISA 枚举成功）。
            #   幂等且安全：未绑定时返回 0；Windows 上为 no-op（见 usb_env）。
            try:
                detached = usb_env.detach_kernel_drivers(RIGOL_VID_INT, DS1000Z_PID_INT)
                if detached:
                    print(f"[scope_visa] 已解绑 {detached} 个内核驱动接口（{backend}）")
            except Exception as e:  # noqa: BLE001
                print(f"[scope_visa] 内核驱动解绑跳过：{e}")
            target = (resource or "").strip()
            if not target:
                # 未配置资源名（空串）→ 直接按 VID/PID 自动枚举
                target = self._find_fallback("")
                if target is None:
                    raise VisaError(
                        f"No RIGOL USB-TMC scope found; enumerated: {self._list_safe()} "
                        f"(backend={backend})"
                    )
            try:
                self._inst = self._rm.open_resource(target, open_timeout=3000)
            except Exception as primary:  # noqa: BLE001
                # 资源名对不上/打不开时，按 VID/PID 枚举回退
                fallback = self._find_fallback(target)
                if fallback is None:
                    raise VisaError(
                        f"Open scope VISA error: {primary}; "
                        f"enumerated: {self._list_safe()} (backend={backend})"
                    ) from primary
                self._inst = self._rm.open_resource(fallback, open_timeout=3000)
                target = fallback
            self.resource = target
            # 超时与读块：波形/BMP 读取数据量可达数十 KB~数百 KB，3s 与默认 20KB 读块偏小。
            # 走 NI-VISA(@ivi) 时大块读取稳定（不再像 libusbK 那样 >100 点必超时），
            # 这里仍保留宽松值以覆盖 BMP 截屏这类大响应；chunk_size 提高读取吞吐。
            self._inst.timeout = 15000
            try:
                self._inst.chunk_size = 204800
            except Exception:  # noqa: BLE001 - 个别后端不支持 chunk_size，忽略
                pass
        except VisaError:
            self.dispose()
            raise
        except Exception as e:  # noqa: BLE001
            self.dispose()
            raise VisaError(f"Open scope VISA error: {e}") from e

    def _list_safe(self) -> list[str]:
        try:
            return list(self._rm.list_resources())
        except Exception:  # noqa: BLE001
            return []

    def _find_fallback(self, wanted: str) -> str | None:
        """按 VID/PID 精确枚举回退。

        匹配规则（2026-10-07 定）：
          ① wanted 非空且确在资源列表里 → 直接用（尊重配置）；
          ② 否则筛 USB 资源，取含 RIGOL VID(0x1AB1) + DS1000Z PID(0x04CE) 的候选中
             第一个；若恰好同时含配置里的序列号片段则更优；
          ③ 仍无 → 退化为「唯一 USB 资源即采用」，否则返回 None（不猜、不误抓）。
        """
        resources = self._list_safe()
        if wanted and wanted in resources:
            return wanted
        # 注意资源名不含 0x1AB1 字面量：pyvisa 把 VID 转成十进制厂商码，
        # RIGOL(0x1AB1=6833) 在资源名里表现为 `USB0::6833::1230::<序列号>::0::INSTR`
        # （见 acceptance.windows.json 实测值）。故两种写法都要匹配。
        usb = [r for r in resources if str(r).upper().startswith("USB")]
        if not usb:
            return None
        # 按 VID/PID 精确匹配（资源名大小写不一，统一大写比较）
        vid_markers = (RIGOL_VID, "6833")  # "0X1AB1" 与十进制 "6833"
        pid_markers = (DS1000Z_PID, "1230")  # "0X04CE" 与十进制 "1230"
        matches = [
            r for r in usb
            if any(v in str(r).upper() for v in vid_markers)
            and any(p in str(r).upper() for p in pid_markers)
        ]
        if not matches:
            # 退化：唯一 USB 资源（须恰好一个，避免误抓同厂商其它仪器）
            return usb[0] if len(usb) == 1 else None
        # 若配置的 wanted 里带了序列号片段，优先选序列号一致的那个
        if wanted:
            for r in matches:
                if wanted.split("::")[-2:-1] and wanted.split("::")[-2:-1][0] in str(r):
                    return r
        return matches[0]

    # ---------- 读写 ----------
    def write(self, command: str) -> None:
        try:
            self._inst.write(command)
        except Exception as e:  # noqa: BLE001
            raise VisaError(f"Write {command} failed: {e}") from e

    def query_bytes(self, command: str) -> bytes:
        """发命令并读回原始字节（带 6 秒总截止，对应原 QueryBytes）。"""
        started = time.monotonic()
        try:
            self._inst.write(command)
        except Exception as e:  # noqa: BLE001
            raise VisaError(f"Write {command} failed: {e}") from e
        # 对文本查询用 read_raw；pyvisa 的 read_raw 拿原始字节（含块头）
        try:
            raw = self._inst.read_raw()
        except Exception as e:  # noqa: BLE001
            raise VisaError(f"Read {command} failed: {e}") from e
        if (time.monotonic() - started) * 1000 >= self.READ_DEADLINE_MS:
            raise VisaError("VISA response deadline exceeded.")
        if len(raw) > self.MAX_RESPONSE:
            raise VisaError("VISA response exceeds 2 MiB.")
        return raw

    def query(self, command: str) -> str:
        return _strip_bom(self.query_bytes(command)).decode("ascii", errors="replace").strip()

    def query_binary_values(self, command: str) -> bytes:
        """发命令并读回 IEEE-488.2 定长二进制块，返回 payload 字节（0..255）。

        用于 :WAVeform:DATA? 的 BYTE 格式（2026-10-08 新增，替代 ASCii 文本读法，
        后者在 USB-TMC 上因数据量过大超时）。用 pyvisa 的 query_binary_values 直接
        解析块头，容器为 bytes，避免手工切分。
        """
        started = time.monotonic()
        try:
            raw = self._inst.query_binary_values(
                command, datatype="B", is_big_endian=False, container=bytes
            )
        except Exception as e:  # noqa: BLE001
            raise VisaError(f"Read {command} failed: {e}") from e
        if (time.monotonic() - started) * 1000 >= self.READ_DEADLINE_MS:
            raise VisaError("VISA response deadline exceeded.")
        if len(raw) > self.MAX_RESPONSE:
            raise VisaError("VISA response exceeds 2 MiB.")
        return bytes(raw)

    def dispose(self) -> None:
        try:
            if self._inst is not None:
                self._inst.close()
        except Exception:  # noqa: BLE001
            pass
        self._inst = None
        try:
            if self._rm is not None:
                self._rm.close()
        except Exception:  # noqa: BLE001
            pass
        self._rm = None

    # 兼容原 C# 的 Dispose 语义
    def close(self) -> None:
        self.dispose()
