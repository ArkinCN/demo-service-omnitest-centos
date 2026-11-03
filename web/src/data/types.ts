/* ===========================================================================
   数据契约。命名与结构对齐设计规格
   《设计规格 · 信息架构与页面》
   docs/20260919-通用Agent测试系统v2.0/01-设计规格-信息架构与页面.md
   （第 4 节层级树、第 6 节 B 区、第 7 节卡片库、第 9 节六流程页面规格）

   场景包源目录 c-data/scenes<sceneId>/，
   两个包都已就位（散热风扇、玻璃升降器）。两包之间的字段差异在加载时由
   src/features/scene/pack.ts 的 normalize() 抹平，压成本契约的映射在
   src/data/loadScene.ts 的 adaptScene() 里做，UI 层只认这一套字段。
   =========================================================================== */

export const FLOW_IDS = ['init', 'req', 'run', 'tune', 'report'] as const
export type FlowId = (typeof FLOW_IDS)[number]

/**
 * 模块标识。模块不占流程序号、不进 stepper，从顶栏右端的常驻按钮进入。
 * 第三轮把知识库从流程 1 降级为模块，理由见
 * 《第三轮实施计划 · 并行派工》第三节第 2 条。
 */
export const MODULE_IDS = ['knowledge'] as const
export type ModuleId = (typeof MODULE_IDS)[number]

/** 卡片库标识（规格 7.2） */
export const CARD_IDS = [
  'product-view',
  'schematic',
  'project-tree',
  'tools',
  'bench-live',
  'remote-device',
  'interlock',
  'workflow',
  'wf-lib',
  'timeseries',
  'progress',
  'pipeline',
  'candidates',
  'param-changes',
  'verdict',
  'evidence',
  'history',
  'experience',
  'artifacts',
  'report-preview',
  'template-fields',
] as const
export type CardId = (typeof CARD_IDS)[number]

/** 来源标记三态（规格 6.2） */
export type ParamSource = '文档' | '人工' | '建议'

/** 状态语义只三档 + 不适用（规格 3.3 / 6.1） */
export type ItemStatus = 'empty' | 'done' | 'alert' | 'na'

/** 三级：参数行 */
export interface ParamItem {
  id: string
  name: string
  value: number | string
  unit?: string
  kind?: 'number' | 'select' | 'switch' | 'readonly' | 'file' | 'table'
  step?: number
  min?: number
  max?: number
  precision?: number
  options?: string[]
  /** 与 options 一一对应的中文显示名；缺省时直接显示 options 里的原值 */
  optionLabels?: string[]
  source?: ParamSource
  status?: ItemStatus
  /** 11px 弱注：单位与取值范围说明 */
  note?: string
  /** 依据：文档名 + 位置 */
  evidence?: string
  /**
   * 「待核实」角标的说明文字。
   * 与 status: 'alert' 不同——alert 是「这个数是编的」（_placeholder），
   * pending 是「这个数有来源但来源本身还没定版」（_status），数值照常可用，
   * 只是引用时要说明。两者可以同时出现。
   */
  pending?: string
}

/** 二级：参数子组 */
export interface ParamSubGroup {
  id: string
  title: string
  items: ParamItem[]
}

/** 一级：参数分组（手风琴） */
export interface ParamGroup {
  id: string
  index: string
  title: string
  defaultOpen?: boolean
  subgroups: ParamSubGroup[]
}

/** B 区顶部输入清单行（规格 6.1） */
export interface ChecklistItem {
  id: string
  index: string
  name: string
  status: ItemStatus
  /** 定位按钮跳到哪个分组 */
  groupId: string
}

/** C 区卡片实例 */
export interface CardInstance {
  id: CardId
  /** 卡名覆写：同一张卡在不同场景包里指的东西不同时用（例如初始化 hero 图，
   *  散热风扇包里是原理图、玻璃升降器包里是结构示意图）。缺省用 CARD_LIB 的卡名。 */
  title?: string
  /** 卡头右侧的灰色时间戳 */
  stamp?: string
  /** 卡内一行摘要 */
  summary?: string
  /** 异常标记，出现即用暗红 */
  alert?: string
  /** 当前流程正在用：卡头左侧墨绿竖条 */
  active?: boolean
}

/** C 区工具条（规格 7.1，四组固定） */
export interface ToolItem {
  id: string
  label: string
  glyph: string
  state: 'online' | 'offline' | 'fault'
  hint?: string
}

export interface ToolGroup {
  id: 'acquire' | 'stimulus' | 'device' | 'session'
  title: string
  tools: ToolItem[]
}

/* ------------------------------------------------------------- C 区画板契约 */

/**
 * 画板节点类型。十一类，与 C 区右侧工具条的可拖工具一一对应。
 * 真正的节点渲染由 W3 在 src/features/canvas/ 下用 registerCanvasNode() 注册，
 * 本文件只定契约。
 */
