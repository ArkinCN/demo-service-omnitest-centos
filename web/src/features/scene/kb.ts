/* ===========================================================================
   知识库流水线产物的类型与取数。

   源目录 c-data/kb，
   整目录已复制到 public/kb/（排除 figures/ 大图与 content.md、source.json，
   前端只需要索引、切片与参数表）。它与场景包是两路产物：

   - 场景包 documents.json 登记的是「这个产品下有哪些材料」，61 条，含没转化的；
   - 知识库流水线 documents/index.json 登记的是「哪些材料真的过了转化流水线」，
     13 份，带页数、切片数、抽取实体数与 OCR / 转化状态。

   两边按 doc_id 与标题对不齐（一边是场景包自己编的 DOC-xxx，一边是流水线的
   doc_id），所以界面上分开呈现：已转化的走流水线索引，未转化的仍由场景包登记
   顶上，不硬把两张表并成一张。
   =========================================================================== */

import { fetchJson } from '../shared/fetchJson'

export interface KbDocument {
  doc_id: string
  title: string
  doc_type: string
  knowledge_class: string
  taxonomy: { l1: string; l2: string; l3: string }
  /** 这份文档用在哪几条流程上 */
  process_tags: string[]
  format: string
  pages: number | null
  page_limit: number | null
  tables: number
  /** 切片数 */
  chunks: number
  figures: number
  entities: Record<string, number>
  /** ok / failed / ocr 一类的转化状态 */
  convert_status: string
  converter: string
  bytes: number
  source_path: string
  note: string | null
  artifacts: string[]
}

export interface KbDocIndex {
  taxonomy: { l1: string; l2: string; l3: string }
  process_tags_vocab: string[]
  summary: {
    documents: number
    converted_ok: number
    failed: number
    total_chunks: number
    total_figures: number
    by_doc_type: Record<string, number>
    by_process_tag: Record<string, number>
  }
  documents: KbDocument[]
}

export interface KbHit {
  rank: number
  score: number
  kind: string
  doc_id: string
  doc_title: string
  chunk_id: string
  heading_path: string[]
  page: number | null
  source_path: string
  snippet: string
}

export interface KbSample {
  query: string
  k: number
  hits: number
  hit_docs: string[]
  pages_cited: number[]
  results: KbHit[]
}

export interface KbSearchSamples {
  engine: string
  tokenizer?: string
  corpus?: Record<string, unknown>
  vector_search?: unknown
  samples: KbSample[]
}

export interface KbExperience {
  id: string
  title: string
  /** 实验沉淀 / 规程沉淀 / 对话沉淀 */
  capture_mode: string
  phenomenon: { text: string; measured?: Record<string, unknown>; failed_detectors?: string[] }
  root_cause: { fault_id?: string; label: string; stage?: string; rationale?: string; independent_sources?: string[] }
  action: {
    parameter?: string
    direction?: string
    current_value?: number | string
    target_baseline?: number | string
    step?: string
    verified_range?: { minimum?: number; maximum?: number }
  }
  result: { status: string; note?: string }
  confidence: number
  source: Record<string, string>
  /** 三个维度各取且只取一个值：process 所属流程 / fault_type 问题类型 / capture_mode 沉淀方式 */
  tags: { scenario?: string; product?: string; process?: string; fault_type?: string; parameters?: string[] }
  time?: string
}

export interface KbExpIndex {
  taxonomy: { l1: string; l2: string; l3: string }
  summary: {
    total: number
    by_capture_mode: Record<string, number>
    by_fault_type: Record<string, number>
  }
  /** 这批经验成立到什么程度、有哪些不能当结论用的地方。必须在界面上显示。 */
  caveats: string[]
  entries: KbExperience[]
}

export interface KbTaxonomyDimension {
  key: string
  name: string
  question: string
  note?: string
  values: { code: string; label: string; desc?: string }[]
}

export interface KbTaxonomy {
  taxonomy: { l1: string; l2: string; l3: string }
  design_note?: string
  dimensions: KbTaxonomyDimension[]
}

export interface KbBundle {
  docs: KbDocIndex | null
  experience: KbExpIndex | null
  samples: KbSearchSamples | null
  taxonomy: KbTaxonomy | null
}

/** 这套产物挂在哪个三级节点下——只给对得上的那个场景包用，不跨产品套用 */
export function kbAppliesTo(kb: KbBundle, sceneId: string): boolean {
  const t = kb.docs?.taxonomy ?? kb.experience?.taxonomy
  if (!t) return false
  return sceneId === `${t.l1}.${t.l2}.${t.l3}`
}

async function getJson<T>(url: string): Promise<T | null> {
  // 2026-10-08：改用统一 fetchJson（原 force-cache 会读旧副本，见 fetchJson 模块头）
  return fetchJson<T>(url)
}

let task: Promise<KbBundle> | null = null

/** 读知识库流水线产物。整套是可选的：任一份取不到就为 null，由调用方回落到场景包。 */
export function loadKb(): Promise<KbBundle> {
  if (task) return task
  task = (async () => {
    const [docs, experience, samples, taxonomy] = await Promise.all([
      getJson<KbDocIndex>('/kb/documents/index.json'),
      getJson<KbExpIndex>('/kb/experience/index.json'),
      getJson<KbSearchSamples>('/kb/search-samples.json'),
      getJson<KbTaxonomy>('/kb/experience/taxonomy.json'),
    ])
    return { docs, experience, samples, taxonomy }
  })()
  return task
}

/** 文件名，用于把一长串绝对路径收成一行可读的东西（全名仍挂 title） */
export const kbFileName = (p: string) => p.split('/').pop() ?? p
