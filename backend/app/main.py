"""
FastAPI application entry point
"""
import time
import re
import logging
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.core import paths
from app.core.config import settings

'''
pydantic v2 把 model_ 前缀当作受保护命名空间，凡是字段名以它开头的模型都会警告
「Field "model_id" has conflict with protected namespace "model_"」。客户原有的
ModelPricing.model_id 正撞在这上面——它是全工程 30 余处引用的既有字段名，为一条
警告去改它得不偿失。这里统一关掉该检查：model_id 这类字段名在我们这是普通业务字段，
不与 pydantic 的 model_* 方法冲突（v2 只在赋值/验证时保护，我们两处都不碰）。
'''
BaseModel.model_config["protected_namespaces"] = ()

# Filter to redact tokens from uvicorn access logs
class TokenRedactFilter(logging.Filter):
    """Redact JWT tokens from log messages"""
    TOKEN_PATTERN = re.compile(r'token=[^&\s\]"]+')

    def filter(self, record: logging.LogRecord) -> bool:
        if record.getMessage():
            record.msg = self.TOKEN_PATTERN.sub('token=***', str(record.msg))
        return True


# Apply filter to uvicorn access logger
logging.getLogger("uvicorn.access").addFilter(TokenRedactFilter())
from app.core.logger import logger
from app.core.exceptions import (
    AppException,
    EmailNotVerifiedException,
    app_exception_handler,
    email_not_verified_handler,
    http_exception_handler,
    validation_exception_handler,
    general_exception_handler
)
from app.db.session import init_db
from app.api.v1 import auth, users, chats, updates, feedbacks, feedback_modules, code_reviews, user_groups, external_links, favorites, presence, dashboard, mculib, registration, invitations, invitation_applications, vibe_coding, gpt_proxy, feature_access, webhooks, agreements, gateway, gateway_admin, agent_chat, agent_image, credits, skills, tasks, agent_stream, kb, kb_entries, kb_documents, runs, interlocks, reports, evaluate, fan_tests, automation_judge
from app.core.scheduler import init_scheduler, shutdown_scheduler
from app.middleware.activity import update_user_activity


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan events

    Startup: Initialize database
    Shutdown: Cleanup resources
    """
    # Startup
    logger.info("Starting application...")
    try:
        init_db()
        logger.info("Database initialized successfully")

        # Ensure upload directories exist
        upload_dir = Path(settings.UPLOAD_FOLDER)
        upload_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Upload directory ensured: {upload_dir}")

        # Ensure link images upload directory exists
        link_images_dir = Path("uploads/link_images")
        link_images_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Link images directory ensured: {link_images_dir}")

        # Initialize background scheduler
        init_scheduler()
        logger.info("Background scheduler initialized")

        # Create shared AI proxy HTTP client (connection pooling)
        app.state.ai_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.AI_PROXY_TIMEOUT, connect=30.0),
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=100,
            ),
        )
        logger.info("Shared AI HTTP client initialized")

        # AI 对话有状态流管理（支持断线/关应用后恢复）。⚠️ 依赖单 worker 内存单例。
        from app.services.agent_stream_manager import AgentStreamManager
        app.state.agent_stream_manager = AgentStreamManager()
        app.state.agent_stream_ttl_task = asyncio.create_task(
            app.state.agent_stream_manager.run_ttl_loop()
        )
        logger.info("Agent stream manager initialized")

        # 内容安全过滤（GB/T 45654）：启动时构建关键词自动机，避免首请求延迟
        from app.services.content_safety_service import content_safety
        content_safety.warm_up()
        logger.info("Content safety keyword automaton initialized")
    except Exception as e:
        logger.error(f"Failed to initialize application: {str(e)}")
        raise

    yield

    # Shutdown
    logger.info("Shutting down application...")
    try:
        app.state.agent_stream_ttl_task.cancel()
        app.state.agent_stream_manager.shutdown()
    except Exception as e:  # noqa: BLE001
        # 关闭阶段的清理失败不该让进程起不来，所以不 raise；
        # 但原先 except: pass 会让「管理器没关干净」这件事彻底无痕，
        # 留一条日志，便于事后核对有没有残留会话。
        logger.warning(f"关闭时清理 agent stream manager 失败（已忽略）：{e}")
    await app.state.ai_http_client.aclose()
    logger.info("Shared AI HTTP client closed")
    shutdown_scheduler()


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Enterprise User Authentication System with LDAP integration",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else f"{settings.API_V1_PREFIX}/openapi.json",
    lifespan=lifespan
)


# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 临时允许所有来源，用于调试
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests and responses"""
    start_time = time.time()

    # Skip detailed logging for WebSocket upgrade requests
    is_websocket = request.headers.get("upgrade", "").lower() == "websocket"

    # Log request
    logger.info(
        f"Request: {request.method} {request.url.path} "
        f"- Client: {request.client.host if request.client else 'unknown'}"
        + (" (WebSocket)" if is_websocket else "")
    )

    # Process request
    response = await call_next(request)

    # Skip response modification for WebSocket connections
    if is_websocket:
        return response

    # Update user activity on successful requests (throttled, 60s per user)
    if response.status_code < 400:
        auth_header = request.headers.get("Authorization")
        update_user_activity(auth_header)

    # Calculate processing time
    process_time = time.time() - start_time

    # Log response
    logger.info(
        f"Response: {request.method} {request.url.path} "
        f"- Status: {response.status_code} "
        f"- Duration: {process_time:.3f}s"
    )

    # Add custom header
    response.headers["X-Process-Time"] = str(process_time)

    return response


