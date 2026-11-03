import { useEffect, useRef, useState } from 'react'
import { useAppStore } from '../../state/useAppStore'

/* ===========================================================================
   自动化「退回」提示 hook（2026-10-10 新增）

   用途：把编排器**真实的调优回环**翻译成一个短暂的 UI 信号，供流程条播放
   「调优运行 → 启动测试」的退回动效。

   真实事件来源（零逻辑改动，只读 store）：
     编排器 `automationOrchestrator.ts` 的调优循环 —— `run` 判定有未达标 →
     进 `tune` 自动采纳 → **`runStage(byId('run'))` 回流程3 重跑**。
     每次回跑都会调 `setCurrent('run')`，于是 store 的 `automationCurrentStageId`
     从 `'tune'` 跳回 `'run'`。本 hook 只捕获这个**边沿**，不推断、不预判。

   纪律：
     · 只在「前值 tune → 新值 run」这一种跳变时置位 `returning`，其余变化（首次进入、
       正常前进 run→tune、回到 idle）一律不触发，避免误报「退回」。
     · 置位后 `holdMs` 毫秒复位（默认 2200ms，够看清一次反向流动）。
     · 定时器与 ref 全量清理；自动化空闲时零副作用；StrictMode 双调安全。
   =========================================================================== */

/** 退回信号保持时长（ms）——一次「反向流动」看得清即可 */
export const STAGE_RETURN_HOLD_MS = 2200

export function useStageReturnCue(holdMs: number = STAGE_RETURN_HOLD_MS): boolean {
  const stageId = useAppStore((s) => s.automationCurrentStageId)
  const [returning, setReturning] = useState(false)
  const prevRef = useRef<string | null>(null)
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    const prev = prevRef.current
    prevRef.current = stageId
    // 只认「调优运行 → 启动测试」这一条回退边沿
    if (prev === 'tune' && stageId === 'run') {
      setReturning(true)
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
      timerRef.current = window.setTimeout(() => {
        setReturning(false)
        timerRef.current = null
      }, holdMs)
    }
  }, [stageId, holdMs])

  // 卸载清定时器，避免卸载后 setState
  useEffect(
    () => () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    },
    [],
  )

  return returning
}
