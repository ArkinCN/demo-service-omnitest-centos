/* ===========================================================================
   报告装配层（修 G-04）。

   此前报告页的「由上游带入」**只是占位文案**：`flow-report/panel.tsx` 的
   `upstream()` 仅按 `from_flow` 前缀判断是否留空，**不 import 任何 run API、
   不读 runId**。后果是报告表头 6 项永远是空的——而按契约，那 6 项恰恰是
   `config-snapshot`（init 的产物）该提供的。

   本模块只做一件事：**按 run_id 把上游产物读回来，整理成报告页能直接用的形状**。

   三条纪律：
     一、**只读，不产生副作用**。取不到返回 null / 空，由调用方决定显示什么，
         本模块不写 store、不改界面。
     二、**不猜**。取不到就说取不到（返回 null），不用场景包的值顶替——
         那会让人把「场景包登记值」当成「本轮确认过的基线」，是两回事。
     三、**字段名不转驼峰**（契约要求下划线命名）。
   =========================================================================== */
import { getRun, type ArtifactKind } from '../flow-run/api'
import { artifactMap } from '../shared/artifacts'

/** 报告表头字段（与 `report-template.json` 的 header_fields 同构） */
export interface ReportHeaderValue {
  key: string
  value: string
  /** 这个值是从哪来的，供界面如实标注 */
  source: 'config-snapshot' | 'scenario-pack' | 'manual' | 'none'
}

/** 判定汇总（从 verdict-table 折出来） */
export interface VerdictSummary {
  total: number
  pass: number
  fail: number
  /** 未采集 ≠ 不通过，单独计数 */
  missing: number
  /** 本台架不适用 ≠ 未采集 ≠ 不通过，单独计数（2026-10-08 新增） */
  notApplicable: number
  /**
   * B 口径通过率 = 通过 ÷（通过 + 不通过），取值 0~1（2026-10-10 新增，需求单编号 3）。
   * 未采集 / 本台架不适用 / 人工判定三类都不进分子分母；
   * **分母为 0 时为 `null`** —— 展示层显示「—」，不许显示 0%。
   */
  passRate: number | null
  /** 后端权威结果还是前端预览 */
  authoritative: boolean
}

/**
 * B 口径通过率 —— 前端唯一实现（与后端 `reports.py:_collect_report_data` 逐字同公式）。
 *
 * 分母只算**已判定**的条目（通过 + 不通过）：未采集、本台架不适用、人工判定都不进。
 * 分母为 0 时返回 `null`（本轮没有任何可判定的通过/不通过项）——
 * 界面与报告一律显示「—」，**禁止显示 0%**：0% 会被读成「全不通过」，与实际语义相反。
 */
export function computePassRate(pass: number, fail: number): number | null {
  const judged = pass + fail
  return judged > 0 ? pass / judged : null
}

/**
 * 通过率显示文本（唯一出口，报告页各处共用）：
 *   无判定数据 → 「—」；整数值 → 「100%」；非整数 → 保留 1 位小数（「66.7%」）。
 * 不做「四舍五入成假整数」：66.6% 不许写成 67%。
 */
export function fmtPassRate(rate: number | null): string {
  if (rate === null) return '—'
  const pct = rate * 100
  // 容忍浮点误差（如 0.1×100 = 10.000000000000002），仍按整数显示
  if (Math.abs(pct - Math.round(pct)) < 1e-9) return `${Math.round(pct)}%`
  return `${pct.toFixed(1)}%`
}

export interface AssembledReport {
  runId: string
  /** 表头字段（只含**取到了值**的项） */
  header: Record<string, string>
  /** 上游还没提供的字段 key（界面据此显示「由上游带入」） */
  missingHeaderKeys: string[]
  verdict: VerdictSummary | null
  /** 本轮产物里都有哪些 kind（供界面显示装配到哪些） */
  artifactKinds: string[]
}

