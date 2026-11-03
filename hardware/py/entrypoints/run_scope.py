"""示波器独立采集（对应原 run-scope.ps1）。

不碰串口：注入假 serial 以通过共享校验（scope-only），只配示波器并抓一次。
发 run_started(mode=scope_only) → scope_configured → capture_completed → run_finished。
capture 的 commandedPwmPercent=null、fanCommandIssued=false（没发过风扇命令）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import runtime  # noqa: E402
import scope_capture  # noqa: E402
from scope_visa import ScopeDevice  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 默认主配置：与后端一致（原 hardware/py/config/experiment.json 不存在）
DEFAULT_CONFIG = os.path.join(os.path.dirname(HERE), "v0.6", "config", "acceptance.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-ConfigPath", "--config", default="")
    ap.add_argument("-RunId", "--run-id", default="")
    args = ap.parse_args()

    config_path = args.config or DEFAULT_CONFIG
    resolved = os.path.realpath(config_path)
    temp = os.path.join(os.path.dirname(resolved), f"scope-validation-{uuid.uuid4().hex}.json")
    seq = 0
    failed = False
    message = ""
    count = 0
    scope = None
    directory = ""
    run_id = args.run_id
    try:
        with open(resolved, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        # 注入假 serial，scope-only 不碰串口
        cfg["serial"] = {"port": "COM1", "baud": 115200,
                         "expectedIdentity": "READY UNO_FAN_V2 25000", "wiringConfirmed": True}
        cfg["scope"]["enabled"] = True
        with open(temp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)

        # 隔离测试：显式传 temp 路径，禁止叠加 FAN_CONFIG_PATH overlay，
        # 否则 scope-only 的假 serial 注入会被外部 overlay 覆盖而失效。
        loaded = runtime.read_experiment_config(temp, allow_overlay=False)
        c = loaded.config
        run_id = run_id or ("scope_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] + "_" + uuid.uuid4().hex[:8])
        directory = os.path.join(loaded.output_root, run_id)
        os.makedirs(directory, exist_ok=True)
        open(os.path.join(directory, "run.claim"), "w").close()
        with open(os.path.join(directory, "config.snapshot.json"), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)

        def emit(t, state, data):
            nonlocal seq
            seq += 1
            runtime.write_run_event(run_id, directory, seq, t, state, data)

        emit("run_started", "starting", {"mode": "scope_only", "fanCommandIssued": False,
                                         "directory": directory, "configPath": resolved})
        scope = ScopeDevice(c["scope"]["resource"], c["scope"].get("expectedIdentity"))
        settings = scope_capture.initialize_scope(scope, c["scope"])
        with open(os.path.join(directory, "scope-settings.json"), "w", encoding="utf-8") as fh:
            json.dump(settings, fh, ensure_ascii=False, indent=2)
        emit("scope_configured", "running", settings)
        time.sleep(int(-(-c["experiment"]["settleSeconds"] * 1000) // 1) / 1000)
        for capture in scope_capture.save_fan_scope_capture(scope, c["scope"], directory, 1, -1):
            capture["commandedPwmPercent"] = None
            capture["fanCommandIssued"] = False
            # ⚠️ 2026-10-09：合并后 artifacts 含**多份** capture.json
            # （<tag>/pwm/capture.json、<tag>/tach/capture.json、<tag>/capture.json），
            # 原用 next(...) 只覆盖第一份 → tach 档那份的 commandedPwmPercent 会残留 -1。
            # 改为逐份覆盖写（scope-only 路径**没有下发过风扇命令**，故全部置 null 才是真的）。
            for meta_path in (a for a in capture["artifacts"] if os.path.basename(a) == "capture.json"):
                with open(meta_path, "w", encoding="utf-8") as fh:
                    json.dump(capture, fh, ensure_ascii=False, indent=2)
            count += 1
            emit("capture_completed", "running", capture)
    except Exception as e:  # noqa: BLE001
        failed = True
        message = str(e)
        sys.stderr.write(message + "\n")
        if directory:
            try:
                seq += 1
                runtime.write_run_event(run_id, directory, seq, "run_error", "starting", {"message": message})
            except Exception as e2:  # noqa: BLE001
                sys.stderr.write(str(e2) + "\n")
    finally:
        if scope is not None:
            try:
                scope.dispose()
            except Exception as e:  # noqa: BLE001
                failed = True
                message = str(e)
        try:
            if os.path.exists(temp):
                os.remove(temp)
        except OSError as e:
            failed = True
            message = str(e)
        if directory:
            summary = {
                "schemaVersion": "1.0", "runId": run_id, "mode": "scope_only",
                "state": "failed" if failed else "completed", "terminalPublished": False,
                "failed": failed, "failureMessage": message, "captureCount": count,
                "fanCommandIssued": False, "exitCode": 1 if failed else 0, "directory": directory,
                "eventsPath": os.path.join(directory, "events.jsonl"),
            }
            try:
                seq += 1
                runtime.write_run_event(run_id, directory, seq, "run_finished",
                                        summary["state"], summary)
            except Exception as e:  # noqa: BLE001
                failed = True
                summary["failed"] = True
                summary["state"] = "failed"
                summary["exitCode"] = 1
                summary["failureMessage"] = str(e)
            summary["terminalPublished"] = True
            summary_path = os.path.join(directory, "summary.json")
            with open(summary_path + ".tmp", "w", encoding="utf-8") as fh:
                json.dump(summary, fh, ensure_ascii=False, indent=2)
            os.replace(summary_path + ".tmp", summary_path)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
