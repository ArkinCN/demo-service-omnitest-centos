"""
统一模型网关 — 三协议端点（无状态）

- POST /gateway/v1/messages            Anthropic Messages
- POST /gateway/v1/chat/completions    OpenAI Chat Completions
- POST /gateway/v1/responses           OpenAI Responses

公共逻辑：鉴权(x-api-key=JWT) → credits 事前校验 → 模型路由 → 转发上游
(流式先 peek 状态码) → 成功后解析 usage → 扣 credits + 记 ai_requests
→ 失败写 error_request_logs。上下文缓存仅透传上游字段，按命中 token 计费。
"""
import asyncio
import json
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Request, Header
from fastapi.responses import StreamingResponse, JSONResponse
from sqlmodel import Session, select
from structlog import get_logger

from app.api.deps import get_db, verify_token_from_api_key
from app.core.config import settings
from app.models.gateway import ModelPricing
from app.schemas.common import error_response
from app.services.gateway_service import (
    GatewayService,
    convert_attachments_to_multimodal,
    inject_cache_control,
)
from app.services.content_safety_service import content_safety
from app.services.safety_responses import build_refusal_response
from app.services.credits_service import CreditsService

logger = get_logger(__name__)
router = APIRouter(prefix="/gateway", tags=["Gateway"])

INSUFFICIENT_CREDITS_MSG = "Credits 不足，请升级或获取更多"


def _client(request: Request) -> httpx.AsyncClient:
    return request.app.state.ai_http_client


def _new_request_id(request: Request) -> str:
    """生成本次请求的全链路 id。若客户端带了 x-request-id 则复用（便于端到端透传），
    否则生成 req_<uuid4hex>。该 id 会写入 ai_requests / error_request_logs，并回传响应头。"""
    incoming = request.headers.get("x-request-id")
    if incoming and incoming.strip():
        return incoming.strip()[:64]
    return f"req_{uuid.uuid4().hex}"


def _with_rid(resp, request_id: str):
    """给响应对象附加 x-request-id 头，便于客户端在报错时引用。"""
    try:
        resp.headers["x-request-id"] = request_id
    except Exception:
        pass
    return resp


