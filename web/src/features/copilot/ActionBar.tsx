import { useT } from '../../i18n'
import { useCallback, useRef, useState } from 'react'
import { copilotActionIcon } from '../../app/icons'
import type { ActionDef } from './actions'
import type { Envelope } from './context'
import { missingContext, missingHint } from './context'

/* ===========================================================================
   预置动作按钮条（06c 第 5.1 节）。

   放在输入区上方一行、与输入框同宽；一行最多 5 枚，第 6 枚起收进末尾的「更多」。
   窄屏按容器宽度递减，最少保留 2 枚加「更多」。按钮一律图标加文字，不用纯图标。
   切流程时整条替换，不做动画堆叠。
   =========================================================================== */

const MAX_VISIBLE = 5
const MIN_VISIBLE = 2
/** 12px 字下一枚按钮的估宽：图标 14 + 间距 6 + 左右内边距 18 + 每个汉字约 12.5 */
const widthOf = (label: string) => 38 + label.length * 12.5
const MORE_W = 66

export interface PickedAction {
  def: ActionDef
  /** 缺的上下文字段；非空时按钮置灰，不会触发 */
  missing: string[]
}

export function ActionBar(props: {
  defs: ActionDef[]
  env: Envelope
  busy: boolean
  onPick: (def: ActionDef) => void
}) {
  const uiT = useT()

  const { defs, env, busy, onPick } = props
  const [width, setWidth] = useState(0)
  const ro = useRef<ResizeObserver | null>(null)
  // 用回调 ref 而不是 useEffect：按钮定义是异步读进来的，
  // 「一枚都没有就整条不渲染」会让挂载期的 effect 拿不到节点，观察器就永远装不上。
  const attach = useCallback((el: HTMLDivElement | null) => {
    ro.current?.disconnect()
    ro.current = null
    if (!el || typeof ResizeObserver === 'undefined') return
    const obs = new ResizeObserver((es) => setWidth(es[0]?.contentRect.width ?? 0))
    obs.observe(el)
    ro.current = obs
  }, [])
  // 切流程时「更多」整条重来：按 defs 的身份在渲染期重置，不用 effect
  const [menu, setMenu] = useState<{ key: ActionDef[]; open: boolean }>({ key: defs, open: false })
  if (menu.key !== defs) setMenu({ key: defs, open: false })
  const open = menu.open
  const setOpen = (v: boolean | ((p: boolean) => boolean)) =>
    setMenu((m) => ({ key: m.key, open: typeof v === 'function' ? v(m.open) : v }))

  if (defs.length === 0) return null

  // 能放几枚：先按 5 枚封顶，再按容器宽度递减，下限 2 枚加「更多」
  let visible = Math.min(MAX_VISIBLE, defs.length)
  if (width > 0) {
    const minimum = uiT('更多') === '更多' ? MIN_VISIBLE : 1
    while (visible > minimum) {
      const used = defs.slice(0, visible).reduce((a, d) => a + widthOf(uiT(d.label)) + 6, 0)
      if (used + (defs.length > visible ? MORE_W : 0) <= width) break
      visible -= 1
    }
  }
  const shown = defs.slice(0, visible)
  const rest = defs.slice(visible)

  /**
   * 忙态只禁用执行类，讲解与准备类保持可点（编排者裁决第 3 条）。
   *
   * 并行期整条按钮条一律随忙态置灰，于是流程 3 那样「开场脚本停在启动闸门上、
   * 整轮不结束」的页面会五枚全灰，观感像坏掉了。真正不能并发的是会动设备与
   * 数据的执行类；讲解与准备只往对话里追加一轮，排队跑没有副作用。
   */
  const state = (d: ActionDef) => {
    if (d.available === false) return { off: true, why: d.unavailable_reason ?? '本场景未开放' }
    const miss = missingContext(d, env)
    if (miss.length) return { off: true, why: `缺上下文：${missingHint(miss)}` }
    if (busy && d.type === 'execute')
      return { off: true, why: '上一轮还没跑完，执行类动作要等它收尾' }
    return { off: false, why: '' }
  }

  const title = (d: ActionDef, why: string) =>
    why
      ? uiT('{v1} · 暂不可用 {v2}', { v1: uiT(d.label), v2: uiT(why) })
      : uiT('{v1} {v2} 类型：{v3} 规程：{v4}{v5}', {
          v1: uiT(d.label), v2: uiT(d.echo), v3: uiT(TYPE_LABEL[d.type]),
          v4: d.skill_ref, v5: d.skill_verify === 'unverified' ? uiT('（待核实）') : '',
        })

  const fire = (d: ActionDef) => {
    setOpen(false)
    if (state(d).off) return
    onPick(d)
  }

  return (
    <div className="cp-actions" ref={attach}>
      {shown.map((d) => {
        const Icon = copilotActionIcon(d.icon)
        const s = state(d)
        return (
          <button
            key={d.id}
            type="button"
            className="cp-act"
            data-redline={String(d.touches_redline)}
            disabled={s.off}
            title={title(d, s.why)}
            onClick={() => fire(d)}
          >
            <Icon size={13} strokeWidth={1.9} />
            {uiT(d.label)}
          </button>
        )
      })}
      {rest.length ? (
        <div className="cp-more">
          <button
            type="button"
            className="cp-act cp-act--more"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
            title={uiT("另有 {v1} 枚预置动作", { v1: rest.length })}
          >
            {uiT("更多 ")}{rest.length}
          </button>
          {open ? (
            <div className="cp-more__menu" role="menu">
              {rest.map((d) => {
                const Icon = copilotActionIcon(d.icon)
                const s = state(d)
                return (
                  <button
                    key={d.id}
                    type="button"
                    role="menuitem"
                    className="cp-more__item"
                    disabled={s.off}
                    title={title(d, s.why)}
                    onClick={() => fire(d)}
                  >
                    <Icon size={13} strokeWidth={1.9} />
                    {uiT(d.label)}
                    <span className="cp-more__type">{uiT(TYPE_LABEL[d.type])}</span>
                  </button>
                )
              })}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

const TYPE_LABEL: Record<ActionDef['type'], string> = {
  explain: '解释',
  prepare: '准备',
  execute: '执行',
}
