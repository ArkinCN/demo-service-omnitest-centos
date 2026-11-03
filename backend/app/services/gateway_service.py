"""
统一网关服务层 — 模型路由、usage 解析、错误记录、扣费协调。

三协议的差异集中在这里：
- 上游路径：anthropic→/v1/messages，openai_chat→/v1/chat/completions，
  openai_responses→/v1/responses。
- 鉴权头：anthropic→x-api-key + anthropic-version；openai_*→Authorization: Bearer。
- usage 字段：anthropic→input_tokens/output_tokens/cache_read_input_tokens；
  openai→prompt_tokens/completion_tokens/prompt_tokens_details.cached_tokens。
"""
import copy
import json
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlmodel import Session, select

from app.models.gateway import GatewayChannel, ModelPricing
from app.models.ai_request import AIRequest
from app.models.error_log import ErrorRequestLog
from app.db.session import engine
from app.core.config import settings
from app.core.logger import logger
from app.services.credits_service import CreditsService


# 协议 → 上游子路径
PROTOCOL_PATHS = {
    "anthropic": "/v1/messages",
    "openai_chat": "/v1/chat/completions",
    "openai_responses": "/v1/responses",
}


# ── 附件多模态转换（从已删除的 streams.py 搬来） ──

def convert_attachments_to_multimodal(messages: list, attachments: list) -> list:
    """将顶级 attachments 转成 OpenAI 多模态消息，嵌入最后一条 user 消息的 content。

    上游不认顶级 attachments 字段；debug-agent crate（hardware_review/pdf 视觉评审）
    把附件作为顶级字段发送，网关在 openai_chat 协议下负责转换。
    """
    if not attachments or not messages:
        return messages

    result = [msg.copy() for msg in messages]

    last_user_idx = None
    for i in range(len(result) - 1, -1, -1):
        if result[i].get("role") == "user":
            last_user_idx = i
            break
    if last_user_idx is None:
        logger.warning("No user message found, cannot attach files")
        return result

    original_content = result[last_user_idx].get("content", "")
    if isinstance(original_content, list):
        text_content = ""
        for part in original_content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_content = part.get("text", "")
                break
    else:
        text_content = original_content

    parts = [{"type": "text", "text": text_content}]
    for att in attachments:
        att_type = att.get("type", "file")
        att_url = att.get("url", "")
        att_key = att.get("key", "")
        att_name = att.get("name", "")
        if att_type == "image":
            part = {"type": "image_url", "image_url": {"url": att_url}}
        else:
            part = {"type": "file_url", "name": att_name, "url": att_url}
        if att_key:
            part["key"] = att_key
        parts.append(part)

    result[last_user_idx]["content"] = parts
    return result


# ── 上下文缓存注入（仅 anthropic，默认开） ──

_EPHEMERAL = {"type": "ephemeral"}


def _mark_block_cache(content):
    """给 content（str 或 list）的末块打 ephemeral 标记，返回归一化后的 list 形式。

    幂等：已带 cache_control 的块不重复打。str 会被转成单个 text 块。
    """
    if isinstance(content, str):
        if not content:
            return content
        return [{"type": "text", "text": content, "cache_control": _EPHEMERAL}]
    if isinstance(content, list) and content:
        last = content[-1]
        if isinstance(last, dict) and "cache_control" not in last:
            last["cache_control"] = _EPHEMERAL
    return content


def inject_cache_control(payload: dict) -> dict:
    """给 anthropic 请求注入 cache_control（ephemeral）以启用上下文缓存。

    策略：system 块 + 最后 1~2 个 user turn 的 content 末块各打一个 ephemeral 标记
    （anthropic 最多 4 个 breakpoint，这里 ≤3 个，安全）。深拷贝避免改原 payload，
    兼容 system/content 的 str|list，幂等跳过已有标记。
    """
    p = copy.deepcopy(payload)

    # system（str 或 list of blocks）
    if p.get("system"):
        p["system"] = _mark_block_cache(p["system"])

    # 最后两个 user turn
    messages = p.get("messages")
    if isinstance(messages, list):
        marked = 0
        for i in range(len(messages) - 1, -1, -1):
            if marked >= 2:
                break
            msg = messages[i]
            if isinstance(msg, dict) and msg.get("role") == "user":
                msg["content"] = _mark_block_cache(msg.get("content", ""))
                marked += 1
    return p


