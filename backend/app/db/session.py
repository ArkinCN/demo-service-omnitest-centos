"""
Database session management
"""
from typing import Generator
from sqlmodel import Session, create_engine
from app.core.config import settings
from app.core.logger import logger


# ---------------------------------------------------------------------------
# 方言适配：同一份代码要能在 SQLite（本地开发）/ MySQL（边缘）/ PostgreSQL（门户）上跑
# ---------------------------------------------------------------------------

def is_postgres(url: str) -> bool:
    return url.startswith(("postgresql", "postgres"))


def is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _build_connect_args(url: str, schema: str) -> dict:
    """按方言给出驱动参数。三者互斥，不能共用一个字典。

    PG   : options 注入 search_path —— 这是「真机/演示两套数据、模型零改动」的关键，
           模型定义里不写 schema 前缀，换 search_path 等于换一整套数据。
    SQLite: FastAPI 的同步依赖运行在线程池中，必须关掉跨线程检查。
    MySQL: init_command 统一时区（PyMySQL 专属参数，其他驱动会报 TypeError）。
    """
    if is_postgres(url):
        return {"options": f"-csearch_path={schema}"}
    if is_sqlite(url):
        return {"check_same_thread": False}
    if url.startswith("mysql"):
        return {"init_command": "SET time_zone='+00:00'"}
    return {}


def _build_pool_kwargs(url: str) -> dict:
    """连接池参数按方言给。

    SQLite 是单文件，没有并发连接概念，用默认池即可。
    PG / MySQL 必须严格限制：原值 pool_size=100 + max_overflow=300 是为 MySQL
    max_connections=500 设计的，直接搬到 max_connections=100 的 PG 上，
    单个 worker 就能把连接吃满，表现为「突然全部请求超时」。
    """
    if is_sqlite(url):
        return {}
    return {
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT,
        "pool_recycle": settings.DB_POOL_RECYCLE,
        "pool_pre_ping": True,
    }


def _create_engine(url: str, schema: str):
    return create_engine(
        url,
        echo=False,
        connect_args=_build_connect_args(url, schema),
        **_build_pool_kwargs(url),
    )


# ---------------------------------------------------------------------------
# 引擎与运行模式
# ---------------------------------------------------------------------------

#: 真机数据引擎
_engine_live = _create_engine(settings.DATABASE_URL, settings.DB_SCHEMA)

#: 演示数据引擎。非 PG 没有 schema 概念，两者指向同一个库，
#: 演示模式因此不可用（由 is_demo_available 判断）。
_engine_demo = (
    _create_engine(settings.DATABASE_URL, settings.DB_DEMO_SCHEMA)
    if is_postgres(settings.DATABASE_URL)
    else _engine_live
)

#: 向后兼容：大量模块直接 `from app.db.session import engine`
engine = _engine_live

_VALID_MODES = ("live", "demo")
_current_mode: str = settings.DB_MODE if is_postgres(settings.DATABASE_URL) else "live"


def is_demo_available() -> bool:
    """演示模式依赖 PG 的两个 schema，SQLite/MySQL 部署不提供。"""
    return is_postgres(settings.DATABASE_URL)


def get_mode() -> str:
    return _current_mode


def set_mode(mode: str) -> None:
    """切换数据源模式。只改进程内状态，不重启、不迁移数据。"""
    global _current_mode
    if mode not in _VALID_MODES:
        raise ValueError(f"非法模式 {mode!r}，只接受 {_VALID_MODES}")
    if mode == "demo" and not is_demo_available():
        raise RuntimeError("演示模式需要 PostgreSQL（omnitest / omnitest_demo 双 schema）")
    _current_mode = mode


def get_engine():
    """按当前模式返回引擎。业务代码请通过 get_session 拿会话，不要直接用它。"""
    return _engine_demo if _current_mode == "demo" else _engine_live


def get_demo_dataset() -> str:
    """读演示 schema 里当前灌的是哪套数据集（normal / fault / stress）。

    不额外建一张「当前数据集」标记表，而是从数据本身取：
    三套演示数据的 runs.mode 分别是 demo-normal / demo-fault / demo-stress，
    取一行就知道当前是哪套。

    这样做的好处是没有「标记与实际数据不一致」的可能 —— 换数据集时如果忘记
    同步标记表，界面会显示错的场景名，而那种错误没人会主动去查。
    标记来自数据，天然一致。

    读不到（库未连、表为空、非 PG 部署）返回空串，调用方按「未知」处理。
    """
    if not is_demo_available():
        return ""
    from sqlalchemy import text

    try:
        with _engine_demo.connect() as conn:
            # 必须带 mode like 'demo-%' 过滤：演示模式下用户正常操作会新建 run，
            # 那些记录的 mode 是 'mock'（应用默认值），不加过滤可能取到它们，
            # 导致「明明灌的是 fault，界面显示别的场景」。
            mode = conn.execute(
                text("select mode from runs where mode like 'demo-%' limit 1")
            ).scalar()
    except Exception:  # noqa: BLE001 - 状态查询失败不该影响主流程
        return ""
    if not mode:
        return ""
    return str(mode).removeprefix("demo-")


def get_session() -> Generator[Session, None, None]:
    """
    Get database session for dependency injection

    Yields:
        Database session

    Usage:
        @app.get("/users")
        def get_users(session: Session = Depends(get_session)):
            return session.query(User).all()
    """
    with Session(get_engine()) as session:
        try:
            yield session
        except Exception as e:
            logger.error(f"Database session error: {str(e)}", exc_info=True)
            session.rollback()
            raise
        finally:
            session.close()


def init_db() -> None:
    """
    Initialize database - create all tables

    Note:
        This should be called during application startup
    """
    from sqlmodel import SQLModel
    from app.models.user import User  # Import all models
    from app.models.chat import Chat  # Import Chat model
    from app.models.feedback import Feedback, FeedbackReply  # Import Feedback models
    from app.models.ai_request import AIRequest  # Import AI request model
    from app.models.email_verification import EmailVerification
    from app.models.invitation_code import InvitationCode
    from app.models.invitation_application import InvitationApplication
    from app.models.invitation_application_verification import InvitationApplicationVerification
    from app.models.vibe_coding import VibeCodingConfig, VibeCodingChannel
    from app.models.feature_access import FeatureGroup, FeatureRoute
    from app.models.agreement import Agreement, UserAgreementAcceptance
    from app.models.gateway import GatewayChannel, ModelPricing
    from app.models.credits import (
        SubscriptionPlan, UserSubscription, UserCredits, CreditTransaction,
    )
    from app.models.task import Task
    from app.models.kb_entry import KbEntry, KbRef
    from app.models.kb_document import KbDocument  # 知识库上传文档（五阶段状态机）
    from app.models.run import Run, Artifact, ActionRecord
    from app.models.interlock import Interlock, GateState, EstopRecord
    from app.models.error_log import ErrorRequestLog
    from app.models.agent_chat_memory import AgentChatMemory  # 助手跨轮会话记忆
    from app.models.stat_group import StatGroupSelection
    from app.models.skill import (
        Skill, SkillVersion, SkillResourceFile, SkillCategory,
        ProjectSkillRule, SkillExpansionLog,
    )

    try:
        if is_postgres(settings.DATABASE_URL):
            # PG 下应用账号（*_app）**故意没有 CREATE 权限** —— 应用不能改库结构，
            # 建表/改列必须走显式迁移。所以这里不调用 create_all：
            # 它需要 CREATE 权限，会直接报 "no schema has been selected to create in"。
            # 改为漂移检测：表缺失或列缺失会在日志里明确告警，提示先跑建表脚本。
            _check_pg_column_drift(engine, settings.DB_SCHEMA)
            if is_demo_available():
                _check_pg_column_drift(_engine_demo, settings.DB_DEMO_SCHEMA)
        else:
            SQLModel.metadata.create_all(engine)
            logger.info("Database tables created successfully")
            # Auto-migrate: 历史增量列（仅 MySQL / SQLite 生效）
            _run_migrations(engine)

        # Seed vibe coding default config
        from app.services.vibe_coding_service import VibeCodingService
        with Session(engine) as seed_session:
            VibeCodingService.seed_default_config(seed_session)

        # Seed feature access data
        from app.services.feature_access_service import FeatureAccessService
        with Session(engine) as seed_session:
            FeatureAccessService.seed_initial_data(seed_session)
        # 聊天内嵌功能路由（chat:*）每次启动查漏补种，误删自愈
        with Session(engine) as seed_session:
            FeatureAccessService.seed_chat_feature_entries(seed_session)
        # 已下线入口（代码调试/代码移植/代码测试）每次启动清理，存量库升级后同样消失
        with Session(engine) as seed_session:
            FeatureAccessService.prune_retired_routes(seed_session)

        # Seed agreement data
        from app.services.agreement_service import AgreementService
        with Session(engine) as seed_session:
            AgreementService.seed_initial_data(seed_session)

        # Seed gateway credits/pricing data（套餐 + 模型定价）
        from app.services.credits_service import CreditsService
        with Session(engine) as seed_session:
            CreditsService.seed_initial_data(seed_session)

        # 无密码模式（AUTH_DISABLED）：预置本地管理员账号并替其接受协议
        from app.services.local_admin_service import seed_local_admin
        seed_local_admin()
    except Exception as e:
        logger.error(f"Error creating database tables: {str(e)}", exc_info=True)
        raise


