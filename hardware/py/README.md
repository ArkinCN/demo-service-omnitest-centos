# 风扇实验硬件包 · Python 跨平台版

这是 `hardware/v0.6/`（原 PowerShell + C# + NI-VISA，纯 Windows）的 **Python 重写版**，
用 `pyserial` + `pyvisa-py` 实现，Windows 与 Linux 通用，最终可部署到 Linux。

> 原 PowerShell 脚本保留在 `hardware/v0.6/` 不删，作为回退对照。
> 本目录与之**行为契约完全一致**：产物格式（events.jsonl / summary.json / …）、
> 串口协议、SCPI 序列、波形推算口径、入口返回 JSON 全部对齐，后端与前端无需改动。

## 目录结构

```
hardware/py/
├── fan_serial.py       # 串口层（pyserial）：SerialWire / FanSession / CancelSignal
├── scope_visa.py       # 示波器 VISA（pyvisa-py）：ScopeDevice / block_payload
├── scope_capture.py    # SCPI 序列 + 波形推算 + CSV/BMP 导出
├── runtime.py          # 配置校验 + 事件/state 原子发布
├── run_experiment.py   # 主流程
├── entrypoints/
│   ├── start.py        # 异步启动（对应 start.ps1）
│   ├── stop.py         # 停止（对应 stop.ps1）
│   ├── run_fan.py      # 独立跑风扇（对应 run-fan.ps1）
│   ├── run_scope.py    # 独立采集示波器（对应 run-scope.ps1）
│   └── check_deps.py   # 依赖检查（对应 check-dependencies.ps1）
├── requirements.txt
└── README.md

../v0.6/config/
├── acceptance.json           # 主配置（port/resource 留空）
├── acceptance.windows.json   # Windows overlay
└── acceptance.linux.json     # Linux overlay

deploy/LINUX-CHECKLIST.md     # Linux 部署检查表
```

## 1. 环境准备

### 1.1 Python 依赖（Windows / Linux 通用）

```bash
python -m pip install -r requirements.txt
```

### 1.2 串口驱动

- **Windows**：安装 CH340/CH341 USB 转串口驱动（UNO 板载），设备管理器中确认 COM 号。
- **Linux**：CH340 通常内核自带（`/dev/ttyUSB0`）；如无权限，把用户加入 `dialout` 组：
  `sudo usermod -aG dialout $USER`（重新登录生效）。

### 1.3 示波器驱动（关键，Windows 需切 WinUSB）

`pyvisa-py` 走 USB-TMC 协议，依赖 `pyusb` + 底层 USB 驱动：

