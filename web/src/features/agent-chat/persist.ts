import type { ChatItem, EvidenceItem, ToolCall, Verdict, EvidenceKind } from './types';

/* --------------------------------------------------- 对话会话的本地持久化

   为什么需要它（2026-10-10，用户需求单）：
   `AgentChat` 的 items / evidence 是组件内 useState，而助手卡片在**收起时会被整块
   卸载**（FlowScreen 收起后只留一条「展开助手」窄条），切流程 / 切页 / 刷新更是连
   FlowScreen、KnowledgeModule 一起卸载 —— 内存态必然丢，用户反馈「收起再打开、
   对话刷新了」。因此对话必须落在浏览器本地。

   与仓库既有本地持久化同范式（见 useAppStore 的 LS_* 一组、KnowledgeModule 的
   `omnitest.kb.assistantHeight`、FlowScreen 的 `flow-assistant-collapsed:<flow>`）：
     · 键名带版本号 `omnitest.chat.v1.<会话键>`，会话键直接用宿主已有的 sessionId
       （`shell-<场景>-<流程>` / `shell-<场景>-knowledge`）→ 天然「每流程一份 +
       知识库一份」，场景切换也自动隔离；
     · 读写一律包 try/catch：隐私窗口与禁用站点数据时 localStorage 会直接抛，
       此时降级为「只在本次会话有效」，不报错、不影响对话；
     · **不落任何密钥**：只存items/evidence 这些纯数据，与 store 里 PIN「用完即弃」
       的纪律一致。

   ⚠️ 本模块刻意保持**纯函数、零 React 依赖**：读写策略集中在 4 个上限常量上，
   便于单测与复查。
   --------------------------------------------------------------------------- */

/** 存储键前缀。整体形状 `omnitest.chat.v1.<persistKey>` */
const KEY_PREFIX = 'omnitest.chat.v1.';

/** 条目数上限：写入前裁剪，只留最新的一批（够人回看，又不至于把键撑爆） */
const MAX_ITEMS = 200;
const MAX_EVIDENCE = 100;

/** 序列化体积上限（字符数）。超过就对半砍 items 再试，直到低于此值或只剩 1 条。 */
const MAX_PAYLOAD_CHARS = 400_000;

/** 重开后未跑完的动作卡改判用的说明文案（如实告知，不假装还能执行） */
export const STALE_TOOL_NOTE = '页面重开后已失效，如需执行请重新发起';

export interface RestoredChat {
  items: ChatItem[];
  evidence: EvidenceItem[];
}

const storageKey = (persistKey: string) => `${KEY_PREFIX}${persistKey}`;

/* --------------------------------------------------------------- 结构校验

   落盘的是外部输入（用户可能手改过 localStorage，历史版本也可能形状不同），
   所以逐项校验、坏项丢弃，而不是整份信任后让渲染层崩。
   --------------------------------------------------------------------------- */

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function str(v: unknown): string | undefined {
  return typeof v === 'string' ? v : undefined;
}

/** 依据条目三类来源的白名单（与 types.ts 的 EvidenceKind 对齐） */
const EVIDENCE_KINDS: readonly EvidenceKind[] = ['procedure', 'case', 'document'];

function parseEvidenceItem(raw: unknown): EvidenceItem | null {
  if (!isRecord(raw)) return null;
  const { id, kind, title, excerpt, source, locator } = raw;
  if (typeof id !== 'string' || typeof kind !== 'string') return null;
  if (!EVIDENCE_KINDS.includes(kind as EvidenceKind)) return null;
  if (typeof title !== 'string' || typeof excerpt !== 'string') return null;
  if (typeof source !== 'string' || typeof locator !== 'string') return null;
  return {
    id,
    kind: kind as EvidenceKind,
    title,
    excerpt,
    source,
    locator,
    href: str(raw.href),
    docId: str(raw.docId),
  };
}

