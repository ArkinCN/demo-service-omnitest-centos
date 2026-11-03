/* ===========================================================================
   非致命报错判定 · 终态调度与上报客户端

   职责：整轮结束后（**每轮仅一次**）取一份「执行日志 + 阶段终态」快照，
   调用纯判定模块 `nonFatalJudge.ts`，把逐条判定结果上报后端落盘
   （`POST /api/automation-judge` → `logs/error_judge.log`），供用户跑一轮后
   打开后台文件逐条核对。**本阶段界面零变化**：只上报，不改任何渲染。

   触发纪律（2026-10-10 用户确认）：
     · **运行中不判定、不隐藏**——只有整轮终态（completed/failed/stopped）才动作；
     · 延迟约 1.5s 再取快照：编排器在 END 事件之后还会紧跟着 emit 尾部报错
       （典型：「报告未生成：…」），不等它入列就取快照会漏条；
     · 每轮按 runId 去重，重复触发（END 与后续事件都会走 _syncAutomation）只上报一次；
     · 快照时刻二次校验：仍是同一 runId、仍处终态、日志非空，否则放弃；
     · fire-and-forget：上报失败**只 console.error 带上下文**（不吞、不裸 catch），
       绝不打断流程、绝不影响界面。

   ⚠️ 为什么用动态 import 由 store 侧调用：store 是底层模块，直接静态 import
   本文件会把 features/automation 拖进 store 的依赖环，沿用项目既有约定
   （`startAutomation` 里也是函数内 `await import(...)`）。
   =========================================================================== */
import { judgeNonFatal, type JudgeReport } from './nonFatalJudge'
import type { AutomationRunStatus, AutomationStage } from './automationOrchestrator'
import type { AutomationLogEntry } from '../../state/useAppStore'

/** 已上报过的 runId 集合（模块级）：保证每轮仅上报一次 */
const reportedRunIds = new Set<string>()

/** 延迟取快照的毫秒数：留足尾部报错（如「报告未生成」）入列的时间 */
const SNAPSHOT_DELAY_MS = 1500

/** 上报上限保护：与后端契约一致（entries ≤ 300、message ≤ 5000） */
const MAX_ENTRIES = 300
const MAX_MESSAGE = 5000
const MAX_REASON = 500

/** 后端统一信封（与 flow-run/api.ts 同形状） */
interface ApiEnvelope<T> {
  success: boolean
  code: number
  message: string
  data: T
}

/** 判定清单请求体（snake_case，字段与后端契约冻结） */
interface JudgeUploadBody {
  run_id: string
  scene_id: string
  terminal_status: string
  uploaded_at: string
  counts: { candidates: number; hide: number; keep: number }
  entries: {
    seq: number
    at_ms: number
    level: string
    stage_id: string
    stage_name: string | null
    stage_final: string | null
    verdict: string
    reason: string
    message: string
  }[]
}

/** 本地时间 ISO 字符串（带时区偏移，便于与后端日志对照） */
function localIso(ms: number): string {
  const d = new Date(ms)
  const pad = (n: number, w = 2) => String(Math.abs(n)).padStart(w, '0')
  const off = -d.getTimezoneOffset()
  const sign = off >= 0 ? '+' : '-'
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` +
    `${sign}${pad(Math.floor(Math.abs(off) / 60))}:${pad(Math.abs(off) % 60)}`
  )
}

/** 截断保护：超长以「…（已截断）」结尾，如实标注而非静默丢弃 */
function clip(s: string, max: number): string {
  if (s.length <= max) return s
  return `${s.slice(0, max)}\n…（原文超长，已截断，完整内容见既有后端日志）`
}

/**
 * 组装请求体（单独导出便于离线验证/单测断言字段）。
 */
export function buildJudgeBody(
  report: JudgeReport,
  opts: { runId: string; sceneId: string; terminalStatus: string; now: number },
): JudgeUploadBody {
  const entries = report.entries.slice(0, MAX_ENTRIES).map((e) => ({
    seq: e.seq,
    at_ms: e.at,
    level: e.level,
    stage_id: e.stageId,
    stage_name: e.stageName,
    stage_final: e.stageFinal,
    verdict: e.verdict,
    reason: clip(e.reason, MAX_REASON),
    message: clip(e.message, MAX_MESSAGE),
  }))
  return {
    run_id: opts.runId,
    scene_id: opts.sceneId,
    terminal_status: opts.terminalStatus,
    uploaded_at: localIso(opts.now),
    counts: { candidates: report.candidates, hide: report.hide, keep: report.keep },
    entries,
  }
}

/**
 * 调度一次终态判定上报（安全、幂等、fire-and-forget）。
 *
 * 由 `useAppStore._syncAutomation` 在终态分支调用；同一 runId 重复调用只会安排一次。
 * 本函数**不返回 Promise**、不抛异常——调用方（store）不需要也不应该等它。
 */
export function scheduleJudgeUpload(args: {
  runId: string
  sceneId: string
  terminalStatus: string
  /** 取快照：此刻重新读 store（日志/阶段/终态可能仍在变） */
  snapshot: () => {
    logs: AutomationLogEntry[]
    stages: Pick<AutomationStage, 'id' | 'name' | 'status'>[]
    runStatus: string
    runId: string | null
  }
}): void {
  const { runId, sceneId, terminalStatus, snapshot } = args
  if (reportedRunIds.has(runId)) return
  reportedRunIds.add(runId) // 先占位去重；失败也记为已尝试，避免重复轰炸后端

  window.setTimeout(() => {
    void (async () => {
      try {
        const snap = snapshot()
        // 快照时刻二次校验：仍同一轮次、仍处终态、日志非空
        if (snap.runId !== runId) return
        const terminal = snap.runStatus === 'completed' || snap.runStatus === 'failed' || snap.runStatus === 'stopped'
        if (!terminal) return
        if (!snap.logs.length) return

        // 无候选报错时同样上报（空清单 + 汇总行）：用户在后台能看到「本轮无候选」，
        // 这本身就是「判定链路在正常跑」的证据，比什么都不写更可核。
        const report = judgeNonFatal(snap.logs, snap.stages, snap.runStatus as AutomationRunStatus, runId)
        const body = buildJudgeBody(report, {
          runId,
          sceneId,
          terminalStatus,
          now: Date.now(),
        })

        const resp = await fetch('/api/automation-judge', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        const json = (await resp.json()) as ApiEnvelope<{ file?: string }>
        if (!resp.ok || !json.success) {
          // 失败如实记控制台（带轮次与统计上下文），不影响界面与流程
          console.error(
            `[automation-judge] 判定清单上报失败 run=${runId} HTTP ${resp.status}：${json?.message ?? '未知'}`,
          )
          return
        }
        console.info(
          `[automation-judge] 判定清单已落盘 run=${runId} 候选 ${report.candidates}（可隐藏 ${report.hide} / 保留 ${report.keep}）→ ${json.data?.file ?? 'logs/error_judge.log'}`,
        )
      } catch (e) {
        // 不裸 catch：把失败原因与轮次一并打出来（网络异常/后端未启动等）
        console.error(`[automation-judge] 判定清单上报异常 run=${runId}：`, e)
      }
    })()
  }, SNAPSHOT_DELAY_MS)
}
