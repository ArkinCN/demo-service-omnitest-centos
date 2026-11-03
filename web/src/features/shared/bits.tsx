import { useT } from '../../i18n'
import type { ReactNode } from 'react'
import { CheckCircle2, LockOpen } from 'lucide-react'
import { Button, Collapsible, Tooltip, cn } from '../../components/ui'
import type { FlowId } from '../../data/types'
import { collapseKey } from '../../state/useAppStore'
import { tally, type BuiltTier, type Flags } from './tiers'

/** 卡体：定高不滚动是壳层规格，但卡内长列表需要自己滚，这里统一给一个滚动容器。 */
export function CardBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('h-full min-h-0 overflow-y-auto pr-0.5', className)}>{children}</div>
}

/** 子组标题条：名称 + 右侧计数 */
export function GroupBar({
  title,
  count,
  right,
  onClick,
  active,
}: {
  title: string
  count?: number | string
  right?: ReactNode
  onClick?: () => void
  active?: boolean
}) {
  const uiT = useT()

  const inner = (
    <>
      <span className="truncate">{uiT(title)}</span>
      {count !== undefined ? <span className="num ml-auto shrink-0 text-t3">{count}</span> : null}
      {right}
    </>
  )
  const cls = cn(
    'flex h-[20px] w-full items-center gap-1.5 px-1.5 text-[11px]',
    active ? 'bg-ink-wash text-ink' : 'bg-sunk text-t2',
  )
  return onClick ? (
    <button type="button" onClick={onClick} className={cn(cls, 'text-left hover:text-ink')}>
      {inner}
    </button>
  ) : (
    <div className={cls}>{inner}</div>
  )
}

/** 一行两列：标签 + 值 */
export function KV({
  k,
  v,
  alert,
  title,
}: {
  k: string
  v: ReactNode
  alert?: boolean
  title?: string
}) {
  const uiT = useT()

  return (
    <div className="flex items-baseline gap-2 py-[2px]" title={title}>
      <span className="shrink-0 text-[11px] text-t3">{uiT(k)}</span>
      <span className={cn('num ml-auto truncate text-[11.5px]', alert ? 'text-alert' : 'text-t1')}>{v}</span>
    </div>
  )
}

/** 细边框标签 */
export function Tag({
  children,
  tone = 'neutral',
  title,
}: {
  children: ReactNode
  tone?: 'neutral' | 'ink' | 'alert' | 'mute'
  title?: string
}) {
  return (
    <span
      title={title}
      className={cn(
        'shrink-0 rounded-tps border px-1 text-[10px] leading-[15px] whitespace-nowrap',
        tone === 'ink' && 'border-ink bg-ink-wash text-ink',
        tone === 'alert' && 'border-alert text-alert',
        tone === 'mute' && 'border-line-soft text-t3',
        tone === 'neutral' && 'border-line text-t2',
      )}
    >
      {children}
    </span>
  )
}

/** 横向占比条，只用墨绿明度，不引第三色相 */
export function Bar({ ratio, alert }: { ratio: number; alert?: boolean }) {
  return (
    <span className="inline-block h-[4px] w-[52px] shrink-0 rounded-full bg-sunk align-middle">
      <span
        className={cn('block h-full rounded-full', alert ? 'bg-alert' : 'bg-ink')}
        style={{ width: `${Math.max(2, Math.min(100, ratio * 100))}%` }}
      />
    </span>
  )
}

export function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center px-3 text-center text-[11px] text-t3">
      {text}
    </div>
  )
}

/** 列表行 */
export function Row({
  children,
  onClick,
  active,
  alert,
  title,
}: {
  children: ReactNode
  onClick?: () => void
  active?: boolean
  alert?: boolean
  title?: string
}) {
  const cls = cn(
    'flex w-full items-center gap-1.5 border-b border-line-soft px-1.5 py-[3px] text-left text-[11.5px] last:border-b-0',
    active && 'bg-ink-wash',
    alert && !active && 'bg-alert-wash/50',
  )
  return onClick ? (
    <button type="button" title={title} onClick={onClick} className={cn(cls, 'hover:bg-ink-wash/60')}>
      {children}
    </button>
  ) : (
    <div title={title} className={cls}>
      {children}
    </div>
  )
}

/**
 * 左栏底部主按钮。六条流程共用同一形态：通栏、lg、primary 实底渐变、
 * CheckCircle2 图标，文案统一 「确认<对象> · <数字><量词>」。
 * 前置条件没满足时不换形态、不置灰——理由只挂 tooltip（DESIGN.md §4 文案纪律 4）。
 *
 * 2026-09-28 两处扩展（都为「确认后变解除确认」这一形态服务）：
 *   - `variant`：确认后换 secondary，与流程 1 的「解除确认」保持一致；
 *   - `icon`：可换成解锁图标。**默认仍是确认态**，老调用点一行都不用改。
 * 之所以不新写一个组件，是因为它们是**同一个位置的同一种按钮**，
 * 拆成两个必然会漂移成两套样式（这轮已经吃过「两个入口各写一套」的亏）。
 */
