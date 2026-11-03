/* ===========================================================================
   四通道时序波形数据获取 hook（实时）。

   做什么：从本轮样本里挑出**最新的、带 capture_id 的样本**，按 id 请求
   `GET /api/fan-tests/{runId}/captures/{id}`，拿到 CH1~CH4 的真实时序波形。
   采集推进时（samples 增长 → 末尾 capture_id 变化）自动拉取最新一次，实现
   「示波器跑到哪、波形图就跟到哪」。

   为什么要「最新一次」而不是全部：一轮会采 20 次（4 档 × 5 次），全部加载
   就是 20 × 4 × 1200 ≈ 9.6 万点，图上重叠不可读。本 hook 只呈现**当前最新**
   一次采集的波形（卡头显示对应档位/时间），历史各次可用 capture_id 扩展。

   ⚠️ 保留最近一次（2026-10-09 新增，修「收工后波形图全暗」）：
     收工后轮询停止、样本不再增长，而**末尾样本往往已无 capture_id**（后端收口后
     不再产新采集点），若照旧 `setWave(null)`，则波形曲线与 4 个通道按钮会**全部
     熄灭**，看起来像坏了。现改为：**只要本轮曾成功取到过波形，就保留在模块级
     `LAST` 里**；取不到新数据时回落到它并置 `stale=true`，由界面如实标注
     「上一轮 · 非实时」。**不新发任何请求**，只是复用已缓存的同一个对象。
     跨轮不混淆：`runId` 变非空新值时清空 `LAST`（与缓存同口径）。

   数据纪律：
   - 缺 capture_id 的样本（模拟执行器 / 未落盘）不请求，如实置 null；
   - 请求失败 / available=false 一律如实透传 error 与 reason，不伪造波形；
   - 同 capture_id 不重复请求（内存缓存）；
   - 保留态必须**显式标注非实时**，不得让上一轮数据冒充本轮。
   =========================================================================== */
import { useEffect, useMemo, useRef, useState } from 'react'
import { getCapture, type FanSample, type WaveCapture } from './api'

/**
 * 模块级「最近一次成功取到的波形」。
 *
 * 为什么放模块级而不是 React state：卡片在终态前后可能重挂载（父级条件渲染 /
 * 路由切换），组件内 state 会随之丢失；模块级记录不随实例销毁，重挂载后可直接
 * hydrate，从而让「收工后仍能看到最近一次波形」在两种机制下都成立。
 * 只保存**一次成功请求的结果**（对象引用复用，零额外内存/零额外请求）。
 */
interface LastWave {
  runId: string
  captureId: string
  wave: WaveCapture
  commandedPct: number | null
}
let LAST: LastWave | null = null

export interface UseWaveforms {
  /** 当前展示的采集 id（无则 null） */
  captureId: string | null
  /** 波形数据（无则 null）；available=false 表示本次采集没读到真实文件 */
  wave: WaveCapture | null
  /** 是否正在请求 */
  loading: boolean
  /** 请求/解析错误（原样透传，不美化） */
  error: string
  /** 当前采集对应的命令占空比（档位），便于卡头标注 */
  commandedPct: number | null
  /** 已缓存的采集 id 数量（调试/核对用） */
  cachedCount: number
  /**
   * 最近一次**成功取到波形数据**的时刻（Date.now()，毫秒）；从未取到为 null。
   * 供卡头「更新于 x.xs 前」活性读数用——让人一眼看出数据在动，而非怀疑卡死。
   */
  updatedAt: number | null
  /**
   * true = 当前展示的是**保留的最近一次成功采集**，不是本轮实时数据
   * （收工后 / 重挂载后取不到新采集时的兜底）。界面必须据此标注「非实时」。
   */
  stale: boolean
  /** stale 时该采集所属的轮次 runId（供卡头标注「上一轮 xxxxxxxx」）；实时时为 null。 */
  staleRunId: string | null
}

/**
 * @param runId    本轮运行 id（未启动为 null）
 * @param samples  轮询得到的增量样本（按时间递增）
 */
