import { useT } from '../../i18n'
/* ===========================================================================
   风扇实验演示页 /fan-demo。

   独立路由页，不碰现有 FlowScreen/五流程。数据与控制逻辑复用 useFanTrend
   （与 flow-run 的 FanTrendPanel 同一份实现）：
     - 「开始/停止」先弹红线确认卡，人点「确认执行」后才真正调后端
     - 每秒轮询增量点（after_sequence 游标 + 串行锁）
     - 状态栏如实显示：模拟/真实、运行状态、是否延期
   =========================================================================== */
import { FanTrendChart } from './FanTrendChart'
import { useFanTrend } from './useFanTrend'

export function FanDemoPage() {
  const uiT = useT()

  const { plan, samples, phase, error, requestStart, requestStop } = useFanTrend()
  const busy = phase === 'running' || phase === 'stopping'

  return (
    <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <h2 style={{ margin: 0, fontSize: 18 }}>{uiT("风扇趋势实验")}</h2>
        <span style={{ fontSize: 13, color: '#888' }}>
          {plan ? (plan.simulation ? uiT('模拟数据（simulation=true）') : uiT('真实台架数据')) : uiT('未启动')}
        </span>
        <span style={{ fontSize: 13, color: '#888' }}>{uiT("状态：")}{phase}</span>
      </div>

      <div style={{ display: 'flex', gap: 12 }}>
        <button
          type="button"
          onClick={requestStart}
          disabled={busy}
          style={{ padding: '8px 16px', cursor: 'pointer' }}
        >
          {uiT("开始测试")}</button>
        <button
          type="button"
          onClick={requestStop}
          disabled={phase !== 'running'}
          style={{ padding: '8px 16px', cursor: 'pointer' }}
        >
          {uiT("停止")}</button>
      </div>

      {error && <div style={{ color: '#A6353A', fontSize: 13 }}>{uiT("错误：")}{uiT(error)}</div>}

      {plan && (
        <div style={{ fontSize: 13, color: '#888' }}>
          {uiT("计划时长 ")}{plan.planned_duration_s}s
          {plan.overrun ? uiT('（已延期）') : ''}
          {plan.actual_duration_s != null ? ` ${uiT('· 实际 {v1}s', { v1: plan.actual_duration_s })}` : ''}
        </div>
      )}

      {plan ? (
        <FanTrendChart plan={plan} samples={samples} height={420} />
      ) : (
        <div style={{ fontSize: 13, color: '#999', height: 420, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          {uiT("暂无数据：点击「开始测试」后曲线将随时间动态刷新")}</div>
      )}
    </div>
  )
}

export default FanDemoPage
