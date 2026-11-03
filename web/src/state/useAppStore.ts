import { create } from 'zustand'
import { approveConfirmation, autoApproveConfirmation, rejectConfirmation } from '../features/remote/bridge'
import { collectFanMeasures, collectRunMeasures } from '../features/flow-run/collect'
import type { FanSample } from '../features/fan-trend/api'
import { mergeSamples } from '../features/fan-trend/samples'
/** 后端权威判定行（与 flow-run/api.ts 的 BackendVerdict 同形状，此处取别名便于切片声明） */
type AutomationVerdict = import('../features/flow-run/api').BackendVerdict
import {
  DEFAULT_SCENE_ID,
  loadCatalog,
  loadScene,
  pathOfScene,
  type CatalogNode,
} from '../data/loadScene'
import { MOCK_SCENE } from '../data/mock/motor.cooling-fan.fu6832'
import type { FlowState } from '../data/flows'
import { FLOW_IDS, type FlowId, type KnowledgeFilter, type ScenePackage } from '../data/types'
import {
  createAutomationOrchestrator,
  createEventBus,
  type AutomationAdapters,
  type AutomationPayload,
  type AutomationRunStatus,
  type AutomationStage,
  type Orchestrator,
} from '../features/automation/automationOrchestrator'

export type PanelView = 'canvas' | 'grid'

/** 参数值：数值型字段**必须**保持 number（左栏 Stepper 只认 number，见 fieldRegistry.validate） */
export type ParamValue = number | string

/**
 * 自动化结果卡的**真实数据**（全部来自编排器事件 payload）。
 *
 * 纪律：耗时由编排器给起止时刻、前端只做减法展示；判定统计取后端权威判定；
 * 失败原因取失败阶段的 message。**任何一项没取到就如实留空**，不编一个数。
 */
export interface AutomationSummary {
  runId: string | null
  startedAt: number | null
  finishedAt: number | null
  /** 失败时的原因（来自失败阶段 message / AUTOMATION_ERROR） */
  errorMessage: string | null
  /** 判定统计：来自 runAndCollect 的真实结果；未跑出判定时全 0
   *  ⚠️ `notApplicable`（本台架不适用）单列，绝不并入 pass/missing——
   *  「测不了」既不是「测过且合格」也不是「漏采」。 */
  metrics: { pass: number; fail: number; missing: number; notApplicable: number; total: number }
  /** 报告是否真下载成功（来自 AUTOMATION_DOWNLOAD_SUCCESS，不推断） */
  reportDownloaded: boolean
  /**
   * 报告产出的**真实状态**（2026-10-05 加：报告改成无论成败都出，得说清是哪一档）。
   *  `skipped` = 这一轮根本没走到报告阶段（如被终止前就停了）。
   */
  reportStatus: 'ok' | 'placeholder' | 'blocked' | 'skipped'
  /** 报告文件名（后端返回的 `file`）；未产出为 null */
  reportFile: string | null
  /** 报告未产出的原因（后端 `reason`），未产出时才有值 */
  reportReason: string | null
  /**
   * 本轮真实采到的样本条数（2026-10-08 新增，来自 runAndCollect 的 samples.length）。
   * 取不到时为 null，结果页显示「—」而不是 0。
   */
  sampleCount: number | null
  /** 调优闭环实际跑了几轮「采纳 → 回流程 3 重测」；0 表示一次都没进调优 */
  tuneRounds: number
  /** 本轮由自动化代确认的安全闸门条数（审计用；无代确认时为 0） */
  gateAckCount: number
}

/** 全屏运行台「执行动作」面板的一条动作（2026-10-08 新增）
 *
 *  来源有两类，按 `id` 合流到同一个列表（见 automationOrchestrator 的说明）：
 *    · 静态声明 `stage.tools`，由编排器按 promise 生命周期自动围栏；
 *    · 动态上报 `reportTool`，用于「采集 30% 档」这类运行时才知道粒度的动作。
 *  ⚠️ 状态**永远是真实调用状态**，不存在写死的动画脚本。
 */
export interface AutomationToolState {
  id: string
  label: string
  status: 'running' | 'done' | 'failed' | 'skipped'
  /** 失败/终止原因（如有），原样透传不美化 */
  message?: string
  /** 首次出现时刻（ms epoch），用于排序与「耗时」提示 */
  at: number
}

/** 执行日志流的一条（2026-10-08 新增） */
export interface AutomationLogEntry {
  /** 单调递增序号：作 React key，保证逐条入场动画稳定 */
  seq: number
  at: number
  level: 'info' | 'success' | 'warn' | 'error'
  /** 来源阶段 id；闸门代确认这类跨阶段动作用 'gate' */
  stageId: string
  message: string
}

/** 实时采集切片（2026-10-08 新增）
 *
 *  ⚠️ **不进持久化**：刷新后拿不回来，也不该假装还在跑。刷新后 UI 显示
 *  「本轮样本未保留，见已落库产物」，由编排器把 running 如实降级为 stopped。
 */
export interface AutomationLiveState {
  plan: import('../features/fan-trend/api').FanPlan | null
  samples: FanSample[]
}

export const EMPTY_AUTOMATION_SUMMARY: AutomationSummary = {
  runId: null,
  startedAt: null,
  finishedAt: null,
  errorMessage: null,
  metrics: { pass: 0, fail: 0, missing: 0, notApplicable: 0, total: 0 },
  reportDownloaded: false,
  reportStatus: 'skipped',
  reportFile: null,
  reportReason: null,
  sampleCount: null,
  tuneRounds: 0,
  gateAckCount: 0,
}

/* ---------------------------------------------------------------------------
   「浮层已被用户退出」的会话级持久化（2026-10-10 新增）。

   为什么用 sessionStorage 而不是 localStorage：它是**会话内的一次操作**，
   不该跨会话沿用；而演示时刷新页面很常见，若刷新后浮层又自己弹回来，
   「退出」就等于白点。sessionStorage 的作用域正好覆盖「本标签页会话」。
   --------------------------------------------------------------------------- */
const SS_OVERLAY_HIDDEN = 'omnitest.automation.overlay-hidden.v1'

function readOverlayHidden(): boolean {
  try {
    return sessionStorage.getItem(SS_OVERLAY_HIDDEN) === '1'
  } catch {
    /* 隐私模式等取不到 → 当没退出过（保守：宁可多显示一次浮层） */
    return false
  }
}

function writeOverlayHidden(v: boolean) {
  try {
    if (v) sessionStorage.setItem(SS_OVERLAY_HIDDEN, '1')
    else sessionStorage.removeItem(SS_OVERLAY_HIDDEN)
  } catch {
    /* 存不下就只在本会话内存里生效 */
  }
}

/** 日志流上限：跑满「4 档 × 最多 1 轮调优」（TUNE_RETRIES）也远用不到 200 条。
 *  封顶是为了不让长跑之后 DOM 无限膨胀；**不丢事实**——被挤掉的都是更早的
 *  过程行，最终结论与失败原因另有 summary/stages 承载。 */
const AUTOMATION_LOG_LIMIT = 200

/** 日志序号自增器（模块级）。作 React key，保证逐条入场动画稳定、不重复。 */
let automationLogSeq = 0

/**
 * 往执行日志流追加一条（模块级函数，供 store 内外共用）。
 *
 * 为什么要独立于 store action：`startAutomation` 里做闸门代确认时需要在
 * `set()` 之外逐条追加（同一个 tick 内多次写），走 action 会连续触发多次渲染。
 * 这里直接读最新 state 并一次合并写入，语义与 action 完全一致。
 */
function pushAutomationLog(level: AutomationLogEntry['level'], stageId: string, message: string): void {
  const entry: AutomationLogEntry = {
    seq: (automationLogSeq += 1),
    at: Date.now(),
    level,
    stageId,
    message,
  }
  useAppStore.setState((s) => {
    const next = [...s.automationLogs, entry]
    return {
      automationLogs: next.length > AUTOMATION_LOG_LIMIT ? next.slice(next.length - AUTOMATION_LOG_LIMIT) : next,
    }
  })
}

/* ===========================================================================
   红线动作与运行状态（第四轮接线）

   红线的原话：启动、停止、急停、写回参数、导出、归档六个动作只能人点，且必须
   经确认。落到前端就是两条纪律：
     1. 六个动作一律经 requestRedline() 排队，由人在确认卡上点「确认」才执行；
     2. 副驾（features/copilot、features/agent-chat）只允许调 requestRedline，
        不允许直接调 approveRedline——批准只能由人的点击触发。
   接了设备桥（c/components/spike-device-mcp）之后，批准动作再转发到桥的
   POST /confirmations/{token}/approve，凭据的四道约束仍只在桥里实现一次。

   2026-09-20 补第三条：批准要带 PIN。桥把鉴权拆成调用票（VITE_BRIDGE_TOKEN，
   进浏览器包）与批准权（BRIDGE_APPROVER_PIN，只在桥的服务端）两级。approveRedline
   因此要一个现场输入的 pin 实参，它从确认卡的输入框来，用完即弃：不存进 store、
   不写 localStorage、不进构建产物。没有 PIN 或 PIN 错，桥回 403，凭据保持 pending。
   依据：08a-开发接口契约-v1.0.md 第 3.4 节「两套确认机制，收口方案」。
   =========================================================================== */

export const REDLINE_ACTIONS = ['start', 'stop', 'estop', 'write_param', 'export', 'archive'] as const
export type RedlineAction = (typeof REDLINE_ACTIONS)[number]

export const REDLINE_LABEL: Record<RedlineAction, string> = {
  start: '启动测试',
  stop: '停止',
  estop: '急停',
  write_param: '写回参数',
  export: '导出',
  archive: '归档',
}

export interface RedlineRequest {
  action: RedlineAction
  /** 确认卡标题，用动作全名，不用代号 */
  title: string
  /** 一句话讲清点下去会发生什么，含物理后果 */
  prompt: string
  /** 参数摘要，一行内讲清这次要改什么 */
  argsSummary: string
  /** 破坏性动作：确认按钮走暗红 */
  danger?: boolean
  /**
   * 安全动作（如急停）：**确认卡不要求现场敲 PIN**，点「确认执行」即放行。
   *
   * ⚠️ 为什么急停要例外（2026-10-05 用户实测反馈「急停不需要填写 PIN，来不及」）：
   * 急停是**安全回路**——现场出状况时分秒必争，让人现场找 PIN、敲 6 位、
   * 输错还被锁 60 秒，与「立即切断驱动输出」的诉求直接相悖。
   * 但它仍是红线动作：**必须经确认卡**（防误触），只是放行通道从「人工 PIN」
   * 改为「自动化放行 token」（同 start 用的那条），台账记 `emergency_auto`，
   * 与 human_pin / automation 三者在日志里区分开，可审计。
   * 没配 `BRIDGE_AUTOMATION_TOKEN` 时桥回 503——此时急停会失败，属如实报错。
   */
  emergency?: boolean
  /** 设备桥签发的凭据。为空表示本轮走回放，没有真设备凭据可批。 */
  confirmToken?: string | null
  /** 凭据所属设备 id，批准时要用 */
  deviceId?: string
  /** 人点「确认」之后才执行的那段动作 */
  onApprove: () => void | Promise<void>
}

/** 流程 3 本轮运行状态机：待启动 → 运行中 → 出判定；停止与急停各有落点 */
export type RunPhase = 'idle' | 'running' | 'done' | 'stopped' | 'estopped'

export const RUN_PHASE_LABEL: Record<RunPhase, string> = {
  idle: '待启动',
  running: '运行中',
  done: '已出判定',
  stopped: '已停止',
  estopped: '已急停',
}

/** 本轮回放的推进时长：2.4 秒走满，够看清「运行中」这一态又不拖慢演示 */
const RUN_TICK_MS = 120
const RUN_TICKS = 20

/**
 * 确认人署名的默认值。真正生效的是 store 里的 operator 字段（可改），
 * 这里只是它的初值。署名只是署名：能不能批由批准 PIN 决定，不由这个名字决定。
 */
export const DEFAULT_OPERATOR = '张工'

interface AppState {
  sceneId: string
  /** 一级场景 / 二级子类 / 三级产品类型 */
  path: [string, string, string]
  scene: ScenePackage
  loading: boolean
  /** 产品三级级联目录，由 public/scenes/index.json 提供 */
  catalog: CatalogNode[]

  /** 参数覆盖值：`${flowId}.${groupId}.${subId}.${itemId}` → 值 */
  overrides: Record<string, ParamValue>
  /** Explicit synthetic draft provenance; follows overrides across stage navigation. */
  configSuggestionDemoDrafts: Record<string, boolean>
  /** 参数被人改过后来源标记转「人工」 */
  touched: Record<string, true>
  /** 已确认并锁定的流程 */
  confirmed: Partial<Record<FlowId, boolean>>

  /** 全局状态位 */
  benchBusy: boolean
  benchUser: string
  /** 安全联锁总闸：未满足项数，0 表示就绪 */
  interlockPending: number
  quota: string

  /** D 区 */
  model: string

  /* ------------------------------------------------------ 第三轮上提的四组字段 */

