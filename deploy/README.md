# OmniTest 部署文件说明

本项目已按公司统一部署体系（`/opt/demo/_infra/`）补齐部署配置，**单机 Docker Compose** 部署。

> ✅ **已上线**：`http://192.168.31.178:5100`（2026-10-05 部署成功，两容器 healthy，check.sh 退出码 0）。
> 部署过程踩过的坑与最终配置见文末「九、部署实录」。

## 一、文件清单

| 文件 | 作用 |
|------|------|
| `docker-compose.yml` | 单机编排：`backend`（FastAPI+gunicorn）+ `web`（nginx，对外 5100） |
| `Dockerfile.web` | 前端镜像：构建 Vite 产物 → nginx 托管（node:22） |
| `deploy/nginx.conf` | nginx 站点配置：静态托管 + `/api`、`/uploads` 反代后端 |
| `backend/Dockerfile` | 后端镜像：Python 3.11-slim-bookworm + gunicorn（含补装依赖） |
| `backend/gunicorn.conf.py` | gunicorn 配置（**单 worker + UvicornWorker**，见下） |
| `backend/.dockerignore` | 后端构建上下文排除 |
| `.dockerignore` | 根构建上下文排除（前端构建用） |
| `deploy/omnitest.conf` | 服务器端部署配置（复制到 `/opt/demo/_infra/deploy-configs/`） |
| `deploy/server-deploy.sh` | 服务器端辅助脚本（init / check / logs，非正式入口） |

## 二、架构

```
浏览器 ──:5100──▶ [web 容器: nginx]
                     ├── /            → web/dist 静态前端
                     ├── /api/        → backend:5100（Proxy，SSE 不缓冲）
                     └── /uploads/    → backend:5100（上传资源）
                                  │
                          [backend 容器]
                          gunicorn + UvicornWorker · 单 worker · 容器内 5100
                                  │
                          卷挂载：backend/uploads、backend/.deploy、/var/log/demo、
                                  web/(只读)、data/(只读)
```

- 仅 `web` 对外暴露 **5100**；`backend` 只在 compose 内网可达。
- 前端所有请求都是相对路径（`/api`、`/scenes`），同源，无需构建期注入后端地址。

> ⚠️ **后端容器目录层级（关键）**：`backend/app/core/paths.py` 用
> `CORE_DIR.parents[3]` 推导 `C_DIR`，因此容器内必须是
> **`<repo>/c/backend/app/core/paths.py`**（四层 parent）。本镜像取
> `repo=/srv/omnitest`，即后端起于 `/srv/omnitest/c/backend`，并把宿主机的
> `web/`、`data/` 只读挂到 `/srv/omnitest/c/web`、`/srv/omnitest/c/data`。
> **不要**把 backend 平铺到 `/app`，否则会 `IndexError: 3` 崩溃循环。

## 三、端口与资源

| 项 | 值 |
|----|----|
| 对外端口 | **5100**（占用则顺延 5101/5102，需同步改 compose 与 omnitest.conf） |
| CPU | `cpus: "1.0"` |
| 内存 | `mem_limit: 1g` |
| 容器名 | 对外 `omnitest`，后端 `omnitest-backend` |

> ⚠️ **单 worker 约束**：`backend/app/db/session.py` 的连接池按单 worker 设计
> （`pool_size=100 + max_overflow=300`）。`gunicorn.conf.py` 固定 `workers = 1`，
> 请勿调大，否则会 N 倍放大连接数撑爆 MySQL。

## 四、环境变量（密钥）

后端读取 `backend/.env`（compose 通过 `env_file: ./.env` 注入）。

首次部署时由 `init-project.sh` 从 `backend/.env.example` 复制生成 `.env`，
**需人工填写**以下必填项（其余可留示例值）：

- `SECRET_KEY` / `JWT_SECRET_KEY`：随机串，≥32 字符
  （`python -c "import secrets; print(secrets.token_urlsafe(48))"`）
- `DATABASE_URL`：默认 `sqlite:///.deploy/motordebug.db`；生产建议 MySQL
- `MOTORDEBUG_LLM_API_KEY`：OpenRouter key（走 `MOTORDEBUG_LLM_BASE_URL`）
- `ENVIRONMENT=production`（生产建议，会关闭 `/docs`）

填完 `chmod 600 backend/.env`。

## 五、部署流程（正式）

