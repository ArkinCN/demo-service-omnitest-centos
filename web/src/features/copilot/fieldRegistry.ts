/**
 * 字段注册表 —— AI 通用「增删改查当前页面字段」的唯一解析 / 校验 / 写入实现。
 *
 * 设计要点（2026-10-14 新增）：
 *
 * 1. **不新造寻址机制**。键口径直接复用 `context.ts` 的 `leafKey()`（四段键
 *    `${flow}.pa|cp|rp.${group}.${key}`），字段清单直接复用 `allLeaves()`。
 *    三处（本文件 / context.ts / flow-init/panel.tsx）共用同一口径，
 *    杜绝「AI 改了值但左栏不动」。
 *
 * 2. **可编辑口径与页面完全一致**。判据照抄 `flow-init/panel.tsx` 的
 *    `!not_applicable && editable !== false`（源码 137 / 229 行）：
 *    **只看场景包的 editable，不看当前值是不是数字**——占位项（`_placeholder`）
 *    恰恰是最需要人现场填的，历史上曾因「没有初始数字值」被锁成只读。
 *
 * 3. **排除三类**：安全联锁（`interlocks`，改它必须人工 PIN）、测试判据
 *    （`requirements`，由测试结果派生的只读判定）、图表与判定结果（无数据落点）。
 *
 * 4. **「删除」= 清空值**。数据模型里没有字段删除，value 传空串即清空；
 *    但仅当该字段是占位项或人工填过（`touched`）时允许，否则会清掉源材料
 *    自带的有效值 → 一律拒绝并说明原因。
 *
 * 5. **跨页隔离**。每页只暴露本页可编辑字段：报告流程（F5）只认报告表头；
 *    初始化流程（F1）认三类；控制参数还必须满足 `adjustable_in_flows`
 *    包含当前流程前缀。
 */
import { useAppStore } from '../../state/useAppStore'
import { allLeaves, leafKey, leafSource, type AnyLeaf } from './context'
import { simp } from '../shared/zh'
import type { ParamValue } from '../../state/useAppStore'
import type { RawControlParam, RawPack } from '../scene/pack'

/** 支持字段读写的流程 id（本批只开 F1；F4/F5 后续批次接入） */
export type FlowScope = 'init' | 'req' | 'run' | 'tune' | 'report'

/** 解析失败时的候选（给模型自纠用） */
export interface FieldCandidate {
  /** 完整层级路径，如「被测对象 → 机械外形 → 风扇外形尺寸」 */
  path: string
  /** 字段名 */
  name: string
}

/** 解析结果 */
export interface ResolvedField {
  leaf: AnyLeaf
  key: string
  /** 完整层级路径（一级类 → 二级组 → 字段名），与界面左栏一致 */
  path: string
  /** 是否可编辑（与页面判据同源） */
  editable: boolean
  /** 不可编辑的原因（editable=false 时给，供如实回话） */
  reason?: string
  /** 数值范围 / 枚举可选值（供校验与告知） */
  min?: number | null
  max?: number | null
  unit?: string | null
  options?: { value: string | number | boolean; label: string }[]
  /** 是不是源材料没给、待现场确认的占位项 */
  placeholder: boolean
}

/** 单项写入结果 */
export interface WriteOutcome {
  field: string
  ok: boolean
  /** 成功时是写入后的值；失败时为空。**数值字段保留 number 类型**（见 validate 注释） */
  value?: ParamValue
  /** 失败原因（如实、可行动） */
  reason?: string
}

/** 流程 id → 控制参数 `adjustable_in_flows` 的前缀（场景包用 F1..F5 编号） */
const FLOW_PREFIX: Record<FlowScope, string> = {
  init: 'F1',
  req: 'F2',
  run: 'F4',
  tune: 'F5',
  report: 'F5',
}