async def _proxy(
    request: Request,
    session: Session,
    payload: dict,
    protocol: str,
    error_type: str,
    token_payload: dict,
):
    """三协议共用的转发核心。"""
    user_id = token_payload.get("user_id")
    username = token_payload.get("username", "unknown")
    module_name = payload.pop("module_name", None) or "ai_chat"
    model = payload.get("model", "unknown")
    stream = bool(payload.get("stream", False))
    ip_address = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )
    # 全链路请求 id：贯穿 ai_requests / error_request_logs / credits 流水，并回传响应头
    request_id = _new_request_id(request)

    # 0) 内容安全过滤·层 1 关键词（GB/T 45654）：零成本确定性拦截，放在一切
    #    校验之前；命中即按本协议正常响应格式拒答，不触达上游、不扣费。
    user_text = content_safety.extract_latest_user_text(payload, protocol)
    verdict = content_safety.screen_keywords(user_text)
    if verdict.blocked:
        content_safety.record_block(
            user_id, module_name, model, verdict, ip_address, request_id, user_text,
        )
        return _with_rid(build_refusal_response(protocol, stream, model, request_id), request_id)

    # 1) 模型准入：必须已在 model_pricing 配置且启用（未配置=未定价，拒绝白嫖）
    if not GatewayService.is_model_allowed(session, model):
        GatewayService.log_error(
            user_id, error_type, model, 400, "model not configured in gateway",
            payload, extra={"reason": "model_not_allowed"}, request_id=request_id,
        )
        return _with_rid(error_response(message=f"模型不可用或未配置: {model}", code=400), request_id)

    # 2) credits 事前校验
    if not CreditsService.has_balance(session, user_id):
        return _with_rid(error_response(message=INSUFFICIENT_CREDITS_MSG, code=402), request_id)

    # 2.5) 内容安全过滤·层 2 大模型分类：语义级风险（意图型请求）。消耗上游
    #    tokens，故放在余额/准入之后；编程/批量链路（module_name != ai_chat）
    #    延迟敏感，仅层 1。
    if module_name == "ai_chat":
        verdict = await content_safety.screen_llm(_client(request), user_text)
        if verdict.blocked:
            content_safety.record_block(
                user_id, module_name, model, verdict, ip_address, request_id, user_text,
            )
            return _with_rid(
                build_refusal_response(protocol, stream, model, request_id), request_id
            )

    # 3) 模型路由
    try:
        base_url, api_key = GatewayService.resolve_upstream(session, model, protocol)
    except ValueError as e:
        return _with_rid(error_response(message=str(e), code=400), request_id)
    upstream_url, headers = GatewayService.build_upstream(base_url, api_key, protocol)

    # 3.5) 转发前的 payload 处理
    #  - openai_chat：把顶级 attachments 转成多模态 content（debug-agent 视觉评审依赖）
    #  - anthropic：默认注入 cache_control 启用上下文缓存
    #  - qwen3.6-plus：关闭思考模式（上游默认开，行为会变）
    if protocol == "openai_chat" and payload.get("attachments"):
        payload["messages"] = convert_attachments_to_multimodal(
            payload.get("messages") or [], payload.pop("attachments")
        )
    # openai_chat 流式默认不在 chunk 里带 usage，必须显式要求，否则末块无 usage → 0 扣费。
    if protocol == "openai_chat" and stream:
        opts = payload.get("stream_options")
        if not isinstance(opts, dict):
            opts = {}
        opts["include_usage"] = True
        payload["stream_options"] = opts
    if model == "qwen3.6-plus":
        payload.setdefault("enable_thinking", False)
    if protocol == "anthropic" and settings.GATEWAY_CACHE_INJECT:
        payload = inject_cache_control(payload)

    # 3.6) 模型路由：把展示名替换成真实上游模型名（配了 upstream_model_id 时）。
    #  放在所有按展示名的协议微调之后，保证上面那些判断仍基于用户可见的 model。
    #  计费/记账继续用展示名 model，用户端无感知。
    upstream_model = GatewayService.resolve_model_name(session, model)
    if upstream_model != model:
        payload["model"] = upstream_model

    # 前置校验/路由解析已全部用完 session。上游转发可能耗时数十秒，期间这条
    # get_db 连接若继续持有就是纯占用——高并发时(如注释翻译 50 并发)会把连接池
    # (size 20 + overflow 30 = 50)占满，导致后续 record_and_charge/log_error 拿不到
    # 连接而超时。这里提前归还连接；后续记账各自用独立的 with Session(engine)。
    session.close()

    client = _client(request)

    # 4) 转发
    if stream:
        return await _proxy_stream(
            client, upstream_url, headers, payload, protocol, error_type,
            user_id, username, module_name, model, ip_address, request_id,
        )

    # 非流式：最多重试 3 次（仅连接失败 / 5xx / 429），4xx 不重试。
    # 读/写超时也不重试：请求已送达上游、可能正在执行，重试会导致上游重复执行
    # 与重复计数（我们记 1 条失败，上游记 N 次请求）。
    # 计费只在最终结果记一次，避免重试中途重复扣费。
    max_retries = 3
    last_error_status = 500
    last_error_body = ""
    last_error_msg = "网关转发失败"
    attempts = 0
    for attempt in range(1, max_retries + 1):
        attempts = attempt
        no_retry = False
        try:
            resp = await client.post(upstream_url, json=payload, headers=headers)
        except httpx.ConnectTimeout as e:
            last_error_status, last_error_body, last_error_msg = 504, str(e), "上游连接超时"
        except httpx.TimeoutException as e:
            last_error_status, last_error_body, last_error_msg = 504, str(e), "上游超时"
            no_retry = True
        except Exception as e:
            last_error_status, last_error_body, last_error_msg = 502, str(e), "网关转发失败"
        else:
            if resp.is_success:
                result = resp.json()
                pt, ct, cache_read, cache_creation = GatewayService.parse_usage(
                    result, protocol
                )
                GatewayService.record_and_charge(
                    user_id, module_name, model, pt, ct, cache_read, ip_address,
                    success=True, request_id=request_id,
                    cache_creation_tokens=cache_creation,
                )
                return _with_rid(JSONResponse(content=result), request_id)
            # 4xx 客户端错误不重试，直接返回
            if 400 <= resp.status_code < 500:
                GatewayService.log_error(
                    user_id, error_type, model, resp.status_code, resp.text, payload,
                    request_id=request_id,
                )
                GatewayService.record_and_charge(
                    user_id, module_name, model, 0, 0, 0, ip_address,
                    success=False, error_message=f"HTTP {resp.status_code}",
                    request_id=request_id,
                )
                return _with_rid(JSONResponse(
                    status_code=resp.status_code, content=_safe_json(resp.text)
                ), request_id)
            # 5xx / 429 → 可重试
            last_error_status, last_error_body = resp.status_code, resp.text
            last_error_msg = f"上游错误 {resp.status_code}"

        if no_retry:
            break
        if attempt < max_retries:
            await asyncio.sleep(attempt)  # 指数退避 1s, 2s

    # 重试耗尽或不可重试：记一次失败（attempts = 实际发往上游的次数，供对账）
    GatewayService.log_error(
        user_id, error_type, model, last_error_status, last_error_body, payload,
        request_id=request_id,
    )
    GatewayService.record_and_charge(
        user_id, module_name, model, 0, 0, 0, ip_address,
        success=False, error_message=f"HTTP {last_error_status} ({attempts} attempts)",
        request_id=request_id,
    )
    code = last_error_status if last_error_status >= 400 else 502
    return _with_rid(error_response(message=last_error_msg, code=code), request_id)


