"""
内容安全拒答响应构造 — 按协议合成「正常助手回复」形态的响应。

拒答绝不能以异常/错误信封（success=false）返回：前端与 CLI 会把那渲染成报错。
必须模仿各协议的正常成功响应，让拒答文本作为一条普通助手消息展示（对齐产品
预期：「我暂时无法生成你要求的内容。请尝试输入其他要求，我会尽力为你提供帮助。」）。

覆盖统一网关与代理端点的三协议 × 流式/非流式六种形态：
- anthropic         /v1/messages          message JSON / Anthropic SSE 事件序列
- openai_chat       /v1/chat/completions  chat.completion JSON / chunk SSE + [DONE]
- openai_responses  /v1/responses         response JSON / response.* SSE 事件序列
"""
import json
import time
import uuid

from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import settings

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse_data(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _sse_event(event: str, obj: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(obj, ensure_ascii=False)}\n\n"


# ── anthropic ──

def _anthropic_json(model: str, text: str) -> dict:
    return {
        "id": f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


def _anthropic_sse(model: str, text: str):
    msg_id = f"msg_{uuid.uuid4().hex}"
    yield _sse_event("message_start", {
        "type": "message_start",
        "message": {
            "id": msg_id, "type": "message", "role": "assistant", "model": model,
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    })
    yield _sse_event("content_block_start", {
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "text", "text": ""},
    })
    yield _sse_event("content_block_delta", {
        "type": "content_block_delta", "index": 0,
        "delta": {"type": "text_delta", "text": text},
    })
    yield _sse_event("content_block_stop", {"type": "content_block_stop", "index": 0})
    yield _sse_event("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {"output_tokens": 0},
    })
    yield _sse_event("message_stop", {"type": "message_stop"})


# ── openai_chat ──

def _openai_chat_json(model: str, text: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _openai_chat_sse(model: str, text: str):
    chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    base = {"id": chunk_id, "object": "chat.completion.chunk",
            "created": created, "model": model}
    yield _sse_data({**base, "choices": [{
        "index": 0, "delta": {"role": "assistant", "content": text},
        "finish_reason": None,
    }]})
    yield _sse_data({**base, "choices": [{
        "index": 0, "delta": {}, "finish_reason": "stop",
    }], "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})
    yield "data: [DONE]\n\n"


# ── openai_responses ──

def _openai_responses_json(model: str, text: str) -> dict:
    # 字段需齐全：官方 openai SDK 走宽松解析，但严格校验型客户端/中间代理
    # （pydantic/serde）缺 parallel_tool_calls/tool_choice/tools/usage 明细会拒收
    return {
        "id": f"resp_{uuid.uuid4().hex}",
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": model,
        "error": None,
        "incomplete_details": None,
        "metadata": None,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "output": [{
            "type": "message", "id": f"msg_{uuid.uuid4().hex}",
            "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }],
        "usage": {
            "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def _openai_responses_sse(model: str, text: str):
    # 事件序列须与真实 Responses API 一致：官方 SDK 的 stream() 状态机在缺
    # content_part.added 时会对 output_text.delta 抛 IndexError（content 列表
    # 只由 content_part.added 填充）；每个事件带自增 sequence_number。
    response = _openai_responses_json(model, text)
    item = response["output"][0]
    part = item["content"][0]
    seq = iter(range(1, 100))

    def ev(etype: str, obj: dict) -> str:
        return _sse_event(etype, {"type": etype, "sequence_number": next(seq), **obj})

    yield ev("response.created", {
        "response": {**response, "status": "in_progress", "output": [], "usage": None},
    })
    yield ev("response.output_item.added", {
        "output_index": 0, "item": {**item, "status": "in_progress", "content": []},
    })
    yield ev("response.content_part.added", {
        "item_id": item["id"], "output_index": 0, "content_index": 0,
        "part": {"type": "output_text", "text": "", "annotations": []},
    })
    yield ev("response.output_text.delta", {
        "item_id": item["id"], "output_index": 0, "content_index": 0,
        "delta": text, "logprobs": [],
    })
    yield ev("response.output_text.done", {
        "item_id": item["id"], "output_index": 0, "content_index": 0,
        "text": text, "logprobs": [],
    })
    yield ev("response.content_part.done", {
        "item_id": item["id"], "output_index": 0, "content_index": 0, "part": part,
    })
    yield ev("response.output_item.done", {"output_index": 0, "item": item})
    yield ev("response.completed", {"response": response})


_JSON_BUILDERS = {
    "anthropic": _anthropic_json,
    "openai_chat": _openai_chat_json,
    "openai_responses": _openai_responses_json,
}
_SSE_BUILDERS = {
    "anthropic": _anthropic_sse,
    "openai_chat": _openai_chat_sse,
    "openai_responses": _openai_responses_sse,
}


def build_refusal_response(protocol: str, stream: bool, model: str,
                           request_id: str = "", text: str = ""):
    """构造与 protocol/stream 匹配的拒答响应（FastAPI Response）。

    text 缺省取 settings.CONTENT_SAFETY_REFUSAL_TEXT。
    """
    text = text or settings.CONTENT_SAFETY_REFUSAL_TEXT
    headers = {"x-request-id": request_id} if request_id else {}
    if stream:
        gen = _SSE_BUILDERS[protocol](model, text)
        return StreamingResponse(
            (chunk.encode("utf-8") for chunk in gen),
            media_type="text/event-stream",
            headers={**_SSE_HEADERS, **headers},
        )
    return JSONResponse(content=_JSON_BUILDERS[protocol](model, text), headers=headers)
