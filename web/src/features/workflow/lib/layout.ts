/**
 * 自动布局。
 *
 * 原文件自带 position，但坐标是人工拖拽的结果，跨文件疏密不一、常有重叠，
 * 直接用会得到一张乱图，所以统一重排。
 *
 * 峰岹的测试工作流绝大多数是「一条长链 + 一个公共异常出口」的形状：
 * 单纯用 dagre 的左→右分层会摊成一条几千像素宽、几十像素高的细带，
 * 在 16:9 视口里要么看不清、要么要一直横向平移。因此对链式图额外做一次
 * 蛇形折行（serpentine），把长链按行折叠成接近视口比例的矩形。
 */
import dagre from 'dagre'
import type { WorkflowModel } from '../types'

export const NODE_WIDTH = 172
export const NODE_HEIGHT = 58

export interface LayoutOptions {
  /** 同层节点间距。 */
  nodeSep?: number
  /** 层间距。 */
  rankSep?: number
  direction?: 'LR' | 'TB'
  /** 关掉蛇形折行，强制纯 dagre 结果。 */
  wrap?: boolean
  /** 折行的目标宽高比，默认 16:9。 */
  aspect?: number
}

export type Positions = Record<string, { x: number; y: number }>

/** 触发折行的最小层数——短流程直接横排更好读。 */
const WRAP_MIN_RANKS = 9
/** 每层节点数超过这个值就不是链式图，不折行。 */
const WRAP_MAX_PER_RANK = 2

export function layoutModel(model: WorkflowModel, options: LayoutOptions = {}): Positions {
  const { nodeSep = 34, rankSep = 64, direction = 'LR', wrap = true, aspect = 16 / 9 } = options

  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: direction, nodesep: nodeSep, ranksep: rankSep, marginx: 24, marginy: 24 })
  g.setDefaultEdgeLabel(() => ({}))

  for (const node of model.nodes) {
    g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT })
  }
  for (const edge of model.edges) {
    // 自环会让 dagre 的分层退化，排版时忽略，渲染时仍保留。
    if (edge.source !== edge.target) g.setEdge(edge.source, edge.target)
  }

  dagre.layout(g)

  const raw: Positions = {}
  for (const node of model.nodes) {
    const laid = g.node(node.id)
    raw[node.id] = laid
      ? { x: laid.x - NODE_WIDTH / 2, y: laid.y - NODE_HEIGHT / 2 }
      : { x: 0, y: 0 }
  }

  if (!wrap || direction !== 'LR') return raw

  const wrapped = serpentine(raw, { nodeSep, rankSep, aspect })
  return wrapped ?? raw
}

/**
 * 把 dagre 的层序重排成蛇形网格。返回 null 表示这张图不适合折行。
 */
function serpentine(
  raw: Positions,
  opts: { nodeSep: number; rankSep: number; aspect: number },
): Positions | null {
  // 按 x 聚成层。dagre 同层的 x 完全相同，直接用字符串键分桶。
  const buckets = new Map<number, string[]>()
  for (const [id, p] of Object.entries(raw)) {
    const bucket = buckets.get(p.x)
    if (bucket) bucket.push(id)
    else buckets.set(p.x, [id])
  }

  const ranks = [...buckets.entries()].sort((a, b) => a[0] - b[0]).map(([, ids]) => ids)
  if (ranks.length < WRAP_MIN_RANKS) return null
  if (ranks.some((r) => r.length > WRAP_MAX_PER_RANK)) return null

  // 每层内部按原 y 保持上下顺序。
  for (const rank of ranks) rank.sort((a, b) => raw[a].y - raw[b].y)

  const cellW = NODE_WIDTH + opts.rankSep
  const tallest = Math.max(...ranks.map((r) => r.length))
  const cellH = tallest * NODE_HEIGHT + (tallest - 1) * opts.nodeSep + opts.rankSep

  // 解 perRow²·cellW / (ranks/perRow·cellH) = aspect
  const perRow = Math.max(
    2,
    Math.min(ranks.length, Math.round(Math.sqrt((opts.aspect * ranks.length * cellH) / cellW))),
  )
  if (perRow >= ranks.length) return null

  const out: Positions = {}
  ranks.forEach((ids, i) => {
    const row = Math.floor(i / perRow)
    const indexInRow = i % perRow
    // 奇数行反向，让上一行末尾与下一行开头在视觉上相邻。
    const col = row % 2 === 0 ? indexInRow : perRow - 1 - indexInRow
    const x = col * cellW
    const blockH = ids.length * NODE_HEIGHT + (ids.length - 1) * opts.nodeSep
    const yTop = row * cellH + (cellH - opts.rankSep - blockH) / 2
    ids.forEach((id, k) => {
      out[id] = { x, y: yTop + k * (NODE_HEIGHT + opts.nodeSep) }
    })
  })
  return out
}
