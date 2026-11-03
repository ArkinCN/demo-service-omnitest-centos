import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.api.v1.gateway_admin import _resolve_user, _search_users, get_user_credits
from app.models.credits import SubscriptionPlan, UserCredits, UserSubscription, CreditTransaction
from app.models.user import User


def _make_session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            SubscriptionPlan.__table__,
            UserSubscription.__table__,
            UserCredits.__table__,
            CreditTransaction.__table__,
        ],
    )
    return Session(engine)


def _add_users(session):
    users = [
        User(username="alice", email="alice@example.com", nickname="爱丽丝"),
        User(username="bob", email="bob@example.com", nickname="鲍勃"),
        User(username="bobby", email="bobby@example.com", nickname="小鲍勃"),
    ]
    session.add_all(users)
    session.add(SubscriptionPlan(plan_key="trial", name="内测", monthly_credits=500))
    session.commit()
    for u in users:
        session.refresh(u)
    return users


def test_resolve_user_exact_matches():
    with _make_session() as session:
        alice, bob, _ = _add_users(session)
        assert _resolve_user(session, str(alice.id)).id == alice.id
        assert _resolve_user(session, "bob@example.com").id == bob.id
        assert _resolve_user(session, "alice").id == alice.id
        assert _resolve_user(session, "鲍勃").id == bob.id
        assert _resolve_user(session, "  alice  ").id == alice.id
        assert _resolve_user(session, "no-such") is None
        assert _resolve_user(session, "") is None


def test_search_users_fuzzy_over_username_email_nickname():
    with _make_session() as session:
        _, bob, bobby = _add_users(session)
        # username 子串命中 bob 与 bobby
        assert {u.id for u in _search_users(session, "bob")} == {bob.id, bobby.id}
        # 大小写不敏感
        assert {u.id for u in _search_users(session, "BOB")} == {bob.id, bobby.id}
        # nickname 子串
        assert [u.id for u in _search_users(session, "小鲍")] == [bobby.id]
        # email 子串
        assert {u.id for u in _search_users(session, "bobby@")} == {bobby.id}
        # LIKE 通配符按字面量处理，不产生全表通配匹配
        assert _search_users(session, "%") == []
        assert _search_users(session, "b_b") == []


@pytest.mark.asyncio
async def test_get_user_credits_exact_and_unique_fuzzy():
    with _make_session() as session:
        alice, _, bobby = _add_users(session)

        exact = await get_user_credits(str(alice.id), session=session, _=None)
        assert exact["data"]["user"]["id"] == alice.id
        assert "credits" in exact["data"]

        # 模糊唯一命中（昵称片段）等同精确命中
        unique = await get_user_credits("小鲍", session=session, _=None)
        assert unique["data"]["user"]["id"] == bobby.id


@pytest.mark.asyncio
async def test_get_user_credits_multi_match_returns_candidates():
    with _make_session() as session:
        _, bob, bobby = _add_users(session)

        # "bob" 是 username 精确命中，精确优先，不进模糊分支
        exact = await get_user_credits("bob", session=session, _=None)
        assert exact["data"]["user"]["id"] == bob.id

        # "鲍" 无精确命中，模糊命中两个昵称 → 返回候选列表
        res = await get_user_credits("鲍", session=session, _=None)
        matches = res["data"]["matches"]
        assert {m["id"] for m in matches} == {bob.id, bobby.id}
        assert {"id", "username", "nickname", "email"} <= set(matches[0].keys())


@pytest.mark.asyncio
async def test_get_user_credits_not_found_returns_404_with_message():
    with _make_session() as session:
        _add_users(session)
        res = await get_user_credits("nobody", session=session, _=None)
        assert res.status_code == 404
        assert "未找到用户".encode() in res.body
