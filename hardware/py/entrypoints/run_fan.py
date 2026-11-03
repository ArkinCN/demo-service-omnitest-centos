"""独立跑风扇（对应原 run-fan.ps1）。

复制配置并把 scope.enabled 置 false，写临时配置，前台运行 run_experiment.py。
临时配置在 finally 删除；退出码透传子进程。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 默认主配置：与后端一致（原 hardware/py/config/experiment.json 不存在）
DEFAULT_CONFIG = os.path.join(os.path.dirname(HERE), "v0.6", "config", "acceptance.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-ConfigPath", "--config", default="")
    ap.add_argument("-RunId", "--run-id", default="")
    ap.add_argument("-Simulation", "--simulation", action="store_true")
    args = ap.parse_args()

    config_path = args.config or DEFAULT_CONFIG
    resolved = os.path.realpath(config_path)
    temp = os.path.join(os.path.dirname(resolved), f"fan-mode-{uuid.uuid4().hex}.json")
    code = 1
    try:
        with open(resolved, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        cfg["scope"]["enabled"] = False
        with open(temp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)

        cmd = [sys.executable, os.path.join(HERE, "run_experiment.py"), "-ConfigPath", temp]
        if args.run_id:
            cmd += ["-RunId", args.run_id]
        if args.simulation:
            cmd.append("-Simulation")
        code = subprocess.call(cmd, cwd=HERE)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(str(e) + "\n")
        code = 1
    finally:
        try:
            if os.path.exists(temp):
                os.remove(temp)
        except OSError as e:
            sys.stderr.write(str(e) + "\n")
            code = 1
    return code


if __name__ == "__main__":
    sys.exit(main())
