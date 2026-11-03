"""
无密码模式（settings.AUTH_DISABLED）的本地管理员账号。

单机/离线部署时不做鉴权，所有请求统一落到这一个账号上：管理员角色、
邮箱域与内部可见性一致（功能分组 INTERNAL 也可见）、多会话不互踢、
已接受全部生效协议（免掉启动时的协议弹窗）。
"""
from typing import Optional

from sqlmodel import Session, select

from app.core.config import settings
from app.core.logger import logger
from app.models.user import User

# 无密码模式下任意密码都可登录，这里的口令只用于占位，不构成鉴权凭据。
_PLACEHOLDER_PASSWORD = "local-no-auth-mode"
# 无密码模式不做单设备互踢：多个窗口/进程同时持 token 都要有效。
_LOCAL_MAX_SESSIONS = 999


def get_or_create_local_admin(session: Session) -> User:
    """取（或首次创建）无密码模式的本地管理员账号。"""
    user: Optional[User] = session.exec(
        select(User).where(User.username == settings.AUTH_DISABLED_USERNAME)
    ).first()

    if user is None:
        user = User(
            username=settings.AUTH_DISABLED_USERNAME,
            nickname="本地管理员",
            email=settings.AUTH_DISABLED_EMAIL,
            auth_type="EMAIL",
            role="admin",
            is_active=True,
            email_verified=True,
            max_sessions=_LOCAL_MAX_SESSIONS,
        )
        user.set_password(_PLACEHOLDER_PASSWORD)
        session.add(user)
        session.commit()
        session.refresh(user)
        logger.info(f"AUTH_DISABLED: created local admin account '{user.username}'")
        return user

    # 存量账号可能是普通用户/被禁用/单会话，这里对齐到无密码模式需要的状态
    changed = False
    for field, value in (
        ("role", "admin"),
        ("is_active", True),
        ("email_verified", True),
        ("deleted_at", None),
    ):
        if getattr(user, field) != value:
            setattr(user, field, value)
            changed = True
    if user.max_sessions < _LOCAL_MAX_SESSIONS:
        user.max_sessions = _LOCAL_MAX_SESSIONS
        changed = True
    if changed:
        session.add(user)
        session.commit()
        session.refresh(user)

    return user


def accept_all_agreements(session: Session, user: User) -> None:
    """替本地账号接受全部生效协议——单机模式不弹协议对话框。"""
    from app.services.agreement_service import AgreementService

    needs, _, pending = AgreementService.check_acceptance_needed(session, user.id)
    if not needs:
        return
    AgreementService.accept_agreements(session, user.id, [a.id for a in pending])
    logger.info(f"AUTH_DISABLED: auto-accepted {len(pending)} agreement(s) for local admin")


def grant_vibe_coding_access(session: Session, user: User) -> None:
    """把本地账号加入 Code Assistant 白名单——单机模式下功能全开。

    只往 allowed_user_ids 里加这一个 id，不把可见性改成 ALL：
    关掉无密码模式后，这条配置不会顺带对全体用户开放。
    """
    import json

    from app.models.vibe_coding import VibeCodingConfig
    from app.services.vibe_coding_service import VibeCodingService

    config: VibeCodingConfig = VibeCodingService.get_config(session)
    allowed = config.allowed_user_ids
    if not isinstance(allowed, list):
        allowed = json.loads(allowed or "[]")
    if config.visibility == "ALL" or user.id in allowed:
        return
    allowed.append(user.id)
    config.allowed_user_ids = allowed
    session.add(config)
    session.commit()
    logger.info("AUTH_DISABLED: granted Code Assistant access to local admin")


def seed_local_admin() -> None:
    """启动时预置本地账号（仅 AUTH_DISABLED 开启时）。"""
    if not settings.AUTH_DISABLED:
        return
    from app.db.session import engine

    with Session(engine) as session:
        user = get_or_create_local_admin(session)
        accept_all_agreements(session, user)
        grant_vibe_coding_access(session, user)

    # 渠道 seed 依赖 admin 已建好（编码助手白名单），必须排在上面之后
    seed_builtin_llm_channel()


# ── 单机版自带大模型渠道 ─────────────────────────────────────────────────
#
# 安装版开箱即用的前提是渠道已经配好。这里在启动 seed 阶段把三条链路一次性
# 指到同一个 OpenAI 兼容上游：
#   1. 首页 AI 对话 —— gateway 按 model_pricing.chat_enabled + sort_order 出列表，
#      前端取第一条作默认，所以主模型必须 chat_enabled=True 且 sort_order 最小。
#   2. 各 Agent 判定 —— 客户端把 model id 写死在请求体里（见下表），gateway 用
#      model_pricing.is_active 做准入、channel_id 做路由，缺行就 400「模型不可用」。
#   3. 编码助手 CLI —— vibe_coding_channels 需要一条 channel_type='main' 的启用行，
#      否则 POST /vibe-coding/token 报「主代理渠道不存在」。
#
# 客户端会真正发出来的 model id 是固定的几个字面量，逐个建行并用
# upstream_model_id 折到实际可用的上游模型上——单机版只有一家上游，
# 别名行的存在只是为了不让这些功能撞上准入 400。

_CHANNEL_NAME = "单机内置大模型"
_VIBE_CHANNEL_NAME = "单机内置大模型（编码助手）"

# 上游上下文窗口。>0 时 AI 对话超窗会滑动丢弃最早历史，避免直接被上游拒。
_CONTEXT_WINDOW = 131072


# ── 主模型标识/展示名：从 .env 派生（2026-10-15 联动改造） ──
#
# 目标：**.env 里 MOTORDEBUG_LLM_MODEL 写什么，UI 下拉就显示什么，且真正调的就是它。**
#
# 改造前 model_id / 展示名是写死的字面量，与 .env 各写各的：只改 .env 会「显示 A、
# 实调 B」名实不符（2026-10-15 处理过一次）。现在两者同源——展示名由上游模型名推导，
# 改一处 .env 即全链路一致，不会再漂移。
#
# 派生规则：
#   'deepseek/deepseek-v4.1-flash' → model_id: 'deepseek-v4.1-flash'
#                                  → 展示名  : 'DeepSeek V4.1 Flash'
# 即：model_id 取上游名的末段（去掉 '厂商/' 前缀）；展示名把 model_id 按 '-' 分词、
# 每段首字母大写后空格相连。若派生结果为空（.env 没配），回退到函数内写死的兜底值，
# 保证 seed 不会因为 .env 缺项而崩。

# .env 未配置时的兜底（与 config.py 的 MOTORDEBUG_LLM_MODEL 默认值保持一致）
_FALLBACK_MODEL_ID = "deepseek-v4.1-flash"


def _derive_main_model_id() -> str:
    """从 .env 的上游模型名派生网关 model_id（去掉 '厂商/' 前缀的末段）。"""
    upstream = settings.MOTORDEBUG_LLM_MODEL.strip()
    if not upstream:
        return _FALLBACK_MODEL_ID
    return upstream.rsplit("/", 1)[-1] or _FALLBACK_MODEL_ID


# 厂商名的大小写修正表：capitalize() 会把 'deepseek' 变成 'Deepseek'，与官方写法不符。
# 命中即用官方写法，未命中的厂商名按 capitalize() 兜底（如 'kimi' -> 'Kimi'）。
_BRAND_CASE = {
    "deepseek": "DeepSeek",
    "openai": "OpenAI",
    "qwen": "Qwen",
    "glm": "GLM",
    "moonshotai": "MoonshotAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "meta": "Meta",
}


def _title_part(part: str) -> str:
    """单个 '-'-分隔片段转展示写法：品牌名查表，其余首字母大写。"""
    low = part.lower()
    if low in _BRAND_CASE:
        return _BRAND_CASE[low]
    # 纯版本号片段（如 'v4.1'、'k2'）→ 'V4.1' / 'K2'
    return part[:1].upper() + part[1:] if part else part


def _derive_main_display_name() -> str:
    """从 model_id 派生 UI 展示名：'deepseek-v4.1-flash' -> 'DeepSeek V4.1 Flash'。"""
    parts = _derive_main_model_id().split("-")
    return " ".join(_title_part(p) for p in parts if p) or _FALLBACK_MODEL_ID


