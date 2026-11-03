import { useEffect, useState } from 'react'
import type { CSSProperties, ReactElement } from 'react'
import { ChevronRight } from 'lucide-react'
import { cn } from '../../components/ui'

/* ===========================================================================
   流程条 · 连接段共享件（2026-10-10 第二轮新增）

   背景：此前两处流程条（顶栏 FlowStepper / 运行台 AutomationStageFlow）的
   **每一段**都无条件挂「流光 + 波浪箭头」→ 用户反馈「满屏动效，看不出流程
   走到哪一步」。本件把「段相位」抽成纯函数 + 分层组件，两处复用同一口径：

   段与节点：FLOWS 顺序 init(1)/req(2)/run(3)/tune(4)/report(5)；
   段 i（1..4）连接节点 [i-1] → [i]，右侧节点即该段的「下一节点」。

   相位口径（用户 2026-10-10 确认，需求单第三部分验收标准）：
     · active    仅「当前节点 → 下一节点」一段：亮色流光 + 亮绿箭头循环平移；
     · returning active 且为调优回退段（段 3：启动测试 → 调优运行）且退回信号
                 置位 → 反向（沿用既有 flow-seg-return / flow-seg-arrow-rev）；
     · done      左节点已完成 → 纯静态线，**无箭头**（已走过区域安静）；
     · pending   运行中但尚未到达 → 纯静态暗线，**无箭头**；
     · idle      非运行态 → 纯静态线，无箭头（空闲态完全安静）。
   curIdx = 4（停在节点 5）时无段满足 active → 无动效段（横向条上无 5→1 连接段）。

   ⚠️ 2026-10-10 二次确认（用户看效果后）：未到达段那个静态暗色小箭头
   "不显示、影响观感" → 已按纯静态线处理（此前实现过锚点居中的暗箭头，
   现整体删除：DOM、CSS 规则与 testid 一并移除，段内不留任何非预期构件）。
   需求单编号 3 原口径（未到达段显示静态暗色箭头）由本次指令覆盖。

   平滑消失（验收标准核心）：动效层**常驻 DOM**，只由 `data-on`
   驱动 CSS transition（opacity + scale 约 0.3s）——节点从「当前进行中」变
   「已完成」时，旧段箭头淡出 + 缩小平滑消失，新段同时淡入；连续切换由
   transition 直接重定向，无闪烁、无残留、不依赖 JS 定时器与动画结束事件。

     ---------------------------------------------------------------------------
     2026-10-10 第三轮（需求单「启动测试 ↔ 调优运行 双向传递动效」）新增相位'loop'：

     调优是闭环（run 判未达标 → tune 自动调参 → 回 run 重跑），此前段 3 只有
     单根动效，用户要「两根线同时存在、反向流动」。现由 `loopSeg` 参数开启：
       · 上线「启动测试 → 调优运行」右向（沿用 .automation-rail-flow，1.5s）
       · 下线「调优运行 → 启动测试」左向（.flow-seg-back，0.9s，**品牌绿非红**）
       · 触发 = 运行中且当前节点 ∈ {启动测试, 调优运行}（curIdx 为 loopSeg-1 或 loopSeg）
       · 进「测试报告」（curIdx=4）自然落 done → 双线静止（需求单编号 2）

     ⚠️ **opt-in 纪律**：`loopSeg` 由顶栏 FlowStepper 与运行台 AutomationStageFlow
         **两处都传**（自动化运行时顶栏被 z-50 全屏浮层遮住，用户实际看的是运行台那条，
         只改顶栏等于用户看不到）；人测页面既不跑自动化、也不渲染运行台那条 → 零动效改动。
         「取消红色退回闪烁」对段 3 生效（loop 优先级高于 returning）。

     ---------------------------------------------------------------------------
     2026-10-12 第四轮（用户需求单「把下线平行直线改成折线」）：

     用户口径：闭环下线的「调优运行 → 启动测试」由平行直线改成折线 ——
     **从「调优运行」标签正中间向下出发、向左、再向上，进入「启动测试」标签正中间**；
     样式 / 动效 / 闭环语义全部不变，只换形态。

     实现（见下方 LoopReturnPath）：
       · 折线走 SVG（宽 200 / 高 96 的视口，left/top 与段容器中线对齐），
         上线仍为原 .automation-rail-flow 直轨，位置用一根透明占位条钉住；
       · 折线动效 = **一枚箭头**，由一次 SMIL `animateMotion rotate="auto"` 沿折线
         驱动（方向：调优运行 → 启动测试，品牌绿；**身后无拖尾光段**）；
       · 端点对齐两侧标签需知道节点内边距 → 新增 `edgePadPx` 参数
         （顶栏 NavLink px-8 传 8；运行台无内边距用默认 0）。

       2026-10-12 跟单（用户看完折线后的三点修正）：
       ① 放慢到 1/3：一程 0.9s → 2.7s（RET_DUR）；
       ② 箭头改到**前进方向的头部**：原先光段用 stroke-dashoffset 扫、箭头另起
          一个 animateMotion 走全程，两者相位无关 → 箭头落在光段尾部。现把二者
          合成一组、组内「行进方向 = +x」，箭头 tip 压原点，箭头恒定在前引导；
       ②' 用户看效果追加：「只保留箭头部分，后面那根直线不要了」→ 组内那根拖尾
          直线（RET_TRAIL_LEN / testid flow-seg-dual-down-sweep）已删除，
          折线上只剩一枚箭头，轨道本体仍由①静态折线承担；
       ③ 端点与文字留空隙：**横向跨度不变**（仍是两标签横向中心之间），
          由纵向承担 —— 端点 = 文字中心 + 半字高(10) + RET_ENDPOINT_GAP(14) = 54px，
          两条竖线整体落到文字**下沿之外约三分之二个字**，既不贴字也不显疏离
          （20→14 见下方常量注释）。
          ⚠️ 本轮先误做成「把端点横移到文字外侧」，等于缩短了跨度，用户当场驳回：
             「不要改从运行调优的『行』和『调』之间出发…进入启动测试的『动』和
              『测』之间的这个长度，你改短了」。跨度是本条的硬约束。
       =========================================================================== */

   /** 闭环段段号（常量，避免硬编码魔数）：段 3 = 启动测试 → 调优运行 */
   export const RUN_TUNE_LOOP_SEG = 3

   export type SegPhase = 'active' | 'returning' | 'loop' | 'done' | 'pending' | 'idle'

   export interface SegPhaseArgs {
     /** 段序号 1..4；段 i 连接节点 [i-1] 到节点 [i] */
     segIndex: number
     /** 段起点（左节点）是否已完成（编排器 status === 'success'） */
     leftDone: boolean
     /** 当前节点 0-based 下标（FLOWS 顺序）；-1 = 无当前节点 */
     curIdx: number
     /** 自动化是否运行中（非运行态一律静默） */
     running: boolean
     /** 退回信号（useStageReturnCue）是否置位 */
     returning: boolean
     /** 本段是否为调优回退段（段 3：启动测试 → 调优运行） */
     isReturnSeg: boolean
     /**
      * 闭环段段号（仅顶栏传 RUN_TUNE_LOOP_SEG，运行台不传）。
      * 命中且运行中、当前节点 ∈ {loopSeg-1, loopSeg} → 'loop'（双轨反向动效）。
      * 优先级高于 active/returning：loop 段不再播单根流光 / 红色退回闪烁。
      */
     loopSeg?: number | null
   }

   /** 段相位推导（纯函数，两处流程条同口径）。 */
   export function segPhaseOf({
     segIndex,
     leftDone,
     curIdx,
     running,
     returning,
     isReturnSeg,
     loopSeg = null,
   }: SegPhaseArgs): SegPhase {
     // ⓪ 闭环段（需求单编号 1）：「启动测试 ↔ 调优运行」两根线同时反向流动。
     //    当前节点停在这两档之任意一档都保持显示；进「测试报告」不命中 → 落 done。
     if (
       running &&
       loopSeg !== null &&
       segIndex === loopSeg &&
       (curIdx === loopSeg - 1 || curIdx === loopSeg)
     ) {
       return 'loop'
     }
     // ① 仅「当前 → 下一」段有动效
     if (running && curIdx >= 0 && segIndex === curIdx + 1) {
       return returning && isReturnSeg ? 'returning' : 'active'
     }
     // ② 已走过（左节点完成）→ 静态线，无箭头
     if (leftDone) return 'done'
     // ③ 运行中但未到达 → 静态线 + 静态暗色箭头
     if (running) return 'pending'
     // ④ 非运行态 → 静态线，无箭头（空闲态完全安静）
     return 'idle'
   }

   /** 基底线色：已走过一段（含当前段所在区间）用品牌浅绿，其余用中性线色。
    *  ⚠️ loop 用 bg-transparent：基线**仍要渲染**（它撑着段的宽 48×s / 高 3×s，
    *  loop 相位的双轨与双箭头全是 absolute，去掉基线会让段容器塌成 0×0 → 整条
    *  流程条横向错位、pill 定位失效）。只把颜色设为透明，做到「占位但不画线」。 */
   const LINE_CLASS: Record<SegPhase, string> = {
     active: 'bg-p200',
     returning: 'bg-p200',
     loop: 'bg-transparent',
     done: 'bg-p200',
     pending: 'bg-line',
     idle: 'bg-line',
   }

