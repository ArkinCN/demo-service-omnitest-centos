#!/usr/bin/env python3
"""OmniTest 硬件采集 agent（主机侧 sidecar）。

为什么需要它
------------
NI-VISA 的 NI-PAL 无法在 Docker 容器内完成初始化（实测 ``--privileged`` /
``--ipc=host`` / ``--pid=host`` 均返回 ``VI_ERROR_SYSTEM_ERROR``，而宿主进程一切
正常），因此示波器采集只能运行在宿主。本服务只做一件事：把「运行 hardware/py
下的采集脚本」暴露成最小 HTTP 接口，容器内的 backend 通过它下发启动/停止请求；
采集数据仍由脚本自己写入共享的 ``runs/`` 目录，后端照旧从磁盘读事件流。

刻意不做的事（保持职责单一，便于测试与替换）
--------------------------------------------
- 不含任何实验/业务逻辑：不解析事件流、不读 CSV、不碰数据库、不接触前端；
- 不管理运行的业务状态：终态由 ``summary.json`` / ``events.jsonl`` 决定（在 backend 侧）；
- 只执行 SCRIPT_ROOT 之内的 ``.py`` 脚本，杜绝被当成通用命令执行器。

接口
----
==========================  ==========================================
GET  /healthz               存活与运行时信息（无需 token，便于本机排障）
GET  /runs                  当前跟踪的运行列表
POST /runs                  异步启动脚本（用于 start.py），返回 pid
GET  /runs/{run_id}/status  存活 / 退出码 / stdout 首行（start.py 的 launch JSON）
POST /exec                  同步执行脚本（用于 stop.py），返回退出码与输出
POST /runs/{run_id}/stop    向进程组发 SIGINT（兜底手段；正常停止走 stop.py）
==========================  ==========================================

安全
----
- 只监听 HWA_BIND（默认 Docker 网桥宿主侧地址），局域网不可达；
- 除 /healthz 外所有接口校验 ``X-Agent-Token``（常量时间比较）；
- 脚本路径必须位于 HWA_SCRIPT_ROOT 之内。
"""

from __future__ import annotations

import hmac
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# ───────────────────────────── 常量（杜绝散落魔法值）─────────────────────────────
RUN_ID_PATTERN = re.compile(r"^[0-9a-zA-Z_-]{1,64}$")
MAX_BODY_BYTES = 64 * 1024
MAX_TRACKED_RUNS = 50
MAX_OUTPUT_CHARS = 4000
DEFAULT_EXEC_TIMEOUT_S = 60.0

HTTP_OK = 200
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_NOT_FOUND = 404
HTTP_CONFLICT = 409
HTTP_SERVER_ERROR = 500

# ───────────────────────── 运行时配置（由 systemd 注入）─────────────────────────
BIND = os.environ.get("HWA_BIND", "172.21.0.1")
PORT = int(os.environ.get("HWA_PORT", "8790"))
TOKEN = os.environ.get("HWA_TOKEN", "")
PYTHON = os.environ.get("HWA_PYTHON", sys.executable)
SCRIPT_ROOT = Path(os.environ.get("HWA_SCRIPT_ROOT", ".")).resolve()
STATE_DIR = Path(os.environ.get("HWA_STATE_DIR") or (Path.home() / ".omnitest-agent")).resolve()
LOG_DIR = STATE_DIR / "logs"

STARTED_AT = time.time()
_registry_lock = threading.Lock()
_runs: dict[str, dict[str, Any]] = {}


class ConflictError(RuntimeError):
    """已有活跃运行时再次请求启动（单设备锁的第二道防线）。"""


# ───────────────────────────────── 工具函数 ─────────────────────────────────
def _now() -> float:
    return time.time()


def _active_run_id() -> str | None:
    """当前仍存活的 run_id（同一时刻至多一个）。"""
    with _registry_lock:
        for run_id, record in _runs.items():
            if _record_alive(record):
                return run_id
    return None


def _trim_registry() -> None:
    """只保留最近 MAX_TRACKED_RUNS 条已结束记录，防止长跑服务内存缓慢膨胀。"""
    with _registry_lock:
        overflow = len(_runs) - MAX_TRACKED_RUNS
        if overflow <= 0:
            return
        finished = sorted(
            ((rid, rec) for rid, rec in _runs.items() if rec["proc"].poll() is not None),
            key=lambda item: item[1]["started_at"],
        )
        for run_id, _record in finished[:overflow]:
            _runs.pop(run_id, None)


def _resolve_script(raw_path: str) -> Path:
    """校验脚本：存在、是 .py、且位于 SCRIPT_ROOT 之内。"""
    candidate = Path(raw_path).resolve()
    if candidate.suffix != ".py":
        raise ValueError("script 必须是 .py 文件")
    if not candidate.is_file():
        raise ValueError(f"script 不存在：{candidate}")
    if candidate != SCRIPT_ROOT and SCRIPT_ROOT not in candidate.parents:
        raise ValueError(f"script 越界（必须位于 {SCRIPT_ROOT} 内）：{candidate}")
    return candidate


