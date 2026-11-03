/** 右侧属性抽屉：把节点 params 摊成键值表，标量可就地编辑。 */
import { useMemo, useState } from 'react'
import { NODE_GROUPS } from '../lib/nodeCatalog'
import type { ParamValue, WorkflowNode } from '../types'

export interface PropertyDrawerProps {
  node: WorkflowNode | null
  readonly?: boolean
  onParamChange?: (nodeId: string, key: string, value: ParamValue) => void
  onLabelChange?: (nodeId: string, label: string) => void
}

type Row = { key: string; value: ParamValue; editable: boolean }

function classify(value: ParamValue): 'number' | 'boolean' | 'string' | 'complex' {
  if (typeof value === 'number') return 'number'
  if (typeof value === 'boolean') return 'boolean'
  if (typeof value === 'string') return 'string'
  return 'complex'
}

function preview(value: ParamValue): string {
  if (value === null) return 'null'
  if (Array.isArray(value)) return `数组 · ${value.length} 项`
  if (typeof value === 'object') return `对象 · ${Object.keys(value as object).length} 个字段`
  return String(value)
}

export function PropertyDrawer({
  node,
  readonly = false,
  onParamChange,
  onLabelChange,
}: PropertyDrawerProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const rows = useMemo<Row[]>(() => {
    if (!node) return []
    return Object.entries(node.params)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, value]) => ({ key, value, editable: classify(value) !== 'complex' }))
  }, [node])

  if (!node) {
    return (
      <aside className="wf-drawer">
        <div className="wf-drawer-empty">在画布上点选一个节点查看配置</div>
      </aside>
    )
  }

  const meta = NODE_GROUPS[node.group] ?? NODE_GROUPS.unknown

  function toggle(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  return (
    <aside className="wf-drawer">
      <header className="wf-drawer-head">
        <span className="wf-chip" style={{ borderColor: meta.color, color: meta.color }}>
          {meta.label}
        </span>
        {readonly ? (
          <h2 className="wf-drawer-title">{node.label}</h2>
        ) : (
          <input
            className="wf-drawer-title-input"
            value={node.label}
            onChange={(e) => onLabelChange?.(node.id, e.target.value)}
            aria-label="节点名称"
          />
        )}
        <code className="wf-drawer-type">{node.type}</code>
      </header>

      {node.embedded && (
        <div className="wf-drawer-note">
          内嵌子流程：{node.embedded.nodes.length} 节点 / {node.embedded.edges.length} 连线
        </div>
      )}

      {rows.length === 0 ? (
        <div className="wf-drawer-empty">该节点没有额外参数</div>
      ) : (
        <dl className="wf-params">
            {rows.map(({ key, value, editable }) => {
              const kind = classify(value)
              return (
                <div className="wf-param" key={key}>
                  <dt title={key}>{key}</dt>
                  <dd>
                    {kind === 'number' && (
                      <input
                        type="number"
                        className="wf-input"
                        value={value as number}
                        disabled={readonly}
                        onChange={(e) =>
                          onParamChange?.(
                            node.id,
                            key,
                            e.target.value === '' ? '' : Number(e.target.value),
                          )
                        }
                      />
                    )}
                    {kind === 'boolean' && (
                      <input
                        type="checkbox"
                        className="wf-checkbox"
                        checked={value as boolean}
                        disabled={readonly}
                        onChange={(e) => onParamChange?.(node.id, key, e.target.checked)}
                      />
                    )}
                    {kind === 'string' && (
                      <input
                        type="text"
                        className="wf-input"
                        value={value as string}
                        disabled={readonly}
                        onChange={(e) => onParamChange?.(node.id, key, e.target.value)}
                      />
                    )}
                    {!editable && (
                      <button
                        type="button"
                        className="wf-expand"
                        onClick={() => toggle(key)}
                        aria-expanded={expanded.has(key)}
                      >
                        {preview(value)}
                      </button>
                    )}
                    {!editable && expanded.has(key) && (
                      <pre className="wf-json">{JSON.stringify(value, null, 2)}</pre>
                    )}
                  </dd>
                </div>
              )
            })}
        </dl>
      )}
    </aside>
  )
}
