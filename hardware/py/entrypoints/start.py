"""异步启动器（对应原 start.ps1）。

建运行目录 + 认领（写入 token 到 run.claim）+ 冻结含绝对根的快照，
后台启动 run_experiment.py（脱离本终端），返回单行 launch JSON。

返回 JSON（与 start.ps1 对齐）：
  {"schemaVersion":"1.0","action":"start","status":"launched","runId":...,"processId":...,
   "directory":...,"eventsPath":...,"summaryPath":...,"stopRequestPath":...}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import runtime  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # hardware/py
# 默认主配置：与后端 fan_executor.py 一致，指向 hardware/v0.6/config/acceptance.json
# （原默认 hardware/py/config/experiment.json 目录不存在，属历史 bug，2026-10-07 修）
DEFAULT_CONFIG = os.path.join(os.path.dirname(HERE), "v0.6", "config", "acceptance.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-ConfigPath", "--config", default="")
    ap.add_argument("-RunId", "--run-id", default="")
    ap.add_argument("-Simulation", "--simulation", action="store_true")
    args = ap.parse_args()

    if args.run_id and not re.match(r"^[a-zA-Z0-9_-]{1,100}$", args.run_id):
        sys.stderr.write("Invalid RunId.\n")
        return 1
    # 显式传 -ConfigPath → 不叠加 overlay；走默认路径 → 允许 overlay（FAN_CONFIG_PATH）
    explicit = bool(args.config)
    config_path = args.config or DEFAULT_CONFIG
    try:
        loaded = runtime.read_experiment_config(config_path, allow_overlay=not explicit)
        run_id = args.run_id or (datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] + "_" + uuid.uuid4().hex[:8])
        directory = os.path.join(loaded.output_root, run_id)
        if os.path.exists(directory):
            raise RuntimeError("Run directory already exists.")
        os.makedirs(directory)

        token = uuid.uuid4().hex
        with open(os.path.join(directory, "run.claim"), "w", encoding="ascii") as fh:
            fh.write(token)

        # 冻结快照：output.root 写绝对路径（子进程读快照，不读易变的用户配置）
        snap = dict(loaded.config)
        snap["output"] = {"root": loaded.output_root}
        snapshot_path = os.path.join(directory, "config.snapshot.json")
        with open(snapshot_path, "w", encoding="utf-8") as fh:
            json.dump(snap, fh, ensure_ascii=False, indent=2)

        runner = os.path.join(HERE, "run_experiment.py")
        cmd = [sys.executable, runner, "-ConfigPath", snapshot_path, "-RunId", run_id, "-ClaimToken", token]
        if args.simulation:
            cmd.append("-Simulation")

        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        out = open(os.path.join(directory, "stdout.jsonl"), "w", encoding="utf-8")
        err = open(os.path.join(directory, "stderr.log"), "w", encoding="utf-8")
        proc = subprocess.Popen(cmd, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                cwd=HERE, creationflags=flags)

        result = {
            "schemaVersion": "1.0", "action": "start", "status": "launched", "runId": run_id,
            "processId": proc.pid, "directory": directory,
            "eventsPath": os.path.join(directory, "events.jsonl"),
            "summaryPath": os.path.join(directory, "summary.json"),
            "stopRequestPath": os.path.join(directory, "stop.request"),
        }
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(str(e) + "\n")
        # 可操作提示（2026-10-09 增）：配置解析失败且未设 FAN_CONFIG_PATH 时，
        # 大概率是主配置的 serial.port / scope.resource 留空未被 overlay 补齐。
        # 仅在错误分支补一句可执行指引，不改控制流（数据纪律：不掩盖真实原因）。
        if not os.environ.get("FAN_CONFIG_PATH"):
            sys.stderr.write(
                "提示：未设置 FAN_CONFIG_PATH。主配置的 serial.port / scope.resource "
                "留空，需由 overlay 补齐；请设 FAN_CONFIG_PATH 指向 "
                "hardware/v0.6/config/acceptance.windows.json（Windows）或 "
                "acceptance.linux.json（Linux）。\n"
            )
        return 1


if __name__ == "__main__":
    sys.exit(main())