def _first_line(log_path: Path) -> str:
    """读日志首行 —— start.py 会在这里打印含 eventsPath 的单行 JSON。"""
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.readline().strip()
    except OSError:
        return ""


def _parse_worker_pid(first_line: str) -> int | None:
    """从 start.py 的 launch JSON 里取真实 worker 的 pid。"""
    try:
        payload = json.loads(first_line)
    except (json.JSONDecodeError, TypeError):
        return None
    pid = payload.get("processId")
    return int(pid) if isinstance(pid, int) else None


def _worker_alive(pid: int | None) -> bool:
    """判断真实采集进程（run_experiment.py）是否存活。

    为什么需要它：start.py 是**瞬时启动器**——拉起 run_experiment.py 后立刻退出，
    所以「启动器退出」不等于「采集结束」。真实 worker 的 pid 出现在 start.py
    打印的 launch JSON 的 ``processId`` 字段里。
    """
    if not pid:
        return False
    return Path(f"/proc/{pid}").exists()


def _record_alive(record: dict[str, Any]) -> bool:
    """一次运行是否仍在进行：启动器存活，或它拉起的真实 worker 存活。

    worker pid 从 start.py 的首行 launch JSON 解析并缓存在 record 上——启动器
    退出后仍要能追踪到 worker，否则会被误判为"已结束"。
    """
    if record["proc"].poll() is None:
        return True
    worker_pid = record.get("worker_pid")
    if worker_pid is None:
        worker_pid = _parse_worker_pid(_first_line(record["log_path"]))
        if worker_pid:
            record["worker_pid"] = worker_pid
    return _worker_alive(worker_pid)


def _tail(log_path: Path, limit: int = 2000) -> str:
    """读日志尾部 —— 供容器内的代理脚本镜像到自己的 stderr。

    为什么要镜像：backend 的 RealFanExecutor 在早失败窗口会读子进程 stderr
    透传真实原因；而子进程实际跑在宿主，容器侧读不到宿主日志文件，只能由
    agent 把尾部内容带回。
    """
    try:
        size = log_path.stat().st_size
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            if size > limit:
                handle.seek(size - limit)
            return handle.read()
    except OSError:
        return ""


def _child_env(extra: dict[str, Any]) -> dict[str, str]:
    """继承服务进程环境，再叠加调用方传入的变量（调用方优先）。"""
    env = dict(os.environ)
    env.update({str(key): str(value) for key, value in extra.items()})
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