/** 段几何：与改造前完全一致，避免影响 useFlowBarScale 测量与顶栏pill 定位 */
const RAIL_CLASS = 'block h-[calc(var(--fb-scale)*3px)] w-[calc(var(--fb-scale)*48px)] rounded-full'
const ARROW_STYLE: CSSProperties = {
  width: 'calc(var(--fb-scale) * 21px)',
  height: 'calc(var(--fb-scale) * 21px)',
}

/* 闭环双轨几何（2026-10-10 第三轮定稿，按用户「太紧凑显小气」反馈放大一档）：
   两根 **3px** 轨（×--fb-scale）+ **14px** 间隙 = 20px 总高（×--fb-scale），
   以段中线为轴上下对称 → 上轨中心 ∓8.5px×scale（半轨1.5 + 间隙14 + 半轨1.5 = 17，两侧各半）。
   ⚠️ 轨高回到 3px（与基线同粗，「两根线」要等粗才有分量），间隙给到 14px：
   2px+8px 在实机上仍偏挤（用户反馈显小气），20px 总高远小于节点高 78px×scale。
   ⚠️ 全部 absolute：不撑开段容器高度 → 段宽/高与改造前完全一致，
   useFlowBarScale 的槽宽测量与顶栏 pill 定位均不受影响。
   ⚠️ loop 相位的基线仍渲染但为**透明**（见 LINE_CLASS.loop）：它要留着撑开段的
   48×3 盒子（去掉会让段容器塌成 0×0、整条流程条横向错位），又不能画线，
   否则基线横在两轨中间会把"两根线"重新连成一条。 */
