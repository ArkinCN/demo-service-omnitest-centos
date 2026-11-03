"""统计分组勾选：记录哪些用户分组（user_groups，仅 CUSTOM）参与统计页排行/趋势。"""
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class StatGroupSelection(SQLModel, table=True):
    __tablename__ = "stat_group_selections"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_group_id: int = Field(foreign_key="user_groups.id", unique=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
