import { useCallback, useEffect, useRef, useState } from 'react';
import './agent-chat.css';
import { mockAdapter, type AgentAdapter, type AgentEvent } from './api';
import {
  type ChatItem,
  type EvidenceItem,
  type ExperienceDraft,
  type PermissionLevel,
  type Verdict,
} from './types';
import { Composer } from './components/Composer';
import { EvidencePanel } from './components/EvidencePanel';
import { ExperienceModal } from './components/ExperienceModal';
import { ToolCallCard } from './components/ToolCallCard';
import { VerdictCard } from './components/VerdictCard';

export interface AgentChatProps {
  /** 后端适配器，缺省用脚本化回放 */
  adapter?: AgentAdapter;
  /** 助手显示名，默认「副驾」 */
  assistantName?: string;
  /** 预置消息流（演示或会话恢复用） */
  initialItems?: ChatItem[];
  /** 预置依据池 */
  initialEvidence?: EvidenceItem[];
  /** 挂载后自动以该文本发起一轮 */
  autoStartPrompt?: string;
  /** 挂载即展开依据抽屉（截图用） */
  evidenceOpenOnMount?: boolean;
  /** 确认人署名，回填到已执行的改动类动作卡片 */
  operator?: string;
  /** 演示用：改动类动作自动放行，不弹确认。生产环境不要开。 */
  autoConfirm?: boolean;
  defaultModel?: string;
  defaultPermission?: PermissionLevel;
  /** 「沉淀为经验」提交回调，缺省只在控制台打印 */
  onSaveExperience?: (draft: ExperienceDraft) => void;
}

let seq = 0;
const uid = (p: string) => `${p}-${(seq += 1)}`;

function draftFromConversation(items: ChatItem[], verdict?: Verdict): ExperienceDraft {
  const firstUser = items.find((i) => i.kind === 'message' && i.role === 'user');
  const tools = items.filter((i): i is Extract<ChatItem, { kind: 'tool' }> => i.kind === 'tool');
  const v = verdict ?? items.filter((i) => i.kind === 'verdict').map((i) => i.verdict).at(-1);
  return {
    title: v ? `${v.title}复测${v.pass ? '通过' : '未通过'}` : '一次调试过程记录',
    phenomenon: firstUser && firstUser.kind === 'message' ? firstUser.text : '',
    cause: v ? `按判据 ${v.expression} 核对，${v.conclusion}` : '',
    action: tools.map((t) => `${t.call.name}：${t.call.argsSummary}`).join('\n'),
    result: tools
      .map((t) => t.call.resultSummary)
      .filter(Boolean)
      .join('；'),
    tags: ['启动测试', '电流限幅', v?.pass ? '合格' : '待复测'],
  };
}

