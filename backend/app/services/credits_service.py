"""
Credits 服务 — 套餐/订阅、余额、计费扣费、月度懒刷新、后台发放重置。

设计要点：
- 余额用整数内部单位避免浮点误差：1 credit = CREDIT_UNIT 个内部单位。
  套餐 monthly_credits 是「整 credits」，存入余额时 × CREDIT_UNIT。
- 模型费率单位为 credits / 1M tokens（后台直观配置）。
- 刷新用懒刷新：每次取账户时，若 credits_refreshed_at 不在当前刷新周期，
  把余额重置为套餐额度（不累加）。内测期周期为「每日」（见 _needs_refresh）。
- AI 对话与 vibe-coding 共用同一 credits 池。
"""
import json
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlmodel import Session, select

from app.models.credits import (
    SubscriptionPlan, UserSubscription, UserCredits, CreditTransaction,
)
from app.models.gateway import ModelPricing, ModuleDisplay
from app.models.ai_request import AIRequest
from app.core.logger import logger

# 1 credit = CREDIT_UNIT 个内部微单位（余额、流水 amount 均为微单位）。
# 取 100 万以保证小额 token 消耗也能精确累积（避免四舍五入成 0 而免费）。
CREDIT_UNIT = 1_000_000

# 内测默认套餐
TRIAL_PLAN_KEY = "trial"
# 内测期默认额度（每日刷新）。该值落库于 subscription_plans.monthly_credits，
# 后台可调节（PUT /gateway-admin/plans/{plan_key}），改库后立即对刷新/重置生效。
TRIAL_DAILY_CREDITS = 500


