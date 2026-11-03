"""
Invitation application email verification model
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel


class InvitationApplicationVerification(SQLModel, table=True):
    __tablename__ = "invitation_application_verifications"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(max_length=120, index=True)
    code: str = Field(max_length=10, index=True)
    expires_at: datetime
    used: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
