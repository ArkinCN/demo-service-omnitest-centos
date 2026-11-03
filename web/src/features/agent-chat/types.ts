// 智能体对话组件 —— 领域类型定义
// 所有面向后端的事件类型见 ./api.ts

/** 权限档位：约束智能体可以执行的动作范围 */
export type PermissionLevel = 'readonly' | 'params' | 'hardware';

export const PERMISSION_OPTIONS: { value: PermissionLevel; label: string; hint: string }[] = [
  { value: 'readonly', label: '只读', hint: '仅读取工程文件与测量数据，不做任何写入' },
  { value: 'params', label: '可改参数', hint: '允许修改标定参数与配置项，不驱动硬件' },
  { value: 'hardware', label: '可控硬件', hint: '允许启停电机、切换负载、控制仪器' },
];

/**
 * AI 助手可选模型（2026-10-14 改为**动态来自后端**）。
 *
 * 此前这里是**硬编码**的三项字面量，与后端 `model_pricing` 表脱钩：后台新增/
 * 停用模型后，前端下拉不会跟着变，还会出现「点得到但一用就报模型不可用」。
 *
 * 现在改为：运行时拉 `GET /api/agent/models`（后端按 `chat_enabled=True &&
 * is_active=True` + 模型级 permissions 过滤、`sort_order` 排序后返回），
 * 后台增删模型前端自动同步。见 `features/agent-chat/models.ts` 的 `fetchModels()`。
 */
export interface ModelOption {
  /** 上送 /api/agent/stream 的 `model` 字面量，即 model_pricing.model_id */
  value: string;
  /** 下拉显示名（model_pricing.display_name，空则回退用 id） */
  label: string;
  /** 是否支持视觉输入（发图时前端据此判断） */
  vision?: boolean;
  /** 是否标记为深度思考模型 */
  reasoning?: boolean;
  /** 厂商显示名，用于分组（缺省为空表示不分组） */
  providerName?: string;
  /** 选择面板 hover 卡片副标题 */
  description?: string;
}

/**
 * 拉取失败或后端暂无可用模型时的**兜底候选项**（单机版开箱即用的主模型）。
 *
 * 后端 `local_admin_service._SEEDED_MODELS[0]` 即 `deepseek-v4.1-flash`
 * （2026-10-15 与 .env 的主模型同名对齐，此前叫 `deepseek-v4-pro`），
 * `chat_enabled=True` 且 `sort_order` 最小，是后端定义的默认主模型。
 * 保留它只为「后端 momentarily 不可达时下拉不空」，正常路径下会被真实列表覆盖。
 */
export const FALLBACK_MODEL_OPTIONS: ModelOption[] = [
  { value: 'deepseek-v4.1-flash', label: 'DeepSeek V4.1 Flash' },
];

/** 后端不可达时的默认选中模型（= 兜底列表首项）。 */
export const DEFAULT_MODEL = FALLBACK_MODEL_OPTIONS[0].value;

/** 一次工具调用的完整记录（调用 + 结果） */
export interface ToolCall {
  /** Local scripted UI summaries, distinct from live backend free text. */
  uiAuthored?: boolean;
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
  /** 查看原文的目标地址；本地知识库没有可点的 PDF，缺省时改走 docId 跳知识库页 */
  href?: string;
  /**
   * 知识库资料的 doc_id（如 fu6832-datasheet）。
   * 本地知识库的原文 PDF 未随交付包提供，没有可点的 href，但条目在知识库页里
   * 是有的——据此跳到 /knowledge 并选中该条目，比显示「原文未接入」有用得多
   * （那句文案会被误读成「原文没检索到」，实际摘录就在卡片正文里）。
   */
  docId?: string;
}

/** 消息流里的一项 */
export type ChatItem =
  | { kind: 'message'; id: string; role: 'user' | 'assistant'; text: string; streaming?: boolean; uiText?: import('../../i18n/messages').UiMessageText }
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
