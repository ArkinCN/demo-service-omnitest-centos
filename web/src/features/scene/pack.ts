/* ===========================================================================
   场景包原始数据的加载与类型。

   数据源（整目录已复制进 public/scenes/<sceneId>/）：
   [源] scenes/motor.cooling-fan.fortior-fu6832
   字段含义见该目录下的 README.md。

   壳层的 ScenePackage（src/data/types.ts）是 UI 契约，只覆盖左栏参数与卡槽；
   各功能卡片要用的明细（61 份文档、24 条经验、70 项控制参数、67 条工作流…）
   走本模块直接读原始 JSON，不经壳层契约压扁。
   =========================================================================== */

import { fetchJson } from '../shared/fetchJson'
import { initialLocale } from '../../i18n/locale'

/**
 * 当前界面是否为英文（2026-10-14）。
 *
 * 本模块是**纯函数模块**（不在 React 渲染里），拿不到 `useT()`，故直接读
 * `initialLocale()`（同 context.ts 的 ctxT、agent-chat/api.ts 上送 locale 的口径）。
 *
 * ⚠️ 2026-10-15（B 方案）后，本函数**只给「读时选择器」用**（headerFieldName /
 * sectionTitle / sectionFields）。归一化 `normalize()` 一律不看语言——它在
 * `loadPack()` 里只跑一次并被模块级缓存固化，按语言定值等于把语言写进数据：
 * 「英文下打开过 → 切回中文」就再也回不来（用户实测反馈），故必须切开。
 */
// ⚠️ 命名用 `isEnglish` 而非 `useEnglish`：它不是 React Hook，只是读 localStorage 的普通函数。
// 叫 `use*` 会让 `react-hooks/rules-of-hooks` 误判为「在非组件里调用 Hook」而报 error。
function isEnglish(): boolean {
  return initialLocale() === 'en'
}

export interface SourceRef {
  file: string
  locator?: string
}

export interface RawAttribute {
  key: string
  name: string
  value: number | string | boolean | null
  unit: string | null
  min: number | null
  max: number | null
  step: number | null
  editable: boolean
  group: string
  note?: string
  /** 枚举型取值集合；非空就渲染下拉，不渲染加减号 */
  options?: { value: string | number | boolean; label: string }[]
  /** 这个量在本产品上不适用（例如有刷直流电机没有「极对数」），显示「不适用」而不是空值 */
  not_applicable?: boolean
  /** 一句话说明这条数据为什么还不算「已核实」；非空就在数值旁挂「待核实」角标 */
  _status?: string
  _placeholder?: boolean
  _source?: SourceRef | SourceRef[]
}

export interface RawControlParam extends RawAttribute {
  default: number | string | null
  adjustable_in_flows: string[]
  value_shell?: string | null
  /** 枚举型参数的取值集合；有它就渲染下拉，min/max/step 不适用 */
  options?: { value: string | number | boolean; label: string }[]
  /** 取值区间是推定的，不是源文件行尾注释给的 */
  range_estimated?: boolean
  /** 实配值低于源注释自己写的下限（源材料自身不一致，按原样登记） */
  value_below_min?: boolean
}

export interface RawInterlock {
  id: string
  name: string
  type: '硬件' | '流程' | '人员'
  threshold?: Record<string, unknown> | null
  action: string
  blocking: boolean
  quote?: string
  note?: string
  _status?: string
  _placeholder?: boolean
  _source?: SourceRef | SourceRef[]
}

export interface RawVariable {
  /** runtime.measure 现场实测量 / threshold 本条阈值 / control-parameters 控制参数 / constant 编译期常量 */
  source: 'runtime.measure' | 'threshold' | 'control-parameters' | 'constant' | string
  ref?: string
  desc: string
  unit?: string | null
  /** source 为 constant 时的字面值 */
  value?: number | string | boolean
  hex?: string
  derived_from?: string | string[]
}

