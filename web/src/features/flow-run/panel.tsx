import { ConfigSuggestionButton } from '../config-suggestions/ConfigSuggestionButton'
import { StageOperation, StageFooter } from '../../app/StageOperation'
import { useT } from '../../i18n'
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  CircuitBoard,
  Cpu,
  Gauge,
  ChevronRight,
  ListFilter,
  Lock,
  Monitor,
  RotateCw,
  ShieldCheck,
  Sliders,
  Waves as WavesIcon,
  Zap,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import {
  Badge,
  Collapsible,
  EmptyState,
  InfoTip,
  Select,
  SourceTag,
  StatusDot,
  Stepper,
  Tooltip,
  cn,
} from '../../components/ui'
import { decimalsOf } from '../../data/loadScene'
import { useNavigate } from 'react-router'
import {
  RUN_PHASE_LABEL,
  collapseKey,
  paramKey,
  resolveParamKey,
  useAppStore,
} from '../../state/useAppStore'
import { useFlowActions } from '../redline'
import {
  getPack,
  sourceLine,
  statusOf,
  type RawControlParam,
  type RawInterlock,
  type RawPack,
} from '../scene/pack'
import { ConfigOverview } from '../../app/LeftPanel'
import { fmtMeasure } from '../shared/format'
import { UnifiedConfigPanel } from '../../app/UnifiedConfigPanel'
import { Empty } from '../shared/bits'
import { buildTiers, demoFilter, readTiers } from '../shared/tiers'
import { getBaselineIds, subscribeBaseline } from '../flow-req/baselineStore'
import { TimeSeriesChart } from '../timeseries'
import { POWERUP_ANNOTATION, currentThresholds, loadWaves, type Wave } from '../waveforms'
import { FanTrendPanel } from '../fan-trend'
import {
  evaluateOnBackend,
  persistRun,
  type BackendVerdict,
} from './api'
import { controlValueMap, evaluateAll, measureOrigin, runtimeMeasures, type VerdictState } from './evaluate'

/* ===========================================================================
   流程 4 · 启动测试及结果分析（v2 视觉样板页）
   左栏：控制参数分组 + 本轮运行设置 + 安全确认闸门，底部悬浮确认主按钮
   卡片：时序曲线（hero，横跨两格）/ 原理图封面 / 判定 / 安全闸门环 / 台架会话
   数据逻辑不动，只换视觉与版式。
   =========================================================================== */

