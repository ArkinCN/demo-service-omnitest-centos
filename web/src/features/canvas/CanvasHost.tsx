import { useT, translate, initialLocale } from '../../i18n'
/* ===========================================================================
   C 区统一画板（React Flow 本体）。

   落的是《第三轮实施计划 · 并行派工》第三节第 5 条那张表：
     外框   C 区容器尺寸与位置完全不变，只有画布内容随滚轮缩放
     缩放   滚轮以指针为锚点，0.4× 至 2.5×；左下角百分比加复位按钮
     平移   空白处左键拖拽或中键拖拽，触控板双指
     节点   十一类，按 registerCanvasNode() 的登记渲染（src/features/canvas/nodes.tsx）
     边     物理连接实线标通道名、数据流虚线，线型口径取 src/data/bench.ts 的 CANVAS_EDGE_DASH
     工具条 右侧工具块拖到落点即建节点，落点之外放手取消
     设备   设备即 MCP 节点，终端只在放大态出现
   版式按「场景包 × 流程」存 localStorage，键见 model.ts 的 layoutKey()。
   =========================================================================== */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  Background,
  BackgroundVariant,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  useStore,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import './canvas.css'

import { Button, Modal, cn } from '../../components/ui'
import { CardArt } from '../../app/CardArt'
import { BENCH_CHANNEL_PENDING, CANVAS_EDGE_DASH } from '../../data/bench'
import { getCanvasNode, getPanelCards, useRegistryVersion } from '../../registry'
import { useAppStore } from '../../state/useAppStore'
import type { CanvasLayout, CanvasNode, FlowId, ScenePackage } from '../../data/types'
import { DeviceMcpExpanded } from '../remote/DeviceMcpNode'
import { WorkflowCanvasExpanded } from '../workflow/canvasAdapter'
import { CanvasCtx } from './ctx'
import { CANVAS_DND_MIME, type CanvasDragPayload } from './dnd'
import {
  CANVAS_NODE_META,
  CANVAS_NODE_SIZE,
  clearLayout,
  defaultLayout,
  loadLayout,
  saveLayout,
} from './model'

const MIN_ZOOM = 0.4
const MAX_ZOOM = 2.5

/* ----------------------------------------------------------------- 节点外壳 */

interface FlowNodeData extends Record<string, unknown> {
  node: CanvasNode
  flow: FlowId
  scene: ScenePackage
}

/**
 * 节点四边各挂一对连接点。连接点本身在画面上隐藏（CSS opacity 0），
 * 只用来给边定端点——边按两个节点的相对位置挑边，避免连线绕过整张卡。
 */
const SIDES = [
  ['l', Position.Left],
  ['r', Position.Right],
  ['t', Position.Top],
  ['b', Position.Bottom],
] as const

function CanvasNodeView({ data }: NodeProps<Node<FlowNodeData>>) {
  const { node, flow, scene } = data
  const reg = getCanvasNode(node.type)
  if (!reg) return null
  return (
    <div className="h-full w-full">
      {SIDES.map(([k, pos]) => (
        <Handle key={`s${k}`} id={`s${k}`} type="source" position={pos} isConnectable={false} />
      ))}
      {SIDES.map(([k, pos]) => (
        <Handle key={`t${k}`} id={`t${k}`} type="target" position={pos} isConnectable={false} />
      ))}
      {reg.render({ node, flow, scene })}
    </div>
  )
}

const NODE_TYPES: NodeTypes = { cv: CanvasNodeView }

/* --------------------------------------------------------------- 模型转换 */

function toFlowNodes(layout: CanvasLayout, flow: FlowId, scene: ScenePackage): Node<FlowNodeData>[] {
  return layout.nodes
    .filter((n) => getCanvasNode(n.type))
    .map((n) => ({
      id: n.id,
      type: 'cv',
      position: { x: n.x, y: n.y },
      style: {
        width: n.w ?? getCanvasNode(n.type)?.size?.w ?? CANVAS_NODE_SIZE.w,
        height: n.h ?? getCanvasNode(n.type)?.size?.h ?? CANVAS_NODE_SIZE.h,
      },
      data: { node: n, flow, scene },
    }))
}