export interface RawRequirement {
  id: string
  name: string
  category: string
  /** 判据表达式能否自动求值；false 表示只能人工判 */
  evaluable?: boolean
  /** 表达式里每个自由变量的来源：runtime.measure 要现场实测，threshold 取自本条 threshold */
  variables?: Record<string, RawVariable>
  criterion: string
  criterion_text: string
  threshold?: Record<string, unknown> | null
  evidence?: string[]
  flows?: string[]
  /** evaluable 为 false 时，为什么写不出布尔表达式 */
  not_evaluable_reason?: string
  /**
   * 该判据关联的调优候选标签（2026-10-08 新增，仅台架派生判据使用）。
   *
   * 用途：流程 5 判出「未达标」后，据此把对应的经验候选标为「命中本轮未达标」，
   * 让推荐针对本轮问题而不是一张静态清单。写的是控制参数 key 或语义标签，
   * 与经验条目的 `tags.parameters` 比对。
   */
  candidate_tags?: string[]
  /**
   * 本台架是否具备测量该判据的手段（2026-10-08 新增，仅台架判据使用）。
   *
   * `false` 表示台架物理上采不到该判据所需的量（如缺 MCU 故障寄存器读通道、
   * 缺红外测速、缺母线电流探头）——这不是"没采到"，是"没这个能力"，故判
   * `not_applicable` 而非 `missing`，并必须配 `bench_inapplicable_reason` 说明缺什么。
   */
  bench_applicable?: boolean
  /** `bench_applicable:false` 时必填：为什么本台架测不了（缺哪台设备） */
  bench_inapplicable_reason?: string
  _status?: string
  _placeholder?: boolean
  note?: string
  _source?: SourceRef | SourceRef[]
}

export interface RawDocument {
  id: string
  type: string
  title: string
  path: string
  size_bytes: number | null
  exists: boolean
  used_in_flows: string[]
  /** 包一是英文枚举，包二直接就是中文；展示一律用 conversion_status_label（归一化时补齐） */
  conversion_status: string
  conversion_status_label: string
  /** 归一化补出来的：这份文档是否已经转化过（未转化 / 未取得 一律为 false） */
  converted: boolean
  url?: string
  _status?: string
  converted_into?: string[]
  applies_to_cooling_fan?: boolean
  note?: string
}

export interface RawExperience {
  id: string
  symptom: string
  cause: string
  action: string
  result: string
  /** 两个包的原始键名不同（包一英文、包二中文），归一化后一律是这四个键 */
  tags: { scene: string[]; flow: string; parameters: string[]; topic: string[] }
  evidence_level: string
  _status?: string
  _source?: SourceRef | SourceRef[]
}

export interface RawDataset {
  id: string
  name: string
  mode: string
  file_path: string
  source_file_path?: string
  file_size_bytes?: number
  row_count?: number
  columns: { key: string; name: string }[]
  sample_rate_sa_per_s?: number
  memory_depth?: string
  scope?: string
  /** 探头变比是否已确认；false 时绝对量级不得对外引用 */
  probe_ratio_confirmed?: boolean
  probe_ratio_note?: string
  /** 这条时序是合成的，不是实测；界面必须显式标「合成数据，非实测」 */
  synthetic?: boolean
  _placeholder?: boolean
  duration_s?: number
  generator?: string
  synthesis_model?: string
  calibration?: string
  measured_range?: Record<string, number | number[]>
  phases?: string[]
  label?: {
    operator_result?: string
    expected_result?: string
    case_id?: string | null
    injected_fault?: string
    meaning?: string
  }
  note?: string
  _source?: SourceRef | SourceRef[]
}

export interface RawWorkflow {
  id: string
  name: string
  group: { key: string; name: string }
  voltage_level: string | null
  voltage_level_name: string
  is_subworkflow: boolean
  file_path: string
  node_count: number
  edge_count: number
  node_types: { type: string; name: string; count: number }[]
  node_group_counts?: Record<string, number>
  covers_requirements?: string[]
  purpose?: string
  _placeholder?: boolean
}

/**
 * 报告的一个表头字段。
 *
 * 两个包的模板不同型：包一是 Excel（.xlsm），字段定位用单元格地址
 * label_cell / value_cell；包二是 PDF 报告样张，同一个概念落成「节 + 字段」
 * 两级 label_section / label_slot / value_slot。归一化后统一成
 * 「一个标题位 label_slot + 一个取值位 value_slot（+ 可选的节 section）」，
 * 渲染器只认这个抽象。
 */
