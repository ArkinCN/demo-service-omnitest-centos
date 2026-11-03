"""SSH 后端与 mock 后端。

真实后端用 paramiko 连台架 Windows 工控机；连不上时自动降级成 mock，
返回合成数据，并且**每一条返回都带 mode 字段**，mock 绝不冒充真实。
"""
from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass
from typing import Literal

import paramiko

from . import config

Mode = Literal["live", "mock", "unknown"]


@dataclass
class ExecResult:
    cmd: str
    rc: int
    out: str
    err: str
    elapsed_ms: int
    mode: Mode


class BenchBackend:
    """一条到台架机的 SSH 会话，带自动降级。

    线程安全：所有对 paramiko 客户端的使用都在一把锁里，
    因为桥和 MCP server 可能并发调用。
    """

    def __init__(self, device: config.DeviceConfig, allow_mock: bool = True) -> None:
        self.device = device
        self.allow_mock = allow_mock
        self._lock = threading.RLock()
        self._client: paramiko.SSHClient | None = None
        self._mode: Mode = "unknown"   # 没连过就是 unknown，不假装自己是 mock
        self._last_error: str | None = None
        self._connected_at: float | None = None
        self._hostname: str | None = None
        self._mock_t0 = time.time()

    # ---------- 状态 ----------

    @property
    def mode(self) -> Mode:
        return self._mode

    @property
    def connected(self) -> bool:
        with self._lock:
            if self._client is None:
                return False
            tr = self._client.get_transport()
            return bool(tr and tr.is_active())

    def snapshot(self) -> dict:
        return {
            "device_id": self.device.id,
            "name": self.device.name,
            "model": self.device.model,
            "kind": self.device.kind,
            "target": f"{self.device.user}@{self.device.host}:{self.device.port}",
            "connected": self.connected,
            "mode": self._mode,
            "hostname": self._hostname,
            "connected_at": self._connected_at,
            "uptime_s": round(time.time() - self._connected_at, 1) if self._connected_at else None,
            "last_error": self._last_error,
            "key_env": self.device.key_env,
            "key_present": bool(self.device.key_path),
        }

    # ---------- 连接 ----------

    def connect(self, force_mock: bool = False) -> dict:
        with self._lock:
            self.disconnect()
            if force_mock:
                self._mode = "mock"
                self._last_error = "force_mock=true，调用方明确要求 mock"
                self._connected_at = time.time()
                self._hostname = "MOCK-BENCH"
                return self.snapshot()

            key_path = self.device.key_path
            if not key_path:
                return self._degrade(f"私钥环境变量 {self.device.key_env} 未设置")

            try:
                cli = paramiko.SSHClient()
                cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                cli.connect(
                    hostname=self.device.host,
                    port=self.device.port,
                    username=self.device.user,
                    key_filename=key_path,
                    timeout=config.SSH_CONNECT_TIMEOUT,
                    banner_timeout=config.SSH_CONNECT_TIMEOUT,
                    auth_timeout=config.SSH_CONNECT_TIMEOUT,
                    look_for_keys=False,
                    allow_agent=False,
                )
                self._client = cli
                self._mode = "live"
                self._last_error = None
                self._connected_at = time.time()
                r = self._exec_live("hostname")
                self._hostname = r.out.strip() or None
                return self.snapshot()
            except Exception as exc:  # noqa: BLE001 — 任何失败都降级并如实记录
                return self._degrade(f"{type(exc).__name__}: {exc}")

    def _degrade(self, reason: str) -> dict:
        self._client = None
        self._last_error = reason
        if not self.allow_mock:
            self._mode = "live"
            self._connected_at = None
            self._hostname = None
            raise RuntimeError(f"SSH 连接失败且未允许 mock：{reason}")
        self._mode = "mock"
        self._connected_at = time.time()
        self._hostname = "MOCK-BENCH"
        return self.snapshot()

    def disconnect(self) -> dict:
        with self._lock:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:  # noqa: BLE001
                    pass
            self._client = None
            self._connected_at = None
            self._hostname = None
            return self.snapshot()

    def ensure(self) -> None:
        """惰性连接。没连过、或 live 会话断了，都重连一次。"""
        if self._mode == "unknown":
            self.connect()
        elif self._mode == "live" and not self.connected:
            self.connect()
        elif self._mode == "mock" and self._connected_at is None:
            self.connect()

    # ---------- 执行 ----------

    def exec(self, cmd: str, timeout: float | None = None) -> ExecResult:
        """跑一条命令。live 走 SSH；mock 走合成器。"""
        with self._lock:
            self.ensure()
            if self._mode == "live" and self.connected:
                return self._exec_live(cmd, timeout)
            return self._exec_mock(cmd)

    def _exec_live(self, cmd: str, timeout: float | None = None) -> ExecResult:
        assert self._client is not None
        t0 = time.time()
        _in, out, err = self._client.exec_command(cmd, timeout=timeout or config.EXEC_TIMEOUT)
        so = out.read().decode("utf-8", "replace")
        se = err.read().decode("utf-8", "replace")
        rc = out.channel.recv_exit_status()
        return ExecResult(cmd, rc, so, se, int((time.time() - t0) * 1000), "live")

    # ---------- mock 合成器 ----------

    def _exec_mock(self, cmd: str) -> ExecResult:
        low = cmd.lower()
        t = time.time() - self._mock_t0
        if "fgpoll" in low:
            body = self._mock_fg_line(t)
        elif "hostname" in low:
            body = "MOCK-BENCH"
        elif "scopectl" in low and "pduty" in low:
            # 合成占空比：跟 mock 转速同相位，20% 到 70% 之间走
            body = f"{45 + 25 * math.sin(2 * math.pi * t / 60.0):.2f}"
        elif "scopectl" in low:
            body = "MOCK_OK idn=RIGOL,DS1104Z Plus,MOCKSERIAL,00.04.04"
        elif "deepcapture" in low:
            body = "MOCK_CAPTURE points=3000000 xinc=4.0E-05 file=C:\\fc_pull\\mock_capture.csv"
        elif "type " in low or "get-content" in low or "tail" in low:
            body = "\n".join(
                f"2026-09-19 21:{40 + i:02d}:00 [INFO] mock log line {i} save_workflow_autosave"
                for i in range(8)
            )
        else:
            body = f"MOCK_ECHO {cmd}"
        return ExecResult(cmd, 0, body + "\n", "", 3, "mock")

    def _mock_fg_line(self, t: float) -> str:
        """合成一条 FgPoll 风格的输出。

        转速按 60s 周期缓慢变化，FG1 ≈ 2.19 × FG2（沿用实测的系统性偏差），
        叠一点噪声，好让前端看到会动的数。
        """
        rpm = 6000 + 2500 * math.sin(2 * math.pi * t / 60.0)
        fg2 = rpm / 60.0
        fg1 = fg2 * 2.19
        jit = lambda v: v * (1 + random.uniform(-0.004, 0.004))  # noqa: E731
        return f"FG2={jit(fg2):.6E} FG1={jit(fg1):.6E}"


