"""集中配置。凭据只从环境变量取，代码里不写死私钥内容。"""
from __future__ import annotations

import os
import sys as _sys
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# libusb-1.0.dll 路径修复（观测层连 USB 示波器的硬前提）
#
# pyvisa-py 的 usbtmc 后端用 pyusb，而 pyusb 用 ctypes.util.find_library 定位
# libusb-1.0.dll，只搜 PATH / 系统目录，**不搜** conda 环境的 Library/bin。
# conda-forge 装的 libusb 恰好落在 <env>/Library/bin，直接调 python.exe（不 activate）
# 时 PATH 里没有它 → pyusb 报 NoBackendError、VISA 枚举为空。
#
# 这里在 import pyvisa 之前把 <env>/Library/bin 加进 PATH 并 add_dll_directory，
# 保证观测层每次启动都能找到 libusb（无需手动 activate 或复制 DLL）。
# ---------------------------------------------------------------------------
if _sys.platform == "win32":
    _conda_lib = os.path.join(_sys.prefix, "Library", "bin")
    if os.path.isdir(_conda_lib):
        os.environ["PATH"] = _conda_lib + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(_conda_lib)  # Python 3.8+，对 ctypes.LoadLibrary 生效
        except (AttributeError, OSError):
            pass


@dataclass(frozen=True)
class DeviceConfig:
    """一台被 MCP 暴露出去的设备。"""

    id: str
    name: str
    model: str
    kind: str                 # host | instrument
    host: str
    port: int
    user: str
    key_env: str              # 环境变量名，其值是私钥【文件路径】；与 webssh 的 keyRef 同一约定
    via: str | None = None    # 仪器类设备经宿主机中转
    tags: list[str] = field(default_factory=list)

    @property
    def key_path(self) -> str | None:
        p = os.environ.get(self.key_env)
        if not p:
            return None
        return os.path.expanduser(p)


BENCH = DeviceConfig(
    id="bench",
    name="峰岹台架工控机",
    model="SK-20251218QPBB / Windows 11",
    kind="host",
    host=os.environ.get("BENCH_HOST", "172.25.5.166"),
    port=int(os.environ.get("BENCH_PORT", "5011")),
    user=os.environ.get("BENCH_USER", "administrator"),
    key_env="FORTIOR_WIN_KEY",
    tags=["ssh", "windows", "session0"],
)

SCOPE = DeviceConfig(
    id="scope",
    name="RIGOL DS1104Z Plus 示波器",
    model="DS1104Z Plus · VISA over USB",
    kind="instrument",
    host=BENCH.host,
    port=BENCH.port,
    user=BENCH.user,
    key_env="FORTIOR_WIN_KEY",
    via="bench",
    tags=["visa", "usbtmc"],
)

DEVICES: dict[str, DeviceConfig] = {BENCH.id: BENCH, SCOPE.id: SCOPE}

# 台架机上的既有工具与路径（来自 fortior-test-bench skill 的实测记录）
FC_PULL = r"C:\fc_pull"
FGPOLL = FC_PULL + r"\FgPoll.exe"
SCOPECTL = FC_PULL + r"\ScopeCtl.exe"
DEEPCAPTURE4 = FC_PULL + r"\DeepCapture4.exe"
MOTORDEBUG_LOG_DIR = r"C:\Users\Administrator\AppData\Local\MotorDebug\logs"

# VISA 读不到有效测量时 Rigol 返回的哨兵值
VISA_NAN = 9.9e37

SSH_CONNECT_TIMEOUT = float(os.environ.get("BENCH_SSH_TIMEOUT", "12"))
EXEC_TIMEOUT = float(os.environ.get("BENCH_EXEC_TIMEOUT", "60"))

# ---------------------------------------------------------------- 本机直连
# 设备直接插本机 USB/串口（控机=本机）时的观测层通道：不再 SSH 到工控机跑客户 exe，
# 而是用 pyvisa-py（纯 Python VISA 后端，不依赖 NI-VISA）直连 RIGOL 示波器发 SCPI。
#
# 两个关键配置（真机到场后填写）：
#   BENCH_BACKEND = ssh | local   观测层走哪条路；默认 ssh 保持向后兼容
#   VISA_RESOURCE = 示波器 VISA 资源名，形如 USB0::0x1AB1::0x04CE::DS1ZC...::INSTR
#
# 前置（真机到场才做）：示波器 USB 驱动需切成 WinUSB（用 Zadig），pyvisa-py 的
# usbtmc 后端才能枚举到设备。没切驱动 / 没插设备时，VISA_RESOURCE 留空即可，
# 后端会如实报「无设备」，不假装读到数。
BENCH_BACKEND = os.environ.get("BENCH_BACKEND", "ssh")
VISA_RESOURCE = os.environ.get("VISA_RESOURCE", "")
VISA_QUERY_TIMEOUT_MS = int(os.environ.get("VISA_QUERY_TIMEOUT_MS", "5000"))

# 通道接线约定（沿用台架实测：README 架构图 CH1 电流 / CH2 FG1 / CH3 FG2 / CH4 PWM1）。
# 真机到场后须按实际接线核对；这是唯一需要现场确认的映射。
CH_CURRENT = 1
CH_FG1 = 2
CH_FG2 = 3
CH_PWM = 4

