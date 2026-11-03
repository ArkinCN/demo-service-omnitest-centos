import {
  loadPack,
  setPack,
  byGroup,
  headerFieldName,
  sourceLine,
  statusOf,
  type RawAttribute,
  type RawPack,
} from '../features/scene/pack'
import { fetchJson } from '../features/shared/fetchJson'
import { MOCK_SCENE } from './mock/motor.cooling-fan.fu6832'
import { FLOW_IDS } from './types'
import type {
  CardInstance,
  ChecklistItem,
  FlowContent,
  FlowId,
  ItemStatus,
  ParamGroup,
  ParamItem,
  ScenePackage,
  ToolGroup,
} from './types'

/**
 * 场景包加载适配层。
 *
 * 真实场景包是一个目录下的 10 份 JSON（不是单文件），整目录已复制到
 * public/scenes/<sceneId>/，源目录见
 * [源] motor.cooling-fan.fortior-fu6832/README.md
 *
 * 本文件负责把它压成壳层的 ScenePackage（左栏参数、卡槽、清单）。
 * 卡片内部要用的明细直接读 src/features/scene/pack.ts 的原始结构，不经这里。
 * 取不到时回落到内置 mock，保证任何时候都能渲染。
 */
export async function loadScene(sceneId: string): Promise<ScenePackage> {
  const pack = await loadPack(sceneId)
  setPack(pack)
  if (!pack) return MOCK_SCENE
  return adaptScene(pack, sceneId)
}

/* --------------------------------------------------------------- 小工具 */

const st = (ok: boolean, na = false): ItemStatus => (na ? 'na' : ok ? 'done' : 'alert')

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

/** 小数位：优先按 step 的量级定，step 是整数时再退回按当前值定（最多 4 位）。 */
export function decimalsOf(n: number | null | undefined): number {
  if (n === null || n === undefined || !Number.isFinite(n) || n === 0) return 0
  const e = n.toExponential()
  const exp = Number(/e([+-]\d+)$/.exec(e)?.[1] ?? 0)
  const mant = e.split('e')[0].replace('-', '').replace('.', '').replace(/0+$/, '')
  return Math.max(0, Math.min(8, mant.length - 1 - exp))
}

function precisionOf(step: number | null, value: unknown) {
  const fromStep = decimalsOf(step)
  if (fromStep > 0) return fromStep
  return typeof value === 'number' ? Math.min(4, decimalsOf(value)) : 0
}

/** 场景包的一条参数 → 壳层 ParamItem */
function toParamItem(a: RawAttribute): ParamItem {
  const step = num(a.step)
  const status = statusOf(a)
  const na = a.not_applicable === true
  const isNum = typeof a.value === 'number'

  // 取值渲染的三条分支，优先级从高到低：
  // 1) not_applicable —— 这个量在本产品上不存在，显示「不适用」，不给控件
  // 2) options 非空 —— 枚举，渲染下拉，min/max/step 一律不适用
  // 3) 数值且可编辑 —— 渲染加减号步进器
  const kind: ParamItem['kind'] = na
    ? 'readonly'
    : a.options?.length
      ? 'select'
      : isNum && a.editable
        ? 'number'
        : 'readonly'

  // 「待核实」已经由数值旁的角标表达，说明文字里不再重复前缀，只写原因本身
  const notes = [
    a._placeholder ? `待确认 · ${a.note ?? '源材料未给出，为占位值'}` : a.note,
    status,
  ].filter(Boolean)

  return {
    id: a.key,
    name: a.name,
    value: na ? '不适用' : ((a.value ?? '—') as number | string),
    unit: na ? undefined : (a.unit ?? undefined),
    kind,
    options: a.options?.map((o) => String(o.value)),
    optionLabels: a.options?.map((o) => o.label),
    step: step ?? 1,
    min: num(a.min) ?? undefined,
    max: num(a.max) ?? undefined,
    precision: precisionOf(step, a.value),
    source: a._placeholder ? '建议' : '文档',
    status: na ? 'na' : a._placeholder ? 'alert' : a.editable ? 'done' : 'na',
    // 待核实是「数值可能变」，不是「缺数据」，所以用角标而不是暗红异常态
    pending: status || undefined,
    note: notes[0],
    evidence: sourceLine(a._source),
  }
}