# (model_id, 展示名, 用途, 是否走便宜档, 是否在首页对话露出, 是否标深度思考, sort_order)
#
# ⚠️ 首行（主模型）的两个名字由 .env 派生，**不要写死**：两者必须同源，否则会出现
# 「下拉显示 A、实际调 B」。其余别名行是客户端写死的 model id 字面量，保持硬编码。
#
# 注意 _seed_model_pricing 按 model_id 精确 upsert，改了 .env 导致 model_id 变化时
# 会**新增一行**而不是重命名旧行（旧行由下方清理逻辑置 is_active=False 停用）。
_SEEDED_MODELS = (
    (_derive_main_model_id(), _derive_main_display_name(), "首页对话与各 Agent 判定（同 .env 主模型）", False, True, True, -100),
    ("deepseek-v4-flash", "DeepSeek Flash", "对话起标题与内容安全分类", True, False, False, -90),
    ("deepseek-chat", "DeepSeek Chat", "AGENT_CHAT_DEFAULT_MODEL 兜底", False, False, False, -80),
    ("qwen3.7-plus", "注释翻译（首选）", "代码注释翻译", False, False, False, -70),
    ("glm-5.2", "注释翻译（兜底）", "代码注释翻译", False, False, False, -60),
)


def _upstream_for(fast: bool) -> str:
    """别名行要折到的真实上游模型名。"""
    if fast and settings.MOTORDEBUG_LLM_FAST_MODEL.strip():
        return settings.MOTORDEBUG_LLM_FAST_MODEL.strip()
    return settings.MOTORDEBUG_LLM_MODEL.strip()


def _provider_name() -> str:
    """渠道对外标注的提供方名。

    按 base_url 判断而不是写死：走 OpenRouter 中转时请求实际发给的是
    OpenRouter 及其挂载的服务商，标成 "DeepSeek" 会误导运维与计费对账。
    """
    base = settings.MOTORDEBUG_LLM_BASE_URL.lower()
    if "openrouter.ai" in base:
        return "OpenRouter"
    if "deepseek.com" in base:
        return "DeepSeek"
    return "自定义上游"


def _seed_gateway_channel(session: Session) -> int:
    """建/更新统一网关的上游渠道，返回渠道 id。按渠道名幂等。"""
    from app.models.gateway import GatewayChannel

    base_url = settings.MOTORDEBUG_LLM_BASE_URL.strip().rstrip("/")
    api_key = settings.MOTORDEBUG_LLM_API_KEY.strip()

    channel: Optional[GatewayChannel] = session.exec(
        select(GatewayChannel).where(GatewayChannel.name == _CHANNEL_NAME)
    ).first()

    if channel is None:
        channel = GatewayChannel(
            name=_CHANNEL_NAME,
            base_url=base_url,
            api_key=api_key,
            protocol="openai_chat",
            enabled=True,
        )
        session.add(channel)
        session.commit()
        session.refresh(channel)
        logger.info(f"AUTH_DISABLED: created gateway channel '{_CHANNEL_NAME}' -> {base_url}")
        return channel.id

    changed = False
    for field, value in (
        ("base_url", base_url),
        ("api_key", api_key),
        ("protocol", "openai_chat"),
        ("enabled", True),
    ):
        if getattr(channel, field) != value:
            setattr(channel, field, value)
            changed = True
    if changed:
        session.add(channel)
        session.commit()
        session.refresh(channel)
        logger.info(f"AUTH_DISABLED: updated gateway channel '{_CHANNEL_NAME}'")
    return channel.id


