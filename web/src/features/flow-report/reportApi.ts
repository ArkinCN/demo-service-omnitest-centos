/* ===========================================================================
   报告生成与下载的取数层（修 G-06 / G-07 的前端一半）。

   此前 `gen-report` 这个 action **只 `setReportGenerated(true)`**——不落产物、
   不调后端、不产生任何文件；`export` 也只弹确认卡。所以链路末端是空的。

   现在真调后端两个端点：
     POST /api/reports/generate?run_id=...   生成报告
     GET  /api/reports/{run_id}/download     下载

   ⚠️ 状态必须**如实透出**：后端可能返回三档（ok / placeholder / blocked），
   前端不能一律显示「报告已生成」——那会把「占位报告」说成正式交付件。
   =========================================================================== */

import { getRun, listRuns, putArtifact } from '../flow-run/api'
import { pickArtifact } from '../shared/artifacts'

export type ReportStatus = 'ok' | 'placeholder' | 'blocked'

/* ===========================================================================
   报告实例 report-instance/v1 —— 报告页「确认表头」的落库形态（2026-09-30）。

   为什么要有它（本轮补的是一个**真实缺口**）：
   报告页的左栏「确认表头」此前**误绑**到「生成报告」动作上（点确认 = 生成+下载），
   而表头本身只存在 `useAppStore.reportHeader`（localStorage）——**从没离开过浏览器**。
   后端生成报告时只读 config-snapshot 的 6 个上游字段，报告页本流程补的 4 项
   根本不进生成的报告。所以「确认表头」既不真确认、确认值也不进报告。

   契约定成：
     · 确认 = 把当前全部表头（上游带入 + 本流程补全）以 report-instance 产物
       落库到最近一轮，`status: 'confirmed'`；
     · 后端生成报告时读这份产物，把 header 合并进报告数据（**确认值优先**于
       config-snapshot），已被确认的键不再列入「未提供」；
     · 与 `flow-run/api.ts` 每轮落的那份 `status:'draft'` 草稿**区分开**——
       后端只认 `status === 'confirmed'` 且带 `header` 字典的那份。
   =========================================================================== */

/** 契约 report-instance/v1 的内容形态（确认态） */
export interface ReportInstance {
  schema: 'report-instance/v1'
  scene_id: string
  status: 'confirmed'
  /** 已确认的表头字段：key → 值（只含**有值**的项，空的不落） */
  header: Record<string, string>
  /** 确认时的表头字段总数（含未填的），便于人肉核对「共几项、填了几项」 */
  header_total: number
  /** 表头字段的完整定义（key/name/from_flow/value_slot），供后端回写与追溯 */
  fields: { key: string; name: string; from_flow: string; value_slot: string }[]
  confirmed_at: string
  confirmed_by: string
}

export interface GenerateResult {
  run_id: string
  status: ReportStatus
  file?: string
  bytes?: number
  reason?: string
  note?: string
  artifacts?: string[]
  download_url?: string
}

interface ApiBody<T> {
  success: boolean
  message: string
  data: T
}

async function call<T>(path: string, init?: RequestInit): Promise<{ data: T; message: string }> {
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
  if (!resp.ok || !body.success) throw new Error(body.message || `HTTP ${resp.status}`)
  return { data: body.data, message: body.message }
}

/** 生成报告。返回后端的真实状态，由调用方决定怎么显示。 */
export async function generateReport(runId: string): Promise<GenerateResult> {
  const { data } = await call<GenerateResult>(
    `/api/reports/generate?run_id=${encodeURIComponent(runId)}`,
    { method: 'POST', body: '{}' },
  )
  return data
}

/**
 * 触发浏览器下载。
 *
 * 为什么用 `<a href download>` 而不是 `window.open`：下载端点在 `/api` 下，
 * 走的是同源代理；用 a 标签带 download 属性不会新开页签、也不会被拦截。
 * 404 时浏览器不会给出有用提示，所以**先探一次**（headReport）再决定要不要点。
 */
export function downloadUrl(runId: string): string {
  return `/api/reports/${encodeURIComponent(runId)}/download`
}

/**
 * 定出报告该挂在哪一轮。
 *
 * 优先用本会话记住的 runId；没有（比如刷新过、或没在本会话点过启动）就**按场景取最近一轮**。
 * 与 `flow-tune/adoptApi.ts` 的 `resolveRunId` 同款做法——报告与采纳一样，
 * 都该挂到「真实的最近一轮」上，而不是因为本会话没点过启动就整个功能不可用。
 *
 * 一轮都没有才抛错（由调用方显示原因），**不降级成假数据**。
 */
export async function resolveReportRunId(sceneId: string, runId: string | null): Promise<string> {
  if (runId) return runId
  const runs = await listRuns(sceneId, 1)
  if (!runs.length) {
    throw new Error('本场景还没有落过轮次，先在流程 3 跑完一轮再生成报告')
  }
  return runs[0].run_id
}

