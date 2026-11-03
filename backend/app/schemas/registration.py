"""
Registration schemas for API requests and responses
"""
import re
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    username: str = Field(min_length=5, max_length=20, description="用户名")

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        # 以中英文或数字开头
        if not re.match(r'^[\u4e00-\u9fa5a-zA-Z0-9]', v):
            raise ValueError("用户名必须以中英文或数字开头")
        # 只允许中英文、数字、-、_、#
        if not re.match(r'^[\u4e00-\u9fa5a-zA-Z0-9\-_#]+$', v):
            raise ValueError("用户名只支持中英文、数字、-、_、#")
        # 至少包含一个中英文字符
        if not re.search(r'[\u4e00-\u9fa5a-zA-Z]', v):
            raise ValueError("用户名至少需要包含一个中英文字符")
        return v
    email: EmailStr = Field(description="邮箱地址")
    password: str = Field(min_length=6, max_length=50, description="密码")
    invitation_code: Optional[str] = Field(default=None, description="内测码")
    company: Optional[str] = Field(default=None, max_length=200, description="企业名称")
    real_name: Optional[str] = Field(default=None, max_length=100, description="真实姓名")


class VerifyEmailRequest(BaseModel):
    email: EmailStr = Field(description="邮箱地址")
    code: str = Field(min_length=6, max_length=6, description="6位验证码")


class ResendVerificationRequest(BaseModel):
    email: EmailStr = Field(description="邮箱地址")


class ForgotPasswordRequest(BaseModel):
    email: EmailStr = Field(description="邮箱地址")


class ResetPasswordRequest(BaseModel):
    email: EmailStr = Field(description="邮箱地址")
    code: str = Field(min_length=6, max_length=6, description="6位验证码")
    new_password: str = Field(min_length=6, max_length=50, description="新密码")
