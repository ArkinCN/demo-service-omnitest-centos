"""
vibe token 签发/校验/吊销的端点级集成测试。

用 FastAPI TestClient + sqlite 内存库覆盖 get_db,不触碰共享 MySQL;
TestClient 不进 `with` 上下文,避免触发 lifespan 里的 init_db(共享库 create_all)。
上游代理调用(火山搜索等)不会被触达:测试只走到鉴权/权限层即返回。

运行:.venv/Scripts/python -m pytest tests/test_vibe_token_endpoints.py -v
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.config import settings
from app.core.security import create_access_token
from app.main import app
from app.models.credits import UserCredits, UserSubscription
from app.models.user import User
from app.models.vibe_coding import VibeCodingChannel, VibeCodingConfig, VibeRevokedToken

FP = "c" * 64
WRONG_FP = "d" * 64


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        app.dependency_overrides[get_db] = lambda: s
        yield s
        app.dependency_overrides.clear()


@pytest.fixture()
def client():
    # 不进 with 上下文 → 不触发 lifespan(init_db 会 create_all 到共享 MySQL)
    return TestClient(app)


@pytest.fixture()
def rich_user(session):
    """有权限有余额的用户(能走通签发)。"""
    user = User(
        username="dev1", email="dev1@example.com",
        hashed_password="x", is_active=True, token_version=1,
    )
    session.add(user)
    session.add(VibeCodingConfig(id=1, enabled=True, visibility="ALL"))
    session.commit()
    session.refresh(user)
    # 预建订阅行:否则 ensure_account 首次调用会按(空的)套餐表把余额重置为 0
    session.add(UserSubscription(
        user_id=user.id, plan_key="trial",
        credits_refreshed_at=datetime.now(timezone.utc),
    ))
    session.add(UserCredits(user_id=user.id, balance=10**9))
    session.add(VibeCodingChannel(
        name="test-main", base_url="http://upstream.invalid", api_key="k",
        model="test-model", enabled=True, channel_type="main", protocol="anthropic",
    ))
    session.commit()
    return user


@pytest.fixture()
def broke_user(session, rich_user):
    """有权限但零余额的用户:auth 通过后止步于 403,永不触达上游。"""
    user = User(
        username="pauper", email="pauper@example.com",
        hashed_password="x", is_active=True, token_version=1,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    session.add(UserCredits(user_id=user.id, balance=0))
    session.commit()
    return user


def bearer_for(user):
    """普通 access token(get_current_user 用)。"""
    return create_access_token({
        "user_id": user.id, "username": user.username, "role": "user",
        "is_active": True, "token_version": user.token_version,
    })


def vibe_token_for(user, **extra):
    payload = {
        "user_id": user.id,
        "token_version": user.token_version,
        "purpose": "vibe-coding",
    }
    payload.update(extra)
    return create_access_token(payload, expires_delta=timedelta(hours=1))


def decode_unverified(token):
    return jwt.get_unverified_claims(token)


class TestIssueToken:
    def test_issue_binds_device_and_minimizes_payload(self, client, session, rich_user):
        resp = client.post(
            "/api/v1/vibe-coding/token",
            json={"channel_id": 1, "device_fp": FP},
            headers={"Authorization": f"Bearer {bearer_for(rich_user)}"},
        )
        body = resp.json()
        assert body["success"], body
        claims = decode_unverified(body["data"]["token"])
        assert claims["purpose"] == "vibe-coding"
        assert claims["dfp"] == FP
        assert len(claims["jti"]) == 32
        assert "iat" in claims
        # payload 最小化:身份信息不再进 token
        assert "username" not in claims
        assert "role" not in claims
        assert "is_active" not in claims
        # TTL 走配置(小时),不再是 7 天
        ttl = claims["exp"] - claims["iat"]
        assert ttl == settings.VIBE_CODING_TOKEN_EXPIRE_HOURS * 3600

    def test_issue_without_fp_leaves_token_unbound(self, client, session, rich_user):
        resp = client.post(
            "/api/v1/vibe-coding/token",
            json={"channel_id": 1},
            headers={"Authorization": f"Bearer {bearer_for(rich_user)}"},
        )
        claims = decode_unverified(resp.json()["data"]["token"])
        assert "dfp" not in claims
        assert "jti" in claims

    def test_invalid_fp_ignored_not_rejected(self, client, session, rich_user):
        resp = client.post(
            "/api/v1/vibe-coding/token",
            json={"channel_id": 1, "device_fp": "not-a-sha256"},
            headers={"Authorization": f"Bearer {bearer_for(rich_user)}"},
        )
        body = resp.json()
        assert body["success"], body
        assert "dfp" not in decode_unverified(body["data"]["token"])


class TestVerifyPath:
    """经 web-search 端点验证共享守卫在真实请求链路上的行为。
    broke_user 余额为零:鉴权通过 → 403(权限层),鉴权失败 → 401。"""

    def test_bound_token_with_correct_fp_passes_auth(self, client, session, broke_user):
        token = vibe_token_for(broke_user, jti="e2e1" * 8, dfp=FP)
        resp = client.post(
            "/api/v1/vibe-coding/web-search",
            json={"query": "hello"},
            headers={"x-api-key": token, "x-device-fp": FP},
        )
        assert resp.status_code == 403, resp.text  # 过了鉴权,止步于余额

    def test_wrong_fp_rejected_and_auto_revoked(self, client, session, broke_user):
        jti = "e2e2" * 8
        token = vibe_token_for(broke_user, jti=jti, dfp=FP)
        resp = client.post(
            "/api/v1/vibe-coding/web-search",
            json={"query": "hello"},
            headers={"x-api-key": token, "x-device-fp": WRONG_FP},
        )
        assert resp.status_code == 401, resp.text
        row = session.get(VibeRevokedToken, jti)
        assert row is not None and row.reason == "device_fp_mismatch"
        # 换回正确指纹也救不回来:已进吊销表
        resp = client.post(
            "/api/v1/vibe-coding/web-search",
            json={"query": "hello"},
            headers={"x-api-key": token, "x-device-fp": FP},
        )
        assert resp.status_code == 401
        assert "revoked" in resp.json()["message"]

    def test_missing_fp_header_rejected_for_bound_token(self, client, session, broke_user):
        token = vibe_token_for(broke_user, jti="e2e3" * 8, dfp=FP)
        resp = client.post(
            "/api/v1/vibe-coding/web-search",
            json={"query": "hello"},
            headers={"x-api-key": token},
        )
        assert resp.status_code == 401

    def test_legacy_token_without_jti_dfp_still_accepted(self, client, session, broke_user):
        # 存量客户端的旧格式 token:必须继续可用(止步于 403 而非 401)
        token = vibe_token_for(broke_user)
        resp = client.post(
            "/api/v1/vibe-coding/web-search",
            json={"query": "hello"},
            headers={"x-api-key": token},
        )
        assert resp.status_code == 403, resp.text


class TestRevokeEndpoint:
    def test_revoke_then_reject(self, client, session, broke_user):
        jti = "e2e4" * 8
        token = vibe_token_for(broke_user, jti=jti)
        resp = client.post("/api/v1/vibe-coding/token/revoke", headers={"x-api-key": token})
        assert resp.json()["data"]["revoked"] is True
        # 吊销后立即全端点失效
        resp = client.post(
            "/api/v1/vibe-coding/web-search",
            json={"query": "hello"},
            headers={"x-api-key": token},
        )
        assert resp.status_code == 401
        # 幂等:重复吊销仍成功
        resp = client.post("/api/v1/vibe-coding/token/revoke", headers={"x-api-key": token})
        assert resp.json()["success"]

    def test_revoke_rejects_non_vibe_token(self, client, session, broke_user):
        resp = client.post(
            "/api/v1/vibe-coding/token/revoke",
            headers={"x-api-key": bearer_for(broke_user)},
        )
        assert resp.status_code == 400

    def test_revoke_legacy_token_reports_not_revoked(self, client, session, broke_user):
        token = vibe_token_for(broke_user)  # 无 jti
        resp = client.post("/api/v1/vibe-coding/token/revoke", headers={"x-api-key": token})
        body = resp.json()
        assert body["success"] and body["data"]["revoked"] is False
