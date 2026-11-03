import { useT } from '../../i18n'
/* ===========================================================================
   风扇时序曲线**受控展示卡**（2026-10-09 从 FanTrendPanel 抽出）。

   为什么抽出来：/run（人测页）与自动化运行台都要用「同一套」时序曲线 UI——
   数据来源标注、趋势/波形切换、状态与计划时长、样本点数、更新于、四通道常驻读数行、
   回到全程、波形通道开关与未采集通道清单。两处各写一份必然漂移，故抽成本组件共用。

   ⚠️ **纯受控、零副作用**（这是它能在运行台里安全使用的关键）：
     · 数据全部由 props 传入（`plan` / `samples`），本组件**不轮询、不请求本身份之外的接口**；
     · **不启停台架**、**不写 store**、**不调 settleRun**——启停与判据收口仍只在
       `FanTrendPanel`（/run 容器）里做，否则运行台会在 running 边沿再启一次台架
       （与编排器抢单设备锁 → 409），终态还会重复写回判据实测量。
     · 唯一的网络行为是 `useWaveforms` 的**只读** GET（按最新 capture_id 拉波形文件）。

   自持的显示层状态（两处实例互不干扰）：`view`（趋势/波形）、`hiddenRoles`、
   `chartRef`、`updatedAt`、`missingChannels`、`canResetZoom`。
   =========================================================================== */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { FanTrendChart, fmtNum, type FanTrendChartHandle } from './FanTrendChart'
import {
  FanWaveChart,
  ROLE_LABEL as ROLE_NAME,
  SHORT_LABEL,
  CH_COLOR,
  type FanWaveChartHandle,
} from './FanWaveChart'
import { useWaveforms } from './useWaveforms'
import type { FanPlan, FanSample } from './api'
import { Segmented } from '../../components/ui/Segmented'

type ViewMode = 'trend' | 'wave'

/**
 * 采集类型标签（2026-10-09 增）。
 *
 * 后端 `profile` 的三种取值来源（见 hardware/py/scope_capture.py）：
 *   · `pwm`        —— 只有 PWM 档（tach 未启用时的既有形态），含 CH1~CH3；
 *   · `tach`       —— 只有转速档（`run-scope` 单独采集路径），只含 CH4；
 *   · `pwm+tach`   —— 合并记录：同一次物理采集的两档已并成一条，含 CH1~CH4。
 * 未列出的取值走调用点的兜底（`${profile} 采集`），不吞掉未知形态。
 */
const CAPTURE_PROFILE_LABEL: Record<string, string> = {
  pwm: 'PWM 采集',
  tach: '转速采集',
  'pwm+tach': 'PWM+转速采集',
}

export interface FanTrendViewProps {
  plan: FanPlan | null
  samples: FanSample[]
  /** 「状态：xxx」显示什么。不传则不渲染该项（运行台按后端 plan.status 传入）。 */
  phaseLabel?: string
  /** 错误文案（/run 传 useFanTrend().error；运行台传 plan.error）。 */
  error?: string
  /** 波形拉取用的 run id；缺省回落到 plan.run_id。 */
  runId?: string | null
  /** 无 plan 时的空态文案（两处措辞不同，故由调用方给）。 */
  emptyHint?: string
  /**
   * 图表容器像素下限，默认 260（/run 既有口径）。
   * 运行台趋势行下限只有 220px，工具行 + 读数行叠加后会挤压绘图区，故传 140 让位，
   * 紧凑降级交给 `FanTrendChart` 既有的 full/slim/tiny。
   */
  chartMinH?: number
  /** 图表高度：/run 的 `full` 布局传 380（沿用旧签名语义）。 */
  full?: boolean
}

