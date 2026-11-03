/* ===========================================================================
   流程 3 的产物落盘与判定求值 —— 走后端，不再只在前端算。

   两条纪律决定了这里必须调后端而不是继续本地求值：
   一、判定要求唯一权威。前端 evaluate.ts 留着做即时预览/交互反馈，但最终结论
       以后端 /api/evaluate 为准——两份结果长时间并存必然会漂移。
   二、轮次产物要能被找回。此前 lastRun.run_id 恒为 null、history 恒为 null，
       刷新就没了；现在每轮落一条 run，轮次和文件都能从后端读回来。

   本文件只负责「后端怎么调、回来什么形状」，不碰任何界面状态。
   =========================================================================== */
import type { Evaluated } from './evaluate'
import { artifactMap, pickArtifact } from '../shared/artifacts'

/** 后端统一响应包装（app/schemas/common.py 的 success_response） */
interface ApiEnvelope<T> {
  success: boolean
  code: number
  message: string
  data: T
}

/** 后端 evaluate_one 的输出：字段与前端 Evaluated 对齐，但用 req_id 而非整个 req 对象 */
export interface BackendVerdict {
  req_id: string
  name: string
  /** 与前端 VerdictState 对齐；not_applicable = 本台架不具备该项测量手段（2026-10-08 新增） */
  state: 'pass' | 'fail' | 'missing' | 'manual' | 'not_applicable'
  used: { name: string; value: number | boolean | string; unit?: string | null }[]
  missing: string[]
  partial?: boolean
  note?: string
  error?: string
  /** state='not_applicable' 时的原因（缺哪台设备），与前端 notApplicableReason 同义 */
  notApplicableReason?: string
}

export interface EvaluateResult {
  scene_id: string
  measures: Record<string, number>
  /** 后端权威计数；not_applicable 单列，不并入 pass/missing（2026-10-08 后端补齐） */
  summary: { pass: number; fail: number; missing: number; manual: number; not_applicable?: number }
  results: BackendVerdict[]
}

export interface RunRecord {
  run_id: string
  user_id: number
  scene_id: string
  status: string
  mode: string
  created_at: string
  updated_at: string
  finished_at: string | null
}

/**
 * 七份产物的类型名。**必须与后端 `ARTIFACT_SCHEMAS` 的键完全一致**
 * （`c/backend/app/models/run.py`），后端对 kind 做白名单校验，不在七值内
 * 一律 409 拒绝。
 *
 * ⚠️ 这里曾写成 precheck / timeline / measurements / tuning-record / report-draft
 * ——七个里只有 config-snapshot 与 verdict-table 两个对得上，其余五份会被后端
 * 拒掉。又因为在调用处把异常 catch 空了，界面上完全看不出来，
 * 结果「刷新后仍能找回轮次」这项验收长期挂着却查不到原因（2026-09-23 全量审查发现）。
 *
 * 取值以主文档 4.1 节「artifact_kind 取七值（一律用流程标识，不用序号）」为准，
 * 并与收发关系表对应：
 *   配置快照 config-snapshot(init) / 需求基线 requirement-baseline(req) /
 *   轮次产物包 run-artifact(run) / 判定结果表 verdict-table(run) /
 *   未达标项清单 gap-list(run) / 参数改动版本 param-change(tune) /
 *   报告实例 report-instance(report)
 *
 * **改这个值之前先看后端**：这类枚举前后端不一致时编译不报错，
 * 只在运行时以 409 或「数据被丢弃」的形式暴露。可用
 * `python scripts/audit_enum_contract.py` 做双向差集复查。
 */
export type ArtifactKind =
  | 'config-snapshot'
  | 'requirement-baseline'
  | 'run-artifact'
  | 'verdict-table'
  | 'gap-list'
  | 'param-change'
  | 'report-instance'

/**
 * 统一请求。后端出错时返回的也是这套包装（error_response），
 * 所以这里先看 HTTP 状态，再看 success 位，两层都要过。
 */
