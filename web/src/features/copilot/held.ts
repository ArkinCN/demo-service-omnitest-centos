import type { ActionDef } from './actions'
import type { Envelope } from './context'

/* ===========================================================================
   两个跨渲染周期的持有位。

   适配器的 send 发生在渲染之外，却要读「刚点的是哪一枚按钮」与「点的当口的
   上下文包」。用模块级私有变量加存取函数而不是组件内的 ref，是为了让读写都落在
   渲染之外，组件里一次 `.current` 都不出现。
   =========================================================================== */

let env: Envelope | null = null
let pending: ActionDef | null = null

export const setHeldEnv = (e: Envelope) => {
  env = e
}
export const heldEnv = (): Envelope | null => env

export const setPending = (d: ActionDef | null) => {
  pending = d
}
/** 取走并清空：一次点击只认领一轮，认领过就还原成手打消息的通路 */
export const takePending = (): ActionDef | null => {
  const d = pending
  pending = null
  return d
}
