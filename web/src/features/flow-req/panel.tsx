import { ConfigSuggestionButton } from '../config-suggestions/ConfigSuggestionButton'
import { requirementIdOf } from '../config-suggestions/protocol'
import { useT } from '../../i18n'
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router'
import {
  Activity,
  Boxes,
  CheckSquare,
  CircuitBoard,
  Gauge,
  Layers,
  ListChecks,
  Pencil,
  Power,
  RotateCw,
  ShieldCheck,
  SlidersHorizontal,
  Square,
  Timer,
  Wind,
  Workflow as WorkflowIcon,
  Wrench,
  Zap,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import {
  Badge,
  Collapsible,
  EmptyState,
  InfoTip,
  Tooltip,
  cn,
} from '../../components/ui'
import { getPack, statusOf, type RawPack, type RawRequirement } from '../scene/pack'
import { useAppStore } from '../../state/useAppStore'
import { loadLatestBaseline, persistBaseline } from './baselineApi'
import { setBaselineIds } from './baselineStore'
import { ConfigOverview } from '../../app/LeftPanel'
import { UnifiedConfigPanel } from '../../app/UnifiedConfigPanel'
import { ConfirmFooter, Empty } from '../shared/bits'
import { buildTiers, readTiers } from '../shared/tiers'
import { listPackWorkflows, loadPackWorkflow, type WfEntry } from '../scene/workflows'
import { WorkflowCanvas } from '../workflow'
import type { WorkflowModel } from '../workflow'
import '../workflow/styles/workflow.css'
import './wf-embed.css'

/* ===========================================================================
   流程 3 · 测试需求确认（v2 视觉，对齐流程 4 样板页）

   左栏「测试要求」：test-requirements.json 的 26 条判据按 10 类折叠，
     每行 = 勾选框 + 短名 + 阈值小徽标 + 可求值圆点，全句进 tooltip。
   卡片：工作流画布（hero，横跨两格，真画布）/ 工作流库（按组折叠）/
     判定表 / 知识依据 / 历史成绩。

   数据来源一律不动：判据读 pack.requirements，工作流经 src/features/scene/workflows.ts
   （散热风扇包是 public/data/wfw/** 的 68 个 .wfw，玻璃升降器包是包内 assets JSON）。
   =========================================================================== */

/** 散热风扇包默认打开的那条；别的包没有同名条目时取第一条 */
const DEFAULT_WF = 'HV_StaticStart'

/** 标签一律收到 6 字以内，全名进 tooltip */
function short(s: string, n = 6) {
  const clean = s.replace(/[（(].*$/, '').trim()
  return clean.length > n ? `${clean.slice(0, n)}…` : clean
}

/* ==================================================== 选中集 / 焦点（跨卡共享） */

let sel = {
  scene: '',
  ids: new Set<string>(),
  focus: null as string | null,
  /**
   * 这个场景的 `ids` 是否已由**服务端基线**接管。
   *
   * 为什么要这个标记：`ensureSel`（同步，渲染期跑）与 `applyBaseline`（异步，
   * 请求回来后跑）都会写 `ids`，无标记时**谁后跑谁赢**。实测症状是
   * 「解除确认后纳入数从 24 变回 26」——读回的值被全选覆盖。
   * 置真后 `ensureSel` 不再写 ids，竞态从根上消失。
   * 换场景包时重置为 false（旧基线不适用于新场景）。
   */
  restored: false,
}
let selVersion = 0
const selListeners = new Set<() => void>()
const bumpSel = () => {
  selVersion += 1
  selListeners.forEach((l) => l())
}
function replaceSelectedIds(ids: Set<string>) {
  sel = { ...sel, ids }
  bumpSel()
}
const subSel = (l: () => void) => {
  selListeners.add(l)
  return () => {
    selListeners.delete(l)
  }
}
const getSelVersion = () => selVersion

/**
 * 需求基线默认把全部判据纳入本轮，取消勾选是「移出基线」的动作。
 *
 * ⚠️ 只在**换场景包**时重置，且**服务端基线已读回时不再覆盖**。
 *
 * 历史坑（两轮）：
 *   ① 原写法「scene 不同就全选」，而刷新后 `sel.scene` 是空串 → 触发重置
 *      → 基线被打回全选，人取消的勾选全复活（「刷新又初始化」）。
 *   ② 加读回后又出现**竞态**：`ensureSel`（同步，在渲染期跑）与
 *      `applyBaseline`（异步，请求回来后跑）都改 `sel.ids`，谁后跑谁赢。
 *      实测症状是「解除确认后纳入数变回 26」——读回的值被全选覆盖掉了。
 * 现在用 `sel.restored` 显式表达「这个场景的基线已被服务端值接管」：
 * 一旦为真，`ensureSel` 就**不再写 ids**（只补 focus），竞态从根上消失。
 */
function ensureSel(pack: RawPack) {
  if (sel.scene === pack.scene.id) return
  sel.scene = pack.scene.id
  // 换包：基线属于上一个场景，标记作废，允许重新全选
  sel.restored = false
  sel.ids = new Set(pack.requirements.requirements.map((r) => r.id))
  sel.focus = pack.requirements.requirements[0]?.id ?? null
  bumpSel()
}

/** 用服务端读回的基线覆盖勾选集。返回是否真的应用了。 */
function applyBaseline(includedIds: string[]) {
  const pack = getPack()
  if (!pack) return false
  // 只保留场景包里存在的 id：基线可能是旧版场景包落的，多出来的 id 直接丢，
  // 不往 sel 里塞孤儿键（否则切包时会带过去，表现为「多了几条不存在的判据」）。
  const known = new Set(pack.requirements.requirements.map((r) => r.id))
  // ⚠️ 允许读到「空基线」：`included_count = 0` 是合法状态
  //（人把全部判据都移出本轮），不能因为 `kept` 为空就当成读失败而放弃。
  sel.ids = new Set(includedIds.filter((id) => known.has(id)))
  // 显式标记：这个场景的 ids 从此由服务端基线决定，`ensureSel` 不得再覆盖。
  sel.restored = true
  bumpSel()
  return true
}

export function toggleReq(id: string) {
  if (sel.ids.has(id)) sel.ids.delete(id)
  else sel.ids.add(id)
  bumpSel()
}

function focusReq(id: string) {
  sel.focus = id
  bumpSel()
}

function useSel() {
  const pack = getPack()
  useSyncExternalStore(subSel, getSelVersion, getSelVersion)
  useEffect(() => {
    if (pack) ensureSel(pack)
  }, [pack])
  return sel
}

/* ================================================ 工作流选中态（画布与库共享） */

const wf = {
  scene: '',
  entries: [] as WfEntry[],
  model: null as WorkflowModel | null,
  active: null as string | null,
}
let wfVersion = 0
const wfListeners = new Set<() => void>()
const bumpWf = () => {
  wfVersion += 1
  wfListeners.forEach((l) => l())
}
const subWf = (l: () => void) => {
  wfListeners.add(l)
  return () => {
    wfListeners.delete(l)
  }
}
const getWfVersion = () => wfVersion

function ensureWf(pack: RawPack) {
  if (wf.scene === pack.scene.id) return
  wf.scene = pack.scene.id
  wf.entries = []
  wf.model = null
  wf.active = null
  bumpWf()
  void (async () => {
    const entries = await listPackWorkflows(pack)
    if (wf.scene !== pack.scene.id) return
    wf.entries = entries
    const first = entries.find((e) => e.name === DEFAULT_WF) ?? entries[0]
    wf.active = first?.id ?? null
    bumpWf()
    const model = first ? await loadPackWorkflow(pack, first) : null
    if (wf.scene !== pack.scene.id) return
    wf.model = model
    bumpWf()
  })()
}

async function openWf(pack: RawPack, e: WfEntry) {
  wf.active = e.id
  wf.model = null
  bumpWf()
  const model = await loadPackWorkflow(pack, e)
  if (wf.active !== e.id) return
  wf.model = model
  bumpWf()
}

function useWf() {
  const pack = getPack()
  useSyncExternalStore(subWf, getWfVersion, getWfVersion)
  useEffect(() => {
    if (pack) ensureWf(pack)
  }, [pack])
  return wf
}

/* --------------------------------------------------------------- 阈值徽标 */

const numText = (v: number) => String(Number(v))

/** 一条判据的阈值压成一个 ≤8 字的小徽标；阈值位空着的显示「待填」 */
const TH_RULES: [RegExp, (v: number) => string][] = [
  [/rpm_min$/, (v) => `≥ ${numText(v)} rpm`],
  [/max_error_rpm$/, (v) => `≤ ${numText(v)} rpm`],
  [/^(required_full_pass|required_pass|required_count)$/, (v) => `${numText(v)} 次`],
  [/pct(_max)?$/, (v) => `± ${numText(v)}%`],
  [/^max_s$/, (v) => `≤ ${numText(v)} s`],
  [/duration_min$/, (v) => `${numText(v)} min`],
  [/ratio_max$/, (v) => `≤ ${numText(v)}×`],
  [/^ratio$/, (v) => `× ${numText(v)}`],
  [/_thr_v$/, (v) => `${numText(v)} V`],
  [/_a$/, (v) => `${numText(v)} A`],
  [/_deg$/, (v) => `± ${numText(v)}°`],
  [/^gears$/, (v) => `${numText(v)} 档`],
  [/^(trig_count|runs)$/, (v) => `${numText(v)} 次`],
  [/_ms(_max)?$/, (v) => `${numText(v)} ms`],
]

function thresholdBadge(r: RawRequirement): string | null {
  const th = r.threshold
  if (!th) return null
  // Trial count is the acceptance target; do not replace it with a speed threshold.
  for (const key of ['required_full_pass', 'required_pass', 'required_count', 'runs', 'trig_count']) {
    const value = th[key]
    if (typeof value === 'number') return `${numText(value)} 次`
  }
  for (const [re, fmt] of TH_RULES) {
    for (const [k, v] of Object.entries(th)) {
      if (!re.test(k)) continue
      if (typeof v === 'number') return fmt(v)
      if (v === null) return '待填'
    }
  }
  for (const v of Object.values(th)) {
    if (Array.isArray(v) && v.every((x) => typeof x === 'string')) {
      const joined = (v as string[]).join('/')
      return /[一-龥]/.test(joined) ? `${v.length} 档` : joined
    }
  }
  return null
}

/* ------------------------------------------------------------- 分组图标 */

const CAT_ICON: [RegExp, LucideIcon][] = [
  [/^性能|基本性能/, Gauge],
  [/^工况/, Wind],
  [/安全与自检|电气与防护/, ShieldCheck],
  [/启动|自锁/, Zap],
  [/转速/, Gauge],
  [/响应|时间/, Timer],
  [/电流|电压/, Activity],
  [/调速|PWM/i, SlidersHorizontal],
  [/风/, Wind],
  [/保护/, ShieldCheck],
  [/硬件|自检/, CircuitBoard],
  [/可靠|耐久|环境/, RotateCw],
  [/防夹|力/, ShieldCheck],
  [/规则|检验/, ListChecks],
]
const iconOf = (name: string, size = 14) => {
  const Ic = catIcon(name)
  return <Ic size={size} strokeWidth={1.9} />
}

const catIcon = (name: string): LucideIcon => {
  for (const [re, ic] of CAT_ICON) if (re.test(name)) return ic
  return ListChecks
}

const WF_GROUP_ICON: [RegExp, LucideIcon][] = [
  [/静止|启动/, Zap],
  [/上下电|POWER/i, Power],
  [/PWM|占空/i, SlidersHorizontal],
  [/风/, Wind],
  [/子流程/, Boxes],
  [/专项|其他/, Wrench],
]
const wfGroupIcon = (name: string): LucideIcon => {
  for (const [re, ic] of WF_GROUP_ICON) if (re.test(name)) return ic
  return WorkflowIcon
}

/** 电压档短名：索引里写的是 LV / SV / HV / MIXED / HSLV / N/A */
const VOLT_SHORT: Record<string, string> = {
  'N/A': '未标',
  MIXED: '三档',
  HSLV: '高低',
  未标电压等级: '未标',
  低压: 'LV',
  标准电压: 'SV',
  高压: 'HV',
}
const voltShort = (v: string) => VOLT_SHORT[v] ?? (v.length > 4 ? '三档' : v)

/* ------------------------------------------------------------------ 左栏 */

function ReqRow({ r }: { r: RawRequirement }) {
  const uiT = useT()

  const s = useSel()
  const confirmed = !!useAppStore((st) => st.confirmed.req)
  const on = s.ids.has(r.id)
  const manual = r.evaluable === false
  const th = thresholdBadge(r)
  const focused = s.focus === r.id

  const detail = (
    <span className="block space-y-1">
      <span className="block font-medium">{uiT(r.name)}</span>
      <span className="num block opacity-75">{r.id}</span>
      <span className="block opacity-75">{uiT(r.criterion_text)}</span>
      {manual ? <span className="block opacity-75">{uiT("人工判 · ")}{uiT(r.not_evaluable_reason)}</span> : null}
      {r._placeholder ? (
        <span className="block opacity-75">
          {confirmed ? uiT('已确认知悉 · 源材料未给出阈值，本次未补值') : uiT('待确认 · 源材料未给出阈值')}
        </span>
      ) : null}
      {statusOf(r) ? <span className="block opacity-75">{uiT("待核实 · ")}{statusOf(r)}</span> : null}
    </span>
  )

  return (
    <div
      className={cn(
        'flex min-h-[34px] items-center gap-2 px-4 py-1 transition-colors hover:bg-p50/60',
        focused && 'bg-p50/80',
      )}
    >
      <button
        type="button"
        role="checkbox"
        aria-checked={on}
        aria-label={uiT(r.name)}
        onClick={() => toggleReq(r.id)}
        className={cn(
          'flex h-[17px] w-[17px] shrink-0 items-center justify-center rounded-[5px] border transition-colors [&>svg]:block',
          on ? 'border-transparent bg-p600 text-white' : 'border-line bg-white text-transparent hover:border-p300',
        )}
      >
        <CheckSquare size={11} strokeWidth={3} />
      </button>

      <Tooltip className="min-w-0 flex-1" content={detail}>
        <button
          type="button"
          onClick={() => focusReq(r.id)}
          className="flex min-w-0 w-full items-center gap-1.5 text-left"
        >
          <span
            className={cn(
              'truncate text-[13px] font-medium',
              on ? 'text-t1' : 'text-t2',
            )}
          >
            {uiT(r.name) === r.name ? short(r.name, 8) : uiT(r.name)}
          </span>
        </button>
      </Tooltip>

      {th ? (
        <span
          className={cn(
            'num shrink-0 rounded-full border px-1.5 text-[12px] leading-[17px]',
            th === '待填'
              ? 'border-dashed border-line text-t3'
              : 'border-p200 bg-p50 text-p700',
          )}
        >
          {uiT(th)}
        </span>
      ) : null}

      <span
        title={manual ? uiT('只能人工判') : uiT('可自动求值')}
        className={cn(
          'h-[7px] w-[7px] shrink-0 rounded-full',
          manual ? 'bg-white ring-1 ring-inset ring-line' : 'bg-p600',
        )}
      />
    </div>
  )
}

/**
 * 刷新后把上次确认的需求基线读回来。
 *
 * 与流程 4 的 `useRestoreAdoption`、流程 1 的 `loadLatestSnapshot` 是同一套路：
 * **不依赖内存**，按场景取最近若干轮，找 `requirement-baseline` 产物。
 * 读不到（还没确认过）是正常态，不打搅人。
 *
 * ⚠️ 不检查 `alive`，改成**幂等回填**（见 flow-tune/panel.tsx 同款说明）。
 * 本应用开着 `<StrictMode>`，React 会 mount → unmount → remount，
 * promise 不保证落在哪一次上；用 `alive` 中断就会把成功结果丢掉，
 * 表现为「请求发了但 store 一直是空的」，且控制台无任何报错。
 * 回填是幂等赋值，重复执行没有副作用。
 */
function useRestoreBaseline(sceneId: string) {
  const restored = useRef<string | null>(null)
  useEffect(() => {
    if (!sceneId || restored.current === sceneId) return
    void loadLatestBaseline(sceneId)
      .then((hit) => {
        if (!hit) return
        restored.current = sceneId
        // **只回填勾选集，不碰确认态**（2026-09-28 用户实测反馈修）。
        //
        // 原来这里跟着调 `confirmFlow('req')`，于是「服务端有基线产物」
        // 被当成「本次应显示已确认」——只要历史上确认过一次，
        // 之后每次进这个页面都是已锁，人没机会自己按一次。
        // 确认态改由 localStorage 记录决定（见 useAppStore 的 LS_CONFIRMED）：
        // 人按过就一直是已确认，没按过就保持未确认——与产物在不在无关。
        applyBaseline(hit.baseline.included_ids)
        useAppStore.getState().setRunId(hit.runId)
        // 同一份基线也灌给「跨流程镜像」：流程 3 渲染期要同步读它来定判据行
        // （见 baselineStore.ts 的说明）。不与界面勾选态共享引用，各持一份数组。
        //
        // ⚠️ 但**人主动解除过**（`confirmed.req === false`）时不灌：解除的语义是
        // 「本轮基线不再有效」，此时被服务端旧产物重新点亮就等于解除没生效。
        // 与 `Shell.useGlobalBaseline` 同一条判据，两处必须一致。
        if (useAppStore.getState().confirmed.req !== false) {
          setBaselineIds([...hit.baseline.included_ids])
        }
      })
      .catch((e: unknown) => {
        // 网络层真出错要留痕，不静默；但界面按「未确认」显示即可
        console.warn('[flow-req] 需求基线读回失败（界面按未确认显示）：', e)
      })
  }, [sceneId])
}

/**
 * 确认基线的落库动作 —— **唯一的入口**。
 *
 * 抽成独立 hook 的原因（不是为了好看）：Hooks 不允许条件调用，
 * 而 `ReqLeftPanel` 在场景包未加载时会提前 `return <Empty>`。
 * 把 `useCallback` 留在组件里就必须挪到提前返回之前，于是拿不到
 * `reqs.length` 这类运行期值。抽出来后组件在**有 pack 之后**才调用它，
 * 依赖值都是现成的，没有 ref、没有 render 期读写（那两类写法
 * React 编译器会丢弃，3-T/3-V 都栽过）。
 *
 * 语义与流程 1「确认并锁定」一致：
 *   - 单一入口（顶栏那颗只改内存的已按用户要求移除）；
 *   - 落库成功才置确认态，失败必须可见（不能让人以为存好了）。
 *
 * ⚠️ 「确认」只冻结「本轮判哪几条」，**不代表**阈值缺失（`_placeholder`）
 * 这件事被解决——那是源材料的问题。界面照旧标注，只把措辞从
 * 「待确认」改成「已确认 · 阈值待补」，不让事实消失。
 */
function useConfirmBaseline(opts: {
  sceneId: string
  ids: Set<string>
  total: number
  onDone: () => void
}) {
  const { sceneId, ids, total, onDone } = opts
  const setNotice = useAppStore((st) => st.setNotice)
  const [saving, setSaving] = useState(false)

  const run = useCallback(async () => {
    setSaving(true)
    try {
      const { runId, baseline } = await persistBaseline({
        sceneId,
        runId: useAppStore.getState().runId,
        includedIds: [...ids],
        totalCount: total,
        operator: useAppStore.getState().benchUser,
      })
      useAppStore.getState().setRunId(runId)
      useAppStore.getState().confirmFlow('req')
      // 确认成功才灌镜像（失败不灌：没落库的基线不该被下游当成本轮基线）
      setBaselineIds([...baseline.included_ids])
      setNotice(
        `已确认需求基线：纳入 ${baseline.included_count}/${baseline.total_count} 条判据` +
          `（轮次 ${runId.slice(0, 8)}），已写入轮次产物，后续流程可取用`,
      )
      // 跳转下一步：与流程 1「确认并锁定后自动跳转」保持一致
      onDone()
    } catch (e) {
      // 落库失败必须看得见：没存上是没存上，不能让人以为确认好了
      setNotice(
        `确认失败（基线未持久化，刷新后会还原）：${e instanceof Error ? e.message : String(e)}`,
      )
    } finally {
      setSaving(false)
    }
  }, [sceneId, ids, total, setNotice, onDone])

  return { run, saving }
}

export function ReqLeftPanel() {
  const uiT = useT()

  const pack = getPack()
  const s = useSel()
  const nav = useNavigate()
  const sceneId = useAppStore((st) => st.sceneId)
  const confirmed = !!useAppStore((st) => st.confirmed.req)
  const setNotice = useAppStore((st) => st.setNotice)
  const unconfirmFlow = useAppStore((st) => st.unconfirmFlow)

  useRestoreBaseline(sceneId)

  // ⚠️ 所有 hook 必须无条件调用，所以这里**先算默认值、不提前 return**。
  // 之前把 `useConfirmBaseline` 放在 `if (!pack) return` 之后，
  // oxlint 的 rules-of-hooks 直接报「Hook is called conditionally」——
  // 场景包未加载时 hook 数就少一个，React 会破坏调用顺序。
  const reqs = pack?.requirements.requirements ?? []
  const total = reqs.length
  const { run: confirmBaseline, saving } = useConfirmBaseline({
    sceneId,
    ids: s.ids,
    total,
    onDone: () => nav('/run'),
  })

  /** 解除确认：回可编辑态。不清勾选值（与流程 1 的「解除确认」同一口径）。 */
  const release = () => {
    unconfirmFlow('req')
    // 解除确认 = 本轮基线不再有效 → 镜像同步清空，
    // 否则流程 3 会继续按一份「已经被人解除掉的基线」过滤判据。
    setBaselineIds(null)
    setNotice('已解除确认：可继续调整纳入范围，改完再点「确认基线」')
  }

  // hook 全部就位后再做空值分支
  if (!pack) return <Empty text={uiT("场景包未加载")} />
  const all = s.ids.size === total

  // 一级类收敛到三类（性能 / 工况 / 安全与自检），骨架取自场景包
  // test-requirements.json 的 group_tiers；十个原分类降为二级组，超 5 条的再切三级。
  const tiers = buildTiers<RawRequirement>(
    readTiers(pack.requirements),
    reqs,
    (r) => r.id,
    (r) => r.category,
  )

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <header className="flex h-[44px] shrink-0 items-center gap-2.5 border-b border-line-soft px-4">
        <ListChecks size={17} strokeWidth={1.9} className="shrink-0 text-p700" />
        <h2 className="text-[16px] leading-none font-semibold tracking-tight text-t1">{uiT("测试要求")}</h2>
        <span className="num text-[12px] text-t3">{reqs.length}</span>
        <div className="ml-auto flex items-center gap-1.5">
          <Badge tone="soft" mono>
            {uiT("已选 ")}{s.ids.size}
          </Badge>
          <Tooltip content={all ? uiT('全部移出本轮') : uiT('全部纳入本轮')}>
            <button
              type="button"
              aria-label={all ? uiT('全部移出本轮') : uiT('全部纳入本轮')}
              onClick={() => {
                replaceSelectedIds(all ? new Set<string>() : new Set(reqs.map((r) => r.id)))
              }}
              className="flex h-[26px] w-[26px] items-center justify-center rounded-tps border border-line bg-white text-t3 transition-colors hover:border-p300 hover:text-p700 [&>svg]:block"
            >
              {/*
                ⚠️ 2026-10-09 用户口径：**图标反映当前选择状态**，不是「点下去会做什么」。
                此前写反了（全选时显示空框 `Square`、非全选时显示 `CheckSquare`），
                与人的直觉相反。现改为：
                  · 全部已选（`all`）→ **打勾 ✓**（`CheckSquare`）
                  · 未全选 / 全不选 → **空格子**（`Square`）
                文案（tooltip / aria-label）仍是「点下去会做什么」的动作语义，两者本就该分开。
              */}
              {all ? <CheckSquare size={13} strokeWidth={1.9} /> : <Square size={13} strokeWidth={1.9} />}
            </button>
          </Tooltip>
        </div>
      </header>

      <div className="fade-b min-h-0 flex-1 overflow-y-auto pb-2">
        <ConfigOverview flow="req" assist={<ConfigSuggestionButton stage="req" pending={saving} getSelection={() => sel.ids} updateSelection={(changes) => {
            const next = new Set(sel.ids)
            // 字段 id 是 `req.<判据id>`，用 protocol 里的唯一映射还原判据 id；
            // 此前写死 slice(4)，前缀一变就静默切错（交接坑 #3）。
            for (const change of changes) { const id = requirementIdOf(change.field_id); if (change.after) next.add(id); else next.delete(id) }
            replaceSelectedIds(next)
            setBaselineIds(null)
          }} />}
          key={pack.scene.id}
          count={total}
        >
          <UnifiedConfigPanel
            flow="req"
            tiers={tiers}
            // 一级类只展开第一个，其余折叠（06b 第 1.2 节）
            defaultOpen={0}
            itemKey={(r) => r.id}
            render={(r) => <ReqRow r={r} />}
            // 组头三态：已选进本轮基线记「已填」，源材料存疑记「待核实」。
            // 「只能人工判」不是异常，不占暗红名额，它由行尾的空心点与栏底的
            // 「可自动求值 n/m」交代。
            flags={(r) => ({
              filled: s.ids.has(r.id),
              pending: !!(r._status || r._placeholder),
            })}
            tierIcon={(t) => iconOf(t, 15)}
            groupIcon={(t) => iconOf(t)}
          />
        </ConfigOverview>
      </div>

      <div className="shrink-0 px-4 pt-2">
        <Tooltip
          content={uiT("可自动求值 {v1} 条，只能人工判 {v2} 条（排程规则与目视检查一类，不硬凑成布尔表达式）。组头的暗红计数即「只能人工判」的条数。", { v1: pack.requirements.evaluable_count, v2: pack.requirements.not_evaluable_count })}
        >
          <span className="flex w-full items-center gap-2 text-[12px] text-t3">
            <span className="num">
              {pack.requirements.evaluable_count}/{reqs.length}
            </span>
            <span className="truncate">{uiT("可自动求值")}</span>
          </span>
        </Tooltip>
      </div>
      {/* ──────── 唯一的确认入口（2026-09-28）───────
          此前顶栏一颗「确认需求基线」（只改内存、不落库）、这里一颗空壳
          （ConfirmFooter 没传 onClick，点了毫无反应）。两颗都不到位。
          现在统一到这里：落 requirement-baseline 产物 → 确认态 → 跳转流程 3。
          确认后按钮变「解除确认」，与流程 1 的形态完全一致（反悔出口保留）。 */}
      {confirmed ? (
        <ConfirmFooter
          label={uiT("解除确认")}
          count={s.ids.size}
          unit="条"
          variant="secondary"
          icon="unlock"
          hint={uiT("基线已确认并写入轮次产物（纳入 {v1} / {v2} 条）。点此解除后可继续调整纳入范围；阈值待补的项不受影响，仍会如实标注。", { v1: s.ids.size, v2: reqs.length })}
          onClick={release}
        />
      ) : (
        <ConfirmFooter
          label={saving ? uiT('确认中…') : uiT('确认基线')}
          count={s.ids.size}
          unit="条"
          hint={uiT("本轮基线纳入 {v1} 条判据（共 {v2} 条），勾选框改的就是这份基线。点击后写入 requirement-baseline 产物并进入流程 3；其中阈值待补的项确认后仍按「阈值待补」跟踪，不会被当成已填。", { v1: s.ids.size, v2: reqs.length })}
          onClick={() => void confirmBaseline()}
        />
      )}
    </div>
  )
}

/* -------------------------------------------------- 卡片 · 工作流画布（hero） */

function WorkflowStage({ full }: { full?: boolean }) {
  const uiT = useT()

  const pack = getPack()
  const { entries, model, active } = useWf()
  const [node, setNode] = useState<string | null>(null)
  const [edit, setEdit] = useState(false)
  if (!pack) return <Empty text={uiT("场景包未加载")} />
  const cur = entries.find((e) => e.id === active)
  if (!model)
    return <EmptyState icon={<WorkflowIcon size={24} strokeWidth={1.5} />} title={uiT("读取工作流")} />

  const subs = model.nodes.filter((n) => n.type === 'subworkflow').length

  return (
    <div className="flex h-full min-h-0 w-full flex-col gap-2">
      <div
        className={cn(
          'wf-root wf-embed min-h-0 min-w-0 flex-1',
          !full && !edit && 'wf-thumb',
        )}
      >
        <WorkflowCanvas
          model={model}
          readonly={!edit}
          selectedId={node}
          onSelect={(n) => setNode(n?.id ?? null)}
          // 组件默认的 fitView 下限 0.6 会顶住缩放把图裁掉边缘，节点一多就看不全。
          // 缩略态卡槽更窄，下限压得更低。组件本体不改，走 props 覆盖。
          fitViewOptions={full ? { minZoom: 0.2, padding: 0.08 } : { minZoom: 0.12, padding: 0.03, maxZoom: 1 }}
          className="h-full w-full"
        />
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-1.5">
        <Tooltip content={uiT(cur?.purpose ?? cur?.name ?? '')}>
          <span className="max-w-[210px] cursor-help truncate text-[13px] font-semibold tracking-tight text-t1">
            {uiT(cur?.name ?? '—')}
          </span>
        </Tooltip>
        <Badge tone="soft" mono>
          {uiT("节点 ")}{model.nodes.length}
        </Badge>
        <Badge tone="neutral" mono>
          {uiT("连线 ")}{model.edges.length}
        </Badge>
        <Badge tone="neutral" mono title={uiT("电压档")}>
          {cur ? uiT(voltShort(cur.voltage)) : '—'}
        </Badge>
        <Badge tone="neutral" mono title={uiT("调用子流程的节点数")}>
          {uiT("子流程 ")}{subs}
        </Badge>
        <Tooltip content={edit ? uiT('退出编辑，回到只读缩略') : uiT('进入编辑：可拖动节点与改连线')}>
          <button
            type="button"
            aria-label={uiT("编辑工作流")}
            aria-pressed={edit}
            onClick={() => setEdit((v) => !v)}
            className={cn(
              'ml-auto flex h-[24px] w-[24px] shrink-0 items-center justify-center rounded-tps border transition-colors [&>svg]:block',
              edit
                ? 'border-p300 bg-p50 text-p700'
                : 'border-line bg-white text-t3 hover:border-p300 hover:text-p700',
            )}
          >
            <Pencil size={13} strokeWidth={1.9} />
          </button>
        </Tooltip>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------ 卡片 · 工作流库 */

function WorkflowLibrary({ full }: { full?: boolean }) {
  const uiT = useT()

  const pack = getPack()
  const { entries, active } = useWf()

  const groups = useMemo(() => {
    const g = new Map<string, WfEntry[]>()
    for (const e of entries) g.set(e.group, [...(g.get(e.group) ?? []), e])
    // 画布当前那条所在的组排到最前，省得展开的组被挤到卡底看不见
    const hasActive = (items: WfEntry[]) => (items.some((e) => e.id === active) ? 1 : 0)
    return [...g.entries()].sort(
      (a, b) => hasActive(b[1]) - hasActive(a[1]) || b[1].length - a[1].length,
    )
  }, [entries, active])

  if (!pack) return <Empty text={uiT("场景包未加载")} />
  if (!entries.length)
    return <EmptyState icon={<Layers size={24} strokeWidth={1.5} />} title={uiT("读取工作流索引")} />

  const fromPack = pack.caps.workflowSource === 'pack-assets'
  const note = fromPack
    ? `工作流是场景包 assets/workflows/*.json，本身已是画布内部模型，不经 parseWfw。共 ${entries.length} 条${pack.workflows.all_placeholder ? '，全部为示例占位' : ''}。`
    : `可加载 .wfw ${entries.length} 个（索引 public/data/workflows.json），场景包 workflows.json 登记 ${pack.workflows.total} 条，两个数出处不同，没有对齐成同一个。`

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div className="flex shrink-0 items-center gap-1.5 pb-1.5">
        <Badge tone="soft" mono>
          {entries.length} {uiT(" 条")}</Badge>
        <Badge tone="neutral" mono>
          {groups.length} {uiT(" 组")}</Badge>
        <span className="ml-auto">
          <InfoTip content={note} />
        </span>
      </div>

      <div
        className="no-scrollbar -mx-3 min-h-0 flex-1 overflow-y-auto"
        style={{
          maskImage: 'linear-gradient(to bottom, #000 calc(100% - 18px), transparent 100%)',
          WebkitMaskImage: 'linear-gradient(to bottom, #000 calc(100% - 18px), transparent 100%)',
        }}
      >
        {groups.map(([g, items], i) => {
          const Icon = wfGroupIcon(g)
          return (
            <Collapsible
              key={g}
              dense
              icon={<Icon size={13} strokeWidth={1.9} />}
              title={short(g.replace(/^PWM\s*/, ''), 8)}
              defaultOpen={full ? i < 6 : items.some((e) => e.id === active)}
              right={<span className="num text-[12px] text-t3">{items.length}</span>}
            >
              {items.map((e) => {
                const on = e.id === active
                return (
                  <Tooltip key={e.id} className="w-full" content={uiT(e.purpose ?? e.name)}>
                    <button
                      type="button"
                      onClick={() => void openWf(pack, e)}
                      className={cn(
                        'flex min-h-[28px] w-full items-center gap-2 px-4 text-left transition-colors',
                        on ? 'bg-p50' : 'hover:bg-p50/70',
                      )}
                    >
                      <span
                        className={cn(
                          'h-[6px] w-[6px] shrink-0 rounded-full',
                          on ? 'bg-p600' : 'bg-p200',
                        )}
                      />
                      <span
                        className={cn(
                          'truncate text-[12.5px]',
                          on ? 'font-medium text-p700' : 'text-t1',
                        )}
                      >
                        {uiT(e.name)}
                      </span>
                      <span className="num ml-auto shrink-0 rounded-full border border-line px-1.5 text-[12px] leading-[17px] text-t3">
                        {voltShort(e.voltage)}
                      </span>
                      <span className="num w-[22px] shrink-0 text-right text-[12px] text-t3">
                        {e.nodeCount}
                      </span>
                    </button>
                  </Tooltip>
                )
              })}
            </Collapsible>
          )
        })}
      </div>
    </div>
  )
}

/* -------------------------------------------------------------- 卡片 · 判定表 */

function CriteriaTable({ full }: { full?: boolean }) {
  const uiT = useT()

  const pack = getPack()
  const s = useSel()
  // 「待确认 → 已确认 · 阈值待补」这个措辞切换要读确认态。
  // hook 必须无条件调用，所以订阅放在提前 return 之前。
  const confirmed = !!useAppStore((st) => st.confirmed.req)
  if (!pack) return <Empty text={uiT("场景包未加载")} />
  const reqs = pack.requirements.requirements
  const picked = reqs.filter((r) => s.ids.has(r.id))
  const auto = picked.filter((r) => r.evaluable !== false).length
  const manual = picked.length - auto
  const holes = picked.filter((r) => r._placeholder).length

  const rows = pack.requirements.categories.map((c) => {
    const items = reqs.filter((r) => r.category === c)
    return { c, n: items.filter((r) => s.ids.has(r.id)).length, total: items.length }
  })



  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div className="flex shrink-0 flex-wrap items-baseline gap-x-2 gap-y-1 pb-2">
        <span className="num text-[26px] leading-none font-semibold tracking-tight text-t1">
          {picked.length}
          <span className="text-[13px] font-normal text-t3">/{reqs.length}</span>
        </span>
        <span className="shrink-0 whitespace-nowrap text-[12px] text-t3">{uiT("本轮纳入")}</span>
        <span className="ml-auto flex shrink-0 flex-wrap items-center gap-x-2.5 gap-y-1">
          <span className="flex items-center gap-1.5">
            <span className="h-[7px] w-[7px] shrink-0 rounded-full bg-p600" />
            <span className="text-[12px] text-t3">{uiT("可求值")}</span>
            <span className="num text-[13px] font-semibold text-t1">{auto}</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-[7px] w-[7px] shrink-0 rounded-full bg-white ring-1 ring-inset ring-line" />
            <span className="text-[12px] text-t3">{uiT("人工判")}</span>
            <span className="num text-[13px] font-semibold text-t1">{manual}</span>
          </span>
          {/* 阈值位在源材料里空着 —— 这是**事实标记**，不是「你确认了没」的状态。
              ⚠️ 确认基线**不会**让它消失：点确认只冻结「本轮判哪几条」，
              并没有把缺失的阈值补上。让它消失等于把「源材料缺阈值」这件事
              在后续流程里藏起来（流程 4 判定时无处可查），比留着更危险。
              所以只改措辞：确认前「待确认」（黄，促人去补），
              确认后「已确认 · 阈值待补」（灰，明确它已被知悉但仍缺）。
              2026-09-28 按用户口径调整（原话：点确认要有变化，但事实不能藏）。 */}
          {holes ? (
            confirmed ? (
              <Badge
                tone="neutral"
                dot
                title={uiT("已确认知悉：{v1} 条判据的阈值位在源材料里空着，本次确认未补值，后续判定仍需人工复核", { v1: holes })}
              >
                {uiT("已确认")}{holes}
              </Badge>
            ) : (
              <Badge tone="warn" dot title={uiT("阈值位在源材料里空着，需人工确认")}>
                {uiT("待确认 ")}{holes}
              </Badge>
            )
          ) : null}
          <InfoTip content={uiT("此时只列不判：判定要的现场实测量由流程 4 台架采集后才求值，这里只冻结本轮要判哪些条。")} />
        </span>
      </div>

      <div
        className="no-scrollbar min-h-0 flex-1 overflow-y-auto"
        style={{
          maskImage: 'linear-gradient(to bottom, #000 calc(100% - 16px), transparent 100%)',
          WebkitMaskImage: 'linear-gradient(to bottom, #000 calc(100% - 16px), transparent 100%)',
        }}
      >
        <div className="grid grid-cols-2 gap-x-4 gap-y-px">
          {rows.map((r) => (
            <Tooltip key={r.c} className="w-full" content={uiT("{v1} · 纳入 {v2} / {v3} 条", { v1: r.c, v2: r.n, v3: r.total })}>
              <div className="flex w-full items-center gap-1.5 py-[2px] leading-[14px]">
                <span className="w-[52px] shrink-0 truncate text-[12px] leading-[14px] text-t2" title={uiT(r.c)}>{uiT(r.c) === r.c ? short(r.c, 4) : uiT(r.c)}</span>
                <span className="h-[5px] min-w-0 flex-1 overflow-hidden rounded-full bg-p100">
                  <span
                    className="block h-full rounded-full bg-p600 transition-[width] duration-500"
                    style={{ width: `${Math.round((r.n / r.total) * 100)}%` }}
                  />
                </span>
                <span className="num w-[26px] shrink-0 text-right text-[12px] leading-[14px] text-t3">
                  {r.n}/{r.total}
                </span>
              </div>
            </Tooltip>
          ))}
        </div>
        {full ? (
          <div className="pt-2">
            {picked.map((r) => (
              <div
                key={r.id}
                className="flex items-center gap-2 border-b border-line-soft py-[5px] last:border-b-0"
              >
                <span className="num w-[92px] shrink-0 text-[12px] text-t3">{r.id}</span>
                <span className="truncate text-[12.5px] text-t1">{uiT(r.name)}</span>
                <span className="num ml-auto shrink-0 text-[12px] text-t3">
                  {thresholdBadge(r) ?? '—'}
                </span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------ 卡片 · 知识依据 */

const fileName = (p: string) => p.split('/').filter(Boolean).at(-1) ?? p

/**
 * 出处定位收成一枚编号徽标：「第 140-146 行」「第二节」「Customer.h:1-40」「p19」这一类。
 * 抠不出编号就不发徽标——半截词比没有更糟；整句一律留在 tooltip 里（DESIGN.md §4 文案纪律 2）。
 */
function locatorTag(locator: string): string | null {
  const m =
    /第\s*[\d〇零一二三四五六七八九十百\-–~至、]+\s*[行页节条款项章]/.exec(locator) ??
    /[\w.]+:\d+(?:-\d+)?/.exec(locator) ??
    /[Pp]\.?\s*\d+/.exec(locator) ??
    /[Ll]ines?\s*[\d-]+/.exec(locator)
  return m ? m[0].replace(/\s+/g, ' ').trim() : null
}

function CriteriaEvidence({ full }: { full?: boolean }) {
  const uiT = useT()

  const pack = getPack()
  const s = useSel()
  if (!pack) return <Empty text={uiT("场景包未加载")} />
  const reqs = pack.requirements.requirements
  const r = reqs.find((x) => x.id === s.focus) ?? reqs[0]
  if (!r) return <Empty text={uiT("判据表为空")} />
  const srcs = Array.isArray(r._source) ? r._source : r._source ? [r._source] : []
  const list = full ? srcs : srcs.slice(0, 3)

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div className="flex shrink-0 items-center gap-2 pb-2">
        <Badge tone="ink" mono>
          {r.id}
        </Badge>
        <Tooltip className="min-w-0" content={uiT(r.criterion_text)}>
          <span className="cursor-help truncate text-[13px] font-medium text-t1">
            {uiT(r.name) === r.name ? short(r.name, 10) : uiT(r.name)}
          </span>
        </Tooltip>
        <span className="num ml-auto shrink-0 text-[12px] text-t3">{srcs.length} {uiT(" 处")}</span>
      </div>

      <div
        className="no-scrollbar min-h-0 flex-1 overflow-y-auto"
        style={{
          maskImage: 'linear-gradient(to bottom, #000 calc(100% - 16px), transparent 100%)',
          WebkitMaskImage: 'linear-gradient(to bottom, #000 calc(100% - 16px), transparent 100%)',
        }}
      >
        {list.map((src, k) => (
          <Tooltip
            key={`${src.file}-${k}`}
            className="w-full"
            content={`${src.file}${src.locator ? `\n${src.locator}` : ''}`}
          >
            <div className="flex w-full items-start gap-2 border-b border-line-soft py-[6px] last:border-b-0">
              <span className="mt-[5px] h-[6px] w-[6px] shrink-0 rounded-full bg-p600" />
              <span className="flex min-w-0 flex-1 items-center gap-1.5">
                <span className="min-w-0 flex-1 truncate text-[12.5px] text-t1">
                  {fileName(src.file)}
                </span>
                {src.locator && locatorTag(src.locator) ? (
                  <Badge tone="neutral" mono className="shrink-0">
                    {locatorTag(src.locator)}
                  </Badge>
                ) : null}
              </span>
            </div>
          </Tooltip>
        ))}
        {r.evidence?.length ? (
          <div className="flex flex-wrap items-center gap-1.5 pt-2">
            {r.evidence.map((e) => (
              <Badge key={e} tone="soft">
                {short(e, 10)}
              </Badge>
            ))}
          </div>
        ) : null}
        {full ? (
          <p className="pt-3 text-[12.5px] leading-6 text-t2">{uiT(r.criterion_text)}</p>
        ) : null}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------ 卡片 · 历史成绩 */

interface Batch {
  id: string
  name: string
  pass: number
  fail: number
  other: number
  note: string
}

/**
 * 历史成绩库尚未建立。这里只列场景包自己登记过的两个批次：
 * 98 次启动故障实验数据包（有 PASS / FAIL 计数），以及包内三条留档波形样本的人工结论。
 */
function batchesOf(pack: RawPack): Batch[] {
  const stats = pack.datasets.package_stats as Record<string, number>
  const out: Batch[] = []
  if (typeof stats.attempts_total === 'number') {
    const pass = stats.pass ?? 0
    const fail = stats.fail ?? 0
    out.push({
      id: 'attempts',
      name: '启停实验包',
      pass,
      fail,
      other: Math.max(0, stats.attempts_total - pass - fail),
      note: `${stats.attempts_total} 个 attempt，已标注 ${stats.labeled ?? 0}，无效 ${stats.invalid ?? 0}`,
    })
  }
  const labeled = pack.datasets.datasets.filter((d) => d.label?.operator_result)
  if (labeled.length) {
    const pass = labeled.filter((d) => d.label?.operator_result === 'PASS').length
    out.push({
      id: 'waves',
      name: '留档波形',
      pass,
      fail: labeled.length - pass,
      other: 0,
      note: `包内留档 ${labeled.length} 条，结论取实验记录里的人工判定`,
    })
  }
  return out
}

function HistoryCard({ full }: { full?: boolean }) {
  const uiT = useT()

  const pack = getPack()
  if (!pack) return <Empty text={uiT("场景包未加载")} />
  const batches = batchesOf(pack)
  if (!batches.length)
    return <EmptyState icon={<Activity size={24} strokeWidth={1.5} />} title={uiT("未登记历史批次")} />

  return (
    <div className="flex h-full min-h-0 w-full flex-col justify-center gap-3">
      {batches.map((b) => {
        const total = b.pass + b.fail + b.other || 1
        return (
          <Tooltip key={b.id} className="w-full" content={uiT(b.note)}>
            <div className="w-full cursor-help">
              <div className="flex items-baseline gap-2 pb-1.5">
                <span className="truncate text-[13px] font-medium text-t1">{uiT(b.name)}</span>
                <span className="num text-[12px] text-t3">{total}</span>
                <span className="num ml-auto text-[12px] text-p700">PASS {b.pass}</span>
                <span className="num text-[12px] text-t2">FAIL {b.fail}</span>
              </div>
              <div className="flex h-[10px] w-full overflow-hidden rounded-full bg-p100">
                <span
                  className="h-full bg-p600 transition-[width] duration-500"
                  style={{ width: `${(b.pass / total) * 100}%` }}
                />
                <span
                  className="h-full bg-alert transition-[width] duration-500"
                  style={{ width: `${(b.fail / total) * 100}%` }}
                />
                <span className="h-full bg-t3/30" style={{ width: `${(b.other / total) * 100}%` }} />
              </div>
            </div>
          </Tooltip>
        )
      })}

      {full ? (
        <div className="min-h-0 flex-1 overflow-y-auto pt-1">
          {pack.datasets.datasets.map((d) => (
            <div
              key={d.id}
              className="flex items-center gap-2 border-b border-line-soft py-[5px] last:border-b-0"
            >
              <span className="num w-[130px] shrink-0 truncate text-[12px] text-t3">{d.id}</span>
              <span className="truncate text-[12.5px] text-t1">{uiT(d.name)}</span>
              <span className="num ml-auto shrink-0 text-[12px] text-t3">
                {d.label?.operator_result ?? '—'}
              </span>
            </div>
          ))}
          <p className="pt-2 text-[12px] leading-5 text-t3">
            {uiT("历史成绩库尚未建立，这里只列场景包登记过的批次与数据集。")}</p>
        </div>
      ) : null}
    </div>
  )
}

export const reqCards = {
  workflow: WorkflowStage,
  'wf-lib': WorkflowLibrary,
  verdict: CriteriaTable,
  evidence: CriteriaEvidence,
  history: HistoryCard,
}
