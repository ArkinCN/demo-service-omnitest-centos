# 配置说明：主配置 + overlay（换机器 / 换设备必读）

本目录采用 **「主配置 + overlay」** 两段式（2026-10-07 起）：

```
config/
├── acceptance.json           # 主配置：只放跨机器不变的公共字段
├── acceptance.windows.json   # Windows overlay：只放 port / resource
├── acceptance.linux.json     # Linux overlay：只放 port / resource
├── experiment.json           # 样例/回退配置（非主链路权威）
└── verification.json         # 验收用例配置（scope.enabled=false）
```

> **权威配置是 `acceptance.json` + overlay**（后端 `fan_executor.py` 默认即指向 `acceptance.json`）。
> `experiment.json` / `verification.json` 为样例/验收用途，非主链路。

## 1. 主配置留空的字段（由 overlay 覆盖）

`acceptance.json` 里下面两项**刻意留空**，运行时由 overlay 补齐：

```jsonc
{
  "serial": { "port": "" },       // 留空 → 由 overlay 或 FAN_SERIAL_PORT 补齐
  "scope":  { "resource": "" }    // 留空 → 运行时按 VID/PID 自动枚举
}
```

**为什么留空**：主配置要同时适配 Windows 和 Linux，写死 `COM3` 会带 Windows 痕迹；
写死资源名会在换机器/换后端时炸（已在 Windows 上踩过）。

## 2. overlay 只写随机器变化的字段

```jsonc
// acceptance.windows.json
{ "serial": { "port": "COM3" },
  "scope":  { "resource": "USB0::6833::1230::DS1ZC271600575::0::INSTR" } }

// acceptance.linux.json
{ "serial": { "port": "/dev/ttyUSB0" },
  "scope":  { "resource": "" } }   // Linux 留空 → 自动枚举
```

**深合并**：overlay 里的字段覆盖主配置同名字段，其它字段沿用主配置。换机器只改 overlay，不动主配置。

## 3. 切换方式

```powershell
# Windows
$env:FAN_CONFIG_PATH = "D:\Task4\OmniTest\hardware\v0.6\config\acceptance.windows.json"
python hardware\py\entrypoints\check_deps.py
```

```bash
# Linux
export FAN_CONFIG_PATH=/opt/demo/omnitest/hardware/v0.6/config/acceptance.linux.json
python hardware/py/entrypoints/check_deps.py
```

**优先级**：主配置 < overlay < 精细环境变量（`FAN_SERIAL_PORT` / `FAN_SCOPE_RESOURCE`）。

> overlay 只对「默认路径」生效；显式传 `-ConfigPath` 时不叠加（保护 `run_scope.py` 隔离测试）。

## 4. 换机器 / 换设备必改项

| # | 改什么 | 在哪改 | 怎么查 |
|---|---|---|---|
| 1 | 串口号 | overlay 的 `serial.port` | `check_deps.py` 的 `availableSerialPorts`；Windows 设备管理器 / Linux `ls /dev/ttyUSB*` |
| 2 | 示波器资源名 | overlay 的 `scope.resource`（**建议留空自动枚举**） | `check_deps.py` 的 `visaResources` |
| 3 | 示波器身份 | 主配置 `scope.expectedIdentity` | 示波器 `*IDN?` 或铭牌序列号 |
| 4 | 驱动（仅 Windows） | — | CH340 驱动 + Zadig 切 WinUSB（Linux 免） |

## 5. 快速自检

```bash
cd hardware/py
python entrypoints/check_deps.py     # ready 应为 true，visaResources 应有 USB0::
python entrypoints/run_fan.py        # 风扇真转（四档 ACK）
python entrypoints/run_scope.py      # 示波器出真实波形
```

> 完整 Linux 部署步骤见 `../deploy/LINUX-CHECKLIST.md`。
