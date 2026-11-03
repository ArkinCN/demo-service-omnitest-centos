/* ===========================================================================
   本轮现场实测采集（真机链路）。

   流程 3 点「启动测试」后，不再只用固定回放波形求值，而是**尽力真采集**：
   调设备桥观测层 read_fg（FG1/FG2 频率 → 转速）与 read_pwm（占空比），
   把能采到的量映射成判据 runtime_measures 的变量名。

   诚实边界：
   - 只有桥返回 mode === 'live' 才采（真连示波器）；mode 为 mock / unknown 一律不采，
     判据落「未采集」，不拿合成数顶替。
   - 设备桥只覆盖转速/占空比，其余 measure（母线电流、保护标志、回归计数、时序等）
     需要客户 MotorDebug 或示波器波形分析，本函数采不到就**不编**，留给判定标「未采集」。

   映射（read_fg 返回字段 → 判据 runtime_measures 变量名）：
     fg1_hz   → fg1_freq_hz   （FG1 电气转速信号频率）
     fg2_hz   → fg2_freq_hz   （FG2 机械转速信号频率）
     fg2_hz×60 → rpm_fg        （FG 脉冲换算转速，FG2 = 1 脉冲/转）
     rpm_mean → rpm_mean       （稳态转速 3 次均值，字段名一致）
   read_pwm 的 duty_percent 暂不映射到判据变量（判据用 target_rpm，需查调速曲线，
   属现场层标定），先只采转速。
   =========================================================================== */
import { callBridgeTool } from '../remote/bridge'
import type { FanSample } from '../fan-trend/api'

/* ------------------------------------------------------------------ 台架实测聚合
   2026-10-08 新增：把风扇实验（/api/fan-tests）的真实采集样本聚合成判据可用的实测量。

   为什么需要它：判定卡的 `runMeasures` 原先只有设备桥的 read_fg（FG 转速），
   而本台架（UNO 发 PWM + Rigol DS1104Z 三通道）根本没有 FG 信号，桥也不连通，
   导致判定恒落「未采集」。本函数从本轮真实样本里提取**本台架确实测得到的量**
   （PWM 占空比精度/频率/供电电压/波形有效性），映射为 TR-BENCH-* 判据的变量名。

   诚实边界（与本项目数据纪律一致，不可逾越）：
   - 只吃 `simulation=false` 的真实样本；模拟数据一律不入判定（由调用方保证）。
   - 缺测量（null）不参与聚合、不补 0；所有档都缺时返回空对象 → 判据落「未采集」。
   - 100% 档为恒高电平、无边沿（pwm_frequency_hz / measured_pwm_duty_pct 为 null），
     属物理合理情形，**不计入有效档、也不判不通过**。
   - 转速（2026-10-08 新增，CH4 测速）：tach 是**独立时基档**（20ms/div），
     与占空比/频率（20µs/div）互不影响，所以 100% 档虽然拿不到 duty/freq，
     **照样能测转速** —— 因此有效测速档的判定只要求 `rpms.length > 0`，
     不复用「占空比与频率都采到才算有效档」那条口径。
   --------------------------------------------------------------------------- */

   /** 台架 PWM 载波基准频率（Hz）：场景包 control-parameters.pwm_frequency = 25 kHz */
   const BENCH_PWM_FREQ_BASIS_HZ = 25000

   /**
   * 「随占空比递增」判据所需的**最少有效测速档数**（2026-10-08）。
   *
   * 为什么是 3：递增是「相邻档比较」的结论，只有 1~2 个点时数学上无法断言递增
   * （1 个点没有「相邻」，2 个点只比一次且极易把采样噪声当成趋势）。
   * 宁可落「未采集」，也不给一个假失败 —— 那比不判更危险。
   */
   const MIN_TACH_GEARS_FOR_RISING = 3

   /** 单个占空比档位的聚合结果 */
   interface DutyGroup {
   commanded: number
   duties: number[] // 非 null 的实测占空比
   freqs: number[] // 非 null 的实测频率
   voltages: number[] // 非 null 的供电电压
   /** 非 null 的实测转速（rpm）。CH4 测速档独有；缺测即为空数组，不补 0。 */
   rpms: number[]
   }