def _backfill_i18n_keys(conn) -> None:
    """Backfill i18n_key for existing feature_groups and feature_routes where it's NULL"""
    from sqlalchemy import text

    group_keys = {
        "agents": "nav_agents",
        "toolbox": "nav_ai_toolbox",
        "apps": "nav_app_center",
    }
    for group_key, i18n_key in group_keys.items():
        conn.execute(text(
            "UPDATE feature_groups SET i18n_key = :i18n_key WHERE group_key = :group_key AND i18n_key IS NULL"
        ), {"i18n_key": i18n_key, "group_key": group_key})

    route_keys = {
        "/agent-debug": "agent_debug",
        "/code-review": "agent_review",
        "/agent-migrate": "agent_migrate",
        "/agent-test": "agent_test",
        "/translator": "agent_translate",
        "/oscilloscope": "agent_oscilloscope",
        "/hardware-review": "agent_hardware_review",
        "/parameter-identification": "agent_param_identification",
        "/vibe-coding": "agent_vibe_coding",
        "/integrated-test-system": "agent_integrated_test_system",
        "/external-links": "nav_quick_links",
    }
    for route_path, i18n_key in route_keys.items():
        conn.execute(text(
            "UPDATE feature_routes SET i18n_key = :i18n_key WHERE route_path = :route_path AND i18n_key IS NULL"
        ), {"i18n_key": i18n_key, "route_path": route_path})

    conn.commit()


def _backfill_cache_read_tokens(conn, inspector) -> None:
    """ai_requests 加缓存列前，历史 Cache R 只存在 consume 流水里，加列后回填一次。

    SQL 为 MySQL/SQLite 通用写法；老库的 credit_transactions 若缺相关列则跳过。
    """
    from sqlalchemy import text

    if "credit_transactions" not in inspector.get_table_names():
        return
    tx_columns = {c["name"] for c in inspector.get_columns("credit_transactions")}
    if not {"ai_request_id", "type", "cache_read_tokens"}.issubset(tx_columns):
        return
    logger.info("Migration: backfilling ai_requests.cache_read_tokens from consume transactions")
    conn.execute(text(
        "UPDATE ai_requests SET cache_read_tokens = ("
        "  SELECT MAX(ct.cache_read_tokens) FROM credit_transactions ct"
        "  WHERE ct.ai_request_id = ai_requests.id AND ct.type = 'consume'"
        ") WHERE EXISTS ("
        "  SELECT 1 FROM credit_transactions ct"
        "  WHERE ct.ai_request_id = ai_requests.id AND ct.type = 'consume'"
        "    AND ct.cache_read_tokens > 0"
        ")"
    ))


