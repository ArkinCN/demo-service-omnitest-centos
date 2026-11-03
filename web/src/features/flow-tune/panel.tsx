import { StageOperation, StageFooter } from '../../app/StageOperation'
import { useT } from '../../i18n'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowRight,
  BookOpen,
  Check,
  CircleDashed,
  GitCompareArrows,
  Layers,
  ListChecks,
  Sliders,
  Sparkles,
  Target,
  TrendingDown,
  TrendingUp,
  Waves as WavesIcon,
} from 'lucide-react'
import {
  Badge,
  Button,
  Collapsible,
  EmptyState,
  InfoTip,
  SourceTag,
  StatusDot,
  Tooltip,
  cn,
} from '../../components/ui'
import { collapseKey, useAppStore } from '../../state/useAppStore'
import { useFlowActions } from '../redline'
import { loadAdoption } from './adoptApi'
import { loadLatestVerdicts, type BackendVerdict } from '../flow-run/api'
import { getPack, sourceLine, type RawControlParam } from '../scene/pack'
import { evaluateAll, runtimeMeasures, type Evaluated } from '../flow-run/evaluate'
import { ConfigOverview } from '../../app/LeftPanel'
import { UnifiedConfigPanel } from '../../app/UnifiedConfigPanel'
import { Empty } from '../shared/bits'
import { demoFilter, type BuiltGroup, type BuiltTier } from '../shared/tiers'
import { TimeSeriesChart } from '../timeseries'
import { POWERUP_ANNOTATION, currentThresholds, loadWaves, type Wave } from '../waveforms'

/* ===========================================================================
   流程 5 · 调优确认及运行（v2 视觉）

   左栏：未达标与推荐 —— 三个大数字 + 未达标项 + 推荐参数（当前 → 建议 + 采纳）
         + 候选队列口径 + 本轮将写回的宏
   卡片：波形对照（hero，PASS/FAIL 三条叠加）/ 候选队列 / 知识依据 / 判定卡 / 参数变更

   判据真求值的逻辑一条没改：未达标项仍由 flow-run/evaluate.ts 的 evaluateAll
   求出，criterion 判成 false 才算未达标；求不出值的单列「未采集」，既不算通过
   也不算不通过，不进推荐。
   =========================================================================== */

/** 判定状态的中文文案（2026-10-08：抽成查表，避免各处三元链漏掉新状态） */
const STATE_TEXT: Record<Evaluated['state'], string> = {
  pass: '通过',
  fail: '不通过',
  missing: '未采集',
  manual: '人工判',
  not_applicable: '本台架不适用',
}

