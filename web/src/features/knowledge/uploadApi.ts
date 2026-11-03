/* ===========================================================================
   知识库文档上传与五阶段转化：取数层（主文档 3.1，P3）。

   端点（后端 app/api/v1/kb_documents.py）：
     POST   /api/kb/documents                 上传原件（multipart）
     GET    /api/kb/documents                 列表
     GET    /api/kb/documents/{doc_id}        详情（轮询五阶段进度）
     POST   /api/kb/documents/{doc_id}/run    推进/重跑阶段

   两条纪律：
   一、**上传与转化分开**：上传只管存盘登记，转化由 run 显式触发。转化可能跑
       几分钟（那份 VML docx 实测 651 秒），挂在一次请求里必然超时。
   二、**失败要看得见**：所有请求先判 HTTP 再判 success 位，两个都过才返回值；
       调用方拿到的是 Error（带后端原话），不是静默的 undefined。
   =========================================================================== */

/** 五阶段（顺序即后端 KB_STAGES，改一处要两处同步） */
export const KB_STAGES = ['recognize', 'extract', 'chunk', 'struct', 'index'] as const
export type KbStage = (typeof KB_STAGES)[number]

export const STAGE_LABEL: Record<KbStage, string> = {
  recognize: '识别',
  extract: '抽取',
  chunk: '切片',
  struct: '结构化',
  index: '索引',
}

export type KbDocStatus = 'pending' | 'converting' | 'indexed' | 'failed' | 'needs_review'

export const STATUS_LABEL: Record<KbDocStatus, string> = {
  pending: '待处理',
  converting: '转化中',
  indexed: '已入库',
  failed: '转化失败',
  needs_review: '需人工校对',
}

export interface KbDocStage {
  key: KbStage
  label: string
  done: boolean
  artifact?: { path: string; done_at: string; summary: string } | null
}

export interface KbDocument {
  doc_id: string
  title: string
  file_name: string
  file_type: string
  size_bytes: number
  sha256: string
  owner_l1: string
  owner_l2: string
  owner_l3: string
  usage: string
  /** 自定义用途标签（可空）。三轴仍是 usage，这个只是更细的说法 */
  usage_label: string
  status: KbDocStatus
  status_label: string
  stage: string
  stage_label: string
  stages: KbDocStage[]
  failed_stage: string | null
  fail_reason: string | null
  entry_count: number
  confidence: number | null
  uploaded_by: string
  created_at: string | null
  updated_at: string | null
}

interface ApiBody<T> {
  success: boolean
  message: string
  data: T
}

/** 统一请求：先判 HTTP 再判 success 位。两个都过才返回值。 */
async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  let body: ApiBody<T> | null = null
  try {
    body = (await resp.json()) as ApiBody<T>
  } catch {
    throw new Error(`HTTP ${resp.status}（响应不是 JSON）`)
  }
  if (!resp.ok || !body.success) {
    throw new Error(body.message || `HTTP ${resp.status}`)
  }
  return body.data
}

export interface UploadInput {
  file: File
  title?: string
  owner_l1?: string
  owner_l2?: string
  owner_l3?: string
  /** 三轴之一（spec / requirement / process）——**只有这三个**，见 data/types.ts 的契约 */
  usage?: string
  /** 自定义用途标签（可空）。不占轴线，只是比三轴更细的说法 */
  usageLabel?: string
}

/**
 * 上传一份原件。**不设 Content-Type**：交给浏览器自己带 multipart 边界，
 * 手写 Content-Type 会把 boundary 写错，后端直接 422。
 */
export async function uploadDocument(input: UploadInput): Promise<{ doc: KbDocument; message: string }> {
  const fd = new FormData()
  fd.append('file', input.file)
  if (input.title) fd.append('title', input.title)
  if (input.owner_l1) fd.append('owner_l1', input.owner_l1)
  if (input.owner_l2) fd.append('owner_l2', input.owner_l2)
  if (input.owner_l3) fd.append('owner_l3', input.owner_l3)
  if (input.usage) fd.append('usage', input.usage)
  if (input.usageLabel) fd.append('usage_label', input.usageLabel)

  const resp = await fetch('/api/kb/documents', { method: 'POST', body: fd })
  const body = (await resp.json().catch(() => null)) as ApiBody<KbDocument> | null
  if (!resp.ok || !body?.success) {
    throw new Error(body?.message || `HTTP ${resp.status}`)
  }
  return { doc: body.data, message: body.message }
}

export function listDocuments(ownerL3?: string): Promise<{
  items: KbDocument[]
  total: number
  counts: Record<KbDocStatus, number>
}> {
  const q = ownerL3 ? `?owner_l3=${encodeURIComponent(ownerL3)}` : ''
  return call(`/api/kb/documents${q}`)
}

export function getDocument(docId: string): Promise<KbDocument> {
  return call(`/api/kb/documents/${encodeURIComponent(docId)}`)
}

/** 推进流水线。until 控跑到哪，only 控从哪重跑（每阶段可单独重跑）。 */
export function runPipeline(
  docId: string,
  opts: { until?: KbStage; only?: KbStage } = {},
): Promise<KbDocument> {
  const p = new URLSearchParams()
  if (opts.until) p.set('until', opts.until)
  if (opts.only) p.set('only', opts.only)
  const q = p.toString()
  return call(`/api/kb/documents/${encodeURIComponent(docId)}/run${q ? `?${q}` : ''}`, {
    method: 'POST',
    body: '{}',
  })
}

/**
 * 轮询直到转化结束（或超时）。
 *
 * 为什么需要轮询：转化是后台跑的，界面要知道「到了哪一步」。这里每 2 秒问一次，
 * 转成终态（indexed / needs_review / failed）就停。**超时不等于失败**——
 * 返回最后的快照，让界面按当前状态显示，而不是抛一个「超时」把已完成的进度藏掉。
 */
export async function pollUntilSettled(
  docId: string,
  opts: { intervalMs?: number; timeoutMs?: number; onTick?: (d: KbDocument) => void } = {},
): Promise<KbDocument> {
  const interval = opts.intervalMs ?? 2000
  const timeout = opts.timeoutMs ?? 15 * 60 * 1000
  const started = Date.now()
  let last = await getDocument(docId)
  opts.onTick?.(last)
  while (Date.now() - started < timeout) {
    if (last.status === 'indexed' || last.status === 'needs_review' || last.status === 'failed') {
      return last
    }
    await new Promise((r) => setTimeout(r, interval))
    last = await getDocument(docId)
    opts.onTick?.(last)
  }
  return last
}
