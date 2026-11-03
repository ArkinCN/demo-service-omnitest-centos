/** 网关 HTTP 客户端。WebSocket 地址也从这里推导，避免各处硬编码。 */
import type { RemoteDevice, ScreenshotResult } from './types';

const BASE = import.meta.env.VITE_GATEWAY_URL ?? 'http://localhost:8022';
const TOKEN = import.meta.env.VITE_GATEWAY_TOKEN ?? '';

const headers = { 'content-type': 'application/json', 'x-gateway-token': TOKEN };

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const gatewayWsUrl = (deviceId: string) =>
  `${BASE.replace(/^http/, 'ws')}/ws?device=${encodeURIComponent(deviceId)}&token=${encodeURIComponent(TOKEN)}`;

export const listDevices = () =>
  fetch(`${BASE}/devices`, { headers }).then(json<RemoteDevice[]>);

export const probeDevice = (id: string) =>
  fetch(`${BASE}/probe/${id}`, { headers }).then(json<{ online: boolean; hostname?: string; error?: string }>);

export const takeScreenshot = (deviceId: string) =>
  fetch(`${BASE}/remote/screenshot`, { method: 'POST', headers, body: JSON.stringify({ deviceId }) })
    .then(json<ScreenshotResult>);
