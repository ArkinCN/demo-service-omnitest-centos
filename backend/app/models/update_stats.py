"""
Update statistics model for tracking download and installation metrics
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import Text


class UpdateStats(SQLModel, table=True):
    """
    Update statistics database model

    Tracks user actions during the update process for analytics and debugging.

    Attributes:
        id: Primary key
        version_id: Foreign key to app_versions table
        user_id: Foreign key to users table (optional for anonymous tracking)
        action: Action type (check/download/install/complete/error)
        client_version: Client's current version before update
        platform: Client platform
        ip_address: Client IP address (for geolocation analysis)
        user_agent: User agent string (for debugging)
        error_message: Error message if action = 'error'
        created_at: Action timestamp
    """
    __tablename__ = "update_stats"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Foreign keys
    version_id: int = Field(
        foreign_key="app_versions.id",
        index=True,
        nullable=False,
        description="版本ID"
    )
    user_id: Optional[int] = Field(
        default=None,
        foreign_key="users.id",
        index=True,
        description="用户ID (可选, 用于关联用户)"
    )

    # Action information
    action: str = Field(
        max_length=20,
        index=True,
        nullable=False,
        description="操作类型: check/download/install/complete/error"
    )
    client_version: str = Field(
        max_length=50,
        nullable=False,
        description="客户端当前版本"
    )
    platform: str = Field(
        max_length=20,
        index=True,
        nullable=False,
        description="平台: windows/macos/linux"
    )

    # Metadata
    ip_address: Optional[str] = Field(
        default=None,
        max_length=45,
        description="客户端IP地址"
    )
    user_agent: Optional[str] = Field(
        default=None,
        max_length=500,
        description="User Agent字符串"
    )
    error_message: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="错误信息 (仅action=error时)"
    )

    # Timestamp
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        index=True,
        description="操作时间"
    )

    class Config:
        """SQLModel configuration"""
        from_attributes = True


class UpdateStatsHelper:
    """Helper class for update statistics operations"""

    # Action constants
    ACTION_CHECK = "check"
    ACTION_DOWNLOAD = "download"
    ACTION_INSTALL = "install"
    ACTION_COMPLETE = "complete"
    ACTION_ERROR = "error"

    @staticmethod
    def create_check_stat(
        version_id: int,
        client_version: str,
        platform: str,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> UpdateStats:
        """Create a 'check' action statistic"""
        return UpdateStats(
            version_id=version_id,
            user_id=user_id,
            action=UpdateStatsHelper.ACTION_CHECK,
            client_version=client_version,
            platform=platform,
            ip_address=ip_address,
            user_agent=user_agent
        )

    @staticmethod
    def create_download_stat(
        version_id: int,
        client_version: str,
        platform: str,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> UpdateStats:
        """Create a 'download' action statistic"""
        return UpdateStats(
            version_id=version_id,
            user_id=user_id,
            action=UpdateStatsHelper.ACTION_DOWNLOAD,
            client_version=client_version,
            platform=platform,
            ip_address=ip_address,
            user_agent=user_agent
        )

    @staticmethod
    def create_install_stat(
        version_id: int,
        client_version: str,
        platform: str,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> UpdateStats:
        """Create an 'install' action statistic"""
        return UpdateStats(
            version_id=version_id,
            user_id=user_id,
            action=UpdateStatsHelper.ACTION_INSTALL,
            client_version=client_version,
            platform=platform,
            ip_address=ip_address,
            user_agent=user_agent
        )

    @staticmethod
    def create_complete_stat(
        version_id: int,
        client_version: str,
        platform: str,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> UpdateStats:
        """Create a 'complete' action statistic"""
        return UpdateStats(
            version_id=version_id,
            user_id=user_id,
            action=UpdateStatsHelper.ACTION_COMPLETE,
            client_version=client_version,
            platform=platform,
            ip_address=ip_address,
            user_agent=user_agent
        )

    @staticmethod
    def create_error_stat(
        version_id: int,
        client_version: str,
        platform: str,
        error_message: str,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> UpdateStats:
        """Create an 'error' action statistic"""
        return UpdateStats(
            version_id=version_id,
            user_id=user_id,
            action=UpdateStatsHelper.ACTION_ERROR,
            client_version=client_version,
            platform=platform,
            error_message=error_message,
            ip_address=ip_address,
            user_agent=user_agent
        )