# ────────────────────────────────── HTTP 层 ──────────────────────────────────
class AgentHandler(BaseHTTPRequestHandler):
    server_version = "OmniTestHWAgent/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - 覆盖基类钩子
        sys.stderr.write("[agent] %s - %s\n" % (self.address_string(), fmt % args))

    # ---- 响应/请求辅助 ----
    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ValueError("请求体过大")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _require_token(self) -> bool:
        supplied = self.headers.get("X-Agent-Token", "")
        if TOKEN and hmac.compare_digest(supplied, TOKEN):
            return True
        self._send_json(HTTP_UNAUTHORIZED, {"ok": False, "error": "invalid token"})
        return False

    @staticmethod
    def _run_id_from(path: str, suffix: str) -> str:
        parts = path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "runs" or parts[2] != suffix:
            raise ValueError("非法路径")
        run_id = parts[1]
        if not RUN_ID_PATTERN.match(run_id):
            raise ValueError("非法 run_id")
        return run_id

    # ---- 路由 ----
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
        try:
            if self.path == "/healthz":
                return self._handle_health()
            if not self._require_token():
                return
            if self.path == "/runs":
                return self._handle_list_runs()
            if self.path.startswith("/runs/") and self.path.endswith("/status"):
                return self._handle_status(self._run_id_from(self.path, "status"))
            self._send_json(HTTP_NOT_FOUND, {"ok": False, "error": "not found"})
        except ValueError as exc:
            self._send_json(HTTP_BAD_REQUEST, {"ok": False, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - 兜底：绝不把栈抛给调用方
            self._send_json(HTTP_SERVER_ERROR, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
        try:
            if not self._require_token():
                return
            if self.path == "/runs":
                return self._handle_start()
            if self.path == "/exec":
                return self._handle_exec()
            if self.path.startswith("/runs/") and self.path.endswith("/stop"):
                return self._handle_stop(self._run_id_from(self.path, "stop"))
            self._send_json(HTTP_NOT_FOUND, {"ok": False, "error": "not found"})
        except ConflictError as exc:
            self._send_json(HTTP_CONFLICT, {"ok": False, "error": str(exc)})
        except ValueError as exc:
            self._send_json(HTTP_BAD_REQUEST, {"ok": False, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._send_json(HTTP_SERVER_ERROR, {"ok": False, "error": str(exc)})

    # ---- 各接口实现 ----
    def _handle_health(self) -> None:
        self._send_json(
            HTTP_OK,
            {
                "ok": True,
                "pid": os.getpid(),
                "user": os.environ.get("USER", ""),
                "python": PYTHON,
                "script_root": str(SCRIPT_ROOT),
                "active_run": _active_run_id(),
                "tracked": len(_runs),
                "uptime_s": round(_now() - STARTED_AT, 1),
            },
        )

    def _handle_list_runs(self) -> None:
        with _registry_lock:
            snapshot = [
                {
                    "run_id": run_id,
                    "pid": record["proc"].pid,
                    "alive": record["proc"].poll() is None,
                    "exit_code": record["proc"].poll(),
                    "started_at": record["started_at"],
                }
                for run_id, record in _runs.items()
            ]
        self._send_json(HTTP_OK, {"ok": True, "runs": snapshot})

    def _handle_start(self) -> None:
        payload = self._read_json()
        run_id = str(payload.get("run_id") or "")
        if not RUN_ID_PATTERN.match(run_id):
            raise ValueError("非法 run_id")
        script = _resolve_script(str(payload.get("script") or ""))
        args = [str(item) for item in (payload.get("args") or [])]
        cwd = payload.get("cwd") or None

        active = _active_run_id()
        if active and active != run_id:
            raise ConflictError(f"已有运行 {active} 在进行，拒绝并发启动")

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"{run_id}.log"
        # 子进程持有自己的 fd，父进程随后即可关闭，避免句柄泄漏。
        log_handle = log_path.open("w", encoding="utf-8", errors="replace")
        try:
            process = subprocess.Popen(
                [PYTHON, str(script), *args],
                cwd=cwd,
                env=_child_env(payload.get("env") or {}),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # 独立进程组，便于按组发信号
            )
        finally:
            log_handle.close()

        with _registry_lock:
            _runs[run_id] = {
                "proc": process,
                "log_path": log_path,
                "started_at": _now(),
                "script": str(script),
            }
        _trim_registry()
        self._send_json(HTTP_OK, {"ok": True, "run_id": run_id, "pid": process.pid})

    def _handle_status(self, run_id: str) -> None:
        with _registry_lock:
            record = _runs.get(run_id)
        if record is None:
            # agent 重启后内存失忆：如实告知"不认识"，由 backend 用磁盘新鲜度兜底。
            return self._send_json(
                HTTP_OK, {"ok": True, "run_id": run_id, "known": False, "alive": False}
            )
        launcher_code = record["proc"].poll()
        alive = _record_alive(record)
        first_line = _first_line(record["log_path"])
        self._send_json(
            HTTP_OK,
            {
                "ok": True,
                "run_id": run_id,
                "known": True,
                "alive": alive,
                # 启动器退出码不等于采集结果：真实终态由 events/summary 决定。
                "exit_code": None if alive else launcher_code,
                "worker_pid": record.get("worker_pid"),
                "pid": record["proc"].pid,
                "started_at": record["started_at"],
                "first_line": first_line,
                "log_tail": _tail(record["log_path"]),
                "log_path": str(record["log_path"]),
            },
        )

    def _handle_exec(self) -> None:
        payload = self._read_json()
        script = _resolve_script(str(payload.get("script") or ""))
        args = [str(item) for item in (payload.get("args") or [])]
        cwd = payload.get("cwd") or None
        timeout = float(payload.get("timeout") or DEFAULT_EXEC_TIMEOUT_S)
        try:
            completed = subprocess.run(
                [PYTHON, str(script), *args],
                cwd=cwd,
                env=_child_env(payload.get("env") or {}),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return self._send_json(
                HTTP_OK, {"ok": False, "error": "timeout", "timeout_s": timeout}
            )
        self._send_json(
            HTTP_OK,
            {
                "ok": True,
                "exit_code": completed.returncode,
                "stdout": (completed.stdout or "")[-MAX_OUTPUT_CHARS:],
                "stderr": (completed.stderr or "")[-MAX_OUTPUT_CHARS:],
            },
        )

    def _handle_stop(self, run_id: str) -> None:
        with _registry_lock:
            record = _runs.get(run_id)
        if record is None or record["proc"].poll() is not None:
            return self._send_json(HTTP_OK, {"ok": True, "signalled": False})
        try:
            os.killpg(os.getpgid(record["proc"].pid), signal.SIGINT)
        except OSError as exc:
            return self._send_json(HTTP_OK, {"ok": False, "error": str(exc)})
        self._send_json(HTTP_OK, {"ok": True, "signalled": True})


def main() -> int:
    if not TOKEN:
        sys.stderr.write("[agent] 拒绝启动：HWA_TOKEN 未配置\n")
        return 2
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((BIND, PORT), AgentHandler)
    sys.stderr.write(
        f"[agent] listening on {BIND}:{PORT} | python={PYTHON} | script_root={SCRIPT_ROOT}\n"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
