import { useT } from '../i18n'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { NavLink, useLocation } from 'react-router'
import {
  Activity,
  AlertOctagon,
  Archive,
  Check,
  CheckCheck,
  CircleSlash,
  Eye,
  CheckCircle2,
  Download,
  FileSignature,
  FolderPlus,
  Layers,
  ListChecks,
  Lock,
  PlayCircle,
  RotateCcw,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  Square,
  Upload,
  Wand2,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Avatar, Button, StatusDot, Tooltip, cn } from '../components/ui'
import { FLOWS, FLOW_BY_PATH } from '../data/flows'
import type { FlowId } from '../data/types'
import { FLOW_ICON, FLOW_SHORT, MODULE_ICON, MODULE_SHORT } from './icons'
import { useKnowledgeTotal } from '../features/knowledge/data'
import { RUN_PHASE_LABEL, flowStateOf, useAppStore } from '../state/useAppStore'
import { useFlowActions } from '../features/redline'
import { useStageReturnCue } from '../features/automation/useStageReturnCue'
import { useFlowBarScale } from '../features/shared/useFlowBarScale'
import { FlowSegLink, RUN_TUNE_LOOP_SEG, segPhaseOf } from '../features/shared/FlowSegLink'
import { ProductCascader } from './ProductCascader'
import { useLocale } from '../i18n'

/** 动作条图标：按动作 id 映射，缺省给一枚通用图标 */
const ACTION_ICON: Record<string, LucideIcon> = {
  upload: Upload,
  'new-class': FolderPlus,
  'to-exp': Sparkles,
  'manage-entry': ListChecks,
  autofill: Wand2,
  'save-tpl': Save,
  validate: CheckCircle2,
  lock: Lock,
  'pick-wf': Layers,
  'import-std': Upload,
  'edit-wf': ListChecks,
  baseline: ShieldCheck,
  start: PlayCircle,
  precheck: ShieldCheck,
  stop: Square,
  estop: AlertOctagon,
  'adopt-back': CheckCheck,
  'ignore-all': CircleSlash,
  rollback: RotateCcw,
  'view-evidence': Search,
  'gen-report': FileSignature,
  preview: Eye,
  export: Download,
  'archive-kb': Archive,
  search: Search,
}

/**
 * 把自动化阶段 id 映射到对应的五流程 id。
 *
 * 2026-10-10 修正：编排器的阶段 id **就是**五流程 id
 * （`automationOrchestrator.ts` 的 DEFAULT_CONFIG：init / req / run / tune / report），
 * 旧实现按早已废弃的 7 阶段 id（init-params / load-cases / …）做 switch，
 * 对现编排器恒返回 null → 顶栏在自动化期间**永远不会**点亮/打勾/报错。
 * 现改为按流程 id 直映射；非五个流程 id 一律 null（不误点亮）。
 */
function flowOfAutomationStage(stageId: string | null): FlowId | null {
  if (!stageId) return null
  return (FLOWS.some((f) => f.id === stageId) ? stageId : null) as FlowId | null
}

/** 五流程 stepper：圆形序号 / 打勾，短名 ≤6 字。知识库不在其中。
 *  自动化运行期间，当前阶段对应的流程高亮脉冲、已完成成功态、失败错误态。
 *
 *  2026-10-09 改造（用户反馈）：
 *   ① 「上方的 UI 太宽」——容器原为 `flex-1`，被拉伸占满顶栏剩余宽度，观感横跨全屏。
 *      现去掉 `flex-1`，改为**按内容自适应宽度 + 自身居中**（`relative` + `mx-auto` 语义），
 *      并把阶段内边距（px-2.5→px-2）、阶段间距（mx-1.5→mx-1）、连接线（w-4/lg:w-7→w-3/lg:w-5）各收一档。
 *   ② 「阶段之间需要有动效」——原来每项各自 `bg-p50` 淡入淡出，**无位移**。
 *      现改为**单一绝对定位高亮块**（`FLOW_PILL`），随激活项 `translateX` 平滑滑动过去。
 *      测量用 `useLayoutEffect` + `ResizeObserver`（断点/窗口变化时重测），避免错位。
 */
