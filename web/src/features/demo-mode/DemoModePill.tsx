/* ===========================================================================
   顶栏的数据源标识器。

   【为什么必须在全局持续可见】
   演示数据和真机数据表结构完全相同、界面完全一样，唯一区别是背后连哪个 schema。
   如果界面上没有持续可见的标记，演示时说过的话、截的图事后无法判断属于哪套数据。
   这是数据纪律问题，不是装饰 —— 与「缺测不补零、模拟必须标注 simulation」同一条线。

   【为什么接口失败就不渲染】
   拿不到状态说明后端或网络有问题。这时显示「真机数据」是一个可能为假的断言；
   显示「未知」又容易被忽略。按本项目的习惯：拿不到就不显示，让缺失本身成为信号。

   【为什么切换要二次确认】
   切换会改变所有人看到的业务数据。演示结束后忘记切回去，下一次真机采集的结果
   会和演示数据混在一起看 —— 这个代价远高于一次 confirm 的打扰。
   =========================================================================== */
import { useCallback, useEffect, useState } from 'react'
import { Database, FlaskConical } from 'lucide-react'
import { Tooltip, cn } from '../../components/ui'
import { activateMode, fetchDemoStatus, type DataMode, type DemoStatus } from './api'

/** 数据集内部名 → 界面短标签。认不出的名字原样显示，不要吞掉。 */
const DATASET_LABEL: Record<string, string> = {
  normal: '正常',
  fault: '故障',
  stress: '极限',
}

export function DemoModePill() {
  const [status, setStatus] = useState<DemoStatus | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    void fetchDemoStatus()
      .then((s) => {
        if (alive) setStatus(s)
      })
      .catch(() => {
        // 静默降级：后端没起来 / 未登录都会走到这里，不该在顶栏弹错误
      })
    return () => {
      alive = false
    }
  }, [])

  const toggle = useCallback(async () => {
    if (!status || busy || !status.demo_available) return
    const next: DataMode = status.mode === 'demo' ? 'live' : 'demo'
    const ok = window.confirm(
      next === 'demo'
        ? '切换到演示数据？\n\n界面上所有测试记录将变成演示数据集（非真机采集）。演示结束后记得切回真机。'
        : '切回真机数据？\n\n界面将恢复显示真实采集记录。',
    )
    if (!ok) return
    setBusy(true)
    try {
      setStatus(await activateMode(next))
    } catch (err) {
      window.alert(`切换失败：${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setBusy(false)
    }
  }, [status, busy])

  // 拿不到状态、或当前部署不支持演示模式时，不占位
  if (!status || !status.demo_available) return null

  const isDemo = status.mode === 'demo'
  const Icon = isDemo ? FlaskConical : Database

  // 认不出的数据集名原样显示：宁可难看，也不要静默隐藏「当前是哪套数据」
  const datasetLabel = DATASET_LABEL[status.dataset] ?? status.dataset
  const label = isDemo ? (datasetLabel ? `演示 · ${datasetLabel}` : '演示数据') : '真机数据'
  const hint = isDemo
    ? `当前显示为演示数据集${datasetLabel ? `（${datasetLabel}场景）` : ''}，非真机采集结果。点击切回真机。`
    : `当前显示为真机采集数据。点击切换到演示数据集${datasetLabel ? `（${datasetLabel}场景）` : ''}。`

  return (
    <Tooltip side="bottom" content={hint}>
      <button
        type="button"
        onClick={() => void toggle()}
        disabled={busy}
        aria-label={hint}
        className={cn(
          'flex h-[30px] items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 transition-colors',
          'min-[1536px]:h-[38px] min-[1536px]:px-3',
          isDemo
            ? 'border-warn/50 bg-warn/10 text-warn hover:bg-warn/15'
            : 'border-line bg-white text-t2 hover:bg-p50',
          busy && 'cursor-wait opacity-60',
        )}
      >
        <Icon size={14} strokeWidth={1.75} className="min-[1536px]:h-[17px] min-[1536px]:w-[17px]" />
        <span className="text-[12px] min-[1536px]:text-[15px]">{label}</span>
      </button>
    </Tooltip>
  )
}
