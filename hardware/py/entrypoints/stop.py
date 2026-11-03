"""停止（对应原 stop.ps1）。

写 stop.request 并轮询 summary.json（每 100ms），返回 finished 或 requested_unconfirmed。
退出码：0=已完成（summary 未 failed），1=失败/异常（summary.failed 或参数错），2=请求未确认。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import runtime  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 默认主配置：与后端 fan_executor.py 一致（原 hardware/py/config/experiment.json 不存在）
DEFAULT_CONFIG = os.path.join(os.path.dirname(HERE), "v0.6", "config", "acceptance.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-RunId", "--run-id", required=True)
    ap.add_argument("-ConfigPath", "--config", default="")
    ap.add_argument("-RunDirectory", "--run-directory", default="")
    ap.add_argument("-WaitSeconds", "--wait-seconds", type=int, default=30)
    args = ap.parse_args()

    if not re.match(r"^[a-zA-Z0-9_-]{1,100}$", args.run_id):
        sys.stderr.write("Invalid RunId.\n")
        return 1
    if not (0 <= args.wait_seconds <= 120):
        sys.stderr.write("WaitSeconds out of range 0..120.\n")
        return 1
    try:
        if args.run_directory:
            directory = os.path.realpath(args.run_directory)
            if os.path.basename(directory) != args.run_id:
                raise RuntimeError("RunDirectory leaf must match RunId.")
        else:
            explicit = bool(args.config)
            config_path = args.config or DEFAULT_CONFIG
            loaded = runtime.read_experiment_config(config_path, allow_overlay=not explicit)
            directory = os.path.join(loaded.output_root, args.run_id)
        if not os.path.isdir(directory):
            raise RuntimeError("Unknown runId.")
        summary_path = os.path.join(directory, "summary.json")
        if not os.path.exists(summary_path):
            with open(os.path.join(directory, "stop.request"), "w", encoding="utf-8") as fh:
                fh.write(datetime.now(timezone.utc).isoformat())
        start = time.monotonic()
        while not os.path.exists(summary_path) and (time.monotonic() - start) < args.wait_seconds:
            time.sleep(0.1)
        if os.path.exists(summary_path):
            with open(summary_path, "r", encoding="utf-8") as fh:
                summary = json.load(fh)
            out = {"schemaVersion": "1.0", "action": "stop", "status": "finished",
                   "runId": args.run_id, "summary": summary}
            print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
            return 1 if summary.get("failed") else 0
        out = {
            "schemaVersion": "1.0", "action": "stop", "status": "requested_unconfirmed",
            "runId": args.run_id,
            "physicalState": "unknown until cleanup ACK; never infer stop from process exit",
            "summaryPath": summary_path,
        }
        print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
        return 2
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(str(e) + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
