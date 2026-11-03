/**
 * 工作流画布。
 *
 * 输入统一内部模型，输出选中事件与编辑后的模型；宿主只需管模型，
 * React Flow 的实例状态完全封在内部。
 */
import { useCallback, useEffect, useMemo, useRef } from 'react'
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeMouseHandler,
  type OnEdgesDelete,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import { layoutModel } from '../lib/layout'
import { NODE_GROUPS } from '../lib/nodeCatalog'
import type { WorkflowModel, WorkflowNode } from '../types'
import { WorkflowNodeCard, type FlowNodeData } from './WorkflowNodeCard'

export interface WorkflowCanvasProps {
  model: WorkflowModel
  /** 节点点选回调，取消选中时传 null。 */
  onSelect?: (node: WorkflowNode | null) => void
  /** 连线增删后的完整模型。参数编辑由 PropertyDrawer 负责，不走这里。 */
  onChange?: (model: WorkflowModel) => void
  readonly?: boolean
  /** 当前选中节点 id，由宿主受控。 */
  selectedId?: string | null
  className?: string
  /**
   * 初始 fitView 的缩放区间。默认下限 0.6——放大态里节点多的图会被这个下限
   * 顶住而裁掉边缘，宿主可以传 { minZoom: 0.2 } 让它缩到看得全为止。
   */
  fitViewOptions?: { padding?: number; minZoom?: number; maxZoom?: number }
}

const DEFAULT_FIT_VIEW = { padding: 0.12, minZoom: 0.6, maxZoom: 1.1 }

const NODE_TYPES = { wfNode: WorkflowNodeCard }

/**
 * 异常出口画成墨绿弱描边虚线，主干走墨绿实线。
 *
 * 原先异常出口是暗红实色：一张十节点的图里每个节点都挂一条 error 边回异常出口，
 * 画面上就是九条暗红斜线，远超「暗红每屏 ≤5 处」的面积约束，而且异常出口的存在
 * 本身不是异常。层次改靠线宽（1.5 / 1）与虚实（实线 / 6 4 虚线）区分。
 */
function edgeStyle(sourceHandle?: string) {
  const isError = sourceHandle === 'error' || sourceHandle === 'false'
  return {
    stroke: isError ? '#a8c5b5' : '#2e5e45',
    strokeWidth: isError ? 1 : 1.5,
    strokeDasharray: isError ? '6 4' : undefined,
  }
}

function toFlowNodes(model: WorkflowModel, selectedId: string | null | undefined): Node[] {
  const positions = layoutModel(model)
  return model.nodes.map((n) => ({
    id: n.id,
    type: 'wfNode',
    position: positions[n.id] ?? { x: 0, y: 0 },
    selected: n.id === selectedId,
    data: {
      label: n.label,
      type: n.type,
      group: n.group,
      paramCount: Object.keys(n.params).length,
      hasEmbedded: Boolean(n.embedded),
    } satisfies FlowNodeData,
  }))
}

function toFlowEdges(model: WorkflowModel): Edge[] {
  return model.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: null,
    targetHandle: null,
    animated: false,
    style: edgeStyle(e.sourceHandle),
    // 保留原始端口名，导出时要写回。
    data: { sourceHandle: e.sourceHandle, targetHandle: e.targetHandle },
  }))
}

function CanvasInner({
  model,
  onSelect,
  onChange,
  readonly = false,
  selectedId,
  className,
  fitViewOptions,
}: WorkflowCanvasProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])

  // 结构签名：只有节点/连线集合变化才重排，参数编辑不应打乱布局。
  const signature = useMemo(
    () =>
      `${model.meta.id ?? model.meta.name}|${model.nodes.map((n) => n.id).join(',')}|${model.edges
        .map((e) => e.id)
        .join(',')}`,
    [model],
  )
  const lastSignature = useRef<string>('')

  useEffect(() => {
    if (lastSignature.current === signature) return
    lastSignature.current = signature
    setNodes(toFlowNodes(model, selectedId))
    setEdges(toFlowEdges(model))
  }, [signature, model, selectedId, setNodes, setEdges])

  // 标签改动同步到已渲染的节点，不触发重排。
  useEffect(() => {
    setNodes((prev) =>
      prev.map((n) => {
        const src = model.nodes.find((m) => m.id === n.id)
        if (!src) return n
        const d = n.data as FlowNodeData
        if (d.label === src.label && d.paramCount === Object.keys(src.params).length) return n
        return {
          ...n,
          data: { ...d, label: src.label, paramCount: Object.keys(src.params).length },
        }
      }),
    )
  }, [model, setNodes])

  useEffect(() => {
    setNodes((prev) =>
      prev.map((n) => (n.selected === (n.id === selectedId) ? n : { ...n, selected: n.id === selectedId })),
    )
  }, [selectedId, setNodes])

  const handleNodeClick = useCallback<NodeMouseHandler>(
    (_, node) => {
      onSelect?.(model.nodes.find((n) => n.id === node.id) ?? null)
    },
    [model, onSelect],
  )

  const handlePaneClick = useCallback(() => onSelect?.(null), [onSelect])

  const handleConnect = useCallback(
    (connection: Connection) => {
      if (readonly || !connection.source || !connection.target) return
      const id = `edge-${connection.source}-${connection.target}-${Date.now()}`
      setEdges((prev) =>
        addEdge({ ...connection, id, style: edgeStyle('output'), data: { sourceHandle: 'output', targetHandle: 'input' } }, prev),
      )
      onChange?.({
        ...model,
        edges: [
          ...model.edges,
          { id, source: connection.source, target: connection.target, sourceHandle: 'output', targetHandle: 'input' },
        ],
      })
    },
    [readonly, model, onChange, setEdges],
  )

  const handleEdgesDelete = useCallback<OnEdgesDelete>(
    (deleted) => {
      if (readonly) return
      const gone = new Set(deleted.map((e) => e.id))
      onChange?.({ ...model, edges: model.edges.filter((e) => !gone.has(e.id)) })
    },
    [readonly, model, onChange],
  )

  return (
    <div className={`wf-canvas ${className ?? ''}`}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={readonly ? undefined : onEdgesChange}
        onEdgesDelete={handleEdgesDelete}
        onConnect={handleConnect}
        onNodeClick={handleNodeClick}
        onPaneClick={handlePaneClick}
        nodesConnectable={!readonly}
        nodesDraggable={!readonly}
        elementsSelectable
        fitView
        fitViewOptions={{ ...DEFAULT_FIT_VIEW, ...fitViewOptions }}
        minZoom={0.1}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#c8c5bd" gap={20} size={1} />
        <Controls showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          nodeColor={(n) => NODE_GROUPS[(n.data as FlowNodeData).group]?.color ?? '#9a9a9a'}
          maskColor="rgba(234, 242, 236, 0.75)"
        />
      </ReactFlow>
    </div>
  )
}

export function WorkflowCanvas(props: WorkflowCanvasProps) {
  return (
    <ReactFlowProvider>
      <CanvasInner {...props} />
    </ReactFlowProvider>
  )
}
