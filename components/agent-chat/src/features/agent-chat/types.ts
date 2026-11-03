// 智能体对话组件 —— 领域类型定义
// 所有面向后端的事件类型见 ./api.ts

/** 权限档位：约束智能体可以执行的动作范围 */
export type PermissionLevel = 'readonly' | 'params' | 'hardware';

export const PERMISSION_OPTIONS: { value: PermissionLevel; label: string; hint: string }[] = [
  { value: 'readonly', label: '只读', hint: '仅读取工程文件与测量数据，不做任何写入' },
  { value: 'params', label: '可改参数', hint: '允许修改标定参数与配置项，不驱动硬件' },
  { value: 'hardware', label: '可控硬件', hint: '允许启停电机、切换负载、控制仪器' },
];

export const MODEL_OPTIONS: { value: string; label: string }[] = [
  { value: 'deepseek-v4-pro', label: 'deepseek-v4-pro' },
  { value: 'deepseek-v4', label: 'deepseek-v4' },
  { value: 'claude-opus-5', label: 'claude-opus-5' },
  { value: 'qwen3-max', label: 'qwen3-max' },
];

/** 一次工具调用的完整记录（调用 + 结果） */
export interface ToolCall {
  id: string;
  /** 工具名，如 rigol_measure */
  name: string;
  /** 工具中文显示名 */
  title?: string;
  /** 调用参数（原始 JSON） */
  args: Record<string, unknown>;
  /** 参数摘要，一行内讲清这次调了什么 */
  argsSummary: string;
  /** pending_confirm：会改变被测对象状态或落盘的动作，等人点确认 */
  status: 'pending_confirm' | 'running' | 'ok' | 'error';
  /** 是否为改动类动作（写参数、控硬件）。改动类一律需人工确认。 */
  mutating?: boolean;
  /** 确认人，确认后回填 */
  confirmedBy?: string;
  /** 耗时，毫秒 */
  durationMs?: number;
  /** 结果摘要，一行内讲清拿到了什么 */
  resultSummary?: string;
  /** 结果原始 JSON */
  result?: unknown;
}

/** 判定卡片：一条判据的结论 */
export interface Verdict {
  id: string;
  /** 判定项名称，如 启动电流峰值 */
  title: string;
  pass: boolean;
  /** 判据表达式，如 I_peak <= 1.5 * I_rated */
  expression: string;
  /** 实测值列表 */
  measurements: { label: string; value: string; unit?: string }[];
  /** 一句话结论 */
  conclusion: string;
  /** 关联的依据条目 id 列表 */
  evidenceIds: string[];
}

/** 依据条目的三类来[源] */
export type EvidenceKind = 'procedure' | 'case' | 'document';

export const EVIDENCE_KIND_LABEL: Record<EvidenceKind, string> = {
  procedure: '规程条目',
  case: '相似案例',
  document: '资料段落',
};

export interface EvidenceItem {
  id: string;
  kind: EvidenceKind;
  title: string;
  /** 正文摘录 */
  excerpt: string;
  /** 来源文件或规程名称（给全名，便于独立定位） */
  source: string;
  /** 页码或条目号 */
  locator: string;
  /** 查看原文的目标地址，缺省则按钮禁用 */
  href?: string;
}

/** 消息流里的一项 */
export type ChatItem =
  | { kind: 'message'; id: string; role: 'user' | 'assistant'; text: string; streaming?: boolean }
  | { kind: 'tool'; id: string; call: ToolCall }
  | { kind: 'verdict'; id: string; verdict: Verdict };

/** 沉淀为经验的表单数据 */
export interface ExperienceDraft {
  title: string;
  phenomenon: string;
  cause: string;
  action: string;
  result: string;
  tags: string[];
}
