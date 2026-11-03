import { useT } from '../../i18n'
import { useEffect } from 'react'
import { AlertOctagon, Check, CircleSlash, Download, FileBarChart, RotateCcw, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Button, cn } from '../../components/ui'
import type { AutomationSummary } from '../../state/useAppStore'
import { fmtElapsed, fmtPct } from '../shared/format'
import type { StageView, VerdictStats } from './automationViewModel'

/* ===========================================================================
   自动化回归 · 完成弹窗（浮在运行台之上）

   2026-10-09：由「整屏结果页」改为**居中模态弹窗**。
   为什么改：跑完之后人最想做的两件事是「看这轮采到的曲线/日志/判定」和
   「看结论」。老实现把结果做成整屏页，一关就整层卸载、本轮数据全丢。
   现在它是盖在运行台上的弹窗 —— 收起它，运行台与本轮数据原样还在。

   三条交互口径（与 Overlay 约定一致）：
     · 「关闭」= 收起弹窗（**只收起**，不退出回归、不清运行台数据）；
     · 「重新运行」= 回引导屏（不直接开跑，仍要人确认一次现场安全）；
     · 「查看报告」= 原地打开报告预览弹窗（不退出回归、不跳报告页）。

   数据纪律（本页最要紧的一条）：**四块统计全部取编排器事件的真值**，
     · 总耗时 ← startedAt/finishedAt 做减法，不由前端累加计时器；
     · 采样点数 ← 本轮 LIVE 通道真实样本条数，不是「计划档数 × 系数」；
     · 调优轮次 ← tune 阶段成功次数，0 就显示 0（一次都没进调优）；
     · 报告三态 ← 后端 ok / placeholder / blocked，**绝不把占位件说成交付件**。
   =========================================================================== */

