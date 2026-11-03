import type { FlowId } from '../../data/types'
import { headerFieldAltName, headerFieldName, type RawPack } from '../scene/pack'
import type { LastRunData } from '../flow-run/api'
import { buildTiers, readTiers } from '../shared/tiers'
import { translate } from '../../i18n/runtime'
import { initialLocale } from '../../i18n/locale'
import type { ActionDef, ActionScope } from './actions'

/**
 * 把上送模型的中文原文按当前界面语言翻译（2026-10-14 用户反馈：英文界面下 AI
 * 仍把「出处」列成中文）。
 *
 * 背景：左栏 UI 的字段名/层级名走 `uiT()` 正确英化，但**送给模型的上下文数据**
 * 走的是另一条路径（本文件的 leafSource / fieldRef），此前是裸取场景包原文，
 * 从未过 i18n → 模型拿到中文，自然只能答中文。
 *
 * 本模块是**纯函数模块**（不在 React 渲染里），拿不到 `useT()`，故直接用
 * `initialLocale()` 读当前语言（与 agent-chat/api.ts 上送 locale 同一来源，
 * 也保证「外发语言」与「请求声明的 locale」一致）。
 *
 * 词条缺失时 `translate()` 原样返回入参 —— 即退化成旧行为，安全。
 * 中文界面下 `translate()` 直接返回原文，行为与改动前完全一致。
 */
function ctxT(text: string): string {
  return translate(text, initialLocale())
}

/* ===========================================================================
   上下文包（context envelope v1）。

   规格见《上下文感知与预置按钮规格》第 1.3 节。该文件在
   docs/20260919-通用Agent测试系统v2.0/06-第三轮改版
   目录下，按编号 06c 定位（磁盘上的文件名沿用了第二轮对助手的旧称，本轮起
   全工程一律称「助手」，故此处不再照抄旧名）。八段依次是：
   session / product / flow / zoneB / zoneC / lastRun / kb / policy，
   外加点按钮时才填的 action 段与可为空的 history 段。

   两条纪律：
   一、只装真取得到的东西。取不到的字段写 null，不拿别处的数顶上，
       依赖该字段的按钮据此置灰。
   二、参数只送人改过的那几项 diff，不送全量——场景包的控制参数有七十余项，
       整包塞进每一轮请求既无意义也读不动。
   =========================================================================== */

export interface Envelope {
  envelope_version: '1'
  action: { button_id: string; type: ActionDef['type']; confirmed: boolean } | null
  session: {
    session_id: string
    operator: string
    started_at: string
    transcript_summary: string | null
  }
  product: {
    scene_id: string
    taxonomy_path: [string, string, string]
    taxonomy_name: string
    product_name: string
  }
  flow: {
    id: ActionScope
    label: string
    step: string | null
    confirmed: Partial<Record<FlowId, boolean>>
  }
  zoneB: Record<string, unknown>
  zoneC: Record<string, unknown>
  lastRun: Record<string, unknown> | null
  history: { runs: unknown[] } | null
  kb: Record<string, unknown>
  policy: {
    permission: string
    auto_run: boolean
    redline_actions: string[]
  }
}

export interface ZoneBFieldRef {
  key: string
  name: string
  /** 左栏菜单里的完整层级路径（一级类 → 二级组 → 字段名）；取不到为字段名本身 */
  source: string
  /** 字段当前实际值（人工覆盖 → 快照 → 源值），供模型引用具体数值 */
  value?: unknown
}

