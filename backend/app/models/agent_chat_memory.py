"""
AI 助手跨轮会话记忆模型（阶段 3 补全，2026-09-29）。

为什么单建一张轻量表、不复用 `chats`：
    `chats`（app/models/chat.py）是客户既有 open-webui 语义的消息**树**结构
    （parentId/childrenIds/currentId），给对话管理页用；而助手链路（/api/agent/stream）
    需要的是**线性 Anthropic messages 列表**（[{role, content}, ...]）。两者语义不同，
    塞进同一张表会把 open-webui 的树结构语义污染掉。单建表爆炸半径最小、互不干扰。

记忆内容纪律：
    - 只存「用户问题 + 最终答复」两段（Anthropic messages 里的 user/assistant），
      以及每轮检索来源的去重摘要；**不存**完整的 tool_result 大文本（检索片段动辄
      数 KB，整段跨轮带着会把上下文窗口吃光，且与轮内 `_compress_stale_tool_results`
      的压缩策略重复）。
    - 答复文本截断到合理长度（默认 2000 字符），防止单轮超长答复把后续几轮的
      窗口挤爆。
"""
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON
from sqlalchemy.ext.mutable import MutableList
from sqlmodel import Column, Field, SQLModel, Session

from app.core.config import settings


class AgentChatMemory(SQLModel, table=True):
    """助手会话记忆：以 (user_id, session_id) 为键，存线性 Anthropic messages。"""

    __tablename__ = "agent_chat_memory"

    id: Optional[int] = Field(default=None, primary_key=True)

    user_id: int = Field(index=True, description="用户 ID（AUTH_DISABLED 时回落本地管理员）")
    session_id: str = Field(index=True, max_length=200, description="会话标识（shell-<场景>-<流程>）")

    # 线性 Anthropic messages：[{role: user/assistant, content: str}, ...]
    # 用 MutableList 包裹 JSON：SQLAlchemy 默认不追踪 JSON 列内部 list 的原地
    # append / 整体赋值，导致「读回后追加再 commit」不落库（实测踩坑）。MutableList
    # 让对 messages 的任何改动都被检测到，append_turn 追加才能持久化。
    messages: Any = Field(
        default_factory=list,
        sa_column=Column(MutableList.as_mutable(JSON)),
        description="线性对话历史",
    )

    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="更新时间")

    class Config:
        from_attributes = True


# 单条答复保留的最大字符数（超出截断，控制跨轮上下文体积）
_MAX_REPLY_CHARS = 2000


def _load(session: Session, user_id: int, session_id: str) -> Optional[AgentChatMemory]:
    return (
        session.query(AgentChatMemory)
        .filter(
            AgentChatMemory.user_id == user_id,
            AgentChatMemory.session_id == session_id,
        )
        .first()
    )


def get_history(session: Session, user_id: int, session_id: str) -> Optional[list[dict]]:
    """读该会话的线性历史（Anthropic messages 格式）。无记录返回 None。

    返回 None 与空列表语义一致（下游 `run_agent_chat` 的 `history or []` 都按无历史处理）。
    """
    if not session_id:
        return None
    row = _load(session, user_id, session_id)
    if row is None:
        return None
    msgs = row.messages
    if not isinstance(msgs, list):
        return None
    return msgs


def append_turn(
    session: Session,
    user_id: int,
    session_id: str,
    user_text: str,
    assistant_text: str,
    source_titles: Optional[list[str]] = None,
) -> None:
    """把一轮（用户问题 + 最终答复）追加进会话记忆，并落库。

    - user_text / assistant_text 为空则跳过该段（不写空消息）。
    - assistant_text 截断到 _MAX_REPLY_CHARS。
    - 记忆条数超上限（AGENT_CHAT_MEMORY_MAX_TURNS）时丢最早一轮，保持窗口可控。
    - 无 session_id 时不写（无键可落，行为与老版一致）。
    """
    if not session_id:
        return
    if not user_text and not assistant_text:
        return

    user_text = (user_text or "").strip()
    assistant_text = (assistant_text or "").strip()
    if len(assistant_text) > _MAX_REPLY_CHARS:
        assistant_text = assistant_text[:_MAX_REPLY_CHARS]

    max_turns = settings.AGENT_CHAT_MEMORY_MAX_TURNS
    row = _load(session, user_id, session_id)

    if row is None:
        msgs: list[dict] = []
    else:
        msgs = row.messages if isinstance(row.messages, list) else []

    # 每轮 = 一条 user + 一条 assistant（都不为空才是一轮）
    if user_text:
        msgs.append({"role": "user", "content": user_text})
    if assistant_text:
        msgs.append({"role": "assistant", "content": assistant_text})

    # 按「轮」裁剪：一轮 2 条消息，超限丢最早的整轮
    if max_turns > 0 and len(msgs) > max_turns * 2:
        overflow = len(msgs) - max_turns * 2
        # 对齐到偶数，避免丢掉半轮（user 与 assistant 不配对）
        overflow = overflow + (overflow % 2)
        msgs = msgs[overflow:]

    if row is None:
        row = AgentChatMemory(user_id=user_id, session_id=session_id, messages=msgs)
        session.add(row)
    else:
        row.messages = msgs
        row.updated_at = datetime.now(timezone.utc)
        session.add(row)
    session.commit()
