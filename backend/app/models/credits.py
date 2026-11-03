"""
Credits 计费体系 — 套餐、订阅、余额、流水

- SubscriptionPlan: 套餐定义（内测期只有 trial，5000/月）。
- UserSubscription: 用户绑定的套餐 + 月度刷新游标。
- UserCredits: 用户当前 credits 余额。
- CreditTransaction: 每笔 credits 变动流水（消耗/发放/重置/退款）。

AI 对话与 vibe-coding 共用同一 credits 池。
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import Text, BigInteger


class SubscriptionPlan(SQLModel, table=True):
    """套餐定义。内测期 seed 一个 trial（5000 credits/月）。"""
    __tablename__ = "subscription_plans"

    id: Optional[int] = Field(default=None, primary_key=True)

    plan_key: str = Field(
        max_length=50,
        nullable=False,
        unique=True,
        index=True,
        description="套餐标识，如 'trial'",
    )
    name: str = Field(max_length=100, nullable=False, description="套餐显示名")
    monthly_credits: int = Field(
        default=0,
        nullable=False,
        description="每月 credits 额度",
    )
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    class Config:
        from_attributes = True


class UserSubscription(SQLModel, table=True):
    """用户订阅。记录绑定套餐与本月刷新游标（懒刷新判断用）。"""
    __tablename__ = "user_subscriptions"

    id: Optional[int] = Field(default=None, primary_key=True)

    user_id: int = Field(
        foreign_key="users.id",
        nullable=False,
        unique=True,
        index=True,
        description="用户ID（一人一订阅）",
    )
    plan_key: str = Field(
        default="trial",
        max_length=50,
        nullable=False,
        description="绑定的套餐 key",
    )
    credits_refreshed_at: Optional[datetime] = Field(
        default=None,
        description="上次按套餐刷新额度的时间（用于月度懒刷新判断）",
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


class UserCredits(SQLModel, table=True):
    """用户 credits 余额。balance 为整数（最小计费粒度，见 credits_service）。"""
    __tablename__ = "user_credits"

    id: Optional[int] = Field(default=None, primary_key=True)

    user_id: int = Field(
        foreign_key="users.id",
        nullable=False,
        unique=True,
        index=True,
        description="用户ID",
    )
    balance: int = Field(
        default=0,
        sa_column=Column(BigInteger, nullable=False, default=0),
        description="当前余额（credits 最小单位，见 CREDIT_UNIT）",
    )
    total_granted: int = Field(
        default=0,
        sa_column=Column(BigInteger, nullable=False, default=0),
        description="累计发放",
    )
    total_consumed: int = Field(
        default=0,
        sa_column=Column(BigInteger, nullable=False, default=0),
        description="累计消耗",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    class Config:
        from_attributes = True


class CreditTransaction(SQLModel, table=True):
    """credits 变动流水。便于对账与后台展示。"""
    __tablename__ = "credit_transactions"

    id: Optional[int] = Field(default=None, primary_key=True)

    user_id: int = Field(
        foreign_key="users.id",
        nullable=False,
        index=True,
        description="用户ID",
    )
    type: str = Field(
        max_length=20,
        nullable=False,
        index=True,
        description="变动类型: consume / grant / reset / refund",
    )
    amount: int = Field(
        default=0,
        sa_column=Column(BigInteger, nullable=False, default=0),
        description="变动量（消耗为负，发放为正）",
    )
    balance_after: int = Field(
        default=0,
        sa_column=Column(BigInteger, nullable=False, default=0),
        description="变动后余额",
    )

    # 消耗类流水的来源信息
    ai_request_id: Optional[int] = Field(
        default=None,
        index=True,
        description="关联的 ai_requests.id（消耗类）",
    )
    model: Optional[str] = Field(default=None, max_length=100)
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    cache_read_tokens: int = Field(default=0)
    cache_creation_tokens: int = Field(default=0)
    multiplier: Optional[float] = Field(default=None)

    note: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )

    class Config:
        from_attributes = True
