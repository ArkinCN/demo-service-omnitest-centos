"""风扇实验 HTTP 接口（阶段 5 接入 v0.6 硬件交接包）。

命名空间独立 `/fan-tests`，避免 `/runs/{run_id}/{artifact_kind}` 动态路由遮蔽。
契约对齐 `hardware/v0.6/docs/01_前端对接方案.md` 提案，字段 snake_case：

  POST /api/fan-tests                       校验计划、生成 run_id、启动一次
  GET  /api/fan-tests/{run_id}              计划 + 状态 + 实际时长 + 是否延期
  GET  /api/fan-tests/{run_id}/samples      返回 sequence>after_sequence 的增量点
  POST /api/fan-tests/{run_id}/stop         停止该运行
  GET  /api/fan-tests/{run_id}/captures/{cid} 短波形（本阶段占位 + 授权 URL）

数据纪律：真实数据只来自真仪器（RealFanExecutor 原样映射 events.jsonl）；
模拟数据（SimFanExecutor）每条响应都带 simulation:true，前端据此如实标注，
不得当实测上报。
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_current_user, get_db
from app.core.exceptions import ConflictException
from app.core.logger import logger
from app.db.session import get_demo_dataset, get_mode
from app.models.interlock import GateState
from app.models.run import Run
from app.models.user import User
from app.schemas.common import error_response, success_response
from app.services.demo_artifacts import persist_demo_artifacts
from app.services.demo_capture import write_demo_capture
from app.services.fan_executor import (
    DEFAULT_STEPS,
    FanRunState,
    get_executor,
    make_run_id,
    read_capture_waveforms,
)

router = APIRouter(prefix="/fan-tests", tags=["Fan Tests"])

# 执行器**不在模块加载时固定**。演示模式要求走模拟执行器，而模式是运行时可切换的，
# 启动时抓一个实例会把模式永久钉死在启动那一刻 —— 这正是「UI 显示演示中、
# 后台还在开串口」的成因。改为每次取用；get_executor() 内部已做单例缓存，
# 反复调用不会重复构造。

#: 演示运行固定的场景与归属。真实运行由计划/配置带场景；模拟运行没有计划上下文，
#: 用演示数据集里那一个，保证与 gen_demo_data.py 灌入的数据同源。
_DEMO_SCENE_ID = "motor.cooling-fan.fortior-fu6832"
_DEMO_USER_ID = 1


def _persist_demo_run(session: Session, st: FanRunState) -> None:
    """演示模式下把「已完成的模拟运行」落库，供历史列表与报告使用。

    为什么放在 API 层而不是 Executor 里：
      真实执行器的产物是 runs/<run_id>/events.jsonl，由采集脚本写盘；
      模拟执行器没有文件产物。不在应用侧补这一步，结果就是
      「图在动、刷新就没了、报告拿不到数据」——演示等于白演。

    为什么必须幂等：
      前端按秒轮询状态，同一个 run 会被反复观察到 terminal。
      没有幂等就会写出一堆重复记录。
    """
    if get_mode() != "demo" or not st.terminal:
        return

    existing = session.exec(select(Run).where(Run.run_id == st.run_id)).first()
    if existing is not None:
        return

    now = datetime.now(timezone.utc)
    dataset = get_demo_dataset() or "normal"
    session.add(
        Run(
            run_id=st.run_id,
            user_id=_DEMO_USER_ID,
            scene_id=_DEMO_SCENE_ID,
            status=st.status,
            # 与演示数据集同前缀：get_demo_dataset() 就是靠这个认出当前是哪套
            mode=f"demo-{dataset}",
            created_at=now,
            finished_at=now,
        )
    )

    # 产物和 Run 一起提交（persist_demo_artifacts 内部不 commit）。
    # 模拟执行器没有 events.jsonl 之类的文件产物，这里必须补齐，
    # 否则报告模块拿不到 verdict-table / report-instance，生成即失败。
    samples, _ = get_executor().samples(st.run_id, 0)
    stamp = now.isoformat()
    persist_demo_artifacts(
        session=session,
        run_id=st.run_id,
        scene_id=_DEMO_SCENE_ID,
        samples=samples,
        started_at=stamp,
        finished_at=stamp,
    )
    session.commit()

    # 采集目录：报告的波形图/趋势图从这里取数。模拟执行器不产文件，
    # 由 demo_capture 按真实目录结构落一份合成波形（带 .demo-marker 标记）。
    # 失败不抛异常 —— 少一张图不该让整轮演示失败。
    write_demo_capture(st.run_id, st.steps or [], dataset)

    logger.info("[fan-tests] 演示运行 %s 已落库（mode=demo-%s，%d 个采样点）",
                st.run_id, dataset, len(samples))


class GateSnapshot(BaseModel):
    """前端逐条确认闸门后上报的快照（与 interlocks 的三件事对齐）。"""

    interlocks_ok: bool = False
    precheck_ok: bool = False
    master_switch_on: bool = False


class FanTestStart(BaseModel):
    """启动请求体。steps 缺省用 DEFAULT_STEPS（30/50/70/100% 各 20s，一轮 80s）。"""

    mode: str = "finite"
    cycles: int = 1
    steps: list[dict] = DEFAULT_STEPS
    default_duration_s: float = 60
    # 安全闸门快照：前端已逐条确认闸门时随请求上报，后端据此放行；
    # 未提供时回退查 DB GateState（保守拒绝）。
    gate: GateSnapshot | None = None


def _plan_dict(st: FanRunState) -> dict:
    """组装计划响应，字段对齐 01_plan.json。"""
    return {
        "schema_version": "fan-trend/1.0",
        "simulation": st.simulation,
        "run_id": st.run_id,
        "mode": st.mode,
        "planned_duration_s": st.planned_duration_s,
        "default_duration_s": st.default_duration_s,
        "cycles": st.cycles,
        "steps": st.steps,
        "status": st.status,
    }


def _status_dict(st: FanRunState) -> dict:
    """组装状态详情，含实际时长、延期标记与权威终态标记。"""
    elapsed = 0.0
    if st.started_at is not None:
        end = st.finished_at or time.monotonic()
        elapsed = round(end - st.started_at, 2)
    return {
        **_plan_dict(st),
        "actual_duration_s": elapsed,
        "overrun": st.overrun or (st.planned_duration_s > 0 and elapsed > st.planned_duration_s),
        "terminal": st.terminal,
        "error": st.error,
    }


def _gate_ok(session: Session, snapshot: GateSnapshot | None) -> tuple[bool, list[str]]:
    """硬闸门：联锁三件事全满足才允许启动。返回 (是否放行, 缺失项说明)。

    优先用前端上报的闸门快照（前端已逐条确认闸门 → 三项布尔）；
    未提供快照时回退查 DB 最近一条 GateState，仍保守拒绝（不存在即未过）。
    无论走哪条路，三项全 true 才放行——上报不降低门槛，只是打通数据源。
    """
    if snapshot is not None:
        missing: list[str] = []
        if not snapshot.interlocks_ok:
            missing.append("联锁项未全部满足")
        if not snapshot.precheck_ok:
            missing.append("预检未全部通过")
        if not snapshot.master_switch_on:
            missing.append("现场安全总闸未开")
        ok = len(missing) == 0
        if ok:
            logger.info("[fan-tests] 闸门通过（前端上报快照：interlocks/precheck/master 三项全真）")
        return ok, missing

    gate = session.exec(
        select(GateState).order_by(GateState.updated_at.desc()).limit(1)
    ).first()
    if gate is None:
        return False, ["安全闸门尚未登记：请先在流程 3 完成联锁确认，或由前端随启动请求上报闸门快照"]
    missing = []
    if not gate.interlocks_ok:
        missing.append("联锁项未全部满足")
    if not gate.precheck_ok:
        missing.append("预检未全部通过")
    if not gate.master_switch_on:
        missing.append("现场安全总闸未开")
    return (len(missing) == 0), missing


@router.post("")
async def start_fan_test(
    payload: FanTestStart,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """校验计划 → 过安全闸门 → 生成 run_id → 启动一次运行。

    两道闸：前端确认卡（防误触）+ 后端硬闸门（联锁三件事），缺一不可。
    """
    # 1. 计划校验（422：输入语义错误）
    if not payload.steps:
        return error_response("计划 steps 不能为空", 422)
    for s in payload.steps:
        if "commanded_pwm_pct" not in s or "duration_s" not in s:
            return error_response("每个 step 须含 commanded_pwm_pct 与 duration_s", 422)
        pwm = s.get("commanded_pwm_pct")
        if not isinstance(pwm, int) or not 0 <= pwm <= 100:
            return error_response("commanded_pwm_pct 须为 0~100 整数", 422)

    # 2. 硬闸门（409：闸门未过，附缺失项）。优先用前端上报快照，缺失回退 DB。
    ok, missing = _gate_ok(session, payload.gate)
    if not ok:
        return error_response("安全闸门未通过，拒绝启动", 409, data={"missing": missing})

    # 3. 单设备锁（409：已有运行）
    run_id = make_run_id()
    # 计划体传给执行器时排除 gate（那是闸门凭据，不属计划）
    plan = payload.model_dump(exclude={"gate"})
    try:
        st = get_executor().start(run_id, plan)
    except ConflictException as e:
        return error_response(str(e), 409)

    logger.info("[fan-tests] run %s started by user %s (simulation=%s)", run_id, current_user.id, st.simulation)
    return success_response(data=_status_dict(st), message="运行已启动")


@router.get("/{run_id}")
async def get_fan_test(
    run_id: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """查询一次运行的计划与状态。

    演示模式下这一步顺带把已完成的模拟运行落库（幂等），详见 _persist_demo_run。
    """
    st = get_executor().status(run_id)
    if st.status == "unknown":
        return error_response("运行不存在", 404)
    _persist_demo_run(session, st)
    return success_response(data=_status_dict(st))


@router.get("/{run_id}/samples")
async def get_samples(
    run_id: str,
    after_sequence: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
):
    """返回 sequence > after_sequence 的增量点，及新的游标。字段对齐 02_samples.json。"""
    st = get_executor().status(run_id)
    if st.status == "unknown":
        return error_response("运行不存在", 404)
    samples, next_seq = get_executor().samples(run_id, after_sequence)
    time_source = (
        "executor_monotonic_measurement_midpoint"
        if st.simulation
        else "capture_utc_derived"
    )
    return success_response(data={
        "simulation": st.simulation,
        "run_id": run_id,
        "time_source": time_source,
        "samples": samples,
        "next_after_sequence": next_seq,
    })


@router.post("/{run_id}/stop")
async def stop_fan_test(
    run_id: str,
    current_user: User = Depends(get_current_user),
):
    """请求停止一次运行（写 stop.request，不强制杀进程）。"""
    st = get_executor().status(run_id)
    if st.status == "unknown":
        return error_response("运行不存在", 404)
    get_executor().stop(run_id)
    logger.info("[fan-tests] run %s stop requested by user %s", run_id, current_user.id)
    return success_response(data={"run_id": run_id, "status": "stopping"}, message="停止请求已提交")


@router.get("/{run_id}/captures/{capture_id}")
async def get_capture(
    run_id: str,
    capture_id: str,
    current_user: User = Depends(get_current_user),
):
    """返回一次采集的**真实时序波形**（各通道电压–时间数组），供前端波形图绘制。

    数据来源：`capture_completed` 事件的 `artifacts`（示波器落盘的 CH{n}.csv 绝对路径），
    由执行器 `capture_meta` 从内存索引查出后**按需读文件**（单文件约 1200 行）。

    数据纪律（不可逾越）：
      - 未知 capture_id → 404；
      - 有索引但文件不可读 → `available=false` + 逐通道 reason，**绝不补零/伪造数组**；
      - 未接通道（如 tach 关闭）不出现在 channels 里，符合 `not_applicable` 语义。
    """
    st = get_executor().status(run_id)
    if st.status == "unknown":
        return error_response("运行不存在", 404)

    meta = get_executor().capture_meta(run_id, capture_id)
    if meta is None:
        return error_response(
            "未找到该采集（capture_id 不属于本轮，或该采集尚未落盘）", 404
        )

    waves = read_capture_waveforms(meta)
    return success_response(data={
        "run_id": run_id,
        "capture_id": capture_id,
        "cycle": meta.get("cycle"),
        "profile": meta.get("profile"),
        "commanded_pwm_pct": meta.get("commanded_pwm_pct"),
        "started_utc": meta.get("startedUtc"),
        "finished_utc": meta.get("finishedUtc"),
        "available": waves["available"],
        "channels": waves["channels"],
        "notes": waves["notes"],
    })