export interface RawHeaderField {
  key: string
  /**
   * 显示名。**恒为中文（繁/简）原文，不随界面语言**（2026-10-15 B 方案）。
   *
   * 显示一律走 `headerFieldName(f)`：中文界面返回本字段，英文界面优先 `name_en`。
   * ⚠️ 历史坑：旧实现在加载时按当时语言把本字段**就地覆写成英文**，又被
   * `loadPack()` 的模块级缓存固化 —— 「英文下打开过、切回中文」后中文名回不来，
   * 且英文名被显示层的中文短标签逻辑（去尾部英文、截 6 字）削成 `1.` / `5. Spe…`。
   */
  name: string
  /** 平行英文名（可选；缺失或空串时回退 `name`）。英文界面下由 `headerFieldName()` 取用 */
  name_en?: string
  type: string
  /** 标题位：Excel 是单元格地址，PDF 是节内字段标题位 */
  label_slot: string
  /** 取值位：Excel 是单元格地址，PDF 是节内字段取值位 */
  value_slot: string
  /** 取值位所在的节；Excel 模板没有节，为空 */
  label_section?: string
  sample_value?: string | null
  label_text_in_template?: string
  filled_in_sample?: boolean
  from_flow: string
  required_by?: string | null
  _source?: SourceRef | SourceRef[]
}

export interface RawSpecSection {
  /** 节名（中文原文，不随界面语言；显示走 `sectionTitle()`） */
  section: string
  /** 平行英文节名（可选；缺失或空串回退 `section`） */
  section_en?: string
  /** 一句话规模说明（Excel 是行区间，PDF 是字段数） */
  rows: string
  /** 字段名列表（中文原文；显示走 `sectionFields()`） */
  fields: string[]
  /** 平行英文字段名列表（与 `fields` **同序同长**；缺失或长度不符时回退 `fields`） */
  fields_en?: string[]
  from_flow: string
  maps_to: string | null
  note?: string
}

export interface RawPack {
  scene: {
    id: string
    taxonomy: Record<'level1_scene' | 'level2_category' | 'level3_product_type', { key: string; name: string }>
    product: { name: string; chip: string; control_scheme: string }
    summary: string
    generated_at: string
    images: {
      id: string
      title: string
      path: string
      width: number
      height: number
      render?: string
      note?: string
      _placeholder?: boolean
    }[]
    /** 原理图变体。包二没有这个字段，归一化时由 images 派生 */
    schematic_variants: { name: string; file: string; note?: string; rendered?: string }[]
    flows: { id: string; name: string }[]
    /** 包二独有：同一次采集在中 / 美 / 欧是三套判据 */
    regulation_matrix?: { region: string; regulation: string; force_limit_n?: number }[]
  }
  attributes: { groups: string[]; attributes: RawAttribute[] }
  controls: { groups: string[]; parameters: RawControlParam[]; notes?: unknown[] }
  interlocks: {
    types: Record<string, string>
    fault_bitmap: { bits: Record<string, string>; _source?: SourceRef }
    interlocks: RawInterlock[]
  }
  requirements: {
    categories: string[]
    criterion_syntax: string
    criterion_globals: string[]
    /** 现场实测量字典：变量名 → 名称 / 单位 / 怎么取 */
    runtime_measures: Record<string, { name: string; unit?: string | null; obtained_by: string }>
    evaluable_count: number
    not_evaluable_count: number
    requirements: RawRequirement[]
  }
  workflows: {
    total: number
    count_by_group: Record<string, number>
    node_type_legend: Record<string, string>
    /** 包二独有：六类抽象节点分组的释义 */
    node_groups?: Record<string, string>
    /** 全部工作流都是示例占位，没有客户真实文件 */
    all_placeholder?: boolean
    /** 有它就表示 assets/workflows/*.json 已经是画布内部模型，不用经 parseWfw */
    model_format?: { note: string; shape: string; [k: string]: unknown }
    workflows: RawWorkflow[]
  }
  datasets: {
    /** 包一的批次统计；包二没有这个概念，为空对象 */
    package_stats: Record<string, unknown>
    package_root?: string
    /** 本包的时序数据是否全部为合成 */
    all_synthetic?: boolean
    synthetic_banner?: string
    why_synthetic?: unknown
    real_data_alternatives?: { id: string; name: string; publisher?: string; url?: string; doi?: string; mode?: string }[]
    datasets: RawDataset[]
  }
  experience: { count: number; evidence_levels: Record<string, string>; experiences: RawExperience[] }
  documents: {
    total: number
    count_by_type: Record<string, number>
    conversion_status_legend: Record<string, string>
    documents: RawDocument[]
  }
  report: {
    /** 模板文件的可独立定位全名。包一是 .xlsm 绝对路径，包二是 PDF 样张标题 */
    template_file: string
    filled_sample_file?: string
    filler_tool?: { name: string; path: string; purpose: string; cli: string }
    /** Excel 模板的分页实测；PDF 模板没有分页，为空数组 */
    sheets: { name: string; max_row?: number; max_column?: number; image_count?: number }[]
    header_fields: RawHeaderField[]
    spec_sections: RawSpecSection[]
    /** 归一化补出来的：产物清单（波形截图 / 编号照片），按组给张数 */
    artifact_groups: { name: string; count: number }[]
    /** 报告模板一句话说明，展示在左栏 */
    template_note?: string
    /** 结论段怎么由判定结果聚合出来 */
    conclusion_binding?: { note: string; _source?: SourceRef | SourceRef[] }
    known_gap?: { text: string; _source?: SourceRef | SourceRef[] }
    /** Excel 模板独有的性能表；PDF 模板没有 */
    performance_table?: {
      sheet: string
      /** 三条通过判据，各自指回 test-requirements.json 的哪一项 */
      pass_condition: { key: string; text: string; maps_to: string }[]
      duty_rows: { start_row: number; step_pct: number; points: number[] }
      regions: string[]
      columns: {
        col: string
        cell: string
        key: string
        name: string
        csv_index: number | null
        csv_unit?: string | null
        sheet_unit?: string | null
        /** CSV 值写进表格前要乘的系数 */
        scale_factor?: number
        /** 是否由 writeFile_rust 自动写入（false 是表内公式列或另填列） */
        auto_filled_by_tool?: boolean
        note?: string
      }[]
    }
    /** Excel 模板独有的波形图位；PDF 模板没有 */
    waveform_image_slots?: {
      sheets_by_voltage: Record<string, string>
      filename_rules: { pattern?: string; meaning?: string; [k: string]: unknown }[]
      counted_images: Record<string, number>
    }
  }
  /** 归一化算出来的场景特征位，供各卡片按需挂标记 */
  caps: {
    /** 时序数据全部为合成，卡片要挂「合成数据，非实测」 */
    syntheticData: boolean
    syntheticBanner: string
    /** 探头变比未确认，电流绝对量级不对外引用 */
    probeUnconfirmed: boolean
    probeNote: string
    /** 带 _status「待核实」标记的对象条数 */
    statusCount: number
    /** 工作流来自场景包 assets/workflows/*.json（画布内部模型）还是 public/data 的 .wfw */
    workflowSource: 'pack-assets' | 'wfw-store'
  }
  /** 知识库那一路 agent 的产物是否就绪；未就绪时文档与经验由场景包顶上 */
  kb: { documentsIndex: unknown | null; experienceIndex: unknown | null; searchSamples: unknown | null }
  /** 静态资源前缀，例如 /scenes/motor.cooling-fan.fortior-fu6832/ */
  base: string
}