```powershell
# 1) 首次：把部署配置放到服务器
scp deploy/omnitest.conf fjs@192.168.31.178:/tmp/
ssh fjs@192.168.31.178 "sudo cp /tmp/omnitest.conf /opt/demo/_infra/deploy-configs/"

# 2) 首次初始化（建目录、生成 .env、systemd、services.list）
.\deploy.ps1 omnitest init

# 3) 人工填 .env 密钥
ssh fjs@192.168.31.178
cd /opt/demo/omnitest && cp backend/.env.example backend/.env && nano backend/.env && chmod 600 backend/.env

# 4) 正式部署
.\deploy.ps1 omnitest all
```

> `D:\deploy.ps1` 已新增 `omnitest` 配置项（Base=`D:\Task4`、Sources=`OmniTest`）。
> 打包时会同步生成 `OmniTest-deploy.tar.gz`，解压后目录名为 `OmniTest`
> （见下节「已知差异」）。

## 六、验证

```bash
docker ps | grep omnitest          # 容器 Up
ss -tlnp | grep :5100              # 端口监听
curl -I http://127.0.0.1:5100      # HTTP 200
/opt/demo/_infra/check.sh; echo $? # 退出码 0
```

## 七、已知差异 / 注意项

1. **包名与解压目录**
   本地目录为 `D:\Task4\OmniTest`，`deploy.ps1` 打出的包顶层目录是 `OmniTest`，
   而目标是 `/opt/demo/omnitest`。本次部署用 `tar --strip-components=1` 手工剥离
   顶层目录完成落位。**后续增量部署需固化这一点**（见第九节），否则解压会在
   `/opt/demo/omnitest/OmniTest/` 下多套一层。

2. **前端 `web/.env`**
   `web/.env` 不在版本控制内（含联调 token）。生产构建**不依赖**它：
   前端请求全部是相对路径，且 `VITE_AGENT_BACKEND=dsh` 等开关仅影响本地联调。
   若生产需要特定前端变量，请在 `Dockerfile.web` 的构建阶段注入。

3. **npm 镜像源**
   后端 pip 已固定阿里云镜像；前端 `npm ci` 走默认源（实测可达，构建成功），
   如后续变慢可在 `Dockerfile.web` 追加 `--registry=https://registry.npmmirror.com`。

4. **`check.sh` 的 OpenRouter 检查**
   该脚本会读 `/opt/demo/sz-metro-corrugation/.env` 的 `OPENROUTER_API_KEY` 做可用性探测。
   本次实测该项【正常】。

5. **AUTH_DISABLED 模式**
   当前 `.env` 设了 `AUTH_DISABLED=true`（单机内网演示：任意密码登录为本地管理员）。
   如需真实鉴权，改为 `false` 并重启。

## 九、部署实录（2026-10-05）

| 项 | 值 |
|----|----|
| 访问地址 | `http://192.168.31.178:5100` |
| 容器 | `omnitest`（nginx，healthy）、`omnitest-backend`（healthy） |
| systemd | `omnitest-compose`（active + enabled） |
| 部署目录 | `/opt/demo/omnitest/` |
| 日志 | `/var/log/demo/omnitest.log`、`omnitest.err.log` |
| 自检 | `check.sh` 退出码 **0**（含 OmniTest 三项全绿，未影响其它 4 个服务） |

### 过程中修复的 5 个问题（改的都是部署文件，未改客户业务代码）

| # | 现象 | 根因 | 修复 |
|---|------|------|------|
| 1 | `exec: "gunicorn": not found` | `requirements.txt` 只有 uvicorn，无 gunicorn | Dockerfile 单独 `pip install gunicorn==21.2.0` |
| 2 | `IndexError: 3` 崩溃循环 | `paths.py` 用 `parents[3]`，要求 `<repo>/c/backend/...`；平铺到 `/app` 层级不足 | 镜像内改 `/srv/omnitest/c/backend` + 挂载 `web/`、`data/` |
| 3 | `/health` 全 500，`FastAPI.__call__() missing 'send'` | FastAPI 是 ASGI，gunicorn 默认 WSGI worker | `worker_class = "uvicorn.workers.UvicornWorker"` |
| 4 | `No module named 'openpyxl'` | 源码 import 了 openpyxl / pymupdf，requirements 未列 | Dockerfile 补装 `openpyxl==3.1.5 pymupdf==1.24.14` |
| 5 | npm `EBADENGINE`（react-router 要求 node>=22.22） | 基础镜像 node:20 偏低 | `Dockerfile.web` 改 `node:22-bookworm-slim` |

### 后续增量部署建议

打包时保持顶层目录为 `OmniTest`，但解压需剥离。可在 `deploy.ps1` 的打包命令加：

```powershell
tar -czf $TarFile --transform 's,^OmniTest,omnitest,' ...
```

或把本地目录重命名为 `omnitest` 并同步 `omnitest.conf` 的 `WINDOWS_PACK_SOURCES`。
