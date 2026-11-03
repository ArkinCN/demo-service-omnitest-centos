import { useLocale, useT } from '../i18n'
import { useEffect, useRef, useState } from 'react'
import { ChevronDown, Cpu } from 'lucide-react'
import type { CatalogNode } from '../data/loadScene'
import { Button, Modal, Select, cn } from '../components/ui'
import { hasUnsavedChanges, useAppStore } from '../state/useAppStore'


interface Pending {
  path: [string, string, string]
  sceneId?: string
  label: string
}

/**
 * 场景包芯片：顶栏只占一枚圆角芯片（产品图标 + 三级产品名），
 * 点开才是三级级联。目录来自 public/scenes/index.json，不写死在代码里。
 */
export function ProductCascader() {
  const uiT = useT()
  const { locale } = useLocale()
  const opts = (nodes: CatalogNode[] = []) => nodes.map((node) => ({ value: node.label, label: uiT(node.label) }))

  const path = useAppStore((s) => s.path)
  const catalog = useAppStore((s) => s.catalog)
  const selectProduct = useAppStore((s) => s.selectProduct)
  const touched = useAppStore((s) => s.touched)
  const confirmed = useAppStore((s) => s.confirmed)
  const [pending, setPending] = useState<Pending | null>(null)
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  if (!catalog.length)
    return <span className="tick shrink-0">{uiT("目录读取中")}</span>

  const lv1 = catalog.find((n) => n.label === path[0]) ?? catalog[0]
  const lv2 = lv1.children?.find((n) => n.label === path[1]) ?? lv1.children?.[0]
  const lv3 = lv2?.children?.find((n) => n.label === path[2]) ?? lv2?.children?.[0]

  const go = (next: Pending) => {
    if (next.path.join('/') === path.join('/')) return
    if (hasUnsavedChanges({ touched, confirmed })) setPending(next)
    else selectProduct(next.path, next.sceneId)
  }

  const pickL1 = (v: string) => {
    const a = catalog.find((n) => n.label === v)
    if (!a) return
    const b = a.children?.[0]
    const c = b?.children?.[0]
    go({ path: [a.label, b?.label ?? '', c?.label ?? ''], sceneId: c?.sceneId, label: c?.label ?? a.label })
  }
  const pickL2 = (v: string) => {
    const b = lv1.children?.find((n) => n.label === v)
    const c = b?.children?.[0]
    go({ path: [lv1.label, v, c?.label ?? ''], sceneId: c?.sceneId, label: c?.label ?? v })
  }
  const pickL3 = (v: string) => {
    const c = lv2?.children?.find((n) => n.label === v)
    go({ path: [lv1.label, lv2?.label ?? '', v], sceneId: c?.sceneId, label: v })
  }

  const changedCount = Object.keys(touched).length
  const lockedFlows = Object.entries(confirmed).filter(([, v]) => v).length

  return (
    <div ref={box} className="relative shrink-0">
      <button
        type="button"
        aria-expanded={open}
        title={`${uiT(lv1.label)} › ${uiT(lv2?.label)} › ${uiT(lv3?.label)}`}
        onClick={() => setOpen((v) => !v)}
        style={locale === 'en' ? { maxWidth: 'min(280px, 15vw)', minWidth: 0 } : undefined}
        className={cn(
          'product-cascader-trigger flex h-[34px] max-w-[280px] items-center gap-2 rounded-full border px-2.5 pr-2 transition-colors duration-150',
          open ? 'border-p400 bg-p50' : 'border-line bg-white hover:border-p300 hover:bg-p50/60',
        )}
      >
        <span className="flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full bg-p100 text-p700">
          <Cpu size={13} strokeWidth={1.75} />
        </span>
        <span className="truncate text-[13px] font-medium text-t1">{uiT(lv3?.label ?? lv1.label)}</span>
        <ChevronDown
          size={14}
          strokeWidth={2}
          className={cn('shrink-0 text-t3 transition-transform', open && 'rotate-180')}
        />
      </button>

      {open ? (
        <div className="animate-pop absolute top-[42px] right-0 z-40 w-[320px] rounded-tp border border-line bg-surface p-3 shadow-tp2">
          <div className="tick mb-2">{uiT("场景包")}</div>
          <div className="space-y-2">
            <Select size="sm" label={uiT("一级场景")} options={opts(catalog)} value={lv1.label} onChange={pickL1} />
            <Select size="sm" label={uiT("二级子类")} options={opts(lv1.children)} value={lv2?.label} onChange={pickL2} />
            <Select size="sm" label={uiT("三级产品类型")} options={opts(lv2?.children)} value={lv3?.label} onChange={pickL3} />
          </div>
        </div>
      ) : null}

      <Modal
        open={!!pending}
        onClose={() => setPending(null)}
        title={uiT("未保存内容将丢失")}
        meta={pending ? uiT("切换到 {v1}", { v1: pending.label }) : ''}
        footer={
          <>
            <Button size="sm" variant="ghost" onClick={() => setPending(null)}>
              {uiT("取消")}</Button>
            <Button
              size="sm"
              variant="danger"
              onClick={() => {
                if (pending) selectProduct(pending.path, pending.sceneId)
                setPending(null)
              }}
            >
              {uiT("丢弃并切换")}</Button>
          </>
        }
      >
        <div className="w-[420px] max-w-full px-1 py-2 text-[13px] leading-6 text-t2">
          <p className="text-t1">{uiT("换产品类型会把六条流程的数据整体换成另一个场景包。")}</p>
          <p>
            {uiT("当前有 ")}<span className="num text-alert">{changedCount}</span> {uiT(" 项人工改过的参数")}{lockedFlows ? (
              <>
                、<span className="num text-alert">{lockedFlows}</span> {uiT(" 条已确认锁定的流程")}</>
            ) : null}
            {uiT("，切换后一并丢弃，且不可撤销。")}</p>
          <p className="text-t3">{uiT("要保留的话，先取消，把本流程的参数另存为模板再回来切。")}</p>
        </div>
      </Modal>
    </div>
  )
}
