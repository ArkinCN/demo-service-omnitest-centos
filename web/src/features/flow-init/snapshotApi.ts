/* ===========================================================================
   配置快照 config-snapshot/v1 —— init 流程的产物。

   为什么要有它（本轮补的是一个**真实缺口**）：
   此前「初始化配置」页改的参数只存在 useAppStore.overrides 里，**纯内存**，
   刷新即丢；「确认并锁定」同样只在内存。表现是：人改了 29 项、点确认，
   刷新后回到 7 项——数据从没离开过浏览器。阶段 2 只接通了「标题保存」，
   参数这一路从来没搭过。

   契约（docs/开发交接/v4.0-20260921/contracts/config-snapshot.schema.json）：
     $id = config-snapshot/v1，产生方 init、消费方 tune/report。
   按主文档 4.1 的收发关系表，「跑完一轮」时也会带一份快照，
   但那份此前只记了场景与时刻（见 flow-run/api.ts 的注释）——本轮把完整的
   product_attributes 填上，两处共用同一个构造器，不再各写一份。

   两条纪律：
     一、**不冒充**。契约 required 里 firmware / interlock_instances / channel_map
         三项，本阶段前端没有可填的真值（工程路径、联锁实例状态、通道映射
         都在后续流程与设备桥那边）。**如实给空数组/最小对象并说明缺什么**，
         不编造路径与状态——编出来的快照比没有更糟，下游会当真值用。
     二、**origin 用契约的三值**（document / manual / suggested），
         与界面上的「文档 / 人工 / 建议」三态一一对应，不另造词。
   =========================================================================== */
import {
  getPack,
  type RawAttribute,
  type RawControlParam,
  type RawHeaderField,
} from '../scene/pack'
import { useAppStore } from '../../state/useAppStore'
import type { FlowId } from '../../data/types'
import { createRun, listRuns, putArtifact, getRun } from '../flow-run/api'
import { pickArtifact } from '../shared/artifacts'

/** 契约 config-snapshot/v1 里 product_attributes 的一项 */
export interface SnapshotAttribute {
  key: string
  value: unknown
  unit?: string
  /** 三态来源：文档 / 人工 / 建议（契约 §6.2） */
  origin: 'document' | 'manual' | 'suggested'
  /** 出处（文件 + 定位），可为空 */
  _source?: { file?: string; locator?: string }
  /**
   * 非契约字段（2026-09-28 加）：这一项属于初始化页的哪一类参数。
   *
   * 缺省 = 本体属性（product-attributes.json）；
   * 'control' = 控制参数（control-parameters.json）；
   * 'header'  = 报告表头字段（report-template.json）。
   *
   * 为什么要它：契约里 `product_attributes` 是**唯一**的参数数组，
   * 而初始化页有三类参数要一起存。加一个判别字段比改契约结构代价小，
   * 且老快照（无此字段）天然按「本体属性」处理，向后兼容。
   */
  _class?: 'control' | 'header'
}

export interface ConfigSnapshot {
  schema: 'config-snapshot/v1'
  snapshot_id: string
  scene_id: string
  scene_pack_version?: string
  locked_at: string
  locked_by: string
  product_attributes: SnapshotAttribute[]
  firmware: {
    project_path: string
    param_header_path: string
    macro_total?: number
    macro_whitelist?: string[]
  }
  interlock_instances: unknown[]
  channel_map: unknown[]
  /**
   * 这份快照落盘时，人是否**按下了「确认并锁定」**。
   *
   * ⚠️ 为什么要单独这个字段（而不是看 locked_at 有没有值）：
   * 契约里 locked_at / locked_by 是 **required**，每份快照都必然有值，
   * 所以它们只能表示「什么时候写的」，**区分不出「只是存了参数」与「已锁定」**。
   * 首版就是拿它当锁定依据，结果刷新后参数回来了、流程也被一并标成锁定——
   * 用户指出「这两者是独立的」。
   *
   * 语义：**参数持久化与流程锁定是两件事**。
   *   - 落快照 = 保存参数（随时可做，人改了就该存住）
   *   - locked = 人显式确认锁定（下游据此认基线；未锁定则下游不该采信）
   * 所以这里记的是那次落盘**是不是由锁定动作触发的**。
   */
  locked?: boolean
  /**
   * 非契约字段（2026-09-28 加）：这份快照各类参数各存了几项。
   * 供人与下游快速判「这份快照覆盖齐了没有」，不必自己去遍历数组分类。
   */
  _counts?: { attributes: number; control: number; header: number }
  /** 非契约字段：本阶段缺了哪些，供人与下游知道这是不完整快照 */
  _incomplete?: string[]
}

