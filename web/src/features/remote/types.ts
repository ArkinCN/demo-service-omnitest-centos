/** 远程设备与终端的共享类型 */

export type DeviceKind = 'host' | 'instrument';

/** 连接目标：keyRef 只是环境变量名，私钥本体永远不进浏览器 */
export interface RemoteTarget {
  host: string;
  port: number;
  user: string;
  keyRef: string;
}

export interface PresetCommand {
  label: string;
  cmd: string;
}

export interface RemoteDevice extends RemoteTarget {
  id: string;
  name: string;
  model: string;
  kind: DeviceKind;
  /** 仪器类设备不直连，经此宿主机中转 */
  via: string | null;
  presets: PresetCommand[];
}

export type ConnState = 'idle' | 'connecting' | 'connected' | 'closed' | 'error';

export interface ScreenshotResult {
  deviceId: string;
  /** live-screen | fallback-file:<路径> | unknown */
  mode: string;
  takenAt: string;
  dataUrl: string;
}
