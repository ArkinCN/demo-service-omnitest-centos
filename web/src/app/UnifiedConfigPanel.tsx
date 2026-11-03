import { useT } from '../i18n'
import { useMemo, useState, type ReactNode } from 'react'
import { Search, X } from 'lucide-react'
import type { BuiltTier, Flags } from '../features/shared/tiers'
import type { FlowId } from '../data/types'
import { useAppStore } from '../state/useAppStore'

// `name_en`（2026-10-15 加入）：报告表头字段带了平行英文名，英文界面下要能按英文名搜到。
const SEARCH_FIELDS = new Set(['name', 'name_en', 'key', 'id', 'title', 'label', 'value', 'unit', 'group', 'g', 'criterion_text', 'file', 'locator', 'note', '_status', 'a', 'p', 'i', 'f', 'req', 'param', '_source', 'options'])

// 分类 Tab 的显示名覆盖表，key 为「流程/一级分类 id」。
// 2026-10-29：这里原先存 `[中文, English]` 元组，与词典并行维护、易出两套英文；
// 现在只存中文，英文一律由 `catalog.ts` 提供（调用处包一层 uiT）。
const CATEGORY_LABEL_OVERRIDES: Readonly<Record<string, string>> = {
  'req/req-perf': '测试要求', 'req/req-cond': '测试工况', 'req/req-safe': '测试安全',
  'init/drive': '驱动配置', 'init/bench': '台架仪器', 'init/out': '产出登记',
  'run/ctl-start': '启动参数', 'run/ctl-run': '运行保护',
  'report/rpt-addr': '固件基线',
}

/** Search human labels and source values, never metadata property names. */
function searchableValues(value: unknown): string {
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  if (Array.isArray(value)) return value.map(searchableValues).join(' ')
  if (value && typeof value === 'object') return Object.entries(value).filter(([key]) => SEARCH_FIELDS.has(key)).map(([, item]) => searchableValues(item)).join(' ')
  return ''
}

/** Presentation only: source items and editing callbacks stay with their flow. */
export function UnifiedConfigPanel<T>({
  tiers, itemKey, render, flags, tierIcon, tierRight, flow = 'init',
}: {
  tiers: BuiltTier<T>[]
  itemKey: (item: T) => string
  render: (item: T) => ReactNode
  flags?: (item: T) => Flags
  tierIcon?: (title: string) => ReactNode
  flow?: FlowId
  groupIcon?: (title: string) => ReactNode
  lockTier?: (tier: BuiltTier<T>) => boolean
  defaultOpen?: number
  tierRight?: (tier: BuiltTier<T>) => ReactNode
}) {
  const uiT = useT()
  const sceneId = useAppStore((state) => state.sceneId)
  const scope = `${sceneId}:${flow}:${tiers.map((tier) => tier.id).join('|')}`
  const defaults = { scope, category: tiers[0]?.id ?? 'all', query: '', reveal: false }
  const [saved, setSaved] = useState(defaults)
  const view = saved.scope === scope ? saved : defaults
  const { category, query, reveal } = view
  const update = (patch: Partial<typeof defaults>) => setSaved((previous) => ({ ...(previous.scope === scope ? previous : defaults), ...patch }))
  const setCategory = (category: string) => update({ category, reveal: false })
  const setQuery = (query: string) => update({ query, reveal: false })
  const categoryTitle = (tier: BuiltTier<T>) =>
    uiT(CATEGORY_LABEL_OVERRIDES[`${flow}/${tier.id}`] ?? tier.title)
  const groups = useMemo(() => tiers.flatMap((tier) => tier.groups.map((group) => ({ tier, group }))), [tiers])
  const total = groups.reduce((count, { group }) => count + group.items.length, 0)
  const needle = query.trim().toLocaleLowerCase()
  const shown = groups.filter(({ tier }) => category === 'all' || category === tier.id).map(({ tier, group }) => ({
    tier, group,
    items: group.items.filter((item) => !needle || `${categoryTitle(tier)} ${uiT(tier.title)} ${uiT(group.title)} ${searchableValues(item)}`.toLocaleLowerCase().includes(needle)),
  })).filter(({ items }) => items.length)
  const limit = !reveal && !needle ? 3 : Infinity
  const visible = shown.map((entry, index) => {
    const preceding = shown.slice(0, index).reduce((count, group) => count + group.items.length, 0)
    return { ...entry, items: entry.items.slice(0, Math.max(0, limit - preceding)) }
  }).filter((entry) => entry.items.length)
  const visibleCount = visible.reduce((count, { items }) => count + items.length, 0)
  const shownCount = shown.reduce((count, { items }) => count + items.length, 0)
  return <section className="unified-config" aria-label={uiT("完整配置分类与字段")}>
    <nav className="unified-config-tabs" data-single={tiers.length === 1} aria-label={uiT("配置分类")}>
      {tiers.length > 1 ? <button type="button" aria-pressed={category === 'all'} onClick={() => setCategory('all')}>{uiT("全部 ")}<small>{total}</small></button> : null}
      {tiers.map((tier) => <div key={tier.id} className="unified-config-tab"><button type="button" aria-pressed={category === tier.id || tiers.length === 1} onClick={() => setCategory(tier.id)}>{tierIcon?.(tier.title)}<span className="config-category-name">{categoryTitle(tier)}</span><small>{tier.count}</small></button>{tierRight?.(tier)}</div>)}
    </nav>
    <details className="config-search-disclosure">
      <summary>{uiT('查找具体字段')}</summary>
      <div className="unified-config-search">
        <Search size={15} aria-hidden="true" />
        <input aria-label={uiT("搜索完整配置")} placeholder={uiT("搜索名称、参数或来源")} value={query} onChange={(event) => setQuery(event.target.value)} />
        {query ? <button type="button" aria-label={uiT("清除搜索")} onClick={() => setQuery('')}><X size={14} /></button> : null}
        <span>{visibleCount}/{total}</span>
      </div>
    </details>
    <div className="unified-config-groups">
      {visible.map(({ tier, group, items }) => <section key={`${tier.id}/${group.id}`} className="unified-config-group">
        <header><div><span>{categoryTitle(tier)}</span><h3>{uiT(group.title)}</h3></div><small>{items.length} {uiT(" 项")}</small></header>
        <div className="unified-config-fields">{items.map((item) => {
          const state = flags?.(item)
          return <div key={itemKey(item)} className="unified-config-field" data-pending={state?.pending || undefined} data-alert={state?.alert || undefined}>{render(item)}</div>
        })}</div>
      </section>)}
      {!shown.length ? <div className="unified-config-empty"><strong>{uiT("没有匹配的配置")}</strong><span>{uiT("尝试其他名称，或清除筛选查看全部字段。")}</span><button type="button" onClick={() => { update({ category: 'all', query: '', reveal: false }) }}>{uiT("显示全部配置")}</button></div> : null}
    </div>
    {visibleCount < shownCount ? <button type="button" className="config-show-category" onClick={() => update({ reveal: true })}>{uiT('展开当前分类全部 {v1} 项', { v1: shownCount })}</button> : null}
  </section>
}