/* ------------------------------------------------------------- 工具条 */

/**
 * C 区工具条四组（规格 7.1）。
 *
 * 组名与分组结构是系统能力，两个场景共用；组内具体有哪几件工具、连的是什么设备，
 * 由场景包自己的数据推出来——散热风扇那边是示波器加程控电源加涵道逆风台架，
 * 玻璃升降器这边是力传感器加位移传感器加环境箱。推不出来的组就不出这一组，
 * 不硬凑。
 */
function toolGroupsOf(pack: RawPack): ToolGroup[] {
  const scope = pack.datasets.datasets.find((d) => d.scope)?.scope
  const ds = pack.datasets.datasets[0]
  const rate = ds?.sample_rate_sa_per_s
  const measures = pack.requirements.runtime_measures ?? {}

  /** 现场实测量按取数手段归到工具上：同一个手段只出一件工具，hint 列它测哪几个量 */
  const byInstrument = new Map<string, string[]>()
  for (const [, m] of Object.entries(measures)) {
    const how = (m.obtained_by ?? '').split(/[，,；;]/)[0].trim()
    if (!how) continue
    byInstrument.set(how, [...(byInstrument.get(how) ?? []), m.name])
  }
  const acquire = [...byInstrument.entries()]
    .sort((a, b) => b[1].length - a[1].length)
    .slice(0, 4)
    .map(([how, names], i) => ({
      id: `acq-${i}`,
      label: how.length > 9 ? `${how.slice(0, 8)}…` : how,
      glyph: ['⎍', '⛁', '⟳', '◎'][i] ?? '◎',
      state: 'offline' as const,
      hint: `${how} · 供 ${names.length} 个实测量：${names.slice(0, 3).join('、')}${names.length > 3 ? ' 等' : ''}`,
    }))

  /** 环境与激励：场景包里可在 F4 现场改的台架与工装类参数 */
  const stimulus = pack.controls.parameters
    .filter((p) => /台架|工装|环境|激励|采集/.test(p.group))
    .slice(0, 4)
    .map((p, i) => ({
      id: `stim-${p.key}`,
      label: p.name.length > 9 ? `${p.name.slice(0, 8)}…` : p.name,
      glyph: ['⏚', '≋', '◍', '⌁'][i] ?? '◍',
      state: 'offline' as const,
      hint: `${p.name}${p.unit ? `（${p.unit}）` : ''} · ${sourceLine(p._source) || '见场景包 control-parameters.json'}`,
    }))

  const groups: ToolGroup[] = []
  if (acquire.length)
    groups.push({
      id: 'acquire',
      title: '数据采集',
      tools: acquire.length
        ? acquire
        : [
            {
              id: 'scope-capture',
              label: '时序采集',
              glyph: '⎍',
              state: 'offline',
              hint: scope ?? '场景包未登记采集仪器',
            },
          ],
    })
  if (stimulus.length) groups.push({ id: 'stimulus', title: '环境与激励', tools: stimulus })
  groups.push({
    id: 'device',
    title: '对象调试',
    tools: [
      {
        id: 'param-write',
        label: '参数写入',
        glyph: '✎',
        state: 'offline',
        hint: `控制参数 ${pack.controls.parameters.length} 项，写回须沿用原数值外壳`,
      },
      {
        id: 'reg-rw',
        label: '状态字读写',
        glyph: '⊞',
        state: 'offline',
        hint: `故障位图 ${Object.keys(pack.interlocks.fault_bitmap?.bits ?? {}).length} 位`,
      },
    ],
  })
  groups.push({
    id: 'session',
    title: '设备接入',
    tools: [
      { id: 'ssh', label: 'SSH 命令行会话', glyph: '▮', state: 'offline', hint: '台架工控机，网关 :8022' },
      { id: 'rdp', label: '远程桌面', glyph: '▤', state: 'offline', hint: '需台架机常驻登录会话' },
      {
        id: 'open-proj',
        label: '本地工程打开',
        glyph: '⌸',
        state: 'offline',
        hint: rate ? `本场景时序口径 ${Math.round(rate)} Sa/s` : '本地调试客户端',
      },
    ],
  })
  return groups
}

/* ------------------------------------------------------------- 六条流程 */

