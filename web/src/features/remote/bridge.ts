/* ===========================================================================
   设备桥 HTTP 客户端。

   桥是 [源] spike-device-mcp/bridge.py（FastAPI，默认 127.0.0.1:8031），
   同进程持有 device-bench MCP server，后面经 paramiko SSH 连峰岹（Fortior）
   电机测试 Windows 工控机 SK-20251218QPBB。页面这一侧只认 HTTP + JSON，
   不知道 SSH 的存在。

   与 ./api.ts 的分工：
     · ./api.ts   → SSH 网关（c/components/webssh，默认 8022），只剩交互式终端一个用途；
     · ./bridge.ts → 设备桥（8031），画布设备节点状态、分层工具菜单、红线凭据。
   两个后端各有独立的地址与 token，全部经 .env 配置，清单见 .env.example。

   两级鉴权（2026-09-20 起）。这里只拿得到其中一级：
     · VITE_BRIDGE_TOKEN → x-bridge-token，**调用票**。它随构建产物进浏览器包，
       按公开处理。持有它能做的事到"让桥签发一张 pending 凭据"为止。
     · 批准 PIN → x-approver-pin，**批准权**。本文件里没有它，也不许有：
       它不是环境变量，由人在确认卡上现场输入，作为参数逐次传进 approveConfirmation，
       用完即弃，不进 localStorage、不进模块级变量、不进构建产物。

   红线纪律：本文件**不导出任何能自行批准的组合函数**。callTool 不带 token 时
   桥一定拒绝执行并回一张 pending 凭据；approveConfirmation 只能由人的点击调用
   （唯一调用点是 src/state/useAppStore.ts 的 approveRedline）。
   依据：[源] spike-device-mcp/README.md 第 3 节、08a-开发接口契约-v1.0.md 第 3 节。
   =========================================================================== */
import { useEffect, useState } from 'react'

export const BRIDGE_URL: string = import.meta.env.VITE_DEVICE_BRIDGE_URL ?? 'http://127.0.0.1:8031'

/* ---------------------------------------------------------------- 调用票的来源

   本地开发读 .env 的 VITE_BRIDGE_TOKEN，图的是起了 vite 就能用。
   构建产物**不内嵌**它：`import.meta.env.DEV` 在 build 时被替换成 false，
   整条分支连同那个字符串一起被消掉，所以 dist 里搜不到桥的 token
   （07i 独立核验 P1：此前它明文躺在 dist/assets/*.js 里）。
   交付出去的页面由操作员现场给票：调一次 setBridgeToken()，存本机 localStorage。

   注意这只解决"票不随产物外流"，不改变票本身的定位——它仍是调用票不是批准权，
   批准另要桥的 BRIDGE_APPROVER_PIN，那一项任何时候都不落盘到浏览器。 */

const DEV_TOKEN: string = import.meta.env.DEV ? (import.meta.env.VITE_BRIDGE_TOKEN ?? '') : ''
const TOKEN_LS_KEY = 'omnitest.bridge.token'

function storedToken(): string {
  try {
    return window.localStorage.getItem(TOKEN_LS_KEY) ?? ''
  } catch {
    return ''
  }
}

const bridgeToken = (): string => DEV_TOKEN || storedToken()

/** 在交付出去的页面上现场给调用票。传空串即清除。 */
export function setBridgeToken(v: string): void {
  try {
    if (v.trim()) window.localStorage.setItem(TOKEN_LS_KEY, v.trim())
    else window.localStorage.removeItem(TOKEN_LS_KEY)
  } catch {
    /* 隐私模式下写不了，就这一次会话内用不上票，按未连通处理 */
  }
}

// 构建产物里没有票，得有个地方现场输入。挂一个全局函数是最小做法，
// 用法写在 README 第 10.5 节，也写进下面 explain() 的那句提示里。
if (typeof window !== 'undefined') {
  ;(window as unknown as Record<string, unknown>).omnitestSetBridgeToken = (v: string) => {
    setBridgeToken(v)
    window.location.reload()
  }
}

/** 没配 token 时桥一律回 401。先在前端讲清缺什么，不让节点只显示一句「未连通」。 */
export const bridgeTokenMissing = () => bridgeToken().trim() === ''

const headers = (): HeadersInit => ({
  'content-type': 'application/json',
  'x-bridge-token': bridgeToken(),
})

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return (await res.json()) as T
}

/* ------------------------------------------------------------------ 数据形状 */

/** 桥的三层工具分组，层名取自每个工具的 meta.group */
export type BridgeLayer = 'connection' | 'observation' | 'action'

export const BRIDGE_LAYER_TITLE: Record<BridgeLayer, string> = {
  connection: '连接层',
  observation: '观测层',
  action: '动作层',
}

export interface BridgeTool {
  name: string
  title?: string
  description?: string
  layer?: string
  /** 红线动作。点下去只会拿回一张待确认凭据，不会直接执行。 */
  guarded: boolean
  human_gate?: string | null
  risk?: string | null
  input_schema?: Record<string, unknown>
}

