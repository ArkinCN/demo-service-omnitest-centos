/* ===========================================================================
   采纳落库：把「人勾了哪几条建议值、由谁、什么时候」写进服务端。

   为什么必须落库：此前 `adoptedApplied` 只活在前端 store 里，刷新即丢——
   主文档阶段 3 验收「人采纳后保存，刷新后仍在」这一条因此一直过不了。
   数据记在服务端，界面只是它的一份展示。

   为什么挂轮次而不另起一张表：主文档 4.1 的收发关系表已经把
   `param-change`（参数改动版本）定为 **tune 流程的产物**，挂在某一轮上。
   轮次产物那套接口（PUT /api/runs/{id}/{kind}）也已经实现并验证过，
   所以这里**后端零改动**，只复用 flow-run/api.ts 现成的三个函数。

   两条纪律：
     一、**刷新后要能读回**，所以读回不依赖内存里的 runId——按场景取最近
         一轮即可（见 resolveRunId）；
     二、**落库失败必须让人看见**。调用方负责把错误显示出来，这里只管抛，
         绝不 catch 空了假装成功（上一阶段最严重的问题就是这个）。
   =========================================================================== */
import { getRun, listRuns, putArtifact } from '../flow-run/api'
import { pickArtifact } from '../shared/artifacts'

export interface AdoptedItem {
  key: string
  name: string
  from: string
  to: string
  /** 参数所属分组（如 'cp' 下的具体分组名），随采纳数据自包含，供写回时拼 run.cp 键 */
  group: string
}

/** param-change 产物里我们写的内容形态 */
export interface ParamChangeContent {
  items: AdoptedItem[]
  count: number
  operator: string
  adopted_at: string
  /** 如实标注还没做的事，不让下游把这份记录当成「已写回设备」 */
  note: string
}

/**
 * 定出采纳该挂在哪一轮。
 *
 * 优先用本会话记住的 runId；没有（比如刷新过）就按场景取最近一轮——
 * 这是真实的「最近一轮」，不是编一个。一轮都没有就抛错，由调用方显示，
 * 不悄悄降级成「存到本地」：那等于又把数据放回了刷新即丢的地方。
 *
 * ⚠️ 这里**取最新一轮是对的**（写入场景：新建的产物该挂在本轮），
 * 与 `loadAdoption` 的「向前找产物」不同——两者方向相反是刻意的：
 *   - 写：挂到当前这一轮（最近的代表当下）
 *   - 读：沿历史往前找最近一份写了该产物的轮次
 * 不要为了「统一」把两者改成一样，那会把写入挂到很旧的轮次上。
 */
export async function resolveRunId(sceneId: string, runId: string | null): Promise<string> {
  if (runId) return runId
  const runs = await listRuns(sceneId, 1)
  if (!runs.length) {
    throw new Error('本场景还没有落过轮次，采纳无处可挂（先在流程 3 跑完一轮）')
  }
  return runs[0].run_id
}

/** 写一份 param-change。同 run + kind 后端是覆盖语义，重复采纳不会堆出两条。 */
export async function persistAdoption(opts: {
  sceneId: string
  runId: string | null
  items: AdoptedItem[]
  operator: string
  /** 落库附言；回滚时传「已回滚」这类话，与采纳的默认措辞区分开 */
  note?: string
}): Promise<{ runId: string; count: number }> {
  const runId = await resolveRunId(opts.sceneId, opts.runId)
  const content: ParamChangeContent = {
    items: opts.items,
    count: opts.items.length,
    operator: opts.operator,
    adopted_at: new Date().toISOString(),
    note:
      opts.note ??
      '采纳记录：人勾选的建议值。这里只记「采纳了什么」，不含写回设备的动作——写回是红线动作，另走确认卡。',
  }
  await putArtifact(runId, 'param-change', content)
  return { runId, count: opts.items.length }
}

/**
 * 读回本场景最近一份采纳记录。
 *
 * ⚠️ **必须向前遍历若干轮，不能只看最新一轮**（2026-09-28 实测修）。
 *
 * 原实现是 `listRuns(sceneId, 1)` 取最新一轮，再在里面找 `param-change`。
 * 这隐含一个错误假设——「最新一轮必然带我要的产物」。但按契约
 * （主文档 4.1：**一轮带多份产物**，且各流程各自落各自的），
 * 一个场景里完全可能「最新一轮只有 config-snapshot，而 param-change 在上一轮」：
 * 例如人在初始化页又按了一次「确认并锁定」，就会新建一轮只带快照，
 * 于是采纳记录明明在库，界面却读不出来。
 *
 * 实测证据：某次运行后 12 轮里 `param-change` 在第 3 轮（`6cee241d`），
 * 前两轮（`75bf9e92` / `b081fd02`）只有 `config-snapshot` →
 * 旧实现在最新一轮找不到就返回空，表现为「采纳过的项刷新后全没了」。
 *
 * 现在与 `flow-req/baselineApi.ts` 的 `loadLatestBaseline` 同款：
 * 按场景取最近若干轮，**逐轮找**目标产物，取到第一份就用。
 * 没有轮次 / 都没写过 → 返回空数组（「还没采纳过」的正常态，不是错误）。
 */
export async function loadAdoption(sceneId: string): Promise<{
  items: AdoptedItem[]
  runId: string | null
}> {
  const runs = await listRuns(sceneId, 10)
  if (!runs.length) return { items: [], runId: null }
  for (const r of runs) {
    try {
      const { artifacts } = await getRun(r.run_id)
      const hit = pickArtifact(artifacts, 'param-change')
      if (hit === undefined) continue
      const items = (hit as ParamChangeContent | null)?.items ?? []
      // ⚠️ 找到产物就返回它**所在的轮次**，不是最新轮——
      // 下游（`applyAdopt` 与顶栏回显）要用这个 runId 才有意义。
      return { items, runId: r.run_id }
    } catch {
      // 某一轮读不到就跳过，继续看下一轮
      continue
    }
  }
  return { items: [], runId: runs[0].run_id }
}
