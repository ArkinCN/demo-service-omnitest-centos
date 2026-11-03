"""
AI Request Model - Track AI API usage for statistics
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import Text


class AIRequest(SQLModel, table=True):
    """
    AI request tracking table.

    Stores all AI API requests for usage statistics and cost tracking.
    Can be joined with user_group_members for group-level statistics.
    """
    __tablename__ = "ai_requests"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    request_id: Optional[str] = Field(
        default=None, max_length=64, index=True,
        description="请求ID(req_xxx)，与 error_request_logs.request_id 同源，全链路排查用",
    )

    # User info
    user_id: int = Field(
        foreign_key="users.id",
        nullable=False,
        index=True,
        description="User ID"
    )

    # Request info
    module_name: str = Field(
        max_length=50,
        nullable=False,
        index=True,
        description="Module name (ai_chat, ai_chat_title, code_review, translator, etc.)"
    )
    model: str = Field(
        max_length=100,
        nullable=False,
        index=True,
        description="Model name (gpt-5.2, deepseek-v3-2-251201, etc.)"
    )

    # Token usage
    prompt_tokens: int = Field(
        default=0,
        description="Input tokens"
    )
    completion_tokens: int = Field(
        default=0,
        description="Output tokens"
    )
    total_tokens: int = Field(
        default=0,
        description="Total tokens"
    )
    cache_read_tokens: int = Field(
        default=0,
        description="Cache read tokens"
    )
    cache_creation_tokens: int = Field(
        default=0,
        description="Cache creation tokens"
    )

    # Cost (unit: 0.0001 CNY, i.e. 10000 = ¥1.00)
    cost_cents: int = Field(
        default=0,
        description="Cost in 0.0001 CNY units"
    )

    # Request status
    success: bool = Field(
        default=True,
        index=True,
        description="Whether request succeeded"
    )
    error_message: Optional[str] = Field(
        default=None,
        sa_column=Column(Text),
        description="Error message if failed"
    )

    # Metadata
    ip_address: Optional[str] = Field(
        default=None,
        max_length=45,
        description="Client IP address"
    )

    # Timestamp
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        index=True,
        description="Request time"
    )

    class Config:
        from_attributes = True
