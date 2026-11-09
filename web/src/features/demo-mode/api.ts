/* ===========================================================================
   数据源模式（真机 / 演示）的接口客户端。

   后端把真机数据（schema omnitest）与演示数据（schema omnitest_demo）物理隔离，
   切换只改连接的 search_path，不动任何数据 —— 所以这里只有「读状态」和「切指针」，
   没有导入、重置这类重动作，接口也应当是毫秒级返回。

   失败一律抛错，由调用方决定降级方式（本项目的约定：拿不到状态就不显示状态，
   而不是显示一个假值）。
   =========================================================================== */

/** 后端统一响应包装（app/schemas/common.py 的 success_response） */
interface ApiEnvelope<T> {
  success: boolean
  code: number
  message: string
  data: T
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  let body: ApiEnvelope<T> | null = null
  try {
    body = (await resp.json()) as ApiEnvelope<T>
  } catch {
    throw new Error(`HTTP ${resp.status}`)
  }
  if (!resp.ok || !body.success) {
    throw new Error(body.message || `HTTP ${resp.status}`)
  }
  return body.data
}

/** live=真机数据 / demo=演示数据 */
export type DataMode = 'live' | 'demo'

export interface DemoStatus {
  mode: DataMode
  /** SQLite / MySQL 部署不支持演示模式，后端返回 false */
  demo_available: boolean
  schema_live: string
  schema_demo: string
}

export function fetchDemoStatus(): Promise<DemoStatus> {
  return call<DemoStatus>('/api/v1/demo/status')
}

export function activateMode(mode: DataMode): Promise<DemoStatus> {
  return call<DemoStatus>('/api/v1/demo/activate', {
    method: 'POST',
    body: JSON.stringify({ mode }),
  })
}
