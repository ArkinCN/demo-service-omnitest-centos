"""风扇联合实验主流程（Python 重写，对应原 run-experiment.ps1）。

流程：读配置 → 建运行目录/认领 → 识别 UNO → 配示波器 → 逐档 SET PWM + 采集 →
安全收尾（SET 0）→ 原子发布 summary.json。

行为对齐点（与原 .ps1 逐条对应）：
- 运行目录已存在则报错；run.claim（带 ClaimToken 时校验）。
- 事件类型/字段/状态与原一致（run_started / controller_identified / command_ack /
  scope_configured / step_started / capture_completed / timing_overrun / step_completed /
  cycle_completed / run_error / run_finished）。
- commands.csv 追加（timestampUtc,cycle,dutyPercent,command,ack,status）。
- 终态：failed > stopped > completed；summary 先写 .tmp 再 os.replace，terminalPublished 最后置 true。
- cleanup 取值：pwm_zero_acknowledged_physical_stop_unverified / failed_physical_state_unknown /
  no_identified_controller_no_zero_command。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

# 允许直接 `python run_experiment.py` 与包内导入两种方式
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fan_serial
import runtime
import scope_capture
from fan_serial import CancelSignal, FanSession, SerialWire
from scope_visa import ScopeDevice


# ---------------------------------------------------------------------------
# 满载档的物理占空比上限（2026-10-12）
# ---------------------------------------------------------------------------
# 为什么 100% 档实际只跑 99%：
#   100% 占空比下 PWM 输出**恒高电平、没有边沿**，示波器按边沿触发（CH3 为触发源）
#   永远等不到触发点 → 该档读不到波形（preamble 全 0、`inc=0`），整档必然失败。
#   实测：配置 100% 时该档 0 个 CSV，而 99% 仍有边沿，可正常采集。
#
# 口径（配置与展示不动，只动下发指令）：
#   · **配置** `experiment.dutiesPercent` 仍是 100 —— 业务语义就是「满载档」；
#   · **页面展示**仍是 100% —— 前端读的就是配置值，无需任何映射；
#   · **实际下发**给 UNO 的指令用 99 —— 由此规避恒高电平；
#   · **数据记录**如实留痕：commands.csv 里记的是 `SET 99`（真实指令），
#     commandedPwmPercent 仍是 100（档位语义），实测占空比如实显示约 99%。
# 这样「实跑 99 / 展示 100」只需本文件一处转换，前端与数据文件都不用改。
PHYSICAL_DUTY_CAP = 99


def _physical_duty(duty: int) -> int:
    """档位配置值 → 实际下发给 UNO 的占空比（满载档降到 PHYSICAL_DUTY_CAP）。"""
    return PHYSICAL_DUTY_CAP if duty >= 100 else duty


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Runner:
    def __init__(self, config_path: str, run_id: str | None, claim_token: str | None, simulation: bool,
                 allow_overlay: bool = True) -> None:
        self.loaded = runtime.read_experiment_config(config_path, allow_overlay=allow_overlay)
        self.cfg = self.loaded.config
        self.simulation = simulation
        self.claim_token = claim_token
        self.run_id = run_id or (datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] + "_" + os.urandom(4).hex())
        self.directory = os.path.join(self.loaded.output_root, self.run_id)
        self.stop_file = os.path.join(self.directory, "stop.request")
        self.sequence = 0
        self.state = "starting"
        self.cycle = 0
        self.complete = 0
        self.captures = 0
        self.failed = False
        self.error_message = ""
        self.cleanup = "not_attempted"
        self.cancelled = False
        self.started = _now()
        self.fan: FanSession | None = None
        self.scope: ScopeDevice | None = None

    def emit(self, event_type: str, data) -> None:
        self.sequence += 1
        runtime.write_run_event(self.run_id, self.directory, self.sequence, event_type, self.state, data)

    def log_command(self, duty, command: str, ack: str, status: str) -> None:
        row = {
            "timestampUtc": _now(), "cycle": self.cycle, "dutyPercent": "" if duty is None else duty,
            "command": command, "ack": ack, "status": status,
        }
        path = os.path.join(self.directory, "commands.csv")
        is_new = not os.path.exists(path)
        with open(path, "a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["timestampUtc", "cycle", "dutyPercent", "command", "ack", "status"])
            if is_new:
                writer.writeheader()
            writer.writerow(row)
        self.emit("command_ack", {
            "cycle": self.cycle, "dutyPercent": duty, "command": command, "ack": ack,
            "meaning": "controller_report; physical RPM and stop not measured",
        })

    def stop_requested(self) -> bool:
        return os.path.exists(self.stop_file) or CancelSignal.requested()

    def run(self) -> int:
        cfg = self.cfg
        claim_path = os.path.join(self.directory, "run.claim")
        # 目录/认领分支顺序（2026-10-07 修）：
        # 原实现先做「目录必须不存在」检查，但 start.py 的异步路径**已先建目录并写 claim**，
        # 导致带 ClaimToken 的联合实验 100% 撞 "Run directory already exists." 而无法采集。
        # 修正为：先按是否带 token 分流——带 token 走「校验分支」（目录须已存在，只校验不重建）；
        # 不带 token（独立直跑）保留原语义（目录须不存在，自建目录/写 claim/存快照）。
        if self.claim_token:
            # 校验分支：start.py 已建目录 + 写 claim + 冻结快照，此处不重复创建
            if not os.path.isdir(self.directory):
                raise RuntimeError("Claimed run directory missing.")
            with open(claim_path, "r", encoding="utf-8") as fh:
                if fh.read() != self.claim_token:
                    raise RuntimeError("Run claim token mismatch.")
        else:
            # 独立直跑分支：保持原语义（目录必须不存在，防止误覆盖历史 run）
            if os.path.exists(self.directory):
                raise RuntimeError("Run directory already exists.")
            os.makedirs(self.directory, exist_ok=False)
            with open(claim_path, "w", encoding="utf-8") as fh:
                fh.write("")
            with open(os.path.join(self.directory, "config.snapshot.json"), "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, ensure_ascii=False, indent=2)
        # runner.started 标记
        open(os.path.join(self.directory, "runner.started"), "w").close()

        CancelSignal.install()
        fan_serial.install_wait_thread(self.stop_file)

        self.emit("run_started", {
            "simulation": bool(self.simulation), "processId": os.getpid(), "directory": self.directory,
            "requestedCycles": cfg["experiment"]["cycles"], "holdSeconds": cfg["experiment"]["holdSeconds"],
            "dutiesPercent": cfg["experiment"]["dutiesPercent"], "configPath": self.loaded.path,
            "capturesPerStep": cfg["experiment"].get("capturesPerStep", 5),
            "captureIntervalSeconds": cfg["experiment"].get("captureIntervalSeconds", 0.5),
        })

        try:
            if self.simulation:
                raise RuntimeError("Simulation mode is not supported in the Python rewrite.")
            # 打开串口 + 识别
            self.fan = FanSession(SerialWire(cfg["serial"]["port"], cfg["serial"]["baud"]))
            self.fan.identify(8000)
            self.emit("controller_identified", {
                "identity": cfg["serial"]["expectedIdentity"], "port": cfg["serial"]["port"],
                "openingPortResetsUno": True,
            })
            self.log_command(None, "STATUS", self.fan.command("STATUS", 2000), "board_report")

            if cfg["scope"]["enabled"]:
                self.scope = ScopeDevice(cfg["scope"]["resource"], cfg["scope"].get("expectedIdentity"))
                settings = scope_capture.initialize_scope(self.scope, cfg["scope"])
                with open(os.path.join(self.directory, "scope-settings.json"), "w", encoding="utf-8") as fh:
                    json.dump(settings, fh, ensure_ascii=False, indent=2)
                self.emit("scope_configured", settings)

            self.state = "running"
            exp = cfg["experiment"]
            while (exp["cycles"] == 0 or self.cycle < exp["cycles"]) and not self.stop_requested():
                self.cycle += 1
                cycle_done = True
                for d in exp["dutiesPercent"]:
                    if self.stop_requested():
                        cycle_done = False
                        break
                    duty = int(d)
                    # 档位语义用 duty（100），实际指令用 physical（99）——
                    # 见文件头 PHYSICAL_DUTY_CAP 的说明。log_command 记真实指令，
                    # 便于事后核对「配置档位 vs 实际下发」。
                    physical = _physical_duty(duty)
                    ack = self.fan.command(f"SET {physical}", 2000)
                    hold_start = time.monotonic()
                    self.log_command(duty, f"SET {physical}", ack, "acknowledged")
                    self.emit("step_started", {"cycle": self.cycle, "dutyPercent": duty,
                                               "targetHoldSeconds": exp["holdSeconds"]})
                    while (time.monotonic() - hold_start) < exp["settleSeconds"] and not self.stop_requested():
                        time.sleep(0.05)
                    if self.stop_requested():
                        cycle_done = False
                        break
                    # 每档连续采集多次（2026-10-09）：原实现每档只采 1 次 → 一轮仅 4 个
                    # 样本点，趋势图上点间连成斜线。改为在 hold 窗口内连续采
                    # capturesPerStep 次（默认 5），每次之间 sleep captureIntervalSeconds
                    # （默认 0.5s）。每次采集都 emit 一条 capture_completed（自带真实
                    # startedUtc/finishedUtc），后端据此逐点算真实 t_s → 曲线沿时间轴铺开。
                    #
                    # ⚠️ 2026-10-09 改：`save_fan_scope_capture` 现已把同一次物理采集的
                    # pwm + tach 两档**合并为一条**记录（长度 1 的列表），故 `results` 通常
                    # 只有 1 条，循环体本身**无需改动**即自动从「两条半量事件」变成
                    # 「一条四通道齐全事件」。`self.captures`（captureCount）随之由
                    # 「每档 2 条」变为「每档 1 条」。
                    #
                    # 窗口约束（关键）：holdSeconds 是该档物理驻留时长，不因多采而缩短或拉长
                    # 语义；**超出窗口即停止本档采集、如实少采**，绝不补假数据。采到的次数
                    # 记进 step_completed 的 captures（循环迭代数，不受合并影响），便于核对。
                    captures_done = 0
                    target = int(exp.get("capturesPerStep", 5))
                    interval = float(exp.get("captureIntervalSeconds", 0.5))
                    for i in range(target):
                        if self.stop_requested():
                            cycle_done = False
                            break
                        if self.scope is not None:
                            results = scope_capture.save_fan_scope_capture(
                                self.scope, cfg["scope"], self.directory, self.cycle, duty)
                            for capture in results:
                                self.captures += 1
                                self.emit("capture_completed", capture)
                            captures_done += 1
                        # 末次之后不必再等间隔；其余按 interval 间隔，且不越过 hold 窗口
                        if i < target - 1:
                            next_at = hold_start + exp["settleSeconds"] + (i + 1) * interval
                            while time.monotonic() < next_at and not self.stop_requested():
                                time.sleep(0.02)
                        # 窗口已满且还有剩余目标 → 如实少采（不补数），并记为 overrun 原因
                        if (time.monotonic() - hold_start) >= exp["holdSeconds"] and i < target - 1:
                            break
                    if not cycle_done:
                        break
                    elapsed = time.monotonic() - hold_start
                    if elapsed > exp["holdSeconds"]:
                        self.emit("timing_overrun", {"cycle": self.cycle, "dutyPercent": duty,
                                                     "elapsedSeconds": elapsed, "reason": "capture exceeded target dwell"})
                    while (time.monotonic() - hold_start) < exp["holdSeconds"] and not self.stop_requested():
                        time.sleep(0.05)
                    if self.stop_requested():
                        cycle_done = False
                        break
                    ack = self.fan.command("STATUS", 2000)
                    # ⚠️ 校验用 `physical`（实际下发值）而非 `duty`（档位语义值）：
                    #   满载档下发的是 99，板子如实回 "OK DUTY 99"；若拿 duty=100 去比，
                    #   会误判成 "Unexpected board status: OK DUTY 99" 让整轮 failed
                    #   （2026-10-12 实测踩到）。见 PHYSICAL_DUTY_CAP 的说明。
                    if ack != f"OK DUTY {physical}":
                        raise RuntimeError(f"Unexpected board status: {ack}")
                    self.log_command(duty, "STATUS", ack, "board_report")
                    self.emit("step_completed", {"cycle": self.cycle, "dutyPercent": duty,
                                                 "actualHoldSeconds": time.monotonic() - hold_start,
                                                 "captures": captures_done,
                                                 "targetCaptures": target})
                if cycle_done:
                    self.complete += 1
                    self.emit("cycle_completed", {"cycle": self.cycle, "completedCycles": self.complete})
            self.cancelled = self.stop_requested()
        except Exception as e:  # noqa: BLE001
            self.failed = True
            self.error_message = str(e)
            sys.stderr.write(self.error_message + "\n")
            try:
                self.emit("run_error", {"message": self.error_message})
            except Exception:  # noqa: BLE001
                sys.stderr.write("Could not persist run_error event.\n")
        finally:
            self._finish()
        return 1 if self.failed else 0

    def _finish(self) -> None:
        self.state = "stopping"
        # 安全收尾：识别过才发 SET 0（对齐原 finally）
        if self.fan is not None and self.fan.identified:
            try:
                ack = self.fan.command("SET 0", 2000)
                self.cleanup = "pwm_zero_acknowledged_physical_stop_unverified"
                try:
                    self.log_command(0, "SET 0", ack, self.cleanup)
                except Exception as e:  # noqa: BLE001
                    self.failed = True
                    sys.stderr.write(str(e) + "\n")
            except Exception as e:  # noqa: BLE001
                self.failed = True
                self.cleanup = "failed_physical_state_unknown"
                sys.stderr.write("SET 0 failed; disconnect fan 5V power: " + str(e) + "\n")
        else:
            self.cleanup = "no_identified_controller_no_zero_command"
            if self.fan is not None:
                self.failed = True

        if self.scope is not None:
            try:
                self.scope.dispose()
            except Exception as e:  # noqa: BLE001
                self.failed = True
                sys.stderr.write(str(e) + "\n")
        if self.fan is not None:
            try:
                self.fan.close()
            except Exception as e:  # noqa: BLE001
                self.failed = True
                sys.stderr.write(str(e) + "\n")
        CancelSignal.remove()

        if self.failed:
            state = "failed"
        elif self.cancelled:
            state = "stopped"
        else:
            state = "completed"
        summary = {
            "schemaVersion": "1.0", "runId": self.run_id, "state": state,
            "simulation": bool(self.simulation), "terminalPublished": False,
            "startedUtc": self.started, "endedUtc": _now(),
            "completedCycles": self.complete, "activeCycle": self.cycle, "captureCount": self.captures,
            "cancelled": self.cancelled, "failed": self.failed, "failureMessage": self.error_message,
            "cleanup": self.cleanup, "physicalStopVerified": False,
            "exitCode": 1 if self.failed else 0,
            "eventsPath": os.path.join(self.directory, "events.jsonl"),
            "commandsPath": os.path.join(self.directory, "commands.csv"),
        }
        try:
            self.emit("run_finished", summary)
        except Exception as e:  # noqa: BLE001
            self.failed = True
            sys.stderr.write("Could not persist terminal event: " + str(e) + "\n")
            summary["failed"] = True
            summary["state"] = "failed"
            summary["exitCode"] = 1
            summary["failureMessage"] = "Could not persist final event/results."
        # 一次性原子发布
        summary["terminalPublished"] = True
        summary_path = os.path.join(self.directory, "summary.json")
        tmp = summary_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, summary_path)


def main() -> int:
    ap = argparse.ArgumentParser(description="Fan experiment runner (Python rewrite)")
    ap.add_argument("-ConfigPath", "--config", default="")
    ap.add_argument("-RunId", "--run-id", default="")
    ap.add_argument("-ClaimToken", "--claim-token", default="")
    ap.add_argument("-Simulation", "--simulation", action="store_true")
    args = ap.parse_args()

    if not re.match(r"^[a-zA-Z0-9_-]{1,100}$", args.run_id) and args.run_id:
        sys.stderr.write("Invalid RunId.\n")
        return 1
    # 默认主配置：与后端 fan_executor.py 一致（hardware/v0.6/config/acceptance.json）。
    # 显式传 -ConfigPath（含 start.py 的冻结快照 / run_fan.py 的临时配置）不叠加 overlay。
    explicit = bool(args.config)
    config_path = args.config or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "v0.6", "config", "acceptance.json"
    )
    try:
        runner = Runner(config_path, args.run_id or None, args.claim_token or None, args.simulation,
                        allow_overlay=not explicit)
        return runner.run()
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(str(e) + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
