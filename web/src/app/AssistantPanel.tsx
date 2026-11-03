import { Panel } from '../components/ui'
import type { FlowId, ScenePackage } from '../data/types'
import { renderAssistant, useRegistryVersion } from '../registry'

/** D 区 · 对话（规格 8）：测试助手，界面短名"助手"。
 *  助手可读、可算、可建议、可写草稿；落盘与控设备一律人点。
 *
 *  2026-10-04 清理：删除了壳层演示对话 `ShellAssistantPanel` 及其专属的
 *  `SEED` 假消息种子、`ToolCard`/`VerdictCard`/`SuggestCard` 三个演示卡片组件。
 *  五条流程在 `features/index.tsx` 已全部 `registerAssistant` 真实助手
 *  （`FlowCopilot`），`hasAssistant(flow)` 恒为 true，壳层退路永不渲染——
 *  是与真实助手语义冲突的死代码（它那句「壳层演示版未接模型」早已过时）。 */

/** 注册了真实助手组件时，D 区整块交给它；否则走壳层的演示对话。
 *
 *  onCollapse 由壳层（FlowScreen）透传，真实助手会据此在头部多渲染一枚收起键。
 *  演示对话这一支不接：它的高度本来就由壳层管，不需要自己折自己。
 */
export function AssistantPanel(props: {
  flow: FlowId
  scene: ScenePackage
  onCollapse?: () => void
}) {
  useRegistryVersion()
  return <Panel>{renderAssistant(props.flow, props)}</Panel>
}