export const CANVAS_NODE_TYPES = [
  'scope',
  'motor',
  'psu',
  'bench',
  'curve',
  'schematic',
  'workflow',
  'verdict',
  'interlock',
  'knowledge',
  'device-mcp',
] as const
export type CanvasNodeType = (typeof CANVAS_NODE_TYPES)[number]

/**
 * 边的两种语义。
 * physical 是仿物理接线，边上标通道名，取值口径见 src/data/bench.ts；
 * data 是数据流。两种边都不参与任何计算。
 */
export type CanvasEdgeKind = 'physical' | 'data'

export interface CanvasNode {
  id: string
  type: CanvasNodeType
  label: string
  x: number
  y: number
  w?: number
  h?: number
  /** 节点落在哪张卡上；有值时节点内容复用该卡的注册渲染 */
  card?: CardId
  /** 任意业务载荷，由各节点实现自行解释 */
  data?: Record<string, unknown>
}

export interface CanvasEdge {
  id: string
  from: string
  to: string
  kind: CanvasEdgeKind
  /** 物理连接边上的通道名，例如 CH4 */
  channel?: string
  label?: string
}

export interface CanvasLayout {
  nodes: CanvasNode[]
  edges: CanvasEdge[]
}

/* ----------------------------------------------------------- D 区助手动作契约 */

/**
 * 助手预置动作。点一下等于把预置的 prompt 或 skill 注入对话并以 mock 方式执行。
 * prompt 与 skill 两者至少给一个：给 prompt 是注入一段话，给 skill 是调一份规程。
 * requiresConfirm 为 true 时先弹确认卡片，走 agent-chat 现成的确认闸门。
 * 六个红线动作（启动、停止、急停、写回参数、导出、归档）一律不做成自动执行，
 * 只能做成「备好等人点」，见《第三轮实施计划》第三节第 8 条。
 */
export interface CopilotAction {
  id: string
  flow: FlowId | ModuleId
  /** 按钮文字，≤6 字 */
  label: string
  /** 图标名，取值须在 src/app/icons.ts 的 COPILOT_ACTION_ICON_NAMES 内 */
  icon: string
  prompt?: string
  skill?: string
  requiresConfirm?: boolean
}

/* --------------------------------------------------------------- 知识三轴契约 */

/**
 * 用途轴，固定三类不加第四类。
 * spec 产品说明书 · requirement 测试需求 · process 工艺。
 */
export type KnowledgeUsage = 'spec' | 'requirement' | 'process'

/** 来源轴，两类。doc 文档 · experience 经验。 */
export type KnowledgeOrigin = 'doc' | 'experience'

export const KNOWLEDGE_USAGE_LABEL: Record<KnowledgeUsage, string> = {
  spec: '产品说明书',
  requirement: '测试需求',
  process: '工艺',
}

export const KNOWLEDGE_ORIGIN_LABEL: Record<KnowledgeOrigin, string> = {
  doc: '文档',
  experience: '经验',
}

/**
 * 三轴筛选。归属轴是三级路径 [场景, 子类, 产品类型]，
 * 三个数组都为空表示该轴不过滤。
 */
export interface KnowledgeFilter {
  usage: KnowledgeUsage[]
  origin: KnowledgeOrigin[]
  owner: string[]
}

export interface FlowContent {
  checklist: ChecklistItem[]
  groups: ParamGroup[]
  /** 网格视图四个卡槽 */
  cards: CardInstance[]
  /** 画布视图的默认版式：卡片位置与连线。W3 接管画板后由 CanvasLayout 取代 */
  canvas?: {
    nodes: { id: CardId; x: number; y: number; w: number; h: number }[]
    links: { from: CardId; to: CardId; kind: 'belong' | 'signal'; label?: string }[]
  }
  greeting: string
  /** 确认条左侧的校验结果一行 */
  verifyLine: string
}

/** 三级产品体系：一级场景 › 二级子类 › 三级产品类型 */
export interface SceneMeta {
  id: string
  scene: string
  subclass: string
  productType: string
  /** 场景包名与版本，显示在全局状态位 */
  packName: string
  packVersion: string
  bench?: string
}

/** 界面配置段：场景包对壳层版式的下发项，目前只有 C 区默认视图 */
export interface SceneUi {
  /** 每条流程进页时 C 区默认落画板还是网格；缺的流程走代码兜底 */
  defaultView?: Partial<Record<FlowId, 'canvas' | 'grid'>>
}

export interface ScenePackage {
  meta: SceneMeta
  toolGroups: ToolGroup[]
  flows: Record<FlowId, FlowContent>
  /** 由 scene.json 的 `default_view` 段拼进来，见 loadScene.ts 的 adaptScene() */
  ui?: SceneUi
}