  /**
   * C 区视图，按流程各存一份：人手点过分段控件的流程记人的选择，
   * 没点过的流程留空、由场景包 ui.defaultView 或代码兜底决定。
   * 人工选择持久到 localStorage，刷新与切页都不回弹。
   */
  canvasView: Partial<Record<FlowId, PanelView>>
  /** 画板上当前选中的节点 id，无选中为 null（W3 消费） */
  canvasSelected: string | null
  /** 折叠状态记忆，键为 `${flowId}.${groupId}`，true 为展开（W4 消费） */
  collapse: Record<string, boolean>
  /** 知识库三轴筛选（W2 消费）；三个数组都空表示不过滤 */
  kbFilter: KnowledgeFilter
  /**
   * 知识库里「人已经看过」的条目 id 集合。
   *
   * 用途是给新导入的条目挂「新增」标识，看过之后就不再标。
   * **必须持久化**（localStorage）：不然一刷新，看过的又全变回「新增」，
   * 标识就失去意义了。只存 id、不存别的内容，条数大也不怕。
   */
  kbSeen: string[]
  /**
   * 「请求打开知识库上传面板」的跨组件信号。
   *
   * 为什么用 store 而不是直接跳页：左栏那个「上传」按钮在**流程页**里
   * （每个流程都会渲染 KnowledgeDrawer），而上传面板挂在**知识库页**。
   * 用户的诉求是「点了就上传一个文件」，不是「跳去另一个页面再自己找入口」。
   * 所以：置为 true → 跳 /knowledge → 知识库页看到信号就开面板 → 立刻复位。
   */
  kbUploadRequest: boolean

  /** 演示模式：只过滤展示面，不删场景包里的任何数据。默认开。 */
  demoMode: boolean

  /* ----------------------------------------------- 第四轮接线：闸门 / 运行 / 红线 */

  /** 安全确认闸门已勾条目的 id。跨左栏、闸门环、顶栏动作条共用这一份。 */
  gateAcked: string[]
  /** 本场景包里需要人工逐条确认的闸门条数（人员类 + 流程类），由左栏登记 */
  gateTotal: number
  /** 流程 3 本轮运行状态 */
  runPhase: RunPhase
  /** 运行进度 0–100 */
  runProgress: number
  /** 已完成第几轮；0 表示本会话还没跑过 */
  runRound: number
  /**
   * 本轮真采集到的现场实测量（键 = 判据 runtime_measures 变量名，如 rpm_mean /
   * fg1_freq_hz / fg2_freq_hz）。由 beginRun 真采集（flow-run/collect.ts）写入，
   * 判定求值时优先用它；采不到的量不在这里，判定落「未采集」。桥不可达 / demo 下为空。
   */
  runMeasures: Record<string, number>
  /** 排队等人确认的红线动作，同一时刻只允许一条 */
  redline: RedlineRequest | null
  /** 批准正在发往设备桥的途中 */
  redlineBusy: boolean
  /** 上一次红线动作失败的原因，确认卡上原样显示 */
  redlineError: string | null
  /**
   * 红线动作留痕：谁在什么时候、以什么渠道确认了什么。
   *   · human_pin        —— 现场有人敲过批准 PIN（普通红线动作）
   *   · emergency_auto   —— 急停（安全动作）走自动化放行 token，免现场 PIN（2026-10-05）
   *   · replay_no_bridge —— 桥未接入，只驱动页面回放
   * 三者分开记，台账可审计「这次是人工批的、急停自动放的、还是纯回放」。
   */
  redlineLog: {
    at: string
    action: RedlineAction
    title: string
    token: string | null
    by: string
    channel: 'human_pin' | 'emergency_auto' | 'replay_no_bridge'
  }[]
  /** 确认人署名。默认「张工」，可在确认卡上改；只做署名，不做鉴权。 */
  operator: string
  /**
   * 本会话与助手完成的对话轮数。上下文包的 session.transcript_summary 由它推出来：
   * 零轮时如实为 null，依赖该字段的按钮（流程 4 的「经验草稿」）据此置灰。
   * 此前这一项在 ActionDock 里写死 null，于是那枚按钮无论如何都亮不起来（07i 核验 P3）。
   */
  chatRounds: number
  /**
   * 知识库里当前选中的条目 id。副驾拿不到组件内的局部 useState，
   * 所以点选动作要落在 store 里，上下文包的 zoneB.selected_document 才有真值
   * （主文档 3.2.2 点名的前置改造：selected_* 必须上提）。
   */
  kbSelectedId: string | null
  /** 流程 4 勾选中的候选参数 key */
  adoptedKeys: string[]
  /** 候选的回显信息，键为参数 key。勾选时由流程 4 左栏登记，供顶栏动作条复用。 */
  adoptMeta: Record<string, { name: string; from: string; to: string; group: string }>
  /** 已确认采纳、待写回的候选。确认采纳（红线 write_param）之后才落这里。 */
  adoptedApplied: { key: string; name: string; from: string; to: string; group: string }[]
  /** 从流程 3 判定卡点进流程 4 时带上的判据 id */
  focusReq: string | null
  /**
   * 本场景最近一次落盘的轮次号（由流程 3 的 persistRun 写入）。
   * 采纳要挂在轮次上（param-change 是 tune 流程的产物，按主文档 4.1 收发表
   * 属于某一轮），没有它采纳就无处落库。刷新后这个值会丢，所以读回时
   * 不依赖它——见 flow-tune/adoptApi.ts 的 resolveRunId。
   */
  runId: string | null
  /** 流程 5 是否已生成报告 */
  reportGenerated: boolean
  /**
   * 报告表头的已填值（修 G-10）。
   *
   * 此前它是 `flow-report/panel.tsx` 里的**模块级变量**（`let header = {}` +
   * 自建订阅），刷新即丢——与「其它已确认参数都持久」不一致，人会以为
   * 「填了表头没保存」。现迁进 store，并按既有范式落 localStorage。
   */
  reportHeader: Record<string, string>
  /**
   * 已读回的**配置快照**值，键形如 `init.cp.调速.speed_mode`。
   *
   * 为什么要单独存一份（而不是只靠 `overrides`）：
   * `overrides` 是内存态，**换页与刷新就重建**；而下游流程要继承的是
   * 「初始化页确认过的基线」，它存在服务端快照里。只靠 `overrides` 回落，
   * 流程 3 永远继承不到（实测：快照里明明有 `init.cp.调速.speed_mode=NONEMODE`，
   * 流程 3 仍显示场景包原值 PWMMODE）。
   *
   * 只读缓存，给人看的与给回落用的都是它；**不参与写入**。
   */
  snapshotValues: Record<string, number | string>
  /** 一句话即时反馈，四秒后自散。只报实际发生的事，不报没做成的事。 */
  notice: string | null

  toggleGate: (id: string) => void
  /** 批量确认闸门（一键确认）：把给定 id 全并入已勾选集，不覆盖已勾的其它项 */
  ackAllGates: (ids: string[]) => void
  setGateTotal: (n: number) => void
  requestRedline: (req: RedlineRequest) => void
  /** pin 由人在确认卡上现场输入；接了桥且没给 pin 时直接报错，不发请求 */
  approveRedline: (pin: string) => Promise<void>
  rejectRedline: () => void
  setOperator: (name: string) => void
  /** 助手跑完一轮时记一笔，供上下文包算对话摘要 */
  noteChatRound: () => void
  setKbSelectedId: (id: string | null) => void
  setRunPhase: (p: RunPhase) => void
  beginRun: () => Promise<void>
  /** 真采集完成后写入本轮实测量（由 beginRun 内部调用，一般不必手动调） */
  setRunMeasures: (m: Record<string, number>) => void
  /**
   * 提交风扇台架实测样本（2026-10-08 新增）。
   *
   * 风扇实验是**异步长任务**（约 40~50 秒），beginRun 无法同步 await 到结束；
   * 由 FanTrendPanel 在 run 到达 terminal、拿到全部 samples 后调用本方法，
   * 内部聚合成台架实测量并**并入** runMeasures（不覆盖桥分支已采到的量）。
   */
  commitFanMeasures: (samples: FanSample[]) => void
  /**
   * 收口一轮运行：提交台架实测量 → 置终态 → 触发判定（2026-10-08 新增）。
   * 由 FanTrendPanel 在风扇实验 terminal / 失败时调用，保证判定时数据已就位。
   */
  settleRun: (samples: FanSample[], failed?: boolean) => void
  toggleAdopt: (key: string, meta?: { name: string; from: string; to: string; group: string }) => void
  /** 一键采纳：把给定推荐项全并入已采纳集（去重，不取消已勾的其它项） */
  adoptAllCandidates: (list: { key: string; name: string; from: string; to: string; group: string }[]) => void
  applyAdopt: (list: { key: string; name: string; from: string; to: string; group: string }[]) => void
  setFocusReq: (id: string | null) => void
  /** 记下本轮落盘后的 run_id，供采纳等下游产物挂载 */
  setRunId: (id: string | null) => void
  setReportGenerated: (v: boolean) => void
  /**
   * 整篇报告预览弹层是否打开（2026-09-30）。
   * 顶栏「预览」按钮此前是**假动作**（只置 reportGenerated + 跳页），
   * 现在改为打开这个弹层；弹层在报告页渲染，读到 store 里已确认/已装配的表头与真判定行。
   */
  reportPreviewOpen: boolean
  setReportPreviewOpen: (v: boolean) => void
  /** 写入/合并已读回的配置快照值（由 snapshotApi.loadLatestSnapshot 调用） */
  setSnapshotValues: (v: Record<string, number | string>) => void
  /** 改一个报告表头字段（空串表示清除该项） */
  setReportHeader: (key: string, value: string) => void
  /** 上游装配后批量回填表头（只覆盖取到值的项，不动人已手填的） */
  mergeReportHeader: (patch: Record<string, string>) => void
  setNotice: (n: string | null) => void

  /* ------------------------------------------ AI 助手权限档位（2026-10-10） */
  /**
   * 当前 AI 助手权限档位。全局单一来源：切换后同步到
   * ① 各 AgentChat 实例（Composer 高亮）② 上下文包 policy.permission
   * ③ 请求体 enabled_tools 的工具白名单。持久化在 `omnitest.permission.v1`。
   */
  permission: PermissionMode
  /** 切换权限档位（写 store + 落盘）；未变化的档位不触发更新 */
  setPermission: (p: PermissionMode) => void

  /* ------------------------------------------ 一键自动化测试流程（2026-09-30） */
  /** 自动化 run 整体状态 */
  automationRunStatus: AutomationRunStatus
  /** 自动化各阶段实时状态（供顶栏/大屏订阅渲染） */
  automationStages: AutomationStage[]
  /** 当前阶段 id */
  automationCurrentStageId: string | null
  /** 给 AI 助手播报的最新一条消息（订阅真实事件，不编造） */
  automationAnnouncement: string
  /**
   * 「已经点了智能测试、正在看引导屏、还没确认开始」。
   *
   * ⚠️ 为什么单独立一个位（2026-10-05 用户实测「点了就闪走」）：
   * 此前顶栏按钮 onClick 直接调 `startAutomation()`，编排器立刻开跑并逐阶段换页，
   * 界面一闪而过、什么都没有。现在点击只置这个位 → 弹引导屏（讲清五步 / 预计耗时 /
   * 会真下发设备启动）→ 人在屏上点「开始测试」才真调 `startAutomation()`。
   * 它只表示「引导屏该不该开」，**不代表任务已启动**。
   */
  automationIntent: boolean
  /**
   * 结果卡要的真实数据（起止时刻 / 判定统计 / 失败原因）。
   * 全部来自编排器事件 payload，**前端不自己算耗时、不编数字**。
   */
  automationSummary: AutomationSummary
  /**
   * 全屏运行台「执行动作」面板的数据（2026-10-08 新增）。
   * 由 AUTOMATION_TOOL 事件驱动；静态声明与适配器动态上报按 id 合流。
   */
  automationTools: AutomationToolState[]
  /** 全屏运行台「执行日志」流；封顶 AUTOMATION_LOG_LIMIT 条 */
  automationLogs: AutomationLogEntry[]
  /** 实时采集切片（plan + 累积 samples），1Hz 更新；**不持久化** */
  automationLive: AutomationLiveState
  /** 本轮后端权威判定（最后一次 runAndCollect 的结果），供右栏判据列表渲染 */
  automationVerdicts: AutomationVerdict[]
  /** 本轮由自动化代确认的安全闸门 id（审计用） */
  automationGateAcks: string[]
  /**
   * 「本轮浮层已被用户退出」（2026-10-10 新增）。
   *
   * 为什么单独立一个位、而不是复用 `clearAutomation()`：后者会把
   * `automationRunStatus` 复位成 `idle`，运行中直接用它会出现双重故障——
   * ① 运行台数据被清空；② 下一条编排器事件立刻把 runStatus 回写成 running，
   * 浮层当场弹回来。所以运行中退出走**软退出**：只隐藏浮层，不清任何数据、
   * 不删持久化，后台编排器继续跑完。
   *
   * ⚠️ 它只拦**渲染**，不拦 store 同步：`_syncAutomation` 与事件订阅保持原样，
   * 顶栏因此仍能读到真实运行信号（按钮显示「回到运行台」），
   * 但浮层不会因为后台事件而自己弹回来。
   */
  automationOverlayHidden: boolean
  /** 运行中退出浮层（软退出）：只置该位，不清数据、不发任何停止指令 */
  hideAutomationOverlay: () => void
  /**
   * 置引导位。⚠️ 置 `true` 时**同时清掉「浮层已隐藏」**——它是「重新进入浮层」
   * 的唯一入口（顶栏按钮第三态「回到运行台」也走这里），不清就会出现
   * 「点了回到运行台却什么都没发生」。
   */
  setAutomationIntent: (v: boolean) => void
  /** 启动自动化。幂等：已在跑则 setNotice「自动化测试正在进行中」 */
  startAutomation: () => void
  /** 终止自动化 */
  stopAutomation: () => void
  /** 关闭结果卡/引导屏：复位 runStatus 与 summary，并清掉本地持久化。
   *  ⚠️ 只清「自动化运行态」，**不动已落库的产物**（快照/基线/判定/报告都还在）。 */
  clearAutomation: () => void
  /** 刷新后恢复上次的自动化运行态（Shell 挂载时调一次）。 */
  restoreAutomation: () => void
  /** 编排器内部回调：把阶段状态/播报/运行状态写回 store（由编排器事件订阅触发，不手动调） */
  _syncAutomation: (
    runStatus: AutomationRunStatus,
    stages: AutomationStage[],
    currentStageId: string | null,
    announcement: string,
    summary: AutomationSummary,
  ) => void

