"""
Agreement model using SQLModel
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel, Column, UniqueConstraint
from sqlalchemy import Text


class Agreement(SQLModel, table=True):
    """
    Agreement database model (服务条款/隐私政策)

    Attributes:
        id: Primary key
        type: Agreement type (terms_of_service / privacy_policy)
        version: Version string (e.g. "1.0")
        title: Agreement title
        content: Agreement content in markdown
        is_published: Whether this version is published
        created_by: Admin user ID who created this version
        published_at: When this version was published
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """
    __tablename__ = "agreements"
    __table_args__ = (
        UniqueConstraint("type", "version", name="uq_agreement_type_version"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    type: str = Field(
        max_length=30,
        nullable=False,
        index=True,
        description="协议类型: terms_of_service / privacy_policy"
    )
    version: str = Field(
        max_length=20,
        nullable=False,
        description="版本号，如 1.0"
    )
    title: str = Field(
        max_length=200,
        nullable=False,
        description="协议标题"
    )
    content: str = Field(
        sa_column=Column(Text, nullable=False),
        description="协议内容 (Markdown)"
    )
    is_published: bool = Field(
        default=False,
        nullable=False,
        description="是否已发布"
    )
    created_by: Optional[int] = Field(
        default=None,
        foreign_key="users.id",
        description="创建者管理员ID"
    )
    published_at: Optional[datetime] = Field(
        default=None,
        description="发布时间"
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


class UserAgreementAcceptance(SQLModel, table=True):
    """
    User agreement acceptance record (用户协议接受记录)

    Attributes:
        id: Primary key
        user_id: User who accepted
        agreement_id: Agreement that was accepted
        accepted_at: When the user accepted
    """
    __tablename__ = "user_agreement_acceptances"
    __table_args__ = (
        UniqueConstraint("user_id", "agreement_id", name="uq_user_agreement"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    user_id: int = Field(
        foreign_key="users.id",
        nullable=False,
        index=True,
        description="用户ID"
    )
    agreement_id: int = Field(
        foreign_key="agreements.id",
        nullable=False,
        index=True,
        description="协议ID"
    )
    accepted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="接受时间"
    )

    class Config:
        from_attributes = True
