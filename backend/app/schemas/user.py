"""
User schemas for API requests and responses
"""
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.config import settings


def _make_avatar_url_absolute(url: Optional[str]) -> Optional[str]:
    """Convert relative avatar path to absolute URL using SERVER_BASE_URL"""
    if not url:
        return url
    if url.startswith("/") and settings.SERVER_BASE_URL:
        return f"{settings.SERVER_BASE_URL.rstrip('/')}{url}"
    return url


class UserBase(BaseModel):
    """Base user schema with common fields"""
    username: str = Field(min_length=3, max_length=80, description="用户名")
    email: EmailStr = Field(description="邮箱地址")
    nickname: Optional[str] = Field(default=None, max_length=100, description="用户昵称")
    company: Optional[str] = Field(default=None, max_length=200, description="企业名称")
    real_name: Optional[str] = Field(default=None, max_length=100, description="真实姓名")


class UserCreate(UserBase):
    """Schema for creating a new user"""
    password: Optional[str] = Field(
        default=None,
        min_length=6,
        max_length=50,
        description="密码（LDAP用户可选）"
    )
    auth_type: str = Field(default="EMAIL", pattern="^(LDAP|EMAIL)$", description="认证方式")
    role: str = Field(default="user", pattern="^(admin|user)$", description="角色")

    @field_validator("auth_type")
    @classmethod
    def validate_auth_type(cls, v: str) -> str:
        """Validate auth_type is uppercase"""
        return v.upper()


class UserUpdate(BaseModel):
    """Schema for updating user information"""
    nickname: Optional[str] = Field(default=None, max_length=100, description="用户昵称")
    email: Optional[EmailStr] = Field(default=None, description="邮箱地址")
    avatar_url: Optional[str] = Field(default=None, max_length=500, description="头像URL")
    role: Optional[str] = Field(default=None, pattern="^(admin|user)$", description="角色")
    company: Optional[str] = Field(default=None, max_length=200, description="企业名称")
    real_name: Optional[str] = Field(default=None, max_length=100, description="真实姓名")
    max_sessions: Optional[int] = Field(default=None, ge=1, le=10, description="最大同时登录设备数（仅管理员可改）")


class UserUpdateStatus(BaseModel):
    """Schema for updating user status"""
    is_active: bool = Field(description="启用状态")


class AccountDeleteRequest(BaseModel):
    """Schema for self-service account deletion"""
    code: str = Field(min_length=4, max_length=10, description="邮箱验证码")


class UserResponse(BaseModel):
    """Schema for user response"""
    id: int = Field(description="用户ID")
    username: str = Field(description="用户名")
    nickname: Optional[str] = Field(default=None, description="用户昵称")
    company: Optional[str] = Field(default=None, description="企业名称")
    real_name: Optional[str] = Field(default=None, description="真实姓名")
    email: str = Field(description="邮箱地址")
    auth_type: str = Field(description="认证方式")
    avatar_url: Optional[str] = Field(default=None, description="头像URL")
    role: str = Field(description="角色")
    is_active: bool = Field(description="启用状态")
    max_sessions: int = Field(default=1, description="最大同时登录设备数")
    last_login_at: Optional[datetime] = Field(default=None, description="最近登录时间")
    last_active_at: Optional[datetime] = Field(default=None, description="最近活跃时间")
    watermark_consent_at: Optional[datetime] = Field(default=None, description="水印免责同意时间")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    @field_validator("avatar_url", mode="after")
    @classmethod
    def resolve_avatar_url(cls, v: Optional[str]) -> Optional[str]:
        return _make_avatar_url_absolute(v)

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class UserGroupInfo(BaseModel):
    """Schema for user's group info in list"""
    id: int
    name: str
    group_type: str


class UserListItem(BaseModel):
    """Schema for user list item (simplified)"""
    id: int
    username: str
    nickname: Optional[str] = None
    company: Optional[str] = None
    real_name: Optional[str] = None
    email: str
    role: str
    is_active: bool
    max_sessions: int = 1
    auth_type: str
    avatar_url: Optional[str] = None
    created_at: datetime
    last_login_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None
    watermark_consent_at: Optional[datetime] = None
    groups: list[UserGroupInfo] = []

    @field_validator("avatar_url", mode="after")
    @classmethod
    def resolve_avatar_url(cls, v: Optional[str]) -> Optional[str]:
        return _make_avatar_url_absolute(v)

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }
