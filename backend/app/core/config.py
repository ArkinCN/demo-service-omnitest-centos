"""
Application configuration using Pydantic Settings
"""
from typing import List, Literal
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import json


class Settings(BaseSettings):
    """Application settings with validation"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Application
    APP_NAME: str = "MotorDebug FastAPI"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Literal["development", "testing", "production"] = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # Security
    SECRET_KEY: str = Field(..., min_length=32)
    JWT_SECRET_KEY: str = Field(..., min_length=32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    # vibe-coding 专用 token 有效期(小时)。CLI 会在会话回合间对接近过期的
    # token 静默续签(读 auth.json → 刷新 access → 重新 issue),因此可压到
    # 个位数小时以缩短泄露后的离线重放窗口,而不影响长会话。
    VIBE_CODING_TOKEN_EXPIRE_HOURS: int = 3

    # Database
    DATABASE_URL: str = Field(..., description="Database connection URL")

    # LDAP
    LDAP_URL: str
    LDAP_ADMIN_DN: str
    LDAP_ADMIN_PASSWORD: str
    LDAP_SEARCH_BASE: str

    # CORS
    CORS_ORIGINS: List[str] = ["*"]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: List[str] = ["*"]
    CORS_ALLOW_HEADERS: List[str] = ["*"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | List[str]) -> List[str]:
        """Parse CORS origins from string or list"""
        if isinstance(v, str):
            if v.startswith("["):
                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                    return [origin.strip() for origin in v.split(",")]
            return [v]
        return v

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"

    # Pagination
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    # Email (SMTP)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_SSL: bool = True
    SMTP_FROM_NAME: str = "MotorDebug"
    SMTP_FROM_EMAIL: str = ""

    # Invitation Code
    REQUIRE_INVITATION_CODE: bool = True

    # 无密码模式（本地/离线单机部署）：为 True 时跳过一切鉴权，所有请求都以
    # 本地管理员账号（AUTH_DISABLED_USERNAME）身份执行，登录接口对任意密码
    # 都签发该账号的有效 token。仅供单机内网演示，禁止在联网服务端开启。
    AUTH_DISABLED: bool = False
    AUTH_DISABLED_USERNAME: str = "admin"
    AUTH_DISABLED_EMAIL: str = "admin@example.internal"

    # File Upload
    UPLOAD_FOLDER: str = "uploads/avatars"
    MAX_AVATAR_SIZE: int = 5 * 1024 * 1024  # 5MB
    SERVER_BASE_URL: str = ""  # e.g. "http://127.0.0.1:5001", used to build full avatar URLs

    # ── 监听端口（外置，禁止在启动命令或脚本里写死）──
    # 后端固定监听本机回环，前端 dev server 由 vite 自行管理（见 web/.env）。
    # 之所以收进配置：交付后换机器/换端口时只改 .env，不用改命令与文档。
    BACKEND_HOST: str = "127.0.0.1"
    BACKEND_PORT: int = Field(default=8011, ge=1, le=65535)
    WEB_PORT: int = Field(default=5173, ge=1, le=65535)

    # ── 运行时数据根（外置，留空则按 app/core/paths.py 的仓库相对推导）──
    # 三项都支持绝对路径或「相对项目根」的写法；留空即用仓库内默认位置。
    # 收进配置是为了让知识库/场景包能挪到别的盘而不必改代码。
    SCENES_DIR: str = ""
    KB_DATA_DIR: str = ""
    DATA_DIR: str = ""
    # 内测通过邮件中对外暴露的下载域名（经官网 nginx 反代到本机后端，避免直接暴露 aiproxy）
    DOWNLOAD_PUBLIC_BASE_URL: str = "https://ai.example.internal"

    # AI Proxy Configuration
    AI_PROXY_BASE_URL: str = "https://c-z0-api-01.hash070.com/v1/chat/completions"
    AI_PROXY_API_KEY: str = ""
    AI_PROXY_TIMEOUT: float = 300.0  # 5 minutes

    # Anthropic (Claude) Proxy Configuration
    ANTHROPIC_BASE_URL: str = "https://dashscope.aliyuncs.com/apps/anthropic"
    ANTHROPIC_API_KEY: str = ""

    # 统一网关：是否默认给 anthropic 请求注入 cache_control（上下文缓存）
    GATEWAY_CACHE_INJECT: bool = True

    # Volcano Engine 联网搜索（用于 mdebug-code 的 WebSearch 工具）
    VOLC_WEB_SEARCH_API_KEY: str = ""
    VOLC_WEB_SEARCH_BASE_URL: str = "https://open.feedcoopapi.com/search_api/web_search"
    VOLC_WEB_SEARCH_TYPE: str = "web"
    VOLC_WEB_SEARCH_TIMEOUT: float = 30.0

    # AI 对话 Agent Loop 检索工具后端（阶段②）
    # KnowledgeSearch 有两种后端，用 KB_BACKEND 切换：
    #   "local"  —— 走本进程内的 BM25 检索（app/services/kb_search.py），
    #                语料是前端 public/kb/ 下的流水线产物。**单机/离线部署用这个**，
    #                因为内网服务在客户网络之外不可达。
    #   "remote" —— 走内网精简检索服务（与 mdebug-code CLI 同源）。
    # 默认 local：本项目的交付形态是单机 Windows 版，默认值必须能直接跑通，
    # 不能依赖一个使用者未必能访问到的内网地址。
    KB_BACKEND: str = "local"
    # 内网精简检索服务（仅 KB_BACKEND=remote 时使用）。
    # 检索服务已由 nginx 收 TLS：必须 https + 域名（SNI 匹配证书），
    # 裸 IP 或明文 http 都会被 nginx 拒掉（400/断连）。
    KB_SEARCH_BASE_URL: str = "https://kb.example.internal:14580"
    KB_SEARCH_API_KEY: str = ""
    KB_SEARCH_TIMEOUT: float = 30.0

    # ── 向量检索一路（阶段 3 补全，附录指定 LanceDB）──
    # 附录 A.3 的「索引」阶段要求**关键词与向量两路**。关键词一路是本进程内的
    # BM25（kb_search.py）；向量一路走 LanceDB，且必须**子进程**调 kb-pipeline
    # 的 venv 跑——lancedb 依赖 pyarrow 且要求 pydantic>=2.7.4，而本后端锁的是
    # pydantic 2.5.0（客户原依赖逐字锁定）。装进后端会静默顶掉它（3-K 有同类事故）。
    #   "hybrid" —— 两路都跑，归一化后加权融合（默认）
    #   "keyword"—— 只跑关键词一路（诊断/排障时用）
    # 向量索引不可用时**自动降级为单路并在结果里标注**，不报错、不静默假装双路。
    KB_VECTOR_MODE: str = "hybrid"
    # 向量索引落盘目录。留空用仓库内 backend/uploads/kb_vector（与原件目录同级，
    # 同属运行期数据、不进交付包）。部署方可指向别的盘。
    KB_VECTOR_DIR: str = ""
    # embedding 模型名。**留空表示不尝试 transformer、直接用本地 hashing 回退**
    # （离线现场默认姿态：本项目实测本机 HuggingFace 不可达）。
    # 若现场能预置模型，把它设成模型名或本地目录即可切到语义向量；
    # ⚠️ 换档后向量空间不同，必须**重建索引**（服务会检测档位不一致并拒绝查询）。
    MOTORDEBUG_EMBED_MODEL: str = ""
    # 融合权重：关键词一路占 w，向量一路占 (1-w)。默认偏向关键词——
    # 本项目语料以「宏名 / 参数名 / 术语」为主，BM25 的字面精确匹配更可靠；
    # 向量一路用作提升召回（同义、近义表述）。
    KB_HYBRID_KEYWORD_WEIGHT: float = 0.6
    # DocLibrarySearch：文档平台资料库（FastGPT 问答工作流，返回带下载链接的资料）
    # 走 /v1/chat/completions：FastGPT 工作流内部用「资料检索专家提示词」把命中资料
    # 整理成带 docs.example.internal 下载/预览链接的 Markdown，直接取 content 即可。
    DOC_LIBRARY_BASE_URL: str = "https://iknow.example.internal:11043/api"
    DOC_LIBRARY_API_KEY: str = ""
    DOC_LIBRARY_TIMEOUT: float = 120.0
    # ── 单机版自带大模型渠道 ──
    # AUTH_DISABLED 开启且 MOTORDEBUG_LLM_API_KEY 非空时，启动 seed 会幂等地建出
    # 一个 OpenAI 兼容渠道，并把首页对话、各 Agent 判定、编码助手主渠道都指过去。
    # 留空即完全不介入，走管理面板手工配置的老路径。
    #
    # 【2026-09-23 改】默认上游由 DeepSeek 官方改为 OpenRouter 中转，模型取
    # deepseek/deepseek-v4.1-flash。三点理由：
    #   一、它支持 tools / tool_choice（本工程 agent loop 的硬依赖）与 1M 上下文；
    #   二、输入 $0.079/M、输出 $0.60/M，比官方直连的 v3.2 档更省；
    #   三、协议仍是 OpenAI 兼容，网关的 openai_chat 分支无须改动。
    # 注意：走第三方中转意味着请求会经 OpenRouter 再转发给其挂载的服务商，
    # 场景包内容（含客户信息）会多经一层，交付前需客户书面认可。
    #
    # ⚠️ base_url **不要带 /v1**：网关的 PROTOCOL_PATHS 已自带
    #    /v1/chat/completions（见 gateway_service.py:28），这里再带 /v1 会拼成
    #    /api/v1/v1/chat/completions → OpenRouter 返回 404。
    #    2026-09-23 就踩过这一下，OpenRouter 的「API base URL」页面给的是带 /v1 的
    #    形式，但本工程需要的是去掉 /v1 的前缀。
    MOTORDEBUG_LLM_API_KEY: str = ""
    MOTORDEBUG_LLM_BASE_URL: str = "https://openrouter.ai/api"
    MOTORDEBUG_LLM_MODEL: str = "deepseek/deepseek-v4.1-flash"
    # 起标题、内容安全分类这类高频轻任务用的便宜档；留空则复用 MOTORDEBUG_LLM_MODEL。
    # 注意：这里必须是**上游真实模型名**，不是网关展示名。OpenRouter 上不存在
    # `deepseek-flash`，留空即自动复用 MOTORDEBUG_LLM_MODEL，避免折出 404。
    MOTORDEBUG_LLM_FAST_MODEL: str = ""

    # Agent loop 的默认模型与轮次上限
    # 必须是网关 model_pricing 里存在的 model_id（前端每次都会显式上送，此处仅兜底）。
    # 留空即由 MOTORDEBUG_LLM_MODEL 派生（见下方 agent_default_model 属性），
    # 这样 .env 换模型时本兜底值自动跟随，不会指向一个已停用的旧 model_id 而 400。
    AGENT_CHAT_DEFAULT_MODEL: str = ""
    # 单轮 agent loop 最大迭代数。降到 8：正常一问 1~3 次检索就够，
    # 20 会让模型在「同名同参重复检索」无拦截时最多空转 19 次（用户实测反馈）。
    AGENT_CHAT_MAX_ITERATIONS: int = 8
    # 助手跨轮会话记忆：保留的最近轮数（每轮 = 一问一答，超限丢最早一轮）。
    # 0 = 关闭记忆（行为退回纯单轮）。
    AGENT_CHAT_MEMORY_MAX_TURNS: int = 8
    # 轮内「同名同参重复检索」连续无进展达到该阈值即提前禁工具、强制收口。
    AGENT_CHAT_NO_PROGRESS_LIMIT: int = 2
    # 写类工具（前端执行）等待人工确认的超时秒数（2026-10-10）。
    # 超时后 loop 如实回填「未确认、未执行」并继续，避免请求悬挂到连接断开。
    AGENT_CONFIRM_TIMEOUT_SECONDS: int = 300
    # AI 对话流恢复（有状态）：完成流缓存保留秒数（够「关应用→重开→进对话」）；
    # streaming 流硬上限（防僵尸）。⚠️ 依赖单 worker 内存单例。
    AGENT_STREAM_RECOVERY_TTL_SECONDS: int = 600
    AGENT_STREAM_MAX_AGE_SECONDS: int = 1800

    # MiMo ASR 语音转写（用于 mdebug-code 的语音输入）。
    # MIMO_ASR_API_KEY 在后端 env 配置，CLI 端不持有。
    MIMO_ASR_API_KEY: str = ""
    MIMO_ASR_BASE_URL: str = "https://api.xiaomimimo.com/v1"
    MIMO_ASR_MODEL: str = "mimo-v2.5-asr"
    MIMO_ASR_TIMEOUT: float = 30.0

    # AI 绘图上游（从 FastGPT 插件迁移而来，直连 timebackward.com，key 仅服务端持有）
    # 模式一 Gemini：鉴权用 URL ?key=，normal/fast 两个不同 key。
    GEMINI_IMAGE_BASE_URL: str = "https://api.timebackward.com/v1beta"
    GEMINI_IMAGE_MODEL: str = "gemini-3.1-flash-image-preview"
    GEMINI_IMAGE_KEY_NORMAL: str = ""
    GEMINI_IMAGE_KEY_FAST: str = ""
    GEMINI_IMAGE_TIMEOUT: float = 180.0
    # 模式二 GPT Image 2：鉴权 Bearer，normal/fast 同一 key。
    GPT_IMAGE_BASE_URL: str = "https://api.timebackward.com/v1"
    GPT_IMAGE_MODEL: str = "gpt-image-2"
    GPT_IMAGE_KEY: str = ""
    GPT_IMAGE_TIMEOUT: float = 600.0

    # 内容安全过滤（GB/T 45654-2025 附录 A，输入侧问题过滤与拒答）
    # 层 1 关键词 AC 自动机 + 层 2 大模型 zero-shot 分类，见 content_safety_service.py
    CONTENT_SAFETY_ENABLED: bool = True
    CONTENT_SAFETY_KEYWORDS_PATH: str = "app/data/safety_keywords.json"
    CONTENT_SAFETY_REFUSAL_TEXT: str = "我暂时无法生成你要求的内容。请尝试输入其他要求，我会尽力为你提供帮助。"
    CONTENT_SAFETY_LLM_ENABLED: bool = True
    # 分类模型（网关 model_pricing 中的展示名）；空 = 复用 AGENT_CHAT_DEFAULT_MODEL。
    # 分类只需输出一行 JSON，用轻量模型即可（v4-flash 实测判定与 pro 一致且快 ~30%）
    CONTENT_SAFETY_LLM_MODEL: str = "deepseek-v4-flash"
    CONTENT_SAFETY_LLM_TIMEOUT: float = 12.0
    CONTENT_SAFETY_LLM_CONFIDENCE: float = 0.7
    CONTENT_SAFETY_LLM_MAX_CHARS: int = 3000
    # 分类模型故障时：False=放行（层 1 仍有效，避免上游抖动导致全站不可用）True=拒答
    CONTENT_SAFETY_LLM_FAIL_CLOSED: bool = False
    # 编程 CLI 链路（vibe-coding / openai 代理）是否启用层 2（延迟敏感，默认仅层 1）
    CONTENT_SAFETY_LLM_CODING_ENABLED: bool = False

    # 内置 Skill 云端下发（占位符展开，见 services/skill_expansion.py）
    # canary 用于按 (user, skill, version) 派生溯源水印——生产环境必须在 env 覆盖。
    SKILL_CANARY_SECRET: str = "motordebug-skill-canary-v1-change-me"
    SKILL_UPLOAD_MAX_FILE_BYTES: int = 512 * 1024      # 单文件上限（SKILL.md/资源）
    SKILL_UPLOAD_MAX_TOTAL_BYTES: int = 4 * 1024 * 1024  # zip 包内容总量上限

    # SkillClaw Ingest（非阻塞旁路：把 vibe-coding 对话投递给本地 SkillClaw → 进化成 skill）
    SKILLCLAW_INGEST_ENABLED: bool = False
    SKILLCLAW_INGEST_URL: str = "http://127.0.0.1:30000/v1/ingest/messages"
    SKILLCLAW_INGEST_TOKEN: str = ""   # 对应 SkillClaw proxy.api_key（默认空 = SkillClaw 不校验）
    SKILLCLAW_INGEST_TIMEOUT: float = 5.0

    # FastGPT Proxy Configuration（已移除：AI 对话/绘图/硬件评审均不再走 FastGPT，
    # 仅 DocLibrarySearch 用独立的 DOC_LIBRARY_* 配置）

    # GitLab MCU 头文件仓库配置
    GITLAB_BASE_URL: str = "http://gitlab.example.internal"
    GITLAB_MCULIB_GROUP_ID: str = "7390"
    GITLAB_MCULIB_TOKEN: str = ""

    # 前端部署 Webhook 配置
    DEPLOY_SECRET_TOKEN: str = ""   # Webhook 验证密钥
    DEPLOY_SCRIPT_PATH: str = ""    # 部署脚本路径
    DEPLOY_REPO_PATH: str = ""      # 前端仓库在服务器上的路径
    DEPLOY_SITE_DIR: str = ""       # 站点发布目录（Nginx root 指向的 current 符号链接所在目录）

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def main_model_id(self) -> str:
        """主模型的网关 model_id，由 MOTORDEBUG_LLM_MODEL 派生（'厂商/名' → '名'）。

        与 local_admin_service._derive_main_model_id() 同口径。放在这里是为了让
        非 seed 场景（agent loop / 内容安全分类的兜底模型）也能拿到同一个值，
        避免 .env 换模型后这些兜底点仍指向已停用的旧 model_id 而 400。
        """
        upstream = (self.MOTORDEBUG_LLM_MODEL or "").strip()
        if not upstream:
            return "deepseek-v4.1-flash"
        return upstream.rsplit("/", 1)[-1] or "deepseek-v4.1-flash"

    @property
    def agent_default_model(self) -> str:
        """agent loop / 分类器实际使用的兜底 model_id。

        AGENT_CHAT_DEFAULT_MODEL 显式配置了就用它，留空则回退到 main_model_id。
        """
        return (self.AGENT_CHAT_DEFAULT_MODEL or "").strip() or self.main_model_id


# Global settings instance
settings = Settings()
