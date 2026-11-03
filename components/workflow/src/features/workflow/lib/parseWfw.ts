/**
 * .wfw 解析器。
 *
 * 文件格式（来自 src-tauri/src/integrated_test_system/workflow_commands.rs）：
 *   外层可选 gzip（魔数 0x1f 0x8b），解压后是 UTF-8 JSON，形如
 *   { formatVersion, metadata, definition: { nodes, edges, variables, ports?,
 *     curveGroups?, curveBindings? } }
 *   节点自身已是 React Flow 形状：{ id, type, position, data }，
 *   参数全部平铺在 data 里（label 之外的字段）。
 */
import type {
  ParamValue,
  WorkflowEdge,
  WorkflowMeta,
  WorkflowModel,
  WorkflowNode,
} from '../types'
import { NODE_TYPE_LABEL, groupOf } from './nodeCatalog'

const GZIP_MAGIC = [0x1f, 0x8b]

export function isGzip(buffer: ArrayBuffer): boolean {
  const head = new Uint8Array(buffer, 0, Math.min(2, buffer.byteLength))
  return head.length === 2 && head[0] === GZIP_MAGIC[0] && head[1] === GZIP_MAGIC[1]
}

function decodeText(buffer: ArrayBuffer): string {
  // utf-8 解码器会把 BOM 保留为 U+FEFF，JSON.parse 不接受，这里显式剥掉。
  const text = new TextDecoder('utf-8').decode(buffer)
  return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text
}

async function gunzip(buffer: ArrayBuffer): Promise<ArrayBuffer> {
  if (typeof DecompressionStream === 'undefined') {
    throw new Error('当前运行环境不支持 DecompressionStream，无法解压 gzip 格式的 .wfw')
  }
  const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream('gzip'))
  return new Response(stream).arrayBuffer()
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function parseNode(raw: unknown, index: number): WorkflowNode {
  const node = asRecord(raw)
  const data = asRecord(node.data)
  const type = typeof node.type === 'string' ? node.type : '_deprecated'

  const { label, embeddedWorkflow, ...rest } = data
  const position = asRecord(node.position)
  const hasPosition = typeof position.x === 'number' && typeof position.y === 'number'

  const parsed: WorkflowNode = {
    id: typeof node.id === 'string' ? node.id : `node-${index}`,
    type,
    label:
      typeof label === 'string' && label.length > 0
        ? label
        : (NODE_TYPE_LABEL[type] ?? type),
    group: groupOf(type),
    params: rest as Record<string, ParamValue>,
    position: hasPosition ? { x: position.x as number, y: position.y as number } : null,
  }

  // subworkflow 节点把整个被引用的工作流内联在 data.embeddedWorkflow 里，
  // 递归解析后挂到 node.embedded，供「下钻查看子流程」使用。
  if (embeddedWorkflow) {
    const inner = asRecord(embeddedWorkflow)
    if (inner.definition || inner.nodes) {
      try {
        parsed.embedded = buildModel(inner, false)
      } catch {
        // 内嵌结构损坏不应连累主流程渲染。
      }
    }
  }

  return parsed
}

function parseEdge(raw: unknown, index: number): WorkflowEdge | null {
  const edge = asRecord(raw)
  if (typeof edge.source !== 'string' || typeof edge.target !== 'string') return null
  return {
    id: typeof edge.id === 'string' ? edge.id : `edge-${index}`,
    source: edge.source,
    target: edge.target,
    sourceHandle: typeof edge.sourceHandle === 'string' ? edge.sourceHandle : undefined,
    targetHandle: typeof edge.targetHandle === 'string' ? edge.targetHandle : undefined,
  }
}

function parseMeta(raw: unknown, formatVersion: string, compressed: boolean): WorkflowMeta {
  const m = asRecord(raw)
  const version = asRecord(m.version)
  const versionText =
    typeof version.major === 'number'
      ? `${version.major}.${version.minor ?? 0}.${version.patch ?? 0}`
      : undefined
  return {
    id: typeof m.id === 'string' ? m.id : undefined,
    name: typeof m.name === 'string' ? m.name : '未命名工作流',
    description: typeof m.description === 'string' ? m.description : undefined,
    author: typeof m.author === 'string' ? m.author : undefined,
    createdAt: typeof m.createdAt === 'string' ? m.createdAt : undefined,
    updatedAt: typeof m.updatedAt === 'string' ? m.updatedAt : undefined,
    version: versionText,
    tags: Array.isArray(m.tags) ? m.tags.filter((t): t is string => typeof t === 'string') : [],
    category: typeof m.category === 'string' ? m.category : undefined,
    isTemplate: m.isTemplate === true,
    isSubsystem: m.isSubsystem === true,
    formatVersion,
    compressed,
  }
}

function buildModel(root: Record<string, unknown>, compressed: boolean): WorkflowModel {
  // definition 缺失时兼容把 nodes/edges 直接放在顶层的内嵌工作流写法。
  const definition = root.definition ? asRecord(root.definition) : root
  const rawNodes = Array.isArray(definition.nodes) ? definition.nodes : []
  const rawEdges = Array.isArray(definition.edges) ? definition.edges : []

  const nodes = rawNodes.map(parseNode)
  const known = new Set(nodes.map((n) => n.id))
  const edges = rawEdges
    .map(parseEdge)
    .filter((e): e is WorkflowEdge => e !== null)
    // 丢弃指向不存在节点的悬空连线，否则 React Flow 会静默吞掉整张图。
    .filter((e) => known.has(e.source) && known.has(e.target))

  return {
    nodes,
    edges,
    variables: Array.isArray(definition.variables) ? definition.variables : [],
    meta: parseMeta(
      root.metadata,
      typeof root.formatVersion === 'string' ? root.formatVersion : 'unknown',
      compressed,
    ),
  }
}

/**
 * 解析未压缩的 .wfw。若传入 gzip 数据会抛错，请改用 parseWfwAsync。
 */
export function parseWfw(buffer: ArrayBuffer): WorkflowModel {
  if (isGzip(buffer)) {
    throw new Error('该 .wfw 为 gzip 压缩格式，请使用 parseWfwAsync()')
  }
  return buildModel(asRecord(JSON.parse(decodeText(buffer))), false)
}

/** 解析任意 .wfw，自动识别并解压 gzip。 */
export async function parseWfwAsync(buffer: ArrayBuffer): Promise<WorkflowModel> {
  const compressed = isGzip(buffer)
  const payload = compressed ? await gunzip(buffer) : buffer
  return buildModel(asRecord(JSON.parse(decodeText(payload))), compressed)
}

/** 导出为格式化 JSON 字符串。 */
export function exportJson(model: WorkflowModel): string {
  return JSON.stringify(model, null, 2)
}