/** 按两个节点的相对位置挑连接点：左右错开走左右，上下错开走上下 */
function pickHandles(a?: CanvasNode, b?: CanvasNode): { sourceHandle: string; targetHandle: string } {
  if (!a || !b) return { sourceHandle: 'sr', targetHandle: 'tl' }
  const dx = b.x - a.x
  const dy = b.y - a.y
  if (Math.abs(dx) > 60) {
    return dx > 0 ? { sourceHandle: 'sr', targetHandle: 'tl' } : { sourceHandle: 'sl', targetHandle: 'tr' }
  }
  return dy > 0 ? { sourceHandle: 'sb', targetHandle: 'tt' } : { sourceHandle: 'st', targetHandle: 'tb' }
}

function toFlowEdges(layout: CanvasLayout): Edge[] {
  const byId = new Map(layout.nodes.map((n) => [n.id, n]))
  return layout.edges.map((e) => ({
    id: e.id,
    source: e.from,
    target: e.to,
    ...pickHandles(byId.get(e.from), byId.get(e.to)),
    type: e.kind === 'physical' ? 'smoothstep' : 'default',
    // 物理连接边标通道名；那套通道映射尚未经客户书面确认，标注里一并挂出来。
    // ⚠️ 本函数是**模块级**（无 hook），故用 translate + initialLocale 口径（同 context.ts 的 ctxT）
    label:
      e.kind === 'physical' && e.label
        ? `${e.label} · ${translate(BENCH_CHANNEL_PENDING, initialLocale())}`
        : undefined,
    labelBgPadding: [4, 2] as [number, number],
    labelBgBorderRadius: 6,
    style: {
      stroke: e.kind === 'physical' ? '#2e5e45' : '#a8c5b5',
      strokeWidth: e.kind === 'physical' ? 1.5 : 1,
      strokeDasharray: CANVAS_EDGE_DASH[e.kind],
    },
  }))
}

/* ------------------------------------------------------------- 右下缩放条

   位置按编排者裁决第 1 条落在右下角，与客户参考页
   （_调研/ref-客户Copilot页面-用户提供-20260919.png）一致；
   缩略导航图让到左下角，两个控件仍分处两角、互不遮挡。 */

function ZoomBar({ onReset }: { onReset: () => void }) {
  const uiT = useT()

  const { zoomIn, zoomOut } = useReactFlow()
  const zoom = useStore((s) => s.transform[2])
  return (
    <div className="cv-zoom">
      <button type="button" aria-label={uiT("缩小")} onClick={() => zoomOut({ duration: 120 })}>
        −
      </button>
      <span className="pct" data-testid="canvas-zoom">
        {Math.round(zoom * 100)}%
      </span>
      <button type="button" aria-label={uiT("放大画布")} onClick={() => zoomIn({ duration: 120 })}>
        +
      </button>
      <button type="button" onClick={onReset}>
        {uiT("复位")}</button>
    </div>
  )
}

/** 缩略导航图只在内容超出视口时出现（规格 2.4），落在右下角、叠在缩放条上方 */
function useOverflow(nodes: Node<FlowNodeData>[]) {
  const w = useStore((s) => s.width)
  const h = useStore((s) => s.height)
  const zoom = useStore((s) => s.transform[2])
  if (!nodes.length || !w || !h) return false
  const xs = nodes.map((n) => n.position.x)
  const ys = nodes.map((n) => n.position.y)
  const ws = nodes.map((n) => Number(n.style?.width ?? CANVAS_NODE_SIZE.w))
  const hs = nodes.map((n) => Number(n.style?.height ?? CANVAS_NODE_SIZE.h))
  const bw = Math.max(...xs.map((x, i) => x + ws[i])) - Math.min(...xs)
  const bh = Math.max(...ys.map((y, i) => y + hs[i])) - Math.min(...ys)
  return bw * zoom > w + 8 || bh * zoom > h + 8
}

function MiniMapIfOverflow({ nodes }: { nodes: Node<FlowNodeData>[] }) {
  const overflow = useOverflow(nodes)
  if (!overflow) return null
  return (
    <MiniMap
      pannable
      zoomable
      /* 原先钉在左下角，放大态下正压住「文档读取」那一列节点，看着像破版。
         改到右下角与缩放条同列（CSS 里给它让出缩放条的 40px），两个控件叠成
         一摞控制区，画板左侧的节点不再被盖。 */
      position="bottom-right"
      style={{ width: 132, height: 88 }}
      nodeColor="#a8c5b5"
      nodeStrokeColor="#2e5e45"
      maskColor="rgba(46, 94, 69, 0.10)"
    />
  )
}