export function AutomationResult({
  status,
  stages,
  stats,
  summary,
  onDismiss,
  onRetry,
  onViewReport,
  onRedownload,
}: {
  status: 'completed' | 'failed' | 'stopped'
  stages: StageView[]
  stats: VerdictStats
  summary: AutomationSummary
  /** 收起弹窗（停留运行台）；**不是**退出回归 */
  onDismiss: () => void
  onRetry: () => void
  /** 打开报告预览弹窗（原地，不退出回归、不跳页） */
  onViewReport: () => void
  onRedownload: () => void
}) {
  const uiT = useT()

  const elapsed =
    summary.startedAt !== null && summary.finishedAt !== null
      ? Math.max(0, summary.finishedAt - summary.startedAt)
      : null
  const failedStage = stages.find((s) => s.status === 'failed')
  const judged = stats.total ?? 0

  const head: { icon: LucideIcon; cls: string; title: string; sub: string } =
    status === 'completed'
      ? {
          icon: Check,
          cls: 'bg-p600 text-white',
          title: '自动化回归已完成',
          sub: '五个阶段全部走完，报告已产出',
        }
      : status === 'failed'
        ? {
            icon: AlertOctagon,
            cls: 'bg-alert text-white',
            title: '自动化回归失败',
            sub: failedStage ? `停在「${failedStage.name}」（本轮已采数据与产物保留）` : '流程中断（本轮已采数据与产物保留）',
          }
        : {
            icon: CircleSlash,
            cls: 'bg-t3/25 text-t2',
            title: '已终止',
            sub: '已采数据与已落库产物保留',
          }

  /* 四块统计：取不到就显示「—」，绝不填 0 充数
     ⚠️ 所有文案都用「占位模板 + 参数」，不要在数组里拼好字符串：
     catalog 的 key 是全中文模板（如 "{v1} 轮"），拼过的串命中不了词典。 */
  const cards: { label: string; value: string }[] = [
    { label: '总耗时', value: elapsed === null ? '—' : fmtElapsed(elapsed) },
    {
      label: '判定通过比',
      value:
        stats.total === null
          ? '—'
          : `${stats.pass}/${stats.total}（${fmtPct(stats.pass, stats.total)}）`,
    },
    {
      label: '采样点数',
      value: summary.sampleCount === null ? '—' : uiT('{v1} 条', { v1: summary.sampleCount }),
    },
    { label: '调优轮次', value: uiT('{v1} 轮', { v1: summary.tuneRounds }) },
  ]

  /* Esc 收起弹窗：弹窗是模态层，键盘用户也要能退出来 */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onDismiss()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onDismiss])

  return (
    /*
      遮罩：整层半透明深墨绿 + 轻模糊，沿用 Modal 的既有视觉语言。
      点遮罩空白 = 收起弹窗；卡片内 stopPropagation，点内容不穿透。
      ⚠️ 不 portal 到 body：它必须留在 overlay 内部（overlay 自己锁了 body 滚动，
      portal 出去会被这套锁与 z 序打乱）。
    */
    <div
      className="automation-overlay-mask absolute inset-0 z-[60] flex items-center justify-center bg-[rgba(16,26,21,0.34)] p-4 backdrop-blur-[2px]"
      onClick={onDismiss}
      data-testid="auto-result-mask"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={uiT(head.title)}
        data-testid="auto-result-dialog"
        onClick={(e) => e.stopPropagation()}
        className="animate-pop flex max-h-[88%] w-full max-w-[760px] flex-col overflow-hidden rounded-tp border border-line bg-surface shadow-tp2"
      >
        {/*
          2026-10-09：**移除弹窗右上角的 ✕**（用户：「删除右上角的关闭，多余了」）。
          理由：底部动作行已有「关闭」（`auto-result-close`），两者是同一条动作
          （都调 `onDismiss`），同一条动作出现两个入口会让人不知道该点哪个——
          与全站「确认/关闭类动作只留一个入口」的口径一致。
          收起弹窗的其它途径仍保留：底部「关闭」、Esc、点遮罩空白。
        */}

        <div className="min-h-0 flex-1 overflow-y-auto px-4 pt-4 pb-4">
          <div className="mx-auto flex w-full max-w-[680px] flex-col">
            {/* 徽章 + 标题 */}
            <div className="flex flex-col items-center text-center">
              <span
                className={cn(
                  'num flex h-[76px] w-[76px] flex-col items-center justify-center rounded-full text-[17px] leading-tight font-bold text-white',
                  head.cls,
                )}
                style={{ boxShadow: '0 0 0 9px var(--tp-p-100), 0 0 0 18px rgba(46,94,69,0.05)' }}
              >
                {stats.total === null ? (
                  '—'
                ) : (
                  <>
                    {stats.pass}/{stats.total}
                    <span className="text-[10px] font-medium">{uiT("通过")}</span>
                  </>
                )}
              </span>
              <h1 className="mt-4 text-[19px] leading-tight font-bold tracking-tight text-t1">
                {uiT(head.title)}
              </h1>
              {/* 2026-10-14：补 uiT() —— 此前只包了 head.title，这句副标题
                  （「五个阶段全部走完，报告已产出」）在英文模式下漏翻。 */}
              <p className="mt-1.5 text-[12.5px] text-t3">{uiT(head.sub)}</p>
            </div>

            {/* 失败/中断原因：有就原样写出来，不吞 */}
            {status !== 'completed' && summary.errorMessage ? (
              <div className="mt-3.5 rounded-tps border border-alert bg-alert-wash px-3 py-2 text-[12px] leading-5 text-alert">
                {summary.errorMessage}
              </div>
            ) : null}

            {/* 四块统计 */}
            <div className="mt-3.5 grid grid-cols-4 gap-2">
              {cards.map((c) => (
                <div
                  key={c.label}
                  className="flex flex-col items-center gap-0.5 rounded-tps border border-line-soft bg-surface px-2 py-2.5"
                >
                  <span className="num text-[17px] leading-none font-semibold text-t1">{c.value}</span>
                  <span className="text-[11px] text-t3">{uiT(c.label)}</span>
                </div>
              ))}
            </div>

            {/* 五阶段回执：逐条含状态、消息与该段耗时 */}
            <div className="mt-3.5 rounded-tps border border-line-soft bg-surface">
              <div className="border-b border-line-soft px-3 py-2 text-[12px] font-semibold text-t1">
                {uiT("阶段回执")}</div>
              <div className="px-3 py-1">
                {stages.map((s) => (
                  <div
                    key={s.id}
                    className="flex items-center gap-2 border-b border-line-soft py-[6px] text-[12px] last:border-b-0"
                  >
                    <span
                      className={cn(
                        'h-[6px] w-[6px] shrink-0 rounded-full',
                        s.status === 'failed'
                          ? 'bg-alert'
                          : s.status === 'success'
                            ? 'bg-p600'
                            : s.status === 'skipped'
                              ? 'bg-t3/40'
                              : 'bg-p200',
                      )}
                    />
                    <span className="shrink-0 font-medium text-t1">{uiT(s.name)}</span>
                    <span className="min-w-0 flex-1 truncate text-t3">{s.message ? uiT(s.message) : '—'}</span>
                    <span className="num shrink-0 text-[11.5px] text-t3">
                      {s.elapsed === null ? '—' : fmtElapsed(s.elapsed)}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* 报告三态行：措辞沿用后端三档口径，未生成时明说不会触发下载 */}
            <div
              className="mt-3 flex items-start gap-2 rounded-tps border px-3 py-2.5 text-[12px] text-t2"
              style={{
                borderColor:
                  summary.reportStatus === 'blocked' ? 'var(--tp-alert)' : 'var(--tp-p-200)',
                background:
                  summary.reportStatus === 'blocked' ? 'var(--tp-alert-wash)' : 'var(--tp-p-50)',
              }}
            >
              <FileBarChart
                size={14}
                strokeWidth={1.9}
                className={cn(
                  'mt-0.5 shrink-0',
                  summary.reportStatus === 'blocked' ? 'text-alert' : 'text-p700',
                )}
              />
              <div className="min-w-0 flex-1">
                {summary.reportStatus === 'ok' || summary.reportStatus === 'placeholder' ? (
                  <>
                    <p className="text-t1">
                      {summary.reportStatus === 'ok'
                        ? uiT('报告已生成')
                        // 2026-10-10 前落的历史轮次才是占位版式；新生成一律走 ok
                        : uiT('报告已生成（历史占位版式）')}
                      {summary.reportDownloaded ? uiT('，并已触发下载。') : uiT('，但下载可能被浏览器拦截。')}
                    </p>
                    <p className="mt-0.5 text-[11.5px] text-t3">
                      {summary.reportFile ? uiT("文件 {v1}", { v1: summary.reportFile }) : ''}
                      {status !== 'completed'
                        ? uiT(' · 本轮测试未全部通过，报告为失败快照（缺的项如实标注「未提供」）')
                        : ''}
                    </p>
                  </>
                ) : summary.reportStatus === 'blocked' ? (
                  <>
                    <p className="text-alert">
                      <b>{uiT("报告未生成")}</b>：{summary.reportReason || uiT('后端未产出报告文件')}
                    </p>
                    <p className="mt-0.5 text-[11.5px] text-t3">
                      {uiT("没有可下载的文件，因此本轮不会触发下载（不假装下载成功）。修好上述原因后点「重新运行」。")}</p>
                  </>
                ) : (
                  <p className="text-t3">{uiT("本轮没有走到报告阶段（提前终止），因此没有报告可下载。")}</p>
                )}
              </div>
              {summary.reportStatus === 'ok' || summary.reportStatus === 'placeholder' ? (
                <Button
                  variant="secondary"
                  size="sm"
                  className="ml-auto shrink-0"
                  icon={<Download size={13} strokeWidth={1.9} />}
                  onClick={onRedownload}
                >
                  {uiT("重新下载")}</Button>
              ) : null}
            </div>

            {/* 动作 */}
            <div className="mt-4 flex shrink-0 items-center gap-2">
              {summary.reportStatus === 'ok' || summary.reportStatus === 'placeholder' ? (
                <Button
                  variant="primary"
                  size="lg"
                  icon={<FileBarChart size={15} strokeWidth={1.9} />}
                  onClick={onViewReport}
                >
                  {uiT("查看报告")}</Button>
              ) : null}
              <Button
                variant={status === 'completed' ? 'secondary' : 'primary'}
                size="lg"
                icon={<RotateCcw size={15} strokeWidth={1.9} />}
                onClick={onRetry}
                data-testid="auto-result-retry"
              >
                {uiT("重新运行")}</Button>
              <Button
                variant="ghost"
                size="lg"
                icon={<X size={15} strokeWidth={1.9} />}
                onClick={onDismiss}
                data-testid="auto-result-close"
              >
                {uiT("关闭")}</Button>
              <span className="num ml-auto text-[11.5px] text-t3">
                {uiT("轮次 ")}{summary.runId ? summary.runId.slice(0, 8) : '—'} {uiT(" · 判定表 ")}{judged || '—'} {uiT(" 条 · 代确认闸门 ")}{summary.gateAckCount} {uiT(" 条")}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
