import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

/* ===========================================================================
  五流程条 · 等比缩放 hook（2026-10-10 新增）

  需求（用户）：流程条整体放大 2 倍，但**任何分辨率都必须单行、绝不换行**；
  空间不足时按比例缩小尺寸，而不是折行。

  算法：
    s = min(1, 可用宽 W ÷ 内容自然宽 N)      // s 上限 1（不放大超过 2 倍基准）
    · W = 外层「槽」的可用宽度（去掉槽自身 padding）；
    · N = 流程条的**内容自然宽**（= 把 --fb-scale 当 1 时的宽度）。
    N 由「条内容宽 ÷ 当前 s」反推：N = 条宽 / curS（线性关系，一次即准）。
    s 写入条根 CSS 变量 --fb-scale，所有尺寸用 calc(var(--fb-scale) * 基准值)
    表达——真实布局收缩，不是 transform 缩放（不模糊、不脱流）。

  紧凑模式（data-compact）：
    标签字号 `labelPx × s` 小于 `compactTextPx`（默认 10px）→ 隐藏文字标签，
    保留放大的圆标 + 序号，悬停用 title 显示全称；随后 s 回升、图标更清晰。

  ⚠️ 稳定性（踩过的坑）：
    不能用「每次 render 都 measure」+「用 scrollWidth 反推」的写法：
      · scrollWidth 含溢出部分，缩放后内容溢出量变化 → 反推出不同 N → setState
        → 再 render → 再 measure …… React 报「Maximum update depth exceeded」。
    因此：只在**槽尺寸变化 / 挂载 / 字体就绪 / 紧凑切换**时测量，且用
    getBoundingClientRect().width（当前渲染宽，不含溢出）反推 N；条设 shrink-0，
    其渲染宽即真实内容宽（不会被父级压缩）。
   =========================================================================== */

export interface FlowBarScaleOpts {
  /** Layout content changed without a viewport resize, e.g. a language switch. */
  contentKey?: string
  /** A deliberately compact icon row uses fixed geometry instead of text measurements. */
  fixedScale?: number
  /** 标签字号基准值（×2 后），用于判定紧凑模式；不传则不启用紧凑判定 */
  labelPx?: number
  /** 标签小于该像素值时进入紧凑模式（隐藏文字、保留图标+序号） */
  compactTextPx?: number
}

export interface FlowBarScaleApi<T extends HTMLElement = HTMLDivElement> {
  /** 挂到外层「槽」容器（负责吸收剩余空间、居中，并指示可用宽度） */
  slotRef: React.RefObject<T | null>
  /** 挂到流程条根节点（写入 --fb-scale 与 data-compact） */
  barRef: React.RefObject<T | null>
  /** 当前缩放比（1 = 完整 2 倍基准；<1 = 按空间等比缩小） */
  scale: number
  /** 是否进入紧凑模式（文字已隐藏，仅图标+序号+悬停全称） */
  compact: boolean
}

export function useFlowBarScale<T extends HTMLElement = HTMLDivElement>(
  opts: FlowBarScaleOpts = {},
): FlowBarScaleApi<T> {
  const { labelPx, compactTextPx = 10, contentKey, fixedScale } = opts
  const slotRef = useRef<T | null>(null)
  const barRef = useRef<T | null>(null)
  const [scale, setScale] = useState(1)
  const [compact, setCompact] = useState(false)
  // 用 ref 保存最新状态，供测量回调读取（避免把 measure 挂进 render 依赖）
  const scaleRef = useRef(1)
  const compactRef = useRef(false)

  const apply = useCallback(
    (nextScale: number, nextCompact: boolean) => {
      if (Math.abs(nextScale - scaleRef.current) > 0.001) {
        scaleRef.current = nextScale
        setScale(nextScale)
      }
      if (nextCompact !== compactRef.current) {
        compactRef.current = nextCompact
        setCompact(nextCompact)
      }
    },
    [],
  )

  const measure = useCallback(() => {
    const slot = slotRef.current
    const bar = barRef.current
    if (!slot || !bar) return
    bar.dataset.fbContent = contentKey ?? ''
    if (fixedScale !== undefined) {
      apply(fixedScale, true)
      return
    }
    const cs = window.getComputedStyle(slot)
    const padL = parseFloat(cs.paddingLeft) || 0
    const padR = parseFloat(cs.paddingRight) || 0
    const avail = slot.clientWidth - padL - padR
    if (avail <= 0) return
    // ⚠️ 必须读 **DOM 上真实生效的 s**（data-fb-scale），不能用 scaleRef：
    // scaleRef 在 apply 时立即更新，但 React 尚未 commit DOM，此时 curW 仍是旧 scale
    // 渲染出的宽度 → natural = curW / 新ref 会算错（曾导致 1440 下条宽 560 > 槽 505 溢出）。
    const domS = Number(bar.dataset.fbScale) || scaleRef.current || 1
    const curW = bar.getBoundingClientRect().width
    if (curW <= 0 || domS <= 0) return
    const natural = curW / domS
    if (natural <= 0) return
    // 宽度与 s 非严格线性：存在不随 s 缩放的固定量（描边、gap 取整、箭头 drop-shadow
    // 外扩等），实测约数像素。用固定安全边距吸收；**不做迭代修正**——迭代会让
    // setState 反复触发、宽度微变互相追逐，最终 React 报「Maximum update depth exceeded」。
    const safeMargin = 8
    const s = Math.max(0.1, Math.min(1, (avail - safeMargin) / natural))
    const nextCompact = labelPx !== undefined && labelPx * s < compactTextPx
    apply(s, nextCompact)
  }, [labelPx, compactTextPx, apply, contentKey, fixedScale])

  // 挂载 / 槽尺寸变化时测量；紧凑切换后也复测一次以收敛。
  // ⚠️ 只用一个 effect 驱动测量，且 measure 不依赖 compact（用 ref 读），
  // 否则「measure 依赖 compact → 紧凑切换 → measure 变 → effect 重跑 → 再 setCompact」
  // 会形成无限更新循环（React: Maximum update depth exceeded）。
  useEffect(() => {
    const slot = slotRef.current
    if (!slot) return
    measure()
    const ro = new ResizeObserver(() => measure())
    ro.observe(slot)
    if (document.fonts?.ready) void document.fonts.ready.then(() => measure())
    return () => ro.disconnect()
  }, [measure])

  // 紧凑切换后内容宽变化 → 复测一次拿到正确 s（独立 effect，不与上面互相触发）
  useLayoutEffect(() => {
    const raf = window.requestAnimationFrame(() => measure())
    return () => window.cancelAnimationFrame(raf)
  }, [compact, measure])

  // 把 s / compact 落到 DOM（供 CSS calc 使用）
  useLayoutEffect(() => {
    const bar = barRef.current
    if (!bar) return
    bar.style.setProperty('--fb-scale', String(scale))
    bar.dataset.fbScale = String(scale)
    if (compact) bar.setAttribute('data-compact', 'true')
    else bar.removeAttribute('data-compact')
  }, [scale, compact])

  return { slotRef, barRef, scale, compact }
}
