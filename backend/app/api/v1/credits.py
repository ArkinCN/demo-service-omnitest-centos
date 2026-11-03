"""
用户端 Credits 自查 — 余额/套餐概览、消费记录、套餐列表。

面向登录用户本人（get_current_user），与管理员端 gateway_admin 的 credits 接口区分。
余额、流水 amount 均为内部微单位，对外换算成整 credits（见 CREDIT_UNIT）。
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select, func

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.credits import SubscriptionPlan, UserSubscription, CreditTransaction
from app.models.ai_request import AIRequest
from app.models.gateway import ModuleDisplay, ModelPricing
from app.schemas.common import success_response
from app.services.credits_service import CreditsService, CREDIT_UNIT

router = APIRouter(prefix="/credits", tags=["Credits"])


def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """流水时间以 UTC 存储（多为 naive）。序列化时补上 UTC 时区标记，
    否则前端 new Date() 会按本地时区解析无偏移字符串，少算 8 小时。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


@router.get("/overview")
async def get_overview(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """本人余额 + 当前套餐概览（驱动用量详情页的资源进度条）。"""
    credits = CreditsService.ensure_account(session, current_user.id)
    balance = credits.balance // CREDIT_UNIT

    sub = session.exec(
        select(UserSubscription).where(UserSubscription.user_id == current_user.id)
    ).first()
    plan_key = sub.plan_key if sub else "trial"
    plan = session.exec(
        select(SubscriptionPlan).where(SubscriptionPlan.plan_key == plan_key)
    ).first()
    total_credits = plan.monthly_credits if plan else 0
    plan_name = plan.name if plan else plan_key

    # 本日/本月消耗：按 UTC+8 统计 consume 流水（流水以 naive UTC 存储）。
    # 统一用真实流水求和（浮点），避免与累计消耗口径/取整不一致导致「累计<本月」。
    cn_tz = timezone(timedelta(hours=8))
    now_cn = datetime.now(cn_tz)

    def _consumed_since(start_cn: datetime) -> float:
        start_utc_naive = start_cn.astimezone(timezone.utc).replace(tzinfo=None)
        units = session.exec(
            select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
                CreditTransaction.user_id == current_user.id,
                CreditTransaction.type == "consume",
                CreditTransaction.created_at >= start_utc_naive,
            )
        ).one()
        # consume 的 amount 为负，取绝对值换算成正 credits。
        return round(abs(units) / CREDIT_UNIT, 4)

    day_start = now_cn.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now_cn.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used_today = _consumed_since(day_start)
    used_month = _consumed_since(month_start)

    return success_response(data={
        "balance": balance,
        "total_credits": total_credits,
        "used_today": used_today,
        "used_month": used_month,
        "total_granted": round(credits.total_granted / CREDIT_UNIT, 4),
        "total_consumed": round(credits.total_consumed / CREDIT_UNIT, 4),
        "plan_key": plan_key,
        "plan_name": plan_name,
    })


