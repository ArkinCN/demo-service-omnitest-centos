import { useCallback, useEffect, useState } from 'react';
import {
  RemoteTerminal, RemoteDeviceCard, ShotModal, useShotZoom,
  listDevices, probeDevice, takeScreenshot,
} from './features/remote';
import type { ConnState, RemoteDevice, ScreenshotResult } from './features/remote';
import './App.css';

export default function App() {
  const [devices, setDevices] = useState<RemoteDevice[]>([]);
  const [activeId, setActiveId] = useState<string>('bench');
  const [states, setStates] = useState<Record<string, ConnState>>({});
  const [shots, setShots] = useState<Record<string, ScreenshotResult>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string>('');
  const { zoom, setZoom, close } = useShotZoom();

  useEffect(() => {
    listDevices()
      .then((ds) => {
        setDevices(ds);
        // 逐台探活，不阻塞首屏
        ds.forEach((d) => probeDevice(d.id)
          .then((r) => setStates((s) => ({ ...s, [d.id]: r.online ? 'connected' : 'error' })))
          .catch(() => setStates((s) => ({ ...s, [d.id]: 'error' }))));
      })
      .catch((e) => setErr(`无法读取设备清单：${e.message}（网关是否已启动？）`));
  }, []);

  const capture = useCallback(async (id: string) => {
    setBusy(id); setErr('');
    try {
      const shot = await takeScreenshot(id);
      setShots((s) => ({ ...s, [id]: shot }));
    } catch (e) {
      setErr(`截图失败：${(e as Error).message}`);
    } finally { setBusy(null); }
  }, []);

  const active = devices.find((d) => d.id === activeId);

  return (
    <div className="remote-root app">
      <header className="app-head">
        <h1>峰岹台架远程控制台</h1>
        <p>浏览器 → 网关 → SSH → 台架 Windows 工控机。终端、预置命令与远程取图在一页内完成。</p>
      </header>

      {err && <div className="app-err">{err}</div>}

      <div className="app-grid">
        <aside className="app-col">
          <h2>设备</h2>
          {devices.map((d) => (
            <RemoteDeviceCard
              key={d.id}
              device={d}
              state={states[d.id] ?? 'idle'}
              selected={d.id === activeId}
              onOpenTerminal={setActiveId}
            />
          ))}
          {devices.length === 0 && !err && <p className="app-hint">读取设备清单中…</p>}
        </aside>

        <main className="app-col app-main">
          <h2>终端</h2>
          {active
            ? <RemoteTerminal
                key={active.id}
                deviceId={active.id}
                target={{ host: active.host, port: active.port, user: active.user, keyRef: active.keyRef }}
                title={active.name}
                presets={active.presets}
                onStateChange={(s) => setStates((m) => ({ ...m, [active.id]: s }))}
              />
            : <p className="app-hint">未选中设备</p>}
        </main>

        <aside className="app-col">
          <h2>截图</h2>
          {devices.filter((d) => !d.via).map((d) => (
            <RemoteDeviceCard
              key={`shot-${d.id}`}
              device={d}
              state={states[d.id] ?? 'idle'}
              shot={shots[d.id]}
              busy={busy === d.id}
              onOpenTerminal={setActiveId}
              onCapture={capture}
              onZoom={setZoom}
            />
          ))}
          <p className="app-hint">
            SSH 处在 Session 0，实时截屏多半拿不到桌面；取不到时网关自动回退为台架机
            <code> C:\fc_pull </code> 下最近一张图，卡片下方标明来源。
          </p>
        </aside>
      </div>

      <ShotModal shot={zoom} onClose={close} />
    </div>
  );
}
