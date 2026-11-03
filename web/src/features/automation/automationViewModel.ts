/* ===========================================================================
   自动化全屏运行台 · 视图派生层（纯函数，无 React）

   职责：把 store 里的**真数据**整理成可直接渲染的视图对象。
   纪律（与 flow-run/panel.tsx 同口径，违反即视为引入缺陷）：
     · 只做「取值 + 格式化 + 分类」，**不推算、不补零、不美化**；
     · 取不到的值一律给 `null`，由 UI 显示「—」或「未采集」；
     · 判据五档全量透传，`not_applicable` 单列且逐条带原因。

   为什么单独一层：运行台三栏要的东西（参数来源、动作态、判据统计、阶段耗时）
   都来自同一批 store 切片；若各组件各算一次，迟早出现「左栏说 4 档、右栏说 3 档」。
   =========================================================================== */
import type { BackendVerdict } from '../flow-run/api'
import type { AutomationStage, AutomationStageStatus } from './automationOrchestrator'
import { resolveParamKey } from '../../state/useAppStore'
import type { RawPack } from '../scene/pack'
import { fmtMeasureOrMissing } from '../shared/format'

/** 参数来源（与 flow-run 的 SourceTag 三态同义，不新增第四态） */
export type ParamSource = '本轮采纳' | '初始化快照' | '场景包文档值' | '不适用'

/** 左栏一行参数视图 */
export interface ParamView {
  key: string
  /** 显示名（已去掉括号注释，全名进 title） */
  name: string
  /** 全名（tooltip 用） */
  fullName: string
  /** 取值的显示文本；无取值时给「—」 */
  display: string
  /** 单位（如有） */
  unit?: string
  source: ParamSource
  /** 该项是否在本轮被采纳过（本轮采纳 → 高亮） */
  adopted: boolean
  editable: boolean
}

/**
 * 构造左栏「本轮自动选定的测试参数」列表。
 *
 * 取值走**回落链**（与流程 3 左栏完全一致，见 useAppStore.resolveParamKey）：
 *   本流程 overrides（= 流程 4 自动采纳的值）→ 初始化快照 → 场景包文档值。
 * 也就是说：自动化跑完调优采纳后，这一栏会**如实变成采纳后的新值**，
 * 这正是「自动选择参数」最直观的证据。
 */
export function buildParamViews(
  pack: RawPack | null,
  overrides: Record<string, number | string>,
  snapshotValues: Record<string, number | string>,
  opts: { onlyThisFlow?: boolean; adoptedKeys?: string[]; limit?: number } = {},
): ParamView[] {
  if (!pack) return []
  const all = pack.controls.parameters
  const params = opts.onlyThisFlow
    ? all.filter((p) => p.adjustable_in_flows?.some((f) => f.startsWith('F4')))
    : all
  const adopted = new Set((opts.adoptedKeys ?? []).map((k) => k.toUpperCase()))
  const picked = opts.limit ? params.slice(0, opts.limit) : params

  return picked.map((p) => {
      // ⚠️ 实参顺序必须与 flow-run/panel.tsx:132 完全一致：`('run', 'cp', p.group, p.key, …)`
      // —— sub 恒为字面量 'cp'，group 才是参数的分组。写反了会生成另一套 key，
      // 回落链读不到流程 1/3 写入的 override 与快照，左栏就会永远显示「场景包文档值」
      // （即「自动选了参数」在界面上看不出任何变化）。
      const r = resolveParamKey('run', 'cp', p.group, p.key, overrides, snapshotValues)
    const raw = r.value
    const has = raw !== undefined
    const isAdopted = adopted.has(p.key.toUpperCase())
    const source: ParamSource = !has
      ? '场景包文档值'
      : isAdopted || r.source === 'run'
        ? '本轮采纳'
        : r.source === 'init'
          ? '初始化快照'
          : '场景包文档值'
    const docValue = p.value
    return {
      key: p.key,
      /**
       * ⚠️ 2026-10-14 改：这里**不再截断括号**，保留全名交给 UI 层。
       *
       * 原因：词典的 key 是**全名**（如「进入闭环转速（FOC 切换转速）」），
       * 先截成「进入闭环转速」就再也命中不了词典 → 英文界面下参数名漏翻成中文。
       * 正确顺序是「先翻译、再截断」：渲染处 `uiT(p.name)` 翻译完全名后，
       * 英文同理（`Closed-loop entry speed (FOC transition speed)` → 截成
       * `Closed-loop entry speed`），中英文行为一致。
       */
      name: p.name,
      fullName: p.name,
      display:
        has ? String(raw) : docValue === null || docValue === undefined ? '—' : String(docValue),
      unit: p.unit ?? undefined,
      source: p.not_applicable ? '不适用' : source,
      adopted: isAdopted,
      editable: !p.not_applicable && p.editable && typeof docValue === 'number',
    }
  })
}

