import type { RawPack, RawRequirement } from '../scene/pack'
import type { Wave } from '../waveforms'

/* ===========================================================================
   判据求值。

   test-requirements.json 给了四样东西，判定卡因此可以真求值而不是写死：
   - `evaluable`  这条判据的表达式能不能自动求值；false 的只登记、不判
   - `criterion`  JavaScript 表达式（criterion_syntax 字段声明），求值结果为布尔
   - `criterion_text` 人读版本
   - `variables`  每个自由变量的来源，四种：
       runtime.measure     现场实测量，必须真采到，采不到就判「未采集」
       threshold           本条自己的 threshold 字段
       control-parameters  control-parameters.json 里按 key 取的当前配置值
       constant            编译期常量（故障位掩码一类），字面值写在变量自己身上

   规矩：凡是有 runtime.measure 变量拿不到的，一律判「未采集」并列出缺哪几个，
   不拿别的数顶替、不给结论。一条判据只要有一个量没采到，它就既不是通过也不是
   不通过——这条在调优流程里同样成立，未采集的项不进未达标清单、不进推荐。

   第五种状态「本台架不适用」（2026-10-08 新增，见 declaredNotApplicable）：
   场景包可显式声明某判据在本台架无测量手段（bench_applicable:false + 原因），
   求值时短路返回 not_applicable，与 missing 严格区分——不给"本该能测却没测到"
   的误导，也不进未达标清单与推荐。
   =========================================================================== */

export type VerdictState = 'pass' | 'fail' | 'missing' | 'manual' | 'not_applicable'

export interface Evaluated {
  req: RawRequirement
  state: VerdictState
  /** 求值用到的量，用于卡面展示 */
  used: { name: string; value: number | boolean | string; unit?: string | null }[]
  /** 缺哪些现场实测量（中文名） */
  missing: string[]
  /** 合取式里还有子句因缺量判不了，但已有子句为假，结论仍成立 */
  partial?: boolean
  /** 结论是怎么来的，逐字写在卡面 tooltip 上，不让观众自己猜 */
  note?: string
  error?: string
  /**
   * 「本台架不适用」的具体原因（2026-10-08 新增）。
   *
   * 与 `missing` 的区别（必须守住，不能混）：
   *   · missing        = 「本该采到却没采到」——暗示采集链路可能有问题，要查；
   *   · not_applicable = 「本台架结构上不具备该测量手段」——需要加装设备，不是故障。
   * 两者对决策的含义完全不同，混用会误导。故此原因取自场景包的显式声明，不由运行时推断。
   */
  notApplicableReason?: string
}

/**
 * 场景包声明「本台架不具备该测量手段」时，求值前先短路返回。
 *
 * 为什么用**显式声明**而不是运行时推断（如"缺测且阈值不可达"）：
 * 推断会随本轮数据波动，同一判据时而不适用、时而未采集，结论不可复现，
 * 演示与验收都站不住。声明一次、稳定复现，且原因可追溯到缺哪台设备。
 *
 * 诚实底线：本函数只**读**声明，不判断"该不该不适用"——是否不适用由场景包
 * 依据实际台架配置写死，代码不替业务做这个决定。
 */
function declaredNotApplicable(req: RawRequirement): string | null {
  const r = req as RawRequirement & { bench_applicable?: boolean; bench_inapplicable_reason?: string }
  if (r.bench_applicable === false) {
    return r.bench_inapplicable_reason || '本台架未配置该项测量手段'
  }
  return null
}

type Scalar = number | boolean | string | (number | string)[]

/**
 * 本轮能提供的现场实测量。
 *
 * 只从真的采到的波形里取，采到什么给什么，一个都不推算：
 * 本轮只回放了主信号一条曲线，能给的就是它的峰值与稳态两项，而且只在判据要的
 * 物理量与波形的物理量对得上时才给。对不上的（例如判据要母线电流、波形是相电流）
 * 一律不给，让那条判据落到「未采集」，不拿相电流冒充母线电流。
 */
export function runtimeMeasures(waves: Wave[], pack?: RawPack): Record<string, number> {
  const out: Record<string, number> = {}

  // 批次统计量：datasets.json 的 package_stats 登记的是真实批次的标注结果
  // （散热风扇包 = 20260811 启动故障 98 次实验，101 次尝试、98 次已标注、
  //   67 次 PASS、30 次 FAIL、1 次作废，_source 指向那份分析报告）。
  // 这是已经采到并标注过的量，不是推算，所以可以进求值；没有登记这一段的
  // 场景包（例如合成的玻璃升降器包）一个数都不给，让判据落到「未采集」。
  const st = pack?.datasets.package_stats as Record<string, unknown> | undefined
  if (st && typeof st.pass === 'number' && typeof st.labeled === 'number') {
    out.pass_count = st.pass as number
  }

  const w = waves.find((x) => x.verdict !== 'pass') ?? waves[0]
  if (!w) return out
  // 波形的物理量写在 Wave.unit 上（由 datasets.json 的列定义推出），
  // 这里只登记「这条曲线本身是什么量」，判据要别的量时匹配不上就是缺。
  if (w.unit === 'A') {
    out.phase_current_peak_a = Number(w.metrics.peak.toFixed(4))
    out.phase_current_steady_a = Number(w.metrics.steadyRms.toFixed(4))
  }
  return out
}

