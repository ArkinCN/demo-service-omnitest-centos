"""
Application version model for update management system
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import Text, JSON


class AppVersion(SQLModel, table=True):
    """
    Application version database model

    Attributes:
        id: Primary key
        version: Version string (e.g., "1.0.0")
        version_code: Integer version code for comparison (e.g., 10000 for 1.0.0)
        title: Version title/name
        channel: Release channel (stable/beta/alpha)
        platform: Target platform (windows/macos/linux)

        file_path: Relative path to update file
        file_size: File size in bytes
        file_hash: SHA256 hash of the file
        signature: Tauri updater signature content

        is_forced: Whether this is a forced update
        min_version: Minimum compatible version string
        rollout_percentage: Gradual rollout percentage (0-100)

        published_by: User ID who published this version
        published_at: Publication timestamp
        is_active: Whether this version is active

        created_at: Record creation timestamp
        updated_at: Last update timestamp
    """
    __tablename__ = "app_versions"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Version information
    version: str = Field(
        max_length=50,
        unique=True,
        index=True,
        nullable=False,
        description="版本号 (如 1.0.0)"
    )
    version_code: int = Field(
        index=True,
        nullable=False,
        description="版本码 (用于比较, 如 10000)"
    )
    title: str = Field(
        max_length=200,
        nullable=False,
        description="版本标题"
    )

    # Release configuration
    channel: str = Field(
        default="stable",
        max_length=20,
        index=True,
        nullable=False,
        description="发布渠道: stable/beta/alpha"
    )
    platform: str = Field(
        default="windows",
        max_length=20,
        index=True,
        nullable=False,
        description="平台: windows/macos/linux"
    )

    # File information
    file_path: str = Field(
        max_length=500,
        nullable=False,
        description="文件相对路径"
    )
    file_size: int = Field(
        nullable=False,
        description="文件大小(字节)"
    )
    file_hash: str = Field(
        max_length=64,
        nullable=False,
        description="文件SHA256哈希"
    )
    signature: str = Field(
        sa_column=Column(Text, nullable=False),
        description="Tauri签名内容"
    )

    # Update strategy
    is_forced: bool = Field(
        default=False,
        index=True,
        nullable=False,
        description="是否强制更新"
    )
    min_version: Optional[str] = Field(
        default=None,
        max_length=50,
        description="最低兼容版本"
    )
    rollout_percentage: int = Field(
        default=100,
        nullable=False,
        description="灰度发布百分比 (0-100)"
    )

    # User whitelist for update
    visibility: str = Field(
        default="ALL",
        max_length=20,
        index=True,
        nullable=False,
        description="可见性：ALL(全员)/SPECIFIED(指定人员)"
    )
    allowed_group_ids: str = Field(
        default="[]",
        sa_column=Column(JSON),
        description="允许更新的分组ID数组"
    )
    allowed_user_ids: str = Field(
        default="[]",
        sa_column=Column(JSON),
        description="允许更新的用户ID数组"
    )

    # Publication information
    published_by: Optional[int] = Field(
        default=None,
        foreign_key="users.id",
        description="发布者用户ID"
    )
    published_at: Optional[datetime] = Field(
        default=None,
        description="发布时间"
    )
    is_active: bool = Field(
        default=True,
        index=True,
        nullable=False,
        description="是否激活"
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

    @staticmethod
    def parse_version_to_code(version: str) -> int:
        """
        Parse version string to integer code for comparison

        Examples:
            "1.0.0" -> 10000
            "1.2.3" -> 10203
            "2.0.0" -> 20000

        Args:
            version: Version string (format: MAJOR.MINOR.PATCH)

        Returns:
            Integer version code
        """
        try:
            parts = version.lstrip('v').split('.')
            major = int(parts[0]) if len(parts) > 0 else 0
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
            return major * 10000 + minor * 100 + patch
        except (ValueError, IndexError):
            return 0

    def is_newer_than(self, other_version: str) -> bool:
        """
        Check if this version is newer than another version

        Args:
            other_version: Version string to compare with

        Returns:
            True if this version is newer
        """
        other_code = self.parse_version_to_code(other_version)
        return self.version_code > other_code

    def is_compatible_with(self, client_version: str) -> bool:
        """
        Check if this version is compatible with a client version

        Args:
            client_version: Client's current version string

        Returns:
            True if compatible
        """
        if not self.min_version:
            return True

        client_code = self.parse_version_to_code(client_version)
        min_code = self.parse_version_to_code(self.min_version)
        return client_code >= min_code

    class Config:
        """SQLModel configuration"""
        from_attributes = True
