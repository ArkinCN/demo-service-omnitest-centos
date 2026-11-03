import { useT } from '../i18n'
import { useEffect } from 'react'
import { Outlet } from 'react-router'
import { TopBar } from './TopBar'
import { RedlineConfirm } from '../features/redline'
import { useAppStore } from '../state/useAppStore'
import { cn } from '../components/ui'
import { applySnapshot, loadLatestSnapshot } from '../features/flow-init/snapshotApi'
import { loadLatestBaseline } from '../features/flow-req/baselineApi'
import { getBaselineIds, setBaselineIds } from '../features/flow-req/baselineStore'
import { loadAdoption } from '../features/flow-tune/adoptApi'
import { heldEnv } from '../features/copilot/held'
import { AutomationRunOverlay } from '../features/automation/AutomationRunOverlay'

// dev 验收脚本要用：把 store 挂到 window，脚本才能读到**页面 React 用的同一个实例**。
// 否则脚本里 `import('/src/state/useAppStore.ts')` 会因 vite 的 ?t= 时间戳不同
// 而拿到另一个模块实例，读到空状态（「刷新后读不到」的假失败，实测栽过）。
if (typeof window !== 'undefined') {
  ;(window as unknown as { __useAppStore?: typeof useAppStore }).__useAppStore = useAppStore
  // 同理挂 heldEnv：它是**模块级变量**，验收脚本要靠它读到「点击当口的上下文包」。
  // 动态 import 会拿到另一实例（读到 null），必须走 window 上的这一份。
  ;(window as unknown as { __heldEnv?: () => unknown }).__heldEnv = heldEnv
}

/**
 * 全局读回配置快照（修 G-11 的关键一环）。
 *
 * 为什么必须放在壳层而不是流程 2 里：**流程 3 是另一个页面**，
 * `overrides` 是内存态、换页即重建；只在流程 2 挂载时读快照，
 * 进流程 3 时 `snapshotValues` 就是空的，回落链断在那里——
 * 表现是「初始化页明明确认过，流程 3 仍显示场景包原值」（实测栽过）。
 *
 * 放在壳层后，切到任一流程都已有一份「初始化页确认过的基线」。
 * 读不到是正常态（还没确认过 / 后端没起），只留一句控制台痕迹，不打扰界面。
 */
function useGlobalSnapshot() {
  const sceneId = useAppStore((s) => s.sceneId)
  useEffect(() => {
    void loadLatestSnapshot(sceneId)
      .then((hit) => {
        if (!hit) return
        // 不检查 alive：StrictMode 下会丢成功结果（见 flow-tune 同款说明）。
        // 回填幂等；且 **applySnapshot 已不再动确认态**——
        // 确认态由 useAppStore 的 localStorage 记录决定（2026-09-28 修「一打开就锁」）。
        applySnapshot(hit.snapshot)
      })
      .catch((e: unknown) => {
        console.warn('[shell] 配置快照读回失败（下游按未确认基线显示）：', e)
      })
  }, [sceneId])
}

/**
 * 全局读回需求基线镜像（修 2→3 断点的**刷新路径**）。
 *
 * 与上面的 `useGlobalSnapshot` 是**同一条教训、第二次犯**：
 * 需求基线是流程 2 的产物，但消费方是流程 3。若只在流程 2 页面挂载时灌镜像，
 * 则「刷新后直接进流程 3」这条路径上镜像恒为 null → 流程 3 退回全表判据，
 * 表现为「确认过的基线一刷新就不生效」。实测证据：`_ui_verify_chain23.mjs`
 * 的 Step 3 —— 确认 24 条后刷新进 /run，镜像读到 null。
 *
 * 放壳层后，切到任一流程都已有一份「流程 2 确认过的基线」。
 * 读不到是正常态（还没确认过 / 后端没起），只留一句控制台痕迹。
 */
function useGlobalBaseline() {
  const sceneId = useAppStore((s) => s.sceneId)
  useEffect(() => {
    let alive = true
    void loadLatestBaseline(sceneId)
      .then((hit) => {
        if (!hit) return
        // ⚠️ **不覆盖已经存在的镜像**（竞态修，实测栽过）：
        // 流程 2 点「确认基线」时会**同步**灌一份刚落的基线（更权威、更新），
        // 而本 hook 是在壳层 mount 时发的请求，返回时可能**晚于**那次灌注，
        // 且它读的是「当时服务端的最新一轮」——可能还是确认前那一轮。
        // 无脑覆盖会把刚确认的 24 条打回 null/旧值，症状是
        // 「刚点完确认进流程 3，判定又变回全表」（`_ui_verify_chain23.mjs` Step 2 抓到）。
        //
        // 判据：**只在镜像为 null（本会话还没拿到过基线）时才灌**。
        // 已有值说明有更近的写入方（本人刚确认 / 流程 2 刚读回），不该被壳层覆盖。
        // 这条不违反 StrictMode 那条纪律：`alive` 只用来**放弃过期请求**，
        // 且放弃的是「本来就不该写」的那一次，不会丢成功结果。
        if (getBaselineIds() !== null) return
        // ⚠️ 还要尊重**本浏览器的确认态**（与确认态持久化同一条纪律）：
        // `confirmed.req === false` 表示**人主动解除过**，此时不该被服务端旧产物
        // 重新点亮基线，否则「解除确认 → 进流程 3」又变回按旧基线过滤
        // （`_ui_verify_chain23.mjs` Step 4 抓到）。`undefined`（从没确认过）
        // 与 `true`（已确认）都允许灌——前者是首次进入，后者本就该生效。
        if (useAppStore.getState().confirmed.req === false) return
        setBaselineIds([...hit.baseline.included_ids])
      })
      .catch((e: unknown) => {
        if (!alive) return
        console.warn('[shell] 需求基线读回失败（流程 3 按全表口径判）：', e)
      })
    return () => {
      alive = false
    }
  }, [sceneId])
}

