import { useT } from '../../i18n'
import { useMemo } from 'react'
import { PlayCircle, ShieldCheck, Sliders, Timer, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Button } from '../../components/ui'
import { FLOWS } from '../../data/flows'
import { getPack } from '../scene/pack'
// 调优重跑轮次从编排器的唯一来源取，不在这里另写一个数字（两处口径曾漂移过）
import { TUNE_RETRIES } from './automationOrchestrator'

/* ===========================================================================
   自动化回归 · 一屏引导（授权前置）

   存在的唯一理由：点「开始自动回归」之前让人知道马上会发生什么。
   屏上不放假进度、不放假倒计时：耗时只给区间估计并标明依据。
   =========================================================================== */

/** 每步一句「这一步在做什么 + 人测页对应哪个动作」 */
const STAGE_HINT: Record<string, string> = {
  init: '读取场景包并落库配置快照，锁定本轮基线参数（对应「确认并锁定」）',
  req: '把本场景全部判据纳入需求基线，确定这轮判哪些（对应「确认基线」）',
  run: '下发设备启动、真采集转速与波形，交给后端出权威判定（对应「确认参数并启动测试」）',
  tune: '未达标项自动采纳推荐参数并写回，再回流程 3 重测（对应「确认采纳」）',
  report: '按模板装配报告并下载到本机（对应「生成报告」）',
}