# ---------------------------------------------------------------- 动作层 · 电机控制桥
# 动作层（start/stop/estop/write_param）真下发走 dll-bridge.exe —— 一个 32 位 Rust 子进程，
# 封装客户 FTGeneralUtils.dll（FTGeneralUtils 的 FFI 桥）。两种运行模式：
#   CLI 一次性模式：`dll-bridge.exe free-run --main-addr 0x...`，跑完即退出。
#       ⚠️ FreeRun 是阻塞的（电机转），且 break-run 是另一个进程、DLL 静态状态不共享，
#       无法跨进程中断 —— 所以 CLI 模式不适合「持续转 + 外部停」这一对动作。
#   IPC 常驻模式：`dll-bridge.exe`（无参数）常驻，stdin/stdout JSON 通信，
#       FreeRun 在 worker 线程阻塞、BreakRun 主线程中断 —— 这才是真启停的正确方式。
# 动作层真启停走 IPC 常驻模式，由 device_bench/dll_bridge.py 封装子进程生命周期。
#
# 关键前提（真机到场后确认）：
#   1. 电机板须经 SWD/JLINK 或 HID 连到本机，且 FTGeneralUtils.dll 能枚举到芯片。
#   2. 板内固件已烧好 → 直接 FreeRun 启动（DownloadCode 后 MCU 已在 debug 模式，
#      FreeRun 序列 SetBreakPoint→EnterDebugMode→FreeRun 可直接跑，无需每次烧固件）。
#   3. 板内无固件 → 需 DownloadCode(chip, hex)，但现场不提供固件工程/hex，属现场层硬阻塞。
#   4. main_addr 是固件 main 函数地址（从 MAP 文件解析），默认 0x08000000。
# dll-bridge 与 device_bench 是 components/ 下的两个平级子项目，用 __file__ 定位，
# 不写死盘符（项目可能迁移，且中文路径易踩 Rust 链接器坑）。
_DLL_BRIDGE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "dll-bridge")
)
DLL_BRIDGE_EXE = os.environ.get(
    "DLL_BRIDGE_EXE",
    os.path.join(_DLL_BRIDGE_DIR, "target", "i686-pc-windows-msvc", "release", "dll-bridge.exe"),
)
DLL_BRIDGE_DLL = os.environ.get(
    "DLL_BRIDGE_DLL",
    os.path.join(_DLL_BRIDGE_DIR, "resources", "FTGeneralUtils.dll"),
)
DLL_BRIDGE_CHIP = os.environ.get("DLL_BRIDGE_CHIP", "FU6832")
# main 函数断点地址（十六进制字面量，int 存）。默认 STM32/FU 系列复位向量。
DLL_BRIDGE_MAIN_ADDR = int(os.environ.get("DLL_BRIDGE_MAIN_ADDR", "0x08000000"), 16)

# 动作层是否允许在没有 dll-bridge.exe / DLL 时「假装执行」。默认 False：缺文件时如实报
# 现场层待接，绝不 mode=mock 冒充「电机已转」。演示需要合成反馈时显式置 1（仅演示，勿用于真机）。
DLL_BRIDGE_ALLOW_MOCK = os.environ.get("DLL_BRIDGE_ALLOW_MOCK", "0") == "1"

# ---------------------------------------------------------------- 批准 PIN
# 红线批准的第二道秘密。与 BRIDGE_TOKEN 分开：BRIDGE_TOKEN 是"调用票"，会被打进
# 浏览器包，任何拿到前端产物的人都有；BRIDGE_APPROVER_PIN 只存在于桥的 .env 与
# 服务端进程内存，前端不得以 VITE_ 前缀变量的形式携带它，只能由人在确认卡上现场输入。
APPROVER_PIN = os.environ.get("BRIDGE_APPROVER_PIN", "")
# 连续输错几次锁定、锁多久（秒）
APPROVER_PIN_MAX_FAILS = int(os.environ.get("BRIDGE_APPROVER_PIN_MAX_FAILS", "5"))
APPROVER_PIN_LOCK_SECONDS = float(os.environ.get("BRIDGE_APPROVER_PIN_LOCK_SECONDS", "60"))

# ---------------------------------------------------------------- 自动化自动授权
# 一键自动化测试流程要"真下发设备启动"而不必人工敲 PIN。红线**不因此作废**，而是
# 多开一条受独立 token 保护的自动化通道：
#   · BRIDGE_AUTOMATION_TOKEN —— 只存在于桥 .env 与进程内存，同样绝不进浏览器包。
#     带 x-automation-token 头调 POST /confirmations/{token}/auto-approve 时，
#     凭据的 approve_channel 记为 "automation"（区别于 human_pin），留痕可审计。
#   · 缺省为空 = **关闭**自动化自动授权（红线仍只走人工 PIN）。只有显式配置了
#     这个 token，自动化流程才能无 PIN 自动批准 start/stop 这类动作。
# 独立于 APPROVER_PIN 的原因：它是"自动化的放行权"，不与人现场批准的 PIN 混用，
# 且两者都能在 .env 里单独开关，互不影响。
AUTOMATION_TOKEN = os.environ.get("BRIDGE_AUTOMATION_TOKEN", "")