const FILES = [
  ['scene', 'scene.json'],
  ['attributes', 'product-attributes.json'],
  ['controls', 'control-parameters.json'],
  ['interlocks', 'safety-interlocks.json'],
  ['requirements', 'test-requirements.json'],
  ['workflows', 'workflows.json'],
  ['datasets', 'datasets.json'],
  ['experience', 'experience.json'],
  ['documents', 'documents.json'],
  ['report', 'report-template.json'],
] as const

async function getJson(url: string): Promise<unknown | null> {
  // 2026-10-08：改用统一的 fetchJson。此前这里写死 `cache: 'force-cache'`，
  // 导致改了场景包 JSON、重启前后端后界面仍读旧副本（见 fetchJson 模块头说明）。
  return fetchJson(url)
}

/* ======================================================================= 归一化

   两个场景包（散热风扇 / 玻璃升降器）同构但不同型：同样的 10 份 JSON、同样的
   `_source` 约定，但有几处字段名与建模方式按各自的源材料走——Excel 模板对 PDF
   报告样张、英文转化枚举对中文枚举、英文标签键对中文标签键。

   `normalize()` 把这些差异在加载时一次性抹平，让卡片与左栏只认一套字段。
   它只补字段、不改数值，也不发明源材料里没有的东西：补不出来的一律留空，由
   UI 显示「—」或按可选字段跳过整块。
   ======================================================================= */

/** 某条数据为什么还不算「已核实」；非空就该在界面上挂「待核实」角标 */
export const statusOf = (o: { _status?: string } | null | undefined): string => o?._status ?? ''

