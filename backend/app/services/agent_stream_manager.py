"""
AI 对话有状态流管理（支持断线/关应用后恢复）。

agent-chat 本身是无状态 SSE（连接断=流结束）。本模块给它加「后端有状态」：
- POST /agent-chat 来了 → 起后台 asyncio 任务跑 run_agent_chat，事件累积进内存缓存；
- 用户断开/关应用后，后台任务继续生成；
- 回到对话时通过 /agent-chat/active + /{id}/subscribe 重新订阅，
  先重放已累积事件、再续接 live，前端用同一套事件处理逻辑重建 UI。

缓存的是「完整原始 SSE 事件序列」（不是聚合态），订阅时重放即可让前端
零额外重建。计费不在此处——run_agent_chat 内部 _stream_model 已实时扣费。

⚠️ 依赖单 worker 部署：缓存是进程内内存单例，多 worker 会导致
「任务在 worker A、恢复请求到 worker B 拿不到」。当前 uvicorn 单进程，OK。
"""
import asyncio
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

import httpx

from app.core.config import settings
from app.core.logger import logger
from app.services.agent_chat_service import run_agent_chat


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AgentStreamCache:
    """单条流的内存缓存：事件序列 + 订阅者队列。"""

    def __init__(self, stream_id: str, user_id: int,
                 chat_id: Optional[str], message_id: Optional[str]):
        self.stream_id = stream_id
        self.user_id = user_id
        self.chat_id = chat_id
        self.message_id = message_id
        self.status = "streaming"  # streaming | completed | error | cancelled
        self.events: list[dict] = []
        self.subscribers: set[asyncio.Queue] = set()
        self.created_at = _now()
        self.finished_at: Optional[datetime] = None
        self.error_message: Optional[str] = None

    def add_subscriber(self) -> tuple[asyncio.Queue, int]:
        """注册订阅队列，同步返回当前事件数作为重放上界（replay_upto）。

        必须「先入集合、再读 seq」且中间无 await：保证晚于本快照的事件
        一定进队列、不会漏（见 subscribe 的不丢不重边界）。
        """
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers.add(q)
        return q, len(self.events)

    def remove_subscriber(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    def append_and_broadcast(self, event: dict) -> None:
        """累积事件并广播给所有订阅者（put_nowait，慢/死订阅者不阻塞后台任务）。"""
        self.events.append(event)
        for q in list(self.subscribers):
            try:
                q.put_nowait(event)
            except Exception:
                self.subscribers.discard(q)


class AgentStreamManager:
    """全局单例：管理所有活跃/最近完成的 agent-chat 流。"""

    def __init__(self):
        self._streams: dict[str, AgentStreamCache] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    # ── 创建 + 后台任务 ──

    def create_stream(self, user_id: int, chat_id: Optional[str],
                      message_id: Optional[str]) -> str:
        self._cleanup_expired()
        stream_id = uuid.uuid4().hex
        self._streams[stream_id] = AgentStreamCache(
            stream_id, user_id, chat_id, message_id,
        )
        return stream_id

    def start(self, stream_id: str, client: httpx.AsyncClient,
              user_message, history, model, ip, enabled_tools) -> None:
        self._tasks[stream_id] = asyncio.create_task(
            self._run(stream_id, client, user_message, history, model, ip, enabled_tools)
        )

    async def _run(self, stream_id, client, user_message, history, model, ip, enabled_tools):
        cache = self._streams.get(stream_id)
        if cache is None:
            return
        try:
            async for event in run_agent_chat(
                client=client, user_id=cache.user_id, user_message=user_message,
                history=history, model=model, ip=ip, enabled_tools=enabled_tools,
            ):
                # 软取消后不再消费下一轮（止损，不发起新的模型调用）
                if cache.status == "cancelled":
                    break
                cache.append_and_broadcast(event)
                if event.get("type") == "error":
                    cache.status = "error"
                    cache.error_message = event.get("message")
            if cache.status == "streaming":
                cache.status = "completed"
        except Exception as e:
            logger.error(f"agent stream {stream_id} failed: {e}")
            cache.status = "error"
            cache.error_message = str(e)
            cache.append_and_broadcast({"type": "error", "message": str(e)})
        finally:
            cache.finished_at = _now()
            self._tasks.pop(stream_id, None)

    # ── 订阅（重放 + 续接，不丢不重） ──

    async def subscribe(self, stream_id: str) -> AsyncGenerator[dict, None]:
        cache = self._streams.get(stream_id)
        if cache is None:
            return
        q, replay_upto = cache.add_subscriber()
        try:
            # 1) 重放快照内已累积的事件
            for ev in cache.events[:replay_upto]:
                yield ev
            # 2) 续接 live 队列
            while True:
                if cache.status != "streaming" and q.empty():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield ev
                except asyncio.TimeoutError:
                    yield {"type": "ping"}
                    if cache.status != "streaming" and q.empty():
                        break
        finally:
            cache.remove_subscriber(q)

    # ── 查询 / 取消 ──

    def peek(self, stream_id: str) -> Optional[AgentStreamCache]:
        return self._streams.get(stream_id)

    def get_active(self, user_id: int, chat_id: Optional[str] = None) -> list[dict]:
        self._cleanup_expired()
        out = []
        for c in self._streams.values():
            if c.user_id != user_id or c.status != "streaming":
                continue
            if chat_id is not None and c.chat_id != chat_id:
                continue
            out.append({
                "stream_id": c.stream_id,
                "chat_id": c.chat_id,
                "message_id": c.message_id,
                "status": c.status,
                "created_at": c.created_at.isoformat(),
            })
        return out

    def cancel(self, stream_id: str) -> bool:
        cache = self._streams.get(stream_id)
        if cache is None or cache.status != "streaming":
            return False
        cache.status = "cancelled"
        cache.append_and_broadcast({"type": "done", "cancelled": True})
        return True

    # ── TTL 清理（防内存泄漏/僵尸任务） ──

    def _cleanup_expired(self) -> None:
        now = _now()
        ttl = settings.AGENT_STREAM_RECOVERY_TTL_SECONDS
        max_age = settings.AGENT_STREAM_MAX_AGE_SECONDS
        for sid in list(self._streams.keys()):
            c = self._streams[sid]
            # 完成流：finished_at + TTL 过期 → 移除
            if c.status != "streaming" and c.finished_at is not None:
                if (now - c.finished_at).total_seconds() > ttl:
                    self._streams.pop(sid, None)
                    continue
            # 僵尸 streaming：超硬上限仍未结束 → 标 error 并取消任务
            if c.status == "streaming" and (now - c.created_at).total_seconds() > max_age:
                c.status = "error"
                c.error_message = "stream exceeded max age"
                c.finished_at = now
                c.append_and_broadcast({"type": "error", "message": "流超时"})
                t = self._tasks.pop(sid, None)
                if t and not t.done():
                    t.cancel()

    async def run_ttl_loop(self) -> None:
        """lifespan 后台循环：定期清理过期缓存。"""
        try:
            while True:
                await asyncio.sleep(60)
                self._cleanup_expired()
        except asyncio.CancelledError:
            pass

    def shutdown(self) -> None:
        for t in self._tasks.values():
            if not t.done():
                t.cancel()
        self._tasks.clear()
