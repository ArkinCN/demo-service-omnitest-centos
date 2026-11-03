import { knownScriptMessage, uiMessage, type UiMessageText } from '../../i18n/messages'
import { translate } from '../../i18n/runtime'
import { useT } from '../../i18n'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import './agent-chat.css';
import { mockAdapter, type AgentAdapter, type AgentEvent } from './api';
import {
  FALLBACK_MODEL_OPTIONS,
  type ChatItem,
  type EvidenceItem,
  type ExperienceDraft,
  type ModelOption,
  type PermissionLevel,
  type Verdict,
} from './types';
import { fetchModels } from './models';
import { Composer } from './components/Composer';
import { EvidencePanel } from './components/EvidencePanel';
import { ExperienceModal } from './components/ExperienceModal';
import { Markdown } from './components/Markdown';
import { ToolCallCard } from './components/ToolCallCard';
import { VerdictCard } from './components/VerdictCard';
import { readStoredChat, writeStoredChat, clearStoredChat } from './persist';
import { useAppStore } from '../../state/useAppStore';

export interface AgentChatProps {
  /** 后端适配器，缺省用脚本化回放 */
  adapter?: AgentAdapter;
  /** 助手显示名，默认「助手」 */
  assistantName?: string;
  /** 预置消息流（演示或会话恢复用） */
  initialItems?: ChatItem[];
  /** 预置依据池 */
  initialEvidence?: EvidenceItem[];
  /** 挂载后自动以该文本发起一轮 */
  autoStartPrompt?: string;
  autoStartUiText?: UiMessageText;
  /**
   * 「上下文包已就绪」门闩（默认 true = 不等）。
   *
   * ⚠️ 为什么需要它（2026-10-05 修「助手不按真实情况回答」）：
   * autoStartPrompt 原先在挂载时立即发起，但承载上下文包的 `ActionDock` 是经
   * `actionSlot` 渲染的子元素——它的 effect 挂载顺序在前，写入的却是**首次 render
   * 算出的那份 envelope**；真后端适配器此时可能仍取不到内容而**整段不送 context**，
   * 模型于是拿不到现场数据、只能凭通用知识瞎答。
   *
   * 宿主（FlowCopilot）拿到 ActionDock 的「就绪」回调后把本值置 true，
   * 自动开场提问才放行——**第一轮请求必然带上真现场数据**。
   *
   * 缺省 undefined 视为 true：不传的调用方（知识库页等）行为与以前完全一致，
   * 不会因为没接门闩而永远不发起开场提问。
   */
  autoStartReady?: boolean;
  /** 挂载即展开依据抽屉（截图用） */
  evidenceOpenOnMount?: boolean;
  /** 确认人署名，回填到已执行的改动类动作卡片 */
  operator?: string;
  /*
   * 曾有一个 autoConfirm 开关：为真时改动类动作不弹确认、直接 resolve(true)。
   * 2026-09-20 整条删除（07i 独立核验 P2）。两条理由：
   *   一、它与 api.ts 的批准转发串起来就是一条「无人点击即批准设备桥凭据」的通路；
   *   二、它放行出来的留痕与真人批准同名同形，台账因此不能当作「确有人批准」的证据。
   * 演示要省点击就少点几个按钮，不在红线上开自动挡。
   */
  defaultModel?: string;
  defaultPermission?: PermissionLevel;
  /** 「沉淀为经验」提交回调，缺省只在控制台打印 */
  onSaveExperience?: (draft: ExperienceDraft) => void;
  /**
   * 消息流与输入区之间的一行插槽，给宿主挂自己的控件（助手预置动作按钮条走这里）。
   * 第三轮收尾轮补：在此之前宿主只能往 .ac-root 里 portal 一个节点，依赖内部 class 名。
   */
  actionSlot?: ReactNode;
  /**
   * 挂载后把命令式接口交给宿主：宿主据此代发一条消息，
   * 等价于人在输入框里打了这段话——用户气泡里就是这段原文。
   * 在此之前宿主只能往 .ac-textarea 写值再点 .ac-send。
   */
  onReady?: (api: AgentChatApi) => void;
  /** 忙态变化回调。在此之前宿主只能 MutationObserver 盯 .ac-header__state[data-busy]。 */
  onBusyChange?: (busy: boolean) => void;
  /**
   * 会话标识，随每轮请求带给后端，由后端据此维护上下文。
   * 缺省 undefined 时后端按无上下文处理（本阶段后端 history 固定 null，
   * 传与不传都不影响回答；补上是为了契约完整，避免后端日后据此分会话时拿不到）。
   */
  sessionId?: string;
  /**
   * 收起回调。传了就由头部的按钮条多渲染一枚「收起」——放在头部按钮组里，
   * 与「沉淀为经验 / 依据」同排，不遮不压；由宿主决定收起后的表现。
   */
  onCollapse?: () => void;
  /**
   * 会话持久化键（2026-10-10 用户需求单：收起再打开、切页、刷新不能丢对话）。
   *
   * **必须随会话变化**：宿主传的 sessionId（`shell-<场景>-<流程>` /
   * `shell-<场景>-knowledge`）天然满足「每流程一份 + 知识库一份」，
   * 本组件不自造命名。最终落盘键 = `omnitest.chat.v1.<persistKey>`。
   *
   * ⚠️ 该 prop 变化即视为**换会话**（不是同会话的新数据），效果同 key 变化：
   * 立刻清掉上一份内存态并改读新键，避免把 A 流程的对话画到 B 流程的卡片里。
   *
   * 缺省 undefined = 不持久化，行为与加它之前完全一致（组件仍可独立复用）。
   */
  persistKey?: string;
}

