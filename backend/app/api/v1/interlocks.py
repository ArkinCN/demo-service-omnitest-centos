"""
安全联锁 + 闸门 + 急停路由（阶段 4.3 引入）。

端点：
  POST /api/interlocks                      登记/导入联锁项
  GET  /api/interlocks?scene_id=            列联锁项
  PATCH /api/interlocks/{id}/confirm        人工确认一条联锁（留确认人）
  GET  /api/gates/{run_id}                  查闸门状态（三件事）
  POST /api/gates/{run_id}/check            校验闸门能否点启动
  POST /api/estop                           急停（先发停机指令，再存状态快照）

核心：联锁是独立数据结构，不与普通参数混。阶段 4 为模拟，急停只记录不真发停机；
阶段 5 接设备桥后在此处补真实停机指令。
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.api.deps import get_current_user, get_db
from app.core.exceptions import ConflictException, NotFoundException
from app.models.interlock import EstopRecord, GateState, Interlock
from app.models.user import User
from app.schemas.common import success_response

router = APIRouter(prefix="/api", tags=["Interlocks"])


@router.post("/interlocks")
async def create_interlock(
    interlock_id: str,
    name: str,
    category: str,
    scene_id: str = "",
    check_method: str = "系统校验",
    threshold: float | None = None,
    unit: str = "",
    trigger_action: str = "停机",
    waivable: bool = False,
    waiver_approver: str = "",
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """登记一条联锁项。"""
    interlock = Interlock(
        interlock_id=interlock_id,
        name=name,
        category=category,
        scene_id=scene_id,
        check_method=check_method,
        threshold=threshold,
        unit=unit,
        trigger_action=trigger_action,
        waivable=waivable,
        waiver_approver=waiver_approver,
    )
    session.add(interlock)
    session.commit()
    session.refresh(interlock)
    return success_response(data=interlock.model_dump(mode="json"), message="联锁已登记")


@router.get("/interlocks")
async def list_interlocks(
    scene_id: str | None = Query(default=None),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列联锁项。"""
    q = select(Interlock)
    if scene_id:
        q = q.where(Interlock.scene_id == scene_id)
    rows = session.exec(q).all()
    return success_response(data=[r.model_dump(mode="json") for r in rows])


@router.patch("/interlocks/{interlock_id}/confirm")
async def confirm_interlock(
    interlock_id: str,
    confirmed_by: str,
    satisfied: bool = True,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """人工确认一条联锁（留确认人）。"""
    interlock = session.exec(
        select(Interlock).where(Interlock.interlock_id == interlock_id)
    ).first()
    if interlock is None:
        raise NotFoundException("联锁项不存在")
    interlock.satisfied = satisfied
    interlock.confirmed_by = confirmed_by
    interlock.updated_at = datetime.now(timezone.utc)
    session.add(interlock)
    session.commit()
    session.refresh(interlock)
    return success_response(data=interlock.model_dump(mode="json"), message="联锁已确认")


def _gate_dict(g: GateState) -> dict:
    d = g.model_dump(mode="json")
    # 闸门能否点启动：三件事同时成立
    d["can_start"] = g.interlocks_ok and g.precheck_ok and g.master_switch_on
    d["missing"] = []
    if not g.interlocks_ok:
        d["missing"].append("联锁项未全部满足")
    if not g.precheck_ok:
        d["missing"].append("预检未全部通过")
    if not g.master_switch_on:
        d["missing"].append("现场安全总闸未开")
    return d


@router.get("/gates/{run_id}")
async def get_gate(
    run_id: str,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查闸门状态（三件事 + 能否启动）。"""
    gate = session.exec(select(GateState).where(GateState.run_id == run_id)).first()
    if gate is None:
        gate = GateState(run_id=run_id)
        session.add(gate)
        session.commit()
        session.refresh(gate)
    return success_response(data=_gate_dict(gate))


@router.post("/gates/{run_id}/check")
async def check_gate(
    run_id: str,
    interlocks_ok: bool,
    precheck_ok: bool,
    master_switch_on: bool,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """校验/更新闸门三件事。"""
    gate = session.exec(select(GateState).where(GateState.run_id == run_id)).first()
    if gate is None:
        gate = GateState(run_id=run_id)
        session.add(gate)
    gate.interlocks_ok = interlocks_ok
    gate.precheck_ok = precheck_ok
    gate.master_switch_on = master_switch_on
    gate.updated_at = datetime.now(timezone.utc)
    session.add(gate)
    session.commit()
    session.refresh(gate)
    return success_response(data=_gate_dict(gate))


@router.post("/estop")
async def estop(
    run_id: str,
    triggered_by: str,
    snapshot: dict | None = None,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """急停：先发停机指令，再存当时状态快照。阶段 4 模拟只记录不真发。"""
    record = EstopRecord(
        run_id=run_id,
        triggered_by=triggered_by,
        stop_command_sent=True,  # 阶段 4 模拟标记已发；阶段 5 接真设备
        snapshot=snapshot or {},
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return success_response(data=record.model_dump(mode="json"), message="急停已记录（模拟）")
