"""
网关错误请求日志（DB 表，替代 logs/erreq.jsonl 便于后台查询）
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import Text


class ErrorRequestLog(SQLModel, table=True):
    """一次失败的上游/网关请求记录。"""
    __tablename__ = "error_request_logs"

    id: Optional[int] = Field(default=None, primary_key=True)

    request_id: Optional[str] = Field(
        default=None, max_length=64, index=True,
        description="请求ID(req_xxx)，与 ai_requests.request_id 同源，用于全链路排查",
    )
    user_id: Optional[int] = Field(default=None, index=True, description="用户ID")
    error_type: str = Field(
        max_length=50,
        nullable=False,
        index=True,
        description="错误来源: gateway_messages / gateway_chat / gateway_responses / ...",
    )
    model: Optional[str] = Field(default=None, max_length=100, index=True)
    response_status: int = Field(default=0, index=True, description="上游/网关返回状态码")
    response_body: Optional[str] = Field(
        default=None,
        sa_column=Column(Text),
        description="上游响应体（截断）",
    )
    request_summary: Optional[str] = Field(
        default=None,
        sa_column=Column(Text),
        description="请求摘要（关键字段，跳过 messages 正文）",
    )
    extra: Optional[str] = Field(
        default=None,
        sa_column=Column(Text),
        description="附加信息 JSON 字符串",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )

    class Config:
        from_attributes = True
