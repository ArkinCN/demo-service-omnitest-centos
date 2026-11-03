/* ===========================================================================
   轮次产物（artifact）的公共类型与读取工具。

   2026-10-04 清理合并：此前「从一轮产物里按 artifact_kind 取 content」的逻辑
   散落在 6 个文件（snapshotApi / baselineApi / reportApi / adoptApi /
   flow-run/api / flow-report/assemble），每处各写一份匿名类型
   `{ artifact_kind?: string; content?: unknown }` 和一句
   `.find(a => a.artifact_kind === 'X')`。这不仅是 6 份重复，还因为各处
   手写字段名，踩过「后端对外字段是 artifact_kind 而非 kind」的坑（见
   snapshotApi 的注释）。抽成这里统一维护，改一次全站生效。

   类型口径（与 flow-run/api.ts 的 ArtifactKind 同源）：
   `getRun` 返回 `artifacts: unknown[]`，元素实际是后端 ArtifactRead 的 schema
   别名——对外字段是 `artifact_kind`（不是 `kind`），值走 `content`。
   =========================================================================== */

/** 后端轮次产物数组元素的实际形态（getRun 返回 unknown[]，这里给真类型） */
export interface ArtifactRef {
  artifact_kind?: string
  content?: unknown
}

/** 把 getRun 返回的 unknown[] 规整成带类型的产物数组 */
export function asArtifacts(artifacts: unknown[] | undefined | null): ArtifactRef[] {
  return (artifacts ?? []) as ArtifactRef[]
}

/**
 * 从一轮产物里按 kind 取第一份 content；没有则返回 undefined。
 *
 * @param artifacts getRun 返回的 artifacts（unknown[]）
 * @param kind 产物 kind（如 'config-snapshot' / 'verdict-table'）
 */
export function pickArtifact(
  artifacts: unknown[] | undefined | null,
  kind: string,
): unknown {
  return asArtifacts(artifacts).find((a) => a?.artifact_kind === kind)?.content
}

/** 把一轮产物摊平成 `kind → content` 的 Map（assemble 等需要一次取多份时用） */
export function artifactMap(artifacts: unknown[] | undefined | null): Map<string, unknown> {
  const m = new Map<string, unknown>()
  for (const a of asArtifacts(artifacts)) {
    if (a?.artifact_kind) m.set(a.artifact_kind, a.content)
  }
  return m
}
