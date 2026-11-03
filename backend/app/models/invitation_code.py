"""
Invitation code model
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel


class InvitationCode(SQLModel, table=True):
    __tablename__ = "invitation_codes"

    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(max_length=32, unique=True, index=True)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    used_by: Optional[int] = Field(default=None, foreign_key="users.id")
    max_uses: int = Field(default=1)
    use_count: int = Field(default=0)
    note: Optional[str] = Field(default=None, max_length=200)
    assigned_email: Optional[str] = Field(default=None, max_length=120, description="指定邮箱（申请获得的码仅限此邮箱使用）")
    is_active: bool = Field(default=True)
    expires_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    used_at: Optional[datetime] = Field(default=None)