async def _proxy_stream(
    client, upstream_url, headers, payload, protocol, error_type,
    user_id, username, module_name, model, ip_address, request_id,
):
    """流式：先 peek 上游状态码再决定 StreamingResponse（参考 claude_proxy）。"""
    upstream_req = client.build_request("POST", upstream_url, json=payload, headers=headers)
    try:
        response = await client.send(upstream_req, stream=True)
    except Exception as e:
        GatewayService.log_error(user_id, error_type, model, 502, str(e), payload, request_id=request_id)
        GatewayService.record_and_charge(
            user_id, module_name, model, 0, 0, 0, ip_address,
            success=False, error_message=str(e), request_id=request_id,
        )
        return _with_rid(error_response(message="网关转发失败", code=502), request_id)

    if not response.is_success:
        body = await response.aread()
        await response.aclose()
        text = body.decode("utf-8", "replace")
        GatewayService.log_error(user_id, error_type, model, response.status_code, text, payload, request_id=request_id)
        GatewayService.record_and_charge(
            user_id, module_name, model, 0, 0, 0, ip_address,
            success=False, error_message=f"HTTP {response.status_code}", request_id=request_id,
        )
        return _with_rid(JSONResponse(status_code=response.status_code, content=_safe_json(text)), request_id)

    async def generator():
        # 累积 usage：从 SSE 末尾的 usage 事件提取（anthropic message_delta / openai 末块）
        captured = {"pt": 0, "ct": 0, "input": 0, "cache": 0, "creation": 0}
        try:
            async for raw in response.aiter_lines():
                if raw:
                    _scan_usage_line(raw, protocol, captured)
                # 原样透传给下游（保留 SSE 行格式）
                yield (raw + "\n").encode("utf-8")
        finally:
            await response.aclose()
            GatewayService.record_and_charge(
                user_id, module_name, model,
                captured["pt"], captured["ct"], captured["cache"],
                ip_address, success=True, request_id=request_id,
                cache_creation_tokens=captured["creation"],
            )

    return StreamingResponse(
        generator(), media_type="text/event-stream",
        headers={"x-request-id": request_id},
    )