/**
 * 工具调用卡：恢复时**必须收口未完成态**。
 *
 * `pending_confirm` / `running` 两张卡在重开后都不可能再续上——等人工确认的
 * `confirmWaiters` 只存在于内存里，适配器那一轮也已随页面卸载而终止。
 * 若原样回填，卡片会显示「待确认」并带一枚点了没反应的确认按钮，让人误以为
 * 还能放行。这里统一改判为 `error`（界面徽章即「未执行」），并把原因写进
 * resultSummary 原样展示；`ToolCallCard` 的确认条只在 `pending_confirm` 时渲染，
 * 因此改判后按钮自然消失，无需动渲染层。
 */
function parseToolCall(raw: unknown): ToolCall | null {
  if (!isRecord(raw)) return null;
  const { id, name, argsSummary, status } = raw;
  if (typeof id !== 'string' || typeof name !== 'string') return null;
  if (typeof argsSummary !== 'string' || typeof status !== 'string') return null;

  const ALLOWED: readonly ToolCall['status'][] = ['pending_confirm', 'running', 'ok', 'error'];
  if (!ALLOWED.includes(status as ToolCall['status'])) return null;

  const stale = status === 'pending_confirm' || status === 'running';
  return {
    id,
    name,
    title: str(raw.title),
    uiAuthored: raw.uiAuthored === true,
    args: isRecord(raw.args) ? raw.args : {},
    argsSummary,
    mutating: raw.mutating === true,
    status: stale ? 'error' : (status as ToolCall['status']),
    confirmedBy: str(raw.confirmedBy),
    durationMs: typeof raw.durationMs === 'number' ? raw.durationMs : undefined,
    resultSummary: stale ? STALE_TOOL_NOTE : str(raw.resultSummary),
    result: stale ? undefined : raw.result,
  };
}

function parseVerdict(raw: unknown): Verdict | null {
  if (!isRecord(raw)) return null;
  const { id, title, expression, conclusion } = raw;
  if (typeof id !== 'string' || typeof title !== 'string') return null;
  if (typeof expression !== 'string' || typeof conclusion !== 'string') return null;
  if (typeof raw.pass !== 'boolean') return null;

  const measurements: Verdict['measurements'] = [];
  if (Array.isArray(raw.measurements)) {
    for (const m of raw.measurements) {
      if (!isRecord(m)) continue;
      if (typeof m.label !== 'string' || typeof m.value !== 'string') continue;
      measurements.push({ label: m.label, value: m.value, unit: str(m.unit) });
    }
  }
  const evidenceIds = Array.isArray(raw.evidenceIds)
    ? raw.evidenceIds.filter((x): x is string => typeof x === 'string')
    : [];

  return { id, title, pass: raw.pass, expression, measurements, conclusion, evidenceIds };
}

function parseChatItem(raw: unknown): ChatItem | null {
  if (!isRecord(raw)) return null;
  const { id, kind } = raw;
  if (typeof id !== 'string') return null;

  if (kind === 'message') {
    const { role, text } = raw;
    if (role !== 'user' && role !== 'assistant') return null;
    if (typeof text !== 'string') return null;
    // streaming 一律收尾：否则重开后气泡会永久挂一个闪烁光标（streaming===true）
    const uiText = isRecord(raw.uiText) && typeof raw.uiText.key === 'string'
      && (!raw.uiText.params || isRecord(raw.uiText.params) && Object.values(raw.uiText.params).every((value) => typeof value === 'string' || typeof value === 'number'))
      ? { key: raw.uiText.key, params: raw.uiText.params as Record<string, string | number> | undefined,
          uiParams: Array.isArray(raw.uiText.uiParams) && raw.uiText.uiParams.every((key) => typeof key === 'string') ? raw.uiText.uiParams as string[] : undefined } : undefined;
    return { kind: 'message', id, role, text, streaming: false, uiText };
  }
  if (kind === 'tool') {
    const call = parseToolCall(raw.call);
    return call ? { kind: 'tool', id, call } : null;
  }
  if (kind === 'verdict') {
    const verdict = parseVerdict(raw.verdict);
    return verdict ? { kind: 'verdict', id, verdict } : null;
  }
  return null;
}

