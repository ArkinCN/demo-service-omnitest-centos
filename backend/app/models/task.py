"""
Task 数据模型（阶段 2 引入）。

对应主文档阶段 2「任务存什么」：标题、原用户 ID、场景 ID、版本、状态。
user_id 为「原用户 ID」——创建任务的那个用户，一律由登录态注入，不信任前端。
"""
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class Task(SQLModel, table=True):
    """测试任务。阶段 2 仅做最小闭环：建任务 → 改字段 → 保存 → 读回。"""

    __tablename__ = "tasks"

    id: Optional[int] = Field(default=None, primary_key=True)

    title: str = Field(max_length=500, description="任务标题")
    user_id: int = Field(
        foreign_key="users.id",
        index=True,
        nullable=False,
        description="所属用户 ID（创建者，从登录态取）",
    )
    scene_id: str = Field(default="", max_length=200, description="场景 ID")
    version: str = Field(default="", max_length=100, description="版本")
    status: str = Field(default="draft", max_length=50, description="状态（阶段 2 默认 draft）")

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="创建时间"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="更新时间"
    )

    class Config:
        from_attributes = True
