import { useT } from '../../i18n'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  CircleSlash,
  FileBarChart,
  Gauge,
  PlayCircle,
  SlidersHorizontal,
  Terminal,
  Zap,
} from 'lucide-react'
import { Button, Panel, PanelHeader, Tooltip, cn } from '../../components/ui'
import { ConsoleChatPanel } from './ConsoleChatPanel'
import { FanTrendView } from '../fan-trend/FanTrendView'
import { getPack } from '../scene/pack'
import { useAppStore } from '../../state/useAppStore'
import type {
  AutomationLiveState,
  AutomationLogEntry,
  AutomationToolState,
} from '../../state/useAppStore'
import type { BackendVerdict } from '../flow-run/api'
import { fmtClock, fmtElapsed, fmtPct } from '../shared/format'
import {
  buildParamViews,
  buildVerdictViews,
  type ParamView,
  type StageStats,
  type StageView,
  type VerdictStats,
  type VerdictView,
} from './automationViewModel'

/* ===========================================================================
   自动化回归 · 全屏运行台（三栏）

   三栏各答一个问题：
     左「在用哪些参数、现在到哪一步了」→ 参数来源 + 真实动作三态；
     中「台架采到什么」→ 复用 FanTrendChart（双纵轴、缺测断线）+ 执行日志；
     右「判得怎么样」→ 四类计数分列 + 判据逐条实测值。

   ⚠️ 三条硬纪律：
     ① 空态给「未开始/暂无」文案，**不显示 0**（0 会被读成「测了但没通过」）；
     ② 缺测（null）显示「未采集」并给原因，**不补零、不插值**；
     ③ 动作三态由编排器按 promise 生命周期围栏，**不存在写死的动画脚本**。
   =========================================================================== */

/** 参数来源徽标的色调：本轮采纳最重、文档值最轻 */
const SOURCE_CLS: Record<ParamView['source'], string> = {
  本轮采纳: 'bg-ink text-white',
  初始化快照: 'bg-p100 text-p700',
  场景包文档值: 'bg-sunk text-t3',
  不适用: 'bg-sunk text-t3',
}

/* ===========================================================================
   中栏「实时趋势 ↔ 执行日志」可拖分隔条（2026-10-09）

   起因：中栏原为「趋势 min-h-220px + 日志 flex-1」——日志把剩余高度全吃掉，
   上方趋势区被压得偏小（用户反馈「上面的区域太小、下面的太大」）。

   口径与流程页「面板 ↔ AI 助手」那条分隔条**同源**（`app/FlowScreen.tsx`）：
     · 布局用 fr 栅格，不用写死像素高 → 视口变化时比例自动保持；
     · 分隔条自带行高（吃掉原来的两区之间 gap），栅格 gap:0，避免条上下各多一道空档；
     · 拖动事件绑 window（指针会滑出 20px 窄条，绑自身会中途丢事件）；
     · 常显 grip + role="separator" + aria-* + 方向键 + 双击复位（键盘可达，不只有鼠标）。
   与流程页的差异：比例是**单一键**（运行台不属于某条流程），且额外把两侧像素下限
   纳入 clamp —— 拖到任何位置都不会把趋势图或日志压没，也不会把底部状态条挤出屏幕。
   =========================================================================== */

/** 终态文案：状态条与趋势卡胶囊共用，避免同一件事两处说法不一致 */
const TERMINAL_LABEL: Record<'completed' | 'failed' | 'stopped', string> = {
  completed: '已完成',
  failed: '失败',
  stopped: '已终止',
}

/**
 * 执行日志区（中栏第三行，与助手卡共用）的**固定高度**：190px（2026-10-10 用户定）。
 *
 * 之前它是「占中栏可用高的比例」（默认 45%），于是同一块区域在 692 / 900 / 1080 高的
 * 窗口下分别是 242 / 336 / 417px —— 换个屏幕就换个高度。用户要求**固定成同一高度**：
 *   · 存的是**像素**而不是比例 ⇒ 窗口缩放时这块不动，多出来的高度全给上方实时趋势
 *     （用户原话：「下面固定，上面是要动的」）；
 *   · 190px = 卡头 47px + 约 6 行日志，取自用户截图里量出的高度；
 *   · 助手态另有更高的下限 300px（见 CONSOLE_AI_MIN_H），本默认值只对日志态生效。
 */
const LOG_DEFAULT_H = 190
/**
 * 趋势区像素下限：沿用它原来的 min-h-[220px]，也正好保住 FanTrendChart 的 full 档。
 *
 * ⚠️ 2026-10-10（机测页助手高度修复）按用户确认的保守口径**保持不变**：助手态下也不
 * 放开，即 AI 卡最多 = 中栏可用高 − 220。将来若要让它像人测页面板那样被压到只剩标题条，
 * 只需要改这个数（人测页对应常量是 `app/FlowScreen.tsx` 的 PANEL_MIN_H）。
 *
 * ⚠️ 它现在只是**拖动 / 键盘**的上界护栏；窗口本身矮到装不下时，渲染照样保住日志区的
 * 固定高度、让趋势让位（见 clampRowHeight / rowHeightBounds 的说明）。
 */
const TREND_MIN_H = 220
/** 日志区像素下限：可拖到的最小高度（沿用它原来的 min-h-[140px]） */
const LOG_MIN_H = 140
/**
 * 助手卡像素下限（助手态 300 —— 日志态的下限是 LOG_MIN_H）。
 *
 * ⚠️ 2026-10-10（机测页助手高度修复）由 216 抬到 300。216 只够把「卡头 47 + 输入区
 * 125 = 172」摆下，对话区只剩 42px（约 2 行）——那正是用户报的「被压扁、展示不完整」。
 * 300 给对话区留 ~128px（约 4~5 行），满足「至少能看到完整的输入框和几条对话」。
 *
 * 与流程页 `app/FlowScreen.tsx` 的 ASSISTANT_MIN_H / ASSISTANT_COMFORT_H 同源（那边
 * 主动下拖可到 160、默认走 216 舒适口径）；这里是运行台第三行，取 300 作为常态下限。
 *
 * ⚠️ 这是**模式下限**：日志态用 LOG_MIN_H、助手态用本值。若不按模式取，
 * 助手态会被日志态的 140px 下界夹回、助手卡底部被裁。
 */
