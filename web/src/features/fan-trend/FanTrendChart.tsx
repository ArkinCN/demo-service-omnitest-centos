/* ===========================================================================
   风扇趋势动态折线图（ECharts，line-race 风格）。

   独立可复用组件，不依赖现有 uPlot TimeSeriesChart。能力：
     - 横轴缩放：dataZoom（inside 滚轮 + slider 底部滑条）+ 「回到全程」复位
     - 动态刷新：增量 setOption（animationDurationUpdate 平滑），x 轴随时间推进
     - 缺测断线：connectNulls=false，null 不补 0、不插值
     - 固定计划横轴 [0, planned_duration_s]，超期自动扩展
     - 三纵轴（2026-10-08）：左轴占空比% + 供电电压V、右轴转速 rpm、
       右偏轴电流探头 V。三条轴下限一律 0（从 0 起画，电压/电流不被压在轴底）。

   按需引入 ECharts 核心，不整包引入，控制包体。
   =========================================================================== */
import { useEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useT } from '../../i18n'
import type { FanPlan, FanSample } from './api'

echarts.use([
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  DataZoomComponent,
  CanvasRenderer,
])

/** 图表对外句柄：只暴露「回到全程」这一个动作，供面板工具行按钮调用 */
export interface FanTrendChartHandle {
  /** 把横轴缩放复位到 0 ~ 全程（inside 与 slider 两个组件都要发） */
  resetZoom: () => void
}

export interface FanTrendChartProps {
  plan: FanPlan
  samples: FanSample[]
  /** 图表高度：数字按 px，字符串按 CSS（如 '100%' 撑满父容器）。默认 360。 */
  height?: number | string
  /**
   * 图表实例就绪时回调一次（仅一次，不进 setOption 依赖）。
   *
   * 为什么用回调而不是 forwardRef：两个渲染点（FanTrendPanel / FanDemoPage）
   * 都只传 props，**没有一个需要命令式操作图表**；为了一个复位动作引入
   * forwardRef + useImperativeHandle 会把「谁持有实例」这条所有权搅浑。
   */
  onChartReady?: (handle: FanTrendChartHandle) => void
}

/* 折线配色。取项目 tokens 的墨绿family（--p-600 深墨绿 → 浅绿 → 近黑 → 暗红），
   第 5 色（转速）用中明度青蓝，与前四色都能分辨，且不引入新的色相体系。 */
const PALETTE = ['#2E5E45', '#6B9E82', '#2C2C2C', '#A6353A', '#1F6F8B']

/** 缺测时的一律文案。凡是「这个量没采到」都走它，不允许显示 0。 */
const MISSING_TEXT = '未采集'

/**
 * 图例缩写（只影响图例，tooltip 与读数行仍用全名 + 单位）。
 * 键是 series 的全名，值是图例上显示的短名。
 */
const LEGEND_SHORT: Record<string, string> = {
  '命令占空比 (%)': '命令占空%',
  '实测占空比 (%)': '实测占空%',
  '供电电压 (V)': '电压 V',
  '电流探头 (V)': '电流 V',
  '转速 (rpm)': '转速 rpm',
}

/**
 * 按物理量级格式化读数（2026-10-08）。
 *
 * 为什么需要：原先 tooltip 用 `String(v)`，把 IEEE754 尾数原样抛给用户 ——
 * 电流探头会显示成 `0.0017566666666666678`（用户实拍截图红框处），电压
 * `4.8920966666666675`。那是采样器的二进制浮点噪声，不是测量精度。
 *
 * @param v     原始值。**null / undefined 一律返回「未采集」**
 * @param digits 有效小数位
 * @param scale 仅用于**显示层**单位换算（如频率 Hz→kHz 传 1e-3），不改原始值
 *
 * ⚠️ 缺测纪律：第一行就判 `v == null` 返回「未采集」。绝不能写
 * `Number(v) || 0` 之类写法——那会把「没采到」悄悄变成「采到 0」。
 */