@router.get("/transactions")
async def get_transactions(
    type: Optional[str] = Query(None, description="consume / earn / 空=全部"),
    module: Optional[str] = Query(None, description="按来源模块过滤（仅消耗类）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分页流水。type=consume(已使用) / earn(已获得)，module 按来源过滤。"""
    rows, total = CreditsService.get_transactions_paged(
        session, current_user.id, type_filter=type, module_filter=module,
        page=page, page_size=page_size,
    )

    # 批量取关联 ai_request 的 module_name（来源列）与 request_id（全链路排查 id）。
    req_ids = [r.ai_request_id for r in rows if r.ai_request_id]
    module_map: dict[int, str] = {}
    request_id_map: dict[int, Optional[str]] = {}
    if req_ids:
        reqs = session.exec(
            select(AIRequest).where(AIRequest.id.in_(req_ids))
        ).all()
        module_map = {req.id: req.module_name for req in reqs}
        request_id_map = {req.id: req.request_id for req in reqs}

    # 抽象展示:流水里 model 记的是计费用 model_id(如 claude-sonnet-5 /
    # gemini-3.1-flash-image-preview),对外应显示抽象标签(如"极致模式"/"AI 绘图"),
    # 与渠道/选择器对外口径一致,不泄漏真实模型。命中"抽象档位(is_tier)"或"绘图模型
    # (per_image_rate>0)"且配了 display_name 时才替换;其余普通模型保持真实名。
    model_ids = {r.model for r in rows if r.model}
    tier_label_map: dict[str, str] = {}
    if model_ids:
        pricings = session.exec(
            select(ModelPricing).where(ModelPricing.model_id.in_(model_ids))
        ).all()
        for p in pricings:
            is_abstract = p.is_tier or (p.per_image_rate or 0) > 0
            label = p.display_name or p.description
            if is_abstract and label:
                tier_label_map[p.model_id] = label

    items = [{
        "id": r.id,
        "created_at": _iso_utc(r.created_at),
        "type": r.type,
        "amount": r.amount / CREDIT_UNIT,
        "model": tier_label_map.get(r.model, r.model),
        "module": module_map.get(r.ai_request_id) if r.ai_request_id else None,
        "request_id": request_id_map.get(r.ai_request_id) if r.ai_request_id else None,
        "prompt_tokens": r.prompt_tokens,
        "completion_tokens": r.completion_tokens,
        "note": r.note,
    } for r in rows]

    return success_response(data={
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.get("/trend")
async def get_trend(
    rng: str = Query("7d", alias="range", description="today / 7d / 30d"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """消耗趋势：today 按小时、7d/30d 按天聚合（UTC+8），空桶补 0。"""
    cn_tz = timezone(timedelta(hours=8))
    now_cn = datetime.now(cn_tz)

    if rng == "today":
        start_cn = now_cn.replace(hour=0, minute=0, second=0, microsecond=0)
        keys = [f"{h:02d}:00" for h in range(now_cn.hour + 1)]
        key_of = lambda dt: f"{dt.hour:02d}:00"
    else:
        days = 30 if rng == "30d" else 7
        start_cn = (now_cn - timedelta(days=days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        keys = [(start_cn + timedelta(days=i)).strftime("%m-%d") for i in range(days)]
        key_of = lambda dt: dt.strftime("%m-%d")

    start_utc_naive = start_cn.astimezone(timezone.utc).replace(tzinfo=None)
    rows = session.exec(
        select(CreditTransaction.amount, CreditTransaction.created_at).where(
            CreditTransaction.user_id == current_user.id,
            CreditTransaction.type == "consume",
            CreditTransaction.created_at >= start_utc_naive,
        )
    ).all()

    agg = {k: 0 for k in keys}
    for amount, created in rows:
        if created is None:
            continue
        dt_cn = created.replace(tzinfo=timezone.utc).astimezone(cn_tz)
        k = key_of(dt_cn)
        if k in agg:
            agg[k] += abs(amount)

    points = [{"bucket": k, "credits": round(agg[k] / CREDIT_UNIT, 4)} for k in keys]
    return success_response(data={"range": rng, "points": points})


@router.get("/module-displays")
async def get_module_displays(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """启用中的来源显示映射（module_key → label + color），驱动用量页来源标签。"""
    rows = session.exec(
        select(ModuleDisplay)
        .where(ModuleDisplay.is_active == True)  # noqa: E712
        .order_by(ModuleDisplay.sort_order, ModuleDisplay.id)
    ).all()
    return success_response(data=[
        {"module_key": r.module_key, "label": r.label, "color": r.color}
        for r in rows
    ])


@router.get("/modules")
async def list_modules(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """本人消耗流水涉及的来源模块（驱动前端来源筛选下拉）。"""
    return success_response(data=CreditsService.list_consume_modules(session, current_user.id))


@router.get("/plans")
async def list_plans(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """启用中的套餐列表（驱动订阅与账单页当前套餐高亮）。"""
    rows = session.exec(
        select(SubscriptionPlan).where(SubscriptionPlan.is_active == True)  # noqa: E712
    ).all()
    return success_response(data=[{
        "plan_key": p.plan_key,
        "name": p.name,
        "monthly_credits": p.monthly_credits,
    } for p in rows])
