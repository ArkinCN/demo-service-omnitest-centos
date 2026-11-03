import { useT } from '../i18n'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { FlowId } from '../data/types'
import { useAppStore } from '../state/useAppStore'
import { cn } from '../components/ui'
import { AssistantPanel } from './AssistantPanel'
import { LeftPanel } from './LeftPanel'
import { ResourcePanel } from './ResourcePanel'

/** 一屏三块：左栏参数 380 · 右上面板（hero）· 右下助手。块间距 24。
 *
 *  右列两行的比例（助手高 / 面板高）现由一条可拖拽分隔条控制，助手还可整块收起。
 *  起因：助手消息一多就被压到只剩输入框，看不到上下文。原来写死在 index.css 的
 *  .right-rows（1.75fr / 1fr）只按视口高度分档，改不了人手想要的即时比例。
 *
 *  三条纪律：
 *  一、默认值与原来一致（1.75 : 1），不拖的话观感不变；
 *  二、比例存 localStorage，跨刷新保留，但每个流程各自记一份；
 *  三、收起是「零高 + 一条窄条」，不是卸载——收起时不打断正在跑的会话。
 */

/**
 * 助手行占右列总高的比例。**唯一的事实来源是两侧的像素下限，比例只是它的换算结果。**
 *
 * ⚠️ 2026-10-10 修「往下拉反而弹起来、往上拉最多到一半」：
 * 老实现按指针**绝对纵坐标**反算比例，且只按 0.15 / 0.97 两个百分比夹取，
 * 可真正渲染的行高另有像素下限（面板 300px、助手 216px）。两套约束不一致时
 * 指针位置与渲染高度就脱节：
 *  · 向上拖被面板 300px 卡死（实测右列 565px 时助手最多 245px ≈ 43%，即「最多一半」）；
 *  · 向下拖被助手下限卡死（默认比例在该列高下算得 198px 已低于下限，渲染被抬到
 *    216px，而存值仍是 0.3636，一按条就跳变，即「往下拉反而弹起来」）。
 *
 * 现在的三条纪律（与 features/automation/AutomationConsole 同一套写法）：
 *  一、量出右列栅格**实测高度**，把两侧像素下限换算成比例区间后再夹取；
 *  二、渲染一律用夹取后的生效值 ⇒ 存值永远等于实际渲染高度，指针与条不会分家；
 *  三、窗口变化只夹**渲染值**、不改写用户存下的比例（需求④：不许被逻辑强制复位）。
 *
 * 下面这两个常量只在「容器高度还未知」（首帧 / 已卸载）时兜底，语义是绝对区间；
 * 拖动时真正生效的上下限见 assistantRatioBounds()。
 */
const MIN_ASSISTANT_RATIO = 0.15
const MAX_ASSISTANT_RATIO = 0.97
/** 与 .right-rows 默认行比一致（1fr / (1.75fr + 1fr)），仅供无历史记录时的默认口径使用 */
const DEFAULT_ASSISTANT_RATIO = 1 / 2.75

/**
 * 拖动条那一行的高度（px）。
 *
 * 条本身充当两行之间的间隔：原来条只有 6px，而两行之间还有一条 gap（clamp 14~24px），
 * 等于在条上下各留一道空档，视觉上是一大块空白。现在条本身就有 gap 那么高，
 * 并把 gap 全收进条里（下方 gap=0），空档不再出现。
 */
const HANDLE_H = 20

