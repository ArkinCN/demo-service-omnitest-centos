#!/usr/bin/env bash
# =============================================================================
# OmniTest 台架机部署（compose 编排 + 门户纳管）
#
# 为什么不直接 docker compose up：
#   ① 令牌不能写进仓库/镜像，必须运行时注入；
#   ② SRC / 镜像 tag / 宿主端口要可覆盖；
#   ③ 需要把「docker run 时代」遗留的同名容器先摘掉，否则 compose 无法接管。
#
# 用法：
#   bash deploy/bench-up.sh
#   OMNITEST_IMAGE=omnitest:20261101 HOST_PORT=10003 bash deploy/bench-up.sh
# =============================================================================
set -euo pipefail

SRC="/opt/demo-hub/demo-platform-core/data/sources/omnitest"
COMPOSE_FILE="$SRC/deploy/bench.compose.yml"
TOKEN_FILE="$HOME/.omnitest-agent/token"
NET="demo-platform-core_aicube-net"
NAME="omnitest"

log() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }

# ---- 前置检查（早失败）----
[ -f "$TOKEN_FILE" ] || { echo "❌ 缺少 agent 令牌：$TOKEN_FILE"; exit 1; }
[ -f "$COMPOSE_FILE" ] || { echo "❌ 缺少 compose 文件：$COMPOSE_FILE"; exit 1; }
docker network inspect "$NET" >/dev/null 2>&1 || { echo "❌ 网络不存在：$NET"; exit 1; }
docker image inspect "${OMNITEST_IMAGE:-omnitest:manualtest}" >/dev/null 2>&1 \
  || { echo "❌ 镜像不存在：${OMNITEST_IMAGE:-omnitest:manualtest}"; exit 1; }
mkdir -p "$SRC/hardware/v0.6/runs"

# ---- 注入 compose 需要的变量（令牌只在环境里，不落盘）----
export SRC
export FAN_AGENT_TOKEN="$(cat "$TOKEN_FILE")"
export OMNITEST_IMAGE="${OMNITEST_IMAGE:-omnitest:manualtest}"
export HOST_PORT="${HOST_PORT:-10003}"

# ---- 摘掉「非 compose 创建」的同名容器，否则 compose 无法接管 ----
if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  owner="$(docker inspect "$NAME" --format '{{index .Config.Labels "com.docker.compose.project"}}' 2>/dev/null || true)"
  if [ "$owner" != "omnitest" ]; then
    log "移除旧的非 compose 容器 $NAME（镜像与回滚容器仍在）"
    docker rm -f "$NAME" >/dev/null
  fi
fi

log "compose up -d（$OMNITEST_IMAGE → :$HOST_PORT）"
docker compose -p omnitest -f "$COMPOSE_FILE" up -d --remove-orphans

# ---- 健康检查（镜像自带 HEALTHCHECK 之外，再从宿主确认可达）----
log "等待 /health ..."
ok=0
for i in $(seq 1 20); do
  if curl -fsS -o /dev/null --max-time 5 "http://127.0.0.1:${HOST_PORT}/health"; then
    log "健康检查通过（约 $((i * 3))s）"; ok=1; break
  fi
  sleep 3
done
if [ "$ok" != 1 ]; then
  log "❌ 健康检查未通过，日志："
  docker compose -p omnitest -f "$COMPOSE_FILE" logs --tail 40 || true
  exit 1
fi

docker ps --filter "name=^${NAME}$" --format '  {{.Names}}  {{.Status}}  {{.Ports}}'
log "完成。门户纳管：项目矩阵 → 导入已有容器 → 勾选 $NAME；入口 http://192.168.31.56:${HOST_PORT}"
