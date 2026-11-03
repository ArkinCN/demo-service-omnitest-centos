from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.v1.gateway_admin import (
    StatGroupSelectionRequest,
    list_request_details,
    list_stat_groups,
    replace_stat_group_selection,
)
from app.models.ai_request import AIRequest
from app.models.credits import CreditTransaction
from app.models.gateway import ModelPricing
from app.models.stat_group import StatGroupSelection
from app.models.user import User
from app.models.user_group import UserGroup, UserGroupMember
from app.services.dashboard_service import DashboardService


def _make_session():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _register_convert_tz(dbapi_conn, _record):
        # SQLite 无 convert_tz，注册等价实现（仅支持测试用到的 +00:00 → +08:00）
        def convert_tz(value, _from_tz, _to_tz):
            if value is None:
                return None
            return str(datetime.fromisoformat(str(value)) + timedelta(hours=8))
        dbapi_conn.create_function("convert_tz", 3, convert_tz)

    SQLModel.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            AIRequest.__table__,
            UserGroup.__table__,
            UserGroupMember.__table__,
            StatGroupSelection.__table__,
            CreditTransaction.__table__,
            ModelPricing.__table__,
        ],
    )
    return Session(engine)


def _add_users(session, *names):
    users = [User(username=n, email=f"{n}@example.com") for n in names]
    session.add_all(users)
    session.commit()
    for u in users:
        session.refresh(u)
    return users


def _add_group(session, name, *, group_type="CUSTOM", is_active=True, members=(), parent_id=None):
    g = UserGroup(name=name, group_type=group_type, is_active=is_active, parent_id=parent_id)
    session.add(g)
    session.commit()
    session.refresh(g)
    for u in members:
        session.add(UserGroupMember(group_id=g.id, user_id=u.id))
    session.commit()
    return g


@pytest.mark.asyncio
async def test_list_stat_groups_only_active_custom_groups():
    with _make_session() as session:
        admin = User(username="admin", email="a@example.com", role="admin")
        u1, u2 = _add_users(session, "u1", "u2")

        g_custom = _add_group(session, "研发组", members=[u1, u2])
        g_empty = _add_group(session, "空组")
        _add_group(session, "LDAP组", group_type="LDAP", members=[u1])
        _add_group(session, "停用组", is_active=False)

        session.add(StatGroupSelection(user_group_id=g_custom.id))
        session.commit()

        listed = await list_stat_groups(session=session, _=admin)
        groups = listed["data"]["groups"]
        assert [(g["name"], g["member_count"], g["selected"]) for g in groups] == [
            ("研发组", 2, True),
            ("空组", 0, False),
        ]
        assert groups[0]["parent_id"] is None
        assert g_empty.id == groups[1]["id"]


@pytest.mark.asyncio
async def test_replace_selection_validates_groups():
    with _make_session() as session:
        admin = User(username="admin", email="a@example.com", role="admin")
        g = _add_group(session, "研发组")
        g_ldap = _add_group(session, "LDAP组", group_type="LDAP")
        g_off = _add_group(session, "停用组", is_active=False)

        missing = await replace_stat_group_selection(
            StatGroupSelectionRequest(user_group_ids=[g.id, 9999]),
            session=session, _=admin,
        )
        assert missing.status_code == 404

        ldap = await replace_stat_group_selection(
            StatGroupSelectionRequest(user_group_ids=[g_ldap.id]),
            session=session, _=admin,
        )
        assert ldap.status_code == 400

        inactive = await replace_stat_group_selection(
            StatGroupSelectionRequest(user_group_ids=[g_off.id]),
            session=session, _=admin,
        )
        assert inactive.status_code == 400

        ok = await replace_stat_group_selection(
            StatGroupSelectionRequest(user_group_ids=[g.id, g.id]),
            session=session, _=admin,
        )
        assert ok["code"] == 200
        assert ok["data"] == {"selected": 1}
        rows = session.exec(select(StatGroupSelection.user_group_id)).all()
        assert list(rows) == [g.id]

        cleared = await replace_stat_group_selection(
            StatGroupSelectionRequest(user_group_ids=[]),
            session=session, _=admin,
        )
        assert cleared["code"] == 200
        assert session.exec(select(StatGroupSelection)).all() == []