function FlowStepper() {
  const uiT = useT()
  const { locale } = useLocale()
  const [narrowViewport, setNarrowViewport] = useState(() => window.matchMedia('(max-width: 1799px)').matches)
  useEffect(() => {
    const query = window.matchMedia('(max-width: 1799px)')
    const update = () => setNarrowViewport(query.matches)
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])
  const compactSteps = narrowViewport

  const { pathname } = useLocation()
  // 模块路由（/knowledge）不属于任何一步，此时 stepper 不点亮任何一步
  const current = FLOW_BY_PATH[pathname] ?? FLOWS[0]
  const onFlow = !!FLOW_BY_PATH[pathname]
  const scene = useAppStore((s) => s.scene)
  const confirmed = useAppStore((s) => s.confirmed)
  // 自动化运行态：订阅阶段列表与当前阶段，用于顶栏实时点亮
  const autoRunning = useAppStore((s) => s.automationRunStatus === 'running')
  const autoStages = useAppStore((s) => s.automationStages)
  const autoCurrent = useAppStore((s) => s.automationCurrentStageId)
  // 当前节点在 FLOWS 中的下标：仅「当前 → 下一」段（下标 +1）播放进度动效
  const autoFlowId = autoRunning ? flowOfAutomationStage(autoCurrent) : null
  const curIdx = autoFlowId ? FLOWS.findIndex((f) => f.id === autoFlowId) : -1
  /* 人测运行态（2026-10-10）：测试运行中给**当前节点**播「光圈扩散」。
     ⚠️ 自动化运行期间 runPhase 也会被置 running（编排器启动台架时写的），
     必须排除 autoRunning —— 否则自动化页面的顶栏节点也会起光圈，
     而需求单要求「自动测试页面流程条零动效改动」。 */
  const runPhase = useAppStore((s) => s.runPhase)
  const humanRunning = !autoRunning && runPhase === 'running'

  // ── 缩放：按可用槽宽等比缩放，保证任何分辨率单行；文字过小则进入紧凑模式 ──────
  // 2026-10-10 调整：整体倍率由 2× 回落到 1.5×（用户反馈「显示尺寸过大」）。
  // 基准：节点高 78、圆标 39、字号 19.5、图标 21、段宽 48、顶栏高 120。
  // labelPx = 20（1.5× 后标签基准字号）；小于 10px 时隐藏文字、保留图标+序号+悬停全称
  const { slotRef, barRef, scale, compact } = useFlowBarScale<HTMLDivElement>({
    contentKey: `${locale}:${compactSteps}`,
    fixedScale: compactSteps ? 0.5 : undefined,
    labelPx: 20,
    compactTextPx: 10,
  })

  // ── 滑动高亮块：测量当前激活项相对 nav 的 offsetLeft/offsetWidth ──────────────
  const navRef = useRef<HTMLDivElement>(null)
  // null = 尚未测量 / 非流程页（不显示高亮），避免首帧从 0 位滑入的抖动
  const [pill, setPill] = useState<{ x: number; w: number } | null>(null)

  useLayoutEffect(() => {
    const nav = navRef.current
    if (!nav) return
    const measure = () => {
      if (!onFlow) {
        setPill(null)
        return
      }
      const el = nav.querySelector<HTMLElement>('[data-active="true"]')
      if (!el) {
        setPill(null)
        return
      }
      // ⚠️ 2026-10-10 修「选中阴影错位」残余项：原用 el.offsetLeft/offsetWidth，
      // 但 offset* 是**当前布局快照**——scale 由 useFlowBarScale 异步落 DOM，
      // 竞态帧里读到的是旧几何（实测 /report 最后一段恒定偏 +8px）。
      // 改用 getBoundingClientRect 相对 nav 实时换算（读的是真实渲染位置，
      // 且 nav 与 el 同源同帧，不受缩放/字体未就绪影响）；四舍五入到 0.5px 保证稳定。
      const navRect = nav.getBoundingClientRect()
      const elRect = el.getBoundingClientRect()
      const x = Math.round((elRect.left - navRect.left) * 2) / 2
      const w = Math.round(elRect.width * 2) / 2
      setPill((p) => (p && Math.abs(p.x - x) < 0.5 && Math.abs(p.w - w) < 0.5 ? p : { x, w }))
    }
    measure()
    // scale 落 DOM 是在下一帧（useFlowBarScale 的 useEffect→setScale→useLayoutEffect），
    // 因此补一次 rAF 重测，消除「测量早于缩放落地」的最后一段错位。
    const raf = window.requestAnimationFrame(measure)
    const ro = new ResizeObserver(measure)
    ro.observe(nav)
    // 断点切换会改变连接线宽度 → 触发 nav 尺寸变化，ResizeObserver 已覆盖；
    // 另监听字体加载完成后的一次重测，避免 web font 落地后宽度跳动导致错位。
    if (document.fonts?.ready) void document.fonts.ready.then(measure)
    return () => {
      window.cancelAnimationFrame(raf)
      ro.disconnect()
    }
    // scale / compact 变化会改变节点几何 → 一并重测高亮块位置
  }, [current.id, onFlow, autoCurrent, autoRunning, scale, compact, uiT])

  // 退回提示：自动化调优循环「tune 采纳 → 回 run 重跑」时，该段走反向动效
  const returning = useStageReturnCue()

  // 顶栏外框高度：随缩放放大到 132×s，但不低于 80px（上一轮已验收的高度）
  useLayoutEffect(() => {
    const nav = navRef.current
    if (!nav) return
    const header = nav.closest('header')
    if (!header) return
    header.style.setProperty('--topbar-h', `max(80px, ${Math.round(120 * scale)}px)`)
  }, [scale])

  return (
    // 窄屏自适应（2026-10-15）：加 topbar-stepper-slot 作为 CSS 断点钩子。
    // ≤1024px 时它被设为 flex-basis:100% + order:2，让流程条独占一整行，
    // 避免与品牌区 / 自动化按钮 / 右侧控件组在同一行互相挤压（它们都是
    // shrink-0，谁也不肯让）。此处 min-width 语义保持原样不动。
    <div ref={slotRef} className={cn('topbar-stepper-slot flex flex-1 items-center justify-center', compactSteps ? 'min-w-[240px]' : 'min-w-0')}>
    <nav
      ref={(el: HTMLDivElement | null) => {
        navRef.current = el
        barRef.current = el
      }}
      aria-label={uiT("五流程")}
      data-flow-bar="top"
      style={{ '--fb-scale': scale } as React.CSSProperties}
      className="relative flex w-fit shrink-0 items-center justify-center"
    >
      {/* 滑动高亮底：纯装饰（aria-hidden），随激活项做 transform 位移。
          ⚠️ 2026-10-10 修「选中阴影错位」根因：此块 `absolute` 但未设 left，
          nav 又是 justify-center 的 flex 容器 → 它作为首个静态子项被布局在
          **内容流居中位置**（实测 static left ≈ 198px），于是最终位置 =
          静态 left + translateX(offsetLeft)，凭空多出一段居中偏移（各路由实测
          恒定 +233px，pill 跑到相邻/空白处）。修复：显式 left-0，让 translateX
          从 nav 左边缘起算，与 offsetLeft 同源。
          --flow-pill-dur 由 CSS 控制（prefers-reduced-motion 下降级为 0）。 */}
      {pill && onFlow ? (
        <span
          aria-hidden
          data-testid="flow-stepper-pill"
          className="flow-pill absolute inset-y-1 left-0 rounded-full bg-p50"
          style={{ transform: `translateX(${pill.x}px)`, width: pill.w }}
        />
      ) : null}
      {FLOWS.map((f, i) => {
        // 2026-10-29：文案只留中文原文，英文由 catalog 提供（此处原先还判了 locale）。
        const precondition = f.id === 'report'
          ? uiT('核对检测结果后整理报告；调参复测按需进行。')
          : uiT(f.precondition ?? '')
        const state = flowStateOf(f.id, current.id, scene, confirmed)
        const on = onFlow && f.id === current.id
        const done = state === 'confirmed'
        const Icon = FLOW_ICON[f.id]
        // 自动化：当前阶段命中的流程 → 高亮脉冲；该流程已有成功阶段 → 成功态；失败 → 错误态
        const autoIsCurrent = autoRunning && autoFlowId === f.id
        const autoStageForFlow = autoStages.find((s) => flowOfAutomationStage(s.id) === f.id)
        const autoDone = autoRunning && autoStageForFlow?.status === 'success'
        const autoFailed = autoRunning && autoStageForFlow?.status === 'failed'
        /* 连接段（2026-10-10 第二轮）：段相位统一由 FlowSegLink/segPhaseOf 推导。
             · 仅「当前节点 → 下一节点」段有动效（亮色流光 + 亮绿箭头循环平移）；
             · 已走过段（左节点完成）纯静态线，无箭头；
             · 未到达段（运行中）纯静态暗线，无箭头（暗色小箭头已按用户指令移除）；
             · 空闲态全部静态、无箭头（完全安静）；
             · 退回段＝「调优运行」这一步之前的连接段（启动测试 → 调优运行），退回时反向。
           平滑消失由 CSS（.flow-seg-anim + data-on 的 opacity/scale 过渡）承担。
           ⚠️ 2026-10-10 第三轮（需求单编号 1）：段 3 传loopSeg=RUN_TUNE_LOOP_SEG
           → 当前节点为「启动测试」或「调优运行」时，该段走'loop' 相位 =
           **上下双轨同时反向流动**（上线右向 1.5s / 下线左向 0.9s，均为品牌绿），
           顶栏不再播放该段的红色退回闪烁；进「测试报告」自然落 done → 双线静止。
           ⚠️ 运行台 AutomationStageFlow 同样传 loopSeg：自动化运行时顶栏被
           z-50 全屏浮层遮住，用户实际看的是运行台那条，两处需同口径。 */
        const leftId = i > 0 ? FLOWS[i - 1].id : null
        const leftDone =
          !!leftId &&
          (autoStages.find((s) => flowOfAutomationStage(s.id) === leftId)?.status === 'success' ||
            // 非运行态：已确认流程之间同样保留浅绿静态线（空闲态安静，但仍标出「已走过」）
            (!autoRunning && flowStateOf(leftId, current.id, scene, confirmed) === 'confirmed'))
        const segPhase =
          i > 0
            ? segPhaseOf({
                segIndex: i,
                leftDone,
                curIdx,
                running: autoRunning,
                returning,
                isReturnSeg: f.id === 'tune',
                loopSeg: RUN_TUNE_LOOP_SEG,
              })
            : null
        return (
          <div key={f.id} className="flex shrink-0 items-center">
            {segPhase ? (
              <FlowSegLink
                segIndex={i}
                phase={segPhase}
                testId="flow-stepper-link"
                arrowTestId="flow-seg-arrow"
                // 闭环折线端点对齐：顶栏节点 NavLink 带 px-8 内边距（scale-1 口径）
                edgePadPx={8}
              />
            ) : null}
            <NavLink
              to={f.path}
              aria-label={uiT(f.label)}
              data-active={on ? 'true' : undefined}
              title={`${f.index} ${uiT(f.label)}${f.precondition ? ` · ${precondition}` : ''}`}
              className={cn(
                // 2026-10-09：底色改由上面的滑动高亮块承担，这里只留 hover 的轻反馈。
                // 2026-10-10：整体放大 1.5 倍（h-[52px]→78×s、px/gap 同步），尺寸全部乘 --fb-scale。
                'relative z-10 flex h-[calc(var(--fb-scale)*78px)] shrink-0 items-center gap-[calc(var(--fb-scale)*5px)] rounded-full px-[calc(var(--fb-scale)*8px)] transition-colors duration-150',
                on ? '' : 'hover:bg-p50/60',
              )}
            >
              <span
                className={cn(
                  'flex h-[calc(var(--fb-scale)*39px)] w-[calc(var(--fb-scale)*39px)] shrink-0 items-center justify-center rounded-full font-semibold transition-all duration-200 [&>svg]:block',
                  autoFailed
                    ? 'bg-alert text-white'
                    : autoIsCurrent
                      ? 'grad-ink text-white shadow-tpink automation-pulse'
                      : on
                        ? 'grad-ink text-white shadow-tpink'
                        : done || autoDone
                          ? 'bg-p100 text-p700'
                          : 'border border-line bg-white text-t3',
                  // 2026-10-10：人测测试运行中 → 当前节点改播「光圈扩散」（run-ring），
                  // 与呼吸光晕**互斥**（同一节点只留一层光圈，用户确认的替代关系）；
                  // 非运行态与其它节点仍按原口径播发光脉冲。
                  on && humanRunning
                    ? 'run-ring'
                    : !autoIsCurrent && (done || autoDone || on)
                      ? 'automation-pulse'
                      : '',
                )}
                style={{ fontSize: 'calc(var(--fb-scale) * 19px)' }}
              >
                {autoFailed ? (
                  <AlertOctagon size={21} strokeWidth={2.5} style={{ width: 'calc(var(--fb-scale) * 21px)', height: 'calc(var(--fb-scale) * 21px)' }} />
                ) : done || autoDone ? (
                  <Check size={21} strokeWidth={2.5} style={{ width: 'calc(var(--fb-scale) * 21px)', height: 'calc(var(--fb-scale) * 21px)' }} />
                ) : on ? (
                  <Icon size={21} strokeWidth={2} style={{ width: 'calc(var(--fb-scale) * 21px)', height: 'calc(var(--fb-scale) * 21px)' }} />
                ) : (
                  f.index
                )}
              </span>
              {/* 标签：紧凑模式（文字过小）下隐藏，仅保留圆标+序号，悬停 title 显示全称 */}
              {!compact && !compactSteps ? (
                <span
                  className={cn(
                    'whitespace-nowrap transition-colors',
                    autoFailed
                      ? 'text-alert'
                      : on
                        ? 'font-semibold text-p700'
                        : done || autoDone
                          ? 'text-t2'
                          : 'text-t3',
                  )}
                  style={{ fontSize: 'calc(var(--fb-scale) * 20px)' }}
                >
                  {uiT(FLOW_SHORT[f.id])}
                </span>
              ) : null}
              {state === 'alert' ? <StatusDot status="alert" /> : null}
            </NavLink>
          </div>
        )
      })}
    </nav>
    </div>
  )
}

