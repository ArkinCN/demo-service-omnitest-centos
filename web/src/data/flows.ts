import type { FlowId } from './types'

export interface FlowAction {
  id: string
  label: string
  /** 主动作：墨绿描边实心文字，每流程一个（规格 5.3） */
  primary?: boolean
  /** 破坏性动作：暗红描边 */
  danger?: boolean
  /** 前置条件未满足时置灰 */
  disabled?: boolean
  disabledReason?: string
}

export interface FlowDef {
  id: FlowId
  path: string
  index: string
  label: string
  /** 标签状态（规格 5.2） */
  precondition?: string
  actions: FlowAction[]
}

/* 第三轮：六流程改五流程，编号 1–5 重排。知识库不占流程序号，
   降级为模块从顶栏右端按钮进入，路由见 src/router.tsx 的 /knowledge。 */
export const FLOWS: FlowDef[] = [
  {
    id: 'init',
    path: '/init',
    index: '1',
    label: '初始化配置',
    precondition: '需先选定产品类型',
    /**
     * ⚠️ 2026-09-29 用户要求：**移除顶栏的「提交并锁定」**。
     *
     * 该动作的业务已由左栏页脚的「确认并锁定 · N 项」承担（`ConfirmFooter`
     * → `confirmAndSnapshot`，全站唯一的落库入口，会存全部三类参数并锁定）。
     * 顶栏那颗只是「跳到初始化页 + 弹提示」，属多余的第二入口——
     * 与流程 2 移除顶栏「确认需求基线」同一口径（确认类动作只留一个入口）。
     *
     * ⚠️ 2026-10-09 用户要求：**隐藏三颗尚未实现的动作按钮**——
     * 「读取文档自动填充」「另存为参数模板」「校验配置」。
     *
     * 原因：三者的能力都在服务端（文档解析 / 模板落盘 / 配置校验），当前原型**未接后端**，
     * 行为表（`features/redline/flowActions.ts`）里也无绑定，只会落到 `noop`
     * （`disabled: true`，提示「该动作在当前原型里未接后端」）。用户要求**不显示**，
     * 因此直接从数据源移除，而不是在 TopBar 里加过滤——按钮不存在于 DOM，
     * 「不显示」与「不可交互」一并满足（沿用 2026-09-29 移除 `lock` 的同一手法）。
     *
     * 口径：顶栏按钮的改/删**只动本文件（数据源）**，不改 TopBar 的共用渲染逻辑。
     * ⚠️ 保留空数组而非删掉 actions 字段：下游按 `current.actions.map()` 渲染，空数组即不渲染按钮。
     * ⚠️ `ACTION_ICON` 里 `save-tpl` 的图标项**保留**（流程 2「另存模板」仍在用）。
     */
    actions: [],
  },
  {
    id: 'req',
    path: '/requirements',
    index: '2',
    label: '测试需求确认',
    precondition: '需流程 1 已确认',
    /**
     * ⚠️ 2026-09-28 用户要求：**移除顶栏的「确认需求基线」主按钮**。
     *
     * 原因：确认基线的动作在全站只该有**一个入口**，即左栏页脚的「确认基线」。
     * 此前顶栏一颗（只改内存、不落库、不跳转）、左栏一颗（空壳、什么都没接），
     * 两颗按钮文案相近、行为都不到位，人不知道该点哪个。
     * 现在统一到左栏那颗：落 requirement-baseline 产物 + 跳转流程 3 + 刷新读回，
     * 与流程 1「确认并锁定」是同一套做法（单一入口，不留第二种口径）。
     *
     * ⚠️ 2026-10-09 用户要求：**隐藏三颗尚未实现的动作按钮**——
     * 「导入标准」「编辑工作流」「另存模板」。
     *
     * 原因：与流程 1 同一口径——三者的能力都在服务端（标准导入 / 工作流编辑落盘 /
     * 模板落盘），当前原型**未接后端**：
     *   · `import-std` 的绑定只弹「本轮未接入，功能待排期」（flowActions.ts）；
     *   · `edit-wf` / `save-tpl` 在行为表里**无绑定**，落到 `noop`（`disabled: true`）。
     * 用户要求**不显示**，因此直接从数据源移除（按钮不进 DOM，不显示也不可点），
     * 与流程 1 的处理保持同一手法。
     *
     * ⚠️ 保留空数组而非删掉 actions 字段：下游按 `current.actions.map()` 渲染，空数组即不渲染按钮。
     * ⚠️ 至此 `save-tpl` 已不再被任何流程使用；`ACTION_ICON` 里的该项保留无害（多余键不参与渲染）。
     */
    actions: [],
  },
  {
    id: 'run',
    path: '/run',
    index: '3',
    label: '启动测试及结果分析',
    precondition: '需流程 2 已确认且安全联锁全绿',
    actions: [
      // ⚠️ 2026-10-05 用户要求：**移除顶栏「启动测试」**——它与左栏页脚的
      // 「确认参数 · N 项」（`ConfirmFooter`）是**同一条动作**
      // （两者都绑 `bind('start')`，见 flow-run/panel.tsx 的注释「同一条动作、
      // 同一份行为表」）。同一条动作出现两次，人不知道该点哪个。
      // 统一到左栏那颗：启动仍走红线确认卡，口径不变。
      //
      // ⚠️ 2026-10-09 用户要求：**隐藏顶栏「预检自检」**（`precheck`）。
      // 直接从数据源移除（与流程 1/2 同一手法）：按钮不进 DOM，不显示也不可点。
      // 其行为绑定（`flowActions.ts` 的 `precheck`，只弹一条 setNotice 自检摘要）
      // **保留**——留着供别处 `bind('precheck')` 需要时使用，只是顶栏不再渲染该按钮。
      // 顶栏其余（停止 / 急停）保留。
      // 置灰不再写死：由 useAppStore 里安全闸门的勾选数现算，九条全勾即放行。
      // 行为表在 src/features/redline/flowActions.ts。
      { id: 'stop', label: '停止' },
      { id: 'estop', label: '急停', danger: true },
    ],
  },
  {
    id: 'tune',
    path: '/tune',
    index: '4',
    label: '调优确认及运行',
    precondition: '需流程 3 有一轮结果',
    actions: [
      // ⚠️ 2026-10-05 用户要求：**移除顶栏「采纳并回到启动测试」**——它与左栏页脚的
      // 「确认采纳 · N 项」（`ConfirmFooter`）是**同一条动作**（左下角注释自认
      // 「与顶栏…同一条动作」），同一条动作两个入口，人不知道点哪个。
      // 统一到左下角那颗：写回仍走红线确认卡，口径不变。
      // 绑定表 `table['adopt-back']` 保留（左下角 `bind('adopt-back')` 仍在用）。
      { id: 'ignore-all', label: '全部忽略' },
      { id: 'rollback', label: '回滚基线', danger: true },
      { id: 'view-evidence', label: '查看依据' },
    ],
  },
  {
    id: 'report',
    path: '/report',
    index: '5',
    label: '测试报告及产出',
    precondition: '需流程 4 有明确结论',
    actions: [
      { id: 'gen-report', label: '生成报告', primary: true },
      { id: 'preview', label: '预览' },
      // 「导出」已删除（2026-09-30 用户口径）：生成报告成功后已**一步到位自动下载**，
      // 导出是重复的第二入口（其内部逻辑也是「探活→没生成就先生成→下载」）。
      // ⚠️ 设备桥的 export 工具映射（flowActions 的 bridgeArgs case 'export'）**保留**——
      // 那是 AI 助手对话里的 export 动作，与这颗按钮无关。
      // 「归档到知识库」只留在「产物留档」卡内那一处——它紧贴产物列表，语义完整；
      // 动作条再放一遍是同一条动作出现两次（DESIGN.md §4 文案纪律 4）。
    ],
  },
]

export const FLOW_BY_ID = Object.fromEntries(FLOWS.map((f) => [f.id, f])) as Record<
  FlowId,
  FlowDef
>

export const FLOW_BY_PATH = Object.fromEntries(FLOWS.map((f) => [f.path, f]))

/** 流程标签状态（规格 5.2）：未开始 / 进行中 / 已确认 / 有异常 */
export type FlowState = 'idle' | 'active' | 'confirmed' | 'alert'
