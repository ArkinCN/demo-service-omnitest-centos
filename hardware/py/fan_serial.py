"""风扇串口层（Python 重写，对应原 src/FanTransport.cs）。

用 pyserial 复刻 .NET SerialPort 的行为与 UNO_FAN_V2 串口协议：
- SerialWire：打开串口时序（DTR 先低→打开→等 150ms→清输入缓冲→DTR 拉高）。
  打开串口会触发 UNO 复位（原 .NET 亦如此，"转两秒"即此物理现象）。
- FanSession.Identify：读帧直到收到 "READY UNO_FAN_V2 25000"，否则拒绝发命令。
- FanSession.Command：只允许 STATUS 或 SET <0..100>；校验 "OK DUTY N" 应答；
  "ERR ..." 抛错；超时报错（物理状态未知）。

跨平台：pyserial 在 Windows/Linux 通用，端口名由 config 提供（COMx 或 /dev/tty*）。
"""
from __future__ import annotations

import threading
import time
from typing import Protocol

import serial  # pyserial

# 与固件 uno_fan.ino 一致的协议常量
IDENTITY = "READY UNO_FAN_V2 25000"
BAUD = 115200
MAX_FRAME = 64


class SerialProtocolError(RuntimeError):
    """串口协议错误（非应答/非法帧/超时），对应原 InvalidOperationException/TimeoutException。"""


class IWire(Protocol):
    def read_byte(self) -> int: ...
    def write(self, text: str) -> None: ...
    def close(self) -> None: ...


class SerialWire:
    """真实串口（pyserial）。打开时序复刻 .NET SerialWire 构造。"""

    def __init__(self, port: str, baud: int = BAUD) -> None:
        # 先建对象不打开：newline/超时与 .NET 对齐（ReadTimeout=50ms, WriteTimeout=1000ms）
        self._ser = serial.Serial()
        self._ser.port = port
        self._ser.baudrate = baud
        self._ser.parity = serial.PARITY_NONE
        self._ser.bytesize = serial.EIGHTBITS
        self._ser.stopbits = serial.STOPBITS_ONE
        self._ser.timeout = 0.05      # read 超时 50ms
        self._ser.write_timeout = 1.0  # write 超时 1000ms
        try:
            # .NET: DtrEnable=false → Open → Sleep(150) → DiscardInBuffer → DtrEnable=true
            self._ser.dtr = False
            self._ser.open()
            time.sleep(0.150)
            self._ser.reset_input_buffer()
            self._ser.dtr = True
        except Exception:
            try:
                self._ser.close()
            except Exception:
                pass
            raise

    def read_byte(self) -> int:
        b = self._ser.read(1)
        if not b:
            raise TimeoutError("serial read timeout")
        return b[0]

    def write(self, text: str) -> None:
        self._ser.write(text.encode("ascii"))

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass


class FanSession:
    """一条到 UNO_FAN_V2 的会话：识别 + 命令 + 应答校验。"""

    def __init__(self, wire: IWire) -> None:
        self._wire = wire
        self.identified = False

    # ---------- 帧读取 ----------
    def _read_frame(self, deadline_ms: int) -> str:
        """读一行（\\n 结尾），超时/非法帧抛错。deadline_ms 为绝对截止（自 clock 起点算）。"""
        text: list[str] = []
        start = time.monotonic()
        while (time.monotonic() - start) * 1000 < deadline_ms:
            try:
                b = self._wire.read_byte()
            except TimeoutError:
                continue
            if (time.monotonic() - start) * 1000 >= deadline_ms:
                raise SerialProtocolError("Serial deadline exceeded; late frame rejected.")
            if b == 10:  # \n
                return "".join(text).rstrip("\r")
            if b < 0 or b > 127:
                raise SerialProtocolError("Non-ASCII serial frame.")
            text.append(chr(b))
            if len(text) > MAX_FRAME:
                raise SerialProtocolError("Serial frame exceeds 64 bytes.")
        raise SerialProtocolError("Serial deadline exceeded; physical fan state unknown.")

    # ---------- 协议 ----------
    def identify(self, timeout_ms: int = 8000) -> None:
        start = time.monotonic()
        for _ in range(64):
            if (time.monotonic() - start) * 1000 >= timeout_ms:
                break
            line = self._read_frame(timeout_ms)
            if line == IDENTITY:
                self.identified = True
                return
        raise SerialProtocolError("Exact UNO_FAN_V2 identity not received; no commands sent.")

    def command(self, command: str, timeout_ms: int = 2000) -> str:
        if not self.identified:
            raise SerialProtocolError("Board identity required before writing.")
        expected = -1
        if command != "STATUS":
            if not command.startswith("SET "):
                raise SerialProtocolError("Only STATUS or SET integer 0..100 permitted.")
            try:
                expected = int(command[4:])
            except ValueError:
                raise SerialProtocolError("Only STATUS or SET integer 0..100 permitted.") from None
            if expected < 0 or expected > 100 or command != "SET " + str(expected):
                raise SerialProtocolError("Only STATUS or SET integer 0..100 permitted.")

        self._wire.write(command + "\n")
        start = time.monotonic()
        for _ in range(32):
            if (time.monotonic() - start) * 1000 >= timeout_ms:
                break
            reply = self._read_frame(timeout_ms)
            if reply.startswith("ERR "):
                raise SerialProtocolError(reply)
            if not reply.startswith("OK DUTY "):
                continue
            try:
                actual = int(reply[8:])
            except ValueError:
                raise SerialProtocolError("Malformed duty acknowledgement.") from None
            if actual < 0 or actual > 100 or reply != "OK DUTY " + str(actual):
                raise SerialProtocolError("Malformed duty acknowledgement.")
            if expected >= 0 and actual != expected:
                raise SerialProtocolError("Duty acknowledgement mismatch: " + reply)
            return reply
        raise SerialProtocolError("No valid acknowledgement; physical fan state unknown.")

    def close(self) -> None:
        self._wire.close()


# ---------------------------------------------------------------------------
# 取消信号（对应 FanTransport.cs 的 CancelSignal：Ctrl+C 置位，循环内检测）
# ---------------------------------------------------------------------------
class CancelSignal:
    """Ctrl+C 置 requested=True；主循环据此优雅收尾（发 SET 0）。"""

    _requested = False
    _installed = False

    @classmethod
    def install(cls) -> None:
        import signal

        cls._requested = False

        def _handler(signum, frame):  # noqa: ANN001
            cls._requested = True

        try:
            signal.signal(signal.SIGINT, _handler)
            cls._installed = True
        except (ValueError, OSError):
            # 非主线程无法注册信号；退化为不拦截，由 stop.request 承担
            cls._installed = False

    @classmethod
    def remove(cls) -> None:
        import signal

        if cls._installed:
            try:
                signal.signal(signal.SIGINT, signal.SIG_DFL)
            except (ValueError, OSError):
                pass
            cls._installed = False

    @classmethod
    def requested(cls) -> bool:
        return cls._requested

    @classmethod
    def set_requested(cls) -> None:
        cls._requested = True


def install_wait_thread(stop_file: str, interval_s: float = 0.05) -> threading.Thread:
    """后台线程：轮询 stop.request，命中即置 CancelSignal（对应原 stopFile 检查）。"""

    def _run() -> None:
        import os

        while not CancelSignal.requested():
            try:
                if os.path.exists(stop_file):
                    CancelSignal.set_requested()
                    return
            except OSError:
                pass
            time.sleep(interval_s)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t