export interface EnvelopeInput {
  flow: ActionScope
  flowLabel: string
  pack: RawPack | null
  sceneId: string
  path: [string, string, string]
  operator: string
  /** 人改过的参数键，键形如 `${flow}.${group}.${sub}.${item}` */
  overrides: Record<string, number | string>
  /** 已读回的配置快照值（确认锁定落库的那份；刷新后 overrides 空了它还在） */
  snapshotValues?: Record<string, number | string>
  /** 参数被人改过后来源标记转「人工」 */
  touched: Record<string, true>
  confirmed: Partial<Record<FlowId, boolean>>
  benchBusy: boolean
  benchUser: string
  interlockPending: number
  canvasView: 'canvas' | 'grid'
  canvasSelected: string | null
  model: string
  /** 本轮对话的一句话摘要，没有对话时为 null */
  transcriptSummary: string | null
  /** 流程 4 已勾选的候选改动。空数组表示没选中，zoneB.selected_candidate 据此为 null。 */
  adopted: { key: string; name: string; from: string; to: string }[]
  /** 本会话已跑完第几轮；0 表示没跑过，lastRun.artifacts 据此为 null */
  runRound: number
  /**
   * 真实最近一轮（由 ActionDock 异步读回，见 flow-run/api.ts 的 loadLatestRun）。
   * **没跑过一轮时为 null**——此时 Envelope.lastRun 也为 null，
   * 依赖 `/lastRun/*` 的助手按钮如实置灰，不再喂假清单给模型。
   */
  lastRun: LastRunData | null
  /** 知识库里当前选中的条目 id（已上提 store）；未选中为 null */
  kbSelectedId: string | null
  /** 流程 4 里人点选的那条未达标判据（即 store 的 focusReq）；未选为 null */
  selectedFailItem: string | null
  /**
   * AI 助手当前权限档位（2026-10-10 权限切换修复）。
   * 由 ActionDock 从 store.permission 订阅传入；缺省（undefined）按 readonly 处理。
   * 这里动态化后，envelope.policy.permission 与 UI 选择才一致——此前是写死常量，
   * 模型永远自述只读（根因报告的断点 B）。
   */
  permission?: string
  /**
   * 流程 5 的**本页**表头填写情况：store.reportHeader 里**已有值**的字段 key 集合
   * （值随手给 true，只当集合用）。
   *
   * ⚠️ 跨页数据隔离（2026-10-04 用户口径「回答只关联当前页面」）：流程 5 助手的
   * 开场白就是「按模板填一遍，哪些字段还没填上」，它需要表头填写状态——但这个
   * 状态的本页真相是 reportHeader（左栏 FieldRow 写的），**不是**流程 1 的
   * `init.rp.header.*` 占位口径（那是另一个录入口径，且已在后端对非 init 流程
   * 隔离）。没有这一段，隔离后流程 5 助手对表头问题将无据可答。
   * 由 ActionDock 从 store 订阅传入；非 report 流程不填（undefined）。
   */
  reportHeaderFilled?: Record<string, true>
}

const REDLINE = ['start', 'stop', 'estop', 'write_back', 'export', 'archive']

/** section 名 → buildTiers 的装载段；控制参数段与属性段各自有自己的 group_tiers */
export type TierSection = 'attributes' | 'controls' | 'report'

function sectionOf(
  pack: RawPack,
  section: TierSection,
): { spec: unknown; items: { key: string; group?: string }[] } {
  if (section === 'controls') return { spec: pack.controls, items: pack.controls.parameters }
  // 报告表头没有 group 字段（RawHeaderField 只有 key/name/value_slot），
  // 它在 tiers 骨架里是「按 id 点名」的，group 不参与装载。
  if (section === 'report') return { spec: pack.report, items: pack.report.header_fields }
  return { spec: pack.attributes, items: pack.attributes.attributes }
}

/**
 * 反查某个字段 key 在左栏 tiers 里的祖先链（不含字段名本身）。
 *
 * 用 `buildTiers` 把该段的条目装一遍，再按 key 找它落在哪个
 * 一级类 / 二级组 / 三级子组；逐级降级，找不到返回空数组。
 *
 * ⚠️ 「出处」= **它在左栏菜单里的完整层级路径**（一级类 → 二级组 → 字段名），
 * 两次修正的历史别走回头路：
 * 1. 第一版用场景包 `_source` 的「文件 · 定位」（`Customer.h:244`、
 *    `A-DebugCopilot…md 第六节`）→ 用户否掉：「出处是指左侧的目录属性」。
 * 2. 第二版改成「一级组 → 字段名」（`机械 → 风扇厚度`）→ 用户仍要**完整层级**。
 * 所以现在拼**三级**（`被测对象 → 机械外形 → 风扇厚度`），骨架取自场景包的
 * `group_tiers`，不另写一套遍历——两套遍历迟早会走偏。
 * 找不到归属就逐级降级（二级 → 一级 → 空串），**不编造一层**。
 */
