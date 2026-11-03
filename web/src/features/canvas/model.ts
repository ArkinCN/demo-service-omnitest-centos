/* ===========================================================================
   C 区统一画板 · 数据模型。

   三件事在这里定死，画板本体（CanvasHost.tsx）与工具条（src/app/ToolRail.tsx）
   都从这里取，不各写一套：

   1. 十一类节点的分组与显示名。分组按《第三轮需求变更方案 v0.1》第 2.2 节的五类
      （被测对象 / 测量设备 / 激励与环境 / 过程与数据 / 服务与连接），每类 ≤5 项。
   2. 每条流程的默认版式（节点位置与连线）。场景包尚未下发版式，这里给的是初始值；
      人摆过之后按「场景包 × 流程」存 localStorage，下次进来还原。
   3. 物理连接边上的通道名一律取 src/data/bench.ts 的 channelLabel()，
      并挂 BENCH_CHANNEL_PENDING 的「待客户确认」——那套映射还没经客户书面确认。
   =========================================================================== */
import { CARD_LIB } from '../../data/cards'
import { channelLabel } from '../../data/bench'
import type {
  CanvasEdge,
  CanvasLayout,
  CanvasNode,
  CanvasNodeType,
  CardId,
  FlowId,
  ScenePackage,
} from '../../data/types'

/** 节点五类。类名同时是右侧工具条的组名口径。 */
export type CanvasNodeGroup =
  | '被测对象'
  | '测量设备'
  | '激励与环境'
  | '过程与数据'
  | '服务与连接'

export const CANVAS_GROUP_ORDER: CanvasNodeGroup[] = [
  '被测对象',
  '测量设备',
  '激励与环境',
  '过程与数据',
  '服务与连接',
]

export interface CanvasNodeMeta {
  /** 节点默认名，≤6 字 */
  label: string
  /** 卡头下的身份行，≤8 字 */
  sub: string
  group: CanvasNodeGroup
  /** 右上角标：走 MCP 的节点才有 */
  tag?: string
}

/** 十一类节点的元数据。类型枚举在 src/data/types.ts 的 CANVAS_NODE_TYPES。 */
export const CANVAS_NODE_META: Record<CanvasNodeType, CanvasNodeMeta> = {
  motor: { label: '被测对象', sub: '产品实物', group: '被测对象' },
  schematic: { label: '原理图', sub: '图纸资产', group: '被测对象' },
  scope: { label: '示波器', sub: '波形采集', group: '测量设备', tag: 'MCP' },
  bench: { label: '测试台架', sub: '台架实况', group: '测量设备', tag: 'MCP' },
  psu: { label: '程控电源', sub: '激励输出', group: '激励与环境' },
  workflow: { label: '工作流', sub: '测试编排', group: '过程与数据' },
  curve: { label: '时序曲线', sub: '实测数据', group: '过程与数据' },
  verdict: { label: '判定表', sub: '判据结论', group: '过程与数据' },
  'device-mcp': { label: '设备节点', sub: 'MCP 服务', group: '服务与连接', tag: 'MCP' },
  interlock: { label: '安全联锁', sub: '联锁状态', group: '服务与连接' },
  knowledge: { label: '知识依据', sub: '知识条目', group: '服务与连接' },
}

/** 节点的连接态。灰是未接入，绿是已接入，暗红是异常——三态与工具条描边同一口径。 */
export type CanvasLinkState = 'online' | 'offline' | 'fault'

export const LINK_STATE_TEXT: Record<CanvasLinkState, string> = {
  online: '已接入',
  offline: '未接入',
  fault: '异常',
}

/* ------------------------------------------------------------------ 默认版式 */

interface Seed {
  type: CanvasNodeType
  x: number
  y: number
  card?: CardId
  /** 覆写显示名；缺省用卡名或 CANVAS_NODE_META.label */
  label?: string
}

const NODE_W = 240
const NODE_H = 152

/**
 * 每条流程的默认版式。
 *
 * 骨架共用四个节点：程控电[源] → 被测对象 → 示波器，加一台设备节点收数据；
 * 各流程再按自己的卡片补 2 至 3 个业务节点。节点总数控制在 7 个以内，
 * 对应「任何一组内部并列条目不超过 5 项」的平铺规则。
 */
const SEEDS: Record<FlowId, Seed[]> = {
  init: [
    { type: 'psu', x: 0, y: 30 },
    { type: 'motor', x: 380, y: 30, card: 'product-view' },
    { type: 'scope', x: 760, y: 30 },
    { type: 'schematic', x: 0, y: 300, card: 'schematic' },
    { type: 'bench', x: 380, y: 300, card: 'bench-live' },
    { type: 'device-mcp', x: 760, y: 300 },
    { type: 'interlock', x: 1140, y: 165, card: 'interlock' },
  ],
  req: [
    { type: 'motor', x: 0, y: 30 },
    { type: 'workflow', x: 380, y: 30, card: 'workflow' },
    { type: 'verdict', x: 760, y: 30, card: 'verdict' },
    { type: 'bench', x: 0, y: 300 },
    { type: 'device-mcp', x: 380, y: 300 },
    { type: 'knowledge', x: 760, y: 300, card: 'evidence' },
  ],
  run: [
    { type: 'psu', x: 0, y: 30 },
    { type: 'motor', x: 380, y: 30 },
    { type: 'scope', x: 760, y: 30 },
    { type: 'curve', x: 1140, y: 30, card: 'timeseries' },
    { type: 'interlock', x: 0, y: 300, card: 'interlock' },
    { type: 'bench', x: 380, y: 300 },
    { type: 'device-mcp', x: 760, y: 300 },
    { type: 'verdict', x: 1140, y: 300, card: 'verdict' },
  ],
  tune: [
    { type: 'motor', x: 0, y: 30 },
    { type: 'scope', x: 380, y: 30 },
    { type: 'curve', x: 760, y: 30, card: 'timeseries' },
    { type: 'knowledge', x: 0, y: 300, card: 'experience' },
    { type: 'device-mcp', x: 380, y: 300 },
    { type: 'verdict', x: 760, y: 300, card: 'verdict' },
  ],
  report: [
    { type: 'curve', x: 0, y: 30, card: 'timeseries' },
    { type: 'verdict', x: 380, y: 30, card: 'verdict' },
    { type: 'knowledge', x: 760, y: 30, card: 'evidence' },
    { type: 'motor', x: 190, y: 300 },
    { type: 'device-mcp', x: 570, y: 300 },
  ],
}