class CreditsService:

    # ── 计费（纯函数，便于测试） ──

    @staticmethod
    def calc_consume_units(
        session: Session,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> Tuple[int, Optional[float]]:
        """按 model_pricing 算本次消耗的内部单位数，返回 (units, multiplier)。

        未配置定价的模型按 0 计（不扣费），multiplier=None。
        """
        pricing = session.exec(
            select(ModelPricing).where(ModelPricing.model_id == model)
        ).first()
        if not pricing or not pricing.is_active:
            return 0, None

        billable_in = max(
            prompt_tokens - cache_read_tokens - cache_creation_tokens, 0
        )
        credits = (
            billable_in / 1_000_000 * pricing.in_rate
            + cache_read_tokens / 1_000_000 * pricing.cache_rate
            + cache_creation_tokens / 1_000_000 * pricing.cache_creation_rate
            + completion_tokens / 1_000_000 * pricing.out_rate
        ) * pricing.multiplier
        units = int(round(credits * CREDIT_UNIT))
        return units, pricing.multiplier

    # ── 账户：懒绑定 + 月度懒刷新 ──

    @staticmethod
    def ensure_account(session: Session, user_id: int) -> UserCredits:
        """确保用户有订阅与余额账户，并执行月度懒刷新。返回 UserCredits。"""
        sub = session.exec(
            select(UserSubscription).where(UserSubscription.user_id == user_id)
        ).first()
        credits = session.exec(
            select(UserCredits).where(UserCredits.user_id == user_id)
        ).first()

        now = datetime.now(timezone.utc)

        if sub is None:
            # 首次：绑定 trial 并发放本月额度
            sub = UserSubscription(
                user_id=user_id, plan_key=TRIAL_PLAN_KEY, credits_refreshed_at=now,
            )
            session.add(sub)
            if credits is None:
                credits = UserCredits(user_id=user_id, balance=0)
            monthly = CreditsService._plan_monthly_units(session, sub.plan_key)
            CreditsService._set_balance(
                session, credits, monthly, txn_type="grant",
                note=f"首次发放套餐额度 {sub.plan_key}",
            )
            session.commit()
            session.refresh(credits)
            return credits

        if credits is None:
            credits = UserCredits(user_id=user_id, balance=0)
            session.add(credits)
            session.commit()
            session.refresh(credits)

        # 每日懒刷新：refreshed_at 不在今天（UTC）→ 重置为套餐额度
        if CreditsService._needs_refresh(sub.credits_refreshed_at, now):
            monthly = CreditsService._plan_monthly_units(session, sub.plan_key)
            CreditsService._set_balance(
                session, credits, monthly, txn_type="reset",
                note=f"每日刷新套餐额度 {sub.plan_key}",
            )
            sub.credits_refreshed_at = now
            sub.updated_at = now
            session.add(sub)
            session.commit()
            session.refresh(credits)

        return credits

    @staticmethod
    def _needs_refresh(refreshed_at: Optional[datetime], now: datetime) -> bool:
        if refreshed_at is None:
            return True
        # 内测期：跨自然日即刷新（按 UTC 日界；与全库 UTC 存储一致）
        ra = refreshed_at
        if ra.tzinfo is None:
            ra = ra.replace(tzinfo=timezone.utc)
        return (ra.year, ra.month, ra.day) != (now.year, now.month, now.day)

    @staticmethod
    def _plan_monthly_units(session: Session, plan_key: str) -> int:
        # 返回套餐单周期额度对应的内部单位数。字段名 monthly_credits 为历史命名，
        # 内测期实际语义是「每日额度」（刷新周期见 _needs_refresh），后台可调。
        plan = session.exec(
            select(SubscriptionPlan).where(SubscriptionPlan.plan_key == plan_key)
        ).first()
        plan_credits = plan.monthly_credits if plan else 0
        return plan_credits * CREDIT_UNIT

    @staticmethod
    def _set_balance(
        session: Session, credits: UserCredits, new_balance: int,
        txn_type: str, note: str,
    ) -> None:
        """把余额设为 new_balance（重置/发放语义），并记一条流水。"""
        delta = new_balance - credits.balance
        credits.balance = new_balance
        if delta > 0:
            credits.total_granted += delta
        credits.updated_at = datetime.now(timezone.utc)
        session.add(credits)
        session.add(CreditTransaction(
            user_id=credits.user_id, type=txn_type, amount=delta,
            balance_after=new_balance, note=note,
        ))

    # ── 余额校验与扣费 ──

    @staticmethod
    def has_balance(session: Session, user_id: int) -> bool:
        credits = CreditsService.ensure_account(session, user_id)
        return credits.balance > 0

    @staticmethod
    def consume(
        session: Session,
        user_id: int,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_read_tokens: int = 0,
        ai_request_id: Optional[int] = None,
        cache_creation_tokens: int = 0,
    ) -> int:
        """事后扣费：按 token×倍率算消耗、扣余额、写流水。返回扣除的内部单位数。

        余额不足时扣到 0（不为负），透支部分记在流水里。
        """
        units, multiplier = CreditsService.calc_consume_units(
            session, model, prompt_tokens, completion_tokens, cache_read_tokens,
            cache_creation_tokens,
        )
        if units <= 0:
            return 0

        credits = CreditsService.ensure_account(session, user_id)
        new_balance = max(credits.balance - units, 0)
        actual = credits.balance - new_balance
        credits.balance = new_balance
        credits.total_consumed += units
        credits.updated_at = datetime.now(timezone.utc)
        session.add(credits)
        session.add(CreditTransaction(
            user_id=user_id, type="consume", amount=-units,
            balance_after=new_balance, ai_request_id=ai_request_id, model=model,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            multiplier=multiplier,
        ))
        session.commit()
        return units

    @staticmethod
    def consume_per_image(
        session: Session,
        user_id: int,
        model: str,
        image_count: int,
        ai_request_id: Optional[int] = None,
    ) -> int:
        """绘图按张扣费：units = per_image_rate × image_count × CREDIT_UNIT。

        per_image_rate 取自 model_pricing；未配置或为 0 则不扣（返回 0）。
        余额不足扣到 0（不为负）。返回扣除的内部单位数。
        """
        if image_count <= 0:
            return 0
        pricing = session.exec(
            select(ModelPricing).where(ModelPricing.model_id == model)
        ).first()
        if not pricing or not pricing.is_active or pricing.per_image_rate <= 0:
            return 0

        units = int(round(pricing.per_image_rate * image_count * CREDIT_UNIT))
        if units <= 0:
            return 0

        credits = CreditsService.ensure_account(session, user_id)
        new_balance = max(credits.balance - units, 0)
        credits.balance = new_balance
        credits.total_consumed += units
        credits.updated_at = datetime.now(timezone.utc)
        session.add(credits)
        session.add(CreditTransaction(
            user_id=user_id, type="consume", amount=-units,
            balance_after=new_balance, ai_request_id=ai_request_id, model=model,
            multiplier=pricing.multiplier,
        ))
        session.commit()
        return units

    @staticmethod
    def grant(session: Session, user_id: int, credits_amount: int, note: str = "") -> UserCredits:
        """后台发放：在现有余额上增加 credits_amount（整 credits）。"""
        credits = CreditsService.ensure_account(session, user_id)
        units = credits_amount * CREDIT_UNIT
        credits.balance += units
        credits.total_granted += units
        credits.updated_at = datetime.now(timezone.utc)
        session.add(credits)
        session.add(CreditTransaction(
            user_id=user_id, type="grant", amount=units,
            balance_after=credits.balance, note=note or "后台发放",
        ))
        session.commit()
        session.refresh(credits)
        return credits

    @staticmethod
    def reset_to_plan(session: Session, user_id: int) -> UserCredits:
        """后台重置：把余额重置为当前套餐额度，并刷新游标。"""
        credits = CreditsService.ensure_account(session, user_id)
        sub = session.exec(
            select(UserSubscription).where(UserSubscription.user_id == user_id)
        ).first()
        plan_key = sub.plan_key if sub else TRIAL_PLAN_KEY
        monthly = CreditsService._plan_monthly_units(session, plan_key)
        CreditsService._set_balance(
            session, credits, monthly, txn_type="reset", note="后台重置为套餐额度",
        )
        if sub:
            sub.credits_refreshed_at = datetime.now(timezone.utc)
            session.add(sub)
        session.commit()
        session.refresh(credits)
        return credits

    @staticmethod
    def reset_all_to_plan(session: Session) -> int:
        """后台批量重置所有有账户的用户。返回处理人数。"""
        rows = session.exec(select(UserCredits)).all()
        count = 0
        for c in rows:
            CreditsService.reset_to_plan(session, c.user_id)
            count += 1
        return count

    # ── 查询（后台） ──

    @staticmethod
    def get_transactions(session: Session, user_id: int, limit: int = 100) -> list[CreditTransaction]:
        stmt = (
            select(CreditTransaction)
            .where(CreditTransaction.user_id == user_id)
            .order_by(CreditTransaction.created_at.desc())
            .limit(limit)
        )
        return list(session.exec(stmt).all())

    # 已使用 = consume；已获得 = 发放/重置/退款。
    _EARN_TYPES = ("grant", "reset", "refund")

    @staticmethod
    def get_transactions_paged(
        session: Session,
        user_id: int,
        type_filter: Optional[str] = None,
        module_filter: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[list[CreditTransaction], int]:
        """分页查询用户流水。type_filter: 'consume' / 'earn' / None(全部)。

        module_filter: 按来源模块过滤（join ai_requests.module_name，仅消耗类有来源）。
        返回 (当前页行, 总条数)。
        """
        from sqlmodel import func
        from app.models.ai_request import AIRequest

        page = max(page, 1)
        page_size = max(min(page_size, 100), 1)

        conds = [CreditTransaction.user_id == user_id]
        if type_filter == "consume":
            conds.append(CreditTransaction.type == "consume")
        elif type_filter == "earn":
            conds.append(CreditTransaction.type.in_(CreditsService._EARN_TYPES))

        row_stmt = select(CreditTransaction)
        count_stmt = select(func.count()).select_from(CreditTransaction)
        if module_filter:
            row_stmt = row_stmt.join(AIRequest, CreditTransaction.ai_request_id == AIRequest.id)
            count_stmt = count_stmt.join(AIRequest, CreditTransaction.ai_request_id == AIRequest.id)
            conds.append(AIRequest.module_name == module_filter)

        total = session.exec(count_stmt.where(*conds)).one()
        rows = session.exec(
            row_stmt
            .where(*conds)
            .order_by(CreditTransaction.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return list(rows), int(total)

    @staticmethod
    def list_consume_modules(session: Session, user_id: int) -> list[str]:
        """用户消耗类流水涉及的来源模块去重列表（驱动前端来源筛选）。"""
        from app.models.ai_request import AIRequest

        rows = session.exec(
            select(AIRequest.module_name)
            .join(CreditTransaction, CreditTransaction.ai_request_id == AIRequest.id)
            .where(
                CreditTransaction.user_id == user_id,
                CreditTransaction.type == "consume",
            )
            .distinct()
        ).all()
        return sorted({m for m in rows if m})

    # ── Seed ──

    @staticmethod
    def seed_initial_data(session: Session) -> None:
        """seed trial 套餐 + 从旧 ai_pricing 迁移模型定价（仅当表为空时）。"""
        # 套餐
        existing_plan = session.exec(
            select(SubscriptionPlan).where(SubscriptionPlan.plan_key == TRIAL_PLAN_KEY)
        ).first()
        if not existing_plan:
            session.add(SubscriptionPlan(
                plan_key=TRIAL_PLAN_KEY, name="体验套餐", monthly_credits=TRIAL_DAILY_CREDITS,
            ))
            session.commit()
            logger.info(f"Seeded trial subscription plan ({TRIAL_DAILY_CREDITS}/day)")

        # 模型定价：仅当 model_pricing 全空时，从旧 MODEL_PRICING 迁移一份初值
        has_any = session.exec(select(ModelPricing)).first()
        if not has_any:
            try:
                from app.core.ai_pricing import MODEL_PRICING
                for model_id, p in MODEL_PRICING.items():
                    # 旧表 CNY/M tokens，初版直接当 credits/M tokens；倍率默认 1.0，
                    # cache_rate 缺省取 in_rate 的 10%（命中更便宜），后台可改。
                    session.add(ModelPricing(
                        model_id=model_id,
                        display_name=model_id,
                        in_rate=float(p.input_price),
                        out_rate=float(p.output_price),
                        cache_rate=float(p.input_price) * 0.1,
                        cache_creation_rate=float(p.input_price),
                        multiplier=1.0,
                        is_active=True,
                    ))
                session.commit()
                logger.info("Seeded model_pricing from ai_pricing.MODEL_PRICING")
            except Exception as e:
                logger.error(f"Seed model_pricing failed: {e}")

        # 绘图模型按张计费，独立幂等 upsert（不受上面 has_any 限制，已有部署也会补齐）。
        # per_image_rate 为初始单价（credits/张），后台可改。
        image_models = [
            ("gemini-3.1-flash-image-preview", "Gemini 绘图", 5.0),
            ("gpt-image-2", "GPT Image 2", 8.0),
        ]
        try:
            for model_id, display, rate in image_models:
                row = session.exec(
                    select(ModelPricing).where(ModelPricing.model_id == model_id)
                ).first()
                if row is None:
                    session.add(ModelPricing(
                        model_id=model_id, display_name=display,
                        per_image_rate=rate, multiplier=1.0, is_active=True,
                    ))
                elif not row.is_active or row.per_image_rate <= 0:
                    # 已存在但未启用/未设单价 → 补齐（不覆盖管理员已设的非零单价）
                    row.is_active = True
                    if row.per_image_rate <= 0:
                        row.per_image_rate = rate
                    session.add(row)
            session.commit()
            logger.info("Seeded/ensured image model pricing")
        except Exception as e:
            logger.error(f"Seed image model_pricing failed: {e}")

        # 来源显示映射：仅当 module_displays 全空时 seed 一套默认（与前端 fallback 同源）。
        # color 为调色板键名（blue/emerald/amber/pink/violet/rose/cyan/slate）。
        has_md = session.exec(select(ModuleDisplay)).first()
        if not has_md:
            try:
                defaults = [
                    ("ai_chat", "AI 对话", "blue"),
                    ("ai_chat_title", "对话标题", "slate"),
                    ("comment_translator", "注释翻译", "amber"),
                    ("ai_image", "AI 绘图", "pink"),
                    ("ai_image_generate", "AI 绘图", "pink"),
                    ("vibe-coding", "Code Assistant", "emerald"),
                    ("vibe-coding-gpt", "Code Assistant", "emerald"),
                    ("code_review", "代码审查", "rose"),
                    ("code_review_agent", "代码审查", "rose"),
                    ("code_porting", "代码移植", "violet"),
                    ("param_identification", "参数辨识", "cyan"),
                    ("motor_control_detection", "电机控制检测", "blue"),
                    ("shunt_detection", "分流检测", "amber"),
                    ("hardware_review", "硬件评审", "violet"),
                    ("cooling_fan_debug", "散热风扇调试", "cyan"),
                    ("cooling_fan_hardware_review", "散热风扇硬件评审", "violet"),
                    ("cooling_fan_shunt_detection", "散热风扇分流检测", "amber"),
                    ("hairdryer_debug", "吹风机调试", "rose"),
                    ("vacuum_debug", "吸尘器调试", "pink"),
                    ("common_test", "通用测试", "slate"),
                    ("volc-websearch", "联网搜索", "cyan"),
                    ("qwen-websearch", "联网搜索", "cyan"),
                    ("mimo-asr", "语音识别", "violet"),
                    ("unknown", "其他", "slate"),
                ]
                for i, (key, label, color) in enumerate(defaults):
                    session.add(ModuleDisplay(
                        module_key=key, label=label, color=color,
                        sort_order=i, is_active=True,
                    ))
                session.commit()
                logger.info("Seeded module_displays defaults")
            except Exception as e:
                logger.error(f"Seed module_displays failed: {e}")
