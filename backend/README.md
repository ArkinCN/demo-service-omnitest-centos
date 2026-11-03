# MotorDebug 业务后端

以客户脱敏工程的 `../../api`（FastAPI + SQLModel）为底座，扩展测试业务、对接多场景 Agent 测试前端。

- **原型**：一个业务服务 + 一个任务工作进程 + 关系数据库 + 文件目录，设备桥独立部署。
- **数据库**：保留原库类型，**不要一开工就换 PostgreSQL**。本地验证用 SQLite，生产用 MySQL。
- **复用原则**：账号、登录、模型网关、额度、报告库、设备工具从客户仓整块复用，**不从零重写**；`auth` / `chats` / `agent_chat` / `credits` 四个模块名**保持原样**，本次只新增 `tasks`。

---

## 一、环境准备（Windows PowerShell）

```powershell
cd d:\Task4\平台代码-脱敏版\backend

# 1. 建虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. 装依赖
pip install -r requirements.txt

# 3. 配环境变量
Copy-Item .env.example .env
# 编辑 .env：
#   - SECRET_KEY / JWT_SECRET_KEY 换成随机值（>=32 字符）
#   - MOTORDEBUG_LLM_API_KEY 填受控 key（勿提交）
#   - 本地验证可保持 DATABASE_URL=sqlite:///.deploy/motordebug.db
```

生成随机密钥：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

---

## 二、启动

```powershell
# 开发态（热重载）
uvicorn app.main:app --reload --host 127.0.0.1 --port 8011

# 生产态（⚠️ 必须单 worker，见下方说明）
uvicorn app.main:app --host 127.0.0.1 --port 8011
```

- API 基址：`http://127.0.0.1:8011/api/v1`
- 健康检查：`http://127.0.0.1:8011/health`
- Swagger UI：`http://127.0.0.1:8011/docs`（`ENVIRONMENT=production` 时自动关闭）

> ⚠️ **不要加 `--workers`**。`db/session.py` 的连接池是「每 worker 一套」（`pool_size=100 + max_overflow=300 = 400`），
> 多 worker 会 N 倍放大，撑爆 MySQL 的 `max_connections`。原注释已明确此约束。

---

## 三、建表与迁移

首次启动会自动建表，无需手工执行。手动触发：

```powershell
python -c "from app.db.session import init_db; init_db()"
```

`init_db()` 做四件事：

1. `SQLModel.metadata.create_all()` 建缺失的表；
2. `_run_migrations()` 跑 40 余条增量 `ALTER TABLE`（幂等，已存在的列会跳过）；
3. 六类 seed：vibe-coding 默认渠道、功能路由、协议、套餐与模型定价、本地管理员；
4. 老库回填（i18n key、缓存 token 列）。

**迁移记录**：见仓库根目录 `../../操作.md` 的「阶段 1」小节。本服务**不使用 Alembic 迁移文件**，迁移以 `session.py` 内的幂等 ALTER 清单为准。

---

## 四、自检与测试

```powershell
# 健康检查
curl.exe http://127.0.0.1:8011/health

# 登录（AUTH_DISABLED=true 时任意密码均签发本地管理员 token）
curl.exe -X POST http://127.0.0.1:8011/api/v1/auth/login `
  -H "Content-Type: application/json" `
  -d '{\"username\":\"admin\",\"password\":\"any\"}'

# 单元测试
pytest

# 代码风格（可跳过）
black --check app
flake8 app
```

---

## 五、目录说明

```
backend/
  app/main.py          服务入口（健康检查、CORS、异常处理、路由注册）
  app/api/v1/          v1 路由（复用 28 个模块，阶段 2 新增 tasks）
  app/api/deps.py      鉴权依赖（登录态、管理员、可选登录、API key）
  app/core/            配置、安全、日志、异常、调度、计费定价
  app/models/          SQLModel 表定义（23 个）
  app/schemas/         Pydantic 请求响应模型（15 个）
  app/services/        业务服务（37 个：认证、额度、内容安全、技能、网关…）
  app/db/session.py    数据库引擎、会话、建表与增量迁移
  app/adapters/        新增：设备桥、报告库等适配（阶段 3 起填充）
  scripts/             建表与一次性迁移脚本
  tests/               测试
  requirements.txt     依赖（原依赖为起点，全版本锁定）
  .env.example         环境变量示例（只留变量名与安全示例）
  .gitignore           排除 .env / .deploy / uploads / __pycache__
```

---

## 六、两条禁止

1. **不要把 `.env` 提交进版本控制**，也不要把真实凭据写进 `.env.example`。
2. **不要违反单 worker 约束**（见第二节说明）。
