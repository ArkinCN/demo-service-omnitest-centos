import { loadCsv } from '../timeseries'
import type { Series } from '../timeseries'
import { getPack, type RawDataset, type RawPack } from '../scene/pack'

/* ===========================================================================
   场景包时序数据的加载与指标计算。

   数据：public/scenes/<sceneId>/assets/waveforms/*.csv，登记在 datasets.json。
   两个包的时序不同源，这里只认 datasets.json 的登记，不对列名与物理量做假设：

   - 散热风扇包：示波器实测，列名 `voltage_v` 沿用通道命名、物理量其实是相电流
     （安培）；t < 0 的上电前窗口是人工 0 V 补线，不是实测，不能据此评噪声零漂；
     探头变比未确认，绝对量级在客户给出 mV/A 系数前不对外引用。
   - 玻璃升降器包：三条合成 CSV（`synthetic: true`），列名 `current_a` 等直接就是
     物理量。合成数据必须在时序卡与判定卡上标「合成数据，非实测」。
   =========================================================================== */

export interface Wave {
  id: string
  title: string
  /** 判定态：只有登记结果严格是 PASS 才算合格，其余一律不当合格用 */
  verdict: 'pass' | 'fail' | 'other'
  /** 登记结果原文，照抄不改写（例如「PASS（电流），但工况本身违反 SI-HW-03」） */
  verdictText: string
  caseId: string | null
  series: Series
  /** 主信号的物理单位，取自 datasets.json 的列名，不写死 */
  unit: string
  /** 这条是合成的，不是实测 */
  synthetic: boolean
  note: string
  sampleRate: number | null
  points: number
  metrics: {
    /** 主信号绝对值峰值 */
    peak: number
    peakAt: number
    /** 首次明显响应的时刻（ms）——越过量程 5% 的第一点 */
    firstResponseMs: number
    /** 末段 0.5 s 的均方根，代表稳态 */
    steadyRms: number
    /** t ≥ 0 的有效样本数 */
    n: number
  }
}

function metricsOf(x: Float64Array | number[], y: Float64Array | number[]) {
  let peak = 0
  let peakAt = 0
  let n = 0
  const tEnd = x[x.length - 1]
  // 阈值按本条曲线自己的量程定（5%），不写死绝对值——两个包的量级差一个数量级
  let span = 0
  for (let i = 0; i < y.length; i += 1) span = Math.max(span, Math.abs(y[i]))
  const thresh = span * 0.05
  let first = Number.NaN
  const last: number[] = []
  for (let i = 0; i < x.length; i += 1) {
    const t = x[i]
    if (t < 0) continue
    n += 1
    const a = Math.abs(y[i])
    if (a > peak) {
      peak = a
      peakAt = t
    }
    if (Number.isNaN(first) && a > thresh) first = t
    if (t > tEnd - 0.5) last.push(y[i])
  }
  const steadyRms = last.length ? Math.sqrt(last.reduce((s, v) => s + v * v, 0) / last.length) : 0
  return {
    peak,
    peakAt,
    firstResponseMs: Number.isNaN(first) ? Number.NaN : first * 1000,
    steadyRms,
    n,
  }
}

/** 登记结果 → 判定态。只有严格 PASS 算合格，带条件的一律归 other，不粉饰。 */
function verdictOf(d: RawDataset): { verdict: Wave['verdict']; text: string } {
  const raw = (d.label?.operator_result ?? d.label?.expected_result ?? '').trim()
  if (!raw) return { verdict: 'other', text: '未登记结果' }
  if (raw === 'PASS') return { verdict: 'pass', text: '合格' }
  if (raw.startsWith('FAIL')) return { verdict: 'fail', text: '不合格' }
  return { verdict: 'other', text: raw }
}

/**
 * 主信号列的挑法。
 * 先按 datasets.json 登记的列序找第一个带物理单位的量，找不到才退回第一条曲线。
 * 时间列由 loadCsv 吃掉，不参与。
 */
const UNIT_OF: [RegExp, string][] = [
  [/current|_a$/i, 'A'],
  [/voltage/i, 'A'], // 散热风扇包的 voltage_v 是通道命名，物理量是相电流
  [/force|_n$/i, 'N'],
  [/speed|mm_s/i, 'mm/s'],
  [/position|opening|_mm$/i, 'mm'],
]

function pickSeries(d: RawDataset, series: Series[]): { s: Series; unit: string } | null {
  const order = d.columns.map((c) => c.key).filter((k) => k !== 'time_s')
  for (const key of order) {
    const hit = series.find((x) => x.name === key || x.name.includes(key))
    if (!hit) continue
    const unit = UNIT_OF.find(([re]) => re.test(key))?.[1]
    if (unit) return { s: hit, unit }
  }
  return series[0] ? { s: series[0], unit: '' } : null
}