export function FanTrendView({
  plan,
  samples,
  phaseLabel,
  error,
  runId,
  emptyHint,
  chartMinH = 260,
  full,
}: FanTrendViewProps) {
  const uiT = useT()

  const effectiveRunId = runId ?? plan?.run_id ?? null

  /** 图表实例句柄（只用于「回到全程」）。趋势图与波形图句柄同形（都只有 `resetZoom`），
   *  切换视图时各自 `onChartReady` 会把它覆盖为当前图表的句柄，
   *  于是工具行的「回到全程」在两个视图下都能真正生效。 */
  const chartRef = useRef<FanTrendChartHandle | FanWaveChartHandle | null>(null)
  const onChartReady = useCallback((h: FanTrendChartHandle | FanWaveChartHandle) => {
    chartRef.current = h
  }, [])

  // 视图：趋势 / 波形（仅显示层切换，不碰采集）
  const [view, setView] = useState<ViewMode>('trend')
  // 波形数据：按最新 capture_id 实时拉取（数据纪律：缺测如实标注，不伪造）
  // stale=true 表示当前展示的是**保留的最近一次采集**（收工后/重挂载后无新数据），
  // 卡头必须如实标注「非实时」，不得让上一轮数据冒充本轮。
  const {
    wave,
    loading: waveLoading,
    error: waveError,
    commandedPct,
    updatedAt,
    stale,
    staleRunId,
  } = useWaveforms(effectiveRunId, samples)
  /**
   * 被用户隐藏的通道角色集合。卡头的通道开关按钮（React）与 ECharts 的
   * `legend.selected` 必须共用同一份真相，否则按钮按下态会和曲线显隐漂移。
   */
  const [hiddenRoles, setHiddenRoles] = useState<Set<string>>(new Set())
  const toggleRole = useCallback((role: string) => {
    setHiddenRoles((prev) => {
      const next = new Set(prev)
      if (next.has(role)) next.delete(role)
      else next.add(role)
      return next
    })
  }, [])
  // 换采集（capture_id 变化）时复位显隐，避免上一份采集的隐藏态串到下一份。
  const captureId = wave?.capture_id ?? ''
  useEffect(() => {
    setHiddenRoles(new Set())
  }, [captureId])

  // 波形视图下 showWave 用于图表容器文案（趋势图无数据提示 vs 波形提示各自表述）
  const waveHint = useMemo(() => {
    if (!wave) return ''
    if (!wave.available) return wave.notes[0] ?? '本次采集未读到波形文件'
    return ''
  }, [wave])

  /**
   * 「回到全程」是否可用：
   *   · 趋势视图——有样本点即可复位（横轴 0~全程）；
   *   · 波形视图——已拿到一次**含可用通道**的采集才可复位（有波形才有缩放可复位）。
   */
  const canResetZoom = view === 'trend'
    ? samples.length > 0
    : Boolean(wave?.channels?.some((c) => c.available && c.time_s?.length))

  /**
   * 未采集通道清单：图例已缩成 CH1~CH4 以避让轴名，
   * 「哪个通道没采到」需要另有一处如实说明。口径：后端返回的通道里 available=false 的，
   * 以及**完全没返回的角色**（如 tach 未启用）都算「未采集」，逐条列出角色名 + 原因。
   * 与 16 处「未采集」文案同义，不补 0、不臆测。
   */
  const missingChannels = useMemo(() => {
    const out: string[] = []
    const byRole = new Map((wave?.channels ?? []).map((c) => [c.role, c]))
    for (const { role } of [
      { role: 'current' },
      { role: 'voltage' },
      { role: 'pwm' },
      { role: 'tach' },
    ]) {
      const c = byRole.get(role)
      if (!c) out.push(`${ROLE_NAME[role] ?? role}（本次未返回）`)
      else if (!c.available) out.push(`${ROLE_NAME[role] ?? role}（${c.reason ?? '未采集'}）`)
    }
    return out
  }, [wave])

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      {/* 工具行：数据来源 + 视图切换 + 运行状态 + 计划时长 + 样本点数 + 更新于 + 回到全程。
          启动仍走各容器的入口，这里不放启动类按钮；
          「回到全程」只动视图缩放，不碰采集与判定，属显示层。 */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 pb-1.5">
        <span className="text-[12px] text-t3">
          {plan ? (plan.simulation ? uiT('模拟数据（simulation=true）') : uiT('真实台架数据')) : uiT('未启动')}
        </span>
        <Segmented
          size="sm"
          ariaLabel={uiT("图表视图切换")}
          items={[
            { value: 'trend', label: '趋势', title: '按档位聚合的趋势（占空比/电压/电流/转速随时间）' },
            { value: 'wave', label: '波形', title: '示波器一次采集的 CH1~CH4 真实时序波形' },
          ]}
          value={view}
          onChange={(v) => setView(v as ViewMode)}
        />
        {phaseLabel !== undefined && <span className="text-[12px] text-t3">{uiT("状态：")}{phaseLabel}</span>}
        {plan && (
          <span className="num text-[12px] text-t3">
            {uiT("计划 ")}{plan.planned_duration_s}s
            {plan.overrun ? uiT('（已延期）') : ''}
            {plan.actual_duration_s != null ? ` ${uiT('· 实际 {v1}s', { v1: plan.actual_duration_s })}` : ''}
          </span>
        )}
        {/* 已采样本点数：多采后一眼可见密度（每档 N 次 × 档数），便于核对链路是否生效 */}
        {samples.length > 0 && (
          <span className="num text-[12px] text-t3" title={uiT("已采到的样本点数（每档连续采集多次后应明显多于档位数）")}>
            {uiT("样本 ")}{samples.length} {uiT(" 点")}</span>
        )}
        {/* 活性指示：显示曲线数据最近一次刷新距今多久，让人一眼看出「系统在动」而非怀疑卡死。
            自带 1s tick，不引发整卡重渲。 */}
        <UpdateAgo updatedAt={updatedAt} />
        {/* ⚠️ 转速读数（`RecentRpm`）已**并入图表上方的四通道读数行**（LatestReadouts），
            此处不再单独出一项，避免「转速」在卡上出现两处。波形视图仍显示当前档位。 */}
        {view === 'wave' && (
          <span className="num text-[12px] text-t3" title={uiT("当前波形对应的采集档位、采集类型与是否实时")}>
            {uiT("波形")}{commandedPct != null ? uiT(" @ {v1}% 档", { v1: commandedPct }) : ''}
            {/* 采集类型三态（2026-10-09 改）：backend 现已把同一次物理采集的 pwm 与
                tach 两档合并为一条记录，`profile` 因此可能是 `pwm+tach` —— 原二值判断
                会把合并采集**误标成「PWM 采集」**（明明含 CH4 转速）。
                三态：仅 pwm → CH1~CH3；仅 tach → CH4；合并 → 四通道全含。
                如实标注，避免误判「为什么没有 CH4」。 */}
            {wave?.profile ? uiT(" · {v1}", { v1: CAPTURE_PROFILE_LABEL[wave.profile] ?? `${wave.profile} 采集` }) : ''}
            {waveLoading ? uiT(' · 加载中…') : ''}
            {/* 保留态：明确标注「非实时 + 轮次前 8 位」，避免把上一轮波形当成本轮结果。 */}
            {stale && (
              <span
                className="ml-1 rounded-tpx border border-line px-1 py-0 text-[11px] text-t3"
                data-testid="wave-stale-badge"
                title={uiT("本轮暂无新采集（通常已收工）；此处展示的是最近一次成功采集的波形，非实时数据")}
              >
                {uiT("非实时")}{staleRunId ? uiT(" · 上一轮 {v1}", { v1: staleRunId.slice(0, 8) }) : ''}
              </span>
            )}
          </span>
        )}
        {/* 右侧区：把［通道开关按钮组］与［回到全程］包进同一个 `ml-auto` 容器，
            由容器一次性推到最右——原来两个按钮各自带 `ml-auto`，在 flex-wrap 下行为不确定。
            顺序即「通道开关在回到全程**左侧**」。 */}
        <div className="ml-auto flex items-center gap-2">
          {view === 'wave' && (
            <WaveChannelToggles
              channels={wave?.channels ?? []}
              hiddenRoles={hiddenRoles}
              onToggle={toggleRole}
            />
          )}
          {/* 「回到全程」：趋势/波形都可用——两者句柄同形，`chartRef` 由当前图表的
              onChartReady 覆盖，点击统一走 `resetZoom()`：
                · 趋势图 → 横轴复位到 0~全程（时间 s）；
                · 波形图 → 缩放复位到整个采集窗口（时间 μs）。
              可用条件：图上有东西可复位（趋势看是否有样本，波形看是否已拿到采集）。 */}
          <button
            type="button"
            onClick={() => chartRef.current?.resetZoom()}
            disabled={!canResetZoom}
            title={
              view === 'trend'
                ? uiT('把横轴缩放复位到 0 ~ 全程（趋势视图）')
                : uiT('把波形缩放复位到整个采集窗口（波形视图）')
            }
            className={
              canResetZoom
                ? 'cursor-pointer rounded-tpx border border-line px-1.5 py-[2px] text-[12px] text-t2 transition-colors hover:border-p300 hover:bg-p50 hover:text-p700 focus:outline-none'
                : 'cursor-not-allowed rounded-tpx border border-line px-1.5 py-[2px] text-[12px] text-t3 opacity-50'
            }
          >
            {uiT("回到全程")}</button>
        </div>
      </div>

      {error && <div className="shrink-0 pb-1.5 text-[12px] text-alert">{uiT("错误：")}{uiT(error)}</div>}
      {view === 'wave' && waveError && (
        <div className="shrink-0 pb-1.5 text-[12px] text-t3">{uiT("波形：")}{waveError}</div>
      )}

      {/* 四通道常驻读数行：把「图上 4 条线当前是多少」直接摆在图表上方，
          不必悬停 tooltip 才看得到。放在工具行之下、图表容器之上
          （**在 FanTrendChart 的 ResizeObserver 之外**），不参与紧凑降级的高度
          计算，避免把绘图区压小。口径见 LatestReadouts。 */}
      {view === 'trend' && <LatestReadouts samples={samples} />}

      {/* 图表容器：占满剩余高度，FanTrendChart 内置 ResizeObserver 自适应。
          min-h 给下限：父级卡槽在矮视口下可能把这一层压到几十像素，
          绘图区一旦低于 ~120px，ECharts 的图例/轴/滑块就会互相重叠。
          默认 260px 兜底（/run）；运行台被分隔条压到更矮时传更小的值让位。 */}
      <div className="flex-1" style={{ minHeight: chartMinH }}>
        {view === 'trend' ? (
          plan ? (
            <FanTrendChart
              plan={plan}
              samples={samples}
              height={full ? 380 : '100%'}
              onChartReady={onChartReady}
            />
          ) : (
            <div className="flex h-full items-center justify-center px-3 text-center text-[13px] text-t3">
              {emptyHint ??
                uiT('暂无数据：点击左栏底部「确认参数并启动测试」后，曲线将随时间动态刷新')}
            </div>
          )
        ) : (
          <FanWaveChart
            wave={wave}
            height={full ? 380 : '100%'}
            onChartReady={onChartReady}
            hiddenRoles={hiddenRoles}
          />
        )}
      </div>
      {view === 'wave' && waveHint && (
        <div className="shrink-0 pt-1 text-[12px] text-t3">{waveHint}</div>
      )}
      {/* 未采集通道清单：图例已缩成 CH1~CH4 以避让轴名，此处补齐「哪个通道没采到 + 原因」。
          数据纪律：如实列出，不补 0、不臆测。 */}
      {view === 'wave' && wave && missingChannels.length > 0 && (
        <div className="shrink-0 pt-1 text-[12px] text-t3">
          {uiT("未采集通道：")}{missingChannels.join('；')}
        </div>
      )}
    </div>
  )
}