/** 取当前场景包的本体属性表（RawPack 里是 attributes.attributes 两层）。 */
function packAttributes(): RawAttribute[] {
  const pack = getPack()
  return pack?.attributes?.attributes ?? []
}

/** 取当前场景包的控制参数表。 */
function packControls(): RawControlParam[] {
  const pack = getPack()
  return pack?.controls?.parameters ?? []
}

/** 取当前场景包的报告表头字段表。 */
function packHeaderFields(): RawHeaderField[] {
  const pack = getPack()
  return pack?.report?.header_fields ?? []
}

/** 把界面三态标记映射到契约三值。取值与 SourceTag 的「文档 / 人工 / 建议」一致。 */
function originOf(a: RawAttribute, touched: boolean): SnapshotAttribute['origin'] {
  if (touched) return 'manual'     // 人改过 → 人工
  if (a._placeholder) return 'suggested' // 源材料没给、当前是占位 → 建议
  return 'document'                // 源材料给的 → 文档
}

const asSource = (s: RawAttribute['_source']): SnapshotAttribute['_source'] | undefined => {
  if (!s) return undefined
  const one = Array.isArray(s) ? s[0] : s
  if (!one) return undefined
  return { file: one.file, locator: one.locator }
}

/**
 * store 里参数覆盖值的类型。useAppStore 的 `ParamValue` 是模块内私有（未导出），
 * 这里用等价的本地别名，不去改公共导出（那是壳层的接口面，动它影响面更大）。
 */
type ParamValue = number | string

/**
 * 由当前 store 现场构造一份 config-snapshot/v1。
 *
 * 取值优先级与界面一致：**override（人改的）优先，其次场景包原值**——
 * 若这里改用场景包原值，人改的东西就又丢了，等于没补。
 *
 * ⚠️ **本轮（2026-09-28）修的真实缺口：只存本体属性，漏了两类可编辑参数。**
 * 初始化页左栏有三类人可改的参数，此前只有第一类进了快照：
 *   ① 本体属性 `init.pa.*`（product-attributes.json）—— 原来就存
 *   ② 控制参数 `init.cp.*`（control-parameters.json）—— **原来漏了**
 *   ③ 报告表头 `init.rp.*`（report-template.json 的表头字段）—— **原来漏了**
 * 表现：改②③后刷新即丢，且**点「保存参数」也存不下**（它走的是同一个
 * `buildSnapshot`）。这是「假通」里最隐蔽的一类——界面上值还在（内存里），
 * 完全看不出没落库。
 *
 * `product_attributes` 是契约 `config-snapshot/v1` 里唯一允许多态的数组
 * （见 docs 契约：键名不变，值形状由 `key` 区分）。所以三类统一进这个数组，
 * 靠 `_class` 字段标注它属于哪一类，**不改契约结构**——下游按 `_class` 分流。
 */
/**
 * 这份快照**将要写入多少条参数**（= 三类参数合计）。
 *
 * ⚠️ 为什么要单独暴露这个数（2026-09-28 用户实测反馈「一共 75 条却确认了 109 条」）：
 * 左栏那个 `total` 是**tiers 的可见项统计**（受折叠与派生分组影响，实测 75），
 * 而快照实际写的是**三类参数全量**（本体属性 29 + 控制参数 70 + 报告表头 10 = 109）。
 * 两个数出自两套口径，同一屏上并列就必然让人怀疑「是不是多存了」。
 *
 * 按用户拍板「以快照实际写入条数为准」：**未确认态按钮也要显示这个数**
 *（以前显示 tiers 的 `total`），这样点之前与点之后是同一个数，
 * 不会出现「按钮 75 → 回执 109」的跳变。
 */
export function snapshotCount(): number {
  return packAttributes().length + packControls().length + packHeaderFields().length
}

