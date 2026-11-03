import { useT } from '../../i18n'
import { useEffect, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from './cn'

export interface SelectOption {
  value: string
  label: string
  meta?: string
}

/** 轻量下拉选择：点击外部关闭、Esc 关闭、键盘可达 */
export function Select({
  options,
  value,
  onChange,
  placeholder = '请选择',
  className,
  align = 'left',
  size = 'md',
  label,
  disabled = false,
}: {
  options: SelectOption[]
  value?: string
  onChange?: (v: string) => void
  placeholder?: string
  className?: string
  align?: 'left' | 'right'
  size?: 'sm' | 'md'
  label?: string
  disabled?: boolean
}) {
  const uiT = useT()

  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const current = options.find((o) => o.value === value)

  useEffect(() => {
    // disabled 时不允许下拉展开，若有残留展开态则收起
    if (disabled && open) setOpen(false)
    if (!open || disabled) return
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, disabled])

  return (
    <div ref={ref} className={cn('relative', className)}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={label}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'flex w-full items-center gap-1.5 rounded-tps border bg-white px-2.5 text-left font-medium transition-colors duration-150',
          size === 'sm' ? 'h-[28px] text-[12px]' : 'h-[32px] text-[13px]',
          open ? 'border-p500 text-p700' : 'border-line text-t1 hover:border-p300',
          disabled && 'cursor-not-allowed opacity-50 hover:border-line hover:text-t1',
        )}
      >
        <span className={cn('truncate', !current && 'text-t3')}>
          {current?.label ?? uiT(placeholder)}
        </span>
        {current?.meta ? (
          <span className="num ml-auto shrink-0 text-[10px] text-t3">{current.meta}</span>
        ) : null}
        <ChevronDown
          size={14}
          strokeWidth={2}
          className={cn(
            'ml-auto shrink-0 text-t3 transition-transform duration-150',
            current?.meta && 'ml-1',
            open && 'rotate-180',
          )}
        />
      </button>
      {open ? (
        <ul
          role="listbox"
          className={cn(
            'animate-pop absolute top-[calc(100%+6px)] z-40 max-h-[280px] min-w-full overflow-auto rounded-tps border border-line bg-surface py-1 shadow-tp2',
            align === 'right' ? 'right-0' : 'left-0',
          )}
        >
          {options.map((o) => (
            <li key={o.value}>
              <button
                type="button"
                role="option"
                aria-selected={o.value === value}
                onClick={() => {
                  onChange?.(o.value)
                  setOpen(false)
                }}
                className={cn(
                  'flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12.5px] whitespace-nowrap transition-colors',
                  o.value === value
                    ? 'bg-p50 font-medium text-p700'
                    : 'text-t2 hover:bg-p50/70 hover:text-p700',
                )}
              >
                {o.label}
                {o.meta ? (
                  <span className="num ml-auto text-[10px] text-t3">{o.meta}</span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