export interface BridgeStatus {
  /** unknown 没连过 / live 真连上台架 / mock 连不上，返回合成数据 */
  mode: 'unknown' | 'live' | 'mock'
  connected: boolean
  hostname?: string | null
  uptime_s?: number
  last_error?: string | null
  pending_confirmations?: number
  pending_tokens?: string[]
  mock_warning?: string
  /** 桥是否要求批准 PIN。两级鉴权上线后恒为 true，留字段是为了对旧桥能降级提示。 */
  approve_requires_pin?: boolean
  approver_pin_gate?: { locked: boolean; retry_after_s: number; fails: number; max_fails: number }
}

export interface BridgeDevice {
  id: string
  name: string
  model: string
  kind: string
  transport?: string
  backend?: string
  target?: string
  status: BridgeStatus
  tool_groups: Partial<Record<BridgeLayer, BridgeTool[]>>
}

export interface BridgeDevices {
  devices: BridgeDevice[]
  guarded_actions?: Record<string, string>
}

/**
 * 一张人工确认凭据。pending 只能由人批到 approved，模型面上没有这条路。
 * 字段名照桥的实际返回：凭据本身以 confirm_token 为标识，不叫 token。
 */
export interface Confirmation {
  confirm_token: string
  tool: string
  state: 'pending' | 'approved' | 'consumed' | 'rejected' | 'expired'
  prompt?: string
  /** 批准时绑定的那一组参数，桥回的是对象不是字符串 */
  args_preview?: Record<string, unknown>
  seconds_left?: number
  approved_by?: string | null
  /** 放行渠道，桥写的。human_pin 表示现场有人敲过批准 PIN。 */
  approve_channel?: string | null
  rejected_reason?: string | null
}

/**
 * 调一个工具的返回。红线动作没带 token 时 executed 为 false，
 * 凭据的各字段**平铺在同一层**（status / confirm_token / prompt / args_preview / …），
 * 不是包在 confirmation 里——这一点踩过一次，接口实测见 README 第 3 节。
 */
export type ToolCallResult = Partial<Confirmation> & {
  status?: string
  executed?: boolean
  mode?: string
  mock_warning?: string
  reason?: string
  how_to_proceed?: string
  message?: string
  [k: string]: unknown
}

/** 参数预览转成一行人话，摆在确认卡上 */
export const previewArgs = (a?: Record<string, unknown>): string =>
  a && Object.keys(a).length
    ? Object.entries(a)
        .map(([k, v]) => `${k}=${String(v)}`)
        .join(' · ')
    : ''

/* -------------------------------------------------------------------- 接口 */

export const bridgeHealth = () =>
  fetch(`${BRIDGE_URL}/health`).then(json<{ ok: boolean; server?: string }>)

export const listBridgeDevices = () =>
  fetch(`${BRIDGE_URL}/devices`, { headers: headers() }).then(json<BridgeDevices>)

export const bridgeDeviceStatus = (id: string) =>
  fetch(`${BRIDGE_URL}/devices/${encodeURIComponent(id)}/status`, { headers: headers() }).then(
    json<BridgeStatus & { pending?: Confirmation[] }>,
  )

/**
 * 调一个 MCP 工具。红线动作**不要**带 confirm_token 调第一次——桥会拒绝执行并
 * 签发一张 pending 凭据，界面据此弹确认卡。这是红线成立的根据，前端骗不过去。
 */
export const callBridgeTool = (deviceId: string, name: string, args: Record<string, unknown> = {}) =>
  fetch(`${BRIDGE_URL}/devices/${encodeURIComponent(deviceId)}/tools/${encodeURIComponent(name)}`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ arguments: args }),
  }).then(json<ToolCallResult>)

/**
 * 人工批准一张凭据。唯一合法调用点是 useAppStore 的 approveRedline，
 * 而 approveRedline 只由确认卡上的「确认」按钮触发。副驾不得调用本函数。
 *
 * pin 是人在确认卡上现场输入的批准 PIN，对应桥 .env 的 BRIDGE_APPROVER_PIN。
 * 它只以实参形式流过这一次调用：不缓存、不落 localStorage、不写进任何模块级变量，
 * 因而不会出现在构建产物里。PIN 缺失或不对，桥回 403，凭据保持 pending。
 */
export const approveConfirmation = (token: string, operator: string, pin: string, note?: string) =>
  fetch(`${BRIDGE_URL}/confirmations/${encodeURIComponent(token)}/approve`, {
    method: 'POST',
    headers: { ...headers(), 'x-approver-pin': pin },
    body: JSON.stringify({ operator, note }),
  }).then(json<Confirmation>)

export const rejectConfirmation = (token: string, reason: string) =>
  fetch(`${BRIDGE_URL}/confirmations/${encodeURIComponent(token)}/reject`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ reason }),
  }).then(json<Confirmation>)

/* ----------------------------------------------------------------- 自动化放行 */

