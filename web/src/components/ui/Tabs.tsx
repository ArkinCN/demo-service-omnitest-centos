import { useT } from '../../i18n'
import type { ReactNode } from 'react'
import { cn } from './cn'

export interface TabItem {
  id: string
  label: string
  index?: string
  badge?: string
  icon?: ReactNode
}

/** 下划线标签组：面板内的二级切换 */
export function Tabs({
  items,
  value,
  onChange,
  className,
}: {
  items: TabItem[]
  value: string
  onChange: (id: string) => void
  className?: string
}) {
  const uiT = useT()

  return (
    <div role="tablist" className={cn('flex items-end gap-5 border-b border-line-soft', className)}>
      {items.map((it) => {
        const on = it.id === value
        return (
          <button
            key={it.id}
            role="tab"
            type="button"
            aria-selected={on}
            onClick={() => onChange(it.id)}
            className={cn(
              '-mb-px flex items-center gap-1.5 border-b-2 px-0.5 pb-2 text-[13px] font-medium transition-colors duration-150 [&>svg]:block',
              on ? 'border-p700 text-p700' : 'border-transparent text-t3 hover:text-t2',
            )}
          >
            {it.icon}
            {uiT(it.label)}
            {it.badge ? <span className="num text-[12px] text-t3">{it.badge}</span> : null}
          </button>
        )
      })}
    </div>
  )
}
