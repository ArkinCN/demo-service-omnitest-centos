"""
AI 绘图 SSE 端点（从 FastGPT 迁移，无状态，仿 /agent-chat）

POST /agent-image ：SSE 流式返回绘图过程事件（进度/单张图片 base64/完成/错误）。
图片以 base64 推给前端，由前端 Tauri 落盘到用户电脑本地（不经 MinIO）。

鉴权 x-api-key=JWT（与网关 / agent-chat 一致）。计费按张扣 credits。
"""
import json
import uuid
from typing import Optional, List

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from structlog import get_logger
from sqlmodel import Session

from app.api.deps import verify_token_from_api_key
from app.db.session import engine
from app.models.user import User
from app.services.content_safety_service import content_safety
from app.services.credits_service import CreditsService
from app.services.feature_access_service import FeatureAccessService
from app.services.gateway_service import GatewayService
from app.services.image_gen_service import run_image_gen
from app.services.vibe_coding_service import VibeCodingService

logger = get_logger(__name__)
router = APIRouter(prefix="/agent-image", tags=["Agent Image"])


class AgentImageRequest(BaseModel):
    mode: str = "gemini"                       # 'gemini' | 'gpt'
    prompt: str
    image_urls: Optional[List[str]] = None     # 图生图参考图（data URL 或 http URL）
    params: Optional[dict] = None              # aspectRatio/imageResolution/size/quality/route/maxImages
    model: Optional[str] = None                # 已弃用：计费/生成模型一律由服务端按 mode 决定，此字段忽略（保留仅为旧前端兼容）


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("", summary="AI 绘图（SSE）")
async def agent_image(
    body: AgentImageRequest,
    request: Request,
    token_payload: dict = Depends(verify_token_from_api_key),
):
    user_id = token_payload.get("user_id")
    ip = _client_ip(request)
    # 全链路 id：复用入站 x-request-id，否则 req_<uuid4hex>（与网关/vibe 一致）。
    _incoming = (request.headers.get("x-request-id") or "").strip()
    request_id = _incoming[:64] if _incoming else f"req_{uuid.uuid4().hex}"
    client = request.app.state.ai_http_client
    # 计费/生成模型权威化：一律按 mode 取服务端配置,忽略客户端传入的 body.model
    # （真实模型 id 不下发、不信客户端，防止自报模型影响计费；与 vibe 抽象档位一致）。
    from app.core.config import settings
    model = settings.GPT_IMAGE_MODEL if body.mode == "gpt" else settings.GEMINI_IMAGE_MODEL

    async def event_stream():
        # 内容安全过滤·层 1 关键词（GB/T 45654）：命中即拒答（error 事件与
        # "提示词不能为空"同构，前端按用户可见文案渲染），不触达上游、
        # generated=0 自然不扣费。层 2 消耗上游 tokens，放在余额校验之后。
        def _refusal_sse() -> str:
            refusal = {"type": "error", "message": settings.CONTENT_SAFETY_REFUSAL_TEXT}
            return f"data: {json.dumps(refusal, ensure_ascii=False)}\n\n"

        # 访问权限强校验（不能只靠前端隐藏入口）：绘图权限由管理后台的
        # feature_routes 记录 chat:image-gen 配置（ALL/INTERNAL/SPECIFIED），
        # 无权限直接拒绝，不触达内容安全/上游、不扣费。JWT payload 无 email，
        # 判 INTERNAL（@example.internal）必须查库。
        with Session(engine) as s:
            user = s.get(User, user_id)
            user_group_ids = VibeCodingService.get_user_group_ids(s, user_id)
            allowed = user is not None and FeatureAccessService.check_route_access(
                s, user_id, user.email or "", user_group_ids,
                FeatureAccessService.CHAT_IMAGE_GEN_ROUTE,
            )
        if not allowed:
            logger.info(f"agent_image access denied: user_id={user_id}")
            denial = {"type": "error", "message": "您暂无 AI 绘图功能的使用权限，请联系管理员"}
            yield f"data: {json.dumps(denial, ensure_ascii=False)}\n\n"
            return

        prompt_text = body.prompt or ""
        verdict = content_safety.screen_keywords(prompt_text)
        if verdict.blocked:
            content_safety.record_block(
                user_id, "ai_image", model, verdict, ip, request_id, prompt_text,
            )
            yield _refusal_sse()
            return

        # 余额校验 + 模型准入
        with Session(engine) as s:
            if not CreditsService.has_balance(s, user_id):
                yield f"data: {json.dumps({'type': 'error', 'message': 'Credits 不足，请升级或获取更多'}, ensure_ascii=False)}\n\n"
                return
            if not GatewayService.is_model_allowed(s, model):
                yield f"data: {json.dumps({'type': 'error', 'message': f'绘图模型不可用或未配置: {model}'}, ensure_ascii=False)}\n\n"
                return

        # 内容安全过滤·层 2 大模型分类：语义级风险（意图型请求）
        verdict = await content_safety.screen_llm(client, prompt_text)
        if verdict.blocked:
            content_safety.record_block(
                user_id, "ai_image", model, verdict, ip, request_id, prompt_text,
            )
            yield _refusal_sse()
            return

        generated = 0
        try:
            async for event in run_image_gen(
                client=client, mode=body.mode, prompt=body.prompt,
                image_urls=body.image_urls, params=body.params,
            ):
                if event.get("type") == "done":
                    generated = int(event.get("generated") or 0)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"agent_image stream failed: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            return

        # 按张扣费（仅对成功生成的张数）
        if generated > 0:
            GatewayService.record_image_and_charge(
                user_id, "ai_image", model, generated, ip, success=True,
                request_id=request_id,
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