/**
 * 本页允许 AI 读写的字段分类。
 *
 * · `report`（测试报告及产出）：只认报告表头——页面上本来也只有表头字段，
 *   把本体属性/控制参数放进来会诱发「跨界复述」（用户明确否掉过）。
 * · 其余流程：三类都开放，但控制参数还要过 `adjustable_in_flows` 这一关。
 */
function allowsType(flow: FlowScope, k: AnyLeaf['k']): boolean {
  if (flow === 'report') return k === 'field'
  return true
}

/** 控制参数是否声明「本流程可调」（严格遵循场景包，与页面行为一致） */
function adjustableHere(flow: FlowScope, p: RawControlParam): boolean {
  const list = p.adjustable_in_flows
  if (!list || list.length === 0) return false
  const prefix = FLOW_PREFIX[flow] ?? 'F1'
  return list.some((f) => String(f).startsWith(prefix))
}

/** 从原始场景包按 key 反查原始属性/参数对象（拿 min/max/unit/options 等元数据） */
function rawOf(
  pack: RawPack | null,
  leaf: AnyLeaf,
): { editable?: boolean; not_applicable?: boolean; min?: number | null; max?: number | null; unit?: string | null; options?: { value: string | number | boolean; label: string }[] } | null {
  if (!pack) return null
  if (leaf.k === 'attr') {
    const a = pack.attributes.attributes.find((x) => x.key === leaf.id)
    return a ?? null
  }
  if (leaf.k === 'param') {
    const p = pack.controls.parameters.find((x) => x.key === leaf.id)
    return p ?? null
  }
  // 报告表头字段没有 min/max/options，恒可编辑
  return { editable: true }
}

/**
 * 组装完整层级路径：一级类 → 二级组 → 字段名（与左栏菜单同口径）。
 *
 * ⚠️⚠️ 2026-10-14 教训：**必须复用 `context.ts` 的 `leafSource()`**，不要自己拼。
 *
 * 初版这里自写了一套「二级组 → 字段名」，结果与上下文里给模型的出处**不一致**
 * （少一级），而模型定位字段时**恰恰照抄上下文给的路径**
 * （如「被测对象 → 机械外形 → 风扇尺寸」）→ 解析必然失败。
 * `leafSource()` 是生产口径：骨架取自场景包 `group_tiers`、经 `tierPathOf` 走
 * 三级、且已按界面语言做过 i18n。两处口径必须同源，否则「模型说的」与
 * 「执行器认的」对不上。
 */
function pathOf(pack: RawPack | null, leaf: AnyLeaf): string {
  const chain = leafSource(pack, leaf)
  return chain || leaf.name
}

/**
 * 列本页全部「可编辑」字段。
 *
 * 返回的是 `ResolvedField[]`，供 `ReadField(all=true)` 与解析候选使用。
 */
export function listEditableFields(flow: FlowScope, pack: RawPack | null): ResolvedField[] {
  if (!pack) return []
  const out: ResolvedField[] = []
  for (const leaf of allLeaves(pack)) {
    if (!allowsType(flow, leaf.k)) continue
    const resolved = resolveLeaf(flow, pack, leaf)
    if (resolved && resolved.editable) out.push(resolved)
  }
  return out
}

/** 把单个 leaf 解析成 ResolvedField（含可编辑判定与原因） */
function resolveLeaf(flow: FlowScope, pack: RawPack | null, leaf: AnyLeaf): ResolvedField | null {
  const raw = rawOf(pack, leaf)
  const placeholder = !!(leaf.placeholder || (raw as { _placeholder?: boolean } | null)?._placeholder)

  let editable = true
  let reason: string | undefined

  if (leaf.k === 'field') {
    // 报告表头字段：无 editable 标记，恒可填
    editable = true
  } else if (raw?.not_applicable) {
    editable = false
    reason = '该字段在当前产品上不适用'
  } else if (raw?.editable === false) {
    editable = false
    reason = '场景包声明该字段为只读'
  } else if (leaf.k === 'param' && !adjustableHere(flow, raw as RawControlParam)) {
    editable = false
    reason = `该控制参数未声明可在当前流程（${FLOW_PREFIX[flow]}）调整`
  }

  return {
    leaf,
    key: leafKey(flow, leaf),
    path: pathOf(pack, leaf),
    editable,
    reason,
    min: raw && 'min' in raw ? (raw.min ?? null) : null,
    max: raw && 'max' in raw ? (raw.max ?? null) : null,
    unit: (raw?.unit ?? null) || null,
    options: raw?.options,
    placeholder,
  }
}

