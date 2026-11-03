/* ===========================================================================
   知识库「抽取稿」取数层（查看内容 / 下载）。

   背景：知识库详情栏「源文件」是一行文本路径（形如 `[源] 调试经验文档/xxx.pdf`），
   用户要求：① 点击弹窗看内容；② 左侧下载图标直接下载。

   ⚠️ 诚实边界：客户**原始 PDF 不在本机**——`[源]` 是脱敏占位前缀，文件在客户内网盘。
   本层对接的是**系统已生成的 Markdown 抽取稿**（后端读 `c/data/kb/documents/<doc_id>/content.md`），
   **不是原件**。调用方（详情栏）必须把这一点如实展示给用户。

   两个后端端点（见 c/backend/app/api/v1/kb_documents.py）：
     GET /api/kb/documents/content-by-title?title=&owner_l3=   读全文
     GET /api/kb/documents/{doc_id}/download                   下载抽取稿

  整包导出端点（本层也提供 URL 构造，供顶栏「导出」按钮用）：
     GET /api/kb/documents/export?owner=&scene=                 整包 zip（见 kbExportUrl）
   =========================================================================== */

export interface DocContent {
  docId: string
  title: string
  /** 抽取稿 Markdown 全文 */
  text: string
  /** 恒 true：内容是系统抽取稿，非原件 */
  isExtract: boolean
  note: string
}

/** 后端返回的原始形状（snake_case，与 success_response 的 data 一致）。 */
interface RawDocContent {
  doc_id: string
  title: string
  text: string
  is_extract: boolean
  note: string
}

interface ApiBody<T> {
  success: boolean
  message: string
  data: T
}

/** 后端返回不可用内容时抛出的可读错误（带 HTTP 状态，便于界面区分"无抽取稿"）。 */
export class DocContentError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

/**
 * 读某文档的抽取稿全文。
 *
 * `title` 与数据侧 index.json 的 title 精确匹配；`ownerL3` 用于同名消歧（可选）。
 * 后端查不到会回 404 + 原因，这里原样抛出（界面据此提示"本机无抽取稿"，不弹空窗）。
 */
export async function fetchDocContent(title: string, ownerL3 = ''): Promise<DocContent> {
  const qs = new URLSearchParams({ title })
  if (ownerL3) qs.set('owner_l3', ownerL3)
  const resp = await fetch(`/api/kb/documents/content-by-title?${qs.toString()}`, {
    headers: { 'Content-Type': 'application/json' },
  })
  let body: ApiBody<RawDocContent> | null = null
  try {
    body = (await resp.json()) as ApiBody<RawDocContent>
  } catch {
    throw new DocContentError(`HTTP ${resp.status}（响应不是 JSON）`, resp.status)
  }
  if (!resp.ok || !body.success) {
    throw new DocContentError(body.message || `HTTP ${resp.status}`, resp.status)
  }
  const d = body.data
  return {
    docId: d.doc_id ?? '',
    title: d.title,
    text: d.text,
    isExtract: d.is_extract ?? true,
    note: d.note,
  }
}

/** 下载抽取稿的 URL（拿到 docId 后用）。 */
export function extractDownloadUrl(docId: string): string {
  return `/api/kb/documents/${encodeURIComponent(docId)}/download`
}

/* ------------------------------------------------------------ 整包导出

   顶栏「导出」按钮此前是空壳（只有图标文字、无 onClick）。后端已新增
   `GET /api/kb/documents/export?owner=&scene=`，这里只负责拼 URL——
   下载走浏览器原生导航（<a download>），不需要 fetch，因为要拿的是文件流。

   ⚠️ 导出范围用 **owner（产品三级名）** 而不是页面筛选态：用户口径是
   「导出整个所属知识库」，筛选是页面上的临时视图，不该决定导出内容。
   ⚠️ scene 带上可让后端按 taxonomy **精确**匹配文档，避免漏文档（实测漏过 3 份）。 */

export function kbExportUrl(owner: string, scene = ''): string {
  const qs = new URLSearchParams({ owner })
  if (scene) qs.set('scene', scene)
  return `/api/kb/documents/export?${qs.toString()}`
}

/* ------------------------------------------------- 合成图文稿（正文 + 插图）

   合成稿由后端离线脚本 `build_kb_combined.py` 生成到 `<doc_id>/combined/index.html`：
   把 content.md 的 `<!-- image -->` 占位按序换成 figures/ 的插图（配不上的占位直接删），
   得到一份干净、可读的图文稿。这里取回整段 HTML 给弹窗 iframe srcdoc 渲染。 */

export interface CombinedDoc {
  docId: string
  title: string
  /** 合成稿完整 HTML（自包含样式；图片 src 指向后端 figure 端点） */
  html: string
  meta: Record<string, unknown>
}

/** 读合成图文稿。无合成稿时返回 null（调用方回退 Markdown 预览）。 */
export async function fetchCombined(title: string, ownerL3 = ''): Promise<CombinedDoc | null> {
  const qs = new URLSearchParams({ title })
  if (ownerL3) qs.set('owner_l3', ownerL3)
  const resp = await fetch(`/api/kb/documents/combined?${qs.toString()}`, {
    headers: { 'Content-Type': 'application/json' },
  })
  if (resp.status === 404) return null
  let body: ApiBody<RawCombined> | null = null
  try {
    body = (await resp.json()) as ApiBody<RawCombined>
  } catch {
    throw new DocContentError(`HTTP ${resp.status}（响应不是 JSON）`, resp.status)
  }
  if (!resp.ok || !body.success) {
    throw new DocContentError(body.message || `HTTP ${resp.status}`, resp.status)
  }
  const d = body.data
  return { docId: d.doc_id, title: d.title, html: d.html, meta: d.meta ?? {} }
}

interface RawCombined {
  doc_id: string
  title: string
  html: string
  meta: Record<string, unknown>
}

/* --------------------------------------------------- title → docId 缓存
   详情栏点「下载」需要 docId，而条目只有 title。避免每次点都重新拉一次全文，
   把第一次 fetchDocContent 拿到的 docId 按 title 缓存（模块级 Map，会话内有效）。 */
const docIdCache = new Map<string, string>()

export function rememberDocId(title: string, docId: string): void {
  if (title && docId) docIdCache.set(title, docId)
}

export function cachedDocId(title: string): string | undefined {
  return docIdCache.get(title)
}
