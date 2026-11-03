"""
Authentication schemas for API requests and responses
"""
from typing import Optional
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Schema for login request"""
    username: str = Field(min_length=1, description="用户名或邮箱")
    password: str = Field(min_length=1, description="密码")
    auth_type: Optional[str] = Field(
        default=None,
        pattern="^(LDAP|EMAIL)$",
        description="认证方式（可选，自动识别）"
    )


class TokenResponse(BaseModel):
    """Schema for token response"""
    access_token: str = Field(description="访问令牌")
    refresh_token: str = Field(description="刷新令牌")
    token_type: str = Field(default="Bearer", description="令牌类型")


class RefreshTokenRequest(BaseModel):
    """Schema for refresh token request"""
    refresh_token: str = Field(description="刷新令牌")


class RefreshTokenResponse(BaseModel):
    """Schema for refresh token response"""
    access_token: str = Field(description="新的访问令牌")
    token_type: str = Field(default="Bearer", description="令牌类型")


class TokenPayload(BaseModel):
    """Schema for JWT token payload"""
    user_id: int = Field(description="用户ID")
    username: str = Field(description="用户名")
    role: str = Field(description="角色")
    is_active: bool = Field(description="启用状态")
    exp: Optional[int] = Field(default=None, description="过期时间戳")
    type: str = Field(description="令牌类型: access 或 refresh")


class LoginResponse(BaseModel):
    """Schema for login response"""
    user: dict = Field(description="用户信息")
    tokens: TokenResponse = Field(description="令牌信息")

    class Config:
        from_attributes = True