  setCanvasView: (flow: FlowId, v: PanelView) => void
  setDemoMode: (on: boolean) => void
  setCanvasSelected: (id: string | null) => void
  setCollapse: (key: string, open: boolean) => void
  setKbFilter: (patch: Partial<KnowledgeFilter>) => void
  /** 把某条知识标记为「已看过」（点开详情时调用），「新增」角标随之消失 */
  markKbSeen: (id: string) => void
  /** 整批标记已看过（点「只看新增 · 点此取消」时调用）：一次并入 kbSeen 并持久化，幂等 */
  markKbSeenBatch: (ids: string[]) => void
  /** 请求打开知识库上传面板（左栏「上传」按钮调用；知识库页消费后复位） */
  requestKbUpload: (on: boolean) => void

  selectProduct: (path: [string, string, string], sceneId?: string) => void
  setParam: (key: string, v: ParamValue) => void
  confirmFlow: (flow: FlowId) => void
  unconfirmFlow: (flow: FlowId) => void
  setModel: (m: string) => void
  /** 启动时把目录与默认场景包读进来（真实包在 public/scenes/ 下） */
  bootstrap: () => void
}

/** 折叠状态记忆的键：流程 × 分组。flow 放宽为 string，供知识库等非五流程面板复用。 */
export const collapseKey = (flow: FlowId | string, group: string) => `${flow}.${group}`

export const paramKey = (flow: FlowId, group: string, sub: string, item: string) =>
  `${flow}.${group}.${sub}.${item}`

/**
 * 跨流程取参数的**回落链**（修 G-11）。
 *
 * 背景：`paramKey` 带 flow 前缀，所以流程 2 改的值存在 `init.cp.*`、
 * 流程 3 读的是 `run.cp.*`——**两套键互不可见**，人在初始化页确认过的值
 * 传不到下游流程。这与「初始化配置是下游基线的来源」这个业务语义相悖。
 *
 * 修法**不动 key 结构**：改 `paramKey` 会让已有快照、`touched`、产物全部失配
 * （`snapshotApi.ts` 里 `init.cp.*` / `init.rp.header.*` 是硬编码的）。
 * 所以改成**读的时候多回看一道**：
 *
 *     flow 自己的 override  →  上游流程的 override  →  场景包原值
 *
 * 语义解释：**自己改过就用自己改的；没改过就继承上游确认过的值**。
 * 这既修好了传递，又不会把「本流程独立改过的值」覆盖掉。
 *
 * ⚠️ 上游只要 `init`。因为按业务契约，配置快照（init 的产物）是
 * tune / report 的输入基线；流程 3（run）的基线同理来自 init。
 *
 * @param flow    当前流程
 * @param group   分组段（如 'cp' 控制参数 / 'pa' 本体属性 / 'rp' 报告表头）
 * @param sub     子段（如分组名，或 'header'）
 * @param item    条目 key
 * @param overrides store 的 overrides
 * @returns 命中的**键**与来源；都没命中返回 `source: 'none'`
 */
export function resolveParamKey(
  flow: FlowId,
  group: string,
  sub: string,
  item: string,
  overrides: Record<string, number | string>,
  /** 已读回的配置快照值（key 形如 `init.cp.调速.speed_mode`）。
   *  **必须有这一档**：`overrides` 是内存态，换页/刷新后 `init.*` 就没了，
   *  只靠它回落，流程 3 永远继承不到初始化页的值（实测栽过）。 */
  snapshot?: Record<string, number | string>,
): { key: string; value: number | string | undefined; source: FlowId | 'none' } {
  const own = paramKey(flow, group, sub, item)
  if (overrides[own] !== undefined) return { key: own, value: overrides[own], source: flow }
  // 上游回落：init 是配置快照的产生方，按契约是下游的基线来源。
  // 先看内存态（同一次会话里改过），再看已落盘快照（换页/刷新后仍然在）。
  if (flow !== 'init') {
    const up = paramKey('init', group, sub, item)
    if (overrides[up] !== undefined) return { key: up, value: overrides[up], source: 'init' }
    if (snapshot && snapshot[up] !== undefined) {
      return { key: up, value: snapshot[up], source: 'init' }
    }
  }
  return { key: own, value: undefined, source: 'none' }
}

/* --------------------------------------------------- 人工选择的本地持久化

   没有后端，人摆过的版式与模式只能落在浏览器本地：换机器、清缓存即丢，
   这是《第三轮实施计划》第六节风险 5 已拍板的取法（甲案）。
   读写一律包 try/catch：隐私窗口与禁用站点数据时 localStorage 会直接抛。 */

const LS_CANVAS_VIEW = 'omnitest.canvasView.v1'
const LS_DEMO_MODE = 'omnitest.demoMode.v1'

function readCanvasView(): Partial<Record<FlowId, PanelView>> {
  try {
    const raw = localStorage.getItem(LS_CANVAS_VIEW)
    if (!raw) return {}
    const j = JSON.parse(raw) as Record<string, unknown>
    const out: Partial<Record<FlowId, PanelView>> = {}
    for (const f of FLOW_IDS) {
      const v = j[f]
      if (v === 'canvas' || v === 'grid') out[f] = v
    }
    return out
  } catch {
    return {}
  }
}

function writeCanvasView(v: Partial<Record<FlowId, PanelView>>) {
  try {
    localStorage.setItem(LS_CANVAS_VIEW, JSON.stringify(v))
  } catch {
    /* 存不下就只在本次会话里生效，不报错、不影响渲染 */
  }
}

/* 报告表头（修 G-10）。此前是 flow-report 的模块级变量，刷新即丢；
   迁进 store 后持久，与「其它已确认参数都持久」保持一致。
   ⚠️ 2026-09-30：原先还存了「导出格式」(fmt)，随「导出」功能一并删除；
   读取仍**兼容旧键形状**（老 localStorage 里是 {header, fmt}），只是忽略 fmt、
   写入时不再带它——否则老用户的旧记录会让首次读崩。 */
const LS_REPORT = 'omnitest.report.v1'

function readReport(): { header: Record<string, string> } {
  try {
    const raw = localStorage.getItem(LS_REPORT)
    if (!raw) return { header: {} }
    const j = JSON.parse(raw) as { header?: unknown }
    const header: Record<string, string> = {}
    if (j.header && typeof j.header === 'object') {
      for (const [k, v] of Object.entries(j.header as Record<string, unknown>)) {
        if (typeof v === 'string' && v) header[k] = v
      }
    }
    return { header }
  } catch {
    return { header: {} }
  }
}

function writeReport(header: Record<string, string>) {
  try {
    localStorage.setItem(LS_REPORT, JSON.stringify({ header }))
  } catch {
    /* 存不下就只在本次会话生效 */
  }
}

/* AI 助手权限档位（2026-10-10 权限切换修复）。

   为什么放到全局 store 并持久化：
   - 此前权限是 AgentChat 组件内的 state，且**没有一路传到后端**——切档只改 UI
     高亮，模型侧永远看到上下文包里写死的 readonly（详见根因报告）。
   - 现在提升为全局、单一来源：切档立即写 store + 落盘；AgentChat（各宿主）、
     上下文包 envelope、请求体 enabled_tools 三处都读它。
   - 用户已确认「全局记忆一档」：刷新/切页/换对话后保持上次选的档位。
   值用 PermissionLevel 的三档字符串；读回时非法值一律回落 'readonly'（安全默认）。 */
const LS_PERMISSION = 'omnitest.permission.v1'

export type PermissionMode = 'readonly' | 'params' | 'hardware'

function readPermission(): PermissionMode {
  try {
    const raw = localStorage.getItem(LS_PERMISSION)
    if (raw === 'readonly' || raw === 'params' || raw === 'hardware') return raw
    return 'readonly'
  } catch {
    return 'readonly'
  }
}

function writePermission(p: PermissionMode) {
  try {
    localStorage.setItem(LS_PERMISSION, p)
  } catch {
    /* 存不下就只在本次会话生效 */
  }
}

/* 知识库「已看过」集合。键与做法同上面几条：换机器/清缓存即丢，
   丢了的表现是「看过的条目又标回新增」——可接受，不影响功能。 */
const LS_KB_SEEN = 'omnitest.kbSeen.v1'

function readKbSeen(): string[] {
  try {
    const raw = localStorage.getItem(LS_KB_SEEN)
    if (!raw) return []
    const j = JSON.parse(raw)
    return Array.isArray(j) ? j.filter((x): x is string => typeof x === 'string') : []
  } catch {
    return []
  }
}

function writeKbSeen(ids: string[]) {
  try {
    localStorage.setItem(LS_KB_SEEN, JSON.stringify(ids))
  } catch {
    /* 同上：存不下只在本次会话有效 */
  }
}

/* 知识库三轴筛选。用户实测：刷新后筛选条件全丢、又得重选一遍。
   与上面几条同范式；只认三个已知轴的白名单值，脏数据一律剔除，
   不把坏值带进界面（否则 filterKnowledge 会过滤出空列表，看起来像"库空了"）。 */
const LS_KB_FILTER = 'omnitest.kb.filter.v1'

function readKbFilter(): KnowledgeFilter {
  const empty: KnowledgeFilter = { usage: [], origin: [], owner: [] }
  try {
    const raw = localStorage.getItem(LS_KB_FILTER)
    if (!raw) return empty
    const j = JSON.parse(raw) as { usage?: unknown; origin?: unknown; owner?: unknown }
    // 白名单只认固定枚举（与 KNOWLEDGE_USAGE_LABEL / KNOWLEDGE_ORIGIN_LABEL 的键一致）
    const pick = <T extends string>(v: unknown, allow: readonly T[]): T[] =>
      Array.isArray(v) ? v.filter((x): x is T => allow.includes(x as T)) : []
    return {
      usage: pick(j.usage, ['spec', 'requirement', 'process'] as const),
      origin: pick(j.origin, ['doc', 'experience'] as const),
      owner: Array.isArray(j.owner) ? j.owner.filter((x): x is string => typeof x === 'string') : [],
    }
  } catch {
    return empty
  }
}

function writeKbFilter(f: KnowledgeFilter) {
  try {
    localStorage.setItem(LS_KB_FILTER, JSON.stringify(f))
  } catch {
    /* 同上 */
  }
}

/* 知识库选中条目 + 左栏展开态。刷新后保持上次所见，不再回落到初始值。 */
const LS_KB_SELECTED = 'omnitest.kb.selected.v1'
const LS_COLLAPSE = 'omnitest.collapse.v1'

function readKbSelected(): string | null {
  try {
    const raw = localStorage.getItem(LS_KB_SELECTED)
    return raw && raw.trim() ? raw : null
  } catch {
    return null
  }
}

function writeKbSelected(id: string | null) {
  try {
    if (id) localStorage.setItem(LS_KB_SELECTED, id)
    else localStorage.removeItem(LS_KB_SELECTED)
  } catch {
    /* 同上 */
  }
}

function readCollapse(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(LS_COLLAPSE)
    if (!raw) return {}
    const j = JSON.parse(raw) as Record<string, unknown>
    const out: Record<string, boolean> = {}
    for (const [k, v] of Object.entries(j)) {
      if (typeof v === 'boolean') out[k] = v
    }
    return out
  } catch {
    return {}
  }
}

function writeCollapse(m: Record<string, boolean>) {
  try {
    localStorage.setItem(LS_COLLAPSE, JSON.stringify(m))
  } catch {
    /* 同上 */
  }
}

/** 演示模式默认开；地址栏 `?mode=full` 仍然直接强制全量，供评审与截图对照 */
function readDemoMode(): boolean {
  try {
    if (typeof window !== 'undefined') {
      const q = new URLSearchParams(window.location.search).get('mode')
      if (q === 'full') return false
      if (q === 'demo') return true
    }
    return localStorage.getItem(LS_DEMO_MODE) !== 'full'
  } catch {
    return true
  }
}

