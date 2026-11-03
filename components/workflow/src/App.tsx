/** Demo 页：左侧按业务分组折叠的工作流列表，中间画布，右侧属性抽屉。 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  PropertyDrawer,
  WorkflowCanvas,
  WorkflowCard,
  exportJson,
  groupEntries,
  listWorkflows,
  loadWorkflow,
  type ParamValue,
  type WorkflowIndexEntry,
  type WorkflowModel,
  type WorkflowNode,
} from './features/workflow'
import './features/workflow/styles/workflow.css'

/** 默认打开 StaticStart 的 HV 档主流程。 */
const DEFAULT_FILE = 'main/StaticStart/HV/HV_StaticStart.wfw'

export default function App() {
  const [entries, setEntries] = useState<WorkflowIndexEntry[]>([])
  const [active, setActive] = useState<WorkflowIndexEntry | null>(null)
  const [model, setModel] = useState<WorkflowModel | null>(null)
  const [selected, setSelected] = useState<WorkflowNode | null>(null)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [readonly, setReadonly] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listWorkflows()
      .then((list) => {
        setEntries(list)
        const start = list.find((e) => e.file === DEFAULT_FILE) ?? list[0] ?? null
        setActive(start)
        // 默认只展开起始工作流所在的分组，其余折叠。
        setCollapsed(new Set(list.map((e) => e.group).filter((g) => g !== start?.group)))
      })
      .catch((e) => setError(String(e.message ?? e)))
  }, [])

  useEffect(() => {
    if (!active) return
    setSelected(null)
    setModel(null)
    loadWorkflow(active)
      .then(setModel)
      .catch((e) => setError(String(e.message ?? e)))
  }, [active])

  const groups = useMemo(() => groupEntries(entries), [entries])

  const handleParamChange = useCallback((nodeId: string, key: string, value: ParamValue) => {
    setModel((prev) =>
      prev
        ? {
            ...prev,
            nodes: prev.nodes.map((n) =>
              n.id === nodeId ? { ...n, params: { ...n.params, [key]: value } } : n,
            ),
          }
        : prev,
    )
    setSelected((prev) =>
      prev && prev.id === nodeId ? { ...prev, params: { ...prev.params, [key]: value } } : prev,
    )
  }, [])

  const handleLabelChange = useCallback((nodeId: string, label: string) => {
    setModel((prev) =>
      prev ? { ...prev, nodes: prev.nodes.map((n) => (n.id === nodeId ? { ...n, label } : n)) } : prev,
    )
    setSelected((prev) => (prev && prev.id === nodeId ? { ...prev, label } : prev))
  }, [])

  const handleExport = useCallback(() => {
    if (!model || !active) return
    const blob = new Blob([exportJson(model)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${active.name}.json`
    a.click()
    URL.revokeObjectURL(url)
  }, [model, active])

  function toggleGroup(group: string) {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(group)) next.delete(group)
      else next.add(group)
      return next
    })
  }

  return (
    <div className="wf-root">
      <nav className="wf-sidebar">
        <h1 className="wf-sidebar-head">工作流库</h1>
        <p className="wf-sidebar-sub">
          {entries.length} 个流程 · {entries.filter((e) => e.isSubflow).length} 个子流程
        </p>
        {groups.map(({ group, items }) => {
          const open = !collapsed.has(group)
          return (
            <section className="wf-group" key={group}>
              <button
                type="button"
                className="wf-group-head"
                onClick={() => toggleGroup(group)}
                aria-expanded={open}
              >
                <span>
                  {open ? '▾' : '▸'} {group}
                </span>
                <span className="wf-group-count">{items.length}</span>
              </button>
              {open && (
                <div className="wf-group-body">
                  {items.map((entry) => (
                    <WorkflowCard
                      key={entry.file}
                      entry={entry}
                      model={active?.file === entry.file ? model : null}
                      active={active?.file === entry.file}
                      onOpen={setActive}
                    />
                  ))}
                </div>
              )}
            </section>
          )
        })}
      </nav>

      <main className="wf-main">
        <header className="wf-main-head">
          <h2 className="wf-main-title">{active?.name ?? '未选择'}</h2>
          {model && (
            <span className="wf-main-meta">
              {model.nodes.length} 节点 · {model.edges.length} 连线 · 格式 v{model.meta.formatVersion}
              {model.meta.compressed ? ' · gzip' : ''}
            </span>
          )}
          <div className="wf-main-actions">
            <button
              type="button"
              className="wf-btn"
              data-variant="accent"
              data-on={readonly ? 'true' : 'false'}
              onClick={() => setReadonly((v) => !v)}
            >
              {readonly ? '只读中' : '可编辑'}
            </button>
            <button type="button" className="wf-btn" onClick={handleExport} disabled={!model}>
              导出 JSON
            </button>
          </div>
        </header>

        {error && <div className="wf-error">{error}</div>}
        {!error && !model && <div className="wf-loading">加载中…</div>}
        {!error && model && (
          <WorkflowCanvas
            model={model}
            readonly={readonly}
            selectedId={selected?.id ?? null}
            onSelect={setSelected}
            onChange={setModel}
          />
        )}
      </main>

      <PropertyDrawer
        node={selected}
        readonly={readonly}
        onParamChange={handleParamChange}
        onLabelChange={handleLabelChange}
      />
    </div>
  )
}
