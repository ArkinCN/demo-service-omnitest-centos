import { useCallback, useRef, useState } from 'react'
import { PenTool } from 'lucide-react'
import { NodeCard } from './NodeCard'
import { ToolRail } from './ToolRail'
import { SEED_NODES, SEED_EDGES, type CanvasNodeJSON, type RailItem } from './model'

/**
 * 方案 B · 自研：一层 transform 视口 + SVG 连线。
 * 这里刻意只实现"滚轮缩放 / 拖拽平移 / 拖动节点 / 拖入新节点 / 复位"这五件事，
 * 用来度量不依赖库要自己补多少代码。
 */

const NODE_W = 188
const NODE_H = 104

interface View { x: number; y: number; k: number }
const INIT: View = { x: 60, y: 20, k: 0.86 }

function edgePath(a: CanvasNodeJSON, b: CanvasNodeJSON, kind: 'physical' | 'data') {
  const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2
  const x2 = b.x, y2 = b.y + NODE_H / 2
  if (kind === 'physical') {
    const mx = (x1 + x2) / 2
    const r = 8
    const dy = Math.sign(y2 - y1) || 1
    if (Math.abs(y2 - y1) < 2) return `M${x1} ${y1} L${x2} ${y2}`
    // 正交折线，拐角圆化
    return `M${x1} ${y1} L${mx - r} ${y1} Q${mx} ${y1} ${mx} ${y1 + r * dy} L${mx} ${y2 - r * dy} Q${mx} ${y2} ${mx + r} ${y2} L${x2} ${y2}`
  }
  const c = Math.max(40, Math.abs(x2 - x1) * 0.45)
  return `M${x1} ${y1} C${x1 + c} ${y1} ${x2 - c} ${y2} ${x2} ${y2}`
}