/** 标签一律收到 6 字以内，全名进 tooltip */
function short(s: string, n = 6) {
  const clean = s.replace(/[（(].*$/, '').trim()
  return clean.length > n ? `${clean.slice(0, n)}…` : clean
}

/* ---------------------------------------------------- 闸门状态（跨卡片共享）

   第四轮把这份状态从模块级私有变量搬进 useAppStore：顶栏动作条要靠它算
   「启动测试」亮不亮，顶栏盾形徽章要靠它报还差几条，模块级变量这两处都拿不到。
   依据：08c-部署联调与演示SOP-v1.0.md 第零节「点不动的三处」第 2 条。 */

export function useGate() {
  const acked = useAppStore((s) => s.gateAcked)
  const total = useAppStore((s) => s.gateTotal)
  return useMemo(() => ({ acked: new Set(acked), total }), [acked, total])
}

/* ------------------------------------------------------------------ 左栏 */

function flowFiltersOf(total: number) {
  return [
    { value: 'F4', label: '本流程可调' },
    { value: 'all', label: `全部 ${total} 项` },
    { value: 'F2', label: '初始化确认' },
    { value: 'F5', label: '调优可调' },
  ]
}

/** 分组图标：按组名关键词取 */
const GROUP_ICON: [RegExp, LucideIcon][] = [
  [/闭环|整定|环路|PI/i, WavesIcon],
  [/流程纪律|纪律/, ShieldCheck],
  [/人员|现场/, Monitor],
  [/启动|预定位|start/i, Zap],
  [/调速|转速|speed/i, Gauge],
  [/顺逆|方向|风/i, RotateCw],
  [/保护|限流|故障/i, ShieldCheck],
  [/电流|电压|功率/i, Activity],
  [/观测|估算|角度/i, WavesIcon],
]
const groupIcon = (name: string): LucideIcon => {
  for (const [re, ic] of GROUP_ICON) if (re.test(name)) return ic
  return Sliders
}
const iconOf = (name: string, size = 14) => {
  const Ic = groupIcon(name)
  return <Ic size={size} strokeWidth={1.9} />
}

function ParamRow({ p }: { p: RawControlParam }) {
  const uiT = useT()

  // G-11：取值走**回落链**——本流程改过用自己的，没改过就继承初始化页确认过的值。
  // 详见 useAppStore.resolveParamKey 的说明（为什么不动 key 结构）。
  //
  // ⚠️ `snapshotValues` 这一档不可少：`overrides` 是**内存态**，换页/刷新即重建，
  // 而流程 3 是另一个页面——只靠内存回落，它永远继承不到初始化页的值
  // （实测栽过：快照里明明是 NONEMODE，流程 3 仍显示场景包原值 PWMMODE）。
  const overrides = useAppStore((s) => s.overrides)
  const snapshotValues = useAppStore((s) => s.snapshotValues)
  const resolved = resolveParamKey('run', 'cp', p.group, p.key, overrides, snapshotValues)
  const key = paramKey('run', 'cp', p.group, p.key)
  const touched = useAppStore((s) => s.touched[key])
  const setParam = useAppStore((s) => s.setParam)
  // 三档：本流程 override → 初始化页（内存或快照）→ 场景包原值
  const value = resolved.value ?? (p.not_applicable ? '不适用' : p.value)
  // 继承来的值要如实标出来源：不是本流程改的，是人**在初始化页**定的基线
  const inherited = resolved.source === 'init'
  const editable = !p.not_applicable && p.editable && typeof p.value === 'number'

  const detail = (
    <span className="block space-y-1">
      <span className="block font-medium">{uiT(p.name)}</span>
      <span className="num block opacity-75">
        {p.key.toUpperCase()}
        {p.min !== null && p.max !== null ? ` · ${p.min}~${p.max}` : ''}
        {p.value_shell ? uiT(" · 外壳 {v1}", { v1: p.value_shell }) : ''}
      </span>
      <span className="block opacity-75">{sourceLine(p._source)}</span>
      {/* 继承来的值必须说清来历：人看到「值变了」要知道是谁定的 */}
      {inherited ? (
        <span className="block opacity-75">{uiT("当前值继承自「初始化配置」确认过的基线")}</span>
      ) : null}
      {statusOf(p) ? <span className="block opacity-75">{uiT("待核实 · ")}{statusOf(p)}</span> : null}
      {p.value_below_min ? <span className="block">{uiT("实配值低于源注释自己写的下限")}</span> : null}
    </span>
  )

  return (
    <div className="flex min-h-[40px] items-center gap-2 px-4 py-1.5 transition-colors hover:bg-p50/60">
      <Tooltip className="min-w-0" content={detail}>
        <span className="flex min-w-0 items-center gap-1.5">
          {/* 继承来的值既非本流程人工改、也非纯文档值，标「建议」以区分——
              三态（文档/人工/建议）是既有枚举，不新增第四态。 */}
          <SourceTag source={inherited ? '建议' : touched ? '人工' : '文档'} />
          <span className="cursor-help truncate text-[13px] font-medium text-t1">{uiT(p.name) === p.name ? short(p.name) : uiT(p.name)}</span>
          {p.value_below_min ? <AlertTriangle size={12} className="shrink-0 text-warn" /> : null}
        </span>
      </Tooltip>

      <span className="ml-auto shrink-0">
        {p.not_applicable ? (
          <span className="text-[12px] text-t3">{uiT("不适用")}</span>
        ) : p.options?.length ? (
          <Select
            size="sm"
            // 窄屏自适应（2026-10-15）：flow-param-select 与 LeftPanel 的参数下拉同款 ——
            // 左栏在 ≤1024px 只有 216~264px，写死的 150px 会把参数名挤没。
            className="flow-param-select w-[150px]"
            label={uiT(p.name)}
            options={p.options.map((o) => ({ value: String(o.value), label: uiT(o.label) }))}
            value={String(value)}
            onChange={(v) => setParam(key, v)}
          />
        ) : editable ? (
          <Stepper
            size="sm"
            label={uiT(p.name)}
            value={Number(value)}
            unit={p.unit ?? undefined}
            step={p.step ?? 1}
            min={p.min ?? undefined}
            max={p.max ?? undefined}
            precision={
              decimalsOf(p.step) || Math.min(4, decimalsOf(typeof p.value === 'number' ? p.value : 0))
            }
            onChange={(n) => setParam(key, n)}
          />
        ) : (
          <span className="num text-[15px] font-semibold text-t1">
            {String(value)}
            {p.unit ? <span className="ml-1 text-[12px] font-normal text-t3">{p.unit}</span> : null}
          </span>
        )}
      </span>
    </div>
  )
}

/**
 * 闸门分组：编号里自带 PROC / PERSON 类别，直接拿来当二级组，不再九条平铺；
 * 组内超过 5 条的（流程类 7 条）再按场景包 group_tiers 切一层三级子组。
 */
interface GateGroup {
  id: string
  title: string
  items: RawInterlock[]
  subs: { id: string; title: string; items: RawInterlock[] }[]
}

function gateGroups(pack: RawPack, items: RawInterlock[]): GateGroup[] {
  const spec = readTiers(pack.interlocks).filter((t) => /流程|人员/.test(t.title))
  const pick = (ids?: string[]) => {
    const want = new Set((ids ?? []).map((x) => x.toLowerCase()))
    return items.filter((i) => want.has(i.id.toLowerCase()))
  }
  const out: GateGroup[] = spec.map((t) => {
    const mine = pick(t.groups.flatMap((g) => g.items ?? []))
    return {
      id: t.id,
      title: t.title,
      items: mine,
      subs:
        mine.length > 5
          ? t.groups
              .map((g) => ({ id: g.id, title: g.title, items: pick(g.items) }))
              .filter((g) => g.items.length > 0)
          : [],
    }
  })
  const used = new Set(out.flatMap((g) => g.items.map((i) => i.id)))
  const rest = items.filter((i) => !used.has(i.id))
  if (rest.length) out.push({ id: 'gate-rest', title: '其他', items: rest, subs: [] })
  return out.filter((g) => g.items.length > 0)
}

/** 闸门一行：圆形勾选 + 短名 + 编号 */
function GateRow({
  i,
  on,
  onToggle,
}: {
  i: RawInterlock
  on: boolean
  onToggle: () => void
}) {
  const uiT = useT()
  return (
    <Tooltip className="w-full" content={`${i.id} ${uiT(i.name)} · ${uiT(i.action)}`}>
      <button
        type="button"
        onClick={onToggle}
        data-gate={i.id}
        aria-pressed={on}
        className="flex w-full items-center gap-2.5 px-4 py-1.5 text-left transition-colors hover:bg-p50/70"
      >
        <span
          className={cn(
            'flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border transition-colors [&>svg]:block',
            on ? 'border-transparent bg-p600 text-white' : 'border-line bg-white text-transparent',
          )}
        >
          <CheckCircle2 size={12} strokeWidth={2.5} />
        </span>
        <span className="truncate text-[13px] text-t1">{uiT(i.name) === i.name ? short(i.name, 10) : uiT(i.name)}</span>
        <span className="num ml-auto shrink-0 text-[12px] text-t3">{i.id}</span>
      </button>
    </Tooltip>
  )
}

export function RunLeftPanel() {
  const nav = useNavigate()
  const phase = useAppStore((state) => state.runPhase)
  const uiT = useT()

  const pack = getPack()
  const [filter, setFilter] = useState('F4')
  const g = useGate()
  const [runs, setRuns] = useState(100)
  const [volt, setVolt] = useState<string>('')
  const [gateOpen, setGateOpen] = useState(false)
  const demo = useAppStore((s) => s.demoMode)
  const toggle = useAppStore((s) => s.toggleGate)
  const ackAllGates = useAppStore((s) => s.ackAllGates)
  const setGateTotal = useAppStore((s) => s.setGateTotal)
  const setNotice = useAppStore((s) => s.setNotice)
  const bind = useFlowActions()
  /* 2026-10-10：本流程的「已确认」是系统在**本轮跑完且判定表落库后自动写入**的，
     此前左栏没有任何反向出口 → 顶栏那一格打勾关不掉（用户反馈）。
     现在补上反悔出口，形态与流程 1/2/5 的「解除确认」同源
     （同一个 ConfirmFooter 的 secondary + unlock 形态，不新写样式）。
     ⚠️ 解除只是取消「已确认」这个标记；下轮跑完测试时仍会照原口径再次自动确认。 */
  const locked = !!useAppStore((s) => s.confirmed.run)
  const unconfirmFlow = useAppStore((s) => s.unconfirmFlow)

  const gateItems = useMemo(
    () => (pack ? pack.interlocks.interlocks.filter((i) => i.type === '人员' || i.type === '流程') : []),
    [pack],
  )
  // 闸门总条数由本场景包登记，写进 store 供顶栏动作条与盾形徽章共用
  useEffect(() => setGateTotal(gateItems.length), [gateItems.length, setGateTotal])

  if (!pack) return <Empty text={uiT("场景包未加载")} />

  // 演示模式只暴露 demo_profile 点名的那 12 项控制参数；全量模式下按流程过滤照旧。
  const params = demoFilter(
    pack.controls,
    'parameters',
    pack.controls.parameters.filter(
      (p) => filter === 'all' || p.adjustable_in_flows?.some((f) => f.startsWith(filter)),
    ),
    (p) => p.key,
  )
  // 一级类取自场景包 control-parameters.json 的 group_tiers：启动与预定位 / 闭环与整定 /
  // 运行与保护。启动组 10 项按「模式与时序」「电流与增益」切三级子组。
  const tiers = buildTiers<RawControlParam>(
    readTiers(pack.controls),
    params,
    (p) => p.key,
    (p) => p.group,
  )
  const green = gateItems.length > 0 && g.acked.size === gateItems.length
  const groups = gateGroups(pack, gateItems)

  const attr = (re: RegExp) => pack.attributes.attributes.find((a) => re.test(`${a.key}${uiT(a.name)}`))
  const vMin = attr(/voltage_min|工作电压下限|运行电压下限/)
  const vMax = attr(/voltage_max|工作电压上限|运行电压上限/)
  const vNom = attr(/rated_bus_voltage|rated_voltage|额定.*电压/)
  const voltOptions = [
    vMin ? `LV ${vMin.value} ${vMin.unit ?? 'V'}` : null,
    vNom ? `SV ${vNom.value} ${vNom.unit ?? 'V'}` : null,
    vMax ? `HV ${vMax.value} ${vMax.unit ?? 'V'}` : null,
  ]
    .filter((x): x is string => !!x)
    .map((x) => ({ value: x, label: x }))
  if (!voltOptions.length) voltOptions.push({ value: '未登记', label: '未登记' })
  const voltValue = volt || voltOptions[Math.min(1, voltOptions.length - 1)].value

  const runReq =
    pack.requirements.requirements.find((r) =>
      Object.keys(r.threshold ?? {}).some((k) => /^runs$|required_pass/.test(k)),
    ) ??
    pack.requirements.requirements.find((r) =>
      Object.keys(r.threshold ?? {}).some((k) => /cycles/.test(k)),
    )
  const runNote = runReq
    ? `判据 ${runReq.id}：${runReq.criterion_text}`
    : '本场景包没有按次数计的回归判据，启停次数只作台架设置。'

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      {/* 栏头 */}
      <header className="flex h-[44px] shrink-0 items-center gap-2.5 border-b border-line-soft px-4">
        <Sliders size={17} strokeWidth={1.9} className="shrink-0 text-p700" />
        <h2 className="text-[16px] leading-none font-semibold tracking-tight text-t1">{uiT("参数")}</h2>
        <span className="num text-[12px] text-t3">{params.length}</span>
        <div className="ml-auto flex items-center gap-1.5">
          <ListFilter size={13} strokeWidth={1.9} className="text-t3" />
          <Select
            size="sm"
            className="w-[118px]"
            label={uiT("按流程过滤")}
            options={flowFiltersOf(pack.controls.parameters.length).map((option) => ({ ...option, label: uiT(option.label) }))}
            value={filter}
            onChange={setFilter}
          />
        </div>
      </header>

      <div className="fade-b min-h-0 flex-1 overflow-y-auto pb-2">
        <ConfigOverview flow="run" assist={<ConfigSuggestionButton stage="run" />}
          key={pack.scene.id}
          count={tiers.reduce((n, t) => n + t.count, 0)}

          actions={<StageOperation title={uiT('本步操作 · 安全确认')}
            status={uiT(`已确认 {v1}/{v2}`, { v1: gateItems.filter((item) => g.acked.has(item.id)).length, v2: gateItems.length })}>
            <p className="stage-operation-status">{green ? uiT('人工安全项已确认') : uiT('人工安全项待确认')}</p>
            <button type="button" className="stage-operation-link" aria-expanded={gateOpen} onClick={() => setGateOpen((v) => !v)}>{uiT('查看逐项清单')}</button>
            <button type="button" className="stage-operation-confirm" disabled={green || gateItems.length === 0 || phase === 'running'} onClick={() => {
              ackAllGates(gateItems.map((item) => item.id))
              setNotice(uiT('人工安全项已批量确认；启动仍需单独确认。'))
            }}>{green ? uiT('人工安全项已确认') : uiT('一键确认安全项')}</button>
            <p className="stage-operation-note">{uiT('请先逐项人工核对；此操作不会启动检测，也不代表自动测得安全。')}</p>
          {gateOpen ? (
            <div className="animate-fade">
              {groups.map((grp, i) => (
                <Collapsible
                  key={grp.id}
                  level={2}
                  icon={iconOf(grp.title)}
                  title={uiT(grp.title)}
                  storeKey={collapseKey('run', grp.id)}
                  // 演示模式下逐条清单一律折叠，组头自带「勾了几条 / 共几条」，
                  // 镜 3 要勾时再点开（06d 第 3.1 节）
                  defaultOpen={!demo && i === 0}
                  stat={{
                    done: grp.items.filter((x) => g.acked.has(x.id)).length,
                    total: grp.items.length,
                  }}
                >
                  {grp.subs.length ? (
                    grp.subs.map((sub, k) => (
                      <Collapsible
                        key={sub.id}
                        level={3}
                        title={uiT(sub.title)}
                        storeKey={collapseKey('run', sub.id)}
                        defaultOpen={!demo && k === 0}
                        stat={{
                          done: sub.items.filter((x) => g.acked.has(x.id)).length,
                          total: sub.items.length,
                        }}
                      >
                        {sub.items.map((i2) => (
                          <GateRow
                            key={i2.id}
                            i={i2}
                            on={g.acked.has(i2.id)}
                            onToggle={() => toggle(i2.id)}
                          />
                        ))}
                      </Collapsible>
                    ))
                  ) : (
                    <>
                      {grp.items.map((i2) => (
                        <GateRow
                          key={i2.id}
                          i={i2}
                          on={g.acked.has(i2.id)}
                          onToggle={() => toggle(i2.id)}
                        />
                      ))}
                    </>
                  )}
                </Collapsible>
              ))}
            </div>
          ) : null}
          </StageOperation>}
        >
          <details className="stage-details"><summary>{uiT('运行参数')}</summary>
          <UnifiedConfigPanel
            flow="run"
            tiers={tiers}
            // 一级类只展开第一个「启动与预定位」，其余折叠
            defaultOpen={0}
            itemKey={(p) => p.key}
            render={(p) => <ParamRow p={p} />}
            flags={(p) => ({
              filled: p.value !== null,
              pending: !!statusOf(p),
              alert: !!p.value_below_min,
            })}
            tierIcon={(t) => iconOf(t, 15)}
            groupIcon={(t) => iconOf(t)}
          />
          </details>
        </ConfigOverview>

        {/* 本轮运行设置 */}
        <Collapsible
          level={1}
          icon={<Cpu size={15} strokeWidth={1.9} />}
          title={uiT("运行设置")}
          storeKey={collapseKey('run', 'run-setting')}
          defaultOpen={false}
          stat={{ total: 2 }}
          right={<InfoTip content={runNote} />}
        >
          <div className="flex min-h-[40px] items-center gap-2 px-4 py-1.5">
            <span className="text-[13px] font-medium text-t1">{uiT("启停次数")}</span>
            <span className="ml-auto">
              <Stepper size="sm" label={uiT("启停次数")} value={runs} step={10} min={1} max={1000} onChange={setRuns} />
            </span>
          </div>
          <div className="flex min-h-[40px] items-center gap-2 px-4 py-1.5">
            <span className="text-[13px] font-medium text-t1">{uiT("电压档")}</span>
            <span className="ml-auto">
              <Select
                size="sm"
                // 窄屏自适应（2026-10-15）：同上，见 index.css 的 .flow-param-select
                className="flow-param-select w-[150px]"
                label={uiT("电压档")}
                options={voltOptions}
                value={voltValue}
                onChange={setVolt}
              />
            </span>
          </div>
        </Collapsible>


      </div>

      <StageFooter
        label={phase === 'done' ? uiT('整理报告') : phase === 'running' ? uiT('检测运行中') : uiT('启动检测')}
        disabled={phase === 'done' ? false : bind('start').disabled}
        onClick={phase === 'done' ? () => nav('/report') : bind('start').onClick}
        reason={phase === 'done' ? uiT('本轮检测已完成；请查看判定结果。') : bind('start').disabled ? uiT(bind('start').reason ?? '') : uiT('人工确认已完成；点击后仍需启动确认。')}
        secondary={<>
          {phase === 'done' ? <button type="button" onClick={() => nav('/tune')}>{uiT('按需查看调参建议')}</button> : null}
          {phase === 'done' ? <button type="button" disabled={bind('start').disabled} onClick={bind('start').onClick}>{uiT('再次检测')}</button> : null}
          {locked ? <button type="button" onClick={() => unconfirmFlow('run')}>{uiT('解除本轮确认')}</button> : null}
        </>}
      />
    </div>
  )
}