const CONSOLE_AI_MIN_H = 300
/** 分隔条行高：原两区之间 10px gap 全收进条里 */
const HANDLE_H = 20
/** 日志区固定高度（px）的持久化键 */
const LOG_H_KEY = 'automation-console-log-height'
/** 旧键：存的是「日志占比」（0~1 的比例），改像素后弃用，读到即清理 */
const LEGACY_SPLIT_KEY = 'automation-console-split-ratio'

/**
 * 可用高：容器高扣掉分隔条那一行。**所有像素换算统一用它**。
 *
 * 老实现夹取时分母用 containerH（含那 20px 条）、而栅格渲染时条是固定行会被扣掉，
 * 两者差 20px，端点处会出现约 8~10px 的口径差（拖到顶时表现为「还差一点/多出来一点」）。
 */
function splitUsable(containerH: number): number {
  return Math.max(0, containerH - HANDLE_H)
}

/** 第三行（日志区 / 助手卡）的**模式下限**：日志态 140、助手态 300 */
function logRowMin(aiActive: boolean): number {
  return aiActive ? CONSOLE_AI_MIN_H : LOG_MIN_H
}

/**
 * 渲染用的第三行高度（px）：**始终取用户存下的固定高**，只有窗口真装不下时才缩到
 * 装得下的最大值（此时上方趋势让位，符合用户「下面固定，上面要动」的口径）。
 * 下限按模式取（日志 140 / 助手 300），所以助手态永远 ≥300px。
 */
function clampRowHeight(px: number, containerH: number, rowMinH: number): number {
  const usable = splitUsable(containerH)
  if (!(usable > 0)) return LOG_DEFAULT_H
  const lo = Math.min(rowMinH, usable)
  const want = Number.isFinite(px) ? px : LOG_DEFAULT_H
  return Math.max(lo, Math.min(want, usable))
}

/**
 * 拖动 / 键盘的合法区间（px）。
 *
 * · 下界 = 模式下限（窗口太矮时退化为可用高）；
 * · 上界 = 给实时趋势留 TREND_MIN_H（220），**但不小于当前值**：窗口矮到装不下时，
 *   渲染会照固定高显示（趋势让位），这时上界必须仍包含当前值，否则一拖就把日志「跳」矮。
 */
function rowHeightBounds(
  containerH: number,
  rowMinH: number,
  currentPx: number,
): { lo: number; hi: number } {
  const usable = splitUsable(containerH)
  if (!(usable > 0)) return { lo: 0, hi: LOG_DEFAULT_H }
  const lo = Math.min(rowMinH, usable)
  const hi = Math.max(lo, Math.min(usable, Math.max(usable - TREND_MIN_H, currentPx)))
  return { lo, hi }
}

/**
 * 读磁盘上的固定高度（px）。
 *
 * ⚠️ 旧版同一个位置存的是「日志占比」（0~1 的比例）。改成像素后旧值不再可用：一律忽略、
 * 回默认 190px，并把旧键清掉（下一次拖动 / 双击复位就写成像素值）。
 * 用「> 1」区分两种口径：比例恒 ≤ 1，像素高恒 > 1。
 */
function readLogHeight(): number {
  if (typeof localStorage === 'undefined') return LOG_DEFAULT_H
  try {
    localStorage.removeItem(LEGACY_SPLIT_KEY)
  } catch {
    /* 清不掉不影响本次 */
  }
  const raw = Number(localStorage.getItem(LOG_H_KEY))
  if (!Number.isFinite(raw) || raw <= 1) return LOG_DEFAULT_H
  return raw
}

/** 还原拖动期间锁住的光标与选区（拖动结束与组件卸载都要调，否则会残留在 body 上） */
function releaseBody() {
  document.body.style.removeProperty('cursor')
  document.body.style.removeProperty('user-select')
}

