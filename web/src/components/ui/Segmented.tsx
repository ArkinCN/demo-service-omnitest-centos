import { useT } from '../../i18n'
import type { ReactNode } from 'react'
import { cn } from './cn'

export interface SegItem {
  value: string
  label: string
  icon?: ReactNode
  title?: string
}

/** 分段控件：浅绿槽 + 白色滑块，用于视图切换、权限档位 */
export function Segmented({
  items,
  value,
  onChange,
  size = 'md',
  className,
  ariaLabel,
}: {
  items: SegItem[]
  value: string
  onChange: (v: string) => void
  size?: 'sm' | 'md'
  className?: string
  ariaLabel?: string
}) {
  const uiT = useT()

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        'inline-flex shrink-0 items-center gap-0.5 rounded-tps bg-p50 p-0.5',
        className,
      )}
    >
      {items.map((it) => {
        const on = it.value === value
        return (
          <button
            key={it.value}
            role="tab"
            type="button"
            aria-selected={on}
            title={uiT(it.title ?? it.label)}
            onClick={() => onChange(it.value)}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-tpx font-medium transition-all duration-150 [&>svg]:block',
              size === 'sm' ? 'h-[22px] px-2 text-[12px]' : 'h-[26px] px-2.5 text-[12px]',
              on
                ? 'bg-white text-p700 shadow-[0_1px_2px_rgba(31,42,36,.10)]'
                : 'text-t2 hover:text-p700',
            )}
          >
            {it.icon}
            {uiT(it.label)}
          </button>
        )
      })}
    </div>
  )
}
