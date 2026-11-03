"""
Skill 端点级集成测试:用 TestClient + sqlite 内存库验证路由装配、鉴权与
admin 门禁全链路。不进 with 上下文,避免触发 lifespan 的 init_db。

运行:.venv/Scripts/python -m pytest tests/test_skill_endpoints.py -v
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.credits import UserCredits
from app.models.user import User
from app.models.vibe_coding import VibeCodingConfig


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
    return TestClient(app)


@pytest.fixture()
def admin_user(session):
    user = User(
        username="admin", email="admin@example.com", hashed_password="x",
        is_active=True, token_version=1, role="admin",
    )
    session.add(user)
    session.add(VibeCodingConfig(id=1, enabled=True, visibility="ALL"))
    session.commit()
    session.refresh(user)
    session.add(UserCredits(user_id=user.id, balance=10**9))
    session.commit()
    return user


@pytest.fixture()
def normal_user(session):
    user = User(
        username="bob", email="bob@example.com", hashed_password="x",
        is_active=True, token_version=1, role="user",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    session.add(UserCredits(user_id=user.id, balance=10**9))
    session.commit()
    return user


def bearer_for(user):
    return create_access_token({
        "user_id": user.id, "username": user.username, "role": user.role,
        "is_active": True, "token_version": user.token_version,
    })


def vibe_token_for(user):
    return create_access_token(
        {"user_id": user.id, "token_version": user.token_version, "purpose": "vibe-coding"},
        expires_delta=timedelta(hours=1),
    )


class TestAdminGate:
    def test_non_admin_cannot_list(self, client, session, normal_user):
        resp = client.get(
            "/api/v1/skills/admin",
            headers={"Authorization": f"Bearer {bearer_for(normal_user)}"},
        )
        assert resp.status_code == 403

    def test_admin_create_and_list(self, client, session, admin_user):
        headers = {"Authorization": f"Bearer {bearer_for(admin_user)}"}
        create = client.post(
            "/api/v1/skills/admin",
            json={
                "name": "pdf-official", "description": "PDF 处理",
                "visibility": "ALL", "version": "1.0.0",
                "content": "# PDF\nbody", "changelog": "init",
            },
            headers=headers,
        )
        assert create.json()["success"], create.json()
        listed = client.get("/api/v1/skills/admin", headers=headers).json()
        assert any(s["name"] == "pdf-official" for s in listed["data"])

    def test_admin_upload_parses_markdown(self, client, session, admin_user):
        headers = {"Authorization": f"Bearer {bearer_for(admin_user)}"}
        content = b"---\nname: parsed-skill\ndescription: from upload\n---\nBody text"
        resp = client.post(
            "/api/v1/skills/admin/upload",
            files={"file": ("SKILL.md", content, "text/markdown")},
            headers=headers,
        )
        data = resp.json()["data"]
        assert data["name"] == "parsed-skill"
        assert data["description"] == "from upload"
        assert "Body text" in data["content"]


class TestUserManifest:
    def test_available_filters_by_visibility(self, client, session, admin_user, normal_user):
        admin_headers = {"Authorization": f"Bearer {bearer_for(admin_user)}"}
        # 公开 skill
        client.post(
            "/api/v1/skills/admin",
            json={"name": "public-skill", "description": "d", "visibility": "ALL",
                  "version": "1.0.0", "content": "pub"},
            headers=admin_headers,
        )
        # 仅指定 admin 可见的 skill
        client.post(
            "/api/v1/skills/admin",
            json={"name": "private-skill", "description": "d", "visibility": "SPECIFIED",
                  "allowed_user_ids": [admin_user.id], "version": "1.0.0", "content": "priv"},
            headers=admin_headers,
        )
        # normal_user 用 vibe token 拉清单
        resp = client.get(
            "/api/v1/vibe-coding/skills/available",
            headers={"x-api-key": vibe_token_for(normal_user)},
        )
        names = [s["name"] for s in resp.json()["data"]["skills"]]
        assert "public-skill" in names
        assert "private-skill" not in names
        # 清单绝不含正文
        for s in resp.json()["data"]["skills"]:
            assert "content" not in s

    def test_available_rejects_non_vibe_token(self, client, session, normal_user):
        resp = client.get(
            "/api/v1/vibe-coding/skills/available",
            headers={"x-api-key": bearer_for(normal_user)},  # 普通 access token
        )
        assert resp.json()["code"] == 401
