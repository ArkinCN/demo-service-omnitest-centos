"""
GPT Proxy - 转发 OpenAI Responses API (/v1/responses)

claw.exe 在使用 OpenAI Responses 协议（如 gpt-5.5）时，
会向 `{OPENAI_BASE_URL}/responses` 发请求；本路由作为该端点的后端代理，
按 JWT payload 中的 main/subagent channel_id（由 `x-motordebug-agent-role` 选择）
查 VibeCodingChannel 表选定上游，注入上游 API Key 后转发。

认证：claw OpenAI compat 客户端把 API key 放在 `Authorization: Bearer <jwt>`。
协议校验：channel.protocol 必须为 'openai_responses'，否则 400。
"""
import json
import uuid
import asyncio
import httpx
from fastapi import APIRouter, Depends, Request, Header
from fastapi.responses import StreamingResponse, JSONResponse
from sqlmodel import Session
from structlog import get_logger

from app.api.deps import get_db
from app.core.config import settings
from app.core.security import decode_token
from app.services.vibe_token_guard import verify_vibe_token
from app.core.exceptions import UnauthorizedException
from app.models.user import User
from app.services.vibe_coding_service import VibeCodingService
from app.services.gateway_service import GatewayService
from app.services.skill_expansion import expand_skill_placeholders
from app.core.ai_recording import record_ai_request, get_client_ip
from app.core.error_logger import save_error_request_log
from app.services.content_safety_service import content_safety
from app.services.safety_responses import build_refusal_response


logger = get_logger(__name__)

proxy_router = APIRouter(prefix="/openai", tags=["GPT Proxy"])

# ChatGPT 账号版 Codex 上游不支持的请求参数，转发前剥离（claw 会固定带
# max_output_tokens）。如后续上游又挑别的字段毛病，往这里加即可。
UPSTREAM_UNSUPPORTED_PARAMS = ("max_output_tokens",)

# Strong refs to in-flight fire-and-forget SkillClaw tasks (else the event loop
# may GC them before they run).
_skillclaw_bg_tasks: set = set()


def _schedule_skillclaw(coro):
    task = asyncio.create_task(coro)
    _skillclaw_bg_tasks.add(task)
    task.add_done_callback(_skillclaw_bg_tasks.discard)