/** 未转化 / 未取得 这两档算「没转化」，其余都算转化过了 */
const NOT_CONVERTED = new Set(['not_converted', '未转化', '未取得'])

function normDocuments(pack: RawPack) {
  for (const d of pack.documents.documents) {
    // 包一的 conversion_status 是英文枚举，展示取 conversion_status_label；
    // 包二的 conversion_status 本身就是中文，没有 label 字段。
    d.conversion_status_label = d.conversion_status_label ?? d.conversion_status
    d.converted = !NOT_CONVERTED.has(d.conversion_status)
  }
}

/** 经验条目的标签键：包一英文 scene/flow/parameters/topic，包二中文 参数/现象/流程 */
function normExperience(pack: RawPack) {
  for (const e of pack.experience.experiences) {
    const t = e.tags as unknown as Record<string, unknown>
    if (Array.isArray(t.scene) && typeof t.flow === 'string') continue
    const list = (v: unknown): string[] =>
      Array.isArray(v)
        ? v.map(String)
        : typeof v === 'string'
          ? v.split('/').map((x) => x.trim()).filter(Boolean)
          : []
    e.tags = {
      scene: list(t.scene ?? t['场景']),
      flow: String(t.flow ?? t['流程'] ?? ''),
      parameters: list(t.parameters ?? t['参数']),
      topic: list(t.topic ?? t['现象'] ?? t['主题']),
    }
  }
}

/** 包二的 scene.json 没有 schematic_variants，用 images 派生：每张图一个变体 */
function normScene(pack: RawPack) {
  if (Array.isArray(pack.scene.schematic_variants) && pack.scene.schematic_variants.length) return
  pack.scene.schematic_variants = (pack.scene.images ?? []).map((im) => ({
    name: im.title.length > 12 ? `${im.title.slice(0, 11)}…` : im.title,
    file: im.path,
    rendered: im.path,
    note: im.note ?? im.render,
  }))
}

interface RawTechPageField {
  key: string
  name_zh?: string
  name_en?: string
  name?: string
  type?: string
  label_section?: string
  label_slot?: string
  value_slot?: string
  sample_value?: string | null
  from_flow: string
  required_by?: string | null
  _source?: SourceRef | SourceRef[]
}

interface RawSpecSectionIn {
  section?: string
  section_no?: string
  name_zh?: string
  rows?: string
  fields: (string | { key: string; name: string; value_slot?: string })[]
  from_flow: string
  maps_to?: string | null
  note?: string
}

/**
 * 报告模板归一化。
 *
 * 包一：Excel 模板（.xlsm），字段定位是单元格地址 label_cell / value_cell。
 * 包二：PDF 报告样张，字段定位是「节 + 字段」两级 label_section / label_slot /
 *       value_slot；没有 sheets、performance_table、waveform_image_slots。
 * 两边共用的抽象只有「一个标题位 + 一个取值位」，归一化后统一叫
 * label_slot / value_slot。
 */