function writeDemoMode(on: boolean) {
  try {
    localStorage.setItem(LS_DEMO_MODE, on ? 'demo' : 'full')
  } catch {
    /* 同上 */
  }
}

/* ------------------------------------------------------ 确认态的本地持久化

   ⚠️ 2026-09-28 用户实测反馈：**「一打开网页就自动帮我锁上，刷新也锁」**。

   成因：确认态此前**没有任何持久化**，而两条读回逻辑（`Shell.tsx` 的
   `useGlobalSnapshot`、`flow-req` 的 `useRestoreBaseline`）在读到服务端产物时
   直接 `confirmFlow(...)`。于是「服务端存在 locked:true 的快照」被当成
   「本次应显示已确认」——只要历史上确认过一次，之后**每次打开都是已锁**，
   人根本没机会在首次进入时自己按一次。

   正确语义（用户拍板）：
     - **首次进入（本浏览器没确认过）→ 未确认态**，由人自己按；
     - 人按过之后 → **持久化**，刷新、重开都保持「已确认」；
     - 点「解除确认」→ 同样持久化，刷新后仍是未确认。

   所以确认态必须**自己持久化**，而不是从「有没有产物」反推。
   与 `kbSeen` / `reportHeader` 用同一套范式（`LS_*` + try/catch 成对读写）。

   为什么按**流程**分别记（而不是一个总开关）：`init` 与 `req` 的确认是
   两件独立的事，人可能只确认了初始化就先去干别的，不该把两级一起点亮。 */
const LS_CONFIRMED = 'omnitest.confirmed.v1'

function readConfirmed(): Partial<Record<FlowId, boolean>> {
  try {
    const raw = localStorage.getItem(LS_CONFIRMED)
    if (!raw) return {}
    const j = JSON.parse(raw) as Record<string, unknown>
    const out: Partial<Record<FlowId, boolean>> = {}
    for (const f of FLOW_IDS) {
      if (j[f] === true) out[f] = true
      // 显式的 false 也要留着：它表示「人主动解除过」，
      // 与「从没确认过」在语义上不同（前者不该被服务端旧产物重新点亮）。
      else if (j[f] === false) out[f] = false
    }
    return out
  } catch {
    return {}
  }
}

function writeConfirmed(v: Partial<Record<FlowId, boolean>>) {
  try {
    localStorage.setItem(LS_CONFIRMED, JSON.stringify(v))
  } catch {
    /* 存不下就只在本次会话生效 */
  }
}

