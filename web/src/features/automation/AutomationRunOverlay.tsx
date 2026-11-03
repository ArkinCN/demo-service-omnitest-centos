import { useT } from '../../i18n'
import { useEffect, useRef, useState } from 'react'
import { LogOut } from 'lucide-react'
import { cn, Modal } from '../../components/ui'
import { FLOWS } from '../../data/flows'
import { FullReport } from '../flow-report/panel'
import { useAppStore } from '../../state/useAppStore'
import { buildStageViews, buildVerdictViews } from './automationViewModel'
import { AutomationConsole } from './AutomationConsole'
import { AutomationIntro } from './AutomationIntro'
import { AutomationResult } from './AutomationResult'
import { AutomationStageFlow } from './AutomationStageFlow'
import { AutoExitConfirm } from './AutoExitConfirm'

/* ===========================================================================
   自动化回归 · 全屏接管容器（三屏路由）

   2026-10-08：由「居中模态卡」改为**整屏接管**。
   为什么改：自动化会横跨五个流程跑。弹窗遮住底层页面时，人既看不到参数被
   改成什么、也看不到台架采到的曲线，「一键」就变成了盲跑。

   2026-10-09：**结果由「整屏结果页」改为「运行台之上的完成弹窗」**。
   为什么改：跑完之后人最想做的两件事是「看这轮采到的曲线/日志/判定」和
   「看结论」。老实现把结果做成整屏页，一关就整层卸载 → 回到人测页，本轮
   数据（趋势/日志/进度/判定）当场消失，想复查只能重跑。现在：

    · 终态不再让整层卸载，`AutomationConsole` 常驻（三栏、分隔条、图表、
      滚动位置全部保住 —— running→result 不重挂载是刻意的）；
    · `AutomationResult` 变成浮在上面的模态弹窗，`dismissed` 只控制弹窗显隐；
    · 弹窗「关闭」= 收起弹窗（停留运行台，可随时从底部「查看执行结果」再开）。

   2026-10-10（本轮）：**新增唯一的退出口**——顶栏那颗「退出自动化测试」
   （原先的「轮次 xxxx」显示与右上角 ✕ 均已删除）。口径：

    · 运行中点它 → **先二次确认**（`AutoExitConfirm`）：
      「测试正在运行，确定退出吗？／退出仅关闭当前界面，后台测试将继续跑完。」；
    · 确认后走**软退出**：只隐藏浮层，不清数据、不发任何设备停止指令，
      后台编排器继续跑到自然完成，操作者稍后可经顶栏「回到运行台」回来；
    · 非运行态（引导态 / 终态）点它 → 没有「后台还在跑」这件事，直接退。

   ⚠️ 为什么软退出不能复用 `exitOverlay()`：后者里的 `clearAutomation()` 会把
   `automationRunStatus` 复位成 idle，而编排器还在跑 —— 下一条事件立刻把它
   回写成 running，浮层当场自己弹回来（同类坑历史上已踩过两次）。

   三态与优先级（沿用既有判定，避免「点了闪一下又变结果」的老毛病）：
     终态 > 运行态 > 引导态。终态一旦成立就常驻运行台 + 弹窗（弹窗可收起）。

   纪律：
     一、退出口**唯一**：顶栏那颗按钮。运行中退出必须过二次确认，且只是
        「界面退出」——**不打断真机流程**，台架继续跑完（不调 stopFanTest、
        不碰 cancel 适配器、不加取消令牌）；
     二、数据全部来自 store 切片（编排器事件驱动），本文件不自己算耗时；
     三、保留既有 data-testid / data-phase 契约；`automation-close`（✕）已按
        用户要求删除，退出断言改用 `auto-exit-button`。
   =========================================================================== */

type Phase = 'intro' | 'running' | 'result'

