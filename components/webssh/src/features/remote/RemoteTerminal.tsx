import { useCallback, useEffect, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { gatewayWsUrl } from './api';
import type { ConnState, PresetCommand, RemoteTarget } from './types';
import './remote.css';

const STATE_TEXT: Record<ConnState, string> = {
  idle: '未连接', connecting: '连接中', connected: '已连接', closed: '已断开', error: '连接失败',
};

export function ConnBadge({ state, detail }: { state: ConnState; detail?: string }) {
  return (
    <span className="rt-badge" data-state={state} title={detail}>
      <i className="dot" />{STATE_TEXT[state]}
    </span>
  );
}

export interface RemoteTerminalProps {
  deviceId: string;
  target: RemoteTarget;
  title?: string;
  presets?: PresetCommand[];
  /** 每收到一段远端输出回调一次，供上层做日志/解析 */
  onOutput?: (chunk: string) => void;
  onStateChange?: (state: ConnState) => void;
}

/**
 * 浏览器里的 SSH 终端。
 * xterm 只负责显示与键盘；真正的 SSH 由网关建立，浏览器与网关之间走 WebSocket。
 */
export function RemoteTerminal({
  deviceId, target, title, presets = [], onOutput, onStateChange,
}: RemoteTerminalProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const bufRef = useRef<string>('');
  const [state, setState] = useState<ConnState>('idle');
  const [detail, setDetail] = useState('');

  const stateRef = useRef<ConnState>('idle');
  const setStateBoth = useCallback((s: ConnState) => {
    stateRef.current = s; setState(s); onStateChange?.(s);
  }, [onStateChange]);

  // 终端实例只建一次，设备切换时复用（清屏即可），避免反复创建 canvas
  useEffect(() => {
    if (!hostRef.current || termRef.current) return;
    const term = new Terminal({
      fontFamily: 'ui-monospace, Menlo, Consolas, "Noto Sans Mono", monospace',
      fontSize: 13, cursorBlink: true, convertEol: true, scrollback: 5000,
      theme: { background: '#101613', foreground: '#DCE6E0', cursor: '#A8C5B5', selectionBackground: '#2E5E45' },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(hostRef.current);
    fit.fit();
    termRef.current = term;
    fitRef.current = fit;

    term.onData((d) => wsRef.current?.readyState === WebSocket.OPEN
      && wsRef.current.send(JSON.stringify({ type: 'input', data: d })));

    const ro = new ResizeObserver(() => {
      try { fit.fit(); } catch { /* 容器尚未布局 */ }
      if (wsRef.current?.readyState === WebSocket.OPEN)
        wsRef.current.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
    });
    ro.observe(hostRef.current);
    return () => { ro.disconnect(); term.dispose(); termRef.current = null; };
  }, []);

  const disconnect = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  const connect = useCallback(() => {
    const term = termRef.current;
    if (!term) return;
    disconnect();
    term.clear();
    setStateBoth('connecting');
    setDetail(`${target.user}@${target.host}:${target.port}`);

    const ws = new WebSocket(gatewayWsUrl(deviceId));
    wsRef.current = ws;
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data as string);
      if (m.type === 'data') {
        term.write(m.data);
        bufRef.current += m.data;
        onOutput?.(m.data);
      } else if (m.type === 'status') {
        setStateBoth(m.state as ConnState);
        setDetail(m.detail ?? '');
        if (m.state === 'error') term.writeln(`\r\n\x1b[31m[网关] ${m.detail}\x1b[0m`);
      }
    };
    ws.onerror = () => { setStateBoth('error'); setDetail('WebSocket 无法连接到网关'); };
    // 出错后 onclose 紧随而至，别把"失败"覆盖成中性的"已断开"
    ws.onclose = () => setStateBoth(stateRef.current === 'error' ? 'error' : 'closed');
  }, [deviceId, target, disconnect, onOutput, setStateBoth]);

  // 设备变化即重连
  useEffect(() => { connect(); return disconnect; /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [deviceId]);

  const runPreset = (cmd: string) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: 'input', data: `${cmd}\r` }));
  };

  const copyAll = async () => {
    const sel = termRef.current?.getSelection();
    await navigator.clipboard.writeText(sel && sel.length > 0 ? sel : bufRef.current);
  };

  const online = state === 'connected';
  return (
    <div className="remote-root rt-terminal">
      <div className="rt-head">
        <span className="rt-title">{title ?? deviceId}</span>
        <span className="rt-sub">{target.user}@{target.host}:{target.port}</span>
        <span className="rt-spacer" />
        <ConnBadge state={state} detail={detail} />
      </div>

      <div className="rt-bar">
        {presets.map((p) => (
          <button key={p.label} className="rt-btn" disabled={!online} onClick={() => runPreset(p.cmd)} title={p.cmd}>
            {p.label}
          </button>
        ))}
        <span className="rt-spacer" />
        <button className="rt-btn" onClick={copyAll}>复制输出</button>
        {online
          ? <button className="rt-btn" data-variant="accent" onClick={disconnect}>断开</button>
          : <button className="rt-btn" data-variant="solid" onClick={connect}>重连</button>}
      </div>

      <div className="rt-screen" ref={hostRef} />
      <p className="rt-note">
        私钥留在网关侧，浏览器只拿到 WebSocket 帧。SSH 落在 Session 0，
        <b>看不到桌面上的 GUI 窗口</b>，需要点按钮的操作仍要人工或计划任务。
      </p>
    </div>
  );
}
