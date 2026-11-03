"""
Authentication API endpoints
"""
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlmodel import Session

from app.api.deps import get_db, get_current_user, get_refresh_token_user
from app.models.user import User
from app.schemas.auth import LoginRequest, LoginResponse, RefreshTokenResponse
from app.schemas.user import UserResponse
from app.schemas.common import success_response
from app.services.auth_service import AuthService
from app.services.presence_manager import presence_manager
from app.core.config import settings
from app.core.logger import logger


router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get("/mode", response_model=dict, summary="Get authentication mode")
def get_auth_mode():
    """
    查询当前部署的鉴权模式（无需鉴权）。

    `auth_disabled=true` 时服务端不校验任何凭据，客户端可用
    `default_username` + 任意密码调 /auth/login 换取可用 token，
    从而跳过登录页直接进入主界面。
    """
    return success_response(
        data={
            "auth_disabled": settings.AUTH_DISABLED,
            "default_username": settings.AUTH_DISABLED_USERNAME if settings.AUTH_DISABLED else None,
        },
        message="Auth mode retrieved successfully",
    )


@router.post("/login", response_model=dict, summary="User login")
def login(
    login_data: LoginRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db)
):
    """
    User login with automatic authentication type detection

    - **username**: Username or email
    - **password**: Password
    - **auth_type**: Optional auth type (LDAP or EMAIL), auto-detected if not provided

    Returns user information and JWT tokens (access + refresh)
    """
    result = AuthService.login(
        session=session,
        username=login_data.username,
        password=login_data.password,
        auth_type=login_data.auth_type
    )

    user = result["user"]

    # 立即踢掉滑出登录窗口的旧设备 WebSocket 连接（不等 30 秒心跳）
    background_tasks.add_task(
        presence_manager.force_disconnect_user,
        user.id,
        user.token_version,
        user.effective_max_sessions()
    )

    # Convert user to dict
    user_dict = UserResponse.model_validate(user).model_dump()

    response_data = {
        "user": user_dict,
        "tokens": result["tokens"].model_dump()
    }

    return success_response(data=response_data, message="Login successful")


@router.post("/refresh", response_model=dict, summary="Refresh access token")
def refresh_token(
    user_and_version: tuple[User, int | None] = Depends(get_refresh_token_user)
):
    """
    Refresh access token using refresh token

    Requires valid refresh token in Authorization header:
    `Authorization: Bearer <refresh_token>`

    Returns new access token
    """
    user, token_version = user_and_version
    result = AuthService.refresh_access_token(user, token_version)

    return success_response(data=result, message="Token refreshed successfully")


@router.post("/logout", response_model=dict, summary="User logout")
def logout(
    current_user: User = Depends(get_current_user)
):
    """
    User logout

    Requires valid access token in Authorization header:
    `Authorization: Bearer <access_token>`

    Note: JWT tokens are stateless. Logout mainly clears client-side tokens.
    For production, consider implementing a token blacklist with Redis.
    """
    logger.info(f"User logged out: {current_user.username} (ID: {current_user.id})")

    return success_response(
        data={"logout": True, "username": current_user.username},
        message=f"User {current_user.username} logged out successfully"
    )


@router.get("/me", response_model=dict, summary="Get current user info")
def get_current_user_info(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get current logged-in user information

    Requires valid access token in Authorization header:
    `Authorization: Bearer <access_token>`

    Returns detailed user information including user groups
    """
    from app.services.user_group_service import UserGroupService
    from app.schemas.user import UserGroupInfo

    user_data = UserResponse.model_validate(current_user).model_dump()

    # Add user's groups
    user_groups = UserGroupService.get_user_groups(session, current_user.id, direct_only=False)
    user_data["groups"] = [
        UserGroupInfo(id=g.id, name=g.name, group_type=g.group_type).model_dump()
        for g in user_groups
    ]

    return success_response(data=user_data, message="User information retrieved successfully")
