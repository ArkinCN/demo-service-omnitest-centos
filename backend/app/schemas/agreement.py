"""
Agreement schemas for API requests and responses
"""
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field


class AgreementCreate(BaseModel):
    """Schema for creating a new agreement draft"""
    type: Literal["terms_of_service", "privacy_policy"] = Field(
        description="协议类型"
    )
    version: str = Field(
        min_length=1,
        max_length=20,
        description="版本号"
    )
    title: str = Field(
        min_length=1,
        max_length=200,
        description="协议标题"
    )
    content: str = Field(
        min_length=1,
        description="协议内容 (Markdown)"
    )


class AgreementUpdate(BaseModel):
    """Schema for updating an unpublished agreement draft"""
    title: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="协议标题"
    )
    content: Optional[str] = Field(
        default=None,
        min_length=1,
        description="协议内容"
    )


class AgreementResponse(BaseModel):
    """Full agreement response (admin)"""
    id: int
    type: str
    version: str
    title: str
    content: str
    is_published: bool
    created_by: Optional[int] = None
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AgreementPublicResponse(BaseModel):
    """Public agreement response (for login page and acceptance dialog)"""
    id: int
    type: str
    version: str
    title: str
    content: str
    published_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AcceptanceCheckResponse(BaseModel):
    """Response for agreement acceptance check"""
    needs_acceptance: bool
    is_first_time: bool = Field(description="用户是否从未接受过任何协议")
    pending_agreements: list[AgreementPublicResponse]


class AgreementAcceptRequest(BaseModel):
    """Request to accept agreements"""
    agreement_ids: list[int] = Field(
        min_length=1,
        description="要接受的协议ID列表"
    )
