/* ===========================================================================
   台架通道映射常量。

   口径来源：涵道逆风台架 SK-20251218QPBB 的实测接线，记录在
   [源] fortior-test-bench/SKILL.md 第 42 至 51 行。
   与《业务逻辑说明 · 六个流程 v1.0》第 3.2 节给的「通道一至四依次接
   FG1 / FG2 / PWM1 / PWM2」不一致，两套口径打架，本轮按实测这一套落，
   并在界面上一律带「待客户确认」标记，不许默默选一套当定论。
   =========================================================================== */
import type { CanvasEdgeKind } from './types'

export interface BenchChannel {
  /** 示波器通道号 */
  channel: 'CH1' | 'CH2' | 'CH3' | 'CH4'
  /** 台架信号名 */
  signal: string
  note: string
}

/** 信号名 → 示波器通道。台架实测，待客户确认。 */
export const BENCH_CHANNEL_MAP: Record<string, BenchChannel> = {
  PWM1: { channel: 'CH4', signal: 'PWM1', note: '驱动输入 1 路' },
  FG1: { channel: 'CH2', signal: 'FG1', note: '转速反馈 1 路，频率为 FG2 的两倍（极对数 2）' },
  FG2: { channel: 'CH3', signal: 'FG2', note: '转速反馈 2 路' },
}

/** 这套映射尚未经客户书面确认，凡在界面上展示通道名的地方都要挂这句 */
export const BENCH_CHANNEL_PENDING = '待客户确认'

/** 画板物理连接边上的通道标注文字 */
export function channelLabel(signal: string): string | undefined {
  return BENCH_CHANNEL_MAP[signal]?.channel
}

/** 边的线型口径：物理连接实线、数据流虚线，供画板与图例共用 */
export const CANVAS_EDGE_DASH: Record<CanvasEdgeKind, string | undefined> = {
  physical: undefined,
  data: '6 4',
}