/**
 * 把本轮 FanSample 聚合成台架实测量。
 *
 * 聚合口径：按 `commanded_pwm_pct` 分档，档内对每个量取**均值**（同一档会采到
 * 多个样本点，均值代表该档的稳态水平）；跨档再取「偏差最大值」用于精度类判据。
 *
 * @param samples 本轮全部样本（来自 /api/fan-tests/{runId}/samples）
 * @returns 判据变量名 → 数值；一样都没采到时返回 `{}`
 */
export function collectFanMeasures(samples: FanSample[]): Record<string, number> {
  const out: Record<string, number> = {}
  if (!samples.length) return out

  // ① 按命令占空比分档
  const groups = new Map<number, DutyGroup>()
  for (const s of samples) {
    const cmd = s.commanded_pwm_pct
    if (typeof cmd !== 'number' || !Number.isFinite(cmd)) continue
    let g = groups.get(cmd)
    if (!g) {
      g = { commanded: cmd, duties: [], freqs: [], voltages: [], rpms: [] }
      groups.set(cmd, g)
    }
    if (typeof s.measured_pwm_duty_pct === 'number' && Number.isFinite(s.measured_pwm_duty_pct))
      g.duties.push(s.measured_pwm_duty_pct)
    if (typeof s.pwm_frequency_hz === 'number' && Number.isFinite(s.pwm_frequency_hz))
      g.freqs.push(s.pwm_frequency_hz)
    if (typeof s.voltage_v === 'number' && Number.isFinite(s.voltage_v)) g.voltages.push(s.voltage_v)
    // 转速：与上面三个量同一次遍历收集，不新增遍历。
    // 后端在 tach 未开启时给的是 null（quality.rpm=not_connected），这里如实跳过。
    if (typeof s.rpm === 'number' && Number.isFinite(s.rpm)) g.rpms.push(s.rpm)
  }
  if (!groups.size) return out

  const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length

  let validDutyCount = 0 // 有边沿、可推算占空比与频率的档位数
  let maxDutyErrPct = 0
  let maxFreqDevPct = 0
  const voltageMeans: number[] = []
  /** 各档转速均值（CH4 测速档，与 PWM 有效性判定相互独立） */
  const tachRpmMeans: TachRpmMean[] = []

  for (const g of groups.values()) {
    // 有效档判定：占空比与频率都采到才算（100% 恒高电平档两者皆 null → 不计入）
    const hasDuty = g.duties.length > 0
    const hasFreq = g.freqs.length > 0

    // 转速独立于 PWM 判定：tach 是另一个时基档，采到就算一档有效测速档。
    // 放在 continue 之前，否则 100% 档（duty/freq 皆 null）会被整档跳过、
    // 丢掉本该采到的转速 —— 那是把「测不到」误当成「没测」。
    if (g.rpms.length) {
      tachRpmMeans.push({ commanded: g.commanded, rpm: mean(g.rpms) })
    }

    if (!hasDuty || !hasFreq) continue
    validDutyCount += 1

    const dutyMean = mean(g.duties)
    const freqMean = mean(g.freqs)
    // 偏差按绝对值取最大：正负偏都要算，不能只留大的一侧
    maxDutyErrPct = Math.max(maxDutyErrPct, Math.abs(dutyMean - g.commanded))
    maxFreqDevPct = Math.max(
      maxFreqDevPct,
      Math.abs(freqMean - BENCH_PWM_FREQ_BASIS_HZ) / BENCH_PWM_FREQ_BASIS_HZ * 100,
    )
    if (g.voltages.length) voltageMeans.push(mean(g.voltages))
  }

  // 一个有效档都没有 → 不编数，如实返回空（判据落「未采集」）
  // ⚠️ 只挡 PWM 四项：转速是另一种测量能力，测到了就该给判据用。
  // tach 未开启时下面本就一个键都不输出，故对既有行为零影响（回归基线不变）。
  if (validDutyCount === 0) return withTach(out, tachRpmMeans)

  out.bench_pwm_duty_err_max_pct = Number(maxDutyErrPct.toFixed(4))
  out.bench_pwm_freq_dev_max_pct = Number(maxFreqDevPct.toFixed(4))
  out.bench_valid_duty_count = validDutyCount
  if (voltageMeans.length) out.bench_voltage_mean_v = Number(mean(voltageMeans).toFixed(4))
  return withTach(out, tachRpmMeans)
}

