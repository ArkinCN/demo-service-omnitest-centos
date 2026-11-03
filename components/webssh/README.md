# webssh — 浏览器里打开单机设备

从网页 SSH 到峰岹台架 Windows 工控机（主机名 `SK-20251218QPBB`，`administrator@172.25.5.166:5011`），
在浏览器里跑命令、按预置按钮、把台架机上的示波器图像拉回页面显示。
为"远程桌面 / 截图回传"预留了独立的 HTTP 接口。

## 架构

```
┌───────────────┐   WebSocket 帧    ┌──────────────────┐   SSH (ssh2)   ┌────────────────────┐
│  浏览器        │  {input|resize}   │  网关 gateway/    │  shell 通道     │ 台架 Windows 工控机 │
│  React +      │ ────────────────► │  Node + express   │ ─────────────► │ SK-20251218QPBB    │
│  xterm.js     │ ◄──────────────── │  + ws + ssh2      │ ◄───────────── │ Session 0（服务）   │
│               │  {data|status}    │                   │   stdout        │                    │
│  RemoteTerminal                   │  私钥只在这一侧    │                 │  C:\fc_pull\*.bmp  │
│  RemoteDeviceCard                 │  token 鉴权        │  exec shot.ps1  │  ScopeCtl /        │
│               │  POST /remote/    │  会话日志 logs/    │ ─────────────► │  DeepCapture       │
│               │   screenshot      │                   │ ◄───────────── │                    │
└───────────────┘  ← base64 图像    └──────────────────┘   base64 图像    └────────────────────┘
```

三层职责划清：浏览器只做显示与键盘，**不持有任何凭据**；网关持有私钥路径并做鉴权、转发、留痕；
台架机侧只多放一个 `shot.ps1`（由网关每次现场下发，不常驻）。

## 选型理由

| 方案 | 结论 | 依据 |
|---|---|---|
| **Node `ssh2` + `ws`（采用）** | 选它 | `ssh2@1.17.0`（2025-08 更新）是 Node 生态事实标准的纯 JS SSH 实现，`shell()` 直接给出 PTY 通道；`ws@8.21.3`（2026-08）活跃。关键是**与前端同一套 Node 工具链**，一次 `npm install`、一个 `npm run dev:all` 起全栈，不引入第二个运行时 |
| Python `asyncssh` + `websockets` | 不选 | `asyncssh` 最新 2.24.0，库本身很好，但要为这个小网关多维护一套 Python 虚拟环境与依赖，收益不抵成本 |
| `ttyd` / `wetty` / `sshx` | 不选 | 它们是**整页终端应用**，不是可嵌入的 React 组件。本任务要的是 `<RemoteTerminal>` 这样能塞进设备面板、能被预置按钮和截图卡围绕的部件；套 iframe 会让状态徽章、预置命令、`onOutput` 回调全都拿不到 |

前端终端用 `@xterm/xterm@6.0.0` + `@xterm/addon-fit@0.11.0`（均 2026-08 更新），是 VS Code 同款终端渲染器。
未引入 `node-pty`：网关不需要在本机开伪终端，PTY 由远端 SSH 服务提供。

## 目录

```
webssh/
├── gateway/
│   ├── server.js        网关：WS↔SSH 转发、/remote/screenshot、/devices、/probe
│   ├── devices.json     设备清单（台架机、RIGOL 示波器、程控电源）与预置命令
│   ├── shot.ps1         远程截图脚本，网关以 base64 EncodedCommand 下发
│   ├── smoke-ws.mjs     不经浏览器的冒烟测试
│   └── logs/            每会话一个日志文件
├── src/features/remote/
│   ├── RemoteTerminal.tsx   终端组件 + ConnBadge 状态徽章
│   ├── RemoteDeviceCard.tsx 设备卡 + ShotModal 放大遮罩
│   ├── api.ts / types.ts    网关客户端与共享类型
│   └── remote.css           色板与样式
├── src/App.tsx          Demo 页：左设备列表 / 中终端 / 右截图卡
└── shots/               实机演示截图与 Playwright 采集脚本
```

## 起步

```bash
cd c/components/webssh
npm install
cp .env.example .env        # 填 GATEWAY_TOKEN 与私钥路径，见下
npm run dev:all             # 同时起网关 :8022 与前端 :5173
```

`.env` 三项必填：

```ini
GATEWAY_TOKEN=<一串长随机串>            # 用 openssl rand -hex 16 生成
FORTIOR_WIN_KEY=[源] .ssh/fortior_win   # 私钥【文件路径】
VITE_GATEWAY_TOKEN=<与 GATEWAY_TOKEN 相同>
```

`npm run build` 出静态产物；网关需单独常驻（`npm run gateway`）。

## 安全说明

- **私钥不进代码、不进浏览器、不进环境变量本体**。`devices.json` 里每台设备写的是 `keyRef`，
  值是一个**环境变量名**；该环境变量存的是私钥**文件路径**。网关按需读盘，前端只看得到 `keyRef` 这个名字。
