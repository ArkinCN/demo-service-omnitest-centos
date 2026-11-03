/* ===========================================================================
   一键自动化测试流程 · 编排器（纯逻辑层）。

   职责边界（分层铁律）：
     本文件**不 import 任何 UI 框架、路由、DOM、zustand、具体测试实现**。
     它只定义：阶段状态机、事件协议、进度计算、默认配置、轻量事件总线，
     以及一个接收「注入适配器」的 createAutomationOrchestrator 编排器。

   依赖倒置：
     编排器通过 AutomationAdapters 拿到它要调用的能力（确认参数、跑测试、
     结果采集、生成下载报告、路由跳转、事件总线、持久化、日志），
     自己不直接 import 具体实现。将来换框架/换状态库/换通信方式，
     只改适配层（由 state/useAppStore.ts 组装注入），编排器零改动。

   单向数据流：
     真实事件（适配器产出）→ 事件总线 emit → 订阅者（store 切片 / AI 播报 /
     大屏）各自更新。编排器**不伪造进度**——测试执行阶段的进度来自适配器
     上报（runCases 适配器内部复用 beginRun 真采集），编排器只转发。

   健壮性：
     · 幂等：模块级 currentRunId 守卫，同一时间只允许一个 run；
     · 可终止：stop() 调 cancel 适配器 + 状态置 stopped；
     · 可恢复：阶段状态经 storage 适配器持久化，restore() 读回；
     · 失败可观测：每个失败都 emit AUTOMATION_ERROR + 写 stage.status=failed。
   =========================================================================== */

/** 一个自动化 run 的整体状态 */
export type AutomationRunStatus = 'idle' | 'running' | 'completed' | 'failed' | 'stopped'

/** 单个阶段的流转状态 */
export type AutomationStageStatus =
  | 'pending'
  | 'current'
  | 'running'
  | 'success'
  | 'failed'
  | 'skipped'

/** 阶段定义（config 里配，route 映射到现有 FLOWS 路径） */
export interface AutomationStageDef {
  id: string
  name: string
  route: string
  /**
   * 进入该阶段时是否 `router.navigate` 到它的 route。
   *
   * ⚠️ 默认 **false**（2026-10-05 用户实测「界面一闪而过」的根治）：
   * 此前 `runStage` 每阶段都换页，五个阶段瞬间连跑 → 页面疯狂闪、什么都看不清。
   * 现在运行期由**全屏浮层**覆盖承载进度，换页毫无意义；
   * 只在整轮结束时由 `start()` 统一跳一次报告页（见 `FINAL_ROUTE`）。
   * 需要「进阶段就换页」的场景（如将来把浮层改成非全屏）再把该阶段显式置 true。
   */
  navigateOnEnter?: boolean
  /**
   * 该阶段最短展示时长（ms）。缺省用 `config.minStageMs`。
   *
   * 用途：`init` / `req` / `tune` / `report` 这些阶段底层调用可能只花几百毫秒，
   * 在浮层上「一闪而过」，人根本来不及看清在做什么——补一个下限让人看清每一步。
   * **真实耗时长的阶段（`run` 真机采集 20-30 秒）必须显式设 0 豁免**，
   * 否则白白多等、拖慢真机流程。
   */
  minShowMs?: number
  /**
   * 本阶段会真实调用的动作清单（2026-10-08 新增，**可选**）。
   *
   * 编排器按 promise 生命周期自动围栏：进阶段全部发 `running`、成功发 `done`、
   * 失败发 `failed`、被终止发 `skipped`。适配器还可以用 `reportTool` 额外上报
   * **动态**动作（如「采集 30% 档」），两者按 id 合流到 UI 的同一个动作面板。
   *
   * ⚠️ `run` 阶段**故意不声明**：它的动作全是动态的（逐档采集 + 判定落库），
   * 静态声明反而会和动态项重复。
   */
  tools?: AutomationToolDef[]
}

/** 阶段运行时的完整状态（含进度与消息，供 UI 渲染） */
export interface AutomationStage extends AutomationStageDef {
  status: AutomationStageStatus
  /** 0–100 */
  progress: number
  message: string
  startTime?: number
  endTime?: number
}

/** 单个阶段内一个「真实动作」的三态（2026-10-08 新增）
 *
 *  ⚠️ 纪律：这里的动作**不是动画脚本**，而是编排器按 promise 生命周期
 *  自动围栏出来的真实调用（见 `runStage`：进阶段发 running、成功发 done、
 *  失败发 failed、被终止发 skipped）。原先左栏「工具调用」只能靠阶段级
 *  message 概括，人看不到「到底哪一步在动」；现在逐条可见，且状态与真实
 *  调用天然一致——写死一串「串口连接 → 指令发送」的假动画会违反项目
 *  「禁止假数据」纪律。
 */
export type AutomationToolStatus = 'running' | 'done' | 'failed' | 'skipped'

/** 阶段内一个真实动作的声明（配在 `AutomationStageDef.tools`） */
export interface AutomationToolDef {
  id: string
  label: string
}

/** 日志级别（2026-10-08 新增）。编排器只给级别，渲染与配色由 UI 决定。 */
export type AutomationLogLevel = 'info' | 'success' | 'warn' | 'error'

/**
 * 实时数据通道的载荷（2026-10-08 新增，`kind` 是判别式）。
 *
 *  ⚠️ 用 `unknown` 而不是 `FanPlan`/`FanSample`：本文件是**纯逻辑层**，
 *  严禁 import 任何业务/UI 模块（见文件头纪律）。业务类型由 store 侧收窄
 *  （`useAppStore` 已经 import 过 `FanSample`，收窄零成本）。
 * 两种 kind 分开而不是塞进一个大对象：样本流是 1Hz 高频、判定是一次性结论，
 *  混在一起会让 UI 每次都做无谓的深比较。
 */
