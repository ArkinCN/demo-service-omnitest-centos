"""
Feature Access Service - 功能分组与路由 CRUD、权限校验、种子数据
"""
import json
from typing import Optional
from sqlmodel import Session, select
from app.models.feature_access import FeatureGroup, FeatureRoute
from app.models.user_group import UserGroupMember
from app.core.logger import logger


class FeatureAccessService:

    # ── 分组管理 ──

    @staticmethod
    def get_groups(session: Session) -> list[dict]:
        stmt = select(FeatureGroup).order_by(FeatureGroup.sort_order)
        groups = list(session.exec(stmt).all())
        return [
            {
                "id": g.id,
                "name": g.name,
                "group_key": g.group_key,
                "sort_order": g.sort_order,
                "is_active": g.is_active,
                "visibility": g.visibility,
                "allowed_group_ids": g.allowed_group_ids if isinstance(g.allowed_group_ids, list) else json.loads(g.allowed_group_ids or "[]"),
                "allowed_user_ids": g.allowed_user_ids if isinstance(g.allowed_user_ids, list) else json.loads(g.allowed_user_ids or "[]"),
                "created_at": g.created_at.isoformat() if g.created_at else None,
            }
            for g in groups
        ]

    @staticmethod
    def create_group(session: Session, data: dict) -> FeatureGroup:
        group = FeatureGroup(
            name=data["name"],
            group_key=data["group_key"],
            sort_order=data.get("sort_order", 0),
            is_active=data.get("is_active", True),
            visibility=data.get("visibility", "ALL"),
            allowed_group_ids=json.dumps(data.get("allowed_group_ids", [])),
            allowed_user_ids=json.dumps(data.get("allowed_user_ids", [])),
        )
        session.add(group)
        session.commit()
        session.refresh(group)
        return group

    @staticmethod
    def update_group(session: Session, group_id: int, data: dict) -> FeatureGroup:
        group = session.get(FeatureGroup, group_id)
        if not group:
            raise ValueError("分组不存在")
        for key in ("name", "group_key", "sort_order", "is_active", "visibility"):
            if key in data:
                setattr(group, key, data[key])
        if "allowed_group_ids" in data:
            group.allowed_group_ids = json.dumps(data["allowed_group_ids"])
        if "allowed_user_ids" in data:
            group.allowed_user_ids = json.dumps(data["allowed_user_ids"])
        session.add(group)
        session.commit()
        session.refresh(group)
        return group

    @staticmethod
    def delete_group(session: Session, group_id: int):
        group = session.get(FeatureGroup, group_id)
        if not group:
            raise ValueError("分组不存在")
        # 检查是否有关联路由
        stmt = select(FeatureRoute).where(FeatureRoute.group_id == group_id)
        routes = session.exec(stmt).all()
        if routes:
            raise ValueError("该分组下还有路由，请先删除所有路由")
        session.delete(group)
        session.commit()

    # ── 路由管理 ──

    @staticmethod
    def get_routes(session: Session, group_id: Optional[int] = None) -> list[dict]:
        stmt = (
            select(FeatureRoute, FeatureGroup.name)
            .join(FeatureGroup, FeatureRoute.group_id == FeatureGroup.id)
            .order_by(FeatureRoute.group_id, FeatureRoute.sort_order)
        )
        if group_id is not None:
            stmt = stmt.where(FeatureRoute.group_id == group_id)
        results = session.exec(stmt).all()
        return [
            {
                "id": r.id,
                "group_id": r.group_id,
                "group_name": gname,
                "name": r.name,
                "route_path": r.route_path,
                "icon": r.icon,
                "is_external_window": r.is_external_window,
                "sort_order": r.sort_order,
                "is_active": r.is_active,
                "visibility": r.visibility,
                "allowed_group_ids": r.allowed_group_ids if isinstance(r.allowed_group_ids, list) else json.loads(r.allowed_group_ids or "[]"),
                "allowed_user_ids": r.allowed_user_ids if isinstance(r.allowed_user_ids, list) else json.loads(r.allowed_user_ids or "[]"),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r, gname in results
        ]

    @staticmethod
    def create_route(session: Session, data: dict) -> FeatureRoute:
        route = FeatureRoute(
            group_id=data["group_id"],
            name=data["name"],
            route_path=data["route_path"],
            icon=data.get("icon"),
            is_external_window=data.get("is_external_window", False),
            sort_order=data.get("sort_order", 0),
            is_active=data.get("is_active", True),
            visibility=data.get("visibility", "ALL"),
            allowed_group_ids=json.dumps(data.get("allowed_group_ids", [])),
            allowed_user_ids=json.dumps(data.get("allowed_user_ids", [])),
        )
        session.add(route)
        session.commit()
        session.refresh(route)
        return route

    @staticmethod
    def update_route(session: Session, route_id: int, data: dict) -> FeatureRoute:
        route = session.get(FeatureRoute, route_id)
        if not route:
            raise ValueError("路由不存在")
        for key in ("group_id", "name", "route_path", "icon", "is_external_window", "sort_order", "is_active", "visibility"):
            if key in data:
                setattr(route, key, data[key])
        if "allowed_group_ids" in data:
            route.allowed_group_ids = json.dumps(data["allowed_group_ids"])
        if "allowed_user_ids" in data:
            route.allowed_user_ids = json.dumps(data["allowed_user_ids"])
        session.add(route)
        session.commit()
        session.refresh(route)
        return route

    @staticmethod
    def delete_route(session: Session, route_id: int):
        route = session.get(FeatureRoute, route_id)
        if not route:
            raise ValueError("路由不存在")
        if route.route_path.startswith("chat:"):
            raise ValueError("聊天内嵌功能路由不可删除，如需关闭请改为停用")
        session.delete(route)
        session.commit()

    # ── 权限校验 ──

    @staticmethod
    def _check_visibility(visibility: str, allowed_user_ids, allowed_group_ids, user_id: int, user_email: str, user_group_ids: list[int]) -> bool:
        """通用可见性检查，分组和路由共用"""
        if visibility == "ALL":
            return True
        if visibility == "INTERNAL":
            return user_email.endswith("@example.internal")
        if visibility == "SPECIFIED":
            allowed_users = allowed_user_ids if isinstance(allowed_user_ids, list) else json.loads(allowed_user_ids or "[]")
            allowed_groups = allowed_group_ids if isinstance(allowed_group_ids, list) else json.loads(allowed_group_ids or "[]")
            if user_id in allowed_users:
                return True
            if any(gid in allowed_groups for gid in user_group_ids):
                return True
        return False

    @staticmethod
    def _check_group_permission(group: FeatureGroup, user_id: int, user_email: str, user_group_ids: list[int]) -> bool:
        return FeatureAccessService._check_visibility(
            group.visibility, group.allowed_user_ids, group.allowed_group_ids,
            user_id, user_email, user_group_ids
        )

    @staticmethod
    def _check_route_permission(route: FeatureRoute, user_id: int, user_email: str, user_group_ids: list[int]) -> bool:
        return FeatureAccessService._check_visibility(
            route.visibility, route.allowed_user_ids, route.allowed_group_ids,
            user_id, user_email, user_group_ids
        )

    @staticmethod
    def get_accessible_features(session: Session, user_id: int, user_email: str, user_group_ids: list[int]) -> list[dict]:
        """
        获取当前用户可见的分组+路由列表（侧边栏加载用）。
        仅返回 is_active 的分组和路由，并按分组权限和路由权限双重过滤。
        """
        groups = session.exec(
            select(FeatureGroup)
            .where(FeatureGroup.is_active == True)
            .order_by(FeatureGroup.sort_order)
        ).all()

        routes = session.exec(
            select(FeatureRoute)
            .where(FeatureRoute.is_active == True)
            .order_by(FeatureRoute.sort_order)
        ).all()

        # 按分组 ID 归类路由（同时过滤路由权限）
        route_map: dict[int, list[dict]] = {}
        for r in routes:
            if not FeatureAccessService._check_route_permission(r, user_id, user_email, user_group_ids):
                continue
            route_map.setdefault(r.group_id, []).append({
                "name": r.name,
                "i18n_key": r.i18n_key,
                "route_path": r.route_path,
                "icon": r.icon,
                "is_external_window": r.is_external_window,
            })

        result = []
        for g in groups:
            # "_" 前缀分组是聊天内嵌功能等非侧边栏能力的权限载体，不下发给侧边栏
            if g.group_key.startswith("_"):
                continue
            if not FeatureAccessService._check_group_permission(g, user_id, user_email, user_group_ids):
                continue
            g_routes = route_map.get(g.id)
            if not g_routes:
                continue
            result.append({
                "id": g.id,
                "name": g.name,
                "i18n_key": g.i18n_key,
                "group_key": g.group_key,
                "routes": g_routes,
            })

        return result

    @staticmethod
    def check_route_access(session: Session, user_id: int, user_email: str, user_group_ids: list[int], route_path: str) -> bool:
        """
        校验用户是否有权限访问某条路由（分组权限 + 路由权限双重检查）。
        """
        stmt = (
            select(FeatureRoute, FeatureGroup)
            .join(FeatureGroup, FeatureRoute.group_id == FeatureGroup.id)
            .where(FeatureRoute.route_path == route_path)
            .where(FeatureRoute.is_active == True)
            .where(FeatureGroup.is_active == True)
        )
        result = session.exec(stmt).first()
        if not result:
            return False
        route, group = result
        if not FeatureAccessService._check_group_permission(group, user_id, user_email, user_group_ids):
            return False
        return FeatureAccessService._check_route_permission(route, user_id, user_email, user_group_ids)

    # ── 种子数据 ──

    # 本版下线的侧边栏入口：代码调试 / 代码移植 / 代码测试。
    # 前端页面与路由代码保留，仅不再由后端下发入口，因此侧边栏不显示。
    RETIRED_ROUTE_PATHS = ("/agent-debug", "/agent-migrate", "/agent-test")

    @staticmethod
    def prune_retired_routes(session: Session) -> None:
        """每次启动清理已下线入口，保证存量库升级后侧边栏同样不再显示。"""
        rows = session.exec(
            select(FeatureRoute).where(
                FeatureRoute.route_path.in_(FeatureAccessService.RETIRED_ROUTE_PATHS)
            )
        ).all()
        if not rows:
            return
        for r in rows:
            session.delete(r)
        session.commit()
        logger.info(
            "Pruned %d retired feature routes: %s",
            len(rows),
            [r.route_path for r in rows],
        )

    @staticmethod
    def seed_initial_data(session: Session):
        """表为空时插入种子数据（从硬编码的侧边栏配置迁移）"""
        existing = session.exec(select(FeatureGroup)).first()
        if existing is not None:
            return

        logger.info("Seeding feature_groups and feature_routes tables...")

        groups_data = [
            # (name, group_key, i18n_key, sort_order)
            ("AI智能体", "agents", "nav_agents", 1),
            ("AI工具箱", "toolbox", "nav_ai_toolbox", 2),
            ("应用中心", "apps", "nav_app_center", 3),
        ]

        group_id_map = {}
        for name, key, i18n_key, sort_order in groups_data:
            g = FeatureGroup(
                name=name,
                group_key=key,
                i18n_key=i18n_key,
                sort_order=sort_order,
                visibility="ALL",
            )
            session.add(g)
            session.flush()
            group_id_map[key] = g.id

        routes_data = [
            # (group_key, name, i18n_key, route_path, icon, is_external_window, sort_order)
            # 代码调试(/agent-debug)、代码移植(/agent-migrate)、代码测试(/agent-test)
            # 三条入口本版不下发，见 RETIRED_ROUTE_PATHS。
            ("agents", "代码审查", "agent_review", "/code-review", "IconZoomCode", False, 2),
            ("agents", "翻译", "agent_translate", "/translator", "IconLanguage", False, 5),
            ("toolbox", "示波器", "agent_oscilloscope", "/oscilloscope", "IconRadar2", True, 1),
            ("toolbox", "硬件参数辨识", "agent_hardware_review", "/hardware-review", "IconCircuitDiode", True, 2),
            ("toolbox", "电机参数辨识", "agent_param_identification", "/parameter-identification", "IconHeartbeat", False, 3),
            ("toolbox", "Code Assistant", "agent_vibe_coding", "/vibe-coding", "IconTerminal2", True, 4),
            ("toolbox", "Integrated Test", "agent_integrated_test_system", "/integrated-test-system", "IconTestPipe", True, 5),
            ("apps", "外链导航", "nav_quick_links", "/external-links", "IconApps", False, 1),
        ]

        for gkey, name, i18n_key, route_path, icon, is_ext, sort_order in routes_data:
            r = FeatureRoute(
                group_id=group_id_map[gkey],
                name=name,
                i18n_key=i18n_key,
                route_path=route_path,
                icon=icon,
                is_external_window=is_ext,
                sort_order=sort_order,
            )
            session.add(r)

        session.commit()
        logger.info("Feature access data seeded successfully")

    # 聊天内嵌功能的权限记录（如 AI 绘图）不是侧边栏路由，route_path 用
    # "chat:xxx" 约定标识，分组用 "_chat"（"_" 前缀 = 不下发侧边栏）。
    # 与 seed_initial_data 的"表空才种"不同，这里每次启动都查漏补种：
    # 既覆盖存量库首次上线，也让误删后重启自愈（check_route_access 查无
    # 记录会 fail-closed 拒绝所有人，功能会整体不可用）。
    CHAT_IMAGE_GEN_ROUTE = "chat:image-gen"

    @staticmethod
    def seed_chat_feature_entries(session: Session):
        existing = session.exec(
            select(FeatureRoute).where(
                FeatureRoute.route_path == FeatureAccessService.CHAT_IMAGE_GEN_ROUTE
            )
        ).first()
        if existing is not None:
            return

        group = session.exec(
            select(FeatureGroup).where(FeatureGroup.group_key == "_chat")
        ).first()
        if group is None:
            group = FeatureGroup(
                name="聊天内嵌功能",
                group_key="_chat",
                sort_order=99,
                visibility="ALL",
            )
            session.add(group)
            session.flush()

        session.add(FeatureRoute(
            group_id=group.id,
            name="AI 绘图",
            i18n_key="chat_image_mode",
            route_path=FeatureAccessService.CHAT_IMAGE_GEN_ROUTE,
            visibility="ALL",
        ))
        session.commit()
        logger.info("Seeded chat embedded feature route: chat:image-gen")
