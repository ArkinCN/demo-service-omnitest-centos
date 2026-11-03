import { useT } from '../../../i18n'
import { useEffect, useRef, useState } from 'react';
import {
  FALLBACK_MODEL_OPTIONS,
  PERMISSION_OPTIONS,
  type ModelOption,
  type PermissionLevel,
} from '../types';

interface Props {
  busy: boolean;
  model: string;
  /** 可选模型列表，由宿主从后端拉取后传入（见 AgentChat 的 fetchModels）。 */
  models?: ModelOption[];
  permission: PermissionLevel;
  autoRun: boolean;
  onModel: (v: string) => void;
  onPermission: (v: PermissionLevel) => void;
  onAutoRun: (v: boolean) => void;
  onSend: (text: string) => void;
  onStop: () => void;
}

// Web Speech API 在 TS 标准库里没有类型，这里按实际用到的部分最小声明。
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
}
type SpeechCtor = new () => SpeechRecognitionLike;

function getSpeechCtor(): SpeechCtor | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as Record<string, unknown>;
  return (w.webkitSpeechRecognition ?? w.SpeechRecognition ?? null) as SpeechCtor | null;
}

export function Composer(props: Props) {
  const uiT = useT()

  const { busy, model, permission, autoRun } = props;
  // 宿主未传（或拉取失败）时用兜底列表，保证下拉不空；正常路径下是后端真实列表。
  // `uiT` 只对**词典里有的**显示名生效：后端 display_name 通常不在词典中，
  // translate() 查不到会原样返回，属预期行为（模型名是数据、不是 UI 文案）。
  const modelOptions = props.models && props.models.length > 0 ? props.models : FALLBACK_MODEL_OPTIONS;
  const [text, setText] = useState('');
  const [listening, setListening] = useState(false);
  const [notice, setNotice] = useState('');
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  const speechCtor = getSpeechCtor();
  const micAvailable = speechCtor !== null;

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 120)}px`;
  }, [text]);

  const submit = () => {
    const v = text.trim();
    if (!v || busy) return;
    props.onSend(v);
    setText('');
  };

  const toggleMic = () => {
    if (!speechCtor) return;
    if (listening) {
      recRef.current?.stop();
      return;
    }
    const rec = new speechCtor();
    rec.lang = 'zh-CN';
    rec.continuous = false;
    rec.interimResults = true;
    rec.onresult = (e) => {
      let s = '';
      for (let i = e.resultIndex; i < e.results.length; i += 1) s += e.results[i][0].transcript;
      setText((prev) => prev + s);
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => {
      setListening(false);
      setNotice('语音识别出错，请改用文字输入。');
    };
    recRef.current = rec;
    setListening(true);
    setNotice('');
    rec.start();
  };

  const permHint = PERMISSION_OPTIONS.find((p) => p.value === permission)?.hint ?? '';

  return (
    <div className="ac-composer">
      <div className="ac-composer__box">
        <textarea
          ref={taRef}
          className="ac-textarea"
          rows={1}
          placeholder={uiT("描述现象或下达指令，Enter 发送，Shift+Enter 换行")}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button
          type="button"
          className="ac-mic"
          data-on={String(listening)}
          disabled={!micAvailable}
          onClick={toggleMic}
          title={micAvailable ? (listening ? uiT('停止录音') : uiT('语音输入（中文）')) : uiT('当前浏览器不支持语音识别')}
          aria-label={uiT("语音输入")}
        >
          ●
        </button>
        {busy ? (
          <button type="button" className="ac-send" onClick={props.onStop}>
            {uiT("停止")}</button>
        ) : (
          <button type="button" className="ac-send" disabled={!text.trim()} onClick={submit}>
            {uiT("发送")}</button>
        )}
      </div>

      <div className="ac-controls">
        <span className="ac-field">
          <label htmlFor="ac-model">{uiT("模型")}</label>
          <select
            id="ac-model"
            className="ac-select"
            value={model}
            onChange={(e) => props.onModel(e.target.value)}
          >
            {modelOptions.map((m) => (
              <option key={m.value} value={m.value}>
                {uiT(m.label)}
              </option>
            ))}
          </select>
        </span>
        <span className="ac-field">
          <label id="ac-perm-label">{uiT("权限")}</label>
          {/* 权限档位是三选一的即时切换，用分段控件比下拉更直观，
              每档的完整含义挂在 title 上，不在界面上平铺整句。 */}
          <span className="ac-seg" role="tablist" aria-labelledby="ac-perm-label">
            {PERMISSION_OPTIONS.map((p) => (
              <button
                key={p.value}
                type="button"
                role="tab"
                title={uiT(p.hint)}
                aria-selected={permission === p.value}
                data-on={String(permission === p.value)}
                onClick={() => props.onPermission(p.value)}
              >
                {uiT(p.label)}
              </button>
            ))}
          </span>
        </span>
        <label className="ac-switch">
          <input type="checkbox" checked={autoRun} onChange={(e) => props.onAutoRun(e.target.checked)} />
          <span className="ac-switch__track" />
          <span title={uiT("只对只读类工具免去逐次确认；写参数与控硬件一律仍需人工点确认")}>{uiT("只读工具免确认")}</span>
        </label>
      </div>
      <div className="ac-hint" data-warn={String(!micAvailable || Boolean(notice))}>
        {notice ||
          uiT("{v1}　写参数与控硬件一律需人工点确认，自动执行不覆盖。{v2}", { v1: uiT(permHint), v2: micAvailable ? '' : uiT('当前浏览器不支持语音识别，麦克风已停用。') })}
      </div>
    </div>
  );
}
