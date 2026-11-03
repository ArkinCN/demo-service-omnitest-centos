import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cn } from './cn'

/** primary 实底渐变 / secondary 浅绿 / ghost 透明 / danger 描边 / quiet 白底描边 */
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'default' | 'solid'
type Size = 'sm' | 'md' | 'lg'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  icon?: ReactNode
  trailing?: ReactNode
  active?: boolean
  block?: boolean
}

const base =
  'relative inline-flex items-center justify-center gap-1.5 rounded-tps border font-medium select-none whitespace-nowrap ' +
  'transition-[background,border-color,color,box-shadow,transform] duration-150 active:translate-y-px ' +
  'disabled:cursor-not-allowed disabled:opacity-45 disabled:active:translate-y-0'

const variants: Record<Variant, string> = {
  primary:
    'grad-ink border-transparent text-white shadow-tpink hover:brightness-[1.08] disabled:shadow-none disabled:grayscale',
  solid:
    'grad-ink border-transparent text-white shadow-tpink hover:brightness-[1.08] disabled:shadow-none disabled:grayscale',
  secondary: 'border-p200 bg-p50 text-p700 hover:bg-p100 hover:border-p300',
  default: 'border-line bg-surface text-t2 hover:border-p300 hover:text-p700 hover:bg-p50/60',
  ghost: 'border-transparent bg-transparent text-t2 hover:bg-p50 hover:text-p700',
  danger: 'border-alert/45 bg-white text-alert hover:bg-alert-wash hover:border-alert',
}

const sizes: Record<Size, string> = {
  sm: 'h-[28px] px-2.5 text-[12px]',
  md: 'h-[32px] px-3 text-[13px]',
  lg: 'h-[38px] px-4 text-[13px]',
}

export function Button({
  variant = 'default',
  size = 'md',
  icon,
  trailing,
  active,
  block,
  className,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      className={cn(
        base,
        sizes[size],
        variants[variant],
        block && 'w-full',
        active && (variant === 'default' || variant === 'ghost') && 'border-p300 bg-p50 text-p700',
        className,
      )}
      {...rest}
    >
      {icon ? <span className="shrink-0 leading-none [&>svg]:block">{icon}</span> : null}
      {children}
      {trailing ? <span className="shrink-0 leading-none">{trailing}</span> : null}
    </button>
  )
}

/** 纯图标按钮：卡头右上、工具条、输入框两侧 */
export function IconButton({
  size = 28,
  tone = 'quiet',
  active,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  size?: number
  tone?: 'quiet' | 'soft' | 'solid' | 'danger'
  active?: boolean
}) {
  const tones = {
    quiet: 'border-transparent bg-transparent text-t3 hover:bg-p50 hover:text-p700',
    soft: 'border-p200 bg-p50 text-p700 hover:bg-p100',
    solid: 'grad-ink border-transparent text-white shadow-tpink hover:brightness-110',
    danger: 'border-transparent bg-transparent text-alert hover:bg-alert-wash',
  }[tone]
  return (
    <button
      type="button"
      style={{ width: size, height: size }}
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-tpx border transition-colors duration-150',
        'disabled:cursor-not-allowed disabled:opacity-40 [&>svg]:block',
        tones,
        active && 'border-p300 bg-p100 text-p700',
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  )
}