const KnowledgeIcon = MODULE_ICON.knowledge

export function TopBar() {
  const reportConfirmed = useAppStore((state) => !!state.confirmed.report)
  const selectedSuggestions = useAppStore((state) => state.adoptedKeys.length)
  const uiT = useT()

  const { locale, setLocale } = useLocale()
  const { pathname } = useLocation()
  const onFlow = !!FLOW_BY_PATH[pathname]
  const current = FLOW_BY_PATH[pathname] ?? FLOWS[0]
  const benchBusy = useAppStore((s) => s.benchBusy)
  const benchUser = useAppStore((s) => s.benchUser)
  const pending = useAppStore((s) => s.interlockPending)
  // 取数是异步的，用 hook 订阅才会在落地后重渲；同步函数取值会永远停在 0
  const kbTotal = useKnowledgeTotal()
  const bind = useFlowActions()
  const runPhase = useAppStore((s) => s.runPhase)
  const gateTotal = useAppStore((s) => s.gateTotal)
  const gateAcked = useAppStore((s) => s.gateAcked)
  const autoRunning = useAppStore((s) => s.automationRunStatus === 'running')
  // ⚠️ 点击**不再直接开跑**（2026-10-05 用户实测「点了界面一闪而过」）：
  // 只置引导位 → 弹全屏引导屏讲清五步/预计耗时/会真下发设备启动 →
  // 人在屏上点「开始测试」才真调 startAutomation()。
  const setAutomationIntent = useAppStore((s) => s.setAutomationIntent)
  const stopAutomation = useAppStore((s) => s.stopAutomation)
  /*
   * 第三态「回到运行台」（2026-10-10 新增）。
   *
   * 场景：运行中人在浮层里点了「退出自动化测试」→ 浮层隐藏，但后台编排器
   * 仍在跑、store 也仍在同步。此时这颗按钮就是**重新进入浮层**的入口
   * （点它清掉隐藏位并置 intent；浮层一渲染就是运行时，不是引导屏）。
   *
   * ⚠️ 这里**不是**「再开一轮」：编排器的 start() 有幂等防线（running 时只提示
   * 「自动化测试正在进行中」），所以不会出现两轮并行。
   */
  const overlayHidden = useAppStore((s) => s.automationOverlayHidden)
  const backToConsole = autoRunning && overlayHidden

  // 动作条右端那行字只在流程 3 报运行态：别的流程没有「启动」这回事，
  // 报「待启动」等于给一条不存在的进度。
  const gateBlocked = current.id === 'run' && !(gateTotal > 0 && gateAcked.length >= gateTotal)
  // 这里只产出**中文原文**；渲染处统一 `uiT(statusText)` 翻译（见本文件下方动作条），
  // 带数字的「已选 N 项建议」由 {v1} 模板词条处理，不再各自判 locale。
  const statusText =
    current.id === 'report' ? (reportConfirmed ? '信息已确认' : '待确认报告信息')
      : current.id === 'tune' ? `已选 ${selectedSuggestions} 项建议`
      : current.id !== 'run' ? '就绪' : gateBlocked ? '闸门未放行' : RUN_PHASE_LABEL[runPhase]
  const statusTone: 'empty' | 'done' | 'alert' =
    current.id === 'report' ? (reportConfirmed ? 'done' : 'empty') : current.id === 'tune' ? 'empty' : current.id !== 'run'
      ? 'done'
      : gateBlocked
        ? 'empty'
        : runPhase === 'estopped'
          ? 'alert'
          : 'done'

  return (
    <header className="shrink-0">
      {/* 顶栏高度（2026-10-10）：随流程条放大到 1.5 倍（120px），窄屏回落但**保底 80px**
          （不低于上一轮已验收的高度）。用 CSS 变量 --topbar-h 由 FlowStepper 的缩放驱动。 */}
      {/* 窄屏自适应（2026-10-15）：高度与换行交给 .topbar-main（index.css）。
          原来是 h-[var(--topbar-h,80px)] **固定高**，内容一旦换行就会被裁；
          现在改为 height:auto + min-height:var(--topbar-h,80px) + flex-wrap:wrap，
          换行时容器自动增高，多出的高度由 Shell 的 flex-col 转嫁给 .shell-main。
          宽屏单行时渲染高度不变，观感与改动前一致。 */}
      <div className="topbar-main flex items-center gap-4 border-b border-line bg-surface"
        style={{ paddingInline: 'clamp(18px, 1.7vw, 32px)' }}>
        {/* 品牌区（2026-10-10）：随 1.5× 流程条同步放大，与头部菜单栏文字/图标对齐。
            宽屏（≥1536）放大到 1.25×；窄屏回落到原尺寸，避免挤占中间流程条的可用宽度。 */}
        <div className="flex shrink-0 items-center gap-2.5 min-[1536px]:gap-3">
          <span className="grad-ink flex h-[32px] w-[32px] items-center justify-center rounded-tps text-[15px] font-bold text-white shadow-tpink min-[1536px]:h-[40px] min-[1536px]:w-[40px] min-[1536px]:text-[19px]">
            O
          </span>
          <span className="text-[19px] leading-none font-bold tracking-tight text-t1 min-[1536px]:text-[24px]">
            Omni<span className="text-p700">Test</span>
          </span>
        </div>

        {/* 「智能测试」一键自动化入口：初始化左侧。三态——
              ① 非运行 → 「AI自动化测试」（2026-10-10 改名，原「自动化测试」），点击只**打开引导屏**（不直接开跑），
                 人在引导屏确认后才启动，这样才有「点了发生什么」的可感知反馈；
              ② 运行中且浮层在 → 「终止」，点一下停掉整个自动化流程；
              ③ 运行中但人已退出浮层 → 「回到运行台」，点一下重新进入看进度
                 （后台那一轮没有中断，也没有重开第二轮）。 */}
        {/* 2026-10-10（用户反馈）：顶栏紧贴视口上边缘，默认 `side="top"` 的浮层
            会被裁到屏幕外（实测「自动化测试」长文案只露出最后一行）。
            顶栏内的提示一律改为**向下弹出**。 */}
        <Tooltip
          side="bottom"
          content={
            backToConsole
              ? uiT('本轮仍在后台继续运行（你退出的是界面，不是测试），点此回到运行台看进度')
              : autoRunning
                ? uiT('自动化回归进行中，点此终止')
                : uiT('一键自动化回归：全屏接管 · 自动选定参数 → 按五步推进 → 产出报告，全程可见可终止')
          }
        >
          <Button
            size="sm"
            data-action={
              backToConsole ? 'automation-back' : autoRunning ? 'automation-stop' : 'automation-start'
            }
            variant={autoRunning && !backToConsole ? 'danger' : 'default'}
            icon={
              backToConsole ? (
                <Activity size={14} strokeWidth={1.75} />
              ) : (
                <PlayCircle size={14} strokeWidth={1.75} />
              )
            }
            onClick={
              backToConsole
                ? () => setAutomationIntent(true)
                : autoRunning
                  ? stopAutomation
                  : () => setAutomationIntent(true)
            }
          >
            <span className="stage-automation-label"><span>{backToConsole ? uiT('回到运行台') : autoRunning ? uiT('终止') : uiT('AI自动化测试')}</span><small>{uiT(autoRunning ? '五阶段自动运行中' : '自动推进 1–5 · 按需复测')}</small></span>
          </Button>
        </Tooltip>

        {/* 2026-10-10：FlowStepper 自带「居中槽」（flex-1 吸收剩余空间 + 内容宽自适应 + 缩放），
            外层不再重复包一层（避免槽宽测量被套娃容器影响）。 */}
        <FlowStepper />

        <div className="flex shrink-0 items-center gap-2.5">
          {/* 知识库是基础模块不是第六步：与 stepper 之间隔一条竖线，
              视觉上跟五步主线断开 */}
          <span className="h-[26px] w-px bg-line min-[1536px]:h-[30px]" />
          {/* 头部右侧控件（2026-10-10）：宽屏随 1.5× 流程条同步放大，窄屏回落原尺寸 */}
          <Tooltip side="bottom" content={uiT("知识库 · 五条流程共用的基础模块")}>
            <NavLink
              to="/knowledge"
              className={({ isActive }) =>
                cn(
                  'flex h-[30px] items-center gap-1.5 rounded-full border px-2.5 transition-colors min-[1536px]:h-[38px] min-[1536px]:px-3',
                  isActive
                    ? 'border-ink bg-ink-wash text-p700'
                    : 'border-line bg-white text-t2 hover:border-ink hover:text-p700',
                )
              }
            >
              <KnowledgeIcon size={14} strokeWidth={1.75} className="min-[1536px]:h-[17px] min-[1536px]:w-[17px]" />
              <span className="text-[12px] min-[1536px]:text-[15px]">{uiT(MODULE_SHORT.knowledge)}</span>
              <span className="num text-[11px] text-t3 min-[1536px]:text-[14px]">{kbTotal}</span>
            </NavLink>
          </Tooltip>
          <ProductCascader />
          <Button size="sm" data-testid="locale-toggle" lang={locale === 'zh-CN' ? 'en' : 'zh-CN'}
            onClick={() => setLocale(locale === 'zh-CN' ? 'en' : 'zh-CN')}>
            {locale === 'zh-CN' ? 'English' : uiT('中文')}
          </Button>
          {/* 2026-10-10（用户反馈）：顶栏的「演示 / 全量」分段控件**已删除**，不再作为可见入口。
              展示口径仍由 store 的 `demoMode` 决定（真源、持久化与 `?mode=demo|full`
              强制口都保留，见 state/useAppStore.ts 的 readDemoMode）：现取值与删除前
              完全一致，只少一颗可点的按钮。若要改成「恒为全量」或整条演示链路一并下线，
              需另外确认。 */}
          <Tooltip side="bottom" content={benchBusy ? uiT("台架被 {v1} 占用中", { v1: benchUser }) : uiT('台架空闲，可排队启动')}>
            <span className="flex h-[30px] items-center gap-1.5 rounded-full border border-line bg-white px-2.5 min-[1536px]:h-[38px] min-[1536px]:px-3">
              <StatusDot status={benchBusy ? 'alert' : 'done'} pulse={!benchBusy} />
              <span className="text-[12px] text-t2 min-[1536px]:text-[15px]">{benchBusy ? uiT('占用') : uiT('空闲')}</span>
            </span>
          </Tooltip>
          <Tooltip side="bottom" content={pending ? uiT("安全联锁还有 {v1} 项待确认", { v1: pending }) : uiT('安全联锁就绪')}>
            <span className="flex h-[30px] items-center gap-1.5 rounded-full border border-line bg-white px-2.5 text-t2 min-[1536px]:h-[38px] min-[1536px]:px-3">
              <ShieldCheck size={14} strokeWidth={1.75} className={cn('min-[1536px]:h-[17px] min-[1536px]:w-[17px]', pending ? 'text-warn' : 'text-p600')} />
              <span className="num text-[12px] min-[1536px]:text-[15px]">{pending ? pending : uiT('就绪')}</span>
            </span>
          </Tooltip>
          <Avatar name="张" size={30} />
        </div>
      </div>

      {/* 动作条 48 · 次表面浅绿，左动作右状态。模块页没有流程动作，整条不渲染 */}
      {/* 窄屏自适应（2026-10-15）：h-[48px] → min-height + 允许换行（见 index.css
          的 .topbar-actions）。动作按钮多时换行而不是互相挤压变形。 */}
      {onFlow ? (
      <div className="topbar-actions flex items-center gap-2 border-b border-line bg-p50"
        style={{ paddingInline: 'clamp(18px, 1.7vw, 32px)' }}>
        {current.actions.filter((a) => !(current.id === 'report' && a.id === 'gen-report' && !reportConfirmed)).slice(0, 4).map((a) => {
          const Icon = ACTION_ICON[a.id] ?? Sparkles
          const b = bind(a.id)
          // 置灰理由一律现算：闸门差几条、有没有勾采纳项，都从 store 取，
          // 不再写死在 data/flows.ts 里（08c 第零节「点不动的三处」第 2 条）
          const reason = b.disabled ? (b.reason ?? a.disabledReason) : undefined
          const btn = (
            <Button
              key={a.id}
              size="sm"
              disabled={b.disabled}
              onClick={b.onClick}
              data-action={a.id}
              variant={current.id === 'report' && a.id === 'gen-report' ? 'default' : a.primary ? 'primary' : a.danger ? 'danger' : 'default'}
              icon={<Icon size={14} strokeWidth={1.75} />}
            >
              {uiT(a.label)}
            </Button>
          )
          return reason ? (
            <Tooltip key={a.id} content={uiT(reason)} side="bottom">
              <span className="cursor-not-allowed">{btn}</span>
            </Tooltip>
          ) : (
            btn
          )
        })}
        <span className="ml-auto flex items-center gap-2 text-[12px] text-t2">
          <StatusDot status={statusTone} pulse={runPhase === 'running'} />
          {uiT(statusText)}
        </span>
      </div>
      ) : null}
    </header>
  )
}
