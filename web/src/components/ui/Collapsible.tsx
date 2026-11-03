import { useT } from '../../i18n'
import { useState, type ReactNode } from 'react'
import { ChevronRight } from 'lucide-react'
import { cn } from './cn'
import { useAppStore } from '../../state/useAppStore'

/**
 * 分组折叠：图标 + 短标题 ≤6 字 + 状态汇总 + 右侧计数 + 折叠箭头。
 *
 * 第三轮改的三件事（依据 06b 第 3.2 节）：
 *   一、`defaultOpen` 缺省改为 false，调用方不传就是折叠；一级类只展开第一个。
 *   二、折叠状态提升到全局 store。传 `storeKey`（用 `collapseKey(flow, group)` 生成）
 *       就按「流程 × 分组」记忆，切页回来不回弹；不传仍走组件内状态。
 *   三、组头给状态汇总：已填 n/m、异常 k 项、待核实 j 项。异常走暗红；待核实是占位计数、
 *       走中性灰，不占状态色名额（琥珀只留给安全相关，见 DESIGN.md 第 8 节第 ⑦ 条）。
 */
export interface CollapsibleStat {
  /** 已填条数；与 total 同时给才渲染「n/m」 */
  done?: number
  total?: number
  /** 异常条数，暗红 */
  alert?: number
  /** 待核实条数，琥珀 */
  pending?: number
}

export function Collapsible({
  title,
  index,
  icon,
  meta,
  right,
  rightInteractive,
  stat,
  defaultOpen = false,
  storeKey,
  lockOpen,
  level = 2,
  children,
  className,
  dense,
}: {
  title: string
  index?: string
  icon?: ReactNode
  meta?: ReactNode
  right?: ReactNode
  /**
   * `right` 里含可点击元素（按钮）时为 true：标题行外层改用 `div`、
   * 折叠点击区单独用一个内层 `button`，右侧插槽独立渲染。
   *
   * 为什么需要它：HTML 不允许 `button` 嵌套 `button`。默认 right 放在标题
   * 那个大 `button` 内（纯展示插槽够了）；但要在标题行右侧放一个真按钮
   * （如「一键采纳」）就必须拆结构，否则浏览器会把嵌套 button 拍平、
   * 点击行为错乱。默认 false，现有调用一律不受影响。
   */
  rightInteractive?: boolean
  stat?: CollapsibleStat
  defaultOpen?: boolean
  /** 折叠状态记忆键，用 `collapseKey(flow, group)` 生成 */
  storeKey?: string
  /** 异常态分组：强制展开且不给折叠入口 */
  lockOpen?: boolean
  /** 1 = 一级类（更重的组头），2 = 二级组，3 = 三级子组 */
  level?: 1 | 2 | 3
  children: ReactNode
  className?: string
  dense?: boolean
}) {
  const uiT = useT()

  const stored = useAppStore((s) => (storeKey ? s.collapse[storeKey] : undefined))
  const setCollapse = useAppStore((s) => s.setCollapse)
  const [local, setLocal] = useState(defaultOpen)
  const open = lockOpen ? true : storeKey ? (stored ?? defaultOpen) : local
  const toggle = () => {
    if (lockOpen) return
    if (storeKey) setCollapse(storeKey, !open)
    else setLocal(!open)
  }

  const summary =
    stat && (stat.total !== undefined || stat.alert || stat.pending) ? (
      <span className="ml-auto flex shrink-0 items-center gap-1.5">
        {stat.alert ? (
          <span
            title={uiT("异常 {v1} 项", { v1: stat.alert })}
            className="num inline-flex h-[17px] items-center rounded-full border border-alert px-1.5 text-[11px] leading-none text-alert"
          >
            {uiT("异常 ")}{stat.alert}
          </span>
        ) : null}
        {stat.pending ? (
          <span
            title={uiT("待核实 {v1} 项", { v1: stat.pending })}
            className="num inline-flex h-[17px] items-center gap-1 rounded-full border border-line px-1.5 text-[11px] leading-none text-t2"
          >
            <span className="h-[5px] w-[5px] rounded-full bg-t3/45" />
            {stat.pending}
          </span>
        ) : null}
        {stat.total !== undefined ? (
          <span className="num text-[12px] text-t3" title={uiT("已填 {v1}/{v2}", { v1: stat.done ?? 0, v2: stat.total })}>
            {stat.done ?? 0}
            <span className="text-t3/70">/{stat.total}</span>
          </span>
        ) : null}
      </span>
    ) : null

  // 标题行内容（折叠箭头 + 图标 + 标题 + meta + 汇总）——两种结构共用。
  const headRow = (
    <>
      <ChevronRight
        size={level === 3 ? 12 : 14}
        strokeWidth={2}
        className={cn(
          'shrink-0 text-t3 transition-transform duration-200',
          open && 'rotate-90 text-p600',
          lockOpen && 'opacity-40',
        )}
      />
      {icon ? <span className="shrink-0 text-p600 [&>svg]:block">{icon}</span> : null}
      {index && !icon ? <span className="num text-[12px] text-t3">{index}</span> : null}
      <span
        className={cn(
          'truncate tracking-tight text-t1',
          level === 1 ? 'text-[13.5px] font-semibold' : 'font-semibold',
          level === 3 ? 'text-[12px] font-medium text-t2' : dense ? 'text-[12px]' : 'text-[13px]',
        )}
      >
        {title}
      </span>
    </>
  )
  const rowClass = cn(
    'group flex w-full items-center gap-2 text-left transition-colors duration-150 hover:bg-p50/70',
    level === 1 ? 'h-[38px] bg-sunk px-4' : level === 3 ? 'h-[26px] px-6' : 'px-4',
    level !== 1 && (dense ? 'h-[30px]' : 'h-[36px]'),
  )

  return (
    <div
      className={cn(
        level === 1 ? 'border-b border-line' : 'border-b border-line-soft last:border-b-0',
        className,
      )}
    >
      {rightInteractive ? (
        /* right 含按钮：外层 div，折叠点击区单独用 button，right 独立渲染——
           HTML 不允许 button 嵌套 button（与流程 3「安全闸门」同款结构）。 */
        <div className={cn(rowClass, 'hover:bg-transparent')}>
          <button
            type="button"
            aria-expanded={open}
            onClick={toggle}
            disabled={lockOpen}
            className="flex min-w-0 flex-1 items-center gap-2 text-left disabled:cursor-default"
          >
            {headRow}
            {meta ? <span className="tick ml-auto">{meta}</span> : null}
            {summary}
            {/* 无 right 占位时给个 auto 推位，保证汇总靠右对齐 */}
            {!right && !summary && !meta ? <span className="ml-auto" /> : null}
          </button>
          {right ? <span className="ml-auto flex shrink-0 items-center gap-1.5">{right}</span> : null}
        </div>
      ) : (
        <button type="button" aria-expanded={open} onClick={toggle} className={rowClass}>
          {headRow}
          {meta ? <span className="tick ml-auto">{meta}</span> : null}
          {summary}
          {right ? (
            <span className={cn('flex items-center gap-1.5', summary ? '' : 'ml-auto')}>{right}</span>
          ) : null}
        </button>
      )}
      {open ? <div className="animate-fade pb-1">{children}</div> : null}
    </div>
  )
}
