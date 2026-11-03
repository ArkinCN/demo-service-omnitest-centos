"""
Feedback model using SQLModel
"""
from datetime import datetime, timezone
from typing import Optional, List
from sqlmodel import Field, SQLModel, Column, Relationship
from sqlalchemy import JSON


class FeedbackModule(SQLModel, table=True):
    """
    Feedback module database model (功能模块)

    Attributes:
        id: Primary key
        name: Module name
        parent_id: Parent module ID (NULL for top-level modules)
        sort_order: Sort order
        is_active: Whether the module is active
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """
    __tablename__ = "feedback_modules"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Module info
    name: str = Field(
        max_length=50,
        nullable=False,
        description="模块名称"
    )
    parent_id: Optional[int] = Field(
        default=None,
        foreign_key="feedback_modules.id",
        description="父模块ID，NULL表示一级模块"
    )
    sort_order: int = Field(
        default=0,
        nullable=False,
        description="排序顺序"
    )
    is_active: bool = Field(
        default=True,
        nullable=False,
        description="是否启用"
    )

    # Timestamps
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
        """SQLModel configuration"""
        from_attributes = True


class Feedback(SQLModel, table=True):
    """
    Feedback database model

    Attributes:
        id: Primary key
        user_id: Foreign key to users table
        category: Feedback category (BUG/FEATURE/QUESTION/OTHER)
        description: Detailed problem description
        contact_info: Optional contact information
        attachments: JSON array of screenshot URLs
        status: Feedback status (PENDING/IN_PROGRESS/RESOLVED/CLOSED)
        priority: Feedback priority (LOW/MEDIUM/HIGH/URGENT)
        assigned_to: Optional admin user ID assigned to this feedback
        created_at: Creation timestamp
        updated_at: Last update timestamp
        resolved_at: Resolution timestamp
    """
    __tablename__ = "feedbacks"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Foreign keys
    user_id: int = Field(
        foreign_key="users.id",
        nullable=False,
        index=True,
        description="提交用户ID"
    )
    assigned_to: Optional[int] = Field(
        default=None,
        foreign_key="users.id",
        description="分配给的管理员ID"
    )
    module_id: Optional[int] = Field(
        default=None,
        foreign_key="feedback_modules.id",
        index=True,
        description="关联的功能模块ID"
    )

    # Feedback content
    category: str = Field(
        max_length=50,
        nullable=False,
        index=True,
        description="意见建议分类：BUG/FEATURE/QUESTION/OTHER"
    )
    description: str = Field(
        nullable=False,
        description="问题描述"
    )
    contact_info: Optional[str] = Field(
        default=None,
        max_length=200,
        description="联系方式"
    )

    # Attachments as JSON array
    attachments: str = Field(
        default="[]",
        sa_column=Column(JSON),
        description="截图URL数组"
    )

    # Status management
    status: str = Field(
        default="PENDING",
        max_length=20,
        nullable=False,
        index=True,
        description="状态：PENDING/IN_PROGRESS/RESOLVED/CLOSED"
    )
    priority: str = Field(
        default="MEDIUM",
        max_length=20,
        nullable=False,
        index=True,
        description="优先级：LOW/MEDIUM/HIGH/URGENT"
    )

    # Timestamps
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
    resolved_at: Optional[datetime] = Field(
        default=None,
        description="解决时间"
    )

    class Config:
        """SQLModel configuration"""
        from_attributes = True


class FeedbackReply(SQLModel, table=True):
    """
    Feedback reply database model

    Attributes:
        id: Primary key
        feedback_id: Foreign key to feedbacks table
        user_id: Foreign key to users table (reply author)
        content: Reply content
        is_internal: Whether this is an internal note (admin only)
        created_at: Creation timestamp
    """
    __tablename__ = "feedback_replies"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Foreign keys
    feedback_id: int = Field(
        foreign_key="feedbacks.id",
        nullable=False,
        index=True,
        description="反馈ID"
    )
    user_id: int = Field(
        foreign_key="users.id",
        nullable=False,
        index=True,
        description="回复用户ID"
    )

    # Reply content
    content: str = Field(
        nullable=False,
        description="回复内容"
    )
    is_internal: bool = Field(
        default=False,
        nullable=False,
        description="是否为内部备注（仅管理员可见）"
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="创建时间"
    )

    class Config:
        """SQLModel configuration"""
        from_attributes = True
