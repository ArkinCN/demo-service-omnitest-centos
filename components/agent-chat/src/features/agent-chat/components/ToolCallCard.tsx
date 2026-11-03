import { useState } from 'react';
import type { ToolCall } from '../types';

const STATUS_TEXT: Record<ToolCall['status'], string> = {
  pending_confirm: '待确认',
  running: '执行中',
  ok: '完成',
  error: '失败',
};

interface Props {
  call: ToolCall;
  /** 改动类动作的确认回调；缺省时不渲染确认条 */
  onConfirm?: (callId: string, approved: boolean) => void;
}

export function ToolCallCard({ call, onConfirm }: Props) {
  const [open, setOpen] = useState(false);
  const duration =
    call.status === 'pending_confirm'
      ? ''
      : call.durationMs === undefined
      ? STATUS_TEXT[call.status]
      : call.durationMs >= 1000
        ? `${(call.durationMs / 1000).toFixed(2)} s`
        : `${call.durationMs} ms`;

  return (
    <div className="ac-card ac-tool" data-status={call.status}>
      <div className="ac-tool__head">
        <span className="ac-tool__dot" data-status={call.status} />
        <span className="ac-tool__name">{call.name}</span>
        {call.title ? <span className="ac-tool__title">{call.title}</span> : null}
        {call.mutating ? (
          <span className="ac-badge ac-badge--sm" data-pass={String(call.status !== 'pending_confirm')}>
            {call.status === 'pending_confirm'
              ? '待确认'
              : call.status === 'error'
                ? '未执行'
                : '已确认执行'}
          </span>
        ) : null}
        <span className="ac-tool__spacer" />
        <span className="ac-tool__dur">{duration}</span>
      </div>
      <div className="ac-tool__body">
        <div className="ac-kv">
          <span className="ac-kv__k">参数</span>
          <span className="ac-kv__v">{call.argsSummary}</span>
        </div>
        <div className="ac-kv">
          <span className="ac-kv__k">结果</span>
          <span className="ac-kv__v">
            {call.status === 'pending_confirm'
              ? '等待人工确认，未执行'
              : call.status === 'running'
                ? '等待返回…'
                : (call.resultSummary ?? '—')}
          </span>
        </div>
        {call.status === 'pending_confirm' && onConfirm ? (
          <div className="ac-tool__confirm">
            <span className="ac-tool__confirm-text">该动作会改变被测对象状态，需人工放行。</span>
            <button type="button" className="ac-btn ac-btn--solid" onClick={() => onConfirm(call.id, true)}>
              确认执行
            </button>
            <button type="button" className="ac-btn ac-btn--ghost" onClick={() => onConfirm(call.id, false)}>
              取消
            </button>
          </div>
        ) : null}
        {call.status === 'ok' && call.mutating && call.confirmedBy ? (
          <div className="ac-kv">
            <span className="ac-kv__k">确认人</span>
            <span className="ac-kv__v">{call.confirmedBy}</span>
          </div>
        ) : null}
        <button type="button" className="ac-tool__toggle" onClick={() => setOpen((v) => !v)}>
          {open ? '收起原始 JSON ▴' : '展开原始 JSON ▾'}
        </button>
        {open ? (
          <pre className="ac-json">
{JSON.stringify({ arguments: call.args, result: call.result ?? null }, null, 2)}
          </pre>
        ) : null}
      </div>
    </div>
  );
}
