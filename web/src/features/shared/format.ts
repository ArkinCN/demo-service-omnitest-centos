/* ===========================================================================
   展示格式化（2026-10-08 新增，跨流程共用）

   为什么抽出来：`flow-run/panel.tsx` 与自动化全屏运行台都要把实测量读数
   显示给人看，两处若各写一份 `toPrecision(4)`，将来改精度口径就会出现
   「同一个量在两个页面显示得不一样」。**单一出处**比就近方便重要。

   ⚠️ 数据纪律（与 flow-run 原有实现逐字一致）：
     · 实测量一律走 4 位有效数字并去尾随零，不把二进制浮点尾数抛给用户；
     · 缺测（null / undefined / NaN）**显示「未采集」而不是 0**——
       补 0 会把「没测到」说成「测到零」。
   =========================================================================== */

/** 4 位有效数字并去尾随零：`0.0017566666666666678` → `0.001757`，`4.7596` → `4.76` */
export function fmtMeasure(v: number): string {
  return String(Number(v.toPrecision(4)))
}

/**
 * 实测量读数的格式化入口：**先判缺测，再格式化**。
 *
 * 为什么要单独包一层：调用点遍布多处（趋势图 tooltip、判据列表、结果页），
 * 漏判一次 null 就会把 `null` 渲染成字面量 "null" 或 NaN。
 */
export function fmtMeasureOrMissing(v: number | null | undefined, missing = '未采集'): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return missing
  return fmtMeasure(v)
}

/** 时长（ms → 人读的 m s / s）。取不到（null）显示「—」，不显示 0s。 */
export function fmtElapsed(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return '—'
  const s = Math.max(0, Math.round(ms / 1000))
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
}

/** 百分比：`done/total` → `38%`。分母为 0 时显示「—」，不显示 0%（那等于说「一步没走」）。 */
export function fmtPct(done: number, total: number): string {
  if (!total) return '—'
  return `${Math.round((done / total) * 100)}%`
}

/** 时钟（ms epoch → `HH:MM:SS.mmm`），日志流的时间戳 */
export function fmtClock(at: number): string {
  const d = new Date(at)
  const p = (n: number, w = 2) => String(n).padStart(w, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`
}