import { useEffect, useRef, useState } from 'react';
import {
  MODEL_OPTIONS,
  PERMISSION_OPTIONS,
  type PermissionLevel,
} from '../types';

interface Props {
  busy: boolean;
  model: string;
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
  const { busy, model, permission, autoRun } = props;
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
          placeholder="描述现象或下达指令，Enter 发送，Shift+Enter 换行"
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
          title={micAvailable ? (listening ? '停止录音' : '语音输入（中文）') : '当前浏览器不支持语音识别'}
          aria-label="语音输入"
        >
          ●
        </button>
        {busy ? (
          <button type="button" className="ac-send" onClick={props.onStop}>
            停止
          </button>
        ) : (
          <button type="button" className="ac-send" disabled={!text.trim()} onClick={submit}>
            发送
          </button>
        )}
      </div>

      <div className="ac-controls">
        <span className="ac-field">
          <label htmlFor="ac-model">模型</label>
          <select
            id="ac-model"
            className="ac-select"
            value={model}
            onChange={(e) => props.onModel(e.target.value)}
          >
            {MODEL_OPTIONS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </span>
        <span className="ac-field">
          <label htmlFor="ac-perm">权限</label>
          <select
            id="ac-perm"
            className="ac-select"
            value={permission}
            onChange={(e) => props.onPermission(e.target.value as PermissionLevel)}
          >
            {PERMISSION_OPTIONS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </span>
        <label className="ac-switch">
          <input type="checkbox" checked={autoRun} onChange={(e) => props.onAutoRun(e.target.checked)} />
          <span className="ac-switch__track" />
          <span title="自动执行只覆盖只读类工具；写参数与控硬件仍需逐次人工确认">开启自动执行</span>
        </label>
      </div>
      <div className="ac-hint" data-warn={String(!micAvailable || Boolean(notice))}>
        {notice ||
          `${permHint}　写参数与控硬件一律需人工点确认，自动执行不覆盖。${
            micAvailable ? '' : '当前浏览器不支持语音识别，麦克风已停用。'
          }`}
      </div>
    </div>
  );
}
