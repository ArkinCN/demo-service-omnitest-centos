import { useT } from '../../i18n'
import { uiMessage, rememberScriptMessages } from '../../i18n/messages'
import { useMemo } from 'react'
import type { AgentAdapter, ChatItem, SendRequest } from '../agent-chat'
import { AgentChat, dshAdapter } from '../agent-chat'
import { makeAdapter } from '../copilot/adapter'
import { USE_DSH } from '../copilot/backend'
import { useAppStore } from '../../state/useAppStore'
import './console-chat.css'

/* ===========================================================================
   运行台 · AI 助手卡（2026-10-10）

   需求：运行台底部日志卡右上角的圆形 AI 按钮切过来，展示**与人测页完全一致**的
   助手卡（"助手 / 电机调试 / dsh"标题、对话区、输入框、停止按钮、模型行、收起）。

   复用口径（对齐知识库页 `knowledgeAdapter.ts` 先例，**直接挂 AgentChat**）：
     · 不走 `FlowCopilot` —— 那个包装固定渲染 `ActionDock`（会注册/暴露预置动作
       与上下文包 envelope），而本需求已确认「纯前端隔离」：不注册任何动作类与
       硬件类能力，故这里**不挂 ActionDock、不传 actionSlot**。
     · 只读档：`defaultPermission="readonly"` + 适配器仅知识检索类工具，不触碰
       设备桥与单设备锁（"对话不影响测试运行"的界面/后端隔离就落在这里）。

   会话独立（用户已确认）：键固定为 `shell-<场景>-auto`，不与人测页助手共享历史，
   两个实例互不覆盖。收起 / 切回 / 刷新后对话都在（靠 AgentChat 的 persistKey）。

   零副作用：不传 autoStartPrompt —— 打开运行台不触发任何模型调用；首次无历史时
   用一条本地静态欢迎语作种子（有历史时 readStoredChat 命中，种子被忽略）。

   ⚠️ 2026-10-10 权限修复后：权限档位改为**全局记忆**（store.permission），运行台
   助手档位随全局；写类操作（如写报告表头）在非只读档仍**必须经人工确认卡**才执行，
   且不触碰设备桥与测试指令——「对话不影响测试运行」的隔离承诺不变。
   =========================================================================== */

/** 运行台助手的固定会话尾缀：与流程页 `shell-<场景>-<流程>` 区分开，天然独立一份 */
const AUTO_SESSION_TAIL = 'auto'

/**
 * 首次打开（无历史）时的欢迎语种子。
 *
 * ⚠️ 刻意**不用 autoStartPrompt**：那会在每次挂载时真发一轮请求给后端。
 * 运行台常在「测试正在跑」时被打开，能不打扰就不打扰；这里只放一条静态说明，
 * 让人知道这块是干什么的、能问什么，需要时自己发第一句。
 */
const GREETING: ChatItem = {
  kind: 'message',
  id: 'auto-greeting',
  role: 'assistant',
  text:
    '我是运行台助手（只读）。测试跑着的时候可以问我：本批采集到哪些数据、某个读数为什么是「未采集」、某条判据的限值依据是什么。' +
    '我只查资料、不改设备——真要动台架请用运行台左下角的各项控制。',
  streaming: false,
}
if (GREETING.kind === 'message') {
  GREETING.uiText = uiMessage(GREETING.text)
  rememberScriptMessages([GREETING.text])
}

/**
 * 运行台助手适配器。
 *
 * · `USE_DSH`（`.env` 里 `VITE_AGENT_BACKEND=dsh`）→ 真后端 `dshAdapter`：
 *   后端只开放知识检索类工具（见 `api.ts` 的 `enabled_tools`），只读回答。
 * · 否则回落本地脚本回放：**如实说一句本轮没后端、不编回答**（照抄知识库页口径），
 *   免得演示态下模型凭通用知识瞎答。
 */
function useConsoleChatAdapter(): AgentAdapter {
  return useMemo(() => {
    // dshAdapter 是单例，无需按场景重建
    if (USE_DSH) return dshAdapter
    const resolve = (_req: SendRequest) => [
      {
        kind: 'say' as const,
        text: '本轮是演示态：运行台助手没有接后端，自由提问答不了。接上后端（VITE_AGENT_BACKEND=dsh）后这里由真实模型回答。',
      },
    ]
    return makeAdapter('console-auto', '运行台助手回放', resolve)
  }, [])
}

export function ConsoleChatPanel({
  onCollapse,
}: {
  /** 点助手卡头部「收起」→ 切回日志卡（由 AutomationConsole 控制卷动） */
  onCollapse: () => void
}) {
  const uiT = useT()

  const sceneId = useAppStore((s) => s.sceneId)
  const operator = useAppStore((s) => s.benchUser)
  const adapter = useConsoleChatAdapter()

  // 会话键与会话标识同一口径（同 FlowCopilot 的做法）：换场景天然换一份会话
  const sessionId = `shell-${sceneId}-${AUTO_SESSION_TAIL}`

  return (
    <div className="console-chat h-full min-h-0">
      <AgentChat
        adapter={adapter}
        assistantName={uiT("助手")}
        operator={operator}
        defaultPermission="readonly"
        // 独立的持久化键：运行台一份、人测页各流程各一份，互不覆盖
        sessionId={sessionId}
        persistKey={sessionId}
        // 无历史时的问候语种子；有历史时 AgentChat 读盘命中，自动忽略种子
        initialItems={[GREETING]}
        onCollapse={onCollapse}
      />
    </div>
  )
}