export function AutomationIntro({
  gateAcked,
  onStart,
  onCancel,
}: {
  /** 已勾选条数；引导屏据此如实说「将代确认 N 条」 */
  gateAcked: number
  onStart: () => void
  onCancel: () => void
}) {
  const uiT = useT()

  /**
   * 闸门清单**自己从场景包读**，不读 store 的 `gateTotal`。
   *
   * ⚠️ 为什么：`gateTotal` 是由流程 3 左栏的 `ConfigOverview` 挂载时调
   * `setGateTotal` 写入的。全屏接管时那个左栏根本没挂载 → `gateTotal` 恒为 0
   * → 引导屏会显示「场景包未加载，无法统计闸门条数」，可实际上闸门一条不少、
   * 待会照样会被逐条代确认。**授权屏报错数会让人误判现场状态**，必须自己读。
   * 口径与流程 3 左栏一致：只算人员类 + 流程类。
   */
  const gateIds = useMemo(() => {
    const pack = getPack()
    if (!pack) return null
    return pack.interlocks.interlocks
      .filter((i) => i.type === '人员' || i.type === '流程')
      .map((i) => i.id)
  }, [])
  /** null = 场景包确实还没加载好；此时不谎报「0 条」 */
  const gateTotal = gateIds ? gateIds.length : 0
  const willAck = gateIds ? Math.max(0, gateTotal - gateAcked) : 0

  // ⚠️ 所有 title/body 都必须过 uiT()，否则英文界面下会漏翻成中文。
  // 带动态数值的写「中文原文 + {v1}/{v2} 占位」，与 catalog.ts 词条一一对应。
  const notes: { title: string; body: string }[] = [
    {
      title: uiT('参数怎么选'),
      body: uiT(
        '按「上次采纳值 → 初始化快照 → 场景包文档值」回落。判定不达标时自动采纳推荐参数、写回并回到第 3 步重测，最多 {v1} 轮。',
        { v1: TUNE_RETRIES },
      ),
    },
    {
      title: gateIds
        ? uiT('将代为确认 {v1} 条安全闸门（共 {v2} 条）', { v1: willAck, v2: gateTotal })
        : uiT('安全闸门'),
      body: gateIds
        ? uiT(
            '已确认 {v1} 条，还差 {v2} 条。点开始即授权代确认，操作者记 automation，逐条写入执行日志可审计。',
            { v1: gateAcked, v2: willAck },
          )
        : uiT(
            '场景包尚未加载完成，无法统计闸门条数；若到开始时仍未加载，后端闸门校验会拒绝启动（原因会原样显示）。',
          ),
    },
    {
      title: uiT('会真下发设备启动'),
      // 全程时长不写死分钟数：它随调优轮次变，改成由 TUNE_RETRIES 派生的采集轮数，
      // 免得改了上限而耗时说明还停在旧口径（原来写「约 1~3 分钟」是按 3 轮估的）。
      body: uiT(
        '风扇会真的转起来。点开始前请确认现场无人接触旋转件、急停回路可用。一轮采集约 45~50 秒；调优重测最多 {v1} 轮，全程采集轮数不超过 {v2} 轮。',
        { v1: TUNE_RETRIES, v2: TUNE_RETRIES + 1 },
      ),
    },
  ]
  const NOTE_ICON: LucideIcon[] = [Sliders, ShieldCheck, Timer]

  return (
    <div className="animate-fade flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="mx-auto flex w-full max-w-[620px] flex-col">
        {/* 呼吸环：表示「将要开始」而不是「正在跑」 */}
        <div className="flex flex-col items-center pt-2 text-center">
          <div className="relative h-[76px] w-[76px]">
            <span className="automation-intro-ring absolute inset-0 rounded-full border-2 border-transparent border-t-p700" />
            <span className="automation-intro-ring-2 absolute inset-[9px] rounded-full border-2 border-transparent border-b-p300" />
            <span className="grad-ink absolute inset-[22px] rounded-full shadow-tpink" />
          </div>
          <h1 className="mt-4 text-[22px] leading-tight font-bold tracking-tight text-t1">
            {uiT("一键自动化回归")}</h1>
          <p className="mt-1.5 text-[13px] text-t3">
            {uiT("自动选参数 · 自动跑完五个流程 · 直到产出报告。全程可见、可终止、可回溯。")}</p>
        </div>

        {/* 五步清单 */}
        <ol className="mt-5 space-y-1.5">
          {FLOWS.map((f, i) => (
            <li
              key={f.id}
              className="animate-rise flex items-center gap-2.5 rounded-tps border border-line-soft bg-surface px-3 py-2"
              style={{ animationDelay: `${i * 45}ms` }}
            >
              <span className="num flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full bg-p100 text-[11px] font-semibold text-p700">
                {f.index}
              </span>
              <span className="shrink-0 text-[13px] font-medium text-t1">{uiT(f.label)}</span>
              <span className="min-w-0 flex-1 truncate text-[12px] text-t3">
                {uiT(STAGE_HINT[f.id] ?? '')}
              </span>
            </li>
          ))}
        </ol>

        {/* 三块告知：会动设备、会改参数、会代确认 */}
        <div className="mt-4 space-y-2">
          {notes.map((n, i) => {
            const Icon = NOTE_ICON[i]
            return (
              <div
                key={n.title}
                className="flex items-start gap-2.5 rounded-tps border border-p200 bg-p50 px-3 py-2.5"
              >
                <Icon size={15} strokeWidth={1.9} className="mt-0.5 shrink-0 text-p700" />
                <div className="min-w-0 flex-1">
                  <p className="text-[12.5px] font-semibold text-t1">{uiT(n.title)}</p>
                  <p className="mt-0.5 text-[12px] leading-5 text-t2">{n.body}</p>
                </div>
              </div>
            )
          })}
        </div>

        <p className="mt-3 rounded-tps border border-line-soft bg-surface px-3 py-2 text-[12px] leading-5 text-t3">
          {uiT("运行期间可随时点「终止」：当前阶段收口，已采数据与已落库产物保留； 报告无论成败都会尝试产出，未产出时如实写明原因。")}</p>

        <div className="mt-4 flex shrink-0 items-center gap-2 pb-1">
          <Button
            variant="primary"
            size="lg"
            icon={<PlayCircle size={15} strokeWidth={2} />}
            onClick={onStart}
            data-testid="auto-intro-start"
          >
            {uiT("开始自动回归")}</Button>
          <Button
            variant="ghost"
            size="lg"
            icon={<X size={15} strokeWidth={1.9} />}
            onClick={onCancel}
            data-testid="auto-intro-cancel"
          >
            {uiT("取消")}</Button>
          <span className="ml-auto text-[11.5px] text-t3">{uiT("取消不产生任何副作用")}</span>
        </div>
      </div>
    </div>
  )
}