export function tierPathOf(
  pack: RawPack | null,
  key: string,
  section: TierSection = 'attributes',
): string[] {
  try {
    if (!pack) return []
    const sec = sectionOf(pack, section)
    const spec = readTiers(sec.spec)
    if (!spec.length) return []
    const tiers = buildTiers(
      spec,
      sec.items,
      (a) => a.key,
      (a) => a.group ?? '',
    )
    const hit = key.toLowerCase()
    for (const t of tiers) {
      for (const g of t.groups) {
        // 命中三级子组
        for (const s of g.subs) {
          if (s.items.some((a) => a.key.toLowerCase() === hit)) {
            return [t.title, g.title, s.title]
          }
        }
        // 只到二级组
        if (g.items.some((a) => a.key.toLowerCase() === hit)) {
          return [t.title, g.title]
        }
      }
    }
  } catch {
    // 场景包结构异常时**降级不报错**：出处是锦上添花，不能因此让整个上下文构建失败
    return []
  }
  return []
}

/** 只送人改过的那几项，键按 `paramKey` 的四段结构拆开 */
function paramDiff(input: EnvelopeInput) {
  return Object.keys(input.touched)
    .filter((k) => k.startsWith(`${input.flow}.`))
    .map((k) => {
      const seg = k.split('.')
      return { key: k, item: seg[seg.length - 1] ?? k, value: input.overrides[k] ?? null }
    })
}

/**
 * 字段值是否**有落地的具体值**（人填的，或源材料给的实数）。
 *
 * ⚠️⚠️ 关键坑（2026-10-05 用户二次实测复现「填了还说缺」）：
 * 场景包对「源材料没给的项」不是写 null，而是写「未知」字符串 + _placeholder: true
 * （见 c/data/scenes/…/product-attributes.json 的 fan_outer_size / fan_thickness）。
 * 所以按「字面值是否为空串」判断会两头错：
 *   · 人没填时，当前值回落到「未知」（非空串）→ 误判成「已填」→ 漏报；
 *   · 人填了时，当前值是被 override 的数字 → 正确判「已填」。
 *
 * 另注：「未知」「—」「-」三个哨兵串一律算没值——它们是场景包对缺口的写法，
 * 不是答案。这与左栏 `flow-init/panel.tsx` 的 `isMeaningfulValue` **同一口径**。
 *
 * 这里的「值」是**当前实际值的回落链**：overrides[key] → snapshotValues[key] → 源值。
 */
function isBlank(v: unknown): boolean {
  if (v === null || v === undefined) return true
  if (typeof v === 'number') return !Number.isFinite(v)
  if (typeof v === 'boolean') return false
  const s = String(v).trim()
  return s === '' || s === '未知' || s === '—' || s === '-'
}

/** 字段当前实际值（人工覆盖 → 已落盘快照 → 源材料值），取不到返回 undefined */
function resolvedValue(
  input: EnvelopeInput,
  key: string,
  fallback: unknown,
): unknown {
  const ov = input.overrides[key]
  if (!isBlank(ov)) return ov
  const snap = input.snapshotValues?.[key]
  if (!isBlank(snap)) return snap
  return fallback
}

/** 三内类的叶子条目：本体属性 / 控制参数 / 报告表头（形状与左栏 Leaf 对齐） */
export interface AnyLeaf {
  k: 'attr' | 'param' | 'field'
  id: string
  g: string
  name: string
  /**
   * 「另一种语言」的字段名（2026-10-15 新增，只有报告表头字段会带）。
   *
   * `name` 随界面语言（中文界面给中文名、英文界面给平行英文名，见 `headerFieldName`）；
   * 本字段给另一种语言的写法，供 `fieldRegistry` 的解析做**双名匹配**：英文界面下用户
   * 或模型给中文名、中文界面下给英文名，同样能落到同一条字段。
   */
  nameAlt?: string
  value: unknown
  /** 源材料缺口的写法（「未知」串 + 该标记），只有本体属性与控制参数会带 */
  placeholder?: boolean
  status?: string
}

/**
 * 叶子的四段键——必须与 `flow-init/panel.tsx` 的 `leafKeyOf` 逐字一致。
 *
 * ⚠️ 2026-10-14 改为 `export`：`fieldRegistry.ts`（AI 通用字段读写）必须复用它，
 * 禁止在第三个地方再手写这套键，否则出现「AI 改了值但左栏不动」。
 */
export function leafKey(flow: string, x: AnyLeaf): string {
  if (x.k === 'attr') return `${flow}.pa.${x.g}.${x.id}`
  if (x.k === 'param') return `${flow}.cp.${x.g}.${x.id}`
  return `${flow}.rp.header.${x.id}`
}

/** 这条叶子是不是「源材料没给的占位项」（源材料缺口标记，不是「人没填」） */
function isPlaceholder(x: AnyLeaf): boolean {
  return !!(x.placeholder || x.status)
}