const DUAL_RAIL_CLASS = 'block h-[calc(var(--fb-scale)*3px)] w-[calc(var(--fb-scale)*48px)] rounded-full'
const DUAL_GAP = 'calc(var(--fb-scale) * 14px)'
/** 闭环双箭头：26px（×--fb-scale），比常规箭头 21px 更大，双轨才撑得起分量 */
const DUAL_ARROW_STYLE: CSSProperties = {
  width: 'calc(var(--fb-scale) * 26px)',
  height: 'calc(var(--fb-scale) * 26px)',
}
/** 箭头容器**中心**的垂直定位：直接对齐各自轨的中心（中线 ∓ 8.5px×scale）。
 *  ⚠️ 容器上带 -translate-y-1/2 已把「容器高的一半」让出去，所以这里**只能**
 *  给轨中心偏移（8.5px），不要再叠加箭头半高（13px）—— 叠加过一次，实测箭头
 *  会整体上飘约 1 个轨间距（截图取证发现）。 */
const ARROW_UP_TOP = 'calc(50% - var(--fb-scale) * 8.5px)'
/* ⚠️ 2026-10-12：原 ARROW_DOWN_TOP（下线箭头定位，中线 +8.5px）随闭环下线改折线
   一并删除 —— 折线箭头由 LoopReturnPath 的 animateMotion 沿路径行走，不再单独定位。 */