/** 交给宿主的命令式接口 */
export interface AgentChatApi {
  /** 代发一条消息；忙态中调用会被忽略，与人点发送按钮同一套闸门 */
  send: (text: string, uiText?: UiMessageText) => void;
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
  const uiT = useT()

  const {
    adapter = mockAdapter,
    assistantName,
    initialItems = [],
    initialEvidence = [],
    autoStartPrompt,
    autoStartUiText,
    autoStartReady = true,
    evidenceOpenOnMount = false,
    operator = '当前操作员',
    defaultModel = useAppStore.getState().model,
    // 保留入参以不破坏调用方接口；2026-10-10 起权限改由全局 store 驱动，此值仅作说明。
    defaultPermission: _defaultPermission,
    onSaveExperience,
    actionSlot,
    onReady,
    onBusyChange,
    sessionId,
    onCollapse,
    persistKey,
  } = props;

  /*
   * 会话恢复（2026-10-10）：有落盘记录就用记录，没有才用 initialItems/initialEvidence。
   *
   * 为什么用惰性初值：读 localStorage 是同步操作，放在 useState 初始化函数里
   * 就能在**首帧之前**拿到历史，避免「先画空壳、再补历史」的闪烁。
   * 本组件被宿主用 key={flow} 挂载，换流程即换实例，惰性初值不会读串。
   */
  const [items, setItems] = useState<ChatItem[]>(() => {
    if (!persistKey) return initialItems;
    return readStoredChat(persistKey)?.items ?? initialItems;
  });
  const [evidence, setEvidence] = useState<EvidenceItem[]>(() => {
    if (!persistKey) return initialEvidence;
    return readStoredChat(persistKey)?.evidence ?? initialEvidence;
  });
  const [shownEvidenceIds, setShownEvidenceIds] = useState<string[] | null>(
    evidenceOpenOnMount ? initialEvidence.map((e) => e.id) : null,
  );
  const [busy, setBusy] = useState(false);
  const [model, setModel] = useState(defaultModel);
  /**
   * 可选模型列表：挂载时从后端拉（2026-10-14 起**不再硬编码**）。
   *
   * 初值用兜底列表（deepseek-v4.1-flash），保证首帧下拉就有内容、不闪空；
   * 拉到后端真实列表后整体替换，并把默认选中项对齐到**后端第一条**
   * （后端按 sort_order 排序，首条即主模型）。拉取失败则保留兜底项，
   * 用户仍能发请求，不会因模型列表拿不到而卡死。
   */
  const [models, setModels] = useState<ModelOption[]>(FALLBACK_MODEL_OPTIONS);
  /**
   * 权限档位**全局化**（2026-10-10 权限切换修复）。
   *
   * 此前它是本组件内部 state，且没有一路传到后端 → 切档只改 UI 高亮，
   * 模型侧永远看到写死的 readonly（根因见报告）。现在以 store 为**单一来源**：
   * 切换即写 store + 落盘，各宿主（流程页/知识库/运行台）共享同一档位。
   * `defaultPermission` prop 保留（不破坏调用方接口），仅在 store 无值时作初始兜底。
   */
  const permission = useAppStore((s) => s.permission) as PermissionLevel;
  const setPermission = useAppStore((s) => s.setPermission);
  // 显式标注：defaultPermission 仅保留接口兼容，不再参与逻辑（权限以 store 为准）
  void _defaultPermission;
  const [autoRun, setAutoRun] = useState(true);
  const [expDraft, setExpDraft] = useState<ExperienceDraft | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  /**
   * 挂载时拉一次后端可用模型列表（2026-10-14）。
   *
   * 为什么用 defaultModel 作函数依赖的「一次性」effect：
   * - 只有真后端适配器（dsh）才需要列表——脚本回放（mock）不调后端，
   *   但它同样可以展示后端列表，这里不做区分，统一拉取；
   * - 拉取失败只 console.warn，**不回退报错弹窗**：下拉保留兜底项，
   *   发请求仍走默认模型，不让「拿不到列表」升级成「助手不可用」。
   * - 严格模式下 React 会双跑 effect，用 AbortController 取消上一轮。
   */
  useEffect(() => {
    const ac = new AbortController();
    let cancelled = false;
    fetchModels(ac.signal)
      .then((list) => {
        if (cancelled || list.length === 0) return;
        setModels(list);
        // 默认选中对齐后端首条（sort_order 最小 = 主模型）；
        // 仅当当前选中值不在新列表里时才改，避免打断用户已选中的项。
        setModel((cur) =>
          list.some((m) => m.value === cur) ? cur : list[0].value,
        );
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        console.warn('[agent-chat] 拉取模型列表失败，沿用兜底候选：', e);
      });
    return () => {
      cancelled = true;
      ac.abort();
    };
  }, []);

