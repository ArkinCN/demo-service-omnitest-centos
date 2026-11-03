"""登录设备数窗口(max_sessions)机制测试(sqlite 内存库,不依赖 MySQL)。

运行:.venv/Scripts/python -m pytest tests/test_session_window.py -v
"""
import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.core.exceptions import UnauthorizedException
from app.core.security import decode_token
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.presence_manager import PresenceManager
from app.services.vibe_token_guard import verify_vibe_token


def make_user(**overrides) -> User:
    fields = dict(
        username="dev1",
        email="dev1@example.com",
        hashed_password="x",
        is_active=True,
        token_version=0,
        max_sessions=1,
    )
    fields.update(overrides)
    return User(**fields)


class TestIsTokenVersionValid:
    def test_single_device_equals_legacy_strict_match(self):
        user = make_user(token_version=5, max_sessions=1)
        assert user.is_token_version_valid(5) is True
        assert user.is_token_version_valid(4) is False

    def test_window_allows_recent_n_logins(self):
        user = make_user(token_version=8, max_sessions=3)
        assert user.is_token_version_valid(8) is True
        assert user.is_token_version_valid(7) is True
        assert user.is_token_version_valid(6) is True
        assert user.is_token_version_valid(5) is False

    def test_none_version_allowed_for_legacy_tokens(self):
        user = make_user(token_version=5)
        assert user.is_token_version_valid(None) is True

    def test_dirty_max_sessions_treated_as_single_device(self):
        for dirty in (0, None, -3):
            user = make_user(token_version=5, max_sessions=dirty)
            assert user.effective_max_sessions() == 1
            assert user.is_token_version_valid(5) is True
            assert user.is_token_version_valid(4) is False


class TestRefreshInheritsVersion:
    def test_refresh_keeps_original_token_version(self):
        user = make_user(id=1, token_version=8, max_sessions=3)
        result = AuthService.refresh_access_token(user, token_version=6)
        assert decode_token(result["access_token"])["token_version"] == 6
        assert decode_token(result["refresh_token"])["token_version"] == 6

    def test_refresh_without_version_uses_current(self):
        user = make_user(id=1, token_version=8)
        result = AuthService.refresh_access_token(user)
        assert decode_token(result["access_token"])["token_version"] == 8


class TestVibeGuardWindow:
    @pytest.fixture()
    def session(self):
        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)
        with Session(engine) as s:
            yield s

    def persist(self, session, **overrides) -> User:
        user = make_user(**overrides)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    def payload_for(self, user, token_version):
        return {
            "user_id": user.id,
            "token_version": token_version,
            "purpose": "vibe-coding",
        }

    def test_single_device_rejects_stale_version(self, session):
        user = self.persist(session, token_version=3, max_sessions=1)
        assert verify_vibe_token(self.payload_for(user, 3), session)
        with pytest.raises(UnauthorizedException):
            verify_vibe_token(self.payload_for(user, 2), session)

    def test_multi_device_window_allows_older_versions(self, session):
        user = self.persist(session, token_version=3, max_sessions=3)
        assert verify_vibe_token(self.payload_for(user, 1), session)
        with pytest.raises(UnauthorizedException):
            verify_vibe_token(self.payload_for(user, 0), session)


class FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self, code=None, reason=None):
        self.closed = True


class TestForceDisconnectWindow:
    async def connect(self, manager, user_id, token_version):
        ws = FakeWebSocket()
        await manager.connect(ws, user_id, "dev1", "user", token_version)
        return ws

    async def test_kicks_only_sessions_outside_window(self):
        manager = PresenceManager()
        ws_old = await self.connect(manager, 1, 6)
        ws_in = await self.connect(manager, 1, 7)
        ws_new = await self.connect(manager, 1, 8)
        kicked = await manager.force_disconnect_user(1, 8, max_sessions=2)
        assert kicked == 1
        assert ws_old.closed is True
        assert ws_in.closed is False
        assert ws_new.closed is False

    async def test_max_sessions_zero_kicks_all(self):
        manager = PresenceManager()
        ws_a = await self.connect(manager, 1, 7)
        ws_b = await self.connect(manager, 1, 8)
        kicked = await manager.force_disconnect_user(1, 8, max_sessions=0)
        assert kicked == 2
        assert ws_a.closed is True
        assert ws_b.closed is True

    async def test_default_single_device_kicks_older(self):
        manager = PresenceManager()
        ws_old = await self.connect(manager, 1, 7)
        ws_new = await self.connect(manager, 1, 8)
        kicked = await manager.force_disconnect_user(1, 8)
        assert kicked == 1
        assert ws_old.closed is True
        assert ws_new.closed is False