def _check_pg_column_drift(eng, schema: str) -> None:
    """PostgreSQL 环境下的结构漂移检测。

    create_all 只建「缺失的表」，不会给已存在的表补列 —— 这正是 MySQL 时代
    那一大堆 ALTER 存在的原因。PG 上我们不自动 ALTER（方言不同、误改风险高），
    改为启动时显式告警：让结构差异在日志里暴露，而不是等某个接口 500 才发现。

    schema 必须显式传入，不能靠 search_path 推断：has_table() 不带 schema 时
    取的是 dialect.default_schema_name（连接首次建立时缓存），
    对第二个引擎会取错，导致「表全在却报全缺失」的假警报。
    """
    from sqlalchemy import inspect
    from sqlmodel import SQLModel

    inspector = inspect(eng)
    drifted: list[str] = []
    for table in SQLModel.metadata.sorted_tables:
        if not inspector.has_table(table.name, schema=schema):
            drifted.append(f"{table.name}(整表缺失)")
            continue
        existing = {col["name"] for col in inspector.get_columns(table.name, schema=schema)}
        missing = [col.name for col in table.columns if col.name not in existing]
        if missing:
            drifted.append(f"{table.name}.{','.join(missing)}")

    if drifted:
        logger.warning(
            "PostgreSQL[%s] 结构漂移（model 有、库表无）：%s。"
            "PG 不自动 ALTER，请显式执行迁移后重启。",
            schema, "; ".join(drifted),
        )
    else:
        logger.info("PostgreSQL[%s] 结构检查通过：model 与库表一致", schema)


