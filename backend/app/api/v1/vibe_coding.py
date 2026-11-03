"""
Code Assistant API - 管理端点 + claw.exe 代理端点
"""
import json
import uuid
import asyncio
import httpx
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Any, Union
from fastapi import APIRouter, Depends, Request, Header
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from structlog import get_logger

from app.api.deps import (
    get_db,
    get_current_user,
    require_admin,
    verify_token_from_api_key,
    verify_token_only,
)
from app.core.config import settings
from app.core.security import create_access_token, decode_token
from app.core.exceptions import UnauthorizedException
from app.models.user import User
from app.schemas.common import success_response, error_response
from app.services.vibe_coding_service import VibeCodingService
from app.services.vibe_token_guard import (
    normalize_device_fp,
    revoke_token,
    verify_vibe_token,
)
from app.services.gateway_service import GatewayService
from app.services.permission import check_entity_permission
from app.services.skill_expansion import expand_skill_placeholders
from app.core.ai_recording import record_ai_request, get_client_ip
from app.core.error_logger import save_error_request_log
from app.services.content_safety_service import content_safety
from app.services.safety_responses import build_refusal_response

logger = get_logger(__name__)

# Fire-and-forget 后台任务的强引用集合。asyncio 只对 Task 持弱引用，
# 不保留引用的话任务可能在运行前被 GC 掉（导致旁路静默失效）。
_skillclaw_bg_tasks: set = set()


def _schedule_skillclaw(coro):
    """调度一个 SkillClaw 旁路投递任务并持有强引用直到完成。"""
    task = asyncio.create_task(coro)
    _skillclaw_bg_tasks.add(task)
    task.add_done_callback(_skillclaw_bg_tasks.discard)
    return task


# ============================================================================
# 管理路由
# ============================================================================

admin_router = APIRouter(prefix="/vibe-coding", tags=["Code Assistant Admin"])


class ConfigUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    visibility: Optional[str] = None
    allowed_group_ids: Optional[list] = None
    allowed_user_ids: Optional[list] = None


class ChannelCreateRequest(BaseModel):
    name: str
    base_url: str
    api_key: str
    model: str
    is_default: Optional[bool] = False
    channel_type: Optional[str] = "main"  # main / subagent
    # anthropic(/v1/messages) / openai_responses(/v1/responses) / openai_chat(/v1/chat/completions)
    protocol: Optional[str] = Field(
        default="anthropic", pattern="^(anthropic|openai_responses|openai_chat)$"
    )
    # 前端展示分组/图标/能力标签
    provider_name: Optional[str] = ""
    provider_icon: Optional[str] = ""
    provider_icon_size: Optional[str] = ""
    vision: Optional[bool] = False
    reasoning: Optional[bool] = False
    sort_order: Optional[int] = 0