/**
 * 助手行的像素下限（2026-10-13 由 160 上调到 180，用户反馈"嵌字"）。
 *
 * 历史：216px 原是为「卡片头 44 + 动作条约 34 + 输入框约 58 + 底部模型行约 40 +
 * 内边距」定的死数（2026-09-23 出现过：被压到只剩一个「发送」按钮）。
 * 2026-10-10 下调到 160，允许用户主动拖到很矮方便看图表，代价是
 * **底部「模型 / 权限」那一行在缩到底时被裁掉**（原注释即写明此取舍）。
 *
 * ⚠️ 2026-10-13 用户反馈：拖矮后底部那一行被"从中间横切"成半截字，观感像 bug
 * （尤其英文模式下标签更长，切得更明显）。要求「底部行保底不被裁」。
 *
 * 实测（Playwright，1440×900，中英文一致）：.ac-root 内部各项高度合计
 *   header 44 + stream 28 + slot 32 + composer 102（= box 45 + controls 26） = 206px
 * 注意 .ac-stream 虽然 flex:1 1 auto + min-height:0，但它自带 padding 14px 上下，
 * **实际最小占位 28px**（漏算它就会算成 178px、仍然差 26px 被裁）。
 * 低于 206px 时超出部分被 .ac-root 的 overflow:hidden 从底部裁掉，
 * 被裁的正是 .ac-controls（模型 / 权限）那一行 → 即用户看到的"嵌字"。
 *
 * 故下限取 208px（206 + 2px 余量）。仍保留「拖到很矮」的自由度（比原先只高 48px），
 * 但保证任何可拖到的高度下底部行都完整可见。默认状态口径仍由
 * defaultAssistantRatio() 复现，不拖时观感不变。
 */
const ASSISTANT_MIN_H = 208

/**
 * 默认（无拖拽记录）时助手行「想要」的高度：让卡片头 + 动作条 + 输入框 +
 * 底部「模型 / 权限」行全部完整可见。用来让「不拖的时候」与改版前一致。
 */
const ASSISTANT_COMFORT_H = 216

/**
 * 上方面板行的像素下限 = 「面板」标题条的高度（44px，等于 components/ui/Card.tsx 里
 * PanelHeader 的 `h-[44px]`）。
 *
 * ⚠️ 2026-10-10 由 300 改成 44（需求②③：解除高度上限 + 拉满时保留「面板」标题）。
 * 原 300px 是「保住图表可读」的保底（2026-10-09 加，起因：面板被压到 209px 时
 * 绘图区只剩 21px，曲线与三根纵轴全看不见）。但它是拿「不让人拖到顶」换来的，
 * 与用户「图表可以被盖住，但让我知道上面还有面板」的需求直接冲突，故改为只保标题条：
 *  · 常规/默认状态不受影响——默认高度由助手行的 216px 舒适口径与默认比例决定，
 *    面板仍拿大头（1600×1000 实测默认面板 507px），图表该多高还是多高；
 *  · 用户主动拖到顶时面板只剩 44px，其下图表内容由 Panel 的 overflow-hidden
 *    裁切（不重叠、不留空白），标题条照常完整可见。
 *
 * 为什么取 44：正好等于 PanelHeader 的高度，落在用户要求的 40-50px 区间内；
 * `.surface-1` 无边框（只有底色/圆角/阴影），44px 的行高能完整容纳标题条本身。
 */
const PANEL_MIN_H = 44

const ratioKey = (flow: FlowId) => `flow-assistant-ratio:${flow}`
const collapsedKey = (flow: FlowId) => `flow-assistant-collapsed:${flow}`

/**
 * 面板行的**有效**像素下限。
 *
 * 常规就是 PANEL_MIN_H（44px）；窗口矮到「面板 44 + 拖动条 20 + 助手 160」= 224px
 * 都放不下时，先把助手行的下限让出来（它的下限是用户确认过、用来保住输入框的），
 * 面板让到剩多少算多少——否则两行合起来超出容器，助手底部（输入框那一行）会被裁掉
 * （2026-09-23 出现过：只剩一个「发送」按钮）。
 * 面板下限改成 44 之后，这条兜底基本只在窗口高度低于约 380px 时才会触发。
 */
function panelMinPx(containerH: number): number {
  if (!(containerH > 0)) return PANEL_MIN_H
  const usable = containerH - HANDLE_H
  if (!(usable > 0)) return 0
  return Math.max(0, Math.min(PANEL_MIN_H, usable - Math.min(ASSISTANT_MIN_H, usable)))
}

/**
 * 助手占比的合法区间，由两侧像素下限换算而来。
 * 容器高未知（<=0）时退回静态兜底区间；lo 恒不大于 hi，保证永远不溢出容器。
 */
