import { useT } from '../../i18n'
/* ===========================================================================
   四通道时序波形图（ECharts）——示波器一次采集的真实电压–时间曲线。

   与 FanTrendChart 的分工（不要混淆两者）：
     - FanTrendChart：**趋势**图。横轴实时时间(s)，画「每档聚合的标量」
       （占空比% / 电压V / 电流探头V / 转速rpm），看随档位推进的趋势。
     - FanWaveChart（本文件）：**波形**图。横轴是示波器采样时间（μs 级，可取负），
       画「一次采集里 4 个物理通道的真实逐点波形」，看的是 25kHz PWM 边沿、
       电压纹波、电流脉冲这类高频细节。

   通道语义（对齐 acceptance.json 的 scope.channels）：
     CH1 电流探头 / CH2 供电电压 / CH3 PWM 驱动 / CH4 转速传感器（tach）。

   数据纪律（不可逾越）：
     - 只画后端返回的真实数组；通道 available=false 或缺失时，图例中该项标
       「未采集」，**绝不补 0 / 插值 / 画一条假的平线**；
     - CH4 转速当前硬件未解（tach.enabled=false），无信号时如实标注，
       不因「图不好看」而伪造；
     - 横轴单位自动从秒换算为 μs（PWM 波形窗口仅约 0.24ms，用 s 读数不便）。
   =========================================================================== */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { WaveCapture } from './api'
import { fmtNum } from './FanTrendChart'

echarts.use([
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  DataZoomComponent,
  CanvasRenderer,
])

/**
 * 四通道配色：与 FanTrendChart.PALETTE 同色系，按物理角色固定，便于对照记忆。
 * 已导出（2026-10-09）：面板卡头的通道开关按钮需要同一份颜色，避免两处硬编码漂移。
 */
export const CH_COLOR: Record<string, string> = {
  current: '#A6353A', // CH1 电流探头（暗红）
  voltage: '#2E5E45', // CH2 供电电压（墨绿）
  pwm: '#6B9E82', // CH3 PWM 驱动（浅绿）
  tach: '#1F6F8B', // CH4 转速传感器（青蓝）
}

/** 角色中文名（**轴名**用，可长，因轴名沿轴竖向摆放、不挤在一起）。 */
export const ROLE_LABEL: Record<string, string> = {
  current: 'CH1 电流探头',
  voltage: 'CH2 供电电压',
  pwm: 'CH3 PWM 驱动',
  tach: 'CH4 转速传感器',
}

/**
 * 通道短标签 `CH1`~`CH4`（2026-10-09 导出）。
 *
 * 用在哪：面板卡头的**通道开关按钮**（图例已从 canvas 内搬出，改由 React 按钮承担）。
 * 角色全名（「CH1 电流探头」等）仍由 y 轴名承载；完整语义可从「轴名 + tooltip」读到。
 *
 * 与 `CH_COLOR` 成对导出（2026-10-09）：标签与配色属同一份「通道显示约定」，
 * 面板复用同一份定义，避免两处硬编码漂移。
 */
export const LEGEND_SHORT: Record<string, string> = {
  current: 'CH1',
  voltage: 'CH2',
  pwm: 'CH3',
  tach: 'CH4',
}

/**
 * `LEGEND_SHORT` 的兼容别名（面板历史引用名）。
 * 保留以免外部引用改名漂移；新代码直接用 `LEGEND_SHORT`。
 */
export const SHORT_LABEL = LEGEND_SHORT

/**
 * 图表对外句柄：只暴露「回到全程」一个动作，供面板工具行按钮复用
 * （与 `FanTrendChartHandle` 同形，面板可以统一按 `resetZoom()` 调用）。
 */
export interface FanWaveChartHandle {
  /** 把横轴缩放复位到「全程」（整个采集窗口），让用户能一键看回完整波形 */
  resetZoom: () => void
}

/**
 * 期望的 4 个通道角色（用于「通道缺失也如实列出」）。
 * 数据纪律：CH4 转速当前硬件未解（tach.enabled=false），后端不会返回该通道；
 * 这里补一条**空的**图例项「CH4 转速传感器（未采集）」，让用户看到「4 个通道都交代了」，
 * 而不是以为漏画。**不伪造任何波形数据**。
 */
const EXPECTED_ROLES: { role: string; channel: number }[] = [
  { role: 'current', channel: 1 },
  { role: 'voltage', channel: 2 },
  { role: 'pwm', channel: 3 },
  { role: 'tach', channel: 4 },
]

