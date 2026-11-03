import { ConfigSuggestionButton } from '../config-suggestions/ConfigSuggestionButton'
import { useT } from '../../i18n'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import {
  Activity,
  Boxes,
  Cable,
  ChevronRight,
  CircuitBoard,
  ClipboardList,
  Cpu,
  FileCode2,
  FileText,
  Folder,
  Gauge,
  Image as ImageIcon,
  Lock,
  Monitor,
  Radar,
  Ruler,
  Sliders,
  Wand2,
  Waves,
  Zap,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import {
  Badge,
  Button,
  EmptyState,
  Input,
  Select,
  SourceTag,
  StatusDot,
  Stepper,
  Tooltip,
  cn,
} from '../../components/ui'
import { BENCH_CHANNEL_MAP, BENCH_CHANNEL_PENDING } from '../../data/bench'
import { decimalsOf } from '../../data/loadScene'
import { registerLeftPanel } from '../../registry'
import { paramKey, useAppStore } from '../../state/useAppStore'
import {
  fileName,
  getPack,
  headerFieldName,
  sizeText,
  sourceLine,
  statusOf,
  type RawAttribute,
  type RawControlParam,
  type RawDocument,
  type RawHeaderField,
  type RawInterlock,
  type RawPack,
} from '../scene/pack'
import { ConfigOverview } from '../../app/LeftPanel'
import { UnifiedConfigPanel } from '../../app/UnifiedConfigPanel'
import { ConfirmFooter, Empty } from '../shared/bits'
import { buildTiers, readTiers, type BuiltGroup, type BuiltTier, type Flags } from '../shared/tiers'
import { simp } from '../shared/zh'
// BENCH_PULL_DIR：台架取图目录，从 .env 读（见 remote/device.ts）。
// 界面文案要用它，但**不从这里另读一份**——同一份配置两处读必然走偏。
// BENCH_HOST 同理：界面上显示的台架地址也取同一份配置，未配置时显示「未配置」，
// 不把客户内网地址写回交付代码（2026-09-24 补：此前本文件里还留着 172.25.5.166）。
import { BENCH_HOST, BENCH_PULL_DIR, probeDevice, type ConnState } from '../remote'
import { applySnapshot, loadLatestSnapshot, persistSnapshot } from './snapshotApi'
import { createTask, readStoredTaskId, writeStoredTaskId } from './taskApi'

/* ===========================================================================
   流程 2 · 初始化配置（v2 视觉，对齐流程 4 样板页）

   左栏：本体属性 8 组折叠（product-attributes.json 29 项），
         参数行 = 来源圆点 + 短标签 + 大字值 + 圆形加减。
   卡片：产品示意图（hero，真图铺满）/ 原理图·文档读取 / 工程树 /
         安全联锁 / 台架实况。
   数据来源一律取场景包原始 JSON，本轮只改视觉，不改数据逻辑。

   注意：本页**没有**上传入口。资料上传统一走左栏顶部知识条上的「上传」
   （开面板 → 五阶段转化）。此前这里另有一条「随传随用/选文件」，
   与它重复，已按用户要求移除（2026-09-24）。
   =========================================================================== */

/** 标签一律收到 6 字以内，全名进 tooltip */
function short(s: string, n = 6) {
  const clean = s.replace(/[（(].*$/, '').trim()
  return clean.length > n ? `${clean.slice(0, n)}…` : clean
}

/* ------------------------------------------------------------------ 左栏 */

const GROUP_ICON: [RegExp, LucideIcon][] = [
  [/被测对象|电机|本体|传动/, Cpu],
  [/驱动|控制|固件|模式/, Sliders],
  [/台架|仪器|通道|接入/, Cable],
  [/联锁|安全|人员|纪律|校验/, Lock],
  [/运行与产出|登记|模板|约束/, ClipboardList],
  [/转速|速度/, Gauge],
  [/电压|供电|额定/, Zap],
  [/电流|功率|力/, Activity],
  [/芯片|主控|观测/, Cpu],
  [/采样|反馈|噪音/, Waves],
  [/机械|外形|尺寸|行程|环境/, Ruler],
]
const groupIcon = (name: string): LucideIcon => {
  for (const [re, ic] of GROUP_ICON) if (re.test(name)) return ic
  return Boxes
}
const iconOf = (name: string, size = 14) => {
  const Ic = groupIcon(name)
  return <Ic size={size} strokeWidth={1.9} />
}

function AttrRow({ a }: { a: RawAttribute }) {
  const uiT = useT()

  const key = paramKey('init', 'pa', a.group, a.key)
  const override = useAppStore((s) => s.overrides[key])
  const touched = useAppStore((s) => s.touched[key])
  const setParam = useAppStore((s) => s.setParam)
  const value = override ?? (a.not_applicable ? '不适用' : a.value)

  /**
   * ⚠️ **占位值（`_placeholder`）必须可编辑**（2026-09-28 用户实测反馈修）。
   *
   * 原判据是 `typeof a.value === 'number' && compact`，而占位字段在场景包里的值
   * 往往是**字符串「未知」**（实测 `fan_thickness.value = "未知"`、
   * `fan_outer_size.value = "未知"`），于是 `editable` 为 false——
   * 界面上只显示「未知」，**没有任何输入控件**。
   *
   * 这是本项目里最荒谬的一处逻辑漏洞：**占位字段恰恰是最需要人现场填的**，
   * 却因为「没有初始数字值」被锁成只读。场景包对这些项明确标着 `editable: true`
   * （允许人改），是我们自己的判据把它挡掉了。
   *
   * 修法：可编辑性**只看场景包的 `a.editable`**，不看当前值是不是数字。
   * 占位项给可输入的起点（Stepper 的 `value` 为 null 时显示空、placeholder 提示）。
   */
  const wantsEdit = !a.not_applicable && a.editable !== false
  // 有数字就用数字做起点；占位/未知则给 null（空输入框），由人填
  const stepperValue = typeof value === 'number' ? value : null

  const detail = (
    <span className="block space-y-1">
      <span className="block font-medium">{uiT(a.name)}</span>
      <span className="num block opacity-75">
        {a.key.toUpperCase()}
        {a.min !== null && a.max !== null ? ` · ${a.min}~${a.max}` : ''}
        {a.unit ? ` · ${a.unit}` : ''}
      </span>
      <span className="block opacity-75">{sourceLine(a._source) || uiT('源材料未登记出处')}</span>
      {/* ⚠️ 占位项要分清「人已填」与「还没填」（2026-09-28）：
          人填过值后再写「待确认」是说不通的（用户实测反馈过）。
          填过的改为「已确认」，只留「这个值是现场给的、不是源材料的」这层信息。 */}
      {a._placeholder ? (
        touched ? (
          <span className="block">{uiT("已确认：源材料没给这一项，当前值由现场填写")}</span>
        ) : (
          <span className="block">{uiT("待现场确认：源材料没给这一项，需现场实测或由客户确认")}</span>
        )
      ) : null}
      {statusOf(a) ? <span className="block opacity-75">{uiT("待核实 · ")}{statusOf(a)}</span> : null}
    </span>
  )

  return (
    <div className="flex min-h-[40px] items-center gap-2 px-4 py-1.5 transition-colors hover:bg-p50/60">
      <Tooltip className="min-w-0" content={detail}>
        <span className="flex min-w-0 items-center gap-1.5">
          <SourceTag source={touched ? '人工' : a._placeholder ? '建议' : '文档'} />
          <span className="cursor-help truncate text-[13px] font-medium text-t1">{uiT(a.name) === a.name ? short(a.name) : uiT(a.name)}</span>
          {/* 小圆点只给「还没填」的占位项——填过的就不再是待办 */}
          {a._placeholder && !touched ? (
            <span
              className="h-[6px] w-[6px] shrink-0 rounded-full bg-t3/45"
              aria-label={uiT("待现场确认 ")}
            />
          ) : null}
        </span>
      </Tooltip>

      <span className="ml-auto shrink-0">
        {a.not_applicable ? (
          <span className="text-[12px] text-t3">{uiT("不适用")}</span>
        ) : a.options?.length ? (
          <Select
            size="sm"
            className="w-[150px]"
            label={uiT(a.name)}
            options={a.options.map((o) => ({ value: String(o.value), label: uiT(o.label) }))}
            value={String(value)}
            onChange={(v) => setParam(key, v)}
          />
        ) : wantsEdit ? (
          <Stepper
            size="sm"
            label={uiT(a.name)}
            value={stepperValue}
            unit={a.unit ?? undefined}
            step={a.step ?? 1}
            min={a.min ?? undefined}
            max={a.max ?? undefined}
            precision={
              decimalsOf(a.step) || Math.min(4, decimalsOf(typeof a.value === 'number' ? a.value : 0))
            }
            onChange={(n) => setParam(key, n)}
          />
        ) : (
          <span className="num text-[15px] font-semibold text-t1">
            {String(value)}
            {a.unit ? <span className="ml-1 text-[12px] font-normal text-t3">{a.unit}</span> : null}
          </span>
        )}
      </span>
    </div>
  )
}

/** 控制参数行：与本体属性行同形，只是取数换成 control-parameters.json */
function ParamRow({ p }: { p: RawControlParam }) {
  const uiT = useT()

  const key = paramKey('init', 'cp', p.group, p.key)
  const override = useAppStore((s) => s.overrides[key])
  const touched = useAppStore((s) => s.touched[key])
  const setParam = useAppStore((s) => s.setParam)
  const value = override ?? (p.not_applicable ? '不适用' : p.value)
  // 与 AttrRow 同一判据：可编辑性只看场景包的 `editable`，不看当前值是不是数字。
  // 控制参数目前没有占位项（实测 70 项都有数字值），但口径保持一致，
  // 免得将来包里有占位项时又出现「最该填的那行填不了」。
  const editable = !p.not_applicable && p.editable !== false
  const stepperValue = typeof value === 'number' ? value : null

  const detail = (
    <span className="block space-y-1">
      <span className="block font-medium">{uiT(p.name)}</span>
      <span className="num block opacity-75">
        {p.key.toUpperCase()}
        {p.min !== null && p.max !== null ? ` · ${p.min}~${p.max}` : ''}
        {p.value_shell ? uiT(" · 外壳 {v1}", { v1: p.value_shell }) : ''}
      </span>
      <span className="block opacity-75">{sourceLine(p._source)}</span>
      {statusOf(p) ? <span className="block opacity-75">{uiT("待核实 · ")}{statusOf(p)}</span> : null}
    </span>
  )

  return (
    <div className="flex min-h-[38px] items-center gap-2 px-4 py-1 transition-colors hover:bg-p50/60">
      <Tooltip className="min-w-0" content={detail}>
        <span className="flex min-w-0 items-center gap-1.5">
          <SourceTag source={touched ? '人工' : '文档'} />
          <span className="cursor-help truncate text-[13px] font-medium text-t1">{uiT(p.name) === p.name ? short(p.name) : uiT(p.name)}</span>
        </span>
      </Tooltip>
      <span className="ml-auto shrink-0">
        {p.options?.length ? (
          <Select
            size="sm"
            className="w-[150px]"
            label={uiT(p.name)}
            options={p.options.map((o) => ({ value: String(o.value), label: uiT(o.label) }))}
            value={String(value)}
            onChange={(v) => setParam(key, v)}
          />
        ) : editable ? (
          <Stepper
            size="sm"
            label={uiT(p.name)}
            value={stepperValue}
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

/* ------------------------------------------- 左栏 · 五个一级类的叶子与装配 */

/**
 * 左栏一条叶子。五个一级类的数据不在同一份 JSON 里（本体属性 / 控制参数 /
 * 安全联锁 / 报告表头 / 台架常量），用一个联合类型收口，渲染只认这一个类型。
 */
type Leaf =
  | { k: 'attr'; id: string; g: string; a: RawAttribute }
  | { k: 'param'; id: string; g: string; p: RawControlParam }
  | { k: 'ilk'; id: string; g: string; i: RawInterlock }
  | { k: 'field'; id: string; g: string; f: RawHeaderField }
  | { k: 'info'; id: string; g: string; label: string; value: string; hint: string; pending?: boolean }

/**
 * 「这一项算不算已填」——组头 `n/m` 的唯一判据。
 *
 * ⚠️ 判据演进（2026-09-28 用户拍板，第三轮口径定稿）：
 *
 * 旧判据是 `!_placeholder && value !== null`——**把 `_placeholder` 项直接排除**。
 * 后果：源材料没给值、但**人已经填上**的那 3 项（额定转速 / 额定母线电压 /
 * 整机额定相电流）永远不计入。用户实测反馈「我页面里 5 个都有值了也没写 5/5」，
 * 指的就是这个——**填了不算数，数字当然不动**。
 *
 * 现判据（用户原话：「改为有数值就算」）：
 *   - **只看有没有一个有意义的数值**，不看它来自源材料还是人工填的；
 *   - 取值时**覆盖值优先**（`override ?? 源值`），否则人填的值不参与判断；
 *   - **`null` / 空串 / 「未知」都不算有数值**。
 *     最后这条很关键：`fan_thickness`、`fan_outer_size` 在场景包里的值是
 *     **字符串「未知」**，若把它当"有值"，这两项**人没填也会显示已填**，`5/5` 虚高。
 *
 * ⚠️ 用户最初还提过「改回原值就不 +1」，随后明确**废除该条**（「采用1废除2」）：
 * 现在**不做**「值与源值比较」这层判断——填过且是有效数值即算。
 *
 * 注：本函数需要读 `overrides`，因此由调用方传入覆盖值解析器，保持纯函数。
 */
const isMeaningfulValue = (v: unknown): boolean => {
  if (v === null || v === undefined) return false
  if (typeof v === 'number') return Number.isFinite(v)
  if (typeof v === 'boolean') return true
  const s = String(v).trim()
  return s !== '' && s !== '未知' && s !== '—' && s !== '-'
}

const leafFlags = (x: Leaf, override?: unknown): Flags => {
  if (x.k === 'attr') {
    const v = override ?? x.a.value
    return { filled: isMeaningfulValue(v), pending: !!(x.a._status || x.a._placeholder) }
  }
  if (x.k === 'param') {
    const v = override ?? x.p.value
    return { filled: isMeaningfulValue(v), pending: !!x.p._status, alert: !!x.p.value_below_min }
  }
  if (x.k === 'ilk') return { filled: true, pending: !!x.i._status }
  if (x.k === 'field') return { filled: !!x.f.sample_value }
  return { filled: !x.pending, pending: x.pending }
}

/**
 * 叶子的 `paramKey` 四段键 —— **必须与 `AttrRow` / `ParamRow` / `FieldRow`
 * 里 `setParam(key, ...)` 用的那个键逐字一致**，否则组头读的是另一个格子，
 * 人填了值组头却不动。
 *
 * 三类的段位取自各自行组件的现有实现（`paramKey(flow, kind, group, name)`）：
 *   - 本体属性  `init.pa.<a.group>.<a.key>`
 *   - 控制参数  `init.cp.<p.group>.<p.key>`
 *   - 报告表头  `init.rp.header.<f.key>`（字段行固定用 `header` 作组名）
 * 其它类型（联锁 / 信息行）不参与覆盖，返回空串，查表必然取不到 → 不传 override。
 *
 * ⚠️ 这里是**第二处**手写这四段键，与行组件是重复信息。若将来改键结构，
 * 两处必须同改（本页没有统一的键构造函数导出，所以只能靠这条注释约束）。
 */
function leafKeyOf(x: Leaf): string {
  if (x.k === 'attr') return paramKey('init', 'pa', x.a.group, x.a.key)
  if (x.k === 'param') return paramKey('init', 'cp', x.p.group, x.p.key)
  if (x.k === 'field') return paramKey('init', 'rp', 'header', x.f.key)
  return ''
}

function FieldRow({ f }: { f: RawHeaderField }) {
  const uiT = useT()

  const key = paramKey('init', 'rp', 'header', f.key)
  const v = useAppStore((s) => s.overrides[key])
  const setParam = useAppStore((s) => s.setParam)
  // 字段显示名随界面语言（2026-10-15）：中文界面下 `simp(headerFieldName(f))` 与原来的
  // `simp(f.name)` 逐字相同；英文界面下取场景包平行英文名，缺失回退中文原文。
  const nm = simp(headerFieldName(f))
  return (
    <div className="flex min-h-[36px] items-center gap-2 px-4 py-1 transition-colors hover:bg-p50/60">
      <Tooltip className="min-w-0" content={uiT("{v1} · 报告模板取值位 {v2}；本项在流程 5 只带入不重填。", { v1: nm, v2: f.value_slot || '—' })}>
        <span className="flex min-w-0 items-center gap-1.5">
          <SourceTag source={v ? '人工' : '建议'} />
          {/* 7 字截断只对中文短名有意义；英文名截到 7 个字符只剩 `Custome…`，
              英文时原样交给 CSS truncate + Tooltip */}
          <span className="cursor-help truncate text-[13px] font-medium text-t1">{uiT(nm) === nm ? (/[\u3400-\u9fff]/.test(nm) ? short(nm, 7) : nm) : uiT(nm)}</span>
        </span>
      </Tooltip>
      <span className="ml-auto shrink-0">
        <Input
          value={String(v ?? '')}
          onChange={(e) => setParam(key, e.target.value)}
          aria-label={uiT(nm)}
          placeholder={uiT("待填")}
          className="h-[26px] w-[142px] text-[12.5px]"
        />
      </span>
    </div>
  )
}

function IlkRow({ i }: { i: RawInterlock }) {
  const uiT = useT()
  // tooltip 内容是场景包数据文本，需包 uiT 才能在英文界面下译出
  return (
    <Tooltip className="w-full" content={`${i.id} ${uiT(i.name)} · ${uiT(i.action)}`}>
      <div className="flex min-h-[32px] w-full cursor-help items-center gap-2 px-4 py-1">
        <Lock size={12} strokeWidth={1.9} className="shrink-0 text-t3" />
        <span className="truncate text-[12.5px] text-t1">{uiT(i.name) === i.name ? short(i.name, 10) : uiT(i.name)}</span>
        <span className="num ml-auto shrink-0 text-[12px] text-t3">{i.id}</span>
      </div>
    </Tooltip>
  )
}

function InfoRow({ x }: { x: Extract<Leaf, { k: 'info' }> }) {
  const uiT = useT()
  const displayValue = x.id.startsWith('ch-') && x.value.endsWith(BENCH_CHANNEL_PENDING)
    ? x.value.slice(0, -BENCH_CHANNEL_PENDING.length) + uiT(BENCH_CHANNEL_PENDING)
    : uiT(x.value)

  return (
    <Tooltip className="w-full" content={uiT(x.hint)}>
      <div className="flex min-h-[32px] w-full cursor-help items-center gap-2 px-4 py-1">
        <span className="truncate text-[12.5px] font-medium text-t1">{uiT(x.label)}</span>
        {x.pending ? <span className="h-[6px] w-[6px] shrink-0 rounded-full bg-t3/45" /> : null}
        <span className="num ml-auto shrink-0 truncate text-[12.5px] text-t2">{displayValue}</span>
      </div>
    </Tooltip>
  )
}

function renderLeaf(x: Leaf) {
  if (x.k === 'attr') return <AttrRow a={x.a} />
  if (x.k === 'param') return <ParamRow p={x.p} />
  if (x.k === 'ilk') return <IlkRow i={x.i} />
  if (x.k === 'field') return <FieldRow f={x.f} />
  return <InfoRow x={x} />
}

/** 二级组内超过 5 条时，按源数据自带的分组名再切一层三级子组（平铺规则一） */
function autoSubs(items: Leaf[], prefix: string) {
  if (items.length <= 5) return []
  const order: string[] = []
  const bag = new Map<string, Leaf[]>()
  for (const x of items) {
    if (!bag.has(x.g)) {
      bag.set(x.g, [])
      order.push(x.g)
    }
    bag.get(x.g)!.push(x)
  }
  if (order.length < 2) return []
  return order.map((g, i) => ({ id: `${prefix}-s${i}`, title: g, items: bag.get(g)! }))
}

const tierOf = (id: string, title: string, groups: BuiltGroup<Leaf>[]): BuiltTier<Leaf> => ({
  id,
  title,
  groups: groups.filter((g) => g.items.length > 0),
  count: groups.reduce((n, g) => n + g.items.length, 0),
})

const groupOf = (id: string, title: string, items: Leaf[]): BuiltGroup<Leaf> => ({
  id,
  title,
  items,
  subs: autoSubs(items, id),
})

/** 二 · 驱动与控制：固件登记走报告表头，控制开关与红线走 F2 可调的控制参数 */
function driveTier(pack: RawPack): BuiltTier<Leaf> {
  const f2 = (s: string) => s.startsWith('F2')
  const fw = pack.report.header_fields.filter((f) => f2(f.from_flow) && /firmware|addr|boot|model/i.test(f.key))
  const params = pack.controls.parameters.filter((p) => p.adjustable_in_flows?.some(f2))
  const isRed = (p: RawControlParam) => /载波|死区|限流|限功率|保护|热管理/.test(p.group)
  const toLeaf = (p: RawControlParam): Leaf => ({ k: 'param', id: p.key, g: p.group, p })
  return tierOf('drive', '驱动与控制', [
    groupOf('drive-fw', '固件登记', fw.map((f): Leaf => ({ k: 'field', id: f.key, g: '固件', f }))),
    groupOf('drive-mode', '控制模式', params.filter((p) => !isRed(p)).map(toLeaf)),
    groupOf('drive-red', '功率与载波', params.filter(isRed).map(toLeaf)),
  ])
}

/** 三 · 台架与仪器：合成数据的场景包没有实体台架，只出仪器登记一组 */
function benchTier(pack: RawPack): BuiltTier<Leaf> {
  const real = !pack.caps.syntheticData
  const link: Leaf[] = real
    ? [
        {
          k: 'info',
          id: 'bench-host',
          g: '台架',
          label: '台架工控机',
          value: BENCH_HOST || '未配置',
          hint: '流程 1 只核对设备在不在，不建会话、不下发动作；实际接入在流程 3。',
        },
        {
          k: 'info',
          id: 'bench-port',
          g: '台架',
          label: '远程网关端口',
          value: '8022',
          hint: '浏览器不持有凭据，私钥只在网关一侧。网关未起时本行仍按登记值显示。',
        },
      ]
    : []
  const chan: Leaf[] = real
    ? Object.values(BENCH_CHANNEL_MAP).map((c): Leaf => ({
        k: 'info',
        id: `ch-${c.signal}`,
        g: '通道',
        label: c.signal,
        value: `${c.channel} · ${BENCH_CHANNEL_PENDING}`,
        pending: true,
        hint: `${c.note}。通道号与物理端子的对应关系属客户既有接线约定，${BENCH_CHANNEL_PENDING}，界面不自行指派。`,
      }))
    : []
  const inst: Leaf[] = instrumentsOf(pack).map((d): Leaf => ({
    k: 'info',
    id: `inst-${d.name}`,
    g: '仪器',
    label: d.name,
    value: real ? '待接入' : '未接入',
    hint: `${d.hint} 仪器由场景包的实测量字典反推：谁取数就出谁，推不出来不硬凑。`,
  }))
  return tierOf('bench', '台架与仪器', [
    groupOf('bench-link', '台架接入', link),
    groupOf('bench-chan', '通道映射', chan),
    groupOf('bench-inst', '仪器登记', inst),
  ])
}

/** 五 · 运行与产出登记：本轮叫什么、跑几次、交给哪份模板 */
function outputTier(pack: RawPack): BuiltTier<Leaf> {
  const f2 = pack.report.header_fields.filter(
    (f) => f.from_flow.startsWith('F2') && !/firmware|addr|boot|model/i.test(f.key),
  )
  const runReq =
    pack.requirements.requirements.find((r) =>
      Object.keys(r.threshold ?? {}).some((k) => /^runs$|required_pass/.test(k)),
    ) ?? pack.requirements.requirements.find((r) => Object.keys(r.threshold ?? {}).some((k) => /cycles/.test(k)))
  const limits: Leaf[] = Object.entries(runReq?.threshold ?? {})
    .filter(([, v]) => typeof v === 'number')
    .slice(0, 3)
    .map(([k, v]): Leaf => ({
      k: 'info',
      id: `run-${k}`,
      g: '约束',
      label: k,
      value: String(v),
      hint: `取自判据 ${runReq?.id} ${runReq?.name}：${runReq?.criterion_text}。本轮运行约束按这条判据的阈值登记，不另编。`,
    }))
  const tpl: Leaf[] = [
    {
      k: 'info',
      id: 'tpl-file',
      g: '模板',
      label: '报告模板',
      value: fileName(pack.report.template_file).slice(0, 22),
      hint: pack.report.template_file,
    },
    {
      k: 'info',
      id: 'tpl-sec',
      g: '模板',
      label: '模板分节',
      value: `${pack.report.spec_sections.length} 节`,
      hint: `报告正文由这 ${pack.report.spec_sections.length} 节构成，表头字段在流程 5 补全。`,
    },
  ]
  return tierOf('out', '运行与产出登记', [
    groupOf('out-id', '产品与批次', f2.map((f): Leaf => ({ k: 'field', id: f.key, g: '登记', f }))),
    groupOf('out-run', '单轮运行约束', limits),
    groupOf('out-tpl', '报告模板绑定', tpl),
  ])
}

export function InitLeftPanel() {
  const uiT = useT()

  const pack = getPack()
  const nav = useNavigate()
  const locked = !!useAppStore((s) => s.confirmed.init)
  /**
   * 订阅「人改过哪些参数」。
   *
   * ⚠️ 为什么要**订阅**而不是 `getState().touched` 读一次：
   * 「待现场确认」徽标要随人填值**实时减少**。用 `getState()` 只在本次渲染时取一份，
   * store 后来变了组件也不会重渲染，徽标数字就还是旧的——
   * 那正是用户遇到的问题（「改了但数字不动」）的同类成因。
   * 这里返回的是对象引用，zustand 按引用比较，`setParam` 每次都会换新对象，
   * 所以能稳定触发重渲染。
   */
  // ⚠️ `touched` 是 `Record<string, true>`（**普通对象，不是 Set/Map**），
  // 判存在要用 `in` / 取值，不能写 `.has()`（本轮写成 `.has()` 报了
  // `Type 'Boolean' has no call signatures`，因为 `obj.has` 不存在）。
  const touchedKeys = useAppStore((s) => s.touched)
  /**
   * 订阅人工覆盖值。组头「已填 n/m」要按**覆盖后的实际值**判断
   *（用户拍板：「改为有数值就算」），所以必须读 `overrides` 而不能只看源材料。
   * 与 `touched` 同一理由：**订阅**而非 `getState()`，否则填值后组头数字不刷新。
   */
  const overrides = useAppStore((s) => s.overrides)
  const unconfirmFlow = useAppStore((s) => s.unconfirmFlow)
  const setNotice = useAppStore((s) => s.setNotice)
  const sceneId = useAppStore((s) => s.sceneId)
  /**
   * **唯一的落库入口**：确认并锁定 = 保存全部参数 + 锁定基线（2026-09-28 合并）。
   *
   * 落的快照带 `locked: true`，且 `buildSnapshot` 会把**三类参数**都写进去
   * （本体属性 `init.pa.*` + 控制参数 `init.cp.*` + 报告表头 `init.rp.*`），
   * 后续流程（调优/报告）据此取用。原「保存参数」按钮已按用户要求并入这里。
   *
   * 失败必须可见：写不进库时**不能**标成已锁定——否则人以为锁好了，
   * 刷新后参数全丢、流程状态还骗人。
   */
  const [locking, setLocking] = useState(false)

  /** 确保有一条任务记录并记下任务号（刷新后据此读回标题）。已有则沿用。 */
  const ensureTask = useCallback(async () => {
    if (readStoredTaskId(sceneId) != null) return
    const t = await createTask({
      title: pack?.scene?.product?.name || '初始化配置',
      scene_id: sceneId,
      version: 'v1',
    })
    writeStoredTaskId(sceneId, t.id)
  }, [sceneId, pack])

  const confirmAndSnapshot = useCallback(async () => {
    setLocking(true)
    try {
      await ensureTask()
      const { runId, snapshot } = await persistSnapshot({
        sceneId,
        operator: useAppStore.getState().benchUser,
        locked: true, // ← 唯一入口：从此只有这一种落库方式
      })
      /**
       * ⚠️ 必须把 runId 记进 store（2026-09-28 补）。
       *
       * 此前这里没记，于是**下游流程拿不到「本轮」是哪个**：
       * 流程 2 的「确认基线」调 `resolveBaselineRunId(sceneId, runId)` 时
       * runId 为 null，只能退化成「新建一轮」——结果同一个场景里
       * 每点一次确认就多一个**没有产物的空轮次**，
       * 而按契约 requirement-baseline 应与 config-snapshot 挂在**同一轮**上
       * （主文档 4.1 收发关系表：一轮带多份产物）。
       * 实测证据：脚本连点两次确认后，轮次列表里多出两个 kinds=[] 的空轮。
       */
      useAppStore.getState().setRunId(runId)
      useAppStore.getState().confirmFlow('init')
      /**
       * ⚠️ 数字口径：**回执也用菜单口径**（2026-09-28 用户第三轮反馈定稿）。
       *
       * 演进：先报快照条数 109 → 与菜单的 75 打架（用户点出「一共 75 条却确认了 109 条」）；
       * 改成两边都写 109 并解释「29 + 70 + 10 的构成」→ 用户仍觉得啰嗦
       * （原话：「本地属性 29 是不用写进去提示的，既然菜单写的 75 项就按照菜单为准」）。
       * 定稿：**回执只报菜单口径 + 轮次号**，不拆构成、不出现第二个数字。
       * 快照里那份 `product_attributes.length` 仍然真实存在（落库内容不变），
       * 只是**不再拿来当界面上要念给用户看的数**。
       */
      // 回执报「锁定了几项 + 哪一轮」——人是靠这个确认没漏存的。
      // 项数用**快照真实写入条数**：这是「存了几项」的准确答案，
      // 且不可能与按钮口径打架——按钮显示的 `total` 是菜单口径，
      // 用户已明确「以菜单为准」，所以这里只报轮次号 + 如实报落库条数，
      // **不再拆解构成**（用户否掉了「本体属性 29」那种写法）。
      setNotice(
        `已确认并锁定：${snapshot.product_attributes.length} 项已写入配置快照（轮次 ${runId.slice(0, 8)}），后续流程可取用`,
      )
      // 与流程 2「确认基线后跳流程 3」、流程 4「采纳后跳流程 3」保持同一种体验（用户拍板）。
      nav('/requirements')
    } catch (e) {
      // 落盘失败必须看得见：锁没锁上是两回事，不能让人以为锁好了。
      // ⚠️ 失败时**不跳转**——跳走会让人以为确认成功了。
      setNotice(`确认失败（数据未持久化，刷新后会丢）：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setLocking(false)
    }
  }, [sceneId, setNotice, ensureTask, nav])

  /**
   * ⚠️ 2026-09-28 用户的决定：**「保存参数」与「确认并锁定」合并成一个入口**。
   *
   * 此前是两条独立的路（`saveDraft` 落 `locked:false`、`confirmAndSnapshot`
   * 落 `locked:true`），理由是「存参数」与「锁基线」语义不同。
   * 但实际用起来，人改完参数要找两个按钮、容易只点一个，
   * 且**两个入口各写一套快照口径**本身就是漂移源。
   * 现在统一为：**唯一的落库入口就是「确认并锁定」**，
   * 它一次把初始化页的**全部参数**（本体属性 + 控制参数 + 报告表头）
   * 落进同一份 `config-snapshot`（带 `locked:true`），供后续流程取用。
   * 「解除确认」仍在（允许反悔再编辑），但不再是「另一种保存」。
   */

  /**
   * 挂载时按场景读回最近一份配置快照，把参数与「已确认」恢复出来。
   *
   * 这段原先挂在已被移除的那个「保存」条里，条子按用户要求删掉后必须搬到这儿——
   * 否则刷新后没人回填，等于把刚补好的持久化又拆了。
   * 读不到（还没落过）是正常态，不报错；失败只留控制台痕。
   */
  useEffect(() => {
    if (!pack) return
    void loadLatestSnapshot(sceneId)
      .then((hit) => {
        if (!hit) return
        // 不检查 alive（StrictMode 下会丢成功结果，见 flow-tune 同款说明）；
        // 回填是幂等的，重复执行没有副作用。
        applySnapshot(hit.snapshot)
        // 把「快照在哪一轮」也记进 store：刷新后下游流程（流程 2 的确认基线）
        // 才能复用**同一轮**，而不是各自新建空轮次（2026-09-28 补，见 confirmAndSnapshot 注释）。
        useAppStore.getState().setRunId(hit.runId)
      })
      .catch((e: unknown) => {
        console.warn('[flow-init] 配置快照读回失败，参数按未保存显示：', e)
      })
  }, [sceneId, pack])

  if (!pack) return <Empty text={uiT("场景包未加载")} />

  const attrs = pack.attributes.attributes
  /**
   * 「待现场确认」的条数 = **源材料没给值、且人还没填过**的条数。
   *
   * ⚠️ 口径演进（2026-09-28 用户拍板）：
   *
   * 原实现是 `attrs.filter((a) => a._placeholder).length`——**纯静态统计**，
   * 数的是场景包 JSON 里 `_placeholder: true` 有几条。问题是它是**常量**：
   * 人把值填上了，`overrides` 里有值了，但 `a._placeholder` 仍是 `true`，
   * 于是徽标数字**永远不动**。用户实测反馈：「怎么我已经修改并锁定了占位还是 0 没有变成 1」。
   *
   * 这确实说不通：人填了值，界面还说它「没确认」。
   * 现在改为**按「人是否填过值」算**（用户选定的口径）：
   *   - 填过的（`touched` 里有这个键）→ 从计数里减掉，并显示为「已确认」
   *   - 全填完 → 徽标自动消失
   *
   * 语义随之更准：它表达的是「**还有几项没着落**」，
   * 而不是「源材料当初缺几项」（后者是历史事实，人补完也不该继续算作待办）。
   */
  const holes = attrs.filter((a) => {
    if (!a._placeholder) return false
    // 人填过这一项 → 不再计入「待现场确认」
    return !touchedKeys[paramKey('init', 'pa', a.group, a.key)]
  }).length
  /** 已补上有值的占位项数（人填过了）——用于「已补 N」提示，让人看到自己的进度 */
  const holesFilled = attrs.filter(
    (a) => a._placeholder && touchedKeys[paramKey('init', 'pa', a.group, a.key)],
  ).length

  // 一 · 被测对象：骨架取自场景包 product-attributes.json 的 group_tiers，不写死在代码里
  const objTiers = buildTiers<Leaf>(
    readTiers(pack.attributes),
    attrs.map((a): Leaf => ({ k: 'attr', id: a.key, g: a.group, a })),
    (x) => x.id,
    (x) => x.g,
  )
  // 四 · 安全联锁：safety-interlocks.json 自己的四个一级类在本页降一级当二级组用
  const ilkSpec = readTiers(pack.interlocks)
  const ilkLeaves = pack.interlocks.interlocks.map((i): Leaf => ({ k: 'ilk', id: i.id, g: i.type, i }))
  const ilkTier: BuiltTier<Leaf> = {
    id: 'ilk',
    title: '安全联锁',
    groups: ilkSpec.map((t) => {
      const built = buildTiers<Leaf>([t], ilkLeaves, (x) => x.id)
      const gs = built[0]?.groups ?? []
      return {
        id: t.id,
        title: t.title,
        items: gs.flatMap((g) => g.items),
        subs: gs.length > 1 ? gs.map((g) => ({ id: g.id, title: g.title, items: g.items })) : [],
      }
    }),
    count: ilkLeaves.length,
  }

  const tiers: BuiltTier<Leaf>[] = [
    ...objTiers,
    driveTier(pack),
    benchTier(pack),
    ilkTier,
    outputTier(pack),
  ].filter((t) => t.groups.length > 0)
  /** 左栏菜单项数。**这是按钮与提示唯一使用的数字**（用户拍板：以菜单为准） */
  const total = tiers.reduce((n, t) => n + t.count, 0)


  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <header className="flex h-[44px] shrink-0 items-center gap-2.5 border-b border-line-soft px-4">
        <Boxes size={17} strokeWidth={1.9} className="shrink-0 text-p700" />
        <h2 className="text-[16px] leading-none font-semibold tracking-tight text-t1">{uiT("初始化配置")}</h2>
        <span className="num text-[12px] text-t3">{total}</span>
        <div className="ml-auto flex items-center gap-1.5">
          {/* ⚠️ 措辞与口径（2026-09-28 用户拍板）：
              「占位」→ **「待现场确认」**（与 tooltip 描述用词一致，意思更直白）；
              数字 = **源材料没给、且人还没填**的条数（人填过就从计数里减掉）。
              全填完徽标**自动消失**——那说明这一轮没有待办了。
              另有「已补 N」在下方提示：让人看得见自己的进度，
              而不是只看到一个「还有几个没弄」的负数。 */}
          {holes ? (
            <Badge
              tone="neutral"
              mono
              title={uiT("{v1} 项在源材料里没有值、且尚未填写，需现场实测或由客户确认{v2}", { v1: holes, v2: holesFilled ? `（已补 ${holesFilled} 项）` : '' })}
            >
              {uiT("待现场确认")}{holes}
            </Badge>
          ) : null}
        </div>
      </header>

      {/* 「随传随用 / 选文件」上传条已按用户要求移除（2026-09-24）。
          它和左栏顶部的「上传」（知识条上那枚，走完整的五阶段转化链路）
          功能重复，两条并排反而让人不知道该用哪个。
          真正上传资料的入口只有一处：知识条上的「上传」。
          ------------------------------------------------------------
          此前这里还有一条「产品名称 + 保存」，同样因与底部「确认配置」
          重复而移除（见下方注释）。 */}

      {/* 「产品名称 + 保存」条已按用户要求移除（2026-09-24）。它原本是阶段 2
          的保存闭环演示件，但页面底部「确认配置」本身就是落库动作，
          两条并排会让人不知道该按哪个。产品名仍显示在顶部标题与上面那行里。 */}

      <div className="fade-b min-h-0 flex-1 overflow-y-auto pb-2">
        <ConfigOverview flow="init" assist={<ConfigSuggestionButton stage="init" pending={locking} />}
          key={pack.scene.id}
          count={total}
        >
          <UnifiedConfigPanel
            flow="init"
            tiers={tiers}
            // 一级类只展开第一个，其余折叠（06b 第 1.2 节）
            defaultOpen={0}
            itemKey={(x) => x.id}
            render={renderLeaf}
            // 「已填 n/m」要**把人工覆盖值算进来**（2026-09-28 用户拍板：
            // 「改为有数值就算」）。`overrides` 以 `paramKey` 拼出的四段键索引：
            // 本体属性 `init.pa.<组>.<键>`、控制参数 `init.cp.<组>.<键>`、
            // 报告表头 `init.rp.header.<键>`。取不到就是没有覆盖，回落源材料值。
            flags={(x) => leafFlags(x, overrides[leafKeyOf(x)])}
            tierIcon={(t) => iconOf(t, 15)}
            groupIcon={(t) => iconOf(t)}
          />
        </ConfigOverview>
      </div>

      <footer className="shrink-0 border-t border-line-soft bg-white/85 px-4 py-3 backdrop-blur">
        {/* ──────── 单一入口（2026-09-28 合并）───────
            此前是两个按钮：「保存参数」（落 locked:false）+「确认并锁定」
            （落 locked:true）。用户要求合并成一个——
            点「确认并锁定」= **保存全部参数 + 锁定基线**，一次做完。
            落下的那份 config-snapshot 带 locked:true 且含三类参数
            （本体属性 + 控制参数 + 报告表头），后续流程据此取用。

            「解除确认」保留：它是「反悔再编辑」的出口，不是「另一种保存」。
            解除后参数仍留在界面与快照里（不清值），只是不再标为已锁定。 */}
        <div className="flex items-center gap-2">
          {/* ⚠️ 数字口径（2026-09-28 三轮用户反馈后定稿）：
              **以左栏菜单的项数为准**（用户原话：「既然菜单写的 75 项就按照菜单为准」），
              且**不在提示里拆解「本地属性 29 项」这类内部构成**——
              用户原话：「本地属性 29 是不用写进去提示的」。

              演进过程：曾用 `lockedCount`（快照条数 109）导致「菜单 75 却显示 109」，
              再改成两边都写 109 并解释构成，仍嫌啰嗦。定稿：
              **按钮与提示都只报菜单口径的 `total`**，提示里不再出现内部构成拆解。
              快照实际写入条数仍在落库回执里报（那是「存了几项」的答案，
              给需要核对的人看），但**不摆在按钮上**，避免与菜单数字打架。 */}
          {locked ? (
            <Tooltip
              content={uiT(`已确认并锁定（轮次快照已写入，后续流程可取用）。解除后可再编辑，下游基线同步失效。`)}
              className="flex-1"
            >
              <Button
                block
                size="lg"
                variant="secondary"
                icon={<Lock size={15} strokeWidth={2} />}
                onClick={() => unconfirmFlow('init')}
              >
                {uiT("解除确认 · ")}{total} {uiT(" 项")}</Button>
            </Tooltip>
          ) : (
            <span className="flex-1">
              <ConfirmFooter
                label={locking ? uiT('锁定中…') : uiT('确认并锁定')}
                count={total}
                unit="项"
                hint={
                  uiT("一次保存并锁定全部参数：菜单共 {v1} 项。", { v1: total }) +
                  (holes
                    ? uiT("其中 {v1} 项源材料没给值、你还没填（已补 {v2} 项）——", { v1: holes, v2: holesFilled }) +
                      uiT(`这些项**不阻塞锁定**，会继续按「待现场确认」跟踪。`)
                    : uiT(`源材料缺的项已全部补齐。`)) +
                  uiT(`点击后写入配置快照（locked:true）并进入流程 2。`)
                }
                onClick={() => void confirmAndSnapshot()}
              />
            </span>
          )}
        </div>
      </footer>
    </div>
  )
}

/* -------------------------------------------------- 卡片 · 产品示意图（hero） */

/** 变体名收成 ≤4 字的短名，全名进 tooltip */
function shortVariant(name: string) {
  if (/VSP/i.test(name)) return 'VSP'
  if (/非|无|無/.test(name)) return '无二极管'
  if (/结构|結構|示意|简图|簡圖/.test(name)) return '结构图'
  if (/原理图|原理圖/.test(name)) return '原理图'
  return simp(short(name.replace(/方案/g, ''), 4))
}

/** 变体登记的是 PDF 原始路径；包内渲出来的分页图挂在 scene.images 上，按 _source.file 对号。 */
function imageOf(pack: RawPack, file: string) {
  return (
    pack.scene.images?.find((im) => {
      const src = (im as { _source?: { file?: string } })._source
      return src?.file === file
    })?.path ?? null
  )
}

function ProductHero({ full }: { full?: boolean }) {
  const uiT = useT()

  const pack = getPack()
  const [pick, setPick] = useState(-1)
  if (!pack) return <Empty text={uiT("场景包未加载")} />

  const vs = pack.scene.schematic_variants
  const srcOf = (v: { file: string; rendered?: string }) =>
    v.rendered ?? (v.file.startsWith('assets/') ? v.file : imageOf(pack, v.file))
  if (!vs.length)
    return <EmptyState icon={<CircuitBoard size={24} strokeWidth={1.5} />} title={uiT("未登记图纸")} />

  const first = Math.max(0, vs.findIndex((v) => srcOf(v)))
  const i = pick >= 0 ? Math.min(pick, vs.length - 1) : first
  const cur = vs[i]
  const src = srcOf(cur)
  const img = src ? pack.scene.images?.find((im) => im.path === src) : undefined
  // 场景包的 chip 字段有两种写法：单一型号（FU6832N…），或「不锁定主控 + 几家参考设计」
  // 的整段说明。后者里抠一个型号出来当徽标是把参考设计说成被测件，这里退回「未锁定主控」。
  const chipText = pack.scene.product.chip
  const chip = /不锁定|未锁定|参考设计/.test(chipText)
    ? '未锁定主控'
    : (/([A-Z]{1,3}\d{3,5}[A-Z]?)/.exec(chipText)?.[1] ?? '主控')

  return (
    <div className={cn(full ? 'relative h-full w-full' : 'absolute inset-0')}>
      {src ? (
        <img
          src={pack.base + src}
          alt={uiT(img?.title ?? cur.name)}
          className={cn('h-full w-full', full ? 'object-contain' : 'object-cover object-center')}
        />
      ) : (
        <div className="flex h-full w-full flex-col items-center justify-center gap-1.5 bg-p50 px-6 text-center">
          <CircuitBoard size={24} strokeWidth={1.5} className="text-p400" />
          <span className="text-[13px] text-t2">{uiT("该变体未渲染分页图")}</span>
          <span className="num max-w-full truncate text-[12px] text-t3" title={cur.file}>
            {fileName(cur.file)}
          </span>
        </div>
      )}

      {/* 芯片徽标 */}
      <Tooltip
        content={uiT("{v1}；图为{v2}{v3}，场景包未登记产品实物照片，不拿渲染图冒充实物。", { v1: chipText, v2: img?.title ?? cur.name, v3: img?.render ? `（${img.render}）` : '' })}
      >
        <span className="absolute top-2.5 left-2.5 inline-flex h-[26px] cursor-help items-center gap-1.5 rounded-full border border-white/70 bg-white/85 px-2.5 shadow-[0_1px_6px_rgba(31,42,36,.12)] backdrop-blur">
          <Cpu size={14} strokeWidth={1.9} className="text-p700" />
          <span className="num text-[12.5px] font-semibold text-t1">{uiT(chip)}</span>
        </span>
      </Tooltip>

      {/* 变体切换 */}
      <div className="absolute right-2.5 bottom-2.5 inline-flex items-center gap-2 rounded-full border border-white/70 bg-white/85 px-2.5 py-1.5 shadow-[0_1px_6px_rgba(31,42,36,.12)] backdrop-blur">
        {vs.slice(0, 3).map((v, k) => (
          <Tooltip key={v.name} content={`${uiT(v.name)} · ${fileName(v.file)}`}>
            <button
              type="button"
              onClick={() => setPick(k)}
              aria-label={uiT(v.name)}
              aria-pressed={i === k}
              className={cn(
                'h-[8px] w-[8px] rounded-full transition-colors',
                i === k ? 'bg-p700' : 'bg-p300 hover:bg-p400',
              )}
            />
          </Tooltip>
        ))}
        <span className="text-[12px] font-medium text-t2">{uiT(cur.name) === cur.name ? uiT(shortVariant(cur.name)) : uiT(cur.name)}</span>
      </div>
    </div>
  )
}

/* ---------------------------------------------- 卡片 · 原理图与文档读取（槽 2） */

interface KeyDoc {
  doc: RawDocument
  icon: LucideIcon
  label: string
  extra?: number
}

/** 三份关键文档：芯片数据手册 / 参数配置源码 / 原理图。按 type 取，取不到就跳过，不硬凑。 */
function keyDocs(pack: RawPack): KeyDoc[] {
  const all = pack.documents.documents.filter((d) => d.exists)
  const pickBy = (re: RegExp) => all.filter((d) => re.test(d.type) || re.test(d.title))
  const out: KeyDoc[] = []
  const ds = pickBy(/数据手册|规格书|standard|标准/i)[0]
  if (ds) out.push({ doc: ds, icon: FileText, label: '数据手册' })
  const src = pickBy(/驱动程序|源码|配置/)[0]
  if (src) out.push({ doc: src, icon: FileCode2, label: short(fileName(src.path), 10) })
  const sch = pickBy(/原理图/)
  if (sch.length) out.push({ doc: sch[0], icon: CircuitBoard, label: '原理图', extra: sch.length })
  // 三类没配齐的包（玻璃升降器包只有法规与报告类文档）按体积补到三份，卡里不留空行
  const has = new Set(out.map((x) => x.doc.id))
  for (const d of [...all].sort((a, b) => (b.size_bytes ?? 0) - (a.size_bytes ?? 0))) {
    if (out.length >= 3) break
    if (has.has(d.id)) continue
    has.add(d.id)
    out.push({ doc: d, icon: FileText, label: short(simp(d.title), 10) })
  }
  return out
}

function DocIntake({ full }: { full?: boolean }) {
  const uiT = useT()

  const pack = getPack()
  if (!pack) return <Empty text={uiT("场景包未加载")} />
  const docs = keyDocs(pack)
  if (!docs.length)
    return <EmptyState icon={<FileText size={24} strokeWidth={1.5} />} title={uiT("未登记文档")} />
  const attrs = pack.attributes.attributes
  const filled = attrs.filter((a) => !a._placeholder && a.value !== null).length

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div
        className="no-scrollbar flex min-h-0 flex-1 flex-col justify-center overflow-y-auto"
        style={{
          maskImage: 'linear-gradient(to bottom, #000 calc(100% - 12px), transparent 100%)',
          WebkitMaskImage: 'linear-gradient(to bottom, #000 calc(100% - 12px), transparent 100%)',
        }}
      >
        {docs.map((d) => (
          <Tooltip
            key={d.doc.id}
            className="w-full"
            content={`${uiT(d.doc.title)}（${d.doc.id}）· ${sizeText(d.doc.size_bytes)}\n${d.doc.path}`}
          >
            <div className="flex w-full cursor-help items-center gap-2.5 border-b border-line-soft py-[7px] last:border-b-0">
              <span className="flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-tpx bg-p50 text-p700">
                <d.icon size={14} strokeWidth={1.75} />
              </span>
              <span className="truncate text-[13px] font-medium text-t1">{uiT(d.label)}</span>
              {d.extra && d.extra > 1 ? (
                <span className="num shrink-0 text-[12px] text-t3">×{d.extra}</span>
              ) : null}
              <span className="num ml-auto shrink-0 text-[12px] text-t3">
                {sizeText(d.doc.size_bytes)}
              </span>
            </div>
          </Tooltip>
        ))}
        {full ? (
          <p className="pt-2 text-[12px] leading-5 text-t3">
            {uiT("回填只认这几份源文件里写死的值：数据手册给芯片电气规格，Customer.h 给整机配置， 原理图给采样链路与分压网络。源材料没写的项留空标「待确认」，不按经验值补。")}</p>
        ) : null}
      </div>
      {/* 回填进度：让这张卡除了文件名之外还有一条可读的量 */}
      <div className="flex shrink-0 items-center gap-2 pt-1.5">
        <span className="text-[12px] text-t3">{uiT("回填")}</span>
        <span className="h-[5px] min-w-0 flex-1 overflow-hidden rounded-full bg-p100">
          <span
            className="block h-full rounded-full bg-p600 transition-[width] duration-500"
            style={{ width: `${Math.round((filled / (attrs.length || 1)) * 100)}%` }}
          />
        </span>
        <span className="num shrink-0 text-[12px] font-semibold text-t1">
          {filled}
          <span className="font-normal text-t3">/{attrs.length}</span>
        </span>
      </div>
      <div className="shrink-0 pt-2">
        <Tooltip content={uiT("已从源文件填得 {v1} / {v2} 项；其余项源材料确实没给。", { v1: filled, v2: attrs.length })}>
          <span className="block">
            <Button block size="sm" variant="secondary" icon={<Wand2 size={13} strokeWidth={1.9} />}>
              {uiT("按这三份回填")}</Button>
          </span>
        </Tooltip>
      </div>
    </div>
  )
}

/* --------------------------------------------------------------- 卡片 · 工程树 */

interface TNode {
  name: string
  children: Map<string, TNode>
  doc?: RawDocument
}

function insert(root: TNode, path: string, doc?: RawDocument) {
  const parts = path.split('/').filter(Boolean)
  let cur = root
  parts.forEach((p, i) => {
    if (!cur.children.has(p)) cur.children.set(p, { name: p, children: new Map() })
    cur = cur.children.get(p)!
    if (i === parts.length - 1) cur.doc = doc
  })
}

/** 把只有一个子目录的链压成一行，避免一长串单链目录把卡撑满 */
function compact(n: TNode): { label: string; node: TNode } {
  const names = [n.name]
  let cur = n
  while (cur.children.size === 1 && !cur.doc) {
    const only = [...cur.children.values()][0]
    if (!only.children.size) break
    names.push(only.name)
    cur = only
  }
  return { label: names.filter(Boolean).join('/'), node: cur }
}

const leafIcon = (d: RawDocument): LucideIcon =>
  /原理图/.test(d.type) ? CircuitBoard : /驱动程序|源码/.test(d.type) ? FileCode2 : FileText

/** 客户工程根目录：路径里以 Program / Project / 工程 结尾的那一段，出现次数最多的那个。 */
function projectRootOf(docs: RawDocument[]) {
  const hits = new Map<string, number>()
  for (const d of docs) {
    const parts = d.path.split('/')
    const i = parts.findIndex((x) => /(program|project|工程)$/i.test(x))
    if (i > 0) {
      const key = parts.slice(0, i + 1).join('/')
      hits.set(key, (hits.get(key) ?? 0) + 1)
    }
  }
  return [...hits.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null
}

/** 被测件的中文名：括号里的出处说明进 tooltip，卡头只留产品名本身 */
function productShort(pack: RawPack) {
  return pack.scene.product.name.replace(/[（(].*$/, '').trim()
}

/** 工程树：客户工程按真实目录（Software / Hardware / Document）铺，工程之外的源材料按类型归一堆。 */
function buildTree(pack: RawPack) {
  const docs = pack.documents.documents.filter((d) => d.path && d.exists)
  const proj = projectRootOf(docs)
  const root: TNode = { name: '', children: new Map() }
  const rest: RawDocument[] = []
  for (const d of docs) {
    if (proj && d.path.startsWith(`${proj}/`)) insert(root, d.path.slice(proj.length + 1), d)
    else rest.push(d)
  }
  if (rest.length) {
    const other: TNode = { name: '其他来源', children: new Map() }
    for (const d of rest) {
      if (!other.children.has(d.type))
        other.children.set(d.type, { name: d.type, children: new Map() })
      other.children.get(d.type)!.children.set(d.id, {
        name: fileName(d.path),
        children: new Map(),
        doc: d,
      })
    }
    root.children.set('其他来源', other)
  }
  return { node: root, prefix: proj, files: docs.length }
}

function ProjectTree({ full }: { full?: boolean }) {
  const uiT = useT()

  const pack = getPack()
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const tree = useMemo(() => (pack ? buildTree(pack) : null), [pack])

  if (!pack || !tree) return <Empty text={uiT("场景包未加载")} />
  if (!tree.node.children.size)
    return <EmptyState icon={<Folder size={24} strokeWidth={1.5} />} title={uiT("未登记源文件")} />

  const count = (n: TNode): number =>
    (n.doc ? 1 : 0) + [...n.children.values()].reduce((s, c) => s + count(c), 0)

  const render = (n: TNode, depth: number, key: string): ReactNode[] => {
    const rows: ReactNode[] = []
    // 工程自己的三根（Software / Hardware / Document）排前，工程外的归到最后
    const rank = (x: TNode) =>
      x.name === '其他来源' ? 9 : /^software$/i.test(x.name) ? 0 : /^hardware$/i.test(x.name) ? 1 : 2
    const kids = [...n.children.values()].sort(
      (a, b) => rank(a) - rank(b) || b.children.size - a.children.size || a.name.localeCompare(b.name),
    )
    for (const raw of kids) {
      const isDir = raw.children.size > 0
      const { label, node: k } = isDir ? compact(raw) : { label: raw.name, node: raw }
      const id = `${key}/${label}`
      const n2 = count(k)
      // 默认只摊开「一层就是文件」的小目录，大堆的留给点击展开，卡里不出半行硬切
      const flat = [...k.children.values()].every((c) => c.children.size === 0)
      const isOpen = open[id] ?? (depth < (full ? 2 : 1) && flat && n2 <= (full ? 24 : 4))
      rows.push(
        <div
          key={id}
          className="flex h-[24px] items-center gap-1.5 text-[12.5px]"
          style={{ paddingLeft: depth * 13 }}
        >
          {isDir ? (
            <button
              type="button"
              aria-label={isOpen ? uiT('折叠') : uiT('展开')}
              aria-expanded={isOpen}
              onClick={() => setOpen((o) => ({ ...o, [id]: !isOpen }))}
              className="flex h-[16px] w-[14px] shrink-0 items-center text-t3 transition-colors hover:text-p700"
            >
              <ChevronRight
                size={13}
                strokeWidth={2}
                className={cn('transition-transform duration-200', isOpen && 'rotate-90 text-p600')}
              />
            </button>
          ) : (
            <span className="w-[14px] shrink-0" />
          )}
          <span className="shrink-0 [&>svg]:block">
            {isDir ? (
              <Folder size={13} strokeWidth={1.9} className="text-p600" />
            ) : (
              (() => {
                const Ic = raw.doc ? leafIcon(raw.doc) : FileText
                return <Ic size={13} strokeWidth={1.9} className="text-t3" />
              })()
            )}
          </span>
          <Tooltip content={raw.doc ? `${uiT(raw.doc.title)}\n${raw.doc.path}` : uiT(label)}>
            <span className={cn('cursor-help truncate', isDir ? 'font-medium text-t1' : 'text-t2')}>
              {label}
            </span>
          </Tooltip>
          <span className="num ml-auto shrink-0 text-[12px] text-t3">
            {isDir ? n2 : sizeText(raw.doc?.size_bytes)}
          </span>
        </div>,
      )
      if (isDir && isOpen) rows.push(...render(k, depth + 1, id))
    }
    return rows
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div className="flex shrink-0 items-baseline gap-1.5 pb-1">
        <Tooltip
          content={uiT("{v1}\n场景包 {v2}\n{v3}", { v1: pack.scene.product.name, v2: pack.scene.id, v3: tree.prefix ?? '本场景包的源材料不在同一个工程目录下' })}
        >
          <span className="cursor-help truncate text-[12.5px] font-medium text-t1">
            {productShort(pack)}
          </span>
        </Tooltip>
        <span className="num min-w-0 truncate text-[12px] text-t3">{pack.scene.id}</span>
        <span className="num ml-auto shrink-0 text-[12px] text-t3">{tree.files}</span>
      </div>
      <div
        className="no-scrollbar min-h-0 flex-1 overflow-y-auto"
        style={{
          maskImage: 'linear-gradient(to bottom, #000 calc(100% - 18px), transparent 100%)',
          WebkitMaskImage: 'linear-gradient(to bottom, #000 calc(100% - 18px), transparent 100%)',
        }}
      >
        {render(tree.node, 0, '')}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------- 卡片 · 安全联锁 */

const TYPE_ORDER = ['硬件', '流程', '人员'] as const

function InterlockRing({ full }: { full?: boolean }) {
  const uiT = useT()
  const pack = getPack()
  if (!pack) return <Empty text={uiT("场景包未加载")} />
  const items = pack.interlocks.interlocks
  const counts = TYPE_ORDER.map((t) => ({ t, n: items.filter((i) => i.type === t).length }))
  // 环形进度表示「已带可核验阈值」的条数占比：硬件项多数有固件阈值，流程与人员项靠人放行。
  const withTh = items.filter((i) => i.threshold && Object.keys(i.threshold).length > 0).length
  const human = items.filter((i) => i.type === '人员' || i.type === '流程').length
  const R = 22
  const C = 2 * Math.PI * R
  const ratio = items.length ? withTh / items.length : 0

  return (
    <div className="flex h-full min-h-0 w-full items-center gap-4">
      <Tooltip content={uiT("共 {v1} 条联锁，其中 {v2} 条带可核验阈值；流程与人员共 {v3} 条要在流程 4 逐条放行。", { v1: items.length, v2: withTh, v3: human })}>
        <div className="relative shrink-0 cursor-help">
          <svg width="58" height="58" viewBox="0 0 58 58">
            <circle cx="29" cy="29" r={R} fill="none" stroke="var(--p-100)" strokeWidth="6" />
            <circle
              cx="29"
              cy="29"
              r={R}
              fill="none"
              stroke="var(--p-600)"
              strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={`${C * ratio} ${C}`}
              transform="rotate(-90 29 29)"
              style={{ transition: 'stroke-dasharray .4s cubic-bezier(.22,.75,.3,1)' }}
            />
          </svg>
          <span className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="num text-[17px] leading-none font-semibold text-t1">{withTh}</span>
            <span className="num text-[12px] text-t3">/{items.length}</span>
          </span>
        </div>
      </Tooltip>

      <div className="min-w-0 flex-1">
        {counts.map(({ t, n }) => (
          <Tooltip
            key={t}
            className="w-full"
            content={uiT("{v1}：{v2}{v3}", { v1: uiT(t), v2: uiT(pack.interlocks.types[t] ?? ''), v3: t === '硬件' ? '' : uiT('（{v1} 条待放行，流程 4 逐条确认）', { v1: human }) })}
          >
            <div className="flex w-full cursor-help items-center gap-1.5 border-b border-line-soft py-[5px] text-[12.5px] text-t2 last:border-b-0">
              <span
                className={cn(
                  'h-[7px] w-[7px] shrink-0 rounded-full',
                  t === '硬件' ? 'bg-p600' : t === '流程' ? 'bg-p300' : 'bg-warn',
                )}
              />
              {uiT(t)}
              <span className="num ml-auto text-[13px] font-semibold text-t1">{n}</span>
            </div>
          </Tooltip>
        ))}
      </div>

      {full ? (
        <ul className="max-h-[400px] min-w-0 flex-1 overflow-y-auto">
          {items.map((i) => (
            <li key={i.id} className="flex items-center gap-2 border-b border-line-soft py-1 last:border-b-0">
              <span className="num shrink-0 text-[12px] text-t3">{i.id}</span>
              <Tooltip content={uiT(i.action)}>
                <span className="cursor-help truncate text-[12.5px] text-t1">{uiT(i.name)}</span>
              </Tooltip>
              <Badge tone="neutral" className="ml-auto">
                {uiT(i.type)}
              </Badge>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------- 卡片 · 台架实况 */

const INSTRUMENT_RULES: { re: RegExp; icon: LucideIcon; name: string; hint: string }[] = [
  {
    re: /示波器|rigol/i,
    icon: Activity,
    name: '数字示波器',
    hint: '实测量字典里由示波器取的量：FG 频率、母线与相电流峰值、三相相位差。',
  },
  {
    re: /红外|CMD7/i,
    icon: Radar,
    name: '红外转速计',
    hint: '机械转速真值由红外转速计 / CMD7 FG2 取，用来校核 FG 换算出的转速。',
  },
  {
    re: /力传感器/,
    icon: Gauge,
    name: '力传感器',
    hint: '防夹力与堵转力由力传感器取，量程按堵转力 ≥212 N 选型。',
  },
  {
    re: /位移传感器/,
    icon: Ruler,
    name: '位移传感器',
    hint: '开口、行程与回缩量由位移传感器取，分辨率 0.05 mm。',
  },
  {
    re: /电流传感器/,
    icon: Zap,
    name: '电流传感器',
    hint: '工作电流与堵转电流由电流传感器取，兼作换向纹波计数源。',
  },
  {
    re: /程控电源/,
    icon: Zap,
    name: '程控电源',
    hint: '试验电压由程控电源给并回读；起动电压试验靠它缓升。',
  },
  {
    re: /声级计/,
    icon: Waves,
    name: '声级计',
    hint: '工作噪音测点在电机出力轴正上方 300 mm，取全过程最大值。',
  },
]

/** 仪器从场景包自己的实测量字典推：谁取数就出谁，推不出来就不出这一行，不硬凑。 */
function instrumentsOf(pack: RawPack) {
  const hows = Object.values(pack.requirements.runtime_measures ?? {}).map((m) => m.obtained_by ?? '')
  return INSTRUMENT_RULES.filter((r) => hows.some((h) => r.re.test(h))).slice(0, 3)
}

function BenchLive({ full }: { full?: boolean }) {
  const uiT = useT()

  const pack = getPack()
  const [state, setState] = useState<ConnState>('connecting')
  useEffect(() => {
    let alive = true
    void probeDevice('bench')
      .then((r) => alive && setState(r.online ? 'connected' : 'closed'))
      .catch(() => alive && setState('error'))
    return () => {
      alive = false
    }
  }, [])
  if (!pack) return <Empty text={uiT("场景包未加载")} />

  const online = state === 'connected'
  const rows = [
    {
      icon: Monitor,
      name: '台架工控机',
      meta: BENCH_HOST || '未配置',
      status: (online ? 'done' : 'empty') as 'done' | 'empty',
      text: online ? '在线' : '未接入',
      hint: online
        ? '网关 :8022 在线，可开 SSH 会话与远程取图。'
        : '网关未启动，流程 2 不需要连台架；起法：cd c/components/webssh && npm run gateway，端口 8022。',
    },
    ...instrumentsOf(pack)
      .slice(0, full ? 3 : 2)
      .map((d) => ({
        icon: d.icon,
        name: d.name,
        meta: '待接入',
        status: 'empty' as const,
        text: '未接入',
        hint: `${d.hint} 初始化阶段不建会话，实际接入在流程 4。`,
      })),
  ]

  return (
    <div
      className="no-scrollbar flex h-full min-h-0 w-full flex-col overflow-y-auto"
      style={{
        maskImage: 'linear-gradient(to bottom, #000 calc(100% - 14px), transparent 100%)',
        WebkitMaskImage: 'linear-gradient(to bottom, #000 calc(100% - 14px), transparent 100%)',
      }}
    >
      {rows.map((r) => (
        <Tooltip key={r.name} className="w-full" content={uiT(r.hint)}>
          <div className="flex w-full cursor-help items-center gap-2.5 border-b border-line-soft py-[7px] last:border-b-0">
            <span className="shrink-0 text-p600 [&>svg]:block">
              <r.icon size={14} strokeWidth={1.8} />
            </span>
            <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-t1">{uiT(r.name)}</span>
            <span className="num shrink-0 text-[12px] text-t3">{uiT(r.meta)}</span>
            <StatusDot status={r.status} label={uiT(r.text)} />
          </div>
        </Tooltip>
      ))}
      {/* 最近一次台架截图：网关未起时没有图，给缩略占位而不是留白 */}
      <Tooltip
        className="w-full"
        content={
          online
            ? uiT("最近一次取图来自台架工控机{v1}，点开可看全图。", { v1: BENCH_PULL_DIR ? ` ${BENCH_PULL_DIR}` : '' })
            : uiT('网关未启动，本场景包里也没有留档的台架截图，这里是占位框——不拿别处的图冒充台架实况。')
        }
      >
        <div className="mt-1.5 flex w-full shrink-0 cursor-help items-center gap-2.5">
          <span className="paper-grid flex h-[38px] w-[62px] shrink-0 items-center justify-center rounded-tpx border border-line-soft bg-p50 text-p400">
            <ImageIcon size={16} strokeWidth={1.75} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[12.5px] font-medium text-t2">{uiT("最近一次截图")}</span>
            <span className="block truncate text-[12px] text-t3">{online ? uiT('待取图') : uiT('无留档')}</span>
          </span>
        </div>
      </Tooltip>
      {full ? (
        <p className="pt-2 text-[12px] leading-5 text-t3">
          {uiT("浏览器不持有任何凭据；私钥只在网关一侧，devices.json 里写的是环境变量名 FORTIOR_WIN_KEY。 初始化配置阶段只核对设备在不在，不下发任何动作。")}</p>
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------------- 装配 */

export const initCards = {
  'product-view': ProductHero,
  schematic: DocIntake,
  'project-tree': ProjectTree,
  interlock: InterlockRing,
  'bench-live': BenchLive,
}

// 左栏整块接管：壳层默认参数栏没有分组图标、占位色标与上传条。
registerLeftPanel('init', InitLeftPanel)
