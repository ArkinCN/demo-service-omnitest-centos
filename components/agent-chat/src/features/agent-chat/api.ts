// 后端适配层：定义 SSE 事件协议，并提供 mock / DeepSeek Harness 两种实现。
import type { EvidenceItem, PermissionLevel, Verdict } from './types';

// ---------------------------------------------------------------------------
// 1. SSE 事件协议
// ---------------------------------------------------------------------------
// 后端以 text/event-stream 推送，每条形如：
//   event: tool_call
//   data: {"type":"tool_call", ...}
// 前端按 data 里的 type 字段分发（event 名与 type 保持一致，便于原生 EventSource 监听）。

/** 助手正文增量。前端把 delta 追加到 messageId 对应的气泡。 */
export interface MessageDeltaEvent {
  type: 'message_delta';
  messageId: string;
  delta: string;
}

/** 工具开始调用。前端建卡片并置为 running。 */
export interface ToolCallEvent {
  type: 'tool_call';
  callId: string;
  name: string;
  title?: string;
  args: Record<string, unknown>;
  argsSummary: string;
  /** 改动类动作（写参数、控硬件、落盘）。为 true 时前端必须先要人确认再放行。 */
  mutating?: boolean;
}

/** 工具返回。前端按 callId 回填同一张卡片。 */
export interface ToolResultEvent {
  type: 'tool_result';
  callId: string;
  status: 'ok' | 'error';
  durationMs: number;
  resultSummary: string;
  result: unknown;
}

/** 判定结论。 */
export interface VerdictEvent {
  type: 'verdict';
  verdict: Verdict;
}

/** 依据条目。可多次推送，前端按 id 去重后并入依据池。 */
export interface EvidenceEvent {
  type: 'evidence';
  items: EvidenceItem[];
}

/** 本轮结束。 */
export interface DoneEvent {
  type: 'done';
  /** 结束原因：正常完成 / 被用户中止 / 出错 */
  reason: 'complete' | 'aborted' | 'error';
  message?: string;
}

export type AgentEvent =
  | MessageDeltaEvent
  | ToolCallEvent
  | ToolResultEvent
  | VerdictEvent
  | EvidenceEvent
  | DoneEvent;

/** 一次发送请求 */
export interface SendRequest {
  text: string;
  model: string;
  permission: PermissionLevel;
  autoRun: boolean;
  /** 历史轮次的会话标识，由后端维护上下文 */
  sessionId?: string;
  signal?: AbortSignal;
  /**
   * 人工确认闸门。适配器在执行 mutating 工具前调用，等到人点了按钮才继续。
   * 由宿主（AgentChat）注入：返回 true 表示确认执行，false 表示取消。
   */
  requestConfirm?: (call: { callId: string; name: string; argsSummary: string }) => Promise<boolean>;
}

/** 适配器接口：把任意后端归一成 AgentEvent 异步流 */
export interface AgentAdapter {
  id: string;
  label: string;
  send(req: SendRequest): AsyncGenerator<AgentEvent, void, void>;
}

