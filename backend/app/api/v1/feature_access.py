"""
Feature Access API - 功能分组与路由管理端点
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import get_db, get_current_user, require_admin
from app.models.user import User
from app.schemas.common import success_response, error_response
from app.services.feature_access_service import FeatureAccessService
from app.services.vibe_coding_service import VibeCodingService


# ============================================================================
# 管理路由
# ============================================================================

admin_router = APIRouter(prefix="/features", tags=["Feature Access Admin"])


# ── Request schemas ──

class GroupCreateRequest(BaseModel):
    name: str
    group_key: str
    i18n_key: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True
    visibility: str = "ALL"
    allowed_group_ids: List[int] = []
    allowed_user_ids: List[int] = []


class GroupUpdateRequest(BaseModel):
    name: Optional[str] = None
    group_key: Optional[str] = None
    i18n_key: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    visibility: Optional[str] = None
    allowed_group_ids: Optional[List[int]] = None
    allowed_user_ids: Optional[List[int]] = None


class RouteCreateRequest(BaseModel):
    group_id: int
    name: str
    i18n_key: Optional[str] = None
    route_path: str
    icon: Optional[str] = None
    is_external_window: bool = False
    sort_order: int = 0
    is_active: bool = True
    visibility: str = "ALL"
    allowed_group_ids: List[int] = []
    allowed_user_ids: List[int] = []


class RouteUpdateRequest(BaseModel):
    group_id: Optional[int] = None
    name: Optional[str] = None
    i18n_key: Optional[str] = None
    route_path: Optional[str] = None
    icon: Optional[str] = None
    is_external_window: Optional[bool] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    visibility: Optional[str] = None
    allowed_group_ids: Optional[List[int]] = None
    allowed_user_ids: Optional[List[int]] = None


# ── Group endpoints ──

@admin_router.get("/groups")
def get_groups(
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    groups = FeatureAccessService.get_groups(session)
    return success_response(groups)


@admin_router.post("/groups")
def create_group(
    req: GroupCreateRequest,
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    try:
        group = FeatureAccessService.create_group(session, req.model_dump())
        return success_response({
            "id": group.id,
            "name": group.name,
            "group_key": group.group_key,
        })
    except Exception as e:
        return error_response(str(e))


@admin_router.put("/groups/{group_id}")
def update_group(
    group_id: int,
    req: GroupUpdateRequest,
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    try:
        data = req.model_dump(exclude_unset=True)
        FeatureAccessService.update_group(session, group_id, data)
        return success_response(message="更新成功")
    except ValueError as e:
        return error_response(str(e), code=404)


@admin_router.delete("/groups/{group_id}")
def delete_group(
    group_id: int,
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    try:
        FeatureAccessService.delete_group(session, group_id)
        return success_response(message="删除成功")
    except ValueError as e:
        return error_response(str(e))


# ── Route endpoints ──

@admin_router.get("/routes")
def get_routes(
    group_id: Optional[int] = Query(None),
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    routes = FeatureAccessService.get_routes(session, group_id)
    return success_response(routes)


@admin_router.post("/routes")
def create_route(
    req: RouteCreateRequest,
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    try:
        route = FeatureAccessService.create_route(session, req.model_dump())
        return success_response({
            "id": route.id,
            "name": route.name,
            "route_path": route.route_path,
        })
    except Exception as e:
        return error_response(str(e))


@admin_router.put("/routes/{route_id}")
def update_route(
    route_id: int,
    req: RouteUpdateRequest,
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    try:
        data = req.model_dump(exclude_unset=True)
        FeatureAccessService.update_route(session, route_id, data)
        return success_response(message="更新成功")
    except ValueError as e:
        return error_response(str(e), code=404)


@admin_router.delete("/routes/{route_id}")
def delete_route(
    route_id: int,
    session: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    try:
        FeatureAccessService.delete_route(session, route_id)
        return success_response(message="删除成功")
    except ValueError as e:
        return error_response(str(e))


# ============================================================================
# 用户路由
# ============================================================================

user_router = APIRouter(prefix="/features", tags=["Feature Access"])


@user_router.get("/accessible")
def get_accessible_features(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户可见的功能分组+路由列表"""
    user_group_ids = VibeCodingService.get_user_group_ids(session, current_user.id)
    result = FeatureAccessService.get_accessible_features(
        session, current_user.id, current_user.email or "", user_group_ids
    )
    return success_response(result)


@user_router.get("/check-access")
def check_route_access(
    route: str = Query(..., description="要校验的路由路径"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """校验当前用户是否有权限访问指定路由"""
    user_group_ids = VibeCodingService.get_user_group_ids(session, current_user.id)
    has_access = FeatureAccessService.check_route_access(
        session, current_user.id, current_user.email or "", user_group_ids, route
    )
    return success_response({"has_access": has_access})
