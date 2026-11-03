# Linux 示波器（USB-TMC）诊断报告

> **状态：✅ 已解决（2026-10-11 02:00）**
> 现象：`No RIGOL USB-TMC scope found; enumerated: ['ASRL/dev/ttyUSB0::INSTR'] (backend=@py)`
> 目标设备：RIGOL DS1104Z Plus（VID 1ab1 / PID 04ce），与风扇 CH340 同插在 192.168.31.178
>
> **实测结果**：`*IDN?` → `RIGOL TECHNOLOGIES,DS1104Z Plus,DS1ZC271600575,00.04.05.SP2`，
> `:WAV:DATA?` 取到 100 点真实波形，风扇串口亦正常。

---

## 一、真正根因（三层，逐层剥开）

### 表层：容器缺少 libusb 访问路径
`/dev/bus/usb` 未挂进容器 → pyusb 只能"看见"设备（读 sysfs 枚举），
一 `set_configuration()` 就 `Errno 19 No such device`。

### 中层：内核 usbtmc 驱动独占接口
RIGOL 的 USB-TMC 接口（`class 0xFE / subclass 0x03 / proto 0x01`）被内核 `usbtmc`
自动绑定，libusb **不接管内核已绑定的接口** → 必须显式 `detach_kernel_driver(iface)`。

### 底层：设备 USB 控制器进入卡死态（最隐蔽）
**这是真正的病根**。表现为：设备仍能被枚举、能 claim、能打开会话，
但对任何 SCPI 命令**都不再应答**（write/read 全部 `Errno 110` 超时）。

识别特征（与普通驱动问题区分）：
- `*IDN?` 可能仍成功（复位后的第一条命令）
- 随后所有命令随机超时，行为**不稳定**
- 换成 `:WAV:MODE?` 又能成功——**同一次会话内时好时坏**

处置：对 sysfs 的 `authorized` 做 `0 → 1` 翻转（USB 软复位，免物理拔插）即可恢复：

```bash
echo 0 > /sys/bus/usb/devices/<bus>-<port>/authorized
sleep 2
echo 1 > /sys/bus/usb/devices/<bus>-<port>/authorized
```

已封装为 `hardware/py/usb_reset.sh`（自动探测 bus-port，打印新设备号）。

---

## 二、已生效的代码改动

| 文件 | 改动 | 作用 |
|------|------|------|
| `docker-compose.yml` | 加 `-v /dev/bus/usb:/dev/bus/usb`、`-v /sys:/sys:ro`、`--device /dev/bus/usb/001/005:...` | 让容器能真正打开 USB 设备 |
| `docker-compose.yml` | **移除** `devices: /dev/usbtmc0` | 该节点在设备重枚举后不重建，留着会让容器起不来 |
| `hardware/py/usb_env.py` | 新增 `detach_kernel_drivers()` | 从内核 usbtmc 抢回接口给 libusb |
| `hardware/py/usb_env.py` | 新增 `is_timeout_error()` / `find_usb_sysfs_path()` | 卡死识别 + 定位 bus-port，供复位脚本用 |
| `hardware/py/usb_env.py` | `ensure_usb_backend()` 加 Linux 分支 | Linux 探测 `libusb-1.0.so.0`，不提前 import usb.core |
| `hardware/py/scope_visa.py` | 打开会话前调 detach | 保证 libusb 能 claim |
| `hardware/py/scope_visa.py` | `_find_fallback` 增加 `6833`/`1230` 匹配 | 资源名用**十进制厂商码**，不是 `0X1AB1`（原代码匹配不到） |
| `hardware/py/scope_link_probe.py` | 新建 | 链路七步自检，卡死时给出复位指引 |
| `hardware/py/usb_reset.sh` | 新建 | USB 软复位，自动探测设备号 |
| `deploy/hardware-setup.sh` | 新增第 6 步 | 自动探测 bus/device 号并回填 compose |

---

## 三、关键认知（避免重复踩坑）

1. **资源名不含 `0x1AB1` 字面量**。pyvisa 把 VID 转成十进制厂商码，
   RIGOL(0x1AB1=6833) 表现为 `USB0::6833::1230::DS1ZC271600575::0::INSTR`。
   原 `_find_fallback` 按 `0X1AB1` 匹配，永远匹配不上（只有"唯一 USB 资源"退化分支能兜）。

2. **`/dev/usbtmc0` 在本机不可靠**。内核 usbtmc 总线没注册（`/sys/bus/usbtmc/` 不存在），
   该节点是空壳（ioctl 返回 ENOTTY），且设备重枚举后不再重建。
   **不要把它写进 compose 的 `devices`**，否则容器直接起不来。

3. **设备号会变**。`/dev/bus/usb/001/005` 中的 bus/device 每次 USB 重插都变，
   必须靠 `hardware-setup.sh` 第 6 步动态回填。

