import { useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Info } from 'lucide-react'
import { cn } from './cn'

/** 说明文字一律收进 tooltip：标签只留 ≤6 字，整句话在这里出现。 */
export function Tooltip({
  content,
  children,
  side = 'top',
  className,
}: {
  content: ReactNode
  children: ReactNode
  side?: 'top' | 'bottom'
  className?: string
}) {
  const ref = useRef<HTMLSpanElement>(null)
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)

  const show = () => {
    const r = ref.current?.getBoundingClientRect()
    if (!r) return
    setPos({ x: r.left + r.width / 2, y: side === 'top' ? r.top - 8 : r.bottom + 8 })
  }

  return (
    <>
      <span
        ref={ref}
        className={cn('inline-flex', className)}
        onMouseEnter={show}
        onMouseLeave={() => setPos(null)}
        onFocus={show}
        onBlur={() => setPos(null)}
      >
        {children}
      </span>
      {pos
        ? createPortal(
            <div
              role="tooltip"
              style={{
                left: pos.x,
                top: pos.y,
                transform: `translate(-50%, ${side === 'top' ? '-100%' : '0'})`,
              }}
              className="animate-fade pointer-events-none fixed z-[90] max-w-[280px] rounded-tps bg-p900/95 px-2.5 py-1.5 text-[12px] leading-5 text-white shadow-tp2"
            >
              {content}
            </div>,
            document.body,
          )
        : null}
    </>
  )
}

/** ⓘ 图标：挂说明文字用 */
export function InfoTip({ content, size = 14 }: { content: ReactNode; size?: number }) {
  return (
    <Tooltip content={content}>
      <span className="cursor-help text-t3 transition-colors hover:text-p700 [&>svg]:block">
        <Info size={size} strokeWidth={1.75} />
      </span>
    </Tooltip>
  )
}