export function AutomationConsole({
  stages,
  stageStats,
  live,
  tools,
  logs,
  verdicts,
  onStop,
  terminalStatus,
  onShowResult,
}: {
  stages: StageView[]
  /** 阶段统计（成功/失败/跳过/总数），来自编排器状态，非时间推算 */
  stageStats: StageStats
  live: AutomationLiveState
  tools: AutomationToolState[]
  logs: AutomationLogEntry[]
  /** 后端权威判定（最后一次 runAndCollect 的结果） */
  verdicts: BackendVerdict[]
  onStop: () => void
  /**
   * 整轮终态（2026-10-09 新增）。`undefined` = 仍在跑。
   *
   * 为什么需要它：本节在**终态也会常驻**（结果弹窗收起后底座要留着，
   * 人才能接着看本轮数据）。此时「终止」按钮已无意义（对已终态调用 stop 是空操作），
   * 底部状态条也不该再说「准备中…」——那会被读成「还没跑」。
   */
  terminalStatus?: 'completed' | 'failed' | 'stopped'
  /** 终态且弹窗已收起时注入：重开完成弹窗（**只开弹窗，不触发任何执行**） */
  onShowResult?: () => void
}) {
  const uiT = useT()

  const pack = getPack()
  const overrides = useAppStore((s) => s.overrides)
  const snapshotValues = useAppStore((s) => s.snapshotValues)
  const adoptedApplied = useAppStore((s) => s.adoptedApplied)
  const adoptedKeys = useMemo(() => adoptedApplied.map((a) => a.key), [adoptedApplied])

  /* 参数视图：走与流程 3 左栏同一条回落链，调优采纳后会如实变成新值 */
  const params = useMemo(
    () => buildParamViews(pack, overrides, snapshotValues, { adoptedKeys, limit: 12 }),
    [pack, overrides, snapshotValues, adoptedKeys],
  )
  const { rows, stats } = useMemo(() => buildVerdictViews(verdicts), [verdicts])

  const cur = stages.find((s) => s.isCurrent)
  /* 秒级滴答：让「本阶段已用时」走动（起止时刻来自编排器，前端只做减法） */
  const now = useNow()
  const elapsedLive = useMemo(() => liveElapsedOf(stages, now), [stages, now])

  /* ---------------------------------------------- 第三行「日志 ↔ AI 助手」双态
   *
   * 2026-10-10 需求：日志卡右上角圆形 AI 按钮，点一下日志上卷、助手卡从下升起，
   * 再点（或点助手内「收起」）反向切回。原理是**双卡常驻 + transform 卷动**：
   *   · 两卡都保持挂载（absolute 叠在同一个卡片栈里）→ 日志滚动位置不丢、
   *     助手对话与进行中的回答不被切换打断（切走时只把卡片移出视野，不卸载）；
   *   · 位移用 transform.driver（GPU 合成、无布局抖动），motion-reduce 下降级为瞬时。
   *
   * `panel` 只影响两块：第三行的**像素下限**（日志 140 / 助手 300，见 CONSOLE_AI_MIN_H）
   * 与两卡的位移。
   * 它**不改日志数据逻辑、不新增任何轮询或硬件调用**（运行台纪律：不另起轮询、
   * 不启停台架），因此助手开合与测试运行完全解耦。
   */
  const [panel, setPanel] = useState<'log' | 'ai'>('log')
  const aiActive = panel === 'ai'
  /** 第三行的像素下限随模式取（日志 140 / 助手 300，见 CONSOLE_AI_MIN_H 注释） */
  const rowMinH = logRowMin(aiActive)

  /* ---------------------------------------------- 中栏「趋势 ↔ 日志」分隔条 */
  /** 日志区高度（px，**不是比例**）—— 窗口缩放时这个数不动，见 LOG_DEFAULT_H */
  const [logH, setLogH] = useState(readLogHeight)
  const splitRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  /** 按下分隔条那一刻的锚点：指针纵坐标 + 第三行当时的**实际像素高**（相对位移法） */
  const dragStart = useRef({ y: 0, h: 0 })
  /** 拆分栅格实测高度：夹取要用它算可用高 */
  const [splitH, setSplitH] = useState(0)

  /**
   * 落盘日志区高度（px）。**所有写入都经过这里**，按「给趋势留 220px」与当前模式下限
   * 夹取，因此存下的值一定可达 ⇒ 存值 = 屏上实际高度，指针与条不会分家
   * （这是人测页修「往下拉反而弹起来」时立的纪律）。入参可以是任何来源
   * （拖动位移、方向键步进、双击复位）。
   *
   * `currentPx` = 当前**屏上**的第三行高度：窗口太矮时渲染会保住固定高、让趋势让位，
   * 那种情况下上界若不包含当前值，一拖就会把日志「跳」矮（见 rowHeightBounds）。
   */
  const persistLogHeight = useCallback(
    (px: number, currentPx: number) => {
      const h = splitRef.current?.getBoundingClientRect().height ?? splitH
      const { lo, hi } = rowHeightBounds(h, rowMinH, currentPx)
      const next = Math.min(hi, Math.max(lo, Number.isFinite(px) ? px : lo))
      setLogH(next)
      try {
        localStorage.setItem(LOG_H_KEY, String(Math.round(next)))
      } catch {
        // 隐私模式下 localStorage 可能被禁；记不住不影响本次调整
      }
    },
    [splitH, rowMinH],
  )

  /* 容器高度跟随窗口/布局变化重算（窗口缩放、底部状态条换行等） */
  useEffect(() => {
    const el = splitRef.current
    if (!el) return
    const measure = () => setSplitH(el.getBoundingClientRect().height)
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  /* 视口/模式变化**不再改写高度状态**：用户存下的固定高一字不改，窗口装不下时只由渲染
   * 现算（clampRowHeight），窗口恢复后自动回到他存的那个高度（人测页同款纪律：不被任何
   * 逻辑强制复位）。删掉旧的 setRatio 收口还顺带解决一个隐患——它会在每次窗口缩放/切模式
   * 时把状态改成夹取后的值，导致「存值 ≠ 屏上高度」，下次拖动的起算点就是错的。 */

  /**
   * 拖拽：按下分隔条后监听 window 的 move/up，而不是条自己的。
   * 指针很容易在拖动中滑出这条 20px 的细条，绑在自己身上会中途丢事件。
   *
   * ⚠️ 2026-10-10（机测页助手高度修复）改为**指针相对位移**：按下时记下起点纵坐标与
   * 第三行当时的实际像素高，移动时用位移换算新高度。老实现按指针绝对纵坐标反算比例，
   * 一旦渲染被下限夹住，指针位置与卡片高度就各说各话（抓条瞬间跳变、往下拖不跟手）。
   * 相对位移严格 1:1 跟手，拖到边界就停在边界，不弹回也不跳。语义与原来一致——
   * 指针上移 = 下方区域（日志卡 / 助手卡）变大，与 ArrowUp 同向。
   */
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      if (!dragging.current) return
      const box = splitRef.current?.getBoundingClientRect()
      if (!box || box.height <= 0) return
      const usable = splitUsable(box.height)
      if (usable <= 0) return
      // 相对位移：指针往上（clientY 变小）→ 位移为正 → 日志区变高
      const nextH = dragStart.current.h - (e.clientY - dragStart.current.y)
      persistLogHeight(nextH, dragStart.current.h)
    }
    const onUp = () => {
      if (!dragging.current) return
      dragging.current = false
      releaseBody()
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      // ⚠️ 运行台会被整体卸载（跑完切结果页）：卸载时也要把锁住的光标/选区还原，
      // 否则会残留 row-resize 光标挂在 body 上，影响后续页面。
      releaseBody()
    }
  }, [persistLogHeight])

  const startDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    const box = splitRef.current?.getBoundingClientRect()
    if (!box) return
    const bar = e.currentTarget.getBoundingClientRect()
    dragging.current = true
    // 起点用**量到的实际高度**（条底边到容器底边 = 第三行高），而不是比例反推：
    // 夹取后的高度才是用户看到的高度，按它起算，抓住条的那一刻才不会跳一下。
    dragStart.current = { y: e.clientY, h: Math.max(0, box.bottom - bar.bottom) }
    // 拖动全程锁住光标与选区，否则手一快就选中了半屏文字
    document.body.style.cursor = 'row-resize'
    document.body.style.userSelect = 'none'
  }

  /**
   * 第三行（日志卡 / 助手卡）最终渲染高度（px）：
   * **默认恒为用户存下的固定高（190px）**，窗口缩放不动它；只有窗口真装不下时才缩到
   * 装得下的最大值（此时上方趋势让位 —— 用户口径「下面固定，上面要动」）。
   * 下限按模式取：日志态 140、助手态 300（助手卡不会被压回「被压扁」）。
   */
  const rowPx = clampRowHeight(logH, splitH, rowMinH)
  const usable = splitUsable(splitH)
  /** 拖动 / 键盘 / aria 报的真实可达区间（px，不是比例） */
  const bounds = rowHeightBounds(splitH, rowMinH, rowPx)
  /** 趋势行下限：给趋势留 220px；窗口太矮装不下时退到「剩多少算多少」，绝不溢出 */
  const trendMinPx = Math.max(0, Math.min(TREND_MIN_H, usable - rowPx))

  /**
   * 中栏三行模板（趋势 / 拖动条 / 日志卡或助手卡）。
   *
   * ⚠️ 2026-10-10 实测踩到的坑：两行**都写成比例**会留下一条空白。
   * `minmax(220px, a fr) 20px minmax(下限, b fr)`（a+b=1）一旦趋势被它 220px 的下限顶住
   * ——而拖到顶必然发生——剩下那行的 fr 之和就 < 1，按 CSS 规范「flex sum 小于 1 时按 1 计」，
   * 浏览器**不会**把剩余空间分完：1280×720 实测排成 220 / 20 / 216.1、缺口 130px；
   * 1920×692 下卡片恒为 216px、缺口 102px 且拖到顶毫无变化。
   *
   * 故：第三行直接给**像素**（固定高），趋势行 `1fr` 吃掉剩下的全部 ⇒ 三行之和恒等于
   * 容器高，既不溢出也不留空白。首帧还没量到容器高（splitH = 0）时用静态值兜底：
   * 绝不能给出 0 高，否则第三行会闪一帧空壳（测量回调随后在绘制前补上真实高度）。
   */
  const splitRows =
    splitH > 0
      ? `minmax(${trendMinPx}px, 1fr) ${HANDLE_H}px ${rowPx}px`
      : `minmax(${TREND_MIN_H}px, 1fr) ${HANDLE_H}px ${LOG_DEFAULT_H}px`

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* 三栏栅格：左栏口径与人测页面左栏**同源**（app/FlowScreen.tsx 的 minmax(300px,380px)）；
          右栏保持原档位；1280 以下（未进 xl）兜底窄一档，避免三栏互相挤压。 */}
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(280px,340px)_minmax(0,1fr)_300px] gap-2.5 overflow-y-auto 2xl:grid-cols-[minmax(300px,380px)_minmax(0,1fr)_320px] xl:grid-cols-[minmax(300px,380px)_minmax(0,1fr)_280px]">
        {/* ── 左栏：参数 + 执行动作 ──
            2026-10-10 样式统一（用户要求「照搬人测页面左栏」）：
              · 容器改用共享 Panel（surface-1：白底 + 圆角 + 柔阴影）；
              · 段头改用共享 PanelHeader（h-[44px] / px-4 / gap-2.5 / 标题 16px / 图标 17px），
                与人测左栏的「参数」标题条完全同规格；
              · 两段之间不再留卡片缝隙，改由 PanelHeader 自带的 border-b 分隔（人测同款）；
              · 行元素对齐人测 ParamRow 口径（min-h-[32px] / py-1 / pl-3 pr-3 / 名称 13px）。
            ⚠️ 只统一观感：菜单项内容、排序、来源徽标与「本轮采纳」语义全部保持原样。 */}
        <Panel>
          <PanelHeader
            icon={<SlidersHorizontal size={17} strokeWidth={1.9} />}
            title={uiT("自动选定的测试参数")}
            right={<span className="num text-[12px] text-t3">{params.length}</span>}
          />
          <div className="min-h-0 flex-1 overflow-y-auto py-1">
            {params.length ? (
              params.map((p) => (
                <Tooltip
                  key={p.key}
                  className="w-full"
                  content={uiT("{v1} · 来源：{v2}{v3}", { v1: p.fullName, v2: p.source, v3: p.adopted ? uiT('（本轮调优自动采纳）') : '' })}
                >
                  <div
                    className={cn(
                      'flex min-h-[32px] items-center gap-2 border-l-2 py-1 pr-3 pl-3 transition-colors',
                      p.adopted ? 'border-l-p700 bg-ink-wash' : 'border-l-transparent',
                    )}
                  >
                    {/* 先翻译全名、再截掉括号注释（顺序不能反，否则命中不了词典 key） */}
                    <span className="min-w-0 flex-1 truncate text-[13px] text-t1">
                      {uiT(p.name).replace(/[（(].*$/, '').trim()}</span>
                    <span
                      className={cn(
                        'shrink-0 rounded-full px-1.5 py-[1px] text-[10px] font-medium',
                        SOURCE_CLS[p.source],
                      )}
                    >
                      {uiT(p.source)}
                    </span>
                    <span className="num shrink-0 text-[13px] font-semibold text-t1">
                      {p.display}
                      {p.unit ? (
                        /* 单位也过 uiT：中文单位（如「次」）需译成 times；V/RPM/s 等
                           英文单位词典没有词条，translate 原样返回，不受影响。 */
                        <span className="ml-0.5 text-[11px] font-normal text-t3">{uiT(p.unit)}</span>
                      ) : null}
                    </span>
                  </div>
                </Tooltip>
              ))
            ) : (
              <p className="px-3 py-3 text-center text-[12px] text-t3">
                {uiT("场景包未加载，暂无参数可显示")}</p>
            )}
          </div>

          <ToolBlock tools={tools} />
        </Panel>

        {/* ── 中栏：实时趋势 + 执行日志（可拖分隔条）+ 状态条 ── */}
        <div className="flex min-h-[320px] flex-col gap-2.5">
          {/*
            拆分栅格：趋势 / 分隔条 / 日志 三行，gap:0 —— 行间距完全由 20px 的条承担。
            ⚠️ 若这里再留 gap，条上下会各多一道空档（流程页曾修过此坑）。
            两侧像素下限写进行模板（minmax），比例越界时栅格自动兜住，
            不会把图表压没、也不会把底部状态条挤出屏幕。
          */}
          <div
            ref={splitRef}
            className="grid min-h-0 flex-1 overflow-hidden"
            style={{ gridTemplateRows: splitRows, gap: '0' }}
          >
          {/* 2026-10-10 样式统一：中/右栏卡标题条与左栏、人测页面同规格
              （Panel + PanelHeader：h-[44px] / px-4 / 标题 16px / 图标 17px；计数 12px）。 */}
          <Panel>
            <PanelHeader
              icon={<Activity size={17} strokeWidth={1.9} />}
              title={uiT("实时趋势")}
              left={<TrendPill cur={cur} live={live} terminalStatus={terminalStatus} />}
              right={
                <span className="num text-[12px] text-t3">
                  {live.plan
                    ? uiT("计划 {v1}s", { v1: live.plan.planned_duration_s })
                    : ''}
                  {/* ⚠️ 「· 实际 {v1}s」必须**单独过一次 uiT**，不能当参数拼进外层模板：
                      参数值不会被递归翻译成整句（它是数据），拼进去就会残留中文「实际」。
                      key 必须与 catalog **逐字符一致**（不含前导空格），空格由 JSX 表达式间的
                      空白提供。写法与 FanTrendView 保持一致。 */}
                  {live.plan?.actual_duration_s != null
                    ? ` ${uiT('· 实际 {v1}s', { v1: live.plan.actual_duration_s })}`
                    : ''}
                  {live.plan?.overrun ? uiT('（已延期）') : ''}
                </span>
              }
            />
            <div className="min-h-0 flex-1 p-2">
              {/*
                与 /run 人测页**同一套**时序曲线 UI（工具行 + 四通道读数行 + 趋势/波形
                切换 + 回到全程），复用 `FanTrendView` 受控展示卡——两处不再各写一份。
                数据仍来自编排器实时流（`automationLive`），这里**不另起轮询、不启停台架**，
                免得与编排器抢单设备锁（409）。
                chartMinH 传 140：本卡所在的中栏趋势行下限是 220px，工具行与读数行叠加
                后要留出空间，紧凑降级交给 FanTrendChart 既有的 full/slim/tiny。
              */}
              <FanTrendView
                plan={live.plan}
                samples={live.samples}
                phaseLabel={live.plan?.status}
                error={live.plan?.error}
                runId={live.plan?.run_id ?? null}
                chartMinH={140}
                emptyHint={
                  cur?.id === 'run'
                    ? uiT('正在下发台架启动指令，拿到首批样本后这里会实时绘制占空比 / 电压 / 电流 / 转速曲线（缺测断线不补零）')
                    : uiT('台架尚未启动。本步骤之前不会产生任何曲线——这里只画真采到的数据。')
                }
              />
            </div>
          </Panel>

          {/*
            可拖拽分隔条：常显抓握手柄（用户曾反馈「没注意到有这个条」，故不藏）。
            role="separator" + aria-* 让读屏软件知道这是可调整的分隔，方向键也能调。
            交互与视觉口径与流程页 app/FlowScreen.tsx 那条**同源**，保持手感一致。

            2026-10-10：aria 报的是**像素**（执行日志区当前高度与真正能拖到的上下界），
            因为这块现在是「固定像素高」而不是比例——报比例会与实际屏上高度对不上。
            双击复位回 LOG_DEFAULT_H（190px），方向键 ±20px（Shift ±60px）。
          */}
          <div
            role="separator"
            data-testid="auto-console-splitter"
            aria-orientation="horizontal"
            aria-label={uiT("调整实时趋势与执行日志的高度")}
            aria-valuenow={Math.round(rowPx)}
            aria-valuemin={Math.round(bounds.lo)}
            aria-valuemax={Math.round(bounds.hi)}
            aria-valuetext={uiT("执行日志区 {v1} 像素", { v1: Math.round(rowPx) })}
            tabIndex={0}
            onPointerDown={startDrag}
            onDoubleClick={() => persistLogHeight(LOG_DEFAULT_H, rowPx)}
            onKeyDown={(e) => {
              // ArrowUp = 日志区变大（与流程页「上键把下方区域拉大」同向）
              // 从**当前屏上高度**起算（rowPx 已是夹取后的值），步进踩在人看得见的高度上
              const step = e.shiftKey ? 60 : 20
              if (e.key === 'ArrowUp') {
                e.preventDefault()
                persistLogHeight(rowPx + step, rowPx)
              } else if (e.key === 'ArrowDown') {
                e.preventDefault()
                persistLogHeight(rowPx - step, rowPx)
              }
            }}
            className="group flex cursor-row-resize items-center justify-center focus-visible:outline-none"
            title={uiT("拖动调整执行日志区高度（默认 190px，双击复位）")}
          >
            <span className="flex items-center gap-1 rounded-full bg-p50/70 px-2.5 py-[3px] transition-colors group-hover:bg-p50 group-focus-visible:bg-p50">
              <span className="h-[2px] w-5 rounded-full bg-t3/60 transition-colors group-hover:bg-ink group-focus-visible:bg-ink" />
              <span className="h-[4px] w-14 rounded-full bg-t2/70 transition-all group-hover:h-[5px] group-hover:bg-ink group-focus-visible:h-[5px] group-focus-visible:bg-ink" />
              <span className="h-[2px] w-5 rounded-full bg-t3/60 transition-colors group-hover:bg-ink group-focus-visible:bg-ink" />
            </span>
          </div>

          {/*
            第三行「日志卡 ↔ AI 助手卡」卷动卡片栈（2026-10-10）。
            · 双卡 absolute 叠放、都保持挂载 → 切换不卸载、不丢状态；
            · 位移用 transform 卷动（日志 -100% 收向顶部、助手 +100% 升起），
              motion-reduce 下 CSS 已取消过渡 → 瞬时切换；
            · 圆形 AI 按钮**不随卷动位移**（固定在卡片栈右上角、悬浮于卡片之上），
              两态恒可点击；两卡头部各留右侧避让，按钮不遮任何既有内容。
          */}
          <div className="relative min-h-0">
            <div className="relative h-full overflow-hidden rounded-tps">
              <div
                className={cn(
                  'absolute inset-0 transition-transform duration-300 ease-[cubic-bezier(0.22,0.75,0.3,1)] motion-reduce:transition-none',
                  aiActive ? '-translate-y-full' : 'translate-y-0',
                )}
                inert={aiActive}
                aria-hidden={aiActive}
              >
                <LogStream logs={logs} />
              </div>
              <div
                className={cn(
                  'absolute inset-0 transition-transform duration-300 ease-[cubic-bezier(0.22,0.75,0.3,1)] motion-reduce:transition-none',
                  aiActive ? 'translate-y-0' : 'translate-y-full',
                )}
                inert={!aiActive}
                aria-hidden={!aiActive}
              >
                <ConsoleChatPanel onCollapse={() => setPanel('log')} />
              </div>
            </div>
            <ConsoleAiButton active={aiActive} onClick={() => setPanel((p) => (p === 'ai' ? 'log' : 'ai'))} />
          </div>
          </div>

          <div className="grad-ink flex shrink-0 items-center gap-2 rounded-tps px-3 py-2 text-white">
                      <PlayCircle size={14} strokeWidth={1.9} className="shrink-0" />
                  <span className="min-w-0 flex-1 truncate text-[12.5px]">
                        {terminalStatus
                          ? uiT("本轮已结束（{v1}）{v2}", { v1: uiT(TERMINAL_LABEL[terminalStatus]), v2: cur?.message ? uiT(" · 末阶段：{v1}", { v1: uiT(cur.message) }) : '' })
                          : cur
                            ? uiT("{v1} · {v2}", { v1: uiT(cur.name), v2: cur.message ? uiT(cur.message) : uiT('进行中') })
                            : uiT('准备中…')}
               </span>
                      {/* 已采样本条数：让「跑到哪了」有个硬指标（0 条就是还没采到，不粉饰） */}
                        <span className="num shrink-0 text-[11.5px] opacity-80">
                          {uiT("已采 ")}{live.samples.length} {uiT(" 条")}</span>
              {/*
                终态不再报「本阶段已用时」：此刻没有「当前阶段」了，
                那个数字会停在最后一刻、看着像还在跑（与状态条同一口径）。
              */}
              {!terminalStatus ? (
                <span className="num shrink-0 text-[11.5px] opacity-80">
                    {uiT("本阶段 ")}{elapsedLive === null ? '—' : fmtElapsed(elapsedLive)}
                      </span>
              ) : null}
            {/*
              「终止」只在运行态出现：对已终态调用 stop 是空操作（编排器直接 return），
              留一个点了没反应的按钮比不放更糟。终态原位换「查看执行结果」——
              它只重开弹窗，**不触发任何执行**（不新增第二个启动/重跑入口）。
            */}
            {terminalStatus ? (
              onShowResult ? (
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<FileBarChart size={13} strokeWidth={1.9} />}
                  onClick={onShowResult}
                  data-testid="auto-console-show-result"
                  className="border-white/40 bg-white/10 text-white hover:bg-white/20"
                >
                  {uiT("查看执行结果")}</Button>
              ) : null
            ) : (
              <Button
                variant="danger"
                size="sm"
                icon={<CircleSlash size={13} strokeWidth={2} />}
                onClick={onStop}
                data-testid="auto-console-stop"
              >
                {uiT("终止")}</Button>
            )}
          </div>
        </div>

        {/* ── 右栏：进度 + 判据统计 + 判据列表 ── */}
        <div className="flex min-h-0 flex-col gap-2.5">
          <ProgressCard stageStats={stageStats} />
          <VerdictPanel stats={stats} rows={rows} />
        </div>
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- 子组件 */