/* --------------------------------------------------------------- 读 / 写 */

/**
 * 读并清洗一份会话记录。
 *
 * 无记录 → null（调用方回落到 initialItems/initialEvidence）；
 * 记录损坏（JSON 解析失败 / 顶层形状不对）→ 删掉该键并 console.warn 自愈，
 * 返回 null。**不抛**：持久化失败绝不能影响对话本身。
 */
export function readStoredChat(persistKey: string): RestoredChat | null {
  try {
    const raw = localStorage.getItem(storageKey(persistKey));
    if (!raw) return null;
    const j: unknown = JSON.parse(raw);
    if (!isRecord(j)) throw new Error('顶层不是对象');

    const items: ChatItem[] = [];
    if (Array.isArray(j.items)) {
      for (const it of j.items) {
        const parsed = parseChatItem(it);
        if (parsed) items.push(parsed);
      }
    }
    const evidence: EvidenceItem[] = [];
    if (Array.isArray(j.evidence)) {
      for (const e of j.evidence) {
        const parsed = parseEvidenceItem(e);
        if (parsed) evidence.push(parsed);
      }
    }

    // 空记录（此前只开过场、没真聊过）与无记录同义：让调用方走初始值那一路，
    // 否则知识库页的问候语种子会被空数组顶掉、变成一张白纸。
    if (items.length === 0 && evidence.length === 0) return null;
    return { items, evidence };
  } catch (e) {
    console.warn(`[agent-chat] 会话记录无法读取，已丢弃该键（${persistKey}）：`, e);
    try {
      localStorage.removeItem(storageKey(persistKey));
    } catch {
      /* 删不掉也只是下次再读到一次坏记录，不影响本次对话 */
    }
    return null;
  }
}

/** 只保留最新的 n 条（对话是线性追加的，旧的先丢） */
function tail<T>(arr: T[], n: number): T[] {
  return arr.length > n ? arr.slice(arr.length - n) : arr;
}

/**
 * 裁剪 + 序列化 + 写入。
 *
 * 两级兜底：条目数先按 MAX_ITEMS/MAX_EVIDENCE 裁剪；序列化体积仍超上限就
 * 对半砍 items 再试。`QuotaExceededError`（隐私模式或配额用尽）时同样裁剪重试
 * 一次，仍失败则 console.warn 后放弃 —— **只告警不抛**，不影响正在进行的对话。
 */
export function writeStoredChat(
  persistKey: string,
  items: ChatItem[],
  evidence: EvidenceItem[],
): void {
  const key = storageKey(persistKey);
  const ev = tail(evidence, MAX_EVIDENCE);

  const attempt = (its: ChatItem[]): string =>
    JSON.stringify({ v: 1, items: its, evidence: ev });

  let its = tail(items, MAX_ITEMS);
  let payload = attempt(its);
  // 体积兜底：对半砍直到进入上限（至少留 1 条，宁可少存也不要整份丢）
  while (payload.length > MAX_PAYLOAD_CHARS && its.length > 1) {
    its = its.slice(Math.ceil(its.length / 2));
    payload = attempt(its);
  }

  const put = () => localStorage.setItem(key, payload);
  try {
    put();
  } catch (e) {
    // 配额不足：再砍一半重试一次；仍失败就放弃本键（本会话内对话照常）
    try {
      its = its.slice(Math.ceil(its.length / 2));
      payload = attempt(its);
      put();
    } catch (e2) {
      console.warn(`[agent-chat] 会话记录写入失败，本次未落盘（${persistKey}）：`, e, e2);
    }
  }
}

/** 清掉一份会话记录（当前无 UI 入口，留作调试与后续「清空对话」备用） */
export function clearStoredChat(persistKey: string): void {
  try {
    localStorage.removeItem(storageKey(persistKey));
  } catch {
    /* 同上：删不掉不影响对话 */
  }
}
