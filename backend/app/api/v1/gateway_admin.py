"""
统一网关后台管理 — 渠道 / 模型定价倍率 / 套餐与 credits / 日志错误面板

全部走 require_admin。
"""
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session, select, func, or_
from sqlalchemy import text as sa_text

from app.api.deps import get_db, require_admin
from app.models.user import User
from app.models.gateway import GatewayChannel, ModelPricing, ModuleDisplay
from app.models.credits import (
    SubscriptionPlan, UserSubscription, UserCredits, CreditTransaction,
)
from app.models.ai_request import AIRequest
from app.models.error_log import ErrorRequestLog
from app.models.stat_group import StatGroupSelection
from app.models.user_group import UserGroup, UserGroupMember
from app.schemas.common import success_response, error_response
from app.services.credits_service import CreditsService, CREDIT_UNIT
from app.services.dashboard_service import DashboardService

admin_router = APIRouter(prefix="/gateway-admin", tags=["Gateway Admin"])


# ── 渠道管理 ──

class ChannelRequest(BaseModel):
    name: str
    base_url: str
    api_key: str
    protocol: str = "anthropic"
    enabled: bool = True


@admin_router.get("/channels")
async def list_channels(session: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = session.exec(select(GatewayChannel).order_by(GatewayChannel.id)).all()
    return success_response(data=[r.model_dump() for r in rows])


@admin_router.post("/channels")
async def create_channel(
    body: ChannelRequest, session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    ch = GatewayChannel(**body.model_dump())
    session.add(ch)
    session.commit()
    session.refresh(ch)
    return success_response(data=ch.model_dump(), message="渠道已创建")


@admin_router.put("/channels/{channel_id}")
async def update_channel(
    channel_id: int, body: ChannelRequest,
    session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    ch = session.get(GatewayChannel, channel_id)
    if not ch:
        return error_response(message="渠道不存在", code=404)
    for k, v in body.model_dump().items():
        setattr(ch, k, v)
    ch.updated_at = datetime.now(timezone.utc)
    session.add(ch)
    session.commit()
    session.refresh(ch)
    return success_response(data=ch.model_dump(), message="渠道已更新")


@admin_router.delete("/channels/{channel_id}")
async def delete_channel(
    channel_id: int, session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    ch = session.get(GatewayChannel, channel_id)
    if not ch:
        return error_response(message="渠道不存在", code=404)
    session.delete(ch)
    session.commit()
    return success_response(data={"id": channel_id}, message="渠道已删除")


# ── 模型定价 / 倍率 ──

class PricingRequest(BaseModel):
    model_id: str
    display_name: str = ""
    upstream_model_id: str = ""
    is_tier: bool = False
    description: str = ""
    channel_id: Optional[int] = None
    in_rate: float = 0.0
    out_rate: float = 0.0
    cache_rate: float = 0.0
    cache_creation_rate: Optional[float] = None
    multiplier: float = 1.0
    context_window: int = 0
    chat_enabled: bool = False
    vision: bool = False
    reasoning: bool = False
    provider_name: str = ""
    provider_icon: str = ""
    provider_icon_size: str = ""
    sort_order: int = 0
    visibility: str = "ALL"
    allowed_group_ids: List[int] = []
    allowed_user_ids: List[int] = []
    is_active: bool = True


@admin_router.get("/models")
async def list_models(session: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = session.exec(select(ModelPricing).order_by(ModelPricing.model_id)).all()
    return success_response(data=[r.model_dump() for r in rows])


@admin_router.post("/models")
async def create_model(
    body: PricingRequest, session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    if session.exec(select(ModelPricing).where(ModelPricing.model_id == body.model_id)).first():
        return error_response(message="模型已存在", code=409)
    data = body.model_dump()
    if data["cache_creation_rate"] is None:
        data["cache_creation_rate"] = body.in_rate
    m = ModelPricing(**data)
    session.add(m)
    session.commit()
    session.refresh(m)
    return success_response(data=m.model_dump(), message="模型已创建")


@admin_router.put("/models/{model_pk}")
async def update_model(
    model_pk: int, body: PricingRequest,
    session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    m = session.get(ModelPricing, model_pk)
    if not m:
        return error_response(message="模型不存在", code=404)
    data = body.model_dump()
    cache_creation_rate = data.pop("cache_creation_rate")
    for k, v in data.items():
        setattr(m, k, v)
    if cache_creation_rate is not None:
        m.cache_creation_rate = cache_creation_rate
    m.updated_at = datetime.now(timezone.utc)
    session.add(m)
    session.commit()
    session.refresh(m)
    return success_response(data=m.model_dump(), message="模型已更新")


@admin_router.post("/models/{model_pk}/recalc-cost")
async def recalc_model_cost(
    model_pk: int, session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    """按该模型当前定价重算历史账目：

    1. ai_requests.cost_cents — 基础成本（不乘倍率）
    2. 已有 consume 流水的 amount/multiplier — 实扣 Credits（乘倍率）
    3. 无流水的成功请求补记 consume 流水（created_at 对齐请求时间，不动余额）
    """
    m = session.get(ModelPricing, model_pk)
    if not m:
        return error_response(message="模型不存在", code=404)
    if m.per_image_rate and m.per_image_rate > 0:
        return error_response(message="按张计费模型不支持按 token 重算", code=400)
    rate_params = {
        "in_rate": m.in_rate,
        "cache_rate": m.cache_rate,
        "cache_creation_rate": m.cache_creation_rate,
        "out_rate": m.out_rate,
        "multiplier": m.multiplier,
        "model": m.model_id,
    }
    # tokens × (credits/M) → credits，×10000 → 0.0001 元，合并为 ÷100
    result = session.execute(
        sa_text(
            "UPDATE ai_requests SET cost_cents = ROUND(("
            "  (CASE WHEN prompt_tokens - cache_read_tokens - cache_creation_tokens > 0"
            "        THEN prompt_tokens - cache_read_tokens - cache_creation_tokens"
            "        ELSE 0 END) * :in_rate"
            "  + cache_read_tokens * :cache_rate"
            "  + cache_creation_tokens * :cache_creation_rate"
            "  + completion_tokens * :out_rate"
            ") / 100.0) WHERE model = :model"
        ),
        rate_params,
    )
    # tokens × (credits/M) × multiplier × CREDIT_UNIT(1M) ÷ 1M = tokens × rate × multiplier
    credits_expr = (
        "  ((CASE WHEN {p}prompt_tokens - {p}cache_read_tokens - {p}cache_creation_tokens > 0"
        "         THEN {p}prompt_tokens - {p}cache_read_tokens - {p}cache_creation_tokens"
        "         ELSE 0 END) * :in_rate"
        "   + {p}cache_read_tokens * :cache_rate"
        "   + {p}cache_creation_tokens * :cache_creation_rate"
        "   + {p}completion_tokens * :out_rate"
        "  ) * :multiplier"
    )
    txn_updated = session.execute(
        sa_text(
            "UPDATE credit_transactions SET"
            f" amount = -ROUND({credits_expr.format(p='')}),"
            " multiplier = :multiplier"
            " WHERE type = 'consume' AND model = :model"
            " AND (prompt_tokens > 0 OR completion_tokens > 0)"
        ),
        rate_params,
    )
    txn_backfilled = session.execute(
        sa_text(
            "INSERT INTO credit_transactions"
            " (user_id, type, amount, balance_after, ai_request_id, model,"
            "  prompt_tokens, completion_tokens, cache_read_tokens, cache_creation_tokens,"
            "  multiplier, note, created_at)"
            " SELECT r.user_id, 'consume',"
            f" -ROUND({credits_expr.format(p='r.')}),"
            "  0, r.id, r.model,"
            "  r.prompt_tokens, r.completion_tokens, r.cache_read_tokens, r.cache_creation_tokens,"
            "  :multiplier, '补记：模型定价重算', r.created_at"
            " FROM ai_requests r"
            " WHERE r.model = :model AND r.success = 1 AND r.total_tokens > 0"
            " AND NOT EXISTS (SELECT 1 FROM credit_transactions t"
            "                 WHERE t.ai_request_id = r.id AND t.type = 'consume')"
        ),
        rate_params,
    )
    session.commit()
    return success_response(
        data={
            "model_id": m.model_id,
            "updated": result.rowcount,
            "credits_updated": txn_updated.rowcount,
            "credits_backfilled": txn_backfilled.rowcount,
        },
        message=(
            f"已重算 {result.rowcount} 条请求成本，"
            f"改写 {txn_updated.rowcount} 条 Credits 流水，补记 {txn_backfilled.rowcount} 条"
        ),
    )


@admin_router.get("/uncosted-models")
async def list_uncosted_models(
    session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    """有 token 消耗但 cost_cents=0 的请求按模型聚合，供补价后重算。"""
    rows = session.execute(
        sa_text(
            "SELECT model, COUNT(*) AS request_count, SUM(total_tokens) AS total_tokens,"
            " MIN(created_at) AS first_at, MAX(created_at) AS last_at"
            " FROM ai_requests"
            " WHERE cost_cents = 0 AND total_tokens > 0 AND model IS NOT NULL AND model != ''"
            " GROUP BY model ORDER BY request_count DESC"
        )
    ).all()
    priced = {
        p.model_id: p.id for p in session.exec(select(ModelPricing)).all()
    }
    return success_response(data=[
        {
            "model": r.model,
            "request_count": int(r.request_count),
            "total_tokens": int(r.total_tokens or 0),
            "first_at": str(r.first_at),
            "last_at": str(r.last_at),
            "model_pk": priced.get(r.model),
        }
        for r in rows
    ])


@admin_router.delete("/models/{model_pk}")
async def delete_model(
    model_pk: int, session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    m = session.get(ModelPricing, model_pk)
    if not m:
        return error_response(message="模型不存在", code=404)
    session.delete(m)
    session.commit()
    return success_response(data={"id": model_pk}, message="模型已删除")


# ── 来源显示映射（module_name → 友好名 + 配色） ──

class ModuleDisplayRequest(BaseModel):
    module_key: str
    label: str
    color: str = "slate"
    sort_order: int = 0
    is_active: bool = True


@admin_router.get("/module-displays")
async def list_module_displays(session: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = session.exec(
        select(ModuleDisplay).order_by(ModuleDisplay.sort_order, ModuleDisplay.id)
    ).all()
    return success_response(data=[r.model_dump() for r in rows])


@admin_router.post("/module-displays")
async def create_module_display(
    body: ModuleDisplayRequest, session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    exists = session.exec(
        select(ModuleDisplay).where(ModuleDisplay.module_key == body.module_key)
    ).first()
    if exists:
        return error_response(message="该来源标识已存在", code=400)
    m = ModuleDisplay(**body.model_dump())
    session.add(m)
    session.commit()
    session.refresh(m)
    return success_response(data=m.model_dump(), message="来源映射已创建")


@admin_router.put("/module-displays/{display_id}")
async def update_module_display(
    display_id: int, body: ModuleDisplayRequest,
    session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    m = session.get(ModuleDisplay, display_id)
    if not m:
        return error_response(message="来源映射不存在", code=404)
    for k, v in body.model_dump().items():
        setattr(m, k, v)
    m.updated_at = datetime.now(timezone.utc)
    session.add(m)
    session.commit()
    session.refresh(m)
    return success_response(data=m.model_dump(), message="来源映射已更新")


@admin_router.delete("/module-displays/{display_id}")
async def delete_module_display(
    display_id: int, session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    m = session.get(ModuleDisplay, display_id)
    if not m:
        return error_response(message="来源映射不存在", code=404)
    session.delete(m)
    session.commit()
    return success_response(data={"id": display_id}, message="来源映射已删除")


# ── 统计分组勾选（统计页排行榜 / 分组趋势维度，复用分组管理页的用户分组） ──

class StatGroupSelectionRequest(BaseModel):
    user_group_ids: List[int]


@admin_router.get("/stat-groups")
async def list_stat_groups(session: Session = Depends(get_db), _: User = Depends(require_admin)):
    groups = session.exec(
        select(UserGroup)
        .where(UserGroup.group_type == "CUSTOM", UserGroup.is_active == True)  # noqa: E712
        .order_by(UserGroup.id)
    ).all()
    counts = dict(session.exec(
        select(UserGroupMember.group_id, func.count(UserGroupMember.id))
        .group_by(UserGroupMember.group_id)
    ).all())
    selected = set(session.exec(select(StatGroupSelection.user_group_id)).all())
    return success_response(data={
        "groups": [
            {
                "id": g.id,
                "name": g.name,
                "parent_id": g.parent_id,
                "member_count": counts.get(g.id, 0),
                "selected": g.id in selected,
            }
            for g in groups
        ],
    })


@admin_router.put("/stat-groups/selection")
async def replace_stat_group_selection(
    body: StatGroupSelectionRequest,
    session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    group_ids = list(dict.fromkeys(body.user_group_ids))
    if group_ids:
        groups = session.exec(select(UserGroup).where(UserGroup.id.in_(group_ids))).all()
        by_id = {g.id: g for g in groups}
        if any(gid not in by_id for gid in group_ids):
            return error_response(message="分组不存在", code=404)
        invalid = [g.name for g in groups if g.group_type != "CUSTOM" or not g.is_active]
        if invalid:
            return error_response(
                message=f"仅支持勾选启用中的自定义分组：{'、'.join(invalid)}", code=400
            )
        # 强制互斥：所选分组间不允许有共同直属成员，否则统计会重复计数
        dup_user_ids = session.exec(
            select(UserGroupMember.user_id)
            .where(UserGroupMember.group_id.in_(group_ids))
            .group_by(UserGroupMember.user_id)
            .having(func.count(UserGroupMember.id) > 1)
        ).all()
        if dup_user_ids:
            rows = session.exec(
                select(User.username, UserGroup.name)
                .join(UserGroupMember, UserGroupMember.user_id == User.id)
                .join(UserGroup, UserGroup.id == UserGroupMember.group_id)
                .where(
                    User.id.in_(list(dup_user_ids)[:5]),
                    UserGroupMember.group_id.in_(group_ids),
                )
                .order_by(User.username)
            ).all()
            conflicts: dict = {}
            for uname, gname in rows:
                conflicts.setdefault(uname, []).append(gname)
            detail = "；".join(
                f"{u} 同时属于「{'」「'.join(gs)}」" for u, gs in conflicts.items()
            )
            return error_response(
                message=f"所选分组存在重复成员：{detail}，请先在分组管理中调整", code=400
            )
    for s in session.exec(select(StatGroupSelection)).all():
        session.delete(s)
    # SQLAlchemy flush 默认先 INSERT 后 DELETE，重新勾选已选分组会撞 user_group_id 唯一约束
    session.flush()
    for gid in group_ids:
        session.add(StatGroupSelection(user_group_id=gid))
    session.commit()
    return success_response(data={"selected": len(group_ids)}, message="统计分组已更新")


# ── 套餐与 credits ──

@admin_router.get("/plans")
async def list_plans(session: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = session.exec(select(SubscriptionPlan)).all()
    return success_response(data=[r.model_dump() for r in rows])


class PlanUpdateRequest(BaseModel):
    # 套餐额度（整 credits）。内测期为「每日额度」，字段沿用历史名 monthly_credits。
    monthly_credits: Optional[int] = None
    name: Optional[str] = None
    is_active: Optional[bool] = None


@admin_router.put("/plans/{plan_key}")
async def update_plan(
    plan_key: str, body: PlanUpdateRequest,
    session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    """修改套餐（如调节每日额度 monthly_credits）。改后对后续每日刷新/重置即时生效，
    不影响已发放的当前余额（需 reset/reset-all 或等下一刷新周期才套用新额度）。"""
    plan = session.exec(
        select(SubscriptionPlan).where(SubscriptionPlan.plan_key == plan_key)
    ).first()
    if plan is None:
        return error_response(message=f"套餐不存在: {plan_key}", code=404)
    data = body.model_dump(exclude_none=True)
    if "monthly_credits" in data and data["monthly_credits"] < 0:
        return error_response(message="额度不能为负", code=400)
    for k, v in data.items():
        setattr(plan, k, v)
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return success_response(data=plan.model_dump(), message="套餐已更新")


def _resolve_user(session: Session, identifier: str) -> Optional[User]:
    """按「用户ID / 邮箱 / 用户名 / 昵称」精确解析用户。纯数字优先当 ID，其次邮箱（含@），
    再依次尝试用户名、昵称精确匹配。找不到返回 None。"""
    ident = (identifier or "").strip()
    if not ident:
        return None
    if ident.isdigit():
        u = session.get(User, int(ident))
        if u:
            return u
    if "@" in ident:
        u = session.exec(select(User).where(User.email == ident)).first()
        if u:
            return u
    u = session.exec(select(User).where(User.username == ident)).first()
    if u:
        return u
    return session.exec(select(User).where(User.nickname == ident)).first()


def _search_users(session: Session, keyword: str, limit: int = 10) -> List[User]:
    """在 username / email / nickname 上做大小写不敏感的子串模糊搜索。
    关键字中的 LIKE 通配符（% _）按字面量转义，避免被当作通配模式。"""
    esc = keyword.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    pattern = f"%{esc}%"
    return list(session.exec(
        select(User).where(
            or_(
                User.username.ilike(pattern, escape="\\"),
                User.email.ilike(pattern, escape="\\"),
                User.nickname.ilike(pattern, escape="\\"),
            )
        ).limit(limit)
    ).all())


@admin_router.get("/credits/{identifier}")
async def get_user_credits(
    identifier: str, session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    """查询某用户的 credits（支持用户ID / 邮箱 / 用户名 / 昵称；精确未命中时模糊搜索）。
    精确命中或模糊唯一命中返回 credits 详情；模糊多命中返回 matches 候选列表，
    由前端展示后按数字 id 二次查询。响应附带解析到的用户信息，前端据此拿到
    数字 id 用于后续 grant/reset。"""
    ident = (identifier or "").strip()
    user = _resolve_user(session, ident)
    if user is None and ident:
        candidates = _search_users(session, ident)
        if len(candidates) == 1:
            user = candidates[0]
        elif candidates:
            return success_response(data={
                "matches": [
                    {"id": u.id, "username": u.username,
                     "nickname": u.nickname, "email": u.email}
                    for u in candidates
                ],
            })
    if user is None:
        return error_response(message=f"未找到用户: {identifier}", code=404)
    credits = CreditsService.ensure_account(session, user.id)
    txns = CreditsService.get_transactions(session, user.id, limit=100)
    return success_response(data={
        "user": {"id": user.id, "username": user.username, "email": user.email},
        "credits": credits.model_dump(),
        "transactions": [t.model_dump() for t in txns],
    })


class GrantRequest(BaseModel):
    credits: int
    note: str = ""


@admin_router.post("/credits/{user_id}/grant")
async def grant_credits(
    user_id: int, body: GrantRequest,
    session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    c = CreditsService.grant(session, user_id, body.credits, body.note)
    return success_response(data=c.model_dump(), message="已发放")


@admin_router.post("/credits/{user_id}/reset")
async def reset_credits(
    user_id: int, session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    c = CreditsService.reset_to_plan(session, user_id)
    return success_response(data=c.model_dump(), message="已重置为套餐额度")


@admin_router.post("/credits/reset-all")
async def reset_all_credits(session: Session = Depends(get_db), _: User = Depends(require_admin)):
    n = CreditsService.reset_all_to_plan(session)
    return success_response(data={"reset_count": n}, message=f"已重置 {n} 个用户")


# ── 日志 / 错误面板 ──

def _serialize_request_log(
    request: AIRequest,
    transaction: Optional[CreditTransaction],
    pricing: Optional[ModelPricing] = None,
) -> dict:
    cache_read_tokens = (
        transaction.cache_read_tokens if transaction else request.cache_read_tokens
    )
    cache_creation_tokens = (
        transaction.cache_creation_tokens
        if transaction
        else request.cache_creation_tokens
    )
    regular_input_tokens = max(
        request.prompt_tokens - cache_read_tokens - cache_creation_tokens, 0
    )
    base_cost_units = 0
    if pricing:
        base_credits = (
            regular_input_tokens / 1_000_000 * pricing.in_rate
            + cache_read_tokens / 1_000_000 * pricing.cache_rate
            + cache_creation_tokens / 1_000_000 * pricing.cache_creation_rate
            + request.completion_tokens / 1_000_000 * pricing.out_rate
        )
        base_cost_units = int(round(base_credits * CREDIT_UNIT))
    data = request.model_dump()
    data.update({
        "regular_input_tokens": regular_input_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "multiplier": transaction.multiplier if transaction else None,
        "cost_units": abs(transaction.amount) if transaction else 0,
        "base_cost_units": base_cost_units,
    })
    return data


def _load_pricing_map(session: Session) -> dict:
    return {p.model_id: p for p in session.exec(select(ModelPricing)).all()}


@admin_router.get("/requests")
async def list_requests(
    user_id: Optional[int] = Query(None),
    model: Optional[str] = Query(None),
    success: Optional[bool] = Query(None),
    limit: int = Query(100, le=500),
    session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    stmt = select(AIRequest, CreditTransaction).join(
        CreditTransaction,
        (CreditTransaction.ai_request_id == AIRequest.id)
        & (CreditTransaction.type == "consume"),
        isouter=True,
    )
    if user_id is not None:
        stmt = stmt.where(AIRequest.user_id == user_id)
    if model:
        stmt = stmt.where(AIRequest.model == model)
    if success is not None:
        stmt = stmt.where(AIRequest.success == success)
    stmt = stmt.order_by(AIRequest.created_at.desc()).limit(limit)
    rows = session.exec(stmt).all()
    pricing_map = _load_pricing_map(session)
    return success_response(data=[
        _serialize_request_log(request, transaction, pricing_map.get(request.model))
        for request, transaction in rows
    ])


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _apply_request_filters(stmt, user_id, module, model, success, start, end, group_ids=None):
    if user_id is not None:
        stmt = stmt.where(AIRequest.user_id == user_id)
    if group_ids is not None:
        stmt = stmt.where(AIRequest.user_id.in_(
            select(UserGroupMember.user_id).where(UserGroupMember.group_id.in_(group_ids))
        ))
    if module:
        stmt = stmt.where(AIRequest.module_name == module)
    if model:
        stmt = stmt.where(AIRequest.model == model)
    if success is not None:
        stmt = stmt.where(AIRequest.success == success)
    if start is not None:
        stmt = stmt.where(AIRequest.created_at >= _to_naive_utc(start))
    if end is not None:
        stmt = stmt.where(AIRequest.created_at < _to_naive_utc(end))
    return stmt


@admin_router.get("/request-details")
async def list_request_details(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user_id: Optional[int] = Query(None),
    module: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    success: Optional[bool] = Query(None),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    group_id: Optional[int] = Query(None),
    session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    """分页请求明细（含用户名、token 拆分、扣费），供管理面板统计页使用。"""
    group_ids = (
        DashboardService.expand_group_ids(session, group_id) if group_id is not None else None
    )
    count_stmt = _apply_request_filters(
        select(func.count(AIRequest.id)), user_id, module, model, success, start, end, group_ids,
    )
    total = session.exec(count_stmt).one() or 0

    stmt = select(AIRequest, CreditTransaction, User.username, User.nickname).join(
        CreditTransaction,
        (CreditTransaction.ai_request_id == AIRequest.id)
        & (CreditTransaction.type == "consume"),
        isouter=True,
    ).join(User, User.id == AIRequest.user_id, isouter=True)
    stmt = _apply_request_filters(stmt, user_id, module, model, success, start, end, group_ids)
    stmt = stmt.order_by(AIRequest.id.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = session.exec(stmt).all()

    items = []
    pricing_map = _load_pricing_map(session)
    for request, transaction, username, nickname in rows:
        data = _serialize_request_log(request, transaction, pricing_map.get(request.model))
        data["username"] = nickname or username or f"#{request.user_id}"
        if isinstance(data.get("created_at"), datetime) and data["created_at"].tzinfo is None:
            data["created_at"] = data["created_at"].replace(tzinfo=timezone.utc)
        items.append(data)

    return success_response(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max((total + page_size - 1) // page_size, 1),
        "items": items,
    })


@admin_router.get("/request-filter-options")
async def request_filter_options(
    session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    """请求明细筛选项：出现过请求的用户、来源模块、模型。"""
    users = session.exec(
        select(AIRequest.user_id, User.username, User.nickname, User.email)
        .join(User, User.id == AIRequest.user_id, isouter=True)
        .distinct()
    ).all()
    modules = session.exec(select(AIRequest.module_name).distinct()).all()
    models = session.exec(select(AIRequest.model).distinct()).all()
    return success_response(data={
        "users": sorted(
            [
                {
                    "id": uid,
                    "username": name or f"#{uid}",
                    "nickname": nickname,
                    "email": email,
                }
                for uid, name, nickname, email in users
            ],
            key=lambda u: u["username"].lower(),
        ),
        "modules": sorted(m for m in modules if m),
        "models": sorted(m for m in models if m),
    })


@admin_router.get("/errors")
async def list_errors(
    user_id: Optional[int] = Query(None),
    error_type: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    session: Session = Depends(get_db), _: User = Depends(require_admin),
):
    stmt = select(ErrorRequestLog)
    if user_id is not None:
        stmt = stmt.where(ErrorRequestLog.user_id == user_id)
    if error_type:
        stmt = stmt.where(ErrorRequestLog.error_type == error_type)
    stmt = stmt.order_by(ErrorRequestLog.created_at.desc()).limit(limit)
    rows = session.exec(stmt).all()
    return success_response(data=[r.model_dump() for r in rows])