/** 本轮实测量的出处，写在卡面上，避免观众把批次统计当成本轮现采 */
export function measureOrigin(pack: RawPack | null): string | null {
  const st = pack?.datasets.package_stats as Record<string, unknown> | undefined
  if (!st || typeof st.pass !== 'number') return null
  return `起停通过次数取自已标注批次：尝试 ${st.attempts_total} 次、已标注 ${st.labeled} 次、通过 ${st.pass} 次、失败 ${st.fail} 次，出自 datasets.json 的 package_stats（源为 20260811 启动故障 98 次实验分析报告）。这是既有批次的标注结果，不是本轮现场重采。`
}

function toScalar(v: unknown): Scalar | undefined {
  if (typeof v === 'number' || typeof v === 'boolean' || typeof v === 'string') return v
  if (Array.isArray(v) && v.every((x) => typeof x === 'number' || typeof x === 'string'))
    return v as (number | string)[]
  return undefined
}

/** 变量取值：按 source 分派到四个来源，取不到返回 undefined */
function resolve(
  pack: RawPack,
  req: RawRequirement,
  name: string,
  v: { source: string; ref?: string; value?: unknown },
  measures: Record<string, number>,
  controlValues: Record<string, number | string>,
): Scalar | undefined {
  switch (v.source) {
    case 'threshold':
      return toScalar((req.threshold as Record<string, unknown> | null)?.[name])
    case 'constant':
      return toScalar(v.value)
    case 'control-parameters': {
      // ref 形如 control-parameters.<key>，key 是 control-parameters.json 的 parameters[].key。
      // 判据要的「当前配置值」必须**优先读采纳/人工改过的值**，否则改了参数、判定结论
      // 永远不变（这是「改了再测还是不通过」的根因之一）。采纳值由 controlValues 传入
      // （已在 evaluateAll 里按回落链 run.cp.* → init.cp.* 取好），这里只做一层查表，
      // 查不到才回落到场景包原值。
      const key = (v.ref ?? '').split('.').pop() ?? name
      if (controlValues[key] !== undefined) return toScalar(controlValues[key])
      const p = pack.controls.parameters.find((x) => x.key === key)
      return toScalar(p?.value)
    }
    default:
      // runtime.measure 的常规取数：只认真采到的 measures，采不到就是 undefined → 未采集。
      //
      // 唯一例外（target_rpm）：场景包 test-requirements.json 的 runtime_measures.target_rpm
      // 自述 obtained_by =「NONEMODE 下等于 control-parameters.nonemode_speed；PWMMODE 下由
      // 占空比查调速曲线得到」。这是场景包设计上就规定的取值规则，接入它不是编数据：
      //   - 本轮真采到 target_rpm → 直接用（优先级最高，真机才有）；
      //   - 没采到、但 speed_mode 为 NONEMODE → 回落读 controlValues.nonemode_speed（采纳/人工
      //     改过的「无调速模式目标转速」），这样改 nonemode_speed 重测，TR-START-02 结论会真实变化；
      //   - speed_mode 为 PWMMODE/VSPMODE 或没配 nonemode_speed → 保持未采集（调速曲线数据不在
      //     本仓库，不编一个占空比换算值）。
      if (name === 'target_rpm') {
        const mode = controlValues.speed_mode
        if (mode === 'NONEMODE' && controlValues.nonemode_speed !== undefined) {
          return toScalar(controlValues.nonemode_speed)
        }
      }
      return toScalar(measures[name])
  }
}

/**
 * 把 store 里的 overrides / snapshotValues 映射成「控制参数 key → 当前生效值」。
 *
 * overrides 的键是 `${flow}.${group}.${sub}.${item}`（控制参数即 `run.cp.<group>.<key>`），
 * 而判据 variables 里 control-parameters 只带参数 key（如 `nonemode_speed`），不带 group。
 * 所以这里遍历场景包参数，逐个按回落链取当前值：
 *   本流程 override（run.cp.*）→ 上游 init 内存（init.cp.*）→ 上游 init 快照（init.cp.*）
 * 与 useAppStore.resolveParamKey 同一套回落口径（不回查 getPack，纯由传入数据算），
 * 但独立实现、不 import store，保持本文件纯函数、可单测。
 */
export function controlValueMap(
  pack: RawPack,
  overrides?: Record<string, number | string>,
  snapshotValues?: Record<string, number | string>,
): Record<string, number | string> {
  const out: Record<string, number | string> = {}
  if (!overrides && !snapshotValues) return out
  for (const p of pack.controls.parameters) {
    const own = `run.cp.${p.group}.${p.key}`
    const up = `init.cp.${p.group}.${p.key}`
    if (overrides && overrides[own] !== undefined) out[p.key] = overrides[own]
    else if (overrides && overrides[up] !== undefined) out[p.key] = overrides[up]
    else if (snapshotValues && snapshotValues[up] !== undefined) out[p.key] = snapshotValues[up]
  }
  return out
}

