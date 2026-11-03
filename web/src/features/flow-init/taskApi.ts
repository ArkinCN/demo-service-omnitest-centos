/* ===========================================================================
   阶段 2 的「一次保存」：网页建任务 → 改字段 → 保存 → 刷新后仍能读回。

   为什么单开一个文件：后端 tasks 是本次新加的最小闭环（POST/PATCH/GET
   /api/v1/tasks），与流程 3 的轮次产物不是一回事，混进 flow-run/api.ts
   会让「哪份数据落在哪张表」再次变模糊。

   两条纪律（与 flow-run/api.ts 同源）：
     一、先看 HTTP 状态再看 success 位，两层都要过；
     二、**不吞异常**。保存失败必须让界面看得到——上一阶段最严重的问题就是
         落盘失败被 catch 空了，界面却一切正常。
   =========================================================================== */

/** 后端统一响应包装（app/schemas/common.py 的 success_response） */
interface ApiEnvelope<T> {
  success: boolean
  code: number
  message: string
  data: T
}

export interface TaskRecord {
  id: number
  title: string
  user_id: number
  scene_id: string
  version: string
  status: string
  created_at: string
  updated_at: string
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
    // 非 JSON（网关错误页、后端没起）：按 HTTP 状态报，别把解析失败说成业务失败
    throw new Error(`HTTP ${resp.status}`)
  }
  if (!resp.ok || !body.success) {
    throw new Error(body.message || `HTTP ${resp.status}`)
  }
  return body.data
}

export function createTask(payload: {
  title: string
  scene_id: string
  version?: string
  status?: string
}): Promise<TaskRecord> {
  return call<TaskRecord>('/api/v1/tasks', { method: 'POST', body: JSON.stringify(payload) })
}

/** 只传要改的字段：后端按 exclude_unset 更新，没传的不动 */
export function updateTask(id: number, patch: Partial<Pick<TaskRecord, 'title' | 'scene_id' | 'version' | 'status'>>): Promise<TaskRecord> {
  return call<TaskRecord>(`/api/v1/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(patch) })
}

export function getTask(id: number): Promise<TaskRecord> {
  return call<TaskRecord>(`/api/v1/tasks/${id}`)
}

/* ------------------------------------------------- 本场景包记住的任务号

   任务号存本地不是为了「保存数据」（数据在服务端），而是为了刷新后知道
   该去读哪一条。按场景包分开存：换产品等于换任务，不能串。
   读写一律包 try/catch：隐私模式下 localStorage 会直接抛。 */

const LS_KEY = 'omnitest.taskId.v1'

function storeKey(sceneId: string) {
  return `${LS_KEY}.${sceneId}`
}

export function readStoredTaskId(sceneId: string): number | null {
  try {
    const raw = localStorage.getItem(storeKey(sceneId))
    const n = Number(raw)
    return raw && Number.isFinite(n) && n > 0 ? n : null
  } catch {
    return null
  }
}

export function writeStoredTaskId(sceneId: string, id: number | null) {
  try {
    if (id === null) localStorage.removeItem(storeKey(sceneId))
    else localStorage.setItem(storeKey(sceneId), String(id))
  } catch {
    /* 存不下就只在本会话有效，不报错、不影响渲染 */
  }
}
