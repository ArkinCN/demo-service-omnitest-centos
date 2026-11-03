import { useT } from '../../i18n'
/* ===========================================================================
   画板节点的统一外壳。

   外观口径与 DESIGN.md 第 3 节一致：节点就是一张 PanelCard——卡头 38（图标徽章 +
   14px 卡名 + 放大按钮），卡体放 CardArt 线条稿或几行事实，卡底一行连接态。
   画板不另起一套卡片样式，避免同一产品里出现两种卡。
   =========================================================================== */
import { createElement, type ReactNode } from 'react'
import { PanelCard, Tooltip, cn } from '../../components/ui'
import { CANVAS_NODE_ICON } from '../../app/icons'
import { CardArt } from '../../app/CardArt'
import type { CanvasNode } from '../../data/types'
import { CANVAS_NODE_META, LINK_STATE_TEXT, type CanvasLinkState } from './model'

/** 卡底事实行：键 ≤4 字、值 ≤10 字，整句进 tooltip 不进卡面 */
export type NodeFact = [string, string]

export function NodeFacts({ facts }: { facts: NodeFact[] }) {
  const uiT = useT()
  return (
    <div className="flex h-full flex-col justify-center gap-1.5 px-1">
      {facts.slice(0, 3).map(([k, v]) => (
        <div key={k} className="flex items-baseline gap-2 text-[12px] leading-none">
          <span className="w-[42px] shrink-0 text-t3">{uiT(k)}</span>
          {/* ⚠️ 值一律过 uiT（2026-10-15 改）。
              原先写的是 `['类型','输出','归属'].includes(k) ? uiT(v) : v` —— 只译这三个 key，
              导致 `['台架', '涵道逆风台架 · SK-20251218QPBB']` 这类**数据值**在英文界面下漏翻。
              现在两层词典（含机翻兜底）已就位，未命中的值 uiT 会原样返回，全量包裹是安全的。 */}
          <span className="num truncate text-t2">{uiT(v)}</span>
        </div>
      ))}
    </div>
  )
}

/**
 * 节点外壳。
 * state 只三态：已接入（主色）/ 未接入（中性灰）/ 异常（暗红），与工具条描边同口径。
 */
export function CanvasNodeShell({
  node,
  state,
  foot,
  onExpand,
  children,
}: {
  node: CanvasNode
  state?: CanvasLinkState
  /** 卡底右侧的一行弱注，例如接入形态或通道名 */
  foot?: string
  onExpand?: () => void
  children?: ReactNode
}) {
  const uiT = useT()

  const meta = CANVAS_NODE_META[node.type]
  return (
    <PanelCard
      className="h-full w-full"
      icon={createElement(CANVAS_NODE_ICON[node.type], { size: 13, strokeWidth: 1.9 })}
      title={uiT(node.label)}
      onExpand={onExpand}
      headerRight={
        meta.tag ? (
          <Tooltip content={uiT("{v1} · 经 MCP 服务接入", { v1: meta.sub })}>
            <span className="rounded-tpx bg-p50 px-1.5 py-0.5 text-[12px] leading-none text-p700">
              {meta.tag}
            </span>
          </Tooltip>
        ) : undefined
      }
      bodyClassName="p-2"
    >
      <div className="flex h-full min-h-0 flex-col">
        {/* 节点高度固定，内容超出时原先被硬切掉半行、且看不出还有下文。
            改成可滚 + 底部渐隐（DESIGN.md §3 卡内长列表口径），不写死绝对高度。 */}
        <div className="cv-node-scroll min-h-0 flex-1">
          {children ?? (node.card ? <CardArt id={node.card} /> : null)}
        </div>
        {state || foot ? (
          <div className="mt-1 flex shrink-0 items-center gap-1.5 text-[12px] leading-none text-t3">
            {state ? (
              <>
                <span
                  className={cn(
                    'h-[6px] w-[6px] shrink-0 rounded-full',
                    state === 'online' ? 'bg-p400' : state === 'fault' ? 'bg-alert' : 'bg-t3/40',
                  )}
                />
                <span>{uiT(LINK_STATE_TEXT[state])}</span>
              </>
            ) : null}
            {foot ? <span className="ml-auto truncate">{uiT(foot)}</span> : null}
          </div>
        ) : null}
      </div>
    </PanelCard>
  )
}
