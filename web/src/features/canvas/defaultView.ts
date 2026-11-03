/* ===========================================================================
   C 区默认视图：画板还是网格，由场景包说了算，不写死在代码里。

   取数口径：public/scenes/<sceneId>/scene.json 的 `default_view` 段，
   形如 {"init":"canvas","req":"canvas","run":"grid","tune":"grid","report":"grid"}。
   收尾轮（W6）把它拼进了 ScenePackage.ui.defaultView（src/data/loadScene.ts 的
   adaptScene()），本文件因此不再自己 fetch 一次 scene.json——同一份 JSON 读两遍
   那笔账已经平掉。场景包没给、或给的值不认识时落到 FALLBACK_DEFAULT_VIEW。

   优先级：人手点过的流程（store.canvasView[flow]）> 场景包 > 兜底。
   人工选择由 store 持久到 localStorage，本文件不再另存一份模块级 Map。
   =========================================================================== */
import type { FlowId, ScenePackage } from '../../data/types'
import { useAppStore, type PanelView } from '../../state/useAppStore'

export type { PanelView }

/** 场景包没给 default_view 时的兜底，理由见《第三轮需求变更方案 v0.1》第 2.5 节那张表 */
export const FALLBACK_DEFAULT_VIEW: Record<FlowId, PanelView> = {
  init: 'canvas',
  req: 'canvas',
  run: 'grid',
  tune: 'grid',
  report: 'grid',
}

/** 场景包下发的默认视图，取不到就兜底 */
export const defaultViewOf = (flow: FlowId, scene?: ScenePackage): PanelView =>
  scene?.ui?.defaultView?.[flow] ?? FALLBACK_DEFAULT_VIEW[flow]

/**
 * 当前该显示哪个视图：人点过按人的，没点过按场景包，场景包没给按兜底。
 * 纯读，不写 store——所以切页不会有「默认值把人的选择盖回去」那一闪。
 */
export function useFlowView(flow: FlowId, scene: ScenePackage): PanelView {
  const picked = useAppStore((s) => s.canvasView[flow])
  return picked ?? defaultViewOf(flow, scene)
}