/**
 * 占位项是否**已被人工填上值**。
 *
 * ⚠️⚠️ 判据只看 `input.touched`（本会话人真的动过手），**三样都不看**：
 *   ① 源材料的推定值——场景包对源材料缺的项常写一个推定值（额定转速按
 *      MOTOR_MAX_SPEED 暂取之类），那是「有出处的待确认值」，不是人填的；
 *   ② `overrides`——`applySnapshot` 会把**已落盘的历史快照**整个灌进 overrides
 *      （见 flow-init/snapshotApi.ts 的回填段），所以 overrides 里有键**不等于**
 *      本会话人填过，它可能只是「上一次确认的旧值」；
 *   ③ `snapshotValues`——同理，那是落盘基线，不是本次填写动作。
 * 若把 ②③ 也算「已填」，用户一进页面（只要历史上确认过一轮）就会看到
 * 「占位项全部已填」，而左栏「待现场确认 N」仍按 touched 算，两处口径打架。
 *
 * `touched` 是唯一表示「人真的填过」的位（`setParam` 里与 overrides 成对写入），
 * 左栏 `flow-init/panel.tsx` 的 `holes` 用的就是它——**同源**。
 */
function humanFilled(input: EnvelopeInput, x: AnyLeaf): boolean {
  if (input.touched[leafKey('init', x)]) return true
  // 兜底：只认「人工「来源」标记」，不认裸 overrides 键。
  // 极少数写入路径可能只写了 overrides 而漏记 touched（历史上出过这类缺口），
  // 这时用「该键的值既不同于源值、又不是源材料原本就在」判——但风险大于收益，
  // 因此这里**不兜底**，宁可如实报「还没填」（漏报优于误报「已填」）。
  return false
}

/**
 * 叶子在左栏里的完整层级路径（出处），复用属性段的构造器，取不到逐级降级。
 *
 * 2026-10-14：层级名与字段名都过 `ctxT()` 按当前界面语言翻译——此前是裸取场景包
 * 中文原文，导致英文界面下模型照抄中文出处（用户实测反馈）。
 * 中文界面下 `ctxT()` 原样返回，行为不变。
 */
export function leafSource(pack: RawPack | null, x: AnyLeaf): string {
  if (x.k === 'field') {
    const chain = tierPathOf(pack, x.id, 'report')
    return [...chain, x.name].filter(Boolean).map(ctxT).join(' → ')
  }
  const chain = x.k === 'attr' ? tierPathOf(pack, x.id) : tierPathOf(pack, x.id, 'controls')
  return [...chain, x.name].filter(Boolean).map(ctxT).join(' → ')
}

/**
 * 把一条叶子收敛成给模型看的字段引用（缺值/占位三段共用）。
 *
 * ⚠️ **必须带出处**（2026-09-28 用户明确要求）。出处的定义是**左栏目录归属**
 * （一级类 → 二级组 → 字段名），**不是文件名**——第一版发的是 `_source` 的
 * 文件·行号，模型照抄出 `Customer.h:244`、`A-DebugCopilot…md` 这类对人无意义的
 * 东西，用户明确否掉（「出处是指左侧的目录属性」）。见 `srcOf` 的说明。
 *
 * 有值时一并带上 `value`：模型要能说出「额定转速已填 18100 rpm」而不是只念字段名。
 */
function fieldRef(input: EnvelopeInput, x: AnyLeaf): ZoneBFieldRef {
  const v = resolvedValue(input, leafKey('init', x), x.value)
  const ref: ZoneBFieldRef = {
    // key 是稳定标识，**不翻译**；name 是给人看的，随界面语言（2026-10-14）。
    key: x.id,
    name: ctxT(x.name),
    source: leafSource(input.pack, x),
  }
  if (!isBlank(v)) ref.value = v
  return ref
}

/**
 * 本体属性 / 控制参数 / 报告表头三内类合起来的一份叶子表。
 *
 * ⚠️ 为什么要合：以前 envelope 的 missing / placeholders **只看本体属性（29 项）**，
 * 助手开口就说「占位字段共 5 项」——而左栏菜单是 75 项（本体属性 + 控制参数 +
 * 报告表头），两个数字对不上，用户没法对账（2026-10-05 用户实测反馈）。
 * 现在统一走这一份表，口径与左栏一致。
 */