4. **pyserial 在 Linux 上不能驱动 usbtmc 设备**。3.5 无 `UsbTMC` 类，
   对 `/dev/usbtmc0` 套 termios 必然 `[Errno 56] Invalid request code`。

---

## 四、日常操作

```bash
# 采集前若报超时，先软复位
sudo bash /opt/demo/omnitest/hardware/py/usb_reset.sh

# 链路自检（容器内）
docker exec omnitest-backend python /srv/omnitest/c/hardware/py/scope_link_probe.py

# 换 USB 口/重插设备后，必须重跑以更新设备号
cd /opt/demo/omnitest && sudo bash deploy/hardware-setup.sh && docker compose -p omnitest up -d
```

若软复位也无效 → 依次尝试：换数据线（非充电线）→ 换 USB 2.0 口 → 改走网口
（示波器屏上 `System → Remote Control` 查 IP，配置 `scope.resource` 为 `TCPIP0::<IP>::INSTR`，
该通路 pyvisa-py 原生支持、不经 libusb，是最稳的备选）。


---

## 一、硬件与内核侧（均正常，不需改）

| 检查项 | 结果 |
|--------|------|
| `lsusb` | `Bus 001 Device 005: ID 1ab1:04ce Rigol Technologies DS1000Z Series` ✅ |
| 接口描述符 | Class `0xFE` / SubClass `0x03` / Protocol `0x01` = 标准 USB-TMC ✅ |
| 端点 | `0x03` Bulk OUT、`0x82` Bulk IN、`0x81` Interrupt IN ✅ 全为 BULK |
| 内核 `usbtmc` 模块 | 已加载，`modinfo` 匹配条件含 `icFEisc03ip01`（与设备完全匹配）✅ |
| dmesg | 无 disconnect 记录，`Device 005` 自 2024111 起未变 ✅ |
| 设备节点 | `/dev/usbtmc0`(180:0)、`/dev/ttyUSB0`(188:0)，udev 规则 MODE=0666 已生效 ✅ |

**风扇串口链路完全正常**：`/dev/ttyUSB0` 打开成功，发 `F?\n` 收到 Arduino ready 响应 `b'<\xfa'`。

---

## 二、根因（本机特有，与代码无关）

### 现象 1：内核 usbtmc 总线未注册

```
/sys/bus/usbtmc/       → 不存在
/sys/class/usbtmc/     → 不存在
/sys/bus/usbtmc/drivers/usbtmc/new_id → 写入报 I/O error
```

dmesg 显示 `registered new interface driver usbtmc` 但**从未 probe 到设备**，
因此 `/dev/usbtmc0` 是个"空壳"节点：对它发 `USBTMC_GET_CAPABILITIES` ioctl
返回 **ENOTTY(56)**，即内核层面它根本不是 usbtmc 设备。

→ **结论：走内核 usbtmc ioctl 协议栈这条路，在本机不可用。**

### 现象 2：libusb 能枚举但设备不应答

给容器加挂 `/dev/bus/usb` + `--device` 授权后，pyusb/libusb **能枚举到**：

```
USB0::6833::1230::DS1ZC271600575::0::INSTR
```

> 这个资源名格式与 Windows 上成功运行时的 `acceptance.windows.json`
> 里配的 `USB0::6833::1230::DS1ZC271600575::0::INSTR` **完全一致**，
> 说明 VID/PID→资源名的映射没问题，驱动侧是通的。

但**所有 USB 控制传输返回 `Pipe error [Errno 32]`**，
Bulk OUT 写入"成功"但设备不返回任何响应，`query('*IDN?')` 必然超时。

→ **结论：RIGOL DS1104Z 在 libusb1 后端下不接受 vendor 控制请求。**

---

## 三、已排除的假设

| 假设 | 验证方式 | 结果 |
|------|---------|------|
| 阿里云镜像缺包 | 换腾讯云源 | 已排除（安装成功但仍不通） |
| pyvisa-py 版本回归 | 降级 0.8.1 → 0.7.1 | 已排除（0.7.1 同样超时） |
| 缺 `/dev/bus/usb` | 加挂后枚举成功 | 部分成立，但通信仍不通 |
| 需显式 detach 内核驱动 | `detach_kernel_driver(0)` | **必须做**，否则 Errno 19；做完 claim 成功但通信仍超时 |
| 需 privileged | `--privileged` | claim 成功，通信仍超时 |
| pyserial 直连 | `serial_for_url('/dev/usbtmc0')` | 失败 `(56,'Invalid request code')`——pyserial 3.5 无 Linux UsbTMC 类，对 usbtmc 设备套 termios 必失败 |
| python-usbtmc 包 | `Instrument.ask()` | 失败——内部同样走 libusb |
| pyvisa query 逻辑问题 | 拆成 write + read_raw | 失败——`write` 本身就超时 |

---

## 四、关键外部证据