export function buildSnapshot(opts: {
  sceneId: string
  operator?: string
  lockedAt?: string
  /** 本次落盘是否由「确认并锁定」触发。默认 false（=只是保存参数） */
  locked?: boolean
}): ConfigSnapshot {
  const st = useAppStore.getState()
  const attrs = packAttributes()

  const product_attributes: SnapshotAttribute[] = attrs.map((a) => {
    const key = `init.pa.${a.group}.${a.key}`
    const override = st.overrides[key]
    const touched = Boolean(st.touched[key])
    const raw = override ?? (a.not_applicable ? '不适用' : a.value)
    return {
      key: a.key,
      value: raw,
      ...(a.unit ? { unit: a.unit } : {}),
      origin: originOf(a, touched),
      ...(asSource(a._source) ? { _source: asSource(a._source) } : {}),
    }
  })

  // ② 控制参数：值取 override，没人改就取场景包原值（与界面显示一致）。
  const controlAttrs: SnapshotAttribute[] = packControls().map((p) => {
    const key = `init.cp.${p.group}.${p.key}`
    const override = st.overrides[key]
    const touched = Boolean(st.touched[key])
    const raw = override ?? (p.not_applicable ? '不适用' : p.value)
    return {
      _class: 'control' as const,
      key: p.key,
      value: raw,
      ...(p.unit ? { unit: p.unit } : {}),
      origin: touched ? ('manual' as const) : ('document' as const),
      ...(asSource(p._source) ? { _source: asSource(p._source) } : {}),
    }
  })

  // ③ 报告表头字段：人填的值同样要存住（首版只在报告页内存里，刷新即丢）。
  const headerAttrs: SnapshotAttribute[] = packHeaderFields().map((f) => {
    const key = `init.rp.header.${f.key}`
    const override = st.overrides[key]
    const touched = Boolean(st.touched[key])
    return {
      _class: 'header' as const,
      key: f.key,
      value: override ?? '',
      origin: touched ? ('manual' as const) : ('suggested' as const),
      ...(touched ? { _source: { locator: `人工填写 · ${key}` } } : {}),
    }
  })

  // firmware：契约 required 要 project_path / param_header_path，本阶段前端拿不到
  // 客户工程真实路径（那些路径在客户机器上、未随包提供）。**如实留空串**并在
  // _incomplete 里点名，不编一条看起来像真的路径。
  const firmware = { project_path: '', param_header_path: '' }

  const counts = {
    attributes: product_attributes.length,
    control: controlAttrs.length,
    header: headerAttrs.length,
  }

  return {
    schema: 'config-snapshot/v1',
    snapshot_id: `cs-${opts.sceneId}-${Date.now().toString(36)}`,
    scene_id: opts.sceneId,
    locked_at: opts.lockedAt ?? new Date().toISOString(),
    locked_by: opts.operator ?? '当前操作员',
    // 只有锁定动作触发的落盘才置 true；保存参数时是 false。
    locked: Boolean(opts.locked),
    // 三类合并进同一数组（契约里 product_attributes 是唯一的参数数组），
    // 靠 `_class` 区分：缺省=本体属性 / 'control'=控制参数 / 'header'=报告表头。
    product_attributes: [...product_attributes, ...controlAttrs, ...headerAttrs],
    // 非契约字段：让下游与人都能一眼看出这份快照覆盖了几类、各几项。
    _counts: counts,
    firmware,
    interlock_instances: [],
    channel_map: [],
    _incomplete: [
      'firmware.project_path 待补：客户工程真实路径在客户机器上，未随交付包提供',
      'firmware.param_header_path 待补：同上',
      'interlock_instances 待补：联锁实例状态在流程 4 闸门与设备桥那边',
      'channel_map 待补：通道映射在流程 2 的采集配置里',
    ],
  }
}

/**
 * 落一份配置快照：新建一轮，把快照写成它的 config-snapshot 产物。
 *
 * 为什么要新建一轮：产物是挂在轮次（run_id）上的，没有轮次就无处挂
 * （与采纳落库同一个道理，见 flow-tune/adoptApi.ts）。这里建的是
 * 「初始化配置」这一轮，run 流程跑完时那份快照仍由 persistRun 自己落。
 *
 * 返回 run_id，供界面记住「这次锁定的快照在哪一轮」。
 *
 * ⚠️ **这是唯一的落库入口**：页面底部的「确认并锁定」（左栏页脚）走它。
 *
 * 演进：曾一度与另一个「保存参数」按钮各写一套（一个落 `locked:false`、
 * 一个落 `locked:true`），两个入口互不知情。2026-09-28 用户要求把
 * 「保存参数」并入「确认并锁定」，**全站只剩这一个入口**，
 * 且它落下的快照含**全部三类参数**（见 `buildSnapshot`）。
 * 顶栏那颗「提交并锁定」也不再自己落库，改为跳到本页由这里统一处理。
 */