export interface FanWaveChartProps {
  wave: WaveCapture | null
  height?: number | string
  /**
   * 图表实例就绪时回调一次（仅一次，不进 setOption 依赖），交出「回到全程」句柄。
   * 与 `FanTrendChart` 同形：面板持有的 chartRef 在趋势/波形两个视图间通用，
   * 切换视图时由各自的 `onChartReady` 覆盖为当前图表的句柄，
   * 这样工具行的「回到全程」在两个视图下都能真正复位（2026-10-09 用户反馈波形下该按钮失效）。
   */
  onChartReady?: (handle: FanWaveChartHandle) => void
  /**
   * 被用户**隐藏**的通道角色集合（受控，2026-10-09）。
   *
   * 为什么放在面板而不是图表内部：卡头的通道开关按钮（React）与 ECharts 的
   * `legend.selected` 必须共用**同一份真相**，否则按钮的按下态会和曲线显隐漂移。
   * 面板持 state，图表只负责把它写进 `legend.selected`。
   *
   * 只接受 role（current/voltage/pwm/tach），**不按 series.name 匹配**——
   * 可用通道的 name 是「CH1 电流探头」，缺失通道是「…（未采集）」，字符串不同。
   */
  hiddenRoles?: Set<string>
}

/** 横轴单位自适应：波形窗口是 μs 级（PWM 档约 0.24ms），用 μs 读数更直观。 */
function pickTimeUnit(maxAbsS: number): { scale: number; unit: string } {
  if (maxAbsS < 1e-3) return { scale: 1e6, unit: 'μs' }
  if (maxAbsS < 1) return { scale: 1e3, unit: 'ms' }
  return { scale: 1, unit: 's' }
}

/**
 * 通道名称条（2026-10-13，需求单编号 1）：波形图上方的水平通道名，消除重叠。
 *
 * 背景：原先通道名是各 y 轴的轴名（nameLocation:'end'），多轴时横向挤在网格
 * 顶带互相叠字（用户实拍截图红框处）。现搬出 canvas，由 React 渲染一条水平名称条，
 * 与图例当初搬出 canvas 的思路一致。
 *
 * 空间不足时的降级优先级（需求单确认口径，按顺序）：
 *   1. 缩小字号（11px → 10px），尽量塞进一行；
 *   2. 仍放不下 → 允许换行（flex-wrap，自然两行内）；
 *   3. 仍放不下（单条自身比容器还宽）→ 该条省略号显示，悬停（title）看完整名称。
 *
 * 实现：先在一条隐藏的测量行里按 11px 排出全部名称，量出总宽与单条最宽，
 * 据此判定档位；容器宽度变化（ResizeObserver）时重判。
 *
 * 颜色（编号 2）：每个通道名前方画一个小色块，文字同色。颜色从曲线配置
 * `CH_COLOR` 读取（series 的 itemStyle/lineStyle 也读同一份），**不硬编码**，
 * 保证名称条与曲线颜色天然一致。
 */
type NameBarMode = 'full' | 'small' | 'wrap' | 'truncate'

export interface ChannelNameItem {
  /** 稳定 key（用角色），避免靠数组下标对齐 */
  key: string
  /** 完整名称，如「CH1 电流探头」 */
  label: string
  /** 通道配色，从 CH_COLOR 读取，与对应曲线颜色一致 */
  color: string
}

function ChannelNameBar({ items }: { items: ChannelNameItem[] }) {
  const uiT = useT()

  const boxRef = useRef<HTMLDivElement>(null)
  const measureRef = useRef<HTMLDivElement>(null)
  const [mode, setMode] = useState<NameBarMode>('full')

  useLayoutEffect(() => {
    const box = boxRef.current
    const measure = measureRef.current
    if (!box || !measure) return
    // 判档：总宽（11px 口径）与可用宽比较；10px 按字面比例 10/11 估算（同一字体线性缩放）。
    const decide = (): NameBarMode => {
      const avail = box.clientWidth
      if (avail <= 0) return 'full'
      const total = measure.scrollWidth
      if (total <= avail) return 'full'
      if (total * (10 / 11) <= avail) return 'small'
      // 换行：总宽 ≤ 2×可用宽且没有任何单条超宽时，flex-wrap 能在两行内装下
      const perChild = Array.from(measure.children).map(
        (el) => (el as HTMLElement).scrollWidth,
      )
      if (total <= avail * 2 && perChild.every((w) => w <= avail)) return 'wrap'
      return 'truncate'
    }
    setMode(decide())
    const ro = new ResizeObserver(() => setMode(decide()))
    ro.observe(box)
    return () => ro.disconnect()
  }, [items])

  const itemStyle: React.CSSProperties =
    mode === 'truncate'
      ? { minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }
      : { whiteSpace: 'nowrap' }

  return (
    <div ref={boxRef} style={{ position: 'relative', width: '100%' }}>
      {/* 隐藏测量行：恒定 11px、不换行，只用于量宽，不参与视觉 */}
      <div
        ref={measureRef}
        aria-hidden
        style={{
          position: 'absolute',
          visibility: 'hidden',
          left: 0,
          top: 0,
          display: 'flex',
          gap: 14,
          whiteSpace: 'nowrap',
          fontSize: 11,
          pointerEvents: 'none',
        }}
      >
        {items.map((it) => (
          <span key={it.key}>
            <span
              style={{
                display: 'inline-block',
                width: 8,
                height: 8,
                borderRadius: 2,
                marginRight: 4,
                background: it.color,
              }}
            />
            {uiT(it.label)}
          </span>
        ))}
      </div>
      {/* 可见名称条：水平排列；truncate 档让每条均分宽度并截断，title 兜底完整名。
          文字颜色与前方小色块同色（编号 2），从 CH_COLOR 读取，不硬编码。 */}
      <div
        style={{
          display: 'flex',
          flexWrap: mode === 'wrap' ? 'wrap' : 'nowrap',
          gap: '2px 14px',
          fontSize: mode === 'full' ? 11 : 10,
          lineHeight: '16px',
          overflow: 'hidden',
        }}
      >
        {items.map((it) => (
          <span
            key={it.key}
            title={uiT(it.label)}
            style={{
              ...itemStyle,
              flex: mode === 'truncate' ? '1 1 0' : undefined,
              color: it.color,
            }}
          >
            <span
              style={{
                display: 'inline-block',
                width: 8,
                height: 8,
                borderRadius: 2,
                marginRight: 4,
                verticalAlign: 'middle',
                background: it.color,
              }}
            />
            {uiT(it.label)}
          </span>
        ))}
      </div>
    </div>
  )
}