@pytest.mark.asyncio
async def test_replace_selection_rejects_overlapping_members():
    with _make_session() as session:
        admin = User(username="admin", email="a@example.com", role="admin")
        u1, u2 = _add_users(session, "u1", "u2")
        g1 = _add_group(session, "组一", members=[u1, u2])
        g2 = _add_group(session, "组二", members=[u2])

        conflict = await replace_stat_group_selection(
            StatGroupSelectionRequest(user_group_ids=[g1.id, g2.id]),
            session=session, _=admin,
        )
        assert conflict.status_code == 400
        assert b"u2" in conflict.body
        assert session.exec(select(StatGroupSelection)).all() == []

        # 单独勾选其中一个不受影响
        ok = await replace_stat_group_selection(
            StatGroupSelectionRequest(user_group_ids=[g1.id]),
            session=session, _=admin,
        )
        assert ok["code"] == 200


def test_group_ranking_uses_selected_user_groups():
    with _make_session() as session:
        u1, u2, u3 = _add_users(session, "u1", "u2", "u3")

        g1 = _add_group(session, "组一", members=[u1])
        g2 = _add_group(session, "组二", members=[u2])
        # u3 所在组未勾选，其请求不应计入
        _add_group(session, "未勾选组", members=[u3])
        session.add_all([
            StatGroupSelection(user_group_id=g1.id),
            StatGroupSelection(user_group_id=g2.id),
        ])
        session.commit()

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for uid, count, cost in [(u1.id, 3, 10000), (u2.id, 1, 90000), (u3.id, 5, 50000)]:
            for _ in range(count):
                session.add(AIRequest(
                    user_id=uid, module_name="ai_chat", model="m",
                    cost_cents=cost, total_tokens=100, success=True,
                    created_at=now,
                ))
        session.commit()

        start = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

        by_requests = DashboardService.get_group_ranking(
            session, start, end, limit=10, sort_by="requests"
        )
        assert [(i.name, i.request_count) for i in by_requests.items] == [
            ("组一", 3), ("组二", 1),
        ]
        assert by_requests.total_count == 2

        by_cost = DashboardService.get_group_ranking(
            session, start, end, limit=10, sort_by="cost"
        )
        assert [(i.name, i.total_cost) for i in by_cost.items] == [
            ("组二", 9.0), ("组一", 3.0),
        ]


def _add_requests(session, user_id, count, *, cost=10000, model="m", prompt_tokens=60, completion_tokens=40):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for _ in range(count):
        session.add(AIRequest(
            user_id=user_id, module_name="ai_chat", model=model,
            cost_cents=cost, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens, success=True,
            created_at=now,
        ))
    session.commit()


@pytest.mark.asyncio
async def test_group_id_filters_dashboard_queries():
    with _make_session() as session:
        admin = User(username="admin", email="a@example.com", role="admin")
        u1, u2 = _add_users(session, "u1", "u2")
        g1 = _add_group(session, "组一", members=[u1])
        _add_requests(session, u1.id, 2)
        _add_requests(session, u2.id, 3)

        china_now = datetime.now(timezone(timedelta(hours=8)))
        start = (china_now - timedelta(days=1)).strftime("%Y-%m-%d")
        end = (china_now + timedelta(days=1)).strftime("%Y-%m-%d")

        # 用户排行：仅统计该分组直属成员
        all_ranking = DashboardService.get_user_ranking(session, start, end, limit=10)
        assert {(i.name, i.request_count) for i in all_ranking.items} == {("u1", 2), ("u2", 3)}
        filtered = DashboardService.get_user_ranking(session, start, end, limit=10, group_id=g1.id)
        assert [(i.name, i.request_count) for i in filtered.items] == [("u1", 2)]
        assert filtered.total_count == 1

        # 概览：请求数 / 人数按分组过滤
        overview_all = DashboardService.get_daily_overview(session, start, end_date=end)
        assert overview_all.total_requests == 5
        assert overview_all.unique_users == 2
        overview = DashboardService.get_daily_overview(session, start, end_date=end, group_id=g1.id)
        assert overview.total_requests == 2
        assert overview.unique_users == 1

        # 不存在的分组返回空数据而非报错
        empty = DashboardService.get_daily_overview(session, start, end_date=end, group_id=99999)
        assert empty.total_requests == 0

        # 请求明细：group_id 过滤；用户列优先显示昵称
        u1.nickname = "用户一"
        session.add(u1)
        session.commit()
        page = await list_request_details(
            page=1, page_size=50, user_id=None, module=None, model=None,
            success=None, start=None, end=None, group_id=g1.id,
            session=session, _=admin,
        )
        items = page["data"]["items"]
        assert page["data"]["total"] == 2
        assert {i["username"] for i in items} == {"用户一"}


