import { useT } from '../../i18n'
/* ===========================================================================
   知识库上传的「归属」选择器：三级（场景 › 子类 › 产品类型）。

   为什么要单独做一个而不是用现成的 Select：
   归属是**三级**的，而且用户明确提出要有**新建**入口——
   「避免上传找不到归属的情况」（原话）：资料可能不属于任何一个已登记的产品，
   比如一份通用的安全规范、或一个还没建包的新产品。此时若归属只能读当前产品，
   人就只能放弃上传或随便挂到一个不相关的产品下，两种结果都错。

   三条规则：
     一、**已有归属可选**：三级目录取自 `public/scenes/index.json` 的 catalog，
         与左栏三轴筛选、ProductCascader 用的是同一份来源，不另配一遍。
     二、**可新建**：任一级都能现场新建。新建只是给出一个**名字**，
         它不会去创建场景包（那要另走建包流程）——所以新建的归属在界面上
         明确标「新」，且**不假装它已经是场景包**。
     三、**取不到就说取不到**：catalog 拉不到时不让整块消失，
         退回两个输入框让人手填，而不是静默把归属置空
         （归属空 = 这份资料谁都看不见，比报错更隐蔽）。
   =========================================================================== */
import { useMemo, useState } from 'react'
import { Check, ChevronDown, Plus } from 'lucide-react'
import { Input } from '../../components/ui'
import { useAppStore } from '../../state/useAppStore'

export interface OwnerTriple {
  l1: string
  l2: string
  l3: string
}

interface CatalogNode {
  label: string
  sceneId?: string
  children?: CatalogNode[]
}

/** 把 catalog 拍平成「一级 › 二级 › 三级」的候选行。
 *  只到二级的、只到一级的分支也收进来——目录不齐时那些层也是有效归属。 */
function flatten(catalog: CatalogNode[] | undefined): OwnerTriple[] {
  const out: OwnerTriple[] = []
  for (const a of catalog ?? []) {
    const level2 = a.children ?? []
    if (!level2.length) {
      out.push({ l1: a.label, l2: '', l3: '' })
      continue
    }
    for (const b of level2) {
      const level3 = b.children ?? []
      if (!level3.length) {
        out.push({ l1: a.label, l2: b.label, l3: '' })
        continue
      }
      for (const c of level3) out.push({ l1: a.label, l2: b.label, l3: c.label })
    }
  }
  return out
}

const keyOf = (o: OwnerTriple) => `${o.l1} › ${o.l2} › ${o.l3}`
const labelOf = (o: OwnerTriple) =>
  [o.l1, o.l2, o.l3].filter(Boolean).join(' › ')