export type AutomationLiveEvent =
  | { kind: 'samples'; plan: unknown; samples: unknown[] }
  | { kind: 'verdicts'; verdicts: unknown[] }

/** 适配器上报「一个真实动作的状态变化」用 */
export interface AutomationToolEvent {
  id: string
  label: string
  status: AutomationToolStatus
  message?: string
}

/**
 * 流程 3 一轮跑完后的**真实**判定统计（2026-10-08 抽出为具名类型）。
 *
 * ⚠️ 全部字段可选是纪律而非偷懒：`runAndCollect` 只有在真拿到后端权威判定后
 * 才填 total/pass/fail；取不到时只给 `hasFail`，统计留空——**宁可少给数字，
 * 也不能给一个编出来的 0**（结果页与判定卡据此显示「—」而不是「0 条通过」）。
 */
export interface AutomationRunMetrics {
  hasFail: boolean
  pass?: number
  fail?: number
  missing?: number
  /** 本台架不具备该测量手段的判据数，**单列**，不并入 pass/missing */
  notApplicable?: number
  total?: number
  /** 本轮真实采到的样本条数（取 runAndCollect 里的 samples.length） */
  sampleCount?: number
}

/** 事件名协议（至少覆盖这些，payload 见 AutomationPayload） */
export type AutomationEventName =
  | 'AUTOMATION_START'
  | 'AUTOMATION_STAGE_CHANGE'
  | 'AUTOMATION_PROGRESS'
  | 'AUTOMATION_LOG'
  | 'AUTOMATION_ERROR'
  | 'AUTOMATION_REPORT_READY'
  | 'AUTOMATION_DOWNLOAD_START'
  | 'AUTOMATION_DOWNLOAD_SUCCESS'
  | 'AUTOMATION_END'
  /** 单个真实动作的状态变化（2026-10-08 新增） */
  | 'AUTOMATION_TOOL'
  /** 实时数据流：台架样本 + 权威判定（2026-10-08 新增） */
  | 'AUTOMATION_LIVE'

export const AUTOMATION_EVENTS: readonly AutomationEventName[] = [
  'AUTOMATION_START',
  'AUTOMATION_STAGE_CHANGE',
  'AUTOMATION_PROGRESS',
  'AUTOMATION_LOG',
  'AUTOMATION_ERROR',
  'AUTOMATION_REPORT_READY',
  'AUTOMATION_DOWNLOAD_START',
  'AUTOMATION_DOWNLOAD_SUCCESS',
  'AUTOMATION_END',
  'AUTOMATION_TOOL',
  'AUTOMATION_LIVE',
] as const

/** 事件载荷。runId 等字段至少要覆盖这些。 */
export interface AutomationPayload {
  runId: string
  stageId: string
  stageName: string
  status: string
  progress: number
  currentTask: string
  message: string
  /** 通过/失败/跳过等统计，报告阶段回填 */
  metrics: Record<string, number>
  /**
   * 整轮起止时刻（ms epoch），**由编排器如实记录**，前端只做展示、不自己算耗时。
   * `AUTOMATION_START` 起带上 startedAt；`AUTOMATION_END` 起两个都带。
   * 用于结果卡的「总耗时」——必须是可复核的实数，不是前端估的。
   */
  startedAt?: number
  finishedAt?: number
  timestamp: number
  /* ---------- 以下为 2026-10-08 新增的可选字段（全部可选，既有订阅方零改动） ---------- */
  /** `AUTOMATION_TOOL`：动作 id */
  toolId?: string
  /** `AUTOMATION_TOOL`：动作显示名 */
  toolLabel?: string
  /** `AUTOMATION_TOOL`：动作三态 */
  toolStatus?: AutomationToolStatus
  /** `AUTOMATION_LOG` / `AUTOMATION_ERROR` / `AUTOMATION_TOOL`：日志级别 */
  level?: AutomationLogLevel
  /** `AUTOMATION_LIVE`：实时数据（判别式 union，业务类型由 store 侧收窄） */
  live?: AutomationLiveEvent
}

/** 事件总线：极简 pub/sub，不引入第三方依赖。 */
export interface EventBus {
  on(name: AutomationEventName, fn: (payload: AutomationPayload) => void): () => void
  emit(name: AutomationEventName, payload: AutomationPayload): void
}

export function createEventBus(): EventBus {
  const listeners = new Map<AutomationEventName, Set<(p: AutomationPayload) => void>>()
  return {
    on(name, fn) {
      let set = listeners.get(name)
      if (!set) {
        set = new Set()
        listeners.set(name, set)
      }
      set.add(fn)
      return () => {
        set?.delete(fn)
      }
    },
    emit(name, payload) {
      const set = listeners.get(name)
      if (!set) return
      for (const fn of [...set]) {
        try {
          fn(payload)
        } catch (e) {
          // 订阅者抛错不能打断编排流：记到 console，不让一个 UI 订阅者拖垮整条链
          console.error(`[automation] 事件 ${name} 的订阅者抛错：`, e)
        }
      }
    },
  }
}

/** 持久化接口（隔离 localStorage 等具体实现） */
export interface AutomationStorage {
  get(key: string): unknown
  set(key: string, value: unknown): void
  remove(key: string): void
}

/** 日志接口 */
export interface AutomationLogger {
  info(message: string): void
  error(message: string, err?: unknown): void
}