@pytest.mark.asyncio
async def test_group_id_filter_includes_descendant_groups():
    with _make_session() as session:
        admin = User(username="admin", email="a@example.com", role="admin")
        u1, u2, u3 = _add_users(session, "u1", "u2", "u3")
        parent = _add_group(session, "父组")
        child = _add_group(session, "子组", members=[u1], parent_id=parent.id)
        grandchild = _add_group(session, "孙组", members=[u2], parent_id=child.id)
        _add_group(session, "其他组", members=[u3])
        _add_requests(session, u1.id, 2)
        _add_requests(session, u2.id, 3)
        _add_requests(session, u3.id, 4)

        assert DashboardService.expand_group_ids(session, parent.id) == [
            parent.id, child.id, grandchild.id,
        ]

        china_now = datetime.now(timezone(timedelta(hours=8)))
        start = (china_now - timedelta(days=1)).strftime("%Y-%m-%d")
        end = (china_now + timedelta(days=1)).strftime("%Y-%m-%d")

        # 选父分组：覆盖整棵子树成员；选子分组：含孙组
        overview = DashboardService.get_daily_overview(session, start, end_date=end, group_id=parent.id)
        assert overview.total_requests == 5
        assert overview.unique_users == 2
        overview_child = DashboardService.get_daily_overview(session, start, end_date=end, group_id=child.id)
        assert overview_child.total_requests == 5
        overview_leaf = DashboardService.get_daily_overview(session, start, end_date=end, group_id=grandchild.id)
        assert overview_leaf.total_requests == 3

        ranking = DashboardService.get_user_ranking(session, start, end, limit=10, group_id=parent.id)
        assert {(i.name, i.request_count) for i in ranking.items} == {("u1", 2), ("u2", 3)}

        page = await list_request_details(
            page=1, page_size=50, user_id=None, module=None, model=None,
            success=None, start=None, end=None, group_id=parent.id,
            session=session, _=admin,
        )
        assert page["data"]["total"] == 5
        assert {i["username"] for i in page["data"]["items"]} == {"u1", "u2"}


@pytest.mark.asyncio
async def test_model_token_stats_breakdown_and_group_filter():
    with _make_session() as session:
        u1, u2 = _add_users(session, "u1", "u2")
        g1 = _add_group(session, "组一", members=[u1])
        _add_requests(session, u1.id, 2, model="model-a", prompt_tokens=100, completion_tokens=50)
        _add_requests(session, u2.id, 1, model="model-b", prompt_tokens=30, completion_tokens=20)

        china_now = datetime.now(timezone(timedelta(hours=8)))
        start = (china_now - timedelta(days=1)).strftime("%Y-%m-%d")
        end = (china_now + timedelta(days=1)).strftime("%Y-%m-%d")

        # 全量：按 total_tokens 降序，占比合计 100
        stats = DashboardService.get_model_token_stats(session, start, end_date=end)
        assert stats.total_tokens == 350
        assert [(i.model, i.request_count, i.prompt_tokens, i.completion_tokens, i.total_tokens) for i in stats.items] == [
            ("model-a", 2, 200, 100, 300),
            ("model-b", 1, 30, 20, 50),
        ]
        assert stats.items[0].percentage == 85.7
        assert stats.items[1].percentage == 14.3

        # 分组过滤：仅统计组内成员
        filtered = DashboardService.get_model_token_stats(session, start, end_date=end, group_id=g1.id)
        assert [i.model for i in filtered.items] == ["model-a"]
        assert filtered.total_tokens == 300

        # 无数据：空列表且不除零
        empty = DashboardService.get_model_token_stats(session, start, end_date=end, group_id=99999)
        assert empty.items == []
        assert empty.total_tokens == 0


def test_cost_trend_stats_daily_cost_and_credits():
    with _make_session() as session:
        u1, u2 = _add_users(session, "u1", "u2")
        g1 = _add_group(session, "组一", members=[u1])
        _add_requests(session, u1.id, 2, cost=10000)  # 2 × 1 元
        _add_requests(session, u2.id, 1, cost=30000)  # 3 元

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(CreditTransaction(user_id=u1.id, type="consume", amount=-2_500_000, created_at=now))
        session.add(CreditTransaction(user_id=u2.id, type="consume", amount=-1_500_000, created_at=now))
        # 非消耗流水不计入
        session.add(CreditTransaction(user_id=u1.id, type="grant", amount=9_000_000, created_at=now))
        session.commit()

        result = DashboardService.get_cost_trend_stats(session, days=2)
        assert result.days == 2
        assert len(result.data) == 2
        assert result.data[0].cost == 0.0
        assert result.data[0].credits == 0.0
        today = result.data[-1]
        assert today.cost == pytest.approx(5.0)
        assert today.credits == pytest.approx(4.0)

        # 分组过滤：成本与 Credits 都只算组内成员
        filtered = DashboardService.get_cost_trend_stats(session, days=2, group_id=g1.id)
        assert filtered.data[-1].cost == pytest.approx(2.0)
        assert filtered.data[-1].credits == pytest.approx(2.5)

        # 不存在的分组返回全零而非报错
        empty = DashboardService.get_cost_trend_stats(session, days=2, group_id=99999)
        assert all(p.cost == 0.0 and p.credits == 0.0 for p in empty.data)


