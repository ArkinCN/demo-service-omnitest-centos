/* ===========================================================================
   风扇实验接口客户端（对接后端 /api/fan-tests，阶段 5）。

   复用 flow-run/api.ts 的 `call<T>` 约定：后端统一 success_response 包装
   { success, code, message, data }，先看 HTTP 状态再看 success 位。

   数据纪律：samples 里缺测字段为 null，前端据此断线，不补 0、不插值；
   simulation=true 时页面如实标注「模拟数据」，不当实测上报。
   =========================================================================== */
/** 后端 success_response 包装 */
interface ApiEnvelope<T> {
  success: boolean
  code: number
  message: string
  data: T
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  let body: ApiEnvelope<T> | null = null
  try {
    body = (await resp.json()) as ApiEnvelope<T>
  } catch {
    throw new Error(`HTTP ${resp.status}`)
  }
  if (!resp.ok || !body.success) {
    throw new Error(body.message || `HTTP ${resp.status}`)
  }
  return body.data
}

export interface FanStep {
  duration_s: number
  commanded_pwm_pct: number
}

export interface FanPlan {
  schema_version: string
  simulation: boolean
  run_id: string
  mode: 'finite' | 'rolling'
  planned_duration_s: number
  default_duration_s: number
  cycles: number
  steps: FanStep[]
  status: string
  actual_duration_s?: number
  overrun?: boolean
  /** 是否已到达权威终态（stopped/completed/failed）。前端据此停止轮询。 */
  terminal?: boolean
  error?: string
}

export interface FanSample {
  sequence: number
  t_s: number | null
  measurement_started_t_s: number | null
  measurement_finished_t_s: number | null
  /**
   * 当前档的命令占空比。
   *
   * ⚠️ 可空（2026-10-09 修）：后端 `data.get("commandedPwmPercent")` 在示波器独立
   * 采集路径（run_scope.py）下会显式置 null —— 那种采集**没有下发过风扇命令**，
   * 命令值本就不存在。原声明为 `number` 属类型契约说谎；消费点一律按可空处理。
   */
  commanded_pwm_pct: number | null
  voltage_v: number | null
  current_probe_v: number | null
  current_a: number | null
  measured_pwm_duty_pct: number | null
  pwm_frequency_hz: number | null
  rpm: number | null
  quality: { voltage?: string; current?: string; rpm?: string }
  capture_id: string | null
}

export interface SamplesResponse {
  simulation: boolean
  run_id: string
  time_source: string
  samples: FanSample[]
  next_after_sequence: number
}

/**
 * 安全闸门快照（随启动请求上报后端）。
 * 后端 `_gate_ok` 优先据此放行；前端已逐条确认闸门时三项均为 true。
 */
export interface FanTestGate {
  interlocks_ok: boolean
  precheck_ok: boolean
  master_switch_on: boolean
}

export function startFanTest(opts: {
  mode?: 'finite' | 'rolling'
  cycles?: number
  steps?: FanStep[]
  default_duration_s?: number
  /** 安全闸门快照：由前端逐条确认闸门后给出，后端据此放行 */
  gate?: FanTestGate
} = {}): Promise<FanPlan> {
  return call<FanPlan>('/api/fan-tests', {
    method: 'POST',
    body: JSON.stringify(opts),
  })
}

export function getFanTest(runId: string): Promise<FanPlan> {
  return call<FanPlan>(`/api/fan-tests/${runId}`)
}

/**
 * 单通道时序波形（示波器一次采集里某个物理通道的真实电压–时间序列）。
 *
 * 数据纪律：`available=false` 表示该通道没采到（文件缺失/未接该通道），此时
 * `time_s`/`voltage_v` 为空数组且 `reason` 写明原因；**绝不补零、不插值、不伪造**。
 */
export interface WaveChannel {
  /** 物理通道号 1..4 */
  channel: number
  /** 通道语义角色：current / voltage / pwm / tach（tach 即 CH4 转速） */
  role: string
  available: boolean
  /** available=false 时的原因（原样透传后端） */
  reason?: string
  /** 各采样点真实时间（秒，相对示波器触发点；可为负） */
  time_s: number[]
  /** 对应的电压值（V，已按探头倍率折算）。电压≠物理量时由前端按角色标注含义 */
  voltage_v: number[]
  /** 电流换算后的安培值（仅 current 通道且换算开启时非空，否则 null） */
  current_a?: (number | null)[] | null
  points?: number
  skippedRows?: number
}

/** 一次采集的完整波形响应（GET /api/fan-tests/{runId}/captures/{captureId}） */
export interface WaveCapture {
  run_id: string
  capture_id: string
  cycle: number | null
  profile: string | null
  commanded_pwm_pct: number | null
  started_utc: string | null
  finished_utc: string | null
  /** 至少一个通道读到真实数据才为 true */
  available: boolean
  channels: WaveChannel[]
  notes: string[]
}

/** 拉取某次采集的真实时序波形（缺测如实返回 available=false，不伪造）。 */
export function getCapture(runId: string, captureId: string): Promise<WaveCapture> {
  return call<WaveCapture>(
    `/api/fan-tests/${encodeURIComponent(runId)}/captures/${encodeURIComponent(captureId)}`,
  )
}

export function getSamples(runId: string, afterSequence: number): Promise<SamplesResponse> {
  return call<SamplesResponse>(
    `/api/fan-tests/${runId}/samples?after_sequence=${encodeURIComponent(afterSequence)}`,
  )
}

export function stopFanTest(runId: string): Promise<{ run_id: string; status: string }> {
  return call(`/api/fan-tests/${runId}/stop`, { method: 'POST' })
}