// 自动化放行 token：与 APPROVER_PIN 同级秘密，只存在于桥 .env 与前端 dev 环境，
// 绝不进构建产物（import.meta.env.DEV 在 build 时被替换成 false，整段被消除）。
const DEV_AUTOMATION_TOKEN: string = import.meta.env.DEV ? (import.meta.env.VITE_AUTOMATION_TOKEN ?? '') : ''
const AUTOMATION_TOKEN_LS_KEY = 'omnitest.bridge.automation-token'

const automationToken = (): string => {
  try {
    return DEV_AUTOMATION_TOKEN || (window.localStorage.getItem(AUTOMATION_TOKEN_LS_KEY) ?? '')
  } catch {
    return ''
  }
}

/**
 * 一键自动化测试流程的自动放行（2026-09-30 加）。
 *
 * 对应桥的 POST /confirmations/{token}/auto-approve，带 x-automation-token 头。
 * 这是「自动化的放行权」，与人工批准 PIN（approveConfirmation）是两条独立通道：
 * 前者记 approve_channel="automation"，后者记 "human_pin"，留痕可审计。
 * 未配置自动化 token 时桥回 503，这里如实抛出，由编排器记为「环境检查失败」。
 */
export const autoApproveConfirmation = (token: string, operator: string) =>
  fetch(`${BRIDGE_URL}/confirmations/${encodeURIComponent(token)}/auto-approve`, {
    method: 'POST',
    headers: { ...headers(), 'x-automation-token': automationToken() },
    body: JSON.stringify({ operator, note: 'automation-flow' }),
  }).then(json<Confirmation>)

/* -------------------------------------------------------------------- 订阅 */

export interface BridgeState {
  /** loading 首次取数中 / online 桥可达 / offline 桥不可达或缺配置 */
  link: 'loading' | 'online' | 'offline'
  device: BridgeDevice | null
  /** 桥不可达时讲清缺什么，不只报一句「未连通」 */
  reason: string | null
  toolCount: number
}

const EMPTY: BridgeState = { link: 'loading', device: null, reason: null, toolCount: 0 }

/** 取数失败时把技术原因翻成一句人话，指名缺哪个配置项 */
function explain(e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e)
  if (bridgeTokenMissing())
    return import.meta.env.DEV
      ? `缺配置 VITE_BRIDGE_TOKEN（与桥的 .env 里 BRIDGE_TOKEN 同值），改完要重启 vite`
      : `本页是构建产物，不内嵌设备桥调用票。在浏览器控制台执行 omnitestSetBridgeToken('<桥的 BRIDGE_TOKEN>') 现场给票；批准红线动作另需桥的批准 PIN，那一项不存浏览器`
  if (/^401/.test(msg)) return `桥拒绝鉴权：VITE_BRIDGE_TOKEN 与桥的 BRIDGE_TOKEN 不一致`
  if (/Failed to fetch|NetworkError|load failed/i.test(msg))
    return `设备桥 ${BRIDGE_URL} 不可达：先起 [源] spike-device-mcp/run-bridge.sh，或改配 VITE_DEVICE_BRIDGE_URL`
  return `设备桥返回异常：${msg}`
}

const countTools = (d: BridgeDevice | null) =>
  d ? Object.values(d.tool_groups ?? {}).reduce((n, g) => n + (g?.length ?? 0), 0) : 0

/**
 * 订阅一台设备。首次拉 GET /devices 取到元信息与分层工具菜单，
 * 之后每 5 秒轮一次 GET /devices/{id}/status 只刷徽章（README 第 5 节的建议口径）。
 */
export function useBridgeDevice(id = 'bench'): BridgeState {
  const [s, setS] = useState<BridgeState>(EMPTY)

  useEffect(() => {
    let alive = true
    if (bridgeTokenMissing()) {
      // 缺 token 是配置问题不是网络问题，不必去打一次必被 401 的请求；
      // 用微任务推一格再置态，避免在 effect 里同步 setState 触发一次级联渲染。
      queueMicrotask(() => alive && setS({ link: 'offline', device: null, reason: explain(new Error('no token')), toolCount: 0 }))
      return () => {
        alive = false
      }
    }
    const pull = () =>
      listBridgeDevices()
        .then((r) => {
          if (!alive) return
          const device = r.devices.find((d) => d.id === id) ?? r.devices[0] ?? null
          setS({
            link: device ? 'online' : 'offline',
            device,
            reason: device ? null : `设备桥在线但没有登记 id=${id} 的设备`,
            toolCount: countTools(device),
          })
        })
        .catch((e: unknown) => {
          if (alive) setS({ link: 'offline', device: null, reason: explain(e), toolCount: 0 })
        })
    pull()
    const poll = window.setInterval(() => {
      if (!alive) return
      bridgeDeviceStatus(id)
        .then((st) => {
          if (!alive) return
          setS((prev) =>
            prev.device
              ? { ...prev, link: 'online', reason: null, device: { ...prev.device, status: st } }
              : prev,
          )
        })
        .catch(() => pull())
    }, 5000)
    return () => {
      alive = false
      window.clearInterval(poll)
    }
  }, [id])

  return s
}