/**
 * 本轮回放哪几条。
 * 散热风扇包一批 101 个 attempt，只复制了 PASS / FAIL 各一条进包，取这两条对照；
 * 玻璃升降器包三条工况各一条，全取。统一规则：取所有「已复制进包」的条目，
 * 超过四条时按判定态取前两个不同态的代表，避免卡里塞不下。
 */
function pickDatasets(pack: RawPack): RawDataset[] {
  const inPack = pack.datasets.datasets.filter((d) => d.mode.includes('into_pack'))
  if (inPack.length <= 4) return inPack
  const seen = new Set<string>()
  const out: RawDataset[] = []
  for (const d of inPack) {
    const k = verdictOf(d).verdict
    if (seen.has(k)) continue
    seen.add(k)
    out.push(d)
  }
  return out.length ? out : inPack.slice(0, 2)
}

const cache = new Map<string, Promise<Wave[]>>()

/** 读当前场景包登记的时序数据。场景包未就位时不缓存空结果。 */
export function loadWaves(): Promise<Wave[]> {
  const pack = getPack()
  if (!pack) return Promise.resolve([])
  const hit = cache.get(pack.scene.id)
  if (hit) return hit

  // 不合格曲线可能不止一条，同一个浅绿画出来会叠成一条。两档次级绿按出现次序发，
  // 叠三条时能一眼数出是三条；暗红仍只留给徽标，不画进曲线，避免整屏红。
  const FAIL_COLORS = ['#6E9A82', '#A8C5B5']

  const task = (async () => {
    const out: Wave[] = []
    let failSeen = 0
    for (const d of pickDatasets(pack)) {
      const rel = d.file_path.split('/assets/')[1]
      if (!rel) continue
      const r = await loadCsv(`${pack.base}assets/${rel}`, { timeColumn: 'time_s' })
      const picked = pickSeries(d, r.series)
      if (!picked) continue
      const { verdict, text } = verdictOf(d)
      const failColor = FAIL_COLORS[failSeen % FAIL_COLORS.length]
      if (verdict === 'fail') failSeen += 1
      const label = d.columns.find((c) => c.key !== 'time_s')?.name ?? d.name
      out.push({
        id: d.id,
        title: d.name,
        verdict,
        verdictText: text,
        caseId: d.label?.case_id ?? null,
        unit: picked.unit,
        synthetic: d.synthetic === true,
        note: d.note ?? '',
        sampleRate: r.sampleRate,
        points: r.plottedPoints,
        series: {
          name: `${label.split('（')[0]} · ${d.id}`,
          unit: picked.unit,
          x: r.time,
          y: picked.s.y,
          status: verdict === 'pass' ? 'pass' : verdict === 'fail' ? 'fail' : undefined,
          // 组件按 status 取色时依赖首帧的 CSS 变量，首帧拿不到会退回中性调色板，
          // 这里直接给显式色：合格墨绿实线，不合格走两档次级绿（见 FAIL_COLORS）。
          color: verdict === 'pass' ? '#2E5E45' : verdict === 'fail' ? failColor : '#9A9A9A',
        },
        metrics: metricsOf(r.time, picked.s.y),
      })
    }
    return out
  })()
  cache.set(pack.scene.id, task)
  return task
}

/**
 * 画进图里的阈值线。
 * 只画量级与本条曲线可比的阈值：远高于曲线量程的（例如软过流 10 A 对上 0.6 A 的
 * 相电流）画进去会把纵轴撑平，默认收起，放大态才给。
 */
export function currentThresholds(includeAll = false, peak = 0): { y: number; label: string; color?: string }[] {
  const pack = getPack()
  if (!pack) return []
  const out: { y: number; label: string; color?: string }[] = []
  const limit = pack.controls.parameters.find(
    (p) => /current_limit|limiter_threshold|overcurrent/i.test(p.key) && typeof p.value === 'number',
  )
  if (limit && typeof limit.value === 'number')
    out.push({ y: limit.value, label: `${limit.name} ${limit.value}${limit.unit ?? ''}（${limit.key.toUpperCase()}）` })

  for (const il of pack.interlocks.interlocks) {
    const th = il.threshold as { value?: number; unit?: string } | null
    if (!th || typeof th.value !== 'number') continue
    if (!/电流|current/i.test(il.name)) continue
    const tooBig = peak > 0 && th.value > peak * 4
    if (tooBig && !includeAll) continue
    out.push({ y: th.value, label: `${il.name} ${th.value}${th.unit ?? ''}（${il.id}）`, color: '#A6353A' })
    if (out.length >= 3) break
  }
  return out
}

export const POWERUP_ANNOTATION = {
  x: 0,
  label: 't=0',
}
