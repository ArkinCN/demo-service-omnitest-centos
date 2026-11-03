"""
AI 对话 Agent Loop SSE 端点（有状态，支持断线/关应用后恢复）。

- POST /agent-chat                  ：发起对话，建流 + 起后台任务 + 订阅当前连接。
                                      首事件 {type:stream_start, stream_id} 让前端记住。
- GET  /agent-chat/active?chat_id=  ：列出该用户该对话的活跃流（恢复入口）。
- GET  /agent-chat/{id}/subscribe   ：重新订阅（重放已累积事件 + 续接 live）。
- POST /agent-chat/{id}/cancel      ：软取消。

后台任务跑 agent loop 并把事件累积进 AgentStreamManager 内存缓存，连接断开
任务继续。鉴权 x-api-key=JWT（或 Bearer，verify_token_from_api_key 已兼容）。
"""
import json
from typing import Optional, Union, List

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from structlog import get_logger

from app.api.deps import verify_token_from_api_key

logger = get_logger(__name__)
router = APIRouter(prefix="/agent-chat", tags=["Agent Chat"])


class AgentChatRequest(BaseModel):
    # 纯文本问题，或 Anthropic content 块数组（图文混合，含 image 块）
    message: Union[str, List[dict]]
    # 历史消息（Anthropic messages 格式：[{role, content}]），可选
    history: Optional[list[dict]] = None
    model: Optional[str] = None
    # 启用的工具名列表；缺省/空列表 = 不启用任何工具。前端工具开关下发。
    enabled_tools: Optional[List[str]] = None
    # 流恢复用：前端对话 id / 用户消息 id（供 /active 查询与兜底定位）
    chat_id: Optional[str] = None
    message_id: Optional[str] = None


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _sse(d: dict) -> str:
    return f"data: {json.dumps(d, ensure_ascii=False)}\n\n"


_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _mgr(request: Request):
    return request.app.state.agent_stream_manager


@router.post("", summary="AI 对话 Agent Loop（SSE，有状态）")
async def agent_chat(
    body: AgentChatRequest,
    request: Request,
    token_payload: dict = Depends(verify_token_from_api_key),
):
    user_id = token_payload.get("user_id")
    ip = _client_ip(request)
    client = request.app.state.ai_http_client
    mgr = _mgr(request)

    stream_id = mgr.create_stream(user_id, body.chat_id, body.message_id)
    mgr.start(stream_id, client, body.message, body.history, body.model, ip, body.enabled_tools)

    async def event_stream():
        yield _sse({"type": "stream_start", "stream_id": stream_id})
        async for event in mgr.subscribe(stream_id):
            yield _sse(event)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.get("/active", summary="列出该对话的活跃流（流恢复入口）")
async def agent_chat_active(
    request: Request,
    chat_id: Optional[str] = None,
    token_payload: dict = Depends(verify_token_from_api_key),
):
    user_id = token_payload.get("user_id")
    streams = _mgr(request).get_active(user_id, chat_id)
    return {"streams": streams}


@router.get("/{stream_id}/subscribe", summary="重新订阅流（重放 + 续接）")
async def agent_chat_subscribe(
    stream_id: str,
    request: Request,
    token_payload: dict = Depends(verify_token_from_api_key),
):
    user_id = token_payload.get("user_id")
    mgr = _mgr(request)
    cache = mgr.peek(stream_id)
    if cache is None:
        return JSONResponse(status_code=404, content={"error": "stream not found"})
    if cache.user_id != user_id:
        return JSONResponse(status_code=403, content={"error": "forbidden"})

    async def event_stream():
        yield _sse({"type": "stream_start", "stream_id": stream_id})
        async for event in mgr.subscribe(stream_id):
            yield _sse(event)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/{stream_id}/cancel", summary="软取消流")
async def agent_chat_cancel(
    stream_id: str,
    request: Request,
    token_payload: dict = Depends(verify_token_from_api_key),
):
    user_id = token_payload.get("user_id")
    mgr = _mgr(request)
    cache = mgr.peek(stream_id)
    if cache is None:
        return JSONResponse(status_code=404, content={"error": "stream not found"})
    if cache.user_id != user_id:
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    ok = mgr.cancel(stream_id)
    return {"cancelled": ok}