def test_user_ranking_sort_by_tokens():
    with _make_session() as session:
        u1, u2 = _add_users(session, "u1", "u2")
        # u1：1 次请求、1000 tokens；u2：2 次请求、200 tokens
        _add_requests(session, u1.id, 1, prompt_tokens=900, completion_tokens=100)
        _add_requests(session, u2.id, 2)

        china_now = datetime.now(timezone(timedelta(hours=8)))
        start = (china_now - timedelta(days=1)).strftime("%Y-%m-%d")
        end = (china_now + timedelta(days=1)).strftime("%Y-%m-%d")

        by_tokens = DashboardService.get_user_ranking(session, start, end, limit=10, sort_by="tokens")
        assert [(i.name, i.total_tokens) for i in by_tokens.items] == [("u1", 1000), ("u2", 200)]

        by_requests = DashboardService.get_user_ranking(session, start, end, limit=10, sort_by="requests")
        assert [i.name for i in by_requests.items] == ["u2", "u1"]


def test_user_stats_model_breakdown_includes_tokens():
    with _make_session() as session:
        (u1,) = _add_users(session, "u1")
        # model-a 请求次数多但 token 少，model-b 反之 → 按 token 降序 model-b 在前
        _add_requests(session, u1.id, 2, model="model-a", prompt_tokens=60, completion_tokens=40)
        _add_requests(session, u1.id, 1, model="model-b", prompt_tokens=800, completion_tokens=200)

        china_now = datetime.now(timezone(timedelta(hours=8)))
        start = (china_now - timedelta(days=1)).strftime("%Y-%m-%d")
        end = (china_now + timedelta(days=1)).strftime("%Y-%m-%d")

        stats = DashboardService.get_user_stats(session, u1.id, start, end)
        assert [(i.name, i.value, i.tokens) for i in stats.model_breakdown] == [
            ("model-b", 1, 1000),
            ("model-a", 2, 200),
        ]


def test_group_stats_aggregates_direct_members_only():
    with _make_session() as session:
        u1, u2, u3 = _add_users(session, "u1", "u2", "u3")
        g1 = _add_group(session, "组一", members=[u1, u2])
        _add_requests(session, u1.id, 2, model="model-a", prompt_tokens=60, completion_tokens=40)
        _add_requests(session, u2.id, 1, model="model-b", prompt_tokens=800, completion_tokens=200)
        _add_requests(session, u3.id, 5, model="model-c")  # 非组内成员，不计入

        china_now = datetime.now(timezone(timedelta(hours=8)))
        start = (china_now - timedelta(days=1)).strftime("%Y-%m-%d")
        end = (china_now + timedelta(days=1)).strftime("%Y-%m-%d")

        stats = DashboardService.get_group_stats(session, g1.id, start, end)
        assert stats.name == "组一"
        assert stats.member_count == 2
        assert stats.total_requests == 3
        assert stats.total_tokens == 1200
        # 模型分布按 token 降序且不含组外模型
        assert [(i.name, i.value, i.tokens) for i in stats.model_breakdown] == [
            ("model-b", 1, 1000),
            ("model-a", 2, 200),
        ]

        with pytest.raises(ValueError):
            DashboardService.get_group_stats(session, 99999, start, end)

