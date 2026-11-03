"""
User model using SQLModel
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel
from app.core.security import get_password_hash, verify_password


class User(SQLModel, table=True):
    """
    User database model

    Attributes:
        id: Primary key
        username: Unique username
        nickname: Display name
        email: Unique email address
        auth_type: Authentication type (LDAP or EMAIL)
        password_hash: Hashed password (null for LDAP users)
        avatar_url: Profile picture URL
        role: User role (admin or user)
        is_active: Account enabled status
        last_login_at: Last login timestamp
        created_at: Account creation timestamp
        updated_at: Last update timestamp
    """
    __tablename__ = "users"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Basic information
    username: str = Field(
        max_length=80,
        unique=True,
        index=True,
        nullable=False,
        description="用户名"
    )
    nickname: Optional[str] = Field(default=None, max_length=100, description="用户昵称")
    company: Optional[str] = Field(default=None, max_length=200, description="企业名称")
    real_name: Optional[str] = Field(default=None, max_length=100, description="真实姓名")
    email: str = Field(
        max_length=120,
        unique=True,
        index=True,
        nullable=False,
        description="邮箱"
    )

    # Authentication
    auth_type: str = Field(
        default="LDAP",
        max_length=20,
        nullable=False,
        description="认证方式：LDAP/EMAIL"
    )
    password_hash: Optional[str] = Field(
        default=None,
        max_length=255,
        description="密码哈希（LDAP用户为空）"
    )

    # Email verification
    email_verified: bool = Field(default=False, nullable=False, description="邮箱是否已验证")

    # Session control
    token_version: int = Field(default=0, nullable=False, description="Token版本号，登录时自增，用于登录设备数限制")
    max_sessions: int = Field(default=1, nullable=False, description="最大同时登录设备数，1=单设备（默认），管理员可为指定用户调大")

    # User attributes
    avatar_url: Optional[str] = Field(default=None, max_length=500, description="头像URL")
    role: str = Field(default="user", max_length=20, nullable=False, description="角色：admin/user")
    is_active: bool = Field(default=True, nullable=False, description="启用状态")

    # LDAP specific
    ldap_dn: Optional[str] = Field(
        default=None,
        max_length=500,
        description="LDAP用户完整DN"
    )

    # Consent
    watermark_consent_at: Optional[datetime] = Field(default=None, description="水印免责同意时间（为空表示未同意）")

    # Soft delete (self-service account deletion)
    deleted_at: Optional[datetime] = Field(default=None, index=True, description="注销时间（非空表示账号已注销）")

    # Timestamps
    last_login_at: Optional[datetime] = Field(default=None, description="最近登录时间")
    last_active_at: Optional[datetime] = Field(default=None, description="最近活跃时间（WebSocket心跳更新）")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="创建时间")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="更新时间")

    def set_password(self, password: str) -> None:
        """Set password hash from plain password"""
        self.password_hash = get_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verify password against hash"""
        if not self.password_hash:
            return False
        return verify_password(password, self.password_hash)

    def update_last_login(self) -> None:
        """Update last login timestamp"""
        self.last_login_at = datetime.now(timezone.utc)

    @property
    def is_admin(self) -> bool:
        """Check if user is admin"""
        return self.role == "admin"

    def effective_max_sessions(self) -> int:
        """最大同时登录设备数下限保护：脏数据（0/None/负数）一律按单设备处理"""
        return max(self.max_sessions or 1, 1)

    def is_token_version_valid(self, token_version: Optional[int]) -> bool:
        """
        版本窗口判据：最近 max_sessions 次登录签发的 token 有效，
        第 N+1 次登录自动使最旧的 token 失效（单设备即 N=1，与旧 != 判据等价）。
        token 未携带版本号时放行（兼容存量旧 token）。
        """
        if token_version is None:
            return True
        return self.token_version - token_version < self.effective_max_sessions()

    class Config:
        """SQLModel configuration"""
        from_attributes = True