/* ---------------------------------------------------------------------------
   闭环下线（调优运行 → 启动测试）· 折线几何（2026-10-12 用户需求）

   用户口径：把「第四节点（调优运行）回到第三节点（启动测试）」的那根平行直线
   改成折线 —— 从「调优运行」标签的正中间向下出发、向左、再向上，进入「启动测试」
   标签的正中间；**样式 / 动效 / 闭环语义都不改**，只把直线改成折线。

   坐标口径（单位＝ scale-1 的 px，1 单位 = calc(var(--fb-scale) * 1px)）：
     · 段容器左边缘 = x0；右节点（调优运行）在段右侧，左节点（启动测试）在段左侧；
     · 节点宽度 = 圆标 39 + 圆标/文字间距 5 + 标签 80（CJK 4 字 × 20px）= 124；
     · 两节点与段之间还各有一段节点内边距 edgePadPx（顶栏 NavLink 的 px-8 = 8，
       运行台无内边距 = 0），故：
         startX（调优运行标签横向中心） = 段宽 48 + edgePad + (39 + 5 + 40) = 132 + edgePad
         endX  （启动测试标签横向中心） = -(edgePad + 40)
     · 折线纵向：端点从**文字下沿之外约三分之二字符**处起（CY + 半字高 + RET_ENDPOINT_GAP），
       再向下潜 DEPTH，横移到另一侧后抬回。

  ⚠️ 横向跨度**锁定为「两标签横向中心之间」**，不可再动（用户 2026-10-12 明确：
   「不要改从运行调优的『行』和『调』之间出发…进入启动测试的『动』和『测』之间
   的这个长度，你改短了」）。因此「端点与文字留空隙、不局促」这一条
   只能由**竖直方向**实现：端点 = 文字中心 + RET_LABEL_HALF(10) + RET_ENDPOINT_GAP(14)，
   两条竖线整体落在文字**下沿之外约三分之二个字**处，端头与文字之间留出空当。
  ⚠️ 为什么用 SVG 而不是三段 absolute 细条：折线要同时承载「沿路径流动的光段」
  与「沿线行走的箭头」，只有 SVG 的 animateMotion 能一刀切好方向（光段与箭头
  同组同相位，箭头才能稳定压在行进方向的头部）；三段 div 拼折角会把箭头转角做错。
  ⚠️ 视口与段容器对齐：vb x = VB_ORIGIN_X 对应段容器 x=0，vb y = VB_CY 对应
  标签文字水平中线，故 outer 只做 translate 定位，内部坐标全部走 viewBox 等比缩放。
  --------------------------------------------------------------------------- */
const RET_EDGE_PAD_DEFAULT = 0
/** 标签横向中心距节点左边缘：圆标 39 + 圆标/文字间距 5 + 半个标签宽 40 */
const RET_NODE_LABEL_CENTER = 39 + 5 + 40
/** 标签字号的**半高**（scale-1 px）：与两处流程条的标签字号
 *  `fontSize: calc(var(--fb-scale) * 20px)` 同源（顶栏 FlowStepper / 运行台
 *  AutomationStageFlow），用于把折线端点让到文字**下沿之外**。 */
const RET_LABEL_HALF = 10
/** 端点与文字之间保留的空隙（CJK 一字 ≈ 20px，与标签字号同档）。
 *  ⚠️ 2026-10-12 用户修正：**只作用在竖直方向**——横向跨度必须保持
 *  「标签中心 ↔ 标签中心」不变（见上方「横向跨度锁定」），
 *  纵向则让到「文字下沿 + 这个空隙」，由这一条完成「不局促」。
 *  ⚠️ 2026-10-12 二次跟单：「靠近文字一点，现在有点远，但不要贴近」
 *  → 20（整字）收到 **14**（约三分之二字宽，端点落在文字下沿之外 14px）。
 *  想再调只动这一个数：值越小越贴字，越大越疏离。 */
const RET_ENDPOINT_GAP = 14
const RET_SEG_W = 48
const RET_DEPTH = 26
const RET_CORNER_R = 10
/** 一程时长：用户 2026-10-12「速度降为现在的三分之一」→ 原 0.9s × 3 */
const RET_DUR = '2.7s'
const RET_VB_W = 200
/** 视口高：只要装得下路径最低点（yBottom = CY + 半字高 + RET_ENDPOINT_GAP + DEPTH，
 *  当前 = 80）即可 —— 盒子是透明的，多余的空白只会平白撑出父级滚动区，
 *  故收到刚好够用；留几像素余量，RET_ENDPOINT_GAP 往上回调时 yBottom 仍在视口内。 */