class ChannelUpdateRequest(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    is_default: Optional[bool] = None
    channel_type: Optional[str] = None
    protocol: Optional[str] = Field(
        default=None, pattern="^(anthropic|openai_responses|openai_chat)$"
    )
    # 前端展示分组/图标/能力标签
    provider_name: Optional[str] = None
    provider_icon: Optional[str] = None
    provider_icon_size: Optional[str] = None
    vision: Optional[bool] = None
    reasoning: Optional[bool] = None
    sort_order: Optional[int] = None


@admin_router.get("/config", summary="获取 Code Assistant 配置")
def get_config(
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    config = VibeCodingService.get_config(session)
    return success_response(data={
        "enabled": config.enabled,
        "visibility": config.visibility,
        "allowed_group_ids": config.allowed_group_ids if isinstance(config.allowed_group_ids, list) else json.loads(config.allowed_group_ids or "[]"),
        "allowed_user_ids": config.allowed_user_ids if isinstance(config.allowed_user_ids, list) else json.loads(config.allowed_user_ids or "[]"),
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    })


@admin_router.put("/config", summary="更新 Code Assistant 配置")
def update_config(
    data: ConfigUpdateRequest,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    config = VibeCodingService.update_config(session, data.model_dump(exclude_none=True))
    return success_response(message="配置已更新", data={
        "enabled": config.enabled,
        "visibility": config.visibility,
        "allowed_group_ids": config.allowed_group_ids if isinstance(config.allowed_group_ids, list) else json.loads(config.allowed_group_ids or "[]"),
        "allowed_user_ids": config.allowed_user_ids if isinstance(config.allowed_user_ids, list) else json.loads(config.allowed_user_ids or "[]"),
    })


# ── 渠道管理 ──

def _serialize_channel(ch) -> dict:
    """序列化渠道，api_key 脱敏"""
    key = ch.api_key or ""
    if len(key) > 8:
        masked_key = key[:3] + "*" * (len(key) - 7) + key[-4:]
    else:
        masked_key = "****"
    return {
        "id": ch.id,
        "name": ch.name,
        "base_url": ch.base_url,
        "api_key_masked": masked_key,
        "model": ch.model,
        "is_active": ch.enabled,
        "is_default": ch.is_default,
        "channel_type": ch.channel_type,
        "protocol": ch.protocol,
        "provider_name": ch.provider_name,
        "provider_icon": ch.provider_icon,
        "provider_icon_size": ch.provider_icon_size,
        "vision": ch.vision,
        "reasoning": ch.reasoning,
        "sort_order": ch.sort_order,
        "created_at": ch.created_at.isoformat() if ch.created_at else None,
        "updated_at": ch.updated_at.isoformat() if ch.updated_at else None,
    }


@admin_router.get("/channels", summary="获取渠道列表")
def get_channels(
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    channels = VibeCodingService.get_channels(session)
    return success_response(data=[_serialize_channel(ch) for ch in channels])


@admin_router.post("/channels", summary="新增渠道")
def create_channel(
    data: ChannelCreateRequest,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    channel = VibeCodingService.create_channel(session, data.model_dump())
    return success_response(message="渠道已创建", data=_serialize_channel(channel))


@admin_router.put("/channels/{channel_id}", summary="修改渠道")
def update_channel(
    channel_id: int,
    data: ChannelUpdateRequest,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    try:
        channel = VibeCodingService.update_channel(session, channel_id, data.model_dump(exclude_none=True))
        return success_response(message="渠道已更新", data=_serialize_channel(channel))
    except ValueError as e:
        return error_response(message=str(e))


@admin_router.delete("/channels/{channel_id}", summary="删除渠道")
def delete_channel(
    channel_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    try:
        VibeCodingService.delete_channel(session, channel_id)
        return success_response(message="渠道已删除")
    except ValueError as e:
        return error_response(message=str(e))


@admin_router.post("/channels/{channel_id}/enable", summary="启用渠道")
def enable_channel(
    channel_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    try:
        channel = VibeCodingService.enable_channel(session, channel_id)
        return success_response(message=f"已启用渠道: {channel.name}", data=_serialize_channel(channel))
    except ValueError as e:
        return error_response(message=str(e))


@admin_router.post("/channels/{channel_id}/disable", summary="禁用渠道")
def disable_channel(
    channel_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    try:
        channel = VibeCodingService.disable_channel(session, channel_id)
        return success_response(message=f"已禁用渠道: {channel.name}", data=_serialize_channel(channel))
    except ValueError as e:
        return error_response(message=str(e))


# 兼容旧前端：/activate 和 /deactivate 别名（语义上等价于 enable/disable）
@admin_router.post("/channels/{channel_id}/activate", summary="启用渠道（别名）", include_in_schema=False)
def activate_channel_alias(
    channel_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    try:
        channel = VibeCodingService.enable_channel(session, channel_id)
        return success_response(message=f"已启用渠道: {channel.name}", data=_serialize_channel(channel))
    except ValueError as e:
        return error_response(message=str(e))


@admin_router.post("/channels/{channel_id}/deactivate", summary="禁用渠道（别名）", include_in_schema=False)
def deactivate_channel_alias(
    channel_id: int,
    session: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    try:
        channel = VibeCodingService.disable_channel(session, channel_id)
        return success_response(message=f"已禁用渠道: {channel.name}", data=_serialize_channel(channel))
    except ValueError as e:
        return error_response(message=str(e))


# ── 用户端：可用渠道列表 ──

@admin_router.get("/channels/available", summary="当前用户可用的渠道列表")
def list_available_channels(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回所有 enabled=True 的渠道（仅暴露 id/name/model，不含 base_url/api_key）。

    渠道 model 命中档位 ModelPricing 时，按其 visibility/allowed_* 过滤（无权者看不到），
    并附带档位展示字段（display_name/description/multiplier/is_tier）供前端展示。
    """
    user_group_ids = VibeCodingService.get_user_group_ids(session, current_user.id)
    perm = VibeCodingService.check_permission(session, current_user.id, user_group_ids)
    if not perm["allowed"]:
        return error_response(message=perm["reason"])

    user_email = current_user.email or ""
    channels = VibeCodingService.get_enabled_channels(session)
    data = []
    for c in channels:
        pricing = VibeCodingService.get_channel_pricing(session, c)
        # 档位权限：命中定价则按 visibility/allowed_* 过滤；裸模型保持可见
        if pricing is not None and not check_entity_permission(
            pricing, current_user.id, user_group_ids, user_email
        ):
            continue
        is_tier = bool(pricing.is_tier) if pricing else False
        # 档位渠道对外只暴露抽象标签，真实 model_id 永不出服务端；
        # 计费/路由由转发端按 token 绑定渠道的 channel.model 权威决定。
        public_model = (
            (pricing.display_name or pricing.description or pricing.model_id)
            if is_tier
            else c.model
        )
        data.append({
            "id": c.id,
            "name": c.name,
            "model": public_model,
            "is_default": c.is_default,
            "protocol": c.protocol,
            "display_name": (pricing.display_name or pricing.model_id) if pricing else "",
            "description": pricing.description if pricing else "",
            "multiplier": pricing.multiplier if pricing else None,
            "is_tier": is_tier,
            # 上下文窗口随渠道下发，CLI 不再靠模型名反推（0=未配/不裁剪）。
            "context_window": int(pricing.context_window) if pricing and pricing.context_window else 0,
            # 前端选择器分组/图标/能力标签：优先渠道自配，档位渠道未配时回落到定价。
            "provider_name": c.provider_name or (pricing.provider_name if pricing else ""),
            "provider_icon": c.provider_icon or (pricing.provider_icon if pricing else ""),
            "provider_icon_size": c.provider_icon_size or (pricing.provider_icon_size if pricing else ""),
            "vision": bool(c.vision or (pricing.vision if pricing else False)),
            "reasoning": bool(c.reasoning or (pricing.reasoning if pricing else False)),
            "sort_order": int(c.sort_order or 0),
        })
    return success_response(data=data)


@admin_router.get("/permission", summary="检查当前用户 Code Assistant 权限")
def check_permission(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_group_ids = VibeCodingService.get_user_group_ids(session, current_user.id)
    result = VibeCodingService.check_permission(session, current_user.id, user_group_ids)
    return success_response(data=result)


# ── 火山引擎联网搜索（mdebug-code WebSearch 工具用）──

class WebSearchRequest(BaseModel):
    query: str
    max_results: Optional[int] = 8


def _extract_volc_search_results(response_json: dict) -> tuple[str, list[dict]]:
    """从火山引擎 web_search 响应里提取 summary + 引用列表。

    web 端点不返回 summary（那是 web_summary 端点的职责），所以 summary 留空；
    每条命中归一为 {title, url, site, snippet, summary, publish_time}：
    - snippet 字段保留 200 字版用于列表展示；
    - summary 字段（500~1000 字，文档推荐喂大模型）放在专用字段里供 CLI 透传。
    """
    result = response_json.get("Result") or {}
    raw_hits = result.get("WebResults") or []

    normalized: list[dict] = []
    for item in raw_hits:
        if not isinstance(item, dict):
            continue
        url = item.get("Url") or ""
        if not url:
            continue
        normalized.append({
            "title": str(item.get("Title") or ""),
            "url": str(url),
            "site": str(item.get("SiteName") or ""),
            "snippet": str(item.get("Snippet") or ""),
            "summary": str(item.get("Summary") or ""),
            "publish_time": str(item.get("PublishTime") or ""),
        })
    return "", normalized


@admin_router.post("/web-search", summary="火山引擎联网搜索（mdebug-code WebSearch 用）")
async def vibe_coding_web_search(
    body: WebSearchRequest,
    request: Request,
    x_api_key: str = Header(..., description="JWT token as Anthropic API key"),
    x_device_fp: Optional[str] = Header(
        None, alias="x-device-fp",
        description="设备指纹(sha-256 hex),与 token 内 dfp claim 绑定校验",
    ),
    session: Session = Depends(get_db),
):
    """mdebug-code 端 WebSearch 工具的后端入口。

    复用 vibe-coding 的 JWT 鉴权 + 权限/额度校验，调用火山引擎
    `/search_api/web_search`（SearchType=web）拿真实联网结果，转成
    `{summary, results:[{title,url,site,snippet,summary,publish_time}]}`
    给 CLI 渲染。
    """
    # 1. 验 JWT
    try:
        payload = decode_token(x_api_key)
    except Exception:
        return error_response(message="Invalid or expired token, please restart terminal", code=401)

    if payload.get("type") != "access":
        return error_response(message="Invalid token type", code=401)

    user_id = payload.get("user_id")
    if not user_id:
        return error_response(message="Invalid token payload", code=401)

    try:
        payload = _verify_and_renew_token(payload, session, x_device_fp)
    except UnauthorizedException as exc:
        return error_response(message=str(exc), code=401)

    username = payload.get("username", "unknown")

    # 2. 权限/额度
    user_group_ids = VibeCodingService.get_user_group_ids(session, user_id)
    perm = VibeCodingService.check_permission(session, user_id, user_group_ids)
    if not perm["allowed"]:
        return error_response(message=perm["reason"], code=403)

    query = (body.query or "").strip()
    if not query:
        return error_response(message="query 不能为空", code=400)

    if not settings.VOLC_WEB_SEARCH_API_KEY:
        return error_response(message="后端未配置 VOLC_WEB_SEARCH_API_KEY", code=503)

    max_results = body.max_results if body.max_results and body.max_results > 0 else 8
    # 火山引擎 web 单次最多 50 条
    max_results = min(max_results, 50)

    ip_address = get_client_ip(request)
    upstream_url = settings.VOLC_WEB_SEARCH_BASE_URL
    search_type = settings.VOLC_WEB_SEARCH_TYPE
    upstream_payload = {
        "Query": query[:100],  # 文档限制 1~100 字符，过长会截断
        "SearchType": search_type,
        "Count": max_results,
        "Filter": {"NeedUrl": True},
        "NeedSummary": True,
    }
    headers = {
        "Authorization": f"Bearer {settings.VOLC_WEB_SEARCH_API_KEY}",
        "Content-Type": "application/json",
    }

    logger.info(
        "Volc web search request",
        user_id=user_id,
        username=username,
        query=query[:80],
    )

    client: httpx.AsyncClient = request.app.state.ai_http_client
    timeout = httpx.Timeout(settings.VOLC_WEB_SEARCH_TIMEOUT, connect=10.0)

    max_retries = 2
    last_exc: Optional[Exception] = None
    response_json: Optional[dict] = None
    for attempt in range(1, max_retries + 1):
        try:
            response = await client.post(
                upstream_url, json=upstream_payload, headers=headers, timeout=timeout,
            )
            if not response.is_success:
                save_error_request_log(
                    request_payload=upstream_payload,
                    response_status=response.status_code,
                    response_body=response.text,
                    error_type="volc_web_search",
                    user_id=user_id,
                    extra_info={"username": username, "query": query[:200]},
                )
                record_ai_request(
                    user_id=user_id, module_name="volc-websearch", model=search_type,
                    prompt_tokens=0, completion_tokens=0, success=False,
                    error_message=f"HTTP {response.status_code}", ip_address=ip_address,
                )
                return error_response(
                    message=f"上游搜索接口错误: {response.status_code}",
                    code=502,
                )
            response_json = response.json()
            # 业务错误信封：ResponseMetadata.Error 非 None
            metadata = response_json.get("ResponseMetadata") or {}
            err = metadata.get("Error")
            if err:
                save_error_request_log(
                    request_payload=upstream_payload,
                    response_status=response.status_code,
                    response_body=response.text,
                    error_type="volc_web_search",
                    user_id=user_id,
                    extra_info={"username": username, "query": query[:200], "error": err},
                )
                record_ai_request(
                    user_id=user_id, module_name="volc-websearch", model=search_type,
                    prompt_tokens=0, completion_tokens=0, success=False,
                    error_message=str(err), ip_address=ip_address,
                )
                return error_response(
                    message=f"上游搜索业务错误: {err.get('Message') or err}",
                    code=502,
                )
            break
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            last_exc = exc
            logger.warning(
                "Volc web search transport error",
                user_id=user_id, attempt=attempt, error=repr(exc),
            )
            if attempt < max_retries:
                await asyncio.sleep(attempt)

    if response_json is None:
        record_ai_request(
            user_id=user_id, module_name="volc-websearch", model=search_type,
            prompt_tokens=0, completion_tokens=0, success=False,
            error_message=repr(last_exc), ip_address=ip_address,
        )
        return error_response(message="联网搜索失败，请稍后再试", code=502)

    summary, results = _extract_volc_search_results(response_json)
    results = results[:max_results]

    # 联网搜索免费（无 LLM token，不扣 credits），仅记账用于后台统计。
    record_ai_request(
        user_id=user_id, module_name="volc-websearch", model=search_type,
        prompt_tokens=0, completion_tokens=0,
        success=True, ip_address=ip_address,
    )

    logger.info(
        "Volc web search completed",
        user_id=user_id, username=username, hits=len(results),
    )

    return success_response(data={
        "query": query,
        "summary": summary,
        "results": results,
    })


# ── 内网知识库检索（mdebug-code KnowledgeSearch 工具用）──

class KnowledgeSearchRequest(BaseModel):
    question: str
    datasets: Optional[list[str]] = None
    dataset_ids: Optional[list[str]] = None
    top_k: Optional[int] = None
    similarity_threshold: Optional[float] = None
    vector_similarity_weight: Optional[float] = None
    keyword: Optional[bool] = None
    highlight: Optional[bool] = None


@admin_router.post("/knowledge-search", summary="内网知识库检索（mdebug-code KnowledgeSearch 用）")
async def vibe_coding_knowledge_search(
    body: KnowledgeSearchRequest,
    request: Request,
    x_api_key: str = Header(..., description="JWT token as Anthropic API key"),
    x_device_fp: Optional[str] = Header(
        None, alias="x-device-fp",
        description="设备指纹(sha-256 hex),与 token 内 dfp claim 绑定校验",
    ),
    session: Session = Depends(get_db),
):
    """mdebug-code 端 KnowledgeSearch 工具的后端入口。

    复用 vibe-coding 的 JWT 鉴权 + 权限校验，代理内网知识库检索服务
    `POST {KB_SEARCH_BASE_URL}/search`（密钥 KB_SEARCH_API_KEY 仅服务端持有，
    CLI 不再直连内网），响应 `{question,total,returned,chunks,doc_aggs}` 原样
    放进统一信封的 data 里给 CLI 渲染。
    """
    # 1. 验 JWT
    try:
        payload = decode_token(x_api_key)
    except Exception:
        return error_response(message="Invalid or expired token, please restart terminal", code=401)

    if payload.get("type") != "access":
        return error_response(message="Invalid token type", code=401)

    user_id = payload.get("user_id")
    if not user_id:
        return error_response(message="Invalid token payload", code=401)

    try:
        payload = _verify_and_renew_token(payload, session, x_device_fp)
    except UnauthorizedException as exc:
        return error_response(message=str(exc), code=401)

    username = payload.get("username", "unknown")

    # 2. 权限
    user_group_ids = VibeCodingService.get_user_group_ids(session, user_id)
    perm = VibeCodingService.check_permission(session, user_id, user_group_ids)
    if not perm["allowed"]:
        return error_response(message=perm["reason"], code=403)

    question = (body.question or "").strip()
    if not question:
        return error_response(message="question 不能为空", code=400)

    if not settings.KB_SEARCH_API_KEY:
        return error_response(message="后端未配置 KB_SEARCH_API_KEY", code=503)

    ip_address = get_client_ip(request)
    upstream_url = f"{settings.KB_SEARCH_BASE_URL.rstrip('/')}/search"
    # 只透传显式给出的可选字段，未给的交由检索服务用其默认值。
    upstream_payload: dict = {"question": question}
    if body.datasets is not None:
        upstream_payload["datasets"] = body.datasets
    if body.dataset_ids is not None:
        upstream_payload["dataset_ids"] = body.dataset_ids
    if body.top_k is not None:
        upstream_payload["top_k"] = max(1, min(body.top_k, 50))
    if body.similarity_threshold is not None:
        upstream_payload["similarity_threshold"] = body.similarity_threshold
    if body.vector_similarity_weight is not None:
        upstream_payload["vector_similarity_weight"] = body.vector_similarity_weight
    if body.keyword is not None:
        upstream_payload["keyword"] = body.keyword
    if body.highlight is not None:
        upstream_payload["highlight"] = body.highlight
    headers = {
        "Authorization": f"Bearer {settings.KB_SEARCH_API_KEY}",
        "Content-Type": "application/json",
    }

    logger.info(
        "KB search request",
        user_id=user_id,
        username=username,
        question=question[:80],
    )

    client: httpx.AsyncClient = request.app.state.ai_http_client
    timeout = httpx.Timeout(settings.KB_SEARCH_TIMEOUT, connect=10.0)

    max_retries = 2
    last_exc: Optional[Exception] = None
    response_json: Optional[dict] = None
    for attempt in range(1, max_retries + 1):
        try:
            response = await client.post(
                upstream_url, json=upstream_payload, headers=headers, timeout=timeout,
            )
            if not response.is_success:
                save_error_request_log(
                    request_payload=upstream_payload,
                    response_status=response.status_code,
                    response_body=response.text,
                    error_type="kb_search",
                    user_id=user_id,
                    extra_info={"username": username, "question": question[:200]},
                )
                record_ai_request(
                    user_id=user_id, module_name="kb-search", model="kb-search",
                    prompt_tokens=0, completion_tokens=0, success=False,
                    error_message=f"HTTP {response.status_code}", ip_address=ip_address,
                )
                return error_response(
                    message=f"知识库检索服务错误: {response.status_code}",
                    code=502,
                )
            response_json = response.json()
            break
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            last_exc = exc
            logger.warning(
                "KB search transport error",
                user_id=user_id, attempt=attempt, error=repr(exc),
            )
            if attempt < max_retries:
                await asyncio.sleep(attempt)

    if response_json is None:
        record_ai_request(
            user_id=user_id, module_name="kb-search", model="kb-search",
            prompt_tokens=0, completion_tokens=0, success=False,
            error_message=repr(last_exc), ip_address=ip_address,
        )
        return error_response(message="知识库检索失败，请稍后再试", code=502)

    # 知识库检索免费（无 LLM token，不扣 credits），仅记账用于后台统计。
    record_ai_request(
        user_id=user_id, module_name="kb-search", model="kb-search",
        prompt_tokens=0, completion_tokens=0,
        success=True, ip_address=ip_address,
    )

    logger.info(
        "KB search completed",
        user_id=user_id, username=username,
        returned=response_json.get("returned"),
    )

    # 裁剪：这份 data 会被 CLI 原样放进模型上下文。chunks 里的 document_id/dataset_id
    # 模型无法用于任何后续调用（工具入参只收 dataset_ids 知识库 id），doc_aggs 全量
    # 可达数十条（每条 32 位 hex id + 长文件名），一次检索白占 2000+ tokens——
    # 只保留正文引用所需字段，聚合截前 10 条且不带 id。
    chunks = [
        {
            key: value
            for key, value in (chunk or {}).items()
            if key in ("content", "similarity", "document", "highlight")
        }
        for chunk in (response_json.get("chunks") or [])
    ]
    doc_aggs = [
        {"doc_name": agg.get("doc_name"), "count": agg.get("count")}
        for agg in (response_json.get("doc_aggs") or [])[:10]
        if isinstance(agg, dict)
    ]

    return success_response(data={
        "question": response_json.get("question") or question,
        "total": response_json.get("total") or 0,
        "returned": response_json.get("returned") or 0,
        "chunks": chunks,
        "doc_aggs": doc_aggs,
    })


class AsrRequest(BaseModel):
    audio: str  # data:audio/wav;base64,...
    language: Optional[str] = "auto"


@admin_router.post("/asr", summary="MiMo 语音转写（mdebug-code 语音输入用）")
async def vibe_coding_asr(
    body: AsrRequest,
    request: Request,
    x_api_key: str = Header(..., description="JWT token as Anthropic API key"),
    x_device_fp: Optional[str] = Header(
        None, alias="x-device-fp",
        description="设备指纹(sha-256 hex),与 token 内 dfp claim 绑定校验",
    ),
    session: Session = Depends(get_db),
):
    """mdebug-code 端语音输入的后端入口。

    复用 vibe-coding 的 JWT 鉴权 + 权限/额度校验，把 WAV（base64 data URL）
    转发给上游 `mimo-v2.5-asr` 的 OpenAI 兼容 `/chat/completions`，归一化返回
    `{text}` 给 CLI。上游 key 存服务端（`MIMO_ASR_API_KEY`），CLI 不持有。
    """
    # 1. 验 JWT
    try:
        payload = decode_token(x_api_key)
    except Exception:
        return error_response(message="Invalid or expired token, please restart terminal", code=401)

    if payload.get("type") != "access":
        return error_response(message="Invalid token type", code=401)

    user_id = payload.get("user_id")
    if not user_id:
        return error_response(message="Invalid token payload", code=401)

    try:
        payload = _verify_and_renew_token(payload, session, x_device_fp)
    except UnauthorizedException as exc:
        return error_response(message=str(exc), code=401)

    username = payload.get("username", "unknown")

    # 2. 仅校验访问权限（功能开关 + 白名单），不计入也不受每日额度限制——
    #    语音转写按设计不扣 vibe-coding 用量额度，额度满的用户也能用。
    user_group_ids = VibeCodingService.get_user_group_ids(session, user_id)
    access = VibeCodingService.check_access(session, user_id, user_group_ids)
    if not access["allowed"]:
        return error_response(message=access["reason"], code=403)

    audio = (body.audio or "").strip()
    if not audio:
        return error_response(message="audio 不能为空", code=400)

    if not settings.MIMO_ASR_API_KEY:
        return error_response(message="后端未配置 MIMO_ASR_API_KEY", code=503)

    language = (body.language or "auto").strip() or "auto"
    ip_address = get_client_ip(request)
    upstream_url = f"{settings.MIMO_ASR_BASE_URL.rstrip('/')}/chat/completions"
    upstream_payload = {
        "model": settings.MIMO_ASR_MODEL,
        "messages": [
            {"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": audio}}]},
        ],
        "asr_options": {"language": language},
        "stream": True,
    }
    headers = {
        "api-key": settings.MIMO_ASR_API_KEY,
        "Content-Type": "application/json",
        "X-Mimo-Source": "mdebug-code",
    }

    client: httpx.AsyncClient = request.app.state.ai_http_client
    timeout = httpx.Timeout(settings.MIMO_ASR_TIMEOUT, connect=10.0)

    async def stream_generator():
        """打开上游 SSE，原样透传 OpenAI 风格的 data: 行给 CLI；
        CLI 端自行解析 choices[].delta.content 算增量。流结束记一次调用
        日志（不扣 vibe-coding 额度），上游报错则下发一条 data: {error} 行。"""
        success = False
        chars = 0
        try:
            async with client.stream(
                "POST", upstream_url, json=upstream_payload, headers=headers, timeout=timeout,
            ) as response:
                if not response.is_success:
                    err_body = (await response.aread()).decode("utf-8", "replace")
                    save_error_request_log(
                        request_payload={"model": settings.MIMO_ASR_MODEL, "language": language},
                        response_status=response.status_code,
                        response_body=err_body,
                        error_type="mimo_asr",
                        user_id=user_id,
                        extra_info={"username": username},
                    )
                    payload_err = json.dumps(
                        {"error": f"上游 ASR 接口错误: {response.status_code}"},
                        ensure_ascii=False,
                    )
                    yield f"data: {payload_err}\n\n".encode("utf-8")
                    return
                async for chunk in response.aiter_bytes():
                    chars += len(chunk)
                    yield chunk
                success = True
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            logger.warning("MiMo ASR stream transport error", user_id=user_id, error=repr(exc))
            payload_err = json.dumps({"error": "语音转写失败，请稍后再试"}, ensure_ascii=False)
            yield f"data: {payload_err}\n\n".encode("utf-8")
        finally:
            # 语音转写免费（不扣 credits），仅记账用于后台统计。
            record_ai_request(
                user_id=user_id, module_name="mimo-asr", model=settings.MIMO_ASR_MODEL,
                prompt_tokens=0, completion_tokens=0,
                success=success, ip_address=ip_address,
            )
            logger.info(
                "MiMo ASR stream completed",
                user_id=user_id, username=username, success=success, bytes=chars,
            )

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )



class IssueTokenRequest(BaseModel):
    channel_id: int  # 兼容旧字段，等同于 main_channel_id
    main_channel_id: Optional[int] = None
    # 客户端设备指纹(sha-256 hex,小写)。提供则编入 token 的 dfp claim,
    # 此后每个请求的 x-device-fp 头必须与之一致,换机器重放直接被吊销。
    # 缺省/非法值 = 不绑定(兼容旧客户端)。
    device_fp: Optional[str] = None


@admin_router.post("/token", summary="签发 Code Assistant 专用长期 token")
def issue_vibe_coding_token(
    body: IssueTokenRequest,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access_payload: dict = Depends(verify_token_only),
):
    """
    签发 vibe-coding 专用 token(有效期 `VIBE_CODING_TOKEN_EXPIRE_HOURS`,
    默认 24 小时;CLI 每次启动重新换发)。
    Payload 同时编入 main_channel_id 与 subagent_channel_id（如已启用），
    后端代理端点据 `x-motordebug-agent-role` header 选择目标渠道。
    请求体可带 device_fp(sha-256 hex)将 token 绑定到签发设备。
    """
    user_group_ids = VibeCodingService.get_user_group_ids(session, current_user.id)
    perm = VibeCodingService.check_permission(session, current_user.id, user_group_ids)
    if not perm["allowed"]:
        return error_response(message=perm["reason"])

    main_id = body.main_channel_id or body.channel_id
    main_channel = VibeCodingService.get_channel_by_id(session, main_id)
    if not main_channel:
        return error_response(message="主代理渠道不存在")
    if not main_channel.enabled:
        return error_response(message="所选主代理渠道已被禁用")
    if main_channel.channel_type != "main":
        return error_response(message="所选渠道不是主代理类型")
    # 档位权限闭环：防止绕过 channels/available 过滤，对无权档位渠道直接签 token
    if not VibeCodingService.is_channel_tier_visible(
        session, main_channel, current_user.id, user_group_ids, current_user.email or ""
    ):
        return error_response(message="无权使用所选渠道")

    subagent_channel = VibeCodingService.get_active_subagent_channel(session)

    # payload 最小化:不再携带 username/role/is_active(token 是 base64 明文,
    # 抓到就能解;身份信息一律运行期从 DB 取,见 vibe_token_guard 的补全逻辑)。
    token_payload = {
        "user_id": current_user.id,
        # 继承请求方 access token 的版本而非用户当前值：vibe token 属于签发它的
        # 那台设备会话，多端场景下取当前值会让旧设备的 vibe token 挤占最新窗口槽位
        "token_version": access_payload.get("token_version", current_user.token_version),
        "purpose": "vibe-coding",
        "jti": uuid.uuid4().hex,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        # 兼容旧解析：vibe_channel_id 仍指向 main
        "vibe_channel_id": main_channel.id,
        "main_channel_id": main_channel.id,
        "subagent_channel_id": subagent_channel.id if subagent_channel else None,
    }
    device_fp = normalize_device_fp(body.device_fp)
    if device_fp:
        token_payload["dfp"] = device_fp
    token = create_access_token(
        data=token_payload,
        expires_delta=timedelta(hours=settings.VIBE_CODING_TOKEN_EXPIRE_HOURS),
    )
    # 对外只返回抽象标签，真实 model_id 永不出服务端；转发端按 token 绑定渠道权威计费/路由。
    return success_response(data={
        "token": token,
        "main": {
            "channel_id": main_channel.id,
            "protocol": main_channel.protocol,
            "model": VibeCodingService.public_model_label(session, main_channel),
            "context_window": VibeCodingService.channel_context_window(session, main_channel),
        },
        "subagent": (
            {
                "channel_id": subagent_channel.id,
                "protocol": subagent_channel.protocol,
                "model": VibeCodingService.public_model_label(session, subagent_channel),
                "context_window": VibeCodingService.channel_context_window(session, subagent_channel),
            }
            if subagent_channel
            else None
        ),
    })


@admin_router.post("/token/revoke", summary="吊销当前 vibe-coding token")
def revoke_vibe_coding_token(
    x_api_key: str = Header(..., description="要吊销的 vibe token 本身"),
    session: Session = Depends(get_db),
):
    """
    自助吊销:把 x-api-key 里这枚 token 的 jti 写入吊销表,即刻全端点失效。
    CLI `logout` 时调用;token 已过期/不合法时视为成功(幂等,revoked=false)。
    旧格式 token 无 jti,无法定点吊销(revoked=false),等自然过期或重登录。
    """
    try:
        payload = decode_token(x_api_key)
    except Exception:
        return success_response(data={"revoked": False})
    if payload.get("purpose") != "vibe-coding":
        return error_response(message="Not a vibe-coding token", code=400)
    jti = payload.get("jti")
    if not jti:
        return success_response(data={"revoked": False})
    revoke_token(
        session,
        jti=jti,
        user_id=payload.get("user_id") or 0,
        exp=payload.get("exp"),
        reason="manual",
    )
    return success_response(data={"revoked": True})


# ============================================================================
# claw.exe 代理路由
# ============================================================================

proxy_router = APIRouter(prefix="/claude/vibe-coding/v1", tags=["Code Assistant Proxy"])


def _verify_and_renew_token(
    payload: dict, session: Session, device_fp: Optional[str] = None
) -> dict:
    """校验 vibe token。逻辑收敛在 services/vibe_token_guard.py(gpt_proxy 同用):
    purpose 隔离 + 用户有效性 + token_version + jti 吊销 + 设备指纹绑定。"""
    return verify_vibe_token(payload, session, device_fp)


def _new_request_id(request: Request) -> str:
    """生成本次请求的全链路 id（与网关一致）。复用入站 x-request-id，否则 req_<uuid4hex>。"""
    incoming = request.headers.get("x-request-id")
    if incoming and incoming.strip():
        return incoming.strip()[:64]
    return f"req_{uuid.uuid4().hex}"


def _anthropic_error_response(
    status_code: int, error_type: str, message: str,
    request_id: Optional[str] = None,
) -> JSONResponse:
    """返回 Anthropic 格式的错误响应，让 claw.exe 能正确解析。
    带上 x-request-id 头便于用户报错时引用、后台全链路排查。"""
    return JSONResponse(
        status_code=status_code,
        content={
            "type": "error",
            "error": {
                "type": error_type,
                "message": message,
            }
        },
        headers={"x-request-id": request_id} if request_id else None,
    )


async def _post_to_skillclaw(
    client: httpx.AsyncClient,
    session_id: str,
    session_done: bool,
    request_data: dict,
    response_body: dict,
    user_alias: str,
    user_id: str = "",
):
    """Fire-and-forget：把一次 vibe-coding 对话投递给本地 SkillClaw 记录/进化。

    这是一条非阻塞旁路——只在响应已产出后异步触发，任何异常都仅记日志、
    绝不影响主代理链路（仿 record_ai_request 的“副作用不影响主链路”惯例）。
    """
    if not settings.SKILLCLAW_INGEST_ENABLED:
        return
    try:
        headers = {"Content-Type": "application/json"}
        if settings.SKILLCLAW_INGEST_TOKEN:
            headers["x-api-key"] = settings.SKILLCLAW_INGEST_TOKEN
        await client.post(
            settings.SKILLCLAW_INGEST_URL,
            json={
                "session_id": session_id,
                "session_done": session_done,
                "user_id": user_id,
                "user_alias": user_alias,
                "request": request_data,
                "response": response_body,
            },
            headers=headers,
            timeout=httpx.Timeout(settings.SKILLCLAW_INGEST_TIMEOUT, connect=2.0),
        )
        logger.info("SkillClaw ingest sent", session_id=session_id, session_done=session_done)
    except Exception as e:
        logger.warning("SkillClaw ingest failed", error=str(e), session_id=session_id)


def _accumulate_anthropic_stream(assistant_blocks: dict, data: dict) -> None:
    """累积 Anthropic SSE 事件，重建 assistant 的 content blocks（text + tool_use）。

    ``assistant_blocks`` 形如 ``{index: block_dict}``，在流结束后转成
    ``{"role":"assistant","content":[...]}`` 投递给 SkillClaw。
    """
    etype = data.get("type")
    if etype == "content_block_start":
        idx = data.get("index", 0)
        block = data.get("content_block") or {}
        btype = block.get("type")
        if btype == "text":
            assistant_blocks[idx] = {"type": "text", "text": block.get("text", "")}
        elif btype == "thinking":
            assistant_blocks[idx] = {"type": "thinking", "thinking": block.get("thinking", "")}
        elif btype == "tool_use":
            assistant_blocks[idx] = {
                "type": "tool_use",
                "id": block.get("id", ""),
                "name": block.get("name", ""),
                "_input_json": "",
            }
    elif etype == "content_block_delta":
        idx = data.get("index", 0)
        delta = data.get("delta") or {}
        dtype = delta.get("type")
        block = assistant_blocks.get(idx)
        if block is None:
            return
        if dtype == "text_delta":
            block["text"] = block.get("text", "") + delta.get("text", "")
        elif dtype == "thinking_delta":
            block["thinking"] = block.get("thinking", "") + delta.get("thinking", "")
        elif dtype == "input_json_delta":
            block["_input_json"] = block.get("_input_json", "") + delta.get("partial_json", "")


def _finalize_anthropic_blocks(assistant_blocks: dict) -> dict:
    """把累积的 blocks 收尾成一个 Anthropic message dict（解析 tool_use 的 JSON 入参）。"""
    content = []
    for idx in sorted(assistant_blocks.keys()):
        block = assistant_blocks[idx]
        if block.get("type") == "tool_use":
            raw = block.pop("_input_json", "") or "{}"
            try:
                block["input"] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                block["input"] = {}
        content.append(block)
    return {"role": "assistant", "content": content}


@proxy_router.post("/messages", summary="Code Assistant Messages Proxy")
async def vibe_coding_messages(
    request: Request,
    x_api_key: str = Header(..., description="JWT token as Anthropic API key"),
    x_device_fp: Optional[str] = Header(
        None, alias="x-device-fp",
        description="设备指纹(sha-256 hex),与 token 内 dfp claim 绑定校验",
    ),
    x_motordebug_agent_role: str = Header(
        "main", description="Agent 角色：main / subagent，决定使用 JWT 中哪一个 channel_id"
    ),
    x_session_id: Optional[str] = Header(None, description="mdebug-code 注入的稳定会话 id（SkillClaw 旁路用）"),
    x_session_done: Optional[str] = Header(None, description="会话结束标志（SkillClaw 旁路用）"),
    session: Session = Depends(get_db),
):
    """
    claw.exe 的代理端点（Anthropic 协议）。
    从 x-api-key header 提取 JWT，按 x-motordebug-agent-role 选择主/子代理 channel，
    检查权限和额度，然后转发到上游 Anthropic 兼容 API。
    """
    # 0. 全链路请求 id：贯穿 ai_requests / error_request_logs / credits 流水，并回传响应头
    request_id = _new_request_id(request)

    # 1. 验证 JWT
    try:
        payload = decode_token(x_api_key)
    except Exception:
        return _anthropic_error_response(401, "authentication_error", "Invalid or expired token, please restart terminal", request_id)

    if payload.get("type") != "access":
        return _anthropic_error_response(401, "authentication_error", "Invalid token type", request_id)

    user_id = payload.get("user_id")
    if not user_id:
        return _anthropic_error_response(401, "authentication_error", "Invalid token payload", request_id)

    # 2. 验证用户有效性（token 可能已过期，需确认用户仍有效）
    try:
        payload = _verify_and_renew_token(payload, session, x_device_fp)
    except UnauthorizedException as e:
        return _anthropic_error_response(401, "authentication_error", str(e), request_id)

    username = payload.get("username", "unknown")

    # 3. 权限 + 额度检查
    user_group_ids = VibeCodingService.get_user_group_ids(session, user_id)
    perm = VibeCodingService.check_permission(session, user_id, user_group_ids)

    if not perm["allowed"]:
        return _anthropic_error_response(403, "permission_error", perm["reason"], request_id)

    # 4. 读取原始请求体
    body = await request.body()
    try:
        request_data = json.loads(body)
    except json.JSONDecodeError:
        return _anthropic_error_response(400, "invalid_request_error", "Invalid JSON body", request_id)

    model = request_data.get("model", "unknown")
    is_stream = request_data.get("stream", False)
    ip_address = get_client_ip(request)

    # 4.5 内容安全过滤（GB/T 45654）：命中即按 Anthropic 协议正常响应格式拒答，
    #     不转发上游、不扣费、不投递 SkillClaw。model 此处为客户端自报值
    #     （5.5 才覆盖为 channel.model），拒答留痕允许记自报值。
    user_text = content_safety.extract_latest_user_text(request_data, "anthropic")
    verdict = await content_safety.screen_text(
        None, user_text, use_llm=settings.CONTENT_SAFETY_LLM_CODING_ENABLED,
    )
    if verdict.blocked:
        content_safety.record_block(
            user_id, "vibe-coding", model, verdict, ip_address, request_id, user_text,
        )
        return build_refusal_response("anthropic", is_stream, model, request_id)

    # SkillClaw 旁路：稳定会话 id 优先取 客户端注入的 x-session-id，
    # 缺失时退化为按用户滚动的会话（靠 SkillClaw idle 心跳兜底切分）。
    skillclaw_session_id = (x_session_id or "").strip() or f"motordebug-user-{user_id}"
    skillclaw_session_done = str(x_session_done or "").strip().lower() in ("1", "true", "yes")

    agent_role = (x_motordebug_agent_role or "main").lower()
    if agent_role not in ("main", "subagent"):
        agent_role = "main"

    logger.info(
        "Code assistant proxy request",
        request_id=request_id,
        user_id=user_id,
        username=username,
        model=model,
        stream=is_stream,
        agent_role=agent_role,
    )

    # 5. 根据 role 选择 channel
    if agent_role == "subagent":
        channel_id = payload.get("subagent_channel_id")
        if not channel_id:
            return _anthropic_error_response(
                400, "invalid_request_error",
                "Token 缺少子代理渠道信息（未启用子代理渠道）", request_id
            )
    else:
        channel_id = payload.get("main_channel_id") or payload.get("vibe_channel_id")
        if not channel_id:
            return _anthropic_error_response(
                400, "invalid_request_error",
                "Token 缺少主代理渠道信息，请重启终端", request_id
            )

    channel = VibeCodingService.get_channel_by_id(session, channel_id)
    if not channel or not channel.enabled:
        return _anthropic_error_response(
            404, "api_error",
            "所选渠道已不可用，请重新选择", request_id
        )
    if channel.protocol != "anthropic":
        return _anthropic_error_response(
            400, "invalid_request_error",
            f"渠道协议不匹配（期望 anthropic，实际 {channel.protocol}）", request_id
        )

    # 5.5 权威化 model：计费/路由只认 token 绑定渠道的 channel.model，不信客户端请求体。
    #     客户端拿到的可能是抽象档位标签（display_name/description），据此无法计费，
    #     且信任客户端 model 会留下自报模型绕过档位/倍率的漏洞。这里统一覆盖：
    #       - 计费用 channel.model（档位则为档位 model_id → 套档位倍率）；
    #       - 转发上游用 resolve_model_name(channel.model)（档位换成真实 upstream_model_id）。
    model = channel.model
    request_data["model"] = GatewayService.resolve_model_name(session, model)

    # 5.6 内置 skill 占位符展开：上游收展开后的副本（无占位符时就是原对象），
    #     request_data 原件继续用于 SkillClaw 投递与错误日志——skill 正文
    #     不外送第三方、不落日志明文。
    user_row = session.get(User, user_id)
    upstream_payload = expand_skill_placeholders(
        session, request_data, protocol="anthropic",
        user_id=user_id, user_group_ids=user_group_ids,
        user_email=(user_row.email if user_row else "") or "",
        request_id=request_id, agent_role=agent_role,
    )

    # 6. 构造上游请求
    upstream_url = f"{channel.base_url}/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": channel.api_key,
        "anthropic-version": "2023-06-01",
    }

    # 转发客户端的 anthropic-version header（如果有的话）
    client_version = request.headers.get("anthropic-version")
    if client_version:
        headers["anthropic-version"] = client_version

    # 转发 anthropic-beta header（如果有的话）
    client_beta = request.headers.get("anthropic-beta")
    if client_beta:
        headers["anthropic-beta"] = client_beta

    client = request.app.state.ai_http_client

    # 6. 转发请求
    max_retries = 3
    last_exception = None

    for attempt in range(1, max_retries + 1):
        try:
            if is_stream:
                return await _handle_streaming(
                    client, upstream_payload, headers, upstream_url,
                    user_id, username, ip_address, model, session,
                    skillclaw_session_id, skillclaw_session_done, request_id,
                    client_payload=request_data,
                )
            else:
                return await _handle_standard(
                    client, upstream_payload, headers, upstream_url,
                    user_id, username, ip_address, model, session,
                    skillclaw_session_id, skillclaw_session_done, request_id,
                    client_payload=request_data,
                )
        except httpx.TimeoutException as e:
            last_exception = e
            logger.warning("Code assistant proxy timeout", request_id=request_id, user_id=user_id, attempt=attempt)
        except httpx.HTTPStatusError as e:
            if 400 <= e.response.status_code < 500:
                save_error_request_log(
                    request_payload=request_data,
                    response_status=e.response.status_code,
                    response_body=e.response.text,
                    error_type="vibe_coding_proxy",
                    user_id=user_id,
                    extra_info={"username": username, "request_id": request_id},
                )
                record_ai_request(
                    user_id=user_id, module_name="vibe-coding", model=model,
                    prompt_tokens=0, completion_tokens=0, success=False,
                    error_message=f"HTTP {e.response.status_code}",
                    ip_address=ip_address, request_id=request_id,
                )
                return _anthropic_error_response(
                    e.response.status_code, "api_error",
                    f"Upstream error: {e.response.status_code}", request_id
                )
            last_exception = e
            logger.warning("Code assistant proxy HTTP error", request_id=request_id, user_id=user_id, status=e.response.status_code, attempt=attempt)
        except Exception as e:
            last_exception = e
            logger.warning("Code assistant proxy error", request_id=request_id, user_id=user_id, error=str(e), attempt=attempt)

        if attempt < max_retries:
            await asyncio.sleep(attempt)

    # 所有重试耗尽
    logger.error("Code assistant proxy failed after retries", request_id=request_id, user_id=user_id, error=str(last_exception))
    record_ai_request(
        user_id=user_id, module_name="vibe-coding", model=model,
        prompt_tokens=0, completion_tokens=0, success=False,
        error_message=str(last_exception), ip_address=ip_address, request_id=request_id,
    )
    return _anthropic_error_response(502, "api_error", "Failed to reach AI service after retries", request_id)


async def _handle_standard(
    client: httpx.AsyncClient,
    payload: dict,
    headers: dict,
    upstream_url: str,
    user_id: int,
    username: str,
    ip_address: str,
    model: str,
    session: Session,
    skillclaw_session_id: str = "",
    skillclaw_session_done: bool = False,
    request_id: Optional[str] = None,
    client_payload: Optional[dict] = None,
):
    """处理非流式请求，成功后递增额度。

    payload = 转发上游的（可能已做 skill 占位符展开）；client_payload = 客户端
    原始请求体，用于 SkillClaw 投递与错误日志（skill 正文不外送/不落盘）。
    """
    if client_payload is None:
        client_payload = payload
    response = await client.post(upstream_url, json=payload, headers=headers)

    if not response.is_success:
        save_error_request_log(
            request_payload=client_payload, response_status=response.status_code,
            response_body=response.text, error_type="vibe_coding_proxy",
            user_id=user_id, extra_info={"username": username, "request_id": request_id},
        )
        response.raise_for_status()

    result = response.json()
    usage = result.get("usage", {})
    cache_read_tokens = usage.get("cache_read_input_tokens", 0) or 0
    cache_creation_tokens = usage.get("cache_creation_input_tokens", 0) or 0
    # prompt_tokens 含普通输入及缓存读写，计费时按三类输入分别拆分。
    prompt_tokens = (usage.get("input_tokens", 0) or 0) + cache_read_tokens + cache_creation_tokens
    completion_tokens = usage.get("output_tokens", 0) or 0

    logger.info(
        "Code assistant proxy completed",
        request_id=request_id,
        user_id=user_id, username=username, model=model,
        input_tokens=prompt_tokens, output_tokens=completion_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
    )

    # 成功 → 记账 + 按 token×倍率扣 credits（统一 credits 池）
    GatewayService.record_and_charge(
        user_id=user_id, module_name="vibe-coding", model=model,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        cache_read_tokens=cache_read_tokens, ip_address=ip_address, success=True,
        request_id=request_id, cache_creation_tokens=cache_creation_tokens,
    )

    # 非阻塞旁路：把完整对话投递给 SkillClaw（失败不影响本次响应）
    if settings.SKILLCLAW_INGEST_ENABLED:
        _schedule_skillclaw(_post_to_skillclaw(
            client, skillclaw_session_id, skillclaw_session_done,
            client_payload, result, username, str(user_id),
        ))

    return JSONResponse(
        content=result,
        headers={"x-request-id": request_id} if request_id else None,
    )


async def _handle_streaming(
    client: httpx.AsyncClient,
    payload: dict,
    headers: dict,
    upstream_url: str,
    user_id: int,
    username: str,
    ip_address: str,
    model: str,
    session: Session,
    skillclaw_session_id: str = "",
    skillclaw_session_done: bool = False,
    request_id: Optional[str] = None,
    client_payload: Optional[dict] = None,
):
    """处理流式请求，完成后递增额度。

    IMPORTANT: 先 await upstream + 验证 status,再决定 JSONResponse 还是
    StreamingResponse。FastAPI 一旦返回 StreamingResponse,ASGI 立刻 commit
    `200 OK + Transfer-Encoding: chunked` 头,此后 generator 内 raise 只能
    硬关 socket,客户端会看到 `unexpected EOF during chunk size line` 而非
    上游真正的 4xx JSON。

    payload 为转发上游的（可能已做 skill 占位符展开）；client_payload 为客户端
    原件，用于 SkillClaw 投递与错误日志。
    """
    if client_payload is None:
        client_payload = payload

    upstream_request = client.build_request(
        "POST", upstream_url, json=payload, headers=headers
    )
    response = await client.send(upstream_request, stream=True)

    if not response.is_success:
        try:
            error_body = await response.aread()
        finally:
            await response.aclose()

        decoded = error_body.decode("utf-8", errors="replace")
        save_error_request_log(
            request_payload=client_payload,
            response_status=response.status_code,
            response_body=decoded,
            error_type="vibe_coding_proxy_stream",
            user_id=user_id,
            extra_info={"username": username, "request_id": request_id},
        )
        record_ai_request(
            user_id=user_id,
            module_name="vibe-coding",
            model=model,
            prompt_tokens=0,
            completion_tokens=0,
            success=False,
            error_message=f"upstream {response.status_code}",
            ip_address=ip_address,
            request_id=request_id,
        )

        try:
            forwarded = json.loads(decoded)
        except (json.JSONDecodeError, ValueError):
            forwarded = {
                "type": "error",
                "error": {
                    "type": "upstream_error",
                    "message": decoded[:500] if decoded else "upstream returned no body",
                },
            }
        return JSONResponse(
            status_code=response.status_code, content=forwarded,
            headers={"x-request-id": request_id} if request_id else None,
        )

    async def stream_generator():
        usage_info = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0}
        # SkillClaw 旁路：累积 assistant 的 content blocks（仅 INGEST 开启时）
        ingest_on = settings.SKILLCLAW_INGEST_ENABLED
        assistant_blocks: dict = {}
        # SSE 事件不一定与网络 chunk 对齐，用字节缓冲按完整行解析，避免事件被切断丢弃。
        sse_buf = b""

        def _process_sse_line(line_bytes: bytes) -> None:
            try:
                line = line_bytes.decode("utf-8").strip()
            except UnicodeDecodeError:
                return
            if not line.startswith("data:"):
                return
            raw = line[5:].strip()
            if not raw or raw == "[DONE]":
                return
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return
            etype = data.get("type")
            if etype == "message_start":
                msg_usage = data.get("message", {}).get("usage", {})
                usage_info["input_tokens"] = max(
                    usage_info["input_tokens"], msg_usage.get("input_tokens", 0) or 0
                )
                usage_info["cache_read_tokens"] = max(
                    usage_info["cache_read_tokens"],
                    msg_usage.get("cache_read_input_tokens", 0) or 0,
                )
                usage_info["cache_creation_tokens"] = max(
                    usage_info["cache_creation_tokens"],
                    msg_usage.get("cache_creation_input_tokens", 0) or 0,
                )
            elif etype == "message_delta":
                # 注意：该上游把最终准确 usage（含 input + cache）放在 message_delta，
                # message_start 的 input_tokens 多为 0，故这里一并兜底刷新。
                delta_usage = data.get("usage", {})
                usage_info["output_tokens"] = max(
                    usage_info["output_tokens"], delta_usage.get("output_tokens", 0) or 0
                )
                usage_info["input_tokens"] = max(
                    usage_info["input_tokens"], delta_usage.get("input_tokens", 0) or 0
                )
                usage_info["cache_read_tokens"] = max(
                    usage_info["cache_read_tokens"],
                    delta_usage.get("cache_read_input_tokens", 0) or 0,
                )
                usage_info["cache_creation_tokens"] = max(
                    usage_info["cache_creation_tokens"],
                    delta_usage.get("cache_creation_input_tokens", 0) or 0,
                )
            if ingest_on:
                _accumulate_anthropic_stream(assistant_blocks, data)

        try:
            async for chunk in response.aiter_bytes():
                yield chunk
                sse_buf += chunk
                while b"\n" in sse_buf:
                    line_bytes, sse_buf = sse_buf.split(b"\n", 1)
                    _process_sse_line(line_bytes)
        finally:
            await response.aclose()
            if sse_buf:
                _process_sse_line(sse_buf)

        # 流式完成 → 记账 + 按 token×倍率扣 credits（统一 credits 池）
        cache_read_tokens = usage_info["cache_read_tokens"]
        prompt_tokens = (
            usage_info["input_tokens"]
            + cache_read_tokens
            + usage_info["cache_creation_tokens"]
        )

        logger.info(
            "Code assistant streaming completed",
            request_id=request_id,
            user_id=user_id, username=username, model=model,
            input_tokens=prompt_tokens,
            output_tokens=usage_info["output_tokens"],
            cache_read_tokens=cache_read_tokens,
        )

        GatewayService.record_and_charge(
            user_id=user_id, module_name="vibe-coding", model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=usage_info["output_tokens"],
            cache_read_tokens=cache_read_tokens,
            ip_address=ip_address, success=True,
            request_id=request_id,
            cache_creation_tokens=usage_info["cache_creation_tokens"],
        )

        # 非阻塞旁路：流结束后把重建的完整对话投递给 SkillClaw
        if ingest_on and assistant_blocks:
            response_body = _finalize_anthropic_blocks(assistant_blocks)
            _schedule_skillclaw(_post_to_skillclaw(
                client, skillclaw_session_id, skillclaw_session_done,
                client_payload, response_body, username, str(user_id),
            ))
        elif ingest_on:
            logger.warning("SkillClaw ingest skipped: no assistant content blocks accumulated")

    stream_headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    if request_id:
        stream_headers["x-request-id"] = request_id
    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers=stream_headers,
    )