const card = (id: CardInstance['id'], summary: string, extra: Partial<CardInstance> = {}): CardInstance => ({
  id,
  summary,
  ...extra,
})

/**
 * 初始化 hero 卡的卡名。
 * 取 scene.json 第一张图自己登记的性质（`kind`）；没登记就按标题里的关键词判。
 * 判不出来才退回「图纸」——不拿「产品示意图」当兜底，那会把线稿说成实物。
 */
function heroImageTitle(pack: RawPack): string {
  const im = pack.scene.images?.[0] as { kind?: string; title?: string } | undefined
  if (!im) return '图纸'
  if (im.kind === '结构示意') return '结构示意图'
  if (im.kind === '实物照片') return '产品照片'
  const t = im.title ?? ''
  if (/原理图|schematic/i.test(t)) return '原理图'
  if (/结构|简图|示意/.test(t)) return '结构示意图'
  if (/照片|photo/i.test(t)) return '产品照片'
  return '图纸'
}

/** 带 _status 的条数说明，两个包都可能有，没有就返回空串 */
function pendingLine(pack: RawPack) {
  return pack.caps.statusCount ? ` · 待核实 ${pack.caps.statusCount} 处` : ''
}

function initFlow(pack: RawPack): FlowContent {
  const attrs = pack.attributes.attributes
  const holes = attrs.filter((a) => a._placeholder)
  const na = attrs.filter((a) => a.not_applicable)
  const grouped = byGroup(attrs, pack.attributes.groups)
  const groups: ParamGroup[] = grouped.map(([g, items], i) => ({
    id: `pa-${i}`,
    index: String(i + 1),
    title: g,
    defaultOpen: i < 2,
    subgroups: [{ id: 'all', title: `${g}（${items.length} 项）`, items: items.map(toParamItem) }],
  }))
  const checklist: ChecklistItem[] = grouped.map(([g, items], i) => ({
    id: `pa-${i}`,
    index: String(i + 1),
    name: `${g} ${items.length} 项`,
    status: st(!items.some((a) => a._placeholder)),
    groupId: `pa-${i}`,
  }))
  const human = pack.interlocks.interlocks.filter((x) => x.type === '人员')
  return {
    checklist,
    groups,
    cards: [
      // 首卡即 hero：场景包登记的图纸铺满，带变体切换与芯片徽标。
      // 卡名随图的性质走：散热风扇包是电路原理图，玻璃升降器包是手绘结构示意图，
      // 不再一律叫「产品示意图」——图里画的不是产品实物。
      card('product-view', pack.scene.images[0]?.title ?? '图纸', {
        active: true,
        title: heroImageTitle(pack),
      }),
      // 槽 2 是三份关键源文件的读取入口，卡里是文件列表不是图，卡名按内容叫「文档读取」
      card('schematic', `数据手册 / 参数配置 / ${pack.scene.schematic_variants.length} 套图纸`, {
        title: '文档读取',
      }),
      card('project-tree', '客户工程目录与源材料'),
      card('interlock', `安全联锁 ${pack.interlocks.interlocks.length} 条 · 人员项 ${human.length}`),
      card('bench-live', '台架与仪器接入状态'),
    ],
    greeting: `本体属性 ${attrs.length} 项已从客户工程读出，其中 ${holes.length} 项源材料没给、标了「待确认」${na.length ? `，${na.length} 项在本产品上不适用` : ''}。点「读取并填充」可从数据手册、Customer.h 与原理图回填，源材料没写的一律留空不编。`,
    verifyLine: `本体属性 ${attrs.length} 项 · 占位 ${holes.length} 项待确认${pendingLine(pack)}`,
  }
}