async def _post_to_skillclaw(
    session_id: str,
    session_done: bool,
    request_data: dict,
    response_body: dict,
    user_alias: str,
    user_id: str = "",
):
    """Fire-and-forget: feed one OpenAI Responses exchange to local SkillClaw.

    Non-blocking side path — runs only after the response is produced; any error
    is logged and never affects the proxy. Mirrors the Anthropic path in
    vibe_coding.py but tags protocol=openai_responses so SkillClaw parses the
    Responses request/response shape.
    """
    if not settings.SKILLCLAW_INGEST_ENABLED:
        return
    try:
        headers = {"Content-Type": "application/json"}
        if settings.SKILLCLAW_INGEST_TOKEN:
            headers["x-api-key"] = settings.SKILLCLAW_INGEST_TOKEN
        async with httpx.AsyncClient() as client:
            await client.post(
                settings.SKILLCLAW_INGEST_URL,
                json={
                    "session_id": session_id,
                    "session_done": session_done,
                    "protocol": "openai_responses",
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


def _openai_error_response(status_code: int, error_type: str, message: str) -> JSONResponse:
    """返回 OpenAI 风格错误"""
    return JSONResponse(
        status_code=status_code,
        content={"error": {"type": error_type, "message": message}},
    )


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip()


def _new_request_id(request: Request) -> str:
    """本次请求的全链路 id（与 vibe_coding 一致）：复用入站 x-request-id，否则 req_<uuid4hex>。"""
    incoming = request.headers.get("x-request-id")
    if incoming and incoming.strip():
        return incoming.strip()[:64]
    return f"req_{uuid.uuid4().hex}"


def _verify_and_renew_token(
    payload: dict, session: Session, device_fp=None
) -> dict:
    """校验 vibe token。逻辑与 vibe_coding.py 共用 services/vibe_token_guard.py:
    purpose 隔离 + 用户有效性 + token_version + jti 吊销 + 设备指纹绑定。"""
    return verify_vibe_token(payload, session, device_fp)


async def _prepare_openai_proxy(
    request: Request, authorization: str | None,
    x_motordebug_agent_role: str, x_session_id: str | None, x_session_done: str | None,
    session: Session, expected_protocol: str, upstream_path: str,
    inject_include_usage: bool = False,
):
    """openai_responses 与 openai_chat 两条 vibe 代理共用的前导。

    鉴权(令牌隔离,purpose=vibe-coding)→ 权限/额度 → 按 role 选 channel → 协议校验
    → model 权威化(channel.model + resolve_model_name)→ 拼上游 URL/headers。
    返回 (ctx, None) 或 (None, error_response)。
    """
    token = _extract_bearer_token(authorization)
    if not token:
        return None, _openai_error_response(401, "authentication_error", "Missing Bearer token")
    try:
        payload = decode_token(token)
    except Exception:
        return None, _openai_error_response(401, "authentication_error", "Invalid or expired token, please restart terminal")
    if payload.get("type") != "access":
        return None, _openai_error_response(401, "authentication_error", "Invalid token type")
    user_id = payload.get("user_id")
    if not user_id:
        return None, _openai_error_response(401, "authentication_error", "Invalid token payload")
    try:
        payload = _verify_and_renew_token(
            payload, session, request.headers.get("x-device-fp")
        )
    except UnauthorizedException as e:
        return None, _openai_error_response(401, "authentication_error", str(e))
    username = payload.get("username", "unknown")

    user_group_ids = VibeCodingService.get_user_group_ids(session, user_id)
    perm = VibeCodingService.check_permission(session, user_id, user_group_ids)
    if not perm["allowed"]:
        return None, _openai_error_response(403, "permission_error", perm["reason"])

    body = await request.body()
    try:
        request_data = json.loads(body)
    except json.JSONDecodeError:
        return None, _openai_error_response(400, "invalid_request_error", "Invalid JSON body")

    model = request_data.get("model", "unknown")
    is_stream = bool(request_data.get("stream", True))
    ip_address = get_client_ip(request)
    request_id = _new_request_id(request)

    # 内容安全过滤（GB/T 45654）：命中即按本协议正常响应格式拒答，
    # 不转发上游、不扣费、不投递 SkillClaw。model 此处为客户端自报值
    # （后面才覆盖为 channel.model），拒答留痕允许记自报值。
    user_text = content_safety.extract_latest_user_text(request_data, expected_protocol)
    verdict = await content_safety.screen_text(
        None, user_text, use_llm=settings.CONTENT_SAFETY_LLM_CODING_ENABLED,
    )
    if verdict.blocked:
        content_safety.record_block(
            user_id, "vibe-coding", model, verdict, ip_address, request_id, user_text,
        )
        return None, build_refusal_response(expected_protocol, is_stream, model, request_id)

    # ChatGPT 账号版 Codex 上游不接受 max_output_tokens 等参数，转发前剥离（chat 无此参数则无操作）。
    stripped = [k for k in UPSTREAM_UNSUPPORTED_PARAMS if request_data.pop(k, None) is not None]
    if stripped:
        logger.info("GPT proxy stripped unsupported params", request_id=request_id, stripped=stripped, model=model)

    agent_role = (x_motordebug_agent_role or "main").lower()
    if agent_role not in ("main", "subagent"):
        agent_role = "main"
    skillclaw_session_id = (x_session_id or "").strip() or f"motordebug-user-{user_id}"
    skillclaw_session_done = str(x_session_done or "").strip().lower() in ("1", "true", "yes")

    logger.info(
        "GPT proxy request", request_id=request_id,
        user_id=user_id, username=username, model=model,
        stream=is_stream, agent_role=agent_role, protocol=expected_protocol,
    )

    if agent_role == "subagent":
        channel_id = payload.get("subagent_channel_id")
        if not channel_id:
            return None, _openai_error_response(400, "invalid_request_error", "Token 缺少子代理渠道信息（未启用子代理渠道）")
    else:
        channel_id = payload.get("main_channel_id") or payload.get("vibe_channel_id")
        if not channel_id:
            return None, _openai_error_response(400, "invalid_request_error", "Token 缺少主代理渠道信息，请重启终端")

    channel = VibeCodingService.get_channel_by_id(session, channel_id)
    if not channel or not channel.enabled:
        return None, _openai_error_response(404, "api_error", "所选渠道已不可用，请重新选择")
    if channel.protocol != expected_protocol:
        return None, _openai_error_response(
            400, "invalid_request_error",
            f"渠道协议不匹配（期望 {expected_protocol}，实际 {channel.protocol}）",
        )

    # 权威化 model + 档位路由：计费/路由只认 token 绑定渠道的 channel.model，不信客户端。
    model = channel.model
    request_data["model"] = GatewayService.resolve_model_name(session, model)

    # openai chat 流式默认末块无 usage，须显式要求（同网关），否则 0 计费。
    if inject_include_usage and is_stream:
        opts = request_data.get("stream_options")
        if not isinstance(opts, dict):
            opts = {}
        opts["include_usage"] = True
        request_data["stream_options"] = opts

    # 内置 skill 占位符展开：上游收展开后的副本（无占位符时就是原对象），
    # request_data 原件继续用于 SkillClaw 投递与错误日志（正文不外送/不落明文）。
    # 必须放在所有 request_data 原地改写之后——展开命中时返回的是深拷贝，
    # 之后再改 request_data 不会反映到上游 payload。
    user_row = session.get(User, user_id)
    upstream_payload = expand_skill_placeholders(
        session, request_data, protocol=expected_protocol,
        user_id=user_id, user_group_ids=user_group_ids,
        user_email=(user_row.email if user_row else "") or "",
        request_id=request_id, agent_role=agent_role,
    )

    upstream_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {channel.api_key}",
    }
    for h in ("originator", "user-agent", "session_id"):
        v = request.headers.get(h)
        if v:
            upstream_headers[h] = v

    ctx = {
        "request_data": upstream_payload, "client_payload": request_data,
        "model": model, "is_stream": is_stream,
        "ip_address": ip_address, "request_id": request_id, "username": username,
        "user_id": user_id, "session": session,
        "skillclaw_session_id": skillclaw_session_id, "skillclaw_session_done": skillclaw_session_done,
        "upstream_url": f"{channel.base_url}/{upstream_path}", "upstream_headers": upstream_headers,
    }
    return ctx, None


async def _run_proxy_retry(client, ctx: dict, handle_stream, handle_standard):
    """转发 + 3 次重试（仅超时/网络错，4xx 不重试）+ 记账。两条代理共用。"""
    rd = ctx["request_data"]; uh = ctx["upstream_headers"]; uu = ctx["upstream_url"]
    cp = ctx.get("client_payload", rd)
    user_id = ctx["user_id"]; username = ctx["username"]; ip_address = ctx["ip_address"]
    model = ctx["model"]; session = ctx["session"]; request_id = ctx["request_id"]
    sid = ctx["skillclaw_session_id"]; sdone = ctx["skillclaw_session_done"]
    handler = handle_stream if ctx["is_stream"] else handle_standard

    max_retries = 3
    last_exception = None
    for attempt in range(1, max_retries + 1):
        try:
            return await handler(
                client, rd, uh, uu, user_id, username, ip_address, model, session,
                sid, sdone, request_id, client_payload=cp,
            )
        except httpx.TimeoutException as e:
            last_exception = e
            logger.warning("GPT proxy timeout", request_id=request_id, user_id=user_id, attempt=attempt)
        except httpx.HTTPStatusError as e:
            if 400 <= e.response.status_code < 500:
                save_error_request_log(
                    request_payload=cp, response_status=e.response.status_code,
                    response_body=e.response.text, error_type="gpt_proxy",
                    user_id=user_id, extra_info={"username": username},
                )
                record_ai_request(
                    user_id=user_id, module_name="vibe-coding", model=model,
                    prompt_tokens=0, completion_tokens=0, success=False,
                    error_message=f"HTTP {e.response.status_code}",
                    ip_address=ip_address, request_id=request_id,
                )
                return _openai_error_response(
                    e.response.status_code, "api_error",
                    f"Upstream error: {e.response.status_code}",
                )
            last_exception = e
            logger.warning("GPT proxy HTTP error", request_id=request_id, user_id=user_id, status=e.response.status_code, attempt=attempt)
        except Exception as e:
            last_exception = e
            logger.warning("GPT proxy error", request_id=request_id, user_id=user_id, error=str(e), attempt=attempt)
        if attempt < max_retries:
            await asyncio.sleep(attempt)

    logger.error("GPT proxy failed after retries", request_id=request_id, user_id=user_id, error=str(last_exception))
    record_ai_request(
        user_id=user_id, module_name="vibe-coding", model=model,
        prompt_tokens=0, completion_tokens=0, success=False,
        error_message=str(last_exception), ip_address=ip_address, request_id=request_id,
    )
    return _openai_error_response(502, "api_error", "Upstream unavailable after retries")


@proxy_router.post("/responses", summary="OpenAI Responses Proxy")
async def gpt_responses(
    request: Request,
    authorization: str | None = Header(None, description="Bearer <jwt>"),
    x_motordebug_agent_role: str = Header("main", description="Agent 角色：main / subagent"),
    x_session_id: str | None = Header(None, alias="x-session-id"),
    x_session_done: str | None = Header(None, alias="x-session-done"),
    session: Session = Depends(get_db),
):
    ctx, err = await _prepare_openai_proxy(
        request, authorization, x_motordebug_agent_role, x_session_id, x_session_done,
        session, "openai_responses", "responses",
    )
    if err:
        return err
    return await _run_proxy_retry(
        request.app.state.ai_http_client, ctx, _handle_streaming, _handle_standard,
    )


@proxy_router.post("/chat/completions", summary="OpenAI Chat Completions Proxy")
async def gpt_chat_completions(
    request: Request,
    authorization: str | None = Header(None, description="Bearer <jwt>"),
    x_motordebug_agent_role: str = Header("main", description="Agent 角色：main / subagent"),
    x_session_id: str | None = Header(None, alias="x-session-id"),
    x_session_done: str | None = Header(None, alias="x-session-done"),
    session: Session = Depends(get_db),
):
    ctx, err = await _prepare_openai_proxy(
        request, authorization, x_motordebug_agent_role, x_session_id, x_session_done,
        session, "openai_chat", "chat/completions", inject_include_usage=True,
    )
    if err:
        return err
    return await _run_proxy_retry(
        request.app.state.ai_http_client, ctx, _handle_chat_streaming, _handle_chat_standard,
    )


async def _handle_standard(client, payload, headers, upstream_url,
                           user_id, username, ip_address, model, session,
                           skillclaw_session_id="", skillclaw_session_done=False,
                           request_id=None, client_payload=None):
    # payload = 转发上游的（可能已做 skill 占位符展开）；client_payload = 客户端
    # 原件，用于 SkillClaw 投递与错误日志（skill 正文不外送/不落盘）。
    if client_payload is None:
        client_payload = payload
    response = await client.post(upstream_url, json=payload, headers=headers)
    if not response.is_success:
        save_error_request_log(
            request_payload=client_payload, response_status=response.status_code,
            response_body=response.text, error_type="gpt_proxy",
            user_id=user_id, extra_info={"username": username},
        )
        response.raise_for_status()
    result = response.json()
    # Non-blocking side path: feed the completed exchange to SkillClaw.
    _schedule_skillclaw(_post_to_skillclaw(
        skillclaw_session_id, skillclaw_session_done,
        client_payload, result, username, str(user_id),
    ))
    # OpenAI Responses 协议的 usage 字段在 response.completed 事件或最终 JSON 中
    # 这里非流式响应直接读 result["usage"]
    usage = result.get("usage", {}) or {}
    details = usage.get("input_tokens_details", {}) or {}
    cache_read_tokens = details.get("cached_tokens", 0) or 0
    cache_creation_tokens = details.get("cache_write_tokens", 0) or 0
    prompt_tokens = usage.get("input_tokens", 0) or 0
    completion_tokens = usage.get("output_tokens", 0) or 0
    # 成功 → 记账 + 按 token×倍率扣 credits（统一 credits 池）
    GatewayService.record_and_charge(
        user_id=user_id, module_name="vibe-coding", model=model,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        cache_read_tokens=cache_read_tokens, ip_address=ip_address, success=True,
        request_id=request_id, cache_creation_tokens=cache_creation_tokens,
    )
    return result


async def _handle_streaming(client, payload, headers, upstream_url,
                            user_id, username, ip_address, model, session,
                            skillclaw_session_id="", skillclaw_session_done=False,
                            request_id=None, client_payload=None):
    """SSE 透传，从 response.completed 事件抓 usage"""
    if client_payload is None:
        client_payload = payload
    upstream_request = client.build_request("POST", upstream_url, json=payload, headers=headers)
    response = await client.send(upstream_request, stream=True)

    if not response.is_success:
        try:
            error_body = await response.aread()
        finally:
            await response.aclose()
        decoded = error_body.decode("utf-8", errors="replace")
        save_error_request_log(
            request_payload=client_payload, response_status=response.status_code,
            response_body=decoded, error_type="gpt_proxy_stream",
            user_id=user_id, extra_info={"username": username},
        )
        record_ai_request(
            user_id=user_id, module_name="vibe-coding", model=model,
            prompt_tokens=0, completion_tokens=0, success=False,
            error_message=f"upstream {response.status_code}",
            ip_address=ip_address, request_id=request_id,
        )
        try:
            forwarded = json.loads(decoded)
        except (json.JSONDecodeError, ValueError):
            forwarded = {"error": {"type": "upstream_error",
                                   "message": decoded[:500] if decoded else "upstream returned no body"}}
        return JSONResponse(status_code=response.status_code, content=forwarded)

    async def stream_generator():
        usage_info = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        }
        final_response = None
        # Byte-buffer line parsing: SSE events (esp. the large response.completed)
        # can split across network chunks, so accumulate bytes and split on "\n"
        # instead of parsing each chunk independently.
        sse_buf = b""
        try:
            async for chunk in response.aiter_bytes():
                yield chunk  # passthrough first, never delay the client
                sse_buf += chunk
                while b"\n" in sse_buf:
                    raw_line, sse_buf = sse_buf.split(b"\n", 1)
                    try:
                        line = raw_line.decode("utf-8").strip()
                    except UnicodeDecodeError:
                        continue
                    if not line.startswith("data: "):
                        continue
                    try:
                        data = json.loads(line[6:])
                    except (json.JSONDecodeError, ValueError):
                        continue
                    # response.completed carries the FULL final response object.
                    if data.get("type") == "response.completed":
                        resp = data.get("response", {}) or {}
                        final_response = resp
                        u = resp.get("usage", {}) or {}
                        usage_info["input_tokens"] = max(
                            usage_info["input_tokens"], u.get("input_tokens", 0) or 0
                        )
                        usage_info["output_tokens"] = max(
                            usage_info["output_tokens"], u.get("output_tokens", 0) or 0
                        )
                        details = u.get("input_tokens_details", {}) or {}
                        usage_info["cache_read_tokens"] = max(
                            usage_info["cache_read_tokens"],
                            details.get("cached_tokens", 0) or 0,
                        )
                        usage_info["cache_creation_tokens"] = max(
                            usage_info["cache_creation_tokens"],
                            details.get("cache_write_tokens", 0) or 0,
                        )
        finally:
            await response.aclose()

        logger.info(
            "GPT proxy streaming completed",
            request_id=request_id,
            user_id=user_id, username=username, model=model,
            input_tokens=usage_info["input_tokens"],
            output_tokens=usage_info["output_tokens"],
            cache_read_tokens=usage_info["cache_read_tokens"],
        )
        # 成功 → 记账 + 按 token×倍率扣 credits（统一 credits 池）
        GatewayService.record_and_charge(
            user_id=user_id, module_name="vibe-coding", model=model,
            prompt_tokens=usage_info["input_tokens"],
            completion_tokens=usage_info["output_tokens"],
            cache_read_tokens=usage_info["cache_read_tokens"],
            ip_address=ip_address, success=True, request_id=request_id,
            cache_creation_tokens=usage_info["cache_creation_tokens"],
        )
        # Non-blocking side path: feed the completed exchange to SkillClaw.
        if final_response is not None:
            _schedule_skillclaw(_post_to_skillclaw(
                skillclaw_session_id, skillclaw_session_done,
                client_payload, final_response, username, str(user_id),
            ))
        elif settings.SKILLCLAW_INGEST_ENABLED:
            logger.warning(
                "SkillClaw ingest skipped: no response.completed captured",
                request_id=request_id,
                session_id=skillclaw_session_id,
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


async def _handle_chat_standard(client, payload, headers, upstream_url,
                                user_id, username, ip_address, model, session,
                                skillclaw_session_id="", skillclaw_session_done=False,
                                request_id=None, client_payload=None):
    """OpenAI Chat Completions 非流式：转发 → 读 usage → 记账。"""
    if client_payload is None:
        client_payload = payload
    response = await client.post(upstream_url, json=payload, headers=headers)
    if not response.is_success:
        save_error_request_log(
            request_payload=client_payload, response_status=response.status_code,
            response_body=response.text, error_type="gpt_proxy",
            user_id=user_id, extra_info={"username": username},
        )
        response.raise_for_status()
    result = response.json()
    _schedule_skillclaw(_post_to_skillclaw(
        skillclaw_session_id, skillclaw_session_done,
        client_payload, result, username, str(user_id),
    ))
    # openai chat usage: prompt_tokens/completion_tokens/prompt_tokens_details.cached_tokens
    pt, ct, cache, cache_creation = GatewayService.parse_usage(result, "openai_chat")
    GatewayService.record_and_charge(
        user_id=user_id, module_name="vibe-coding", model=model,
        prompt_tokens=pt, completion_tokens=ct, cache_read_tokens=cache,
        ip_address=ip_address, success=True, request_id=request_id,
        cache_creation_tokens=cache_creation,
    )
    return result


async def _handle_chat_streaming(client, payload, headers, upstream_url,
                                 user_id, username, ip_address, model, session,
                                 skillclaw_session_id="", skillclaw_session_done=False,
                                 request_id=None, client_payload=None):
    """OpenAI Chat Completions 流式：SSE 透传，从 include_usage 的末块(choices 空、带 usage)抓 usage。"""
    if client_payload is None:
        client_payload = payload
    upstream_request = client.build_request("POST", upstream_url, json=payload, headers=headers)
    response = await client.send(upstream_request, stream=True)

    if not response.is_success:
        try:
            error_body = await response.aread()
        finally:
            await response.aclose()
        decoded = error_body.decode("utf-8", errors="replace")
        save_error_request_log(
            request_payload=client_payload, response_status=response.status_code,
            response_body=decoded, error_type="gpt_proxy_stream",
            user_id=user_id, extra_info={"username": username},
        )
        record_ai_request(
            user_id=user_id, module_name="vibe-coding", model=model,
            prompt_tokens=0, completion_tokens=0, success=False,
            error_message=f"upstream {response.status_code}",
            ip_address=ip_address, request_id=request_id,
        )
        try:
            forwarded = json.loads(decoded)
        except (json.JSONDecodeError, ValueError):
            forwarded = {"error": {"type": "upstream_error",
                                   "message": decoded[:500] if decoded else "upstream returned no body"}}
        return JSONResponse(status_code=response.status_code, content=forwarded)

    async def stream_generator():
        usage_obj: dict = {}
        sse_buf = b""
        try:
            async for chunk in response.aiter_bytes():
                yield chunk  # passthrough first, never delay the client
                sse_buf += chunk
                while b"\n" in sse_buf:
                    raw_line, sse_buf = sse_buf.split(b"\n", 1)
                    try:
                        line = raw_line.decode("utf-8").strip()
                    except UnicodeDecodeError:
                        continue
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        obj = json.loads(data)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    # include_usage 的末块 choices 为空、带 usage
                    if obj.get("usage"):
                        usage_obj = obj
        finally:
            await response.aclose()

        pt, ct, cache, cache_creation = (
            GatewayService.parse_usage(usage_obj, "openai_chat")
            if usage_obj else (0, 0, 0, 0)
        )
        logger.info(
            "GPT chat streaming completed", request_id=request_id,
            user_id=user_id, username=username, model=model,
            prompt_tokens=pt, completion_tokens=ct, cache_read_tokens=cache,
        )
        GatewayService.record_and_charge(
            user_id=user_id, module_name="vibe-coding", model=model,
            prompt_tokens=pt, completion_tokens=ct, cache_read_tokens=cache,
            ip_address=ip_address, success=True, request_id=request_id,
            cache_creation_tokens=cache_creation,
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
