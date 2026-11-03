/**
 * 画布数据模型 —— 建议原样搬进场景包 JSON（scene.flows[flow].canvas）。
 * 节点按"六类"分，类型决定外观（图标、副标题、连接点语义），实例只带业务字段。
 */
import {
  Fan, Cpu, Server, Activity, Workflow, Database,
  type LucideIcon,
} from 'lucide-react'

export type NodeKind =
  | 'dut'        // 被测对象（电机）
  | 'board'      // 驱动板（芯片）
  | 'bench'      // 测试台架（MCP·SSH）
  | 'scope'      // 示波器（MCP）
  | 'workflow'   // 工作流
  | 'datasource' // 数据源

export type LinkState = 'online' | 'warn' | 'fault' | 'offline'

export interface KindMeta {
  label: string
  /** 卡头副标题：这一类在系统里的身份 */
  sub: string
  icon: LucideIcon
  /** 右上角标签：MCP 节点才有 */
  tag?: string
}

export const KIND: Record<NodeKind, KindMeta> = {
  dut:        { label: '被测对象', sub: '直流无刷电机', icon: Fan },
  board:      { label: '驱动板',   sub: '电机驱动芯片', icon: Cpu },
  bench:      { label: '测试台架', sub: '台架控制',     icon: Server,   tag: 'MCP' },
  scope:      { label: '示波器',   sub: '波形采集',     icon: Activity, tag: 'MCP' },
  workflow:   { label: '工作流',   sub: '测试编排',     icon: Workflow },
  datasource: { label: '数据源',   sub: '知识库 / 数据集', icon: Database },
}

export interface CanvasNodeData extends Record<string, unknown> {
  kind: NodeKind
  /** 实例名，覆盖 KIND.label */
  name: string
  /** 连接状态圆点；MCP 节点显示后台链路（SSH）与地址 */
  state: LinkState
  /** 卡底那行说明：MCP 节点写 "SSH · 172.25.5.166"，其余写业务口径 */
  channel?: string
  /** 卡身 2~3 行键值，超过就折叠（不平铺） */
  facts?: [string, string][]
}

export interface CanvasNodeJSON extends CanvasNodeData {
  id: string
  x: number
  y: number
}

/** 连线两类：物理接线（实线）/ 数据链路（虚线） */
export type EdgeKind = 'physical' | 'data'
export interface CanvasEdgeJSON {
  id: string
  from: string
  to: string
  kind: EdgeKind
  label?: string
}

export const SEED_NODES: CanvasNodeJSON[] = [
  { id: 'wf-1', kind: 'workflow', name: '变速稳态工作流', state: 'online',
    channel: '阶段 3/5 · 运行中',
    facts: [['步骤', '12'], ['当前步', '斜坡升速']], x: 40, y: 40 },
  { id: 'ds-1', kind: 'datasource', name: '芯片知识库', state: 'online',
    channel: '工艺 / 测试需求 / 说明书',
    facts: [['文档', '318'], ['版本', 'v2.1']], x: 40, y: 300 },
  { id: 'bench-1', kind: 'bench', name: '风机测试台架', state: 'online',
    channel: 'SSH · 172.25.5.166:8963',
    facts: [['通道', 'PWM1/2 · FG1/2'], ['台架', 'bench-a']], x: 330, y: 170 },
  { id: 'board-1', kind: 'board', name: 'FU6832N 驱动板', state: 'warn',
    channel: 'SWD 在线调试',
    facts: [['固件', 'v0.9.4-rc2'], ['载波', '20 kHz']], x: 620, y: 60 },
  { id: 'dut-1', kind: 'dut', name: '涵道风机电机', state: 'online',
    channel: '极对数 2 · 逆风加载',
    facts: [['额定', '24 V / 3 A'], ['转速', '4 820 rpm']], x: 620, y: 320 },
  { id: 'scope-1', kind: 'scope', name: 'Rigol DS1104Z', state: 'fault',
    channel: 'SSH · VISA 直连',
    facts: [['采样', '1 GSa/s'], ['通道', 'CH1 相电流']], x: 900, y: 190 },
]

export const SEED_EDGES: CanvasEdgeJSON[] = [
  { id: 'e1', from: 'wf-1', to: 'bench-1', kind: 'data', label: '下发测试序列' },
  { id: 'e2', from: 'ds-1', to: 'bench-1', kind: 'data', label: '判据 / 参数' },
  { id: 'e3', from: 'bench-1', to: 'board-1', kind: 'physical', label: 'PWM 驱动' },
  { id: 'e4', from: 'bench-1', to: 'dut-1', kind: 'physical', label: 'FG 反馈' },
  { id: 'e5', from: 'board-1', to: 'dut-1', kind: 'physical', label: '三相输出' },
  { id: 'e6', from: 'board-1', to: 'scope-1', kind: 'physical', label: '相电流探头' },
  { id: 'e7', from: 'dut-1', to: 'scope-1', kind: 'physical' },
]

/** 右侧工具条：可拖入画布的功能模块，按组分层（不平铺） */
export interface RailItem { kind: NodeKind; name: string; state: LinkState; channel?: string; facts?: [string, string][] }
export interface RailGroup { id: string; title: string; items: RailItem[] }

export const RAIL: RailGroup[] = [
  {
    id: 'device', title: '设备',
    items: [
      { kind: 'scope', name: '示波器', state: 'offline', channel: 'SSH · 待连接', facts: [['采样', '—']] },
      { kind: 'bench', name: '测试台架', state: 'offline', channel: 'SSH · 待连接', facts: [['通道', '—']] },
      { kind: 'board', name: '驱动板', state: 'offline', channel: 'SWD · 待连接', facts: [['固件', '—']] },
    ],
  },
  {
    id: 'object', title: '对象',
    items: [
      { kind: 'dut', name: '被测电机', state: 'offline', channel: '未接入', facts: [['额定', '—']] },
    ],
  },
  {
    id: 'logic', title: '逻辑',
    items: [
      { kind: 'workflow', name: '工作流', state: 'offline', channel: '未启动', facts: [['步骤', '—']] },
      { kind: 'datasource', name: '数据源', state: 'offline', channel: '未挂载', facts: [['文档', '—']] },
    ],
  },
]