function assistantRatioBounds(containerH: number): { lo: number; hi: number } {
  if (!(containerH > 0)) return { lo: MIN_ASSISTANT_RATIO, hi: MAX_ASSISTANT_RATIO }
  const usable = containerH - HANDLE_H
  if (usable <= 0) return { lo: MIN_ASSISTANT_RATIO, hi: MAX_ASSISTANT_RATIO }
  const hi = Math.min(
    MAX_ASSISTANT_RATIO,
    Math.max(MIN_ASSISTANT_RATIO, 1 - panelMinPx(containerH) / usable),
  )
  // 矮视口下两侧下限之和可能超过容器高：此时锁成同一个点（占满可用空间，而不是溢出屏幕）
  const lo = Math.min(ASSISTANT_MIN_H / usable, hi)
  return { lo, hi }
}

/** 把助手占比夹进合法区间。渲染、落盘、aria 全走它 ⇒ 存值 = 实际渲染高度。 */
function clampAssistantRatio(r: number, containerH: number): number {
  const { lo, hi } = assistantRatioBounds(containerH)
  if (!Number.isFinite(r)) return lo
  return Math.min(hi, Math.max(lo, r))
}

/**
 * 无拖拽记录 / 双击复位时的默认占比：按「舒适高度 216px」取，再夹进合法区间。
 * 容器够高时等于旧默认 1/2.75；容器偏矮时等于 216px（复现旧实现靠 min() 的效果）。
 */
function defaultAssistantRatio(containerH: number): number {
  if (!(containerH > 0)) return DEFAULT_ASSISTANT_RATIO
  const usable = containerH - HANDLE_H
  if (usable <= 0) return DEFAULT_ASSISTANT_RATIO
  return clampAssistantRatio(
    Math.max(DEFAULT_ASSISTANT_RATIO, ASSISTANT_COMFORT_H / usable),
    containerH,
  )
}

/**
 * 读回该流程存下的比例。返回 null 表示**用户还没拖过**——此时走
 * defaultAssistantRatio(实测高)，即「默认观感」，而不是把某个写死的常量当成用户意愿。
 * 存值原样返回、此处不夹取：夹取交给渲染与落盘，窗口变化才不会篡改用户的选择。
 */
function readRatio(flow: FlowId): number | null {
  if (typeof localStorage === 'undefined') return null
  const raw = Number(localStorage.getItem(ratioKey(flow)))
  if (!Number.isFinite(raw) || raw <= 0) return null
  return raw
}

/** 还原拖动期间锁住的光标与选区（拖动结束与组件卸载都要调，否则会残留在 body 上） */
function releaseBody() {
  document.body.style.removeProperty('cursor')
  document.body.style.removeProperty('user-select')
}

