"""
Invitation schemas for API requests and responses
"""
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class InvitationCodeCreate(BaseModel):
    count: int = Field(default=1, ge=1, le=100, description="批量生成数量")
    max_uses: int = Field(default=1, ge=1, description="最大使用次数")
    note: Optional[str] = Field(default=None, max_length=200, description="备注")
    expires_days: Optional[int] = Field(default=None, ge=1, description="过期天数")


class InvitationCodeResponse(BaseModel):
    id: int
    code: str
    max_uses: int
    use_count: int
    is_active: bool
    note: Optional[str] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    used_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }


class InvitationApplicationSendCode(BaseModel):
    email: EmailStr = Field(description="邮箱地址")


class InvitationApplicationCreate(BaseModel):
    email: EmailStr = Field(description="邮箱地址")
    code: str = Field(min_length=4, max_length=10, description="邮箱验证码")
    name: Optional[str] = Field(default=None, max_length=100, description="姓名")
    company: Optional[str] = Field(default=None, max_length=200, description="企业名称")
    reason: Optional[str] = Field(default=None, max_length=500, description="申请理由")
    sales_email: Optional[EmailStr] = Field(default=None, description="业务员归属邮箱")


class InvitationApplicationReview(BaseModel):
    status: str = Field(pattern="^(APPROVED|REJECTED)$", description="审核结果")


class InvitationApplicationResponse(BaseModel):
    id: int
    email: str
    name: Optional[str] = None
    company: Optional[str] = None
    reason: Optional[str] = None
    sales_email: Optional[str] = None
    status: str
    reviewed_by: Optional[int] = None
    invitation_code_id: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.replace(tzinfo=timezone.utc).isoformat() if v and v.tzinfo is None else (v.isoformat() if v else None)
        }
