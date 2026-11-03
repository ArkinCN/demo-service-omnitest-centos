# ============================================================
# OmniTest 后端 gunicorn 配置
# 启动：gunicorn -c gunicorn.conf.py app.main:app
# ============================================================

import multiprocessing
import os

# ---- 网络 ----
bind = "0.0.0.0:5100"
backlog = 2048

# ---- 工作进程 ----
# ⚠️ 本项目**必须单 worker**：db/session.py 的连接池是「每 worker 一套」
# （pool_size=100 + max_overflow=300 = 400），多 worker 会 N 倍放大，
# 撑爆 MySQL 的 max_connections。原 README 已明确此约束，勿改。
workers = 1

# worker 类型：**必须**用 UvicornWorker。
# ⚠️ FastAPI 是 ASGI 应用，若用默认的 sync/gthread（WSGI）worker，
#    会报 `FastAPI.__call__() missing 1 required positional argument: 'send'`
#    （已实测踩坑）。UvicornWorker 由 uvicorn[standard] 提供，已在依赖中。
#    它自身带事件循环 + 并发处理能力，故 threads 不再需要（设 1）。
worker_class = "uvicorn.workers.UvicornWorker"
threads = 1

# 长请求（大模型 SSE、知识库转化）需要较长超时
timeout = 300
graceful_timeout = 60
keepalive = 5

# 定期回收 worker，缓解潜在内存增长（1G 内存限制下的保守设置）。
#
# ⚠️ 2026-10-12 由 2000/200 大幅上调（**重要**）：实测原阈值在正常运行中段就触发
#    worker 优雅替换（uvicorn 把它透传为 limit_max_requests；某 worker 服务到第
#    2099 个请求时被换下，master 存活、日志无异常字样）。替换瞬间会：
#      ① 进程内存里的运行状态与**单设备锁**全部丢失 → 前端轮询旧轮次报
#         「运行不存在」，重试请求与仍在跑的真机轮次撞车（示波器
#         VI_ERROR_RSRC_BUSY）——2026-10-12 自动化失败事故的触发源；
#      ② 前端恰好落在替换窗口的轮询可能读到 404（现已由 fan_executor 的
#         磁盘重建 + 跨进程锁兜底，但替换本身仍是抖动源，应尽量少发生）。
#    上调后回收间隔从「约 1 小时」拉到数天级（按本部署实测峰值 ~33 req/min 估算），
#    兼顾内存保守策略与运行连续性。如需调整可用环境变量覆盖；
#    gunicorn 语义：0 = 不按请求数回收。
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS") or 50000)
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER") or 2000)

# ---- 日志 ----
# 统一落到 /var/log/demo/（由 docker-compose 挂载宿主机同名目录）
accesslog = "/var/log/demo/omnitest.log"
errorlog = "/var/log/demo/omnitest.err.log"
loglevel = "info"
access_log_format = '%({x-forwarded-for}i)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)sus'

# ---- 进程 ----
proc_name = "omnitest"
# 预加载：先 import 应用再 fork，缩短首个请求延迟。
# 注：lifespan 的初始化（建表、调度器、内容安全预热）在 worker fork 后各跑一次，
# 单 worker 下无重复副作用，可安全开启。
preload_app = True

# 若设了环境变量 GUNICORN_WORKERS，则以其为准（部署方可临时覆盖，仍建议保持 1）
if os.getenv("GUNICORN_WORKERS"):
    workers = int(os.environ["GUNICORN_WORKERS"])

# 仅供 multiprocessing 参考（保留，便于日后需要时调优）
_default_workers = multiprocessing.cpu_count() * 2 + 1
