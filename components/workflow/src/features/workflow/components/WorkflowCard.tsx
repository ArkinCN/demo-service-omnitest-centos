/** 面板用紧凑卡片：名称、节点数、电压档，加一条按分组配色的缩略条。 */
import { useMemo } from 'react'
import { NODE_GROUPS } from '../lib/nodeCatalog'
import type { NodeGroupId, WorkflowIndexEntry, WorkflowModel } from '../types'

export interface WorkflowCardProps {
  entry: WorkflowIndexEntry
  /** 已加载的模型，用于画缩略图；未加载时只显示索引里的节点数。 */
  model?: WorkflowModel | null
  active?: boolean
  onOpen?: (entry: WorkflowIndexEntry) => void
}

export function WorkflowCard({ entry, model, active = false, onOpen }: WorkflowCardProps) {
  // 缩略图：按分组统计节点占比，画成一条分段色带，成本远低于渲染真图。
  const segments = useMemo(() => {
    if (!model) return []
    const tally = new Map<NodeGroupId, number>()
    for (const n of model.nodes) tally.set(n.group, (tally.get(n.group) ?? 0) + 1)
    const total = model.nodes.length || 1
    return [...tally.entries()]
      .sort((a, b) => (NODE_GROUPS[a[0]]?.order ?? 99) - (NODE_GROUPS[b[0]]?.order ?? 99))
      .map(([group, count]) => ({
        group,
        pct: (count / total) * 100,
        color: NODE_GROUPS[group]?.color ?? '#9a9a9a',
        label: NODE_GROUPS[group]?.label ?? group,
        count,
      }))
  }, [model])

  return (
    <button
      type="button"
      className="wf-card"
      data-active={active ? 'true' : 'false'}
      onClick={() => onOpen?.(entry)}
      title={entry.file}
    >
      <div className="wf-card-top">
        <span className="wf-card-name">{entry.name}</span>
        <span className="wf-card-volt" data-volt={entry.voltage}>
          {entry.voltage}
        </span>
      </div>
      <div className="wf-card-meta">
        <span>{entry.nodeCount} 节点</span>
        <span className="wf-card-dot">·</span>
        <span>{entry.edgeCount} 连线</span>
        {entry.isSubflow && <span className="wf-card-tag">子流程</span>}
      </div>
      <div className="wf-card-thumb" aria-hidden={segments.length === 0}>
        {segments.length === 0 ? (
          <div className="wf-card-thumb-empty" />
        ) : (
          segments.map((s) => (
            <span
              key={s.group}
              style={{ width: `${s.pct}%`, background: s.color }}
              title={`${s.label} ${s.count}`}
            />
          ))
        )}
      </div>
    </button>
  )
}
