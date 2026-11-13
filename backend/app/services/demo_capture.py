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
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.logger import logger
from app.core.paths import C_DIR

#: 演示目录标记文件。清理逻辑只认它，绝不碰真实采集目录。
MARKER = ".demo-marker"

#: 与真实采集同参数：每通道 1200 点。
SAMPLE_COUNT = 1200
#: 每点 0.4µs → 整窗 480µs，恰好容纳 12 个 25kHz 周期（原来 0.2µs/20点 = 250kHz，与样本里
#: 的 pwm_frequency_hz=24950 差 10 倍，图形与标称对不上）。
DT_S = 4e-7
T_START = -0.00024
#: PWM 周期点数：25kHz × 0.4µs → 40µs = 100 点。
PWM_PERIOD = 100

# ---------------------------------------------------------------------------
# 各通道物理模型参数
#
# 为什么按通道分别建模：这四条通道测的是完全不同的物理量，
# 全用方波就是「一眼假」的根源（原实现正是如此）。下面的取值刻意与
# 样本里的量级对齐（voltage_v≈4.95、current_probe_v≈0.003、pwm≈25kHz）。
# ---------------------------------------------------------------------------

#: 母线电压基线（对齐 samples 里的 voltage_v）。
VOLTAGE_BASE_V = 4.95
#: 与 PWM 同频的三角纹波半幅。
VOLTAGE_RIPPLE_V = 0.016
#: 工频干扰幅度。
VOLTAGE_MAINS_V = 0.003
#: 母线电压白噪声标准差。
VOLTAGE_NOISE_V = 0.0009
#: 工频频率。
MAINS_FREQ_HZ = 50.0

#: 电流探头基线电压（对齐 samples 里的 current_probe_v）。
PROBE_BASE_V = 0.003
#: 开关沿 di/dt 尖峰幅度。
PROBE_SPIKE_V = 0.055
#: 寄生振荡（振铃）频率与衰减时间常数。
RING_FREQ_HZ = 500000.0
RING_TAU_S = 2e-6
#: 探头白噪声标准差。
PROBE_NOISE_V = 0.00012

#: 驱动逻辑高电平。
PWM_HIGH_V = 3.3
#: 上升/下降沿占用的采样点数（真实驱动有上升时间，不是理想阶跃）。
PWM_EDGE_POINTS = 2

#: 转速脉冲：标称周期点数、占空比、周期抖动比例。
TACH_PERIOD_POINTS = 120.0
TACH_DUTY = 0.5
TACH_JITTER = 0.015
TACH_HIGH_V = 3.3

#: 保留的演示目录数量。演示只用最近几轮，多余的清掉，避免污染 runs/ 目录。
KEEP_DEMO_DIRS = 5


def _runs_root() -> Path:
    return C_DIR / "hardware" / "v0.6" / "runs"


def _noise(seed: int, idx: int, sigma: float) -> float:
    """确定性伪随机噪声，返回 [-sigma, +sigma]。

    为什么不用 random：既要「看起来随机」，又要同一轮同一档位每次生成**完全一致**。
    否则每次刷新图都变，排查时会误以为数据在漂。用整数哈希后线性映射即可。
    """
    x = (seed * 1103515245 + idx * 12345) & 0x7FFFFFFF
    x ^= (x >> 13)
    x = (x * 1274126177) & 0x7FFFFFFF
    return ((x / 0x7FFFFFFF) * 2.0 - 1.0) * sigma


