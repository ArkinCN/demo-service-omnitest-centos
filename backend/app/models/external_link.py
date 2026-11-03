"""
External Link models using SQLModel
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import JSON, Text


class ExternalLink(SQLModel, table=True):
    """
    External Link database model

    Attributes:
        id: Primary key
        title: Link title
        url: Link URL
        description: Link description
        icon_url: Optional icon URL
        category: Link category name
        category_order: Category display order
        link_order: Link display order within category
        maintainer_id: Maintainer user ID
        created_by: Creator user ID
        visibility: Visibility control (ALL/SPECIFIED)
        allowed_group_ids: JSON array of allowed group IDs
        allowed_user_ids: JSON array of allowed user IDs
        period_type: Period type (LONG_TERM/SHORT_TERM)
        start_time: Opening start time
        end_time: Opening end time
        time_pattern: Smart time pattern (e.g., LAST_WEEK_OF_MONTH)
        status: Link status (ACTIVE/INACTIVE/ARCHIVED)
        click_count: Total click count
        last_accessed_at: Last access timestamp
        reminder_config: JSON reminder configuration
        related_todo_ids: JSON array of related TODO IDs
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """
    __tablename__ = "external_links"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Basic information
    title: str = Field(
        max_length=200,
        nullable=False,
        index=True,
        description="链接标题"
    )
    url: str = Field(
        max_length=1000,
        nullable=False,
        description="链接地址"
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="链接描述"
    )
    icon_url: Optional[str] = Field(
        default=None,
        max_length=500,
        description="图标URL"
    )

    # Category and ordering
    category: str = Field(
        max_length=100,
        nullable=False,
        index=True,
        description="分类名称"
    )
    category_order: int = Field(
        default=0,
        nullable=False,
        index=True,
        description="分类排序"
    )
    link_order: int = Field(
        default=0,
        nullable=False,
        index=True,
        description="链接在分类内的排序"
    )

    # Maintainer and creator
    maintainer_id: Optional[int] = Field(
        default=None,
        foreign_key="users.id",
        index=True,
        description="维护人ID"
    )
    created_by: int = Field(
        foreign_key="users.id",
        nullable=False,
        index=True,
        description="创建人ID"
    )

    # Permission control
    visibility: str = Field(
        default="ALL",
        max_length=20,
        nullable=False,
        index=True,
        description="可见性：ALL(全员)/SPECIFIED(指定人员)"
    )
    allowed_group_ids: str = Field(
        default="[]",
        sa_column=Column(JSON),
        description="允许访问的分组ID数组"
    )
    allowed_user_ids: str = Field(
        default="[]",
        sa_column=Column(JSON),
        description="允许访问的用户ID数组"
    )

    # Time management
    period_type: str = Field(
        default="LONG_TERM",
        max_length=20,
        nullable=False,
        index=True,
        description="开放周期：LONG_TERM(长期)/SHORT_TERM(短期)"
    )
    start_time: Optional[datetime] = Field(
        default=None,
        description="开放开始时间"
    )
    end_time: Optional[datetime] = Field(
        default=None,
        description="开放结束时间"
    )
    time_pattern: Optional[str] = Field(
        default=None,
        max_length=100,
        description="智能时间模式：LAST_WEEK_OF_MONTH/FIRST_WEEK_OF_MONTH/等"
    )

    # Tags
    tags: str = Field(
        default="[]",
        sa_column=Column(JSON),
        description="标签（JSON数组）"
    )

    # Status and statistics
    status: str = Field(
        default="ACTIVE",
        max_length=20,
        nullable=False,
        index=True,
        description="状态：ACTIVE(启用)/INACTIVE(停用)/ARCHIVED(归档)"
    )
    click_count: int = Field(
        default=0,
        nullable=False,
        description="总点击次数"
    )
    last_accessed_at: Optional[datetime] = Field(
        default=None,
        description="最近访问时间"
    )

    # Reserved fields for future features
    reminder_config: str = Field(
        default="{}",
        sa_column=Column(JSON),
        description="提醒配置JSON"
    )
    related_todo_ids: str = Field(
        default="[]",
        sa_column=Column(JSON),
        description="关联的待办事项ID数组"
    )
    related_links_url: str = Field(
        default="[]",
        sa_column=Column(JSON),
        description="关联链接（JSON数组，每项包含name和url）"
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


class ExternalLinkClick(SQLModel, table=True):
    """
    External Link click tracking model

    Attributes:
        id: Primary key
        link_id: Foreign key to external_links table
        user_id: Foreign key to users table
        clicked_at: Click timestamp
        user_agent: Optional browser user agent
    """
    __tablename__ = "external_link_clicks"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Foreign keys
    link_id: int = Field(
        foreign_key="external_links.id",
        nullable=False,
        index=True,
        description="外链ID"
    )
    user_id: int = Field(
        foreign_key="users.id",
        nullable=False,
        index=True,
        description="点击用户ID"
    )

    # Click info
    clicked_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
        description="点击时间"
    )
    user_agent: Optional[str] = Field(
        default=None,
        max_length=500,
        description="浏览器User-Agent"
    )

    class Config:
        """SQLModel configuration"""
        from_attributes = True


class UserFavoriteFolder(SQLModel, table=True):
    """
    User favorite folder model for organizing saved links

    Attributes:
        id: Primary key
        user_id: Owner user ID
        name: Folder name
        description: Optional folder description
        sort_order: Display order
        is_default: Whether this is the default folder
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """
    __tablename__ = "user_favorite_folders"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Owner
    user_id: int = Field(
        foreign_key="users.id",
        nullable=False,
        index=True,
        description="所属用户ID"
    )

    # Folder info
    name: str = Field(
        max_length=100,
        nullable=False,
        description="收藏夹名称"
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="收藏夹描述"
    )
    sort_order: int = Field(
        default=0,
        nullable=False,
        description="排序顺序"
    )
    is_default: bool = Field(
        default=False,
        nullable=False,
        description="是否为默认收藏夹"
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


class UserLinkFavorite(SQLModel, table=True):
    """
    User link favorite model for tracking saved links

    Attributes:
        id: Primary key
        user_id: User who favorited the link
        link_id: The favorited link
        folder_id: Optional folder (NULL means uncategorized/default)
        created_at: When the link was favorited
    """
    __tablename__ = "user_link_favorites"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # References
    user_id: int = Field(
        foreign_key="users.id",
        nullable=False,
        index=True,
        description="用户ID"
    )
    link_id: int = Field(
        foreign_key="external_links.id",
        nullable=False,
        index=True,
        description="外链ID"
    )
    folder_id: Optional[int] = Field(
        default=None,
        foreign_key="user_favorite_folders.id",
        index=True,
        description="收藏夹ID (NULL表示未分类)"
    )

    # Timestamp
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="收藏时间"
    )

    class Config:
        """SQLModel configuration"""
        from_attributes = True
