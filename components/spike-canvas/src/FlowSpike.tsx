import { useCallback, useRef, useState } from 'react'
import {
  ReactFlow, ReactFlowProvider, Background, BackgroundVariant,
  Handle, Position, useNodesState, useEdgesState, useReactFlow, useStore,
  type Node, type Edge, type NodeProps, type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Network } from 'lucide-react'
import { NodeCard } from './NodeCard'
import { ToolRail } from './ToolRail'
import {
  SEED_NODES, SEED_EDGES, type CanvasNodeData, type RailItem,
} from './model'

/** 自定义节点：外观完全由 NodeCard 控制，React Flow 只负责定位与连接点 */
function DeviceNode({ data, selected }: NodeProps<Node<CanvasNodeData>>) {
  return (
    <>
      <Handle type="target" position={Position.Left} />
      <NodeCard data={data} selected={selected} />
      <Handle type="source" position={Position.Right} />
    </>
  )
}
const nodeTypes: NodeTypes = { device: DeviceNode }

const toNodes = (): Node<CanvasNodeData>[] =>
  SEED_NODES.map((n) => ({
    id: n.id, type: 'device', position: { x: n.x, y: n.y },
    data: { kind: n.kind, name: n.name, state: n.state, channel: n.channel, facts: n.facts },
  }))

const EDGE_STYLE = {
  // 与 c/ WorkflowCanvas.edgeStyle 同口径：主干墨绿实线 1.5，弱化链路浅绿虚线 1
  physical: { type: 'smoothstep', style: { stroke: '#2e5e45', strokeWidth: 1.5 } },
  data: { type: 'default', animated: true, style: { stroke: '#a8c5b5', strokeWidth: 1, strokeDasharray: '6 4' } },
} as const

const toEdges = (): Edge[] =>
  SEED_EDGES.map((e) => ({
    id: e.id, source: e.from, target: e.to, label: e.label,
    ...EDGE_STYLE[e.kind],
  }))

function ZoomBar() {
  const { zoomIn, zoomOut, fitView } = useReactFlow()
  const zoom = useStore((s) => s.transform[2])
  return (
    <div className="zoombar" data-testid="zoombar">
      <button type="button" onClick={() => zoomOut({ duration: 120 })} aria-label="缩小">−</button>
      <span className="pct" data-testid="zoom-pct">{Math.round(zoom * 100)}%</span>
      <button type="button" onClick={() => zoomIn({ duration: 120 })} aria-label="放大">+</button>
      <button type="button" onClick={() => fitView({ duration: 200, padding: 0.12 })}>复位</button>
    </div>
  )
}

function Canvas() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<CanvasNodeData>>(toNodes())
  const [edges, , onEdgesChange] = useEdgesState<Edge>(toEdges())
  const { screenToFlowPosition, fitView } = useReactFlow()
  const [dragOver, setDragOver] = useState(false)
  const seq = useRef(0)

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const raw = e.dataTransfer.getData('application/x-canvas-node')
    if (!raw) return
    const it = JSON.parse(raw) as RailItem
    seq.current += 1
    const pos = screenToFlowPosition({ x: e.clientX, y: e.clientY })
    setNodes((ns) => ns.concat({
      id: `new-${seq.current}`, type: 'device',
      position: { x: pos.x - 94, y: pos.y - 40 },
      selected: true,
      data: { kind: it.kind, name: it.name, state: it.state, channel: it.channel, facts: it.facts },
    }))
  }, [screenToFlowPosition, setNodes])

  return (
    <div
      className="canvas-wrap"
      data-testid="canvas"
      onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; setDragOver(true) }}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        /* 滚轮缩放 + 拖拽平移；外框尺寸不变，内容随之缩放 */
        zoomOnScroll
        panOnDrag
        panOnScroll={false}
        zoomOnDoubleClick={false}
        minZoom={0.35}
        maxZoom={2.5}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        proOptions={{ hideAttribution: true }}
        onDoubleClick={() => fitView({ duration: 200, padding: 0.12 })}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#dfe6e1" />
      </ReactFlow>
      <div className="legend">
        <span><i />物理接线</span>
        <span><i className="dash" />数据链路</span>
        <span>滚轮缩放 · 空白拖拽平移 · 双击复位</span>
      </div>
      <ZoomBar />
      {dragOver ? <div className="drophint">松手放置节点</div> : null}
    </div>
  )
}

export function FlowSpike() {
  return (
    <div className="panel" data-testid="panel">
      <div className="panel-head">
        <Network size={17} strokeWidth={1.9} />
        方案 A · React Flow（@xyflow/react）
        <span className="meta">C 区 1180 × 620 · 外框固定</span>
      </div>
      <div className="panel-body">
        <ReactFlowProvider>
          <Canvas />
        </ReactFlowProvider>
        <ToolRail />
      </div>
    </div>
  )
}
