"""
Invitation application model
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel


class InvitationApplication(SQLModel, table=True):
    __tablename__ = "invitation_applications"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(max_length=120, index=True)
    name: Optional[str] = Field(default=None, max_length=100)
    company: Optional[str] = Field(default=None, max_length=200)  # 企业名称
    reason: Optional[str] = Field(default=None, max_length=500)
    sales_email: Optional[str] = Field(default=None, max_length=120)  # 业务员归属邮箱
    status: str = Field(default="PENDING")  # PENDING | APPROVED | REJECTED
    reviewed_by: Optional[int] = Field(default=None, foreign_key="users.id")
    invitation_code_id: Optional[int] = Field(default=None, foreign_key="invitation_codes.id")
    reviewed_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