/** 报告文件是否已存在（用 HEAD 探，避免把整个文件拉下来只为了看一眼） */
export async function reportExists(runId: string): Promise<boolean> {
  try {
    const resp = await fetch(downloadUrl(runId), { method: 'HEAD' })
    return resp.ok
  } catch {
    return false
  }
}

/**
 * 状态的中文与语气，供界面统一使用。
 *
 * 2026-10-10 口径变更：系统内置模板即正式报告，后端默认返回 `ok`。
 * `placeholder` 保留只为**兼容改版前落的历史轮次**（那时的报告确实是占位件），
 * 新生成不会再走这一档；文案不再出现「可替换」。
 */
export const REPORT_STATUS_TEXT: Record<ReportStatus, { label: string; tone: 'ok' | 'warn' | 'alert' }> = {
  ok: { label: '报告已生成', tone: 'ok' },
  placeholder: { label: '报告已生成（历史占位版式）', tone: 'warn' },
  blocked: { label: '生成失败', tone: 'alert' },
}

export interface TemplateStatus {
  ready: boolean
  filename?: string
  bytes?: number
  uploaded_at?: string
  note?: string
}

/** 查当前模板状态：已上传客户模板 or 缺位（用系统自建模板） */
export async function templateStatus(): Promise<TemplateStatus> {
  const { data } = await call<TemplateStatus>('/api/reports/template/status')
  return data
}

/** 上传客户模板（.xlsm），覆盖式。返回后端确认信息。 */
export async function uploadTemplate(file: File): Promise<{ filename: string; bytes: number; note?: string }> {
  const fd = new FormData()
  fd.append('file', file)
  const resp = await fetch('/api/reports/template', { method: 'POST', body: fd })
  let body: ApiBody<{ filename: string; bytes: number; note?: string }> | null = null
  try {
    body = (await resp.json()) as ApiBody<{ filename: string; bytes: number; note?: string }>
  } catch {
    throw new Error(`HTTP ${resp.status}（响应不是 JSON）`)
  }
  if (!resp.ok || !body.success) throw new Error(body.message || `HTTP ${resp.status}`)
  return body.data
}

/**
 * 落一份**已确认**的报告实例（表头）。
 *
 * 与 `persistBaseline` 同款：有轮次就复用、没有就按场景取最近一轮
 * （`resolveReportRunId` 已把「一轮都没有」抛成可见错误，由调用方显示）。
 * 同 run + kind 后端是覆盖语义，重复确认不会堆两条。
 *
 * fields 传**表头字段的完整定义**（不只值）：后端据此知道每个键的中文名与
 * 来源流程，回写报告时能如实标注出处，也便于将来模板换型时追溯。
 */
export async function persistReportInstance(opts: {
  sceneId: string
  runId: string | null
  header: Record<string, string>
  fields: { key: string; name: string; from_flow: string; value_slot: string }[]
  operator: string
}): Promise<{ runId: string; instance: ReportInstance }> {
  const runId = await resolveReportRunId(opts.sceneId, opts.runId)
  // 只落**有值**的项：空值落进去会被后端当成「确认了空」，
  // 与「未填」不区分——null 才是「未提供」的正解。
  const header: Record<string, string> = {}
  for (const [k, v] of Object.entries(opts.header)) {
    const s = (v ?? '').trim()
    if (s) header[k] = s
  }
  const instance: ReportInstance = {
    schema: 'report-instance/v1',
    scene_id: opts.sceneId,
    status: 'confirmed',
    header,
    header_total: opts.fields.length,
    fields: opts.fields,
    confirmed_at: new Date().toISOString(),
    confirmed_by: opts.operator,
  }
  await putArtifact(runId, 'report-instance', instance)
  return { runId, instance }
}

/**
 * 读回最近一份**已确认**的报告实例（表头）。
 *
 * 与 `loadLatestBaseline` 同款：不依赖内存，按场景取最近若干轮逐轮找。
 * **必须校验 `status === 'confirmed'` 且 `header` 是对象**——每轮 `persistRun`
 * 还落了一份 `status:'draft'` 的草稿（只有 note），拿它回填会把表头清空。
 * 返回 null = 还没确认过（正常态）。
 */
export async function loadLatestReportInstance(
  sceneId: string,
): Promise<{ instance: ReportInstance; runId: string } | null> {
  const runs = await listRuns(sceneId, 10)
  for (const r of runs) {
    try {
      const { artifacts } = await getRun(r.run_id)
      const body = pickArtifact(artifacts, 'report-instance') as ReportInstance | undefined
      if (
        body &&
        body.schema === 'report-instance/v1' &&
        body.status === 'confirmed' &&
        body.header &&
        typeof body.header === 'object'
      ) {
        return { instance: body, runId: r.run_id }
      }
    } catch {
      // 某一轮读不到就跳过，继续看下一轮
      continue
    }
  }
  return null
}
