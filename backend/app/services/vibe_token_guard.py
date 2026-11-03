"""
Vibe token 共享守卫 — 校验与吊销

vibe-coding 专用 token 的**全部**运行期校验收敛于此,调用方:
- vibe_coding.py 四个端点(messages / web-search / asr / knowledge-search)
- gpt_proxy.py 的 openai_responses / openai_chat 代理前导

在原有 purpose 隔离、用户有效性、token_version(登录设备数窗口)之上追加:
- **jti 吊销**:命中 vibe_revoked_tokens 表即拒。泄露的 token 可单独掐掉,
  不必强迫用户重新登录;
- **设备指纹绑定**:token 内 `dfp` claim 与请求头 `x-device-fp` 不一致,
  按盗用处理——自动吊销该 jti 并拒绝。无 `dfp` 的旧格式 token 跳过此检查
  (兼容存量客户端,升级后自然收敛)。

注意:新增校验只对携带对应 claim 的新 token 生效,旧 token 行为完全不变,
因此可先发后端、再发客户端。
"""
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete
from sqlmodel import Session
from structlog import get_logger

from app.core.exceptions import UnauthorizedException
from app.models.user import User
from app.models.vibe_coding import VibeRevokedToken

logger = get_logger(__name__)

# 设备指纹规范形态:sha-256 的小写 hex
DEVICE_FP_HEX_LEN = 64


def normalize_device_fp(value: Optional[str]) -> Optional[str]:
    """归一化设备指纹:小写去空白;非 64 位 hex 视为无效返回 None(宽容忽略)。"""
    if not value:
        return None
    fp = value.strip().lower()
    if len(fp) != DEVICE_FP_HEX_LEN or any(c not in "0123456789abcdef" for c in fp):
        return None
    return fp


def verify_vibe_token(
    payload: dict, session: Session, device_fp: Optional[str] = None
) -> dict:
    """
    校验 vibe token,返回补全后的 payload;失败抛 UnauthorizedException。

    device_fp 传请求头 `x-device-fp` 原值(可为 None)。
    返回前会用 DB 里的用户名补全 payload["username"]——新格式 token 不再
    携带 username/role,下游打日志/记账仍按原字段读取,无需改动。
    """
    # 令牌隔离:代理端点只接受 vibe-coding 专用令牌,拒绝普通会话/刷新令牌,
    # 与 get_current_user 拒绝 vibe 令牌形成双向隔离。
    if payload.get("purpose") != "vibe-coding":
        raise UnauthorizedException("Not a vibe-coding token")

    user_id = payload.get("user_id")
    if not user_id:
        return payload

    user = session.get(User, user_id)
    if not user or not user.is_active:
        raise UnauthorizedException("User not found or inactive")

    # token_version:登录设备数窗口判据,超出 max_sessions 次登录前签发的
    # token 失效(单设备用户即"重新登录后旧 token 全部失效")
    if not user.is_token_version_valid(payload.get("token_version")):
        raise UnauthorizedException("Session expired due to login from another device")

    # jti 吊销黑名单
    jti = payload.get("jti")
    if jti and session.get(VibeRevokedToken, jti) is not None:
        raise UnauthorizedException("Token has been revoked, please restart terminal")

    # 设备指纹绑定:不符即视为 token 正被另一台机器重放,立即吊销
    bound_fp = payload.get("dfp")
    if bound_fp:
        presented = normalize_device_fp(device_fp)
        if not presented or not hmac.compare_digest(bound_fp, presented):
            if jti:
                revoke_token(
                    session,
                    jti=jti,
                    user_id=user_id,
                    exp=payload.get("exp"),
                    reason="device_fp_mismatch",
                )
            logger.warning(
                "vibe token device fingerprint mismatch — token revoked",
                user_id=user_id,
                jti=jti,
            )
            raise UnauthorizedException(
                "Token is bound to another device and has been revoked, please restart terminal"
            )

    payload["username"] = user.username
    return payload


def revoke_token(
    session: Session, *, jti: str, user_id: int, exp, reason: str
) -> None:
    """把 jti 写入吊销表(幂等),并机会性清理已过期的历史行。"""
    if isinstance(exp, (int, float)):
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
    else:
        # exp 缺失时按最长历史 TTL(7 天)兜底,保证行最终可清理
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    if session.get(VibeRevokedToken, jti) is None:
        session.add(
            VibeRevokedToken(
                jti=jti, user_id=user_id, reason=reason, expires_at=expires_at
            )
        )
        session.commit()

    session.execute(
        delete(VibeRevokedToken).where(
            VibeRevokedToken.expires_at < datetime.now(timezone.utc)
        )
    )
    session.commit()
