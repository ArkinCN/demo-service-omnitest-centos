"""
统一模型网关 — 渠道与模型定价

- GatewayChannel: 上游渠道（base_url/api_key/protocol），网关按 model 路由到渠道。
- ModelPricing: 每个模型的费率与倍率（credits 计费用），后台可配。
- ModuleDisplay: 来源模块（ai_requests.module_name）→ 用量页显示名+配色，后台可配。
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import JSON


class GatewayChannel(SQLModel, table=True):
    """统一网关的上游渠道。一个渠道 = 一组上游 API 配置 + 协议。"""
    __tablename__ = "gateway_channels"

    id: Optional[int] = Field(default=None, primary_key=True)

    name: str = Field(
        max_length=100,
        nullable=False,
        description="渠道名称，如 'Anthropic 官方'、'通义千问'",
    )
    base_url: str = Field(
        max_length=500,
        nullable=False,
        description="上游 API Base URL（不含 /v1/messages 等具体路径）",
    )
    api_key: str = Field(
        max_length=500,
        nullable=False,
        description="上游 API Key",
    )
    protocol: str = Field(
        default="anthropic",
        max_length=20,
        nullable=False,
        index=True,
        description="上游协议: anthropic / openai_chat / openai_responses",
    )
    enabled: bool = Field(
        default=True,
        nullable=False,
        description="是否启用",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="创建时间",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="更新时间",
    )

    class Config:
        from_attributes = True
        protected_namespaces = ()


class ModelPricing(SQLModel, table=True):
    """模型费率与倍率（credits 计费）。费率单位：credits / 1M tokens。

    扣费：credits = ((prompt-cache_read)*in_rate + cache_read*cache_rate
                     + completion*out_rate) / 1_000_000 * multiplier
    """
    __tablename__ = "model_pricing"

    id: Optional[int] = Field(default=None, primary_key=True)

    model_id: str = Field(
        max_length=100,
        nullable=False,
        unique=True,
        index=True,
        description="模型标识，如 'gpt-5.2'、'deepseek-v4-pro'",
    )
    display_name: str = Field(
        default="",
        max_length=100,
        description="展示名，如 'GPT-5.2'",
    )
    upstream_model_id: str = Field(
        default="",
        max_length=100,
        description=(
            "路由目标：转发给上游时实际使用的模型名。"
            "空=透传 model_id；非空时网关把请求体的 model 替换成它，"
            "用户端与计费/记账仍按展示用的 model_id。"
        ),
    )
    is_tier: bool = Field(
        default=False,
        nullable=False,
        description=(
            "是否为抽象档位（如 极致/性能/经济/Auto）。"
            "True 时面板里置顶独立成组、只露档位名+描述，真实模型由 upstream_model_id 隐藏。"
        ),
    )
    description: str = Field(
        default="",
        max_length=500,
        description="档位/模型描述，用作选择面板 hover 卡片副标题。",
    )
    channel_id: Optional[int] = Field(
        default=None,
        foreign_key="gateway_channels.id",
        index=True,
        description="绑定的上游渠道；NULL 表示用协议默认渠道",
    )

    # 费率：credits / 1M tokens
    in_rate: float = Field(default=0.0, description="输入费率 credits/M tokens")
    out_rate: float = Field(default=0.0, description="输出费率 credits/M tokens")
    cache_rate: float = Field(
        default=0.0,
        description="缓存命中输入费率 credits/M tokens（通常低于 in_rate）",
    )
    cache_creation_rate: float = Field(
        default=0.0,
        description="缓存写入费率 credits/M tokens（默认继承 in_rate）",
    )

    multiplier: float = Field(
        default=1.0,
        nullable=False,
        description="倍率（如 0.25/0.6/1.0），作用于最终 credits 消耗",
    )

    # 绘图按张计费：每生成一张图扣多少 credits（0=不按张计；绘图模型须 >0）。
    per_image_rate: float = Field(
        default=0.0,
        nullable=False,
        description="每张图片消耗的 credits（绘图模型用，按张计费）。",
    )

    context_window: int = Field(
        default=0,
        nullable=False,
        description="上下文窗口大小（tokens）。0=不限/不裁剪；>0 时 AI 对话超窗会滑动丢弃最早历史。",
    )

    chat_enabled: bool = Field(
        default=False,
        nullable=False,
        description="是否在 AI 对话模型面板露出（网关模型是全集，AI 对话只用其中部分）。",
    )
    vision: bool = Field(
        default=False,
        nullable=False,
        description="是否支持视觉输入（AI 对话发图时据此判断）。",
    )
    reasoning: bool = Field(
        default=False,
        nullable=False,
        description="是否支持深度思考（UI 标记）。",
    )

    # ── AI 对话展示元信息 ──
    provider_name: str = Field(
        default="",
        max_length=50,
        description="厂商显示名（前端按此分组），如 'DeepSeek'。",
    )
    provider_icon: str = Field(
        default="",
        max_length=200,
        description="厂商 logo 路径，如 '/modelAvatars/DeepSeek.svg'。",
    )
    provider_icon_size: str = Field(
        default="",
        max_length=20,
        description="logo 尺寸 class（如 'size-5'），空则前端用默认。",
    )
    sort_order: int = Field(
        default=0,
        nullable=False,
        description="排序权重，越小越靠前。",
    )

    # ── 模型级权限（与旧 chat_models 一致）──
    visibility: str = Field(
        default="ALL",
        max_length=20,
        nullable=False,
        description="可见性：ALL / INTERNAL(@example.internal) / SPECIFIED。",
    )
    allowed_group_ids: list = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="SPECIFIED 时允许的用户组 ID 数组（JSON）。",
    )
    allowed_user_ids: list = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="SPECIFIED 时允许的用户 ID 数组（JSON）。",
    )

    # 预留错峰折扣字段（本期不实现按时段变价逻辑）
    off_peak_multiplier: Optional[float] = Field(
        default=None,
        description="预留：错峰倍率（本期不启用）",
    )

    is_active: bool = Field(
        default=True,
        nullable=False,
        description="是否启用（对用户可见/可路由）",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    class Config:
        from_attributes = True
        protected_namespaces = ()


class ModuleDisplay(SQLModel, table=True):
    """来源模块显示映射。把 ai_requests.module_name 映射成用量页的友好名 + 配色。

    color 存调色板键名（blue/emerald/amber/pink/violet/rose/cyan/slate），
    前端据此套用对应的 Tailwind 类（含暗色变体），不直接存 hex。
    未在表中的 module 前端会 fallback：原样显示 + 按名 hash 配色。
    """
    __tablename__ = "module_displays"

    id: Optional[int] = Field(default=None, primary_key=True)

    module_key: str = Field(
        max_length=100,
        nullable=False,
        unique=True,
        index=True,
        description="来源标识，对应 ai_requests.module_name，如 'ai_chat'、'vibe-coding'",
    )
    label: str = Field(max_length=100, nullable=False, description="显示名，如 'AI 对话'")
    color: str = Field(
        default="slate",
        max_length=20,
        nullable=False,
        description="调色板键名：blue/emerald/amber/pink/violet/rose/cyan/slate",
    )
    sort_order: int = Field(default=0, nullable=False, description="排序权重，越小越靠前")
    is_active: bool = Field(default=True, nullable=False, description="是否启用（停用则前端走 fallback）")

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    class Config:
        from_attributes = True
        protected_namespaces = ()