function normReport(pack: RawPack) {
  const r = pack.report as unknown as Record<string, unknown>

  // 表头字段
  // 2026-10-15（B 方案）：归一化**不再看界面语言**——`name` 恒为中文原文，平行英文名
  // 存进 `name_en`，渲染期由 `headerFieldName()` 按当前语言二选一。这样 `loadPack()`
  // 的模块级缓存不会把语言「固化」进数据（旧实现在英文下加载后切回中文，名字回不来）。
  if (!Array.isArray(r.header_fields)) {
    const page = (r.technical_report_documentation_page ?? []) as RawTechPageField[]
    pack.report.header_fields = page.map((f) => ({
      key: f.key,
      name: f.name_zh ?? f.name ?? f.name_en ?? f.key,
      name_en: f.name_en,
      type: f.type ?? 'text',
      label_slot: f.label_slot ?? '',
      value_slot: f.value_slot ?? '',
      label_section: f.label_section,
      sample_value: f.sample_value ?? null,
      from_flow: f.from_flow,
      required_by: f.required_by ?? null,
      _source: f._source,
    }))
  } else {
    for (const f of pack.report.header_fields as unknown as (RawHeaderField & {
      label_cell?: string
      value_cell?: string
    })[]) {
      // 英文名（JSON 里本就有的 name_en）原样留在对象上，由 headerFieldName() 读时取用；
      // 这里只把旧定位位字段名归一（label_cell → label_slot）。
      f.label_slot = f.label_slot ?? f.label_cell ?? ''
      f.value_slot = f.value_slot ?? f.value_cell ?? ''
    }
  }

  // 规格表分节
  // 2026-10-15（B 方案）：与表头字段同口径——中文原文进 `section` / `fields`，
  // 平行英文进 `section_en` / `fields_en`（与 fields 同序同长），渲染期由
  // `sectionTitle()` / `sectionFields()` 按当前语言选。
  // 旧实现「加载时按语言二选一」并把中文原文丢掉（注释声称暂存 `_zh`，实际从未存在），
  // 是「英文切回中文不恢复 + 英文名被削成 `1.` / `5. Spe…`」的源头。
  pack.report.spec_sections = ((r.spec_sections ?? []) as (RawSpecSectionIn & {
    section_en?: string
    fields_en?: string[]
  })[]).map((s) => ({
    section: s.section ?? s.name_zh ?? s.section_no ?? '',
    section_en: s.section_en,
    rows: s.rows ?? `${s.fields?.length ?? 0} 字段`,
    fields: (s.fields ?? []).map((f) => (typeof f === 'string' ? f : f.name)),
    fields_en: s.fields_en,
    from_flow: s.from_flow,
    maps_to: s.maps_to ?? null,
    note: s.note,
  }))

  // 模板全名与一句话说明
  const src = r.template_source as Record<string, string> | undefined
  if (!pack.report.template_file && src)
    pack.report.template_file = src.title ?? src.file ?? String(src.kind ?? '')
  pack.report.template_note =
    (r.cell_model_note as string | undefined) ?? pack.report.filler_tool?.purpose ?? ''
  pack.report.sheets = pack.report.sheets ?? []

  // 产物清单：包一是按分页统计的波形截图，包二是报告里的编号照片
  const slots = pack.report.waveform_image_slots
  if (slots) {
    pack.report.artifact_groups = Object.entries(slots.counted_images).map(([name, count]) => ({
      name,
      count,
    }))
  } else {
    const photos = Number(r.photo_count ?? 0)
    pack.report.artifact_groups = photos
      ? [{ name: `报告内编号照片（${pack.report.template_file ? '样张实测' : '登记'}）`, count: photos }]
      : []
  }
}

/** 统计带 _status 标记的对象条数，用于左栏摘要 */
function countStatus(pack: RawPack): number {
  const lists: { _status?: string }[][] = [
    pack.attributes.attributes,
    pack.controls.parameters,
    pack.interlocks.interlocks,
    pack.requirements.requirements,
    pack.documents.documents,
    pack.experience.experiences,
  ]
  return lists.reduce((n, l) => n + l.filter((x) => x._status).length, 0)
}

/** 加载后就地补齐两个包之间的字段差异，让 UI 只认一套字段。 */
export function normalize(pack: RawPack): RawPack {
  normScene(pack)
  normDocuments(pack)
  normExperience(pack)
  normReport(pack)

  const ds = pack.datasets
  const probe = ds.datasets.find((d) => d.probe_ratio_confirmed === false)
  const synthetic = ds.all_synthetic === true || ds.datasets.every((d) => d.synthetic === true)
  pack.caps = {
    syntheticData: !!ds.datasets.length && synthetic,
    syntheticBanner:
      ds.synthetic_banner ?? '本场景包的时序数据是合成的，不是实测，不得进入任何合规报告。',
    probeUnconfirmed: !!probe,
    probeNote: probe?.probe_ratio_note ?? '',
    statusCount: countStatus(pack),
    workflowSource: pack.workflows.model_format ? 'pack-assets' : 'wfw-store',
  }
  ds.package_stats = ds.package_stats ?? {}
  return pack
}

const cache = new Map<string, Promise<RawPack | null>>()

/** 读一份场景包。任何一个必需文件缺失都返回 null，由调用方回落。 */
export function loadPack(sceneId: string): Promise<RawPack | null> {
  const hit = cache.get(sceneId)
  if (hit) return hit
  const base = `/scenes/${sceneId}/`
  const task = (async () => {
    const parts = await Promise.all(FILES.map(([, f]) => getJson(base + f)))
    if (parts.some((p) => p === null)) return null
    const pack = Object.fromEntries(FILES.map(([k], i) => [k, parts[i]])) as unknown as RawPack
    // 知识库那一路的产物是可选的（另一 agent 在做），存在就接，不存在就用场景包
    const [documentsIndex, experienceIndex, searchSamples] = await Promise.all([
      getJson('/kb/documents/index.json'),
      getJson('/kb/experience/index.json'),
      getJson('/kb/search-samples.json'),
    ])
    pack.kb = { documentsIndex, experienceIndex, searchSamples }
    pack.base = base
    return normalize(pack)
  })()
  cache.set(sceneId, task)
  return task
}