/**
 * 报告表头里**由上游提供**的字段。取自 `report-template.json` 的 `from_flow`
 * 标记为 `F2 初始化配置` 的那 6 项；其余 4 项（F6）由报告页自己填。
 *
 * 写成常量而不是运行时从 JSON 读：这份清单是**契约**（模板字段与来源流程的
 * 对应关系），改动应当是可审的、显式的，而不是随数据漂移。
 */
export const UPSTREAM_HEADER_KEYS = [
  'model',
  'project_name',
  'firmware_version',
  'inlet_start_addr',
  'bootloader',
  'outlet_start_addr',
] as const

interface SnapshotAttr {
  key?: string
  value?: unknown
  _class?: string
}

/**
 * 从一轮产物里装配报告所需的数据。
 *
 * @param runId 轮次号；为空或该轮不存在时返回 null（**不抛**，由调用方展示「未取到」）
 */
export async function assembleReport(runId: string | null): Promise<AssembledReport | null> {
  if (!runId) return null

  let artifacts: unknown[]
  try {
    const r = await getRun(runId)
    artifacts = r.artifacts ?? []
  } catch (e) {
    // 读不到是正常态（还没跑过一轮 / 后端没起），记一句便于排查，不打断界面
    console.warn('[flow-report] 上游产物读取失败：', e)
    return null
  }

  const byKind = artifactMap(artifacts)

  // ── 表头：从 config-snapshot 的 product_attributes 里按 key 取
  //
  // ⚠️ 只认**真快照**（有 product_attributes 数组）。`persistRun` 落的那份同名
  // 产物只记场景与时刻（见业务流通文档 G-09），拿它当快照会让表头全空——
  // 与 loadLatestSnapshot 里的守卫同一个道理。
  const header: Record<string, string> = {}
  const missing: string[] = [...UPSTREAM_HEADER_KEYS]
  const snap = byKind.get('config-snapshot') as { product_attributes?: SnapshotAttr[] } | undefined
  if (snap && Array.isArray(snap.product_attributes)) {
    for (const a of snap.product_attributes) {
      const k = a?.key
      if (!k || a.value === null || a.value === undefined || a.value === '') continue
      if ((UPSTREAM_HEADER_KEYS as readonly string[]).includes(k)) {
        header[k] = String(a.value)
        const i = missing.indexOf(k)
        if (i >= 0) missing.splice(i, 1)
      }
    }
  }

  // ── 判定汇总：从 verdict-table 折
  let verdict: VerdictSummary | null = null
  const vt = byKind.get('verdict-table') as
    | { verdicts?: { state?: string }[]; authoritative?: boolean }
    | undefined
  if (vt && Array.isArray(vt.verdicts)) {
    const states = vt.verdicts.map((v) => v?.state ?? '')
    const pass = states.filter((s) => s === 'pass').length
    const fail = states.filter((s) => s === 'fail').length
    verdict = {
      total: states.length,
      pass,
      fail,
      missing: states.filter((s) => s === 'missing' || s === '未采集').length,
      // 本台架不适用（2026-10-08）：与 missing 分开统计，不进通过/不通过
      notApplicable: states.filter((s) => s === 'not_applicable' || s === '本台架不适用').length,
      // 通过率（2026-10-10）：分母只含已判定的通过/不通过，与后端同公式
      passRate: computePassRate(pass, fail),
      authoritative: Boolean(vt.authoritative),
    }
  }

  return {
    runId,
    header,
    missingHeaderKeys: missing,
    verdict,
    artifactKinds: [...byKind.keys()],
  }
}

/** 供界面显示的产物名（中文），未知 kind 原样显示 */
export const ARTIFACT_LABEL: Record<string, string> = {
  'config-snapshot': '配置快照',
  'requirement-baseline': '需求基线',
  'run-artifact': '轮次产物包',
  'verdict-table': '判定结果表',
  'gap-list': '未达标项清单',
  'param-change': '参数改动版本',
  'report-instance': '报告实例',
}

export const artifactLabel = (k: string): string => ARTIFACT_LABEL[k] ?? k

/** 便于调用方按 kind 取产物（保留给后续扩展用） */
export type { ArtifactKind }