export const useAppStore = create<AppState>((set) => ({
  sceneId: DEFAULT_SCENE_ID,
  path: ['电机', '散热风扇', 'FU6832 散热风扇驱动板'],
  scene: MOCK_SCENE,
  loading: false,
  catalog: [],

  overrides: {},
  configSuggestionDemoDrafts: {},
  touched: {},
  /**
   * 确认态从 localStorage 起（见 LS_CONFIRMED 的说明）。
   * 首次进入读不到记录 → `{}` → 各流程都是「未确认」，由人自己按。
   * 注意**不再预置 `{ init: false }`**：显式 false 表示「人解除过」，
   * 而首进应该是「从没确认过」，两者在 UI 上虽同样显示未确认，
   * 但写回 localStorage 时前者会盖掉「从未确认」这个事实。
   */
  confirmed: readConfirmed(),

  benchBusy: false,
  benchUser: '张工',
  interlockPending: 0,
  quota: '额度 82%',

  model: 'deepseek-v4.1-flash',

  canvasView: readCanvasView(),
  demoMode: readDemoMode(),
  canvasSelected: null,
  collapse: readCollapse(),
  kbFilter: readKbFilter(),
  kbSeen: readKbSeen(),
  kbUploadRequest: false,

  gateAcked: [],
  gateTotal: 0,
  runPhase: 'idle',
  runProgress: 0,
  runRound: 0,
  runMeasures: {},
  redline: null,
  redlineBusy: false,
  redlineError: null,
  redlineLog: [],
  operator: DEFAULT_OPERATOR,
  chatRounds: 0,
  kbSelectedId: readKbSelected(),
  adoptedKeys: [],
  adoptMeta: {},
  adoptedApplied: [],
  focusReq: null,
  runId: null,
  reportGenerated: false,
  reportPreviewOpen: false,
  reportHeader: readReport().header,
  snapshotValues: {},
  notice: null,
  permission: readPermission(),
  automationRunStatus: 'idle',
  automationStages: [],
  automationCurrentStageId: null,
  automationAnnouncement: '',
  automationIntent: false,
  automationSummary: { ...EMPTY_AUTOMATION_SUMMARY },
  automationTools: [],
  automationLogs: [],
  automationLive: { plan: null, samples: [] },
  automationVerdicts: [],
  automationGateAcks: [],
  // 刷新后保持「已退出」态：本次会话里人点过退出，刷新不该让浮层自己再弹回来
  automationOverlayHidden: readOverlayHidden(),

  toggleGate: (id) =>
    set((s) => {
      const gateAcked = s.gateAcked.includes(id)
        ? s.gateAcked.filter((x) => x !== id)
        : [...s.gateAcked, id]
      // 顶栏那枚盾形徽章读的就是这个数：勾一条少一条，不另存一份口径
      return { gateAcked, interlockPending: Math.max(0, s.gateTotal - gateAcked.length) }
    }),
  setGateTotal: (n) =>
    set((s) =>
      s.gateTotal === n ? {} : { gateTotal: n, interlockPending: Math.max(0, n - s.gateAcked.length) },
    ),
  /**
   * 一键确认：把给定 id 全并入已勾选集（去重，不覆盖已勾的其它项）。
   * ⚠️ 只改「勾选态」，**不绕过红线**——「启动测试」仍要走确认卡。
   */
  ackAllGates: (ids) =>
    set((s) => {
      const merged = new Set(s.gateAcked)
      for (const id of ids) merged.add(id)
      const gateAcked = [...merged]
      return { gateAcked, interlockPending: Math.max(0, s.gateTotal - gateAcked.length) }
    }),

  requestRedline: (req) => set({ redline: req, redlineError: null }),
  rejectRedline: () => {
    const req = useAppStore.getState().redline
    set({ redline: null, redlineBusy: false, redlineError: null })
    // 驳回也要通知桥，让那张凭据落到 rejected，别挂到超时
    if (req?.confirmToken) void rejectConfirmation(req.confirmToken, '操作员在页面上驳回').catch(() => null)
    resolveRedlineWaiter(false)
  },
  approveRedline: async (pin: string) => {
    const st0 = useAppStore.getState()
    const req = st0.redline
    if (!req) return
    // 安全动作（急停）走自动化放行通道，**不要求现场敲 PIN**——来不及（用户实测口径）。
    // 其它红线动作照旧：接了桥就必须有 PIN。先拦一道不是当闸口（真闸口在桥上），
    // 而是别拿空 PIN 去撞桥的连错计数，把人自己锁掉。
    if (req.confirmToken && !req.emergency && !pin.trim()) {
      set({ redlineError: '请先输入批准 PIN（取自设备桥 .env 的 BRIDGE_APPROVER_PIN，不在本页面里）' })
      return
    }
    set({ redlineBusy: true, redlineError: null })
    try {
      // 接了设备桥就把批准转发过去，不在前端另起一套凭据：红线的四道约束
      // （单次使用、180 秒过期、绑工具名、绑参数指纹）只在桥里实现一次。
      // · 急停（emergency）→ autoApproveConfirmation，走 x-automation-token 放行，
      //   台账记 emergency_auto；未配 BRIDGE_AUTOMATION_TOKEN 时桥回 503，如实抛错。
      // · 其它 → approveConfirmation，PIN 只在这一行里过一次手，不留任何副本。
      if (req.confirmToken) {
        if (req.emergency) await autoApproveConfirmation(req.confirmToken, st0.operator)
        else await approveConfirmation(req.confirmToken, st0.operator, pin, req.title)
      }
      await req.onApprove()
      set((s) => ({
        redline: null,
        redlineBusy: false,
        redlineLog: [
          {
            at: new Date().toISOString(),
            action: req.action,
            title: req.title,
            token: req.confirmToken ?? null,
            by: st0.operator,
            channel: !req.confirmToken
              ? ('replay_no_bridge' as const)
              : req.emergency
                ? ('emergency_auto' as const)
                : ('human_pin' as const),
          },
          ...s.redlineLog,
        ].slice(0, 50),
      }))
      resolveRedlineWaiter(true)
    } catch (e) {
      set({ redlineBusy: false, redlineError: e instanceof Error ? e.message : String(e) })
    }
  },
  setOperator: (name) => set({ operator: name.trim() || DEFAULT_OPERATOR }),
  noteChatRound: () => set((s) => ({ chatRounds: s.chatRounds + 1 })),
  setKbSelectedId: (kbSelectedId) => {
    writeKbSelected(kbSelectedId)
    set({ kbSelectedId })
  },

  setRunPhase: (runPhase) => set({ runPhase }),
  setRunMeasures: (runMeasures) => set({ runMeasures }),
  commitFanMeasures: (samples) => {
    // 聚合本轮台架实测（PWM 占空比精度/频率/电压/有效档数）。采不到时返回空对象，
    // 此时保持原有 runMeasures 不动（可能含桥分支采到的转速），不把已有的量清掉。
    const bench = collectFanMeasures(samples)
    if (!Object.keys(bench).length) return
    set((s) => ({ runMeasures: { ...s.runMeasures, ...bench } }))
  },
  beginRun: async () => {
    set({ runPhase: 'running', runProgress: 0, runMeasures: {} })
    // 真采集（先采数，再推进进度）：调设备桥 read_fg 读转速/频率。
    // 桥不可达 / 未真连 / 电机未转 → 返回空，判定如实落「未采集」，不阻塞演示。
    // 先采后判，保证 VerdictCard 在 running→done 触发求值时 runMeasures 已就位
    // （否则又是「异步读回覆盖同步写入」那一类时序坑）。
    //
    // ⚠️ 台架量（TR-BENCH-*）不在这里采：风扇实验是约 40~50 秒的异步长任务，
    // 本函数只负责启动与进度推进。真正的台架实测量由 FanTrendPanel 在 run 到达
    // terminal 后调 commitFanMeasures 写入——但那样就晚于本函数的 runPhase='done'。
    // 因此 FanTrendPanel 必须在提交完 measures 之后才把 runPhase 置 done（见该组件）。
    const measures = await collectRunMeasures()
    set({ runMeasures: measures })
    // 进度条推进到 95% 封顶后停住，**不自动置 done**（2026-10-08 改）。
    // 原因：本函数只能估计"看起来在跑"，而判定必须等风扇实验真正跑完、台架实测量
    // 落袋。原先 2.4 秒就置 done 会抢在实验结束（40~50 秒）之前触发判定，
    // 判定只能落「未采集」。现在收口统一交给 settleRun（由 FanTrendPanel 在实验
    // terminal 时调用）：先提交台架量，再置 done，保证判定时数据已就位。
    let i = 0
    const timer = window.setInterval(() => {
      i += 1
      const st = useAppStore.getState()
      // 中途被停止/急停，或已由 settleRun 收口，就不再推进
      if (st.runPhase !== 'running') {
        window.clearInterval(timer)
        return
      }
      if (i >= RUN_TICKS) {
        // 走满也不出判定：停在 95% 等实验真正结束（避免长任务下进度条卡 100% 却无结论）
        window.clearInterval(timer)
        set({ runProgress: 95 })
      } else {
        set({ runProgress: Math.round((i / RUN_TICKS) * 100) })
      }
    }, RUN_TICK_MS)
  },

  /**
   * 收口一轮运行（2026-10-08 新增）：提交台架实测量 → 置终态 → 触发判定。
   *
   * 由 FanTrendPanel 在风扇实验到达 terminal 时调用，顺序不可颠倒：
   * 必须先 `commitFanMeasures` 把台架量写进 runMeasures，再置 runPhase='done'
   * —— 因为 VerdictCard 的判定 effect 是监听 `running→非running` 边沿触发的，
   * 一旦先置 done，判定会立刻用**还没有台架量**的 measures 求值，结论又变「未采集」。
   */
  settleRun: (samples, failed) => {
    const st0 = useAppStore.getState()
    // 仅在本轮确实在运行时收口。⚠️ RunPhase 类型不含 'stopping'（那是 FanPhase 的值），
    // 原写法 `!== 'stopping'` 恒真且触发 TS2367，2026-10-08 移除该冗余判断。
    if (st0.runPhase !== 'running') return
    // ① 先落台架实测量（commitFanMeasures 内部采不到时不动 runMeasures）
    const bench = collectFanMeasures(samples)
    const nextMeasures = Object.keys(bench).length
      ? { ...st0.runMeasures, ...bench }
      : st0.runMeasures
    // ② 再置终态：失败落 estopped（判定 effect 同样会触发，但只出已有结论）
    set((s) => ({
      runMeasures: nextMeasures,
      runProgress: 100,
      runPhase: failed ? 'estopped' : 'done',
      runRound: s.runRound + 1,
    }))
  },

  toggleAdopt: (key, meta) =>
    set((s) => ({
      adoptedKeys: s.adoptedKeys.includes(key)
        ? s.adoptedKeys.filter((x) => x !== key)
        : [...s.adoptedKeys, key],
      adoptMeta: meta ? { ...s.adoptMeta, [key]: meta } : s.adoptMeta,
    })),
  /**
   * 一键采纳：把给定推荐项全并入已采纳集（与 ackAllGates 同款「去重、不取消已勾」）。
   *
   * 为什么用「并入」而不是「覆盖」：人可能已手工勾了别的项，「一键采纳」的语义是
   * 「把推荐全勾上」而非「只勾推荐、清掉人工项」。与闸门的一键确认同一口径。
   * adoptMeta 一并写入，否则顶栏动作条读不到「宏名 原值→新值」，回显缺一截。
   */
  adoptAllCandidates: (list) =>
    set((s) => {
      const keys = new Set(s.adoptedKeys)
      const meta = { ...s.adoptMeta }
      for (const x of list) {
        keys.add(x.key)
        meta[x.key] = { name: x.name, from: x.from, to: x.to, group: x.group }
      }
      return { adoptedKeys: [...keys], adoptMeta: meta }
    }),
  /**
   * 读回服务端已落库的采纳记录。
   *
   * ⚠️ 必须**同时**回填 `adoptedKeys` 与 `adoptMeta`，不能只写 `adoptedApplied`：
   * 界面上勾选框读的是 `adoptedKeys`（见 flow-tune/panel.tsx 的 RecRow：
   * `useAdopted().has(c.param.key)`），而 `adoptedApplied` 只被「参数变更」卡
   * 那类展示消费。此前只写后者 → 刷新后数据其实读回来了，**勾选框却全灭**，
   * 表现为「采纳没保存」（后端产物明明在）。这是 3-Z 验收 5 代跑时抓到的真缺陷。
   *
   * `adoptMeta` 一并回填的理由：顶栏动作条要按它摆「宏名 原值→新值」，
   * 不回填则刷新后回显缺一截。
   */
  applyAdopt: (list) =>
    set((s) => {
      // 4→3 回环：采纳的建议值要真写进控制参数，流程 3 的 ParamRow 才能读到。
      // 键与 ParamRow 读的同一把（paramKey('run','cp', group, key)）。
      // group 随采纳数据自包含（勾选时登记、落库时写入、读回时带回），
      // **不在这里反查 getPack()**：刷新后 useGlobalAdoption 读回可能早于
      // 场景包加载完成，getPack() 还是 null，反查会静默丢值（实测栽过）。
      // 只写「to 是数值」的建议：「人工判定」这类无具体数值的 to 是 NaN，跳过，
      // 避免把流程 3 的下拉/布尔项顶成非法值。
      //
      // ⚠️ 2026-10-08 修：原先写的是 `overrides[k] = x.to`，而 x.to 一律是**字符串**
      // （adoptAll 用 String(fmt(...)) 拼的，param-change 产物读回来也是字符串）。
      // 于是判据求值时：前端 JS `'1.08' >= 1.0` 会隐式转换 → 判通过；
      // 后端 Python `'1.08' >= 1.0` 抛 TypeError 被吞掉 → 该判据落「未采集」。
      // 同一判据两侧结论漂移，且「采纳后重测」看起来毫无反应。
      // 这里写已经算好的**数值** num（它就是上面那个有限性判断用的值），字符串只留在 adoptMeta 里做回显。
      const overrides = { ...s.overrides }
      const touched = { ...s.touched }
      for (const x of list) {
        if (!x.group) continue
        const num = Number(x.to)
        if (!Number.isFinite(num)) continue
        const k = paramKey('run', 'cp', x.group, x.key)
        overrides[k] = num
        touched[k] = true
      }
      return {
        adoptedApplied: list,
        adoptedKeys: list.map((x) => x.key),
        adoptMeta: Object.fromEntries(
          list.map((x) => [x.key, { name: x.name, from: x.from, to: x.to, group: x.group }]),
        ),
        overrides,
        touched,
      }
    }),
  setFocusReq: (focusReq) => set({ focusReq }),
  setRunId: (runId) => set({ runId }),
  setReportGenerated: (reportGenerated) => set({ reportGenerated }),
  setReportPreviewOpen: (reportPreviewOpen) => set({ reportPreviewOpen }),
  setSnapshotValues: (v) => set((s) => ({ snapshotValues: { ...s.snapshotValues, ...v } })),
  setReportHeader: (key, value) =>
    set((s) => {
      const header = { ...s.reportHeader }
      if (value) header[key] = value
      else delete header[key] // 空串 = 清除该项，不留空键
      writeReport(header)
      return { reportHeader: header }
    }),
  mergeReportHeader: (patch) =>
    set((s) => {
      // ⚠️ **只补不覆盖**：上游装配的值不该盖掉人已经手填的
      // （F6 那 4 项由本流程填，恰好与上游 6 项不重叠；这条是为将来扩展留的保险）
      const header = { ...s.reportHeader }
      let changed = false
      for (const [k, v] of Object.entries(patch)) {
        if (!v) continue
        if (header[k] !== v) {
          header[k] = v
          changed = true
        }
      }
      if (!changed) return s
      writeReport(header)
      return { reportHeader: header }
    }),
  setNotice: (notice) => set({ notice }),
  setPermission: (permission) =>
    set((s) => {
      if (s.permission === permission) return s
      writePermission(permission)
      return { permission }
    }),

  _syncAutomation: (runStatus, stages, currentStageId, announcement, summary) => {
    set({
      automationRunStatus: runStatus,
      automationStages: stages,
      automationCurrentStageId: currentStageId,
      automationAnnouncement: announcement,
      automationSummary: summary,
    })

    /* ------------------------------------------------------------------
       非致命报错判定（汇报模式）· 编号 1 的**唯一接入点**（2026-10-10）

       仅在**整轮终态**触发一次：取一份「日志 + 阶段终态」快照交给纯判定模块，
       把逐条判定落后台清单文件（logs/error_judge.log）供用户跑一轮后核对。
       ⚠️ 本阶段**界面零变化**：不改渲染、不动任何运行中路径、不新增 store 切片。
       ⚠️ 为什么延迟 + 动态 import：① 编排器在 END 之后还会紧跟 emit 尾部报错
         （如「报告未生成」），需等其入列；② 避免 store 静态依赖 features/automation
         形成循环依赖（沿用 startAutomation 里 `await import(...)` 的既有约定）。
       去重、快照二次校验、失败只 console 记录等纪律，全在 judgeReport.ts 内。
       ------------------------------------------------------------------ */
    if (
      !(runStatus === 'completed' || runStatus === 'failed' || runStatus === 'stopped') ||
      !summary.runId
    ) {
      return
    }
    const _rid = summary.runId
    void import('../features/automation/judgeReport').then(({ scheduleJudgeUpload }) => {
      scheduleJudgeUpload({
        runId: _rid,
        sceneId: useAppStore.getState().sceneId,
        terminalStatus: runStatus,
        snapshot: () => {
          const s = useAppStore.getState()
          return {
            logs: s.automationLogs,
            stages: s.automationStages.map((x) => ({ id: x.id, name: x.name, status: x.status })),
            runStatus: s.automationRunStatus,
            runId: s.automationSummary.runId,
          }
        },
      })
    })
  },
  /*
   * 置引导位。⚠️ 置 true 时**同时清掉「浮层已隐藏」**：它是「重新进入浮层」的
   * 唯一入口（顶栏「回到运行台」也走这里）。不清的话会出现「点了回到运行台、
   * 界面却毫无变化」——浮层被隐藏位挡在渲染之外。
   */
  setAutomationIntent: (automationIntent) => {
    if (automationIntent) writeOverlayHidden(false)
    set(
      automationIntent
        ? { automationIntent, automationOverlayHidden: false }
        : { automationIntent },
    )
  },
  /**
   * 运行中退出浮层（**软退出**）。
   *
   * 与 `clearAutomation()` 的关键区别：这里**只隐藏浮层**，不清任何运行数据、
   * 不删持久化、不发停止指令。后台编排器继续跑到自然完成，台架不受影响。
   * 用 clearAutomation 会清空运行台数据并把 runStatus 复位成 idle，
   * 下一条编排器事件又把浮层拉回来（历史已踩过，见 AutomationRunOverlay 注释）。
   */
  hideAutomationOverlay: () => {
    writeOverlayHidden(true)
    // 同时清引导位：人主动关掉了浮层，也就没有「要看浮层」的意图了。
    // 留着它会有两个副作用：① 渲染闸门若叠上 `!intent` 会当场失效（实测栽过）；
    // ② 下次经「回到运行台」重进时 intent 无 0→1 边沿，结果弹窗的 dismissed 不会复位。
    set({ automationOverlayHidden: true, automationIntent: false })
  },
    /**
     * 启动自动化（**授权瞬间**：安全闸门在此代确认）。
     *
     * 口径（2026-10-08 用户确认）：允许自动代确认人员/流程类闸门，但必须
     * 满足三条——① 引导屏已明示「本轮将代为确认 N 条」；② 人点了「开始自动回归」
     * 才执行（顶栏按钮只置 intent，不直接调本函数）；③ 逐条写入执行日志与
     * `automationGateAcks`，操作者记 `automation`，可审计。
     *
     * ⚠️ 为什么要在这里代确认、而不是让 runAndCollect 自己判定：`runAndCollect`
     * 沿用手动路径的 `green = gateTotal > 0 && gateAcked.length >= gateTotal`，
     * 若用户是从流程 1/2 页面点的自动化，闸门左栏从未挂载 → `gateTotal` 恒为 0
     * → `green` 永远 false → 后端按 409 拒绝启动。所以此处必须**同时**补齐
     * `setGateTotal`，否则代确认了也放行不了。
     *
     * ⚠️ 这不是绕过红线：闸门确认只是「勾选态」，启动本身仍由引导屏这一次
     * 显式点击授权（与手动路径「一键确认闸门后仍需在确认卡上确认」同一条纪律）。
     */
  startAutomation: () => {
      // 幂等：同一时间只允许一个 run。已在跑就只提示，不创建新 run。
      if (getOrchestrator().getRunStatus() === 'running') {
        useAppStore.getState().setNotice('自动化测试正在进行中')
        return
      }
      // 真启动时关掉引导态：引导屏交给编排器事件驱动（runStatus=running → 切进度屏）
          // ⚠️ 同时清空上一轮的过程数据（动作/日志/样本/判定），否则重跑时会把
       // 上一轮的判据与曲线带进来，看起来像「还没开跑就已经有数据」。
          // 新一轮开跑：清掉「浮层已隐藏」，否则上一轮点过退出会把这轮浮层也藏起来
          writeOverlayHidden(false)
          set({
            automationIntent: false,
            automationOverlayHidden: false,
            automationTools: [],
            automationLogs: [],
            automationLive: { plan: null, samples: [] },
            automationVerdicts: [],
          })

          void (async () => {
        // ① 取本场景的闸门清单（与流程 3 左栏 `gateItems` 同一口径：人员类 + 流程类）
        let gateIds: string[] = []
        try {
          const { getPack } = await import('../features/scene/pack')
          const pack = getPack()
          if (pack) {
            gateIds = pack.interlocks.interlocks
              .filter((i) => i.type === '人员' || i.type === '流程')
              .map((i) => i.id)
          }
        } catch (e) {
          // 读不到场景包时**不静默**：闸门清单取不到就无法代确认，如实留痕后继续
          // （后续 runAndCollect 会因 gate 未放行被后端 409 拒绝，原因会原样透出）。
          console.error('[automation] 读取安全闸门清单失败，无法代确认闸门：', e)
        }

        const st = useAppStore.getState()
        // ② 代确认未勾选的那些，并逐条记账
        const missing = gateIds.filter((id) => !st.gateAcked.includes(id))
        if (missing.length) {
          st.ackAllGates(missing)
          useAppStore.setState({ automationGateAcks: missing })
          for (const id of missing) {
            pushAutomationLog('warn', 'gate', `代确认安全闸门 ${id}（操作者：automation）`)
          }
          useAppStore.getState().setNotice(`已代确认 ${missing.length} 条安全闸门并记入执行日志`)
        }
        // ③ 补齐 gateTotal：流程 3 左栏未挂载时它恒为 0，会让下游 green 判定永远为 false
        if (gateIds.length) st.setGateTotal(gateIds.length)

        // ④ 真启动
        const r = await getOrchestrator().start()
        if (r.error === 'already_running') {
          useAppStore.getState().setNotice('自动化测试正在进行中')
        }
      })()
    },
    stopAutomation: () => {
        void getOrchestrator().stop()
      },
      /**
       * 关闭自动化浮层：复位运行态。
       *
       * ⚠️ 只复位**内存态与本地持久化**；已落库的产物（config-snapshot /
       * requirement-baseline / verdict-table / report-instance…）一律不动——
       * 关掉结果卡不等于回滚测试，这个区别必须明确，否则人会以为「关了就等于没跑」。
       */
      clearAutomation: () => {
        void import('../features/automation/automationOrchestrator').then(({ AUTOMATION_STORAGE_KEY }) => {
          try {
            localStorage.removeItem(AUTOMATION_STORAGE_KEY)
          } catch {
            /* 清不掉就只清内存，不影响本会话 */
          }
        })
        // 整层退出：隐藏位一并复位，否则下一轮浮层会被上一轮的退出态挡住
        writeOverlayHidden(false)
        set({
          automationRunStatus: 'idle',
          automationStages: [],
          automationCurrentStageId: null,
          automationAnnouncement: '',
          automationIntent: false,
          automationOverlayHidden: false,
          automationSummary: { ...EMPTY_AUTOMATION_SUMMARY },
          // 运行态清空，但**已落库产物不受影响**（下一轮会重新落）
          automationTools: [],
          automationLogs: [],
          automationLive: { plan: null, samples: [] },
          automationVerdicts: [],
          automationGateAcks: [],
        })
      },
  /**
   * 刷新后恢复上次的自动化运行态。
   *
   * 编排器的 `restore()` 一直在，但全仓从没人调 → 刷新即丢（本次补上）。
   * 「刷新时正在跑」由编排器如实降级为 `stopped`（JS 上下文已断，不能装还在跑）。
   */
  restoreAutomation: () => {
    const snap = getOrchestrator().restore()
    if (snap.runStatus === 'idle' && !snap.stages.length) return
    set({
      automationRunStatus: snap.runStatus,
      automationStages: snap.stages,
      automationCurrentStageId: snap.currentStageId,
      automationAnnouncement: '',
      // 刷新后过程态一律复位：样本/动作/日志/判定/闸门台账**都不持久化**，
      // 运行台会显示「本轮样本未保留，见已落库产物」，不假装还在跑。
      automationTools: [],
      automationLogs: [],
      automationLive: { plan: null, samples: [] },
      automationVerdicts: [],
      automationGateAcks: [],
      automationSummary: {
        runId: snap.runId,
        startedAt: snap.startedAt,
        finishedAt: snap.finishedAt,
        errorMessage:
          snap.stages.find((s) => s.status === 'failed')?.message ?? null,
        metrics: {
          pass: snap.metrics.pass ?? 0,
          fail: snap.metrics.fail ?? 0,
          missing: snap.metrics.missing ?? 0,
          // ⚠️ 本台架不适用单列：持久化里没有这个键（旧快照缺失），
          // 不能因为读不到就并进 pass —— 宁可少一个数，也不谎报「测过且合格」。
          notApplicable: snap.metrics.not_applicable ?? 0,
          total: snap.metrics.total ?? 0,
        },
        reportDownloaded: snap.metrics.report_downloaded === 1,
        reportStatus:
          snap.metrics.report_status_code === 1
            ? 'ok'
            : snap.metrics.report_status_code === 2
              ? 'placeholder'
              : 'skipped',
        reportFile: null,
        reportReason: null,
        // 刷新恢复时这三项**取不到就如实给「未知」**，不用 0 冒充：
        //   sampleCount=null → 结果页显示「—」（本轮样本不持久化，见 AutomationLiveState）；
        //   tuneRounds=0     → 刷新前若已跑过调优，这里只能承认「不知道」，
        //                       故按 0 显示并在 UI 侧以阶段回执为准，不编数字；
        //   gateAckCount=0   → 同理，闸门台账不持久化。
        // 刷新后这三项的取数口径（2026-10-08）：
        //   sampleCount ← 持久化 metrics.sample_count（它跟着 metrics 一起落库了，
        //       所以刷新后仍在；旧快照没这个键时为 null → 结果页显示「—」）；
        //   tuneRounds  ← tune 阶段成功次数（阶段状态是持久化的，刷新后仍准）；
        //   gateAckCount= 0（闸门台账不持久化，如实显示 0 条而非编一个数）。
        sampleCount: snap.metrics.sample_count ?? null,
        tuneRounds: snap.stages.filter((x) => x.id === 'tune' && x.status === 'success').length,
        gateAckCount: 0,
      },
    })
  },

  setCanvasView: (flow, v) =>
    set((s) => {
      const canvasView = { ...s.canvasView, [flow]: v }
      writeCanvasView(canvasView)
      return { canvasView }
    }),
  setDemoMode: (demoMode) => {
    writeDemoMode(demoMode)
    set({ demoMode })
  },
  setCanvasSelected: (canvasSelected) => set({ canvasSelected }),
  setCollapse: (key, open) =>
    set((s) => {
      const next = { ...s.collapse, [key]: open }
      writeCollapse(next)
      return { collapse: next }
    }),
  setKbFilter: (patch) =>
    set((s) => {
      const next = { ...s.kbFilter, ...patch }
      writeKbFilter(next)
      return { kbFilter: next }
    }),
  markKbSeen: (id) =>
    set((s) => {
      if (!id || s.kbSeen.includes(id)) return s
      const next = [...s.kbSeen, id]
      writeKbSeen(next)
      return { kbSeen: next }
    }),
  markKbSeenBatch: (ids) =>
    set((s) => {
      const add = ids.filter((x) => x && !s.kbSeen.includes(x))
      if (!add.length) return s
      const next = [...s.kbSeen, ...add]
      writeKbSeen(next)
      return { kbSeen: next }
    }),
  requestKbUpload: (kbUploadRequest) => set({ kbUploadRequest }),

  selectProduct: (path, sceneId) => {
    const id = sceneId ?? DEFAULT_SCENE_ID
    // 换包等于换掉五条流程的全部数据，上一个产品的人工改动与确认状态不再适用，
    // 一并清掉；「要不要丢」的询问在 ProductCascader 里做，这里只负责执行。
    // 闸门、本轮运行、采纳候选同样属于「上一个产品的现场状态」，一并清掉。
    //
    // ⚠️ 确认态清空必须**同时写 localStorage**（2026-09-28 修）。
    // 确认态已改为本地持久化（见 LS_CONFIRMED）；只在内存里清 `confirmed: {}`
    // 会留下一个隐蔽后果：**刷新时 store 从 localStorage 读出 true →
    // 紧接着 selectProduct 把内存清成 {} → 界面又变未确认**，
    // 表现为「确认过但刷新就丢」，与持久化的目的一点都不符。
    // 清内存与清持久记录必须成对，否则两边不一致。
    writeConfirmed({})
    // 知识库三件同源：已读集合、三轴筛选、选中条目——换库时内存与持久一起清，
    // 否则「换产品后刷新，旧筛选/旧已读复活」。（kbSeen 此前只清内存，是个真缺口。）
    writeKbSeen([])
    writeKbFilter({ usage: [], origin: [], owner: [] })
    writeKbSelected(null)
    set({
      path,
      loading: true,
      overrides: {},
      configSuggestionDemoDrafts: {},
      touched: {},
      confirmed: {},
      gateAcked: [],
      interlockPending: 0,
      runPhase: 'idle',
      runProgress: 0,
      runRound: 0,
      kbSelectedId: null,
      // 换产品等于换知识库：已读集合只对上一个产品的条目有意义，
      // 留着会把新产品的同 id 条目误判成「已看过」，新导入的就不标「新增」了。
      kbSeen: [],
      // 三轴筛选同理：上一个产品选的归属/用途/来源对新库没有意义，留着会
      // 过滤出新库为空，看起来像「这个产品没有知识」。成对清持久记录。
      kbFilter: { usage: [], origin: [], owner: [] },
      kbUploadRequest: false,
      adoptedKeys: [],
      adoptMeta: {},
      adoptedApplied: [],
      focusReq: null,
      runId: null,
      reportGenerated: false,
      // 报告表头是**产品相关**的（机型 / 项目名称 / 韫体版本），换产品必须清——
      // 留着会把上一个产品的机型填进新产品的报告里。
      reportHeader: {},
      snapshotValues: {},
      notice: null,
    })
    void loadScene(id).then((scene) => set({ scene, sceneId: id, loading: false }))
  },
  setParam: (key, v) =>
    set((s) => ({
      overrides: { ...s.overrides, [key]: v },
      touched: { ...s.touched, [key]: true },
    })),
  /**
   * 置确认态并**持久化**。
   *
   * 两边都要写：store 供本次渲染，localStorage 供刷新/重开。
   * 只写 store 就回到「刷新即丢」；只写 localStorage 则界面不重渲染。
   */
  confirmFlow: (flow) =>
    set((s) => {
      const confirmed = { ...s.confirmed, [flow]: true }
      writeConfirmed(confirmed)
      return { confirmed }
    }),
  unconfirmFlow: (flow) =>
    set((s) => {
      const confirmed = { ...s.confirmed, [flow]: false }
      writeConfirmed(confirmed)
      return { confirmed }
    }),
  setModel: (model) => set({ model }),
  bootstrap: () => {
    set({ loading: true })
    // ?scene=<sceneId> 直接指定开哪个场景包，给截图脚本与分享链接用；
    // 目录里没有这个 id 时忽略，走 index.json 的 default。
    const wanted =
      typeof window === 'undefined' ? null : new URLSearchParams(window.location.search).get('scene')
    void loadCatalog().then(({ catalog, defaultScene }) => {
      set({ catalog })
      const target = wanted && pathOfScene(catalog, wanted) ? wanted : defaultScene
      void loadScene(target).then((scene) =>
        set({
          scene,
          sceneId: target,
          loading: false,
          path: pathOfScene(catalog, target) ?? [
            scene.meta.scene,
            scene.meta.subclass,
            scene.meta.productType,
          ],
        }),
      )
    })
  },
}))