/**
 * 汇总场景包三类字段为统一叶子表（本体属性 / 控制参数 / 报告表头）。
 *
 * ⚠️ 2026-10-14 改为 `export`：`fieldRegistry.ts` 的 `listEditableFields()`
 * 与 `resolveField()` 以它为唯一字段清单来源，避免再抄一遍遍历逻辑。
 */
export function allLeaves(pack: RawPack | null): AnyLeaf[] {
  if (!pack) return []
  const out: AnyLeaf[] = []
  for (const a of pack.attributes.attributes) {
    out.push({
      k: 'attr',
      id: a.key,
      g: a.group,
      name: a.name,
      value: a.value,
      placeholder: a._placeholder,
      status: a._status,
    })
  }
  for (const p of pack.controls.parameters) {
    out.push({
      k: 'param',
      id: p.key,
      g: p.group,
      name: p.name,
      value: p.value,
      placeholder: p._placeholder,
      status: p._status,
    })
  }
  for (const f of pack.report.header_fields) {
    out.push({
      k: 'field',
      id: f.key,
      g: 'header',
      // 2026-10-15：报告表头字段带平行英文名，`name` 随界面语言（中文界面与改动前逐字相同），
      // `nameAlt` 带另一种语言名供双名匹配。attr / param 段没有平行英文名，维持原样。
      name: headerFieldName(f),
      nameAlt: headerFieldAltName(f),
      value: f.sample_value,
    })
  }
  return out
}