class LocalVisaBackend:
    """本机直连示波器后端（pyvisa-py，纯 Python VISA，不依赖 NI-VISA）。

    与 `BenchBackend`（SSH 到工控机）是**平级的两条路**，由 `config.BENCH_BACKEND`
    二选一。设备直接插本机 USB 时走这条：不再 SSH 去跑客户 exe，而是用 pyvisa-py
    的 usbtmc 后端直发 SCPI 给 RIGOL DS1104Z。

    接口对齐 `BenchBackend` 里的那几个（mode / connected / snapshot / connect /
    disconnect），外加一个 `query(cmd)` 供观测层发 SCPI 查询。

    ⚠️ 诚实边界：
      - pyvisa-py 的 usbtmc 后端需要示波器 USB 驱动切成 WinUSB（Zadig），且设备插上，
        否则 `list_resources()` 为空、连接会失败。失败时如实报错，**绝不降级成 mock
        假装有数据**（mock 只在显式 force_mock 时出现，且由上层 _envelope 标 mock_warning）。
      - SCPI 命令基于 RIGOL DS1000Z 公开协议 + 台架通道接线约定，真机到场后须校准。
    """

    def __init__(self) -> None:
        self._resource_name = config.VISA_RESOURCE
        self._rm = None
        self._inst = None
        self._mode: Mode = "unknown"
        self._last_error: str | None = None

    @property
    def mode(self) -> Mode:
        return self._mode

    @property
    def connected(self) -> bool:
        return self._inst is not None

    def snapshot(self) -> dict:
        return {
            "device_id": "scope",
            "name": "RIGOL DS1104Z Plus 示波器（本机直连）",
            "model": "DS1104Z Plus · VISA over USB",
            "kind": "instrument",
            "target": self._resource_name or "(未配置 VISA_RESOURCE)",
            "connected": self.connected,
            "mode": self._mode,
            "hostname": None,
            "connected_at": None,
            "uptime_s": None,
            "last_error": self._last_error,
            "backend": "local-visa",
        }

    def connect(self, force_mock: bool = False) -> dict:
        if force_mock:
            self._mode = "mock"
            self._last_error = "force_mock=true，调用方明确要求 mock"
            return self.snapshot()

        if not self._resource_name:
            self._mode = "unknown"
            self._last_error = (
                "未配置 VISA_RESOURCE（示波器资源名）。本机直连前需："
                "① 示波器 USB 驱动切成 WinUSB（Zadig）；② 设 VISA_RESOURCE=USB0::...::INSTR"
            )
            return self.snapshot()

        try:
            import pyvisa  # 延迟导入：ssh 路径不需要它

            self._rm = pyvisa.ResourceManager("@py")  # 纯 Python 后端，不依赖 NI-VISA
            # 列出资源，确认目标存在
            resources = self._rm.list_resources()
            if self._resource_name not in resources:
                self._mode = "unknown"
                self._last_error = (
                    f"VISA_RESOURCE={self._resource_name} 未在设备列表中找到。"
                    f"当前可见资源：{resources or '（空）'}"
                )
                return self.snapshot()
            self._inst = self._rm.open_resource(
                self._resource_name,
                open_timeout=config.VISA_QUERY_TIMEOUT_MS,
                query_delay=0.1,
            )
            self._inst.timeout = config.VISA_QUERY_TIMEOUT_MS
            # 握手：*IDN? 确认真是示波器
            idn = self._inst.query("*IDN?").strip()
            self._mode = "live"
            self._last_error = None
            self._idn = idn
        except Exception as exc:  # noqa: BLE001 —— 连接失败如实记录，不降级 mock
            self._inst = None
            self._mode = "unknown"
            self._last_error = f"{type(exc).__name__}: {exc}"
        return self.snapshot()

    def disconnect(self) -> dict:
        if self._inst is not None:
            try:
                self._inst.close()
            except Exception:  # noqa: BLE001
                pass
        self._inst = None
        self._rm = None
        self._mode = "unknown"
        return self.snapshot()

    def query(self, cmd: str) -> str:
        """发一条 SCPI 查询，返回原始响应字符串。未连接时抛错（由调用方如实呈现）。"""
        if self._inst is None:
            raise RuntimeError(
                f"示波器未连接（last_error={self._last_error or '未尝试连接'}）"
            )
        return self._inst.query(cmd).strip()

    def query_binary(self, cmd: str) -> bytes:
        """发一条二进制查询（如 :WAVeform:DATA?），返回剥掉 IEEE488.2 头后的数据字节。"""
        if self._inst is None:
            raise RuntimeError(
                f"示波器未连接（last_error={self._last_error or '未尝试连接'}）"
            )
        raw = self._inst.query_binary_values(
            cmd, datatype="B", is_big_endian=True, container=bytes
        )
        if isinstance(raw, bytes):
            return raw
        if isinstance(raw, (list, tuple)):
            return bytes(raw)
        return b""