/** 标签一律收到 6 字以内，全名进 tooltip */
function short(s: string, n = 6) {
  const clean = s.replace(/[（(].*$/, '').trim()
  return clean.length > n ? `${clean.slice(0, n)}…` : clean
}

/**
 * 参数宏的短名 ≤6 字。
 * 名字里带括号代号的（速度环 PID Ki（SKI））直接取代号，否则两条速度环参数截断后
 * 会撞成同一个「速度环 PI…」；没有代号的才按 6 字截断。全名与量程一律进 tooltip。
 */
function paramShort(p: RawControlParam) {
  const tag = /[（(]([A-Za-z0-9_]{2,6})[)）]\s*$/.exec(p.name)?.[1]
  if (tag) return tag
  return short(p.name)
}

function fmt(v: number | string | boolean) {
  if (typeof v === 'number') return String(Number(v.toPrecision(4)))
  if (typeof v === 'boolean') return v ? '真' : '假'
  return v
}

/* ------------------------------------------------- 采纳状态（跨左栏与卡片共享）

   第四轮搬进 useAppStore：顶栏「采纳并回到启动测试」要读同一份勾选，
   模块级变量它读不到（08c 第零节「点不动的三处」第 1 条）。 */

function useAdopted() {
  const keys = useAppStore((s) => s.adoptedKeys)
  return useMemo(() => new Set(keys), [keys])
}

/** 勾选时把回显信息一并登记，顶栏动作条据此摆出「宏名 原值→新值」 */
function useToggleAdopt() {
  const toggle = useAppStore((s) => s.toggleAdopt)
  return (c: Candidate) =>
    toggle(c.param.key, {
      name: c.param.name,
      from: String(fmt(c.current)),
      to: String(fmt(c.suggested)),
      group: c.param.group,
    })
}

/* ------------------------------------------------------------ 候选推荐（数据） */

// 候选推荐的纯数据逻辑已抽到 ./candidates.ts（computeCandidates/rankOf），
// 组件与一键自动化的「调优重试」共用同一份实现，避免两处各写一套遍历。
import { computeCandidates, rankOf, type Candidate, type FailedHint } from './candidates'
export { computeCandidates, rankOf } from './candidates'
export type { Candidate, FailedHint } from './candidates'

/**
 * 候选列表（可选按本轮未达标项优先排序）。
 *
 * @param hints 本轮未达标提示。不传时行为与改造前完全一致（保持既有调用点语义）。
 */
export function useCandidates(hints?: FailedHint[]): Candidate[] {
  const pack = getPack()
  // hints 是每次渲染新数组，不能直接进依赖（会无限重算）；用内容指纹做 key
  const key = hints?.length ? hints.map((h) => h.reqId).sort().join(',') : ''
  return useMemo(
    () => (pack ? computeCandidates(pack, hints) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [pack, key],
  )
}

/** 从 evaluateAll 的未达标行汇总出「未达标提示」，供候选映射使用。 */
function failedHintsOf(failed: Evaluated[]): FailedHint[] {
  return failed.map((r) => ({
    reqId: r.req.id,
    candidateTags: (r.req as { candidate_tags?: string[] }).candidate_tags,
  }))
}

/* --------------------------------------------------------------- 判定（数据） */

function useWaves() {
  const pack = getPack()
  const [waves, setWaves] = useState<Wave[]>([])
  useEffect(() => {
    let alive = true
    void loadWaves().then((w) => alive && setWaves(w))
    return () => {
      alive = false
    }
  }, [pack])
  // 演示主线只对照一失败一成功两条，第三条同为失败样本、讲的是同一件事
  return pack ? demoFilter(pack.datasets, 'datasets', waves, (w) => w.id) : waves
}

/** 图例上的成败字样，不能只有样本编号 */
const verdictWord = (w: Wave) =>
  w.verdict === 'pass' ? 'PASS' : w.verdict === 'fail' ? 'FAIL' : w.verdictText

interface Shortfalls {
  waves: Wave[]
  rows: Evaluated[]
  failed: Evaluated[]
  missing: Evaluated[]
  passed: Evaluated[]
  /** 本台架不具备测量手段的判据（2026-10-08 新增，与 missing 严格区分） */
  notApplicable: Evaluated[]
}

function useShortfalls(): Shortfalls {
  const pack = getPack()
  const waves = useWaves()
  const sceneId = useAppStore((s) => s.sceneId)
  // 采纳/人工改过的控制参数：判定的 control-parameters 变量要读采纳值，
  // 否则「改了参数结论不变」（与流程 3 VerdictCard 同一口径）。
  const overrides = useAppStore((s) => s.overrides)
  const snapshotValues = useAppStore((s) => s.snapshotValues)
  // 本轮台架实测（2026-10-08 新增）：由流程 4 跑完实验后 settleRun 写入。
  // 流程 5 原先只吃离线回放波形，导致未达标项基于历史数据、与本轮实测无关；
  // 并入后与流程 3 VerdictCard 完全同口径（runMeasures 覆盖 runtimeMeasures，实测优先）。
  const runMeasures = useAppStore((s) => s.runMeasures)
  // 流程 3 落的判定表（verdict-table）。读到了就按 req_id 对齐覆盖，让流程 4 的
  // 「未达标项」真正继承流程 3 的判定；读不到（还没跑过一轮 / 后端没起）就回退
  // 前端重算，保持旧行为。
  const [backendVerdicts, setBackendVerdicts] = useState<BackendVerdict[] | null>(null)

  useEffect(() => {
    if (!sceneId) return
    void loadLatestVerdicts(sceneId)
      .then(({ verdicts }) => {
        // 幂等回填：重复写同一批值无副作用；**不检查 alive**（StrictMode 下
        // 检查它就是把成功结果丢掉）。空 verdicts 不置位，保持前端重算。
        if (verdicts.length) setBackendVerdicts(verdicts)
      })
      .catch(() => {
        // 读不到 = 正常态（还没跑过一轮），保持前端重算，不打扰界面
      })
  }, [sceneId])

  // 演示模式只在 demo_profile 点名的判据上统计，与流程 3 判定卡同一口径
  const rows = useMemo(() => {
    if (!pack) return []
    // 实测优先：runMeasures（本轮台架）覆盖 runtimeMeasures（离线回放），
    // 与流程 3 VerdictCard 的 `{...runtimeMeasures(waves,pack), ...runMeasures}` 逐字一致，
    // 避免两处口径漂移出两份结论。
    const all = evaluateAll(
      pack,
      { ...runtimeMeasures(waves, pack), ...runMeasures },
      overrides,
      snapshotValues,
    )
    // 有流程 3 的判定表就按 req_id 对齐覆盖（与流程 3 VerdictCard 的 shownRows
    // 同一算法）；没有就保持前端重算。找不到对应 req 的行不覆盖（保守，不写错）。
    const merged = backendVerdicts
      ? (() => {
          const byId = new Map(backendVerdicts.map((v) => [v.req_id, v]))
          return all.map((r) => {
            const b = byId.get(r.req.id)
            return b ? { ...r, state: b.state, note: b.note ?? r.note, missing: b.missing ?? r.missing } : r
          })
        })()
      : all
    return demoFilter(pack.requirements, 'requirements', merged, (r) => r.req.id)
  }, [pack, waves, backendVerdicts, overrides, snapshotValues, runMeasures])
  return {
    waves,
    rows,
    failed: rows.filter((r) => r.state === 'fail'),
    missing: rows.filter((r) => r.state === 'missing'),
    passed: rows.filter((r) => r.state === 'pass'),
    // 本台架不适用（2026-10-08）：单独分桶，**不进未达标清单、不进推荐**——
    // 推荐一个"本台架根本测不了"的问题没有意义。
    notApplicable: rows.filter((r) => r.state === 'not_applicable'),
  }
}

/** 卡体高度随视口缩放，图表高度跟着量出来（与样板页同一套做法） */
function useBoxHeight() {
  const [h, setH] = useState(0)
  const ro = useRef<ResizeObserver | null>(null)
  const ref = useCallback((el: HTMLDivElement | null) => {
    ro.current?.disconnect()
    if (!el) return
    const obs = new ResizeObserver(() => setH(el.clientHeight))
    obs.observe(el)
    ro.current = obs
    setH(el.clientHeight)
  }, [])
  return [ref, h] as const
}

/* ------------------------------------------------------------------ 左栏 */

/** 变化幅度小徽标：方向靠图标，不靠颜色，避免多一处状态色 */
function DeltaTag({ c }: { c: Candidate }) {
  const Icon = c.dir === 'down' ? TrendingDown : c.dir === 'up' ? TrendingUp : CircleDashed
  return (
    <span className="num inline-flex h-[20px] shrink-0 items-center gap-1 rounded-full border border-p200 bg-p50 px-1.5 text-[12px] leading-none font-medium text-p700">
      <Icon size={12} strokeWidth={2} className="block" />
      {c.delta}
    </span>
  )
}

function RecRow({ c }: { c: Candidate }) {
  const uiT = useT()

  const on = useAdopted().has(c.param.key)
  const toggleAdopt = useToggleAdopt()
  const tip = (
    <span className="block space-y-1">
      <span className="block font-medium">{uiT(c.param.name)}</span>
      <span className="num block opacity-75">
        {c.param.key.toUpperCase()}
        {c.param.min !== null ? ` · ${c.param.min}~${c.param.max}` : ''}
        {c.param.value_shell ? uiT(" · 外壳 {v1}", { v1: c.param.value_shell }) : ''}
      </span>
      <span className="block opacity-75">
        {c.exp.id} · {uiT(c.rationale)}
      </span>
      <span className="block opacity-75">{sourceLine(c.exp._source)}</span>
    </span>
  )
  return (
    <div
      className={cn(
        'flex min-h-[44px] items-center gap-2 px-4 py-1.5 transition-colors',
        on ? 'bg-p50/70' : 'hover:bg-p50/50',
      )}
    >
      <Tooltip className="min-w-0 flex-1" content={tip}>
        <span className="flex min-w-0 flex-col gap-1">
          <span className="flex min-w-0 items-center gap-1.5">
            <SourceTag source={rankOf(c.exp) >= 3 ? '文档' : '建议'} title={c.exp.evidence_level} />
            <span className="cursor-help truncate text-[13px] font-medium text-t1">
              {uiT(c.param.name) === c.param.name ? paramShort(c.param) : uiT(c.param.name)}
            </span>
          </span>
          <span className="num flex items-center gap-1.5 text-[15px] leading-none font-semibold text-t1">
            <span className="text-t3">{fmt(c.current)}</span>
            <ArrowRight size={12} strokeWidth={2} className="shrink-0 text-p400" />
            <span className="text-p700">{fmt(c.suggested)}</span>
            {c.param.unit && typeof c.suggested === 'number' ? (
              <span className="text-[12px] font-normal text-t3">{c.param.unit}</span>
            ) : null}
          </span>
        </span>
      </Tooltip>
      <DeltaTag c={c} />
      <Tooltip content={on ? uiT('取消采纳') : uiT('采纳这一项，写回仍要人点底部按钮')}>
        <button
          type="button"
          role="checkbox"
          aria-checked={on}
          aria-label={uiT("采纳 {v1}", { v1: uiT(c.param.name) })}
          onClick={() => toggleAdopt(c)}
          className={cn(
            'flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full border transition-colors [&>svg]:block',
            on ? 'border-transparent bg-p600 text-white' : 'border-line bg-white text-transparent hover:border-p300',
          )}
        >
          <Check size={13} strokeWidth={2.6} />
        </button>
      </Tooltip>
    </div>
  )
}

/** 推荐参数按改动部位切三类（06f 第 2.5 节）：改哪一段，决定这一条该不该在本轮动 */
const REC_TIER: { id: string; title: string; hit: (c: Candidate) => boolean }[] = [
  {
    id: 'rec-start',
    title: '启动阶段',
    hit: (c) => /启动|预定位|防夹|start|align/i.test(`${c.param.group}${c.param.key}`),
  },
  {
    id: 'rec-switch',
    title: '闭环切换',
    hit: (c) => /loop_rpm|smo_speed|switch/i.test(c.param.key),
  },
  { id: 'rec-tune', title: '环路整定', hit: () => true },
]

function recTiers(cands: Candidate[]): BuiltTier<Candidate>[] {
  const left = [...cands]
  const groups: BuiltGroup<Candidate>[] = []
  for (const t of REC_TIER) {
    if (t.id === 'rec-tune') continue
    const items = left.filter(t.hit)
    for (const x of items) left.splice(left.indexOf(x), 1)
    if (items.length) groups.push({ id: t.id, title: t.title, items, subs: [] })
  }
  if (left.length) groups.push({ id: 'rec-tune', title: '环路整定', items: left, subs: [] })
  return [{ id: 'rec', title: '推荐参数', groups, count: cands.length }]
}

/** 未采集按「缺哪个实测量」归并，不再逐条平铺，也不再硬截断到 10 条 */
function missingTiers(missing: Evaluated[]): BuiltTier<Evaluated>[] {
  const order: string[] = []
  const bag = new Map<string, Evaluated[]>()
  for (const r of missing) {
    const k = r.missing[0] ?? '未登记实测量'
    if (!bag.has(k)) {
      bag.set(k, [])
      order.push(k)
    }
    bag.get(k)!.push(r)
  }
  // 同一个缺失量挡住 6 条以上时再按判据分类切一层三级子组（平铺规则一）
  const groups = order.map((k, i) => {
    const items = bag.get(k)!
    const cats: string[] = []
    const byCat = new Map<string, Evaluated[]>()
    for (const r of items) {
      if (!byCat.has(r.req.category)) {
        byCat.set(r.req.category, [])
        cats.push(r.req.category)
      }
      byCat.get(r.req.category)!.push(r)
    }
    return {
      id: `miss-${i}`,
      title: k,
      items,
      subs:
        items.length > 5 && cats.length > 1
          ? cats.map((c, j) => ({ id: `miss-${i}-${j}`, title: c, items: byCat.get(c)! }))
          : [],
    }
  })
  return [{ id: 'miss', title: '未采集', groups, count: missing.length }]
}

/**
 * 刷新后把上次采纳的记录读回来。
 *
 * 「刷新仍在」这条验收靠的就是这一步：采纳时写在服务端的 param-change 产物里，
 * 进流程 4 时按场景取最近一轮读出来，回填到 store，界面上的已采纳列表就回来了。
 * 读不到（还没采纳过 / 后端没起）就保持为空，不报错——空是正常态，不是故障。
 * 但**网络层真出错要留一句控制台痕迹**，别静默。
 *
 * ⚠️⚠️ 不要用「`alive` 开关 + 守卫」这套写法（踩过两次，2026-09-24 与 09-28）：
 * 本应用开着 `<StrictMode>`（main.tsx），开发模式下 React 会
 * **mount → unmount → remount**，且返回的 promise 不保证落在哪一次上。
 * 于是出现两种失败叠加：
 *   - 首次 mount 的请求 resolve 时组件已被 unmount → `alive=false` → 结果被丢；
 *   - 若守卫在别处被置位，remount 又直接 return 不再请求。
 * 表现都是「**请求发了（或发了好几次），store 里一条都没有**」——
 * 而控制台没有任何报错，因为这不是错误，是被我们自己丢掉的成功结果。
 *
 * 正确做法：**不中断，改成幂等回填**。
 *   - 请求照发（重复一次的成本只是一次 GET）；
 *   - **不检查 `alive`**，拿到就写 store——重复写同一批值没有副作用
 *     （`applyAdopt` 是幂等赋值）；
 *   - 守卫只用来避免「同一场景反复发请求」，且**只在成功后**置位。
 * 这样无论 React 挂载几次、promise 落在哪一次，最终 store 一定有数据。
 */
function useRestoreAdoption(sceneId: string) {
  const applyAdopt = useAppStore((s) => s.applyAdopt)
  const setRunId = useAppStore((s) => s.setRunId)
  const restored = useRef<string | null>(null)
  useEffect(() => {
    if (!sceneId || restored.current === sceneId) return
    void loadAdoption(sceneId)
      .then(({ items, runId }) => {
        // ⚠️ 刻意**不检查 alive**：StrictMode 下检查它就是把成功结果丢掉。
        // 重复回填是幂等的，不会造成问题。
        restored.current = sceneId
        if (runId) setRunId(runId)
        if (items.length) applyAdopt(items)
      })
      .catch((e: unknown) => {
        // 不清 restored：下一次挂载/切换场景会再试一次，不把失败固化成「已恢复」
        console.warn('[flow-tune] 采纳记录读回失败（界面按未采纳显示）：', e)
      })
  }, [sceneId, applyAdopt, setRunId])
}

export function TuneLeftPanel() {
  const uiT = useT()

  const pack = getPack()
  const { failed, missing, passed, rows, notApplicable } = useShortfalls()
  // 候选按「本轮未达标」优先：命中项排前并标注，使推荐针对本轮问题（2026-10-08）。
  const cands = useCandidates(failedHintsOf(failed))
  const picked = useAdopted()
  const adopt = useFlowActions()('adopt-back')
  const focusReq = useAppStore((s) => s.focusReq)
  const demo = useAppStore((s) => s.demoMode)
  const sceneId = useAppStore((s) => s.sceneId)
  const adoptAllCandidates = useAppStore((s) => s.adoptAllCandidates)
  /* 2026-10-10：本流程的「已确认」是在**采纳参数写回时**由系统自动写入的，
     此前左栏没有反向出口 → 顶栏那一格打勾关不掉（用户反馈）。
     现补上反悔出口，形态与流程 1/2/5 的「解除确认」同源（同一 ConfirmFooter 形态）。
     ⚠️ 解除只取消标记；下次采纳参数时仍会照原口径再次自动确认。 */
  const locked = !!useAppStore((s) => s.confirmed.tune)
  const unconfirmFlow = useAppStore((s) => s.unconfirmFlow)
  useRestoreAdoption(sceneId)

  if (!pack) return <Empty text={uiT("场景包未加载")} />

  const takenList = cands.filter((c) => picked.has(c.param.key))
  // 一键采纳：把全部推荐参数并入已采纳集（与 RecRow 勾选同一 meta 口径）。
  const adoptAll = () =>
    adoptAllCandidates(
      cands.map((c) => ({
        key: c.param.key,
        name: c.param.name,
        from: String(fmt(c.current)),
        to: String(fmt(c.suggested)),
        group: c.param.group,
      })),
    )
  const failTier: BuiltTier<Evaluated>[] = [
    {
      id: 'fail',
      title: '未达标项',
      groups: failed.length
        ? [{ id: 'fail-all', title: '判成不通过', items: failed, subs: [] }]
        : [],
      count: failed.length,
    },
  ]

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <header className="flex h-[44px] shrink-0 items-center gap-2.5 border-b border-line-soft px-4">
        <Target size={17} strokeWidth={1.9} className="shrink-0 text-p700" />
        <h2 className="text-[16px] leading-none font-semibold tracking-tight text-t1">{uiT("未达标与推荐")}</h2>
        {/* 三个大数字退成栏头一行：精简后未达标只有一条，用不着三个 26px 的数（06d 第 3.2 节） */}
        <Tooltip
          className="ml-auto"
          content={uiT("未达标 {v1} · 已通过 {v2} · 未采集 {v3}{v4}；判据表本轮统计 {v5} 条。criterion 真判成 false 的才算未达标；缺现场实测量而求不出值的单列「未采集」；需要本台架未配置的测量手段的（如 MCU 故障寄存器、FG 转速、母线电流探头）单列「本台架不适用」并写明缺什么——三者都不进调优推荐。", { v1: failed.length, v2: passed.length, v3: missing.length, v4: notApplicable.length ? ` · 本台架不适用 ${notApplicable.length}` : '', v5: rows.length })}
        >
          {/* 演示模式只留「未达标几条」这一个数：已通过与未采集两个计数进 tooltip
              与下面的折叠组，不在栏头再摆一遍（06d 第 3.2 节） */}
          <span className="num flex cursor-help items-center gap-2 text-[12.5px]">
            <span className={cn('font-semibold', failed.length ? 'text-alert' : 'text-t1')}>
              {failed.length}
            </span>
            {demo ? (
              <span className="text-t3">{uiT("条未达标")}</span>
            ) : (
              <>
                <span className="text-t3">/</span>
                <span className="font-semibold text-t1">{passed.length}</span>
                <span className="text-t3">/</span>
                <span className="text-t3">{missing.length}</span>
              </>
            )}
          </span>
        </Tooltip>
        <InfoTip
          content={
            focusReq
              ? uiT("计数口径与流程 3 判定卡同一套求值：未达标 / 已通过 / 未采集，「本台架不适用」单列不计入前三项。本次从流程 3 判定卡的判据 {v1} 点进来。", { v1: focusReq })
              : uiT('计数口径与流程 3 判定卡同一套求值：未达标 / 已通过 / 未采集，「本台架不适用」单列不计入前三项。')
          }
        />
      </header>
      {focusReq ? (
        <div className="shrink-0 border-b border-line-soft bg-p50 px-4 py-1.5 text-[12px] text-p700">
          {uiT("来自流程 3 判定卡的未达标项 ")}<span className="num font-semibold">{focusReq}</span>
        </div>
      ) : null}

      <div className="fade-b min-h-0 flex-1 overflow-y-auto pb-2">
        <ConfigOverview flow="tune"
          key={pack.scene.id}
          count={cands.length + failed.length + missing.length}
          actions={<StageOperation title={uiT('本步操作 · 选择本轮建议')} status={uiT(`已选 {v1}/{v2} · 按需调参`, { v1: takenList.length, v2: cands.length })}>
            <p className="stage-operation-status">{failed.length ? uiT(`{v1} 条未达标，先核对依据再选择建议。`, { v1: failed.length }) : missing.length ? uiT('尚有未采集项，不能据此认为已通过。') : uiT('当前无未达标项，按需查看建议。')}</p>
            <button type="button" className="stage-operation-link" onClick={adoptAll} disabled={!cands.length || takenList.length === cands.length}>{uiT('全选建议')}</button>
            <div className="stage-operation-fields">{cands.slice(0, 2).map((candidate) => <RecRow key={candidate.param.key} c={candidate} />)}</div>
            {!cands.length ? <p>{uiT('当前没有可采纳建议。')}</p> : null}
            <p className="stage-operation-note">{uiT('勾选只是选择，不是写入。确认采纳后返回检测复测。')}</p>
          </StageOperation>}
        >
          <details className="stage-details"><summary>{uiT('参数详情与全部建议')}</summary>
          {/* 一级类只展开第一个「未达标项」；有未达标时强制展开，不许折叠掉 */}
          {failed.length ? (
            <UnifiedConfigPanel
              flow="tune"
              tiers={failTier}
              defaultOpen={0}
              lockTier={() => true}
              itemKey={(r) => r.req.id}
              flags={() => ({ alert: true })}
              tierIcon={() => <ListChecks size={15} strokeWidth={1.9} />}
              groupIcon={() => <StatusDot status="alert" />}
              render={(r) => (
                <Tooltip
                  className="w-full"
                  content={uiT("{v1} {v2} · 要求 {v3}", { v1: r.req.id, v2: r.req.name, v3: r.req.criterion_text })}
                >
                  <div className="flex min-h-[40px] w-full items-center gap-2 px-4 py-1.5">
                    <StatusDot status="alert" />
                    <span className="cursor-help truncate text-[13px] font-medium text-t1">
                      {uiT(r.req.name) === r.req.name ? short(r.req.name, 10) : uiT(r.req.name)}
                    </span>
                    <span className="num ml-auto shrink-0 text-[12px] text-t3">{r.req.id}</span>
                  </div>
                </Tooltip>
              )}
            />
          ) : (
            <Collapsible
              level={1}
              icon={<ListChecks size={15} strokeWidth={1.9} />}
              title={uiT("未达标项")}
              storeKey={collapseKey('tune', 'fail')}
              defaultOpen
              stat={{ total: 0 }}
            >
              <div className="px-4 py-3">
                {/* 不编数据：本轮 20 条可求值判据一条都没有现场实测量，
                    「0 条不通过」不是「都合格」，是根本没判。这句话要写在屏幕上，
                    不能让观众把空态读成通过。回放与候选队列照常保留。 */}
                <EmptyState
                  icon={<Check size={24} strokeWidth={1.6} />}
                  title={uiT("本轮无现场实测，判据未求值")}
                  hint={uiT("未采集 {v1} 条：判据要的现场实测量（母线电流、转速、力、位移、声压级）本轮没有采，因此既判不出通过也判不出不通过。屏幕上的时序与候选是既有数据的回放，不是本轮实测。", { v1: missing.length })}
                />
              </div>
            </Collapsible>
          )}

          {/* 推荐参数：默认折叠，组内按改动部位切三类。
              「一键采纳」按钮挂在「推荐参数」分类 tab 右侧（tierRight 插槽）：
              点一下把全部推荐参数并入已采纳集，免去逐条勾选，便于直接进下一步。 */}
          {cands.length ? (
            <UnifiedConfigPanel
              flow="tune"
              tiers={recTiers(cands)}
              // 一级类里只有「未达标项」默认展开，推荐与未采集一律折叠
              defaultOpen={-1}
              itemKey={(c) => c.param.key}
              flags={(c) => ({ filled: picked.has(c.param.key) })}
              tierIcon={() => <Sparkles size={15} strokeWidth={1.9} />}
              groupIcon={() => <Sliders size={14} strokeWidth={1.9} />}
              tierRight={(tier) =>
                tier.id === 'rec' ? (
                  <Tooltip
                    content={
                      takenList.length === cands.length
                        ? uiT("推荐参数 {v1} 项已全部勾选", { v1: cands.length })
                        : uiT("勾选全部 {v1} 项推荐参数（已选 {v2} 项）", { v1: cands.length, v2: takenList.length })
                    }
                  >
                    <Button
                      size="sm"
                      variant="default"
                      icon={<Check size={13} strokeWidth={2.4} />}
                      onClick={adoptAll}
                      disabled={takenList.length === cands.length}
                      data-action="adopt-all"
                    >
                      {uiT("全选建议")}</Button>
                  </Tooltip>
                ) : null
              }
              render={(c) => <RecRow c={c} />}
            />
          ) : (
            <Collapsible
              level={1}
              icon={<Sparkles size={15} strokeWidth={1.9} />}
              title={uiT("推荐参数")}
              storeKey={collapseKey('tune', 'rec')}
              defaultOpen={false}
              stat={{ total: 0 }}
            >
              <div className="px-4 py-3">
                <EmptyState icon={<Sparkles size={24} strokeWidth={1.6} />} title={uiT("经验库无可对上的项")} />
              </div>
            </Collapsible>
          )}

          {/* 未采集：按缺哪个实测量归并，不截断 */}
          {missing.length ? (
            <UnifiedConfigPanel
              flow="tune"
              tiers={missingTiers(missing)}
              defaultOpen={-1}
              itemKey={(r) => r.req.id}
              tierIcon={() => <CircleDashed size={15} strokeWidth={1.9} />}
              groupIcon={() => <CircleDashed size={14} strokeWidth={1.9} />}
              render={(r) => (
                <Tooltip
                  className="w-full"
                  content={uiT("{v1} {v2} · 缺 {v3}", { v1: r.req.id, v2: r.req.name, v3: r.missing.join('、') })}
                >
                  <div className="flex min-h-[36px] w-full items-center gap-2 px-4 py-1">
                    <StatusDot status="na" />
                    <span className="cursor-help truncate text-[13px] text-t2">{uiT(r.req.name) === r.req.name ? short(r.req.name, 10) : uiT(r.req.name)}</span>
                    <span className="num ml-auto shrink-0 text-[12px] text-t3">{uiT("缺")}{r.missing.length}</span>
                  </div>
                </Tooltip>
              )}
            />
          ) : null}
          </details>
        </ConfigOverview>
      </div>

      <StageFooter
        label={uiT('确认采纳并返回检测')}
        disabled={adopt.disabled || !takenList.length}
        onClick={adopt.onClick}
        reason={!takenList.length ? uiT('先选择要采纳的建议。') : uiT('仍需写参确认；返回后复测，不代表固件已生效。')}
        secondary={locked ? <button type="button" onClick={() => unconfirmFlow('tune')}>{uiT('解除采纳确认')}</button> : null}
      />
    </div>
  )
}

/* -------------------------------------------------- 卡片 · 波形对照（hero） */

function WaveOverlay({ full }: { full?: boolean }) {
  const uiT = useT()

  const pack = getPack()
  const waves = useWaves()
  const [box, boxH] = useBoxHeight()
  if (!waves.length)
    return <EmptyState icon={<WavesIcon size={24} strokeWidth={1.5} />} title={uiT("读取时序")} />
  const peak = Math.max(...waves.map((w) => w.metrics.peak))
  const unit = waves[0].unit

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-1.5 pb-1.5">
        {waves.map((w) => (
          <Tooltip
            key={w.id}
            content={uiT("{v1} · {v2} · 峰值 {v3} {v4} @ {v5} s", { v1: w.title, v2: w.verdictText, v3: w.metrics.peak.toFixed(2), v4: w.unit, v5: w.metrics.peakAt.toFixed(2) })}
          >
            <span
              className={cn(
                'num inline-flex h-[22px] cursor-help items-center gap-1.5 rounded-full border px-2 text-[12px] font-medium',
                w.verdict === 'fail'
                  ? 'border-line bg-white text-t2'
                  : 'border-p200 bg-p50 text-p700',
              )}
            >
              <span
                className="h-[3px] w-[12px] shrink-0 rounded-full"
                style={{ background: w.series.color }}
              />
              {w.id}
              <span className={cn('font-semibold', w.verdict === 'fail' ? 'text-alert' : 'text-p700')}>
                {verdictWord(w)}
              </span>
            </span>
          </Tooltip>
        ))}
        {pack?.caps.syntheticData ? (
          <Badge tone="warn" title={uiT(pack.caps.syntheticBanner)}>
            {uiT("合成")}</Badge>
        ) : null}
        {/* Δ峰值不进演示分镜：精简后前后对照靠曲线形状讲（06d 第 3.2 节），放大态仍给 */}
        {full ? (
          <span className="num ml-auto text-[12px] text-t3">
            {uiT("Δ峰值 ")}{(peak - Math.min(...waves.map((w) => w.metrics.peak))).toFixed(2)} {unit}
          </span>
        ) : null}
      </div>
      <div ref={box} className="min-h-0 flex-1">
        <TimeSeriesChart
          series={waves.map((w) => w.series)}
          annotations={[POWERUP_ANNOTATION]}
          thresholds={currentThresholds(full, peak)}
          showOverlayLabels={!!full}
          legend={!!full}
          cursor={!!full}
          height={full ? 400 : Math.max(120, boxH - 20)}
          xLabel={uiT("时间 s · 纵轴 {v1}", { v1: unit || '原始量' })}
        />
      </div>
    </div>
  )
}

