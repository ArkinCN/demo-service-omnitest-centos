/* ===========================================================================
   SSH 网关（c/components/webssh）的 HTTP 客户端。WebSocket 地址也从这里推导。

   第四轮起页面接两个后端，各有独立地址与 token，全部经 .env 配置：
     · 本文件 → SSH 网关，默认 http://localhost:8022，只剩交互式终端一个用途；
     · ./bridge.ts → 设备桥，默认 http://127.0.0.1:8031，画布设备节点状态、
       分层工具菜单、红线凭据都走它。
   变量清单见工程根目录的 .env.example。改完 .env 必须重启 vite，
   Vite 不热加载环境变量。
   =========================================================================== */
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
