"""
Presence API - 用户在线状态 WebSocket 和 REST API

WebSocket 端点：/api/v1/presence/ws?token=xxx
REST 端点：
- GET /api/v1/presence/online-count - 获取在线用户数（管理员）
- GET /api/v1/presence/online-users - 获取在线用户列表（管理员）
- GET /api/v1/presence/status/{user_id} - 检查用户是否在线
"""
import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlmodel import select

from app.api.deps import require_admin, get_current_active_user
from app.models.user import User
from app.services.presence_manager import presence_manager, HEARTBEAT_TIMEOUT
from app.schemas.common import success_response
from app.core.security import decode_token
from app.core.logger import logger
from app.db.session import get_session


router = APIRouter(prefix="/presence", tags=["Presence"])


async def get_user_from_token(token: str) -> tuple[User | None, int | None]:
    """从 token 获取用户（WebSocket 认证），同时返回 token_version。不校验 token_version，交由调用方处理。"""
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None, None

        user_id = payload.get("user_id")
        if not user_id:
            return None, None

        token_version = payload.get("token_version")

        # 获取数据库会话
        for session in get_session():
            statement = select(User).where(User.id == user_id)
            user = session.exec(statement).first()

            if not user or not user.is_active:
                return None, None

            return user, token_version

        return None, None
    except Exception as e:
        logger.warning(f"Failed to get user from token: {str(e)}")
        return None, None




@router.websocket("/ws")
async def websocket_presence(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
):
    """
    WebSocket 在线状态端点

    客户端连接后：
    1. 发送 {"type": "heartbeat"} 保持在线（每 30 秒）
    2. 接收 {"type": "pong"} 响应
    3. 可接收广播消息（如系统通知）

    认证：通过 query parameter 传递 token
    """
    # 1. 认证
    user, token_version = await get_user_from_token(token)

    # 2. 必须先 accept 再 close，否则 Starlette 返回 HTTP 403，前端拿不到 close code
    await websocket.accept()

    if not user:
        await websocket.send_json({
            "type": "error",
            "reason": "Token invalid or expired"
        })
        await websocket.close(code=4001, reason="Unauthorized")
        return

    user_id = user.id
    username = user.username
    role = user.role

    # 3. 校验 token_version（登录设备数窗口，见 User.is_token_version_valid）
    if not user.is_token_version_valid(token_version):
        await websocket.send_json({
            "type": "force_logout",
            "reason": "您的账号在其他设备登录，当前会话已断开"
        })
        await websocket.close(code=4002, reason="Session replaced by new login")
        return

    # 4. 注册到 presence manager
    user_session = await presence_manager.connect(websocket, user_id, username, role, token_version or 0)

    # 5. 发送连接成功消息
    await websocket.send_json({
        "type": "connected",
        "user_id": user_id,
        "online_count": presence_manager.get_online_user_count()
    })

    try:
        while True:
            try:
                # 等待消息，超时检测
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=HEARTBEAT_TIMEOUT
                )

                message = json.loads(data)
                msg_type = message.get("type")

                if msg_type == "heartbeat":
                    # 校验 token_version（登录设备数窗口）；用户被禁用/注销后
                    # 心跳同样立即断开，不等 token 过期
                    for db_session in get_session():
                        db_user = db_session.exec(
                            select(User).where(User.id == user_id)
                        ).first()
                        if db_user and (
                            not db_user.is_active
                            or not db_user.is_token_version_valid(user_session.token_version)
                        ):
                            await websocket.send_json({
                                "type": "force_logout",
                                "reason": "您的账号在其他设备登录，当前会话已断开"
                            })
                            await websocket.close(code=4002, reason="Session replaced by new login")
                            return

                    # 处理心跳（仅维护连接状态，不更新数据库）
                    await presence_manager.heartbeat(user_session)

                    # 响应 pong
                    await websocket.send_json({
                        "type": "pong",
                        "online_count": presence_manager.get_online_user_count()
                    })

            except asyncio.TimeoutError:
                # 心跳超时，断开连接
                logger.warning(f"Heartbeat timeout: user_id={user_id}")
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: user_id={user_id}, error={str(e)}")
    finally:
        await presence_manager.disconnect(user_session)


@router.get("/online-count", response_model=dict, summary="Get online user count (Admin only)")
def get_online_count(
    _: User = Depends(require_admin),
):
    """
    获取当前在线用户数（仅管理员）

    返回当前通过 WebSocket 连接的用户数量
    """
    count = presence_manager.get_online_user_count()
    return success_response(
        data={"online_count": count},
        message="Online count retrieved successfully"
    )


@router.get("/online-users", response_model=dict, summary="Get online user list (Admin only)")
def get_online_users(
    _: User = Depends(require_admin),
):
    """
    获取在线用户列表（仅管理员）

    返回当前所有在线用户的信息
    """
    users = presence_manager.get_online_users()
    return success_response(
        data={
            "online_count": len(users),
            "users": users,
        },
        message="Online users retrieved successfully"
    )


@router.get("/status/{user_id}", response_model=dict, summary="Check if user is online")
def check_user_online(
    user_id: int,
    current_user: User = Depends(get_current_active_user),
):
    """
    检查指定用户是否在线

    - 管理员可以查看任何用户
    - 普通用户只能查看自己
    """
    if not current_user.is_admin and current_user.id != user_id:
        raise ForbiddenException("You can only check your own online status")

    is_online = presence_manager.is_user_online(user_id)
    return success_response(
        data={"user_id": user_id, "is_online": is_online},
        message="User status retrieved successfully"
    )