GitHub **pyvisa/pyvisa-py#414**：同型号 DS1104Z Plus 在 Linux + pyvisa-py 上
**基本可通信**（枚举、打开、SCPI 读写都正常，仅 `:WAV:DATA?` 大块读取有截断问题）。
该 issue 中 pyvisa 调试日志同样是 `reading 20480 bytes`，且该机固件未说明版本。

**差异点**：本机固件为 `00.04.05.SP2`，dmesg 显示设备自 `bcdDevice=0.02` 起从未重连过。

---

## 五、候选方案（按可行性排序）

### 方案 A：换 USB 物理链路（成本最低，先试）
Errno 32 / Pipe error 在实践中常由以下物理因素引起：

- USB 线质量问题（充电线无数据线芯，最常见）
- USB 3.0 的 SS+/SS− 差分对接触不良 → 换 USB 2.0 口
- 供电不足（示波器 USB 供电 + 风扇同时插）

**动作**：换一根**数据线**（非充电线）+ 插主板 USB 2.0 口，观察 `lsusb` 是否仍显示 `Device 005`。
若换口后设备号变化（如变成 Device 007），说明确实重连过，此时立刻重跑通信测试。

### 方案 B：改用网络接口（LXI/TCPIP，绕开 USB）
DS1104Z Plus 自带以太网口。pyvisa 对 `TCPIP0::<IP>::INSTR` 支持完整，
且 issue #414 中明确提到「TCPIP protocol works fine」。

**动作**：
1. 示波器接网线，与服务器同网段
2. 查示波器 IP（屏上 `System → Remote Control`）
3. `acceptance.linux.json` 的 `scope.resource` 改为 `TCPIP0::<IP>::INSTR`
4. 后端仍用 `@py`（TCPIP 通路 pyvisa-py 原生支持，不经 libusb）

**代价**：需改配置（1 行）；风险低。**这是最可能一次成功的方案。**

### 方案 C：装 NI-VISA Linux runtime，走 `@ivi`
与 Windows 成功路径完全一致。

**代价**：需下载安装 RIGOL/NI 官方 VISA runtime（约 100~300MB，闭源），
容器内需额外挂载 runtime 目录。许可与版本兼容需确认。

### 方案 D：容器改用 host 网络 + 宿主中转
宿主机已验证 `detach + claim` 成功（见下方实验记录），
若方案 A/B 都不行，可让容器通过宿主机的 USB 代理访问设备。
实现复杂度较高，仅作兜底。

---

## 六、已验证可行的最小改动（方案 A/B 的前置）

无论最终用哪个方案，**必须先 detach 内核驱动**，否则 libusb 拿不到句柄：

```python
d = usb.core.find(idVendor=0x1ab1, idProduct=0x04ce)
for i in range(4):
    try:
        if d.is_kernel_driver_active(i):
            d.detach_kernel_driver(i)
    except Exception:
        pass
```

容器侧 compose 需补两个挂载（当前缺失，是本轮实测确认的关键）：

```yaml
volumes:
  - /dev/bus/usb:/dev/bus/usb          # libusb 访问 raw USB 节点
devices:
  - /dev/bus/usb/001/005:/dev/bus/usb/001/005   # 显式 cgroup 授权
```

> 注：`devices:` 直接写 `/dev/bus/usb/001/005` 会随设备重插而失效（设备号会变），
> 故用 `-v` 挂整个 `/dev/bus/usb` + `--device` 显式授权当前节点。
> 更稳的做法是在 hardware-setup.sh 里动态探测 RIGOL 的 bus 号再生成 compose 片段。

---

## 七、下一步（最小单元，建议顺序）

1. **换线换口** → 重跑 §六 的 detach + pyvisa `*IDN?` 测试（5 分钟，无需改代码）
2. 若仍超时 → **走网线**，改 `scope.resource` 为 TCPIP（改 1 行配置）
3. 若网线也不通 → 评估方案 C（NI-VISA Linux runtime）

每一步都先跑最小验证脚本，确认通了再改正式代码。

---

## 附：最小验证脚本

保存为 `/tmp/scope_probe.py`，在容器内执行：

```python
import warnings; warnings.filterwarnings('ignore')
import usb.core
d = usb.core.find(idVendor=0x1ab1, idProduct=0x04ce)
for i in range(4):
    try:
        if d.is_kernel_driver_active(i):
            d.detach_kernel_driver(i)
    except Exception:
        pass
import pyvisa
rm = pyvisa.ResourceManager('@py')
for r in rm.list_resources():
    print('枚举:', r)
inst = rm.open_resource('USB0::6833::1230::DS1ZC271600575::0::INSTR')
inst.timeout = 8000
print('✅ IDN:', inst.query('*IDN?'))
```

运行方式：

```bash
docker run --rm \
  -v /dev/bus/usb:/dev/bus/usb \
  -v /sys:/sys:ro \
  --device /dev/bus/usb/001/005:/dev/bus/usb/001/005 \
  --entrypoint python omnitest-backend:latest /tmp/scope_probe.py
```