def _waveform(channel: int, duty_pct: int, seed: int = 0) -> list[float]:
    """按通道物理意义生成合成波形（返回值写入 voltage_V 列）。

    四条通道测的物理量不同，统一用方波就是「一眼假」的根源。这里分别建模：

      CH1 电流探头 → 开关沿 di/dt 尖峰 + 寄生参数引起的指数衰减振铃
      CH2 母线电压 → 三角纹波叠加的直流，再叠工频与白噪声
      CH3 驱动信号 → 方波 + 有限上升/下降沿
      CH4 转速脉冲 → 低频方波 + 码盘周期抖动（±TACH_JITTER）

    注意：`current_A` 列仍留空（换算未确认，见 _write_channel），
    这里生成的是**探针电压**，与真实链路的字段语义一致。
    """
    duty = max(0, min(int(duty_pct), 100)) / 100.0
    period_s = PWM_PERIOD * DT_S
    values: list[float] = []

    for i in range(SAMPLE_COUNT):
        t = i * DT_S
        phase = (t % period_s) / period_s

        if channel == 1:
            # 探头基线 + 白噪声，再在每个开关沿叠加尖峰与衰减振铃
            value = PROBE_BASE_V + _noise(seed, i, PROBE_NOISE_V)
            for edge_phase in (0.0, duty):
                dt = (phase - edge_phase) * period_s
                if 0.0 <= dt < 8 * RING_TAU_S:
                    ring = math.exp(-dt / RING_TAU_S) * math.sin(2 * math.pi * RING_FREQ_HZ * dt)
                    value += PROBE_SPIKE_V * ring
        elif channel == 2:
            # 三角纹波（与 PWM 同频）+ 工频 + 白噪声；占空比 0 时无纹波
            tri = 1.0 - 4.0 * abs(phase - 0.5)
            mains = math.sin(2 * math.pi * MAINS_FREQ_HZ * t) * VOLTAGE_MAINS_V
            ripple = tri * VOLTAGE_RIPPLE_V if duty > 0 else 0.0
            value = VOLTAGE_BASE_V + ripple + mains + _noise(seed, i, VOLTAGE_NOISE_V)
        elif channel == 3:
            # 方波 + 有限边沿（线性过渡），而不是理想阶跃
            edge_w = PWM_EDGE_POINTS * DT_S / period_s
            value = PWM_HIGH_V if phase < duty else 0.0
            for edge_phase, rising in ((0.0, True), (duty, False)):
                d = phase - edge_phase
                if 0.0 <= d < edge_w:
                    frac = d / edge_w
                    value = PWM_HIGH_V * (frac if rising else 1.0 - frac)
                    break
        else:
            # 转速脉冲：标称周期 + 逐周期抖动，模拟码盘不均匀
            jitter = _noise(seed, i // max(int(TACH_PERIOD_POINTS), 1), TACH_JITTER)
            local_period = TACH_PERIOD_POINTS * (1.0 + jitter)
            local = (i % local_period) / local_period if local_period > 0 else 0.0
            value = TACH_HIGH_V if local < TACH_DUTY else 0.0
            # 低电平上叠噪声，但不能为负 —— 码盘输出不会低于 0V
            value = max(0.0, value + _noise(seed, i, 0.006))

        values.append(round(value, 5))
    return values


def _seed_for(run_id: str, duty_pct: int) -> int:
    """由 run_id + 占空比派生稳定的噪声种子（同一轮同一档位波形可复现）。"""
    return (abs(hash(run_id)) ^ (int(duty_pct) * 7919)) & 0x7FFFFFFF


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


def write_demo_capture(run_id: str, steps: list[dict[str, Any]], dataset: str, *,
                       events: bool = True) -> Path | None:
    """为一个演示 run 生成采集目录。

    失败不抛异常：图表画不出来是「少一张图」，不该让整轮演示因此失败。

    ``events=False`` 只落波形与标记、**不写 events.jsonl**。
    用途是「运行中提前出图」：events.jsonl 里带 run_finished，
    运行中就写它会让磁盘态把本轮判成已收尾，与"仍在跑"自相矛盾。
    收尾时按默认值再调一次，把事件补全即可（波形覆盖写，幂等）。
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

        if events:
            _write_events(run_dir / "events.jsonl", run_id, steps, now)

        for idx, step in enumerate(steps, 1):
            duty = int(step.get("commanded_pwm_pct", 0))
            cycle_dir = run_dir / f"cycle{idx:04d}_duty{duty:03d}"
            seed = _seed_for(run_id, duty)
            # CH1 电流探头 / CH2 母线电压 / CH3 驱动信号，各按自身物理模型生成
            for ch in (1, 2, 3):
                _write_channel(cycle_dir / "pwm" / f"CH{ch}.csv", _waveform(ch, duty, seed))
            # CH4 转速脉冲
            _write_channel(cycle_dir / "tach" / "CH4.csv", _waveform(4, duty, seed))

        cleanup_old_demo_dirs()
        logger.info("[demo-capture] 生成演示采集目录 %s（%d 档）", run_id, len(steps))
        return run_dir
    except Exception as exc:  # noqa: BLE001 - 图表缺失不该中断演示
        logger.warning("[demo-capture] 生成采集目录失败（报告图表将显示为空）：%s", exc)
        return None
