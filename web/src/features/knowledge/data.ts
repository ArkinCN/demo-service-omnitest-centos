/* ===========================================================================
   知识库数据取数层。

   第三轮把知识库从流程 1 降级为模块，原 src/data/loadScene.ts 的 kbFlow()
   已下架，知识库的数据一律从这里取。

   ⚠️ 2026-09-24 起**取数改走服务端**（主文档阶段 3 验收 6）：
   此前这里直接 fetch 场景包的 documents.json + experience.json，三轴分类
   只做在前端，服务端的 kb_entries 表形同虚设——CRUD 改的是表、列表读的是
   JSON，两套并存必然漂移（项目里已因这类双源吃过亏）。现在定死：
       **库是唯一权威源，场景包只作导入源**（导入脚本
       `c/backend/scripts/import_kb_from_scenes.py`）。
   场景包 index.json 这路保留，只用来把 sceneId 反查成三级中文名，
   因为服务端按归属中文名过滤，不带 sceneId 字段。

   切后计数必须与切前一致（散热风扇包 85 条、用途轴 8/12/65），
   有脚本守着：`python scripts/verify_kb_counts.py`（双向比对，不是靠眼睛）。

   ⚠️ 取数失败**不回退静态 JSON**。回退等于又变回两套源，而且人看不出
   自己看的是旧数据。失败就报出来，界面上写明原因。
   =========================================================================== */
import { useEffect, useSyncExternalStore } from 'react'
import type {
  FlowId,
  KnowledgeFilter,
  KnowledgeOrigin,
  KnowledgeUsage,
} from '../../data/types'
import { useAppStore } from '../../state/useAppStore'
import { fetchJson } from '../shared/fetchJson'

/** 一条知识条目。三轴取值同时挂在同一条上。 */
export interface KnowledgeEntry {
  id: string
  title: string
  /** 用途轴 */
  usage: KnowledgeUsage
  /** 来源轴 */
  origin: KnowledgeOrigin
  /** 归属轴：三级路径 [场景, 子类, 产品类型] */
  owner: [string, string, string]
  /** 证据级，例如「台架实测数据」「规程条款」「未验证」 */
  evidenceLevel?: string
  summary?: string
  /** 本条会被哪些流程调用，供 B 区抽屉按流程过滤 */
  usedBy?: FlowId[]

  /* --------- 以下为 W2 新增的可选字段，只增不改，老的读法一律照旧 --------- */
  /** 06a 体系里的二级归类，例如「B1 调试规程与纪律」 */
  usageClass?: string
  /** 用途轴落位拿不准，需人工复核 */
  needsReview?: boolean
  /** 场景包登记的材料类型，例如「调试规程（dc-skills）」 */
  docType?: string
  /** 转化状态的中文显示名 */
  conversion?: string
  converted?: boolean
  sizeBytes?: number | null
  /** 源文件绝对路径或公开链接，供详情栏给出可独立定位的全名 */
  path?: string | null
  url?: string
  note?: string
  /** `_status`：这条为什么还不算已核实 */
  status?: string
  /** 经验条目的四段正文 */
  case?: { symptom: string; cause: string; action: string; result: string }
  /** 知识库流水线补上的页数与切片数（只有已过流水线的文档才有） */
  pages?: number | null
  chunks?: number
}

/** 三轴各取值的条目计数，筛选器每一轴都要显示 */
export interface KnowledgeCounts {
  total: number
  usage: Record<KnowledgeUsage, number>
  origin: Record<KnowledgeOrigin, number>
}

const EMPTY_COUNTS: KnowledgeCounts = {
  total: 0,
  usage: { spec: 0, requirement: 0, process: 0 },
  origin: { doc: 0, experience: 0 },
}

/* --------------------------------------------------------------- 原始 JSON 型 */

interface RawDoc {
  id: string
  type: string
  title: string
  path: string | null
  size_bytes: number | null
  exists: boolean
  used_in_flows: string[]
  conversion_status: string
  conversion_status_label?: string
  url?: string
  note?: string
  _status?: string
  usage?: string
  usage_class?: string
  usage_review?: string
}

interface RawExp {
  id: string
  symptom: string
  cause: string
  action: string
  result: string
  tags: Record<string, unknown>
  evidence_level: string
  _status?: string
  usage?: string
  usage_class?: string
  usage_review?: string
}

interface CatalogNode {
  id: string
  label: string
  sceneId?: string
  children?: CatalogNode[]
}

/* ------------------------------------------------------------------ 取值映射 */

/**
 * 用途轴的中文三值 → 英文码的映射**已移到服务端**（导入脚本
 * `import_kb_from_scenes.py` 的 USAGE_CODE，口径与这里原来的完全一致）。
 * 前端只做三值校验，不再自己翻译一遍——两处翻译迟早会不一致。
 */