/**
 * 归一化：去掉空白/全角空格、书名号/引号，并把**层级分隔符统一成一个字符**。
 *
 * ⚠️ 2026-10-14：必须把 `→` / `-` / `—` / `>` / `/` 一律换成同一个分隔符，
 * 否则模型按「被测对象 → 机械外形 → 风扇厚度」给路径、而用户或模型偶尔写成
 * 「被测对象-机械外形-风扇厚度」时，第二、三段就比不上了。
 */
function norm(s: string): string {
  return simp(String(s))
    .replace(/[\s\u3000]+/g, '')
    .replace(/[「」『』“”"'（）()【】[\]]/g, '')
    // 层级分隔符统一：→ > » - — – / \ · 全部折成 '>'
    // （连字符写在字符类**末尾**，避免被解析成范围）
    .replace(/[→>»/\\·\u2014\u2013-]+/g, '>')
    .toLowerCase()
}

/**
 * 三级解析：① 精确键 → ② 精确字段名 → ③ 完整路径/字段名模糊包含。
 *
 * 三级都命中不了时返回 null，调用方再用 `findSimilar()` 给候选。
 * 同级别有多条命中时返回第一条（场景包内 key 唯一，name 偶有重复）。
 */
export function resolveField(
  flow: FlowScope,
  pack: RawPack | null,
  ident: string,
): ResolvedField | null {
  if (!pack || !ident) return null
  const want = String(ident).trim()
  const wantNorm = norm(want)

  const pool: ResolvedField[] = []
  for (const leaf of allLeaves(pack)) {
    if (!allowsType(flow, leaf.k)) continue
    const r = resolveLeaf(flow, pack, leaf)
    if (r) pool.push(r)
  }

  // ① 精确键（含末段 key 精确，允许用户只给 key 不给 flow 前缀）
  const byKey = pool.find((r) => r.key === want)
  if (byKey) return byKey
  const byLast = pool.find((r) => r.key.split('.').pop() === want)
  if (byLast) return byLast

  // ② 精确字段名（原样，或归一化后相等）。**双名匹配**（2026-10-15）：
  //    报告表头字段同时带中 / 英两个名字（leaf.name 随界面语言、leaf.nameAlt 是另一种），
  //    用户或模型给任何一边的写法都要能命中；其它段没有 nameAlt，行为与改动前一致。
  const byName = pool.find((r) => r.leaf.name === want || r.leaf.nameAlt === want)
  if (byName) return byName
  const byNameNorm = pool.find(
    (r) => norm(r.leaf.name) === wantNorm || (r.leaf.nameAlt != null && norm(r.leaf.nameAlt) === wantNorm),
  )
  if (byNameNorm) return byNameNorm

  // ③ 完整路径或字段名模糊包含（路径里的 → / > / - 都当作分隔符）
  const flat = norm(want)
  const byPath = pool.find((r) => norm(r.path).includes(flat))
  if (byPath) return byPath
  const byContains = pool.find(
    (r) => norm(r.leaf.name).includes(flat) || (r.leaf.nameAlt != null && norm(r.leaf.nameAlt).includes(flat)),
  )
  if (byContains) return byContains

  return null
}

/** 找不到字段时给相似候选（字段名包含关系 + 长度接近优先），默认取 3 条 */
export function findSimilar(
  flow: FlowScope,
  pack: RawPack | null,
  ident: string,
  top = 3,
): FieldCandidate[] {
  if (!pack) return []
  const want = norm(ident)
  if (!want) return []
  const pool: ResolvedField[] = []
  for (const leaf of allLeaves(pack)) {
    if (!allowsType(flow, leaf.k)) continue
    const r = resolveLeaf(flow, pack, leaf)
    if (r) pool.push(r)
  }
  // 评分：单字命中数 / 长度差，越大越像
  const chars = new Set([...want])
  const scored = pool
    .map((r) => {
      const n = norm(r.leaf.name)
      // 双名一起参与打分（2026-10-15）：用户给的语言与界面语言不同时也能给对候选
      const alt = r.leaf.nameAlt ? norm(r.leaf.nameAlt) : ''
      let hit = 0
      for (const c of chars) if (n.includes(c) || alt.includes(c)) hit++
      return { r, score: hit * 100 - Math.abs(n.length - want.length) }
    })
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, top)
  return scored.map((x) => ({ path: x.r.path, name: x.r.leaf.name }))
}

/** 解析出「数值 + 可选单位后缀」；非数值返回 null */
function parseNumeric(raw: string): number | null {
  const s = String(raw).trim().replace(/[，,]/g, '')
  if (!/^[+-]?(\d+(\.\d*)?|\.\d+)$/.test(s)) return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}

/**
 * 校验一个待写入值；通过返回归一化后的值（字符串形式），不通过返回原因。
 *
 * 校验顺序（任一不过即拒，原因要能直接说给人听）：
 *  ① 字段可编辑（含 not_applicable / adjustable_in_flows）
 *  ② 清空守卫：空串只允许占位项或本人填过的项
 *  ③ 枚举字段必须落在 options 内
 *  ④ 数值字段必须可解析、且落在 min..max 内
 */
export function validate(
  _flow: FlowScope,
  _pack: RawPack | null,
  field: ResolvedField,
  rawValue: string,
): { ok: true; value: ParamValue } | { ok: false; reason: string } {
  if (!field.editable) {
    return { ok: false, reason: field.reason || '该字段不可编辑' }
  }

  const raw = String(rawValue ?? '')
  const trimmed = raw.trim()

  // ② 清空守卫
  if (trimmed === '') {
    const key = field.key
    const touched = useAppStore.getState().touched[key]
    if (!field.placeholder && !touched) {
      return {
        ok: false,
        reason: '这是源材料自带的有效值，不允许清空；如确需修改请给出新值',
      }
    }
    return { ok: true, value: '' }
  }

  // ③ 枚举
  if (field.options && field.options.length) {
    const hit = field.options.find(
      (o) => String(o.value) === trimmed || o.label === trimmed || norm(o.label) === norm(trimmed),
    )
    if (!hit) {
      const labels = field.options.map((o) => o.label).join(' / ')
      return { ok: false, reason: `取值必须是以下之一：${labels}` }
    }
    return { ok: true, value: String(hit.value) }
  }

  // ④ 数值校验。
  //
  // ⚠️ 「这个字段是不是数值型」不能只看 min/max 是否存在——场景包里大量数值字段
  // 的 min/max 是 null（如 fan_outer_size，实测 `min=null max=null unit=mm`）。
  // 初版据此判为「非数值型」直接放行，于是 `20mm` 这种**带单位后缀**的输入也能通过，
  // 写进 overrides 后界面上就出现「20mm mm」这种脏数据。
  // 现在的判据（三者任一 → 数值型）：
  //   ① 声明了 min 或 max；
  //   ② 当前值本身就是数字类型；
  //   ③ **声明了 unit**（如 `fan_outer_size` 有 unit=mm 但 min/max 为 null）。
  // 第 ③ 条是关键：文本型字段（客户名称、工程师）都不带 unit，带 unit 的
  // 就是物理量，必须拒收「20mm」这种带后缀的写法。
  const numeric = parseNumeric(trimmed)
  const numericField =
    (field.min !== null && field.min !== undefined) ||
    (field.max !== null && field.max !== undefined) ||
    typeof field.leaf.value === 'number' ||
    !!field.unit
  if (numeric !== null) {
    if (field.min !== null && field.min !== undefined && numeric < field.min) {
      return { ok: false, reason: `值小于允许下限 ${field.min}${field.unit ? ' ' + field.unit : ''}` }
    }
    if (field.max !== null && field.max !== undefined && numeric > field.max) {
      return { ok: false, reason: `值大于允许上限 ${field.max}${field.unit ? ' ' + field.unit : ''}` }
    }
    // ⚠️ 必须返回**数字**而不是字符串（2026-10-15 修「AI 填了值但左栏看起来是空的」）：
    // 左栏数值字段用 `Stepper`，其 `value={typeof v === 'number' ? v : null}`
    // （flow-init/panel.tsx:139）——给字符串就变成 null，输入框显示为空，
    // 用户以为「没填进去」。人的输入路径 `onChange={(n) => setParam(key, n)}`
    // 传的也是数字，这里必须与之一致。
    return { ok: true, value: numeric }
  }
  if (numericField) {
    const range: string[] = []
    if (field.min !== null && field.min !== undefined && field.max !== null && field.max !== undefined)
      range.push(`${field.min}~${field.max}`)
    const unit = field.unit ? ` ${field.unit}` : ''
    return {
      ok: false,
      reason:
        `该字段是数值型，请**只填数字本身、不要带单位后缀**` +
        `（写 20 而不是「20${field.unit || ''}」）` +
        `${range.length ? `；允许范围 ${range[0]}${unit}` : ''}`,
    }
  }
  return { ok: true, value: trimmed }
}

/**
 * 真正写入。
 *
 * · `attr` / `param` → `setParam(${flow}.pa|cp.${group}.${key}, value)`
 *   （同时写 overrides 与 touched，左栏由既有订阅自动更新）
 * · `field` → `setReportHeader(key, value)`
 *
 * ⚠️ 这里**不自动落库**：流程 1 的唯一落库入口是「确认并锁定」（persistSnapshot），
 * AI 若绕过会破坏「人确认才落库」的纪律。落库由调用方（执行器）按字段类型决定。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function applyWrite(_flow: FlowScope, field: ResolvedField, value: ParamValue): void {
  const st = useAppStore.getState()
  if (field.leaf.k === 'field') {
    // 报告表头字段一律是文本，转成字符串存
    st.setReportHeader(field.leaf.id, String(value))
    return
  }
  // ⚠️ 原样传 ParamValue（数值字段必须保持 number），勿在此 String() 化
  st.setParam(field.key, value)
}

/** 读字段当前值（人工覆盖 → 已落盘快照 → 场景包源值）；取不到返回 null */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function readValue(_flow: FlowScope, field: ResolvedField): string | null {
  const st = useAppStore.getState()
  const ov = st.overrides[field.key]
  const snap = st.snapshotValues?.[field.key]
  const cur = ov !== undefined && ov !== '' ? ov : snap !== undefined && snap !== '' ? snap : null
  if (cur !== null && cur !== undefined) return String(cur)
  if (field.leaf.value === null || field.leaf.value === undefined) return null
  return String(field.leaf.value)
}

/** 字段的人类可读描述（给执行器回报用）：路径 + 当前值 + 单位 + 范围 */
export function describe(field: ResolvedField): string {
  const parts: string[] = [field.path]
  const cur = readValue('init', field)
  parts.push(cur === null || cur === '' ? '（空）' : cur)
  if (field.unit) parts.push(`单位 ${field.unit}`)
  if (field.options?.length) parts.push(`可选 ${field.options.map((o) => o.label).join('/')}`)
  else if (field.min !== null && field.min !== undefined && field.max !== null && field.max !== undefined)
    parts.push(`范围 ${field.min}~${field.max}`)
  return parts.join(' · ')
}
