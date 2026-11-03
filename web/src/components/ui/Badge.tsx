import type { ReactNode } from 'react'
import { useT } from '../../i18n'
import type { ItemStatus, ParamSource } from '../../data/types'
import { cn } from './cn'

export type BadgeTone = 'ink' | 'soft' | 'neutral' | 'alert' | 'warn'

const tones: Record<BadgeTone, string> = {
  ink: 'bg-p700 text-white border-transparent',
  soft: 'bg-p50 text-p700 border-p200',
  neutral: 'bg-white text-t3 border-line',
  alert: 'bg-alert-wash text-alert border-alert/35',
  warn: 'bg-warn-wash text-warn border-warn/30',
}

/** 圆点 + 词。徽标一律药丸形，只放一个短词。 */
export function Badge({
  tone = 'neutral',
  dot,
  icon,
  children,
  className,
  mono,
  title,
}: {
  tone?: BadgeTone
  dot?: boolean
  icon?: ReactNode
  children: ReactNode
  className?: string
  mono?: boolean
  title?: string
}) {
  const dotColor = {
    ink: 'bg-white',
    soft: 'bg-p600',
    neutral: 'bg-t3',
    alert: 'bg-alert',
    warn: 'bg-warn',
  }[tone]
  return (
    <span
      // 悬停出全称：徽标正文可能被省略号截断（见下），全称必须能从 title 读到。
      // 调用方显式传 title 时以调用方为准，避免把业务说明覆盖掉。
      // children 若是字符串就直接用作全称，是节点（如带计数的复合内容）则只能靠调用方传。
      title={title ?? (typeof children === 'string' ? children : undefined)}
      className={cn(
        // min-w-0 + max-w-full：允许在 flex 行里被压窄，且不超过父容器。
        // 原来是 shrink-0 + nowrap：既不收缩也不裁剪，长 id 会顶出面板边框。
        // 现在 shrink-0 只作为「父容器宽松时不主动拉伸」的默认值，
        // 需要收缩的父容器（如 PanelHeader 的右侧位）会把 shrink 覆盖回来。
        'inline-flex h-[20px] min-w-0 max-w-full shrink items-center gap-1.5 overflow-hidden rounded-full border px-2 text-[12px] leading-none font-medium whitespace-nowrap',
        mono && 'num',
        tones[tone],
        className,
      )}
    >
      {dot ? <span className={cn('h-[6px] w-[6px] shrink-0 rounded-full', dotColor)} /> : null}
      {icon ? <span className="shrink-0 [&>svg]:block">{icon}</span> : null}
      {/* 正文自己承担省略：flex 子项默认 min-width:auto 会撑破父级，
          必须 min-w-0 + truncate 才能真的出省略号而不再溢出。
          用 flex-1 而不是固定宽度：定宽徽标（如 EntryRow 的 w-[76px]）
          外层 justify-center 需要正文作为可伸缩项才能真正居中，
          宽裕时也不影响原本的自适应宽度。 */}
      <span className="min-w-0 flex-1 truncate">{children}</span>
    </span>
  )
}

/** 来源标记：小圆点色标，不写字（悬停出全称） */
export function SourceTag({ source, title }: { source: ParamSource; title?: string }) {
  const uiT = useT()
  const map: Record<ParamSource, { cls: string; name: string }> = {
    文档: { cls: 'bg-p600', name: '来文档' },
    人工: { cls: 'bg-warn', name: '来人工' },
    建议: { cls: 'bg-p300', name: '来建议' },
  }
  const s = map[source] ?? map['文档']
  return (
    <span
      title={title ? `${uiT(s.name)} · ${title}` : uiT(s.name)}
      aria-label={uiT(s.name)}
      className={cn('inline-block h-[6px] w-[6px] shrink-0 rounded-full', s.cls)}
    />
  )
}

/** 状态语义只三档 + 不适用 */
export function StatusDot({
  status,
  label,
  pulse,
}: {
  status: ItemStatus
  label?: string
  pulse?: boolean
}) {
  const map: Record<ItemStatus, { cls: string; text: string; txt: string }> = {
    empty: { cls: 'bg-white ring-1 ring-inset ring-line', text: '未填', txt: 'text-t3' },
    done: { cls: 'bg-p600', text: '已填', txt: 'text-p700' },
    alert: { cls: 'bg-alert', text: '异常', txt: 'text-alert' },
    na: { cls: 'bg-t3/45', text: '不适用', txt: 'text-t3' },
  }
  const uiT = useT()
  const s = map[status]
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5" title={uiT(s.text)}>
      <span
        className={cn('h-[7px] w-[7px] shrink-0 rounded-full', s.cls)}
        style={pulse ? { animation: 'pulse-dot 2.4s ease-in-out infinite' } : undefined}
      />
      {label === undefined ? null : (
        <span className={cn('text-[12px] font-medium whitespace-nowrap', s.txt)}>
          {label || uiT(s.text)}
        </span>
      )}
    </span>
  )
}

/** 头像：墨绿实底圆形 */
export function Avatar({
  name,
  size = 28,
  tone = 'ink',
}: {
  name: string
  size?: number
  tone?: 'ink' | 'soft'
}) {
  return (
    <span
      style={{ width: size, height: size, fontSize: Math.round(size * 0.42) }}
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-full font-medium select-none',
        tone === 'ink' ? 'grad-ink text-white' : 'bg-p100 text-p700',
      )}
    >
      {name.slice(0, 1)}
    </span>
  )
}
