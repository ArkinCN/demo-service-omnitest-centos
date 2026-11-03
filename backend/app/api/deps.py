"""
Dependency injection for FastAPI routes
"""
from typing import Generator, Optional
from fastapi import Depends, Header, HTTPException, status
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.user import User
from app.core.config import settings
from app.core.security import decode_token
from app.core.exceptions import UnauthorizedException, ForbiddenException


def _local_admin(session: Session) -> User:
    """无密码模式（settings.AUTH_DISABLED）下所有请求统一使用的本地管理员账号。"""
    from app.services.local_admin_service import get_or_create_local_admin

    return get_or_create_local_admin(session)


def _local_admin_payload(session: Session) -> dict:
    """无密码模式下伪造的 token payload，字段与 AuthService._generate_tokens 对齐。"""
    user = _local_admin(session)
    return {
        "user_id": user.id,
        "username": user.username,
        "role": user.role,
        "is_active": user.is_active,
        "token_version": user.token_version,
        "type": "access",
    }


def get_db() -> Generator[Session, None, None]:
    """
    Get database session dependency

    Yields:
        Database session
    """
    yield from get_session()


def get_current_user(
    authorization: Optional[str] = Header(None, description="Bearer token"),
    session: Session = Depends(get_db),
) -> User:
    """
    Get current authenticated user from JWT token

    Args:
        authorization: Authorization header with Bearer token
        session: Database session

    Returns:
        Current user object

    Raises:
        UnauthorizedException: If token is invalid or user not found
    """
    # 无密码模式：无 token / token 失效一律按本地管理员放行
    if settings.AUTH_DISABLED:
        return _local_admin(session)

    # Extract token from "Bearer <token>"
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedException("Invalid authentication credentials")

    token = authorization.replace("Bearer ", "")

    # Decode token
    try:
        payload = decode_token(token)
    except HTTPException:
        raise UnauthorizedException("Invalid or expired token")

    # Verify token type
    if payload.get("type") != "access":
        raise UnauthorizedException("Invalid token type")

    # 令牌隔离：vibe-coding 代理专用令牌（7 天、purpose=vibe-coding）只能用于
    # /vibe-coding、/openai 代理端点，不得用于账号/管理/AI 对话等常规接口——
    # 防止抓包/泄漏后被当作完整账号令牌调用管理接口提权。
    if payload.get("purpose") == "vibe-coding":
        raise UnauthorizedException("This token is scoped to the vibe-coding proxy only")

    # Get user from database
    user_id = payload.get("user_id")
    if not user_id:
        raise UnauthorizedException("Invalid token payload")

    statement = select(User).where(User.id == user_id)
    user = session.exec(statement).first()

    if not user:
        raise UnauthorizedException("User not found")

    if user.deleted_at is not None:
        raise UnauthorizedException("User account has been deleted")

    if not user.is_active:
        raise UnauthorizedException("User account is disabled")

    # 登录设备数限制：版本窗口判据（max_sessions=1 时等价旧的严格相等判据）
    if not user.is_token_version_valid(payload.get("token_version")):
        raise UnauthorizedException("Session expired due to login from another device")

    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Get current active user

    Args:
        current_user: Current user from get_current_user

    Returns:
        Current active user

    Raises:
        UnauthorizedException: If user is not active
    """
    if not current_user.is_active:
        raise UnauthorizedException("User account is disabled")
    return current_user


def require_admin(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """
    Require admin role

    Args:
        current_user: Current active user

    Returns:
        Current user if admin

    Raises:
        ForbiddenException: If user is not admin
    """
    if current_user.role != "admin":
        raise ForbiddenException("Admin privileges required")
    return current_user


def get_refresh_token_user(
    authorization: Optional[str] = Header(None, description="Bearer refresh token"),
    session: Session = Depends(get_db)
) -> tuple[User, Optional[int]]:
    """
    Get user from refresh token

    Args:
        authorization: Authorization header with Bearer refresh token
        session: Database session

    Returns:
        (User, refresh token 里携带的 token_version)。版本随返回值透出，
        供刷新时继承签发——refresh 是续命同一会话，不能升级到最新版本，
        否则多端用户的旧设备会通过刷新挤占新登录的窗口槽位。

    Raises:
        UnauthorizedException: If token is invalid or user not found
    """
    # 无密码模式：refresh 同样直通本地管理员
    if settings.AUTH_DISABLED:
        user = _local_admin(session)
        return user, user.token_version

    # Extract token
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedException("Invalid authentication credentials")

    token = authorization.replace("Bearer ", "")

    # Decode token
    try:
        payload = decode_token(token)
    except HTTPException:
        raise UnauthorizedException("Invalid or expired token")

    # Verify token type
    if payload.get("type") != "refresh":
        raise UnauthorizedException("Invalid token type, refresh token required")

    # Get user from database
    user_id = payload.get("user_id")
    if not user_id:
        raise UnauthorizedException("Invalid token payload")

    statement = select(User).where(User.id == user_id)
    user = session.exec(statement).first()

    if not user:
        raise UnauthorizedException("User not found")

    if user.deleted_at is not None:
        raise UnauthorizedException("User account has been deleted")

    if not user.is_active:
        raise UnauthorizedException("User account is disabled")

    # 登录设备数限制：版本窗口判据（见 User.is_token_version_valid）
    token_version = payload.get("token_version")
    if not user.is_token_version_valid(token_version):
        raise UnauthorizedException("Session expired due to login from another device")

    return user, token_version

def verify_token_only(
    authorization: Optional[str] = Header(None, description="Bearer token"),
    session: Session = Depends(get_db),
) -> dict:
    """
    Lightweight JWT verification without database lookup.
    Only validates the token signature and expiration.

    Use this for high-concurrency endpoints where you only need
    to verify the user is authenticated, not fetch user details.

    Returns:
        Token payload containing user_id, username, etc.
    """
    # 无密码模式：直接返回本地管理员的伪 payload
    if settings.AUTH_DISABLED:
        return _local_admin_payload(session)

    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedException("Invalid authentication credentials")

    token = authorization.replace("Bearer ", "")

    try:
        payload = decode_token(token)
    except HTTPException:
        raise UnauthorizedException("Invalid or expired token")

    if payload.get("type") != "access":
        raise UnauthorizedException("Invalid token type")

    # 令牌隔离：vibe-coding 代理专用令牌（7 天、purpose=vibe-coding）只能用于
    # /vibe-coding、/openai 代理端点，不得用于账号/管理/AI 对话等常规接口——
    # 防止抓包/泄漏后被当作完整账号令牌调用管理接口提权。
    if payload.get("purpose") == "vibe-coding":
        raise UnauthorizedException("This token is scoped to the vibe-coding proxy only")

    if not payload.get("user_id"):
        raise UnauthorizedException("Invalid token payload")

    return payload


def verify_token_from_api_key(
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
    authorization: Optional[str] = Header(None),
    session: Session = Depends(get_db),
) -> dict:
    """
    从 x-api-key 或 Authorization: Bearer 取并验证 JWT。

    - Anthropic 兼容客户端（如 claw.exe）将 JWT 作为 x-api-key 发送；
    - app 内的 agent_debug / pdf 等走 debug-agent crate（写死 Bearer），
      统一网关接管后这些调用方只改 URL、保留 Authorization: Bearer。
    优先取 x-api-key，缺失时回退 Bearer。

    Returns:
        Token payload containing user_id, username, etc.
    """
    # 无密码模式：直接返回本地管理员的伪 payload
    if settings.AUTH_DISABLED:
        return _local_admin_payload(session)

    token = x_api_key
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):]
    if not token:
        raise UnauthorizedException("Missing authentication credentials")

    try:
        payload = decode_token(token)
    except HTTPException:
        raise UnauthorizedException("Invalid or expired token")

    if payload.get("type") != "access":
        raise UnauthorizedException("Invalid token type")

    # 令牌隔离：vibe-coding 代理专用令牌（7 天、purpose=vibe-coding）只能用于
    # /vibe-coding、/openai 代理端点，不得用于账号/管理/AI 对话等常规接口——
    # 防止抓包/泄漏后被当作完整账号令牌调用管理接口提权。
    if payload.get("purpose") == "vibe-coding":
        raise UnauthorizedException("This token is scoped to the vibe-coding proxy only")

    if not payload.get("user_id"):
        raise UnauthorizedException("Invalid token payload")

    return payload


def get_optional_user(
    authorization: Optional[str] = Header(None, description="Optional Bearer token"),
    session: Session = Depends(get_db)
) -> Optional[User]:
    """
    Get current user from JWT token (optional)

    Returns None if no token provided or token is invalid.
    Useful for endpoints that work with or without authentication.

    Args:
        authorization: Optional Authorization header with Bearer token
        session: Database session

    Returns:
        Current user object if authenticated, None otherwise
    """
    # 无密码模式：始终返回本地管理员
    if settings.AUTH_DISABLED:
        return _local_admin(session)

    if not authorization:
        return None

    # Extract token from "Bearer <token>"
    if not authorization.startswith("Bearer "):
        return None

    token = authorization.replace("Bearer ", "")

    # Decode token
    try:
        payload = decode_token(token)
    except HTTPException:
        return None

    # Verify token type
    if payload.get("type") != "access":
        return None

    # 令牌隔离：vibe-coding 代理令牌不得用于常规接口（见 get_current_user）。
    if payload.get("purpose") == "vibe-coding":
        return None

    # Get user from database
    user_id = payload.get("user_id")
    if not user_id:
        return None

    statement = select(User).where(User.id == user_id)
    user = session.exec(statement).first()

    if not user or not user.is_active or user.deleted_at is not None:
        return None

    # 登录设备数限制：版本窗口判据（见 User.is_token_version_valid）
    if not user.is_token_version_valid(payload.get("token_version")):
        return None

    return user
