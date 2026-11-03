/* ===========================================================================
   调优候选推荐的纯数据逻辑（从 flow-tune/panel.tsx 的 useCandidates 抽出）。

   为什么抽成纯函数而不是留在组件里：
     一键自动化测试流程的「调优重试」要在适配层（非 React 组件）里**自动采纳
     推荐参数**，必须拿到与流程 4 界面**同一份**候选列表。若只留 useCandidates
     （React hook），适配层要么复刻一遍遍历逻辑（复制粘贴、必然漂移），要么
     没法用。抽成 computeCandidates(pack) 纯函数后，组件与自动化共用同一实现。

   口径与 panel.tsx 的 useCandidates **逐字一致**（06d 第 2.2 节）：
     · 来源：经验条目 tags.flow.startsWith('F5')，参数名命中控制参数表；
     · 建议值：从动作原文 deriveSuggestion 推（读不出给「人工判定」）；
     · 排序：证据级（台架实测数据 > 台架经验/判定工具输出 > 规程条款）优先，
       「能不能给出具体数值」退为第二键。

   2026-10-08 增强：computeCandidates 新增**可选** hints 入参（本轮未达标提示）。
   传入时命中项标 hitsFailed 并排最前，使推荐针对本轮问题；不传时行为与改造前
   完全一致（向后兼容 useAppStore.tuneOnce 的一键自动化调用）。
   =========================================================================== */
import type { RawControlParam, RawExperience, RawPack } from '../scene/pack'

export interface Candidate {
  exp: RawExperience
  param: RawControlParam
  current: number | string | boolean
  suggested: number | string
  delta: string
  /** 建议值相对当前值的方向，用于变化幅度徽标 */
  dir: 'up' | 'down' | 'none'
  rationale: string
  /**
   * 该候选是否命中本轮未达标项（2026-10-08 新增）。
   * 仅当调用方传入了 failedHints 时可能为 true；不传时恒为 false。
   */
  hitsFailed?: boolean
  /** 命中的判据 id 列表，供卡面标注「命中本轮未达标：TR-BENCH-05」 */
  hitReqIds?: string[]
}

/**
 * 本轮未达标提示（由流程 5 从 evaluateAll 的 failed 行汇总而来）。
 *
 * 为什么要这个入参：`computeCandidates` 原设计只吃场景包，推荐是一张固定的
 * 经验规则表，**不感知本轮到底判出了什么问题**——于是"改参数"与"本轮缺陷"
 * 之间没有因果。传入本集合后，命中项会被标出并排前，推荐才针对本轮问题。
 */
export interface FailedHint {
  /** 判据 id，如 TR-BENCH-05 */
  reqId: string
  /** 该判据声明的关联标签（来自 test-requirements.json 的 candidate_tags） */
  candidateTags?: string[]
}

/** 候选是否命中任一未达标提示：按「参数 key（大写）」比对判据的 candidate_tags。 */
function matchHints(c: Candidate, hints: FailedHint[]): FailedHint[] {
  const key = c.param.key.toUpperCase()
  return hints.filter((h) => (h.candidateTags ?? []).some((t) => t.toUpperCase() === key))
}

/** 从经验条目的动作原文里读出调整方向与幅度；读不出就不给数，只给动作原文。 */
function deriveSuggestion(
  p: RawControlParam,
  action: string,
): { v: number | string; delta: string; dir: Candidate['dir'] } | null {
  if (typeof p.value !== 'number') return null
  const pct = /([上下])调\s*(\d+)\s*%/.exec(action)
  if (pct) {
    const up = pct[1] === '上'
    const k = up ? 1 + Number(pct[2]) / 100 : 1 - Number(pct[2]) / 100
    return {
      v: Number((p.value * k).toPrecision(4)),
      delta: `${up ? '+' : '−'}${pct[2]}%`,
      dir: up ? 'up' : 'down',
    }
  }
  const abs = /上调\s*([\d.]+)\s*~\s*([\d.]+)\s*A/.exec(action)
  if (abs)
    return {
      v: Number((p.value + Number(abs[2])).toFixed(3)),
      delta: `+${abs[2]} ${p.unit ?? ''}`.trim(),
      dir: 'up',
    }
  const pm = /±\s*(\d+)\s*%/.exec(action)
  if (pm)
    return { v: Number((p.value * (1 + Number(pm[1]) / 100)).toPrecision(4)), delta: `±${pm[1]}%`, dir: 'up' }
  if (/加大|延长|提高/.test(action))
    return { v: Number((p.value * 1.2).toPrecision(4)), delta: '+20%', dir: 'up' }
  return null
}

/** 经验条目的证据级 → 三档序位（只是排序口径，不是概率） */
const EVIDENCE_RANK: Record<string, number> = {
  台架实测数据: 3,
  台架经验: 2,
  判定工具输出: 2,
  规程条款: 1,
}
/** 证据级 → 序位（供界面按证据级给来源徽标），与排序用同一张表。 */
export const rankOf = (e: RawExperience) => EVIDENCE_RANK[e.evidence_level] ?? 1

/**
 * 计算当前场景包的调优候选列表（与 panel.tsx useCandidates 同一口径）。
 *
 * 纯函数：不依赖 hook、不读 store，只由 pack 推算。供流程 4 界面与
 * 一键自动化的「调优重试」共用，避免两处各写一份遍历逻辑。
 *
 * @param hints 可选。本轮未达标提示集合（来自流程 5 的 evaluateAll failed 行）。
 *   传入时：命中 hint 的候选标记 hitsFailed + 排到最前，让推荐针对本轮问题；
 *   **不传时：输出顺序与标记与改造前逐字一致**，保证 tuneOnce 等既有调用方零影响。
 */
export function computeCandidates(pack: RawPack, hints?: FailedHint[]): Candidate[] {
  const byMacro = new Map<string, RawControlParam>()
  for (const p of pack.controls.parameters) byMacro.set(p.key.toUpperCase(), p)
  const out: Candidate[] = []
  for (const e of pack.experience.experiences) {
    if (!e.tags.flow?.startsWith('F5')) continue
    for (const m of e.tags.parameters ?? []) {
      const p = byMacro.get(m.toUpperCase())
      if (!p || out.some((c) => c.param.key === p.key)) continue
      const s = deriveSuggestion(p, e.action)
      out.push({
        exp: e,
        param: p,
        current: p.value ?? '—',
        suggested: s?.v ?? '人工判定',
        delta: s?.delta ?? '未给数',
        dir: s?.dir ?? 'none',
        rationale: e.action,
      })
    }
  }
  // 命中标记：只在有 hints 时计算，避免无谓开销与语义污染
  if (hints?.length) {
    for (const c of out) {
      const hits = matchHints(c, hints)
      if (hits.length) {
        c.hitsFailed = true
        c.hitReqIds = hits.map((h) => h.reqId)
      }
    }
  }
  return out.sort(
    (a, b) =>
      // 命中本轮未达标的排最前：这是「推荐针对本轮问题」的核心体现
      Number(Boolean(b.hitsFailed)) - Number(Boolean(a.hitsFailed)) ||
      rankOf(b.exp) - rankOf(a.exp) ||
      Number(typeof b.suggested === 'number') - Number(typeof a.suggested === 'number'),
  )
}