- **无 token 不启动**。`GATEWAY_TOKEN` 未设置时网关直接退出，堵死"忘了配就裸奔"的路径。
  HTTP 走 `x-gateway-token` 头，WebSocket 走 query 参数（浏览器 WS API 不支持自定义头）。
- **会话全程留痕**。`gateway/logs/<日期>_<设备>_<会话号>.log` 逐条记录 `in`（键入）、`out`（回显）、
  `ssh` / `ws` 生命周期事件。
- **当前边界**：token 是单一共享密钥，比较未做常数时间；网关默认监听所有网卡且是明文 http/ws。
  只适合内网或本机使用。要对外暴露，需要补三件事：放到 TLS 反向代理之后（wss）、
  换成按人签发的短期凭据、给 `/remote/screenshot` 之类端点加频率限制。
- **命令未做白名单**。终端是全权 shell，能连上就等于拿到 `administrator` 权限。设备清单的
  `presets` 只是快捷方式，不构成限制。若要给非运维人员用，应在网关侧加命令白名单。

## 远程截图的实际行为

台架机的 SSH 服务跑在 **Session 0**，桌面 GUI 在 Session 1，两者会话隔离。
`shot.ps1` 因此分两步：先试 `Graphics.CopyFromScreen` 抓 `VirtualScreen`，并抽样 9 个像素做全黑判定；
判定为空（Session 0 的典型结果）就回退到 `C:\fc_pull` 下按修改时间最新的一张 `bmp/png/jpg`。
返回体里的 `mode` 字段如实标出这张图的来源，前端卡片直接把它显示在缩略图下方——
**不伪装成实时截屏**。

实测走的是回退路径，拿回 `C:\fc_pull\run_screen.bmp`（1,152,054 字节，RIGOL 示波器界面）。
要拿到真实时桌面，需要在用户会话（Session 1）里跑一个常驻的截图代理，由计划任务以
"仅在用户登录时运行 + 最高权限"启动——这条路本工程留了接口没有实现。

## 接口清单

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/health` | 无 | 存活探测，`{ok,ts}` |
| GET | `/devices` | token | 设备清单（含预置命令），已剥离凭据 |
| GET | `/probe/:id` | token | 对该设备跑一条 `hostname` 探活，`{online,hostname}` |
| POST | `/remote/screenshot` | token | 体 `{deviceId}`；回 `{deviceId,mode,takenAt,dataUrl}` |
| WS | `/ws?device=&token=` | token | 交互式 shell |

WebSocket 帧格式：

```jsonc
// 浏览器 → 网关
{ "type": "input",  "data": "hostname\r" }
{ "type": "resize", "cols": 120, "rows": 30 }
// 网关 → 浏览器
{ "type": "data",   "data": "SK-20251218QPBB\r\n" }
{ "type": "status", "state": "connecting|connected|closed|error", "detail": "..." }
```

## 集成到别的页面

```tsx
import { RemoteTerminal, RemoteDeviceCard, listDevices } from './features/remote';

<RemoteTerminal
  deviceId="bench"
  target={{ host: '172.25.5.166', port: 5011, user: 'administrator', keyRef: 'FORTIOR_WIN_KEY' }}
  title="峰岹台架工控机"
  presets={[{ label: '列设备', cmd: 'powershell -NoProfile -Command "Get-PnpDevice -Status OK"' }]}
  onOutput={(chunk) => parseFgFrequency(chunk)}   // 每段远端输出回调一次，可接判定逻辑
  onStateChange={(s) => setBadge(s)}
/>
```

接一台新设备只需在 `gateway/devices.json` 加一条：直连设备给 `host/port/user/keyRef`；
示波器、电源这类经工控机中转的仪器给 `via: "bench"`，网关会自动解析到宿主机的连接参数。
组件样式全部走 `.remote-root` 下的 CSS 变量（主色 `#2E5E45`、强调 `#A6353A`、浅底 `#EAF2EC`、背景白），
覆盖这些变量即可换色，不必改组件。

## 已知坑

- **FitAddon 与 flex 布局会打架**。终端容器若写 `flex: 1`，拟合改变行数 → 容器变高 → `ResizeObserver`
  再触发拟合，来回振荡，元素永远不"稳定"（Playwright 点击会直接超时）。容器高度必须用视口单位钉死。
- **控制台是 GBK**。走 PowerShell 时务必 `[Console]::OutputEncoding = UTF8` 且
  `$ProgressPreference = 'SilentlyContinue'`，否则中文乱码并混入 CLIXML 噪声。`shot.ps1` 已内置。
- **中文路径**。台架机上带中文或空格的路径，`scp` 直传易失败；惯例是先落 `C:\fc_pull\`，再用
  PowerShell `Copy-Item` 搬到目标位置。