/**
 * 通道开关按钮组——波形图的「图例」。
 *
 * 为什么不是 ECharts 内置图例：内置图例画在 canvas **内部**左上角，与 y 轴名挤在
 * 同一水平带（多次叠字）。这里改为 React 按钮，放在工具行右侧，且**可点击切换显隐**，
 * 与图表共用 `hiddenRoles` 状态（唯一真相）。
 *
 * 口径（数据纪律）：
 *   - 固定按 4 个角色（current/voltage/pwm/tach）渲染，**未采集的通道也列出**（置灰不可点），
 *     让用户看到「4 个通道都交代了」，而不是以为漏画；
 *   - 置灰按钮的 `title` 写明确原因（后端 `reason` 优先，缺失则说「本次未返回」）；
 *   - 纯显示层开关，不改任何测量值、不影响判定收口。
 */
function WaveChannelToggles({
  channels,
  hiddenRoles,
  onToggle,
}: {
  channels: { role: string; available: boolean; reason?: string }[]
  hiddenRoles: Set<string>
  onToggle: (role: string) => void
}) {
  const uiT = useT()

  const byRole = new Map(channels.map((c) => [c.role, c]))
  const roles = ['current', 'voltage', 'pwm', 'tach']
  return (
    <div className="flex items-center gap-1" role="group" aria-label={uiT("通道显隐开关")}>
      {roles.map((role) => {
        const ch = byRole.get(role)
        const available = Boolean(ch?.available)
        const hidden = hiddenRoles.has(role)
        const color = CH_COLOR[role] ?? '#666'
        const label = SHORT_LABEL[role] ?? role
        const title = !available
          ? `${ROLE_NAME[role] ?? role}：未采集${ch?.reason ? `（${ch.reason}）` : '（本次未返回）'}`
          : hidden
            ? `${ROLE_NAME[role] ?? role}：已隐藏，点击显示`
            : `${ROLE_NAME[role] ?? role}：显示中，点击隐藏`
        return (
          <button
            key={role}
            type="button"
            disabled={!available}
            onClick={() => onToggle(role)}
            title={title}
            aria-pressed={available && !hidden}
            className={
              'inline-flex items-center gap-1 rounded-tpx border px-1.5 py-[2px] text-[12px] transition-all duration-150 focus:outline-none ' +
              (!available
                ? 'cursor-not-allowed border-line text-t3 opacity-50'
                : hidden
                  ? 'cursor-pointer border-line text-t3 opacity-45 hover:border-p300 hover:bg-p50 hover:opacity-80'
                  : 'cursor-pointer border-line text-t2 hover:border-p300 hover:bg-p50 hover:text-p700')
            }
          >
            {/* 色块即该通道曲线色：隐藏时降透明度「熄灭」，与曲线显隐一致 */}
            <span
              aria-hidden="true"
              className="block h-[10px] w-[10px] shrink-0 rounded-[2px]"
              style={{ backgroundColor: color, opacity: available && !hidden ? 1 : 0.35 }}
            />
            {label}
          </button>
        )
      })}
    </div>
  )
}

