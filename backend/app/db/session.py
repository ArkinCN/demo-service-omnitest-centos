"""
Database session management
"""
from typing import Generator
from sqlmodel import Session, create_engine
from app.core.config import settings
from app.core.logger import logger


# Create database engine
engine = create_engine(
    settings.DATABASE_URL,
    echo=False,  # Disable SQL logging to reduce noise
    pool_pre_ping=True,  # Test connections before using
    pool_recycle=3600,  # Recycle connections after 1 hour
    # 连接池上限 = pool_size + max_overflow = 100 + 300 = 400 条并发连接。
    # 8核16GB 服务器 + MySQL max_connections=500：400 条约占 ~1GB MySQL 内存，余量充裕。
    # 注意：池是「每 worker 一套」，本服务必须保持单 uvicorn worker（不要加 --workers），
    # 否则 N×400 会撑爆 MySQL 的 500 上限。修复后单连接为毫秒级借还，400 主要用于吸收突发峰值。
    pool_size=100,  # Base pool size（常驻连接，用完归还不关闭）
    max_overflow=300,  # Additional connections when pool is exhausted（用完即关）
    pool_timeout=30,  # Wait up to 30s for a connection（池满 400 仍拿不到=真过载，早失败优于干等）
    # NOTE: init_command 是 PyMySQL 专属参数，SQLite/其他驱动不支持。
    # 本地 SQLite 部署时自动跳过，仅 MySQL 连接串才注入。
    **(
        {"connect_args": {"init_command": "SET time_zone='+00:00'"}}
        if settings.DATABASE_URL.startswith("mysql")
        else {"connect_args": {"check_same_thread": False}}
        if settings.DATABASE_URL.startswith("sqlite")
        else {}
    ),
)


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
    with Session(engine) as session:
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
        SQLModel.metadata.create_all(engine)
        logger.info("Database tables created successfully")

        # Auto-migrate: add missing columns to existing tables
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


def _run_migrations(eng) -> None:
    """Run incremental ALTER TABLE migrations for existing tables"""
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