/* ------------------------------------------------------------ 卡片 · 时序曲线 */

/**
 * 本轮回放哪几条时序。演示主线只要一失败一成功两条（datasets.json 的
 * demo_profile 点名 TRY-0010 与 TRY-0009）；全量模式下包里登记的照旧全放。
 */
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
  return pack ? demoFilter(pack.datasets, 'datasets', waves, (w) => w.id) : waves
}

/** 图例上的成败字样：只有编号看不出这条是成还是败（06d 第 3.1 节） */
const verdictWord = (w: Wave) =>
  w.verdict === 'pass' ? 'PASS' : w.verdict === 'fail' ? 'FAIL' : w.verdictText

/** 卡体高度随视口缩放，图表高度跟着量出来，避免 1440/1600 下横轴被裁。
 *  用回调 ref 而不是 useEffect：卡体是在时序数据到位之后才挂上来的，
 *  空态阶段 ref 还是 null，写在 useEffect 里会错过那一次挂载。 */
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

/**
 * 旧「图表」卡实现：回放场景包历史数据集（TRY-0010/0009/0021）。
 *
 * ⚠️ 2026-10-06 起本卡已改由 `FanTrendPanel`（实时风扇趋势）承担，
 * 本组件**保留不删**，仅供其他用途或回退（其依赖 useWaves/TimeSeriesChart
 * 与场景包 datasets 仍在）。若要恢复历史回放，把 runCards.timeseries 指回它即可。
 *
 * 同时注意：本函数若不再被引用，`useWaves` 可能成为未使用警告——保留是有意为之，
 * 因为回退路径需要它。
 */
