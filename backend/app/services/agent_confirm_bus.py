"""
待确认写操作的挂起登记簿（2026-10-10，权限切换修复）。

背景：写类工具（如 WriteReportHeader）不在后端执行，而是由**前端**在操作员点
「确认执行」之后真正写入。因此 agent loop 发完 tool_call(mutating=true) 后必须
把这次调用**挂起**，等 /api/agent/confirm 回执到了再把结果回填给模型。

实现：单进程内存单例字典 {call_id: _Pending}。
⚠️ 依赖 uvicorn 单 worker 部署（与 agent_stream_manager 同一前提，主文档已约定）。
多 worker 下回执可能落到别的进程、查不到挂起项——那是部署约束，不是本模块的锅。

调用方约定：
- register(call_id, user_id) -> asyncio.Future：loop 侧 await 这个 Future。
- resolve(call_id, payload, user_id) -> bool：/confirm 侧放行；带归属校验（user_id
  不匹配视为未找到），无挂起项返回 False（端点据此回 404，兼容设备桥凭据流）。
- unregister(call_id)：超时 / 取消 / 断开兜底清理，防内存泄漏。
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from app.core.logger import logger


@dataclass
class _Pending:
    call_id: str
    user_id: int
    future: "asyncio.Future[dict]" = field(repr=False)


# 模块级单例：{call_id: _Pending}
_PENDING: dict[str, _Pending] = {}


def register(call_id: str, user_id: int) -> "asyncio.Future[dict]":
    """登记一次待确认写入，返回 loop 侧要 await 的 Future。

    loop 侧应这样用：
        fut = register(call_id, user_id)
        try:
            result = await asyncio.wait_for(fut, timeout=...)
        except asyncio.TimeoutError:
            ...  # 如实回填「未确认，未执行」
        finally:
            unregister(call_id)
    """
    loop = asyncio.get_event_loop()
    fut: "asyncio.Future[dict]" = loop.create_future()
    _PENDING[call_id] = _Pending(call_id=call_id, user_id=user_id, future=fut)
    logger.info(f"agent confirm bus: registered pending {call_id} (user={user_id})")
    return fut


def resolve(call_id: str, payload: dict, user_id: int) -> bool:
    """放行一次待确认写入。返回是否命中挂起项。

    - 无该 call_id → False（端点回 404）。
    - user_id 不匹配 → False（归属校验：别人的回执不能放行我的挂起位）。
    - 命中 → set_result(payload) 唤醒 loop，返回 True。
    """
    p = _PENDING.get(call_id)
    if p is None:
        return False
    if p.user_id and user_id and p.user_id != user_id:
        logger.warning(
            f"agent confirm bus: user mismatch for {call_id} "
            f"(owner={p.user_id}, actor={user_id}) — rejected"
        )
        return False
    if not p.future.done():
        p.future.set_result(payload or {})
    return True


def unregister(call_id: str) -> None:
    """兜底清理挂起项（超时 / 取消 / 断开时调用）防泄漏。"""
    p = _PENDING.pop(call_id, None)
    if p is not None and not p.future.done():
        # 标记为已取消，避免 loop 侧 await 到永不返回的 Future
        p.future.cancel()


def pending_count() -> int:
    """当前挂起数（供 /health 或调试观测，非核心路径）。"""
    return len(_PENDING)
