# NI-VISA（@ivi）Linux 部署指南

> 2026-10-11 实测通过。适用：RIGOL DS1000Z Plus + Ubuntu 20.04 + Docker。

## 为什么换 @ivi

原用 `pyvisa-py`（`@py`）+ libusb，与 DS1104Z 固件 `00.04.05.SP2` 兼容性差：

| 症状 | 说明 |
|------|------|
| **第二次读数起永久失败** | 同一会话内第 1 次正常（450 点），第 2~6 次 preamble 全 0（`inc=0`）。重设触发源/电平、新建 VISA 会话均无效，USB 复位只够恢复一次 |
| 点数上限 450 | 500 点起必 `VI_ERROR_TMO`。`chunk_size` 2048/20480/65536、`timeout` 20~30s 全试过，无效 |
| `:DISPlay:DATA?` 截屏必超时 | BMP/PNG/JPEG 三格式全挂（同会话波形读取正常） |

换 `@ivi` 后：**连续 8 次读数全成功**、1200 点不报错。
外部佐证：`rigol-mcp` 项目文档写明「USB is currently hardware-tested on **Windows only**」；
GitHub `pyvisa-py#414` 记录同型号 DS1104z 在 Linux 下也有 USB 读取异常。

---

## 一、安装 NI-VISA runtime

NI 官方只提供 **在线仓库使能包**（`NILinux2026Q3DeviceDrivers.zip` 内每个 deb 仅 34KB）。
**注意：2026 Q3 只支持 jammy(22.04)/noble(24.04)，无 focal(20.04) 仓库**（404）。
但 `libvisa` 只依赖 `libgcc1 libc6 libstdc++6`（无版本下限），实测可跨版本装。

```bash
# 1) 装仓库使能包（选与系统**最接近**的版本；20.04 用 2204 的即可）
sudo dpkg -i ni-ubuntu2204-drivers-2026Q3.deb

# 2) 直接从仓库地址抓包（无需 apt 解析 jammy 源）
BASE=https://download.ni.com/ni-linux-desktop/2026/Q3/deb/ni/jammy
curl -s "$BASE/dists/jammy/ni/binary-amd64/Packages" -o /tmp/ni_pkgs.txt

# 3) 下载 VISA 相关包
for p in libvisa libvisa-data ni-visa-runtime ni-visa-sysapi \
         ni-visa-lxi-discovery ni-visa-labview-io-control \
         ni-visa-passport-usb ni-visa-passport-serial \
         ni-visa-passport-enet ni-visa-labview-rc \
         ni-euladepot ni-syscfg-runtime nicurli ni-avahi-client \
         ni-visa-config; do
  f=$(grep -A20 "^Package: $p$" /tmp/ni_pkgs.txt | grep -m1 '^Filename:' | awk '{print $2}')
  [ -n "$f" ] && curl -O "$BASE/$f"
done

# 4) 安装（--force-depends 跳过发行版版本检查）
sudo dpkg -i --force-depends *.deb
```

关键包作用：`libvisa`（VISA 核心）→ `ni-visa-config`（**生成 `/etc/ni-visa/visaconf.ini`**，
不装它 `/etc/nivisa` 永远不生成，USB 后端不会加载）→ `ni-visa-passport-usb`（USB 后端）。

## 二、解绑内核 usbtmc（必做，否则 RSRC_BUSY）

RIGOL 的 USB-TMC 接口（class `0xFE`/subclass `0x03`）会被内核 `usbtmc` 自动绑定，
NI-VISA 要独占它。不解绑时 `open_resource()` 报 `VI_ERROR_RSRC_BUSY`，且 `list_resources('USB?*')` 为空。

```bash
# 找 RIGOL 的接口号（形如 1-8）
IF=$(ls /sys/bus/usb/devices/ | grep -E "^[0-9]+-[0-9]+$" | while read d; do
  [ "$(cat /sys/bus/usb/devices/$d/idVendor 2>/dev/null)" = "1ab1" ] && echo "$d:1.0" && break
done)
echo "$IF" | sudo tee /sys/bus/usb/drivers/usbtmc/unbind
```
> `deploy/hardware-setup.sh` 第 8 步已自动做这件事。
> 回退 `@py` 时 `sudo modprobe usbtmc` 即可重新绑定。

## 三、软链到标准名（容器内必需）

pyvisa 的 `@ivi` 只按 `libvisa.so` 这个名字找库，**不认带版本号的 `libvisa.so.26.5.0`**，
找不到时报错且 `errs` 为空列表（极难排查）。

```bash
sudo mkdir -p /opt/nivisa
sudo ln -s /usr/lib/x86_64-linux-gnu/libvisa.so.26.5.0 /opt/nivisa/libvisa.so
```

## 四、compose 挂载

```yaml
    volumes:
      - /dev/bus/usb:/dev/bus/usb                              # libusb 通路（回退 @py 时用）
      - /sys:/sys:ro
      - /usr/lib/x86_64-linux-gnu/libvisa.so.26.5.0:/usr/lib/x86_64-linux-gnu/libvisa.so.26.5.0:ro
      - /usr/lib/x86_64-linux-gnu/ni-visa:/usr/lib/x86_64-linux-gnu/ni-visa:ro   # 各 passport .so
      - /etc/ni-visa:/etc/ni-visa:ro                          # visaconf.ini
      - /opt/nivisa/libvisa.so:/usr/lib/x86_64-linux-gnu/libvisa.so:ro          # 标准名软链
    environment:
      VISA_LIBRARY_PATH: "/usr/lib/x86_64-linux-gnu/libvisa.so.26.5.0"
      NIVISA_NO_CACHE: "1"
```

## 五、代码侧

`hardware/py/scope_visa.py` 的 `_default_backend()` 已改为**恒返回 `@ivi`**（Windows/Linux 一致）。
仍可用 `SCOPE_VISA_BACKEND` 环境变量显式覆盖。

`acceptance.linux.json` 的 `scope.waveformPoints` 已恢复 **1200**（libusb 的 450 上限不再适用）。

---

## 故障速查

| 报错 | 原因 | 处理 |
|------|------|------|
| `OSError: Could not open VISA library`（errs 为空） | 容器内没有 `libvisa.so` 标准名 | 检查软链是否挂上 |
| `VI_ERROR_RSRC_BUSY` | 内核 usbtmc 抢占 | 解绑（第二步） |
| `list_resources('USB?*')` 为空 | USB passport 未启用 | 确认 `ni-visa-passport-usb` 已装 + `/etc/ni-visa/visaconf.ini` 存在 |
| 枚举名是 `USB0::0x1AB1::0x04CE::...` | NI-VISA 的正常格式 | 与 libusb 的 `USB0::6833::1230::...` 不同，两者都能开 |
| `-350,"Queue overflow"` | 错误队列塞满（30 条上限） | USB 复位 + 解绑；`code` 里已加 `-350` 提前 break |
| 全程 `VI_ERROR_TMO` 且设备在线 | 仪器 USB 子系统卡死 | **物理拔插 USB 线**，软件层无法恢复 |