const RET_VB_H = 96
const RET_VB_CY = 30
/** 视口原点相对段容器左边缘的偏移（vb x = 52 ↔ 段容器 x = 0） */
const RET_VB_ORIGIN_X = 52

/** 系统「减少动态效果」偏好（订阅一次，供折线箭头/流光降级使用）。 */
function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false)
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const sync = () => setReduced(mq.matches)
    sync()
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [])
  return reduced
}

/**
 * 闭环下线折线：调优运行标签横向中心 ↓ 向左 ↑ 启动测试标签横向中心。
 *
 * 动效与既有下线同源（品牌绿反向传递），三处按用户 2026-10-12 口径调整：
 *   ① 放慢到 1/3：一程 RET_DUR = 2.7s（原 0.9s）；
 *   ② **箭头在前进方向的头部**：只由**一次** `animateMotion rotate="auto"` 驱动
 *      —— 以「行进方向 = +x」为基准，箭头 tip 压在原点，恒定在前引导；
 *      **无拖尾光段**（用户 2026-10-12 看图后要求「只保留箭头」）；
 *   ③ 端点与文字留空隙：横向跨度**不动**，由纵向让开
 *      （端点 = 文字中心 + 半字高 + RET_ENDPOINT_GAP，竖线落到文字下沿之外）。
 *   降级偏好下动效全部不渲染，只留静态折线 + 一枚停在横段中点、朝行进方向的箭头。
 */
