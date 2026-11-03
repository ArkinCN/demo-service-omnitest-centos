import { useT } from '../../i18n'
import { useEffect, useRef } from 'react'
import { AlertTriangle, LogOut } from 'lucide-react'
import { Button } from '../../components/ui'

/* ===========================================================================
   自动化回归 · 退出二次确认（2026-10-10 新增）

   为什么需要它：运行中点「退出自动化测试」会让操作者**离开现场**——曲线、
   进度、日志都看不见了，而本轮真机测试仍在后台继续跑。这一步改变的是眼前
   的现场，因此必须先问一句，避免误触。

   文案口径（需求单原文，不改写、不换说法）：
     · 提示：测试正在运行，确定退出吗？
     · 补充：退出仅关闭当前界面，后台测试将继续跑完。

   三个「安全方向」等价：Esc、点遮罩空白、点「取消」——全部算取消。
   初始焦点落在「取消」：默认答案取最保守的那个，回车不会误退。

   ⚠️ 本组件**不自己判断运行态**：是否该弹由调用方（AutomationRunOverlay）
   按 runStatus 决定；终态时调用方会把它收掉（「已经跑完了还问你在不在跑」
   是错的）。

   ⚠️ 不 portal 到 body：它必须留在 overlay 内部（overlay 自己锁了 body 滚动，
   portal 出去会被那套锁与 z 序打乱）。层级取 z-[70]，压在结果弹窗（z-[60]）之上。
   =========================================================================== */

export function AutoExitConfirm({
  onCancel,
  onConfirm,
}: {
  /** 取消退出（留在浮层继续看）：Esc / 点遮罩 / 点「取消」三处都走它 */
  onCancel: () => void
  /** 确认退出：由调用方执行软退出（只隐藏浮层，不中断后台） */
  onConfirm: () => void
}) {
  const uiT = useT()

  const cardRef = useRef<HTMLDivElement>(null)

  /* Esc = 取消（安全方向）。capture 阶段监听并 stopPropagation，
     避免同一次按键继续冒泡给其它 Esc 监听（如结果弹窗的收起）。 */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      onCancel()
    }
    document.addEventListener('keydown', onKey, true)
    return () => document.removeEventListener('keydown', onKey, true)
  }, [onCancel])

  /* 焦点锁：Tab / Shift+Tab 在卡内两个按钮之间循环，不跑到背后界面去 */
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Tab') return
    const nodes = cardRef.current?.querySelectorAll<HTMLElement>('button')
    if (!nodes || nodes.length === 0) return
    const first = nodes[0]
    const last = nodes[nodes.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  return (
    <div
      className="automation-overlay-mask absolute inset-0 z-[70] flex items-center justify-center bg-[rgba(16,26,21,0.34)] p-4 backdrop-blur-[2px]"
      /* 点遮罩空白 = 取消（与结果弹窗「点遮罩收起」同一手感） */
      onClick={onCancel}
      data-testid="auto-exit-confirm-mask"
    >
      <div
        ref={cardRef}
        role="alertdialog"
        aria-modal="true"
        aria-label={uiT("测试正在运行，确定退出吗？")}
        data-testid="auto-exit-confirm"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
        className="animate-pop flex w-full max-w-[430px] flex-col overflow-hidden rounded-tp border border-line bg-surface shadow-tp2"
      >
        <div className="flex items-start gap-3 px-4 pt-4 pb-1">
          <span className="flex h-[38px] w-[38px] shrink-0 items-center justify-center rounded-full bg-alert-wash text-alert">
            <AlertTriangle size={19} strokeWidth={2} />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-[15px] leading-snug font-bold text-t1">
              {uiT("测试正在运行，确定退出吗？")}</h2>
            <p className="mt-1.5 text-[12.5px] leading-5 text-t3">
              {uiT("退出仅关闭当前界面，后台测试将继续跑完。")}</p>
          </div>
        </div>

        <div className="mt-3.5 flex items-center justify-end gap-2 border-t border-line-soft px-4 py-3">
          {/* autoFocus：默认焦点落在最保守的那个答案上（回车即取消） */}
          <Button
            variant="ghost"
            size="md"
            autoFocus
            onClick={onCancel}
            data-testid="auto-exit-cancel"
          >
            {uiT("取消")}</Button>
          <Button
            variant="primary"
            size="md"
            icon={<LogOut size={13} strokeWidth={1.9} />}
            onClick={onConfirm}
            data-testid="auto-exit-ok"
          >
            {uiT("确定退出")}</Button>
        </div>
      </div>
    </div>
  )
}

export default AutoExitConfirm
