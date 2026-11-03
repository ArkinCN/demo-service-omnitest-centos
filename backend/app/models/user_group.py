"""
User Group models using SQLModel
"""
from datetime import datetime, timezone
from typing import Optional, List, TYPE_CHECKING
from sqlmodel import Field, SQLModel, Relationship

if TYPE_CHECKING:
    from app.models.user import User


class UserGroup(SQLModel, table=True):
    """
    User Group database model

    Supports two types of groups:
    - CUSTOM: Manually created and managed groups
    - LDAP: Auto-synced groups based on LDAP OU hierarchy

    Attributes:
        id: Primary key
        name: Group name
        description: Group description
        parent_id: Parent group ID (for hierarchy)
        group_type: Group type (CUSTOM or LDAP)
        ldap_dn: LDAP DN for LDAP groups (e.g., ou=标准化部,ou=应用中心,...)
        is_active: Group enabled status
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """
    __tablename__ = "user_groups"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Basic information
    name: str = Field(
        max_length=100,
        nullable=False,
        index=True,
        description="分组名称"
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="分组描述"
    )

    # Hierarchy
    parent_id: Optional[int] = Field(
        default=None,
        foreign_key="user_groups.id",
        index=True,
        description="父分组ID"
    )

    # Group type
    group_type: str = Field(
        default="CUSTOM",
        max_length=20,
        nullable=False,
        index=True,
        description="分组类型：CUSTOM/LDAP"
    )

    # LDAP specific
    ldap_dn: Optional[str] = Field(
        default=None,
        max_length=500,
        unique=True,
        description="LDAP DN（LDAP分组专用）"
    )

    # Status
    is_active: bool = Field(
        default=True,
        nullable=False,
        description="启用状态"
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="创建时间"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="更新时间"
    )

    # Relationships
    children: List["UserGroup"] = Relationship(
        back_populates="parent",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    parent: Optional["UserGroup"] = Relationship(
        back_populates="children",
        sa_relationship_kwargs={"remote_side": "UserGroup.id"}
    )
    members: List["UserGroupMember"] = Relationship(
        back_populates="group",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    @property
    def is_ldap_group(self) -> bool:
        """Check if this is an LDAP group"""
        return self.group_type == "LDAP"

    @property
    def is_custom_group(self) -> bool:
        """Check if this is a custom group"""
        return self.group_type == "CUSTOM"

    class Config:
        """SQLModel configuration"""
        from_attributes = True


class UserGroupMember(SQLModel, table=True):
    """
    User-Group membership model (many-to-many relationship)

    Attributes:
        id: Primary key
        user_id: User ID
        group_id: Group ID
        source: How the membership was created (MANUAL or LDAP)
        created_at: Membership creation timestamp
    """
    __tablename__ = "user_group_members"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Foreign keys
    user_id: int = Field(
        foreign_key="users.id",
        nullable=False,
        index=True,
        description="用户ID"
    )
    group_id: int = Field(
        foreign_key="user_groups.id",
        nullable=False,
        index=True,
        description="分组ID"
    )

    # Source of membership
    source: str = Field(
        default="MANUAL",
        max_length=20,
        nullable=False,
        description="成员来源：MANUAL/LDAP"
    )

    # Timestamp
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="加入时间"
    )

    # Relationships
    group: Optional[UserGroup] = Relationship(back_populates="members")

    class Config:
        """SQLModel configuration"""
        from_attributes = True
        # Unique constraint on (user_id, group_id) - handled in migration script