def _scan_usage_line(line: str, protocol: str, captured: dict) -> None:
    """从单行 SSE 尝试提取 usage（尽力而为，解析失败忽略）。"""
    s = line.strip()
    if not s.startswith("data:"):
        return
    data = s[5:].strip()
    if not data or data == "[DONE]":
        return
    try:
        obj = json.loads(data)
    except Exception:
        return
    usage = obj.get("usage")
    # anthropic: message_start.message.usage / message_delta.usage
    if usage is None and isinstance(obj.get("message"), dict):
        usage = obj["message"].get("usage")
    # openai_responses 流式：usage 在 response.completed 事件的 response.usage
    if usage is None and isinstance(obj.get("response"), dict):
        usage = obj["response"].get("usage")
    if not isinstance(usage, dict):
        return
    if protocol == "anthropic":
        captured["input"] = max(
            captured["input"], usage.get("input_tokens", 0) or 0
        )
        captured["cache"] = max(
            captured["cache"], usage.get("cache_read_input_tokens", 0) or 0
        )
        captured["creation"] = max(
            captured["creation"], usage.get("cache_creation_input_tokens", 0) or 0
        )
        captured["pt"] = (
            captured["input"] + captured["cache"] + captured["creation"]
        )
        captured["ct"] = max(
            captured["ct"], usage.get("output_tokens", 0) or 0
        )
    else:
        pt = usage.get("prompt_tokens") or usage.get("input_tokens", 0) or 0
        ct = usage.get("completion_tokens") or usage.get("output_tokens", 0) or 0
        details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
        captured["pt"] = max(captured["pt"], pt)
        captured["ct"] = max(captured["ct"], ct)
        captured["cache"] = max(
            captured["cache"], details.get("cached_tokens", 0) or 0
        )
        captured["creation"] = max(
            captured["creation"], details.get("cache_write_tokens", 0) or 0
        )


def _safe_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        return {"error": text[:2000]}


# ── 三端点 ──

@router.post("/v1/messages", summary="Gateway - Anthropic Messages")
async def gateway_messages(
    request: Request,
    session: Session = Depends(get_db),
    token_payload: dict = Depends(verify_token_from_api_key),
):
    payload = await request.json()
    return await _proxy(request, session, payload, "anthropic", "gateway_messages", token_payload)


@router.post("/v1/chat/completions", summary="Gateway - OpenAI Chat Completions")
async def gateway_chat_completions(
    request: Request,
    session: Session = Depends(get_db),
    token_payload: dict = Depends(verify_token_from_api_key),
):
    payload = await request.json()
    return await _proxy(request, session, payload, "openai_chat", "gateway_chat", token_payload)


@router.post("/v1/responses", summary="Gateway - OpenAI Responses")
async def gateway_responses(
    request: Request,
    session: Session = Depends(get_db),
    token_payload: dict = Depends(verify_token_from_api_key),
):
    payload = await request.json()
    return await _proxy(request, session, payload, "openai_responses", "gateway_responses", token_payload)


@router.get("/models", summary="AI 对话可用模型（chat_enabled 的网关模型）")
async def list_chat_models(
    session: Session = Depends(get_db),
    token_payload: dict = Depends(verify_token_from_api_key),
):
    """返回 AI 对话面板可选的模型：仅 chat_enabled 且启用、且当前用户有权限的网关模型。"""
    from app.models.user import User
    from app.models.user_group import UserGroupMember
    from app.services.permission import check_entity_permission

    user_id = token_payload.get("user_id")
    user = session.get(User, user_id) if user_id else None
    user_email = (user.email or "") if user else ""
    group_ids = [
        gm.group_id
        for gm in session.exec(
            select(UserGroupMember).where(UserGroupMember.user_id == user_id)
        ).all()
    ] if user_id else []

    rows = session.exec(
        select(ModelPricing)
        .where(ModelPricing.chat_enabled == True)  # noqa: E712
        .where(ModelPricing.is_active == True)  # noqa: E712
        .order_by(ModelPricing.sort_order, ModelPricing.id)
    ).all()

    data = []
    for m in rows:
        # 模型级权限（ModelPricing 字段与权限检查同构）
        if not check_entity_permission(m, user_id, group_ids, user_email):
            continue
        data.append({
            "id": m.model_id,
            "name": m.display_name or m.model_id,
            "vision": m.vision,
            "reasoning": m.reasoning,
            "context_window": m.context_window,
            "provider_name": m.provider_name or "",
            "provider_icon": m.provider_icon or "",
            "provider_icon_size": m.provider_icon_size or "",
            "sort_order": m.sort_order,
            "is_tier": m.is_tier,
            "description": m.description or "",
            "multiplier": m.multiplier,
        })
    return {"success": True, "code": 200, "message": "Success", "data": data}
