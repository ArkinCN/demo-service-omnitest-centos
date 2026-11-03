"""
Presence Manager - 用户在线状态管理器

核心设计：
- 内存 SESSION_POOL 维护所有活跃 WebSocket 连接
- 心跳机制检测连接存活（客户端每 30 秒发送心跳）
- 在线判断：通过 WebSocket 连接状态判断（实时）
- last_active_at 更新：由 API 请求认证触发，而非心跳
"""
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Set, Optional, List
from dataclasses import dataclass, field
from fastapi import WebSocket

from app.core.logger import logger


# 配置常量
HEARTBEAT_INTERVAL = 30  # 客户端心跳间隔（秒）
HEARTBEAT_TIMEOUT = 90  # 心跳超时时间（秒），3 次心跳失败
ONLINE_THRESHOLD_MINUTES = 3  # 在线判断阈值（分钟）


@dataclass
class UserSession:
    """单个用户会话"""
    user_id: int
    username: str
    role: str
    websocket: WebSocket
    token_version: int = 0
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_heartbeat: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __hash__(self):
        return id(self.websocket)

    def __eq__(self, other):
        if isinstance(other, UserSession):
            return self.websocket is other.websocket
        return False


class PresenceManager:
    """
    在线状态管理器 - 全局单例

    职责：
    1. 管理 WebSocket 连接
    2. 处理心跳和在线状态
    3. 在线判断基于 WebSocket 连接（实时）
    4. last_active_at 更新由 API 请求认证触发
    """

    def __init__(self):
        # SESSION_POOL: user_id -> Set[UserSession] (同一用户可能多个设备登录)
        self._sessions: Dict[int, Set[UserSession]] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        websocket: WebSocket,
        user_id: int,
        username: str,
        role: str = "user",
        token_version: int = 0,
    ) -> UserSession:
        """用户 WebSocket 连接"""
        session = UserSession(
            user_id=user_id,
            username=username,
            role=role,
            websocket=websocket,
            token_version=token_version,
        )

        async with self._lock:
            if user_id not in self._sessions:
                self._sessions[user_id] = set()
            self._sessions[user_id].add(session)

        logger.info(
            f"User connected to presence: user_id={user_id}, username={username}, "
            f"total_sessions={len(self._sessions.get(user_id, set()))}"
        )

        return session

    async def disconnect(self, session: UserSession):
        """用户 WebSocket 断开"""
        async with self._lock:
            if session.user_id in self._sessions:
                self._sessions[session.user_id].discard(session)
                if not self._sessions[session.user_id]:
                    del self._sessions[session.user_id]

        logger.info(
            f"User disconnected from presence: user_id={session.user_id}, username={session.username}"
        )

    async def heartbeat(self, session: UserSession) -> None:
        """
        处理心跳

        心跳仅用于维护 WebSocket 连接状态，不再触发数据库更新。
        last_active_at 的更新由 API 请求认证时的后台任务处理。
        """
        now = datetime.now(timezone.utc)
        session.last_heartbeat = now

    async def force_disconnect_user(
        self, user_id: int, current_token_version: int, max_sessions: int = 1
    ) -> int:
        """
        强制断开指定用户已滑出登录窗口的旧会话。

        判据与 User.is_token_version_valid 一致：会话版本落后当前版本
        max_sessions 及以上即踢。max_sessions=0 表示踢掉全部会话
        （账号注销等"全部下线"场景）。

        Args:
            user_id: 用户 ID
            current_token_version: 当前最新的 token_version
            max_sessions: 用户的最大同时登录设备数

        Returns:
            被踢掉的会话数
        """
        kicked = 0
        async with self._lock:
            sessions = self._sessions.get(user_id, set()).copy()
            for session in sessions:
                if current_token_version - session.token_version >= max_sessions:
                    try:
                        await session.websocket.send_json({
                            "type": "force_logout",
                            "reason": "您的账号在其他设备登录，当前会话已断开"
                        })
                        await session.websocket.close(code=4002, reason="Session replaced by new login")
                    except Exception as e:
                        logger.warning(f"Failed to force disconnect: user_id={user_id}, error={str(e)}")
                    self._sessions[user_id].discard(session)
                    kicked += 1
            if user_id in self._sessions and not self._sessions[user_id]:
                del self._sessions[user_id]
        if kicked:
            logger.info(f"Force disconnected {kicked} old session(s) for user_id={user_id}")
        return kicked

    def get_online_user_count(self) -> int:
        """获取当前在线用户数"""
        return len(self._sessions)

    def get_online_user_ids(self) -> List[int]:
        """获取所有在线用户 ID"""
        return list(self._sessions.keys())

    def get_online_users(self) -> List[dict]:
        """获取在线用户列表（包含基本信息）"""
        users = []
        for user_id, sessions in self._sessions.items():
            if sessions:
                # 取第一个 session 获取用户名
                first_session = next(iter(sessions))
                users.append({
                    "user_id": user_id,
                    "username": first_session.username,
                    "role": first_session.role,
                    "session_count": len(sessions),  # 该用户的连接数（多设备）
                    "connected_at": min(s.connected_at for s in sessions).isoformat(),
                })
        return users

    def is_user_online(self, user_id: int) -> bool:
        """检查用户是否在线"""
        return user_id in self._sessions and len(self._sessions[user_id]) > 0

    async def broadcast_to_all(self, message: dict):
        """
        向所有在线用户广播消息

        用于推送系统通知等
        """
        for sessions in self._sessions.values():
            for session in sessions:
                try:
                    await session.websocket.send_json(message)
                except Exception as e:
                    logger.warning(
                        f"Failed to broadcast message: user_id={session.user_id}, error={str(e)}"
                    )

    async def send_to_user(self, user_id: int, message: dict):
        """
        向指定用户的所有会话发送消息

        Args:
            user_id: 目标用户 ID
            message: 消息内容
        """
        sessions = self._sessions.get(user_id, set())
        for session in sessions:
            try:
                await session.websocket.send_json(message)
            except Exception as e:
                logger.warning(
                    f"Failed to send message to user: user_id={user_id}, error={str(e)}"
                )

    async def broadcast_to_admins(self, message: dict):
        """
        向所有管理员广播消息

        用于推送管理通知等
        """
        for sessions in self._sessions.values():
            for session in sessions:
                if session.role == "admin":
                    try:
                        await session.websocket.send_json(message)
                    except Exception as e:
                        logger.warning(
                            f"Failed to broadcast to admin: user_id={session.user_id}, error={str(e)}"
                        )


# 全局单例
presence_manager = PresenceManager()
