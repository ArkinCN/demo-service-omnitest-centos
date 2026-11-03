#!/bin/bash
# ============================================================
# OmniTest 服务器端部署辅助脚本（参考用）
#
# 说明：正式部署仍走统一入口 /opt/demo/_infra/deploy.sh omnitest <动作>。
#       本脚本只是把「本项目特有」的步骤（首次初始化、环境自检、看日志）
#       收在一处，便于人工执行与排障。**不替代**统一脚本。
#
# 用法：
#   bash deploy/server-deploy.sh init      # 首次：建目录 + 生成 .env 模板
#   bash deploy/server-deploy.sh check     # 环境自检（docker/端口/磁盘）
#   bash deploy/server-deploy.sh logs      # 跟踪后端日志
# ============================================================

set -euo pipefail

WORK_DIR="/opt/demo/omnitest"
BACKEND_LOG="/var/log/demo/omnitest.log"
BACKEND_ERR="/var/log/demo/omnitest.err.log"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

do_init() {
    log "初始化目录：$WORK_DIR"
    sudo mkdir -p "$WORK_DIR"
    sudo chown "$(id -un):$(id -gn)" "$WORK_DIR"

    if [ -f "$WORK_DIR/backend/.env.example" ] && [ ! -f "$WORK_DIR/backend/.env" ]; then
        cp "$WORK_DIR/backend/.env.example" "$WORK_DIR/backend/.env"
        chmod 600 "$WORK_DIR/backend/.env"
        log "已生成 backend/.env（请手工填入真实密钥后 chmod 600）"
    fi

    log "同步 compose 顶层 .env（供 compose 变量插值；密钥在 backend/.env）"
    if [ ! -f "$WORK_DIR/.env" ]; then
        printf '# OmniTest 顶层环境文件（通常留空，密钥统一放 backend/.env）\n' > "$WORK_DIR/.env"
        chmod 600 "$WORK_DIR/.env"
    fi

    log "完成。下一步：编辑 $WORK_DIR/backend/.env 填密钥。"
}

do_check() {
    log "== 依赖检查 =="
    command -v docker   >/dev/null && docker --version || { log "❌ 缺少 docker"; exit 1; }
    docker compose version 2>/dev/null || { log "❌ 缺少 docker compose 插件"; exit 1; }

    log "== 端口检查（5100 应为空闲）=="
    if ss -tln | grep -q ":5100 "; then
        log "⚠️  端口 5100 已被占用："
        ss -tlnp | grep ":5100 "
        log "   请把 PORT 顺延为 5101/5102 并同步改 docker-compose.yml 与 omnitest.conf"
    else
        log "✅ 端口 5100 空闲"
    fi

    log "== 资源 =="
    free -h
    df -h /
}

do_logs() {
    log "跟踪日志（Ctrl+C 退出）"
    touch "$BACKEND_LOG" "$BACKEND_ERR" 2>/dev/null || true
    tail -f "$BACKEND_LOG" "$BACKEND_ERR"
}

case "${1:-}" in
    init)  do_init  ;;
    check) do_check ;;
    logs)  do_logs  ;;
    *)
        echo "用法：$0 {init|check|logs}"
        exit 1
        ;;
esac