- **Windows**：
  1. 安装 [Zadig](https://zadig.akeo.ie/)，把 RIGOL DS1104Z 的 USB 接口驱动**替换为 WinUSB**（本项目已确认该机为 WinUSB）。
  2. 确保已装 `pyusb`（`requirements.txt` 已含）；`pyvisa-py` 的 usbtmc 后端经 libusb/WinUSB 访问设备。
  3. 若 `@py` 后端仍枚举不到（Windows 偶发 libusb 链路问题），可**临时切 NI-VISA 后端**：
     `set SCOPE_VISA_BACKEND=@ivi`（需已装 NI-VISA 64 位）。
- **Linux**：内核自带 `usbtmc`，**无需任何驱动**，`@py` 后端直接可见。

> 诊断：跑 `python entrypoints/check_deps.py`，看输出里 `visaResources` 是否出现 `USB0::` 开头项，
> 以及 `visaBackends` 里两个后端（`@py` / `@ivi`）各自枚举到什么——一眼区分「驱动问题」还是「后端选错」。

## 2. 配置（主配置 + overlay，2026-10-07 起）

**主配置** `../v0.6/config/acceptance.json` 只维护跨机器不变的公共字段；
随机器变化的 `serial.port` 与 `scope.resource` **默认留空**，由 overlay 覆盖：

```
config/
├── acceptance.json           # 主配置（port/resource 留空）
├── acceptance.windows.json   # Windows overlay：port=COM3, resource=USB0::...
└── acceptance.linux.json     # Linux overlay：port=/dev/ttyUSB0, resource=""(自动枚举)
```

**切换方式**（环境变量 `FAN_CONFIG_PATH` 指向 overlay）：

```powershell
# Windows
$env:FAN_CONFIG_PATH = "D:\Task4\OmniTest\hardware\v0.6\config\acceptance.windows.json"
python entrypoints/check_deps.py
```

```bash
# Linux
export FAN_CONFIG_PATH=/opt/demo/omnitest/hardware/v0.6/config/acceptance.linux.json
python entrypoints/check_deps.py
```

**合并优先级**（后者覆盖前者，深合并）：主配置 < overlay < 精细环境变量。

**精细环境变量**（临时救急，优先级最高，不改文件）：

| 变量 | 作用 | 示例 |
|---|---|---|
| `FAN_CONFIG_PATH` | 指向 overlay 文件 | `.../acceptance.windows.json` |
| `FAN_SERIAL_PORT` | 直接覆盖串口号 | `COM3` / `/dev/ttyUSB0` |
| `FAN_SCOPE_RESOURCE` | 直接覆盖示波器资源名 | `USB0::6833::1230::...::INSTR` |
| `SCOPE_VISA_BACKEND` | VISA 后端 | `@py`（默认）/ `@ivi` |

> **overlay 只对「默认路径」生效**：显式传 `-ConfigPath` 时不叠加 overlay，
> 以保证 `run_scope.py` 的隔离测试（写临时配置再读）不被污染。

> **示波器资源名留空 = 自动枚举**：`ScopeDevice` 会按 USB-TMC 的
> **VID=0x1AB1（RIGOL）+ PID=0x04CE（DS1000Z）** 匹配候选，再用 `*IDN?` 验证身份。
> 因此 Linux 上无需写死资源名，换机器也不会因资源名变化而失败。

## 3. 运行

```bash
cd hardware/py

# ① 依赖自检（推荐先跑；默认读 v0.6/config/acceptance.json + overlay）
python entrypoints/check_deps.py

# ② 只跑风扇（约 40 秒，不碰示波器）
python entrypoints/run_fan.py -ConfigPath ../v0.6/config/acceptance.json

# ③ 只采示波器（不碰串口）
python entrypoints/run_scope.py -ConfigPath ../v0.6/config/acceptance.json

# ④ 联合实验（异步启动）
python entrypoints/start.py -ConfigPath ../v0.6/config/acceptance.json -RunId test_001
python entrypoints/stop.py -RunId test_001 -WaitSeconds 30
```

## 4. 跨平台差异

| 项 | Windows | Linux |
|---|---|---|
| 串口名 | `COM3`（overlay 覆盖） | `/dev/ttyUSB0`（overlay 覆盖） |
| 示波器驱动 | Zadig 切 WinUSB + pyusb | 内核自带 usbtmc，免驱动 |
| VISA 后端 | `@py`，偶发问题可切 `@ivi` | `@py`（默认，免配置） |
| 串口权限 | 无 | 加入 `dialout` 组 |
| 其余 | 完全相同 | 完全相同 |

> Linux 完整部署步骤见 `deploy/LINUX-CHECKLIST.md`。

## 5. 数据纪律

- 真实数据只来自真设备；失败原因原样透传（如 `Open scope VISA error ...`），不美化、不降级。
- 无设备时不伪造：如实报错。
- `capture` 缺测值（`current_a` / `rpm`）保持 `null` + `quality` 原因，不填 0。

## 6. 与原 PowerShell 版的关系

| 原文件 | Python 对应 |
|---|---|
| `src/FanTransport.cs` | `fan_serial.py` |
| `src/ScopeVisa.cs` | `scope_visa.py` |
| `src/ScopeCapture.psm1` | `scope_capture.py` |
| `src/Runtime.psm1` | `runtime.py` |
| `run-experiment.ps1` | `run_experiment.py` |
| `start/stop/run-fan/run-scope/check-dependencies.ps1` | `entrypoints/*.py` |

产物格式（`runs/<runId>/` 下 events.jsonl / summary.json / state.json / commands.csv /
scope-settings.json / CH{n}.csv / CH{n}_preamble.txt / screen.bmp / capture.json）与 PowerShell 版一致，
后端 `fan_executor.py` 与前端无需任何改动。