export function AgentChat(props: AgentChatProps) {
  const {
    adapter = mockAdapter,
    assistantName = '副驾',
    initialItems = [],
    initialEvidence = [],
    autoStartPrompt,
    evidenceOpenOnMount = false,
    operator = '当前操作员',
    autoConfirm = false,
    defaultModel = 'deepseek-v4-pro',
    defaultPermission = 'params',
    onSaveExperience,
  } = props;

  const [items, setItems] = useState<ChatItem[]>(initialItems);
  const [evidence, setEvidence] = useState<EvidenceItem[]>(initialEvidence);
  const [shownEvidenceIds, setShownEvidenceIds] = useState<string[] | null>(
    evidenceOpenOnMount ? initialEvidence.map((e) => e.id) : null,
  );
  const [busy, setBusy] = useState(false);
  const [model, setModel] = useState(defaultModel);
  const [permission, setPermission] = useState<PermissionLevel>(defaultPermission);
  const [autoRun, setAutoRun] = useState(true);
  const [expDraft, setExpDraft] = useState<ExperienceDraft | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  /** 等待人工确认的改动类动作：callId → resolve */
  const confirmWaiters = useRef(new Map<string, (ok: boolean) => void>());
  /** 已作出的确认决定：callId → 是否放行 + 确认人。事件与点击的先后顺序都靠它兜住。 */
  const decisions = useRef(new Map<string, { approved: boolean; by: string }>());
  const streamRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = streamRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [items]);

  const apply = useCallback((ev: AgentEvent) => {
    setItems((prev) => {
      switch (ev.type) {
        case 'message_delta': {
          const idx = prev.findIndex((i) => i.kind === 'message' && i.id === ev.messageId);
          if (idx === -1) {
            return [
              ...prev,
              { kind: 'message', id: ev.messageId, role: 'assistant', text: ev.delta, streaming: true },
            ];
          }
          const next = [...prev];
          const cur = next[idx];
          if (cur.kind === 'message') next[idx] = { ...cur, text: cur.text + ev.delta, streaming: true };
          return next;
        }
        case 'tool_call':
          return [
            ...prev,
            {
              kind: 'tool',
              id: ev.callId,
              call: {
                id: ev.callId,
                name: ev.name,
                title: ev.title,
                args: ev.args,
                argsSummary: ev.argsSummary,
                mutating: ev.mutating,
                status: !ev.mutating
                  ? 'running'
                  : decisions.current.get(ev.callId)?.approved === true
                    ? 'running'
                    : decisions.current.get(ev.callId)?.approved === false
                      ? 'error'
                      : 'pending_confirm',
                confirmedBy: decisions.current.get(ev.callId)?.approved
                  ? decisions.current.get(ev.callId)?.by
                  : undefined,
              },
            },
          ];
        case 'tool_result': {
          const idx = prev.findIndex((i) => i.kind === 'tool' && i.id === ev.callId);
          if (idx === -1) return prev;
          const next = [...prev];
          const cur = next[idx];
          if (cur.kind === 'tool') {
            next[idx] = {
              ...cur,
              call: {
                ...cur.call,
                status: ev.status,
                confirmedBy:
                  cur.call.confirmedBy ??
                  (decisions.current.get(ev.callId)?.approved
                    ? decisions.current.get(ev.callId)?.by
                    : undefined),
                durationMs: ev.durationMs,
                resultSummary: ev.resultSummary,
                result: ev.result,
              },
            };
          }
          return next;
        }
        case 'verdict':
          return [...prev, { kind: 'verdict', id: ev.verdict.id, verdict: ev.verdict }];
        case 'done':
          return prev.map((i) => (i.kind === 'message' ? { ...i, streaming: false } : i));
        default:
          return prev;
      }
    });
    if (ev.type === 'evidence') {
      setEvidence((prev) => {
        const seen = new Set(prev.map((e) => e.id));
        return [...prev, ...ev.items.filter((e) => !seen.has(e.id))];
      });
    }
  }, []);

  /** 注入给适配器的人工确认闸门 */
  const requestConfirm = useCallback(
    (call: { callId: string }) =>
      new Promise<boolean>((resolve) => {
        if (autoConfirm) {
          decisions.current.set(call.callId, { approved: true, by: `${operator}（演示自动放行）` });
          setItems((prev) =>
            prev.map((i) =>
              i.kind === 'tool' && i.id === call.callId
                ? { ...i, call: { ...i.call, status: 'running', confirmedBy: operator } }
                : i,
            ),
          );
          resolve(true);
          return;
        }
        confirmWaiters.current.set(call.callId, resolve);
      }),
    [autoConfirm, operator],
  );

  const handleConfirm = useCallback(
    (callId: string, approved: boolean) => {
      const resolve = confirmWaiters.current.get(callId);
      confirmWaiters.current.delete(callId);
      decisions.current.set(callId, { approved, by: operator });
      setItems((prev) =>
        prev.map((i) =>
          i.kind === 'tool' && i.id === callId
            ? {
                ...i,
                call: {
                  ...i.call,
                  status: approved ? 'running' : 'error',
                  confirmedBy: approved ? operator : undefined,
                },
              }
            : i,
        ),
      );
      resolve?.(approved);
    },
    [operator],
  );

  const run = useCallback(
    async (text: string) => {
      if (busy) return;
      setItems((prev) => [...prev, { kind: 'message', id: uid('u'), role: 'user', text }]);
      setBusy(true);
      const ac = new AbortController();
      abortRef.current = ac;
      try {
        for await (const ev of adapter.send({
          text,
          model,
          permission,
          autoRun,
          signal: ac.signal,
          requestConfirm,
        })) {
          apply(ev);
          if (ev.type === 'done') break;
        }
      } finally {
        setBusy(false);
        abortRef.current = null;
      }
    },
    [adapter, apply, autoRun, busy, model, permission, requestConfirm],
  );

  const started = useRef(false);
  useEffect(() => {
    if (!autoStartPrompt || started.current) return;
    started.current = true;
    void run(autoStartPrompt);
    // run 的依赖会随状态变化，这里只在挂载时触发一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStartPrompt]);

  const shownEvidence =
    shownEvidenceIds === null
      ? []
      : evidence.filter((e) => shownEvidenceIds.includes(e.id));

  return (
    <div className="ac-root" data-drawer={String(shownEvidenceIds !== null)}>
      <header className="ac-header">
        <span className="ac-header__avatar">AI</span>
        <span className="ac-header__title">{assistantName}</span>
        <span className="ac-header__sub">电机调试</span>
        <span className="ac-header__spacer" />
        <span className="ac-header__state" data-busy={String(busy)}>
          {busy ? '执行中' : '待命'}
        </span>
        <button
          type="button"
          className="ac-iconbtn"
          onClick={() => setExpDraft(draftFromConversation(items))}
          disabled={items.length === 0}
        >
          沉淀为经验
        </button>
        <button
          type="button"
          className="ac-iconbtn"
          onClick={() =>
            setShownEvidenceIds((v) => (v === null ? evidence.map((e) => e.id) : null))
          }
          disabled={evidence.length === 0}
        >
          依据 {evidence.length}
        </button>
      </header>

      <div className="ac-stream" ref={streamRef}>
        {items.map((it) => {
          if (it.kind === 'message') {
            return (
              <div className={`ac-row ac-row--${it.role}`} key={it.id}>
                <div className={`ac-bubble ac-bubble--${it.role}`}>
                  {it.text}
                  {it.streaming ? <span className="ac-caret" /> : null}
                </div>
              </div>
            );
          }
          if (it.kind === 'tool') {
            return (
              <div className="ac-row ac-row--assistant" key={it.id}>
                <ToolCallCard call={it.call} onConfirm={handleConfirm} />
              </div>
            );
          }
          return (
            <div className="ac-row ac-row--assistant" key={it.id}>
              <VerdictCard
                verdict={it.verdict}
                onOpenEvidence={setShownEvidenceIds}
                onDistill={(v) => setExpDraft(draftFromConversation(items, v))}
              />
            </div>
          );
        })}
      </div>

      <Composer
        busy={busy}
        model={model}
        permission={permission}
        autoRun={autoRun}
        onModel={setModel}
        onPermission={setPermission}
        onAutoRun={setAutoRun}
        onSend={(t) => void run(t)}
        onStop={() => abortRef.current?.abort()}
      />

      {shownEvidenceIds !== null ? (
        <EvidencePanel items={shownEvidence} onClose={() => setShownEvidenceIds(null)} />
      ) : null}

      {expDraft ? (
        <ExperienceModal
          draft={expDraft}
          onCancel={() => setExpDraft(null)}
          onSubmit={(d) => {
            setExpDraft(null);
            if (onSaveExperience) onSaveExperience(d);
            else console.info('[agent-chat] 经验条目', d);
          }}
        />
      ) : null}
    </div>
  );
}

export default AgentChat;
