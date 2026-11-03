/* ===========================================================================
   工作流画布 → C 区画板的适配层。

   第三轮之后画布只有一处实现：C 区统一画板上的 workflow 节点，放大态直接复用
   已注册的「工作流画布」卡片（src/features/flow-req/panel.tsx 注册进 registry 的
   那一张），里面就是 WorkflowCanvas 本体。两处不再各写一套画布。

   本文件只做转接，不碰 WorkflowCanvas 的任何签名（WorkflowCanvasProps 冻结，
   flow-req 页在用）。注册表里取不到那张卡时返回 null，由调用方画空态。
   =========================================================================== */
import type { ReactNode } from 'react'
import { getPanelCards } from '../../registry'
import type { FlowId, ScenePackage } from '../../data/types'

/** 工作流画布挂在需求确认流程上，别的流程复用同一份注册实现 */
const WORKFLOW_HOST_FLOW: FlowId = 'req'

function workflowCard() {
  return getPanelCards(WORKFLOW_HOST_FLOW).find((c) => c.id === 'workflow')
}

/** 节点缩略态：卡片的常规渲染 */
export function WorkflowCanvasThumb({ scene }: { scene: ScenePackage }): ReactNode {
  const reg = workflowCard()
  return reg ? reg.render({ flow: WORKFLOW_HOST_FLOW, scene }) : null
}

/** 节点放大态：卡片的放大渲染，缺省时退回常规渲染 */
export function WorkflowCanvasExpanded({ scene }: { scene: ScenePackage }): ReactNode {
  const reg = workflowCard()
  if (!reg) return null
  return (reg.renderExpanded ?? reg.render)({ flow: WORKFLOW_HOST_FLOW, scene })
}
