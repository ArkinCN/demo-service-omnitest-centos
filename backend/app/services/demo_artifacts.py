"""演示运行的产物构造。

【为什么单独一个模块】
  产物结构（config-snapshot / verdict-table / run-artifact / report-instance）
  是业务契约，散在 API 层会和接口逻辑混在一起。集中在这里，
  既能被 fan_tests 复用，也能被离线脚本（gen_demo_data.py）参照。

【为什么判定项写成常量表】
  TR-BENCH-01 … TR-TIME-01 这 30 项是验收要求本身，不是可调参数。
  它们是业务的固定契约（与真实数据里的 req_id 完全一致），
  放常量比放配置更合适 —— 配置化会让人误以为可以随便改。

【为什么演示数据全 pass】
  演示的用途是展示「系统跑通是什么样」，不是展示故障。
  需要故障场景时用 fault 数据集（gen_demo_data.py 灌的），
  两者职责分开：跑的这套是"顺利路径"，预置那套是"异常路径"。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session

from app.core.logger import logger
from app.models.run import Artifact

#: 30 个判定项，顺序即报告展示顺序。与真实库 verdict-table 的 req_id 一一对应。
REQ_TABLE: list[tuple[str, str]] = [
    ("TR-BENCH-01", "PWM 占空比输出精度"),
    ("TR-BENCH-02", "PWM 载波频率符合性"),
    ("TR-BENCH-03", "供电电压稳定范围"),
    ("TR-BENCH-04", "波形采集有效性"),
    ("TR-BENCH-05", "输出占空比上限配置覆盖运行档位"),
    ("TR-BENCH-06", "转速采集有效性"),
    ("TR-BENCH-07", "稳态转速范围"),
    ("TR-BENCH-08", "转速随占空比递增"),
    ("TR-CURR-01", "启动母线峰值电流"),
    ("TR-HW-01", "母线电压检测自检（Vbus ±10%）"),
    ("TR-HW-02", "三相输出自检（IPM 相位 ±5°）"),
    ("TR-ONOFF-01", "三档电压 ON/OFF 次数回归"),
    ("TR-PROT-01", "过压保护验证"),
    ("TR-PROT-02", "欠压保护验证"),
    ("TR-PROT-03", "低压告警 LVW 验证"),
    ("TR-PROT-04", "堵转保护验证"),
    ("TR-PROT-05", "超速保护验证"),
    ("TR-PROT-06", "启动失败保护验证"),
    ("TR-PROT-07", "过流保护验证（硬过流 / 软过流）"),
    ("TR-PWM-01", "PWM 调速曲线全档位验证"),
    ("TR-PWM-02", "PWM 100% → 最低运行 Duty 不停转"),
    ("TR-PWM-03", "每 10% PWM 阶跃响应时间"),
    ("TR-RUN-01", "最大工作电压下最低转速长跑 5 分钟"),
    ("TR-SPEED-01", "FG1 / FG2 转速一致性"),
    ("TR-SPEED-02", "稳态转速偏差"),
    ("TR-SPEED-03", "稳态转速稳定性（无振荡）"),
    ("TR-SPEED-04", "FG 与实际转速误差"),
    ("TR-START-01", "起动成功率（100 次启停回归）"),
    ("TR-START-02", "自动启动盲试（probe 3 次 + full 100 次）"),
    ("TR-TIME-01", "启动到全速稳定时间"),
]

#: 产物类型 → schema_version。必须与真实数据同格式（`kind/v1`），
#: 前端按这个字段判别结构版本，写成裸 `v1` 会认不出。
SCHEMA_VERSION = {
    "config-snapshot": "config-snapshot/v1",
    "verdict-table": "verdict-table/v1",
    "run-artifact": "run-artifact/v1",
    "report-instance": "report-instance/v1",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_config_snapshot(scene_id: str) -> dict[str, Any]:
    """配置快照。结构对齐真实数据，字段值取演示场景的固定内容。"""
    return {
        "schema": "config-snapshot/v1",
        "scene_id": scene_id,
        "locked": True,
        "locked_at": _now_iso(),
        "locked_by": "演示账号",
        "firmware": {"project_path": "", "param_header_path": ""},
        "_counts": {"header": 10, "control": 70, "attributes": 29},
        "_incomplete": ["firmware.project_path", "firmware.param_header_path"],
        "note": "演示运行自动生成的配置快照",
    }


def build_verdict_table(judged_at: str) -> dict[str, Any]:
    """判定表：30 项全部 pass。

    not_applicable 会让报告出现「未判定」，演示场景下不合适 ——
    需要「部分不适用」的效果请用预置的 fault / stress 数据集。
    """
    verdicts = [
        {"name": name, "req_id": req_id, "state": "pass", "used": [], "missing": []}
        for req_id, name in REQ_TABLE
    ]
    return {"verdicts": verdicts, "judged_at": judged_at, "authoritative": True}


def build_run_artifact(measures: dict[str, Any], started_at: str, finished_at: str) -> dict[str, Any]:
    """实测指标。数值由模拟执行器产出，全部标 simulation。"""
    return {
        "note": "演示运行：模拟执行器按秒产出的合成实测值，非真实仪器采集",
        "simulation": True,
        "started_at": started_at,
        "finished_at": finished_at,
        "measures": measures,
    }


def build_report_instance(scene_id: str) -> dict[str, Any]:
    """报告实例。演示运行直接给到 confirmed，报告可立即生成。"""
    now = _now_iso()
    return {
        "schema": "report-instance/v1",
        "status": "confirmed",
        "note": "演示运行自动生成，全部判定项通过",
        "scene_id": scene_id,
        "confirmed_at": now,
        "confirmed_by": "演示账号",
        "watermark": "演示数据",
    }


def summarize_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """把逐点采样汇总成 measures。

    只统计真实存在的字段：模拟执行器里电流/转速可能是 null（表示「未采集」），
    这里不补零 —— 补零会让报告把「没测」显示成「测到 0」。
    """
    duty = [s["measured_pwm_duty_pct"] for s in samples if s.get("measured_pwm_duty_pct") is not None]
    volt = [s["voltage_v"] for s in samples if s.get("voltage_v") is not None]
    rpm = [s["rpm"] for s in samples if s.get("rpm") is not None]

    measures: dict[str, Any] = {
        "sample_count": len(samples),
        "pass_count": len(REQ_TABLE),
    }
    if duty:
        measures["bench_pwm_duty_mean_pct"] = round(sum(duty) / len(duty), 4)
    if volt:
        measures["bench_voltage_mean_v"] = round(sum(volt) / len(volt), 4)
    if rpm:
        measures["steady_rpm_min"] = min(rpm)
        measures["steady_rpm_max"] = max(rpm)
    return measures


def persist_demo_artifacts(
    session: Session,
    run_id: str,
    scene_id: str,
    samples: list[dict[str, Any]],
    started_at: str,
    finished_at: str,
) -> int:
    """为演示运行写入 4 类产物。返回写入条数。

    **不在这里 commit**：调用方通常还要写 Run 本身，两者必须在同一事务里提交，
    否则会出现「run 写成功、产物写失败」的半成品 —— 而 run 存在会让下次轮询
    直接跳过重试，产物就永远补不上了。
    """
    judged_at = _now_iso()
    measures = summarize_samples(samples)

    payloads = {
        "config-snapshot": build_config_snapshot(scene_id),
        "verdict-table": build_verdict_table(judged_at),
        "run-artifact": build_run_artifact(measures, started_at, finished_at),
        "report-instance": build_report_instance(scene_id),
    }

    now = datetime.now(timezone.utc)
    for kind, content in payloads.items():
        session.add(
            Artifact(
                run_id=run_id,
                artifact_kind=kind,
                schema_version=SCHEMA_VERSION[kind],
                content=content,
                created_at=now,
                updated_at=now,
            )
        )
    logger.info("[demo] 运行 %s 写入 %d 类产物（待提交）", run_id, len(payloads))
    return len(payloads)