/**
 * 秒级滴答：返回当前时刻（ms），只用于让「本阶段已用时」走动。
 * ⚠️ 它只是重渲染的节拍源，**不产生任何业务状态**，也不当计时器基准
 * （真实耗时一律用编排器写的 startTime/endTime 做减法）。
 */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [])
  return now
}

/**
 * 当前阶段的实时已用时（ms）。
 *
 * ⚠️ 阶段未结束时编排器不给 endTime（`elapsed` 为 null），此时若直接取 0 会让
 * 「本阶段已用时」永远显示 0s，看着像卡住了。所以按 startTime 实时减——
 * startTime 也是编排器写的，这里只做减法，不自己起计时器。
 */
function liveElapsedOf(stages: StageView[], now: number): number | null {
  const cur = stages.find((s) => s.isCurrent)
  if (!cur) return null
  if (cur.elapsed !== null) return cur.elapsed
  if (cur.startTime === null) return null
  return Math.max(0, now - cur.startTime)
}

/**
 * 趋势卡右上角状态胶囊：当前档位 / 真实 vs 模拟 / 缺测说明。
 *
 * ⚠️ 终态没有「当前阶段」了，此时不再显示「待命」——那会把人读成
 * 「还没开始跑」，可实际上本轮刚刚跑完（且数据就在图上）。
 */