// ---------------------------------------------------------------------------
// 2. mockAdapter —— 脚本化回放，用于截图与演示
// ---------------------------------------------------------------------------

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export const MOCK_EVIDENCE: EvidenceItem[] = [
  {
    id: 'ev-proc-1',
    kind: 'procedure',
    title: '直流无刷电机启动测试规程 · 4.3 启动电流限值',
    excerpt:
      '空载启动过程中，母线电流峰值不得超过额定电流的 1.5 倍；若超出，应先检查启动斜坡时间与开环电流限幅设置，再判定为不合格。',
    source: '《电机驱动芯片调试规程》Fortior-DBG-STD-002 Rev.C',
    locator: '第 12 页 · 条 4.3',
    href: '#/doc/Fortior-DBG-STD-002#p12',
  },
  {
    id: 'ev-proc-2',
    kind: 'procedure',
    title: '直流无刷电机启动测试规程 · 4.5 转速稳定判据',
    excerpt:
      '启动完成判据为：FG 反馈频率在 200 ms 窗口内波动小于 ±2%，且与目标转速偏差不超过 ±3%。',
    source: '《电机驱动芯片调试规程》Fortior-DBG-STD-002 Rev.C',
    locator: '第 13 页 · 条 4.5',
    href: '#/doc/Fortior-DBG-STD-002#p13',
  },
  {
    id: 'ev-case-1',
    kind: 'case',
    title: '相似案例：同系列芯片启动电流偏高（工单 DBG-2405-118）',
    excerpt:
      '现象为启动瞬间峰值电流达额定 1.8 倍。原因为 Customer.h 中启动斜坡时间设为 80 ms，低于该负载推荐的 150 ms。把斜坡时间改到 160 ms 后峰值降至 1.24 倍，复测通过。',
    source: '调试案例库 case-library.sqlite · 工单 DBG-2405-118',
    locator: '记录 118 · 2024-05-21',
    href: '#/case/DBG-2405-118',
  },
  {
    id: 'ev-doc-1',
    kind: 'document',
    title: '芯片数据手册 · 电流采样与限幅寄存器说明',
    excerpt:
      'CURR_LIMIT 寄存器以 12 位无符号数表示限幅阈值，LSB 对应 3.2 mA。开环启动阶段的实际限幅值为 CURR_LIMIT 与 STARTUP_ILIM 二者取小。',
    source: '《FU68xx 系列电机驱动芯片数据手册》V2.1',
    locator: '第 47 页 · 表 8-4',
    href: '#/doc/FU68xx-DS-V2.1#p47',
  },
];

const MOCK_VERDICT: Verdict = {
  id: 'vd-1',
  title: '空载启动电流峰值',
  pass: true,
  expression: 'I_peak ≤ 1.5 × I_rated',
  measurements: [
    { label: '实测峰值 I_peak', value: '1.87', unit: 'A' },
    { label: '额定电流 I_rated', value: '1.50', unit: 'A' },
    { label: '倍率', value: '1.25', unit: '×' },
    { label: '限值', value: '1.50', unit: '×' },
  ],
  conclusion: '峰值 1.87 A 为额定的 1.25 倍，低于 1.5 倍限值，判定合格。',
  evidenceIds: ['ev-proc-1', 'ev-case-1', 'ev-doc-1'],
};

interface Emit {
  (ev: AgentEvent): void;
}

/**
 * 脚本化会话：读取 Customer.h → motor_start → rigol_measure → 判定合格 → 依据 3 条。
 * motor_start 属改动类动作，执行前走人工确认闸门。
 * @param pace 单位延时倍率，0 表示不等待（截图用）
 */
