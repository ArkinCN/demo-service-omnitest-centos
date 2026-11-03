"""
vibe_token_guard 单元测试(sqlite 内存库,不依赖 MySQL)。

运行:.venv/Scripts/python -m pytest tests/test_vibe_token_guard.py -v
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.core.exceptions import UnauthorizedException
from app.models.user import User
from app.models.vibe_coding import VibeRevokedToken
from app.services.vibe_token_guard import (
    normalize_device_fp,
    revoke_token,
    verify_vibe_token,
)

FP = "a" * 64
OTHER_FP = "b" * 64


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def user(session):
    u = User(
        username="dev1",
        email="dev1@example.com",
        hashed_password="x",
        is_active=True,
        token_version=3,
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


def payload_for(user, **extra):
    base = {
        "user_id": user.id,
        "token_version": user.token_version,
        "purpose": "vibe-coding",
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=24)).timestamp()),
    }
    base.update(extra)
    return base


class TestNormalizeDeviceFp:
    def test_valid_lowercase_hex(self):
        assert normalize_device_fp(FP) == FP

    def test_uppercase_and_whitespace_normalized(self):
        assert normalize_device_fp(f"  {FP.upper()}  ") == FP

    def test_invalid_values_return_none(self):
        assert normalize_device_fp(None) is None
        assert normalize_device_fp("") is None
        assert normalize_device_fp("short") is None
        assert normalize_device_fp("g" * 64) is None  # 非 hex 字符
        assert normalize_device_fp("a" * 63) is None


class TestVerifyVibeToken:
    def test_rejects_non_vibe_purpose(self, session, user):
        with pytest.raises(UnauthorizedException):
            verify_vibe_token(payload_for(user, purpose="access"), session)

    def test_rejects_inactive_user(self, session, user):
        user.is_active = False
        session.add(user)
        session.commit()
        with pytest.raises(UnauthorizedException):
            verify_vibe_token(payload_for(user), session)

    def test_rejects_stale_token_version(self, session, user):
        with pytest.raises(UnauthorizedException):
            verify_vibe_token(payload_for(user, token_version=2), session)

    def test_legacy_token_without_jti_or_dfp_passes(self, session, user):
        # 存量客户端的旧格式 token(无 jti/dfp)必须继续可用
        result = verify_vibe_token(payload_for(user), session)
        assert result["username"] == "dev1"

    def test_username_enriched_from_db_not_token(self, session, user):
        # 新格式 token 不携带 username,下游读 payload["username"] 仍要有值
        result = verify_vibe_token(payload_for(user), session)
        assert result["username"] == user.username

    def test_revoked_jti_rejected(self, session, user):
        payload = payload_for(user, jti="deadbeef01")
        revoke_token(
            session, jti="deadbeef01", user_id=user.id,
            exp=payload["exp"], reason="manual",
        )
        with pytest.raises(UnauthorizedException, match="revoked"):
            verify_vibe_token(payload, session)

    def test_matching_device_fp_passes(self, session, user):
        payload = payload_for(user, jti="j1", dfp=FP)
        result = verify_vibe_token(payload, session, device_fp=FP)
        assert result["username"] == "dev1"

    def test_device_fp_header_case_insensitive(self, session, user):
        payload = payload_for(user, jti="j1", dfp=FP)
        verify_vibe_token(payload, session, device_fp=FP.upper())

    def test_mismatched_device_fp_rejected_and_auto_revoked(self, session, user):
        payload = payload_for(user, jti="j2", dfp=FP)
        with pytest.raises(UnauthorizedException, match="another device"):
            verify_vibe_token(payload, session, device_fp=OTHER_FP)
        # 指纹不符按盗用处理:jti 已自动进吊销表
        assert session.get(VibeRevokedToken, "j2") is not None
        assert session.get(VibeRevokedToken, "j2").reason == "device_fp_mismatch"
        # 此后即使换回正确指纹也已失效
        with pytest.raises(UnauthorizedException, match="revoked"):
            verify_vibe_token(payload, session, device_fp=FP)

    def test_missing_device_fp_header_rejected_for_bound_token(self, session, user):
        payload = payload_for(user, jti="j3", dfp=FP)
        with pytest.raises(UnauthorizedException):
            verify_vibe_token(payload, session, device_fp=None)

    def test_unbound_token_ignores_header(self, session, user):
        # 无 dfp 的 token 带不带指纹头都放行(兼容:新 CLI 打旧 token)
        verify_vibe_token(payload_for(user), session, device_fp=FP)


class TestRevokeToken:
    def test_idempotent(self, session, user):
        for _ in range(2):
            revoke_token(
                session, jti="dup", user_id=user.id,
                exp=int(datetime.now(timezone.utc).timestamp()) + 3600,
                reason="manual",
            )
        assert session.get(VibeRevokedToken, "dup") is not None

    def test_expired_rows_cleaned_on_insert(self, session, user):
        past = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())
        revoke_token(session, jti="old", user_id=user.id, exp=past, reason="manual")
        # 下一次写入会清理已过期的 "old"
        future = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
        revoke_token(session, jti="new", user_id=user.id, exp=future, reason="manual")
        assert session.get(VibeRevokedToken, "old") is None
        assert session.get(VibeRevokedToken, "new") is not None

    def test_missing_exp_falls_back_to_seven_days(self, session, user):
        revoke_token(session, jti="noexp", user_id=user.id, exp=None, reason="manual")
        row = session.get(VibeRevokedToken, "noexp")
        assert row is not None
        assert row.expires_at > datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=6)