export function SvgSpike() {
  const [nodes, setNodes] = useState<CanvasNodeJSON[]>(SEED_NODES)
  const [view, setView] = useState<View>(INIT)
  const [sel, setSel] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [panning, setPanning] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const pan = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null)
  const nodeDrag = useRef<{ id: string; dx: number; dy: number } | null>(null)
  const seq = useRef(0)

  const toWorld = useCallback((cx: number, cy: number) => {
    const r = wrap.current!.getBoundingClientRect()
    return { x: (cx - r.left - view.x) / view.k, y: (cy - r.top - view.y) / view.k }
  }, [view])

  /* 滚轮缩放：以指针为锚点，外框尺寸不变 */
  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    const r = wrap.current!.getBoundingClientRect()
    const px = e.clientX - r.left, py = e.clientY - r.top
    setView((v) => {
      const k = Math.min(2.5, Math.max(0.35, v.k * Math.exp(-e.deltaY * 0.0016)))
      return { k, x: px - ((px - v.x) / v.k) * k, y: py - ((py - v.y) / v.k) * k }
    })
  }

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return
    const t = (e.target as HTMLElement).closest('[data-node-id]') as HTMLElement | null
    if (t) {
      const id = t.dataset.nodeId!
      const n = nodes.find((x) => x.id === id)!
      const w = toWorld(e.clientX, e.clientY)
      nodeDrag.current = { id, dx: w.x - n.x, dy: w.y - n.y }
      setSel(id)
    } else {
      pan.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }
      setPanning(true)
      setSel(null)
    }
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }

  const onPointerMove = (e: React.PointerEvent) => {
    if (nodeDrag.current) {
      const d = nodeDrag.current
      const w = toWorld(e.clientX, e.clientY)
      setNodes((ns) => ns.map((n) => (n.id === d.id ? { ...n, x: w.x - d.dx, y: w.y - d.dy } : n)))
    } else if (pan.current) {
      const p = pan.current
      setView((v) => ({ ...v, x: p.vx + (e.clientX - p.x), y: p.vy + (e.clientY - p.y) }))
    }
  }

  const onPointerUp = () => { nodeDrag.current = null; pan.current = null; setPanning(false) }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false)
    const raw = e.dataTransfer.getData('application/x-canvas-node')
    if (!raw) return
    const it = JSON.parse(raw) as RailItem
    const w = toWorld(e.clientX, e.clientY)
    seq.current += 1
    const id = `new-${seq.current}`
    setNodes((ns) => ns.concat({ id, ...it, x: w.x - NODE_W / 2, y: w.y - NODE_H / 2 }))
    setSel(id)
  }

  const byId = new Map(nodes.map((n) => [n.id, n]))
  const pct = Math.round(view.k * 100)
  const zoomTo = (f: number) => setView((v) => {
    const r = wrap.current!.getBoundingClientRect()
    const px = r.width / 2, py = r.height / 2
    const k = Math.min(2.5, Math.max(0.35, v.k * f))
    return { k, x: px - ((px - v.x) / v.k) * k, y: py - ((py - v.y) / v.k) * k }
  })

  return (
    <div className="panel" data-testid="panel">
      <div className="panel-head">
        <PenTool size={17} strokeWidth={1.9} />
        方案 B · 自研 transform 视口 + SVG 连线
        <span className="meta">C 区 1180 × 620 · 外框固定</span>
      </div>
      <div className="panel-body">
        <div
          className="canvas-wrap"
          data-testid="canvas"
          ref={wrap}
          style={{
            overflow: 'hidden', touchAction: 'none',
            cursor: panning ? 'grabbing' : 'grab',
            background: 'radial-gradient(circle, #dfe6e1 1px, transparent 1px) 0 0 / 16px 16px, var(--tp-bg)',
          }}
          onWheel={onWheel}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onDoubleClick={() => setView(INIT)}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
        >
          <div style={{
            position: 'absolute', left: 0, top: 0, width: 0, height: 0,
            transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})`,
            transformOrigin: '0 0',
          }}>
            <svg style={{ position: 'absolute', left: 0, top: 0, width: 2000, height: 1200, overflow: 'visible', pointerEvents: 'none' }}>
              {SEED_EDGES.map((e) => {
                const a = byId.get(e.from), b = byId.get(e.to)
                if (!a || !b) return null
                return (
                  <g key={e.id}>
                    <path
                      d={edgePath(a, b, e.kind)} fill="none"
                      stroke={e.kind === 'physical' ? '#2e5e45' : '#a8c5b5'}
                      strokeWidth={e.kind === 'physical' ? 1.5 : 1}
                      strokeDasharray={e.kind === 'data' ? '6 4' : undefined}
                    />
                    {e.label ? (
                      <text
                        x={(a.x + NODE_W + b.x) / 2} y={(a.y + b.y) / 2 + NODE_H / 2 - 6}
                        textAnchor="middle" fontSize="10" fill="var(--tp-text-3)"
                        stroke="#fff" strokeWidth="3" paintOrder="stroke"
                      >{e.label}</text>
                    ) : null}
                  </g>
                )
              })}
            </svg>
            {nodes.map((n) => (
              <div
                key={n.id} data-node-id={n.id}
                style={{ position: 'absolute', left: n.x, top: n.y, cursor: 'move' }}
              >
                <NodeCard data={n} selected={sel === n.id} />
              </div>
            ))}
          </div>
          <div className="legend">
            <span><i />物理接线</span>
            <span><i className="dash" />数据链路</span>
            <span>滚轮缩放 · 空白拖拽平移 · 双击复位</span>
          </div>
          <div className="zoombar" data-testid="zoombar">
            <button type="button" onClick={() => zoomTo(1 / 1.2)} aria-label="缩小">−</button>
            <span className="pct" data-testid="zoom-pct">{pct}%</span>
            <button type="button" onClick={() => zoomTo(1.2)} aria-label="放大">+</button>
            <button type="button" onClick={() => setView(INIT)}>复位</button>
          </div>
          {dragOver ? <div className="drophint">松手放置节点</div> : null}
        </div>
        <ToolRail />
      </div>
    </div>
  )
}