export function OwnerPicker({
  value,
  onChange,
  defaultOwner,
}: {
  value: OwnerTriple
  onChange: (v: OwnerTriple) => void
  /** 当前产品（缺省候选，也是「用作归属」的一键入口） */
  defaultOwner: OwnerTriple
}) {
  const uiT = useT()

  const catalog = useAppStore((s) => s.catalog) as CatalogNode[] | undefined
  const options = useMemo(() => {
    const list = flatten(catalog)
    // 把当前产品排最前：绝大多数上传都是挂在正在看的产品下
    const defKey = keyOf(defaultOwner)
    const rest = list.filter((o) => keyOf(o) !== defKey)
    return defaultOwner.l1 ? [defaultOwner, ...rest] : list
  }, [catalog, defaultOwner])

  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState<OwnerTriple>(
    value.l1 ? value : defaultOwner,
  )

  const currentLabel = labelOf(value)

  return (
    <div className="flex flex-col gap-1">
      <span className="flex items-center gap-2 text-[12px] text-t2">
        {uiT("归属")}<span className="text-[11px] text-t3">{uiT("三级：场景 › 子类 › 产品类型")}</span>
        <button
          type="button"
          onClick={() => {
            setCreating((v) => !v)
            setDraft(value.l1 ? value : defaultOwner)
            setOpen(false)
          }}
          className="ml-auto flex items-center gap-0.5 rounded-tps px-1.5 text-[11px] text-p700 transition-colors hover:bg-p50"
        >
          <Plus size={11} strokeWidth={2.2} />
          {creating ? uiT('取消新建') : uiT('新建归属')}
        </button>
      </span>

      {creating ? (
        // 新建：三级各一个输入框。**不限制必须填满三级**——
        // 一份通用规范可能只有一级或两级，强迫填满会逼人编一个不存在的子类。
        <div className="flex flex-col gap-1.5 rounded-tps border border-p300 bg-p50/60 p-2">
          <div className="grid grid-cols-3 gap-1.5">
            <Input
              value={draft.l1}
              placeholder={uiT("一级，如 通用")}
              aria-label={uiT("归属一级")}
              onChange={(e) => setDraft({ ...draft, l1: e.target.value })}
              className="h-[26px] text-[12px]"
            />
            <Input
              value={draft.l2}
              placeholder={uiT("二级（可空）")}
              aria-label={uiT("归属二级")}
              onChange={(e) => setDraft({ ...draft, l2: e.target.value })}
              className="h-[26px] text-[12px]"
            />
            <Input
              value={draft.l3}
              placeholder={uiT("三级（可空）")}
              aria-label={uiT("归属三级")}
              onChange={(e) => setDraft({ ...draft, l3: e.target.value })}
              className="h-[26px] text-[12px]"
            />
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={!draft.l1.trim()}
              onClick={() => {
                const v = { l1: draft.l1.trim(), l2: draft.l2.trim(), l3: draft.l3.trim() }
                onChange(v)
                setCreating(false)
              }}
              className="rounded-tps border border-p300 bg-white px-2 py-[3px] text-[11.5px] text-p700 transition-colors hover:bg-p50 disabled:opacity-45"
            >
              {uiT("用这个归属")}</button>
            <span className="text-[11px] text-t3">
              {uiT("新建的只是归属名，不会创建场景包；三级可留空")}</span>
          </div>
        </div>
      ) : (
        <div className="relative">
          <button
            type="button"
            aria-haspopup="listbox"
            aria-expanded={open}
            aria-label={uiT("归属")}
            onClick={() => setOpen((v) => !v)}
            className={
              'flex h-[28px] w-full items-center gap-1.5 rounded-tps border bg-white px-2.5 text-left text-[12px] font-medium transition-colors ' +
              (open ? 'border-p500 text-p700' : 'border-line text-t1 hover:border-p300')
            }
          >
            <span className={'truncate ' + (currentLabel ? '' : 'text-t3')}>
              {currentLabel || uiT('选一个归属，或新建')}
            </span>
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
              className="animate-pop absolute top-[calc(100%+6px)] z-40 max-h-[240px] min-w-full overflow-auto rounded-tps border border-line bg-surface py-1 shadow-tp2"
            >
              {options.length ? (
                options.map((o) => (
                  <li key={keyOf(o)}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={keyOf(o) === keyOf(value)}
                      onClick={() => {
                        onChange(o)
                        setOpen(false)
                      }}
                      className={
                        'flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12.5px] whitespace-nowrap transition-colors ' +
                        (keyOf(o) === keyOf(value)
                          ? 'bg-p50 font-medium text-p700'
                          : 'text-t2 hover:bg-p50/70 hover:text-p700')
                      }
                    >
                      <span className="truncate">{labelOf(o)}</span>
                      {keyOf(o) === keyOf(defaultOwner) ? (
                        <span className="ml-auto shrink-0 text-[10.5px] text-t3">{uiT("当前产品")}</span>
                      ) : null}
                      {keyOf(o) === keyOf(value) ? (
                        <Check size={12} strokeWidth={2.4} className="ml-auto shrink-0 text-p600" />
                      ) : null}
                    </button>
                  </li>
                ))
              ) : (
                <li className="px-2.5 py-2 text-[12px] text-t3">
                  {uiT("已有归属目录取不到，请用上方「新建归属」手填。")}</li>
              )}
            </ul>
          ) : null}
        </div>
      )}
    </div>
  )
}