def test_daily_overview_includes_cost_and_credits():
    with _make_session() as session:
        u1, u2 = _add_users(session, "u1", "u2")
        g1 = _add_group(session, "g1", members=[u1])
        # u1: 2 x 10000 cost_cents = 2 CNY; u2: 1 x 10000 = 1 CNY
        _add_requests(session, u1.id, 2)
        _add_requests(session, u2.id, 1)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(CreditTransaction(user_id=u1.id, type="consume", amount=-2_500_000, created_at=now))
        session.add(CreditTransaction(user_id=u2.id, type="consume", amount=-1_500_000, created_at=now))
        # 非 consume 流水不计入 Credits
        session.add(CreditTransaction(user_id=u1.id, type="grant", amount=9_000_000, created_at=now))
        session.commit()

        china_now = datetime.now(timezone(timedelta(hours=8)))
        start = (china_now - timedelta(days=1)).strftime("%Y-%m-%d")
        end = (china_now + timedelta(days=1)).strftime("%Y-%m-%d")

        overview = DashboardService.get_daily_overview(session, start, end_date=end)
        assert overview.total_cost == 3.0
        assert overview.total_credits == 4.0

        filtered = DashboardService.get_daily_overview(session, start, end_date=end, group_id=g1.id)
        assert filtered.total_cost == 2.0
        assert filtered.total_credits == 2.5

def test_trend_stats_explicit_date_range():
    with _make_session() as session:
        (u1,) = _add_users(session, "u1")
        _add_requests(session, u1.id, 3)
        session.add(CreditTransaction(
            user_id=u1.id, type="consume", amount=-2_000_000,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ))
        session.commit()

        china_now = datetime.now(timezone(timedelta(hours=8)))
        start = (china_now - timedelta(days=2)).strftime("%Y-%m-%d")
        end = china_now.strftime("%Y-%m-%d")

        trend = DashboardService.get_trend_stats(
            session, metric="requests", start_date=start, end_date=end
        )
        assert trend.days == 3
        assert len(trend.data) == 3
        assert sum(p.value for p in trend.data) == 3

        cost_trend = DashboardService.get_cost_trend_stats(
            session, start_date=start, end_date=end
        )
        assert cost_trend.days == 3
        assert len(cost_trend.data) == 3
        assert sum(p.credits for p in cost_trend.data) == 2.0

        with pytest.raises(ValueError):
            DashboardService.get_trend_stats(
                session, metric="requests", start_date=end, end_date=start
            )

def test_user_and_group_stats_include_credits():
    with _make_session() as session:
        u1, u2, u3 = _add_users(session, "u1", "u2", "u3")
        g1 = _add_group(session, "g1", members=[u1, u2])
        _add_requests(session, u1.id, 1)
        _add_requests(session, u2.id, 1)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(CreditTransaction(user_id=u1.id, type="consume", amount=-1_500_000, created_at=now))
        session.add(CreditTransaction(user_id=u2.id, type="consume", amount=-2_000_000, created_at=now))
        session.add(CreditTransaction(user_id=u3.id, type="consume", amount=-9_000_000, created_at=now))
        # grant 不计入
        session.add(CreditTransaction(user_id=u1.id, type="grant", amount=5_000_000, created_at=now))
        session.commit()

        china_now = datetime.now(timezone(timedelta(hours=8)))
        start = (china_now - timedelta(days=1)).strftime("%Y-%m-%d")
        end = (china_now + timedelta(days=1)).strftime("%Y-%m-%d")

        user_stats = DashboardService.get_user_stats(session, u1.id, start, end)
        assert user_stats.total_credits == 1.5

        group_stats = DashboardService.get_group_stats(session, g1.id, start, end)
        assert group_stats.total_credits == 3.5  # 仅组内成员，不含 u3


@pytest.mark.asyncio
async def test_replace_selection_keeps_already_selected_groups():
    with _make_session() as session:
        users = _add_users(session, "u1", "u2")
        g1 = _add_group(session, "g1", members=[users[0]])
        g2 = _add_group(session, "g2", members=[users[1]])
        first = await replace_stat_group_selection(
            StatGroupSelectionRequest(user_group_ids=[g1.id]), session=session, _=None
        )
        assert first["success"] is True

        # 重新提交包含已勾选分组的列表，不应撞唯一约束
        second = await replace_stat_group_selection(
            StatGroupSelectionRequest(user_group_ids=[g1.id, g2.id]), session=session, _=None
        )
        assert second["success"] is True
        selected = set(session.exec(select(StatGroupSelection.user_group_id)).all())
        assert selected == {g1.id, g2.id}


def test_delete_group_removes_stat_selection():
    from app.services.user_group_service import UserGroupService

    with _make_session() as session:
        session.connection().exec_driver_sql("PRAGMA foreign_keys=ON")
        users = _add_users(session, "u1")
        g = _add_group(session, "g1", members=[users[0]])
        session.add(StatGroupSelection(user_group_id=g.id))
        session.commit()

        UserGroupService.delete_group(session, g.id)

        assert session.exec(select(StatGroupSelection)).all() == []
        assert session.get(UserGroup, g.id) is None
