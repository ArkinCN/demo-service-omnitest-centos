import { useEffect, useMemo, useState } from 'react'
import { FLOW_BY_ID } from '../../data/flows'
import type { FlowId } from '../../data/types'
import { useAppStore } from '../../state/useAppStore'
import { defaultViewOf } from '../canvas/defaultView'
import { loadLatestRun, type LastRunData } from '../flow-run/api'
import { getPack } from '../scene/pack'
import { ActionBar } from './ActionBar'
import { buttonsOf, loadActions, type ActionDef, type ActionScope } from './actions'
import { buildEnvelope } from './context'
import { setHeldEnv, setPending } from './held'

/* ===========================================================================
   预置动作按钮条的装配件：读按钮定义、算上下文包、把点击接到对话上。

   收尾轮（W6）起走 AgentChat 的正经接口，并行期那套「宿主侧 DOM 接管三件套」
   已整体下架：
     · 挂位  原先往 .ac-root 里 portal 一个节点 → 现在传 AgentChat 的 actionSlot
     · 发送  原先往 .ac-textarea 写值再点 .ac-send → 现在用 AgentChatApi.send()
     · 忙态  原先 MutationObserver 盯 .ac-header__state[data-busy] → 现在收
             onBusyChange 回调
   本组件因此不再碰 agent-chat 的任何 class 名，也不再需要 composer.ts。

   任何一块 agent-chat 对话都能用：把 send 与 busy 传进来即可，
   /knowledge 页的助手也照此挂（scope 传 'knowledge'）。
   =========================================================================== */

