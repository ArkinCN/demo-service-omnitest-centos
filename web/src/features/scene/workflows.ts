/* ===========================================================================
   工作流的统一取数口。

   两个场景包的工作流从两个地方来，画布组件本身不用改：

   - 散热风扇包：客户真实的 68 个 `.wfw` 二进制/明文文件，放在 public/data/wfw/**，
     索引是 public/data/workflows.json，要经 parseWfw 解析。
   - 玻璃升降器包：场景包自带的 assets/workflows/*.json，本身已经是画布的统一内部
     模型（{nodes, edges, meta, variables}），直接喂给 WorkflowCanvas，不用解析。

   `workflowSource`（归一化时按 workflows.model_format 判定）决定走哪一条，
   调用方只认这里导出的两个函数。
   =========================================================================== */
import { listWorkflows, loadWorkflow, registerNodeGroups, NODE_TYPE_GROUP } from '../workflow'
import type { NodeGroupId, WorkflowIndexEntry, WorkflowModel } from '../workflow'
import { fetchJson } from '../shared/fetchJson'
import type { RawPack } from './pack'

/** 列表条目在两种来源下的统一形状 */
export interface WfEntry {
  id: string
  name: string
  group: string
  voltage: string
  /** 供加载用：.wfw 走索引条目，包内 JSON 走相对包根的路径 */
  entry?: WorkflowIndexEntry
  assetPath?: string
  nodeCount: number
  edgeCount: number
  purpose?: string
  /** 这条是示例占位，不是客户真实文件 */
  placeholder?: boolean
}

/**
 * 包二的节点 `group` 是本包自定义的中文抽象分组（设置 / 激励 / 采集 / 判定 /
 * 控制流 / 数据处理），不是画布组件 NodeGroupId 枚举里的成员。
 *
 * 处理办法是把包自己声明的分组原样注册进画布的分组表——分组名照包自己写的显示，
 * 只借用同色相的明度档做配色。不能把它映射成峰岹的分组 id，那样画布上「开始」
 * 节点会被标成「数据处理」，是错的标签。包没声明分组的，落回按节点类型查表，
 * 还查不到就是 unknown（显示「未识别」），照常渲染。
 */
const PALETTE_ORDER: NodeGroupId[] = [
  'basic',
  'hid_presets',
  'debugging',
  'logic',
  'data',
  'verify',
  'instruments',
  'report',
]

const registered = new Set<string>()

function groupMapperOf(pack: RawPack): (raw: string, type: string) => NodeGroupId {
  const declared = Object.keys(pack.workflows.node_groups ?? {})
  if (declared.length && !registered.has(pack.scene.id)) {
    registered.add(pack.scene.id)
    registerNodeGroups(
      declared.map((name, i) => ({
        id: name,
        label: name,
        paletteFrom: PALETTE_ORDER[i % PALETTE_ORDER.length],
      })),
    )
  }
  const known = new Set(declared)
  return (raw, type) =>
    (known.has(raw) ? (raw as NodeGroupId) : undefined) ?? NODE_TYPE_GROUP[type] ?? 'unknown'
}

const assetCache = new Map<string, WorkflowModel>()

/** 列出当前场景包能用的工作流 */
export async function listPackWorkflows(pack: RawPack): Promise<WfEntry[]> {
  if (pack.caps.workflowSource === 'pack-assets') {
    return pack.workflows.workflows.map((w) => ({
      id: w.id,
      name: w.name,
      group: w.group.name,
      voltage: w.voltage_level_name || w.voltage_level || '—',
      // file_path 是**包根之下的相对路径**（形如 ./assets/xxx.wfw，2026-09-23
      // 由 Linux 绝对路径改来）。这里靠 split('/assets/') 取后半段再拼包前缀，
      // 所以场景包里的 file_path **必须保留 /assets/ 分隔符**，改动前先确认。
      // 取不到后半段（包外登记的条目）就给空串，调用方会跳过它。
      assetPath: w.file_path.split('/assets/')[1] ? `assets/${w.file_path.split('/assets/')[1]}` : '',
      nodeCount: w.node_count,
      edgeCount: w.edge_count,
      purpose: w.purpose,
      placeholder: w._placeholder === true,
    }))
  }

  const entries = await listWorkflows({ baseUrl: '/data' })
  const meta = new Map(pack.workflows.workflows.map((w) => [w.name, w]))
  return entries.map((e) => {
    const m = meta.get(e.name)
    return {
      id: e.id,
      name: e.name,
      group: m?.group.name ?? e.group,
      voltage: e.voltage,
      entry: e,
      nodeCount: e.nodeCount,
      edgeCount: e.edgeCount,
      purpose: m?.purpose,
      placeholder: m?._placeholder === true,
    }
  })
}

/** 读一条工作流，产出画布的统一内部模型 */
export async function loadPackWorkflow(pack: RawPack, w: WfEntry): Promise<WorkflowModel | null> {
  if (w.entry) return loadWorkflow(w.entry, { baseUrl: '/data' })
  if (!w.assetPath) return null

  const url = pack.base + w.assetPath
  const hit = assetCache.get(url)
  if (hit) return hit

  // 2026-10-08：改用统一 fetchJson（原 force-cache 会读旧副本，见 fetchJson 模块头）
  const raw = await fetchJson<{
    nodes: { id: string; type: string; label: string; group: string; params?: Record<string, unknown>; position?: { x: number; y: number } | null }[]
    edges: { id: string; source: string; target: string; sourceHandle?: string; targetHandle?: string }[]
    meta?: Record<string, unknown>
    variables?: unknown[]
  }>(url)
  if (!raw) return null
  const toGroup = groupMapperOf(pack)
  const model: WorkflowModel = {
    nodes: (raw.nodes ?? []).map((n) => ({
      id: n.id,
      type: n.type,
      label: n.label || n.type,
      group: toGroup(n.group, n.type),
      params: n.params ?? {},
      // 包内示例的坐标全是 (0,0)，等于没给，交给自动布局
      position: n.position && (n.position.x || n.position.y) ? n.position : null,
    })),
    edges: (raw.edges ?? []).map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.sourceHandle,
      targetHandle: e.targetHandle,
    })),
    meta: {
      id: String(raw.meta?.id ?? w.id),
      name: String(raw.meta?.name ?? w.name),
      tags: (raw.meta?.tags as string[] | undefined) ?? [],
      category: raw.meta?.category as string | undefined,
      description: raw.meta?.note as string | undefined,
      isTemplate: raw.meta?.isTemplate === true,
      isSubsystem: raw.meta?.isSubsystem === true,
      formatVersion: String(raw.meta?.formatVersion ?? '1.0.0'),
      compressed: false,
    },
    variables: raw.variables ?? [],
  }
  assetCache.set(url, model)
  return model
}