/* ---------------------------------------------------------- 卡片 · 候选队列 */

/** 盲试候选的槽位上限：auto-startup-tune 规程写死 10 个固定候选，耗尽即转人工。 */
const QUEUE_CAP = 10

function CandidateQueue({ full }: { full?: boolean }) {
  const uiT = useT()

  const { failed } = useShortfalls()
  const cands = useCandidates(failedHintsOf(failed))
  const picked = useAdopted()
  const demo = useAppStore((s) => s.demoMode)
  const hitCount = cands.filter((c) => c.hitsFailed).length
  if (!cands.length) return <EmptyState icon={<Layers size={24} strokeWidth={1.5} />} title={uiT("无候选")} />
  const cur = cands.findIndex((c) => !picked.has(c.param.key))
  // 放大态逐个铺满 10 个槽位；卡内空间有限，只铺命中的候选，空槽压成一行，
  // 免得把半行硬切在卡底。
  // 演示模式（06d 第 3.2 节）首屏只铺当前这一条候选，另外几条与 10 个槽位一并收成
  // 一行「另 n 条」，点开卡或切全量模式才逐条铺。
  const lite = demo && !full
  const shownCands = lite ? cands.slice(0, 1) : cands
  const free = Math.max(0, QUEUE_CAP - cands.length)
  const slots = Array.from({ length: full ? QUEUE_CAP : shownCands.length })

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div
        className="no-scrollbar min-h-0 flex-1 overflow-y-auto"
        style={{
          maskImage: 'linear-gradient(to bottom, #000 calc(100% - 16px), transparent 100%)',
          WebkitMaskImage: 'linear-gradient(to bottom, #000 calc(100% - 16px), transparent 100%)',
        }}
      >
        <ol className="relative">
          {/* 竖向连线：把 10 个槽位串成一条推进路径 */}
          <span className="absolute top-1.5 bottom-1.5 left-[6px] w-px bg-line-soft" aria-hidden />
          {slots.map((_, i) => {
            const c = shownCands[i]
            const on = c ? picked.has(c.param.key) : false
            const isCur = i === cur
            return (
              <li key={i} className="relative flex items-center gap-2.5 py-[2px] pl-0">
                <span
                  className={cn(
                    'relative z-10 flex h-[13px] w-[13px] shrink-0 items-center justify-center rounded-full border-2 bg-surface transition-colors',
                    on
                      ? 'border-p600 bg-p600'
                      : isCur
                        ? 'border-p600'
                        : c
                          ? 'border-line'
                          : 'border-dashed border-line',
                  )}
                >
                  {isCur ? <span className="h-[5px] w-[5px] rounded-full bg-p600" /> : null}
                </span>
                {c ? (
                  <Tooltip
                    className="min-w-0 flex-1"
                    content={uiT("{v1}（{v2}） · {v3} {v4}{v5}", { v1: c.param.name, v2: c.param.key.toUpperCase(), v3: c.exp.id, v4: c.rationale, v5: c.hitsFailed
                        ? ` · 命中本轮未达标：${(c.hitReqIds ?? []).join('、')}`
                        : uiT(' · 来自规程固定候选表（本轮未命中）') })}
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span
                        className={cn(
                          'cursor-help truncate text-[13px]',
                          on ? 'font-medium text-t1' : isCur ? 'font-medium text-p700' : 'text-t2',
                        )}
                      >
                        {uiT(c.param.name) === c.param.name ? paramShort(c.param) : uiT(c.param.name)}
                      </span>
                      {/* 命中本轮未达标：如实标出来，让「为什么推荐它」有据可查 */}
                      {c.hitsFailed ? (
                        <Badge tone="soft" className="shrink-0">
                          {uiT("命中")}</Badge>
                      ) : null}
                      <span className="num ml-auto shrink-0 text-[12px] text-t3">{c.delta}</span>
                    </span>
                  </Tooltip>
                ) : (
                  <span className="text-[13px] text-t3">{uiT("空位")}</span>
                )}
              </li>
            )
          })}
          {!full && (free || lite) ? (
            <li className="relative flex items-center gap-2.5 py-[2px]">
              <span className="relative z-10 h-[13px] w-[13px] shrink-0 rounded-full border-2 border-dashed border-line bg-surface" />
              <span className="text-[13px] text-t3">{lite ? uiT('另有候选') : uiT('空位')}</span>
              <span className="num ml-auto shrink-0 text-[12px] text-t3">
                {lite ? cands.length - 1 : free}
              </span>
            </li>
          ) : null}
        </ol>
      </div>
      <div className="flex shrink-0 items-center gap-1.5 border-t border-line-soft pt-1.5">
        <span className="num text-[12px] text-t3">
          {cands.length}
          <span className="text-t3">/{QUEUE_CAP}</span>
        </span>
        {hitCount ? (
          <span className="num text-[12px] text-p700">{uiT("命中本轮 ")}{hitCount}</span>
        ) : null}
        {lite ? null : <span className="text-[12px] text-t3">{uiT("上限 10 · 耗尽转人工")}</span>}
        <InfoTip
          content={uiT("候选来自经验库中流程为「F5 调优确认及运行」的条目，按证据级排序（台架实测数据 > 台架经验/判定工具输出 > 规程条款）。{v1}固定候选表口径出自客户端规程 auto-startup-tune（盲试最多 10 个候选，每个只偏离基线一个轴；耗尽仍不行判 need_human 转人工，不得创建第 11 个候选）。", { v1: hitCount
              ? `本轮已按未达标项优先排序：${hitCount} 条命中（标「命中」），命中的候选建议直接针对本轮判出的问题。`
              : uiT('本轮无未达标项命中，以下为可用候选清单。') })}
        />
      </div>
    </div>
  )
}

