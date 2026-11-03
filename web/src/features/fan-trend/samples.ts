/* ===========================================================================
   样本归一的**唯一实现**（2026-10-09）。

   为什么需要它：同一轮样本有三个消费点——/run 的 `useFanTrend` 轮询、自动化运行台
   的 `runAndCollect` 采集循环、`AUTOMATION_LIVE` 写 store——若各写一份合并逻辑，
   迟早漂移（本轮踩过：运行台那份没有去重，图上同一段斜坡画了好几遍）。

   归一的两条口径：
     ① **按 sequence 去重**：`sequence` 是后端权威序号（real 路径下取自 events.jsonl
        事件序号；sim 路径下是自增计数器）。同一 sequence 只保留第一次出现的样本。
     ② **按 t_s 排序**：保持时间轴单调，ECharts 的折线才不会来回折返。
        `t_s` 为 null 的样本按 0 参与排序（缺测不丢点，只是排在最前）。

   数据纪律：去重只丢弃「序号已存在」的重复回带，**不改任何测量值**、
   不补 0、不插值、不重算 t_s。
   =========================================================================== */
import type { FanSample } from './api'

/**
 * 把 `incoming` 合并进 `prev`：按 `sequence` 去重 + 按 `t_s` 升序。
 *
 * @param prev     已累计的样本（会被复制，不原地修改）
 * @param incoming 本批新到的样本（可含与 prev 重复的 sequence）
 * @returns 去重并排好序的新数组
 */
export function mergeSamples(prev: FanSample[], incoming: FanSample[]): FanSample[] {
  if (incoming.length === 0) return prev
  const seen = new Set(prev.map((s) => s.sequence))
  const merged = [...prev]
  for (const s of incoming) {
    if (seen.has(s.sequence)) continue
    seen.add(s.sequence)
    merged.push(s)
  }
  merged.sort((a, b) => (a.t_s ?? 0) - (b.t_s ?? 0))
  return merged
}

export default mergeSamples