export function WaveformPanel({ full }: { full?: boolean }) {
  const uiT = useT()

  const pack = getPack()
  const waves = useWaves()
  const [box, boxH] = useBoxHeight()
  const [on, setOn] = useState<Record<string, boolean>>({})
  if (!waves.length)
    return <EmptyState icon={<WavesIcon size={24} strokeWidth={1.5} />} title={uiT("读取时序")} />
  const show = waves.filter((w) => on[w.id] ?? true)
  const peak = Math.max(...waves.map((w) => w.metrics.peak))
  const th = currentThresholds(full, peak)
  const unit = waves[0].unit

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-1.5 pb-1.5">
        {waves.map((w) => {
          const active = on[w.id] ?? true
          return (
            <Tooltip key={w.id} content={`${uiT(w.title)} · ${uiT(w.verdictText)}`}>
              <button
                type="button"
                onClick={() => setOn((o) => ({ ...o, [w.id]: !(o[w.id] ?? true) }))}
                className={cn(
                  'num inline-flex h-[22px] items-center gap-1.5 rounded-full border px-2 text-[12px] font-medium transition-colors',
                  active
                    ? w.verdict === 'fail'
                      ? 'border-p200 bg-white text-t2'
                      : 'border-p200 bg-p50 text-p700'
                    : 'border-line bg-white text-t3',
                )}
              >
                <span
                  className="h-[6px] w-[6px] rounded-full"
                  style={{ background: active ? w.series.color : 'var(--p-200)' }}
                />
                {w.id}
                <span className={cn('font-semibold', w.verdict === 'fail' ? 'text-alert' : 'text-p700')}>
                  {verdictWord(w)}
                </span>
              </button>
            </Tooltip>
          )
        })}
        {pack?.caps.syntheticData ? (
          <Badge tone="warn" title={uiT(pack.caps.syntheticBanner)}>
            {uiT("合成")}</Badge>
        ) : null}
        {pack?.caps.probeUnconfirmed ? <InfoTip content={uiT(pack.caps.probeNote)} /> : null}
        {/* 采样率读数不进演示分镜（06d 第 3.1 节），放大态仍给 */}
        {full ? (
          <span className="num ml-auto text-[12px] text-t3">
            {waves[0].sampleRate ? `${Math.round(waves[0].sampleRate / 1000)} kSa/s` : '—'}
          </span>
        ) : null}
      </div>
      <div ref={box} className="min-h-0 flex-1">
        <TimeSeriesChart
          series={show.map((w) => w.series)}
          annotations={[POWERUP_ANNOTATION]}
          thresholds={th}
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

/* ---------------------------------------------------------- 卡片 · 原理图封面 */

function SchematicCover({ full }: { full?: boolean }) {
  const uiT = useT()

  const pack = getPack()
  const [i, setI] = useState(-1)
  if (!pack) return <Empty text={uiT("场景包未加载")} />
  // 变体登记的是 PDF 原始路径；包内渲出来的分页图挂在 scene.images 上，
  // 按 _source.file 与变体对上号，对不上的如实显示「未渲染分页图」，不拿别的图冒充。
  const imgOf = (file: string) =>
    pack.scene.images?.find((im) => {
      const src = (im as { _source?: { file?: string } })._source
      return src?.file === file
    })?.path ?? null
  const vs = pack.scene.schematic_variants
  const srcOf = (v: { file: string; rendered?: string }) =>
    v.rendered ?? (v.file.startsWith('assets/') ? v.file : imgOf(v.file))
  const renderable = vs.findIndex((v) => srcOf(v))
  const pick = i >= 0 ? i : Math.max(0, renderable)
  if (!vs.length)
    return <EmptyState icon={<CircuitBoard size={24} strokeWidth={1.5} />} title={uiT("未登记图纸")} />
  const cur = vs[Math.min(pick, vs.length - 1)]
  const src = srcOf(cur)

  return (
    <div className="flex h-full min-h-0 w-full flex-col gap-1.5">
      <div className="min-h-0 flex-1 overflow-hidden rounded-tp2 bg-p50">
        {src ? (
          <img
            src={pack.base + src}
            alt={uiT(cur.name)}
            className={cn(
              'h-full w-full',
              full ? 'object-contain' : src.endsWith('.svg') ? 'object-cover object-center' : 'object-cover object-top',
            )}
          />
        ) : (
          <EmptyState icon={<CircuitBoard size={24} strokeWidth={1.5} />} title={uiT("未渲染分页图")} />
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {vs.slice(0, 4).map((v, k) => (
          <Tooltip key={v.name} content={uiT(v.name)}>
            <button
              type="button"
              onClick={() => setI(k)}
              className={cn(
                'h-[6px] w-[18px] rounded-full transition-colors',
                pick === k ? 'bg-p600' : 'bg-p200 hover:bg-p300',
              )}
              aria-label={uiT(v.name)}
            />
          </Tooltip>
        ))}
        <span className="num ml-auto text-[12px] text-t3">
          {Math.min(pick, vs.length - 1) + 1}/{vs.length}
        </span>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------- 卡片 · 判定卡 */

const STATE_LABEL: Record<VerdictState, string> = {
  pass: '通过',
  fail: '不通过',
  missing: '未采集',
  manual: '人工判',
  // 2026-10-08 新增第五态：本台架不具备该测量手段（区别于「未采集」——
  // 未采集是"本该采到却没采到"，不适用是"台架没这个能力"，对决策含义不同）
  not_applicable: '本台架不适用',
}

/**
 * 实测量读数的显示格式化（2026-10-08）。
 *
 * ✅ 2026-10-08 起实现移入 `../shared/format`，与自动化全屏运行台共用同一份口径。
 * 口径：4 位有效数字并去掉尾随零（`0.0017566666666666678` → `0.001757`，
 * `4.7596` → `4.76`），与 flow-tune 面板 `fmt()` 的 `toPrecision(4)` 同一套。
 *
 * 为什么要抽出去：判定卡、趋势图 tooltip、自动化运行台三处都显示同一批实测量，
 * 各写一份 `toPrecision(4)` 迟早会出现「同一个量在两个页面显示得不一样」。
 */

/* ---------------------------------------------------------- 需求基线（跨流程读）
   流程 2 的「确认基线」决定**本轮判哪几条**。此前流程 3 从来不读这份基线，
   `evaluateAll` 直接对场景包全表求值——「流程 2 取消了 14 条，流程 3 照样判 20 条」。
   这里订阅 `flow-req/baselineStore` 的镜像（写入方：流程 2 的确认与读回）。

   返回 `string[] | null`：**null 表示本会话还没读到基线**，调用方据此选择
   「不过滤」。不要把它转成空数组——那会把「没确认过」显示成「一条都不判」。 */
function useRequirementBaseline(): string[] | null {
  return useSyncExternalStore(subscribeBaseline, getBaselineIds, getBaselineIds)
}

/**
 * 本轮「落库 + 置位」只做一次的守卫（2026-10-08）。
 *
 * 为什么需要它：落库与置位原来挂在判定卡的 effect 里，且排在
 * `if (cancelled) return` 之后。判定卡会因**画板/网格视图切换、卡片重排、
 * registry 版本变化**而卸载重挂，cleanup 会把 await 期间那个闭包标记成
 * cancelled —— 于是 `evaluateOnBackend` 返回后直接 return，`persistRun`
 * 与 `confirmFlow('run')` 一次都没执行：判定上得了屏、产物存不下来、
 * 顶栏「启动测试及结果分析」那一格永远点不亮（实测栽过：真实台架跑完一轮，
 * `POST /api/evaluate` 200，随后 `POST /api/runs` 一次都没发出）。
 *
 * 现在把落库**与组件生命周期解耦**：cancelled 只用来护住组件自身的
 * setState（authoritative / authState / persistError），落库与置位改由
 * 模块级 round 守卫保证「同一轮只落一次、且不因卸载而放弃」。
 */
let persistedRunRound: number | null = null

function VerdictCard({ full }: { full?: boolean }) {
  const uiT = useT()

  const pack = getPack()
  const waves = useWaves()
  const demo = useAppStore((s) => s.demoMode)
  const runPhase = useAppStore((s) => s.runPhase)
  const runProgress = useAppStore((s) => s.runProgress)
  const setFocusReq = useAppStore((s) => s.setFocusReq)
  const nav = useNavigate()
  // 流程 2 确认过的需求基线（修 2→3 断点）。null = 本会话还没读到基线 → 不过滤。
  const baselineIds = useRequirementBaseline()

  /*
   * 后端权威判定。前端这几行算出来的是**预览**，一跑完一轮就去后端要最终结论：
   * 判定只有一份权威，两份长期并存必然漂移。后端够不着（没起服务、没登录）时
   * 保留预览并明确标出来，不假装那就是结论。
   */
  const [authoritative, setAuthoritative] = useState<BackendVerdict[] | null>(null)
  const [authState, setAuthState] = useState<'idle' | 'loading' | 'ok' | 'fallback'>('idle')
  /*
   * 落盘失败的原因。**不能只 catch 掉不出声**：轮次存不下会让「刷新后找回本轮」
   * 失效，而界面上毫无痕迹，人只会以为功能没做。2026-09-23 全量审查就是靠
   * 这个缺口才定位到 artifact_kind 前后端不一致——在那之前，落盘一直失败、
   * 界面一直正常。这里把失败显式化，让「判定成功但没存下」这件事看得见。
   */
  const [persistError, setPersistError] = useState<string | null>(null)
  const sceneId = useAppStore((s) => s.sceneId)
  // 采纳/人工改过的控制参数与配置快照：判定里 control-parameters 变量要读采纳值，
  // 否则「改了参数结论不变」。同时读本轮真采集量 runMeasures（beginRun 写入）。
  const overrides = useAppStore((s) => s.overrides)
  const snapshotValues = useAppStore((s) => s.snapshotValues)
  const runMeasures = useAppStore((s) => s.runMeasures)

  /*
   * 每跑完一轮（runPhase 从 running 落回 idle）去后端要一次权威判定，
   * 顺带把这一轮落成可找回的轮次产物（阶段 4 验收：刷新后仍能找回轮次和文件）。
   *
   * 两件事都不阻塞界面：成功就换成后端结论，失败就保留前端预览并标注，
   * 让人知道「这是预览不是结论」，而不是静默假装成权威。
   */
  const prevPhase = useRef(runPhase)
  useEffect(() => {
    const finished = prevPhase.current === 'running' && runPhase !== 'running'
    prevPhase.current = runPhase
    if (!finished || !pack) return

    let cancelled = false
    // 本轮真采集量（beginRun 先采后判，running→done 时已就位）+ 固定波形回退。
    // 用 getState() 读最新值，避免 effect 闭包捕获到过期的 runMeasures/overrides。
    const st = useAppStore.getState()
    const measures = { ...runtimeMeasures(waves, pack), ...st.runMeasures }
    setAuthState('loading')

    void (async () => {
      try {
        const result = await evaluateOnBackend(
          sceneId,
          measures,
          controlValueMap(pack, st.overrides, st.snapshotValues),
        )
        // cancelled 只护住组件自身的 state（卸载后不该再 setState），**不**牵连落库。
        if (!cancelled) {
          setAuthoritative(result.results)
          setAuthState('ok')
        }
        // 落盘与求值分开：求值结果要立刻上屏，落盘失败不该把判定也一起丢掉。
        // ⚠️ 这里不能因 cancelled 而 return（见 persistedRunRound 的说明）。
        // 守卫键取**当前**轮次号而不是 effect 入口处那个：急停/停止收口时
        // settleRun 会在本 effect 之后才把 runRound +1（入口处读到的是旧号），
        // 拿旧号比对会把这一轮误判成「已有更新一轮」而永远不落库。
        const curRound = useAppStore.getState().runRound
        if (persistedRunRound === curRound) return
        persistedRunRound = curRound
        try {
          const localRows = evaluateAll(pack, measures, st.overrides, st.snapshotValues)
          const runId = await persistRun({
            sceneId,
            verdicts: localRows,
            measures,
            backendVerdicts: result.results,
            startedAt: new Date(Date.now() - 1000).toISOString(),
          })
          // 记住本轮号：流程 4 的采纳（param-change）要挂在某一轮上，
          // 没有它采纳就无处落库。刷新后这个值会丢，读回另走「按场景取最近一轮」。
          useAppStore.getState().setRunId(runId)
          // 运行流程的确认锚点（2026-10-08 补齐断点）：本轮正常跑完且判定表**真落库**
          // → 置 confirmed.run，顶栏「启动测试及结果分析」打勾。此前全站没有任何
          // confirmFlow('run')，导致这一格永远点不亮（用户反馈「五个阶段完不成」的断点之一）。
          // 只认 runPhase==='done'：被停止/急停收口的算中断，不算完成，不点亮（如实，不粉饰）。
          // 读 store 最新值而不是闭包里的 runPhase：落库是异步的，await 期间状态可能又变。
          if (useAppStore.getState().runPhase === 'done') useAppStore.getState().confirmFlow('run')
        } catch (e) {
          // 判定照旧算数（落盘失败不该把结论一起丢掉），但**必须留痕**：
          // 既要在控制台给出可查的原因，也要在卡面上标出来，
          // 否则「刷新后找回本轮」会静默失效，人只会以为功能没做。
          const msg = e instanceof Error ? e.message : String(e)
          console.error('[flow-run] 本轮产物落盘失败，刷新后无法找回：', msg)
          // 落盘失败要放开守卫：本轮仍允许被再次触发（卡片重挂 / 再来一轮）时重试。
          persistedRunRound = null
          if (!cancelled) setPersistError(msg)
        }
      } catch (e) {
        // 后端够不着（没起服务 / 响应不合法）：退回前端预览，并让卡面把这件事说清楚。
        // ⚠️ 原因必须留下来（2026-10-08）：本分支原先是裸 catch，异常被完全吞掉，
        // 于是「后端返回了前端不认的包装」这类问题在界面上只表现为「预览」两个字，
        // 排查时毫无线索。现按项目纪律原样透传到控制台。
        console.error('[flow-run] 后端权威判定不可用，已退回前端预览：', e instanceof Error ? e.message : e)
        if (cancelled) return
        setAuthoritative(null)
        setAuthState('fallback')
      }
    })()

    return () => {
      cancelled = true
    }
    // waves 每次回放都会换一份新数组，不能进依赖，否则会反复重求值
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runPhase, sceneId, pack])

  if (!pack) return <Empty text={uiT("场景包未加载")} />
  // 流程 2 确认的需求基线：**只判「本轮纳入的那几条」**（修 2→3 断点）。
  //
  // ⚠️ `null` 与 `[]` 语义不同（见 baselineStore.ts）：
  //   · `null`（本会话还没读到过基线）→ **不过滤**，保持旧的「全表」行为，
  //     这样没走过流程 2 的路径（直接进流程 3）不会突然变成 0 条。
  //   · `[]`（基线明说一条都不纳入）→ **真的判 0 条**，不拿全表顶替。
  const inBaseline = (id: string) => (baselineIds === null ? true : baselineIds.includes(id))
  // 演示模式只判 demo_profile 点名的 6 条；放大态与全量模式给全表。
  // 判定输入 = 固定波形（演示回退）+ 本轮真采集（rpm/频率，真机优先）。
  const all = evaluateAll(
    pack,
    { ...runtimeMeasures(waves, pack), ...runMeasures },
    overrides,
    snapshotValues,
  )
  const scoped = all.filter((r) => inBaseline(r.req.id))
  const rows = full ? scoped : demoFilter(pack.requirements, 'requirements', scoped, (r) => r.req.id)

  /**
   * 展示行：后端给了权威判定就以后端为准（按 req_id 对齐，前端预览只作兜底）。
   * 后端结果驱动的三个计数才是最终结论——本地预览可能因算法实现细节有出入，
   * 两处数字必须同源，否则同一屏里「总计」和「明细」会互相打架。
   */
  const backendById = authoritative
    ? new Map(authoritative.map((v) => [v.req_id, v]))
    : null
  const shownRows = backendById
    ? rows.map((r) => {
        const b = backendById.get(r.req.id)
        return b ? { ...r, state: b.state, note: b.note ?? r.note, missing: b.missing ?? r.missing } : r
      })
    : rows
  const pPass = shownRows.filter((r) => r.state === 'pass').length
  const pFail = shownRows.filter((r) => r.state === 'fail').length
  const pMissing = shownRows.filter((r) => r.state === 'missing').length
  // 「本台架不适用」单独计数：不与 missing 混，也不计入通过（2026-10-08）
  const pNa = shownRows.filter((r) => r.state === 'not_applicable').length

  // 首屏只列有结论的那几行：演示模式下不拿「未采集」补位凑行数（06d 第 3.1 节
  // 「判定卡，只留有结论的几行」）；全表进放大态。
  // 2026-10-08：首屏纳入 not_applicable——它是有明确结论的一类（"本台架测不了"，
  // 已带原因），把它藏起来反而让人以为还有悬而未决的项。
  const list = full
    ? shownRows
    : demo
      ? shownRows.filter((r) => r.state === 'pass' || r.state === 'fail').slice(0, 3)
      : [
          ...shownRows.filter((r) => r.state === 'pass' || r.state === 'fail'),
          ...shownRows.filter((r) => r.state === 'not_applicable'),
          ...shownRows.filter((r) => r.state === 'missing'),
        ].slice(0, 3)

  const Stat = ({ n, label, tone }: { n: number; label: string; tone: 'ok' | 'bad' | 'mute' }) => (
    <div className="flex min-w-0 flex-1 flex-col gap-0.5">
      <span className="flex items-center gap-1.5">
        <span
          className={cn(
            'h-[7px] w-[7px] shrink-0 rounded-full',
            tone === 'ok' ? 'bg-p600' : tone === 'bad' && n > 0 ? 'bg-alert' : 'bg-t3/40',
          )}
        />
        <span className="text-[12px] text-t3">{label}</span>
      </span>
      <span
        className={cn(
          'num text-[26px] leading-none font-semibold tracking-tight',
          tone === 'bad' && n > 0 ? 'text-alert' : 'text-t1',
        )}
      >
        {n}
      </span>
    </div>
  )

  // 本轮正在跑时判定还没出，摆一条进度而不是摆上一轮的结论
  if (runPhase === 'running')
    return (
      <div className="flex h-full min-h-0 w-full flex-col justify-center gap-2.5 px-1">
        <div className="flex items-baseline gap-2">
          <span className="num text-[26px] leading-none font-semibold text-t1">{runProgress}%</span>
          <span className="text-[12px] text-t3">{uiT("运行中 · 判定待出")}</span>
        </div>
        <div className="h-[6px] overflow-hidden rounded-full bg-p100">
          <div
            className="h-full rounded-full bg-p600 transition-[width] duration-200"
            style={{ width: `${runProgress}%` }}
          />
        </div>
        <p className="text-[12px] leading-5 text-t3">{uiT("本轮回放已登记时序，跑完即按判据求值。")}</p>
      </div>
    )

  const judgedCount = shownRows.filter((r) => r.state === 'pass' || r.state === 'fail').length
  // 分母也要跟着基线收窄：基线把表砍到 6 条时，还说「/ 20 条可求值」会让人
  // 以为漏判了 14 条。口径写成「本轮纳入的这几条里，有几条可求值」。
  const inScopeEvaluable = all.filter((r) => r.req.evaluable !== false && inBaseline(r.req.id)).length
  const scopeNote =
    baselineIds === null ? '（未读到需求基线，按全表判）' : `（需求基线纳入 ${all.filter((r) => inBaseline(r.req.id)).length} 条）`
  const tip = `已求值 ${judgedCount} / ${inScopeEvaluable} 条可求值判据，本轮判定表 ${shownRows.length} 条：通过 ${pPass}、不通过 ${pFail}、本台架不适用 ${pNa}${
    pMissing ? `、未采集 ${pMissing}` : ''
  }。「本台架不适用」指该判据需要本台架未配置的测量手段（逐条 tooltip 写明缺什么），与「未采集」（本该采到却没采到）不同，不参与通过/不通过统计。判定范围${scopeNote}。结论来源：${
    authState === 'ok'
      ? '后端判定（权威）'
      : authState === 'loading'
        ? '正在向后端求值…'
        : authState === 'fallback'
          ? '前端预览（后端不可达，非最终结论）'
          : '前端预览（尚未跑完一轮）'
  }。${persistError ? `⚠ 本轮已判定但**产物落盘失败**，刷新后找不回本轮（${persistError}）。` : ''}${measureOrigin(pack) ?? ''}${
    judgedCount === 0
      ? '本轮一条都判不了：判据要的现场实测量（母线电流、转速、力、位移、声压级）得由台架传感器现场采，本轮只回放了一条曲线，不拿别的数顶替。'
      : ''
  }参数说明：采纳/修改的参数若未被任何判据公式引用（比如预定位强度、预定位时间、启动 IQ 电流这些固件宏），判定结论**不随采纳变化**——它们改的是电机实际行为，要真机烧固件跑起来才体现。参数对判定生效的两条真实路径：①被判据公式引用的参数（如「无调速模式目标转速 nonemode_speed → 目标转速 → TR-START-02」）；②电机插上做真启停回归，产生本轮新实测量。`

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      {/* 演示模式把三个 26px 大数字收成一行：首屏只需要「判出几条、其中几条不通过」，
          分项计数进 tooltip（06d 第 3.1 节与 06b 第 3 节密度规则） */}
      <div className={cn('flex shrink-0 gap-2 pb-2', demo && !full ? 'items-center' : 'items-start')}>
        {demo && !full ? (
          <Tooltip className="min-w-0 flex-1" content={tip}>
            <span className="flex cursor-help items-baseline gap-1.5">
              <span className={cn('num text-[26px] leading-none font-semibold tracking-tight', pFail > 0 ? 'text-alert' : 'text-t1')}>
                {pFail}
              </span>
              <span className="text-[12px] text-t3">{uiT("条不通过 · 已判 ")}{judgedCount}</span>
            </span>
          </Tooltip>
        ) : (
          <>
            <Stat n={pPass} label={uiT("通过")} tone="ok" />
            <Stat n={pFail} label={uiT("不通过")} tone="bad" />
            {/*
              第三格优先展示「本台架不适用」：本台架只有风扇+示波器，大量判据
              在结构上测不了（缺 MCU 故障寄存器 / FG 信号 / 母线电流探头）。
              这类项如实标为不适用并写明缺什么设备，比混在「未采集」里更利于决策。
              只有确实不存在不适用项时才退回展示「未采集」。
            */}
            {pNa > 0 ? (
              <Stat n={pNa} label={uiT("本台架不适用")} tone="mute" />
            ) : (
              <Stat n={pMissing} label={uiT("未采集")} tone="mute" />
            )}
          </>
        )}
        <InfoTip content={tip} />
      </div>
      <div
        className="no-scrollbar min-h-0 flex-1 overflow-y-auto"
        style={{
          maskImage: 'linear-gradient(to bottom, #000 calc(100% - 18px), transparent 100%)',
          WebkitMaskImage: 'linear-gradient(to bottom, #000 calc(100% - 18px), transparent 100%)',
        }}
      >
        {list.map((r) => {
          // 未达标的行点得动：带着判据 id 进流程 4，那边直接定位到这一条。
          // 别的行不可点——没有结论可跟进的行给点击反馈是假的。
          const jump = r.state === 'fail'
          const row = (
            <div
              className={cn(
                'flex w-full items-center gap-2 border-b border-line-soft py-[5px] last:border-b-0',
                jump && 'rounded-tpx transition-colors hover:bg-alert-wash/60',
              )}
            >
              <StatusDot status={r.state === 'pass' ? 'done' : r.state === 'fail' ? 'alert' : 'na'} />
              <span className="truncate text-[12.5px] text-t1">{uiT(r.req.name) === r.req.name ? short(r.req.name, 12) : uiT(r.req.name)}</span>
              <span className="num ml-auto shrink-0 text-[12px] text-t3">{uiT(STATE_LABEL[r.state])}</span>
              {jump ? <ChevronRight size={13} strokeWidth={2} className="shrink-0 text-alert" /> : null}
            </div>
          )
          return (
            <Tooltip
              key={r.req.id}
              className="w-full"
              content={uiT("{v1}{v2}{v3}{v4}{v5}", { v1: r.req.criterion_text, v2: r.used.length
                  ? ` · 本轮实测：${r.used
                      .map(
                        (u) =>
                          `${u.name} ${
                            typeof u.value === 'number' ? fmtMeasure(u.value) : String(u.value)
                          }${u.unit ?? ''}`,
                      )
                      .join('、')}`
                  : '', v3: r.state === 'not_applicable' && r.notApplicableReason
                  ? ` · 本台架不适用：${r.notApplicableReason}`
                  : '', v4: r.note ? ` · ${r.note}` : r.missing.length ? ` · 缺 ${r.missing.join('、')}` : '', v5: jump ? uiT(' · 点此进流程 4 看推荐') : '' })}
            >
              {jump ? (
                <button
                  type="button"
                  data-testid="verdict-fail-row"
                  aria-label={uiT("{v1} 未达标，进流程 4", { v1: uiT(r.req.name) })}
                  className="w-full text-left"
                  onClick={() => {
                    setFocusReq(r.req.id)
                    nav('/tune')
                  }}
                >
                  {row}
                </button>
              ) : (
                row
              )}
            </Tooltip>
          )
        })}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------- 卡片 · 安全闸门环 */

function GateRing({ full }: { full?: boolean }) {
  const uiT = useT()

  const pack = getPack()
  const g = useGate()
  if (!pack) return <Empty text={uiT("场景包未加载")} />
  const human = pack.interlocks.interlocks.filter((i) => i.type === '人员' || i.type === '流程')
  const hw = pack.interlocks.interlocks.filter((i) => i.type === '硬件')
  const done = g.acked.size
  const total = human.length || 1
  const R = 26
  const C = 2 * Math.PI * R
  const ratio = done / total

  return (
    <div className="flex h-full min-h-0 w-full items-center gap-4">
      <div className="relative shrink-0">
        <svg width="68" height="68" viewBox="0 0 68 68">
          <circle cx="34" cy="34" r={R} fill="none" stroke="var(--p-100)" strokeWidth="7" />
          <circle
            cx="34"
            cy="34"
            r={R}
            fill="none"
            stroke={ratio === 1 ? 'var(--p-600)' : 'var(--tp-warn)'}
            strokeWidth="7"
            strokeLinecap="round"
            strokeDasharray={`${C * ratio} ${C}`}
            transform="rotate(-90 34 34)"
            style={{ transition: 'stroke-dasharray .4s cubic-bezier(.22,.75,.3,1)' }}
          />
        </svg>
        <span className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="num text-[17px] leading-none font-semibold text-t1">{done}</span>
          <span className="num text-[11px] text-t3">/{human.length}</span>
        </span>
      </div>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex items-center gap-1.5">
          <ShieldCheck size={14} strokeWidth={1.9} className="shrink-0 text-p700" />
          <span className="text-[13px] font-medium text-t1">{uiT("人工闸门")}</span>
          <Badge tone={ratio === 1 ? 'soft' : 'warn'} dot className="ml-auto">
            {ratio === 1 ? uiT('全绿') : uiT('待确认')}
          </Badge>
        </div>
        <div className="flex items-center gap-1.5 text-[12px] text-t3">
          <Lock size={13} strokeWidth={1.9} className="shrink-0 text-p400" />
          {uiT("硬件联锁")}<span className="num ml-auto text-t1">{hw.length}</span>
        </div>
        <Tooltip content={uiT("硬件联锁由固件阈值保证，不需要人工逐条确认；人工闸门未全绿前「启动测试」保持置灰。")}>
          <span className="num cursor-help text-[12px] text-t3">
            {uiT("共 ")}{pack.interlocks.interlocks.length} {uiT(" 条")}</span>
        </Tooltip>
        {full ? (
          <ul className="max-h-[300px] overflow-y-auto pt-1">
            {pack.interlocks.interlocks.map((i) => (
              <li key={i.id} className="flex items-center gap-2 border-b border-line-soft py-1 last:border-b-0">
                <span className="num shrink-0 text-[12px] text-t3">{i.id}</span>
                <span className="truncate text-[12.5px] text-t1">{uiT(i.name)}</span>
                <Badge tone="neutral" className="ml-auto">
                  {uiT(i.type)}
                </Badge>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------ 卡片 · 台架实况

   第三轮撤掉「单机设备会话」这张独立卡（《第三轮需求变更方案 v0.1》第 2.3 节第 4 条），
   本页原来那份 BENCH 设备记录与 src/features/remote/device.ts 的 BENCH_DEVICE
   是同一台机器（峰岹电机测试 Windows 工控机 SK-20251218QPBB）的两份逐字拷贝，
   收尾轮合并成一份、留 device.ts 那份。设备现在只以画板上的 MCP 节点出现，
   节点体在 src/features/remote/DeviceMcpNode.tsx。 */

/* ---------------------------------------------------------- 卡片 · 执行进度（备） */

function Progress({ full }: { full?: boolean }) {
  const uiT = useT()

  const pack = getPack()
  const waves = useWaves()
  const demo = useAppStore((s) => s.demoMode)
  const runPhase = useAppStore((s) => s.runPhase)
  const runProgress = useAppStore((s) => s.runProgress)
  const runRound = useAppStore((s) => s.runRound)
  const baselineIds = useRequirementBaseline()
  if (!pack) return <Empty text={uiT("场景包未加载")} />
  const s2 = pack.datasets.package_stats as Record<string, number>
  const hasBatch = typeof s2.attempts_total === 'number'
  const done = hasBatch ? (s2.labeled ?? 0) : waves.length
  const total = hasBatch ? s2.attempts_total : pack.datasets.datasets.length

  // ⚠️ 这行日志此前是**假的**：写「载入需求基线：判据 N 条」，而 N 取的是
  // 场景包全量条数，与「人确认了哪几条」无关（打了这行反而让人以为读了基线）。
  // 现在如实分三种说法，并且**只用基线镜像里的真值**。
  // 日志行全部走 uiT 模板词条（英文界面下整行译出；模板捕获值里若是数据文本需单独再包 uiT）
  const baselineLine =
    baselineIds === null
      ? uiT("[00:00.0] 未读到需求基线（流程 2 未确认）：按场景包全表 {v1} 条判", {
          v1: pack.requirements.requirements.length,
        })
      : uiT("[00:00.0] 载入需求基线：本轮纳入 {v1}/{v2} 条判据", {
          v1: baselineIds.length,
          v2: pack.requirements.requirements.length,
        })

  const log = [
    baselineLine,
    uiT("[00:00.3] 联锁自检：硬件 {v1} 条由固件阈值保证", {
      // ⚠️ '硬件' 是**数据比较值**（下面 filter 用），必须保持原文，不能包 uiT，否则筛不出条目
      v1: pack.interlocks.interlocks.filter((i) => i.type === '硬件').length,
    }),
    uiT("[00:02.0] 采集口径：{v1} Sa/s", {
      v1: Math.round(pack.datasets.datasets[0]?.sample_rate_sa_per_s ?? 0),
    }),
    ...waves.map((w) =>
      uiT("[回放] {v1} {v2} · 峰值 {v3} {v4} @ {v5} s", {
        v1: w.id,
        // verdictText 是场景包数据文本，需单独再包一次（uiT 的参数只做替换、不翻译参数值）
        v2: uiT(w.verdictText),
        v3: w.metrics.peak.toFixed(2),
        v4: w.unit,
        v5: w.metrics.peakAt.toFixed(2),
      }),
    ),
  ]

  return (
    <div className="flex h-full min-h-0 w-full flex-col gap-2">
      <div className="flex shrink-0 items-baseline gap-2">
        <span className="num text-[26px] leading-none font-semibold text-t1">{done}</span>
        {demo && !full ? null : <span className="num text-[13px] text-t3">/ {total}</span>}
        <Tooltip content={uiT("{v1} {v2} / {v3}。{v4}", { v1: hasBatch ? uiT('已标注') : uiT('已回放'), v2: done, v3: total, v4: log.join('　') })}>
          <span className="ml-auto cursor-help text-[12px] text-t3">
            {hasBatch ? uiT("已标注 / {v1}", { v1: total }) : uiT("已回放 / {v1}", { v1: total })}
          </span>
        </Tooltip>
      </div>
      {/* 本轮运行态：待启动 / 运行中 / 已出判定 / 已停止 / 已急停，由顶栏那颗
          「启动测试」经红线确认卡驱动，不是自己跑起来的 */}
      <div className="flex shrink-0 items-center gap-1.5">
        <Badge tone={runPhase === 'estopped' ? 'warn' : runPhase === 'running' ? 'soft' : 'neutral'} dot>
          {uiT(RUN_PHASE_LABEL[runPhase])}
        </Badge>
        <span className="num text-[12px] text-t3" data-testid="run-phase">
          {runPhase === 'running' ? `${runProgress}%` : runRound > 0 ? uiT("本会话第 {v1} 轮", { v1: runRound }) : uiT('本会话未启动')}
        </span>
      </div>
      <div className="h-[6px] shrink-0 overflow-hidden rounded-full bg-p100">
        <div
          className="h-full rounded-full bg-p600 transition-[width] duration-500"
          style={{ width: `${runPhase === 'running' ? runProgress : Math.round((done / (total || 1)) * 100)}%` }}
        />
      </div>
      <div className="mono min-h-0 flex-1 overflow-y-auto text-[11px] leading-[18px] text-t3">
        {/* 演示模式首屏不铺日志行，只留进度条与计数，全量日志进放大态
            （06d 第 3.1 节：执行进度日志折叠到二级） */}
        {(full ? log : demo ? [] : log.slice(-3)).map((l) => (
          <div key={l} className="truncate" title={l}>
            {l}
          </div>
        ))}
      </div>
    </div>
  )
}

export const runCards = {
  // ⚠️ 2026-10-06：flow-run 首卡「图表」已从 WaveformPanel（场景包历史波形回放）
  // 换成 FanTrendPanel（接 /api/fan-tests 实时轮询的风扇趋势）。
  // WaveformPanel 函数体**保留**（见上方定义），供其他用途或回退；仅取消它在本卡的挂载。
  // 原因：本卡位置需要展示实时采集趋势，与场景包离线数据集是两类数据。
  timeseries: FanTrendPanel,
  schematic: SchematicCover,
  verdict: VerdictCard,
  interlock: GateRing,
  progress: Progress,
}