export function fmtNum(v: number | null | undefined, digits: number, scale = 1): string {
  if (v == null || !Number.isFinite(v)) return MISSING_TEXT
  const n = v * scale
  return n.toFixed(digits)
}

/** 一条折线的显示规格。位置参数已排到第 4 个，再堆精度会不可读，故改选项对象。 */
interface LineSpec {
  /** 虚线（命令参考线用） */
  dashed?: boolean
  /** 挂在哪条纵轴上（对应 option.yAxis 的下标） */
  yAxisIndex?: number
  /** tooltip / 读数的有效小数位 */
  digits?: number
  /** 显示层单位换算系数（1 = 不换算） */
  scale?: number
}

type Point = [number, number | null]

/**
 * 采样点密度的自适应阈值（2026-10-09）。
 *
 * 背景：真机原先每档只采 1 次 → 一轮仅 4 个点，必须显示标记才看得出取值；
 * 硬件改为每档连续多次采集后（默认 5 次 × 4 档 ≈ 20 点），若仍全部画实心标记，
 * 密处会糊成一片、遮住曲线。故按点数自适应：
 *   - 点少（≤ DENSE_POINTS）：显示实心标记，逐点可读；
 *   - 点多（> DENSE_POINTS）：弱化标记（小号），以细线为主，读数走 tooltip。
 * 这是纯显示层策略，不改变 series 的 name / 数据 / 缺测断线语义。
 */
const DENSE_POINTS = 12

