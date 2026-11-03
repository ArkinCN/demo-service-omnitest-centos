/* ===========================================================================
   非致命报错判定（汇报模式）· 纯判定模块

   ⚠️ 本文件是「隐藏非致命报错」需求的**唯一判定口径实现**（编号 1）。
   编号 2 的界面过滤、编号 3 的右下角灰点都**必须复用本模块**，不许再写第二份
   判定——两份实现必然漂移，届时会出现「界面藏了但清单说保留」这种自相矛盾。

   判定口径：**双重确认**（2026-10-10 用户逐项确认）
     一条 warn/error 日志被判「可隐藏（hide）」须**同时**满足：
       ① 整轮终态 === completed（界面「本轮已结束（已完成）」）；
       ② 该条所在环节能对应到本轮阶段，且该阶段最终状态 === success
          （说明这条报错已被重试等机制自行吸收，未影响流程）；
       ③ 未命中保护清单。
     其余一律「保留（keep）」，并给中文依据。

   ⚠️⚠️ 为什么必须叠加「环节级」判断，不能只看整轮终态（本次最重要的防误判点）：
   `automationOrchestrator.ts` 明确「报告阶段的成败**不回写** finalStatus」
   （见该文件流程 5 的注释）。也就是说「报告未生成：…」这条**红色**报错出现时，
   整轮 `finalStatus` 仍然是 `completed`。若只判整轮终态，这条会被当成非致命
   藏掉——正是用户最担心的「把致命错误误判为可隐藏，导致汇报时误以为成功」。
   叠加环节判断后：报告阶段 status=failed → 该条保留显示，隐患消除。

   纪律：
     · 纯函数、无 DOM、无 store 依赖、无副作用（供离线用例与 Playwright 直调）；
     · 方向永远是「宁多显示、不误藏」：拿不准就 keep。
   =========================================================================== */
import type { AutomationLogLevel, AutomationRunStatus, AutomationStage } from './automationOrchestrator'

/** 判定为「可隐藏」的最小日志形状（与 store 的 AutomationLogEntry 结构兼容） */
export interface JudgeLogEntry {
  seq: number
  at: number
  level: AutomationLogLevel
  stageId: string
  message: string
}

/** 单条报错的判定结果 */
export interface JudgeEntryResult {
  seq: number
  /** 日志产生时刻（ms epoch） */
  at: number
  level: 'warn' | 'error'
  stageId: string
  /** 该 stageId 对应阶段的名称；对应不上为 null */
  stageName: string | null
  /** 该阶段最终状态；对应不上或阶段未收口为 null */
  stageFinal: string | null
  /** hide = 界面可隐藏（编号 2 生效）；keep = 必须保留显示 */
  verdict: 'hide' | 'keep'
  /** 中文依据，直接给人看（用户验收时逐条核对这一列） */
  reason: string
  /** 报错原文，一字不改（供后台清单与复核） */
  message: string
}

/** 整轮判定报告 */
export interface JudgeReport {
  candidates: number
  hide: number
  keep: number
  entries: JudgeEntryResult[]
}

/**
 * 保护清单：命中即**保留显示**（永不隐藏）。
 *
 * 这些都是「操作指引 / 审计 / 合规」类文案——它们被藏掉会让人漏掉该做的动作
 * 或看不到审计事实，与「汇报不扎眼」的初衷相悖。
 * ⚠️ 保守白名单，只增不减需谨慎；扩充前请用真实日志核对措辞。
 */
const PROTECTED_PATTERNS: { re: RegExp; why: string }[] = [
  { re: /下载被浏览器拦截|手动点击/, why: '操作指引类（需人工介入），永不隐藏' },
  { re: /代确认|安全闸门/, why: '审计事实类（记录自动化代确认了哪条闸门），永不隐藏' },
  { re: /报告未生成/, why: '报告产出失败属关键结论，永不隐藏' },
]

/** 可隐藏的原因文案（统一措辞，便于用户核对） */
const REASON_HIDE = '整轮已完成，且该报错所在环节最终成功（已被重试等机制自行吸收，未影响流程）'

/**
 * 判定一批执行日志。
 *
 * @param logs      运行台执行日志（store.automationLogs），按 seq 升序
 * @param stages    本轮阶段定义（含 status/name），用于把 stageId 映射到环节终态
 * @param runStatus 整轮终态
 * @param runId     轮次号；为 null 表示没有有效轮次 → 全部保留（不判定）
 */
export function judgeNonFatal(
  logs: JudgeLogEntry[],
  stages: Pick<AutomationStage, 'id' | 'name' | 'status'>[],
  runStatus: AutomationRunStatus,
  runId: string | null,
): JudgeReport {
  // 候选集：只取 warn/error（info/success 无「报错」语义，不参与）
  const candidates = logs.filter((l) => l.level === 'warn' || l.level === 'error')

  // 阶段索引：stageId → {name, status}
  const stageById = new Map<string, { name: string; status: string }>()
  for (const s of stages) stageById.set(s.id, { name: s.name, status: String(s.status) })

  const overallCompleted = runStatus === 'completed'
  const hasRun = !!runId

  const entries: JudgeEntryResult[] = candidates.map((l) => {
    const stage = stageById.get(l.stageId)
    const stageName = stage?.name ?? null
    const stageFinal = stage?.status ?? null
    const protectedHit = PROTECTED_PATTERNS.find((p) => p.re.test(l.message))

    // ── 保留分支（按「最该说清的原因」优先）──
    let verdict: 'hide' | 'keep' = 'keep'
    let reason: string
    if (!hasRun) {
      reason = '本轮无有效轮次号，保守保留'
    } else if (!overallCompleted) {
      reason =
        runStatus === 'failed'
          ? '整轮以「失败」结束，致命错误绝不隐藏'
          : runStatus === 'stopped'
            ? '整轮被「终止」，结果不完整，一律保留'
            : '整轮尚未进入终态，暂不判定（保留显示）'
    } else if (protectedHit) {
      reason = protectedHit.why
    } else if (!stage) {
      reason = `日志来源「${l.stageId}」无法对应到本轮任一环节（可能是审计/跨阶段事件），保守保留`
    } else if (stage.status !== 'success') {
      reason =
        stage.status === 'failed'
          ? `所在环节「${stage.name}」最终失败，该报错是流程的失败原因，必须显示`
          : stage.status === 'skipped'
            ? `所在环节「${stage.name}」被跳过（多为终止导致），结果不完整，保留`
            : `所在环节「${stage.name}」未收口（状态 ${stage.status}），无法确认已吸收，保留`
    } else {
      // ✅ 三条同时满足 → 可隐藏
      verdict = 'hide'
      reason = REASON_HIDE
    }

    return {
      seq: l.seq,
      at: l.at,
      level: l.level as 'warn' | 'error',
      stageId: l.stageId,
      stageName,
      stageFinal,
      verdict,
      reason,
      message: l.message,
    }
  })

  const hide = entries.filter((e) => e.verdict === 'hide').length
  return {
    candidates: entries.length,
    hide,
    keep: entries.length - hide,
    entries,
  }
}