export function buildEnvelope(input: EnvelopeInput): Envelope {
  const p = input.pack
  const attrs = p?.attributes.attributes ?? []
  const params = p?.controls.parameters ?? []
  const reqs = p?.requirements.requirements ?? []
  const interlocks = p?.interlocks.interlocks ?? []
  /** 三内类合起来的叶子表（本体属性 + 控制参数 + 报告表头） */
  const leaves = allLeaves(p)
  /** 本体属性里 `not_applicable` 的 key 集合：这些不是「缺值」，是「本产品不适用」 */
  const packAttrNA = new Set(attrs.filter((a) => a.not_applicable).map((a) => a.key))

  // ---------------------------------------------------------------- lastRun
  // ⚠️ 2026-09-29 重大修正：此前这里是**写死的假数据**——无论跑没跑过一轮，
  // 都一律报「所有判据未采集 + 全部 runtime.measure 变量未采集（本场景 42 项）」。
  // 后果：模型拿着这份假清单编出「判据挂错流程」这类**不存在的问题**
  // （用户问「判据与工作流有没有对不上」，助手给了误导性自查建议）。
  //
  // 现在改为**只认真数据**：由 `ActionDock` 调 `flow-run/api.ts` 的
  // `loadLatestRun(sceneId, requiredMeasures)` 异步读回真轮次产物，作为入参传进来。
  //   - 跑过一轮 → 填真 run_id / 真 verdicts / 真 failed_items / 真缺的实测量；
  //   - 没跑过 → `input.lastRun` 为 null → 这里也输出 null，
  //     依赖 `/lastRun/*` 的助手按钮据此如实置灰（提示走 missingHint），不编。
  //
  // `precheck` 里「硬件项」目前仍由脚本化回放给出（真硬件预检属设备层），
  // 但这**不再冒充整轮判定**——它只在真有轮次时附加，没有轮次就不给整个 lastRun。
  const lastRun: Record<string, unknown> | null = input.lastRun
    ? {
        run_id: input.lastRun.run_id,
        finished_at: input.lastRun.finished_at,
        overall: input.lastRun.overall,
        overall_note: input.lastRun.overall_note,
        verdicts: input.lastRun.verdicts,
        failed_items: input.lastRun.failed_items,
        missing_measures: input.lastRun.missing_measures,
        artifacts: input.lastRun.artifacts,
        precheck: {
          hardware: 'ok',
          pending_gates: interlocks.filter((i) => i.type !== '硬件').map((i) => i.id),
          note: '硬件项由脚本化回放给出，人工与流程类闸门须人逐条确认',
        },
      }
    : null

  return {
    envelope_version: '1',
    action: null,
    session: {
      session_id: `shell-${input.sceneId}-${input.flow}`,
      operator: input.operator,
      started_at: new Date().toISOString(),
      transcript_summary: input.transcriptSummary,
    },
    product: {
      scene_id: input.sceneId,
      taxonomy_path: input.path,
      taxonomy_name: input.path.join(' › '),
      product_name: p?.scene.product.name ?? input.path[2],
    },
    flow: {
      id: input.flow,
      // 流程名随界面语言（2026-10-14）；id 是稳定标识不译。
      label: ctxT(input.flowLabel),
      step: null,
      confirmed: input.confirmed,
    },
    zoneB: {
      form_groups: (p?.attributes.groups ?? []).map((g) => ({
        id: g,
        name: ctxT(g),
        item_count: attrs.filter((a) => a.group === g).length,
      })),
      values: Object.fromEntries(paramDiff(input).map((d) => [d.key, d.value])),
      // missing / placeholders 给的是**中文名 + 英文键**两个字段。
      //
      // 此前只传 `a.key`（如 rated_speed），模型照着念，回答里全是用户看不懂的
      // 英文键名（用户反馈过）。中文名是界面左栏用的那一套，与菜单对齐；
      // 英文键留着是给模型精确定位用的（检索知识库时宏名更好命中）。
      //
      // ⚠️⚠️ 跨页数据隔离（2026-10-04 用户口径「回答只关联当前页面」，前端层根治）：
      // 缺值/占位三段全部来自**流程 1（初始化配置）的现场数据**。
      // 此前任何流程的 envelope 都带这两段，模型在流程 3/5 也能看到并答出
      // 「预定位强度」「风扇厚度」等第一阶段参数——即便后端摘要已隔离，数据仍在
      // envelope 里流动，泄露面没断根。这里在**源头**裁剪：非 init 流程直接输出
      // 空数组，这些字段不再进入其它流程的上下文。init 流程照旧输出（本页数据）。
      //
      // ⚠️⚠️ 口径重构（2026-10-05 用户实测「助手不按真实情况回答」）：
      // 以前只有 missing（无值）+ placeholders（源材料占位）两段，且**只看本体属性
      // 29 项**，于是助手开口就是「占位字段共 5 项」——而左栏菜单有 75 项，两个数字
      // 对不上，用户没法对账。
      //
      // ⚠️⚠️⚠️ 另一个更关键的坑（本轮真根因）：场景包对源材料没给的项**多数仍带一个
      // 推定值**（额定转速 18100、额定母线电压 12.1、整机额定相电流 0.7 都是「按
      // MOTOR_MAX_SPEED 暂取，待客户确认」这类），只有 fan_outer_size / fan_thickness
      // 写了「未知」。所以**不能按「有没有值」判占位项填没填**——那会把 3 项推定值
      // 误判成「人已填」，助手于是说「这些有着落」，而左栏的「待现场确认 N」又把它
      // 们算进去，两处口径打架（截图里助手说 5 项占位、左栏却显示有值，就是这个矛盾）。
      //
      // 现在的判据很明确：**占位项（_placeholder / _status）的「填没填」只看「人工
      // 覆盖或已落盘快照有没有值」——源材料给什么都不算人填过**。这与左栏
      // `flow-init/panel.tsx` 的 `holes`（按 `touched` 口径）同源。
      // 三段各司其职，三内类（本体属性 / 控制参数 / 报告表头）都算：
      //   missing              当前取不到有效值的字段（人没填 + 源材料也没给）
      //   placeholders_pending 源材料没给、**人还没填**的项（= 左栏「待现场确认 N」）
      //   placeholders_filled  源材料没给、**人已填**的项（= 左栏「已补 N 项」）
      missing:
        input.flow === 'init'
          ? leaves
              .filter((x) => {
                if (x.k !== 'attr') return false
                if (packAttrNA.has(x.id)) return false
                // ⚠️⚠️ 占位项（源材料缺口标记）**一律归 pending / filled 两段**，
                // 不进 missing——它们是「源材料没给、待现场确认」，不是「取不到值」，
                // 两段描述的是同一个字段的两种状态，混着报会自相矛盾
                // （2026-10-05 实测到「风扇外形尺寸」既在 missing 又在 filled，
                // 模型据此两边都念，用户读起来更乱）。
                if (isPlaceholder(x)) return false
                // 非占位项：源值也要么没有、要么是哨兵串（未知/—/-）才算「取不到值」。
                return isBlank(x.value)
              })
              .map((x) => fieldRef(input, x))
          : [],
      placeholders_pending:
        input.flow === 'init'
          ? leaves.filter((x) => isPlaceholder(x) && !humanFilled(input, x)).map((x) => fieldRef(input, x))
          : [],
      placeholders_filled:
        input.flow === 'init'
          ? leaves.filter((x) => isPlaceholder(x) && humanFilled(input, x)).map((x) => fieldRef(input, x))
          : [],
      /**
       * 兼容别名：placeholders = 还没填的占位项。
       *
       * 场景包的 `copilot-actions.json` 里有按钮把 `/zoneB/placeholders` 写进
       * `context_requires`（缺字段就置灰），删掉这个键会让那几枚按钮**恒灰**。
       * 所以保留键名，值等同 placeholders_pending；新代码请用 pending/filled 两段。
       */
      placeholders:
        input.flow === 'init'
          ? leaves.filter((x) => isPlaceholder(x) && !humanFilled(input, x)).map((x) => fieldRef(input, x))
          : [],
      touched: paramDiff(input).map((d) => d.key),
      selected_item: null,
      // 2026-09-24 接真数：这两个字段原先「恒为 null」是因为选中态还留在各面板的
      // 局部 useState 里，副驾拿不到。现在已上提到 store：
      //   selected_document ← 知识库页选中的条目（store.kbSelectedId）
      //   selected_fail_item ← 流程 4 选中的未达标判据（store.focusReq）
      // 取不到就仍为 null（人还没点），依赖它们的按钮照旧置灰——
      // **不为了点亮按钮而编一个值**。
      selected_document: input.kbSelectedId,
      selected_fail_item: input.selectedFailItem,
      // 候选改动是例外：它的选中态第四轮已上提到 store 的 adoptedKeys / adoptMeta，
      // 这里接上去，勾了候选「写回草稿」就能亮（07i 核验 P3）。
      selected_candidate: input.adopted.length
        ? {
            count: input.adopted.length,
            keys: input.adopted.map((c) => c.key),
            items: input.adopted,
          }
        : null,
      interlocks: interlocks.map((i) => ({
        id: i.id,
        name: i.name,
        type: i.type,
        blocking: i.blocking,
      })),
      requirements: reqs.map((r) => ({
        id: r.id,
        name: ctxT(r.name),
        category: r.category,
        evaluable: r.evaluable !== false,
      })),
      /**
       * 控制参数名表（key / 中文名 / 单位）。
       *
       * ⚠️ 2026-10-05 收窄：**report 流程不下发**。
       * 起因（用户实测「阶段五引用错误的阶段一数据」）：这份表是**全量 70 项**
       * 控制参数，而控制参数属于「初始化配置 / 调优」语境。流程 5 页本用不到它，
       * 却等于把一大串流程 1 的参数名递到模型手上，成了跨页复述的素材。
       * 已核实：场景包里依赖 `/zoneB/control_params` 的按钮只有
       * `run.dryrun`（干跑一遍）与 `tune.candidates`（候选推荐）两枚，
       * **report 流程没有任何按钮依赖它** → 不下发不会让任何按钮恒灰。
       * 其余流程保持全量（避免扩大改动面）。
       */
      control_params:
        input.flow === 'report'
          ? []
          : params.map((c) => ({ key: c.key, name: ctxT(c.name), unit: c.unit })),
      firmware_project: p ? { source: p.base, note: '场景包登记的控制参数来源工程' } : null,
      report_template: p ? { file: p.report.template_file, fields: p.report.header_fields.length } : null,
      /**
       * 流程 5 本页的表头未填项（跨页隔离的正面补齐，2026-10-04）。
       *
       * 为什么放 zoneB：流程 5 助手要答「哪些表头还没填上」，数据的**本页真相**
       * 是 store.reportHeader（左栏 FieldRow 写的）与 pack.report.header_fields
       * 的差集——与流程 1 的 `init.rp.header.*` 占位口径是**两个录入口径**
       * （G-10 迁移后的现状）。后端摘要据此在 report 流程输出「报告表头未填项」，
       * 隔离掉流程 1 字段后助手仍有据可答。
       * 非 report 流程不出（undefined）——本页数据不跨页。
       *
       * ⚠️ 2026-10-05 补 `source`（出处）：此前只给 `{key,name,value_slot}`，
       * 而引用纪律（`_CITE_RULE ④`）**强制要求「按条目列字段必须带出处」**——
       * 模型拿不到本页字段的出处，就只好去别处找一个现成的三级路径来凑，
       * 而流程 1 的「被测对象 → 额定工况 → 额定转速」正好是现成模板：
       * 这就是流程 5 答出流程 1 清单的直接诱因之一（用户实测反馈）。
       * 现在补齐：出处走 `tierPathOf(key,'report')`（报告模板自己的 `group_tiers`
       * 骨架），命中不到就退到字段名本身——与 `leafSource` 同口径，不编造。
       */
      report_header_missing:
        input.flow === 'report'
          ? (p?.report.header_fields ?? [])
              .filter((f) => !(input.reportHeaderFilled && input.reportHeaderFilled[f.key]))
              .map((f) => {
                const chain = tierPathOf(p, f.key, 'report')
                return {
                  key: f.key,
                  // 名字与出处随界面语言（2026-10-14；2026-10-15 起优先取场景包平行英文名，
                  // 缺失再回退词典翻译）。key / value_slot 是稳定标识，不译。
                  name: ctxT(headerFieldName(f)),
                  value_slot: f.value_slot,
                  // 一级类 → 二级组 → 字段名；骨架里只有两级时就是两级，不硬凑三级
                  source: [...chain, headerFieldName(f)].filter(Boolean).map(ctxT).join(' → '),
                }
              })
          : undefined,
    },
    zoneC: {
      view: input.canvasView,
      selected_node: input.canvasSelected,
      workflow_nodes: (p?.workflows.workflows ?? []).map((w) => ({ id: w.id, name: w.name })),
      workflow_templates: Object.keys(p?.workflows.count_by_group ?? {}),
      devices: (p?.datasets.datasets ?? []).map((d) => ({
        id: d.id,
        name: d.name,
        kind: d.mode,
        online: false,
      })),
      bench_status: {
        busy: input.benchBusy,
        user: input.benchUser,
        interlock_pending: input.interlockPending,
      },
    },
    lastRun,
    // 历史轮次对比（/history/runs）仍为 null：后端有轮次存储，但「多轮并排比」
    // 这一功能尚未实现（run.compare 按钮据此如实置灰）。lastRun 已接真，history 未接。
    history: null,
    kb: {
      hits: [],
      index_summary: {
        documents: p?.documents.total ?? 0,
        experiences: p?.experience.count ?? 0,
        by_type: p?.documents.count_by_type ?? {},
      },
      conversion_status: p?.documents.conversion_status_legend ?? {},
      experience_summary: {
        count: p?.experience.count ?? 0,
        evidence_levels: p?.experience.evidence_levels ?? {},
      },
      unclassified: [],
    },
    policy: {
      // 动态读当前权限档位（2026-10-10）：不再写死 readonly。
      // 缺省（未传入）按 readonly 处理——安全默认，与后端 select_tools 口径一致。
      permission: input.permission || 'readonly',
      auto_run: true,
      redline_actions: REDLINE,
    },
  }
}