# Register exception handlers (more specific first)
app.add_exception_handler(EmailNotVerifiedException, email_not_verified_handler)
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)


# Include routers
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)
app.include_router(chats.router, prefix=settings.API_V1_PREFIX)
app.include_router(feedbacks.router, prefix=settings.API_V1_PREFIX)
app.include_router(feedback_modules.router, prefix=settings.API_V1_PREFIX)
app.include_router(code_reviews.router, prefix=settings.API_V1_PREFIX)
app.include_router(updates.router, prefix=f"{settings.API_V1_PREFIX}/updates", tags=["Updates"])
app.include_router(user_groups.router, prefix=settings.API_V1_PREFIX)
app.include_router(user_groups.ldap_router, prefix=settings.API_V1_PREFIX)
app.include_router(external_links.router, prefix=settings.API_V1_PREFIX)
app.include_router(favorites.router, prefix=settings.API_V1_PREFIX)
app.include_router(presence.router, prefix=settings.API_V1_PREFIX)
app.include_router(dashboard.router, prefix=settings.API_V1_PREFIX)
app.include_router(mculib.router, prefix=settings.API_V1_PREFIX)
app.include_router(registration.router, prefix=settings.API_V1_PREFIX)
app.include_router(invitations.router, prefix=settings.API_V1_PREFIX)
app.include_router(invitation_applications.router, prefix=settings.API_V1_PREFIX)
app.include_router(vibe_coding.admin_router, prefix=settings.API_V1_PREFIX)
app.include_router(vibe_coding.proxy_router, prefix=settings.API_V1_PREFIX)
app.include_router(gpt_proxy.proxy_router, prefix=settings.API_V1_PREFIX)
app.include_router(feature_access.admin_router, prefix=settings.API_V1_PREFIX)
app.include_router(feature_access.user_router, prefix=settings.API_V1_PREFIX)
app.include_router(webhooks.router, prefix=settings.API_V1_PREFIX)
app.include_router(agreements.router, prefix=settings.API_V1_PREFIX)
app.include_router(gateway.router, prefix=settings.API_V1_PREFIX)
app.include_router(gateway_admin.admin_router, prefix=settings.API_V1_PREFIX)
app.include_router(skills.user_router, prefix=settings.API_V1_PREFIX)
app.include_router(skills.admin_router, prefix=settings.API_V1_PREFIX)
app.include_router(agent_chat.router, prefix=settings.API_V1_PREFIX)
app.include_router(agent_image.router, prefix=settings.API_V1_PREFIX)
app.include_router(credits.router, prefix=settings.API_V1_PREFIX)
app.include_router(tasks.router, prefix=settings.API_V1_PREFIX)
# 助手会话兼容适配层：前端调 /api/agent/stream（无 /v1 前缀），故挂 /api
app.include_router(agent_stream.router, prefix="/api")
from app.api.v1.config_suggestions import router as config_suggestions_router
app.include_router(config_suggestions_router, prefix="/api")
# 知识库检索：前端建议形态 /api/kb/search（无 /v1 前缀），故挂 /api
app.include_router(kb.router, prefix="/api")
# 知识库三轴分类条目 CRUD：/api/kb/entries/*
app.include_router(kb_entries.router, prefix="/api")
# 知识库文档上传与五阶段转化：/api/kb/documents/*（阶段 3.1）
app.include_router(kb_documents.router, prefix="/api")
# 轮次产物读写：/api/runs/*（阶段 4.1）
app.include_router(runs.router, prefix="/api")
# 安全联锁 + 闸门 + 急停（阶段 4.3）
app.include_router(interlocks.router)
# 报告生成适配层（阶段 4.4）
app.include_router(reports.router)
# 判据求值（阶段 4，判定放后端）
app.include_router(evaluate.router)
# 风扇实验接口：/api/fan-tests/*（阶段 5 接入 v0.6 硬件交接包）
app.include_router(fan_tests.router, prefix="/api")
# 非致命报错判定清单落盘：/api/automation-judge（汇报模式 · 编号 1，纯追加）
app.include_router(automation_judge.router)


