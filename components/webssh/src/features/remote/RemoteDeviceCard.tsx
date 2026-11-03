import { useState } from 'react';
import { ConnBadge } from './RemoteTerminal';
import type { ConnState, RemoteDevice, ScreenshotResult } from './types';
import './remote.css';

export interface RemoteDeviceCardProps {
  device: RemoteDevice;
  state: ConnState;
  selected?: boolean;
  shot?: ScreenshotResult;
  busy?: boolean;
  onOpenTerminal: (id: string) => void;
  onCapture?: (id: string) => void;
  /** 点缩略图放大 */
  onZoom?: (shot: ScreenshotResult) => void;
}

/** 设备面板卡：名称、在线状态、最近一次截图缩略图、打开终端 */
export function RemoteDeviceCard({
  device, state, selected, shot, busy, onOpenTerminal, onCapture, onZoom,
}: RemoteDeviceCardProps) {
  return (
    <div className="remote-root rd-card" data-selected={selected ? 'true' : 'false'}>
      <div className="rd-top">
        <div>
          <div className="rd-name">{device.name}</div>
          <div className="rd-model">{device.model}</div>
        </div>
        <span className="rt-spacer" />
        <ConnBadge state={state} />
      </div>

      <div className="rd-addr">
        {device.via ? `经 ${device.via} 中转` : `${device.user}@${device.host}:${device.port}`}
      </div>

      {/* 只有具备取图能力（或已有图）的卡才占缩略图的版面，列表卡不留空框 */}
      {(onCapture || shot) && (
        <div className="rd-thumb" onClick={() => shot && onZoom?.(shot)}>
          {shot
            ? <img src={shot.dataUrl} alt={`${device.name} 最近截图`} />
            : <span className="ph">{busy ? '正在取图…' : '暂无截图'}</span>}
        </div>
      )}
      {shot && <div className="rd-meta">{shot.takenAt.slice(11, 19)} · {shot.mode}</div>}

      <div className="rd-actions">
        <button className="rt-btn" data-variant="solid" onClick={() => onOpenTerminal(device.id)}>打开终端</button>
        {onCapture && (
          <button className="rt-btn" disabled={busy} onClick={() => onCapture(device.id)}>
            {busy ? '取图中…' : '远程截图'}
          </button>
        )}
      </div>
    </div>
  );
}

/** 截图放大遮罩 */
export function ShotModal({ shot, onClose }: { shot: ScreenshotResult | null; onClose: () => void }) {
  if (!shot) return null;
  return (
    <div className="rd-modal" onClick={onClose}>
      <img src={shot.dataUrl} alt="放大截图" />
    </div>
  );
}

/** 便于上层管理"当前放大的那张图" */
export function useShotZoom() {
  const [zoom, setZoom] = useState<ScreenshotResult | null>(null);
  return { zoom, setZoom, close: () => setZoom(null) };
}