/**
 * 全局读回采纳记录（修 4→3 回环的**刷新路径**）。
 *
 * 采纳值写的是内存 `overrides`（见 `applyAdopt`），`nav('/run')` 同会话没问题；
 * 但**整页刷新后直接落在流程 3** 时，`useRestoreAdoption` 只在流程 4 挂载时跑，
 * 流程 3 读不到已采纳值——回环在刷新路径上断了。
 *
 * 放壳层后，切到任一流程都已有一份「采纳过哪些值」。
 * 守卫只用 `adoptedApplied.length > 0`（本会话已有更近的采纳/回滚写入就不灌，
 * 尊重规律 1：异步读回不覆盖同步写入）；**不检查 alive**——`applyAdopt` 幂等，
 * StrictMode 下检查 alive 会把成功结果丢掉。
 */
function useGlobalAdoption() {
  const sceneId = useAppStore((s) => s.sceneId)
  useEffect(() => {
    void loadAdoption(sceneId)
      .then(({ items }) => {
        if (useAppStore.getState().adoptedApplied.length > 0) return
        if (items.length) useAppStore.getState().applyAdopt(items)
      })
      .catch((e: unknown) => {
        console.warn('[shell] 采纳记录读回失败（流程 3 按未采纳显示）：', e)
      })
  }, [sceneId])
}

/**
 * 刷新后恢复自动化运行态（2026-10-05 补）。
 *
 * 编排器一直有 `restore()`，但**全仓从没人调**过 → 刷新即丢：
 * 跑了一半刷个新，浮层、顶栏阶段条、结果卡全都不见了。
 * 这里在壳层挂载时恢复一次；「刷新时正在跑」由编排器如实降级为 stopped。
 */
function useGlobalAutomation() {
  const restoreAutomation = useAppStore((s) => s.restoreAutomation)
  useEffect(() => {
    restoreAutomation()
  }, [restoreAutomation])
}

/** 一句话即时反馈。只报刚刚真发生的事，四秒后自散，不做可点的通知中心。 */
function Notice() {
  const uiT = useT()

  const notice = useAppStore((s) => s.notice)
  const setNotice = useAppStore((s) => s.setNotice)
  useEffect(() => {
    if (!notice) return
    const t = window.setTimeout(() => setNotice(null), 4000)
    return () => window.clearTimeout(t)
  }, [notice, setNotice])
  if (!notice) return null
  return (
    <div
      role="status"
      data-testid="notice"
      className="animate-rise fixed bottom-5 left-1/2 z-40 -translate-x-1/2 rounded-tps border border-line bg-surface px-3.5 py-2 text-[12.5px] text-t1 shadow-tp2"
    >
      {uiT(notice)}
    </div>
  )
}

/** 应用壳：基准画布 1920×1080（16:9）。顶栏 80 + 动作条 48 + 内容区。
 *  内容区外边距横 32 纵 24；1440 / 1600 宽度下栅格按比例收缩，不裁切。 */
export function Shell() {
  useGlobalSnapshot()
  useGlobalBaseline()
  useGlobalAdoption()
  useGlobalAutomation()
  const autoRunning = useAppStore((s) => s.automationRunStatus === 'running')
  return (
    <div className={cn('flex h-full min-h-0 w-full flex-col bg-page', autoRunning && 'automation-running')}>
      <TopBar />
      <main
        className="flex min-h-0 flex-1"
        style={{ padding: 'clamp(16px, 1.7vw, 32px) clamp(18px, 1.7vw, 32px)' }}
      >
        <Outlet />
      </main>
      {/* 六条红线共用这一张确认卡，全局挂一处 */}
      <RedlineConfirm />
      {/*
        一键自动化全屏浮层：**全局挂一处**（与确认卡/Notice 同层）。
        ⚠️ 挂在壳层而不是流程页里，是因为自动化会跨五个流程跑；
        挂在任一流程页里，换页就会把它卸载掉（老实现挂在右上卡片区，
            且挂载条件就是 running，跑完立刻消失——「看不到结果」的根源）。

            2026-10-08：内部已改为**整屏接管**（fixed inset-0），因此挂载在 Shell
            根部最外层、与 TopBar/Notice 同级即可；接管期间由 overlay 自己锁 body
            滚动，底层人测页不再可交互。
          */}
              <AutomationRunOverlay />
      <Notice />
    </div>
  )
}
