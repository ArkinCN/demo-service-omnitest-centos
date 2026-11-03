/* ===========================================================================
  需求基线的「最近一次确认」内存镜像（修「流程 2 确认 → 流程 3 不生效」）。

  为什么需要它（本轮补的是一个**真实断点**）：
  流程 2 的「确认基线」会把 included_ids 落进服务端 `requirement-baseline` 产物，
  流程 2 自己刷新也能读回勾选框。但**流程 3 从来不读这份产物**：
  `evaluateAll(pack, ...)` 直接对场景包全量判据求值，与「本轮纳入哪几条」无关。
  表现是「流程 2 取消了 14 条，流程 3 照样判 20 条」——看似流通，实则断在消费端。

  为什么用模块级镜像而不是再读一次服务端：
  流程 3 需要**同步**拿到这个集合来决定判据行（渲染期求值，不能 await）。
  与 `snapshotValues` 之于流程 3 控制参数是同一套做法：
    - 写入方（流程 2 的确认 / 读回）把结果同步一份到这里；
    - 消费方（流程 3）渲染期同步读它。
  服务端仍是权威（刷新后由 `useRestoreBaseline` 再灌一次）。

  三条纪律：
    一、**null ≠ 空集**。`null` = 本会话还没读到过基线（**不做过滤，判全表**，
        这是旧行为，向后兼容）；`[]` = 基线明说「一条都不纳入」（**真的判 0 条**）。
        把两者混为一谈会让「首次进入没确认过」和「确认了 0 条」显示成一样。
    二、**只读，不改**（消费方只 get）。
    三、**不冒充**：没读到就如实返回 null，不用场景包全量条数顶替成「已按基线判」。
   =========================================================================== */

let includedIds: string[] | null = null
const listeners = new Set<() => void>()

/** 写入方调用：流程 2 确认落库后、以及刷新读回后，各灌一次 */
export function setBaselineIds(ids: string[] | null): void {
  includedIds = ids
  listeners.forEach((l) => l())
}

/** 供 React 订阅（`useSyncExternalStore` 的快照读法） */
export function getBaselineIds(): string[] | null {
  return includedIds
}

export function subscribeBaseline(l: () => void): () => void {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

export function resetBaselineIds(): void {
  setBaselineIds(null)
}
