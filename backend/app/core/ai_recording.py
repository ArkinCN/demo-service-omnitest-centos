"""
AI 请求记录 — 公共记账工具（旧 cost_cents 体系）。

历史上这两个函数定义在 ai_proxy.py，被 claude_proxy / gpt_proxy / vibe_coding 复用。
为了让旧 proxy（ai_proxy/claude_proxy）能被删除而不牵连仍保留的 gpt_proxy/vibe_coding，
把它们抽到此中立模块。

注意：这是旧 cost_cents 计费（calculate_cost），不扣 credits。统一网关 gateway.py
走的是新 credits 体系（GatewayService.record_and_charge）。本模块仅供尚未迁移到网关
的保留端点（gpt_proxy 的 Responses、vibe_coding）使用。
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import Request
from sqlmodel import Session
from structlog import get_logger

from app.db.session import engine
from app.models.ai_request import AIRequest
from app.core.ai_pricing import calculate_cost

logger = get_logger(__name__)


def get_client_ip(request: Request) -> str:
    """Get client IP address"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def record_ai_request(
    user_id: int,
    module_name: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    success: bool = True,
    error_message: Optional[str] = None,
    ip_address: Optional[str] = None,
    request_id: Optional[str] = None,
):
    """Record AI request to database"""
    try:
        with Session(engine) as session:
            request = AIRequest(
                user_id=user_id,
                module_name=module_name,
                model=model,
                request_id=request_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                cost_cents=calculate_cost(model, prompt_tokens, completion_tokens),
                success=success,
                error_message=error_message,
                ip_address=ip_address,
                created_at=datetime.now(timezone.utc),
            )
            session.add(request)
            session.commit()
    except Exception as e:
        logger.error("Failed to record AI request", error=str(e))