export async function persistSnapshot(opts: {
  sceneId: string
  operator?: string
  /** true = 由「确认并锁定」触发；false/缺省 = 只是保存参数 */
  locked?: boolean
}): Promise<{ runId: string; snapshot: ConfigSnapshot }> {
  const snapshot = buildSnapshot(opts)
  const run = await createRun(opts.sceneId, 'mock')
  await putArtifact(run.run_id, 'config-snapshot', snapshot)
  return { runId: run.run_id, snapshot }
}

/**
 * 读回最近一份配置快照。
 *
 * 刷新后内存里的 overrides / confirmed 必丢，所以**不依赖内存**：
 * 按场景取最近若干轮，逐轮看有没有 config-snapshot，取到第一份就用。
 * 返回 null 表示这个场景还没落过快照（正常态，不是故障）。
 */
export async function loadLatestSnapshot(
  sceneId: string,
): Promise<{ snapshot: ConfigSnapshot; runId: string } | null> {
  const runs = await listRuns(sceneId, 10)
  for (const r of runs) {
    try {
      const { artifacts } = await getRun(r.run_id)
      const body = pickArtifact(artifacts, 'config-snapshot') as ConfigSnapshot | undefined
      // 只认真快照：老轮次那份只记了场景与时刻（没有 product_attributes），
      // 拿它回填会把界面清空——必须校验 schema，别把占位当快照。
      if (body && body.schema === 'config-snapshot/v1' && Array.isArray(body.product_attributes)) {
        return { snapshot: body, runId: r.run_id }
      }
    } catch {
      // 某一轮读不到就跳过，继续看下一轮；整体读不回来由调用方兜底
      continue
    }
  }
  return null
}

/**
 * 把快照的 product_attributes 回填到 store。
 *
 * 只回填**能在场景包里找到对应属性**的项：快照可能是旧版本场景包落的，
 * 多出来的 key 直接忽略（不往 store 里塞孤儿键，否则切产品时会带过去）。
 * 同时把 init 标为已确认——快照落盘本身就意味着「已锁定」。
 */