/* ---------------------------------------------------------- 卡片 · 知识依据 */

/**
 * 现象收成关键词：经验条目的 symptom 写的是整句（「起转起来了，但切闭环瞬间掉速或失步」），
 * 卡面只留第一个短句并压到 8 字，整句与原因、动作、结果一律在 tooltip 里。
 */
function symptomKey(sym: string) {
  const first = sym.split(/[，,。；;：:]/)[0]
  // ⚠️ 截断长度随语言：中文按 8 字，英文按 24 字符。
  // 英文一个单词就 5~8 字符，沿用 8 会截出「98 bench…」这种看不懂的碎片（实测踩到）。
  return short(first, /[\u4e00-\u9fff]/.test(first) ? 8 : 24)
}

function EvidencePanel({ full }: { full?: boolean }) {
  const uiT = useT()

  const cands = useCandidates()
  const picked = useAdopted()
  const demo = useAppStore((s) => s.demoMode)
  if (!cands.length) return <EmptyState icon={<BookOpen size={24} strokeWidth={1.5} />} title={uiT("无命中条目")} />

  // 一条经验可能带出多个参数，这里按经验去重。演示模式首屏只留排在最前的那一条
  // （证据级「台架实测数据」的 EXP-009），另外两条折到卡内滚动区之外，
  // 切全量或放大才给（06d 第 3.2 节「知识库依据的另外 2 条经验 折叠到二级」）。
  const seen = new Set<string>()
  const uniq = cands.filter((c) => (seen.has(c.exp.id) ? false : (seen.add(c.exp.id), true)))
  const hits = uniq.slice(0, full ? 12 : demo ? 1 : 3)
  const rest = uniq.length - hits.length

  return (
    <div
      className="no-scrollbar flex h-full min-h-0 w-full flex-col gap-1.5 overflow-y-auto"
      style={{
        maskImage: 'linear-gradient(to bottom, #000 calc(100% - 12px), transparent 100%)',
        WebkitMaskImage: 'linear-gradient(to bottom, #000 calc(100% - 12px), transparent 100%)',
      }}
    >
      {hits.map((c) => {
        const rank = rankOf(c.exp)
        const on = picked.has(c.param.key)
        return (
          <Tooltip
            key={c.exp.id}
            className="w-full"
            content={
              <span className="block space-y-1">
                <span className="block font-medium">
                  {c.exp.id} · {uiT(c.exp.symptom)}
                </span>
                <span className="block opacity-80">{uiT("原因 · ")}{uiT(c.exp.cause)}</span>
                <span className="block opacity-80">{uiT("动作 · ")}{uiT(c.rationale)}</span>
                <span className="block opacity-80">{uiT("结果 · ")}{uiT(c.exp.result)}</span>
                <span className="block opacity-70">{sourceLine(c.exp._source)}</span>
              </span>
            }
          >
            <div className="flex w-full shrink-0 cursor-help items-center gap-2.5 rounded-tps border border-line-soft px-2.5 py-1.5 transition-colors hover:border-p200 hover:bg-p50/60">
              <span
                className={cn(
                  'flex h-[24px] w-[24px] shrink-0 items-center justify-center rounded-tpx [&>svg]:block',
                  on ? 'bg-p700 text-white' : 'bg-p50 text-p700',
                )}
              >
                <BookOpen size={13} strokeWidth={1.9} />
              </span>
              <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-t1">
                {/* ⚠️ 必须「先翻译整句、再截断」：symptom 在词典里是**全句**，
                    先截成首段会命中不了词条（此前写成 uiT(symptomKey(...)) 译不出） */}
                {symptomKey(uiT(c.exp.symptom))}
              </span>
              {/* 证据级直接写字：三格条一格一格数不清是什么意思（06d 第 3.2 节） */}
              <Badge tone={rank >= 3 ? 'soft' : 'neutral'} className="shrink-0">
                {uiT(c.exp.evidence_level)}
              </Badge>
              <Badge tone="neutral" mono className="shrink-0">
                {c.exp.id}
              </Badge>
            </div>
          </Tooltip>
        )
      })}
      {rest > 0 ? (
        <Tooltip
          className="w-full"
          content={uiT("另外 {v1} 条命中经验证据级更低，演示主线不讲；切「全量」或放大这张卡可逐条看。", { v1: rest })}
        >
          <span className="num block shrink-0 cursor-help px-2.5 py-1 text-[12px] text-t3">
            {uiT("另 ")}{rest} {uiT(" 条")}</span>
        </Tooltip>
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------ 卡片 · 判定卡 */

function VerdictCard({ full }: { full?: boolean }) {
  const uiT = useT()

  const pack = getPack()
  const { rows, failed, missing, passed, notApplicable } = useShortfalls()
  if (!pack) return <Empty text={uiT("场景包未加载")} />
  const judged = passed.length + failed.length
  // 不适用项排在未采集之前：它是「有明确结论」的项（已说明缺什么设备），
  // 混在未采集后面会让人以为还有悬而未决的判据（2026-10-08）。
  const list = full ? rows : [...failed, ...passed, ...notApplicable, ...missing].slice(0, 5)

  // 环：可求值判据里已经判出结果的占比。左栏已经给过三个大数字，这里换成环 + 中心数，
  // 同一条信息不在一屏里用同一种形态说第二遍。
  const evaluable = pack.requirements.evaluable_count || 1
  const R = 24
  const C = 2 * Math.PI * R
  const ratio = Math.min(1, judged / evaluable)

  const Legend = ({ n, label, tone }: { n: number; label: string; tone: 'ok' | 'bad' | 'mute' }) => (
    <span className="flex items-center gap-1.5">
      <span
        className={cn(
          'h-[7px] w-[7px] shrink-0 rounded-full',
          tone === 'ok' ? 'bg-p600' : tone === 'bad' ? 'bg-alert' : 'bg-t3/40',
        )}
      />
      <span className="text-[12px] text-t3">{label}</span>
      <span className={cn('num ml-auto text-[13px] font-semibold', tone === 'bad' && n > 0 ? 'text-alert' : 'text-t1')}>
        {n}
      </span>
    </span>
  )

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div className="flex shrink-0 items-center gap-3 pb-2">
        <span className="relative shrink-0">
          <svg width="62" height="62" viewBox="0 0 62 62">
            <circle cx="31" cy="31" r={R} fill="none" stroke="var(--p-100)" strokeWidth="6" />
            <circle
              cx="31"
              cy="31"
              r={R}
              fill="none"
              stroke="var(--p-600)"
              strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={`${C * ratio} ${C}`}
              transform="rotate(-90 31 31)"
              style={{ transition: 'stroke-dasharray .4s cubic-bezier(.22,.75,.3,1)' }}
            />
          </svg>
          <span className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="num text-[20px] leading-none font-semibold text-t1">{judged}</span>
            <span className="num text-[12px] text-t3">/{evaluable}</span>
          </span>
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <Legend n={passed.length} label={uiT("通过")} tone="ok" />
          <Legend n={failed.length} label={uiT("不通过")} tone="bad" />
          {/* 优先展示「本台架不适用」：本台架只有风扇+示波器，多数判据结构上测不了。
              这类项已写明缺什么设备，比笼统的「未采集」更利于决策（2026-10-08）。 */}
          {notApplicable.length ? (
            <Legend n={notApplicable.length} label={uiT("本台架不适用")} tone="mute" />
          ) : (
            <Legend n={missing.length} label={uiT("未采集")} tone="mute" />
          )}
        </span>
        <InfoTip
          content={uiT("已求值 {v1} / {v2} 条可求值判据，全表 {v3} 条。{v4}{v5}", { v1: judged, v2: pack.requirements.evaluable_count, v3: rows.length, v4: notApplicable.length
              ? `「本台架不适用」${notApplicable.length} 条：缺 MCU 故障寄存器 / FG 转速信号 / 母线电流探头 / 程控电源等测量手段，逐条 tooltip 写明缺什么，不参与通过统计。`
              : '', v5: judged === 0
              ? uiT('本轮一条都判不了：判据要的现场实测量（母线电流、转速、力、位移、声压级）得由台架传感器现场采，本轮只回放了登记进包的曲线，不拿别的数顶替。')
              : '' })}
        />
      </div>
      <div
        className="no-scrollbar min-h-0 flex-1 overflow-y-auto"
        style={{
          maskImage: 'linear-gradient(to bottom, #000 calc(100% - 16px), transparent 100%)',
          WebkitMaskImage: 'linear-gradient(to bottom, #000 calc(100% - 16px), transparent 100%)',
        }}
      >
        {list.map((r) => (
          <Tooltip
            key={r.req.id}
            className="w-full"
            content={uiT("{v1} {v2} · {v3}{v4}", { v1: r.req.id, v2: r.req.name, v3: r.req.criterion_text, v4: r.state === 'not_applicable' && r.notApplicableReason
                ? ` · 本台架不适用：${r.notApplicableReason}`
                : r.missing.length
                  ? ` · 缺 ${r.missing.join('、')}`
                  : '' })}
          >
            <div className="flex w-full items-center gap-2 border-b border-line-soft py-[5px] last:border-b-0">
              <StatusDot status={r.state === 'pass' ? 'done' : r.state === 'fail' ? 'alert' : 'na'} />
              <span className="cursor-help truncate text-[12.5px] text-t1">{uiT(r.req.name) === r.req.name ? short(r.req.name, 12) : uiT(r.req.name)}</span>
              <span className="num ml-auto shrink-0 text-[12px] text-t3">{uiT(STATE_TEXT[r.state])}</span>
            </div>
          </Tooltip>
        ))}
      </div>
    </div>
  )
}

/** 缩略包络：小卡里不画坐标轴，只留曲线本身的形状与 t=0 的位置 */
function Spark({ w }: { w: Wave }) {
  const uiT = useT()
  const { x, y } = w.series
  const d = useMemo(() => {
    const N = 160
    const n = y.length
    if (!n) return { top: '', bottom: '', zero: 0 }
    let span = 0
    for (let i = 0; i < n; i += 1) span = Math.max(span, Math.abs(y[i]))
    span = span || 1
    const top: string[] = []
    const bot: string[] = []
    for (let b = 0; b < N; b += 1) {
      const s0 = Math.floor((b * n) / N)
      const s1 = Math.max(s0 + 1, Math.floor(((b + 1) * n) / N))
      let lo = Infinity
      let hi = -Infinity
      for (let i = s0; i < s1 && i < n; i += 1) {
        if (y[i] < lo) lo = y[i]
        if (y[i] > hi) hi = y[i]
      }
      if (!Number.isFinite(lo)) continue
      top.push(`${b},${20 - (hi / span) * 19}`)
      bot.push(`${b},${20 - (lo / span) * 19}`)
    }
    const t0 = x.length ? (-Number(x[0]) / (Number(x[x.length - 1]) - Number(x[0]))) * N : 0
    return { top: top.join(' '), bottom: bot.reverse().join(' '), zero: t0 }
  }, [x, y])

  return (
    <svg viewBox="0 0 160 40" preserveAspectRatio="none" className="h-full w-full" aria-label={uiT("{v1} 波形缩略", { v1: w.id })}>
      <line x1="0" y1="20" x2="160" y2="20" stroke="var(--tp-line)" strokeWidth="0.5" />
      <line
        x1={d.zero}
        y1="1"
        x2={d.zero}
        y2="39"
        stroke="var(--tp-line)"
        strokeWidth="0.6"
        strokeDasharray="2 2"
      />
      <polygon points={`${d.top} ${d.bottom}`} fill="var(--p-300)" opacity="0.55" />
      <polyline points={d.top} fill="none" stroke="var(--p-600)" strokeWidth="0.6" />
    </svg>
  )
}

/* ------------------------------------------------------------ 卡片 · 本轮波形 */

/**
 * 本轮那一条曲线的读数。
 * hero 已经把两轮叠在一起对照了，这张卡只盯本轮：取和判定同一条曲线
 * （evaluate 的 runtimeMeasures 也是这么挑的：优先非 PASS 的那条），
 * 给峰值、稳态 RMS、首次响应三个读数 + 一条不带坐标轴的缩略曲线。
 */
function RoundWave({ full }: { full?: boolean }) {
  const uiT = useT()

  const waves = useWaves()
  const [box, boxH] = useBoxHeight()
  if (!waves.length)
    return <EmptyState icon={<WavesIcon size={24} strokeWidth={1.5} />} title={uiT("读取时序")} />
  const w = waves.find((x) => x.verdict !== 'pass') ?? waves[0]

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div className="flex shrink-0 items-baseline gap-2 pb-1">
        <span className="num text-[26px] leading-none font-semibold tracking-tight text-t1">
          {w.metrics.peak.toFixed(2)}
        </span>
        <span className="text-[12px] text-t3">{w.unit || uiT('原始量')} {uiT(" 峰值")}</span>
        <Tooltip content={uiT("{v1} {v2} · {v3} · 峰值出现在 {v4} s", { v1: w.id, v2: w.title, v3: w.verdictText, v4: w.metrics.peakAt.toFixed(2) })}>
          <span className="num ml-auto cursor-help text-[12px] text-t3">{w.id}</span>
        </Tooltip>
      </div>
      <div className="flex shrink-0 items-center gap-3 pb-1.5">
        <Tooltip content={uiT("末段 0.5 s 的均方根，代表稳态")}>
          <span className="num cursor-help text-[12px] text-t3">
            {uiT("稳态 ")}<span className="text-[13px] font-semibold text-t1">{w.metrics.steadyRms.toFixed(2)}</span>
          </span>
        </Tooltip>
        <Tooltip content={uiT("首次越过本条曲线量程 5% 的时刻")}>
          <span className="num cursor-help text-[12px] text-t3">
            {uiT("首响")}{' '}
            <span className="text-[13px] font-semibold text-t1">
              {Number.isNaN(w.metrics.firstResponseMs) ? '—' : `${Math.round(w.metrics.firstResponseMs)} ms`}
            </span>
          </span>
        </Tooltip>
      </div>
      <div ref={box} className="min-h-0 flex-1">
        {full ? (
          <TimeSeriesChart
            series={[w.series]}
            annotations={[POWERUP_ANNOTATION]}
            thresholds={currentThresholds(true, w.metrics.peak)}
            height={Math.max(220, boxH - 6)}
            xLabel={uiT("时间 s · 纵轴 {v1}", { v1: w.unit || '原始量' })}
          />
        ) : (
          <Spark w={w} />
        )}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------ 卡片 · 参数变更 */

/**
 * 本轮要写回固件的宏，逐行给「宏名 · 原值 → 新值」。
 * 取已勾选采纳的候选；一条都没勾时按队列顺序给前三条待采纳的，并在卡头标明是待采纳。
 * 写回口径：只改数值外壳里的那个数，量纲与括号写法照抄原值——这张卡显示的就是要改的那一行。
 */
function ParamChanges({ full }: { full?: boolean }) {
  const uiT = useT()

  const all = useCandidates()
  const picked = useAdopted()
  const demo = useAppStore((s) => s.demoMode)
  const numeric = all.filter((c) => typeof c.suggested === 'number')
  const chosen = numeric.filter((c) => picked.has(c.param.key))
  // 演示主线一次只动一项（06d 第 2.1 节），首屏就只列那一项
  const rows = (chosen.length ? chosen : numeric).slice(0, full ? 10 : demo ? 1 : 3)
  const pending = chosen.length === 0

  if (!rows.length)
    return <EmptyState icon={<GitCompareArrows size={24} strokeWidth={1.5} />} title={uiT("无可写回的宏")} />

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div className="flex shrink-0 items-center gap-2 pb-1.5">
        <Tooltip
          className="min-w-0 flex-1"
          content={uiT("已采纳 {v1} 项 / 候选 {v2} 项。写回沿用原数值外壳与量纲，只改括号里的那个数；落盘与重编重烧一律由人点，助手不写回。", { v1: chosen.length, v2: numeric.length })}
        >
          <span className="flex cursor-help items-baseline gap-1.5">
            <span className="num text-[26px] leading-none font-semibold tracking-tight text-t1">
              {chosen.length}
            </span>
            <span className="text-[12px] text-t3">
              {demo && !full ? (pending ? uiT('项已采纳 · 待采纳') : uiT('项已采纳 · 待写回')) : uiT("项已采纳 / 候选 {v1}", { v1: numeric.length })}
            </span>
          </span>
        </Tooltip>
        {demo && !full ? null : (
          <Tooltip content={uiT("写回沿用原数值外壳与量纲，只改括号里的那个数；落盘与重编重烧一律由人点，助手不写回。")}>
            <span className="num ml-auto cursor-help text-[12px] text-t3">
              {pending ? uiT('待采纳') : uiT('待写回')}
            </span>
          </Tooltip>
        )}
      </div>
      <div className="no-scrollbar min-h-0 flex-1 overflow-y-auto">
        {rows.map((c) => (
          <Tooltip
            key={c.param.key}
            className="w-full"
            content={uiT("{v1}（{v2}）· 依据 {v3} · {v4}", { v1: c.param.name, v2: c.param.key.toUpperCase(), v3: c.exp.id, v4: c.rationale })}
          >
            <div className="flex w-full cursor-help items-center gap-2 border-b border-line-soft py-[7px] last:border-b-0">
              <span
                className={cn(
                  'h-[7px] w-[7px] shrink-0 rounded-full',
                  picked.has(c.param.key) ? 'bg-p600' : 'bg-p200',
                )}
              />
              <span className="num min-w-0 flex-1 truncate text-[12.5px] font-medium text-t1">
                {c.param.key.toUpperCase()}
              </span>
              <span className="num shrink-0 text-[12px] text-t3">{fmt(c.current)}</span>
              <ArrowRight size={12} strokeWidth={2} className="shrink-0 text-t3" />
              <span className="num shrink-0 text-[13px] font-semibold text-t1">
                {fmt(c.suggested)}
                {c.param.unit ? (
                  <span className="ml-0.5 text-[12px] font-normal text-t3">{c.param.unit}</span>
                ) : null}
              </span>
            </div>
          </Tooltip>
        ))}
      </div>
    </div>
  )
}

/* -------------------------------------------------------------- 卡槽登记 */

export const tuneCards = {
  history: WaveOverlay,
  candidates: CandidateQueue,
  verdict: VerdictCard,
  evidence: EvidencePanel,
  timeseries: RoundWave,
  'param-changes': ParamChanges,
}
