/* 三种节点体：卡片型（CardArt）、事实型（三行事实）、设备型（MCP）。
   单独成文件，注册调用留在 nodes.tsx。 */
import { CardArt } from '../../app/CardArt'
import { getPanelCards } from '../../registry'
import { DeviceMcpNodeBody } from '../remote/DeviceMcpNode'
import { useBridgeDevice } from '../remote/bridge'
import type { CanvasNode, FlowId, ScenePackage } from '../../data/types'
import { CanvasNodeShell, NodeFacts, type NodeFact } from './CanvasNodeShell'
import type { CanvasLinkState } from './model'
import { useCanvasCtx } from './ctx'

/**
 * 卡片型节点：卡体优先用该卡在本流程已注册的真实渲染（场景包的图、曲线、判定表），
 * 没有注册实现时才退回 CardArt 线条稿——线条稿是通用占位，两个场景包共用一张，
 * 玻璃升降器包拿它当结构示意图会画出一把风扇，不能当默认。
 */
export function CardNode({ node, flow, scene }: { node: CanvasNode; flow: FlowId; scene: ScenePackage }) {
  const { expand } = useCanvasCtx()
  const reg = node.card ? getPanelCards(flow).find((c) => c.id === node.card) : undefined
  return (
    <CanvasNodeShell node={node} onExpand={() => expand(node)}>
      {reg ? reg.render({ flow, scene }) : node.card ? <CardArt id={node.card} /> : null}
    </CanvasNodeShell>
  )
}

/** 事实型节点：场景包里没有对应卡片的，卡体列三行事实 */
export function FactNode({
  node,
  facts,
  state,
  foot,
}: {
  node: CanvasNode
  facts: NodeFact[]
  state?: CanvasLinkState
  foot?: string
}) {
  const { expand } = useCanvasCtx()
  return (
    <CanvasNodeShell node={node} state={state} foot={foot} onExpand={() => expand(node)}>
      <NodeFacts facts={facts} />
    </CanvasNodeShell>
  )
}

export function DeviceNode({ node, scene }: { node: CanvasNode; scene: ScenePackage }) {
  const { expand } = useCanvasCtx()
  // 节点状态改读设备桥：三态映射照 README 第 5 节——live 走绿，mock 走中性并显式
  // 标「合成」，桥不可达或 connected=false 走暗红。
  const bridge = useBridgeDevice()
  const mode = bridge.device?.status.mode
  const state: CanvasLinkState =
    bridge.link !== 'online' ? 'offline' : mode === 'live' ? 'online' : mode === 'mock' ? 'offline' : 'fault'
  const foot = bridge.link === 'online' ? `设备桥 · ${bridge.toolCount} 个工具` : '设备桥未接入'
  return (
    <CanvasNodeShell node={node} state={state} foot={foot} onExpand={() => expand(node)}>
      <DeviceMcpNodeBody scene={scene} bridge={bridge} />
    </CanvasNodeShell>
  )
}