function TrendPill({
  cur,
  live,
  terminalStatus,
}: {
  cur?: StageView
  live: AutomationLiveState
  terminalStatus?: 'completed' | 'failed' | 'stopped'
}) {
  const uiT = useT()

  const last = live.samples.length ? live.samples[live.samples.length - 1] : null
  const rpm = last && typeof last.rpm === 'number' ? `${Math.round(last.rpm)} rpm` : null
  const why = [...live.samples].reverse().find((s) => s.quality?.rpm)?.quality?.rpm
  return (
    <span className="flex min-w-0 items-center gap-1.5 rounded-full bg-ink-wash px-2 py-[3px] text-[11.5px] text-t2">
      <span
        className={cn(
          'h-[6px] w-[6px] shrink-0 rounded-full',
          /* 终态点不再呼吸：那不是「正在跑」的信号 */
          terminalStatus ? 'bg-p600' : 'automation-pulse bg-p700',
        )}
      />
      <span className="shrink-0">
        {terminalStatus ? uiT("本轮已结束（{v1}）", { v1: uiT(TERMINAL_LABEL[terminalStatus]) }) : cur ? uiT(cur.name) : uiT('待命')}
      </span>
      {last ? (
        <>
          <span className="text-t3">·</span>
          <span className="num shrink-0">
            {last.commanded_pwm_pct}{uiT("% 档")}</span>
        </>
      ) : null}
      <span className="text-t3">·</span>
      <span className="num shrink-0 text-p700">
        {rpm ?? uiT("转速未采集{v1}", { v1: why ? `（${why}）` : '' })}
      </span>
      {live.plan?.simulation ? (
        <span className="shrink-0 text-alert">{uiT("· 模拟数据")}</span>
      ) : null}
    </span>
  )
}

