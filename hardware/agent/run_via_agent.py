#!/usr/bin/env python3
"""容器内代理：把 backend 对 start.py 的调用转发到主机 hw-agent。

为什么需要它
------------
NI-VISA 的 NI-PAL 无法在容器内初始化，真实采集必须跑在宿主。本脚本让
``RealFanExecutor`` **完全无感**——它看到的仍是一个普通的本地子进程。

与 start.py 的契约保持一致（backend 只依赖这三点）
--------------------------------------------------
1. 参数：``-RunId <id>``
2. stdout 首行：单行 JSON（含 ``eventsPath``），供后端定位事件流
3. 退出码：0 = 采集正常收尾；非零 = 失败，且 stderr 有可行动原因

⚠️ 关键认知：start.py 是**瞬时启动器**——拉起 ``run_experiment.py`` 后立刻退出。
所以本代理**不能**用"启动器是否退出"判断采集是否结束，必须等事件流里的
``run_finished``（或 summary.json 的 ``terminalPublished``）。runs/ 是 bind-mount，
容器内能直接读这些文件。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

POLL_INTERVAL_S = 1.0
FIRST_LINE_WAIT_S = 15.0
TERMINAL_SETTLE_S = 2.0
EVENT_TAIL_BYTES = 8192
MAX_WAIT_S = float(os.environ.get("FAN_AGENT_MAX_WAIT_S", "1800"))
HTTP_TIMEOUT_S = 15.0

EXIT_OK = 0
EXIT_FAILED = 1


def _request(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "X-Agent-Token": token},
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
        return json.loads(response.read().decode("utf-8"))


def _fail(message: str) -> int:
    sys.stderr.write(f"[run_via_agent] {message}\n")
    sys.stderr.flush()
    return EXIT_FAILED


def _has_terminal(events_path: Path | None) -> bool:
    """事件流是否已收尾：summary.json 的 terminalPublished 或 run_finished 事件。"""
    if events_path is None:
        return False
    summary_path = events_path.parent / "summary.json"
    try:
        if summary_path.is_file():
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            if data.get("terminalPublished"):
                return True
    except (OSError, json.JSONDecodeError):
        pass
    try:
        if events_path.is_file():
            text = events_path.read_text(encoding="utf-8", errors="replace")
            return '"run_finished"' in text[-EVENT_TAIL_BYTES:]
    except OSError:
        pass
    return False


def _rewrite_launch_paths(first_line: str) -> str:
    """把 launch JSON 里**供容器读取**的路径改写成容器视角。

    为什么：backend 在容器里按这些路径读事件流、终态与**波形 CSV**，而 start.py
    打印的是宿主绝对路径。不改写就会出现"文件明明在写、后端却读不到"。
    ``directory`` 也必须改写 —— 波形接口 read_capture_waveforms 正是用它拼
    CH*.csv 的路径（漏改的直接后果：波形图全部 available=false）。
    与宿主交互的路径转换由 stop_via_agent 在转发时反向完成。
    """
    try:
        launch = json.loads(first_line) if first_line else {}
    except json.JSONDecodeError:
        return first_line
    host_root = os.environ.get("FAN_AGENT_RUNS_ROOT_HOST") or ""
    container_root = os.environ.get("FAN_AGENT_RUNS_ROOT_CONTAINER") or ""
    if not host_root or not container_root:
        return first_line
    for key in ("eventsPath", "summaryPath", "directory"):
        value = launch.get(key)
        if isinstance(value, str) and value.startswith(host_root):
            launch[key] = container_root + value[len(host_root):]
    return json.dumps(launch, ensure_ascii=False)


def _container_events_path(first_line: str) -> Path | None:
    """把 launch JSON 里的宿主 eventsPath 映射成容器内路径。

    依赖两个环境变量（部署时注入）：
      FAN_AGENT_RUNS_ROOT_HOST       宿主侧 runs 根目录
      FAN_AGENT_RUNS_ROOT_CONTAINER  容器侧对应挂载点
    """
    try:
        launch = json.loads(first_line) if first_line else {}
    except json.JSONDecodeError:
        return None
    host_events = launch.get("eventsPath") or ""
    host_root = os.environ.get("FAN_AGENT_RUNS_ROOT_HOST") or ""
    container_root = os.environ.get("FAN_AGENT_RUNS_ROOT_CONTAINER") or ""
    if not host_events or not host_root or not container_root:
        return None
    if not host_events.startswith(host_root):
        return None
    relative = host_events[len(host_root):].lstrip("/")
    return Path(container_root) / relative


def main() -> int:
    parser = argparse.ArgumentParser(description="通过主机 hw-agent 启动采集脚本")
    parser.add_argument("-RunId", required=True, dest="run_id")
    args = parser.parse_args()

    base_url = (os.environ.get("FAN_AGENT_URL") or "").rstrip("/")
    token = os.environ.get("FAN_AGENT_TOKEN") or ""
    script = os.environ.get("FAN_AGENT_START_SCRIPT") or ""
    if not base_url or not token or not script:
        return _fail("FAN_AGENT_URL / FAN_AGENT_TOKEN / FAN_AGENT_START_SCRIPT 未配置")

    # 只透传硬件侧真正需要的变量。
    # ⚠️ 不能直接透传容器内的 FAN_CONFIG_PATH / FAN_PYTHON：它们在容器里是
    # /srv/omnitest/... 这类路径，宿主上并不存在，传过去必然解析失败。
    child_env = {
        key: os.environ[key]
        for key in ("FAN_SERIAL_PORT", "SCOPE_VISA_BACKEND")
        if key in os.environ
    }
    overlay_host_path = os.environ.get("FAN_AGENT_CONFIG_PATH")
    if overlay_host_path:
        child_env["FAN_CONFIG_PATH"] = overlay_host_path

    try:
        _request(
            "POST",
            f"{base_url}/runs",
            token,
            {"run_id": args.run_id, "script": script, "args": ["-RunId", args.run_id], "env": child_env},
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        return _fail(f"agent 拒绝启动（HTTP {exc.code}）：{detail}")
    except Exception as exc:  # noqa: BLE001 - 网络异常统一转成可行动提示
        return _fail(f"无法连接主机 agent（{base_url}）：{exc}")

    status_url = f"{base_url}/runs/{args.run_id}/status"

    # ---- 等首行 launch JSON 并原样打到 stdout（backend 靠它定位 events.jsonl）----
    deadline = time.monotonic() + FIRST_LINE_WAIT_S
    first_line = ""
    while time.monotonic() < deadline:
        try:
            status = _request("GET", status_url, token)
        except Exception:  # noqa: BLE001 - 轮询期间偶发失败不致命
            status = {}
        first_line = (status.get("first_line") or "").strip()
        if first_line:
            break
        if status.get("alive") is False:
            break
        time.sleep(POLL_INTERVAL_S)
    raw_first_line = first_line
    if raw_first_line:
        # 打印给后端的是**改写后的容器视角路径**；本脚本自己仍用原始宿主路径判断终态。
        sys.stdout.write(_rewrite_launch_paths(raw_first_line) + "\n")
        sys.stdout.flush()

    events_path = _container_events_path(raw_first_line)

    # ---- 等事件流收尾（而不是等启动器退出）----
    wait_deadline = time.monotonic() + MAX_WAIT_S
    while True:
        if _has_terminal(events_path):
            return EXIT_OK
        try:
            status = _request("GET", status_url, token)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"轮询 agent 状态失败：{exc}")
        if status.get("alive") is False:
            # worker 已退出：给终态落盘留一个短暂宽限，再判定成败。
            time.sleep(TERMINAL_SETTLE_S)
            if _has_terminal(events_path):
                return EXIT_OK
            tail = status.get("log_tail") or ""
            if tail:
                sys.stderr.write(tail if tail.endswith("\n") else tail + "\n")
                sys.stderr.flush()
            code = status.get("exit_code")
            return EXIT_FAILED if code is None else int(code)
        if time.monotonic() > wait_deadline:
            return _fail(f"等待采集收尾超时（>{MAX_WAIT_S:.0f}s）")
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    raise SystemExit(main())
