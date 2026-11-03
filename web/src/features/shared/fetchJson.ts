/* ===========================================================================
   场景包 / 静态 JSON 的统一取数入口（2026-10-08 新增）。

   背景（真实踩过的坑）：原先各处直接用 `fetch(url, { cache: 'force-cache' })`。
   `force-cache` 的语义是**优先使用浏览器缓存副本，即使它已过期**，于是：

     · 改了 public/scenes/**.json、重启前后端 → 界面毫无变化；
     · 排查半天以为是代码没生效，其实是浏览器一直在读旧副本。

   现在的策略（按环境分档）：
     · 开发态（`import.meta.env.DEV`）→ `default`：走标准 HTTP 缓存语义，
       带 ETag/Last-Modified 时浏览器会发条件请求，文件变了立刻拿到新内容，
       文件没变则命中 304，仍比每次全量下载省。
     · 构建产物 → `force-cache`：演示/离线场景下优先用缓存，避免无谓网络往返。

   为什么要抽成一处：此前 6 个文件各写一遍 fetch 选项，改策略要改 6 处、
   漏一处就出现"有的文件更新了有的没更新"的诡异现象。集中一处可保证口径一致。

   诚实边界：不吞错误——取不到就返回 null，由调用方决定怎么显示（与各调用点
   既有行为一致，都是"取不到 → 返回 null → 界面按缺省处理"）。
   =========================================================================== */

/** 静态 JSON 的缓存策略：开发态可感知更新，构建产物走强缓存。 */
const CACHE_MODE: RequestCache = import.meta.env.DEV ? 'default' : 'force-cache'

/**
 * 取一份静态 JSON。失败（网络错 / 非 2xx / 解析失败）一律返回 null，
 * 不抛错——调用点全部按「可能没有这份数据」设计（场景包、知识库均可选）。
 */
export async function fetchJson<T = unknown>(url: string): Promise<T | null> {
  try {
    const r = await fetch(url, { cache: CACHE_MODE })
    if (!r.ok) return null
    return (await r.json()) as T
  } catch (e) {
    console.error('[fetchJson] 取数失败：', url, e)
    return null
  }
}
