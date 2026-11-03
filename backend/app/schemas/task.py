"""
Task 请求响应模型（阶段 2 引入）。
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    """创建任务请求。user_id 不由前端传，由登录态注入。"""

    title: str = Field(..., max_length=500, description="任务标题")
    scene_id: str = Field(default="", max_length=200, description="场景 ID")
    version: str = Field(default="", max_length=100, description="版本")
    status: str = Field(default="draft", max_length=50, description="状态")


class TaskUpdate(BaseModel):
    """更新任务请求。只更新显式传入的字段（exclude_unset）。"""

    title: Optional[str] = Field(default=None, max_length=500)
    scene_id: Optional[str] = Field(default=None, max_length=200)
    version: Optional[str] = Field(default=None, max_length=100)
    status: Optional[str] = Field(default=None, max_length=50)


class TaskRead(BaseModel):
    """任务响应。"""

    id: int
    title: str
    user_id: int
    scene_id: str
    version: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
