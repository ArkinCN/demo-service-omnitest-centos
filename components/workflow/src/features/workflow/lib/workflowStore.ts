/**
 * 工作流索引与文件加载。
 *
 * 数据由 scripts/buildIndex.mjs 预生成到 public/data/ 下，
 * 集成到宿主工程时把 baseUrl 改成宿主的静态资源前缀即可。
 */
import type { WorkflowIndexEntry, WorkflowModel } from '../types'
import { parseWfwAsync } from './parseWfw'

export interface StoreOptions {
  /** 静态资源前缀，默认 'data'（相对站点根）。 */
  baseUrl?: string
}

interface IndexFile {
  generatedAt: string
  count: number
  workflows: WorkflowIndexEntry[]
}

const modelCache = new Map<string, WorkflowModel>()

/** 读取索引 JSON。 */
export async function listWorkflows(options: StoreOptions = {}): Promise<WorkflowIndexEntry[]> {
  const base = options.baseUrl ?? 'data'
  const res = await fetch(`${base}/workflows.json`)
  if (!res.ok) throw new Error(`读取工作流索引失败：HTTP ${res.status}`)
  const json = (await res.json()) as IndexFile
  return json.workflows
}

/** 按索引条目加载并解析 .wfw，结果带内存缓存。 */
export async function loadWorkflow(
  entry: WorkflowIndexEntry,
  options: StoreOptions = {},
): Promise<WorkflowModel> {
  const cached = modelCache.get(entry.file)
  if (cached) return cached

  const base = options.baseUrl ?? 'data'
  // 路径里有中文与空格，必须逐段编码。
  const encoded = entry.file.split('/').map(encodeURIComponent).join('/')
  const res = await fetch(`${base}/wfw/${encoded}`)
  if (!res.ok) throw new Error(`读取 ${entry.name} 失败：HTTP ${res.status}`)

  const model = await parseWfwAsync(await res.arrayBuffer())
  modelCache.set(entry.file, model)
  return model
}

/** 按业务分组折叠列表用。 */
export function groupEntries(
  entries: WorkflowIndexEntry[],
): { group: string; items: WorkflowIndexEntry[] }[] {
  const map = new Map<string, WorkflowIndexEntry[]>()
  for (const e of entries) {
    const bucket = map.get(e.group)
    if (bucket) bucket.push(e)
    else map.set(e.group, [e])
  }
  return [...map.entries()]
    .sort((a, b) => a[0].localeCompare(b[0], 'zh'))
    .map(([group, items]) => ({
      group,
      items: items.sort((a, b) => a.name.localeCompare(b.name, 'zh')),
    }))
}