/** JSON 指针取值（只用到 /a/b 这一档，够覆盖 context_requires 的写法） */
export function pointer(env: Envelope, ptr: string): unknown {
  let cur: unknown = env
  for (const seg of ptr.split('/').slice(1)) {
    if (cur === null || typeof cur !== 'object') return undefined
    cur = (cur as Record<string, unknown>)[seg]
  }
  return cur
}

/** 缺哪些上下文字段。null 与 undefined 算缺，空数组不算缺。 */
export function missingContext(def: ActionDef, env: Envelope): string[] {
  return def.context_requires.filter((ptr) => {
    const v = pointer(env, ptr)
    return v === null || v === undefined
  })
}

/** 缺字段时按钮悬停提示：缺什么、去哪补 */
const WHERE: Record<string, string> = {
  '/lastRun/artifacts': '先在流程 3 跑完一轮（跑完才有一轮真产物可引用）',
  '/history/runs': '历史轮次索引（轮次存储尚未实现，至少跑过两轮才能比）',
  '/zoneB/selected_document': '先在知识库页选中一份文档',
  '/zoneB/selected_fail_item': '先在 B 区选中一条未达标项',
  '/zoneB/selected_candidate': '先在流程 4 的推荐参数里勾选至少一条候选改动',
  '/zoneB/firmware_project': '先在流程 1 指定驱动工程目录',
  '/zoneB/report_template': '先在流程 5 载入报告模板',
  '/session/transcript_summary': '先与助手对话至少一轮（本会话对话摘要由对话轮数推出）',
  '/lastRun/precheck': '先跑一次预检',
  '/lastRun/verdicts': '先跑完一轮测试',
  '/lastRun/failed_items': '先跑完一轮测试',
}

export function missingHint(missing: string[]): string {
  return missing.map((m) => WHERE[m] ?? m).join('；')
}
