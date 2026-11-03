import { useT } from '../i18n'
import { useMemo, useState, createElement } from 'react'
import { LayoutGrid, Layers, Network } from 'lucide-react'
import { useAppStore } from '../state/useAppStore'
import { CanvasHost, useFlowView } from '../features/canvas'
import { Button, Modal, Panel, PanelCard, PanelHeader, Segmented, cn } from '../components/ui'
import { CARD_LIB } from '../data/cards'
import type { CardId, CardInstance, FlowId, ScenePackage } from '../data/types'
import { getPanelCards, useRegistryVersion } from '../registry'
import { CARD_ICON } from './icons'
import { CardArt } from './CardArt'
import { ToolRail } from './ToolRail'

/** C 区 · 面板：一页只有一个 hero（首卡横跨两格），其余退后。 */

/**
 * 第三轮：画板为默认视图，网格降为备选。视图状态上提到 store.canvasView，
 * 按流程各存一份、人工选择持久到 localStorage；某条流程人没点过时，
 * 默认值读场景包的 ui.defaultView（由 scene.json 的 default_view 拼成），
 * 不写死在代码里。画板本体在 src/features/canvas/，自研 SVG 画布已整个下架。
 */
type View = 'canvas' | 'grid'

const cardIcon = (id: CardId, size = 13) =>
  createElement(CARD_ICON[id] ?? Layers, { size, strokeWidth: 1.9 })

/** 五卡版式：首卡 hero 横跨两列，其余四张填满第二行与右上角 */
function slotStyle(i: number, n: number): React.CSSProperties {
  if (n >= 5) {
    if (i === 0) return { gridColumn: '1 / span 2', gridRow: '1' }
    if (i === 1) return { gridColumn: '3', gridRow: '1' }
    return { gridColumn: String(i - 1), gridRow: '2' }
  }
  if (n === 4) {
    if (i === 0) return { gridColumn: '1 / span 2', gridRow: '1' }
    if (i === 1) return { gridColumn: '3', gridRow: '1' }
    if (i === 2) return { gridColumn: '1 / span 2', gridRow: '2' }
    return { gridColumn: '3', gridRow: '2' }
  }
  if (n === 3) {
    if (i === 0) return { gridColumn: '1 / span 2', gridRow: '1 / span 2' }
    return { gridColumn: '3', gridRow: String(i) }
  }
  return {}
}

