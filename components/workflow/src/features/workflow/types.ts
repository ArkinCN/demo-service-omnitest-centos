/**
 * 统一内部工作流模型。
 *
 * 由 parseWfw() 从峰岹 .wfw 文件产出，脱离 React Flow 与 Tauri 运行时，
 * 便于在任意 React 宿主中复用。
 */

/** 节点分组标识，取自客户端引擎 nodeTypes.ts 的 NODE_CATEGORIES。 */
export type NodeGroupId =
  | 'basic'
  | 'hid'
  | 'hid_presets'
  | 'debugging'
  | 'hid_query'
  | 'logic'
  | 'data'
  | 'verify'
  | 'subsystems'
  | 'instruments'
  | 'report'
  | 'unknown'

/** 节点参数值：.wfw 的 data 字段是自由 JSON，这里不收窄。 */
export type ParamValue = unknown

export interface WorkflowNode {
  id: string
  /** 原始 .wfw 节点类型字符串，例如 'hid_preset_speed_test'。 */
  type: string
  /** 展示名：优先 data.label，回退到类型中文名。 */
  label: string
  /** 所属分组。未知类型归入 'unknown'。 */
  group: NodeGroupId
  /** data 去掉 label 后的其余字段。 */
  params: Record<string, ParamValue>
  /** 原始文件里的坐标，缺失时为 null（交给自动布局）。 */
  position: { x: number; y: number } | null
  /** subworkflow 节点内嵌的子工作流，已递归解析。 */
  embedded?: WorkflowModel
}

export interface WorkflowEdge {
  id: string
  source: string
  target: string
  /** 出端口：'output' 主干、'error' 异常分支、'true'/'false' 条件分支。 */
  sourceHandle?: string
  targetHandle?: string
}

export interface WorkflowMeta {
  /** 稳定 ID，老文件可能缺失。 */
  id?: string
  /** metadata.name；样例文件里大多是占位值「新工作流」。 */
  name: string
  description?: string
  author?: string
  createdAt?: string
  updatedAt?: string
  version?: string
  tags: string[]
  category?: string
  isTemplate: boolean
  isSubsystem: boolean
  /** 文件格式版本，样例全部为 '1.0.0'。 */
  formatVersion: string
  /** 源文件是否为 gzip 压缩。 */
  compressed: boolean
}

export interface WorkflowModel {
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  meta: WorkflowMeta
  /** definition.variables 原样保留。 */
  variables: unknown[]
}

/** 工作流索引条目，对应 public/data/workflows.json 的一行。 */
export interface WorkflowIndexEntry {
  id: string
  name: string
  /** 目录派生的业务分组，例如 'StaticStart'、'子流程'。 */
  group: string
  /** 电压档：HV / SV / LV / HSLV / MIXED / N/A。 */
  voltage: string
  /** 相对 public/data/wfw/ 的文件路径。 */
  file: string
  nodeCount: number
  edgeCount: number
  /** 是否为子流程库文件。 */
  isSubflow: boolean
}
