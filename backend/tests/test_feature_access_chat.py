"""聊天内嵌功能(chat:image-gen)权限种子与校验测试(sqlite 内存库,不依赖 MySQL)。

运行:.venv/Scripts/python -m pytest tests/test_feature_access_chat.py -v
"""
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.feature_access import FeatureGroup, FeatureRoute
from app.services.feature_access_service import FeatureAccessService

ROUTE = FeatureAccessService.CHAT_IMAGE_GEN_ROUTE
INTERNAL_EMAIL = "dev1@example.internal"
EXTERNAL_EMAIL = "guest@example.com"


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def seeded_route(session) -> FeatureRoute:
    FeatureAccessService.seed_chat_feature_entries(session)
    return session.exec(
        select(FeatureRoute).where(FeatureRoute.route_path == ROUTE)
    ).one()


class TestSeedChatFeatureEntries:
    def test_seed_creates_hidden_group_and_route(self, session):
        route = seeded_route(session)
        group = session.get(FeatureGroup, route.group_id)
        assert group.group_key == "_chat"
        assert route.visibility == "ALL"

    def test_seed_is_idempotent(self, session):
        FeatureAccessService.seed_chat_feature_entries(session)
        FeatureAccessService.seed_chat_feature_entries(session)
        routes = session.exec(
            select(FeatureRoute).where(FeatureRoute.route_path == ROUTE)
        ).all()
        assert len(routes) == 1

    def test_seed_heals_after_route_deleted(self, session):
        route = seeded_route(session)
        session.delete(route)
        session.commit()
        FeatureAccessService.seed_chat_feature_entries(session)
        healed = session.exec(
            select(FeatureRoute).where(FeatureRoute.route_path == ROUTE)
        ).all()
        assert len(healed) == 1


class TestSidebarHidesUnderscoreGroups:
    def test_accessible_features_exclude_chat_group(self, session):
        seeded_route(session)
        result = FeatureAccessService.get_accessible_features(
            session, user_id=1, user_email=INTERNAL_EMAIL, user_group_ids=[]
        )
        assert all(g["group_key"] != "_chat" for g in result)


class TestCheckRouteAccess:
    def check(self, session, user_id=1, email=INTERNAL_EMAIL, group_ids=None):
        return FeatureAccessService.check_route_access(
            session, user_id, email, group_ids or [], ROUTE
        )

    def test_all_visibility_allows_everyone(self, session):
        seeded_route(session)
        assert self.check(session, email=EXTERNAL_EMAIL) is True

    def test_internal_visibility_filters_by_email_domain(self, session):
        route = seeded_route(session)
        route.visibility = "INTERNAL"
        session.add(route)
        session.commit()
        assert self.check(session, email=INTERNAL_EMAIL) is True
        assert self.check(session, email=EXTERNAL_EMAIL) is False

    def test_specified_visibility_matches_user_or_group(self, session):
        route = seeded_route(session)
        route.visibility = "SPECIFIED"
        route.allowed_user_ids = "[7]"
        route.allowed_group_ids = "[3]"
        session.add(route)
        session.commit()
        assert self.check(session, user_id=7, email=EXTERNAL_EMAIL) is True
        assert self.check(session, user_id=8, email=EXTERNAL_EMAIL, group_ids=[3]) is True
        assert self.check(session, user_id=8, email=EXTERNAL_EMAIL, group_ids=[9]) is False

    def test_missing_route_fails_closed(self, session):
        assert self.check(session) is False

    def test_inactive_route_fails_closed(self, session):
        route = seeded_route(session)
        route.is_active = False
        session.add(route)
        session.commit()
        assert self.check(session) is False


class TestDeleteRouteGuard:
    def test_chat_route_cannot_be_deleted(self, session):
        route = seeded_route(session)
        with pytest.raises(ValueError):
            FeatureAccessService.delete_route(session, route.id)

    def test_normal_route_still_deletable(self, session):
        group = FeatureGroup(name="g", group_key="g", visibility="ALL")
        session.add(group)
        session.flush()
        route = FeatureRoute(
            group_id=group.id, name="r", route_path="/r", visibility="ALL"
        )
        session.add(route)
        session.commit()
        FeatureAccessService.delete_route(session, route.id)
        assert session.get(FeatureRoute, route.id) is None
