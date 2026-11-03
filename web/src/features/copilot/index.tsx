import { useT } from '../../i18n'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FlowId } from '../../data/types'
import { registerCopilotActions } from '../../registry'
import { useAppStore } from '../../state/useAppStore'
import { AgentChat, type AgentChatApi, type SendRequest } from '../agent-chat'
import { dshAdapter } from '../agent-chat/api'
import { getPack } from '../scene/pack'
import { makeAdapter, type Step } from './adapter'
import { ActionDock } from './ActionDock'
import { buttonsOf, loadActions, scopesOf, toCopilotActions } from './actions'
import { USE_DSH } from './backend'
import { heldEnv, takePending } from './held'
import { stepsForAction } from './actionScripts'
import { scriptFor } from './scripts'
import { rememberScriptMessages, uiMessage } from '../../i18n/messages'
import './copilot.css'

/**
 * 挂载即自动发起的那一问。按钮条给的是预置动作，这一句是进页面的开场。
 *
 * ⚠️ 措辞必须**锚定本页的对象**，不能有歧义（2026-10-05 用户实测）。
 * `report` 原为「按模板填一遍，哪些字段还没填上」——「字段」一词既可理解成
 * 「场景包字段」也可理解成「报告表头字段」，模型选了前者，于是照着流程 1 的
 * 本体属性占位口径答了一整张表（截图实测）。现在把对象写死成
 * 「报告模板的表头字段」，并显式排除本体属性，从提问端就堵住歧义。
 */
const PROMPT: Record<FlowId, string> = {
  init: '产品本体属性里哪些是占位的',
  req: '判据与工作流有没有对不上的地方',
  run: '跑一次预检，然后回放本批 CH1 波形并对判据',
  tune: '为什么不合格，给候选参数和依据',
  report: '报告模板的表头字段里，哪几项还没填上（只讲报告表头，不要提初始化配置的本体属性）',
}

/* ---------------------------------------------------------------------------
   登记与渲染分开。

   按钮定义一读进来就整份登记进注册表（五条流程加知识库模块），不等哪个页面挂载——
   /knowledge 是模块页、不挂 FlowCopilot，若把登记写在组件里，知识库那四枚就只有先
   逛过流程页才登记得上。渲染各页自理：本组件渲染五条流程那五组，/knowledge 页
   由知识库模块把 <ActionDock scope="knowledge" …/> 传给自己那块对话的 actionSlot。
   --------------------------------------------------------------------------- */

let registeredScene = ''
function registerForScene(sceneId: string) {
  if (registeredScene === sceneId) return
  registeredScene = sceneId
  void loadActions(sceneId).then((file) => {
    for (const scope of scopesOf(file)) {
      registerCopilotActions(scope, toCopilotActions(scope, buttonsOf(file, scope)))
    }
  })
}
registerForScene(useAppStore.getState().sceneId)
useAppStore.subscribe((s) => registerForScene(s.sceneId))

export function FlowCopilot({
  flow,
  onCollapse,
}: {
  flow: FlowId
  /** 由壳层传入：让助手头部多一枚「收起」按钮，点了把整块助手折成一条窄条。
   *  放在头部而不是绝对定位浮在右上角——浮层会压住这里的「沉淀为经验 / 依据」。 */
  onCollapse?: () => void
}) {
  const uiT = useT()

  const pack = getPack()
  const sceneId = useAppStore((s) => s.sceneId)
  const operator = useAppStore((s) => s.benchUser)
  // 对话的命令式接口与忙态由 AgentChat 交回来，不再从 DOM 上反推
  const [api, setApi] = useState<AgentChatApi | null>(null)
  const [busy, setBusy] = useState(false)
  const send = useCallback((text: string) => api?.send(text, uiMessage(text)), [api])
  const openingUiText = useMemo(() => uiMessage(PROMPT[flow]), [flow])
  const noteChatRound = useAppStore((s) => s.noteChatRound)

  /**
   * 上下文包是否已就绪（2026-10-05 修「助手不按真实情况回答」）。
   *
   * 本组件是 AgentChat 与 ActionDock 的共同父层，因此是**唯一能串起这条门闩**的地方：
   * ActionDock 算出 envelope 并挂上持有位后回调 onEnvReady(true) → 这里置 true →
   * AgentChat 的 autoStart 才放行。不这样串，「开场那一问」与「挂 envelope」是
   * 同一次 commit 的两个 effect，谁先谁后由渲染层级决定，第一轮请求就会漏带上下文
   * （真后端适配器取不到 context 时整段不送，模型只能凭通用知识瞎答）。
   *
   * 用 state 而非 ref：它要作为 prop 传下去并在变化时触发 AgentChat 的 effect 重跑。
   */
  const [envReady, setEnvReady] = useState(false)

  /**
   * 忙态的下降沿就是「跑完一轮」。记一笔，上下文包据此给出 session.transcript_summary，
   * 依赖它的「经验草稿」按钮才可能可用；此前那一项写死 null，按钮恒灰（07i 核验 P3）。
   */
  const wasBusy = useRef(false)
  const handleBusy = useCallback(
    (b: boolean) => {
      setBusy(b)
      if (wasBusy.current && !b) noteChatRound()
      wasBusy.current = b
    },
    [noteChatRound],
  )

  useEffect(() => {
    registerForScene(sceneId)
  }, [sceneId])

  // 会话标识：与上下文包 context.ts 的 session_id 同一口径（shell-<场景>-<流程>），
  // 后端据此维护上下文。换流程即换会话，与上下文包的行为保持一致。
  const sessionId = `shell-${sceneId}-${flow}`

  const adapter = useMemo(() => {
    if (!pack) return null
    // 联调档：直连后端适配层。确认闸门由 AgentChat 注入 requestConfirm，
    // dshAdapter 内部已有实现，宿主这一侧不用另接。
    if (USE_DSH) return dshAdapter
    rememberScriptMessages(scriptFor(flow, pack).filter((step) => step.kind === 'say').map((step) => step.text))
    /**
     * 一轮发什么，按发的是什么决定：
     * 刚点过的那枚预置动作认领得上，就放它那段脚本；否则回落到本流程的默认脚本。
     */
    const resolve = (req: SendRequest): Step[] => {
      const def = takePending()
      const snapshot = heldEnv()
      if (def && snapshot && req.text.trim() === def.prompt.trim()) {
        return stepsForAction(def, pack, snapshot)
      }
      return scriptFor(flow, pack)
    }
    return makeAdapter(`flow-${flow}`, `流程回放 · ${flow}`, resolve)
  }, [flow, pack])

  if (!adapter) {
    return (
      <div className="flex h-full items-center justify-center text-[12px] text-t3">
        {uiT("场景包加载中…")}</div>
    )
  }

  return (
    <div className="copilot-slot h-full min-h-0">
      <AgentChat
        key={flow}
        adapter={adapter}
        assistantName={uiT("助手")}
        operator={operator}
        defaultPermission="readonly"
        autoStartPrompt={PROMPT[flow]}
        autoStartUiText={openingUiText}
        // 等上下文包挂上持有位再发开场提问，保证第一轮就带真现场数据
        autoStartReady={envReady}
        onReady={setApi}
        onBusyChange={handleBusy}
        sessionId={sessionId}
        // 会话持久化键 = 会话标识：每流程一份，收起 / 切页 / 刷新后对话都还在
        persistKey={sessionId}
        onCollapse={onCollapse}
        actionSlot={
          <ActionDock scope={flow} send={send} busy={busy} onEnvReady={setEnvReady} />
        }
      />
    </div>
  )
}

export { ActionDock } from './ActionDock'
export { ActionBar } from './ActionBar'
