import { useT } from '../../i18n'
/* ===========================================================================
   B 区顶部「本流程可用知识」窄条与抽屉。

   窄条常驻在每个流程页左栏顶部，显示本流程会调用的知识条数，
   点「查看」开右侧抽屉，不跳页。抽屉正文按 06a 第三节那张 13 个调用点的
   调用表过滤：只列本流程实际会调用的条目，按用途轴分三组，组内超过 5 条
   收成「还有 N 条」，不把整个知识库铺进抽屉。
   窄条与抽屉的外形、Props 签名与 W1 落的占位一致，没有改。
   =========================================================================== */
import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { ChevronRight } from 'lucide-react'
import { Badge, Drawer, EmptyState } from '../../components/ui'
import { KNOWLEDGE_ICON } from '../../app/icons'
import { KNOWLEDGE_USAGE_LABEL, type FlowId, type KnowledgeUsage } from '../../data/types'
import { knowledgeForFlow, useKnowledge, type KnowledgeEntry } from './data'
import { useAppStore } from '../../state/useAppStore'

export interface KnowledgeDrawerProps {
  flow: FlowId
  /** 本流程可用知识条数；不传就按调用表自己算 */
  count?: number
  /** 抽屉正文；不传就按调用表自己列 */
  children?: ReactNode
}

const USAGE_ORDER: KnowledgeUsage[] = ['spec', 'requirement', 'process']
const MAX_ROWS = 5

function Group({ usage, items }: { usage: KnowledgeUsage; items: KnowledgeEntry[] }) {
  const uiT = useT()

  const [open, setOpen] = useState(usage === 'requirement')
  if (!items.length) return null
  const Doc = KNOWLEDGE_ICON.doc
  const Exp = KNOWLEDGE_ICON.experience
  return (
    <div className="border-b border-line-soft last:border-b-0">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex h-[34px] w-full items-center gap-2 px-1 text-left transition-colors hover:bg-p50/70"
      >
        <ChevronRight
          size={14}
          strokeWidth={2}
          className={`shrink-0 text-t3 transition-transform duration-200 ${open ? 'rotate-90 text-p600' : ''}`}
        />
        <span className="text-[13px] font-semibold text-t1">{uiT(KNOWLEDGE_USAGE_LABEL[usage])}</span>
        <span className="tick ml-auto">{items.length}</span>
      </button>
      {open ? (
        <ul className="animate-fade pb-1.5">
          {items.slice(0, MAX_ROWS).map((e) => (
            <li key={e.id} className="flex items-center gap-2 py-[5px] pl-6 pr-1">
              {e.origin === 'doc' ? (
                <Doc size={13} strokeWidth={1.8} className="shrink-0 text-p600" />
              ) : (
                <Exp size={13} strokeWidth={1.8} className="shrink-0 text-p500" />
              )}
              <span className="min-w-0 flex-1 truncate text-[12.5px] text-t2" title={e.title}>
                {e.title}
              </span>
              <span className="num shrink-0 text-[11.5px] text-t3">{e.id}</span>
            </li>
          ))}
          {items.length > MAX_ROWS ? (
            <li className="py-[5px] pl-6 text-[12px] text-t3">
              {uiT("还有 ")}{items.length - MAX_ROWS} {uiT(" 条，去知识库页看全部")}</li>
          ) : null}
        </ul>
      ) : null}
    </div>
  )
}

export function KnowledgeDrawer({ flow, count, children }: KnowledgeDrawerProps) {
  const uiT = useT()

  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const { entries } = useKnowledge()
  const Icon = KNOWLEDGE_ICON.usage
  const Upload = KNOWLEDGE_ICON.upload

  const mine = knowledgeForFlow(entries, flow)
  const n = count ?? mine.length

  return (
    <>
      <div className="flex h-[30px] shrink-0 items-center gap-2 border-b border-line-soft bg-p50/60 px-3">
        <Icon size={13} strokeWidth={1.9} className="shrink-0 text-p600" />
        <span className="truncate text-[12px] text-t2">{uiT("本流程可用知识")}</span>
        <span className="num text-[11px] text-t3">{n} {uiT(" 条")}</span>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="ml-auto rounded-tps px-1.5 text-[11px] text-t2 transition-colors hover:bg-white hover:text-p700"
        >
          {uiT("查看")}</button>
        {/* 「上传」= **上传一个文件到知识库**（用户明确的口径，2026-09-24 更正）。
            此前写法变过两次，记下来免得再走回头路：
              ① 最早：没有任何 onClick，点了没反应；
              ② 上一轮改成 `nav('/knowledge')` —— 那是「跳转到知识库入口」，
                 不是用户要的「在这里上传」。用户指出「写错了」。
              ③ 现在：置一个跨页信号 + 跳到知识库页，那一页看到信号**直接开上传面板**，
                 人立刻就能选文件，不用再自己找入口。 */}
        <button
          type="button"
          aria-label={uiT("上传知识")}
          title={uiT("上传一份资料到知识库")}
          onClick={() => {
            useAppStore.getState().requestKbUpload(true)
            nav('/knowledge')
          }}
          className="flex h-5 items-center gap-1 rounded-tps px-1.5 text-[11px] text-t2 transition-colors hover:bg-white hover:text-p700"
        >
          <Upload size={12} strokeWidth={1.9} />
          {uiT("上传")}</button>
      </div>

      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title={uiT("本流程可用知识")}
        meta={uiT("{v1} 条", { v1: n })}
        width={460}
      >
        {children ??
          (mine.length ? (
            <div className="px-1">
              <p className="pb-2 text-[12px] text-t3">
                {uiT("只列本流程会调用的条目，按用途轴分三组。")}</p>
              {USAGE_ORDER.map((u) => (
                <Group key={u} usage={u} items={mine.filter((e) => e.usage === u)} />
              ))}
              <div className="flex items-center gap-2 pt-3">
                <Badge tone="soft">{uiT("去知识库页管理全部条目")}</Badge>
              </div>
            </div>
          ) : (
            <EmptyState
              title={uiT("本流程暂无调用")}
              hint={uiT("场景包登记里没有标到这条流程的知识条目。")}
            />
          ))}
      </Drawer>
    </>
  )
}