/** 路由接口（编排器不能用 hook，由组件层注入 navigate 函数）。
 *
 *  ⚠️ 用法已收窄（2026-10-05）：**只在整轮结束时跳一次报告页**。
 *  逐阶段换页已取消（那正是「界面一闪而过」的来源）。
 */
export interface AutomationRouter {
  navigate(path: string): void
}

/** 自动化要复用的测试能力适配器（依赖倒置的落点）。
 *
 * 阶段严格对齐顶部五流程（init/req/run/tune/report）：
 *   initParams     → 流程1 初始化配置：自动确认参数（persistSnapshot）
 *   confirmBaseline→ 流程2 测试需求确认：自动确认基线（persistBaseline）
 *   runAndCollect  → 流程3 启动测试：真下发启动 + 真采集 + 判定落库，返回是否有未达标
 *   tuneOnce       → 流程4 调优确认：判 fail → 自动采纳推荐参数 → 真写回 → 回流程3；
 *                    由编排器按 config.tuneRetries 循环调用（每次会回到流程3 重跑）
 *   generateReport → 流程5 报告生成
 *   downloadReport → 流程5 报告下载
 */
export interface AutomationAdapters {
  /** 流程1 初始化配置：自动确认参数（复用 persistSnapshot） */
  initParams(): Promise<void>
  /** 流程2 测试需求确认：自动确认需求基线（复用 persistBaseline） */
  confirmBaseline(): Promise<void>
  /** 流程3 启动测试：真下发启动 + 真采集 + 判定落库。
   *  返回本轮是否有未达标(fail)，以及**真实判定统计**（供结果卡展示，不编数字）。
   *  pass/fail/missing/total 取后端权威判定结果；取不到时只给 hasFail，统计留空。
   *  notApplicable 单列「本台架不适用」，绝不并入 pass（见 AutomationRunMetrics）。 */
  runAndCollect(onProgress: (progress: number) => void): Promise<AutomationRunMetrics>
  /** 流程4 调优确认：自动采纳推荐参数并写回；返回「是否还有可采纳的推荐项」。
   *  无推荐项（没有 fail / 没有候选）返回 false，编排器据此直接进报告。 */
  tuneOnce(): Promise<{ adopted: boolean }>
  /**
   * 流程5 报告生成（复用后端 `POST /api/reports/generate`）。
   *
   * 返回后端**真实三档状态**（`ok` / `placeholder` / `blocked`）与文件名 / 原因——
   * 编排器据此在结果卡上如实呈现，**不把「占位报告」说成正式交付件**。
   * `blocked`（没产出文件）时编排器会如实记失败，不会去下载一个不存在的文件。
   */
  generateReport(): Promise<{
    status: 'ok' | 'placeholder' | 'blocked'
    file?: string
    reason?: string
  }>
  /** 流程5 报告下载（复用 `GET /api/reports/{run_id}/download`；被拦截/无文件时返回 blocked） */
  downloadReport(): Promise<{ blocked?: boolean; reason?: string }>
  /** 终止（复用 stop / estop） */
  cancel?(): Promise<void>
  /**
   * 上报一个**动态**真实动作的状态（2026-10-08 新增）。
   *
   * ⚠️ 这两个回调由 `createAutomationOrchestrator` 在创建时**注入**（覆盖 undefined），
   * 所以适配器实现方不必自己声明——它们只是「编排器给我的上报通道」。
   * 之所以不直接把总线交给适配器自己 emit：走编排器的 `emit()` 才能自动带上
   * runId / 当前阶段 / 起止时刻等默认字段，适配器不必也不该重复拼一遍信封。
   */
  reportTool?(e: AutomationToolEvent): void
  /** 上报实时数据（台架样本流 / 一次性权威判定），语义见 `AutomationLiveEvent` */
  reportLive?(l: AutomationLiveEvent): void
  router: AutomationRouter
  eventBus: EventBus
  storage: AutomationStorage
  logger: AutomationLogger
}

/** 编排器的可配置项（阶段/超时/重试/调优重试次数/节流，全部集中在这，不散落硬编码） */
export interface AutomationConfig {
  /** 阶段序列（对齐顶部五流程），按序推进 */
  stages: AutomationStageDef[]
  /** 单个阶段超时（毫秒），超时视为失败 */
  stageTimeoutMs: number
  /** 单个阶段失败重试次数 */
  maxRetries: number
  /** 流程4 调优重试上限：跑流程3→判fail→采纳→回流程3，最多循环这么多次。
   *  缺省取 `TUNE_RETRIES`（唯一来源），别在调用处再写死一个数字。 */
  tuneRetries: number
  /** 播报节流（毫秒）：同类型事件至少间隔这么久才重发一次 */
  announceThrottleMs: number
  /** 持久化键名 */
  storageKey: string
  /**
   * 瞬时阶段的**最短展示时长**（毫秒）；0 表示不加。
   *
   * 起因（2026-10-05 用户实测「界面一闪而过」）：`init`/`req`/`tune`/`report`
   * 这些阶段的底层调用可能只花几百毫秒，浮层上刚亮就跳到下一个，人看不清。
   * 补一个下限让每步都「看得见」。
   * 上限代价：4 个瞬时阶段 × 900ms ≈ 3.6s，对真机流程（数十秒）可忽略。
   */
  minStageMs: number
}

