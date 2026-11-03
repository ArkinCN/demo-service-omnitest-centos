"""
测试任务路由（阶段 2 引入）。

完整链路：POST /tasks 建任务 → PATCH /tasks/{id} 改字段 → GET /tasks/{id} 读回。
- 复用 get_current_user 鉴权；
- user_id 一律从登录态取，不信任前端传参；
- 归属校验：非本人任务读/改一律 403。
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_current_user, get_db
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.task import Task
from app.models.user import User
from app.schemas.common import success_response
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["Tasks"])


def _owned_task(task_id: int, session: Session, user_id: int) -> Task:
    """取任务并校验归属：不存在 404，非本人 403。"""
    task = session.get(Task, task_id)
    if task is None:
        raise NotFoundException("任务不存在")
    if task.user_id != user_id:
        raise ForbiddenException("无权访问该任务")
    return task


def _to_dict(task: Task) -> dict:
    """Task 实例 → 可序列化 dict（datetime 转 ISO 字符串）。"""
    return TaskRead.model_validate(task).model_dump(mode="json")


@router.post("")
async def create_task(
    payload: TaskCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建任务。user_id 从登录态取，不信任前端。"""
    task = Task(
        title=payload.title,
        user_id=current_user.id,
        scene_id=payload.scene_id,
        version=payload.version,
        status=payload.status,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return success_response(data=_to_dict(task), message="任务已创建")


@router.get("/{task_id}")
async def get_task(
    task_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """读取任务（校验归属：非本人 403）。"""
    task = _owned_task(task_id, session, current_user.id)
    return success_response(data=_to_dict(task))


@router.patch("/{task_id}")
async def update_task(
    task_id: int,
    payload: TaskUpdate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新任务字段（校验归属：非本人 403）。"""
    task = _owned_task(task_id, session, current_user.id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, key, value)
    task.updated_at = datetime.now(timezone.utc)
    session.add(task)
    session.commit()
    session.refresh(task)
    return success_response(data=_to_dict(task), message="任务已更新")
