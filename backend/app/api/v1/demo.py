"""数据源模式切换（真机 / 演示）。

【为什么需要这个接口】
  真机数据在 schema ``omnitest``，演示数据在 schema ``omnitest_demo``，
  两者表结构完全相同，只靠连接时的 ``search_path`` 区分。
  切换模式 = 改进程内用哪个引擎，不动数据、不重启进程、不迁移任何表。

【切换不是「改数据」，是「换读哪个库」】
  演示数据由离线脚本预先生成并灌入 omnitest_demo（见 db/migrate/gen_demo_data.py）。
  本接口只负责把查询指向它，因此切换是毫秒级的，也不会污染真机数据。

【多 worker 限制】
  模式存在进程内存里。本服务必须保持单 uvicorn worker（既有部署约束），
  多 worker 会出现「一部分请求读真机、一部分读演示」的错乱状态。
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import require_admin
from app.core.config import settings
from app.db.session import get_mode, is_demo_available, set_mode
from app.models.user import User

router = APIRouter(prefix="/demo", tags=["demo"])


class DemoStatus(BaseModel):
    """当前数据源状态。前端据此显示「演示中」角标。"""

    mode: str = Field(description="live=真机数据 / demo=演示数据")
    demo_available: bool = Field(
        description="当前部署是否支持演示模式（需要 PostgreSQL 双 schema；SQLite/MySQL 部署为 false）"
    )
    schema_live: str = Field(default="", description="真机数据所在 schema")
    schema_demo: str = Field(default="", description="演示数据所在 schema")


class ActivateRequest(BaseModel):
    mode: Literal["live", "demo"]


def _status() -> DemoStatus:
    return DemoStatus(
        mode=get_mode(),
        demo_available=is_demo_available(),
        schema_live=settings.DB_SCHEMA,
        schema_demo=settings.DB_DEMO_SCHEMA,
    )


@router.get("/status", response_model=DemoStatus)
def read_status() -> DemoStatus:
    """查询当前数据源模式。只读，登录用户即可访问。

    前端应在全局顶栏展示 mode：``demo`` 时必须有明显标识，
    避免把演示数据误当成真实测试结果。
    """
    return _status()


@router.post("/activate", response_model=DemoStatus)
def activate(
    payload: ActivateRequest,
    _admin: User = Depends(require_admin),
) -> DemoStatus:
    """切换数据源模式。仅管理员。

    切到 ``demo`` 前请确认 omnitest_demo 里已灌好目标数据集
    （``db/migrate/gen_demo_data.py`` 产出，运维脚本导入）。
    """
    try:
        set_mode(payload.mode)
    except (ValueError, RuntimeError) as exc:
        # ValueError: 非法模式值；RuntimeError: 当前部署不支持演示模式
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _status()
