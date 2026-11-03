"""
Feature Access models - 功能分组与路由权限控制
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import JSON


class FeatureGroup(SQLModel, table=True):
    """
    功能分组表 — 如 AI智能体、AI工具箱、应用中心
    """
    __tablename__ = "feature_groups"

    id: Optional[int] = Field(default=None, primary_key=True)

    name: str = Field(
        max_length=50,
        nullable=False,
        description="分组名，如 'AI智能体'"
    )
    group_key: str = Field(
        max_length=50,
        nullable=False,
        unique=True,
        description="标识符，如 'agents'"
    )
    i18n_key: Optional[str] = Field(
        default=None,
        max_length=100,
        description="国际化翻译 key，如 'nav_agents'，前端优先用此 key 翻译"
    )
    sort_order: int = Field(
        default=0,
        nullable=False,
        description="排序权重，越小越靠前"
    )
    is_active: bool = Field(
        default=True,
        nullable=False,
        description="是否启用"
    )
    visibility: str = Field(
        default="ALL",
        max_length=20,
        nullable=False,
        description="可见性：ALL(全员) / INTERNAL(内部用户) / SPECIFIED(指定人员)"
    )
    allowed_group_ids: str = Field(
        default="[]",
        sa_column=Column(JSON),
        description="允许访问的用户组 ID 数组"
    )
    allowed_user_ids: str = Field(
        default="[]",
        sa_column=Column(JSON),
        description="允许访问的用户 ID 数组"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="创建时间"
    )

    class Config:
        from_attributes = True


class FeatureRoute(SQLModel, table=True):
    """
    功能路由表 — 分组下的具体路由条目
    """
    __tablename__ = "feature_routes"

    id: Optional[int] = Field(default=None, primary_key=True)

    group_id: int = Field(
        nullable=False,
        foreign_key="feature_groups.id",
        description="所属分组 ID"
    )
    name: str = Field(
        max_length=100,
        nullable=False,
        description="路由显示名"
    )
    i18n_key: Optional[str] = Field(
        default=None,
        max_length=100,
        description="国际化翻译 key，如 'agent_debug'，前端优先用此 key 翻译"
    )
    route_path: str = Field(
        max_length=200,
        nullable=False,
        description="前端路由路径，如 '/agent-debug'"
    )
    icon: Optional[str] = Field(
        default=None,
        max_length=100,
        description="图标名，如 'IconDeviceImacCode'"
    )
    is_external_window: bool = Field(
        default=False,
        nullable=False,
        description="是否为独立窗口路由"
    )
    sort_order: int = Field(
        default=0,
        nullable=False,
        description="排序权重，越小越靠前"
    )
    is_active: bool = Field(
        default=True,
        nullable=False,
        description="是否启用"
    )
    visibility: str = Field(
        default="ALL",
        max_length=20,
        nullable=False,
        description="可见性：ALL(跟随分组) / INTERNAL(内部用户) / SPECIFIED(指定人员)"
    )
    allowed_group_ids: str = Field(
        default="[]",
        sa_column=Column(JSON),
        description="允许访问的用户组 ID 数组"
    )
    allowed_user_ids: str = Field(
        default="[]",
        sa_column=Column(JSON),
        description="允许访问的用户 ID 数组"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="创建时间"
    )

    class Config:
        from_attributes = True
