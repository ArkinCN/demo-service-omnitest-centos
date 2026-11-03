/* ===========================================================================
  需求基线 requirement-baseline/v1 —— req 流程的产物。

  为什么要有它（本轮补的是一个**真实缺口**）：
  流程 2（测试需求确认）的勾选基线此前只存在 `flow-req/panel.tsx` 的
  模块级变量 `sel.ids` 里——**纯内存**。翻页或刷新就回到「全选」默认值，
  人取消勾选的「移出本轮」动作**从来没离开过浏览器**。
  这与流程 1（初始化）的 config-snapshot 是同一个毛病，只是当时只修了前者。

  契约（主文档 4.1「artifact_kind 取七值」）：
    requirement-baseline(req) → tune/report，schema = requirement-baseline/v1。
  后端 `ARTIFACT_SCHEMAS` 早已登记，PUT /api/runs/{id}/requirement-baseline
  一直可用——**只是前端从未调用过**。

  两条纪律：
    一、**不冒充**。基线的判据内容（阈值、分类、可否自动求值）属于场景包，
       本产物只记「本轮纳入哪几条 + 落库时刻」，不复制一份判据定义
       （复制会产生第二份真相，场景包一改就对不上）。
    二、**落库失败必须让人看见**。调用方负责显示错误，这里只管抛，
       绝不 catch 空了假装成功。
   =========================================================================== */
import { getRun, listRuns, putArtifact, createRun } from '../flow-run/api'
import { pickArtifact } from '../shared/artifacts'

/** 契约 requirement-baseline/v1 的内容形态 */
export interface RequirementBaseline {
  schema: 'requirement-baseline/v1'
  scene_id: string
  /** 本轮纳入基线的判据 id（勾选框勾上的那些） */
  included_ids: string[]
  /** 本轮纳入的条数（与 included_ids.length 一致，便于人肉核对） */
  included_count: number
  /** 场景包判据总数（含被移出的） */
  total_count: number
  locked_at: string
  locked_by: string
}

/**
 * 把基线挂到轮次上。
 *
 * 为什么优先复用已有轮次而不是每次新建：
 * 流程 1 的「确认并锁定」已经建过一轮（配置快照挂在那轮上）。需求基线
 * 按契约是**同一轮**的产物（主文档 4.1 收发关系表：一份轮次带多份产物）。
 * 每次点确认都新建一轮会让「本轮」这个概念糊掉，且刷新读回时要面对
 * 一堆空轮次。所以：**有轮次就复用，没有才新建**（与 adoptApi.resolveRunId 同款）。
 */
export async function resolveBaselineRunId(sceneId: string, runId: string | null): Promise<string> {
  if (runId) return runId
  const runs = await listRuns(sceneId, 1)
  if (runs.length) return runs[0].run_id
  // 一轮都没有（人直接从流程 2 进来、没走过初始化页）：
  // 如实建一轮，而不是拒绝——否则「确认基线」在这个路径下永远点不动。
  const run = await createRun(sceneId, 'mock')
  return run.run_id
}

/** 写一份需求基线。同 run + kind 后端是覆盖语义，重复确认不会堆出两条。 */
export async function persistBaseline(opts: {
  sceneId: string
  runId: string | null
  includedIds: string[]
  totalCount: number
  operator: string
}): Promise<{ runId: string; baseline: RequirementBaseline }> {
  const runId = await resolveBaselineRunId(opts.sceneId, opts.runId)
  const baseline: RequirementBaseline = {
    schema: 'requirement-baseline/v1',
    scene_id: opts.sceneId,
    // 排序后再落：Set 的迭代顺序随插入顺序变化，不排会让「同样的勾选」
    // 每次落出不同的数组，覆盖比对与 diff 都会误报。
    included_ids: [...opts.includedIds].sort(),
    included_count: opts.includedIds.length,
    total_count: opts.totalCount,
    locked_at: new Date().toISOString(),
    locked_by: opts.operator,
  }
  await putArtifact(runId, 'requirement-baseline', baseline)
  return { runId, baseline }
}

/**
 * 读回最近一份需求基线。
 *
 * 与 loadLatestSnapshot 同款思路：**不依赖内存**，按场景取最近若干轮，
 * 逐轮找 requirement-baseline。返回 null = 还没确认过（正常态，不是故障）。
 *
 * ⚠️ 必须校验 schema 与 included_ids 是数组：老轮次里没有这份产物，
 * 或将来 shape 变了，拿它回填会把勾选态清空——比不回填更难查。
 */
export async function loadLatestBaseline(
  sceneId: string,
): Promise<{ baseline: RequirementBaseline; runId: string } | null> {
  const runs = await listRuns(sceneId, 10)
  for (const r of runs) {
    try {
      const { artifacts } = await getRun(r.run_id)
      const body = pickArtifact(artifacts, 'requirement-baseline') as RequirementBaseline | undefined
      if (
        body &&
        body.schema === 'requirement-baseline/v1' &&
        Array.isArray(body.included_ids)
      ) {
        return { baseline: body, runId: r.run_id }
      }
    } catch {
      // 某一轮读不到就跳过，继续看下一轮
      continue
    }
  }
  return null
}