export function ConfirmFooter({
  label,
  count,
  unit,
  hint,
  onClick,
  variant = 'primary',
  icon = 'confirm',
}: {
  label: string
  count: number | string
  unit: string
  hint: ReactNode
  onClick?: () => void
  /** 确认态用 primary（实底），解除态用 secondary（描边） */
  variant?: 'primary' | 'secondary'
  /** confirm = 勾选图标，unlock = 解锁图标 */
  icon?: 'confirm' | 'unlock'
}) {
  const uiT = useT()

  return (
    <footer className="shrink-0 border-t border-line-soft bg-white/85 px-4 py-3 backdrop-blur">
      <Tooltip content={hint} className="w-full">
        <Button
          block
          size="lg"
          variant={variant}
          icon={
            icon === 'unlock' ? (
              <LockOpen size={15} strokeWidth={2} />
            ) : (
              <CheckCircle2 size={15} strokeWidth={2} />
            )
          }
          onClick={onClick}
        >
          {uiT(label)} · {count} {uiT(unit)}
        </Button>
      </Tooltip>
    </footer>
  )
}

/* ===========================================================================
   分层折叠树的渲染组件。骨架、取数与演示模式过滤在同目录的 tiers.ts。
   =========================================================================== */

/** 组头状态汇总的聚合口径：alert 走暗红、pending 走琥珀，两者不互相顶替 */
function merge(a: ReturnType<typeof tally>, b: ReturnType<typeof tally>) {
  return {
    done: a.done + b.done,
    total: a.total + b.total,
    alert: a.alert + b.alert,
    pending: a.pending + b.pending,
  }
}

const ZERO = { done: 0, total: 0, alert: 0, pending: 0 }

/**
 * 分层折叠树的渲染：一级类默认只展开第一个，二级组与三级子组同理各只展开第一个。
 * 折叠状态按 `collapseKey(flow, id)` 记进 store，切页回来不回弹。
 */
export function TierTree<T>({
  flow,
  tiers,
  itemKey,
  render,
  flags,
  lockTier,
  tierIcon,
  tierRight,
  groupIcon,
  defaultOpen = 0,
}: {
  flow: FlowId
  tiers: BuiltTier<T>[]
  itemKey: (t: T) => string
  render: (t: T) => ReactNode
  /** 每条给三态：已填 / 异常 / 待核实；不给就只显示条数 */
  flags?: (t: T) => Flags
  /** 该一级类强制展开且不给折叠入口（异常态分组） */
  lockTier?: (t: BuiltTier<T>) => boolean
  /** 一级类 / 二级组的图标，按标题取 */
  tierIcon?: (title: string) => ReactNode
  /**
   * 一级类标题行右侧的交互插槽（如「一键采纳」按钮）。返回非空时，
   * 该一级类的 Collapsible 会改用「div 外框 + 独立折叠按钮」结构，
   * 避免 button 嵌套 button。按一级类取，返回 null 则该类走默认结构。
   */
  tierRight?: (t: BuiltTier<T>) => ReactNode
  groupIcon?: (title: string) => ReactNode
  /** 默认展开第几个一级类（只展开这一个），其余全部折叠 */
  defaultOpen?: number
}) {
  const uiT = useT()

  const stat = (items: T[]) => (flags ? tally(items, flags) : { ...ZERO, total: items.length })
  return (
    <>
      {tiers.map((t, i) => {
        const tStat = t.groups.reduce((acc, g) => merge(acc, stat(g.items)), { ...ZERO })
        // 二级组默认展开哪一个：优先挑不需要再分三级的那一组，让首屏直接见到值，
        // 而不是连开三层才看到第一个数。都要分三级时退回第一组。
        const openGroup = Math.max(
          0,
          t.groups.findIndex((x) => x.subs.length === 0),
        )
        const tr = tierRight?.(t)
        return (
          <Collapsible
            key={t.id}
            level={1}
            index={String(i + 1)}
            icon={tierIcon?.(t.title)}
            title={uiT(t.title)}
            storeKey={collapseKey(flow, t.id)}
            defaultOpen={i === defaultOpen}
            lockOpen={lockTier?.(t)}
            right={tr ?? undefined}
            rightInteractive={!!tr}
            stat={flags ? tStat : { total: t.count }}
          >
            {t.groups.map((g, j) => (
              <Collapsible
                key={g.id}
                level={2}
                icon={groupIcon?.(g.title)}
                title={uiT(g.title)}
                storeKey={collapseKey(flow, g.id)}
                defaultOpen={j === openGroup}
                stat={flags ? stat(g.items) : { total: g.items.length }}
              >
                {g.subs.length
                  ? g.subs.map((sub, k) => (
                      <Collapsible
                        key={sub.id}
                        level={3}
                        title={uiT(sub.title)}
                        storeKey={collapseKey(flow, sub.id)}
                        defaultOpen={k === 0}
                        stat={flags ? stat(sub.items) : { total: sub.items.length }}
                      >
                        {sub.items.map((x) => (
                          <div key={itemKey(x)}>{render(x)}</div>
                        ))}
                      </Collapsible>
                    ))
                  : g.items.map((x) => <div key={itemKey(x)}>{render(x)}</div>)}
              </Collapsible>
            ))}
          </Collapsible>
        )
      })}
    </>
  )
}
