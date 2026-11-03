"""
Code Assistant Service - 权限检查、credits 门控、渠道/配置管理
"""
import json
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select, col

from app.models.vibe_coding import VibeCodingConfig, VibeCodingChannel
from app.models.gateway import ModelPricing
from app.models.user_group import UserGroupMember
from app.services.credits_service import CreditsService, CREDIT_UNIT
from app.services.permission import check_entity_permission


class VibeCodingService:

    @staticmethod
    def seed_default_config(session: Session):
        """初始化默认配置行（id=1）"""
        existing = session.get(VibeCodingConfig, 1)
        if not existing:
            config = VibeCodingConfig(id=1)
            session.add(config)
            session.commit()

    @staticmethod
    def get_config(session: Session) -> VibeCodingConfig:
        """获取全局配置"""
        config = session.get(VibeCodingConfig, 1)
        if not config:
            config = VibeCodingConfig(id=1)
            session.add(config)
            session.commit()
            session.refresh(config)
        return config

    @staticmethod
    def update_config(session: Session, data: dict) -> VibeCodingConfig:
        """更新全局配置"""
        config = VibeCodingService.get_config(session)
        for key, value in data.items():
            if hasattr(config, key) and key != "id":
                setattr(config, key, value)
        config.updated_at = datetime.now(timezone.utc)
        session.add(config)
        session.commit()
        session.refresh(config)
        return config

    @staticmethod
    def get_user_group_ids(session: Session, user_id: int) -> list[int]:
        """获取用户所属的所有用户组ID"""
        stmt = select(UserGroupMember.group_id).where(
            UserGroupMember.user_id == user_id
        )
        return list(session.exec(stmt).all())

    @staticmethod
    def _check_visibility(config: VibeCodingConfig, user_id: int, user_group_ids: list[int]) -> bool:
        """检查用户是否在可见范围内"""
        if config.visibility == "ALL":
            return True

        if config.visibility == "SPECIFIED":
            allowed_users = config.allowed_user_ids if isinstance(config.allowed_user_ids, list) else json.loads(config.allowed_user_ids or "[]")
            allowed_groups = config.allowed_group_ids if isinstance(config.allowed_group_ids, list) else json.loads(config.allowed_group_ids or "[]")

            if user_id in allowed_users:
                return True
            if any(gid in allowed_groups for gid in user_group_ids):
                return True

        return False

    @staticmethod
    def check_permission(
        session: Session,
        user_id: int,
        user_group_ids: list[int],
    ) -> dict:
        """
        检查用户权限 + credits 余额（统一 credits 池）。
        Returns: {"allowed": bool, "reason": str, "credits_balance": int}
        credits_balance 为整 credits（内部微单位 ÷ CREDIT_UNIT）。
        """
        config = VibeCodingService.get_config(session)

        if not config.enabled:
            return {"allowed": False, "reason": "Code Assistant 功能当前已关闭", "credits_balance": 0}

        if not VibeCodingService._check_visibility(config, user_id, user_group_ids):
            return {"allowed": False, "reason": "暂无使用 Code Assistant 的权限", "credits_balance": 0}

        credits = CreditsService.ensure_account(session, user_id)
        balance = credits.balance // CREDIT_UNIT
        if credits.balance <= 0:
            return {"allowed": False, "reason": "Credits 余额不足", "credits_balance": balance}

        return {"allowed": True, "reason": "", "credits_balance": balance}

    @staticmethod
    def check_access(
        session: Session,
        user_id: int,
        user_group_ids: list[int],
    ) -> dict:
        """仅校验访问权限（功能开关 + 可见性/白名单），不涉及每日额度。

        用于不计入额度、也不受额度耗尽限制的端点（如语音转写 /vibe-coding/asr）：
        额度满的用户仍可调用，且该调用不消耗额度。
        Returns: {"allowed": bool, "reason": str}
        """
        config = VibeCodingService.get_config(session)
        if not config.enabled:
            return {"allowed": False, "reason": "Code Assistant 功能当前已关闭"}
        if not VibeCodingService._check_visibility(config, user_id, user_group_ids):
            return {"allowed": False, "reason": "暂无使用 Code Assistant 的权限"}
        return {"allowed": True, "reason": ""}

    # ── 渠道管理 ──

    @staticmethod
    def get_channels(
        session: Session, channel_type: Optional[str] = None
    ) -> list[VibeCodingChannel]:
        """获取所有渠道列表；可选按 channel_type (main/subagent) 过滤"""
        stmt = select(VibeCodingChannel).order_by(VibeCodingChannel.id)
        if channel_type is not None:
            stmt = stmt.where(VibeCodingChannel.channel_type == channel_type)
        return list(session.exec(stmt).all())

    @staticmethod
    def create_channel(session: Session, data: dict) -> VibeCodingChannel:
        """新增渠道（默认未启用）；若标记 is_default 或为首个渠道则自动设为默认"""
        is_default = data.get("is_default", False)
        channel_type = data.get("channel_type", "main")
        protocol = data.get("protocol", "anthropic")
        # 首个 main 渠道自动设为默认；subagent 渠道与 main 默认隔离
        if channel_type == "main":
            existing_count = session.exec(
                select(VibeCodingChannel).where(VibeCodingChannel.channel_type == "main")
            ).all()
            if len(existing_count) == 0:
                is_default = True
            if is_default:
                _unset_all_defaults(session)
        else:
            is_default = False
        channel = VibeCodingChannel(
            name=data["name"],
            base_url=data["base_url"],
            api_key=data["api_key"],
            model=data["model"],
            enabled=False,
            is_default=is_default,
            channel_type=channel_type,
            protocol=protocol,
            provider_name=data.get("provider_name", "") or "",
            provider_icon=data.get("provider_icon", "") or "",
            provider_icon_size=data.get("provider_icon_size", "") or "",
            vision=bool(data.get("vision", False)),
            reasoning=bool(data.get("reasoning", False)),
            sort_order=int(data.get("sort_order", 0) or 0),
        )
        session.add(channel)
        session.commit()
        session.refresh(channel)
        return channel

    @staticmethod
    def update_channel(session: Session, channel_id: int, data: dict) -> VibeCodingChannel:
        """修改渠道"""
        channel = session.get(VibeCodingChannel, channel_id)
        if not channel:
            raise ValueError("渠道不存在")
        for key in ("name", "base_url", "api_key", "model", "is_default",
                    "channel_type", "protocol", "provider_name", "provider_icon",
                    "provider_icon_size", "vision", "reasoning", "sort_order"):
            if key in data:
                setattr(channel, key, data[key])
        if data.get("is_default") and channel.channel_type == "main":
            _unset_all_defaults(session, except_id=channel_id)
        channel.updated_at = datetime.now(timezone.utc)
        session.add(channel)
        session.commit()
        session.refresh(channel)
        return channel

    @staticmethod
    def delete_channel(session: Session, channel_id: int):
        """
        删除渠道。
        约束：若该渠道是最后一个 enabled 渠道，且至少还有用户在用 vibe coding，
        则阻止删除以避免线上零渠道。简化处理：仅在它是最后一个 enabled 时阻止。
        若删除的是默认渠道，则将第一个 enabled 渠道设为新的默认。
        """
        channel = session.get(VibeCodingChannel, channel_id)
        if not channel:
            raise ValueError("渠道不存在")
        if channel.enabled:
            other_enabled = session.exec(
                select(VibeCodingChannel).where(
                    VibeCodingChannel.enabled == True,
                    VibeCodingChannel.id != channel_id,
                )
            ).first()
            if not other_enabled:
                raise ValueError("不能删除最后一个启用的渠道")
        was_default = channel.is_default
        session.delete(channel)
        session.commit()
        if was_default:
            _promote_first_enabled_as_default(session)

    @staticmethod
    def enable_channel(session: Session, channel_id: int) -> VibeCodingChannel:
        """
        启用指定渠道；
        - main 类型：启用后若无默认渠道则自动设为默认（与现有逻辑一致）
        - subagent 类型：全局唯一启用，启用此条会自动停用其它所有 subagent
        """
        channel = session.get(VibeCodingChannel, channel_id)
        if not channel:
            raise ValueError("渠道不存在")
        # subagent 互斥：先停用其它 subagent
        if channel.channel_type == "subagent":
            others = session.exec(
                select(VibeCodingChannel).where(
                    VibeCodingChannel.channel_type == "subagent",
                    VibeCodingChannel.id != channel_id,
                    VibeCodingChannel.enabled == True,
                )
            ).all()
            for other in others:
                other.enabled = False
                other.updated_at = datetime.now(timezone.utc)
                session.add(other)
        channel.enabled = True
        channel.updated_at = datetime.now(timezone.utc)
        session.add(channel)
        session.commit()
        # main 启用后若没有默认渠道，将当前设为默认
        if channel.channel_type == "main":
            existing_default = session.exec(
                select(VibeCodingChannel).where(
                    VibeCodingChannel.is_default == True,
                    VibeCodingChannel.channel_type == "main",
                )
            ).first()
            if not existing_default:
                channel.is_default = True
                channel.updated_at = datetime.now(timezone.utc)
                session.add(channel)
                session.commit()
        session.refresh(channel)
        return channel

    @staticmethod
    def disable_channel(session: Session, channel_id: int) -> VibeCodingChannel:
        """禁用指定渠道；若禁用的是默认渠道则将第一个 enabled 提升为默认"""
        channel = session.get(VibeCodingChannel, channel_id)
        if not channel:
            raise ValueError("渠道不存在")
        was_default = channel.is_default
        channel.enabled = False
        channel.updated_at = datetime.now(timezone.utc)
        session.add(channel)
        session.commit()
        if was_default:
            _promote_first_enabled_as_default(session)
        session.refresh(channel)
        return channel

    @staticmethod
    def get_enabled_channels(session: Session) -> list[VibeCodingChannel]:
        """获取所有启用的渠道（用户可见）。仅返回 main 类型（subagent 不暴露选择）"""
        stmt = (
            select(VibeCodingChannel)
            .where(
                VibeCodingChannel.enabled == True,
                VibeCodingChannel.channel_type == "main",
            )
            .order_by(VibeCodingChannel.id)
        )
        return list(session.exec(stmt).all())

    @staticmethod
    def get_active_subagent_channel(session: Session) -> Optional[VibeCodingChannel]:
        """获取当前启用的子代理渠道（全局唯一，可能为 None）"""
        stmt = select(VibeCodingChannel).where(
            VibeCodingChannel.enabled == True,
            VibeCodingChannel.channel_type == "subagent",
        )
        return session.exec(stmt).first()

    @staticmethod
    def get_channel_by_id(session: Session, channel_id: int) -> Optional[VibeCodingChannel]:
        """按 id 查渠道"""
        return session.get(VibeCodingChannel, channel_id)

    @staticmethod
    def get_channel_pricing(session: Session, channel: VibeCodingChannel) -> Optional[ModelPricing]:
        """渠道 model 对应的 ModelPricing（即档位/模型定价），无则 None。

        约定：渠道 model 字段可填档位的 model_id（如 '极致'），从而复用统一网关的
        档位路由（upstream_model_id）、倍率（multiplier）与权限（visibility/allowed_*）。
        """
        return session.exec(
            select(ModelPricing).where(ModelPricing.model_id == channel.model)
        ).first()

    @staticmethod
    def public_model_label(
        session: Session, channel: VibeCodingChannel
    ) -> str:
        """渠道对外暴露的 model 标签（永不泄漏抽象档位背后的真实 model_id）。

        档位渠道（ModelPricing.is_tier=True）→ display_name 优先，回退 description，
        再回退 model_id；非档位渠道 → 直接用渠道 model（真实模型名，本就该展示）。
        计费/路由由后端按 token 绑定渠道的 channel.model 权威决定，与本标签无关。
        """
        pricing = VibeCodingService.get_channel_pricing(session, channel)
        if pricing is not None and pricing.is_tier:
            return pricing.display_name or pricing.description or pricing.model_id
        return channel.model

    @staticmethod
    def channel_context_window(session: Session, channel: VibeCodingChannel) -> int:
        """渠道上下文窗口（tokens）。取绑定 ModelPricing.context_window，无则 0。

        0 语义为"未下发/不裁剪"，由 CLI 侧决定回退默认。随 /token、/channels/available
        一起下发，让 CLI 不再靠模型名反推窗口大小。
        """
        pricing = VibeCodingService.get_channel_pricing(session, channel)
        return int(pricing.context_window) if pricing and pricing.context_window else 0

    @staticmethod
    def is_channel_tier_visible(
        session: Session,
        channel: VibeCodingChannel,
        user_id: int,
        user_group_ids: list[int],
        user_email: str = "",
    ) -> bool:
        """该渠道对应的档位是否对此用户可见。

        渠道 model 命中某条 ModelPricing → 套用其 visibility/allowed_* 权限；
        未命中（裸模型、未配定价）→ 视为可见，保持旧渠道行为不被破坏。
        """
        pricing = VibeCodingService.get_channel_pricing(session, channel)
        if pricing is None:
            return True
        return check_entity_permission(pricing, user_id, user_group_ids, user_email)


def _unset_all_defaults(session: Session, except_id: int | None = None):
    """取消所有渠道的默认状态"""
    stmt = select(VibeCodingChannel).where(VibeCodingChannel.is_default == True)
    if except_id is not None:
        stmt = stmt.where(VibeCodingChannel.id != except_id)
    for ch in session.exec(stmt).all():
        ch.is_default = False
        ch.updated_at = datetime.now(timezone.utc)
        session.add(ch)
    session.flush()


def _promote_first_enabled_as_default(session: Session):
    """将第一个启用的渠道提升为默认"""
    first = session.exec(
        select(VibeCodingChannel)
        .where(VibeCodingChannel.enabled == True)
        .order_by(VibeCodingChannel.id)
    ).first()
    if first:
        first.is_default = True
        first.updated_at = datetime.now(timezone.utc)
        session.add(first)
        session.commit()