export function applySnapshot(snapshot: ConfigSnapshot, _flow: FlowId = 'init'): number {
  const attrs = packAttributes()
  // ⚠️ **不覆盖本次会话已经改过的项**。
  //
  // 这是必须的：loadLatestSnapshot 取的是「最近一轮」的快照，而它可能是
  // 上一次会话落的、比当前界面上的值更旧。若无条件覆盖，人刚改一项、
  // 一切页回来就被旧快照抹掉——比丢数据更难查（看起来像"改了没生效"）。
  // 现有 touched 里的键代表**本次会话人手改过**，一律以界面为准。
  const sessionTouched = useAppStore.getState().touched

  const overrides: Record<string, ParamValue> = {}
  const touched: Record<string, true> = {}
  // 全量基线（不做「与原值相同就跳过」那种优化）——它是给下游流程**回落读**用的，
  // 「初始化页确认过的每个值」都该能被继承，哪怕它恰好等于场景包原值。
  const baseline: Record<string, number | string> = {}
  let applied = 0
  for (const item of snapshot.product_attributes) {
    // ⚠️ 按 `_class` 分流回填（2026-09-28）。三类参数的 store 键中间段不同，
    // 且**反查来源也不同**（属性在 attributes.json、控制在 control-parameters.json、
    // 表头在 report-template.json）。用同一张表反查会把控制参数当属性查不到，
    // 于是静默少回填——正是「刷新后值丢一半」的成因。
    const cls = item._class ?? 'attr'
    // 三类分别解析，各自拿到 group / 键中间段 / 原值。
    // 用一个统一的小结构收口，避免在联合类型上直接取属性（TS 会拒）。
    let storeKey = ''
    let base: ParamValue = ''
    if (cls === 'control') {
      const hit = packControls().find((p) => p.key === item.key)
      if (!hit) continue
      storeKey = `init.cp.${hit.group}.${hit.key}`
      const raw = hit.not_applicable ? '不适用' : hit.value
      base = typeof raw === 'number' || typeof raw === 'string' ? raw : ''
    } else if (cls === 'header') {
      const hit = packHeaderFields().find((f) => f.key === item.key)
      if (!hit) continue
      // 表头字段没有 group 维度，界面用的就是固定段 `header`（见 FieldRow）。
      storeKey = `init.rp.header.${hit.key}`
      base = ''
    } else {
      const hit = attrs.find((a) => a.key === item.key)
      if (!hit) continue
      storeKey = `init.pa.${hit.group}.${hit.key}`
      const raw = hit.not_applicable ? '不适用' : hit.value
      base = typeof raw === 'number' || typeof raw === 'string' ? raw : ''
    }
    // 快照里的值来自上一轮的 store，形状是 number|string|boolean|null；
    // store 只收 number|string。**只回过得去的值**：null / boolean 这类
    // 场景包原值本来也是 null 的项，回填成 '' 反而会覆盖掉界面的正确显示，
    // 所以直接跳过、不计入 applied（宁可少回填，不要回填错）。
    const v: unknown = item.value
    if (typeof v !== 'number' && typeof v !== 'string') continue
    // ⚠️ baseline 要在「本次会话已改过」判断**之前**记：那一档跳过的项
    // 恰恰是**人刚刚改过**的，而它们正是下游最该继承的值。
    baseline[storeKey] = v
    // 本次会话已改过这一项 → 跳过 overrides 回填，别让旧快照把它盖回去
    if (sessionTouched[storeKey]) continue
    // 与场景包原值相同的项不必写进 overrides——写进去会让「来源」全变人工。
    // 表头字段没有「原值」概念（靠人填），origin=manual 即视为人填。
    overrides[storeKey] = v
    if (item.origin === 'manual' && (cls === 'header' || String(v) !== String(base))) {
      touched[storeKey] = true
    }
    applied += 1
  }

  // ⚠️ **参数回填与流程锁定是两件事，不能捆在一起**（用户指出的原话）。
  //
  // 首版这里无条件写 `confirmed[flow] = true`，于是「只要存过参数，
  // 刷新后就自动变成已锁定」——参数保持住了，但流程被顺手锁上了。
  // 二者语义不同：
  //   · 参数：人改过的值，随时该存住
  //   · 锁定：人显式按过「确认并锁定」，下游据此认基线
  // 所以只有快照**自己记着那次是锁定动作**时才恢复锁定态；
  // 老快照没这个字段（undefined）按**未锁定**处理——宁可让人再确认一次，
  // 也不要替他认定「已经锁过了」。
  // ⚠️ **参数一律回填，但确认态交给「本地持久化记录」决定，不靠快照反推**。
  //
  // 2026-09-28 用户实测反馈：「一打开网页就自动帮我锁上，刷新页锁我，
  // 第一次进来应该不是锁住的」。成因就在这里——原写法见到 `snapshot.locked`
  // 为真就 `confirmFlow(flow)`，而 locked:true 是**历史事实**：
  // 只要曾经确认过一次，服务端就永远留着那份快照，于是之后每次打开都被点亮，
  // 人根本没机会在首次进入时自己按一次。
  //
  // 正确判据：**本浏览器有没有记录过这次确认**（`store.confirmed` 由
  // localStorage 起，见 useAppStore 的 LS_CONFIRMED）。
  //   - 从没确认过 → 保持未确认（哪怕服务端有旧产物）
  //   - 人按过 → store 已是 true（且已持久化），什么都不用做
  //   - 人解除过 → store 是 false，**不能被服务端旧产物重新点亮**
  //
  // 这样「确认过 → 刷新仍锁」与「首次进来不锁」两个要求同时成立。
  useAppStore.setState((s) => ({
    overrides: { ...s.overrides, ...overrides },
    touched: { ...s.touched, ...touched },
    // 全量基线同时入 store：下游流程（流程 3/4）靠它回落继承
    // 「初始化页确认过的值」——见 useAppStore.resolveParamKey 的说明。
    snapshotValues: { ...s.snapshotValues, ...baseline },
  }))
  return applied
}
