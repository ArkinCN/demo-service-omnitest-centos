import { useT } from '../../i18n'
import { useEffect, useRef, useState } from 'react'
import { Minus, Plus } from 'lucide-react'
import { cn } from './cn'

/**
 * 数值加减：圆形加减按钮夹着大号数字 + 小号单位。
 *
 * ⚠️ `value` 允许为 `null`（2026-09-28 新增，为「占位/待现场确认」字段服务）：
 * 这类字段在场景包里没有初始数值（值是「未知」），但**恰恰最需要人去填**。
 * 传 null 时输入框显示为空、以 placeholder 提示要填什么，
 * 而不是像以前那样因为「没有数字」而整行退化成不可编辑的只读文本。
 * 老调用点都传数字，行为完全不变。
 *
 * ⚠️ 超范围提示（2026-10-10 新增，需求单编号 1）：
 * 此前越界值被 `clamp` **静默**夹到边界，人不知道自己填错了。
 * 现在输入越界或非数字时，用红色浮层说明「超出允许范围 X~Y，已调整为 Y」。
 * 三条纪律：
 *   ① 提示只负责**告知已纠偏**，回传给调用方的仍是夹取后的合法值，onChange 契约不变
 *      （非法值绝不进 store，也不会进判定与报告链路）；
 *   ② 浮层 `absolute` 定位、**不参与布局**，不撑高既有 40px 行高；约 4 秒自动消失；
 *   ③ 带 `role="status"` / `aria-live="polite"`，读屏可播报。
 */
export function Stepper({
  value,
  unit,
  step = 1,
  min,
  max,
  precision = 0,
  onChange,
  disabled,
  className,
  label,
  size = 'md',
  emptyHint = '待填',
}: {
  /** 当前值；null = 还没有值（占位/待现场确认），显示为空输入框 */
  value: number | null
  unit?: string
  step?: number
  min?: number
  max?: number
  precision?: number
  onChange?: (next: number) => void
  disabled?: boolean
  className?: string
  label?: string
  size?: 'sm' | 'md'
  /** value 为 null 时输入框里的灰字提示 */
  emptyHint?: string
}) {
  const uiT = useT()

  const clamp = (n: number) => {
    let v = n
    if (min !== undefined) v = Math.max(min, v)
    if (max !== undefined) v = Math.min(max, v)
    return Number(v.toFixed(precision))
  }

  /** 允许范围的文字描述（两侧都没配时不描述范围） */
  const rangeText =
    min !== undefined && max !== undefined
      ? `${min}~${max}`
      : min !== undefined
        ? `不小于 ${min}`
        : max !== undefined
          ? `不大于 ${max}`
          : ''
  const outOfRange = (n: number) =>
    (min !== undefined && n < min) || (max !== undefined && n > max)
  const valueText = (n: number) => `${n.toFixed(precision)}${unit ? ` ${uiT(unit)}` : ''}`

  const [hint, setHint] = useState<string | null>(null)
  const timer = useRef<number | null>(null)
  /** 置提示并重排 4 秒自动消失（连续出错时以最后一次为准） */
  const showHint = (msg: string) => {
    setHint(msg)
    if (timer.current !== null) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setHint(null), 4000)
  }
  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current)
    },
    [],
  )

  /** 空值时以 0 为基准步进（再被 min 夹住）；有值就正常加减 */
  const bump = (dir: 1 | -1) => {
    const raw = (value ?? 0) + dir * step
    // 空值起点的夹取只用于给出合法初值，不算「用户填错」，不提示（避免噪音）
    if (value !== null && outOfRange(raw)) {
      showHint(
        `超出允许范围${rangeText ? ` ${rangeText}` : ''}，已调整为 ${valueText(clamp(raw))}`,
      )
    }
    onChange?.(clamp(raw))
  }
  const d = size === 'sm' ? 22 : 24

  const round =
    'inline-flex shrink-0 items-center justify-center rounded-full border border-line bg-white text-t2 ' +
    'transition-colors duration-150 hover:border-p400 hover:bg-p50 hover:text-p700 disabled:opacity-40 [&>svg]:block'

  return (
    <div
      className={cn(
        'relative inline-flex shrink-0 items-center gap-1.5',
        disabled && 'opacity-50',
        className,
      )}
    >
      <button
        type="button"
        disabled={disabled}
        onClick={() => bump(-1)}
        aria-label={uiT('{v1} 减小', { v1: label ?? uiT('数值') })}
        style={{ width: d, height: d }}
        className={round}
      >
        <Minus size={13} strokeWidth={2} />
      </button>
      <span className="inline-flex items-baseline gap-1">
        <input
          aria-label={label}
          // null → 空串（受控输入不能给 null，React 会当非受控）
          value={value === null ? '' : value.toFixed(precision)}
          placeholder={value === null ? uiT(emptyHint) : undefined}
          disabled={disabled}
          onChange={(e) => {
            const raw = e.target.value.trim()
            // 允许清空（回到「还没填」态），不把空串硬塞成 0——
            // 0 是一个**有意义的真实值**（如转速 0），不能拿它冒充「未填」。
            if (raw === '') {
              setHint(null)
              return
            }
            const n = Number(raw)
            if (Number.isNaN(n)) {
              // 非数字：不入链路（原值保持不动），只提示由人改正
              showHint('请输入数字')
              return
            }
            if (outOfRange(n)) {
              showHint(
                `超出允许范围${rangeText ? ` ${rangeText}` : ''}，已调整为 ${valueText(clamp(n))}`,
              )
            }
            onChange?.(clamp(n))
          }}
          className={cn(
            'num w-[58px] min-w-0 rounded border-0 bg-transparent p-0 text-right font-semibold text-t1 focus:outline-none',
            size === 'sm' ? 'text-[15px]' : 'text-[17px]',
            value === null && 'text-t3',
            // 出现提示时数值一并转红，让人一眼定位是哪一格填错了
            hint && 'text-alert ring-1 ring-alert/50',
          )}
        />
        {unit ? <span className="min-w-[26px] shrink-0 text-[12px] text-t3">{uiT(unit)}</span> : null}
      </span>
      <button
        type="button"
        disabled={disabled}
        onClick={() => bump(1)}
        aria-label={uiT('{v1} 增大', { v1: label ?? uiT('数值') })}
        style={{ width: d, height: d }}
        className={round}
      >
        <Plus size={13} strokeWidth={2} />
      </button>

      {/* 超范围/非数字提示：绝对定位浮层，不占布局；约 4 秒后自动消失。
          常驻渲染（而非条件挂载）是为了让 aria-live 区域先存在再变内容，读屏才播报。 */}
      <span
        role="status"
        aria-live="polite"
        className={cn(
          'pointer-events-none absolute right-0 top-full z-40 mt-1 max-w-[260px] rounded-tps px-2 py-[3px]',
          'text-[11px] font-medium leading-[15px] text-alert transition-opacity duration-150',
          hint
            ? 'bg-white opacity-100 shadow-[0_2px_8px_rgba(31,42,36,0.14)] ring-1 ring-alert/30'
            : 'opacity-0',
        )}
      >
        {uiT(hint ?? '')}
      </span>
    </div>
  )
}