export function ActionDock({
  scope,
  send,
  busy,
  onEnvReady,
}: {
  scope: ActionScope
  /** 代发一条消息，取自 AgentChat 的 onReady 句柄 */
  send: (text: string) => void
  /** 对话是否在跑一轮，取自 AgentChat 的 onBusyChange */
  busy: boolean
  /**
   * 上下文包「首次就绪」回调（2026-10-05 修「助手不按真实情况回答」）。
   *
   * ⚠️ 为什么需要它：`AgentChat` 的自动开场提问（autoStartPrompt）与这里的
   * `setHeldEnv` 是**同一次 commit 的两个 effect**。本组件是 AgentChat 通过
   * `actionSlot` 渲染的**子元素**，其 effect 先于父组件执行——所以开场那一问
   * 发出的瞬间 `held.ts` 里挂的还是**首次 render 算出的那份 envelope**；
   * 而真后端适配器（dshAdapter）在 `heldEnv()` 取不到内容时**整段不送 context**，
   * 模型于是没有任何现场数据、只能凭通用知识作答（用户实测：助手列「额定转速/
   * 额定电压/风扇尺寸/风扇厚度」等 5 项占位，与左栏已填值冲突）。
   *
   * 由本组件（envelope 的唯一生产者）在**首次算出可用 envelope** 后宣告就绪，
   * 父层据此放行 autoStart，保证第一轮请求就带真现场数据。
   *
   * 纪律：**幂等、单调**（只报 true，不回退）；不传则行为与以前完全一致。
   */
  onEnvReady?: (ready: boolean) => void
}) {
  const pack = getPack()
  const sceneId = useAppStore((s) => s.sceneId)
  const scene = useAppStore((s) => s.scene)
  const path = useAppStore((s) => s.path)
  const overrides = useAppStore((s) => s.overrides)
  const touched = useAppStore((s) => s.touched)
  const confirmed = useAppStore((s) => s.confirmed)
  const benchBusy = useAppStore((s) => s.benchBusy)
  const benchUser = useAppStore((s) => s.benchUser)
  const interlockPending = useAppStore((s) => s.interlockPending)
  const picked = useAppStore((s) => s.canvasView[scope as FlowId])
  const canvasSelected = useAppStore((s) => s.canvasSelected)
  const model = useAppStore((s) => s.model)
  // 第四轮上提到 store 的三处选中态/进度，接进上下文包，
  // 对应的红线准备按钮才有可能从恒灰转可用（07i 核验 P3）
  const adoptedKeys = useAppStore((s) => s.adoptedKeys)
  const adoptMeta = useAppStore((s) => s.adoptMeta)
  const runRound = useAppStore((s) => s.runRound)
  const chatRounds = useAppStore((s) => s.chatRounds)
  // 上下文包里的两个 selected_* 原先恒为 null（选中态在各面板局部 useState 里）。
  // 现在从 store 取真值：知识库选中条目、流程 4 选中的未达标判据。
  const kbSelectedId = useAppStore((s) => s.kbSelectedId)
  const focusReq = useAppStore((s) => s.focusReq)
  // 已落盘的配置快照值：missing/placeholders 判「缺不缺」要按当前实际值算
  // （overrides → snapshotValues → 场景包原值），只看静态场景包会「人填了还说缺」。
  const snapshotValues = useAppStore((s) => s.snapshotValues)
  // 流程 5 的本页表头填写状态：reportHeader 里已有值的键 → true（只当集合用）。
  // 摘要据此给「报告表头未填项」——跨页隔离后流程 5 助手对表头问题仍有据可答。
  const reportHeader = useAppStore((s) => s.reportHeader)
  // AI 助手权限档位（2026-10-10）：上下文包 policy.permission 要动态反映当前档位，
  // 否则模型永远以为自己是只读。订阅 store 后切档即让 envelope 重建、下轮请求生效。
  const permission = useAppStore((s) => s.permission)
  const reportHeaderFilled = useMemo(() => {
    const out: Record<string, true> = {}
    for (const [k, v] of Object.entries(reportHeader)) {
      if (v && v.trim()) out[k] = true
    }
    return out
  }, [reportHeader])

  // canvasView 第三轮改成按流程存，这里取本 scope 那一份；
  // 人没点过就是场景包给的默认值（知识库模块没有 C 区，落兜底值不参与判断）
  const canvasView = picked ?? defaultViewOf(scope as FlowId, scene)

  const [defs, setDefs] = useState<ActionDef[]>([])

  /**
   * 真实最近一轮（助手上下文 lastRun 的真数据源）。
   *
   * ⚠️ 2026-09-29：此前上下文里的 lastRun 是 `context.ts` 里**写死的假数据**
   * （一律"所有判据未采集 + 42 项实测量未采集"），模型据此编出不存在的问题。
   * 现在在这里异步读回真轮次产物，作为入参喂给 buildEnvelope。
   *
   * 纪律：
   *   · **不检查 alive**——StrictMode 下检查会把成功结果丢掉（幂等回填，拿到就写）；
   *   · 换场景（sceneId 变）先清回 null，旧场景的轮次不适用于新场景；
   *   · 读不到（确实没跑过一轮）就保持 null，**如实**让下游据此置灰，不编。
   */
  const [lastRun, setLastRun] = useState<LastRunData | null>(null)

  const env = useMemo(
    () =>
      buildEnvelope({
        flow: scope,
        flowLabel: FLOW_BY_ID[scope as keyof typeof FLOW_BY_ID]?.label ?? scope,
        pack,
        sceneId,
        path,
        operator: benchUser,
        overrides,
        touched,
        confirmed,
        benchBusy,
        benchUser,
        interlockPending,
        canvasView,
        canvasSelected,
        model,
        // 对话摘要按已跑完的轮数如实给；一轮都没跑过时为 null，不编一句摘要顶上
        transcriptSummary:
          chatRounds > 0
            ? `本会话已与助手完成 ${chatRounds} 轮对话（流程 ${scope}）`
            : null,
        adopted: adoptedKeys.map((k) => ({
          key: k,
          name: adoptMeta[k]?.name ?? k,
          from: adoptMeta[k]?.from ?? '—',
          to: adoptMeta[k]?.to ?? '—',
        })),
        runRound,
        lastRun,
        kbSelectedId,
        selectedFailItem: focusReq,
        reportHeaderFilled,
        snapshotValues,
        permission,
      }),
    [
      scope,
      pack,
      sceneId,
      path,
      overrides,
      touched,
      confirmed,
      benchBusy,
      benchUser,
      interlockPending,
      canvasView,
      canvasSelected,
      model,
      adoptedKeys,
      adoptMeta,
      runRound,
      lastRun,
      chatRounds,
      kbSelectedId,
      focusReq,
      reportHeaderFilled,
      snapshotValues,
      permission,
    ],
  )

  // 适配器在 send 里要按这份上下文包展开脚本，而 send 发生在渲染之外
  useEffect(() => {
    setHeldEnv(env)
    // 宣告「上下文包已挂上持有位」：父层据此放行自动开场提问，
    // 保证第一轮请求就带真现场数据（见 props 的 onEnvReady 说明）。
    // 幂等且单调（重复调用只是再置一次 true，无副作用）。
    onEnvReady?.(true)
  }, [env, onEnvReady])

  /**
   * 读回真实最近一轮（lastRun）。依赖 sceneId：换场景必须重读。
   *
   * 判据声明的 `runtime.measure` 变量全集在此现算，供 loadLatestRun 算「真缺的量」
   * （所需 − 该轮真采到）。pack 变化时理论上也该重算，但 pack 与 sceneId 同源
   * （换场景才换包），用 sceneId 作依赖足够；pack 为空时给空数组，仍能读回轮次。
   */
  useEffect(() => {
    const pack = getPack()
    const required = [
      ...new Set(
        (pack?.requirements.requirements ?? []).flatMap((r) =>
          Object.entries(r.variables ?? {})
            .filter(([, v]) => v.source === 'runtime.measure')
            .map(([name]) => name),
        ),
      ),
    ]
    // 变量名 → 中文名（场景包 runtime_measures 的 name）：missing_measures 输出
    // 「中文名(英文键)」，助手回答里才不会出现英文键名（用户实测反馈过）。
    const legend: Record<string, string> = {}
    const rm = pack?.requirements.runtime_measures as
      | Record<string, { name?: string } | undefined>
      | undefined
    if (rm) {
      for (const [k, v] of Object.entries(rm)) {
        if (v?.name) legend[k] = v.name
      }
    }
    // 换场景先清空：旧场景的轮次不适用于新场景，避免短暂显示上一库的判定
    setLastRun(null)
    // 不检查 alive：幂等回填，StrictMode 下检查会把成功结果丢掉
    void loadLatestRun(sceneId, required, legend)
      .then((hit) => setLastRun(hit))
      .catch((e: unknown) => {
        // 读不到 = 正常态（还没跑过一轮 / 后端不可用）：保持 null，如实置灰
        console.warn('[copilot] lastRun 读回失败（助手按「没跑过一轮」处理）：', e)
      })
  }, [sceneId])

  useEffect(() => {
    let alive = true
    void loadActions(sceneId).then((file) => {
      if (alive) setDefs(buttonsOf(file, scope))
    })
    return () => {
      alive = false
    }
  }, [sceneId, scope])

  return (
    <ActionBar
      defs={defs}
      env={env}
      busy={busy}
      onPick={(d) => {
        setPending(d)
        send(d.prompt)
      }}
    />
  )
}
