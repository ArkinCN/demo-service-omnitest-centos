import { useT } from '../../i18n'
import { useEffect, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { createPortal } from 'react-dom'
import { cn } from './cn'

function useEscape(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])
}

/** 居中放大浮层：资源卡片点击放大用 */
export function Modal({
  open,
  onClose,
  title,
  meta,
  footer,
  children,
  width = 960,
  zIndex = 50,
}: {
  open: boolean
  onClose: () => void
  title: string
  meta?: string
  footer?: ReactNode
  children: ReactNode
  width?: number
  /** 遮罩层 z-index（默认 50）；当上层有更高 z 的容器（如自动化回归结果弹窗 z-60）时需调高 */
  zIndex?: number
}) {
  const uiT = useT()

  useEscape(open, onClose)
  if (!open) return null
  return createPortal(
    <div
      className="animate-fade fixed inset-0 z-50 flex items-center justify-center bg-[rgba(16,26,21,0.34)] p-10 backdrop-blur-[2px]"
      style={{ zIndex }}
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        /*
         * 窄屏自适应（2026-10-15）：补 maxWidth。
         * 原来只有内联 width（调用方给的，如 1220px），在 ≤1024px 的投屏 / 小窗口下
         * 会横向溢出屏幕 —— 外层遮罩只有 p-10 的 40px 内边距，拦不住它。
         * 加 maxWidth:100% 后：宽屏仍是原宽（宽度由 width 决定，maxWidth 不生效），
         * 窄屏自动收到容器可用宽度。高度侧早有 max-h-[min(80vh,100%)] 兜着，只差宽度。
         */
        style={{ width, maxWidth: '100%' }}
        onClick={(e) => e.stopPropagation()}
        className="animate-pop flex max-h-[min(80vh,100%)] flex-col overflow-hidden rounded-tp border border-line bg-surface shadow-tp2"
      >
        <header className="flex h-[48px] shrink-0 items-center gap-2.5 border-b border-line-soft px-4">
          <h3 className="text-[16px] font-semibold tracking-tight text-t1">{title}</h3>
          {meta ? <span className="truncate text-[12px] text-t3">{meta}</span> : null}
          <button
            type="button"
            onClick={onClose}
            aria-label={uiT("关闭")}
            className="ml-auto flex h-7 w-7 items-center justify-center rounded-tpx text-t3 transition-colors hover:bg-p50 hover:text-p700"
          >
            <X size={16} strokeWidth={1.75} />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-auto p-4">{children}</div>
        {footer ? (
          <footer className="flex h-[44px] shrink-0 items-center justify-end gap-2 border-t border-line-soft px-3">
            {footer}
          </footer>
        ) : null}
      </div>
    </div>,
    document.body,
  )
}

/** 右侧抽屉：工具详情 / 文档预览用 */
export function Drawer({
  open,
  onClose,
  title,
  meta,
  children,
  width = 420,
}: {
  open: boolean
  onClose: () => void
  title: string
  meta?: string
  children: ReactNode
  width?: number
}) {
  const uiT = useT()

  useEscape(open, onClose)
  if (!open) return null
  return createPortal(
    <div
      className="animate-fade fixed inset-0 z-50 flex justify-end bg-[rgba(16,26,21,0.28)] backdrop-blur-[2px]"
      onClick={onClose}
    >
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={title}
        /* 窄屏自适应（2026-10-15）：同 Modal，补 maxWidth —— 抽屉默认 420px，
           在更窄的窗口里会横向溢出（它从右侧滑出，溢出部分既看不见也点不到）。 */
        style={{ width, maxWidth: '100%' }}
        onClick={(e) => e.stopPropagation()}
        className={cn(
          'flex h-full flex-col bg-surface shadow-tp2',
          'animate-rise',
        )}
      >
        <header className="flex h-[48px] shrink-0 items-center gap-2.5 border-b border-line-soft px-4">
          <h3 className="text-[16px] font-semibold tracking-tight text-t1">{title}</h3>
          {meta ? <span className="truncate text-[12px] text-t3">{meta}</span> : null}
          <button
            type="button"
            onClick={onClose}
            aria-label={uiT("关闭")}
            className="ml-auto flex h-7 w-7 items-center justify-center rounded-tpx text-t3 transition-colors hover:bg-p50 hover:text-p700"
          >
            <X size={16} strokeWidth={1.75} />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-auto p-3">{children}</div>
      </aside>
    </div>,
    document.body,
  )
}