/**
 * 活性读数：显示「曲线数据最近一次刷新距今多久」。
 *
 * 为什么单独做一个子组件而不是在父组件里算：距今时间需要每秒重算，
 * 若放在父组件里会让整张卡（含两个 ECharts 实例）每秒重渲一次。
 * 这里让**子组件自己持 1s tick**，父组件只在 `updatedAt` 变化时重渲，开销可控。
 *
 * 口径：`updatedAt` 为空（本轮还没取到波形 / 还没启动）→ 显示「等待首次采集」，
 * 不显示 0 或假值（数据纪律：没采到就如实说没采到）。
 */
function UpdateAgo({ updatedAt }: { updatedAt: number | null }) {
  const uiT = useT()

  const [, force] = useState(0)
  useEffect(() => {
    if (updatedAt == null) return
    const t = window.setInterval(() => force((n) => n + 1), 1000)
    return () => window.clearInterval(t)
  }, [updatedAt])

  if (updatedAt == null) {
    return (
      <span className="num text-[12px] text-t3" title={uiT("尚未取到本轮波形数据")}>
        {uiT("等待首次采集")}</span>
    )
  }
  const ageS = Math.max(0, (Date.now() - updatedAt) / 1000)
  return (
    <span
      className="num text-[12px] text-t3"
      title={uiT("曲线数据最近一次刷新距今多久；采集本身约 1.5~2s 一次，约 2s 内跳动属正常")}
    >
      {uiT("更新于 ")}{ageS < 10 ? ageS.toFixed(1) : Math.round(ageS)}{uiT("s 前")}</span>
  )
}