export function FanWaveChart({ wave, height = 360, onChartReady, hiddenRoles }: FanWaveChartProps) {
  const uiT = useT()

  const hostRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  const [compact, setCompact] = useState<'full' | 'slim'>('full')
  // 上一次的 y 轴数量：用于判断是否需要 notMerge 全量重建（轴数变化时）。
  const axisCountRef = useRef(0)
  // 上一次套用初始窄窗的采集 id：仅当采集变化时重设视野，避免每 tick 拽回用户缩放。
  const windowKeyRef = useRef<string>('')
  // 用 ref 存回调，避免 parent 每次重渲换函数导致 init effect 反复重建图表。
  const readyRef = useRef(onChartReady)
  readyRef.current = onChartReady

  // 初始化实例（仅一次）
  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const chart = echarts.init(host)
    chartRef.current = chart
    // 复位句柄：只暴露「回到全程」。波形图只有一个 inside 型 dataZoom（无滑块），
    // 复位即把窗口拉回 0%~100%（整个采集窗口），与趋势图的语义一致。
    readyRef.current?.({
      resetZoom: () => {
        chart.dispatchAction({ type: 'dataZoom', dataZoomIndex: 0, start: 0, end: 100 })
      },
    })
    const ro = new ResizeObserver(() => {
      chart.resize()
      setCompact(host.clientHeight < 200 ? 'slim' : 'full')
    })
    ro.observe(host)
    return () => {
      ro.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  // 数据变化 → 重建 series
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return

    const channels = wave?.channels ?? []
    // 横轴单位：取所有可用通道里 |t| 最大者决定
    let maxAbs = 0
    for (const c of channels) {
      if (!c.available || !c.time_s?.length) continue
      for (const t of c.time_s) maxAbs = Math.max(maxAbs, Math.abs(t))
    }
    const { scale, unit } = pickTimeUnit(maxAbs || 1e-3)

    // 可用通道（有真实数据）——下方 y 轴、初始视野窗口、series 都要用，故先声明。
    const drawn = channels.filter((c) => c.available && c.time_s?.length)

    // 默认视野窗口（2026-10-09）：只显示约 2 个 PWM 周期的时宽，让方波看得清。
    //
    // 为什么：PWM 载波 25kHz（周期 40μs），采集窗 1200 点 ≈ 240μs ≈ 6 个周期；
    // 全窗铺满卡宽（约 500px）时一个周期只有 ~80px，方波挤成密集竖条（像毛刺）。
    // 取两周期（80μs）后边沿清晰；全窗仍可用滚轮缩小看到。
    // 实现：把这个窗口作为 **dataZoom 的初始 startValue/endValue**（不是 xAxis.min/max，
    // 那样会钳死轴范围、缩不出去）；且只在采集变化时给一次，避免每 tick 拽回用户缩放。
    const span = (() => {
      let lo = Infinity
      let hi = -Infinity
      for (const c of drawn) {
        if (!c.time_s?.length) continue
        lo = Math.min(lo, c.time_s[0])
        hi = Math.max(hi, c.time_s[c.time_s.length - 1])
      }
      return Number.isFinite(lo) && hi > lo ? { lo, hi, width: hi - lo } : null
    })()
    const targetSpan = Math.min(span?.width ?? 8e-5, 8e-5) // 80μs = 2 个 25kHz 周期
    const center = span ? (span.lo + span.hi) / 2 : 0 // 取时间轴中心（触发点附近最完整）
    const viewMin = (center - targetSpan / 2) * scale
    const viewMax = (center + targetSpan / 2) * scale
    // 采集变化（capture_id 变了 / 首次出图）才重设视野；同一采集的刷新沿用用户缩放。
    const windowKey = wave?.capture_id ?? ''
    const applyInitialWindow = windowKeyRef.current !== windowKey
    windowKeyRef.current = windowKey

    // 每个可用通道一条独立 y 轴（2026-10-09）。
    //
    // 为什么一通道一轴：4 个通道量程天差地别 —— CH1 电流探头约 ±0.01V、
    // CH2 供电电压约 5V、CH3 PWM（÷10 探头 + offset）约 −60V、CH4 转速脉冲
    // 约 0~5V。同轴绘制时 −60V 的 PWM 会把其它三条压成贴底直线（实测截图：
    // CH1/CH2 完全看不见）。一通道一轴后各自按自身量程铺满，四条都看得清。
    // 轴在左右两侧交替摆放，避免左边堆满刻度。
    const roleIndex = new Map<string, number>()
    drawn.forEach((c, i) => roleIndex.set(c.role, i))

    // 把后端返回的通道与「期望的 4 个角色」对齐：后端没返回的角色（如 tach 未启用）
    // 也补一条空 series，图例里如实写「（未采集）」，保证 4 通道都交代清楚。
    const byRole = new Map(channels.map((c) => [c.role, c]))
    const ordered: { channel: number; role: string; data?: typeof channels[number] }[] = []
    for (const exp of EXPECTED_ROLES) {
      const hit = byRole.get(exp.role)
      ordered.push({ channel: exp.channel, role: exp.role, data: hit })
      if (hit) byRole.delete(exp.role)
    }
    // 角色表之外的后端通道（未来新增）也照常显示，不吞数据
    for (const [role, c] of byRole) ordered.push({ channel: c.channel, role, data: c })

    const series = ordered.map(({ role, channel, data }) => {
      const label = uiT(ROLE_LABEL[role] ?? `CH${channel}`)
      const color = CH_COLOR[role] ?? '#666'
      // 稳定 id（2026-10-09）：增量 setOption（不 notMerge）时，ECharts 按 id 对齐
      // 新旧 series。若不给 id，通道「未采集 ↔ 有数据」切换会让索引错位、出现残影。
      // 用 role 作 id（4 个角色恒定且唯一），与显示名无关。
      const id = `wave-${role}`
      // 缺采集：不画线，图例项显示「（未采集）」——绝不伪造平线
      if (!data || !data.available || !data.time_s?.length) {
        return {
          id,
          name: uiT("{v1}（未采集）", { v1: label }),
          type: 'line' as const,
          data: [] as [number, number][],
          itemStyle: { color },
          lineStyle: { color, width: 1, opacity: 0.35 },
          showSymbol: false,
          z: 1,
        }
      }
      return {
        id,
        name: label,
        type: 'line' as const,
        // 1200 点/通道：采样降频 + 大数组优化，避免卡顿（显示层策略，不改数据）
        sampling: 'lttb' as const,
        large: true,
        largeThreshold: 800,
        showSymbol: false,
        connectNulls: false,
        yAxisIndex: roleIndex.get(role) ?? 0,
        data: data.time_s.map((t, i) => [t * scale, data.voltage_v[i]] as [number, number]),
        itemStyle: { color },
        lineStyle: { color, width: 1.2 },
        // tooltip 走 fmtNum：null → 未采集，不出现 0
        tooltip: {
          valueFormatter: (v: unknown) => fmtNum(v as number | null, 3),
        },
      }
    })

    // 每条可用通道配一条 y 轴：左右交替，只有最左轴保留 splitLine（其余关掉，避免横线叠层）。
    // 同样给稳定 id（按角色），让增量合并按 id 对齐轴，避免通道增减时轴错位。
    //
    // ⚠️ 2026-10-13（需求单编号 1）：通道名不再作为轴名（nameLocation:'end'）画在
    // canvas 顶部——多轴时横向挤在同一水平带互相叠字（用户实拍截图红框处）。
    // 通道名改由图表上方的 React 名称条（ChannelNameBar）承担。轴名必须**显式置
    // name:''**：增量 setOption（合并模式）下省略字段会保留旧值，残留旧轴名。
    const yAxis = drawn.map((c, i) => {
      const isLeft = i % 2 === 0
      return {
        id: `axis-${c.role}`,
        type: 'value' as const,
        name: '', // 通道名已搬到上方名称条（见上注释）；置空防合并残留
        axisLabel: { fontSize: 10, color: CH_COLOR[c.role] ?? '#666' },
        axisLine: { show: true, lineStyle: { color: CH_COLOR[c.role] ?? '#666' } },
        position: isLeft ? ('left' as const) : ('right' as const),
        offset: Math.floor(i / 2) * 44,
        scale: true, // 不设 min:0：PWM 档为负值，强制 0 起会压扁波形
        splitLine: { show: i === 0 },
      }
    })
    const axisCount = Math.max(1, Math.ceil(drawn.length / 2))

    const option: echarts.EChartsCoreOption = {
      color: ordered.map((o) => CH_COLOR[o.role] ?? '#666'),
      animation: false, // 波形逐点绘制，关掉动画避免重绘抖动
      // 图例**不再画在 canvas 内**（2026-10-09 搬迁）：通道开关已移到卡片工具行
      // （「回到全程」左侧）的 React 按钮组，见 FanTrendPanel 的 WaveChannelToggles。
      //
      // 为什么仍保留 legend 配置对象：`legend.selected` 是 ECharts 里控制**单条 series
      // 显隐**的标准开关（内部走 `legendToggleSelect` 语义），即使图例本体不渲染也照样生效。
      // 面板把 `hiddenRoles` 写进 `selected` 即可切换曲线显隐，**不改 series/yAxis 数量**，
      // 因此走增量合并、不整图重建、也不会把用户的缩放窗口拽回。
      legend: {
        show: false, // 受控：显隐唯一真相在面板 hiddenRoles，图例本体不绘制
        // 选中态以 **series.name** 为键（true=显示 / false=隐藏）。
        // ⚠️ 不能直接拿 role 当键：可用通道的 name 是「CH1 电流探头」，缺失通道是
        // 「CH1 电流探头（未采集）」，两者都能靠 `startsWith(ROLE_LABEL[role])` 命中，
        // 故这里按 role 反查 ROLE_LABEL 前缀，**不做 name 精确匹配**。
        selected: Object.fromEntries(
          series.map((s) => {
            const hit = Object.entries(ROLE_LABEL).find(([, label]) => s.name.startsWith(uiT(label)))
            const role = hit?.[0]
            return [s.name, !(role && hiddenRoles?.has(role))]
          }),
        ),
        data: series.map((s) => s.name),
      },
      // grid.top：通道名已搬出 canvas（上方名称条），轴名不再占顶带，
      // 只需少量上边距即可（36 → 12）。坐标轴/刻度口径不变。
      // grid.bottom 34：为**居中置底的 x 轴名**留一行（同趋势图口径），
      // 否则轴名会压住末端刻度数字（2026-10-09 修「右下角文字遮挡」）。
      grid: {
        left: 52 + (axisCount - 1) * 44,
        right: 52 + (axisCount - 1) * 44,
        top: 12,
        bottom: 34,
        containLabel: true,
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        // 不在全局设 valueFormatter（各 series 自带）
      },
      xAxis: {
        type: 'value',
        name: uiT("时间 ({v1})", { v1: unit }),
        // ⚠️ 2026-10-09 修「右下角文字遮挡」：value 轴默认把轴名摆在**末端**，
        // 压住最后一个刻度数字。改为居中置底（middle），与趋势图同一口径。
        nameLocation: 'middle',
        nameGap: 22,
        nameTextStyle: { fontSize: 10, align: 'center', verticalAlign: 'top' },
        axisLabel: { fontSize: 11 },
        // 横轴上下限交给 dataZoom 管（不写 min/max）：
        // 写死 min/max 会**钳死**轴范围，用户滚轮缩不出去（只能看到窄窗）。
        // 改为初始 dataZoom 窗口收窄到 ~2 个 PWM 周期，用户可自由滚轮拉回全窗。
      },
      // 无可用通道时的兜底轴：通道名同样在上方名称条，canvas 内不再画轴名。
      yAxis: yAxis.length ? yAxis : [{ type: 'value' as const, name: '', scale: true }],
      dataZoom: [
        // 初始窗口：仅在**首次看到该采集**时给出 start/end 百分比（收窄到约 2 个周期），
        // 同一采集的后续刷新**不带** start/end，从而保留用户当前缩放（不每 tick 拽回）。
        applyInitialWindow
          ? {
              type: 'inside' as const,
              xAxisIndex: 0,
              filterMode: 'none' as const,
              startValue: viewMin,
              endValue: viewMax,
            }
          : { type: 'inside' as const, xAxisIndex: 0, filterMode: 'none' as const },
      ],
      series,
    }
    // 增量更新（2026-10-09 改）：原为 `setOption(option, true)`（notMerge 全量重建），
    // 每次采集刷新都要重建 4×1200 点的全部曲线，重绘成本可感知。
    // 现默认走合并模式：配合 series/yAxis 的稳定 id，ECharts 只更新变化的部分。
    //
    // ⚠️ 唯一例外：y 轴**数量变化**时（如 CH4 由「未采集」空 series 变为有数据，
    // 可用通道数增加 → 轴数量增加）用 notMerge 全量重建一次，避免合并模式下
    // 轴数量增减产生错位/残影。轴数量不变时（绝大多数刷新）走增量，保持低开销。
    const axisCountChanged = axisCountRef.current !== yAxis.length
    axisCountRef.current = yAxis.length
    chart.setOption(option, axisCountChanged)
    // hiddenRoles 进依赖：面板点通道开关时要重下发 option（仅改 legend.selected）。
    // ⚠️ 它**不影响 yAxis/series 数量**，所以 axisCountChanged 语义不变，
    //   切换显隐走增量合并，不会整图重建、也不会拽回用户的缩放窗口。
  }, [wave, compact, hiddenRoles, uiT])

  const hasAny = useMemo(
    () => Boolean(wave?.channels?.some((c) => c.available && c.time_s?.length)),
    [wave],
  )

  // 通道名称条的数据：与 setOption 里的 ordered 同一排序口径
  // （期望 4 角色在前、后端额外通道追加在后），未采集的通道也照常列出。
  const nameItems = useMemo<ChannelNameItem[]>(() => {
    const channels = wave?.channels ?? []
    const byRole = new Map(channels.map((c) => [c.role, c]))
    const items: ChannelNameItem[] = EXPECTED_ROLES.map((exp) => ({
      key: exp.role,
      label: uiT(ROLE_LABEL[exp.role] ?? `CH${exp.channel}`),
      color: CH_COLOR[exp.role] ?? '#666',
    }))
    for (const exp of EXPECTED_ROLES) byRole.delete(exp.role)
    for (const [role, c] of byRole) {
      items.push({
        key: role,
        label: uiT(ROLE_LABEL[role] ?? `CH${c.channel}`),
        color: CH_COLOR[role] ?? '#666',
      })
    }
    return items
  }, [wave, uiT])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height }}>
      {/* 通道名称条（编号 1）：从 canvas 内轴名搬出，水平排列、不重叠 */}
      <ChannelNameBar items={nameItems} />
      <div style={{ position: 'relative', width: '100%', flex: 1, minHeight: 0 }}>
        <div ref={hostRef} style={{ width: '100%', height: '100%' }} />
        {!hasAny && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#999',
              fontSize: 13,
              pointerEvents: 'none',
              textAlign: 'center',
              padding: '0 16px',
            }}
          >
            {wave
              ? uiT('本次采集未读到波形文件（详见上方提示）；不伪造曲线。')
              : uiT('暂无波形：启动测试并完成首次采集后，CH1~CH4 真实时序波形将在此显示。')}
          </div>
        )}
      </div>
    </div>
  )
}

export default FanWaveChart