function reqFlow(pack: RawPack): FlowContent {
  const reqs = pack.requirements.requirements
  const holes = reqs.filter((r) => r._placeholder)
  const manual = reqs.filter((r) => r.evaluable === false)
  const checklist: ChecklistItem[] = pack.requirements.categories.map((c, i) => {
    const items = reqs.filter((r) => r.category === c)
    return {
      id: `tr-${i}`,
      index: String(i + 1),
      name: `${c} ${items.length} 条`,
      status: st(!items.some((r) => r._placeholder)),
      groupId: `tr-${i}`,
    }
  })
  const wfNote = pack.workflows.all_placeholder
    ? `工作流库 ${pack.workflows.total} 条全部是本包自建的示例`
    : `工作流库 ${pack.workflows.total} 条`
  return {
    checklist,
    groups: [],
    // 卡槽顺序即视觉权重：首卡是 hero（工作流画布，横跨两格），第 2 槽是工作流库，
    // 第二行铺判定表 / 知识依据 / 历史成绩。
    cards: [
      card('workflow', `真画布 · 默认 HV_StaticStart`, { active: true }),
      card('wf-lib', wfNote),
      card('verdict', `判据 ${reqs.length} 条，此时只列不判`),
      card('evidence', '判据出自哪份材料的哪一条'),
      card('history', '同产品同工作流的历次成绩'),
    ],
    greeting: `判据 ${reqs.length} 条按 ${pack.requirements.categories.length} 类列出，可自动求值 ${pack.requirements.evaluable_count} 条、只能人工判 ${manual.length} 条。${wfNote}，画布默认打开一条，勾选框改的是本轮基线。`,
    verifyLine: `判据 ${reqs.length} 条 · 人工判 ${manual.length} 条${holes.length ? ` · ${holes.length} 条待确认` : ''}`,
  }
}

function runFlow(pack: RawPack): FlowContent {
  const params = pack.controls.parameters
  const inRun = params.filter((p) => p.adjustable_in_flows?.some((f) => f.startsWith('F4')))
  const human = pack.interlocks.interlocks.filter((i) => i.type === '人员' || i.type === '流程')
  const hw = pack.interlocks.interlocks.filter((i) => i.type === '硬件')
  const groups: ParamGroup[] = byGroup(params, pack.controls.groups).map(([g, items], i) => ({
    id: `cp-${i}`,
    index: String(i + 1),
    title: g,
    defaultOpen: i < 1,
    subgroups: [{ id: 'all', title: `${g}（${items.length} 项）`, items: items.map(toParamItem) }],
  }))
  const checklist: ChecklistItem[] = [
    { id: 'cfg', index: '1', name: '流程 2 配置快照已锁定', status: 'done', groupId: 'cp-0' },
    { id: 'base', index: '2', name: '流程 3 需求基线已冻结', status: 'done', groupId: 'cp-0' },
    {
      id: 'ctl',
      index: '3',
      name: `控制参数 ${params.length} 项（本流程可调 ${inRun.length}）`,
      status: 'done',
      groupId: 'cp-0',
    },
    { id: 'hw', index: '4', name: `硬件联锁 ${hw.length} 条由固件阈值保证`, status: 'done', groupId: 'cp-0' },
    { id: 'gate', index: '5', name: `安全确认闸门 ${human.length} 条待逐条确认`, status: 'alert', groupId: 'cp-0' },
  ]
  const synth = pack.caps.syntheticData ? '，时序为合成数据（非实测），卡片上已标' : ''
  return {
    checklist,
    groups,
    cards: [
      card(
        'timeseries',
        `登记 ${pack.datasets.datasets.length} 条 · 本轮回放 ${
          pack.datasets.datasets.filter((d) => d.mode.includes('into_pack')).length
        } 条${pack.caps.syntheticData ? '（合成）' : ''}`,
        { active: true },
      ),
      // 卡槽顺序即视觉权重：首卡是 hero（横跨两格），其余三张按四卡版式铺。
      // 第三轮删两张（06d 第 3.1 节）：
      //   「安全联锁状态盘」与左栏安全闸门是同一组 19 条的第二次呈现，删卡留左栏；
      //   「原理图」演示中不翻页，退回卡库按需拖入（卡库入口在卡头「换卡」里）。
      card('verdict', '按判据表逐条判定'),
      // 「单机设备会话」这张独立卡第三轮撤掉：一台设备在画板上就是一个 MCP 节点
      // （src/features/remote/DeviceMcpNode.tsx），网格视图不再另开一张卡。
      // 依据：《第三轮需求变更方案 v0.1》第 2.3 节第 4 条。
      card('progress', '本轮执行进度与日志'),
    ],
    greeting: `控制参数 ${params.length} 项已载入，本流程可调 ${inRun.length} 项${synth}。安全确认闸门 ${human.length} 条未全绿之前，「启动测试」按钮保持置灰。`,
    verifyLine: `控制参数 ${params.length} 项就绪 · 闸门 ${human.length} 条未确认`,
  }
}

