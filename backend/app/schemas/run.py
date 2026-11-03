"""
轮次产物请求响应模型（阶段 4.1 引入）。字段一律下划线命名。
"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class RunCreate(BaseModel):
    """创建一轮运行。run_id 后端生成。"""

    scene_id: str = Field(default="", max_length=200)
    mode: str = Field(default="mock", description="mock / real（诚实标记）")


class RunRead(BaseModel):
    """运行响应。"""

    run_id: str
    user_id: int
    scene_id: str
    status: str
    mode: str
    created_at: datetime
    finished_at: Optional[datetime]

    class Config:
        from_attributes = True


class ArtifactPut(BaseModel):
    """写入一份产物。schema 由 artifact_kind 推导，前端只需传 content。"""

    content: dict[str, Any] = Field(..., description="产物正文（JSON）")


class ArtifactRead(BaseModel):
    """产物响应。

    字段名用 schema_version 而不是 schema：`schema` 是 pydantic v2 父类
    BaseModel 上的一个方法名，直接拿来当字段会触发
    「Field name "schema" shadows an attribute in parent "BaseModel"」警告。
    对外契约仍要求叫 schema，所以用 serialization_alias 把序列化名改回去——
    契约不变，警告消失。
    """

    model_config = ConfigDict(populate_by_name=True)

    run_id: str
    artifact_kind: str
    schema_version: str = Field(
        ...,
        serialization_alias="schema",
        validation_alias="schema",
        description="schema 标识 + 版本号，如 config-snapshot/v1",
    )
    content: dict[str, Any]
    created_at: datetime
    updated_at: datetime
