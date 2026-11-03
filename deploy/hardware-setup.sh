#!/usr/bin/env bash
# =============================================================================
# OmniTest 宿主机硬件配置（部署方案 A：硬件挂 Linux 本体机 + 容器 devices 直通）
#
#   用途：首次部署时在服务器上执行一次，执行完日常部署不再需要它。
#   要求：root 或 sudo；UNO 与示波器已插好。
#   幂等：可重复执行。
#
#   本脚本只做「宿主机侧」的事：内核模块、udev 规则、用户组、日志目录。
#   容器侧（Dockerfile / docker-compose.yml / acceptance.linux.json）由仓库提供。
# =============================================================================
set -euo pipefail

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
fi
DEPLOY_USER="${DEPLOY_USER:-${SUDO_USER:-fjs}}"

log()  { echo -e "\n\033[1;34m==> $*\033[0m"; }
ok()   { echo -e "  [OK]   $*"; }
warn() { echo -e "  [WARN] $*"; }
die()  { echo -e "  [FAIL] $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
log "1/7 检查硬件是否被识别"
# ---------------------------------------------------------------------------
# 期望 VID:PID —— 1a86:7523 = CH340(UNO)；1ab1:04ce = RIGOL DS1104Z Plus
lsusb | grep -iE "1ab1:04ce|1a86:7523" \
    && ok "USB 设备已识别" \
    || warn "未匹配到预期 USB 设备（1ab1:04ce / 1a86:7523），请核对下方 lsusb 输出"

ls -la /dev/ttyUSB* /dev/usbtmc* 2>/dev/null || warn "设备节点尚未出现"
# 记下实际节点名：与 docker-compose.yml 的 devices 必须一致
echo "  实际节点：$(ls /dev/ttyUSB* /dev/usbtmc* 2>/dev/null | tr '\n' ' ')"

# ---------------------------------------------------------------------------
log "2/7 加载 usbtmc 内核模块（USB-TMC 示波器必需）"
# ---------------------------------------------------------------------------
$SUDO modprobe usbtmc
echo "usbtmc" | $SUDO tee /etc/modules-load.d/usbtmc.conf >/dev/null
# ⚠️ 不要写成 `lsmod | grep -q usbtmc`：在 set -o pipefail 下，grep -q 命中即退出，
#    lsmod 收到 SIGPIPE 返回 141 → 整条管道判为失败 → 误报「加载失败」并 die，
#    导致后续 udev/用户组步骤全不执行。改为捕获到变量再判断。
USBTMC_LOADED="$(lsmod | grep usbtmc || true)"
[ -n "$USBTMC_LOADED" ] && ok "usbtmc 已加载并设为开机自载" || die "usbtmc 加载失败"

# ---------------------------------------------------------------------------
log "3/7 写入 udev 规则"
# ---------------------------------------------------------------------------
# 说明（部署时的关键理解）：
#   · 真正让容器能访问设备节点的是下面第 3 条（usbmisc/usbtmc）与第 2 条（tty）。
#   · 第 1 条（SUBSYSTEM=="usb"）针对 /dev/bus/usb/XX/YY 原始节点，
#     pyvisa-py 走 usbtmc + libusb 时通常用不到，留着无害（备 USB 直连场景）。
$SUDO tee /etc/udev/rules.d/99-omnitest.rules >/dev/null <<'EOF'
# OmniTest 硬件：UNO(CH340) + RIGOL DS1104Z Plus(USB-TMC)
# MODE=0666 让容器内进程（非 root 且无宿主组成员资格时）也能读写设备节点。
SUBSYSTEM=="usb",    ATTR{idVendor}=="1ab1", ATTR{idProduct}=="04ce", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="tty",     ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="usbmisc", KERNEL=="usbtmc*",                          MODE="0666", GROUP="plugdev"
EOF

$SUDO udevadm control --reload-rules
$SUDO udevadm trigger
ok "udev 规则已生效（99-omnitest.rules）"

# ---------------------------------------------------------------------------
log "4/7 把部署用户加入 dialout / plugdev 组"
# ---------------------------------------------------------------------------
if id "$DEPLOY_USER" >/dev/null 2>&1; then
    $SUDO usermod -aG dialout,plugdev "$DEPLOY_USER"
    ok "$DEPLOY_USER 已加入 dialout,plugdev"
else
    warn "用户 $DEPLOY_USER 不存在，跳过（可稍后手动 usermod）"
fi

# ---------------------------------------------------------------------------
log "5/7 预建日志目录（gunicorn.conf.py 硬编码 /var/log/demo）"
# ---------------------------------------------------------------------------
# ⚠️ 不创建会导致 gunicorn 启动即失败（accesslog/errorlog 打不开）。
#    但若因某种原因未创建，Docker 会自动以 root 身份创建该挂载点，容器内 root 仍可写。
$SUDO mkdir -p /var/log/demo
$SUDO chown "$DEPLOY_USER":"$DEPLOY_USER" /var/log/demo 2>/dev/null || $SUDO chown root:root /var/log/demo
$SUDO chmod 755 /var/log/demo
ok "/var/log/demo 就绪"

# ---------------------------------------------------------------------------
log "6/7 探测示波器 raw USB 节点并回填 docker-compose.yml"
# ---------------------------------------------------------------------------
# 起因（2026-10-11 实测）：示波器走 libusb 通路，容器需要
#   ① -v /dev/bus/usb:/dev/bus/usb   （容器内能 ls 到节点）
#   ② --device /dev/bus/usb/BBB/DDD  （设备 cgroup 授权，否则 libusb_open 报 Errno 5）
# 而 BBB/DDD（bus/device 号）**每次 USB 重插都会变**，写死在 compose 里很快失效，
# 表现为 `error gathering device information` 或后端突然打不开示波器。
# 故此处动态探测并就地回填。
RIGOL_VID="1ab1"
RIGOL_PID="04ce"
SCOPE_NODE=""
for _vid in /sys/bus/usb/devices/*/idVendor; do
    [ -f "$_vid" ] || continue
    _v=$(cat "$_vid" 2>/dev/null) || continue
    [ "${_v,,}" = "$RIGOL_VID" ] || continue
    _pidf="${_vid%idVendor}idProduct"
    [ -f "$_pidf" ] || continue
    _p=$(cat "$_pidf" 2>/dev/null) || continue
    [ "${_p,,}" = "$RIGOL_PID" ] || continue
    # devnum 只是 device 号（如 5），完整节点需 bus 号/device 号：/dev/bus/usb/001/005。
    # bus 号取自设备目录名的 '-' 左侧（1-8 → bus 1），device 号取自 devnum。
    _devdir="$(dirname "$_vid")"                       # /sys/bus/usb/devices/1-8
    _busnum="$(cat "$_devdir/busnum" 2>/dev/null)"
    [ -n "$_busnum" ] || _busnum="$(basename "$_devdir" | cut -d- -f1)"
    _devnum="$(cat "$_devdir/devnum" 2>/dev/null)"
    [ -n "$_busnum" ] && [ -n "$_devnum" ] && SCOPE_NODE="$(printf '%03d/%03d' "$_busnum" "$_devnum")"
    break
done

if [ -z "$SCOPE_NODE" ]; then
    warn "未找到示波器 raw USB 节点（VID $RIGOL_VID / PID $RIGOL_PID）"
    warn "  设备未插好时，docker compose 会因 devices 声明缺失而启动失败。"
else
    ok "示波器节点: /dev/bus/usb/$SCOPE_NODE"
    COMPOSE_FILE="${COMPOSE_FILE:-$(dirname "$0")/../docker-compose.yml}"
    if [ -f "$COMPOSE_FILE" ] && grep -qE '/dev/bus/usb/[0-9]+/[0-9]+:' "$COMPOSE_FILE"; then
        $SUDO cp "$COMPOSE_FILE" "$COMPOSE_FILE.bak.$(date +%Y%m%d-%H%M%S)" 2>/dev/null
        sed -i -E "s|/dev/bus/usb/[0-9]+/[0-9]+:/dev/bus/usb/[0-9]+/[0-9]+|/dev/bus/usb/$SCOPE_NODE:/dev/bus/usb/$SCOPE_NODE|g" "$COMPOSE_FILE"
        ok "docker-compose.yml 已回填 /dev/bus/usb/$SCOPE_NODE"
    fi
fi

# ---------------------------------------------------------------------------
log "7/7 在宿主机 Python 上验证硬件库与设备可见性（可选诊断）"
# ---------------------------------------------------------------------------
PYBIN="${PYBIN:-python3}"
if command -v "$PYBIN" >/dev/null 2>&1; then
    if "$PYBIN" -c "import serial, pyvisa" >/dev/null 2>&1; then
        ok "宿主机 $PYBIN 已有 serial + pyvisa（容器内另有一套，不冲突）"
    else
        warn "宿主机 $PYBIN 缺 serial/pyvisa —— 不影响容器内采集，仅影响本机手工诊断"
        warn "  如需本机诊断：$PYBIN -m pip install -r hardware/py/requirements.txt"
    fi
    # 容器内探测用同一段逻辑：能否枚举 USB-TMC 设备
    if "$PYBIN" -c "import serial, pyvisa" >/dev/null 2>&1; then
        "$PYBIN" - <<'PY' || warn "VISA 枚举未发现设备（不阻断部署，容器内可能表现不同）"
import pyvisa
try:
    rm = pyvisa.ResourceManager("@py")
    res = rm.list_resources()
    print("  [OK]   VISA 资源：", res if res else "（空——检查 udev 规则与设备是否插好）")
except Exception as e:
    print("  [WARN] VISA 枚举失败：", e)
    raise SystemExit(1)
PY
    fi
else
    warn "未找到 $PYBIN，跳过本机诊断"
fi

# ---------------------------------------------------------------------------
log "8/8 解绑内核 usbtmc 驱动（NI-VISA @ivi 需要独占 USB 接口）"
# ---------------------------------------------------------------------------
# 原因（2026-10-11 实测）：示波器的 USB-TMC 接口（class 0xFE/subclass 0x03）
# 会被内核 usbtmc 自动绑定。NI-VISA 的 USB passport 要独占该接口，
# 不解绑时 `open_resource()` 直接报 `VI_ERROR_RSRC_BUSY`，
# 且 `list_resources('USB?*')` 枚举不到设备。
# （pyvisa-py@py 恰恰相反：它抢不过内核驱动，必须靠 usb_env 里显式 detach。）
#
# 解绑后 libusb/pyvisa-py 路线会失效 —— 这是有意的取舍：@ivi 是稳定的那条路。
# 需要回退 @py 时，重跑 `modprobe usbtmc` 即可（见脚本末尾提示）。
RIGOL_IF=""
for _if in /sys/bus/usb/devices/*/idVendor; do
    [ -f "$_if" ] || continue
    _v=$(cat "$_if" 2>/dev/null) || continue
    [ "${_v,,}" = "1ab1" ] || continue
    _pidf="${_if%idVendor}idProduct"
    _p=$(cat "$_pidf" 2>/dev/null) || continue
    [ "${_p,,}" = "04ce" ] || continue
    RIGOL_IF=$(basename "$(dirname "$_if")")
    break
done
if [ -n "$RIGOL_IF" ] && [ -L "/sys/bus/usb/devices/$RIGOL_IF/driver" ]; then
    if [ "$(basename "$(readlink -f "/sys/bus/usb/devices/$RIGOL_IF/driver")")" = "usbtmc" ]; then
        echo "$RIGOL_IF" | $SUDO tee /sys/bus/usb/drivers/usbtmc/unbind >/dev/null 2>&1 \
            && ok "已解绑内核 usbtmc（$RIGOL_IF）→ NI-VISA 可独占" \
            || warn "解绑 usbtmc 失败，@ivi 会报 RSRC_BUSY"
    else
        ok "内核驱动非 usbtmc（已是 $(basename "$(readlink -f "/sys/bus/usb/devices/$RIGOL_IF/driver")")），无需解绑"
    fi
else
    warn "未找到 RIGOL USB 接口的 usbtmc 绑定，跳过（如遇 RSRC_BUSY 手动执行："
    warn "  echo '<ifnum>' | sudo tee /sys/bus/usb/drivers/usbtmc/unbind)"
fi

# ---------------------------------------------------------------------------
cat <<EOF

==============================================================================
✅ 宿主机硬件配置完成

接下来（每次改代码都走这几步）：
  1. 确认硬件已插：ls -la /dev/ttyUSB* /dev/usbtmc*
  2. 核对 docker-compose.yml 的 devices 与上面实际节点一致
  3. cd /opt/demo/omnitest && docker compose -p omnitest up -d --build
  4. 查日志：docker logs -f omnitest-backend

⚠️ 设备节点不存在时，docker compose up 会直接失败（后端连带起不来）。

用户组变更需重新登录 SSH 才生效。
==============================================================================
EOF