export function ResourcePanel({ flow, scene }: { flow: FlowId; scene: ScenePackage }) {
  const uiT = useT()

  useRegistryVersion()
  // 人点过按人的，没点过按场景包的 ui.defaultView，场景包没给才落代码兜底
  const view = useFlowView(flow, scene)
  const setView = useAppStore((s) => s.setCanvasView)
  const [open, setOpen] = useState<CardInstance | null>(null)
  // 自动化运行态：只用来在面板角上挂一枚轻提示。
  // ⚠️ 真正的进度/结果全屏浮层在 Shell 层挂载（features/automation/AutomationRunOverlay），
  // 本组件**不再订阅 stages/currentStageId**——老实现订阅它们渲染「右上大屏」，
  // 且挂载条件就是 running，跑完立刻卸载，人看不到结果（2026-10-05 已退役）。
  const autoRunning = useAppStore((s) => s.automationRunStatus === 'running')

  const registered = useMemo(() => getPanelCards(flow), [flow])
  const regById = useMemo(() => new Map(registered.map((r) => [r.id, r])), [registered])
  const content = scene.flows[flow]

  // 卡槽以场景包的 content.cards 为准：有几张铺几张（slotStyle 支持 3 / 4 / 5 三种版式）。
  // 第三轮起不再拿「注册过但没进卡槽」的卡回填到 5 格——否则 loadScene.ts 里删掉的卡
  // （流程 3 的原理图与安全联锁状态盘、流程 4 的判定卡）会被自动补回屏幕。
  // 没进卡槽的卡仍可取用，入口在卡头的「换卡」下拉里。
  const slots: CardInstance[] = content.cards
  const spare: CardInstance[] = useMemo(
    () =>
      registered
        .filter((r) => !content.cards.some((c) => c.id === r.id))
        .map((r) => ({ id: r.id as CardId })),
    [content, registered],
  )

  const GRID_SLOTS = 5
  const [swapped, setSwapped] = useState<Record<string, CardId>>({})
  const pool = useMemo(() => [...slots, ...spare], [slots, spare])
  const gridSlots = useMemo(() => {
    const base = slots.slice(0, GRID_SLOTS)
    return base.map((c) => {
      const to = swapped[c.id]
      return to ? (pool.find((x) => x.id === to) ?? c) : c
    })
  }, [slots, pool, swapped])
  const shown = new Set(gridSlots.map((c) => c.id))
  const hidden = pool.filter((c) => !shown.has(c.id))
  const swap = (from: CardId, to: CardId) => setSwapped((m) => ({ ...m, [from]: to }))

  const renderCard = (id: CardId) => {
    const reg = regById.get(id)
    return reg ? reg.render({ flow, scene }) : <CardArt id={id} />
  }

  return (
    /* relative：给运行态角标做定位基准（Panel 自身没有 relative） */
    <Panel className="relative">
      {/* 自动化运行态轻提示：真正的进度/结果由全屏浮层（Shell 层挂载）承担。
          这里只留一枚角标，让「面板本身」也知道正在跑，不与浮层抢信息。 */}
      {autoRunning ? (
        <div className="pointer-events-none absolute right-3 bottom-3 z-10 flex items-center gap-1.5 rounded-full border border-ink bg-surface/95 px-2.5 py-1 text-[11.5px] text-t2 shadow-tp2">
          <span className="automation-pulse h-[6px] w-[6px] rounded-full bg-ink" />
          {uiT("自动化测试进行中")}</div>
      ) : null}
      <PanelHeader
        icon={<Layers size={17} strokeWidth={1.9} />}
        title={uiT("面板")}
        right={
          <Segmented
            ariaLabel={uiT("面板视图")}
            value={view}
            onChange={(v) => setView(flow, v as View)}
            items={[
              { value: 'canvas', label: '画板', icon: <Network size={13} strokeWidth={1.9} /> },
              { value: 'grid', label: '网格', icon: <LayoutGrid size={13} strokeWidth={1.9} /> },
            ]}
          />
        }
      />

      <div className="flex min-h-0 flex-1">
        {view === 'grid' ? (
          <div
            className="min-h-0 flex-1 overflow-hidden"
            style={{ padding: 'clamp(12px, 1.05vw, 20px)' }}
          >
            {/* 窄屏自适应（2026-10-15）：加 panel-grid-scroll 钩子。
                堆叠档（≤860px）右列只拿到容器高的 8/13，本容器可用高从约 500px
                掉到约 150px，而网格行高下限就占了 220+140=360px，**实测越出 118px、
                卡片下半截被裁**。B3 档由 index.css 给它 overflow-y:auto ——
                溢出部分可滚动查看，符合「不裁切」的验收口径；宽屏保持原观感。
                ⚠️ 挂在这一层（而不是外层 padding 容器）才有效：滚动容器必须是
                   高度确定且**直接包住网格**的那一个，否则网格的溢出内容不参与
                   外层 scrollHeight 的计算，加了也不会出现滚动条。
                ⚠️ 网格行高下限本身**不能动**：其注释写明是「宁可溢出也不把图表
                   压没」的有意取舍（2026-10-09），动它会让绘图区重新变成一条缝。 */}
            <div
              key={flow}
              className="panel-grid-scroll grid h-full"
              style={{
                gap: 'clamp(12px, 0.9vw, 16px)',
                gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
                // 行高给下限（2026-10-09）：原 '1.4fr 1fr' 在矮视口下被算成 73px/52px，
                // hero 卡只剩 136px，绘图区 21px —— 曲线与三根纵轴全都看不见
                //（实测 tooltip 都抓不到）。220px 是「卡头 + 读数行 + 三轴 + 底部滑块」
                // 的最小可读高度；容器不够高时它会溢出，而不是把图表压没。
                gridTemplateRows: 'minmax(220px, 1.4fr) minmax(140px, 1fr)',
              }}
            >
              {gridSlots.map((c, i) => (
                <PanelCard
                  key={c.id}
                  icon={cardIcon(c.id, i === 0 ? 14 : 13)}
                  title={uiT(c.title ?? CARD_LIB[c.id]?.title ?? regById.get(c.id)?.label ?? c.id)}
                  stamp={c.stamp}
                  active={c.active}
                  hero={i === 0}
                  alert={c.alert}
                  style={{ ...slotStyle(i, gridSlots.length), animationDelay: `${i * 45}ms` }}
                  onExpand={() => setOpen(c)}
                  onSwap={hidden.length ? (id) => swap(c.id, id as CardId) : undefined}
                  swapOptions={hidden.map((h) => ({
                    value: h.id,
                    label: CARD_LIB[h.id]?.title ?? regById.get(h.id)?.label ?? h.id,
                  }))}
                >
                  {renderCard(c.id)}
                </PanelCard>
              ))}
            </div>
          </div>
        ) : (
          // 统一画板：滚轮缩放、拖拽平移、工具条拖入建节点、节点放大态，
          // 本体在 src/features/canvas/CanvasHost.tsx。
          <CanvasHost flow={flow} scene={scene} />
        )}
        <ToolRail groups={scene.toolGroups} />
      </div>

      <Modal
        open={!!open}
        onClose={() => setOpen(null)}
        width={1220}
        title={open ? uiT(open.title ?? CARD_LIB[open.id]?.title ?? open.id) : ''}
        meta={open?.summary}
        footer={
          <>
            <Button size="sm" variant="ghost" onClick={() => setOpen(null)}>
              {uiT("关闭")}</Button>
            <Button size="sm" variant="secondary">
              {uiT("在新窗口打开")}</Button>
            <Button size="sm" variant="primary">
              {uiT("固定到卡槽")}</Button>
          </>
        }
      >
        <div className={cn('flex h-[min(64vh,470px)] items-center justify-center rounded-tp2 bg-p50 p-2')}>
          {open ? (
            regById.get(open.id) ? (
              (regById.get(open.id)!.renderExpanded ?? regById.get(open.id)!.render)({ flow, scene })
            ) : (
              <div className="h-[min(56vh,400px)] w-[620px]">
                <CardArt id={open.id} />
              </div>
            )
          ) : null}
        </div>
      </Modal>
    </Panel>
  )
}