/**
 * 四通道常驻读数行。
 *
 * 为什么做：趋势图画了 5 条线（命令/实测占空比、电压、电流、转速），
 * 但**数值只在悬停 tooltip 里出现**，用户「在趋势图上并不能直接看到 4 个通道
 * 对应的参数值」。这里把各通道**最新一次有效采样**常驻摆在图表上方，一眼可读。
 *
 * 四通道对应关系（与 FanWaveChart.ROLE_LABEL 一致）：
 *   · CH1 电流探头   → `current_probe_v`（V）；若有换算后的 `current_a` 则优先显示安培
 *   · CH2 供电电压   → `voltage_v`（V）
 *   · CH3 PWM 驱动   → `measured_pwm_duty_pct`（实测占空比 %）
 *   · CH4 转速传感器 → `rpm`（rpm）
 *   另列 `commanded_pwm_pct`（命令占空比 %）作参考，方便对照实测是否跟得上。
 *
 * 取值口径（项目数据纪律，绝不违背）：
 *   取**该量最后一个非 null 的样本**，而不是最后一个样本——末尾样本常常是 100% 档
 *   恒高电平那一档（该档无 PWM 边沿，duty/freq 天然为 null），直接取末尾会把
 *   「本来采到过」误报成「未采集」。
 *   格式化统一走 `fmtNum`：`null` → 「未采集」，**严禁 `Number(v) || 0`**（不补 0、不插值）。
 */
