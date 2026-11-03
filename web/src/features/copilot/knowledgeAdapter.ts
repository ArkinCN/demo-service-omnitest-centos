import { useMemo } from 'react'
import type { AgentAdapter, SendRequest } from '../agent-chat'
import { dshAdapter } from '../agent-chat/api'
import { getPack } from '../scene/pack'
import { makeAdapter, type Step } from './adapter'
import { USE_DSH } from './backend'
import { heldEnv, takePending } from './held'
import { stepsForAction } from './actionScripts'

/**
 * 知识库模块页那块对话用的适配器。
 *
 * 两条路（与流程页 `copilot/index.tsx` **同一口径**，共用 USE_DSH 开关）：
 *   · USE_DSH（.env 里 VITE_AGENT_BACKEND=dsh）→ 走真后端 dshAdapter，
 *     四枚预置动作（库存盘点/缺口清单/抽取草稿/分类归位）与自由提问都由真实模型回答。
 *     上下文包由 ActionDock 的 setHeldEnv 带上，dshAdapter 会把它一并发给后端。
 *   · 否则回落本地脚本回放：认领得上预置动作就放它那段脚本；认不出（人自己打的字）
 *     就如实说一句本轮没后端，不编回答。
 *
 * ⚠️ 此前这里**硬编码只走回放**，即便后端已接通，知识库四按钮仍只回「本轮是演示态」
 * ——同一语义两套判据的老坑（见 backend.ts 顶部说明）。改为共用 USE_DSH 后消除分叉。
 */
export function useKnowledgeAdapter(): AgentAdapter | undefined {
  const pack = getPack()
  return useMemo(() => {
    // dshAdapter 是单例，无需按 pack 重建
    if (USE_DSH) return dshAdapter
    if (!pack) return undefined
    const resolve = (req: SendRequest): Step[] => {
      const def = takePending()
      const snapshot = heldEnv()
      if (def && snapshot && req.text.trim() === def.prompt.trim()) {
        return stepsForAction(def, pack, snapshot)
      }
      return [
        {
          kind: 'say',
          text: '本轮是演示态：没有接后端，只有输入区上方那几枚预置动作有脚本化回放，自由提问答不了。要看知识库能做什么，点上面的按钮。',
        },
      ]
    }
    return makeAdapter('module-knowledge', '知识库回放', resolve)
  }, [pack])
}
