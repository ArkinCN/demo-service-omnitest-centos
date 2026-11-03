/**
 * 前端工具执行器注册表（2026-10-10，权限切换修复）。
 *
 * 背景：写类工具（如 WriteReportHeader）由**前端**在人工点「确认执行」之后真正执行，
 * 结果再经 /api/agent/confirm 回传后端。但 agent-chat 是通用组件，不该硬编码
 * 具体业务（写报告表头属于 app 侧）。故这里提供一张**注册表**：app 侧把自己的
 * 执行器注册进来，AgentChat 侧的确认流程只按工具名查表调用。
 *
 * 与 `features/index.tsx` 里 knowledge/register 的「副作用导入装配」同一手法。
 */
export interface ToolExecResult {
  /** 是否执行成功（写成功 = true；失败/落库失败 = false） */
  ok: boolean
  /** 给人与给模型看的结果说明（成功/失败都要如实写，不得谎报完成） */
  summary: string
  /** 可选结构化数据（供后续扩展，当前回传后端但模型只用 summary） */
  data?: unknown
}

export type ToolExecutor = (args: Record<string, unknown>) => Promise<ToolExecResult>

const REGISTRY = new Map<string, ToolExecutor>()

/** 注册一个前端工具执行器（按工具名）。重复注册以最后一次为准。 */
export function registerToolExecutor(name: string, fn: ToolExecutor): void {
  REGISTRY.set(name, fn)
}

/** 取执行器；未注册返回 undefined（调用方据此如实报「无执行器，未执行」）。 */
export function getToolExecutor(name: string): ToolExecutor | undefined {
  return REGISTRY.get(name)
}