/** 已加载完成的场景包（同步取用，供 render 期读取）。 */
let current: RawPack | null = null
export const setPack = (p: RawPack | null) => {
  current = p
}
export const getPack = (): RawPack | null => current

/* ------------------------------------------------------ 报告名称：读时双语选择
 *
 * 2026-10-15（B 方案）：报告段的名称类字段（表头字段名、分节名、分节字段名）
 * **归一化时不再按语言定值**，中文原文与平行英文名同时留在数据里（见 normReport），
 * 显示与上送 AI 时用下面这几个**读时选择器**二选一。
 *
 * 为什么必须是读时选择：`loadPack()` 的模块级缓存 + `normalize()` 只跑一次，
 * 若在那里按语言定值，语言就成了「数据的一部分」——实测踩到两个后果：
 *   ① 英文下打开过、切回中文后名字回不来（缓存固化）；
 *   ② 英文名进中文短标签逻辑后被削成 `1.` / `5. Spe…`（用户截图反馈）。
 * 现在组件用 `useT()` 订阅语言、切语言即重渲 → 重渲时调这里取到新语言，无需重载。
 *
 * 英文名缺失/空串/长度不符一律回退中文：老场景包（没有 *_en 字段）行为与改动前一致。
 */

/** 表头字段显示名：中文界面恒为中文原文；英文界面优先 `name_en`，缺失回退中文 */
export function headerFieldName(f: RawHeaderField): string {
  return isEnglish() && f.name_en ? f.name_en : f.name
}

/**
 * 表头字段的「另一种语言名」，供 AI 工具做**双名匹配**（2026-10-15）：
 * 中文界面给出英文名、英文界面给出中文名；该字段本来只有一种名字时返回 undefined。
 */
export function headerFieldAltName(f: RawHeaderField): string | undefined {
  return isEnglish() ? (f.name_en ? f.name : undefined) : f.name_en
}

/** 分节显示名：中文界面恒为中文原文；英文界面优先 `section_en`，缺失回退中文 */
export function sectionTitle(s: RawSpecSection): string {
  return isEnglish() && s.section_en ? s.section_en : s.section
}

/** 分节字段名列表：英文界面优先 `fields_en`（**须与 fields 同序同长**，否则回退），中文界面恒为 `fields` */
export function sectionFields(s: RawSpecSection): string[] {
  return isEnglish() && s.fields_en?.length === s.fields.length ? s.fields_en : s.fields
}

/* ---------------------------------------------------------------- 取数助手 */

export function byGroup<T extends { group: string }>(items: T[], groups: string[]) {
  const map = new Map<string, T[]>(groups.map((g) => [g, []]))
  for (const it of items) {
    if (!map.has(it.group)) map.set(it.group, [])
    map.get(it.group)!.push(it)
  }
  return [...map.entries()].filter(([, v]) => v.length > 0)
}

export function countBy<T>(items: T[], key: (t: T) => string) {
  const m = new Map<string, number>()
  for (const it of items) m.set(key(it), (m.get(key(it)) ?? 0) + 1)
  return [...m.entries()]
}

/** 把 `_source` 归一成一行可独立定位的文字：绝对路径 + 定位符 */
export function sourceLine(s?: SourceRef | SourceRef[]): string {
  if (!s) return ''
  const one = Array.isArray(s) ? s[0] : s
  if (!one) return ''
  return one.locator ? `${one.file}（${one.locator}）` : one.file
}

export const fileName = (p: string) => p.split('/').pop() ?? p

export function sizeText(bytes?: number | null) {
  if (!bytes) return '—'
  if (bytes >= 1 << 20) return `${(bytes / (1 << 20)).toFixed(1)} MB`
  if (bytes >= 1 << 10) return `${(bytes / (1 << 10)).toFixed(0)} KB`
  return `${bytes} B`
}

/** 场景包 flow 标识（F1..F6）↔ 壳层 flow 标识 */
export const FLOW_CODE: Record<string, string> = {
  kb: 'F1',
  init: 'F2',
  req: 'F3',
  run: 'F4',
  tune: 'F5',
  report: 'F6',
}