/** 单档的转速均值（用于跨档比较递增性，故连命令占空比一起留） */
interface TachRpmMean {
  commanded: number
  rpm: number
}

/**
 * 把转速聚合结果并进实测量表（2026-10-08）。
 *
 * 四个键：
 *  - bench_valid_tach_count        采到转速的档位数（有效性判据用）
 *  - bench_rpm_mean_min / _max     各档转速均值的最小/最大值（范围判据用）
 *  - bench_rpm_rising_gear_count   转速随占空比递增的相邻档对数（**仅当有效档 ≥3 时输出**）
 *
 * 为什么递增只给标量、不给「各档 rpm 数组」：判据表达式在前后端两侧求值，
 * 后端 Python 的 eval 沙箱**只注入 abs**，数组方法一律抛异常 → 该判据会落
 * 「未采集」。标量比较（>=）两侧都能求，口径才一致。
 *
 * 有效测速档为 0（tach 未开启 / 波形削波 / 未采到）时**一个键都不输出**：
 * 让 TR-BENCH-06/07 落「未采集」，而不是拿 0 当转速去判。
 */
function withTach(out: Record<string, number>, tachRpmMeans: TachRpmMean[]): Record<string, number> {
  if (!tachRpmMeans.length) return out
  tachRpmMeans.sort((a, b) => a.commanded - b.commanded)
  out.bench_valid_tach_count = tachRpmMeans.length
  out.bench_rpm_mean_min = Number(Math.min(...tachRpmMeans.map((x) => x.rpm)).toFixed(4))
  out.bench_rpm_mean_max = Number(Math.max(...tachRpmMeans.map((x) => x.rpm)).toFixed(4))
  if (tachRpmMeans.length >= MIN_TACH_GEARS_FOR_RISING) {
    let rising = 0
    for (let i = 1; i < tachRpmMeans.length; i += 1) {
      // 严格大于：档间转速必须真的上升，持平（噪声内）不计为递增
      if (tachRpmMeans[i].rpm > tachRpmMeans[i - 1].rpm) rising += 1
    }
    out.bench_rpm_rising_gear_count = rising
  }
  return out
}

/** 一次真采集。桥不可达 / 未真连 / 电机未转（无有效测量）时返回空对象。 */
export async function collectRunMeasures(deviceId = 'bench'): Promise<Record<string, number>> {
  const out: Record<string, number> = {}
  try {
    const fg = await callBridgeTool(deviceId, 'read_fg', { samples: 3, interval_s: 0.5 })
    // 只有真连（live）且采到才登记；mock/unknown 一律不采（见文件头诚实边界）
    if (fg.mode !== 'live' || fg.status !== 'ok') return out

    if (typeof fg.rpm_mean === 'number') out.rpm_mean = fg.rpm_mean

    const samples = (fg.samples ?? []) as Array<Record<string, unknown>>
    // 取最后一次有有效频率的采样（数组是时间升序，倒着找第一条非空）
    const last = [...samples].reverse().find(
      (s) => typeof s.fg1_hz === 'number' || typeof s.fg2_hz === 'number',
    )
    if (last) {
      if (typeof last.fg1_hz === 'number') out.fg1_freq_hz = last.fg1_hz as number
      if (typeof last.fg2_hz === 'number') {
        out.fg2_freq_hz = last.fg2_hz as number
        out.rpm_fg = (last.fg2_hz as number) * 60
      }
    }
  } catch {
    // 桥不可达（demo / 没起桥 / 网络错）：留空，判据落「未采集」。不抛错、不阻塞演示。
  }
  return out
}