/* ---------------------------------------------------------------- 判据视图 */

/** 判据展示态：与 BackendVerdict.state 一一对应（五档，不合并、不新增） */
export type VerdictTone = 'pass' | 'fail' | 'missing' | 'manual' | 'not_applicable'

export interface VerdictView {
  reqId: string
  name: string
  tone: VerdictTone
  /** 右侧显示的实测摘要；缺测写「未采集」，不适用写原因摘要 */
  valueText: string
  /** tooltip 全文：本轮实测 + 缺什么 + 错误 */
  detail: string
}

/** 判据统计（四类计数 + 总数）。`total` 为 null 表示后端判定表还没来。 */
export interface VerdictStats {
  pass: number
  fail: number
  missing: number
  notApplicable: number
  total: number | null
}

/**
 * 由权威判定表派生右栏统计与行视图。
 *
 * ⚠️ `not_applicable` **绝不并入 pass 或 missing**：它是「本台架结构上没这个
 * 测量手段」（如需 MCU 故障寄存器），既不是「测过且合格」也不是「漏采」。
 * 空数组 → total=null（UI 显示「—」），而不是 0。
 */
export function buildVerdictViews(verdicts: BackendVerdict[]): {
  rows: VerdictView[]
  stats: VerdictStats
} {
  const rows: VerdictView[] = verdicts.map((v) => {
    const used = (v.used ?? [])
      .map(
        (u) =>
          `${u.name} ${
            typeof u.value === 'number' ? fmtMeasureOrMissing(u.value) : String(u.value)
          }${u.unit ?? ''}`,
      )
      .join('、')
    const naReason = v.notApplicableReason ?? ''
    const valueText =
      v.state === 'not_applicable'
        ? naReason
          ? `不适用：${naReason.length > 18 ? `${naReason.slice(0, 18)}…` : naReason}`
          : '本台架不适用'
        : v.state === 'missing'
          ? `未采集${v.missing?.length ? `（缺 ${v.missing.join('、')}）` : ''}`
          : used || v.note || '—'
    const detail = [
      used ? `本轮实测：${used}` : '',
      v.state === 'not_applicable' && naReason ? `本台架不适用：${naReason}` : '',
      v.note ?? '',
      !used && v.missing?.length ? `缺 ${v.missing.join('、')}` : '',
      v.error ? `错误：${v.error}` : '',
    ]
      .filter(Boolean)
      .join(' · ')
    return { reqId: v.req_id, name: v.name, tone: v.state, valueText, detail }
  })

  return {
    rows,
    stats: {
      pass: verdicts.filter((v) => v.state === 'pass').length,
      fail: verdicts.filter((v) => v.state === 'fail').length,
      missing: verdicts.filter((v) => v.state === 'missing').length,
      notApplicable: verdicts.filter((v) => v.state === 'not_applicable').length,
      total: verdicts.length ? verdicts.length : null,
    },
  }
}

/* ---------------------------------------------------------------- 阶段视图 */

export interface StageView {
  id: string
  name: string
  index: string
  status: AutomationStageStatus
  /** 该阶段已用时（ms）；**未结束为 null**（此时由 `liveElapsedOf` 按 startTime 实时算） */
  elapsed: number | null
  /** 阶段开始时刻（ms epoch），running 中用来实时累加已用时 */
  startTime: number | null
  message: string
  isCurrent: boolean
}

export interface StageStats {
  done: number
  failed: number
  skipped: number
  total: number
}

/** 阶段总览 + 统计。`total` 恒为配置里的阶段数，不随状态变化。 */
export function buildStageViews(
  stages: AutomationStage[],
  labels: { id: string; index: string; name: string }[],
  currentId: string | null,
): { views: StageView[]; stats: StageStats } {
  const views: StageView[] = stages.map((s) => {
    const meta = labels.find((l) => l.id === s.id)
    const elapsed =
      typeof s.endTime === 'number' && typeof s.startTime === 'number'
        ? s.endTime - s.startTime
        : null
    return {
      id: s.id,
      name: s.name,
      index: meta?.index ?? '·',
      status: s.status,
      elapsed,
      startTime: typeof s.startTime === 'number' ? s.startTime : null,
      message: s.message,
      isCurrent: currentId === s.id || s.status === 'running' || s.status === 'current',
    }
  })
  return {
    views,
    stats: {
      done: stages.filter((s) => s.status === 'success').length,
      failed: stages.filter((s) => s.status === 'failed').length,
      skipped: stages.filter((s) => s.status === 'skipped').length,
      total: stages.length,
    },
  }
}

/** 阶段总耗时（ms）：取起止时刻做减法；取不到给 null，UI 显示「—」。 */
export function totalElapsed(startedAt: number | null, finishedAt: number | null): number | null {
  if (startedAt === null || finishedAt === null) return null
  return Math.max(0, finishedAt - startedAt)
}