import type { AgentAdapter, AgentEvent, SendRequest } from '../agent-chat'
import type { EvidenceItem, Verdict } from '../agent-chat'
import { rememberScriptMessages, uiMessage, type UiMessageText } from '../../i18n/messages'

/* ===========================================================================
   按流程回放的脚本化适配器。

   agent-chat 自带的 mockAdapter 只有一段固定脚本（读 Customer.h → 启动 → 取数
   → 判定），不贴六条流程。这里把「脚本」抽成数据，每条流程给一段自己的脚本，
   再用同一套 AgentEvent 协议吐出去——组件本体一行没改。
   改动类动作照样走人工确认闸门：requestConfirm 未注入时按「不放行」处理。
   =========================================================================== */

export type Step =
  | { kind: 'say'; text: string; uiText?: UiMessageText }
  | {
      kind: 'tool'
      callId: string
      name: string
      title: string
      args: Record<string, unknown>
      argsSummary: string
      mutating?: boolean
      durationMs: number
      resultSummary: string
      result: unknown
    }
  | { kind: 'verdict'; verdict: Verdict }
  | { kind: 'evidence'; items: EvidenceItem[] }

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

/** 轮次序号。消息与工具调用的标识必须逐轮唯一，否则第二轮的正文会追加到
    第一轮的同名气泡里、第二轮的工具结果会回填到第一轮的同名卡片上。 */
let turn = 0

async function* play(steps: Step[], req: SendRequest, pace: number): AsyncGenerator<AgentEvent, void, void> {
  const wait = (ms: number) => (pace === 0 ? Promise.resolve() : sleep(ms * pace))
  turn += 1
  const t = turn
  const uid = (id: string) => `t${t}-${id}`
  let seg = 0
  for (const s of steps) {
    if (s.kind === 'say') {
      rememberScriptMessages([s.text])
      seg += 1
      const messageId = `m${t}-${seg}`
      for (let i = 0; i < s.text.length; i += 6) {
        await wait(22)
        yield { type: 'message_delta', messageId, delta: s.text.slice(i, i + 6), uiText: s.uiText ?? uiMessage(s.text) }
      }
      continue
    }
    if (s.kind === 'tool') {
      await wait(240)
      yield {
        type: 'tool_call',
        uiAuthored: true,
        callId: uid(s.callId),
        name: s.name,
        title: s.title,
        args: s.args,
        argsSummary: s.argsSummary,
        mutating: s.mutating,
      }
      if (s.mutating) {
        const ok = req.requestConfirm
          ? await req.requestConfirm({ callId: uid(s.callId), name: s.name, argsSummary: s.argsSummary })
          : false
        if (!ok) {
          yield {
            type: 'tool_result',
            uiAuthored: true,
            callId: uid(s.callId),
            status: 'error',
            durationMs: 0,
            resultSummary: '已取消：未获人工确认，动作未执行',
            result: { cancelled: true, reason: 'not_confirmed' },
          }
          yield { type: 'done', reason: 'aborted' }
          return
        }
      }
      await wait(Math.min(900, s.durationMs))
      yield {
        type: 'tool_result',
        uiAuthored: true,
        callId: uid(s.callId),
        status: 'ok',
        durationMs: s.durationMs,
        resultSummary: s.resultSummary,
        result: s.result,
      }
      continue
    }
    if (s.kind === 'verdict') {
      await wait(200)
      yield { type: 'verdict', verdict: s.verdict }
      continue
    }
    await wait(160)
    yield { type: 'evidence', items: s.items }
  }
  yield { type: 'done', reason: 'complete' }
}

/**
 * steps 可以是一段固定脚本，也可以是按请求现算的一段脚本——
 * 点预置动作按钮时走后者：同一条流程里，按钮各有各的脚本，
 * 手打的消息仍回落到该流程的默认脚本。
 */
export function makeAdapter(
  id: string,
  label: string,
  steps: Step[] | ((req: SendRequest) => Step[]),
  pace = 1,
): AgentAdapter {
  if (Array.isArray(steps)) rememberScriptMessages(steps.filter((step) => step.kind === 'say').map((step) => step.text))
  return {
    id,
    label,
    send: (req: SendRequest) => play(typeof steps === 'function' ? steps(req) : steps, req, pace),
  }
}