class GatewayService:

    # ── 模型路由 ──

    @staticmethod
    def is_model_allowed(session: Session, model: str) -> bool:
        """模型是否已在 model_pricing 配置且启用。未配置的模型一律拒绝放行，
        避免传入未定价模型免费白嫖上游。"""
        pricing = session.exec(
            select(ModelPricing).where(ModelPricing.model_id == model)
        ).first()
        return pricing is not None and pricing.is_active

    @staticmethod
    def get_context_window(session: Session, model: str) -> int:
        """取模型的上下文窗口(tokens)。0=不限。"""
        pricing = session.exec(
            select(ModelPricing).where(ModelPricing.model_id == model)
        ).first()
        return pricing.context_window if pricing else 0

    @staticmethod
    def resolve_upstream(session: Session, model: str, protocol: str) -> Tuple[str, str]:
        """按 model 找绑定渠道；找不到则取该协议下任一启用渠道；再不行回退到
        编译期默认（anthropic 用 settings.ANTHROPIC_BASE_URL/KEY）。

        渠道与协议是一对一的（每个渠道只有单一 base_url + 单一协议），而同一个
        展示模型可能被多种协议请求（openai_chat 走 /v1/chat/completions、anthropic
        走 /v1/messages）。因此绑定渠道的协议若与本次请求协议不符，必须忽略它、
        按请求协议另选一个启用渠道，否则会把协议路径拼到错误的 base_url 上（如
        DeepSeek 的 OpenAI 端点 https://api.deepseek.com 与 Anthropic 端点
        https://api.deepseek.com/anthropic 互不相同）。

        返回 (base_url, api_key)。
        """
        pricing = session.exec(
            select(ModelPricing).where(ModelPricing.model_id == model)
        ).first()
        channel: Optional[GatewayChannel] = None
        if pricing and pricing.channel_id:
            channel = session.get(GatewayChannel, pricing.channel_id)
        # 渠道不存在 / 未启用 / 协议与本次请求不符 → 按请求协议另选一个启用渠道
        if channel is None or not channel.enabled or channel.protocol != protocol:
            channel = session.exec(
                select(GatewayChannel)
                .where(GatewayChannel.protocol == protocol)
                .where(GatewayChannel.enabled == True)  # noqa: E712
            ).first()
        if channel is not None:
            return channel.base_url.rstrip("/"), channel.api_key

        # 回退：anthropic 用现有 config，避免阶段①没配渠道时网关不可用
        if protocol == "anthropic":
            return settings.ANTHROPIC_BASE_URL.rstrip("/"), settings.ANTHROPIC_API_KEY
        raise ValueError(f"无可用渠道: protocol={protocol}, model={model}")

    @staticmethod
    def resolve_protocol(session: Session, model: str) -> str:
        """返回模型绑定渠道的协议（anthropic / openai_chat / openai_responses）。

        按 ModelPricing.channel_id → GatewayChannel.protocol 取；无绑定渠道 / 渠道停用
        则回退 "anthropic"（历史默认）。agent loop 据此决定用哪套请求/SSE 格式。
        """
        pricing = session.exec(
            select(ModelPricing).where(ModelPricing.model_id == model)
        ).first()
        if pricing and pricing.channel_id:
            channel = session.get(GatewayChannel, pricing.channel_id)
            if channel and channel.enabled and channel.protocol:
                return channel.protocol
        return "anthropic"

    @staticmethod
    def resolve_model_name(session: Session, model: str) -> str:
        """展示名 → 真实上游模型名。

        若该 model 配了非空 upstream_model_id，则返回它（转发时用），
        否则原样返回 model（透传）。计费/记账始终用展示名 model，不受影响。
        """
        pricing = session.exec(
            select(ModelPricing).where(ModelPricing.model_id == model)
        ).first()
        if pricing and pricing.upstream_model_id:
            return pricing.upstream_model_id
        return model

    @staticmethod
    def build_upstream(base_url: str, api_key: str, protocol: str) -> Tuple[str, dict]:
        """拼上游 URL 与鉴权头。"""
        url = f"{base_url}{PROTOCOL_PATHS[protocol]}"
        if protocol == "anthropic":
            headers = {
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            }
        else:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
        return url, headers

    # ── usage 解析（统一成 prompt/completion/cache_read/cache_creation） ──

    @staticmethod
    def parse_usage(result: dict, protocol: str) -> Tuple[int, int, int, int]:
        """从非流式响应体解析总输入、输出、缓存读取和缓存写入 tokens。"""
        usage = result.get("usage") or {}
        if protocol == "anthropic":
            prompt = usage.get("input_tokens", 0) or 0
            completion = usage.get("output_tokens", 0) or 0
            cache_read = usage.get("cache_read_input_tokens", 0) or 0
            cache_creation = usage.get("cache_creation_input_tokens", 0) or 0
            prompt_total = prompt + cache_read + cache_creation
            return prompt_total, completion, cache_read, cache_creation
        prompt = usage.get("prompt_tokens") or usage.get("input_tokens", 0) or 0
        completion = usage.get("completion_tokens") or usage.get("output_tokens", 0) or 0
        details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
        cache_read = details.get("cached_tokens", 0) or 0
        cache_creation = details.get("cache_write_tokens", 0) or 0
        return prompt, completion, cache_read, cache_creation

    # ── 计费记账（成功后调用） ──

    @staticmethod
    def record_and_charge(
        user_id: int, module_name: str, model: str,
        prompt_tokens: int, completion_tokens: int, cache_read_tokens: int,
        ip_address: Optional[str], success: bool = True,
        error_message: Optional[str] = None,
        request_id: Optional[str] = None,
        cache_creation_tokens: int = 0,
    ) -> None:
        """写 ai_requests 并扣 credits。各自独立 try。

        cost_cents 优先按网关 model_pricing 费率算基础成本（不乘倍率，0.0001 元），
        模型无网关定价时回退旧静态价格表。
        request_id 为本次请求的全链路 id（req_xxx），写入 ai_requests.request_id，
        与 error_request_logs.request_id、credits 流水（经 ai_request_id 关联）同源。
        """
        ai_request_id = None
        try:
            from app.core.ai_pricing import calculate_cost
            with Session(engine) as session:
                units, multiplier = CreditsService.calc_consume_units(
                    session, model, prompt_tokens, completion_tokens,
                    cache_read_tokens, cache_creation_tokens,
                )
                if units > 0 and multiplier:
                    cost_cents = int(round(units / (multiplier * 100)))
                else:
                    cost_cents = calculate_cost(model, prompt_tokens, completion_tokens)
                req = AIRequest(
                    user_id=user_id, module_name=module_name, model=model,
                    request_id=request_id,
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_creation_tokens=cache_creation_tokens,
                    cost_cents=cost_cents,
                    success=success, error_message=error_message, ip_address=ip_address,
                    created_at=datetime.now(timezone.utc),
                )
                session.add(req)
                session.commit()
                session.refresh(req)
                ai_request_id = req.id
        except Exception as e:
            logger.error(f"Gateway record_ai_request failed: {e}")

        if not success:
            return
        try:
            with Session(engine) as session:
                CreditsService.consume(
                    session, user_id=user_id, model=model,
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                    cache_read_tokens=cache_read_tokens, ai_request_id=ai_request_id,
                    cache_creation_tokens=cache_creation_tokens,
                )
        except Exception as e:
            logger.error(f"Gateway credits consume failed: {e}")

    @staticmethod
    def record_image_and_charge(
        user_id: int, module_name: str, model: str,
        image_count: int, ip_address: Optional[str],
        success: bool = True, error_message: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        """绘图按张记账：写 ai_requests（tokens=0）并按张扣 credits。各自独立 try。"""
        ai_request_id = None
        try:
            with Session(engine) as session:
                pricing = session.exec(
                    select(ModelPricing).where(ModelPricing.model_id == model)
                ).first()
                cost_cents = 0
                if success and image_count > 0 and pricing and pricing.per_image_rate > 0:
                    cost_cents = int(round(pricing.per_image_rate * image_count * 10000))
                req = AIRequest(
                    user_id=user_id, module_name=module_name, model=model,
                    request_id=request_id,
                    prompt_tokens=0, completion_tokens=0, total_tokens=0,
                    cost_cents=cost_cents,
                    success=success, error_message=error_message, ip_address=ip_address,
                    created_at=datetime.now(timezone.utc),
                )
                session.add(req)
                session.commit()
                session.refresh(req)
                ai_request_id = req.id
        except Exception as e:
            logger.error(f"Gateway record_image_request failed: {e}")

        if not success or image_count <= 0:
            return
        try:
            with Session(engine) as session:
                CreditsService.consume_per_image(
                    session, user_id=user_id, model=model,
                    image_count=image_count, ai_request_id=ai_request_id,
                )
        except Exception as e:
            logger.error(f"Gateway image credits consume failed: {e}")

    # ── 错误记录（DB 表，替代 JSONL） ──

    @staticmethod
    def log_error(
        user_id: Optional[int], error_type: str, model: Optional[str],
        response_status: int, response_body: str,
        request_payload: Optional[dict] = None, extra: Optional[dict] = None,
        request_id: Optional[str] = None,
    ) -> None:
        try:
            summary = None
            if request_payload:
                summary = json.dumps({
                    k: request_payload.get(k)
                    for k in ("model", "stream", "max_tokens", "temperature")
                    if k in request_payload
                }, ensure_ascii=False)
            with Session(engine) as session:
                session.add(ErrorRequestLog(
                    user_id=user_id, error_type=error_type, model=model,
                    request_id=request_id,
                    response_status=response_status,
                    response_body=(response_body or "")[:4000],
                    request_summary=summary,
                    extra=json.dumps(extra, ensure_ascii=False) if extra else None,
                ))
                session.commit()
        except Exception as e:
            logger.error(f"Gateway log_error failed: {e}")
