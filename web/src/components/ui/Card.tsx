import { useT } from '../../i18n'
import { useState, type HTMLAttributes, type ReactNode } from 'react'
import { ChevronDown, Maximize2, RefreshCw, Replace } from 'lucide-react'
import { cn } from './cn'
import { IconButton } from './Button'

/** 一级 · 主表面：白底 + 圆角 12 + 柔阴影。每屏的容器都用它。 */
export function Panel({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <section
      className={cn('surface-1 flex min-h-0 min-w-0 flex-col overflow-hidden', className)}
      {...rest}
    >
      {children}
    </section>
  )
}

/** 二级 · 次表面：浅绿底无阴影 + 圆角 10。退居背景的分组、说明、工具行。 */
export function SoftCard({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('surface-2', className)} {...rest}>
      {children}
    </div>
  )
}

/** 区标题条：图标 + 标题 + 右侧动作位 */
export function PanelHeader({
  icon,
  title,
  meta,
  left,
  right,
  className,
}: {
  icon?: ReactNode
  title: string
  meta?: ReactNode
  left?: ReactNode
  right?: ReactNode
  className?: string
}) {
  return (
    <header
      className={cn(
        'flex h-[44px] shrink-0 items-center gap-2.5 border-b border-line-soft px-4',
        className,
      )}
    >
      {icon ? <span className="shrink-0 text-p700 [&>svg]:block">{icon}</span> : null}
      {/* 标题必须 shrink-0 + nowrap：header 是 flex，右侧动作位是 shrink-0，
          栏宽被压窄（例如右栏 clamp(300px,21vw,400px) 且挂了一枚长 id 徽标）时
          收缩量会全压到标题上；中文没有词边界，会逐字断行成竖排，并顶破定高
          44px 与图标、徽标叠在一起。标题是定长短词，永不参与收缩。 */}
      <h2 className="shrink-0 text-[16px] leading-none font-semibold tracking-tight whitespace-nowrap text-t1">
        {title}
      </h2>
      {meta ? (
        <span className="min-w-0 truncate text-[12px] text-t3">{meta}</span>
      ) : null}
      {left}
      {/* 右侧动作位：可收缩 + min-w-0 + 裁剪。
          此前这里是 shrink-0，里面又是 Badge（自身 shrink-0、nowrap），
          当内容比栏宽还长（例如挂了一整条条目 id
          motor.cooling-fan.fortior-fu6832:DOC-CASE-…）时既不收缩也不裁剪，
          直接顶出面板圆角边框外。改成可收缩后由子元素自己决定省略策略：
          Badge 会在下面用 max-w-full + truncate 收成省略号，并挂 title 出全称。 */}
      <div className="ml-auto flex min-w-0 items-center gap-1.5">{right}</div>
    </header>
  )
}