/* ------------------------------------------------------------------- 本体 */

function CanvasInner({
  flow,
  scene,
  nodes: seeded,
}: {
  flow: FlowId
  scene: ScenePackage
  nodes?: CanvasNode[]
}) {
  const uiT = useT()

  const sceneId = scene.meta.id
  const selected = useAppStore((s) => s.canvasSelected)
  const setSelected = useAppStore((s) => s.setCanvasSelected)
  const { screenToFlowPosition, fitView } = useReactFlow()

  const initial = useMemo<CanvasLayout>(() => {
    const stored = loadLayout(sceneId, flow)
    if (stored) return stored
    if (seeded?.length) return { nodes: seeded, edges: [] }
    return defaultLayout(flow, scene)
  }, [sceneId, flow, scene, seeded])

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<FlowNodeData>>(
    toFlowNodes(initial, flow, scene),
  )
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(toFlowEdges(initial))
  const [expanded, setExpanded] = useState<CanvasNode | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const seq = useRef(0)
  const edgesRef = useRef<CanvasLayout['edges']>(initial.edges)

  // 换流程或换场景包等于换一张图，整体重建；人摆过的版式在 initial 里已经取回
  const signature = `${sceneId}|${flow}`
  const lastSignature = useRef(signature)
  useEffect(() => {
    if (lastSignature.current === signature) return
    lastSignature.current = signature
    edgesRef.current = initial.edges
    setNodes(toFlowNodes(initial, flow, scene))
    setEdges(toFlowEdges(initial))
    window.setTimeout(() => fitView({ padding: 0.12, duration: 0 }), 0)
  }, [signature, initial, flow, scene, setNodes, setEdges, fitView])

  /**
   * 场景包对象本身被换掉（启动时先给 mock、真包读完再替换）而流程没变时，
   * 不重排版式，只把新场景包与新卡名灌进已有节点——否则节点里显示的会是
   * 上一份 scene 的数字。
   */
  useEffect(() => {
    const fresh = new Map(defaultLayout(flow, scene).nodes.map((n) => [n.id, n]))
    setNodes((prev) =>
      prev.map((n) => {
        if (n.data.scene === scene) return n
        const f = fresh.get(n.id)
        return {
          ...n,
          data: {
            ...n.data,
            scene,
            node: f ? { ...n.data.node, label: f.label } : n.data.node,
          },
        }
      }),
    )
  }, [scene, flow, setNodes])

  const persist = useCallback(
    (list: Node<FlowNodeData>[]) => {
      const layout: CanvasLayout = {
        nodes: list.map((n) => ({
          ...n.data.node,
          x: Math.round(n.position.x),
          y: Math.round(n.position.y),
        })),
        edges: edgesRef.current,
      }
      saveLayout(sceneId, flow, layout)
    },
    [sceneId, flow],
  )

  const reset = useCallback(() => {
    clearLayout(sceneId, flow)
    const fresh = defaultLayout(flow, scene)
    edgesRef.current = fresh.edges
    setNodes(toFlowNodes(fresh, flow, scene))
    setEdges(toFlowEdges(fresh))
    window.setTimeout(() => fitView({ padding: 0.12, duration: 200 }), 0)
  }, [sceneId, flow, scene, setNodes, setEdges, fitView])

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragOver(false)
      const raw = e.dataTransfer.getData(CANVAS_DND_MIME)
      if (!raw) return
      let payload: CanvasDragPayload
      try {
        payload = JSON.parse(raw) as CanvasDragPayload
      } catch {
        return
      }
      if (!getCanvasNode(payload.type)) return
      seq.current += 1
      const size = getCanvasNode(payload.type)?.size ?? CANVAS_NODE_SIZE
      const p = screenToFlowPosition({ x: e.clientX, y: e.clientY })
      const node: CanvasNode = {
        id: `drop-${payload.type}-${seq.current}`,
        type: payload.type,
        label: payload.label || CANVAS_NODE_META[payload.type].label,
        x: Math.round(p.x - size.w / 2),
        y: Math.round(p.y - size.h / 2),
        w: size.w,
        h: size.h,
      }
      setNodes((prev) => {
        const next = [...prev, ...toFlowNodes({ nodes: [node], edges: [] }, flow, scene)]
        persist(next)
        return next
      })
      setSelected(node.id)
    },
    [screenToFlowPosition, setNodes, flow, scene, persist, setSelected],
  )

  const ctx = useMemo(() => ({ expand: setExpanded, selectedId: selected }), [selected])

  /** 放大态的内容：设备走终端视图，工作流复用工作流画布，其余复用卡片的放大渲染 */
  const expandedBody = (node: CanvasNode): ReactNode => {
    if (node.type === 'device-mcp') return <DeviceMcpExpanded scene={scene} />
    if (node.type === 'workflow') return <WorkflowCanvasExpanded scene={scene} />
    if (node.card) {
      const reg = getPanelCards(flow).find((c) => c.id === node.card)
      if (reg) return (reg.renderExpanded ?? reg.render)({ flow, scene })
      return (
        <div className="h-[min(56vh,400px)] w-[620px]">
          <CardArt id={node.card} />
        </div>
      )
    }
    const impl = getCanvasNode(node.type)
    return (
      <div className="h-[280px] w-[420px]">{impl ? impl.render({ node, flow, scene }) : null}</div>
    )
  }

  return (
    <CanvasCtx.Provider value={ctx}>
      <div
        className="cv-wrap"
        onDragOver={(e) => {
          e.preventDefault()
          e.dataTransfer.dropEffect = 'copy'
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeDragStop={() => persist(nodes)}
          onNodeClick={(_, n) => setSelected(n.id)}
          onNodeDoubleClick={(_, n) => setExpanded((n.data as FlowNodeData).node)}
          onPaneClick={() => setSelected(null)}
          nodesConnectable={false}
          elementsSelectable
          zoomOnScroll
          panOnDrag={[0, 1]}
          panOnScroll={false}
          zoomOnDoubleClick={false}
          minZoom={MIN_ZOOM}
          maxZoom={MAX_ZOOM}
          fitView
          fitViewOptions={{ padding: 0.12, minZoom: MIN_ZOOM, maxZoom: 1 }}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#dfe6e1" />
          <MiniMapIfOverflow nodes={nodes} />
        </ReactFlow>

        <div className="cv-legend">
          <span>
            <i />
            {uiT("物理接线")}</span>
          <span>
            <i className="dash" />
            {uiT("数据流")}</span>
          <span>{uiT("通道映射")} {uiT(BENCH_CHANNEL_PENDING)}</span>
        </div>
        <ZoomBar onReset={reset} />
        {dragOver ? <div className="cv-drop">{uiT("松手即在此处建节点")}</div> : null}
      </div>

      <Modal
        open={!!expanded}
        onClose={() => setExpanded(null)}
        /* 设备节点放大态只有「设备卡 + 接入形态 + 工具统计 + 终端」四块，
           按 1220 宽铺开右半边基本是空的；这一类单独收窄到 860。 */
        width={expanded?.type === 'device-mcp' ? 860 : 1220}
        title={expanded ? expanded.label : ''}
        meta={expanded ? CANVAS_NODE_META[expanded.type].sub : undefined}
        footer={
          <>
            <Button size="sm" variant="ghost" onClick={() => setExpanded(null)}>
              {uiT("关闭")}</Button>
            <Button size="sm" variant="secondary">
              {uiT("在新窗口打开")}</Button>
          </>
        }
      >
        <div
          className={cn(
            'flex items-center justify-center rounded-tp2 bg-p50 p-2',
            expanded?.type === 'device-mcp' ? 'h-[min(42vh,300px)]' : 'h-[min(64vh,470px)]',
          )}
        >
          {expanded ? expandedBody(expanded) : null}
        </div>
      </Modal>
    </CanvasCtx.Provider>
  )
}

/**
 * 画板挂载点。签名与 W1 放行的接口清单一致：{flow, scene, nodes?, fallback?}。
 * 一类节点都没注册时才渲染 fallback；正常情况下走 React Flow 本体。
 */
export function CanvasHost({
  flow,
  scene,
  nodes,
  fallback,
}: {
  flow: FlowId
  scene: ScenePackage
  nodes?: CanvasNode[]
  fallback?: ReactNode
}) {
  useRegistryVersion()
  if (!getCanvasNode('motor')) return <>{fallback ?? null}</>
  return (
    <ReactFlowProvider>
      <CanvasInner flow={flow} scene={scene} nodes={nodes} />
    </ReactFlowProvider>
  )
}
