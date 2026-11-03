"""
知识库三轴分类条目模型（阶段 3.1 引入，P3）。

三轴分类（主文档 3.1）：
- 归属 owner：三级（l1 场景 / l2 子类 / l3 产品类型）
- 来[源] origin：两类（doc 文档 / experience 经验）
- 用途 usage：三类（spec 产品说明书 / requirement 测试需求 / process 工艺）

条目生命周期两道闸：
1. 软删除：删除只改 status=deleted 不抹数据，可查可恢复（原件保留 90 天）；
2. 被引用禁删：引用计数 >0 时删除请求返回 409 并逐条列出引用方。

版本化：改文档/改经验一律出新版本不原地覆盖；同一 entry_key 下 version 递增；
经验的改动理由（change_reason）是必填字段。
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Text
from sqlmodel import Column, Field, SQLModel


class KbEntry(SQLModel, table=True):
    """知识条目（文档或经验）。同一 entry_key 的多条记录构成版本链，最新版本 status 由
    deleted_at 是否为空区分（软删除）。"""

    __tablename__ = "kb_entries"

    id: Optional[int] = Field(default=None, primary_key=True)

    entry_key: str = Field(index=True, description="逻辑条目的稳定标识，版本链共享同一个 key")
    version: int = Field(default=1, description="版本号，同一 entry_key 下递增")
    origin: str = Field(max_length=20, index=True, description="来源：doc / experience")
    title: str = Field(max_length=500, description="标题（经验用 symptom 首句）")
    usage: str = Field(max_length=20, index=True, description="用途：spec / requirement / process")

    owner_l1: str = Field(default="", max_length=100, description="归属一级（场景）")
    owner_l2: str = Field(default="", max_length=100, description="归属二级（子类）")
    owner_l3: str = Field(default="", max_length=100, description="归属三级（产品类型）")

    content: str = Field(default="{}", sa_column=Column(JSON), description="条目正文（JSON，按 origin 定形状）")

    status: str = Field(default="active", max_length=20, index=True, description="active / deleted（软删除）")
    change_reason: str = Field(default="", sa_column=Column(Text), description="改动理由；经验更新时必填")
    deleted_at: Optional[datetime] = Field(default=None, description="软删除时间（非空即已删除）")

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="创建时间")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="更新时间")

    class Config:
        from_attributes = True


class KbRef(SQLModel, table=True):
    """条目引用关系表。记录「谁引用了哪条知识条目」，用于引用禁删校验。"""

    __tablename__ = "kb_refs"

    id: Optional[int] = Field(default=None, primary_key=True)

    ref_key: str = Field(index=True, description="引用方标识（如 run_id / report_id / 判据 id）")
    ref_label: str = Field(default="", description="引用方显示名（供 409 响应逐条列出）")
    target_entry_key: str = Field(index=True, description="被引用的条目 entry_key")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        from_attributes = True