def _seed_model_pricing(session: Session, channel_id: int) -> None:
    """建/更新客户端会发出的那几个 model id 的定价行。

    费率一律为 0：单机版没有计费诉求，而 gateway 的余额闸门只看 balance > 0，
    零费率能保证跑再久都不会被扣到 0 而拦下请求。
    """
    from app.models.gateway import ModelPricing

    for (
        model_id,
        display_name,
        description,
        fast,
        chat_enabled,
        reasoning,
        sort_order,
    ) in _SEEDED_MODELS:
        upstream = _upstream_for(fast)
        row: Optional[ModelPricing] = session.exec(
            select(ModelPricing).where(ModelPricing.model_id == model_id)
        ).first()

        desired = {
            "display_name": display_name,
            "description": description,
            "upstream_model_id": upstream,
            "channel_id": channel_id,
            "in_rate": 0.0,
            "out_rate": 0.0,
            "cache_rate": 0.0,
            "cache_creation_rate": 0.0,
            "multiplier": 1.0,
            "chat_enabled": chat_enabled,
            "reasoning": reasoning,
            "context_window": _CONTEXT_WINDOW,
            "is_active": True,
            "provider_name": _provider_name(),
            "sort_order": sort_order,
            "visibility": "ALL",
        }

        if row is None:
            session.add(ModelPricing(model_id=model_id, **desired))
            continue
        for field, value in desired.items():
            if getattr(row, field) != value:
                setattr(row, field, value)
        session.add(row)

    # 清理历史遗留的本渠道行：改名后旧 model_id（如 deepseek-v4-pro）不会再被
    # 上面的 upsert 命中，会一直挂在网关列表里。这里把「绑本渠道 + 不在当前
    # _SEEDED_MODELS 名单内」的行停用（is_active=False），而不是物理删除——
    # 删除会连带破坏 ai_requests 等历史记录的外键引用与计费对账。
    seeded_ids = {m[0] for m in _SEEDED_MODELS}
    stale = session.exec(
        select(ModelPricing)
        .where(ModelPricing.channel_id == channel_id)
        .where(ModelPricing.is_active == True)  # noqa: E712
    ).all()
    stale_names = []
    for row in stale:
        if row.model_id not in seeded_ids:
            row.is_active = False
            row.chat_enabled = False
            session.add(row)
            stale_names.append(row.model_id)

    session.commit()
    logger.info(
        f"AUTH_DISABLED: seeded {len(_SEEDED_MODELS)} model_pricing rows on channel {channel_id}"
        + (f"; deactivated stale rows: {stale_names}" if stale_names else "")
    )


def _seed_vibe_channel(session: Session) -> None:
    """建/更新编码助手 CLI 的主代理渠道。按渠道名幂等。

    protocol 必须是 openai_chat：CLI 走 /api/v1/openai/chat/completions 转发，
    那条路由会硬校验渠道协议，写 anthropic 会被 400 挡掉。
    """
    from app.models.vibe_coding import VibeCodingChannel

    base_url = settings.MOTORDEBUG_LLM_BASE_URL.strip().rstrip("/")
    api_key = settings.MOTORDEBUG_LLM_API_KEY.strip()
    model = _SEEDED_MODELS[0][0]

    channel: Optional[VibeCodingChannel] = session.exec(
        select(VibeCodingChannel).where(VibeCodingChannel.name == _VIBE_CHANNEL_NAME)
    ).first()

    desired = {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "enabled": True,
        "is_default": True,
        "channel_type": "main",
        "protocol": "openai_chat",
        "provider_name": _provider_name(),
        "reasoning": True,
        "sort_order": 0,
    }

    if channel is None:
        session.add(VibeCodingChannel(name=_VIBE_CHANNEL_NAME, **desired))
        session.commit()
        logger.info(f"AUTH_DISABLED: created vibe coding channel '{_VIBE_CHANNEL_NAME}'")
        return

    changed = False
    for field, value in desired.items():
        if getattr(channel, field) != value:
            setattr(channel, field, value)
            changed = True
    if changed:
        session.add(channel)
        session.commit()
        logger.info(f"AUTH_DISABLED: updated vibe coding channel '{_VIBE_CHANNEL_NAME}'")


def seed_builtin_llm_channel() -> None:
    """把随包分发的大模型 key 落成可用渠道（仅 AUTH_DISABLED + 配了 key 时）。

    未配 key 就整段跳过，保持管理面板手工配置的老行为不变。
    """
    if not settings.AUTH_DISABLED:
        return
    if not settings.MOTORDEBUG_LLM_API_KEY.strip():
        logger.info("AUTH_DISABLED: MOTORDEBUG_LLM_API_KEY 未配置，跳过内置渠道 seed")
        return
    if not settings.MOTORDEBUG_LLM_MODEL.strip():
        logger.warning("AUTH_DISABLED: MOTORDEBUG_LLM_MODEL 为空，跳过内置渠道 seed")
        return

    from app.db.session import engine

    try:
        with Session(engine) as session:
            channel_id = _seed_gateway_channel(session)
            _seed_model_pricing(session, channel_id)
            _seed_vibe_channel(session)
    except Exception as exc:  # noqa: BLE001 - seed 失败不应拦住服务启动
        logger.error(f"AUTH_DISABLED: 内置大模型渠道 seed 失败: {exc}", exc_info=True)