/** 编排器暴露给外部的操作面 */
export interface Orchestrator {
  /** 启动一个 run。幂等：已在跑则返回 { error: 'already_running' } */
  start(): Promise<{ error?: 'already_running'; runId?: string }>
  stop(): Promise<void>
  getRunStatus(): AutomationRunStatus
  getStages(): AutomationStage[]
  getCurrentStageId(): string | null
  /** 从持久化恢复上次未完成的 run（刷新后调用）。
   *  返回完整快照含 runStatus / 起止时刻 / 判定统计——UI 据此恢复结果卡；
   *  刷新打断的 `running` 会被如实降级为 `stopped`（见实现注释）。 */
  restore(): {
    runId: string | null
    stages: AutomationStage[]
    runStatus: AutomationRunStatus
    currentStageId: string | null
    startedAt: number | null
    finishedAt: number | null
    metrics: Record<string, number>
  }
  /** 订阅事件（供 store 切片 / AI 播报 / 大屏挂订阅） */
  on(name: AutomationEventName, fn: (payload: AutomationPayload) => void): () => void
}

/** 整轮结束后统一跳转的目标路由（唯一一次换页）。报告是本轮自动化的自然终点。 */
export const FINAL_ROUTE = '/report'

/**
 * 自动化运行态的持久化键。
 *
 * ⚠️ 导出它是有原因的：`clearAutomation()`（关掉结果卡）要**清掉这份本地记录**，
 * 否则刷新一次结果卡又「复活」。但注意：清的只是**运行态**，
 * 已落库的测试产物（快照/基线/判定/报告）一律不动——这点在 clearAutomation 注释里写明。
 */
export const AUTOMATION_STORAGE_KEY = 'omnitest.automation.v1'

/**
 * 流程 4 调优重跑轮次上限 —— **唯一来源**。
 *
 * 演示口径（2026-10-10 用户拍板，需求单编号 2）：**只重跑 1 轮**。
 * 一次真机测试要几分钟，轮次越多等待越久；跑满上限后无论结果如何都出报告。
 * 循环条件（`start()` 里的 while）与引导屏文案（`AutomationIntro`）都从这里派生，
 * 别处不许再写一个数字 —— 这两处口径曾经漂移过（注释写 3、逻辑改 1）。
 */
export const TUNE_RETRIES = 1

const DEFAULT_CONFIG: AutomationConfig = {
  // 阶段严格对齐顶部五流程（data/flows.ts 的 FLOWS）：id/name/route 一一对应。
  // navigateOnEnter 一律不设（默认 false）——运行期由全屏浮层覆盖，不逐阶段换页。
  // minShowMs 逐阶段标：瞬时阶段走默认下限，真机采集阶段（run）显式 0 豁免。
  stages: [
    {
      id: 'init',
      name: '初始化配置',
      route: '/init',
      tools: [
        { id: 'load-pack', label: '读取场景包' },
        { id: 'snapshot', label: '落库配置快照' },
        { id: 'lock-baseline', label: '锁定基线参数' },
      ],
    },
    {
      id: 'req',
      name: '测试需求确认',
      route: '/requirements',
      tools: [
        { id: 'collect-criteria', label: '汇总本场景判据' },
        { id: 'persist-baseline', label: '落库需求基线' },
      ],
    },
    // run 阶段真机采集本身 20-30 秒，**不加最小展示时长**，否则白白拖慢。
    // ⚠️ 也**不声明 tools**：本阶段的真实动作全是动态的（逐档下发 + 轮询 + 判定），
    // 由 `runAndCollect` 用 `reportTool` 逐档上报，静态声明只会与之重复。
    { id: 'run', name: '启动测试及结果分析', route: '/run', minShowMs: 0 },
    {
      id: 'tune',
      name: '调优确认及运行',
      route: '/tune',
      tools: [
        { id: 'candidates', label: '计算推荐参数' },
        { id: 'adopt-writeback', label: '采纳并写回' },
        { id: 'persist-param-change', label: '落库参数改动' },
      ],
    },
    // report 阶段：**报告现在无论成败都要出**（2026-10-05 用户口径），
    // 而生成 + 下载本身要真调后端（占位 xlsx 写入可能就是几百毫秒到数秒）。
    // 给它一个很小的下限（300ms）只为「让人看见这一步发生过」，
    // 不沿用 config.minStageMs 的 900ms——失败路径上多等 900ms 纯属浪费。
    {
      id: 'report',
      name: '测试报告及产出',
      route: '/report',
      minShowMs: 300,
      tools: [
        { id: 'generate-report', label: '按模板生成报告' },
        { id: 'download-report', label: '下载报告到本机' },
      ],
    },
  ],
  stageTimeoutMs: 120_000,
  maxRetries: 1,
  // 流程4 调优重试：跑流程3→判fail→自动采纳→回流程3，最多循环 TUNE_RETRIES 次（现为 1，见常量说明），
  // 之后无论结果都出报告。
  tuneRetries: TUNE_RETRIES,
  announceThrottleMs: 400,
  storageKey: AUTOMATION_STORAGE_KEY,
  minStageMs: 900,
}