function tuneFlow(pack: RawPack): FlowContent {
  const exps = pack.experience.experiences
  const tuneExp = exps.filter((e) => e.tags.flow?.startsWith('F5'))
  const inTune = pack.controls.parameters.filter((p) =>
    p.adjustable_in_flows?.some((f) => f.startsWith('F5')),
  )
  const checklist: ChecklistItem[] = [
    { id: 'fail', index: '1', name: '未达标项：由流程 4 的判定结果带入', status: 'alert', groupId: 'tn-0' },
    { id: 'cause', index: '2', name: '归因：按经验库匹配到的参数方向', status: 'done', groupId: 'tn-0' },
    {
      id: 'cand',
      index: '3',
      name: `候选参数由 ${tuneExp.length} 条 F5 经验匹配得出`,
      status: st(tuneExp.length > 0),
      groupId: 'tn-1',
    },
    { id: 'impact', index: '4', name: `影响面检查：本流程可调 ${inTune.length} 项`, status: 'done', groupId: 'tn-1' },
    { id: 'shell', index: '5', name: '写回须沿用原数值外壳与量纲', status: 'alert', groupId: 'tn-1' },
  ]
  return {
    checklist,
    groups: [],
    // 卡槽顺序即视觉权重：首卡是 hero（波形对照，横跨两格），第 2 槽占右上角，
    // 其余三张铺第二行（候选队列 · 知识库依据 · 判定卡）。
    cards: [
      card('history', `${pack.datasets.datasets.filter((d) => d.mode.includes('into_pack')).length} 条历次波形叠加对照`, { active: true }),
      card('candidates', '盲试候选队列 · 上限 10 个'),
      card('evidence', `依据：经验库 ${exps.length} 条中匹配到的条目`),
      // 「判定卡」与左栏的未达标 / 已通过 / 未采集是同一件事的第二次呈现，第三轮删卡留左栏
      // 第 5 槽原来是「时序曲线」，与 hero 的波形对照是同一批数据、同一种图，
      // 一页两张曲线卡是重复；换成本轮要写回固件的宏。单条曲线读数从卡头「换卡」进得来。
      card('param-changes', '本轮写回的宏 · 原值 → 新值'),
    ],
    greeting: `推荐这几项，是因为经验库 ${exps.length} 条里有 ${tuneExp.length} 条属调优流程，其中能在本包 ${pack.controls.parameters.length} 个控制参数里按宏名对上的才进候选，对不上的一律不推。写回沿用原数值外壳，只改括号内数字。`,
    verifyLine: `候选 ${Math.min(4, tuneExp.length)} 项待人工采纳 · 助手不写回`,
  }
}

function reportFlow(pack: RawPack): FlowContent {
  const h = pack.report.header_fields
  const checklist: ChecklistItem[] = h.map((f, i) => ({
    id: f.key,
    index: String(i + 1),
    name: `${headerFieldName(f)}（${f.value_slot || '—'}）`,
    status: f.from_flow.startsWith('F6') ? 'alert' : 'done',
    groupId: 'rp-0',
  }))
  const arts = pack.report.artifact_groups.reduce((a, b) => a + b.count, 0)
  const need = h.filter((f) => f.from_flow.startsWith('F6')).length
  return {
    checklist,
    groups: [],
    // 卡槽顺序即视觉权重：首卡是 hero（报告预览，横跨两格），第 2 槽是产物留档，
    // 其余三张铺第二行（判定汇总 · 历史对比 · 模板字段）。
    cards: [
      card('report-preview', '按模板节结构渲染，非成稿', { active: true }),
      card('artifacts', `图位 ${arts} 张待采集`),
      card('verdict', '口径同流程 4 判定卡'),
      card('history', '历史报告库未建，对照实验批次'),
      card('template-fields', `${pack.report.spec_sections.length} 节规格表`),
    ],
    greeting: `报告模板已就位，表头 ${h.length} 字段里 ${need} 项要本流程补全${pack.caps.syntheticData ? '，且本场景时序是合成数据、不得进合规报告' : ''}。结论段我按判定结果聚合起草，须人工复核后定稿。`,
    verifyLine: `表头 ${h.length} 字段 · ${checklist.filter((c) => c.status === 'alert').length} 项需本流程补全`,
  }
}

