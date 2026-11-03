import { useT } from '../../../i18n'
import { useState } from 'react';
import type { ToolCall } from '../types';
import { STALE_TOOL_NOTE } from '../persist';

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
  const uiT = useT()

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
        {call.title ? <span className="ac-tool__title">{call.uiAuthored ? uiT(call.title) : call.title}</span> : null}
        {call.mutating ? (
          <span className="ac-badge ac-badge--sm" data-pass={String(call.status !== 'pending_confirm')}>
            {call.status === 'pending_confirm'
              ? uiT('待确认')
              : call.status === 'error'
                ? uiT('未执行')
                : uiT('已确认执行')}
          </span>
        ) : null}
        <span className="ac-tool__spacer" />
        <span className="ac-tool__dur">{uiT(duration)}</span>
      </div>
      <div className="ac-tool__body">
        <div className="ac-kv">
          <span className="ac-kv__k">{uiT("参数")}</span>
          <span className="ac-kv__v">{call.uiAuthored ? uiT(call.argsSummary) : call.argsSummary}</span>
        </div>
        <div className="ac-kv">
          <span className="ac-kv__k">{uiT("结果")}</span>
          <span className="ac-kv__v">
            {call.status === 'pending_confirm'
              ? uiT('等待人工确认，未执行')
              : call.status === 'running'
                ? uiT('等待返回…')
                : (call.uiAuthored || call.resultSummary === STALE_TOOL_NOTE ? uiT(call.resultSummary ?? '—') : call.resultSummary ?? '—')}
          </span>
        </div>
        {call.status === 'pending_confirm' && onConfirm ? (
          <div className="ac-tool__confirm">
            <span className="ac-tool__confirm-text">{uiT("该动作会写入数据或改变被测对象状态，需人工放行。")}</span>
            <button type="button" className="ac-btn ac-btn--solid" onClick={() => onConfirm(call.id, true)}>
              {uiT("确认执行")}</button>
            <button type="button" className="ac-btn ac-btn--ghost" onClick={() => onConfirm(call.id, false)}>
              {uiT("取消")}</button>
          </div>
        ) : null}
        {call.status === 'ok' && call.mutating && call.confirmedBy ? (
          <div className="ac-kv">
            <span className="ac-kv__k">{uiT("确认人")}</span>
            <span className="ac-kv__v">{call.confirmedBy}</span>
          </div>
        ) : null}
        <button type="button" className="ac-tool__toggle" onClick={() => setOpen((v) => !v)}>
          {open ? uiT('收起原始 JSON ▴') : uiT('展开原始 JSON ▾')}
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