async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  let body: ApiEnvelope<T> | null = null
  try {
    body = (await resp.json()) as ApiEnvelope<T>
  } catch {
    // 非 JSON 响应（网关错误页等）：直接按 HTTP 状态报，别把解析失败说成业务失败
    throw new Error(`HTTP ${resp.status}`)
  }
  if (!resp.ok || !body.success) {
    throw new Error(body.message || `HTTP ${resp.status}`)
  }
  return body.data
}

/**
 * 求判定。measures 由调用方给（来自 runtimeMeasures(waves, pack)），
 * 后端不自己造数：它只按这轮真采到的量求值，采不到就落「未采集」。
 *
 * ⚠️ 这里**没有**复用上面的 `call()`，而是单独解析（2026-10-08 修）：
 * 后端 `/api/evaluate` 早期返回的是**裸 payload**（`{scene_id, measures, summary, results}`），
 * 而 `call()` 只认 `{success, code, message, data}` 包装 —— 判到 `body.success === undefined`
 * 就抛 `HTTP 200`。后果不是「报错」而是**静默降级**：每轮跑完都走 outer catch 退回前端预览，
 * `persistRun` 一次都没执行 → 判定表不落库 → `confirmFlow('run')` 不调 →
 * 顶栏「启动测试及结果分析」永远点不亮（真实台架跑完 45s 实测栽过）。
 *
 * 后端已改成 `success_response` 包装（`backend/app/api/v1/evaluate.py`）。
 * 本函数两种形状都认，并在读到裸 payload 时明确 warn 一次——
 * 「兼容」不等于「掩盖」：后端没重启时这条 warn 就是提示。
 */
export async function evaluateOnBackend(
  sceneId: string,
  measures: Record<string, number>,
  /** 采纳/人工改过的控制参数（key = 场景包参数 key → 当前值），后端据此覆盖原值，
   *  否则权威判定永远读场景包原值、「改了参数结论不变」。 */
  controlOverrides: Record<string, number | string> = {},
): Promise<EvaluateResult> {
  const resp = await fetch('/api/evaluate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scene_id: sceneId, measures, control_overrides: controlOverrides }),
  })
  const body = (await resp.json()) as ApiEnvelope<EvaluateResult> & EvaluateResult
  const enveloped = typeof body?.success === 'boolean'
  if (!resp.ok || (enveloped && !body.success)) {
    throw new Error(body?.message || `HTTP ${resp.status}`)
  }
  if (!enveloped) {
    console.warn(
      '[flow-run] /api/evaluate 返回裸 payload（后端仍是旧版，未加载统一响应包装），已兼容解析；重启后端即可走标准包装',
    )
    return body as EvaluateResult
  }
  return body.data
}

export function createRun(sceneId: string, mode: 'mock' | 'real' = 'mock'): Promise<RunRecord> {
  return call<RunRecord>('/api/runs', {
    method: 'POST',
    body: JSON.stringify({ scene_id: sceneId, mode }),
  })
}