function LoopReturnPath({ edgePadPx = RET_EDGE_PAD_DEFAULT }: { edgePadPx?: number }) {
  const reduced = usePrefersReducedMotion()
  // ⚠️ 路径坐标是**视口坐标**：段空间 x 需 + RET_VB_ORIGIN_X 才是 vb x
  // （outer 的 left = -RET_VB_ORIGIN_X，使 vb x=ORIGIN 落在段容器左边缘）。
  const vbX = (x: number) => x + RET_VB_ORIGIN_X
  // 横向跨度锁定「两标签横向中心之间」（用户口径，不得缩短）
  const startX = vbX(RET_SEG_W + edgePadPx + RET_NODE_LABEL_CENTER)
  const endX = vbX(-(edgePadPx + 40))
  // 端点落到文字**下沿之外**（文字中心 + 半字高 + RET_ENDPOINT_GAP）：
  // 竖线不穿过标签文字，端头与文字之间留出空当（「不局促」由竖向承担）
  const yTop = RET_VB_CY + RET_LABEL_HALF + RET_ENDPOINT_GAP
  const yBottom = yTop + RET_DEPTH
  // 折角用二次贝塞尔倒角：直角在 animateMotion 的 rotate="auto" 下会让箭头
  // 在拐点瞬间跳转 90°，倒角后切线连续，观感与rail 的圆角语言一致。
  const d = [
    `M ${startX} ${yTop}`,
    `L ${startX} ${yBottom - RET_CORNER_R}`,
    `Q ${startX} ${yBottom} ${startX - RET_CORNER_R} ${yBottom}`,
    `L ${endX + RET_CORNER_R} ${yBottom}`,
    `Q ${endX} ${yBottom} ${endX} ${yBottom - RET_CORNER_R}`,
    `L ${endX} ${yTop}`,
  ].join(' ')

  return (
    <svg
      aria-hidden
      data-testid="flow-seg-dual-down"
      className="pointer-events-none absolute overflow-visible"
      viewBox={`0 0 ${RET_VB_W} ${RET_VB_H}`}
      style={{
        width: `calc(var(--fb-scale) * ${RET_VB_W}px)`,
        height: `calc(var(--fb-scale) * ${RET_VB_H}px)`,
        left: `calc(var(--fb-scale) * ${-RET_VB_ORIGIN_X}px)`,
        top: '50%',
        transform: `translateY(calc(var(--fb-scale) * ${-RET_VB_CY}px))`,
      }}
    >
      {/* ① 静态折线底线：与上线等粗、同色（品牌浅绿），只换形态不换语言 */}
      <path
        d={d}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ stroke: 'var(--tp-p-200)', strokeWidth: 3 }}
      />
      {/* ② 行进箭头：折线上**只留这一枚箭头**在跑（身后无拖尾光段）。
            组内以「行进方向 = +x」为基准：箭头 tip 压在原点 (0,0)、图形朝 +x
            → 恒定处于前进方向的**头部**。
            rotate="auto" 让整组随路径切线转向（下行 → 左行 → 上行），
            路径起点在调优运行侧、终点在启动测试侧，故方向天然是反向传递。
            ⚠️ 用 SMIL 而非 CSS：SMIL 能把图形直接贴着路径走并转到切线方向，
            CSS 的 stroke-dashoffset 只能做「光段扫过」，做不出沿线行走的箭头。
            ⚠️ 两端各留 8% 周期淡入淡出：折线起/终点是端头，硬切会突兀
            （沿用直线版「淡入淡出防硬切」的做法）。
            ⚠️ 2026-10-12 用户看效果后追加修正：**删除箭头身后的光段直线**。
            原先「光段 + 箭头」同组同相位（箭头确在头部，但身后拖着一根深绿短线），
            用户口径「只保留箭头部分，后面那根直线不要了」→ 组内 `<line>`、
            `RET_TRAIL_LEN` 与 testid flow-seg-dual-down-sweep 一并删除；
            轨道本体仍由 ① 静态折线承担，闭环语义 / 节奏不变。 */}
      {!reduced ? (
        <g
          data-testid="flow-seg-dual-down-runner"
          style={{
            stroke: 'var(--p-500)',
            strokeWidth: 3.5,
            fill: 'none',
            filter: 'drop-shadow(0 0 3px rgba(77, 143, 109, 0.85))',
          }}
        >
          {/* 箭头：tip 在原点、开口朝 -x（行进反侧），与前进方向一致 */}
          <path
            data-testid="flow-seg-dual-down-arrow"
            d="M -6 7 L 0 0 L -6 -7"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <animateMotion dur={RET_DUR} repeatCount="indefinite" rotate="auto" path={d} />
          <animate
            attributeName="opacity"
            values="0;1;1;0"
            keyTimes="0;0.08;0.92;1"
            dur={RET_DUR}
            repeatCount="indefinite"
          />
        </g>
      ) : (
        /* 降级偏好：不跑 animateMotion，静态停在折线横段中点、箭头朝左（行进方向） */
        <g
          data-testid="flow-seg-dual-down-runner"
          transform={`translate(${(startX + endX) / 2} ${yBottom}) rotate(180)`}
          style={{
            stroke: 'var(--p-500)',
            strokeWidth: 3.5,
            fill: 'none',
            filter: 'drop-shadow(0 0 3px rgba(77, 143, 109, 0.85))',
          }}
        >
          <path
            data-testid="flow-seg-dual-down-arrow"
            d="M -6 7 L 0 0 L -6 -7"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>
      )}
    </svg>
  )
}

export interface FlowSegLinkProps {
  segIndex: number
  phase: SegPhase
  /** 段容器 testid：顶栏 'flow-stepper-link' / 运行台 'auto-stage-link' */
  testId: string
  /** 动效箭头 testid：顶栏 'flow-seg-arrow' / 运行台 'auto-seg-arrow' */
  arrowTestId: string
  /**
   * 节点内边距（节点边缘到段边缘的 px，scale-1 口径）。
   * 仅闭环下线折线用它把端点对到两侧标签的正中：
   *   · 顶栏 FlowStepper 的 NavLink 带 px-8 → 传 8；
   *   · 运行台 AutomationStageFlow 的节点无内边距 → 用默认 0。
   * 不传即按 0（与运行台一致），非 loop 相位不受影响。
   */
  edgePadPx?: number
}