async function playScript(req: SendRequest, emit: Emit, pace: number): Promise<void> {
  const wait = (ms: number) => (pace === 0 ? Promise.resolve() : sleep(ms * pace));
  let seg = 0;
  /** 每段叙述占一个独立气泡：工具卡片之后继续说话时应新起一条消息 */
  const say = async (text: string) => {
    seg += 1;
    const messageId = `m-assist-${seg}`;
    for (let i = 0; i < text.length; i += 6) {
      await wait(26);
      emit({ type: 'message_delta', messageId, delta: text.slice(i, i + 6) });
    }
  };
  /** 改动类动作的确认闸门；未注入闸门时按"不放行"处理，绝不默认执行 */
  const confirm = async (callId: string, name: string, argsSummary: string) => {
    if (!req.requestConfirm) return false;
    return req.requestConfirm({ callId, name, argsSummary });
  };

  await say('先看工程里的启动参数，再跑一次空载启动并抓电流波形。');

  await wait(320);
  emit({
    type: 'tool_call',
    callId: 'tc-1',
    name: 'read_file',
    title: '读取工程文件',
    args: { path: 'MotorApp/Inc/Customer.h', symbols: ['STARTUP_RAMP_MS', 'CURR_LIMIT', 'RATED_CURRENT_A'] },
    argsSummary: '读取 MotorApp/Inc/Customer.h 的 3 个启动相关宏',
  });
  await wait(640);
  emit({
    type: 'tool_result',
    callId: 'tc-1',
    status: 'ok',
    durationMs: 612,
    resultSummary: 'STARTUP_RAMP_MS=160，CURR_LIMIT=0x01F4，RATED_CURRENT_A=1.50',
    result: {
      path: 'MotorApp/Inc/Customer.h',
      macros: { STARTUP_RAMP_MS: 160, CURR_LIMIT: '0x01F4', STARTUP_ILIM: '0x0190', RATED_CURRENT_A: 1.5 },
      lines: [148, 151, 153],
    },
  });

  await say('斜坡时间 160 ms 在推荐区间内。启动属改动类动作，请确认后执行。');

  await wait(300);
  const startArgs = '空载启动至 3000 rpm，斜坡 160 ms';
  emit({
    type: 'tool_call',
    callId: 'tc-2',
    name: 'motor_start',
    title: '启动电机',
    args: { mode: 'no_load', target_rpm: 3000, ramp_ms: 160 },
    argsSummary: startArgs,
    mutating: true,
  });
  const go = await confirm('tc-2', 'motor_start', startArgs);
  if (!go) {
    emit({
      type: 'tool_result',
      callId: 'tc-2',
      status: 'error',
      durationMs: 0,
      resultSummary: '已取消：未获人工确认，电机未启动',
      result: { cancelled: true, reason: 'not_confirmed' },
    });
    await say('启动未获确认，本轮到此为止。需要时重新下达指令。');
    emit({ type: 'done', reason: 'aborted' });
    return;
  }
  await wait(900);
  emit({
    type: 'tool_result',
    callId: 'tc-2',
    status: 'ok',
    durationMs: 2140,
    resultSummary: '启动成功，1.8 s 后转速稳定在 2982 rpm（偏差 −0.6%）',
    result: { started: true, settle_ms: 1804, steady_rpm: 2982, rpm_ripple_pct: 0.9, fg1_hz: 99.4 },
  });

  await wait(300);
  emit({
    type: 'tool_call',
    callId: 'tc-3',
    name: 'rigol_measure',
    title: '示波器取数',
    args: { channel: 'CH2', probe: '电流钳 100 mV/A', window_ms: 500, depth: 1_200_000 },
    argsSummary: 'CH2 深存储抓取 500 ms 启动段，深度 1.2 M 点',
  });
  await wait(1000);
  emit({
    type: 'tool_result',
    callId: 'tc-3',
    status: 'ok',
    durationMs: 3480,
    resultSummary: 'I_peak = 1.87 A（t = 42 ms），稳态 0.41 A',
    result: {
      channel: 'CH2',
      sample_rate_sa_s: 2_400_000,
      points: 1_200_000,
      i_peak_a: 1.87,
      i_peak_t_ms: 42,
      i_steady_a: 0.41,
      waveform_ref: 'shots/startup_ch2.npy',
    },
  });

  await say('按规程 4.3 的限值核对：');
  await wait(260);
  emit({ type: 'verdict', verdict: MOCK_VERDICT });
  await wait(200);
  emit({ type: 'evidence', items: MOCK_EVIDENCE });
  await say('本项通过。若换成带载工况，建议把限幅重新按负载曲线核一遍。');
  emit({ type: 'done', reason: 'complete' });
}

/** 把回调式脚本转成异步事件流 */
function toStream(req: SendRequest, pace: number): AsyncGenerator<AgentEvent, void, void> {
  const queue: AgentEvent[] = [];
  let notify: (() => void) | null = null;
  let finished = false;
  const emit: Emit = (ev) => {
    queue.push(ev);
    notify?.();
  };
  const task = playScript(req, emit, pace).finally(() => {
    finished = true;
    notify?.();
  });

  async function* gen(): AsyncGenerator<AgentEvent, void, void> {
    while (true) {
      if (queue.length > 0) {
        yield queue.shift()!;
        continue;
      }
      if (finished) {
        await task;
        return;
      }
      await new Promise<void>((r) => {
        notify = () => {
          notify = null;
          r();
        };
      });
    }
  }
  return gen();
}

