"""
内置 Skill 展开审计（best-effort）

把成功展开的 (user, tool_use_id, skill, version) 写入 SkillExpansionLog，用于
溯源与频次统计。两条硬性约束：

1. **按 distinct tool_use_id 去重**：会话历史每轮重放会让同一占位符反复展开，
   若按展开次数计数会随会话长度线性膨胀。tool_use_id 在一次工具调用后稳定不变，
   是天然去重键。进程级 LRU（依赖本服务单 uvicorn worker 的内存单例，与
   SkillClaw 后台任务、流恢复缓存同一前提）挡掉重放，避免每请求查库。
2. **绝不影响主请求**：全程 try/except 吞异常；审计失败只记日志。
"""
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session
from structlog import get_logger

from app.models.skill import SkillExpansionLog

logger = get_logger(__name__)

# 进程级已审计 tool_use_id 的 LRU（bounded，防内存无界增长）
_SEEN_MAX = 50_000
_seen: "OrderedDict[str, None]" = OrderedDict()


def _mark_seen(key: str) -> bool:
    """首次见到返回 True 并记入；已见返回 False。"""
    if key in _seen:
        _seen.move_to_end(key)
        return False
    _seen[key] = None
    if len(_seen) > _SEEN_MAX:
        _seen.popitem(last=False)
    return True


def record_expansions(
    session: Session,
    *,
    user_id: int,
    request_id: str,
    agent_role: str,
    protocol: str,
    events: list[dict],
) -> None:
    """把本次请求成功展开的事件落审计表（去重 + 吞异常）。

    events: [{tool_use_id, skill_id, version_code, resource_path}]
    去重键 = (user_id, tool_use_id, skill_id, version_code, resource_path)。
    """
    try:
        rows: list[SkillExpansionLog] = []
        for ev in events:
            tuid = ev.get("tool_use_id")
            if not tuid:
                continue
            dedup_key = (
                f"{user_id}:{tuid}:{ev.get('skill_id')}:"
                f"{ev.get('version_code')}:{ev.get('resource_path') or ''}"
            )
            if not _mark_seen(dedup_key):
                continue
            rows.append(SkillExpansionLog(
                user_id=user_id,
                skill_id=int(ev["skill_id"]),
                version_code=int(ev["version_code"]),
                resource_path=ev.get("resource_path"),
                tool_use_id=str(tuid)[:128],
                request_id=(request_id or "")[:64] or None,
                agent_role=agent_role[:20],
                protocol=protocol[:30],
                created_at=datetime.now(timezone.utc),
            ))
        if not rows:
            return
        for row in rows:
            session.add(row)
        session.commit()
    except Exception as e:  # noqa: BLE001 — 审计绝不能拖垮主请求
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning("skill expansion audit failed", error=str(e), user_id=user_id)


def reset_seen_cache_for_tests() -> None:
    """测试辅助：清空进程级去重缓存。"""
    _seen.clear()