export function FanTrendChart({ plan, samples, height = 360, onChartReady }: FanTrendChartProps) {
  const uiT = useT()

  const hostRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  /**
   * 两级紧凑（按卡片高度渐进降级）。
   *
   * 背景：网格视图下趋势图是首卡（横跨两列），实测只分到约 110px 高 ——
   * 图例（18px）+ 滑块（20px）+ 上下边距会把绘图区挤没，ECharts 干脆让它们
   * 互相重叠（实测：图例压住整块绘图区，曲线完全看不见）。
   *
   *  - 正常（≥220px）：图例 + 底部滑块
   *  - 紧凑（<200px）：收掉滑块，边距压到最小
   *  - 极矮（<130px）：**再收掉图例**，只留曲线；数值仍可在 tooltip 里逐项读到
   *
   * 迟滞阈值（进/出各差 20px）避免在临界点反复横跳导致闪烁。
   */
  const [compact, setCompact] = useState<'full' | 'slim' | 'tiny'>('full')
  // 回调只存不直接用：放依赖里会让父组件每次渲染都新建函数从而反复触发
  const readyRef = useRef(onChartReady)
  readyRef.current = onChartReady

  const axisEnd = useMemo(() => {
    const planned = plan.planned_duration_s > 0 ? plan.planned_duration_s : plan.default_duration_s
    let end = planned
    for (const s of samples) {
      if (s.t_s != null && s.t_s > end) end = s.t_s
    }
    return Math.ceil(end)
  }, [plan, samples])

  // 初始化实例（仅一次）
  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const chart = echarts.init(host)
    chartRef.current = chart
    // 复位句柄：只暴露「回到全程」。用 start/end 百分比而不是 startValue/endValue，
    // 这样即使计划时长变化也不需要重新计算全程的具体秒数。
    readyRef.current?.({
      resetZoom: () => {
        chart.dispatchAction({ type: 'dataZoom', dataZoomIndex: 0, start: 0, end: 100 })
        chart.dispatchAction({ type: 'dataZoom', dataZoomIndex: 1, start: 0, end: 100 })
      },
    })
    // 高度监听：卡片高度随布局变化（画板/网格切换、助手面板拖动、窗口缩放），
    // 决定用哪一档布局。这是本组件**唯一**新增的 ResizeObserver 职责。
    const ro = new ResizeObserver(() => {
      chart.resize()
      const h = host.clientHeight
      setCompact((prev) => {
        if (prev === 'full') return h < 200 ? 'slim' : 'full'
        if (prev === 'slim') return h < 130 ? 'tiny' : h >= 220 ? 'full' : 'slim'
        return h >= 150 ? 'slim' : 'tiny'
      })
    })
    ro.observe(host)
    return () => {
      ro.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  // 数据/计划变化 → 增量 setOption（不重建实例）
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return

    const point = (t: number | null, v: number | null): Point => [t ?? 0, v]
    // 稀疏点（≤ DENSE_POINTS）显示标记便于逐点读数；密集点弱化标记，以细线为主。
    const sparse = samples.length <= DENSE_POINTS
    const line = (name: string, pick: (s: FanSample) => number | null, spec: LineSpec = {}) => {
      const { dashed = false, yAxisIndex = 0, digits = 2, scale = 1 } = spec
      return {
        name,
        type: 'line' as const,
        // 自适应：稀疏时显点，密集时只在 hover/emphasis 处显点（避免糊成一片）
        showSymbol: sparse,
        showAllSymbol: sparse,
        symbolSize: sparse ? 6 : 4,
        connectNulls: false,
        yAxisIndex,
        data: samples.map((s) => point(s.t_s, pick(s))),
        lineStyle: dashed ? { type: 'dashed' as const } : undefined,
        // tooltip / 读数统一走 fmtNum：null → 未采集，绝不出现 0
        tooltip: { valueFormatter: (v: unknown) => fmtNum(v as number | null, digits, scale) },
      }
    }

    const option: echarts.EChartsCoreOption = {
      color: PALETTE,
      animationDuration: 300,
      animationDurationUpdate: 300,
      animationEasingUpdate: 'linear',
      // 图例：scroll 型单行 + **缩写显示**。
      // 为什么缩写：卡槽宽约 340px，5 项全名（「命令占空比 (%)」…）放不下会换行，
      // 换行后的图例会与绘图区叠在一起（实测：曲线被完全盖住，只剩图例文字）。
      // 只缩图例、**不改 series.name** —— tooltip 仍显示完整名与单位，
      // 读数含义不丢；这里只解决「图例挤」这一个显示问题。
      // 极矮档（tiny）整条隐藏：此时连 18px 都留不出，曲线比图例重要，
      // 数值仍可在 tooltip 里逐项读到。
      legend: {
        show: compact !== 'tiny',
        top: 0,
        type: 'scroll',
        textStyle: { fontSize: 12 },
        formatter: (name: string) => LEGEND_SHORT[name] ?? name,
      },
      // right 56 → 92：右侧要摆**两条**轴（转速 + 电流探头偏轴），各留刻度与轴名的位置。
      // 紧凑档再收一收：把滑块让掉、边距压到最小，保住绘图区。
      grid: {
        left: 48,
        right: 92,
        top: compact === 'tiny' ? 8 : 34,
        // bottom 2026-10-09 微调：x 轴名改为居中置底后，需要在刻度数字行**之下**
        // 再留出轴名的高度（full 档还要在轴名之下容纳 dataZoom 滑块 20px + 8px 边距）。
        //   full 56→68：轴名行 + 滑块行都放得下；
        //   非 full 20→34：无滑块，只多留一条轴名行的位置。
        bottom: compact === 'full' ? 68 : 34,
        containLabel: true,
      },
      tooltip: {
        trigger: 'axis',
        // ⚠️ 这里**不再**设全局 valueFormatter：各系列的 digits/scale 不同
        // （占空比 2 位、电压 3 位、电流 5 位、频率走 kHz），统一在 series.tooltip 里带。
        // 没采到的值由各自的 fmtNum 兜成「未采集」，不会退化成 0。
      },
      xAxis: {
        type: 'value',
        min: 0,
        max: axisEnd,
        name: uiT('时间 (s)'),
        // ⚠️ 2026-10-09 修复「时间字样重叠」：value 轴默认把轴名摆在**末端**，
        // 正好压住最后一个刻度数字（截图右下角「时间 (s)」与 `60` 叠字）。
        // 改为居中置于轴下方（middle），并给足 gap 让开刻度数字行；
        // 紧凑档没有滑块（见 dataZoom），middle + gap 也不会与别的东西打架。
        nameLocation: 'middle',
        nameGap: compact === 'full' ? 30 : 22,
        nameTextStyle: { fontSize: 10, align: 'center', verticalAlign: 'top' },
        axisLabel: { fontSize: 11 },
      },
      // 三纵轴：左轴占空比% + 供电电压；右轴转速 rpm；右偏轴电流探头。
      // 三条下限一律 min: 0 ——「从 0 开始画」是读数习惯，量程不从 0 起会把
      // 电压(4.9)与电流(0.002)这类小量程变化放大成看不懂的锯齿。
      // 两条右轴 splitLine:false，避免与左轴网格叠成双层横线。
      yAxis: [
        {
          type: 'value',
          min: 0,
          name: uiT('占空比 % / 电压 V'),
          nameTextStyle: { fontSize: 10 },
          axisLabel: { fontSize: 11 },
        },
        {
          type: 'value',
          min: 0,
          position: 'right',
          name: uiT('转速 (rpm)'),
          nameLocation: uiT('转速 (rpm)') === '转速 (rpm)' ? 'end' : 'middle',
          nameRotate: uiT('转速 (rpm)') === '转速 (rpm)' ? 0 : 90,
          nameGap: uiT('转速 (rpm)') === '转速 (rpm)' ? 15 : 52,
          nameTextStyle: { fontSize: 10, align: 'right' },
          axisLabel: { fontSize: 11 },
          splitLine: { show: false },
        },
        {
          type: 'value',
          min: 0,
          position: 'right',
          offset: uiT('电流 (V)') === '电流 (V)' ? 44 : 76,
          name: uiT('电流 (V)'),
          nameLocation: uiT('电流 (V)') === '电流 (V)' ? 'end' : 'middle',
          nameRotate: uiT('电流 (V)') === '电流 (V)' ? 0 : 90,
          nameGap: uiT('电流 (V)') === '电流 (V)' ? 15 : 44,
          nameTextStyle: { fontSize: 10, align: 'right' },
          axisLabel: { fontSize: 10 },
          splitLine: { show: false },
        },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
        // 非正常档不画底部滑块：它固定占 20px + 边距，矮卡片里等于把绘图区整个
        // 让掉。滚轮缩放（inside）仍在，用户照样能放大，回程靠面板的「回到全程」。
        ...(compact === 'full' ? [{ type: 'slider' as const, xAxisIndex: 0, height: 20, bottom: 8 }] : []),
      ],
      // 四条实测线（对应硬件 CH1 电流 / CH2 电压 / CH3 PWM / CH4 测速）
      // + 一条命令占空比虚线参考。yAxisIndex 对应上面三条纵轴。
      // showSymbol 已改为按样本点数自适应（见上方 sparse），此处不再逐个指定。
      series: [
        line(uiT('命令占空比 (%)'), (s) => s.commanded_pwm_pct, { dashed: true, digits: 2 }),
        line(uiT('实测占空比 (%)'), (s) => s.measured_pwm_duty_pct, { digits: 2 }),
        line(uiT('供电电压 (V)'), (s) => s.voltage_v, { digits: 3 }),
        line(uiT('电流探头 (V)'), (s) => s.current_probe_v, { digits: 5, yAxisIndex: 2 }),
        line(uiT('转速 (rpm)'), (s) => s.rpm, { digits: 0, yAxisIndex: 1 }),
      ],
    }
    chart.setOption(option)
  }, [samples, axisEnd, compact, uiT])

  return (
    <div style={{ position: 'relative', width: '100%', height }}>
      <div ref={hostRef} style={{ width: '100%', height: '100%' }} />
      {samples.length === 0 && (
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
          }}
        >
          {uiT('暂无数据：点击「确认参数 · N 项并启动测试」后，四通道（占空比 / 电压 / 电流 / 转速）曲线将随时间动态刷新')}
        </div>
      )}
    </div>
  )
}

export default FanTrendChart