/** C 区卡片：卡头图标 + 短标题 + 图标按钮；卡体以视觉内容为主 */
export function PanelCard({
  icon,
  title,
  summary,
  stamp,
  active,
  alert,
  hero,
  onExpand,
  onSwap,
  swapOptions = [],
  onRefresh,
  headerRight,
  children,
  className,
  style,
  bodyClassName,
}: {
  icon?: ReactNode
  title: string
  summary?: string
  stamp?: string
  active?: boolean
  alert?: string
  hero?: boolean
  onExpand?: () => void
  onSwap?: (cardId: string) => void
  swapOptions?: { value: string; label: string }[]
  onRefresh?: () => void
  headerRight?: ReactNode
  children?: ReactNode
  className?: string
  bodyClassName?: string
  style?: React.CSSProperties
}) {
  const uiT = useT()

  const [swapOpen, setSwapOpen] = useState(false)
  return (
    <article
      style={style}
      className={cn(
        'animate-rise group flex min-h-0 min-w-0 flex-col overflow-hidden rounded-tp border bg-surface',
        'transition-[box-shadow,border-color,transform] duration-200',
        hero
          ? 'border-p200 shadow-tp1'
          : 'border-line shadow-[0_1px_2px_rgba(31,42,36,.04)] hover:border-p200 hover:shadow-tp1',
        alert && 'border-alert/40',
        className,
      )}
    >
      <header className="flex h-[38px] shrink-0 items-center gap-2 border-b border-line-soft pr-1.5 pl-3">
        {icon ? (
          <span
            className={cn(
              'flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-tpx [&>svg]:block',
              hero || active ? 'bg-p700 text-white' : 'bg-p50 text-p700',
            )}
          >
            {icon}
          </span>
        ) : null}
        <h3 className="truncate text-[14px] leading-none font-semibold tracking-tight text-t1">
          {title}
        </h3>
        {alert ? (
          <span className="shrink-0 rounded-full border border-alert/40 bg-alert-wash px-1.5 text-[11px] leading-[17px] text-alert">
            {alert}
          </span>
        ) : null}
        {stamp ? <span className="num shrink-0 text-[11px] text-t3">{stamp}</span> : null}
        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          {headerRight}
          {onSwap && swapOptions.length ? (
            <div className="relative">
              <IconButton
                size={24}
                aria-label={uiT("{v1} 换卡", { v1: title })}
                aria-expanded={swapOpen}
                title={uiT("换成卡片库里的另一张卡")}
                onClick={() => setSwapOpen((v) => !v)}
              >
                <Replace size={14} strokeWidth={1.75} />
              </IconButton>
              {swapOpen ? (
                <>
                  <button
                    type="button"
                    aria-label={uiT("关闭换卡")}
                    className="fixed inset-0 z-10 cursor-default"
                    onClick={() => setSwapOpen(false)}
                  />
                  <ul
                    role="listbox"
                    className="animate-pop absolute top-[26px] right-0 z-20 min-w-[160px] overflow-hidden rounded-tps border border-line bg-surface py-1 shadow-tp2"
                  >
                    {swapOptions.map((o) => (
                      <li key={o.value}>
                        <button
                          type="button"
                          role="option"
                          aria-selected={false}
                          onClick={() => {
                            setSwapOpen(false)
                            onSwap(o.value)
                          }}
                          className="block w-full truncate px-2.5 py-1.5 text-left text-[12px] text-t2 transition-colors hover:bg-p50 hover:text-p700"
                        >
                          {uiT(o.label)}
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
            </div>
          ) : null}
          {onRefresh ? (
            <IconButton size={24} aria-label={uiT("{v1} 刷新", { v1: title })} onClick={onRefresh} title={uiT("刷新")}>
              <RefreshCw size={14} strokeWidth={1.75} />
            </IconButton>
          ) : null}
          {onExpand ? (
            <IconButton size={24} aria-label={uiT("{v1} 放大", { v1: title })} onClick={onExpand} title={uiT("放大")}>
              <Maximize2 size={14} strokeWidth={1.75} />
            </IconButton>
          ) : null}
        </div>
      </header>

      <div
        className={cn(
          'relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden px-3 py-2.5',
          bodyClassName,
        )}
      >
        {children}
      </div>

      {summary ? (
        <footer className="shrink-0 truncate border-t border-line-soft px-3 py-1.5 text-[12px] text-t3">
          {summary}
        </footer>
      ) : null}
    </article>
  )
}

/** 空态：插画式图标 + 一行短句 */
export function EmptyState({
  icon,
  title,
  hint,
  action,
}: {
  icon?: ReactNode
  title: string
  hint?: string
  action?: ReactNode
}) {
  return (
    <div className="flex h-full min-h-0 flex-col items-center justify-center gap-2 px-6 text-center">
      <span className="flex h-[52px] w-[52px] items-center justify-center rounded-full bg-p50 text-p300 [&>svg]:block">
        {icon ?? <ChevronDown size={24} strokeWidth={1.5} />}
      </span>
      <span className="text-[13px] font-medium text-t2">{title}</span>
      {hint ? <span className="max-w-[260px] text-[12px] leading-5 text-t3">{hint}</span> : null}
      {action}
    </div>
  )
}

/** 骨架块 */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('skeleton rounded-tpx', className)} />
}