# Mount static files for uploads
# Note: This must be done after including routers to avoid route conflicts
uploads_path = Path(settings.UPLOAD_FOLDER).parent  # "uploads" directory
if not uploads_path.exists():
    uploads_path.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_path)), name="uploads")
logger.info(f"Static files mounted: /uploads -> {uploads_path}")


# Health check endpoint
# ⚠️ 必须保持免鉴权且最先注册：门户的健康检查（约 8 秒窗口）与镜像自带的
#    HEALTHCHECK 都打这个地址，任何前置依赖（数据库、模型）都不能挡住它。
@app.get("/health", tags=["Health"], include_in_schema=False)
def health_check():
    return {"status": "healthy"}


# ── 前端静态托管（2026-10-29 单容器改造）────────────────────────────────────
# 背景：门户（AI Cube Hub）只允许一个容器、不读 docker-compose.yml、只注入 TZ，
# 因此去掉 nginx，改由 FastAPI 直接托管 Vite 构建产物：
#   · /assets/*   → 构建产物里的静态资源（文件名带 hash，可长缓存）
#   · 其余 GET     → 先按路径找同名文件，找不到回退 index.html（前端路由 /init、/run …）
#   · /api、/uploads 不参与回退：接口 404 必须如实 404，不能伪装成 200 的 HTML
# 目录沿用 app/core/paths.py 的 c/web/dist 契约；本地开发没有 dist 时自动跳过，
# 保持原有的 {"status":"ok"} 根路由，vite dev server 照常工作。
_SPA_DIST = paths.C_DIR / "web" / "dist"

if (_SPA_DIST / "index.html").is_file():
    _spa_assets = _SPA_DIST / "assets"
    if _spa_assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_spa_assets)), name="spa-assets")

    @app.get("/{spa_path:path}", include_in_schema=False)
    def spa_fallback(spa_path: str):
        """静态文件优先，其次回退 index.html；接口前缀一律 404。"""
        if spa_path.startswith(("api/", "uploads/")):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        if spa_path:
            candidate = (_SPA_DIST / spa_path).resolve()
            # 防目录穿越：只允许 dist 目录内的真实文件
            if candidate.is_file() and _SPA_DIST.resolve() in candidate.parents:
                return FileResponse(candidate)
        return FileResponse(_SPA_DIST / "index.html")

    logger.info(f"SPA static files mounted: {_SPA_DIST}")
else:
    @app.get("/", tags=["Root"], include_in_schema=False)
    def read_root():
        return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=5000,
        reload=settings.is_development,
        log_level=settings.LOG_LEVEL.lower()
    )