function LatestReadouts({ samples }: { samples: FanSample[] }) {
  const uiT = useT()

  const latest = useMemo(() => {
    // 逐个量取「最后一个非 null 样本」，返回 { value, why }
    const pick = (
      get: (s: FanSample) => number | null,
      qualityKey?: 'voltage' | 'current' | 'rpm',
    ): { value: number | null; why?: string } => {
      for (let i = samples.length - 1; i >= 0; i--) {
        const v = get(samples[i])
        if (typeof v === 'number' && v != null) return { value: v }
      }
      // 一个都没采到时，把后端给的原因原样透传（not_connected / 削波等），不猜。
      const why = qualityKey
        ? [...samples].reverse().find((s) => s.quality?.[qualityKey])?.quality?.[qualityKey]
        : undefined
      return { value: null, why }
    }
    return {
      commanded: pick((s) => s.commanded_pwm_pct),
      duty: pick((s) => s.measured_pwm_duty_pct),
      voltage: pick((s) => s.voltage_v, 'voltage'),
      // 电流优先给安培（换算后更直观）；否则退回探头电压 V。两者都取各自最后一个非 null。
      currentA: pick((s) => s.current_a),
      currentV: pick((s) => s.current_probe_v, 'current'),
      rpm: pick((s) => s.rpm, 'rpm'),
    }
  }, [samples])

  // 电流读数：有安培值就用安培（标 A），否则退回探头电压（标 V）——缺测口径一致。
  const current = latest.currentA.value != null
    ? { text: fmtNum(latest.currentA.value, 3), unit: 'A' }
    : { text: fmtNum(latest.currentV.value, 3), unit: 'V' }
  const currentWhy =
    latest.currentA.value == null && latest.currentV.value == null ? latest.currentV.why : undefined

  const items: Array<{ label: string; title: string; text: string; unit: string; why?: string; accent?: boolean }> = [
    {
      label: '命令占空比',
      title: 'CH3 的目标占空比（指令值，虚线参考）',
      text: fmtNum(latest.commanded.value, 1),
      unit: '%',
    },
    {
      label: '实测占空比',
      title: 'CH3 PWM 驱动实测占空比',
      text: fmtNum(latest.duty.value, 1),
      unit: '%',
      accent: true,
    },
    {
      label: '供电电压',
      title: 'CH2 供电电压（母线）',
      text: fmtNum(latest.voltage.value, 3),
      unit: 'V',
      accent: true,
      why: latest.voltage.why,
    },
    {
      label: '电流探头',
      title: 'CH1 电流探头（有换算值则显示安培，否则显示探头电压）',
      text: current.text,
      unit: current.unit,
      accent: true,
      why: currentWhy,
    },
    {
      label: '转速',
      title: 'CH4 测速 = 频率 × 60 / 每转脉冲数（PPR）',
      text: fmtNum(latest.rpm.value, 0),
      unit: 'RPM',
      accent: true,
      why: latest.rpm.why,
    },
  ]

  return (
    <div
      className="mb-1.5 flex shrink-0 flex-wrap items-center gap-x-3.5 gap-y-1 rounded-tps border border-line bg-p50 px-2 py-1.5"
      data-testid="trend-latest-readouts"
    >
      {items.map((it) => {
        const missing = it.text === '未采集'
        return (
          <span key={it.label} className="num flex items-baseline gap-1 text-[12px] text-t3" title={uiT(it.title)}>
            {uiT(it.label)}
            <span className={`text-[13px] font-semibold ${missing ? 'text-t3' : it.accent ? 'text-t1' : 'text-t2'}`}>
              {uiT(it.text)}
            </span>
            <span className="text-[11px] text-t3">{it.unit}</span>
            {/* 缺测原因原样透传（如 not_connected），不翻译、不吞 */}
            {missing && it.why ? <span className="text-[11px] text-t3">（{it.why}）</span> : null}
          </span>
        )
      })}
    </div>
  )
}

export default FanTrendView
