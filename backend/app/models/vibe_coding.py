"""
Code Assistant models - 权限配置与渠道
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import JSON


class VibeCodingConfig(SQLModel, table=True):
    """
    Code Assistant 全局配置表（单行，id=1）
    """
    __tablename__ = "vibe_coding_config"

    id: int = Field(default=1, primary_key=True)

    enabled: bool = Field(
        default=True,
        nullable=False,
        description="全局开关"
    )
    visibility: str = Field(
        default="SPECIFIED",
        max_length=20,
        nullable=False,
        description="可见性：ALL(全员)/SPECIFIED(指定人员)"
    )
    allowed_group_ids: str = Field(
        default="[]",
        sa_column=Column(JSON),
        description="允许访问的用户组ID数组"
    )
    allowed_user_ids: str = Field(
        default="[]",
        sa_column=Column(JSON),
        description="允许访问的用户ID数组"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="更新时间"
    )

    class Config:
        from_attributes = True


class VibeRevokedToken(SQLModel, table=True):
    """
    已吊销的 vibe-coding token(按 JWT jti)。

    每个 vibe 请求都会以 jti 主键查一次本表(与既有的用户有效性查询同库同事务,
    代价一次 PK 点查)。行数上限 = 未过期的吊销记录数;过期行在每次写入时机会性
    清理,无需独立调度任务。
    """
    __tablename__ = "vibe_revoked_tokens"

    jti: str = Field(
        primary_key=True,
        max_length=64,
        description="被吊销 token 的 JWT ID"
    )
    user_id: int = Field(
        nullable=False,
        index=True,
        description="token 所属用户"
    )
    reason: str = Field(
        default="",
        max_length=100,
        nullable=False,
        description="吊销原因: manual(自助/登出) / device_fp_mismatch(指纹不符自动吊销)"
    )
    expires_at: datetime = Field(
        nullable=False,
        description="原 token 的 exp,过此时间该行可清理"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="吊销时间"
    )

    class Config:
        from_attributes = True


class VibeCodingChannel(SQLModel, table=True):
    """
    Code Assistant 渠道表 — 每个渠道包含一组 API 配置
    可以同时启用多个渠道，由用户在客户端选择使用哪一个
    """
    __tablename__ = "vibe_coding_channels"

    id: Optional[int] = Field(default=None, primary_key=True)

    name: str = Field(
        max_length=100,
        nullable=False,
        description="渠道名称，如 '通义千问'、'Anthropic 官方'"
    )
    base_url: str = Field(
        max_length=500,
        nullable=False,
        description="API Base URL"
    )
    api_key: str = Field(
        max_length=500,
        nullable=False,
        description="API Key"
    )
    model: str = Field(
        max_length=100,
        nullable=False,
        description="模型名称，如 'qwen3.6-plus'"
    )
    enabled: bool = Field(
        default=False,
        nullable=False,
        description="是否启用（对用户可见，可多个为 True）"
    )
    is_default: bool = Field(
        default=False,
        nullable=False,
        description="是否为默认渠道（最多一个为 True）"
    )
    channel_type: str = Field(
        default="main",
        max_length=20,
        nullable=False,
        description="渠道类型: main(主代理) / subagent(子代理)"
    )
    protocol: str = Field(
        default="anthropic",
        max_length=20,
        nullable=False,
        description="上游协议: anthropic / openai_responses / openai_chat"
    )
    # 前端展示分组/图标/能力标签（命名对齐网关 ModelPricing，供 CLI/app 选择器分组显示）
    provider_name: str = Field(
        default="",
        max_length=50,
        nullable=False,
        description="厂商显示名（前端按此分组），如 'DeepSeek'"
    )
    provider_icon: str = Field(
        default="",
        max_length=200,
        nullable=False,
        description="厂商 logo 路径，如 '/modelAvatars/DeepSeek.svg'"
    )
    provider_icon_size: str = Field(
        default="",
        max_length=20,
        nullable=False,
        description="厂商 logo 尺寸 class，如 'size-5'"
    )
    vision: bool = Field(
        default=False,
        nullable=False,
        description="是否支持视觉输入（前端显示'视觉'标签）"
    )
    reasoning: bool = Field(
        default=False,
        nullable=False,
        description="是否支持深度思考（前端显示'深度思考'标签）"
    )
    sort_order: int = Field(
        default=0,
        nullable=False,
        description="排序权重，越小越靠前"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="创建时间"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="更新时间"
    )

    class Config:
        from_attributes = True