/** 场景包目录 → 本仓数据契约 */
export function adaptScene(raw: unknown, sceneId: string): ScenePackage {
  const pack = raw as RawPack
  if (!pack?.scene?.taxonomy) return MOCK_SCENE
  const t = pack.scene.taxonomy
  return {
    meta: {
      id: pack.scene.id ?? sceneId,
      scene: t.level1_scene.name,
      subclass: t.level2_category.name,
      productType: t.level3_product_type.name,
      packName: `${t.level2_category.name} · ${t.level3_product_type.name}`,
      packVersion: pack.scene.generated_at,
      bench: pack.caps.syntheticData ? '合成数据回放 · 无实测台架' : '涵道逆风台架 · SK-20251218QPBB',
    },
    toolGroups: toolGroupsOf(pack),
    flows: {
      init: initFlow(pack),
      req: reqFlow(pack),
      run: runFlow(pack),
      tune: tuneFlow(pack),
      report: reportFlow(pack),
    },
    ui: { defaultView: defaultViewOf(pack) },
  }
}

/**
 * scene.json 的 `default_view` 段 → ScenePackage.ui.defaultView。
 * 只认 'canvas' / 'grid' 两个值，别的一律丢掉交给代码兜底；
 * 整段缺失时返回空对象，不编造默认值。
 */
function defaultViewOf(pack: RawPack): Partial<Record<FlowId, 'canvas' | 'grid'>> {
  const raw = (pack.scene as { default_view?: unknown }).default_view
  const out: Partial<Record<FlowId, 'canvas' | 'grid'>> = {}
  if (raw && typeof raw === 'object') {
    for (const f of FLOW_IDS) {
      const v = (raw as Record<string, unknown>)[f]
      if (v === 'canvas' || v === 'grid') out[f] = v
    }
  }
  return out
}

/* --------------------------------------------------------- 产品三级级联目录 */

/** 三级级联的一个节点。第三级挂 sceneId 的才有场景包。 */
export interface CatalogNode {
  id: string
  label: string
  children?: CatalogNode[]
  sceneId?: string
}

interface SceneIndexFile {
  default?: string
  catalog: CatalogNode[]
}

/**
 * 产品目录由 public/scenes/index.json 驱动，不写死在代码里：
 * 新增一个场景包时只在那份 JSON 里加一行，前端不用改。
 * 取不到时回落到只有一个默认场景的最小目录，保证页面仍能渲染。
 */
const FALLBACK_CATALOG: CatalogNode[] = [
  {
    id: 'motor',
    label: '电机',
    children: [
      {
        id: 'cooling-fan',
        label: '散热风扇',
        children: [
          {
            id: 'fortior-fu6832',
            label: 'FU6832 散热风扇驱动板',
            sceneId: 'motor.cooling-fan.fortior-fu6832',
          },
        ],
      },
    ],
  },
]

export const DEFAULT_SCENE_ID = 'motor.cooling-fan.fortior-fu6832'

let catalogTask: Promise<{ catalog: CatalogNode[]; defaultScene: string }> | null = null

export function loadCatalog(): Promise<{ catalog: CatalogNode[]; defaultScene: string }> {
  if (catalogTask) return catalogTask
  catalogTask = (async () => {
    // 2026-10-08：改用统一 fetchJson（原 force-cache 会读旧副本，见 fetchJson 模块头）
    const j = await fetchJson<SceneIndexFile>('/scenes/index.json')
    if (!j || !Array.isArray(j.catalog) || !j.catalog.length) {
      return { catalog: FALLBACK_CATALOG, defaultScene: DEFAULT_SCENE_ID }
    }
    return { catalog: j.catalog, defaultScene: j.default ?? DEFAULT_SCENE_ID }
  })()
  return catalogTask
}

/** 在目录里按 sceneId 找出三级路径 */
export function pathOfScene(catalog: CatalogNode[], sceneId: string): [string, string, string] | null {
  for (const a of catalog)
    for (const b of a.children ?? [])
      for (const c of b.children ?? []) if (c.sceneId === sceneId) return [a.label, b.label, c.label]
  return null
}
