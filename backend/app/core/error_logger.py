"""
Error request logging utility for AI proxy services

Uses a single JSONL file with RotatingFileHandler instead of
creating individual JSON files per error, to avoid file descriptor
exhaustion under high concurrency.
"""
import json
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime
from logging.handlers import RotatingFileHandler
from structlog import get_logger

from app.core.config import settings

logger = get_logger(__name__)

# Dedicated logger for error request logs (JSONL format with rotation)
_erreq_logger = logging.getLogger("erreq")
_erreq_logger.setLevel(logging.INFO)
_erreq_logger.propagate = False

if not _erreq_logger.handlers:
    log_dir = Path(settings.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "erreq.jsonl",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    _erreq_logger.addHandler(handler)


def _summarize_payload(payload: dict) -> dict:
    """Extract key fields from request payload, skipping large content like messages."""
    if not isinstance(payload, dict):
        return {"raw": str(payload)[:500]}
    summary = {}
    # Preserve small scalar/config fields
    for key in ("model", "max_tokens", "temperature", "top_p", "stream",
                "chatId", "responseChatItemId", "variables"):
        if key in payload:
            summary[key] = payload[key]
    # For messages, only record count and first user message preview
    messages = payload.get("messages")
    if isinstance(messages, list):
        summary["message_count"] = len(messages)
        payload_size = len(json.dumps(payload, ensure_ascii=False))
        summary["payload_bytes"] = payload_size
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                    content = " ".join(texts)
                if isinstance(content, str) and content:
                    summary["first_user_message"] = content[:200]
                break
    # Include any unknown top-level keys as names only
    known = {"model", "max_tokens", "temperature", "top_p", "stream",
             "chatId", "responseChatItemId", "variables", "messages", "tools"}
    extra_keys = [k for k in payload if k not in known]
    if extra_keys:
        summary["other_keys"] = extra_keys
    return summary


def save_error_request_log(
    request_payload: dict,
    response_status: int,
    response_body: str,
    error_type: str,
    user_id: Optional[int] = None,
    extra_info: Optional[dict] = None,
) -> None:
    """
    Save error request details as a JSONL line to logs/erreq.jsonl.

    Args:
        request_payload: The request payload sent to upstream API
        response_status: HTTP status code from upstream API
        response_body: Response body from upstream API
        error_type: Type of error (e.g., "ai_proxy", "fastgpt")
        user_id: User ID if available
        extra_info: Additional information to include
    """
    try:
        # Only log key summary instead of the full request payload
        payload_summary = _summarize_payload(request_payload)
        log_content = {
            "timestamp": datetime.now().isoformat(),
            "error_type": error_type,
            "user_id": user_id,
            "response_status": response_status,
            "response_body": response_body[:2000] if isinstance(response_body, str) else response_body,
            "request_summary": payload_summary,
            "extra": extra_info,
        }
        _erreq_logger.info(json.dumps(log_content, ensure_ascii=False))
    except Exception as e:
        logger.error("Failed to save error request log", error=str(e))