/** 物理连接边：`[起, 止, 信号名]`，信号名走 channelLabel() 换成通道号 */
const PHYSICAL: Record<FlowId, [CanvasNodeType, CanvasNodeType, string?][]> = {
  init: [
    ['psu', 'motor'],
    ['motor', 'scope', 'FG1'],
    ['bench', 'motor', 'PWM1'],
  ],
  req: [['motor', 'bench', 'FG1']],
  run: [
    ['psu', 'motor'],
    ['motor', 'scope', 'FG1'],
    ['bench', 'motor', 'PWM1'],
  ],
  tune: [['motor', 'scope', 'FG2']],
  report: [],
}

/** 数据流边：`[起, 止]` */
const DATA: Record<FlowId, [CanvasNodeType, CanvasNodeType][]> = {
  init: [
    ['schematic', 'motor'],
    ['scope', 'device-mcp'],
    ['bench', 'device-mcp'],
    ['interlock', 'bench'],
  ],
  req: [
    ['workflow', 'verdict'],
    ['knowledge', 'verdict'],
    ['bench', 'device-mcp'],
    ['workflow', 'device-mcp'],
  ],
  run: [
    ['scope', 'curve'],
    ['curve', 'verdict'],
    ['bench', 'device-mcp'],
    ['interlock', 'motor'],
  ],
  tune: [
    ['scope', 'curve'],
    ['curve', 'verdict'],
    ['knowledge', 'verdict'],
    ['device-mcp', 'curve'],
  ],
  report: [
    ['curve', 'verdict'],
    ['knowledge', 'verdict'],
    ['device-mcp', 'curve'],
  ],
}

/** 节点显示名：卡片实例的覆写名优先，其次卡名，最后类型默认名 */
function labelOf(seed: Seed, scene: ScenePackage, flow: FlowId): string {
  if (seed.label) return seed.label
  if (seed.card) {
    const inst = scene.flows[flow].cards.find((c) => c.id === seed.card)
    return inst?.title ?? CARD_LIB[seed.card]?.title ?? CANVAS_NODE_META[seed.type].label
  }
  return CANVAS_NODE_META[seed.type].label
}

/** 物理连接边的标注：通道号加一句「待客户确认」，口径见 src/data/bench.ts */
export function edgeChannel(signal?: string): { channel?: string; text?: string } {
  if (!signal) return {}
  const ch = channelLabel(signal)
  return ch ? { channel: ch, text: `${signal} · ${ch}` } : { text: signal }
}

/** 某条流程的默认版式。场景包暂未下发版式，这一份即初始值。 */
export function defaultLayout(flow: FlowId, scene: ScenePackage): CanvasLayout {
  const seeds = SEEDS[flow]
  const nodes: CanvasNode[] = seeds.map((s) => ({
    id: s.card ? `card-${s.card}` : `type-${s.type}`,
    type: s.type,
    label: labelOf(s, scene, flow),
    x: s.x,
    y: s.y,
    w: NODE_W,
    h: NODE_H,
    card: s.card,
  }))
  const byType = new Map(seeds.map((s, i) => [s.type, nodes[i].id]))

  const edges: CanvasEdge[] = []
  for (const [from, to, signal] of PHYSICAL[flow]) {
    const a = byType.get(from)
    const b = byType.get(to)
    if (!a || !b) continue
    const { channel, text } = edgeChannel(signal)
    edges.push({ id: `p-${a}-${b}`, from: a, to: b, kind: 'physical', channel, label: text })
  }
  for (const [from, to] of DATA[flow]) {
    const a = byType.get(from)
    const b = byType.get(to)
    if (!a || !b) continue
    edges.push({ id: `d-${a}-${b}`, from: a, to: b, kind: 'data' })
  }
  return { nodes, edges }
}

/** 新建节点的默认尺寸，工具条拖入落点时用 */
export const CANVAS_NODE_SIZE = { w: NODE_W, h: NODE_H }

/* -------------------------------------------------------------- 版式持久化 */

const LS_PREFIX = 'omnitest.canvas.v1'

/** 存储键含场景包与流程：换包或换流程各记各的版式 */
export const layoutKey = (sceneId: string, flow: FlowId) => `${LS_PREFIX}:${sceneId}:${flow}`

export function loadLayout(sceneId: string, flow: FlowId): CanvasLayout | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(layoutKey(sceneId, flow))
    if (!raw) return null
    const parsed = JSON.parse(raw) as CanvasLayout
    if (!Array.isArray(parsed?.nodes) || !Array.isArray(parsed?.edges)) return null
    return parsed
  } catch {
    return null
  }
}

export function saveLayout(sceneId: string, flow: FlowId, layout: CanvasLayout) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(layoutKey(sceneId, flow), JSON.stringify(layout))
  } catch {
    /* 隐私模式或配额用尽：版式记不住不影响画板本身 */
  }
}

export function clearLayout(sceneId: string, flow: FlowId) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.removeItem(layoutKey(sceneId, flow))
  } catch {
    /* 同上 */
  }
}
