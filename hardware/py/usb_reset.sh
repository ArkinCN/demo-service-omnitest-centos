#!/usr/bin/env bash
# =============================================================================
# USB 设备软复位（免物理拔插）
#
# 用途：RIGOL DS1104Z 的 USB 控制器在一次异常传输后会卡死——设备仍能被枚举、
#       能 claim，但对任何 SCPI 命令都不再应答（write/read 全部 Errno 110 超时）。
#       对 sysfs 的 authorized 做 0→1 翻转即可让它恢复（实测 2026-10-11 有效）。
#
# 用法：
#   sudo bash usb_reset.sh              # 自动探测 RIGOL 的 bus-port
#   sudo bash usb_reset.sh 1-8          # 指定 bus-port
#
# ⚠️ 必须以 root 运行（写 sysfs 需要）。容器内无此权限，故在**宿主机**执行。
# ⚠️ 复位瞬间 USB 设备会重枚举，bus 号/device 号可能变化：
#    若 docker-compose.yml 里显式写了 --device /dev/bus/usb/BBB/DDD，
#    复位后需同步更新（可用本脚本末尾提示的新设备号）。
# =============================================================================
set -uo pipefail

RIGOL_VID="1ab1"
RIGOL_PID="04ce"
SYSFS_BASE="/sys/bus/usb/devices"

log() { echo "[usb_reset] $*"; }
die() { echo "[usb_reset][FAIL] $*" >&2; exit 1; }

# ---- 定位设备的 bus-port（如 1-8）----
find_port() {
    local vid_file
    for vid_file in "$SYSFS_BASE"/*/idVendor; do
        [ -f "$vid_file" ] || continue
        local vid pid_file pid
        vid=$(cat "$vid_file" 2>/dev/null) || continue
        [ "${vid,,}" = "$RIGOL_VID" ] || continue
        pid_file="${vid_file%idVendor}idProduct"
        [ -f "$pid_file" ] || continue
        pid=$(cat "$pid_file" 2>/dev/null) || continue
        [ "${pid,,}" = "$RIGOL_PID" ] || continue
        basename "$(dirname "$vid_file")"
        return 0
    done
    return 1
}

PORT="${1:-}"
if [ -z "$PORT" ]; then
    PORT="$(find_port)" || die "未在 sysfs 找到 RIGOL ($RIGOL_VID:$RIGOL_PID)，设备是否插好？"
fi

DEV_DIR="$SYSFS_BASE/$PORT"
[ -d "$DEV_DIR" ] || die "设备目录不存在: $DEV_DIR"
AUTH="$DEV_DIR/authorized"

BUS_NUM="${PORT%%-*}"
echo "----"
log "目标设备   : $PORT ($RIGOL_VID:$RIGOL_PID)"
log "VID/PID    : $(cat "$DEV_DIR/idVendor" 2>/dev/null):$(cat "$DEV_DIR/idProduct" 2>/dev/null)"

# ---- 执行 0→1 翻转 ----
log "写入 authorized=0 …"
echo 0 > "$AUTH" 2>/dev/null || die "写 authorized 失败（需要 root）"
sleep 2

log "写入 authorized=1 …"
echo 1 > "$AUTH" 2>/dev/null || die "写 authorized 失败（需要 root）"
sleep 3

# ---- 复位后汇报 ----
log "复位完成，设备现状："
lsusb | grep -i "${RIGOL_VID}:${RIGOL_PID}" || log "⚠️ lsusb 未见设备，检查线缆/供电"

NEW_PORT="$(find_port || true)"
if [ -n "$NEW_PORT" ] && [ "$NEW_PORT" != "$PORT" ]; then
    log "⚠️ 设备端口已变化: $PORT → $NEW_PORT"
    PORT="$NEW_PORT"
fi
NEW_BUS="${PORT%%-*}"
NEW_NUM="$(cat "$DEV_DIR/devnum" 2>/dev/null || echo '?')"
log "新设备节点 : /dev/bus/usb/$NEW_BUS/$NEW_NUM"
case "$DEV_DIR" in
    */usb*) ;;
esac
USB_NODE="/dev/bus/usb/$NEW_BUS/$NEW_NUM"
log "若 docker-compose.yml 显式声明了 --device /dev/bus/usb/... ，请更新为："
log "    $USB_NODE:$USB_NODE"
log "现在可重测："
log "    python hardware/py/scope_link_probe.py"
log "----"

# ---------------------------------------------------------------------------
# NI-VISA(@ivi) 专用收尾：解绑内核 usbtmc + 重启 backend 容器
# ---------------------------------------------------------------------------
# 为什么必须做（2026-10-12 实测）：
#   ① 本机示波器已改用 NI-VISA(@ivi)，它需要**独占** USB-TMC 接口。
#      重新枚举后内核 usbtmc 会自动绑回，不解绑则 @ivi 打开报 VI_ERROR_RSRC_BUSY。
#   ② 容器内 `/dev/bus/usb` 是**创建时快照挂载**的，拔插/重新枚举产生的新节点
#      不会自动出现（容器内 ls 不到、@ivi 超时，宿主机同一时刻却正常）。
#      必须重启容器才刷新。
log "----"
log "NI-VISA 收尾处理"

IFACE=""
for _v in /sys/bus/usb/devices/*/idVendor; do
    [ -f "$_v" ] || continue
    [ "$(cat "$_v" 2>/dev/null)" = "1ab1" ] || continue
    IFACE="$(basename "$(dirname "$_v")"):1.0"
    break
done

if [ -n "$IFACE" ]; then
    if [ -L "/sys/bus/usb/devices/$IFACE/driver" ]; then
        echo "$IFACE" > /sys/bus/usb/drivers/usbtmc/unbind 2>/dev/null             && log "✓ 已解绑内核 usbtmc（$IFACE）→ NI-VISA 可独占"             || log "⚠️ 解绑 usbtmc 失败（可能需 root 或已解绑）"
    else
        log "· 内核驱动未占用（已解绑或无驱动）"
    fi
else
    log "⚠️ 未找到 RIGOL 接口，跳过解绑"
fi

# 重启容器以刷新 /dev/bus/usb 快照
if command -v docker >/dev/null 2>&1; then
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^omnitest-backend$'; then
        docker restart omnitest-backend >/dev/null 2>&1             && log "✓ 已重启 omnitest-backend（刷新 USB 节点快照）"             || log "⚠️ 容器重启失败，请手动执行：docker restart omnitest-backend"
        sleep 8
    else
        log "· omnitest-backend 未运行，跳过容器重启"
    fi
fi

log "----"
log "完成后自检："
log "    docker exec omnitest-backend python -c \"import pyvisa; rm=pyvisa.ResourceManager('@ivi'); print(rm.list_resources('USB?*')); rm.close()\""
log "----"