export function useWaveforms(runId: string | null, samples: FanSample[]): UseWaveforms {
  // 初始值直接 hydrate 模块级保留记录（同轮次才认）：
  // 卡片重挂载后立刻就能显示上一次波形，不必等一轮网络往返。
  const [wave, setWave] = useState<WaveCapture | null>(() =>
    LAST && runId && LAST.runId === runId ? LAST.wave : null,
  )
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [cachedCount, setCachedCount] = useState(0)
  const [updatedAt, setUpdatedAt] = useState<number | null>(null)
  /** 当前展示的是否为「保留的非实时波形」 */
  const [stale, setStale] = useState(false)
  /** 保留波形所属轮次（stale 时为 runId，实时时为 null） */
  const [staleRunId, setStaleRunId] = useState<string | null>(null)

  // 缓存：capture_id → WaveCapture（避免同一 id 重复请求）
  const cacheRef = useRef<Map<string, WaveCapture>>(new Map())
  // 在途标记：避免同一 id 并发重复请求
  const inflightRef = useRef<Set<string>>(new Set())
  const aliveRef = useRef(true)

  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
    }
  }, [])

  // 取「最新一次带 capture_id 的样本」。倒序找，避免每 tick 全量扫描。
  const latest = useMemo(() => {
    for (let i = samples.length - 1; i >= 0; i -= 1) {
      const s = samples[i]
      if (s.capture_id) return s
    }
    return null
  }, [samples])

  const captureId = latest?.capture_id ?? null
  const commandedPct = latest?.commanded_pwm_pct ?? null

  useEffect(() => {
    if (!runId) {
      // 连 runId 都没有（未启动 / 已切走）：本轮无从谈起，如实清空。
      setWave(null)
      setError('')
      setLoading(false)
      setStale(false)
      setStaleRunId(null)
      return
    }
    if (!captureId) {
      // 有 runId 但当前没有带 capture_id 的样本（典型：**收工后**样本不再增长，
      // 或重挂载后 samples 还是空的）。此时**保留最近一次成功采集**并置 stale，
      // 界面标注「上一轮 · 非实时」——不再把整张波形图清空（修「收工后全暗」）。
      const kept = LAST && LAST.runId === runId ? LAST : null
      setWave(kept?.wave ?? null)
      setStale(Boolean(kept))
      setStaleRunId(kept ? kept.runId : null)
      setError('')
      setLoading(false)
      return
    }
    const cached = cacheRef.current.get(captureId)
    if (cached) {
      setWave(cached)
      setError('')
      setLoading(false)
      setStale(false)
      setStaleRunId(null)
      // ⚠️ 缓存命中**不更新** updatedAt（2026-10-09 修）：
      // updatedAt 的语义是「最近一次**取到新波形**的时刻」。若命中缓存也刷新它，
      // 那么只要 captureId 不变，age 会被反复重置为 ~0s——「更新于 x.xs 前」
      // 就永远显示 0，反而看不出「采集卡住了」。保持不清，age 才能如实上涨。
      return
    }
    if (inflightRef.current.has(captureId)) return
    inflightRef.current.add(captureId)
    setLoading(true)
    setError('')
    void (async () => {
      try {
        const res = await getCapture(runId, captureId)
        if (!aliveRef.current) return
        cacheRef.current.set(captureId, res)
        setCachedCount(cacheRef.current.size)
        setWave(res)
        setUpdatedAt(Date.now())
        setStale(false)
        setStaleRunId(null)
        // 记录「最近一次成功采集」：供收工后/重挂载后保留展示（只有取到新数据才更新，
        // 所以跨轮不会混淆——换轮时下面的 runId effect 会清掉它）。
        LAST = { runId, captureId, wave: res, commandedPct: latest?.commanded_pwm_pct ?? null }
        // available=false 不是异常，是「如实没采到」；原因放 error 行提示
        setError(res.available ? '' : (res.notes[0] ?? '本次采集未读到波形文件'))
      } catch (e) {
        if (!aliveRef.current) return
        setError((e as Error).message)
        // 请求失败也不清空：优先保留模块级最近一次成功采集（标注非实时），
        // 没有保留物时才置 null（如实空态）。
        const kept = LAST && LAST.runId === runId ? LAST : null
        setWave(kept?.wave ?? null)
        setStale(Boolean(kept))
        setStaleRunId(kept ? kept.runId : null)
      } finally {
        inflightRef.current.delete(captureId)
        if (aliveRef.current) setLoading(false)
      }
    })()
  }, [runId, captureId, latest])

  // 新一轮开始（runId 变为不同值）时清缓存与保留记录，避免上一轮波形残留/冒充。
  // ⚠️ 只在「确实换了轮次」时清：runId 抖动为 null（如短暂卸载）不清，
  //    否则会把刚记下的保留波形误删，收工后又变全暗。
  const prevRunIdRef = useRef<string | null>(runId)
  useEffect(() => {
    const prev = prevRunIdRef.current
    prevRunIdRef.current = runId
    if (!runId || prev === runId) return
    cacheRef.current.clear()
    inflightRef.current.clear()
    setCachedCount(0)
    setWave(null)
    setError('')
    setUpdatedAt(null)
    setStale(false)
    setStaleRunId(null)
    LAST = null
  }, [runId])

  return {
    captureId,
    wave,
    loading,
    error,
    commandedPct,
    cachedCount,
    updatedAt,
    stale,
    staleRunId,
  }
}

export default useWaveforms
