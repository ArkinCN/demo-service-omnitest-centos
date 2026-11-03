"""
轮次产物读写路由（阶段 4.1 引入）。

端点（主文档 4.1 建议）：
  POST /api/runs                              创建一轮，返回 run_id
  GET  /api/runs?scene_id=&limit=             历史轮次索引
  GET  /api/runs/{run_id}                     一轮的全部产物
  PUT  /api/runs/{run_id}/{artifact_kind}     写入一份产物
  GET  /api/runs/{run_id}/{artifact_kind}     读一份产物

artifact_kind 七值，schema 由 ARTIFACT_SCHEMAS 写死版本号推导。
归属校验：非本人运行读/写返回 403。字段一律下划线命名。
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from app.api.deps import get_current_user, get_db
from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.models.run import ARTIFACT_SCHEMAS, ActionRecord, Artifact, Run, can_transition
from app.models.user import User
from app.schemas.common import success_response
from app.schemas.run import ArtifactPut, ArtifactRead, RunCreate, RunRead

router = APIRouter(prefix="/runs", tags=["Runs"])


def _owned_run(run_id: str, session: Session, user_id: int) -> Run:
    """取运行并校验归属：不存在 404，非本人 403。"""
    run = session.exec(select(Run).where(Run.run_id == run_id)).first()
    if run is None:
        raise NotFoundException("运行不存在")
    if run.user_id != user_id:
        raise ForbiddenException("无权访问该运行")
    return run


def _run_dict(run: Run) -> dict:
    return RunRead.model_validate(run).model_dump(mode="json")


def _artifact_dict(a: Artifact) -> dict:
    """内部字段 schema_version → 对外契约字段 schema（由 serialization_alias 完成）。"""
    return ArtifactRead(
        run_id=a.run_id,
        artifact_kind=a.artifact_kind,
        schema_version=a.schema_version,
        content=a.content,
        created_at=a.created_at,
        updated_at=a.updated_at,
    ).model_dump(mode="json", by_alias=True)


@router.post("")
async def create_run(
    payload: RunCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建一轮运行。run_id 用 uuid hex，可拼进 URL。"""
    run = Run(
        run_id=uuid.uuid4().hex,
        user_id=current_user.id,
        scene_id=payload.scene_id,
        status="draft",
        mode=payload.mode,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return success_response(data=_run_dict(run), message="运行已创建")


@router.get("")
async def list_runs(
    scene_id: str | None = Query(default=None, description="按场景过滤"),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """历史轮次索引（按时间倒序）。"""
    q = select(Run).where(Run.user_id == current_user.id)
    if scene_id:
        q = q.where(Run.scene_id == scene_id)
    q = q.order_by(Run.created_at.desc()).limit(limit)
    runs = session.exec(q).all()
    return success_response(data=[_run_dict(r) for r in runs])


@router.get("/{run_id}")
async def get_run(
    run_id: str,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """一轮的全部产物（运行元信息 + 各 artifact）。"""
    run = _owned_run(run_id, session, current_user.id)
    artifacts = session.exec(
        select(Artifact).where(Artifact.run_id == run_id).order_by(Artifact.created_at)
    ).all()
    return success_response(data={
        "run": _run_dict(run),
        "artifacts": [_artifact_dict(a) for a in artifacts],
    })


@router.put("/{run_id}/{artifact_kind}")
async def put_artifact(
    run_id: str,
    artifact_kind: str,
    payload: ArtifactPut,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """写入一份产物。artifact_kind 非法返回 409；同 run+kind 覆盖（更新时间）。"""
    if artifact_kind not in ARTIFACT_SCHEMAS:
        raise ConflictException(
            f"artifact_kind 必须是七值之一：{' / '.join(ARTIFACT_SCHEMAS)}"
        )
    run = _owned_run(run_id, session, current_user.id)

    existing = session.exec(
        select(Artifact).where(
            Artifact.run_id == run_id, Artifact.artifact_kind == artifact_kind
        )
    ).first()
    if existing:
        existing.content = payload.content
        existing.updated_at = datetime.now(timezone.utc)
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return success_response(data=_artifact_dict(existing), message="产物已更新")

    artifact = Artifact(
        run_id=run_id,
        artifact_kind=artifact_kind,
        schema_version=ARTIFACT_SCHEMAS[artifact_kind],
        content=payload.content,
    )
    session.add(artifact)
    session.commit()
    session.refresh(artifact)
    return success_response(data=_artifact_dict(artifact), message="产物已写入")


@router.get("/{run_id}/{artifact_kind}")
async def get_artifact(
    run_id: str,
    artifact_kind: str,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """读一份产物。"""
    run = _owned_run(run_id, session, current_user.id)
    artifact = session.exec(
        select(Artifact).where(
            Artifact.run_id == run_id, Artifact.artifact_kind == artifact_kind
        )
    ).first()
    if artifact is None:
        raise NotFoundException("产物不存在")
    return success_response(data=_artifact_dict(artifact))


# ── 4.2 运行状态机 + 幂等动作 ──

@router.post("/{run_id}/transition")
async def transition_run(
    run_id: str,
    to_status: str,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """状态迁移（主文档 4.2 状态机）。非法迁移返回 409。"""
    run = _owned_run(run_id, session, current_user.id)

    if not can_transition(run.status, to_status):
        raise ConflictException(
            f"非法状态迁移：{run.status} → {to_status}"
        )

    run.status = to_status
    if to_status == "completed":
        run.finished_at = datetime.now(timezone.utc)
    session.add(run)
    session.commit()
    session.refresh(run)
    return success_response(data=_run_dict(run), message="状态已迁移")


@router.post("/{run_id}/actions")
async def record_action(
    run_id: str,
    action_type: str,
    action_key: str,
    payload: dict | None = None,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录一个动作（主文档 4.2「先记动作和幂等键，再发命令」）。

    幂等：同一 (run_id, action_key) 已存在时返回同一 action_id，不再新建。
    阶段 4 为模拟环境，只记录不真下发；阶段 5 接设备桥后在此处补真实执行。
    """
    run = _owned_run(run_id, session, current_user.id)

    existing = session.exec(
        select(ActionRecord).where(
            ActionRecord.run_id == run_id, ActionRecord.action_key == action_key
        )
    ).first()
    if existing:
        # 幂等命中：返回同一 action_id，不重复执行
        return success_response(data={
            "action_id": existing.action_id,
            "status": existing.status,
            "replayed": True,
        }, message="幂等命中，未重复执行")

    record = ActionRecord(
        run_id=run_id,
        action_id=uuid.uuid4().hex,
        action_key=action_key,
        action_type=action_type,
        status="requested",
        payload=payload or {},
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return success_response(data={
        "action_id": record.action_id,
        "status": record.status,
        "replayed": False,
    }, message="动作已记录")