/** 脚本化回放适配器：用于演示，带真实节奏 */
export const mockAdapter: AgentAdapter = {
  id: 'mock',
  label: '演示回放（mock）',
  send(req: SendRequest) {
    return toStream(req, 1);
  },
};

/** 截图用：不等待，一次性把整段脚本吐完（确认闸门照样生效） */
export const mockAdapterInstant: AgentAdapter = {
  id: 'mock-instant',
  label: '演示回放（即时）',
  send(req: SendRequest) {
    return toStream(req, 0);
  },
};

// ---------------------------------------------------------------------------
// 3. dshAdapter —— 对接 DeepSeek Harness Python SDK 的会话流（预留，未联通）
// ---------------------------------------------------------------------------
// 后端约定：Python 侧用 DeepSeek Harness（下称 DSH）的 session.stream() 拿到原生事件，
// 在 FastAPI 里转成上面的 SSE 协议。映射关系如下，改后端时照此对齐：
//
//   DSH 原生事件                         →  本协议事件
//   ------------------------------------------------------------------
//   assistant.text.delta{text}           →  message_delta{messageId, delta}
//   assistant.message.start{id}          →  （不推；前端按 messageId 首见即建气泡）
//   tool.invoke{call_id,name,arguments}  →  tool_call{callId,name,args,argsSummary}
//                                           argsSummary 由后端 summarize_args() 生成，
//                                           前端不做参数渲染逻辑。
//   tool.output{call_id,ok,elapsed,data} →  tool_result{callId,status,durationMs,
//                                           resultSummary,result}
//   judge.result{...}                    →  verdict{verdict}   ← DSH 判定工具的结构化返回，
//                                           后端负责补 expression / measurements 字段。
//   retrieval.hits[{source,page,text}]   →  evidence{items}    ← kind 由检索库路由决定：
//                                           规程库→procedure，案例库→case，资料库→document。
//   run.finished{status}                 →  done{reason}
//
// 权限档位与自动执行的传递：POST body 里的 permission / auto_run 直达 DSH 的
// tool policy，前端只负责把用户选择带上，不在前端做拦截。
//
// 人工确认闸门：DSH 侧把改动类工具登记为 requires_approval，推 tool_call 时带 mutating:true
// 并挂起该次调用；前端调 requestConfirm 拿到人的点击后，POST /api/agent/confirm
// {call_id, approved, actor} 放行或取消，DSH 再继续推 tool_result。
export const dshAdapter: AgentAdapter = {
  id: 'dsh',
  label: 'DeepSeek Harness',
  async *send(req: SendRequest) {
    const resp = await fetch('/api/agent/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: req.text,
        model: req.model,
        permission: req.permission,
        auto_run: req.autoRun,
        session_id: req.sessionId,
      }),
      signal: req.signal,
    });
    if (!resp.ok || !resp.body) {
      yield { type: 'done', reason: 'error', message: `HTTP ${resp.status}` };
      return;
    }
    const confirmAt = async (callId: string) => {
      const ok = req.requestConfirm ? await req.requestConfirm({ callId, name: '', argsSummary: '' }) : false;
      await fetch('/api/agent/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ call_id: callId, approved: ok }),
      });
    };
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // SSE 以空行分隔一条消息
      let sep: number;
      while ((sep = buf.indexOf('\n\n')) !== -1) {
        const raw = buf.slice(0, sep);
        buf = buf.slice(sep + 2);
        const dataLine = raw
          .split('\n')
          .filter((l) => l.startsWith('data:'))
          .map((l) => l.slice(5).trim())
          .join('');
        if (!dataLine) continue;
        try {
          const ev = JSON.parse(dataLine) as AgentEvent;
          if (ev.type === 'tool_call' && ev.mutating) void confirmAt(ev.callId);
          yield ev;
        } catch {
          // 协议外的行直接丢弃，不中断流
        }
      }
    }
    yield { type: 'done', reason: 'complete' };
  },
};

export const ADAPTERS: Record<string, AgentAdapter> = {
  mock: mockAdapter,
  'mock-instant': mockAdapterInstant,
  dsh: dshAdapter,
};