export function AutomationRunOverlay() {
  const uiT = useT()

  const intent = useAppStore((s) => s.automationIntent)
  const runStatus = useAppStore((s) => s.automationRunStatus)
  const stages = useAppStore((s) => s.automationStages)
  const currentId = useAppStore((s) => s.automationCurrentStageId)
  const summary = useAppStore((s) => s.automationSummary)
  const tools = useAppStore((s) => s.automationTools)
  const logs = useAppStore((s) => s.automationLogs)
  const live = useAppStore((s) => s.automationLive)
  const verdicts = useAppStore((s) => s.automationVerdicts)
  const gateAcked = useAppStore((s) => s.gateAcked)
  const startAutomation = useAppStore((s) => s.startAutomation)
  const stopAutomation = useAppStore((s) => s.stopAutomation)
  const clearAutomation = useAppStore((s) => s.clearAutomation)
  const setAutomationIntent = useAppStore((s) => s.setAutomationIntent)
  /** 「本轮浮层已被用户退出」（软退出位），见下方渲染闸门 */
  const overlayHidden = useAppStore((s) => s.automationOverlayHidden)
  const hideAutomationOverlay = useAppStore((s) => s.hideAutomationOverlay)

  /**
   * 本地「弹窗已收起」位。
   *
   * ⚠️ 它**只控制完成弹窗的显隐**，不再让整层 overlay 卸载（2026-10-09 改）。
   * 老实现是 `dismissed → phase=null`，关掉结果卡等于退出全屏，运行台数据全丢。
   * 新轮次启动时复位（intent false→true 边沿），保证新一轮跑完弹窗照常弹出。
   */
  const [dismissed, setDismissed] = useState(false)
  const wasIntent = useRef(false)
  if (intent && !wasIntent.current) {
    wasIntent.current = true
    if (dismissed) setDismissed(false)
  }
  if (!intent && wasIntent.current) wasIntent.current = false

  /**
   * 「退出二次确认」是否开着（本地态）。
   *
   * 只有**运行中**才需要它：那时离开界面会让人看不到本轮进度，而真机仍在跑，
   * 必须先问一句。非运行态退出没有后果，直接走（见 requestExit）。
   */
  const [confirmExit, setConfirmExit] = useState(false)

  /** 「查看报告」报告预览弹窗是否开着（本地态）。
   *  只控制弹窗显隐，不退出回归、不清运行台数据（2026-10-10 改）。 */
  const [reportOpen, setReportOpen] = useState(false)

  const isFinal = runStatus === 'completed' || runStatus === 'failed' || runStatus === 'stopped'
  const phase: Phase | null = isFinal
    ? 'result'
    : runStatus === 'running'
      ? 'running'
      : intent
        ? 'intro'
        : null
  /** 终态类型（非终态为 undefined）；运行台据此把「终止」换掉、状态条改文案 */
  const terminalStatus: 'completed' | 'failed' | 'stopped' | undefined = isFinal
    ? (runStatus as 'completed' | 'failed' | 'stopped')
    : undefined
  /** 完成弹窗是否打开：只有终态且人没收起它时才盖在运行台上 */
  const resultDialogOpen = isFinal && !dismissed

  const { views, stats: stageStats } = buildStageViews(
    stages,
    FLOWS.map((f) => ({ id: f.id, index: f.index, name: f.label })),
    currentId,
  )
  const { stats: liveVerdictStats } = buildVerdictViews(verdicts)

  /**
   * 完成弹窗用的判定统计（2026-10-09 修）。
   *
   * ⚠️ **不能只用 `buildVerdictViews(verdicts)`**：`verdicts` 是右栏的**实时**判定表，
   * 它不持久化（见 AutomationLiveState），刷新恢复或快照恢复后就是空数组 →
   * `total=null` → 弹窗徽章与「判定通过比」双双显示「—」，明明本轮判了 20 条却像没测。
   * （实测：`_syncAutomation` 落终态后徽章渲染成「—」，而 `summary.metrics.total=20`。）
   *
   * 口径（诚实优先，不编数字）：
   *   · `summary.metrics.total > 0` → **以后端/编排器落库的 metrics 为准**（权威且跨刷新有效）；
   *   · metrics 全 0（判定表还没来）→ 退回实时判定表统计，取不到仍是 `total=null`（显示「—」）；
   *   · 两处都取不到 → 保持「—」，**绝不用 0 冒充**。
   */
  const verdictStats =
    summary.metrics.total > 0
      ? {
          pass: summary.metrics.pass,
          fail: summary.metrics.fail,
          missing: summary.metrics.missing,
          notApplicable: summary.metrics.notApplicable,
          total: summary.metrics.total,
        }
      : liveVerdictStats

  /* 整屏接管期间锁掉底层滚动：不应还能滚到背后的人测页 */
  useEffect(() => {
    if (!phase) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [phase])

  /**
   * 收起完成弹窗（停留运行台）。
   *
   * ⚠️⚠️ 这里**绝不能调 `clearAutomation()`**（2026-10-09 实测栽过）：
   * `clearAutomation()` 会把 `automationRunStatus` 复位成 `idle`，于是
   * `phase` 立刻变 null → 整层 overlay 卸载。表现是「点关闭不但没停留，
   * 反而直接退出了全屏回归」，且运行台数据全丢——正是本次要修的那个问题
   * 换了个触发点复现。收起弹窗只动 `dismissed` 这一个本地位。
   */
  const dismissResult = () => setDismissed(true)
  /**
   * 整层退出（**非运行态专用**）：清掉本轮显示态，回人测流程页。
   *
   * ⚠️ 只在 `runStatus !== 'running'` 时可用：它调的 `clearAutomation()` 会把
   * runStatus 复位成 idle，运行中用它会被下一条编排器事件当场拉回来。
   * 运行中退出请走 `confirmAndExit()`（软退出）。
   */
  const exitOverlay = () => {
    setDismissed(true)
    setAutomationIntent(false)
    clearAutomation()
  }

  /**
   * 退出入口 —— 全浮层**唯一**的那一个（顶栏「退出自动化测试」按钮）。
   *
   * 分岔口径（需求单编号 2 / 6）：
   *   · 运行中 → 先弹二次确认（离开界面就看不到本轮进度了，而真机仍在跑）；
   *   · 非运行态（引导态 / 终态）→ 没有「后台还在跑」这件事，直接退，不问。
   */
  const requestExit = () => {
    if (runStatus === 'running') setConfirmExit(true)
    else exitOverlay()
  }

  /**
   * 确认退出 = **软退出**：只隐藏浮层，不清数据、不停后台、不发任何设备指令。
   *
   * ⚠️ 刻意**不调** `exitOverlay()` / `clearAutomation()`：那会把 runStatus 复位
   * 成 idle 并清空运行台数据，而后台编排器还在跑 —— 下一条事件就把它回写成
   * running，浮层当场弹回来（历史踩过）。真正的清理留给下一轮启动或整层退出。
   * ⚠️ 也**不调** `stopAutomation()`：本需求要的就是「台架继续跑」。
   */
  const confirmAndExit = () => {
    setConfirmExit(false)
    hideAutomationOverlay()
  }

  /* 确认弹窗开着时本轮若已走到终态（自然跑完/失败/被终止），自动收掉它：
     「已经跑完了还问你在不在跑」是错的。 */
  useEffect(() => {
    if (confirmExit && runStatus !== 'running') setConfirmExit(false)
  }, [confirmExit, runStatus])
  /** 重新运行＝回到引导屏（仍让人确认一次现场安全，不直接开跑） */
  const retry = () => {
    setDismissed(true)
    clearAutomation()
    setAutomationIntent(true)
  }
  /**
   * 「查看报告」= **原地**打开报告预览弹窗（不退出回归、不跳 /report）。
   *
   * 2026-10-10 改：老实现是 `exitOverlay() + navigate('/report')`，会把整层回归
   * 退出并跳到第 5 节点页面，人想复查运行台数据还得重新进一轮。现改为弹窗预览：
   * 关闭弹窗只复位 `reportOpen`，回归层与本轮数据（趋势/日志/判定）全程保留。
   */
  const viewReport = () => setReportOpen(true)
  const redownload = () => {
    void import('../flow-report/reportApi').then(async ({ downloadUrl, resolveReportRunId }) => {
      const st = useAppStore.getState()
      try {
        const rid = await resolveReportRunId(st.sceneId, st.runId)
        const a = document.createElement('a')
        a.href = downloadUrl(rid)
        a.download = ''
        document.body.appendChild(a)
        a.click()
        a.remove()
      } catch (e) {
        // 失败如实抛出到控制台；不给用户「已下载」的假反馈
        console.error('[automation] 重新下载报告失败：', e)
        st.setNotice(`重新下载失败：${e instanceof Error ? e.message : String(e)}`)
      }
    })
  }

  /*
   * ⚠️ 无运行态时**必须整层不渲染**（2026-10-09 修「打开项目一片空白」）。
   *
   * 真因：本组件挂在 Shell 根部、常驻挂载。老实现漏了这层守卫 → `phase === null`
   * （intent=false 且 runStatus=idle，即平时打开页面）时，外层
   * `<div class="automation-takeover fixed inset-0 z-50 flex flex-col bg-page">`
   * 照样渲染：一个 **z-50 的全屏 div，内部三个分支全不渲染 → 空壳**。
   * 且 `bg-page` 并非有效工具类（样式表里没有），该层是**透明**的 →
   * 底层人测页被完全盖住却一个像素都不画，DOM 里什么都在（rootLen 9 万+），
   * 视觉上就是「一片空白」。Playwright 实测：`elementFromPoint(10,10)` 命中
   * 的正是这个 `.automation-takeover`。
   *
   * 修法：保持「挂载常驻」不变（卸载会丢 running→result 的常驻运行台），
   * 只在**渲染层**加守卫——三态都不成立时返回 null。
   *
   * ⚠️ 2026-10-10 追加第二个条件：`automationOverlayHidden`（人点了退出）。
   * 它是**渲染级**闸门，只挡浮层、不挡 store 同步 —— `_syncAutomation` 与事件
   * 订阅照旧，顶栏因此仍能读到真实运行信号（按钮显示「回到运行台」）。
   * 清掉该位的唯一入口是 `setAutomationIntent(true)`（「回到运行台」走它）。
   *
   * ⚠️ 这里**只判 overlayHidden，不能再叠 `&& !intent`**（2026-10-10 实测栽过）：
   * 从「回到运行台」重进时 intent 被置 true 且此后没人清它，叠上 `!intent`
   * 会让隐藏位当场失效 —— 表现是「重进之后**再点退出就退不掉了**」。
   * 引导态不需要这个条件兜底：`setAutomationIntent(true)` 本身已清隐藏位。
   */
  if (!phase || overlayHidden) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={uiT("一键自动化回归")}
      data-testid="automation-overlay"
      data-phase={phase}
      className="automation-takeover fixed inset-0 z-50 flex flex-col bg-page"
    >
      {/* 引导屏：同样给顶栏，保持「这是全屏模式」的认知一致 */}
      {phase === 'intro' ? (
        <>
          <HeaderBar onExit={requestExit} />
          <AutomationIntro
                gateAcked={gateAcked.length}
                onStart={startAutomation}
             onCancel={exitOverlay}
              />
        </>
      ) : null}

      {/*
        运行台（运行态与终态共用同一分支）：
        ⚠️ 刻意**不拆成两个分支**——running→result 若换分支，Console 会被卸载重建，
        图表、日志滚动位置、分隔条比例全部重置。终态只是「多盖一层弹窗」，
        底座必须原样留着，人收起弹窗才能接着看本轮数据。
      */}
      {phase === 'running' || phase === 'result' ? (
        <>
          <HeaderBar views={views} onExit={requestExit} />
          <main className="relative flex min-h-0 flex-1 flex-col p-3">
            <AutomationConsole
                stages={views}
                stageStats={stageStats}
                live={live}
              tools={tools}
              logs={logs}
              verdicts={verdicts}
              onStop={stopAutomation}
              terminalStatus={terminalStatus}
              onShowResult={isFinal && dismissed ? () => setDismissed(false) : undefined}
            />

            {/* 完成弹窗：浮在运行台之上，收起后运行台全貌可见 */}
            {resultDialogOpen ? (
              <AutomationResult
                status={runStatus as 'completed' | 'failed' | 'stopped'}
                stages={views}
                stats={verdictStats}
                summary={summary}
                onDismiss={dismissResult}
                onRetry={retry}
                onViewReport={viewReport}
                onRedownload={redownload}
              />
            ) : null}
          </main>
        </>
      ) : null}

      {/* 退出二次确认：只在运行中弹；走到终态由上面的 effect 自动收掉。
          ⚠️ 它调的是 confirmAndExit（软退出），不是 exitOverlay。 */}
      {confirmExit && phase === 'running' ? (
        <AutoExitConfirm onCancel={() => setConfirmExit(false)} onConfirm={confirmAndExit} />
      ) : null}

      {/* 「查看报告」报告预览弹窗：复用报告页 FullReport，portal 到 body 覆盖回归层。
          右上角 X / Esc / 点遮罩关闭；关闭只复位 reportOpen，回归层不动。
          ⚠️ zIndex=70：结果弹窗遮罩是 z-60，默认 z-50 会被它盖住、点不到右上角 X。 */}
      <Modal
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        title={uiT("报告预览")}
        meta={uiT("按模板节结构渲染 · 非最终成稿")}
        width={880}
        zIndex={70}
      >
        <div className="max-h-[70vh] overflow-y-auto bg-p50 p-3">
          <FullReport />
        </div>
      </Modal>
    </div>
  )
}

