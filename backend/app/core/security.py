"""
Security utilities for JWT and password hashing
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import HTTPException, status

from app.core.config import settings


# ── 密码哈希（2026-10-29 改：去掉 passlib，直接调用 bcrypt）──────────────────
# 原实现是 passlib 1.7.4 的 CryptContext(schemes=["bcrypt"])。该库自 2020 年起停更，
# 其 bcrypt 后端初始化时会用一段 >72 字节的口令跑 detect_wrap_bug() 自检，而
# bcrypt>=4.0 对超长口令直接抛 ValueError —— 结果是「装完就崩」：
#   · AUTH_DISABLED=true 时启动建管理员即崩（seed_local_admin → set_password）
#   · 本地账号登录 / 建用户 / 重置密码全部 500
# 现改为直接调用 bcrypt 库（requirements 已锁 bcrypt==4.0.1，不新增依赖）。
# 哈希格式仍是 $2b$，历史密码无需重置、无需数据迁移。
_BCRYPT_ROUNDS = 12       # 与 passlib 默认一致，避免新旧哈希计算成本不一致
_BCRYPT_MAX_BYTES = 72    # bcrypt 算法上限；见 _password_bytes 的说明


def _password_bytes(password: str) -> bytes:
    """把口令编码为 UTF-8 并截断到 72 字节（bcrypt 算法上限）。

    passlib 时代超长口令是**静默截断**的，bcrypt>=4 改为**抛异常**。这里显式截断，
    保持与历史哈希一致的校验结果：否则过去用超长口令注册的用户会变成无法登录（500）。
    """
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create JWT access token

    Args:
        data: Data to encode in the token
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create JWT refresh token

    Args:
        data: Data to encode in the token
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Dict[str, Any]:
    """
    Decode and verify JWT token

    Args:
        token: JWT token to decode

    Returns:
        Decoded token payload

    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验口令。

    防御性处理：口令或哈希为空、哈希串损坏、非 bcrypt 格式、含非法字节，
    一律返回 False（视为校验失败），不把异常抛到接口层变成 500。
    """
    if not plain_password or not hashed_password:
        return False
    try:
        return bcrypt.checkpw(_password_bytes(plain_password), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def get_password_hash(password: str) -> str:
    """生成口令哈希，格式为 `$2b$12$...`（与 passlib 时代产物同格式）。"""
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")
