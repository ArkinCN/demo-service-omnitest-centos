import { useT } from '../../i18n'
/* ===========================================================================
   上传面板的「用途」选择器：三轴固定三类 + 可新建自定义标签。

   ⚠️ 这里有个**契约约束**必须先讲清（决定了本组件的做法）：
   `data/types.ts` 明写「用途轴，固定三类不加第四类」，主文档 3.1 也定「用途（三类）」。
   而且三轴计数是 `c.usage[e.usage] += 1`——多出第四类会让计数变成 NaN。

   所以「新建用途」不是"加第四个轴"，而是：
     · 选定一个**已有三轴**作为归类（决定它进哪个筛选组、怎么计数）；
     · 再给一个**自定义标签**作为更细的说法（存在条目正文里，不占轴线）。
   界面上把这两件事分开问，人一眼就知道「新建的是标签，归类仍要选一个」。

   为什么不干脆放开第四类：那要同时改后端枚举、schema 校验、前端类型、
   计数逻辑与左栏筛选，且与主文档冲突——**契约先于便利**。
   =========================================================================== */
import { useState } from 'react'
import { Check, ChevronDown, Plus } from 'lucide-react'
import { Input } from '../../components/ui'
import { KNOWLEDGE_USAGE_LABEL, type KnowledgeUsage } from '../../data/types'

export interface UsageChoice {
  /** 归入哪个三轴（必需，决定筛选与计数） */
  usage: KnowledgeUsage
  /** 自定义标签（可空；非空表示这是新建的说法，比三轴更细） */
  customLabel: string
}

const OPTIONS: KnowledgeUsage[] = ['spec', 'requirement', 'process']

export function UsagePicker({
  value,
  onChange,
}: {
  value: UsageChoice
  onChange: (v: UsageChoice) => void
}) {
  const uiT = useT()

  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState({ axis: value.usage, label: '' })

  const current = value.customLabel
    ? `${KNOWLEDGE_USAGE_LABEL[value.usage]} · ${value.customLabel}`
    : KNOWLEDGE_USAGE_LABEL[value.usage]

  return (
    <div className="flex flex-col gap-1">
      <span className="flex items-center gap-2 text-[12px] text-t2">
        {uiT("用途")}<span className="text-[11px] text-t3">{uiT("归入三轴之一；可另加更细的说法")}</span>
        <button
          type="button"
          onClick={() => {
            setCreating((v) => !v)
            setDraft({ axis: value.usage, label: '' })
            setOpen(false)
          }}
          className="ml-auto flex items-center gap-0.5 rounded-tps px-1.5 text-[11px] text-p700 transition-colors hover:bg-p50"
        >
          <Plus size={11} strokeWidth={2.2} />
          {creating ? uiT('取消新建') : uiT('新建用途')}
        </button>
      </span>

      {creating ? (
        <div className="flex flex-col gap-1.5 rounded-tps border border-p300 bg-p50/60 p-2">
          <div className="flex items-center gap-1.5">
            <span className="shrink-0 text-[11.5px] text-t3">{uiT("归入")}</span>
            <div className="flex gap-1">
              {OPTIONS.map((u) => (
                <button
                  key={u}
                  type="button"
                  onClick={() => setDraft({ ...draft, axis: u })}
                  className={
                    'rounded-tps border px-1.5 py-[2px] text-[11.5px] transition-colors ' +
                    (draft.axis === u
                      ? 'border-p400 bg-white font-medium text-p700'
                      : 'border-line text-t2 hover:border-p300')
                  }
                >
                  {uiT(KNOWLEDGE_USAGE_LABEL[u])}
                </button>
              ))}
            </div>
          </div>
          <Input
            value={draft.label}
            placeholder={uiT("更细的说法，如「启动测试」「量产工艺」")}
            aria-label={uiT("自定义用途")}
            onChange={(e) => setDraft({ ...draft, label: e.target.value })}
            className="h-[26px] text-[12px]"
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={!draft.label.trim()}
              onClick={() => {
                onChange({ usage: draft.axis, customLabel: draft.label.trim() })
                setCreating(false)
              }}
              className="rounded-tps border border-p300 bg-white px-2 py-[3px] text-[11.5px] text-p700 transition-colors hover:bg-p50 disabled:opacity-45"
            >
              {uiT("用这个用途")}</button>
            <span className="text-[11px] text-t3">
              {uiT("三轴仍是原有三类（筛选与计数靠它），自定义标签只是更细的说法")}</span>
          </div>
        </div>
      ) : (
        <div className="relative">
          <button
            type="button"
            aria-haspopup="listbox"
            aria-expanded={open}
            aria-label={uiT("用途")}
            onClick={() => setOpen((v) => !v)}
            className={
              'flex h-[28px] w-full items-center gap-1.5 rounded-tps border bg-white px-2.5 text-left text-[12px] font-medium transition-colors ' +
              (open ? 'border-p500 text-p700' : 'border-line text-t1 hover:border-p300')
            }
          >
            <span className="truncate">{current}</span>
            <ChevronDown
              size={14}
              strokeWidth={2}
              className={
                'ml-auto shrink-0 text-t3 transition-transform duration-150' +
                (open ? ' rotate-180' : '')
              }
            />
          </button>
          {open ? (
            <ul
              role="listbox"
              className="animate-pop absolute top-[calc(100%+6px)] z-40 max-h-[240px] min-w-full overflow-y-auto rounded-tps border border-line bg-surface py-1 shadow-tp2"
            >
              {OPTIONS.map((u) => (
                <li key={u}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={u === value.usage && !value.customLabel}
                    onClick={() => {
                      // 选三轴 = 清掉自定义标签（人明确要按轴线归类，不要再留旧标签）
                      onChange({ usage: u, customLabel: '' })
                      setOpen(false)
                    }}
                    className={
                      'flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12.5px] whitespace-nowrap transition-colors ' +
                      (u === value.usage && !value.customLabel
                        ? 'bg-p50 font-medium text-p700'
                        : 'text-t2 hover:bg-p50/70 hover:text-p700')
                    }
                  >
                    {uiT(KNOWLEDGE_USAGE_LABEL[u])}
                    {u === value.usage && value.customLabel ? (
                      <span className="ml-auto num shrink-0 text-[10.5px] text-t3">
                        {uiT("当前归入")}</span>
                    ) : null}
                    {u === value.usage && !value.customLabel ? (
                      <Check size={12} strokeWidth={2.4} className="ml-auto shrink-0 text-p600" />
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
    </div>
  )
}