/** 有没有未确认的人工改动；换产品前要问一句「未保存内容将丢失」 */
export function hasUnsavedChanges(s: {
  touched: Record<string, true>
  confirmed: Partial<Record<FlowId, boolean>>
}): boolean {
  return Object.keys(s.touched).length > 0 || Object.values(s.confirmed).some(Boolean)
}

/** 流程标签状态（规格 5.2）：已确认 / 有异常 / 进行中 / 未开始 */
export function flowStateOf(
  flow: FlowId,
  current: FlowId,
  scene: ScenePackage,
  confirmed: Partial<Record<FlowId, boolean>>,
): FlowState {
  if (confirmed[flow]) return 'confirmed'
  // 暗红每屏 ≤3 处（规格 3.3）：只有当前流程才把异常提到顶部标签上，
  // 其余流程未进入，显示未开始，不预告异常。
  if (flow === current) {
    return scene.flows[flow].checklist.some((c) => c.status === 'alert') ? 'alert' : 'active'
  }
  return 'idle'
}

/* ===========================================================================
   红线的「等人点」承诺版接口。

   副驾那一侧（features/agent-chat）拿到设备桥的 confirm_token 之后，不允许自己去调
   approveConfirmation——那是第二个批准调用点，等于在红线上开了第二个口子。它改走
   这里：把动作排进同一张确认卡，人敲 PIN 点确认才 resolve(true)，点取消 resolve(false)。
   于是全工程批准桥凭据的路径只剩一条：确认卡 → approveRedline → approveConfirmation。
   =========================================================================== */

let redlineWaiter: ((ok: boolean) => void) | null = null

function resolveRedlineWaiter(ok: boolean) {
  const w = redlineWaiter
  redlineWaiter = null
  w?.(ok)
}

/** 排一个红线动作并等人的裁决。返回 true 表示人敲了 PIN 并确认执行。 */
export function requestRedlineAsync(req: Omit<RedlineRequest, 'onApprove'>): Promise<boolean> {
  // 同一时刻只允许一条红线排队；上一条还挂着就按「未获批准」收尾，不静默丢弃
  resolveRedlineWaiter(false)
  return new Promise<boolean>((resolve) => {
    redlineWaiter = resolve
    useAppStore.getState().requestRedline({ ...req, onApprove: () => undefined })
  })
}

/* ===========================================================================
   一键自动化测试流程：编排器单例 + 依赖注入装配。

   分层纪律：这里只负责「把真实测试能力包成适配器、喂给纯逻辑编排器」，
   编排器本体在 features/automation/automationOrchestrator.ts，不 import 这里。

   为什么用模块级单例 + 懒创建：
     · store 顶层若直接 import 各 feature 模块，会与「features 反向 import store」
       形成循环依赖（snapshotApi 就 import 了 useAppStore）；动态 import 在函数内
       才执行，天然解环，且只在人真的点「智能测试」时才加载这些模块。
     · 单例保证「同一时间只允许一个 run」的幂等判断落在同一份状态上。

   路由跳转：编排器是纯逻辑，不能用 useNavigate hook。这里注入 react-router 的
   全局 router（src/router.tsx 导出），router.navigate 保持 SPA 无刷新跳转。
   =========================================================================== */

let _orchestrator: Orchestrator | null = null

