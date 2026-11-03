import type { FlowId } from '../data/types'

// 2026-10-29 收口完成：这里原有的 `useStageText()`（`(中文, English)` 双参垫片）已删除，
// 三个流程面板的 31 处调用全部改为 `useT()` 返回的 uiT 单参调用。
// 界面文案现在只有一条通路：`uiT(中文原文)` + `i18n/catalog.ts`。

/**
 * 五阶段展示文案：**只存中文原文**，英文一律由 `catalog.ts` 提供（经 `uiT` 翻译）。
 *
 * 2026-10-29 前这里是 `[中文, English]` 元组，同一句话要在代码和词典两处维护，
 * 容易出现「同一中文两套英文」，已改为单值。
 */
export const STAGE_PRESENTATION: Readonly<Record<FlowId, { index: string; title: string; description: string }>> = {
  init: { index: '01', title: '设备属性', description: '核对被测设备的固有属性、驱动配置和台架条件。' },
  req: { index: '02', title: '测试目标', description: '确定测什么、测多少次，以及怎样判定通过。' },
  run: { index: '03', title: '执行检测', description: '检查运行条件与安全放行，采集数据并按要求判定。' },
  tune: { index: '04', title: '调参复测', description: '从未达标项核对调整建议，采纳后返回检测验证。' },
  report: { index: '05', title: '报告交付', description: '核对报告信息与模板，汇集测试结果及其来源。' },
}