/** 左栏「执行动作」区块：真实调用三态，由编排器按 promise 生命周期围栏。
 *  2026-10-10 样式统一：并入左栏同一张 Panel（不再单独成卡），段头用共享 PanelHeader、
 *  行元素用人测页面左栏的行口径；三态语义与文案一字未改。 */
function ToolBlock({ tools }: { tools: AutomationToolState[] }) {
  const uiT = useT()

  return (
    <>
      <PanelHeader
        icon={<Zap size={17} strokeWidth={1.9} />}
        title={uiT("执行动作")}
        right={<span className="num text-[12px] text-t3">{tools.length}</span>}
      />
      <div className="min-h-[160px] flex-1 overflow-y-auto py-1">
        {tools.length ? (
          tools.map((t) => (
            <Tooltip key={t.id} className="w-full" content={uiT(t.message ?? t.label)}>
              <div className="flex min-h-[32px] items-center gap-2 py-1 pr-3 pl-3">
                <span
                  className={cn(
                    'h-[6px] w-[6px] shrink-0 rounded-full',
                    t.status === 'failed'
                      ? 'bg-alert'
                      : t.status === 'done'
                        ? 'bg-p600'
                        : t.status === 'skipped'
                          ? 'bg-t3/40'
                          : 'automation-pulse bg-ink',
                  )}
                />
                <span
                  className={cn(
                    'min-w-0 flex-1 truncate text-[13px]',
                    t.status === 'done' || t.status === 'skipped' ? 'text-t3' : 'text-t1',
                  )}
                >
                  {uiT(t.label)}
                </span>
                <span className="num shrink-0 text-[11.5px] text-t3">
                  {t.status === 'running'
                    ? uiT('进行中')
                    : t.status === 'done'
                      ? uiT('已完成')
                      : t.status === 'failed'
                        ? uiT('失败')
                        : uiT('已跳过')}
                </span>
              </div>
            </Tooltip>
          ))
        ) : (
          <p className="px-3 py-3 text-center text-[12px] text-t3">
            {uiT("尚未开始执行，第一个动作出现后这里会逐条列出")}</p>
        )}
      </div>
    </>
  )
}