function getOrchestrator(): Orchestrator {
  if (_orchestrator) return _orchestrator

  // 轻量事件总线：编排器 emit，store 切片订阅后写回（单向数据流）
  const bus = createEventBus()

  /* 组装真实适配器：复用已联通的测试能力，不重写测试逻辑。
   *
   * ⚠️ 2026-10-10（用户要求）：**适配器一律不写 `confirmed`（确认态）**。
   * 顶栏流程条上那个节点的勾（✓）只代表「人自己在该页左下角点过确认」——
   * 确认并锁定（流程 1）/ 确认基线（流程 2）/ 确认参数并启动测试（流程 3）/
   * 确认采纳（流程 4，经红线确认卡）/ 确认表头（流程 5），实现都在各自面板里。
   * 机测代跑**不算**：否则人没按过、顶栏却已打勾，页脚与节点两处状态就不一致
   * （用户实测反馈的正是这一条：机测跑完顶栏自动打勾，刷新后仍然亮）。
   *
   * 机测照旧落库、照旧推进阶段，只是不再替人点亮确认态。编排器本体不读 `confirmed`
   * （`features/automation/` 全目录 0 处引用，已核），故去掉这些写入不产生副作用；
   * 运行过程中「这一步跑到了」仍由顶栏既有的脉冲 / 成功态（autoDone）表示。
   */
  const adapters: AutomationAdapters = {
    initParams: async () => {
      const { persistSnapshot } = await import('../features/flow-init/snapshotApi')
      const st = useAppStore.getState()
      const { runId } = await persistSnapshot({
        sceneId: st.sceneId,
        operator: st.benchUser,
        locked: true,
      })
      st.setRunId(runId)
      // 不置 confirmed：机测不代点亮顶栏节点（见上方适配器头说明）
    },
    confirmBaseline: async () => {
      // 流程2 测试需求确认：自动把全部判据纳入基线（与界面「确认基线」全选同一口径）。
      const { getPack } = await import('../features/scene/pack')
      const { persistBaseline } = await import('../features/flow-req/baselineApi')
      const st = useAppStore.getState()
      const pack = getPack()
      if (!pack) throw new Error('场景包未加载，无法确认需求基线')
      const ids = pack.requirements.requirements.map((r) => r.id)
      if (!ids.length) throw new Error('场景包判据为空，无法确认需求基线')
      const { runId } = await persistBaseline({
        sceneId: st.sceneId,
        runId: st.runId,
        includedIds: ids,
        totalCount: ids.length,
        operator: st.benchUser,
      })
      st.setRunId(runId)
      // 不置 confirmed：机测不代点亮顶栏节点（见上方适配器头说明）
    },
    runAndCollect: async (onProgress) => {
      // 流程3 启动测试（2026-10-08 改）：真机链路 = 风扇台架 /api/fan-tests。
      //
      // 为什么改：原实现走**设备桥**（callBridgeTool('bench','start')）+ beginRun 的
      // read_fg 采集，而真机已换成「UNO 发 PWM + Rigol DS1104Z」台架，桥不适用；
      // 且原实现 `await new Promise` 死等 runPhase==='done'，但 beginRun 自 2026-10-08
      // 起**永不置 done**（done 由 UI 组件 FanTrendPanel 在渲染时置），自动化路径下
      // 无人置 done → 必然 30 秒超时（用户截图「测试执行超时未完成」的根因）。
      //
      // 现改为本函数**自行驱动**：真启动 → 增量轮询真样本 → terminal 判终态 → 自行收口。
      // 数据纪律：全部真数据（/api/fan-tests）；失败如实 throw，不降级、不补 0、不编值。
      const { getPack } = await import('../features/scene/pack')
      const { loadWaves } = await import('../features/waveforms')
      const { evaluateOnBackend, persistRun } = await import('../features/flow-run/api')
      const { evaluateAll, runtimeMeasures, controlValueMap } = await import('../features/flow-run/evaluate')
      const { startFanTest, getSamples, getFanTest } = await import('../features/fan-trend/api')
      const st = useAppStore.getState()
      const pack = getPack()
      if (!pack) throw new Error('场景包未加载，无法跑测试')

      /* 上报通道（2026-10-08 新增）：把「过程」暴露给全屏运行台。
         ⚠️ 走编排器注入的 reportTool/reportLive，而不是直接写 store ——
         这样时序与其它阶段事件保持同一条流，UI 不会看到「动作已完成但
         阶段还没开始」这类错位。 */
      const reportTool = adapters.reportTool
            const reportLive = adapters.reportLive
      /** 上报一个动态动作（真实调用才发，不预发） */
      const tool = (id: string, label: string, status: 'running' | 'done' | 'failed' | 'skipped', message?: string) =>
        reportTool?.({ id, label, status, message })

      // ① 安全闸门全绿快照（与手动路径 FanTrendPanel 同口径）。
      const green = st.gateTotal > 0 && st.gateAcked.length >= st.gateTotal
      const gate = { interlocks_ok: green, precheck_ok: green, master_switch_on: green }

      // ② 真启动风扇台架。接口异常（闸门未过 409 / 单设备锁 409 / 网络错）如实抛出。
      // ⚠️ 本函数是适配器（不在 create 的 set 作用域内），须用 useAppStore.setState。
      useAppStore.setState({ runPhase: 'running', runProgress: 0, runMeasures: {} })
      tool('fan-start', '下发台架启动', 'running')
      const plan = await startFanTest({ gate })
      // 真机流程拒绝模拟数据：后端若返回 simulation=true 说明未接真台架，如实报错。
      if (plan.simulation) {
        useAppStore.setState({ runPhase: 'idle' })
        tool('fan-start', '下发台架启动', 'failed', '后端返回模拟数据（simulation=true），已拒绝')
        throw new Error('后端返回的是模拟数据（simulation=true），拒绝在真机流程中使用')
      }
      tool('fan-start', '下发台架启动', 'done', `run_id ${plan.run_id.slice(0, 8)} · 计划 ${plan.planned_duration_s}s`)

      // ③ 增量轮询真实样本 + 以 terminal 判终态（串行锁 + after_sequence 游标）。
      // ⚠️ 声明为 let：每轮用 mergeSamples 重新绑定（去重 + 按 t_s 排序后的新数组）。
      let samples: FanSample[] = []
      let cursor = 0
      let lastPlan = plan
      // 超时上限：按后端计划时长的 3 倍 + 60 秒兜底（正常路径以 terminal 为准，不死等）。
      const plannedS = plan.planned_duration_s || plan.default_duration_s || 60
      const timeoutMs = Math.max(120_000, plannedS * 3 * 1000 + 60_000)
      const deadline = Date.now() + timeoutMs
      // 已采档位数（用于真实进度：已到达终态的档位 / 计划档位数）。
const updateProgress = () => {
        const totalSteps = Math.max(1, plan.steps?.length ?? 4)
        const doneSteps = new Set(
          samples
            .filter((s) => s.measurement_finished_t_s != null)
            .map((s) => s.commanded_pwm_pct),
        ).size
        onProgress(Math.min(99, Math.round((doneSteps / totalSteps) * 100)))
      }
      /* 逐档动作上报（2026-10-08 新增）：
         真实台架每采完一档才多一条「measurement_finished」，所以这里拿
         「已完成的档位集合」去重，**只在真完成时**发 done，
         绝不为「还没采到」预发一条假动作。 */
      const reportedDoneDuties = new Set<number>()
      while (true) {
        const res = await getSamples(lastPlan.run_id, cursor)
        // 归一（按 sequence 去重 + 按 t_s 排序）走唯一实现：
        // 原实现是 `for (const s of res.samples) samples.push(s)`，既不去重也不排序，
        // 后端一旦回带重叠窗口，同一段斜坡会被重复画进趋势图、「已采 N 条」也会虚高。
        if (res.samples.length) {
          samples = mergeSamples(samples, res.samples)
        }
        cursor = Math.max(cursor, res.next_after_sequence)
        updateProgress()

        // 实时样本流：让中栏趋势图随采集动态生长（1Hz，天然不卡）
        reportLive?.({ kind: 'samples', plan: lastPlan, samples: [...samples] })

        // 逐档完成 → 发一条 done 动作（带该档实测转速，缺测则如实写「未采集」）
        for (const s of samples) {
          const duty = s.commanded_pwm_pct
          if (duty == null) continue
          if (s.measurement_finished_t_s == null) continue
          if (reportedDoneDuties.has(duty)) continue
          reportedDoneDuties.add(duty)
          const rpmText = typeof s.rpm === 'number' ? `${Math.round(s.rpm)} rpm` : '转速未采集'
          tool(`fan-duty-${duty}`, `采集 ${duty}% 档`, 'done', rpmText)
          pushAutomationLog('success', 'run', `${duty}% 档采集完成 · ${rpmText}`)
        }

        lastPlan = await getFanTest(lastPlan.run_id)
        if (lastPlan.terminal) {
          // 权威终态。失败 → 如实抛出后端透传的原因（不美化、不降级）。
          if (lastPlan.status === 'failed') {
            useAppStore.setState({ runPhase: 'idle' })
            const why = lastPlan.error || '风扇台架采集失败（后端未提供原因）'
            tool('fan-collect', '轮询采集', 'failed', why)
            pushAutomationLog('error', 'run', `台架采集失败：${why}`)
            throw new Error(why)
          }
          break
        }
        if (Date.now() > deadline) {
          useAppStore.setState({ runPhase: 'idle' })
          const why = `风扇台架运行超时（>${Math.round(timeoutMs / 1000)}s）未到达终态`
          tool('fan-collect', '轮询采集', 'failed', why)
          throw new Error(why)
        }
        await new Promise((r) => setTimeout(r, 1000))
      }

// ④ 收口：先写台架实测量，再置终态（顺序不可颠倒，见 settleRun 说明）。
      const bench = collectFanMeasures(samples)
      useAppStore.setState((s) => ({
        runMeasures: Object.keys(bench).length ? { ...s.runMeasures, ...bench } : s.runMeasures,
        runProgress: 100,
        runPhase: 'done',
        runRound: s.runRound + 1,
      }))
      // 最后一批样本再上报一次：确保终态那一刻曲线是完整的
      reportLive?.({ kind: 'samples', plan: lastPlan, samples: [...samples] })
      tool('fan-collect', '轮询采集', 'done', `共采到 ${samples.length} 条样本`)

      // ⑤ 判定落库（复用 flow-run/panel 的链路），并返回是否有未达标。
      tool('fan-judge', '后端权威判定', 'running')
      const waves = await loadWaves()
      const measures = { ...runtimeMeasures(waves, pack), ...useAppStore.getState().runMeasures }
      const result = await evaluateOnBackend(
        st.sceneId,
        measures,
        controlValueMap(pack, st.overrides, st.snapshotValues),
      )
      // 权威判定上报给右栏判据列表（一次性结论，与样本流同一通道）
      reportLive?.({ kind: 'verdicts', verdicts: result.results })
      const localRows = evaluateAll(pack, measures, st.overrides, st.snapshotValues)
      const runId = await persistRun({
        sceneId: st.sceneId,
        verdicts: localRows,
        measures,
        backendVerdicts: result.results,
      })
      st.setRunId(runId)
      // ⚠️ 2026-10-10 起**不再**置 run 已确认（原注释：与交互路径同一锚点，否则自动化结束后
      // 顶栏那一格点不亮）。用户新口径：顶栏节点只由「人在流程 3 左下角点『确认参数并启动
      // 测试』」那条交互路径点亮（见 flow-run/panel.tsx 的同处锚点），机测代跑不代点亮，
      // 免得页脚与节点两处状态不一致。
      const hasFail = result.results.some((v) => v.state === 'fail')
      // 真实判定统计（后端权威结果）——结果卡据此展示「通过 x · 未通过 y · 未采集 z」，
      // 数字直接来自本轮判定表，不是前端估的
      const pass = result.results.filter((v) => v.state === 'pass').length
      const fail = result.results.filter((v) => v.state === 'fail').length
      const missing = result.results.filter((v) => v.state === 'missing').length
      // 本台架不适用（2026-10-08）：单独计数，绝不并入 pass——
      // 那是"没测"不是"测过且合格"，混进去就是假数据。
      const notApplicable = result.results.filter((v) => v.state === 'not_applicable').length
      const jd = `通过 ${pass} · 未通过 ${fail} · 未采集 ${missing} · 本台架不适用 ${notApplicable}`
      tool('fan-judge', '后端权威判定', 'done', jd)
      pushAutomationLog('info', 'run', `判定完成：${jd}（共 ${result.results.length} 条）`)
      return {
        hasFail,
        pass,
        fail,
        missing,
        notApplicable,
        total: result.results.length,
        sampleCount: samples.length,
      }
    },
    tuneOnce: async () => {
      // 流程4 调优确认：自动采纳推荐参数并写回（persistAdoption 落 param-change + applyAdopt 写回 overrides）。
      // 复用 computeCandidates 拿推荐列表，自动采纳「能给出具体数值」的项（suggested 为数字）。
      // 设备侧写回走桥的自动化放行通道（write_param 同款），但 FTGeneralUtils.dll 无写单参数接口，
      // 真写回仍如实标「现场层待接」——自动化能保证的是：采纳值落产物 + 流程3 读到新值。
      const { getPack } = await import('../features/scene/pack')
      const { computeCandidates } = await import('../features/flow-tune/candidates')
      const { persistAdoption } = await import('../features/flow-tune/adoptApi')
      const { callBridgeTool, autoApproveConfirmation } = await import('../features/remote/bridge')
      const st = useAppStore.getState()
            const pack = getPack()
            if (!pack) throw new Error('场景包未加载，无法调优')

const cands = computeCandidates(pack).filter((c) => typeof c.suggested === 'number')
      if (!cands.length) {
        // 没有可自动采纳的推荐项：如实返回，编排器据此直接进报告（不空转）。
        pushAutomationLog('info', 'tune', '无可采纳的推荐参数，按要求直接出报告')
        return { adopted: false }
      }

      const items = cands.map((c) => ({
        key: c.param.key,
        name: c.param.name,
        from: String(c.current),
        to: String(c.suggested),
        group: c.param.group,
      }))
      // 采纳明细逐条上报：左栏参数高亮 + 日志可复核（谁把哪个值改成多少）
      adapters.reportTool?.({
        id: 'tune-candidates',
        label: '计算推荐参数',
        status: 'done',
        message: `命中 ${items.length} 项`,
      })
      for (const it of items) {
        pushAutomationLog('info', 'tune', `自动采纳推荐：${it.name} ${it.from} → ${it.to}`)
      }

      // ① 写回 store overrides（流程3 读到新值）。⚠️ 2026-10-10 起不置 tune 已确认：
      // 顶栏「调优运行」那一格的勾只由人在流程 4 左下角点「确认采纳」并批准确认卡点亮
      // （见 features/redline/flowActions.ts 的 adopt.onApprove）；机测不代点亮。
      st.applyAdopt(items)
      st.setRunPhase('idle')

      // ② 落 param-change 产物（复用 persistAdoption）
      const { runId } = await persistAdoption({
        sceneId: st.sceneId,
        runId: st.runId,
        items,
        operator: st.operator,
      })
      st.setRunId(runId)

      // ③ 真写回设备：走桥的 write_param（自动化放行）。设备侧如实标「现场层待接」，
      //    这里只保证「尝试了真下发」，失败不阻断（采纳值已落产物 + overrides）。
      try {
        const first = (await callBridgeTool('bench', 'write_param', { key: items[0].key, value: Number(items[0].to) })) as { confirm_token?: string }
        const token = first.confirm_token ?? null
        if (token) {
          await autoApproveConfirmation(token, st.operator)
          await callBridgeTool('bench', 'write_param', { key: items[0].key, value: Number(items[0].to), confirm_token: token })
        }
      } catch {
        // 真下发失败不阻断：设备侧写回本就现场层待接，采纳值已在产物与内存，流程3 可重跑。
      }

      return { adopted: true }
    },
    /**
     * 流程5 报告生成：**复用后端既有导出链路**（`POST /api/reports/generate`），
     * 不自研任何 Excel 写入。
     *
     * ⚠️ 返回后端的**真实三档状态**（不吞成 void）：编排器要据此在结果卡上
     * 如实区分「正式报告 / 系统自建模板报告 / 未产出」——一律显示「已生成」
     * 会把占位件说成交付件（模块头明确禁止）。
     *
     * 轮次不存在时 `resolveReportRunId` 抛「本场景还没有落过轮次」——**原样抛出**，
     * 由编排器如实记失败（用户口径：无轮次时如实标注，不补建空轮次、不假装成功）。
     */
    generateReport: async () => {
      const { generateReport, resolveReportRunId } = await import('../features/flow-report/reportApi')
      const st = useAppStore.getState()
      const rid = await resolveReportRunId(st.sceneId, st.runId)
      const r = await generateReport(rid)
      return { status: r.status, file: r.file, reason: r.reason }
    },
    /**
     * 流程5 报告下载：先**探一次文件存在性**再点下载。
     *
     * 为什么不直接点：生成失败（`blocked`）时后端根本没有文件，直接点 `<a>`
     * 只会让浏览器打开一个 404 页签，人看到的是「白屏/报错」而不是「报告没生成」。
     * 先 HEAD 探一次（`reportExists` 复用既有实现），没有就返回 blocked + 原因，
     * 让编排器/结果卡如实说明「报告未生成」，而不是假装下载过了。
     */
    downloadReport: async () => {
      const { downloadUrl, reportExists, resolveReportRunId } = await import('../features/flow-report/reportApi')
      const st = useAppStore.getState()
      const rid = await resolveReportRunId(st.sceneId, st.runId)
      const exists = await reportExists(rid)
      if (!exists) {
        return { blocked: true, reason: '轮次还没有报告文件（生成阶段未产出），无法下载' }
      }
      const a = document.createElement('a')
      a.href = downloadUrl(rid)
      a.download = ''
      document.body.appendChild(a)
      a.click()
      a.remove()
      // 文件确实存在且已触发下载；浏览器是否拦截仍无法从代码里可靠探测，
      // 交给 UI 层提示「若未开始下载请手动点击」。
      return { blocked: false }
    },
    cancel: async () => {
      // 终止：复用 stop 的语义。真机已启动的电机停转由流程 3 的「停止」红线承担，
      // 自动化终止这里只做状态收口，不冒充「电机已停」（红线仍要求人点急停/停止）。
      const st = useAppStore.getState()
      st.setRunPhase('stopped')
    },
    router: {
      navigate: async (path: string) => {
        const { router } = await import('../router')
        router.navigate(path)
      },
    },
    eventBus: bus,
    storage: {
      get: (key: string) => {
        try {
          const raw = localStorage.getItem(key)
          return raw ? JSON.parse(raw) : null
        } catch {
          return null
        }
      },
      set: (key: string, value: unknown) => {
        try {
          localStorage.setItem(key, JSON.stringify(value))
        } catch {
          /* 存不下就只在本次会话生效 */
        }
      },
      remove: (key: string) => {
        try {
          localStorage.removeItem(key)
        } catch {
          /* 同上 */
        }
      },
    },
    logger: {
      info: (m: string) => console.info(`[automation] ${m}`),
      error: (m: string, e?: unknown) => console.error(`[automation] ${m}`, e ?? ''),
    },
  }

  _orchestrator = createAutomationOrchestrator(adapters)

  // 单向数据流：编排器事件 → store 切片。播报节流（同一条消息不重复刷屏）。
  let lastAnnounce = ''
  let lastAnnounceAt = 0
  const sync = (payload?: AutomationPayload) => {
    /* ------------------------------------------------------------------
       ① 先分流「非阶段类」事件（2026-10-08 新增）。
       这些事件不参与阶段/播报的计算，纯粹是给全屏运行台供数据：
         · AUTOMATION_TOOL —— 动作面板的一条（静态围栏 / 适配器动态上报）
         · AUTOMATION_LIVE —— 台架样本流（1Hz）或一次性权威判定
         · AUTOMATION_LOG / ERROR —— 执行日志流
       ⚠️ 放在这里而不是各自单独订阅，是为了保证「日志与动作的先后顺序」
       与编排器的实际 emit 顺序一致（拆成两个订阅会因注册顺序而错位）。
       ------------------------------------------------------------------ */
    if (payload) {
      // 动作面板：按 toolId upsert（同一动作重复上报只更新状态，不新增行）
      if (payload.toolId && payload.toolStatus) {
        const t = {
          id: payload.toolId,
          label: payload.toolLabel ?? payload.toolId,
          status: payload.toolStatus,
          message: payload.message || undefined,
          at: Date.now(),
        }
        useAppStore.setState((s) => {
          const i = s.automationTools.findIndex((x) => x.id === t.id)
          if (i < 0) return { automationTools: [...s.automationTools, t] }
          const next = s.automationTools.slice()
          next[i] = t
          return { automationTools: next }
        })
      }
      // 实时数据：samples 整体替换；verdicts 一次性替换。
      if (payload.live) {
        const live = payload.live as
          | { kind: 'samples'; plan: unknown; samples: unknown[] }
          | { kind: 'verdicts'; verdicts: unknown[] }
        if (live.kind === 'samples') {
          // ⚠️ 进 UI 前再兜一次归一（2026-10-09）：这是样本进入趋势图的**唯一闸口**，
          // 即便上游（runAndCollect）漏了去重，也不会把重复点画到图上。
          // 开销：n≈20/轮、1Hz，O(n log n) 可忽略。
          const normalized = mergeSamples([], (live.samples ?? []) as FanSample[])
          useAppStore.setState({
            automationLive: {
              plan: (live.plan ?? null) as AutomationLiveState['plan'],
              samples: normalized,
            },
          })
        } else {
          useAppStore.setState({
            automationVerdicts: (live.verdicts ?? []) as AutomationVerdict[],
          })
        }
      }
      // 执行日志：ERROR 走 error 级，其余按 payload.level
      if (payload.message) {
        const isLogish =
          payload.status === 'failed' || typeof payload.currentTask === 'string'
        if (isLogish && (payload.level !== undefined || payload.status === 'failed')) {
          pushAutomationLog(
            payload.level ?? (payload.status === 'failed' ? 'error' : 'info'),
            payload.stageId,
            payload.message,
          )
        }
      }
    }

    const o = _orchestrator!
    const stages = o.getStages()
    const cur = o.getCurrentStageId()
    const curStage = stages.find((s) => s.id === cur)
    let announcement = ''
    if (curStage) {
      announcement =
        curStage.status === 'failed'
          ? `⚠️ ${curStage.name}失败：${curStage.message}`
          : curStage.status === 'running'
            ? `${curStage.name} ${curStage.progress}%${curStage.message ? ` · ${curStage.message}` : ''}`
            : `${curStage.name} · ${curStage.message}`
    }
    const now = Date.now()
    const runStatus = o.getRunStatus()

    /**
     * 结果卡的真实数据：**只从编排器事件 payload 取**，前端不自己算耗时、不编数字。
     *   · runId / startedAt / finishedAt —— payload 直接给
     *   · metrics —— 只认带 metrics 的事件（END 带判定统计；其它事件默认为空对象，不覆盖）
     *   · reportDownloaded —— 只在 DOWNLOAD_SUCCESS 事件置 true（不推断）
     *   · errorMessage —— 只在某阶段 failed 或有 ERROR 事件时取 message
     */
    const prev = useAppStore.getState().automationSummary
    const summary = {
      runId: payload?.runId || prev.runId,
      startedAt: payload?.startedAt ?? prev.startedAt,
      finishedAt: payload?.finishedAt ?? prev.finishedAt,
      // metrics 为空对象时保留上一份（避免中间事件把判定统计冲成 0）
          metrics:
            payload?.metrics && Object.keys(payload.metrics).length > 0
              ? {
          pass: payload.metrics.pass ?? 0,
          fail: payload.metrics.fail ?? 0,
        missing: payload.metrics.missing ?? 0,
              // ⚠️ 本台架不适用单列：并进 pass 就是把「没测」说成「测过且合格」
                  notApplicable: payload.metrics.not_applicable ?? 0,
              total: payload.metrics.total ?? 0,
                }
            : prev.metrics,
      reportDownloaded:
        prev.reportDownloaded || payload?.metrics?.report_downloaded === 1,
      // 报告三态：只认带 report_status_code 的事件（END 带），中途事件不覆盖
      reportStatus:
        payload?.metrics?.report_status_code === 1
          ? 'ok'
          : payload?.metrics?.report_status_code === 2
            ? 'placeholder'
            : payload?.metrics?.report_status_code === 0 && payload?.status && payload.status !== 'running'
              ? 'blocked'
              : prev.reportStatus,
      // 文件名从报告阶段的 message 里取（编排器把「报告已产出 status=… file=…」写进阶段消息；
      // 取不到就保持上一份——文件名是锦上添花，取不到不该让整段退化）
      reportFile: (() => {
        const rep = stages.find((s) => s.id === 'report')
        const hit = rep?.message?.match(/file=([^\s]+)/)
        return hit ? hit[1] : prev.reportFile
      })(),
      reportReason: (() => {
        const rep = stages.find((s) => s.id === 'report')
        if (rep?.status === 'failed') {
          const m = rep.message ?? ''
          const hit = m.match(/报告未生成[：:]\s*(.+)$/)
          return hit ? hit[1].trim() : (prev.reportReason ?? m.slice(0, 200))
        }
        return prev.reportReason
      })(),
      // 失败原因优先取「失败阶段的 message」（最具体），其次 ERROR 事件的 message
            errorMessage:
              stages.find((s) => s.status === 'failed')?.message ?? prev.errorMessage,
            // 采样点数：由编排器随 metrics 下发（真实样本条数）。取不到给 null，
                  // 结果页显示「—」——**不用 0 冒充「一条都没采到」**，那会把两种情况混成一种。
                  sampleCount: payload?.metrics?.sample_count ?? prev.sampleCount,
            // 调优轮次：以「tune 阶段成功次数」为准——它正好等于「采纳→回流程3重测」的轮数，
            // 没进过调优就是 0，不写 undefined（结果页要能显示 0 而不是「—」）
            tuneRounds: (() => {
              const n = stages.filter((s) => s.id === 'tune' && s.status === 'success').length
            return n || prev.tuneRounds
            })(),
            gateAckCount: useAppStore.getState().automationGateAcks.length,
          }

    if (announcement && (announcement !== lastAnnounce || now - lastAnnounceAt > 2000)) {
      lastAnnounce = announcement
      lastAnnounceAt = now
      useAppStore.getState()._syncAutomation(runStatus, stages, cur, announcement, summary)
    } else {
      useAppStore.getState()._syncAutomation(runStatus, stages, cur, lastAnnounce, summary)
    }
  }
  const names = [
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
  for (const n of names) {
    // 把 payload 透传给 sync：结果卡要的 startedAt/finishedAt/metrics 只在 payload 里
    bus.on(n, (payload) => sync(payload))
  }

  return _orchestrator
}
