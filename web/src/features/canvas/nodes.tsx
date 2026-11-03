/* ===========================================================================
   十一类画板节点的注册。

   本文件被 src/features/canvas/index.ts import 一次即生效（副作用注册），
   不需要动已冻结的 src/features/index.tsx。

   节点分五类，类内不超过 5 项，见 model.ts 的 CANVAS_NODE_META：
     被测对象  motor · schematic
     测量设备  scope · bench
     激励与环境 psu
     过程与数据 workflow · curve · verdict
     服务与连接 device-mcp · interlock · knowledge
   =========================================================================== */

import { registerCanvasNode } from '../../registry'
import type { CanvasNodeType, ScenePackage } from '../../data/types'
import { CANVAS_NODE_META, CANVAS_NODE_SIZE, type CanvasLinkState } from './model'
import { CardNode, DeviceNode, FactNode } from './nodeKinds'

/**
 * 设备类节点的连接态取自场景包工具条上对应那一件工具的状态，
 * 不做整条工具条的聚合——聚合会把某一件工具的异常安到别的设备头上。
 * 对不上工具的节点一律「未接入」，不假报在线。
 */
const TOOL_MATCH: Partial<Record<CanvasNodeType, RegExp>> = {
  scope: /示波|波形|采集|采样/,
  psu: /电源|供电/,
  bench: /台架|涵道|风|温箱|工装/,
}

function stateOfTools(scene: ScenePackage, type: CanvasNodeType): CanvasLinkState {
  const re = TOOL_MATCH[type]
  if (!re) return 'offline'
  const hit = scene.toolGroups.flatMap((g) => g.tools).find((t) => re.test(t.label))
  if (!hit) return 'offline'
  return hit.state === 'online' ? 'online' : hit.state === 'fault' ? 'fault' : 'offline'
}

/** 卡片型：有 card 就画 CardArt，没有就退回事实行 */
const CARD_KINDS: CanvasNodeType[] = [
  'motor',
  'schematic',
  'workflow',
  'curve',
  'verdict',
  'interlock',
  'knowledge',
]

for (const type of CARD_KINDS) {
  registerCanvasNode({
    type,
    label: CANVAS_NODE_META[type].label,
    size: CANVAS_NODE_SIZE,
    render: ({ node, flow, scene }) =>
      node.card ? (
        <CardNode node={node} flow={flow} scene={scene} />
      ) : (
        <FactNode node={node} facts={[['类型', CANVAS_NODE_META[type].sub]]} />
      ),
  })
}

registerCanvasNode({
  type: 'scope',
  label: CANVAS_NODE_META.scope.label,
  size: CANVAS_NODE_SIZE,
  render: ({ node, scene }) => (
    <FactNode
      node={node}
      state={stateOfTools(scene, 'scope')}
      foot="波形采集"
      facts={[
        ['通道', 'CH1–CH4'],
        ['台架', scene.meta.bench ?? '未登记'],
      ]}
    />
  ),
})

registerCanvasNode({
  type: 'bench',
  label: CANVAS_NODE_META.bench.label,
  size: CANVAS_NODE_SIZE,
  render: ({ node, flow, scene }) =>
    node.card ? (
      <CardNode node={node} flow={flow} scene={scene} />
    ) : (
      <FactNode
        node={node}
        state={stateOfTools(scene, 'bench')}
        foot="台架实况"
        facts={[['台架', scene.meta.bench ?? '未登记']]}
      />
    ),
})

registerCanvasNode({
  type: 'psu',
  label: CANVAS_NODE_META.psu.label,
  size: CANVAS_NODE_SIZE,
  render: ({ node, scene }) => (
    <FactNode
      node={node}
      state={stateOfTools(scene, 'psu')}
      foot="激励输出"
      facts={[
        ['输出', '按场景包设定'],
        ['归属', scene.meta.productType],
      ]}
    />
  ),
})

registerCanvasNode({
  type: 'device-mcp',
  label: CANVAS_NODE_META['device-mcp'].label,
  size: { w: 240, h: 168 },
  render: ({ node, scene }) => <DeviceNode node={node} scene={scene} />,
})