function newRunId(): string {
  return `auto_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

export function createAutomationOrchestrator(
  adapters: AutomationAdapters,
  config: Partial<AutomationConfig> = {},
): Orchestrator {
  const cfg: AutomationConfig = { ...DEFAULT_CONFIG, ...config }
  const bus = adapters.eventBus
  const logger = adapters.logger

  // ── 运行态（模块级？不，闭包内，每次 create 一套，避免多实例串状态）──
  let runStatus: AutomationRunStatus = 'idle'
  let runId: string | null = null
  let stages: AutomationStage[] = cfg.stages.map((s) => ({
    ...s,
    status: 'pending' as AutomationStageStatus,
    progress: 0,
    message: '',
  }))
  let currentStageId: string | null = null
  /** 是否被请求终止 */
  let stopRequested = false
  /** 整轮起止时刻（ms epoch）——如实记录，供结果卡展示「总耗时」 */
  let startedAt: number | null = null
  let finishedAt: number | null = null
  /** 最近一轮的判定统计（由 runAndCollect 回填真值），随 END 下发供结果卡展示 */
  let lastMetrics: Record<string, number> = {}

  function emit(name: AutomationEventName, extra: Partial<AutomationPayload> = {}): void {
    const cur = stages.find((s) => s.id === currentStageId)
    bus.emit(name, {
      runId: runId ?? '',
      stageId: cur?.id ?? '',
      stageName: cur?.name ?? '',
      status: runStatus,
      progress: cur?.progress ?? 0,
      currentTask: cur?.message ?? '',
      message: '',
      metrics: {},
      // 起止时刻默认带上最新值：订阅方任何事件都能读到（结果卡不必只认 END）
      startedAt: startedAt ?? undefined,
      finishedAt: finishedAt ?? undefined,
      ...extra,
      timestamp: Date.now(),
    })
  }

  /* ------------------------------------------------------------------
     动作（工具）状态通道
     ------------------------------------------------------------------
     两个入口合流到同一个 `AUTOMATION_TOOL` 事件：
       ① 静态声明：`stage.tools`，由下面的 `fenceStageTools` 按 promise
          生命周期自动围栏（进阶段 running → 成功 done / 失败 failed /
          被终止 skipped）；
       ② 动态上报：适配器调 `adapters.reportTool?.({id,label,status})`，
          用于「采集 30% 档」这类只有运行时才知道粒度的动作。
     UI 侧按 toolId 建 map 合流，两类动作在一个面板里按到达顺序展示。
     ------------------------------------------------------------------ */

  /** 静态动作围栏：把某阶段声明的动作整批置为指定状态 */
  function fenceStageTools(stage: AutomationStageDef, status: AutomationToolStatus, message = ''): void {
    for (const t of stage.tools ?? []) {
      emit('AUTOMATION_TOOL', { toolId: t.id, toolLabel: t.label, toolStatus: status, message })
    }
  }

  // 注入给适配器的两个上报通道（覆盖实现方可能给的 undefined）：
  // 走编排器的 emit 才能自动带上 runId / 当前阶段 / 起止时刻等默认字段。
  adapters.reportTool = (e: AutomationToolEvent): void => {
    emit('AUTOMATION_TOOL', {
      toolId: e.id,
      toolLabel: e.label,
      toolStatus: e.status,
      message: e.message ?? '',
    })
  }
  adapters.reportLive = (l: AutomationLiveEvent): void => {
    emit('AUTOMATION_LIVE', { live: l })
  }

  function persist(): void {
    try {
      adapters.storage.set(cfg.storageKey, {
        runId,
        runStatus,
        currentStageId,
        stages,
        // 起止时刻一并落盘：刷新恢复时结果卡的「总耗时」才有据
        startedAt,
        finishedAt,
        metrics: lastMetrics,
      })
    } catch (e) {
      logger.error('自动化状态持久化失败', e)
    }
  }

  function updateStage(stageId: string, patch: Partial<AutomationStage>): void {
    stages = stages.map((s) => (s.id === stageId ? { ...s, ...patch } : s))
  }

  function setCurrent(stageId: string, status: AutomationStageStatus, message: string): void {
    currentStageId = stageId
    // 只有当前阶段带 current/running，其余已完成/失败的保持原状，未开始的 pending
    stages = stages.map((s) => {
      if (s.id === stageId) return { ...s, status, message, startTime: s.startTime ?? Date.now() }
      return s
    })
    emit('AUTOMATION_STAGE_CHANGE', { stageId, stageName: stages.find((s) => s.id === stageId)?.name ?? '', status, currentTask: message })
    persist()
  }

  function finishStage(stageId: string, ok: boolean, message: string): void {
    const now = Date.now()
    stages = stages.map((s) =>
      s.id === stageId
        ? { ...s, status: ok ? 'success' : 'failed', progress: ok ? 100 : s.progress, message, endTime: now }
        : s,
    )
    persist()
  }

  /**
   * 可中断的等待：每 50ms 轮询一次 `stopRequested`，被终止就立即返回。
   *
   * ⚠️ 纯逻辑实现（只用 setTimeout，不 import 任何 UI/DOM/zustand），
   * 不破坏编排器「纯逻辑层」的纪律。
   * 用途：给瞬时阶段补「最短展示时长」，让人看清每一步（见 `minShowMs`）。
   */
  function sleepInterruptible(ms: number): Promise<void> {
    return new Promise((resolve) => {
      if (ms <= 0) return resolve()
      const deadline = Date.now() + ms
      const tick = () => {
        if (stopRequested || Date.now() >= deadline) return resolve()
        setTimeout(tick, 50)
      }
      setTimeout(tick, 50)
    })
  }

  /** 跑一个阶段：带重试、超时与最小展示时长。返回是否成功。 */
  async function runStage(stage: AutomationStageDef, run: (onProgress: (n: number) => void) => Promise<void>): Promise<boolean> {
    setCurrent(stage.id, 'running', `开始：${stage.name}`)
    // ⚠️ 不再逐阶段换页（那正是「界面一闪而过」的来源）。
    // 仅当该阶段显式要求时才 navigate；整轮结束由 start() 统一跳 FINAL_ROUTE。
    if (stage.navigateOnEnter) adapters.router.navigate(stage.route)

    const stageStartedAt = Date.now()
    // 最小展示时长：run 阶段显式 0（真机采集本来就慢，不加）；其余走 config 默认。
    const minShow = stage.minShowMs ?? cfg.minStageMs

    let attempt = 0
    // eslint-disable-next-line no-constant-condition
    while (true) {
      attempt += 1
      // 每次尝试都把静态动作置 running：重试时面板会如实回到「进行中」，
      // 而不是留着上一轮的 failed 不动（那会让人以为已经彻底失败）。
      fenceStageTools(stage, 'running', attempt > 1 ? `第 ${attempt} 次尝试` : '')
      const progressTick = (n: number) => {
        const clamped = Math.max(0, Math.min(100, Math.round(n)))
        updateStage(stage.id, { progress: clamped })
        emit('AUTOMATION_PROGRESS', { stageId: stage.id, stageName: stage.name, progress: clamped, currentTask: stages.find((s) => s.id === stage.id)?.message ?? '' })
      }
      try {
        const timeout = new Promise<never>((_, reject) => {
          setTimeout(() => reject(new Error(`阶段「${stage.name}」超时（${cfg.stageTimeoutMs}ms）`)), cfg.stageTimeoutMs)
        })
        await Promise.race([run(progressTick), timeout])
        // 补足最短展示时长：只补「实际耗时不足」的部分，不额外拖慢慢阶段。
        // 补等期间被终止则立即返回（交给下面 stopRequested 分支收口）。
        const spent = Date.now() - stageStartedAt
        if (minShow > 0 && spent < minShow) await sleepInterruptible(minShow - spent)
        if (stopRequested) {
          fenceStageTools(stage, 'skipped', '已终止')
          finishStage(stage.id, false, `${stage.name} 被终止`)
          return false
        }
        fenceStageTools(stage, 'done')
        finishStage(stage.id, true, `${stage.name} 完成`)
        logger.info(`[automation] 阶段完成：${stage.name}（耗时 ${Date.now() - stageStartedAt}ms）`)
        return true
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        logger.error(`[automation] 阶段失败：${stage.name}`, e)
        if (stopRequested) {
          fenceStageTools(stage, 'skipped', '已终止')
          finishStage(stage.id, false, `${stage.name} 被终止`)
          return false
        }
        if (attempt > cfg.maxRetries) {
          // 失败原因逐条透传到动作面板，不吞也不美化
          fenceStageTools(stage, 'failed', msg)
          finishStage(stage.id, false, `${stage.name} 失败：${msg}`)
          emit('AUTOMATION_ERROR', { stageId: stage.id, stageName: stage.name, status: 'failed', message: msg, level: 'error' })
          return false
        }
        // 重试：如实记录，不静默
        emit('AUTOMATION_LOG', { stageId: stage.id, stageName: stage.name, status: 'running', message: `${stage.name} 第 ${attempt} 次尝试失败（${msg}），重试中…`, level: 'warn' })
      }
    }
  }

  async function start(): Promise<{ error?: 'already_running'; runId?: string }> {
    if (runStatus === 'running') return { error: 'already_running' }
    stopRequested = false
    runId = newRunId()
    runStatus = 'running'
    startedAt = Date.now()
    finishedAt = null
    // 判定统计每轮重置（runAndCollect 会回填真实值，见 start() 里的 metrics）
    lastMetrics = {}
    stages = cfg.stages.map((s) => ({ ...s, status: 'pending' as AutomationStageStatus, progress: 0, message: '' }))
        currentStageId = null
        persist()
    // startedAt 随 START 一并下发：结果卡的「总耗时」由编排器给实数，前端不算
    emit('AUTOMATION_START', { runId, stageId: '', stageName: '', status: 'running', currentTask: '自动化测试启动', startedAt })
    logger.info(`[automation] 启动 run=${runId}`)

    let finalStatus: AutomationRunStatus = 'completed'
    let loop = 0

    // ── 流程1 初始化配置 ──
    if (!stopRequested && !(await runStage(byId('init'), () => adapters.initParams()))) finalStatus = 'failed'

    // ── 流程2 测试需求确认 ──
    if (finalStatus === 'completed' && !stopRequested && !(await runStage(byId('req'), () => adapters.confirmBaseline()))) finalStatus = 'failed'

    // ── 流程3 启动测试 + 流程4 调优确认（构成重试循环）──
    // 循环体：跑流程3 出判定 → 有 fail 就进流程4 自动采纳推荐参数 → 回流程3 重跑。
    // 最多循环 cfg.tuneRetries 次；全部通过 / 无推荐参数 / 达到上限，都退出循环进报告。
    let hasFail = false
    /** 把 runAndCollect 的返回收集成结果卡要的 metrics（真实判定统计，不编）
     *  ⚠️ `not_applicable`（本台架不具备该测量手段）必须**单列**：
     *  它既不是「测过且合格」也不是「本该采到却没采」，并进 pass 或 missing
     *  都是造假（详见 useAppStore 里 runAndCollect 的同口径注释）。 */
    const collectMetrics = (r: AutomationRunMetrics) => {
      hasFail = r.hasFail
      if (typeof r.total === 'number') {
        lastMetrics = {
          pass: r.pass ?? 0,
          fail: r.fail ?? 0,
          missing: r.missing ?? 0,
          not_applicable: r.notApplicable ?? 0,
          total: r.total,
          // 采样点数跟着 metrics 一起持久化 → 结果页与刷新后都能如实显示，
          // 不再依赖「刷新即丢」的那份内存样本（否则明明采到了却显示「—」）。
          sample_count: r.sampleCount ?? 0,
        }
      }
    }
    if (finalStatus === 'completed' && !stopRequested) {
      const okRun = await runStage(byId('run'), (p) => adapters.runAndCollect(p).then(collectMetrics))
      if (!okRun) finalStatus = 'failed'
    }

    while (finalStatus === 'completed' && !stopRequested && hasFail && loop < cfg.tuneRetries) {
      loop += 1
      // 流程4 调优：自动采纳推荐参数并写回；返回「是否真的采纳到了项」。
      let adopted = true
      const okTune = await runStage(byId('tune'), () => adapters.tuneOnce().then((r) => {
        adopted = r.adopted
        if (!r.adopted) {
          // 没有可采纳的推荐项：如实说明，直接结束循环进报告（不空转）
        emit('AUTOMATION_LOG', { stageId: 'tune', stageName: '调优确认及运行', status: 'running', message: `第 ${loop} 轮：无推荐参数可采纳，直接出报告`, level: 'info' })
        }
      }))
      if (!okTune) { finalStatus = 'failed'; break }
      // 无推荐参数可采纳 → 没法再调优，直接退出循环进报告
      if (!adopted) {
        emit('AUTOMATION_LOG', { stageId: 'tune', stageName: '调优确认及运行', status: 'success', message: '无推荐参数可采纳，按要求直接输出报告' })
        break
      }
      // 回流程3 重跑（重跑会用最新判定覆盖 metrics——结果卡展示的永远是**最后一轮**的真实统计）
      const okReRun = await runStage(byId('run'), (p) => adapters.runAndCollect(p).then(collectMetrics))
      if (!okReRun) { finalStatus = 'failed'; break }
      if (!hasFail) {
        emit('AUTOMATION_LOG', { stageId: 'run', stageName: '启动测试及结果分析', status: 'success', message: `第 ${loop} 轮调优后已全部通过`, level: 'success' })
      }
    }
    if (finalStatus === 'completed' && hasFail && loop >= cfg.tuneRetries) {
      // 达到调优重试上限仍不通过：按用户口径「无论结果都出报告」，如实播报后继续
      emit('AUTOMATION_LOG', { stageId: 'tune', stageName: '调优确认及运行', status: 'success', message: `已达到调优重试上限 ${cfg.tuneRetries} 次，仍有未达标项，按要求输出报告` })
    }

    // ── 流程5 报告生成 + 下载 ──
    //
    // ⚠️⚠️ 2026-10-05 用户口径：「**无论导出操作最终成功还是失败，都必须自动触发报告文件的
    // 下载**」。所以这里**去掉了 `finalStatus === 'completed'` 这个前置**——那是本轮之前的
    // 写法，流程 3 一失败整段被跳过，结果卡上「测试报告及产出」永远是 `—`，人拿不到报告
    // （用户实测截图：流程 3 失败 → 底部只有「重试/关闭」，没有报告入口）。
    //
    // 复用后端既有导出链路（**不自研**）：`adapters.generateReport` → `POST /api/reports/generate`
    // （模板缺失时后端出**占位 xlsm**，真文件可下载），`adapters.downloadReport` →
    // `GET /api/reports/{run_id}/download`。前端只负责触发与如实呈现状态。
    //
    // 三种情形：
    //   ① 跑完（completed）        → 正常出报告并下载
    //   ② 中途失败（failed）       → **也出报告并下载**：流程 1/2 已落库 → 轮次存在 →
    //                                报告是「失败快照」（表头取已落快照、判定缺失如实留空）
    //   ③ 未落到轮次（流程 1 就失败）→ 生成必然失败（后端 404 轮次不存在）→ 如实记失败原因，
    //                                **不假装下载成功**，结果卡据此不显示下载入口
    //   ④ 被终止（stopped）        → 同样尝试出报告（已采数据保留，出个快照比什么都拿不到强）
    //
    // ⚠️ 报告生成与下载**合并成一次 `runStage`**：此前是两次（同阶段跑两遍），
    // 日志里会出现两条「测试报告及产出」，观感上像两个阶段。
    let reportDownloaded = false
    /**
     * 报告阶段的真实结果，随 END 下发（结果卡据此显示「已生成/未生成 + 原因」）。
     * ⚠️ 显式标注类型：赋值发生在 `runStage` 的**闭包**里，TS 的控制流分析看不到，
     * 会把它一直窄化成初值 `'skipped'`，于是后面的比较全报「无重叠」。
     */
    let reportStatus: 'ok' | 'placeholder' | 'blocked' | 'skipped' = 'skipped' as
      | 'ok' | 'placeholder' | 'blocked' | 'skipped'
    let reportFile: string | null = null
    let reportReason: string | null = null

    // 终止时也出报告（已采数据保留，出一份快照比什么都拿不到强）。
    // ⚠️ `finalStatus` 此刻还不可能是 `'stopped'`（那是下面才赋的），
    // 所以这里只需判 `!stopRequested`——写成 `|| finalStatus === 'stopped'` 会被
    // TS 判为「类型无重叠」而编译不过，且逻辑上也是多余的。
    if (!stopRequested) {
      const okReport = await runStage(byId('report'), async () => {
        // ① 先生成（复用后端三档行为：ok / placeholder / blocked）
        const gen = await adapters.generateReport()
        reportStatus = gen.status
        reportFile = gen.file ?? null
        reportReason = gen.reason ?? null
        if (gen.status === 'blocked') {
          // 生成失败：不下载（没有文件可下）。抛出异常让 runStage 如实标 failed + 记原因。
          throw new Error(gen.reason ?? '报告生成失败')
        }
        // ② 再下载（同一个阶段内，保证「生成→下载」原子可见）
        const dl = await adapters.downloadReport()
        if (dl.blocked) {
          emit('AUTOMATION_DOWNLOAD_START', { stageId: 'report', stageName: '测试报告及产出', status: 'running', currentTask: '下载被浏览器拦截，请手动点击下载', message: 'blocked', level: 'warn' })
        } else {
          reportDownloaded = true
        }
      })
      // ⚠️ 报告阶段的成败**不回写 finalStatus**（本轮口径：测试失败 ≠ 报告失败，
      // 报告该出还是要出；报告出不来时结果卡单独如实说明，不把整轮判成另一个错）。
      if (!okReport && !reportReason) {
        reportReason = '报告阶段未能完成'
      }
    }

    if (stopRequested) finalStatus = 'stopped'

    runStatus = finalStatus
    finishedAt = Date.now()
    persist()
    // 下载成功事件：结果卡据此显示「报告已生成并下载」而非默认措辞（真实事件，不推断）
    if (reportDownloaded) {
      emit('AUTOMATION_DOWNLOAD_SUCCESS', { stageId: 'report', stageName: '测试报告及产出', status: finalStatus, currentTask: '报告已生成并下载' })
    }
    emit('AUTOMATION_END', {
      runId,
      stageId: currentStageId ?? '',
      stageName: '',
      status: finalStatus,
      currentTask: finalStatus === 'completed' ? '自动化测试流程已完成' : finalStatus === 'stopped' ? '已终止' : '已失败',
      // 结果卡要的真实数据：起止时刻（算耗时）+ 判定统计 + 报告三态
      startedAt,
      finishedAt,
      metrics: {
        ...lastMetrics,
        report_downloaded: reportDownloaded ? 1 : 0,
        // 报告状态也进 metrics（既有字段类型是 Record<string, number>，用数字编码）
        //  0=未产出  1=ok  2=placeholder
        report_status_code: reportStatus === 'ok' ? 1 : reportStatus === 'placeholder' ? 2 : 0,
      },
    })
    // 报告结果单独随日志给出（人能在日志流里看到「报告已生成 / 未生成 + 原因」）
    if (reportStatus === 'blocked') {
      emit('AUTOMATION_ERROR', { stageId: 'report', stageName: '测试报告及产出', status: 'failed', message: `报告未生成：${reportReason ?? '未知原因'}` })
    } else if (reportStatus !== 'skipped') {
      logger.info(`[automation] 报告已产出 status=${reportStatus} file=${reportFile ?? '—'}`)
    }
    logger.info(`[automation] 结束 run=${runId} status=${finalStatus} 耗时=${startedAt ? finishedAt - startedAt : 0}ms`)
    // 唯一一次换页：整轮结束后停到报告页（运行期由全屏浮层覆盖，不逐阶段换页）。
    // 失败/终止也跳——报告页是自然落脚点，且浮层结果卡会常驻说明原因。
    try {
      adapters.router.navigate(FINAL_ROUTE)
    } catch (e) {
      logger.error('[automation] 结束跳转报告页失败', e)
    }
    return { runId }
  }

  function byId(id: string): AutomationStageDef {
    return cfg.stages.find((s) => s.id === id) ?? cfg.stages[0]
  }

  async function stop(): Promise<void> {
    if (runStatus !== 'running') return
    stopRequested = true
    try {
      await adapters.cancel?.()
    } catch (e) {
      logger.error('[automation] 终止动作失败', e)
    }
  }

  /**
   * 从持久化恢复上次的 run（刷新后调用）。
   *
   * ⚠️ 刷新会把正在跑的 run **实质打断**（JS 上下文没了），所以恢复出的
   * `running` 一律如实降级为 `stopped` 并注明原因——不能显示成「还在跑」骗人。
   * 已结束的 `completed / failed / stopped` 原样恢复，仅用于展示结果卡。
   */
  function restore(): {
    runId: string | null
    stages: AutomationStage[]
    runStatus: AutomationRunStatus
    currentStageId: string | null
    startedAt: number | null
    finishedAt: number | null
    metrics: Record<string, number>
  } {
    const empty = {
      runId: null,
      stages: [] as AutomationStage[],
      runStatus: 'idle' as AutomationRunStatus,
      currentStageId: null,
      startedAt: null,
      finishedAt: null,
      metrics: {} as Record<string, number>,
    }
    try {
      const saved = adapters.storage.get(cfg.storageKey) as {
        runId?: string
        runStatus?: AutomationRunStatus
        currentStageId?: string | null
        stages?: AutomationStage[]
        startedAt?: number | null
        finishedAt?: number | null
        metrics?: Record<string, number>
      } | null
      if (!saved?.stages) return empty

      runId = saved.runId ?? null
      stages = saved.stages
      currentStageId = saved.currentStageId ?? null
      startedAt = saved.startedAt ?? null
      finishedAt = saved.finishedAt ?? null
      lastMetrics = saved.metrics ?? {}
      runStatus = saved.runStatus ?? 'idle'

      // 刷新导致的「假运行中」：如实降级为已终止（并在被中断的当前阶段上留痕）
      if (runStatus === 'running') {
        runStatus = 'stopped'
        finishedAt = finishedAt ?? Date.now()
        const interrupted = currentStageId ?? stages.find((s) => s.status === 'running')?.id
        if (interrupted) {
          stages = stages.map((s) =>
            s.id === interrupted
              ? { ...s, status: 'failed' as AutomationStageStatus, message: `${s.name} 因页面刷新中断`, endTime: Date.now() }
              : s.status === 'running'
                ? { ...s, status: 'skipped' as AutomationStageStatus }
                : s,
          )
        }
        persist()
      }
      return { runId, stages, runStatus, currentStageId, startedAt, finishedAt, metrics: lastMetrics }
    } catch (e) {
      logger.error('[automation] 恢复持久化状态失败', e)
      return empty
    }
  }

  return {
    start,
    stop,
    getRunStatus: () => runStatus,
    getStages: () => stages,
    getCurrentStageId: () => currentStageId,
    restore,
    on: (name, fn) => bus.on(name, fn),
  }
}
