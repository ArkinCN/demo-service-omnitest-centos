/* ===========================================================================
   风扇实时趋势卡片（/run 人测页首卡「时序曲线」的**容器**）。

   替换原 WaveformPanel（场景包历史波形回放）：改为接后端 /api/fan-tests
   实时轮询的风扇趋势图。签名与其它卡片一致 `({ full })`，布局自适应卡片槽高度。

   ⚠️ 本组件只做「容器」：数据获取（useFanTrend）与副作用（启停台架、终态写回判据）
   留在这里；**展示部分全部交给 `FanTrendView`**（2026-10-09 抽出，与自动化运行台
   共用同一份 UI，避免两套实现漂移）。

   为什么副作用不能搬进 FanTrendView：它订阅 runPhase，在本组件里进入 running 边沿时
   会**真的启动台架**、终态时 `settleRun()` **写回判据实测量**。运行台是编排器在驱动
   同一台设备，若把这份副作用带过去，会抢单设备锁（409）并污染判据。

   ⚠️ 交互口径（2026-10-06）：本卡**不再自带开始/停止按钮**。
   启动由 flow-run 左栏底部「确认参数并启动测试」按钮统一承担（那里已过红线
   确认卡）；本卡订阅 store 的 runPhase，检测到进入 running 时自动开始采集，
   进入 stopped/estopped 时自动停止。这样启动只有一个入口，图表卡直接出数据。

   数据纪律：真实数据只来自接口；simulation=true 时显式标注「模拟数据」。
   =========================================================================== */
import { useEffect, useRef } from 'react'
import { useFanTrend } from './useFanTrend'
import { FanTrendView } from './FanTrendView'
import type { FanTestGate } from './api'
import { useAppStore } from '../../state/useAppStore'

export function FanTrendPanel({ full }: { full?: boolean }) {
  const { plan, samples, phase, error, beginNow, stopNow, runId } = useFanTrend()
  // 订阅运行状态：左下角按钮经红线确认后调 beginRun() → runPhase='running'
  const runPhase = useAppStore((s) => s.runPhase)
  // 闸门快照来源：前端逐条确认闸门（gateAcked/gateTotal），全绿即三项视为 true
  const gateAcked = useAppStore((s) => s.gateAcked)
  const gateTotal = useAppStore((s) => s.gateTotal)
  const settleRun = useAppStore((s) => s.settleRun)
  const prevPhaseRef = useRef(runPhase)
  // 已收口标记：避免 phase 抖动（done 重渲多次）时重复 settleRun
  const settledRef = useRef(false)
  // 拿最新 samples：settleRun 由 effect 触发，闭包里的 samples 可能是旧值
  const samplesRef = useRef(samples)
  samplesRef.current = samples

  useEffect(() => {
    const prev = prevPhaseRef.current
    prevPhaseRef.current = runPhase
    // 边沿检测：非 running → running 才启动（避免重复触发）
    if (runPhase === 'running' && prev !== 'running') {
      settledRef.current = false
      const green = gateTotal > 0 && gateAcked.length >= gateTotal
      const gate: FanTestGate = {
        interlocks_ok: green,
        precheck_ok: green,
        master_switch_on: green,
      }
      beginNow(gate)
    }
    // 边沿检测：running → stopped/estopped 才停止
    if ((runPhase === 'stopped' || runPhase === 'estopped') && prev === 'running') {
      stopNow()
    }
  }, [runPhase, gateAcked, gateTotal, beginNow, stopNow])

  /*
   * 收口：风扇实验到达终态时，先把本轮台架实测样本交给 store 聚合成判据实测量，
   * 再让 runPhase 落回 done —— 顺序不可颠倒（见 useAppStore.settleRun 说明：
   * 判定 effect 监听 running→非running 边沿，先置 done 会用还没数据的状态求值）。
   *
   * 为什么在这里做：唯一知道"实验真的跑完了"的地方是 useFanTrend 的 phase
   * （后端 terminal 字段驱动），而它只在本组件内部。beginRun 只能按固定时长
   * 估推，估不准长任务（实验约 80 秒）。
   */
  useEffect(() => {
    if (settledRef.current) return
    if (runPhase !== 'running') return
    if (phase !== 'done' && phase !== 'error') return
    settledRef.current = true
    // 失败（phase==='error'）也照常提交已采到的样本：能判的判、缺的如实未采集，
    // 不因一次失败把本轮已有数据全丢掉。
    settleRun(samplesRef.current, phase === 'error')
  }, [phase, runPhase, settleRun])

  // 展示层（工具行/读数行/趋势·波形视图/回到全程）全在 FanTrendView 里，两处共用。
  return (
    <FanTrendView
      plan={plan}
      samples={samples}
      phaseLabel={phase}
      error={error}
      runId={runId}
      full={full}
    />
  )
}

export default FanTrendPanel