def _run_migrations(eng) -> None:
    """历史增量 ALTER（MySQL / SQLite 专用）。

    ⚠️ 下面这批 SQL 全是 MySQL 方言：TINYINT(1)、MODIFY COLUMN、CHANGE ...
    在 PostgreSQL 上执行必然语法错误。PG 是新建库，结构以 model 定义为准
    （create_all 一次建全），不走这段历史迁移。

    为什么不在 PG 上做等价转换：两套迁移分支迟早不同步，而 PG 这边没有历史包袱，
    唯一正确的来源就是 model。真要改 PG 结构，走显式迁移 + 版本化，而不是这里。
    """
    if is_postgres(settings.DATABASE_URL):
        _check_pg_column_drift(eng, settings.DB_SCHEMA)
        return

    from sqlalchemy import text, inspect

    # Add new columns: (table, column, SQL)
    add_column_migrations = [
        ("users", "email_verified", "ALTER TABLE users ADD COLUMN email_verified TINYINT(1) NOT NULL DEFAULT 0"),
        ("invitation_codes", "assigned_email", "ALTER TABLE invitation_codes ADD COLUMN assigned_email VARCHAR(120) DEFAULT NULL"),
        ("invitation_applications", "sales_email", "ALTER TABLE invitation_applications ADD COLUMN sales_email VARCHAR(120) DEFAULT NULL"),
        ("invitation_applications", "company", "ALTER TABLE invitation_applications ADD COLUMN company VARCHAR(200) DEFAULT NULL"),
        ("users", "token_version", "ALTER TABLE users ADD COLUMN token_version INT NOT NULL DEFAULT 0"),
        ("users", "max_sessions", "ALTER TABLE users ADD COLUMN max_sessions INT NOT NULL DEFAULT 1"),
        ("feature_routes", "visibility", "ALTER TABLE feature_routes ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'ALL'"),
        ("feature_routes", "allowed_group_ids", "ALTER TABLE feature_routes ADD COLUMN allowed_group_ids JSON DEFAULT NULL"),
        ("feature_routes", "allowed_user_ids", "ALTER TABLE feature_routes ADD COLUMN allowed_user_ids JSON DEFAULT NULL"),
        ("feature_groups", "i18n_key", "ALTER TABLE feature_groups ADD COLUMN i18n_key VARCHAR(100) DEFAULT NULL"),
        ("feature_routes", "i18n_key", "ALTER TABLE feature_routes ADD COLUMN i18n_key VARCHAR(100) DEFAULT NULL"),
        ("users", "company", "ALTER TABLE users ADD COLUMN company VARCHAR(200) DEFAULT NULL"),
        ("users", "real_name", "ALTER TABLE users ADD COLUMN real_name VARCHAR(100) DEFAULT NULL"),
        ("users", "watermark_consent_at", "ALTER TABLE users ADD COLUMN watermark_consent_at DATETIME DEFAULT NULL"),
        ("users", "deleted_at", "ALTER TABLE users ADD COLUMN deleted_at DATETIME DEFAULT NULL"),
        ("vibe_coding_channels", "is_default", "ALTER TABLE vibe_coding_channels ADD COLUMN is_default TINYINT(1) NOT NULL DEFAULT 0"),
        ("vibe_coding_channels", "channel_type", "ALTER TABLE vibe_coding_channels ADD COLUMN channel_type VARCHAR(20) NOT NULL DEFAULT 'main'"),
        ("vibe_coding_channels", "protocol", "ALTER TABLE vibe_coding_channels ADD COLUMN protocol VARCHAR(20) NOT NULL DEFAULT 'anthropic'"),
        ("vibe_coding_channels", "provider_name", "ALTER TABLE vibe_coding_channels ADD COLUMN provider_name VARCHAR(50) NOT NULL DEFAULT ''"),
        ("vibe_coding_channels", "provider_icon", "ALTER TABLE vibe_coding_channels ADD COLUMN provider_icon VARCHAR(200) NOT NULL DEFAULT ''"),
        ("vibe_coding_channels", "provider_icon_size", "ALTER TABLE vibe_coding_channels ADD COLUMN provider_icon_size VARCHAR(20) NOT NULL DEFAULT ''"),
        ("vibe_coding_channels", "vision", "ALTER TABLE vibe_coding_channels ADD COLUMN vision TINYINT(1) NOT NULL DEFAULT 0"),
        ("vibe_coding_channels", "reasoning", "ALTER TABLE vibe_coding_channels ADD COLUMN reasoning TINYINT(1) NOT NULL DEFAULT 0"),
        ("vibe_coding_channels", "sort_order", "ALTER TABLE vibe_coding_channels ADD COLUMN sort_order INT NOT NULL DEFAULT 0"),
        ("model_pricing", "context_window", "ALTER TABLE model_pricing ADD COLUMN context_window INT NOT NULL DEFAULT 0"),
        ("model_pricing", "chat_enabled", "ALTER TABLE model_pricing ADD COLUMN chat_enabled TINYINT(1) NOT NULL DEFAULT 0"),
        ("model_pricing", "vision", "ALTER TABLE model_pricing ADD COLUMN vision TINYINT(1) NOT NULL DEFAULT 0"),
        ("model_pricing", "reasoning", "ALTER TABLE model_pricing ADD COLUMN reasoning TINYINT(1) NOT NULL DEFAULT 0"),
        ("model_pricing", "provider_name", "ALTER TABLE model_pricing ADD COLUMN provider_name VARCHAR(50) NOT NULL DEFAULT ''"),
        ("model_pricing", "provider_icon", "ALTER TABLE model_pricing ADD COLUMN provider_icon VARCHAR(200) NOT NULL DEFAULT ''"),
        ("model_pricing", "provider_icon_size", "ALTER TABLE model_pricing ADD COLUMN provider_icon_size VARCHAR(20) NOT NULL DEFAULT ''"),
        ("model_pricing", "sort_order", "ALTER TABLE model_pricing ADD COLUMN sort_order INT NOT NULL DEFAULT 0"),
        ("model_pricing", "visibility", "ALTER TABLE model_pricing ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'ALL'"),
        ("model_pricing", "allowed_group_ids", "ALTER TABLE model_pricing ADD COLUMN allowed_group_ids JSON DEFAULT NULL"),
        ("model_pricing", "allowed_user_ids", "ALTER TABLE model_pricing ADD COLUMN allowed_user_ids JSON DEFAULT NULL"),
        ("model_pricing", "per_image_rate", "ALTER TABLE model_pricing ADD COLUMN per_image_rate FLOAT NOT NULL DEFAULT 0"),
        ("model_pricing", "upstream_model_id", "ALTER TABLE model_pricing ADD COLUMN upstream_model_id VARCHAR(100) NOT NULL DEFAULT ''"),
        ("model_pricing", "is_tier", "ALTER TABLE model_pricing ADD COLUMN is_tier TINYINT(1) NOT NULL DEFAULT 0"),
        # 知识库文档的自定义用途标签（2026-09-24）。表是先建的、列是后加的，
        # 所以必须走迁移；**只靠 create_all 不会给已存在的表补列**。
        ("kb_documents", "usage_label", "ALTER TABLE kb_documents ADD COLUMN usage_label VARCHAR(100) NOT NULL DEFAULT ''"),
        ("model_pricing", "description", "ALTER TABLE model_pricing ADD COLUMN description VARCHAR(500) NOT NULL DEFAULT ''"),
        ("model_pricing", "cache_creation_rate", "ALTER TABLE model_pricing ADD COLUMN cache_creation_rate FLOAT NOT NULL DEFAULT 0"),
        ("error_request_logs", "request_id", "ALTER TABLE error_request_logs ADD COLUMN request_id VARCHAR(64) DEFAULT NULL"),
        ("ai_requests", "request_id", "ALTER TABLE ai_requests ADD COLUMN request_id VARCHAR(64) DEFAULT NULL"),
        ("ai_requests", "cache_read_tokens", "ALTER TABLE ai_requests ADD COLUMN cache_read_tokens INT NOT NULL DEFAULT 0"),
        ("ai_requests", "cache_creation_tokens", "ALTER TABLE ai_requests ADD COLUMN cache_creation_tokens INT NOT NULL DEFAULT 0"),
        ("credit_transactions", "cache_creation_tokens", "ALTER TABLE credit_transactions ADD COLUMN cache_creation_tokens INT NOT NULL DEFAULT 0"),
        ("user_credits", "updated_at", "ALTER TABLE user_credits ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"),
    ]

    # Alter existing columns: (table, column, expected_nullable, SQL)
    alter_column_migrations = [
        ("invitation_codes", "created_by", True, "ALTER TABLE invitation_codes MODIFY COLUMN created_by INT DEFAULT NULL"),
    ]

    # Rename columns: (table, old_column, new_column, SQL)
    rename_column_migrations = [
        (
            "vibe_coding_channels",
            "is_active",
            "enabled",
            "ALTER TABLE vibe_coding_channels CHANGE is_active enabled TINYINT(1) NOT NULL DEFAULT 0",
        ),
    ]

    inspector = inspect(eng)
    with eng.connect() as conn:
        for table, column, sql in add_column_migrations:
            if table not in inspector.get_table_names():
                continue
            columns = [c["name"] for c in inspector.get_columns(table)]
            if column not in columns:
                logger.info(f"Migration: adding column {table}.{column}")
                conn.execute(text(sql))
                if table == "model_pricing" and column == "cache_creation_rate":
                    conn.execute(text(
                        "UPDATE model_pricing SET cache_creation_rate = in_rate"
                    ))
                if table == "ai_requests" and column == "cache_read_tokens":
                    _backfill_cache_read_tokens(conn, inspector)
                conn.commit()

        # Backfill i18n_key for existing feature data
        _backfill_i18n_keys(conn)

        for table, column, expected_nullable, sql in alter_column_migrations:
            if table not in inspector.get_table_names():
                continue
            columns = {c["name"]: c for c in inspector.get_columns(table)}
            if column in columns and columns[column].get("nullable") != expected_nullable:
                logger.info(f"Migration: altering column {table}.{column}")
                conn.execute(text(sql))
                conn.commit()

        for table, old_column, new_column, sql in rename_column_migrations:
            if table not in inspector.get_table_names():
                continue
            columns = [c["name"] for c in inspector.get_columns(table)]
            if old_column in columns and new_column not in columns:
                logger.info(f"Migration: renaming column {table}.{old_column} -> {new_column}")
                conn.execute(text(sql))
                conn.commit()
