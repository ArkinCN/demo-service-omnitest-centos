"""演示运行的采集目录生成。

【为什么需要】
  报告的趋势图 / 波形图读的是 `hardware/v0.6/runs/<run_id>/` 下的
  events.jsonl 与 `cycle*/pwm/CH*.csv`。模拟执行器只产内存样本、不写文件，
  于是演示报告的图表区全是「（无）」。这个模块把样本落成与真实采集**同构**的
  目录，让报告能正常出图 —— 走的是同一条链路，不是给报告开后门。

【为什么必须打标记】
  这些目录混在真实采集目录里，必须能一眼区分、且清理时绝不误删真数据。
  每个演示目录写一个 `.demo-marker`，里面记录生成时间与数据集。

【数据纪律】
  目录里的事件与波形都是合成值，但**不冒充真实采集**：
  events.jsonl 的 `data.simulation` 固定为 true，任何后续排查都能识别来源。
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.logger import logger
from app.core.paths import C_DIR

#: 演示目录标记文件。清理逻辑只认它，绝不碰真实采集目录。
MARKER = ".demo-marker"

#: 与真实采集同参数：每通道 1200 点、步长 0.2µs、起点 -120µs。
SAMPLE_COUNT = 1200
DT_S = 2e-7
T_START = -0.00012
#: PWM 方波周期（点数）。20 点在高采样率下足够密，图表看起来像连续方波。
PWM_PERIOD = 20

#: 保留的演示目录数量。演示只用最近几轮，多余的清掉，避免污染 runs/ 目录。
KEEP_DEMO_DIRS = 5


def _runs_root() -> Path:
    return C_DIR / "hardware" / "v0.6" / "runs"


def _waveform(duty_pct: int, phase: int = 0) -> list[float]:
    """按占空比生成 PWM 方波：高 5V / 低 0V。"""
    high = max(1, round(PWM_PERIOD * duty_pct / 100))
    return [5.0 if ((i + phase) % PWM_PERIOD) < high else 0.0 for i in range(SAMPLE_COUNT)]


def _write_channel(path: Path, values: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("sample,time_s,voltage_V,current_A\n")
        for idx, volt in enumerate(values):
            # current_A 留空：模拟执行器不产电流，报告会如实显示「未采集」
            fh.write(f"{idx},{T_START + idx * DT_S},{volt},\n")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _write_events(path: Path, run_id: str, steps: list[dict[str, Any]], started: datetime) -> None:
    """写出 events.jsonl：run_started → 每档一条 capture_completed → run_finished。

    只在 `type` 与 `data.simulation` 上求稳：报告用 `"capture_completed"`
    这段字符串做「是否有真实采集」的判据，其余字段是给图表取档位用的。
    """
    lines: list[str] = []
    seq = 1

    def emit(kind: str, state: str, data: dict[str, Any], ts: datetime) -> None:
        nonlocal seq
        lines.append(json.dumps({
            "schemaVersion": "1.0",
            "runId": run_id,
            "sequence": seq,
            "timestampUtc": _iso(ts),
            "type": kind,
            "state": state,
            "data": data,
        }, ensure_ascii=False))
        seq += 1

    emit("run_started", "starting", {
        "simulation": True,
        "processId": 0,
        "directory": str(path.parent),
        "requestedCycles": 1,
        "dutiesPercent": [int(s.get("commanded_pwm_pct", 0)) for s in steps],
    }, started)

    for idx, step in enumerate(steps, 1):
        duty = int(step.get("commanded_pwm_pct", 0))
        duration = float(step.get("duration_s", 0))
        begin = started
        end = started
        emit("capture_completed", "running", {
            "schemaVersion": "1.0",
            "simulation": True,
            "startedUtc": _iso(begin),
            "finishedUtc": _iso(end),
            "cycle": 1,
            "commandedPwmPercent": duty,
            "profile": "pwm+tach",
            "source": "demo: 模拟执行器合成波形，非真实仪器采集",
            "timebaseSecondsPerDiv": 2e-05,
            "durationSeconds": duration,
        }, end)

    emit("run_finished", "completed", {"simulation": True, "ok": True}, started)

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cleanup_old_demo_dirs(keep: int = KEEP_DEMO_DIRS) -> None:
    """清理旧的演示目录，只保留最近 keep 个。

    只删带 MARKER 的目录 —— 真实采集目录没有这个文件，不会被误伤。
    """
    root = _runs_root()
    if not root.is_dir():
        return
    demo_dirs = [d for d in root.iterdir() if d.is_dir() and (d / MARKER).exists()]
    demo_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in demo_dirs[keep:]:
        shutil.rmtree(stale, ignore_errors=True)
        logger.info("[demo-capture] 清理旧演示目录 %s", stale.name)


def write_demo_capture(run_id: str, steps: list[dict[str, Any]], dataset: str) -> Path | None:
    """为一个演示 run 生成采集目录。

    失败不抛异常：图表画不出来是「少一张图」，不该让整轮演示因此失败。
    """
    try:
        root = _runs_root()
        run_dir = root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        (run_dir / MARKER).write_text(
            json.dumps({"demo": True, "dataset": dataset, "generatedAt": _iso(now)},
                       ensure_ascii=False),
            encoding="utf-8",
        )

        _write_events(run_dir / "events.jsonl", run_id, steps, now)

        for idx, step in enumerate(steps, 1):
            duty = int(step.get("commanded_pwm_pct", 0))
            cycle_dir = run_dir / f"cycle{idx:04d}_duty{duty:03d}"
            # 三相相位差 120°，与真实三相 PWM 的观感一致
            for ch, phase in ((1, 0), (2, PWM_PERIOD // 3), (3, PWM_PERIOD * 2 // 3)):
                _write_channel(cycle_dir / "pwm" / f"CH{ch}.csv", _waveform(duty, phase))
            # CH4 是转速脉冲：占空比 50% 的低频方波
            _write_channel(cycle_dir / "tach" / "CH4.csv", _waveform(50))

        cleanup_old_demo_dirs()
        logger.info("[demo-capture] 生成演示采集目录 %s（%d 档）", run_id, len(steps))
        return run_dir
    except Exception as exc:  # noqa: BLE001 - 图表缺失不该中断演示
        logger.warning("[demo-capture] 生成采集目录失败（报告图表将显示为空）：%s", exc)
        return None