/** 全屏顶栏：品牌 + 模式标 + 五步骤流光条 + 退出按钮（唯一的退出口） */
function HeaderBar({
  views,
  onExit,
}: {
  views?: ReturnType<typeof buildStageViews>['views']
  onExit: () => void
}) {
  const uiT = useT()

  return (
    <header
      className="flex h-[max(56px,var(--auto-header-h,56px))] shrink-0 items-center gap-3 border-b border-line bg-surface px-4"
    >
      {/* 2026-10-10（用户反馈）：品牌区原为写死像素（logo 28 / 字号 16 / 徽标 10.5），
          流程条放大到 1.5× 后显得过小。现全部乘 --fb-scale，与流程条节点同档
          （圆标 39×s、节点字号 19×s、标签 20×s，见 AutomationStageFlow）；
          引导屏没有流程条、--fb-scale 缺失，回落 1（与原尺寸相当）。 */}
      <div className="flex shrink-0 items-center" style={{ gap: 'calc(var(--fb-scale, 1) * 8px)' }}>
        <span
          className="grad-ink flex items-center justify-center rounded-tps font-bold text-white shadow-tpink"
          style={{
            width: 'calc(var(--fb-scale, 1) * 39px)',
            height: 'calc(var(--fb-scale, 1) * 39px)',
            fontSize: 'calc(var(--fb-scale, 1) * 19px)',
          }}
        >
          O
        </span>
        <span
          className="leading-none font-bold tracking-tight text-t1"
          style={{ fontSize: 'calc(var(--fb-scale, 1) * 20px)' }}
        >
          Omni<span className="text-p700">Test</span>
        </span>
        <span
          className="rounded-full bg-p100 font-medium text-p700"
          style={{
            fontSize: 'calc(var(--fb-scale, 1) * 13px)',
            paddingInline: 'calc(var(--fb-scale, 1) * 9px)',
            paddingBlock: 'calc(var(--fb-scale, 1) * 4px)',
          }}
        >
          {uiT("全屏自动回归")}</span>
      </div>

      {views && views.length ? (
        <div className="flex min-w-0 flex-1 items-center px-2">
          <AutomationStageFlow views={views} />
        </div>
      ) : (
        <div className="min-w-0 flex-1" />
      )}

      {/*
        退出口唯一：原「轮次 xxxx」显示（runId.slice(0,8)）与右上角 ✕（automation-close）
        均按用户要求删除，这里只留这一颗按钮。运行中点击会先过二次确认，
        非运行态直接退（分岔在 requestExit）。
      */}
      <ExitButton onExit={onExit} />
    </header>
  )
}