export function putArtifact(
  runId: string,
  kind: ArtifactKind,
  content: unknown,
): Promise<{ run_id: string; artifact_kind: string; schema: string }> {
  return call(`/api/runs/${runId}/${kind}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  })
}

export function getRun(runId: string): Promise<{ run: RunRecord; artifacts: unknown[] }> {
  return call(`/api/runs/${runId}`)
}

export function listRuns(sceneId: string, limit = 20): Promise<RunRecord[]> {
  return call<RunRecord[]>(
    `/api/runs?scene_id=${encodeURIComponent(sceneId)}&limit=${limit}`,
  )
}

/** 状态迁移（后端校验合法性，非法返回 409 并带回原因） */
export function transitionRun(runId: string, toStatus: string): Promise<RunRecord> {
  return call<RunRecord>(`/api/runs/${runId}/transition?to_status=${encodeURIComponent(toStatus)}`, {
    method: 'POST',
  })
}

/**
 * 把本轮结果落成一轮可找回的产物。
 *
 * 落的五份（全部取自 ArtifactKind 七值，后端才认）：
 *   config-snapshot  配置快照（场景 + 时刻）
 *   run-artifact     轮次产物包（本轮实测量 + 起止时间）
 *   verdict-table    判定结果表（结论，优先用后端权威结果）
 *   gap-list         未达标项清单（从判定表里筛出不通过的项）
 *   report-instance  报告实例（草稿态，真实报告待 M08 模板）
 *
 * 为什么是这五份：「跑完一轮」的产生方是 run 流程，按主文档 4.1 节的收发关系表，
 * run 产 run-artifact / verdict-table / gap-list；config-snapshot 由 init 产但本轮要记
 * 场景与时刻；report-instance 先落草稿占位（消费方是 report 流程）。
 * requirement-baseline（req 产）与 param-change（tune 产）不属于本轮，**不冒充**。
 *
 * 顺序有讲究——先落快照与实测量，再落判定表：判定表要引用前面的量，
 * 反过来的话中途失败会留下一张无从复核的结论表。
 *
 * 返回 run_id，供界面记住「本轮」；后端不可用时抛错，由调用方决定是否降级到本地预览。
 */
export async function persistRun(opts: {
  sceneId: string
  verdicts: Evaluated[]
  measures: Record<string, number>
  backendVerdicts?: BackendVerdict[]
  startedAt?: string
  finishedAt?: string
}): Promise<string> {
  const run = await createRun(opts.sceneId, 'mock')
  const now = opts.finishedAt ?? new Date().toISOString()

  await putArtifact(run.run_id, 'config-snapshot', {
    scene_id: opts.sceneId,
    captured_at: opts.startedAt ?? now,
    // 场景包的参数快照由后续阶段补；本阶段先记场景与时刻，不冒充完整配置
    note: '本阶段只记场景与时刻，控制参数全量快照待阶段 5 接设备桥后补',
  })

  await putArtifact(run.run_id, 'run-artifact', {
    measures: opts.measures,
    started_at: opts.startedAt ?? now,
    finished_at: now,
    note: '本轮真采到的实测量与起止时刻；取不到的量不在表内，下游据此判「未采集」',
  })

  await putArtifact(run.run_id, 'verdict-table', {
    // 判定表是结论，优先记后端那份权威结果；后端没给才用前端预览
    verdicts: opts.backendVerdicts ?? opts.verdicts.map(toVerdictRow),
    authoritative: Boolean(opts.backendVerdicts),
    judged_at: now,
  })

  // 未达标项清单：把不通过的判据单独拎出来，供调优流程直接取用，
  // 不必让下游再去解析整张判定表
  const failed = (opts.backendVerdicts ?? opts.verdicts.map(toVerdictRow)).filter(
    (v) => v.state === 'fail',
  )
  await putArtifact(run.run_id, 'gap-list', {
    items: failed,
    count: failed.length,
    note: failed.length
      ? '本轮未达标项，供调优流程取用'
      : '本轮无未达标项（注意：未采集不等于达标，见判定表的 missing）',
  })

  await putArtifact(run.run_id, 'report-instance', {
    status: 'draft',
    note: '报告实例草稿占位：真实报告生成待模板 .xlsm 到位（M08 硬阻塞）',
  })

  // 落完产物把状态推到 completed，让「跑完了」这件事在轮次记录里也有据
  try {
    await transitionRun(run.run_id, 'queued')
    await transitionRun(run.run_id, 'prechecking')
    await transitionRun(run.run_id, 'awaiting_approval')
    await transitionRun(run.run_id, 'running')
    await transitionRun(run.run_id, 'collecting')
    await transitionRun(run.run_id, 'evaluating')
    await transitionRun(run.run_id, 'completed')
  } catch (e) {
    // 状态机走得动就走；走不动说明后端版本与前端不一致，
    // 但产物已经落盘，不该因此把整轮判成失败。
    // 不过要留一条可查的痕：否则轮次会一直停在 draft，
    // 界面上却看不出异常（与落盘失败同源的「静默」问题）。
    console.warn('[flow-run] 轮次状态机推进失败，产物已落盘但状态未推进：', e)
  }

  return run.run_id
}

/**
 * 读回本场景最近一份判定表（流程 3 落的 verdict-table）。
 *
 * 这是流程 4「未达标项」该继承的判定来源。此前流程 4 不读它，而是用
 * `evaluateAll` + 同一份固定波形**重算**，3→4 断在这里——流程 3 落了后端
 * 权威判定，流程 4 却视而不见、自己再算一遍（两份可能漂移）。
 *
 * 与 loadLatestBaseline / loadAdoption 同款：按场景取最近若干轮，逐轮找
 * verdict-table，取到第一份就用；读不到返回空（「还没跑过一轮」的正常态）。
 *
 * ⚠️ 只认有 `verdicts` 数组的产物：老轮次或 shape 变了，拿空回填会把
 * 界面清成「0 条判定」，比不回填更难查。
 */
export async function loadLatestVerdicts(sceneId: string): Promise<{
  verdicts: BackendVerdict[]
  runId: string | null
}> {
  const runs = await listRuns(sceneId, 10)
  if (!runs.length) return { verdicts: [], runId: null }
  for (const r of runs) {
    try {
      const { artifacts } = await getRun(r.run_id)
      const body = pickArtifact(artifacts, 'verdict-table') as { verdicts?: BackendVerdict[] } | undefined
      if (body && Array.isArray(body.verdicts)) {
        return { verdicts: body.verdicts, runId: r.run_id }
      }
    } catch {
      // 某一轮读不到就跳过，继续看下一轮
      continue
    }
  }
  return { verdicts: [], runId: runs[0].run_id }
}

/* ===========================================================================
   助手上下文包要用的「最近一轮真实轮次」。
   ---------------------------------------------------------------------------
   背景（2026-09-29 用户实测）：助手上下文里的 `lastRun` 原先在
   `copilot/context.ts` 里**写死**——无论跑没跑过一轮，都一律报「所有判据
   未采集 + N 项实测量未采集」。模型据此编出「判据挂错流程」这类**不存在
   的问题**（用户问「判据与工作流有没有对不上」，助手拿着假清单给了误导性
   自查建议）。

   这里把它接真：按场景读回最近一轮**真带产物**的轮次，组装成真实 lastRun。
   读不到（确实没跑过一轮）返回 null——如实标注，绝不编。

   设计：与 `loadLatestVerdicts` 同款——`listRuns(limit=10)` 逐轮 `getRun`，
   取第一份带 `verdict-table` 的轮次，顺带取同轮的 `run-artifact` 与 `gap-list`
   （契约定：**一轮带多份产物**）。单轮读失败跳过，不让一轮的异常拖垮整体。
   =========================================================================== */

/** 助手上下文包 lastRun 的真数据形状（字段与 copilot/context.ts 消费端对齐） */
export interface LastRunData {
  run_id: string
  finished_at: string | null
  /** 由真 verdicts 派生：有 fail→'fail'；无 fail 有 missing→'missing'；全 pass→'pass'；空→'invalid' */
  overall: 'pass' | 'fail' | 'missing' | 'invalid'
  overall_note: string
  /** 真判定表（pass/fail/missing/manual），不是「一律未采集」 */
  verdicts: BackendVerdict[]
  /** 未达标项（state==='fail'） */
  failed_items: BackendVerdict[]
  /** **真缺的**实测量 = 判据声明所需 − 该轮真采到的（不是「声明集合」本身） */
  missing_measures: string[]
  /** 该轮真落下的产物索引 */
  artifacts: { run_id: string; items: string[] } | null
}

/** 由真判定汇总 overall，并给一句如实的说明 */
function summarize(vs: BackendVerdict[]): { overall: LastRunData['overall']; note: string } {
  if (!vs.length) return { overall: 'invalid', note: '本轮判定表为空，结论不成立' }
  const fail = vs.filter((v) => v.state === 'fail').length
  const missing = vs.filter((v) => v.state === 'missing').length
  const pass = vs.filter((v) => v.state === 'pass').length
  // 本台架不适用（2026-10-08）：不计入 missing——它已写明缺什么设备，不是"漏采"。
  const na = vs.filter((v) => v.state === 'not_applicable').length
  const naNote = na ? `、${na} 条本台架不适用（缺测量手段，逐条有原因）` : ''
  if (fail) return { overall: 'fail', note: `本轮不通过：${fail} 条未达标、${pass} 条通过、${missing} 条未采集${naNote}` }
  if (missing)
    return { overall: 'missing', note: `本轮无未达标，但有 ${missing} 条未采集（未采集不等于达标）${naNote}` }
  return { overall: 'pass', note: `本轮全部通过：${pass} 条${naNote}` }
}

/**
 * 读回本场景最近一轮带产物的轮次，组装成助手上下文用的 lastRun。
 *
 * @param sceneId 场景 id
 * @param requiredMeasures 判据声明的 `runtime.measure` 变量全集（用于算「真缺的」）。
 *   传空数组时，`missing_measures` 只能反映「该轮 measures 为空」，不做差额推算。
 * @param legend 变量名 → 中文名（场景包 requirements.runtime_measures 的 name）。
 *   传入时 `missing_measures` 输出「中文名(英文键)」——助手上下文摘要据此给模型
 *   中文名，回答里才不会出现用户看不懂的英文键名（用户实测反馈过）。
 *   不传维持英文键（向后兼容）。
 * @returns 有有效产物 → LastRunData；一轮都没有 → null（如实的「没跑过」）
 */
export async function loadLatestRun(
  sceneId: string,
  requiredMeasures: string[] = [],
  legend?: Record<string, string>,
): Promise<LastRunData | null> {
  const runs = await listRuns(sceneId, 10)
  if (!runs.length) return null

  for (const r of runs) {
    let artifacts: unknown[] = []
    try {
      const got = await getRun(r.run_id)
      artifacts = got.artifacts ?? []
    } catch {
      continue // 某一轮读不到就跳过，继续看下一轮
    }
    const byKind = artifactMap(artifacts)
    const vt = byKind.get('verdict-table') as { verdicts?: BackendVerdict[] } | undefined
    // 没有判定表的轮次不算「跑过一轮的结果」（可能只落了快照）
    if (!vt || !Array.isArray(vt.verdicts)) continue

    const verdicts = vt.verdicts
    const ra = byKind.get('run-artifact') as
      | { measures?: Record<string, number>; finished_at?: string; started_at?: string }
      | undefined
    const gl = byKind.get('gap-list') as { items?: BackendVerdict[] } | undefined

    // 真采到的量（键集合）；判据要但没采到的才算「未采集」。
    // 有 legend 时输出「中文名(英文键)」：上下文摘要给模型中文名，
    // 回答里才不会照抄英文键名（与 agent_context._fmt_fields 同一口径）。
    const measured = new Set(Object.keys(ra?.measures ?? {}))
    const missing_measures = requiredMeasures
      .filter((m) => !measured.has(m))
      .map((m) => (legend?.[m] ? `${legend[m]}(${m})` : m))

    const { overall, note } = summarize(verdicts)

    return {
      run_id: r.run_id,
      finished_at: ra?.finished_at ?? r.finished_at ?? null,
      overall,
      overall_note: note,
      verdicts,
      failed_items: Array.isArray(gl?.items) ? gl.items : verdicts.filter((v) => v.state === 'fail'),
      missing_measures,
      artifacts: {
        run_id: r.run_id,
        // artifacts 的元素是后端返回的对象数组，字段名是 artifact_kind。
        // 这里显式收窄成 Record 再取，避免 `a?.artifact_kind` 在 `{}` 上报 TS2339。
        items: artifacts
          .map((a) => String((a as { artifact_kind?: string } | null)?.artifact_kind ?? ''))
          .filter(Boolean),
      },
    }
  }
  return null
}

/** 前端 Evaluated → 判定表行（与后端 BackendVerdict 同形状，便于两处消费同一套渲染） */
export function toVerdictRow(e: Evaluated): BackendVerdict {
  return {
    req_id: e.req.id,
    name: e.req.name,
    state: e.state,
    used: e.used,
    missing: e.missing,
    partial: e.partial,
    note: e.note,
    error: e.error,
  }
}