export function FlowSegLink({
  segIndex,
  phase,
  testId,
  arrowTestId,
  edgePadPx = RET_EDGE_PAD_DEFAULT,
}: FlowSegLinkProps): ReactElement {
  const animOn = phase === 'active' || phase === 'returning'
  const returning = phase === 'returning'
  // 闭环双轨：上线右向（启动测试→调优运行）+ 下线左向（调优运行→启动测试）
  const loop = phase === 'loop'

  return (
    <span
      aria-hidden
      data-testid={testId}
      data-seg={segIndex}
      data-phase={phase}
      className="relative z-10 flex shrink-0 items-center"
      style={
        {
          '--fb-wave-dur': '1.4s',
          '--fb-seg-travel': 'calc(var(--fb-scale) * 34px)',
          // 下线节奏0.9s/程（用户2026-10-10 定：上线 1.5s、下线 0.9s）
          '--fb-wave-dur-back': '0.9s',
        } as CSSProperties
      }
    >
      {/* ① 基底线：常显（loop 相位透明占位，见 LINE_CLASS 注释）；颜色随相位
          用 transition-colors 淡变，不突变 */}
      <span className={cn(RAIL_CLASS, 'transition-colors duration-300', LINE_CLASS[phase])} />

      {/* ② 流光带（仅 active/returning）：常驻 DOM，data-on 控制淡入淡出 + 缩放 */}
      {loop ? (
        <>
          {/* ②-1 闭环上线（启动测试 → 调优运行）：保持原「平行直线 + 右向流光」不动。
              下线（调优运行 → 启动测试）已按用户 2026-10-12 需求改为折线，
              故此处只画上线；用一根同高的透明占位条维持上线原本的垂直位置
              （双轨原本上下对称，各距中线 8.5px×scale），几何与改造前一致。 */}
          <span className="flow-seg-anim" data-on="true" data-testid="flow-seg-dual">
            <span
              className="absolute left-0 top-1/2 flex -translate-y-1/2 flex-col items-center"
              style={{ gap: DUAL_GAP }}
            >
              <span className={cn(DUAL_RAIL_CLASS, 'automation-rail-flow')} data-testid="flow-seg-dual-up" />
              <span aria-hidden className={cn(DUAL_RAIL_CLASS, 'opacity-0')} />
            </span>
          </span>

          {/* ②-2 闭环下线（调优运行 → 启动测试）：折线 —— 从「调优运行」标签正中
              向下出发、向左、再向上进入「启动测试」标签正中；样式/动效/闭环语义
              均沿用直线版（品牌绿反向传递、0.9s 一程），只换形态。
              ⚠️ 折线自带沿线行走的箭头，原等宽 ChevronLeft 已删除（避免双箭头）。 */}
          <span className="flow-seg-anim" data-on="true">
            <LoopReturnPath edgePadPx={edgePadPx} />
          </span>

          {/* ②-3 闭环上线箭头：朝右（启动测试 → 调优运行）循环平移。垂直居中由
              **容器**的 -translate-y-1/2 承担，箭头自身不带 translate
              （keyframes 的 transform 会覆盖它）。 */}
          <span className="flow-seg-anim" data-on="true">
            <span
              className="absolute left-0 -translate-y-1/2"
              style={{ top: ARROW_UP_TOP, width: DUAL_ARROW_STYLE.width }}
            >
              <ChevronRight
                size={26}
                strokeWidth={3.5}
                data-testid={`${arrowTestId}-up`}
                className="flow-seg-arrow block"
                style={DUAL_ARROW_STYLE}
              />
            </span>
          </span>
        </>
      ) : (
        <>
          <span className="flow-seg-anim" data-on={animOn ? 'true' : 'false'}>
            <span className={cn(RAIL_CLASS, returning ? 'flow-seg-return' : 'automation-rail-flow')} />
          </span>

          {/* ③ 动效箭头（仅 active/returning）：循环平移；退回时反向 */}
          <span className="flow-seg-anim" data-on={animOn ? 'true' : 'false'}>
            <ChevronRight
              size={21}
              strokeWidth={3.5}
              data-testid={arrowTestId}
              className={cn(
                'absolute top-1/2 left-0 -translate-y-1/2',
                returning ? 'flow-seg-arrow-rev' : 'flow-seg-arrow',
              )}
              style={ARROW_STYLE}
            />
          </span>
        </>
      )}

      {/* ④ 未到达段（pending）：只保留基底线，不渲染任何箭头
          （2026-10-10 用户确认「暗色小箭头不显示、影响观感」）。 */}
    </span>
  )
}
