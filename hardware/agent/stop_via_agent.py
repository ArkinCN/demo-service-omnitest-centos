#!/usr/bin/env python3
"""容器内代理：把 backend 对 stop.py 的调用转发到主机 hw-agent。

与 stop.py 的契约一致：``-RunId <id>`` 必填，``-RunDirectory <dir>`` 可选。
停止语义不变——真正的 stop.py 仍在宿主执行（写 stop.request、下发 SET 0 等 ACK），
本脚本只负责转发，不做任何状态判断。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

HTTP_TIMEOUT_S = 90.0  # stop.py 自身在 backend 侧的超时是 60s，这里留余量


def main() -> int:
    parser = argparse.ArgumentParser(description="通过主机 hw-agent 执行 stop.py")
    parser.add_argument("-RunId", required=True, dest="run_id")
    parser.add_argument("-RunDirectory", default=None, dest="run_directory")
    args = parser.parse_args()

    base_url = (os.environ.get("FAN_AGENT_URL") or "").rstrip("/")
    token = os.environ.get("FAN_AGENT_TOKEN") or ""
    script = os.environ.get("FAN_AGENT_STOP_SCRIPT") or ""
    if not base_url or not token or not script:
        sys.stderr.write("[stop_via_agent] FAN_AGENT_URL / FAN_AGENT_TOKEN / FAN_AGENT_STOP_SCRIPT 未配置\n")
        return 1

    remote_args = ["-RunId", args.run_id]
    if args.run_directory:
        # backend 现在拿到的是**容器视角**目录（run_via_agent 会把 directory 改写成
        # /srv/omnitest/c/...），而 stop.py 在宿主执行，必须换回宿主路径。
        run_directory = args.run_directory
        container_root = os.environ.get("FAN_AGENT_RUNS_ROOT_CONTAINER") or ""
        host_root = os.environ.get("FAN_AGENT_RUNS_ROOT_HOST") or ""
        if container_root and host_root and run_directory.startswith(container_root):
            run_directory = host_root + run_directory[len(container_root):]
        remote_args += ["-RunDirectory", run_directory]

    # 同样的路径陷阱：容器内的 FAN_CONFIG_PATH 宿主不存在，改用宿主专用变量。
    child_env = {
        key: os.environ[key]
        for key in ("FAN_SERIAL_PORT", "SCOPE_VISA_BACKEND")
        if key in os.environ
    }
    overlay_host_path = os.environ.get("FAN_AGENT_CONFIG_PATH")
    if overlay_host_path:
        child_env["FAN_CONFIG_PATH"] = overlay_host_path

    payload = json.dumps(
        {"script": script, "args": remote_args, "env": child_env, "timeout": 60}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/exec",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "X-Agent-Token": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        sys.stderr.write(f"[stop_via_agent] agent 返回 HTTP {exc.code}\n")
        return 1
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[stop_via_agent] 无法连接主机 agent：{exc}\n")
        return 1

    if result.get("stdout"):
        sys.stdout.write(result["stdout"])
    if result.get("stderr"):
        sys.stderr.write(result["stderr"])
    if not result.get("ok"):
        sys.stderr.write(f"[stop_via_agent] 远端执行失败：{result.get('error')}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
