/** 五流程、一模块、四组工具、卡片、画板节点与助手动作的图标表。
 *  导航、卡头、工具条、分组、画板、助手按钮统一从这里取。
 *
 *  第三轮并行期本文件冻结：W2 / W3 / W5 要用的图标已在此一次性登记完。
 *  收尾轮（W6）按 W5 跨包请求单第 3 条补齐了 11 个语义图标名，
 *  助手动作图标表因此由 17 个扩到 28 个。 */
import {
  Activity,
  AlertTriangle,
  BatteryCharging,
  BookOpen,
  Boxes,
  Cable,
  CheckCircle2,
  CircuitBoard,
  ClipboardCheck,
  Download,
  FileDiff,
  Fan,
  FileBarChart,
  FileText,
  Filter,
  FolderTree,
  FlaskConical,
  Gauge,
  GitCompareArrows,
  LayoutGrid,
  Library,
  LibraryBig,
  Link2,
  Lightbulb,
  LineChart,
  ListChecks,
  ListTree,
  Lock,
  Maximize2,
  Network,
  NotebookPen,
  PackageCheck,
  PlayCircle,
  Plus,
  RefreshCw,
  Scale,
  ScrollText,
  Search,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Stethoscope,
  Tags,
  Upload,
  Wand2,
  Waves,
  Wind,
  Workflow,
  Wrench,
  ZoomIn,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { CanvasNodeType, FlowId, ModuleId } from '../data/types'

export const FLOW_ICON = {
  init: SlidersHorizontal,
  req: ClipboardCheck,
  run: PlayCircle,
  tune: Gauge,
  report: FileBarChart,
} as const satisfies Record<FlowId, unknown>

/** 导航短名 ≤6 字 */
export const FLOW_SHORT: Record<FlowId, string> = {
  init: '初始化',
  req: '测试需求',
  run: '启动测试',
  tune: '调优运行',
  report: '测试报告',
}

/** 模块：不进 stepper，从顶栏右端常驻按钮进入 */
export const MODULE_ICON = {
  knowledge: Library,
} as const satisfies Record<ModuleId, unknown>

export const MODULE_SHORT: Record<ModuleId, string> = {
  knowledge: '知识库',
}

export const TOOL_GROUP_ICON = {
  acquire: Waves,
  stimulus: Wind,
  device: Wrench,
  session: Cable,
} as const

export const CARD_ICON = {
  'product-view': Boxes,
  schematic: CircuitBoard,
  'project-tree': BookOpen,
  tools: Wrench,
  'bench-live': Activity,
  'remote-device': Cable,
  interlock: ShieldCheck,
  workflow: ClipboardCheck,
  'wf-lib': ListTree,
  timeseries: Waves,
  progress: Activity,
  pipeline: Workflow,
  candidates: ListChecks,
  'param-changes': GitCompareArrows,
  verdict: ShieldCheck,
  evidence: BookOpen,
  history: FileBarChart,
  experience: Lightbulb,
  artifacts: Boxes,
  'report-preview': FileBarChart,
  'template-fields': ClipboardCheck,
} as const

/** 画板十一类节点的图标（W3 用） */
export const CANVAS_NODE_ICON = {
  scope: Waves,
  motor: Fan,
  psu: BatteryCharging,
  bench: Activity,
  curve: LineChart,
  schematic: CircuitBoard,
  workflow: Workflow,
  verdict: ShieldCheck,
  interlock: Lock,
  knowledge: BookOpen,
  'device-mcp': Server,
} as const satisfies Record<CanvasNodeType, unknown>

/** 画板控件（缩放、复位、全屏、网格 / 画板切换）图标 */
export const CANVAS_UI_ICON = {
  zoom: ZoomIn,
  reset: RefreshCw,
  expand: Maximize2,
  grid: LayoutGrid,
  board: Network,
} as const

/** 知识库页三轴筛选与条目操作图标（W2 用） */
export const KNOWLEDGE_ICON = {
  usage: Tags,
  origin: FileText,
  owner: ListTree,
  filter: Filter,
  upload: Upload,
  add: Plus,
  doc: ScrollText,
  experience: FlaskConical,
} as const

/**
 * 助手预置动作按钮的图标表（W5 用）。
 * CopilotAction.icon 的取值必须是本表的键（COPILOT_ACTION_ICON_NAMES），取不到时退回 Sparkles。
 */
export const COPILOT_ACTION_ICON: Record<string, LucideIcon> = {
  search: Search,
  explain: BookOpen,
  wand: Wand2,
  check: CheckCircle2,
  shield: ShieldCheck,
  play: PlayCircle,
  list: ListChecks,
  chart: LineChart,
  report: FileBarChart,
  upload: Upload,
  download: Download,
  compare: GitCompareArrows,
  params: SlidersHorizontal,
  alert: AlertTriangle,
  refresh: RefreshCw,
  idea: Lightbulb,
  sparkles: Sparkles,
  /* 收尾轮补齐的 11 个语义名（W5 跨包请求单第 3 条）：
     并行期只有上面 17 个可用，W5 的 29 枚按钮被迫共用，语义有折损；
     补齐后 copilot-actions.json 里这 11 枚按 icon_draft 的原语义回填。 */
  library: LibraryBig,
  'folder-tree': FolderTree,
  scale: Scale,
  link: Link2,
  workflow: Workflow,
  lock: Lock,
  stethoscope: Stethoscope,
  network: Network,
  'file-diff': FileDiff,
  'note-pen': NotebookPen,
  package: PackageCheck,
}

export const COPILOT_ACTION_ICON_NAMES = Object.keys(COPILOT_ACTION_ICON)

export const copilotActionIcon = (name: string): LucideIcon =>
  COPILOT_ACTION_ICON[name] ?? Sparkles