/** 场景包的流程编号 ↔ 壳层流程标识。F1 是已下架的知识库流程，不落任何流程页 */
const FLOW_OF_CODE: Record<string, FlowId> = {
  F2: 'init',
  F3: 'req',
  F4: 'run',
  F5: 'tune',
  F6: 'report',
}

const flowsOf = (labels: string[]): FlowId[] => {
  const out: FlowId[] = []
  for (const s of labels) {
    const f = FLOW_OF_CODE[s.slice(0, 2)]
    if (f && !out.includes(f)) out.push(f)
  }
  return out
}

async function getJson<T>(url: string): Promise<T | null> {
  // 2026-10-08：改用统一 fetchJson（原 force-cache 会读旧副本，见 fetchJson 模块头）
  return fetchJson<T>(url)
}

/** 在三级目录里按 sceneId 反查出这一条的三级中文名 */
function ownerOf(catalog: CatalogNode[] | undefined, sceneId: string): [string, string, string] {
  for (const a of catalog ?? [])
    for (const b of a.children ?? [])
      for (const c of b.children ?? [])
        if (c.sceneId === sceneId) return [a.label, b.label, c.label]
  const parts = sceneId.split('.')
  return [parts[0] ?? sceneId, parts[1] ?? '', parts[2] ?? '']
}

/* ------------------------------------------------------------------ 取数入口 */

const cache = new Map<string, Promise<KnowledgeEntry[]>>()
const ready = new Map<string, KnowledgeEntry[]>()
/** 取数失败的原因，按场景包存。空表示这一包取数正常。 */
const errors = new Map<string, string>()

/* ------------------------------------------------------------ 服务端条目型 */

/** 后端 KbEntryRead 的形状（app/schemas/kb_entry.py）。字段一律下划线命名。 */
interface ServerEntry {
  entry_key: string
  version: number
  origin: string
  title: string
  usage: string
  owner_l1: string
  owner_l2: string
  owner_l3: string
  content: Record<string, unknown>
  status: string
  change_reason: string
}

/** content 里存的是场景包里的原始条目，按 origin 分两种形状 */
type Content = Partial<RawDoc> & Partial<RawExp> & { pages?: number | null; chunks?: number }

const USAGE_OK: KnowledgeUsage[] = ['spec', 'requirement', 'process']

/** 服务端三轴值 → 前端枚举；不在三值内时回落 process 并标待复核（与导入脚本同口径） */
const usageFromServer = (v: string): [KnowledgeUsage, boolean] =>
  USAGE_OK.includes(v as KnowledgeUsage) ? [v as KnowledgeUsage, false] : ['process', true]

function toEntry(e: ServerEntry): KnowledgeEntry {
  const c = (e.content ?? {}) as Content
  const [usage, fallback] = usageFromServer(e.usage)
  const owner: [string, string, string] = [e.owner_l1, e.owner_l2, e.owner_l3]
  const isDoc = e.origin === 'doc'
  return {
    id: e.entry_key,
    title: e.title,
    usage,
    origin: isDoc ? 'doc' : 'experience',
    owner,
    usageClass: c.usage_class,
    needsReview: fallback || !!c.usage_review,
    docType: c.type,
    conversion: c.conversion_status_label ?? c.conversion_status,
    converted: !['not_converted', '未转化', '未取得'].includes(c.conversion_status ?? ''),
    sizeBytes: c.size_bytes ?? null,
    path: c.exists ? (c.path ?? null) : null,
    url: c.url,
    note: c.note,
    status: c._status,
    usedBy: isDoc
      ? flowsOf(c.used_in_flows ?? [])
      : flowsOf(c.tags?.flow ? [String(c.tags.flow)] : []),
    summary: isDoc ? c.note : c.action,
    evidenceLevel: c.evidence_level,
    pages: c.pages ?? null,
    chunks: c.chunks,
    case: isDoc
      ? undefined
      : {
          symptom: c.symptom ?? e.title,
          cause: c.cause ?? '',
          action: c.action ?? '',
          result: c.result ?? '',
        },
  }
}

/**
 * 从服务端取某个场景包下的全部知识条目。
 *
 * 归属用三级中文名过滤：库里两个场景包是并存的，只按 l3 过滤才不会把
 * 另一个产品的条目算进来（导入时已按「场景包:原 id」做 key，不会串号，
 * 但过滤仍要显式带上归属）。
 */
