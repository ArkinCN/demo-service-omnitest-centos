import type { CanvasNodeType, CardId } from './types'

/** 卡片库元数据（规格 7.2）。分四类，卡名与代码标识在此一处定义。 */
export const CARD_LIB: Record<
  CardId,
  { title: string; group: '产品与资产' | '设备与连接' | '过程与数据' | '知识与记录' }
> = {
  'product-view': { title: '产品示意图', group: '产品与资产' },
  schematic: { title: '原理图', group: '产品与资产' },
  'project-tree': { title: '工程与文件树', group: '产品与资产' },
  tools: { title: '工具清单与状态', group: '设备与连接' },
  'bench-live': { title: '台架实况', group: '设备与连接' },
  'remote-device': { title: '单机设备会话', group: '设备与连接' },
  interlock: { title: '安全联锁状态盘', group: '设备与连接' },
  workflow: { title: '工作流画布', group: '过程与数据' },
  'wf-lib': { title: '工作流库', group: '过程与数据' },
  timeseries: { title: '时序曲线', group: '过程与数据' },
  progress: { title: '执行进度与日志', group: '过程与数据' },
  pipeline: { title: '转化流水线', group: '过程与数据' },
  candidates: { title: '候选队列', group: '过程与数据' },
  'param-changes': { title: '参数变更', group: '过程与数据' },
  verdict: { title: '判定卡', group: '过程与数据' },
  evidence: { title: '知识库依据', group: '知识与记录' },
  history: { title: '历史对比', group: '知识与记录' },
  experience: { title: '经验库', group: '知识与记录' },
  artifacts: { title: '产物留档', group: '知识与记录' },
  'report-preview': { title: '报告预览', group: '知识与记录' },
  'template-fields': { title: '模板字段', group: '知识与记录' },
}

export const CARD_LIST = Object.entries(CARD_LIB).map(([id, v]) => ({
  id: id as CardId,
  ...v,
}))

/* ---------------------------------------------------------- 卡片 → 画板节点 */

/**
 * 卡片库标识到画板节点类型的映射，让一张卡可以直接当画板节点用。
 * 表里没有的卡不上画板，只在网格视图出现。真正的节点渲染由 W3 在
 * src/features/canvas/ 下用 registerCanvasNode() 注册。
 */
export const CARD_CANVAS_NODE: Partial<Record<CardId, CanvasNodeType>> = {
  'product-view': 'motor',
  schematic: 'schematic',
  'bench-live': 'bench',
  'remote-device': 'device-mcp',
  interlock: 'interlock',
  workflow: 'workflow',
  timeseries: 'curve',
  verdict: 'verdict',
  evidence: 'knowledge',
  experience: 'knowledge',
  'project-tree': 'knowledge',
}