/**
 * 把一条判据的顶层 `&&` 拆成子句；括号内部的 `&&` 不拆。
 *
 * 为什么要拆：判据多半是合取式。合取式里只要有一个子句已经判成假，整条就是假，
 * 剩下那几个子句缺不缺实测量都改不了这个结论（假 ∧ 未知 = 假）。这不是拿别的数
 * 顶替，也不是猜，是逻辑本身允许的短路。反过来，已算的子句全为真而还有子句缺量时，
 * 整条仍然判不了，照旧落「未采集」——真 ∧ 未知 = 未知。
 */
function clausesOf(expr: string): string[] {
  const out: string[] = []
  let depth = 0
  let buf = ''
  for (let i = 0; i < expr.length; i += 1) {
    const ch = expr[i]
    if (ch === '(') depth += 1
    if (ch === ')') depth -= 1
    if (depth === 0 && ch === '&' && expr[i + 1] === '&') {
      out.push(buf)
      buf = ''
      i += 1
      continue
    }
    // 顶层出现 || 就不拆了：或式没有这条短路规则
    if (depth === 0 && ch === '|' && expr[i + 1] === '|') return [expr]
    buf += ch
  }
  out.push(buf)
  return out.map((x) => x.trim()).filter(Boolean)
}

/** 子句里用到了哪几个自由变量（只认这条判据 variables 段登记过的名字） */
function varsIn(clause: string, names: string[]): string[] {
  return names.filter((n) => new RegExp(`\\b${n}\\b`).test(clause))
}

export function evaluateAll(
  pack: RawPack,
  measures: Record<string, number>,
  /** 采纳/人工改过的控制参数值（store.overrides，键 run.cp.* / init.cp.*） */
  overrides?: Record<string, number | string>,
  /** 已读回的配置快照值（store.snapshotValues，键 init.cp.*），换页/刷新后仍在 */
  snapshotValues?: Record<string, number | string>,
): Evaluated[] {
  const legend = pack.requirements.runtime_measures ?? {}
  // control-parameters 变量要读采纳值：先按回落链把 store 值映射成 key→value。
  const controlValues = controlValueMap(pack, overrides, snapshotValues)
  return pack.requirements.requirements.map<Evaluated>((req) => {
    // 本台架不适用：场景包显式声明优先于一切求值（含 evaluable 检查）。
    // 这类判据不是"判不了"，是"本台架没有测量它的手段"——按 missing 展示会误导决策。
    const naReason = declaredNotApplicable(req)
    if (naReason) {
      return { req, state: 'not_applicable', used: [], missing: [], notApplicableReason: naReason }
    }
    if (req.evaluable === false || !req.criterion || !req.variables) {
      return { req, state: 'manual', used: [], missing: [] }
    }
    const scope: Record<string, Scalar> = {}
    const used: Evaluated['used'] = []
    const missing: string[] = []
    for (const [name, v] of Object.entries(req.variables)) {
      const value = resolve(pack, req, name, v, measures, controlValues)
      if (value === undefined) {
        missing.push(legend[name]?.name ?? v.desc ?? name)
        continue
      }
      scope[name] = value
      // 阈值与常量不进「用到的量」展示位，那里只放实测与配置值，免得卡面全是阈值
      if (v.source !== 'threshold' && v.source !== 'constant')
        used.push({ name: v.desc ?? name, value: value as number | boolean | string, unit: v.unit })
    }
    const names = Object.keys(scope)
    // criterion 来自本地场景包，不是用户输入；criterion_globals 只允许 Math 与字面量
    const run = (expr: string) => {
      const fn = new Function('Math', ...names, `"use strict"; return (${expr});`)
      return Boolean(fn(Math, ...names.map((n) => scope[n])))
    }
    if (missing.length) {
      // 合取短路：缺量的判据里，凡是已经能算的子句算一遍；有一个为假就足以判不通过。
      const all = Object.keys(req.variables)
      try {
        for (const cl of clausesOf(req.criterion)) {
          const need = varsIn(cl, all)
          if (!need.length || need.some((n) => !(n in scope))) continue
          if (!run(cl)) {
            return {
              req,
              state: 'fail',
              used,
              missing,
              partial: true,
              note: `按已采到的量判：「${cl}」不成立，这一条就是不通过。还缺 ${missing.join('、')}，但合取式里已有一项为假，补齐也翻不过来。`,
            }
          }
        }
      } catch {
        /* 子句算不动就当没算，照旧落未采集，不编结论 */
      }
      return { req, state: 'missing', used, missing }
    }
    try {
      const ok = run(req.criterion)
      return { req, state: ok ? 'pass' : 'fail', used, missing: [] }
    } catch (e) {
      return { req, state: 'missing', used, missing: [], error: String(e) }
    }
  })
}