export function FlowScreen({ flow }: { flow: FlowId }) {
  const uiT = useT()

  const scene = useAppStore((s) => s.scene)
  // 自动化运行期间：左栏收起、右上大屏与右下 AI 拉伸铺满（有过渡，见 index.css）。
  const autoRunning = useAppStore((s) => s.automationRunStatus === 'running')
  // 比例与收起态都按流程分别记住：流程 3 想把助手拉大，不该顺带改到流程 5。
  // ratio = null 表示该流程用户还没拖过，走「默认观感」口径（defaultAssistantRatio）。
  const [ratio, setRatio] = useState<number | null>(() => readRatio(flow))
  const [collapsed, setCollapsed] = useState(
    () => typeof localStorage !== 'undefined' && localStorage.getItem(collapsedKey(flow)) === '1',
  )
  const rowsRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  /** 按下拖动条那一刻的锚点：指针纵坐标 + 助手行当时的**实际像素高**（相对位移法） */
  const dragStart = useRef({ y: 0, h: 0 })

  /**
   * 右列栅格实测高度（px）。
   *
   * 拖动与夹取都必须用它，不能用视口高或估算值：右列高 = 视口 − 顶栏 − 页面留白，
   * 还随窗口尺寸与自动化运行态（左栏收起）变化。首帧量不到时为 0，夹取退回静态兜底区间；
   * 量到后同帧内即换成真实区间（ResizeObserver 回调在绘制前派发，不会闪一帧）。
   */
  const [rowsH, setRowsH] = useState(0)

  // 切流程：把该流程自己那份比例与收起态读回来
  useEffect(() => {
    setRatio(readRatio(flow))
    setCollapsed(
      typeof localStorage !== 'undefined' && localStorage.getItem(collapsedKey(flow)) === '1',
    )
  }, [flow])

  /* 右列高度跟随窗口/布局变化：窗口缩放、自动化运行态收左栏、底部状态条换行等 */
  useEffect(() => {
    const el = rowsRef.current
    if (!el) return
    // 取整：避开亚像素高度反复触发 setState（ResizeObserver 对 0.3px 级变化也会回调）
    const measure = () => setRowsH(Math.round(el.getBoundingClientRect().height))
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  /**
   * 落盘助手占比。**所有写入都经过这里**，且这里统一按实测高夹取，
   * 因此存下的值一定落在当前可达区间内 ⇒ 存值 = 实际渲染高度，指针与拖动条永不分家。
   * 入参可以是任何来源（拖动位移、方向键步进、双击复位），不必各自记得夹取。
   */
  const persistRatio = useCallback(
    (r: number) => {
      const h = rowsRef.current?.getBoundingClientRect().height ?? 0
      const next = clampAssistantRatio(r, h)
      setRatio(next)
      try {
        localStorage.setItem(ratioKey(flow), String(next))
      } catch {
        // 隐私模式下 localStorage 可能被禁；记不住不影响本次调整
      }
    },
    [flow],
  )

  const persistCollapsed = useCallback(
    (c: boolean) => {
      setCollapsed(c)
      try {
        localStorage.setItem(collapsedKey(flow), c ? '1' : '0')
      } catch {
        // 同上
      }
    },
    [flow],
  )

  /**
   * 拖拽：按下分隔条后监听 window 的 move/up，而不是分隔条自己的。
   * 指针很容易在拖动中滑出那条 20px 的条，绑在自己身上会中途丢事件。
   *
   * ⚠️ 2026-10-10 改为**相对位移**：按下时记下起点纵坐标与助手行当时的实际像素高，
   * 移动时用位移换算新高度。老实现按指针绝对纵坐标反算比例，一旦夹取生效，
   * 指针与渲染高度就各说各话（抓条瞬间跳变、往下拖不跟手，即「弹起来」）。
   * 相对位移则严格 1:1 跟手：拖到夹取边界就停在边界，不会弹回、也不会跳。
   */
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      if (!dragging.current) return
      const box = rowsRef.current?.getBoundingClientRect()
      if (!box || box.height <= 0) return
      const usable = box.height - HANDLE_H
      if (usable <= 0) return
      // 助手在下面：指针往上（clientY 变小）→ 位移为正 → 助手变高；往下则相反
      const nextH = dragStart.current.h - (e.clientY - dragStart.current.y)
      persistRatio(nextH / usable)
    }
    const onUp = () => {
      if (!dragging.current) return
      dragging.current = false
      releaseBody()
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      // 拖动中途切流程/整块卸载也要还原：否则 row-resize 光标与禁选会残留在 body 上
      releaseBody()
    }
  }, [persistRatio])

  const startDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    const box = rowsRef.current?.getBoundingClientRect()
    if (!box) return
    const handle = e.currentTarget.getBoundingClientRect()
    dragging.current = true
    // 起点用**量到的实际高度**（条底边到容器底边 = 助手行高），而不是比例反推：
    // 栅格夹取后的高度才是用户看到的高度，按它起算，抓住条的那一刻才不会跳一下。
    dragStart.current = { y: e.clientY, h: Math.max(0, box.bottom - handle.bottom) }
    // 拖动全程锁住光标与选区，否则手一快就选中了半屏文字
    document.body.style.cursor = 'row-resize'
    document.body.style.userSelect = 'none'
  }

  /**
   * 生效比例 = 用户存下的比例（没拖过则用默认口径）夹进「当前容器实测高」对应的合法区间。
   * 渲染**只用它**：这样「存下的高度」与「看到的高度」永远一致，指针与拖动条不会分家。
   * 注意只夹渲染值、不回写存储值——窗口变矮时临时压缩，变回来自动恢复用户的选择
   * （需求④：不被任何逻辑强制复位）。
   */
  const bounds = assistantRatioBounds(rowsH)
  const eff = clampAssistantRatio(ratio ?? defaultAssistantRatio(rowsH), rowsH)

  /**
   * 用实测高换算 grid 行高（三行：上方面板 / 拖动条 / 助手）。
   *
   * ⚠️ 2026-10-10 实测踩到的坑：两行**都写成比例**会留下一条空白。
   * `minmax(300px, a fr) 20px minmax(160px, b fr)`（a+b=1）一旦面板被它 300px 的
   * 下限顶住——而这恰好就是「拉到顶」那一瞬间——剩下那行的 fr 之和就 < 1，
   * 按 CSS 规范「flex sum 小于 1 时按 1 计」，浏览器**不会**把剩余空间分完：
   * 818px 容器实测排成 300 / 20 / 310.45，助手本该 498px 只有 310px，
   * 底部空出 187px（截图肉眼可见一整条空白）。
   *
   * 故：助手行直接给**像素**（就是用户拖到的那个高度），面板行 `1fr` 吃掉剩下的全部。
   * 助手高度不再依赖 fr 的分配细节，面板被下限顶住时也不会留空白。
   *
   * 收起时只剩两行：上方面板占满 + 一条「展开助手」窄条自己撑高度。
   * 首帧还没量到容器高（rowsH=0）时退回比例写法兜底：绝不能给出 0 高，
   * 否则助手卡片会闪一帧空壳（测量回调随后在绘制前补上真实高度）。
   */
  const usable = Math.max(0, rowsH - HANDLE_H)
  const panelFloor = panelMinPx(rowsH)
  const assistantPx = Math.max(0, Math.min(eff * usable, usable - panelFloor))
  const rows = collapsed
    ? 'minmax(0, 1fr) auto'
    : rowsH > 0
      ? `minmax(${panelFloor}px, 1fr) ${HANDLE_H}px ${assistantPx.toFixed(2)}px`
      : `minmax(${PANEL_MIN_H}px, ${(1 - eff).toFixed(4)}fr) ${HANDLE_H}px minmax(${ASSISTANT_MIN_H}px, ${eff.toFixed(4)}fr)`

  return (
    <div
      /*
       * 只需 flex-1 + min-h-0：由父级 flex 容器分配剩余高度。
       * 不要再加 h-full —— flex-1 与 height:100% 同时存在会互相打架，
       * 父级高度不确定时整块会撑出视口，把助手底部（输入框那一行）挤出屏幕
       * （2026-09-23 出现过：输入框下的「模型 / 权限」行只露一半）。
       * items-stretch 保留：左右两列等高。
       */
      className={cn(
        // 窄屏自适应（2026-10-15）：加 flow-split-grid 作为列定义的**唯一消费点**
        // （见 index.css）；autoRunning 时额外挂 flow-split-auto，供断点用
        // :not(.flow-split-auto) 排除——自动化接管时左栏不渲染，栅格只剩一个子元素，
        // 若还套用堆叠档的两行模板，右列会被压进上面那一行。
        'flow-split-grid grid min-h-0 w-full flex-1 items-stretch overflow-hidden',
        autoRunning && 'automation-grid flow-split-auto',
      )}
      style={{
        // 窄屏自适应（2026-10-15）：原来这里直接写 gridTemplateColumns / gap，
        // 但**内联样式优先级高于任何样式表规则**，index.css 里的窄屏断点覆盖不动
        // （除非上 !important，那又会跟 Tailwind 的 utilities 打架）。
        // 现改为「内联只给宽屏口径的变量，样式表负责消费」：
        //   .flow-split-grid { grid-template-columns: var(--flow-cols, var(--flow-cols-wide, …)) }
        // 各断点只覆盖 --flow-cols；宽屏口径与 autoRunning 让位分支仍由 JS 决定，逻辑零改动。
        // ⚠️ 变量名必须是 --flow-cols-**wide**：若内联直接写 --flow-cols，
        //    内联自定义属性的高优先级会让下方所有断点全部失效（别改回短名）。
        '--flow-cols-wide': autoRunning ? '0px minmax(0, 1fr)' : 'minmax(300px, 380px) minmax(0, 1fr)',
        '--flow-gap-wide': autoRunning ? '0px' : 'clamp(14px, 1.25vw, 24px)',
      } as React.CSSProperties}
    >
      {autoRunning ? null : <LeftPanel flow={flow} scene={scene} />}
      <div
        ref={rowsRef}
        className="right-rows grid min-h-0 min-w-0 overflow-hidden"
        // 右列不设 gap：竖排间距完全由分隔条那一行承担。
        // 若这里也留 gap，条上下会各多一道空档（4-N 修过一次）。
        style={{ gridTemplateRows: rows, gap: '0' }}
      >
        <ResourcePanel flow={flow} scene={scene} />

        {collapsed ? (
          <button
            type="button"
            onClick={() => persistCollapsed(false)}
            aria-expanded={false}
            title={uiT("展开助手")}
            className="mt-2 flex h-9 w-full items-center justify-center gap-2 rounded-tp border border-line-soft bg-surface text-[12px] text-t2 transition-colors hover:border-ink hover:text-ink"
          >
            <span aria-hidden>▲</span>
            {uiT("展开助手")}</button>
        ) : (
          <>
            {/*
              可拖拽分隔条：一个有高度的实心条，鼠标进入才显形（平时只一条细线，
              不与内容抢注意力）。role="separator" + aria-* 让读屏软件知道这是
              可调整的分隔，方向键也能调——键盘可达，不只有鼠标能改。

              aria-valuenow / min / max 报的是「当前实测高对应的可达区间」
              （见 assistantRatioBounds），读屏读到的就是键盘能真正调到的范围，
              不会出现「报了 0.97 但按上去没反应」这种假上限。

              条本身充当了两行之间的间隔，"视觉上像一条可抓的缝"，而不是
              "两块内容之间空了一大截"。
            */}
            <div
              role="separator"
              aria-orientation="horizontal"
              aria-label={uiT("调整助手高度")}
              aria-valuenow={Math.round(eff * 100)}
              aria-valuemin={Math.round(bounds.lo * 100)}
              aria-valuemax={Math.round(bounds.hi * 100)}
              tabIndex={0}
              onPointerDown={startDrag}
              onDoubleClick={() => persistRatio(defaultAssistantRatio(rowsH))}
              onKeyDown={(e) => {
                const step = e.shiftKey ? 0.05 : 0.02
                // 从**生效值**起算：ratio 可能为 null（该流程还没拖过）或已被夹取，
                // 步进必须踩在用户当前看得见的高度上，才不会有"按了没反应"的一步。
                if (e.key === 'ArrowUp') {
                  e.preventDefault()
                  persistRatio(eff + step)
                } else if (e.key === 'ArrowDown') {
                  e.preventDefault()
                  persistRatio(eff - step)
                }
              }}
              className="group flex cursor-row-resize items-center justify-center focus-visible:outline-none"
              title={uiT("拖动调整助手高度（双击复位）")}
            >
              {/*
                ⚠️ 2026-10-09 用户反馈「没注意到这里有拖动条」——原设计**平时几乎不可见**
                （一条 bg-line 细线，悬停才显形）。现改为**常显抓握手柄**：
                 · 坐着也不藏：外层圆角 capsule 底 + 中间一条较深的横条 + 两侧渐隐短线，
                   静止即读作「一根可抓的把手」；悬停/聚焦进一步加深加粗。
                 · 拖动逻辑（指针拖拽 / 双击复位 / 键盘方向键 / aria-*）**完全不变**。
              */}
              <span className="flex items-center gap-1 rounded-full bg-p50/70 px-2.5 py-[3px] transition-colors group-hover:bg-p50 group-focus-visible:bg-p50">
                <span className="h-[2px] w-5 rounded-full bg-t3/60 transition-colors group-hover:bg-ink group-focus-visible:bg-ink" />
                <span className="h-[4px] w-14 rounded-full bg-t2/70 transition-all group-hover:h-[5px] group-hover:bg-ink group-focus-visible:h-[5px] group-focus-visible:bg-ink" />
                <span className="h-[2px] w-5 rounded-full bg-t3/60 transition-colors group-hover:bg-ink group-focus-visible:bg-ink" />
              </span>
            </div>

            {/*
              收起按钮交给 AssistantPanel 自己渲染在头部右侧（由它决定落点），
              不再绝对定位浮在右上角——那样会压住头部的「沉淀为经验 / 依据」按钮。
            */}
            <AssistantPanel
              flow={flow}
              scene={scene}
              onCollapse={() => persistCollapsed(true)}
            />
          </>
        )}
      </div>
    </div>
  )
}