/** 中栏执行日志流：深色底 + 等宽字体，四级色 */
const LOG_CLS: Record<AutomationLogEntry['level'], string> = {
  info: 'text-white/75',
  success: 'text-[#7FD1A8]',
  warn: 'text-[#F0C36D]',
  error: 'text-[#F09A9E]',
}

function LogStream({ logs }: { logs: AutomationLogEntry[] }) {
  const uiT = useT()

  const boxRef = useRef<HTMLDivElement>(null)
  // 新的日志在末尾，滚到底部才能看到最新一条（倒序不装，用原生滚动更符合阅读习惯）
  useEffect(() => {
    const el = boxRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [logs.length])

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-tp bg-[#1A2320]">
      {/* ⚠️ 头部右侧留 52px：右上角悬浮着圆形 AI 按钮（不随卷动位移），
          不给「N 条」计数让位的话会被按钮压住。
          2026-10-10 样式统一：标题条改用与其它卡相同的 h-[44px] / 16px 标题 / 17px 图标
          规格（圆角同步为 rounded-tp）；只有配色仍是深色卡自己的（不套浅色 PanelHeader，
          否则白字会被压成黑字）。 */}
      <header className="flex h-[44px] shrink-0 items-center gap-2.5 border-b border-white/10 pr-[52px] pl-4">
        <Terminal size={17} strokeWidth={1.9} className="shrink-0 text-white/70" />
        <h2 className="shrink-0 text-[16px] leading-none font-semibold tracking-tight whitespace-nowrap text-white">
          {uiT("执行日志")}</h2>
        <span className="num ml-auto text-[12px] text-white/60">{logs.length} {uiT(" 条")}</span>
      </header>
      {/* log-scroll：深色区专属浅色滚动条 + 固定水槽，让右侧竖条常显、可直接拖动
          （全局浅绿滚动条在 #1A2320 深底上看不见，见 index.css 的 .log-scroll 说明）。 */}
      <div ref={boxRef} className="log-scroll min-h-0 flex-1 overflow-y-auto px-3 pb-2">
        {logs.length ? (
          logs.map((l) => (
            <div key={l.seq} className="automation-log-line mono flex gap-2 text-[11px] leading-[18px]">
              <span className="num shrink-0 text-white/30">{fmtClock(l.at)}</span>
              <span className={cn('min-w-0 flex-1 break-words', LOG_CLS[l.level])}>{uiT(l.message)}</span>
            </div>
          ))
        ) : (
          <p className="py-2 text-[11px] text-white/35">
            {uiT("等待第一条执行记录…（参数落库、闸门代确认、指令下发、各档采集、判定结果都会出现在这里）")}</p>
        )}
      </div>
    </section>
  )
}

/**
 * 卡片栈右上角的圆形「AI」按钮（2026-10-10）。
 *
 * 定位：悬浮在卡片之上、绝对右上角，**不随卷动位移**（两态同一位、恒可点击）。
 * 语义随状态切换（`aria-pressed` / `aria-label` / tooltip），两态都用同一枚按钮。
 * 视觉：墨绿渐充实心 + 白色加粗「AI」，悬浮阴影营造漂浮感；hover 轻微放大、
 * active 下压、focus-visible 显式描边环；助手态加一圈激活光环以示「已展开」。
 */
function ConsoleAiButton({ active, onClick }: { active: boolean; onClick: () => void }) {
  const uiT = useT()

  return (
    <button
      type="button"
      data-testid="auto-log-ai-toggle"
      aria-pressed={active}
      aria-label={active ? uiT('返回执行日志') : uiT('切换到 AI 助手')}
      title={active ? uiT('返回执行日志') : uiT('切换到 AI 助手')}
      onClick={onClick}
      className={cn(
        'grad-ink absolute top-1.5 right-2 z-10 flex h-9 w-9 items-center justify-center rounded-full',
        'text-[12px] font-bold text-white shadow-tpink transition-transform',
        'hover:scale-105 active:scale-95',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-p50 focus-visible:ring-offset-2 focus-visible:ring-offset-surface',
        active ? 'ring-2 ring-p100' : '',
      )}
    >
      AI
    </button>
  )
}

/** 右栏执行进度卡：阶段完成数 / 总数 + 进度条（取真实阶段状态，不按时间假推） */
function ProgressCard({ stageStats }: { stageStats: StageStats }) {
  const uiT = useT()

  const done = stageStats.done + stageStats.skipped
  const total = stageStats.total
  const failed = stageStats.failed > 0
  return (
    <Panel className="shrink-0">
      {/* 标题条右侧刻意留空：阶段数已在卡内以大号数字 + 进度条呈现，
          再放一份就是同一信息说两遍（用户对冗余元素敏感）。 */}
      <PanelHeader icon={<Gauge size={17} strokeWidth={1.9} />} title={uiT("执行进度")} />
      <div className="px-4 py-3">
        <div className="flex items-baseline gap-1.5">
          <span className="num text-[24px] leading-none font-bold text-p700">{done}</span>
          <span className="num text-[12px] text-t3">/ {total} {uiT(" 个阶段")}</span>
        </div>
        <div className="mt-2 h-[6px] w-full overflow-hidden rounded-full bg-p100">
          <div
            className={cn('h-full rounded-full transition-[width] duration-300', failed ? 'bg-alert' : 'grad-ink')}
            style={{ width: fmtPct(done, total) === '—' ? '0%' : fmtPct(done, total) }}
          />
        </div>
      </div>
    </Panel>
  )
}

/** 右栏判据面板：四类计数分列 + 判据逐条（不适用单列，逐条写明缺什么） */
function VerdictPanel({ stats, rows }: { stats: VerdictStats; rows: VerdictView[] }) {
  const uiT = useT()

  const cells: { label: string; n: number; cls: string }[] = [
    { label: '通过', n: stats.pass, cls: 'text-p700' },
    { label: '不通过', n: stats.fail, cls: stats.fail > 0 ? 'text-alert' : 'text-t3' },
    { label: '未采集', n: stats.missing, cls: 'text-t2' },
    { label: '本台架不适用', n: stats.notApplicable, cls: 'text-t3' },
  ]
  return (
    <Panel className="flex-1">
      <PanelHeader
        icon={<AlertTriangle size={17} strokeWidth={1.9} />}
        title={uiT("判定结果")}
        right={
          <span className="num text-[12px] text-t3">
            {stats.total === null ? uiT('待判定') : uiT("{v1} 条", { v1: stats.total })}
          </span>
        }
      />
      <div className="grid shrink-0 grid-cols-4 gap-1 border-b border-line-soft px-4 py-2">
        {cells.map((c) => (
          <div key={c.label} className="flex flex-col items-center gap-0.5">
            <span className={cn('num text-[17px] leading-none font-bold', c.cls)}>
              {stats.total === null ? '—' : c.n}
            </span>
            <span className="text-center text-[10px] leading-tight text-t3">{uiT(c.label)}</span>
          </div>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto py-1">
        {rows.length ? (
          rows.map((v) => (
            <Tooltip key={v.reqId} className="w-full" content={uiT("{v1} · {v2}", { v1: v.reqId, v2: v.detail || v.name })}>
              <div
                className={cn(
                  'mb-1 flex min-h-[32px] items-center gap-2 rounded-tps px-3 py-1',
                  v.tone === 'fail' ? 'bg-alert-wash' : 'bg-sunk',
                )}
              >
                <span
                  className={cn(
                    'h-[6px] w-[6px] shrink-0 rounded-full',
                    v.tone === 'pass'
                      ? 'bg-p600'
                      : v.tone === 'fail'
                        ? 'bg-alert'
                        : v.tone === 'manual'
                          ? 'bg-warn'
                          : 'bg-t3/40',
                  )}
                />
                <span className="min-w-0 flex-1 truncate text-[13px] text-t1">{uiT(v.name)}</span>
                <span
                  className={cn(
                    'num max-w-[45%] shrink-0 truncate text-[11.5px]',
                    v.tone === 'fail' ? 'text-alert' : 'text-t3',
                  )}
                >
                  {uiT(v.valueText)}
                </span>
              </div>
            </Tooltip>
          ))
        ) : (
          <p className="px-3 py-3 text-center text-[12px] leading-5 text-t3">
            {uiT("本轮判定还没出来。判定由后端出权威结论，跑完一轮后逐条列出—— 缺测的项会写「未采集」，本台架测不了的会写明缺哪台设备。")}</p>
        )}
      </div>
    </Panel>
  )
}
