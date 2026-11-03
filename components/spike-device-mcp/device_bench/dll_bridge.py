"""dll-bridge 子进程适配器（IPC 常驻模式）。

把 c/components/dll-bridge 那个 32 位 Rust 子进程包成 Python 可用对象。
dll-bridge.exe 封装客户 FTGeneralUtils.dll 的 FFI（Start/Stop 电机靠 FreeRun/BreakRun）。

为什么用 IPC 常驻模式而不是 CLI 一次性模式：
  - FreeRun 是**阻塞**的（电机持续转，直到 BreakRun 中断）。
  - CLI 模式每次命令是独立进程，break-run 会加载一个全新的 DLL 实例，静态状态不共享，
    无法中断另一个进程里的 FreeRun。
  - IPC 常驻模式里 FreeRun 在 worker 线程阻塞、BreakRun 从主线程中断（DLL 内部消息机制），
    这才是「持续转 + 外部停」的正确形态。

协议（对齐 dll-bridge/src/ipc.rs，serde camelCase）：
  请求一行 JSON：
    {"id":"<uuid>","timestamp":<ms>,"payload":{"type":"freeRun","mainAddr":134217728}}
  响应一行 JSON（type 取值见下）：
    {"type":"ready"}                                  —— 子进程启动就绪
    {"type":"dllLoaded","dllPath":"..."}              —— InitDll 成功后先发这条
    {"type":"success","requestId":"<id>","data":{}}   —— 请求成功（data 可缺省）
    {"type":"error","requestId":"<id>","message":"...","code":-101}
    {"type":"callbackEvent","msgId":..,"wParam":..,"lParam":..}  —— DLL 异步回调（记录后跳过）

诚实边界：本适配器只做「真下发」。exe / DLL 缺失、子进程启动失败、DLL 调用失败，一律抛
RuntimeError，由上层（server.py 动作层）如实转成「现场层待接 / 失败」，绝不静默降级成
「电机已转」的假成功。合成反馈只在 server.py 显式 force_mock 时才出现。
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import uuid
from typing import Any

from . import config

# 单条响应读取的超时（秒）。freeRun 要先过 SetBreakPoint + EnterDebugMode（约 7s），
# 给足余量；其它动作更快。子进程卡死时据此及时报错而非无限挂起。
READY_TIMEOUT_S = 30.0
FREERUN_TIMEOUT_S = 90.0
DEFAULT_TIMEOUT_S = 60.0


class DllBridgeError(RuntimeError):
    """dll-bridge 真下发失败（缺文件 / 启动失败 / DLL 调用失败 / 超时）。"""


class DllBridgeClient:
    """一个常驻 dll-bridge.exe 子进程的客户端。线程安全，动作串行化。"""

    def __init__(
        self,
        exe_path: str | None = None,
        dll_path: str | None = None,
        chip: str | None = None,
        main_addr: int | None = None,
    ) -> None:
        self.exe_path = exe_path or config.DLL_BRIDGE_EXE
        self.dll_path = dll_path or config.DLL_BRIDGE_DLL
        self.chip = chip or config.DLL_BRIDGE_CHIP
        self.main_addr = config.DLL_BRIDGE_MAIN_ADDR if main_addr is None else main_addr

        self._lock = threading.RLock()
        self._proc: subprocess.Popen[str] | None = None
        self._out_q: queue.Queue[str | None] = queue.Queue()
        self._reader: threading.Thread | None = None
        self._ready = False
        self._dll_loaded = False
        # 最近若干条 DLL 回调事件（诊断用，FreeRun 期间被 dll-bridge 内部节流/静默）
        self._callbacks: list[dict] = []

    # ---------------- 生命周期 ----------------

    def _check_files(self) -> None:
        if not os.path.isfile(self.exe_path):
            raise DllBridgeError(
                f"dll-bridge.exe 不存在：{self.exe_path}。"
                "动作层真下发依赖它，请先在 c/components/dll-bridge 用 32 位工具链编译"
                "（vcvarsall.bat x86 + cargo build --target i686-pc-windows-msvc --release）。"
            )
        if not os.path.isfile(self.dll_path):
            raise DllBridgeError(
                f"FTGeneralUtils.dll 不存在：{self.dll_path}。"
                "它是客户设备控制 DLL，缺失时无法真启停电机。"
            )

    def _ensure_started(self) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return
            self._check_files()
            popen_kwargs: dict[str, Any] = {
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "bufsize": 1,
            }
            # 设备桥由 run_bridge.py 以 DETACHED_PROCESS 启动（无控制台），子进程不新建
            # 控制台窗口，否则点「确认执行」会弹一个永远空白的黑框（dll-bridge 是 IPC
            # 常驻程序，stdout/stderr 全走管道）。仅 Windows 有效。
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
            self._proc = subprocess.Popen([self.exe_path], **popen_kwargs)
            self._ready = False
            self._dll_loaded = False
            self._callbacks = []
            # 后台线程把 stdout 逐行搬进队列，主线程按超时从队列取，避免阻塞读卡死。
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()
            # 等 ready
            line = self._wait_line(READY_TIMEOUT_S, "等待 dll-bridge 就绪")
            msg = self._parse(line)
            if msg.get("type") != "ready":
                raise DllBridgeError(f"dll-bridge 首条消息不是 ready：{line.strip()}")

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        try:
            for line in self._proc.stdout:
                self._out_q.put(line)
        finally:
            self._out_q.put(None)  # EOF 哨兵

    def _wait_line(self, timeout_s: float, what: str) -> str:
        deadline = time.time() + timeout_s
        while True:
            remain = deadline - time.time()
            if remain <= 0:
                raise DllBridgeError(f"{what}超时（{timeout_s}s）")
            try:
                item = self._out_q.get(timeout=remain)
            except queue.Empty:
                raise DllBridgeError(f"{what}超时（{timeout_s}s）")
            if item is None:
                raise DllBridgeError(
                    f"dll-bridge 子进程已退出（{what}）。stderr 尾部：{self._stderr_tail()}"
                )
            return item

    def _stderr_tail(self) -> str:
        if self._proc is None or self._proc.stderr is None:
            return ""
        try:
            # 非阻塞读不到就用空串，避免卡住
            import msvcrt  # noqa: F401  # Windows 专用
            return ""
        except Exception:  # noqa: BLE001
            return ""

    def _parse(self, line: str) -> dict[str, Any]:
        try:
            return json.loads(line.strip())
        except json.JSONDecodeError as exc:
            raise DllBridgeError(f"dll-bridge 返回非法 JSON：{line.strip()!r}（{exc}）")

    def _write(self, payload: dict) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        try:
            self._proc.stdin.write(json.dumps(payload) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise DllBridgeError(f"向 dll-bridge 写请求失败：{exc}")

    # ---------------- 请求 ----------------

    def request(self, payload_type: str, timeout_s: float = DEFAULT_TIMEOUT_S, **fields: Any) -> dict:
        """发一条 IPC 请求，阻塞等到匹配的 success/error 响应，返回 success 的 data 字典。

        跳过 callbackEvent / dllLoaded / ready 这些无 requestId 的中间消息。
        error 响应抛 DllBridgeError。
        """
        self._ensure_started()
        with self._lock:
            rid = uuid.uuid4().hex
            msg = {
                "id": rid,
                "timestamp": int(time.time() * 1000),
                "payload": {"type": payload_type, **fields},
            }
            self._write(msg)
            deadline = time.time() + timeout_s
            while True:
                line = self._wait_line(max(0.1, deadline - time.time()), f"请求 {payload_type}")
                resp = self._parse(line)
                t = resp.get("type")
                if t == "callbackEvent":
                    self._callbacks.append(resp)
                    self._callbacks = self._callbacks[-20:]
                    continue
                if t == "dllLoaded":
                    self._dll_loaded = True
                    continue
                if t == "ready":
                    continue
                if resp.get("requestId") != rid:
                    # 串行模型下不该出现别的 requestId；出现了也不误匹配，继续等。
                    continue
                if t == "error":
                    raise DllBridgeError(
                        f"{payload_type} 失败：{resp.get('message')} (code={resp.get('code')})"
                    )
                if t == "success":
                    data = resp.get("data")
                    return data if isinstance(data, dict) else {}
                raise DllBridgeError(f"dll-bridge 未知响应类型：{line.strip()!r}")

    # ---------------- 动作封装 ----------------

    def init(self) -> None:
        """加载 DLL + 注册回调。幂等：只做一次。"""
        if self._dll_loaded:
            return
        self.request("initDll", DEFAULT_TIMEOUT_S, dllPath=self.dll_path)
        self.request("setCallBackFun", DEFAULT_TIMEOUT_S)

    def free_run(self, main_addr: int | None = None) -> dict:
        """启动电机：SetBreakPoint→EnterDebugMode→FreeRun（FreeRun 在 worker 阻塞，电机持续转）。

        返回 data（FreeRun 确认运行后的附加信息）。成功后电机在转，直到 break_run()。
        """
        self.init()
        return self.request(
            "freeRun", FREERUN_TIMEOUT_S, mainAddr=(main_addr or self.main_addr)
        )

    def break_run(self) -> dict:
        """停止电机：BreakRun 中断 FreeRun。返回 data 含 mcu_stopped 等。"""
        self.init()
        return self.request("breakRun", DEFAULT_TIMEOUT_S)

    def download_code(self, chip: str | None = None, hex_path: str | None = None) -> dict:
        """烧录固件（DownloadCode）。需要固件工程 hex，属现场层。"""
        self.init()
        return self.request(
            "downloadCode",
            FREERUN_TIMEOUT_S,
            chipName=(chip or self.chip),
            projectPath=hex_path or "",
        )

    def reset(self, address: int | None = None) -> dict:
        """复位 MCU 并停在断点（BreakRun + SetBreakPoint + EnterDebugMode）。"""
        self.init()
        return self.request("reset", FREERUN_TIMEOUT_S, address=(address or self.main_addr))

    def shutdown(self) -> None:
        with self._lock:
            if self._proc is None:
                return
            try:
                self._write({"id": uuid.uuid4().hex, "timestamp": int(time.time() * 1000),
                             "payload": {"type": "shutdown"}})
            except DllBridgeError:
                pass
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.terminate()
            finally:
                self._proc = None
                self._ready = False
                self._dll_loaded = False

    @property
    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def callbacks(self) -> list[dict]:
        return list(self._callbacks)


# 进程内单例：bridge.py 与 MCP server 共用同一份（动作串行、避免多进程抢 HID）。
_CLIENT: DllBridgeClient | None = None
_CLIENT_LOCK = threading.Lock()


def get_client() -> DllBridgeClient:
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = DllBridgeClient()
        return _CLIENT