/**
 * 退出按钮（全浮层唯一退出口）。
 *
 * 样式口径：与流程条节点**同族** —— 白底 + 细描边 + 全圆角，取「未到达节点」
 * 那套 token（`border-line` / `bg-white` / `text-t3`），hover 走浅绿反馈。
 *
 * ⚠️ 尺寸与字号一律乘 `--fb-scale`（由 `AutomationStageFlow` 写到本 header 上），
 * **不写死像素**：流程条会随视口放大到 1.5×，写死像素会让两者比例失衡。
 * 变量缺失时回落到 1（此时与流程条未缩放态一致）。
 *
 * 图标取 LogOut：一眼能认出是「退出」，不必靠文字猜。
 */
function ExitButton({ onExit }: { onExit: () => void }) {
  const uiT = useT()

  return (
    <button
      type="button"
      data-testid="auto-exit-button"
      onClick={onExit}
      title={uiT("退出AI自动化测试：只关闭当前界面，后台测试继续跑完")}
      className={cn(
        'inline-flex shrink-0 cursor-pointer items-center rounded-full border border-line bg-white text-t3 transition-colors duration-150',
        'hover:border-p300 hover:bg-p50 hover:text-p700',
        'focus-visible:border-p300 focus-visible:bg-p50 focus-visible:text-p700 focus-visible:outline-none',
      )}
      style={{
        height: 'calc(var(--fb-scale, 1) * 32px)',
        gap: 'calc(var(--fb-scale, 1) * 6px)',
        paddingInline: 'calc(var(--fb-scale, 1) * 12px)',
        fontSize: 'calc(var(--fb-scale, 1) * 13px)',
      }}
    >
      {/* 2026-10-10（用户反馈）：文案改「退出AI自动化测试」；图标 14→16×s，
          与放大后的品牌区/流程条比例协调 */}
      <LogOut
        strokeWidth={1.9}
        className="shrink-0"
        style={{
          width: 'calc(var(--fb-scale, 1) * 16px)',
          height: 'calc(var(--fb-scale, 1) * 16px)',
        }}
      />
      {uiT("退出AI自动化测试")}</button>
  )
}
