import { useT } from '../../../i18n'
/** 画布上的单个节点。描边成形，不做实色填充，选中时切到强调色。 */
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { NODE_GROUPS } from '../lib/nodeCatalog'
import type { NodeGroupId } from '../types'

export interface FlowNodeData extends Record<string, unknown> {
  label: string
  type: string
  group: NodeGroupId
  paramCount: number
  hasEmbedded: boolean
}

export function WorkflowNodeCard({ data, selected }: NodeProps) {
  const uiT = useT()

  const d = data as FlowNodeData
  const meta = NODE_GROUPS[d.group] ?? NODE_GROUPS.unknown

  return (
    <div
      className="wf-node"
      data-selected={selected ? 'true' : 'false'}
      style={{ '--node-color': meta.color, '--node-fill': meta.fill } as React.CSSProperties}
    >
      <Handle type="target" position={Position.Left} className="wf-handle" />
      <div className="wf-node-title" title={uiT(d.label)}>
        {uiT(d.label)}
      </div>
      <div className="wf-node-sub">
        <span className="wf-node-group">{uiT(meta.label)}</span>
        {d.paramCount > 0 && <span className="wf-node-count">{d.paramCount} {uiT(" 项参数")}</span>}
        {d.hasEmbedded && <span className="wf-node-embed">{uiT("内嵌子流程")}</span>}
      </div>
      <Handle type="source" position={Position.Right} className="wf-handle" />
    </div>
  )
}
