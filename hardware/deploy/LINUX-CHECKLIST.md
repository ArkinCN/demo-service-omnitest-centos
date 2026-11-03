# Linux 部署检查表（设备直插服务器即测）

适用：OmniTest 风扇台架从 Windows（本地跑通）迁移到 Linux 服务器，设备直接插服务器测试。

---

## 0. 前置：项目与 Python 环境

```bash
cd /opt/demo/omnitest
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/
pip install -r hardware/py/requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

- [ ] `.venv` 创建成功，`python -V` 能显示版本（建议 3.10~3.12，**不要用 3.14+**，pyvisa 生态兼容性风险）
- [ ] `pip list` 中可见 `pyserial / pyvisa / pyvisa-py / pyusb`
- [ ] 后端 `fan_executor.py` 的 `_PYTHON` 默认用 `sys.executable`，启动后端时用的是同一个 `.venv/bin/python`

---

## 1. 串口（UNO 风扇，CH340）

```bash
# 插上 UNO 后
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
ls -l /dev/serial/by-id/          # 更稳的设备名（推荐用这个）
```

- [ ] 出现 `/dev/ttyUSB0`（或 `/dev/ttyACM0`）
- [ ] **权限**：当前用户已在 `dialout` 组
  ```bash
  sudo usermod -aG dialout $USER   # 之后需重新登录（或 newgrp dialout）生效
  groups | grep dialout            # 确认已生效
  ```
- [ ] 若无 `dialout` 组权限，打开串口会报 `Permission denied`
- [ ] 建议用 by-id 名：`/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`，避免插拔后序号漂移

---

## 2. 示波器（RIGOL DS1104Z，USB-TMC）

```bash
# 插上示波器后，确认内核识别到 usbtmc
lsmod | grep usbtmc
ls -l /dev/usbtmc* 2>/dev/null
dmesg | tail -20        # 看是否有 RIGOL / usbtmc 相关日志
```

- [ ] `usbtmc` 模块已加载（多数发行版内置，无需手动加载）
- [ ] **无需 Zadig、无需 NI-VISA、无需任何驱动**（这是 Linux 相对 Windows 的最大优势）
- [ ] 若未识别：换 USB 口（避开纯供电口）、换数据线、确认示波器后面板的是 **USB Device 口**

---

## 3. 配置（overlay 切换）

```bash
# 确认 Linux overlay 的串口名与实际一致
cat hardware/v0.6/config/acceptance.linux.json
# 若实际是 /dev/ttyUSB0 而非默认值，改这个 overlay 的 serial.port
```

- [ ] `acceptance.linux.json` 的 `serial.port` = 实际设备名
- [ ] `acceptance.linux.json` 的 `scope.resource` = `""`（留空 → 自动按 VID/PID 枚举）
- [ ] 设置 overlay 环境变量：
  ```bash
  export FAN_CONFIG_PATH=/opt/demo/omnitest/hardware/v0.6/config/acceptance.linux.json
  ```
- [ ] 建议写入 `~/.bashrc` 或 systemd unit 的 `Environment=`，避免每次手动 export

---

## 4. 按序自检（关键，逐条过）

```bash
cd /opt/demo/omnitest/hardware/py

# ① 依赖 + 资源自检
python entrypoints/check_deps.py
```

- [ ] `availableSerialPorts` 含实际串口名
- [ ] `configuredPort` 与实际一致（overlay 生效）
- [ ] `visaResources` 出现 `USB0::...`（**这一条是示波器能否采数的分水岭**）
- [ ] `visaBackends` 里 `@py` 的 `ok=true`（Linux 应直接用 `@py`，无需 `@ivi`）
- [ ] `missing` 为空 → `ready=true`

```bash
# ② 只采示波器（不碰串口，最安全的先验证）
python entrypoints/run_scope.py
# 期望：runs/scope_*/ 下产出 capture.json + CH1/CH2/CH3.csv + screen.bmp
```

- [ ] `capture.json` 里 `metrics` 有真实数值（`voltage.meanV` 等）
- [ ] 无 `Open scope VISA error: No device found.`

```bash
# ③ 只跑风扇（约 40 秒，四档 PWM）
python entrypoints/run_fan.py
# 期望：四档 30/50/70/100 全 ACK，风扇真转
```

- [ ] `commands.csv` 四档均有 `OK DUTY N` 记录
- [ ] 亲眼确认风扇真的转起来

```bash
# ④ 联合实验（异步）
python entrypoints/start.py -ConfigPath ../v0.6/config/acceptance.json -RunId test_001
sleep 5 && cat ../v0.6/runs/test_001/events.jsonl
python entrypoints/stop.py -RunId test_001 -WaitSeconds 30
```

- [ ] `events.jsonl` 有 `controller_identified` + `capture_completed`（**不再出现 `Run directory already exists.`**）
- [ ] `summary.json` 的 `terminalPublished=true`

---

## 5. 后端 / 前端联调

```bash
cd /opt/demo/omnitest/backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8011
```

- [ ] 后端用同一个 `.venv/bin/python`，`_PYTHON` 自动指向它
- [ ] 前端点「启动」→ 曲线动态刷新（真实数据）
- [ ] 若失败，前端 ≤10 秒显示具体原因（后端 `_watch` 早失败收敛已生效）

---

## 6. 常见故障速查

| 现象 | 根因 | 处理 |
|---|---|---|
| `serial.port is empty after overlay merge` | 未设 `FAN_CONFIG_PATH`，主配置 port 为空 | 设 overlay 环境变量 |
| `Configured serial port absent` | 串口号与实际不符 | 改 overlay 的 `serial.port` |
| `Permission denied` 打开串口 | 不在 `dialout` 组 | `usermod -aG dialout` + 重新登录 |
| `Open scope VISA error: No device found.` | usbtmc 未识别 / 资源名不匹配 | `lsmod \| grep usbtmc`；确认 `scope.resource` 留空 |
| 示波器枚举到但身份校验失败 | `expectedIdentity` 序列号不符 | 改 overlay 的 `scope.expectedIdentity` |
| `Run directory already exists.` | 历史遗留 run_id | 换 `-RunId`；该 bug 已修（start.py 路径不再冲突） |

---

## 7. 迁移完成判据

- [ ] `check_deps.py` → `ready=true` 且 `visaResources` 有 `USB0::`
- [ ] `run_scope.py` → 产出真实波形 CSV
- [ ] `run_fan.py` → 四档 ACK + 风扇真转
- [ ] 前端点启动 → 真实曲线 + 无「暂无数据」死循环
- [ ] overlay 环境变量已持久化（重启后仍生效）