  /** 等待人工确认的改动类动作：callId → resolve */
  const confirmWaiters = useRef(new Map<string, (ok: boolean) => void>());
  /** 已作出的确认决定：callId → 是否放行 + 确认人。事件与点击的先后顺序都靠它兜住。 */
  const decisions = useRef(new Map<string, { approved: boolean; by: string }>());
  const streamRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = streamRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [items]);

  /* -------------------------------- 会话持久化（2026-10-10）

     收起卡片 / 切流程 / 切页都会把本组件**整块卸载**，刷新更是连宿主一起重来，
     所以对话必须落盘；否则用户看到的就是「一收起、对话就白了」。
     写入节奏：跑一轮时事件是高频追加的，因此 400ms 防抖；另有卸载兜底，
     免得刚跑完的最后一轮正好落在防抖窗口里被丢掉。
     ------------------------------------------------ */

  /** 最新一份对话与依据：防抖回调与卸载兜底都从这里取值，避免闭包拿到旧数组 */
  const latestRef = useRef({ items, evidence });
  latestRef.current = { items, evidence };

  /** 会话键也跟随 ref：卸载时那个 cleanup 闭包里要拿得到当时的值 */
  const persistKeyRef = useRef(persistKey);
  persistKeyRef.current = persistKey;

  useEffect(() => {
    if (!persistKey) return;
    const timer = setTimeout(() => {
      writeStoredChat(persistKey, latestRef.current.items, latestRef.current.evidence);
    }, 400);
    return () => clearTimeout(timer);
  }, [items, evidence, persistKey]);

  // 卸载兜底：宿主收起 / 切页 / 换会话时的最后一次落盘
  useEffect(() => {
    if (!persistKey) return;
    return () => {
      writeStoredChat(persistKey, latestRef.current.items, latestRef.current.evidence);
    };
  }, [persistKey]);

  /**
   * 换会话（persistKey 变化）时立刻换台：
   * 清掉上一份内存态并改读新键。本组件的宿主目前都用 key={flow} 挂载，
   * 换流程走的是「卸载重建」而不是这条路径；保留它是为了这个接口在别处复用时
   * 不会把 A 会话的对话画到 B 会话的卡片里。
   * ⚠️ 下方所有 effect 都排在它后面，因此「跳过开场提问」与「卸载兜底」
   * 拿到的都是换台之后的状态。
   */
  const prevPersistKey = useRef(persistKey);
  useEffect(() => {
    if (prevPersistKey.current === persistKey) return;
    prevPersistKey.current = persistKey;
    if (!persistKey) {
      setItems([]);
      setEvidence([]);
      return;
    }
    const restored = readStoredChat(persistKey);
    setItems(restored?.items ?? []);
    setEvidence(restored?.evidence ?? []);
  }, [persistKey]);

  const apply = useCallback((ev: AgentEvent) => {
    setItems((prev) => {
      switch (ev.type) {
        case 'message_delta': {
          const idx = prev.findIndex((i) => i.kind === 'message' && i.id === ev.messageId);
          if (idx === -1) {
            return [
              ...prev,
              { kind: 'message', id: ev.messageId, role: 'assistant', text: ev.delta, streaming: true, uiText: ev.uiText },
            ];
          }
          const next = [...prev];
          const cur = next[idx];
          if (cur.kind === 'message') next[idx] = { ...cur, text: cur.text + ev.delta, streaming: true, uiText: ev.uiText ?? cur.uiText };
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
                uiAuthored: ev.uiAuthored,
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
                uiAuthored: ev.uiAuthored ?? cur.call.uiAuthored,
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
        case 'done': {
          const stopped = prev.map((i) => (i.kind === 'message' ? { ...i, streaming: false } : i));
          // 出错必须以气泡形态让人看见。此前 done{reason:error} 只把 streaming 置 false，
          // 带回来的 message 被丢弃，界面上表现为「发出去一片静默、什么也不回」——
          // 与「模型还在想」无法区分。这里把错误原样落成一条助手消息。
          if (ev.reason === 'error') {
            return [
              ...stopped,
              {
                kind: 'message',
                id: uid('err'),
                role: 'assistant',
                text: `本轮未能完成：${ev.message ?? '后端返回错误，未附原因'}`,
                uiText: uiMessage('本轮未能完成：{v1}', { v1: ev.message ?? '后端返回错误，未附原因' }),
                streaming: false,
              },
            ];
          }
          return stopped;
        }
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

  /**
   * 清空当前会话（2026-10-14 用户需求）：消息流 + 依据抽屉 + localStorage 落盘一起清。
   *
   * 为什么三处都要清：
   *   - `items` / `evidence` 是内存态，不清则界面照旧；
   *   - `clearStoredChat` 删 localStorage，不清则刷新/切页/收起再打开会把旧对话读回来。
   *
   * 注意执行顺序：**先删落盘、再清内存**。因为下面这个 400ms 防抖的自动落盘 effect
   * 会在 items/evidence 变化后把最新值写回，清完内存正好把空数组写回去（等于落盘仍是
   * 干净的）；反过来先清内存也可能被同一次 tick 的旧闭包写脏。两处配合才是稳的。
   *
   * 忙态时不放行：正在流式输出时清空会让后续事件往空列表里追加，产生"半截回答"。
   */
  const clearConversation = useCallback(() => {
    if (busy) return;
    if (persistKey) clearStoredChat(persistKey);
    setItems([]);
    setEvidence([]);
    setShownEvidenceIds(null);
  }, [busy, persistKey]);

  /**
   * 注入给适配器的人工确认闸门。
   * 只有一条出路：把 resolve 挂进 confirmWaiters，等人在气泡的确认卡上点。
   * 没有任何分支能在无人点击的情况下 resolve(true)——自动放行的那条已删。
   */
  const requestConfirm = useCallback(
    (call: { callId: string }) =>
      new Promise<boolean>((resolve) => {
        confirmWaiters.current.set(call.callId, resolve);
      }),
    [],
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
    async (text: string, authoredUiText?: UiMessageText) => {
      if (busy) return;
      // 意图识别分支：命中「启动自动化测试流程」直接交给自动化编排器，
      // 不当作普通对话丢给模型（这是用户明说的第二种入口，两种入口同一套流程）。
      if (/启动自动化测试|开始自动化测试|一键自动化/.test(text.trim())) {
        setItems((prev) => [...prev, { kind: 'message', id: uid('u'), role: 'user', text, uiText: authoredUiText }])
        setItems((prev) => [
          ...prev,
          {
            kind: 'message',
            id: uid('auto'),
            role: 'assistant',
            text: '已启动自动化测试流程：自动确认参数 → 按阶段推进 → 生成并下载报告。进度会在全屏运行浮层与顶部阶段条实时展示。',
            uiText: uiMessage('已启动自动化测试流程：自动确认参数 → 按阶段推进 → 生成并下载报告。进度会在全屏运行浮层与顶部阶段条实时展示。'),
            streaming: false,
          },
        ])
        useAppStore.getState().startAutomation()
        // 订阅播报：自动化事件经 store.automationAnnouncement 下发，这里把它追加进对话，
        // 做一次防刷屏（同一条消息不重复追加）。
        const unsub = useAppStore.subscribe((s, prev) => {
          if (s.automationAnnouncement && s.automationAnnouncement !== prev.automationAnnouncement) {
            setItems((items) => {
              const last = items[items.length - 1]
              if (last && last.kind === 'message' && last.text === s.automationAnnouncement) return items
              return [
                ...items,
                {
                  kind: 'message',
                  id: uid('ann'),
                  role: 'assistant',
                  text: s.automationAnnouncement,
                  uiText: uiMessage(s.automationAnnouncement),
                  streaming: false,
                },
              ]
            })
          }
          // 流程结束（runStatus 离开 running）就停止订阅，不留泄漏
          if (s.automationRunStatus !== 'running' && prev.automationRunStatus === 'running') {
            unsub()
          }
        })
        return
      }
      setItems((prev) => [...prev, { kind: 'message', id: uid('u'), role: 'user', text, uiText: authoredUiText }]);
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
          sessionId,
        })) {
          apply(ev);
          if (ev.type === 'done') break;
        }
      } catch (e) {
        // 适配器抛出的任何异常都要落成一条可见的助手消息。
        // 只留 finally 会把异常吞掉：用户看到的是「发了消息、界面毫无反应」，
        // 分不清是模型在思考、还是链路根本没通。
        const aborted = ac.signal.aborted;
        if (!aborted) {
          setItems((prev) => [
            ...prev,
            {
              kind: 'message',
              id: uid('err'),
              role: 'assistant',
              text: `本轮未能完成：${e instanceof Error ? e.message : String(e)}`,
              uiText: uiMessage('本轮未能完成：{v1}', { v1: e instanceof Error ? e.message : String(e) }),
              streaming: false,
            },
          ]);
        }
      } finally {
        setBusy(false);
        abortRef.current = null;
      }
    },
    [adapter, apply, autoRun, busy, model, permission, requestConfirm, sessionId],
  );

  // 命令式接口：句柄本身一次性给出去，内部始终打到最新那份 run 上，
  // 免得宿主握着一个闭包过期的 send。
  const runRef = useRef(run);
  runRef.current = run;
  useEffect(() => {
    onReady?.({ send: (text: string, uiText?: UiMessageText) => void runRef.current(text, uiText) });
  }, [onReady]);

  useEffect(() => {
    onBusyChange?.(busy);
  }, [busy, onBusyChange]);

  /*
   * 自动开场提问：**等上下文包就绪再发**（2026-10-05 修「助手不按真实情况回答」）。
   *
   * 两道闸门：
   *   ① autoStartReady —— 宿主（FlowCopilot）收到 ActionDock 的 onEnvReady 后置 true，
   *      保证发出去的那一轮 request 里 heldEnv() 已有真现场数据，模型不是瞎答；
   *   ② started —— 只发一次。
   *
   * ⚠️ StrictMode 坑（项目铁律）：以前是「发之前就把 started 置 true」，而本 effect
   * 依赖 `autoStartPrompt`，StrictMode 双调用 + ready 后置两种时序混在一起，
   * 容易出现「第一次置位但那次 run 被丢弃 → 之后再也不发」。现在把记账放在
   * **真正进入发送分支之后**，且以「已记账」为唯一判据：ready 到来时若还没发过，
   * 一定发得出去；已发过则严格幂等。
   *
   * ⚠️ 恢复到历史对话时**不再自动开场**（2026-10-10）：否则刷新一次就多出一轮
   * 「产品本体属性里哪些是占位的」——人看到的不是「上次的对话」，而是被追问了一句。
   * 判定放在惰性初始化期内联读，不额外引入时序依赖；读不到历史时才置 false 走原逻辑。
   */
  const started = useRef(
    persistKey ? readStoredChat(persistKey) !== null : false,
  );
  useEffect(() => {
    if (!autoStartPrompt || !autoStartReady || started.current) return;
    started.current = true;
    void run(autoStartPrompt, autoStartUiText);
    // run 的依赖会随状态变化，这里只在「ready 且未发过」时触发一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStartPrompt, autoStartReady, autoStartUiText]);

  const shownEvidence =
    shownEvidenceIds === null
      ? []
      : evidence.filter((e) => shownEvidenceIds.includes(e.id));

  return (
    <div className="ac-root" data-drawer={String(shownEvidenceIds !== null)}>
      <header className="ac-header">
        <span className="ac-header__avatar">AI</span>
        <span className="ac-header__title">{assistantName ?? uiT('助手')}</span>
        <span className="ac-header__sub">{uiT("电机调试")}</span>
        {/*
          后端标识：一眼看出这一轮走的是 dsh（真后端）还是 mock（脚本回放）。
          起因是「发了消息毫无反应」这类现象，光看界面分不清前端挂的是哪个适配器，
          排查时要反复猜。把它显式写出来，以后一眼可辨。
        */}
        <span className="ac-header__sub" title={uiT("后端适配器：{v1}", { v1: adapter.id })}>
          {adapter.id}
        </span>
        <span className="ac-header__spacer" />
        <span className="ac-header__state" data-busy={String(busy)}>
          {busy ? uiT('执行中') : uiT('待命')}
        </span>
        <button
          type="button"
          className="ac-iconbtn"
          onClick={() => setExpDraft(draftFromConversation(items))}
          disabled={items.length === 0}
        >
          {uiT("沉淀为经验")}</button>
        <button
          type="button"
          className="ac-iconbtn"
          onClick={() =>
            setShownEvidenceIds((v) => (v === null ? evidence.map((e) => e.id) : null))
          }
          disabled={evidence.length === 0}
        >
          {uiT("依据 ")}{evidence.length}
        </button>
        {/*
          清空对话（2026-10-14 用户需求）：消息流 + 依据 + 落盘一起清。
          与「沉淀为经验」「依据」同排；对话为空或正在执行时禁用，避免空点与半截回答。
        */}
        <button
          type="button"
          className="ac-iconbtn"
          onClick={clearConversation}
          disabled={busy || (items.length === 0 && evidence.length === 0)}
          title={uiT("清空当前对话（消息与依据一并清除）")}
        >
          {uiT("清空对话")}
        </button>
        {/* 宿主要求折叠时给一枚收起键；与上面两枚同排，所以不会重叠 */}
        {onCollapse ? (
          <button
            type="button"
            className="ac-iconbtn"
            onClick={onCollapse}
            title={uiT("收起助手")}
          >
            {uiT("收起")}</button>
        ) : null}
      </header>

      <div className="ac-stream" ref={streamRef}>
        {items.map((it) => {
          if (it.kind === 'message') {
            let displayText = it.text
            if (it.uiText) {
              const displayParams = it.uiText.params && Object.fromEntries(Object.entries(it.uiText.params).map(([key, value]) =>
                [key, it.uiText?.uiParams?.includes(key) && typeof value === 'string' ? uiT(value) : value]))
              const complete = uiT(it.uiText.key, displayParams)
              const original = translate(it.uiText.key, 'zh-CN', it.uiText.params)
              const partial = it.text.length < original.length && original.startsWith(it.text)
              displayText = partial
                ? complete.slice(0, Math.ceil(complete.length * Math.min(1, it.text.length / Math.max(1, original.length))))
                : complete
            } else if (it.role === 'assistant' && !it.streaming && knownScriptMessage(it.text)) {
              displayText = uiT(it.text)
            }
            return (
              <div className={`ac-row ac-row--${it.role}`} key={it.id}>
                <div className={`ac-bubble ac-bubble--${it.role}`}>
                  {/* 助手回答按 Markdown 渲染：后端给的是 ### / ** / - 这类语法，
                      直接当纯文本显示会让人看到一堆符号（用户反馈过）。
                      用户自己打的字不渲染——人写的就是想原样看到的。 */}
                  {it.role === 'assistant' ? <Markdown text={displayText} /> : displayText}
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

      {actionSlot ? <div className="ac-slot">{actionSlot}</div> : null}

      <Composer
        busy={busy}
        model={model}
        models={models}
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