export function loadKnowledge(sceneId: string): Promise<KnowledgeEntry[]> {
  const hit = cache.get(sceneId)
  if (hit) return hit
  const task = (async () => {
    // 服务端按归属中文名过滤，所以先把 sceneId 反查成三级名
    const index = await getJson<{ catalog: CatalogNode[] }>('/scenes/index.json')
    const owner = ownerOf(index?.catalog, sceneId)

    const r = await fetch(
      `/api/kb/entries?owner=${encodeURIComponent(owner[2])}&limit=500`,
      { headers: { 'Content-Type': 'application/json' } },
    )
    if (!r.ok) throw new Error(`知识库取数失败 HTTP ${r.status}`)
    const body = (await r.json()) as {
      success: boolean
      message: string
      data: { items: ServerEntry[] }
    }
    if (!body.success) throw new Error(body.message || '知识库取数失败')

    const out = (body.data?.items ?? []).map(toEntry)
    ready.set(sceneId, out)
    errors.delete(sceneId)
    listeners.forEach((l) => l())
    return out
  })().catch((e: unknown) => {
    // 不回退静态 JSON：那等于又变回两套源，而且人看不出自己在看旧数据。
    // 留痕后向上抛，由 useKnowledge 把错误交给界面显示。
    const msg = e instanceof Error ? e.message : String(e)
    errors.set(sceneId, msg)
    console.error('[knowledge] 服务端取数失败：', msg)
    listeners.forEach((l) => l())
    throw e
  })
  cache.set(sceneId, task)
  return task
}

/** 按三轴筛选。 */
export function filterKnowledge(
  entries: KnowledgeEntry[],
  f: KnowledgeFilter,
): KnowledgeEntry[] {
  return entries.filter(
    (e) =>
      (f.usage.length === 0 || f.usage.includes(e.usage)) &&
      (f.origin.length === 0 || f.origin.includes(e.origin)) &&
      (f.owner.length === 0 || f.owner.every((o) => e.owner.includes(o))),
  )
}

/** 三轴计数。 */
export function countKnowledge(entries: KnowledgeEntry[]): KnowledgeCounts {
  const c: KnowledgeCounts = {
    total: entries.length,
    usage: { spec: 0, requirement: 0, process: 0 },
    origin: { doc: 0, experience: 0 },
  }
  for (const e of entries) {
    c.usage[e.usage] += 1
    c.origin[e.origin] += 1
  }
  return c
}

/** 某条流程实际会调用的知识条目，供 B 区顶部抽屉用。 */
export function knowledgeForFlow(entries: KnowledgeEntry[], flow: FlowId): KnowledgeEntry[] {
  return entries.filter((e) => !e.usedBy || e.usedBy.includes(flow))
}

/**
 * 顶栏知识库按钮上挂的条目总数。
 *
 * 这是个同步函数，取数没落地时只能返回 0——src/app/TopBar.tsx 是在 render 期
 * 直接调它的，而 TopBar 订阅的三个 store 字段（benchBusy / benchUser /
 * interlockPending）在运行期都不变，所以它挂载后不会因为取数落地而重渲。
 * 要让顶栏的数字在首屏就对，TopBar 那一行得改成调下面的 useKnowledgeTotal()；
 * TopBar 本轮冻结，这条已写进本包的跨包请求单。
 */
export function knowledgeTotal(): number {
  const id = useAppStore.getState().sceneId
  return ready.get(id)?.length ?? EMPTY_COUNTS.total
}

/* ----------------------------------------------------------------- React 侧 */

const EMPTY: KnowledgeEntry[] = []
const listeners = new Set<() => void>()
const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

/** 当前场景包的知识条目。组件里用这一个就够，取数与缓存都在里面。 */
export function useKnowledge(): {
  entries: KnowledgeEntry[]
  loading: boolean
  /** 取数失败的原因；正常时为 null。界面必须把它显示出来，不许静默。 */
  error: string | null
} {
  const sceneId = useAppStore((s) => s.sceneId)
  const entries = useSyncExternalStore(
    subscribe,
    () => ready.get(sceneId) ?? EMPTY,
    () => EMPTY,
  )
  const error = useSyncExternalStore(
    subscribe,
    () => errors.get(sceneId) ?? null,
    () => null,
  )
  useEffect(() => {
    // 取数失败会抛，这里接住是为了不让 React 报未处理拒绝；
    // 原因已经记进 errors，界面拿得到。
    void loadKnowledge(sceneId).catch(() => undefined)
  }, [sceneId])
  return { entries, loading: !ready.has(sceneId) && !errors.has(sceneId), error }
}

/** 当前场景包的知识条目总数（会随取数落地自动重渲）。供顶栏按钮用。 */
export function useKnowledgeTotal(): number {
  return useKnowledge().entries.length
}
