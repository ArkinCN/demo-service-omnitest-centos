"""
知识库条目请求响应模型（阶段 3.1 引入）。字段一律下划线命名。
"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class KbEntryCreate(BaseModel):
    """创建条目。entry_key 由后端生成，前端不传。"""

    origin: str = Field(..., description="doc / experience")
    title: str = Field(..., max_length=500)
    usage: str = Field(..., description="spec / requirement / process")
    owner_l1: str = Field(default="")
    owner_l2: str = Field(default="")
    owner_l3: str = Field(default="")
    content: dict[str, Any] = Field(default_factory=dict, description="条目正文（JSON）")


class KbEntryUpdate(BaseModel):
    """更新条目 = 出新版本。origin 不可改（改来源应另起条目）。"""

    title: Optional[str] = Field(default=None, max_length=500)
    usage: Optional[str] = Field(default=None)
    content: Optional[dict[str, Any]] = Field(default=None)
    # 经验（origin=experience）更新时必填改动理由
    change_reason: Optional[str] = Field(default=None)


class KbEntryRead(BaseModel):
    """条目响应。"""

    entry_key: str
    version: int
    origin: str
    title: str
    usage: str
    owner_l1: str
    owner_l2: str
    owner_l3: str
    content: dict[str, Any]
    status: str
    change_reason: str
    deleted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KbRefCreate(BaseModel):
    """登记一条引用关系（供引用禁删校验）。"""

    ref_key: str = Field(..., description="引用方标识")
    ref_label: str = Field(default="", description="引用方显示名")
    target_entry_key: str = Field(..., description="被引用条目 key")
