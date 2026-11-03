import { useT } from '../i18n'
import { createElement, useState } from 'react'
import {
  Activity,
  Camera,
  Cable,
  Fan,
  Gauge,
  Monitor,
  Plug,
  Radio,
  RefreshCw,
  Ruler,
  Terminal,
  Thermometer,
  Waves,
  Wind,
  Zap,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Drawer, StatusDot, Tooltip, cn } from '../components/ui'
import type { CanvasNodeType, ToolGroup, ToolItem } from '../data/types'
import { probeDevice } from '../features/remote'
import {
  BRIDGE_LAYER_TITLE,
  callBridgeTool,
  useBridgeDevice,
  type BridgeLayer,
  type BridgeTool,
} from '../features/remote/bridge'
import { useRedlineGate } from '../features/redline'
import { REDLINE_LABEL, useAppStore, type RedlineAction } from '../state/useAppStore'
import { CANVAS_DND_MIME, CANVAS_NODE_META, type CanvasDragPayload } from '../features/canvas'
import { TOOL_GROUP_ICON } from './icons'

/* ===========================================================================
   C 区右侧竖工具条 56px。

   第三轮改三件事（依据《第三轮实施计划 · 并行派工》W3 卡第 5 条）：
     1. 十四枚图标由无分组平铺改为按能力域分组，每组带组名与分隔线；
     2. 每枚工具块可拖进画板，落点即建节点，落点之外放手取消；
     3. 连接状态由右上角小圆点改为绿 / 红 / 灰三态描边，顶部单独放一枚刷新。
   组名在 56 宽里只放得下两字，全称进 tooltip——标签 ≤6 字的口径见 DESIGN.md 第 4 节。
   =========================================================================== */

/** 组名的两字短名。全称仍在 tooltip 里。 */
const GROUP_SHORT: Record<ToolGroup['id'], string> = {
  acquire: '采集',
  stimulus: '激励',
  device: '调试',
  session: '接入',
}

/** 组默认落成哪类画板节点 */
const GROUP_NODE: Record<ToolGroup['id'], CanvasNodeType> = {
  acquire: 'scope',
  stimulus: 'psu',
  device: 'device-mcp',
  session: 'device-mcp',
}

/** 工具名命中关键词时按工具本身定节点类型，命不中落回组默认 */
const NODE_BY_WORD: [RegExp, CanvasNodeType][] = [
  [/示波|波形|采样|采集/, 'scope'],
  [/电源|供电/, 'psu'],
  [/台架|工装|涵道|风/, 'bench'],
  [/终端|命令|远程|桌面|会话|网关/, 'device-mcp'],
  [/联锁|安全/, 'interlock'],
]

function nodeTypeOf(g: ToolGroup, t: ToolItem): CanvasNodeType {
  for (const [re, type] of NODE_BY_WORD) if (re.test(t.label)) return type
  return GROUP_NODE[g.id] ?? 'device-mcp'
}

/** 工具图标：按名称关键词取，取不到就退回本组图标 */
const BY_WORD: [RegExp, LucideIcon][] = [
  [/示波|波形|采样/, Waves],
  [/电流|电压|功率|电源/, Zap],
  [/转速|测速|频率/, Gauge],
  [/温|热/, Thermometer],
  [/风|涵道|逆风/, Fan],
  [/声|噪/, Radio],
  [/位移|尺寸|量/, Ruler],
  [/相机|截图|图像/, Camera],
  [/终端|命令|脚本/, Terminal],
  [/远程|桌面|主机|工控/, Monitor],
  [/接线|通道|接入/, Plug],
  [/网关|会话|连接/, Cable],
  [/采集|记录/, Activity],
]

/** 同组里图标不重样：命中关键词优先，重了就按组内序号从备选池取 */
const POOL: LucideIcon[] = [Activity, Gauge, Zap, Ruler, Plug, Camera, Radio, Thermometer]

function iconsOf(g: ToolGroup): LucideIcon[] {
  const used = new Set<LucideIcon>()
  return g.tools.map((t, i) => {
    let ic: LucideIcon | undefined
    for (const [re, cand] of BY_WORD) {
      if (re.test(t.label) && !used.has(cand)) {
        ic = cand
        break
      }
    }
    if (!ic) ic = POOL.find((c) => !used.has(c)) ?? POOL[i % POOL.length]
    used.add(ic)
    return ic
  })
}

/** 三态描边：绿已接入、暗红异常、灰未接入 */
const STATE_RING: Record<ToolItem['state'], string> = {
  online: 'border-p300 bg-p50 text-p700',
  fault: 'border-alert/60 bg-alert-wash text-alert',
  offline: 'border-line bg-white text-t2',
}

const STATE_TEXT: Record<ToolItem['state'], string> = {
  online: '已接入',
  fault: '异常',
  offline: '未接入',
}

/* ---------------------------------------------------------------- 设备桥工具

   工具条下半截挂的是设备桥（c/components/spike-device-mcp，默认 127.0.0.1:8031）
   现在真挂着的工具，按桥返回的三层分组渲染：连接层 / 观测层 / 动作层。

   两类点击行为不一样，这个差别是红线本身：
     · 连接层与观测层不受闸口约束，点了直接调，结果摆在抽屉里；
     · 动作层六个工具对应六条红线，点下去只会拿回一张待确认凭据，
       执行必须由人在确认卡上再点一次。前端骗不过去——桥会直接拒绝执行。
   依据：[源] spike-device-mcp/README.md 第 3 节与第 5 节。 */

const LAYER_SHORT: Record<BridgeLayer, string> = {
  connection: '连接',
  observation: '观测',
  action: '动作',
}

const LAYER_ICON: Record<BridgeLayer, LucideIcon> = {
  connection: Cable,
  observation: Activity,
  action: Zap,
}

/** 桥的动作层工具名与六条红线一一对应 */
const TOOL_REDLINE: Record<string, RedlineAction> = {
  start: 'start',
  stop: 'stop',
  estop: 'estop',
  write_param: 'write_param',
  export: 'export',
  archive: 'archive',
}

function BridgeRail({
  onOpen,
}: {
  onOpen: (v: { tool: BridgeTool; layer: BridgeLayer }) => void
}) {
  const uiT = useT()

  const bridge = useBridgeDevice()
  const redline = useRedlineGate()
  const setNotice = useAppStore((s) => s.setNotice)

  if (bridge.link !== 'online')
    return (
      <div className="flex w-full flex-col items-center gap-1 border-t border-line-soft px-2 pt-3">
        <Tooltip content={bridge.reason ?? uiT('正在探设备桥')}>
          <span className="flex items-center justify-center gap-1 text-[12px] leading-none text-t3">
            <Cable size={11} strokeWidth={1.9} />
            {uiT("设备")}</span>
        </Tooltip>
        <Tooltip content={bridge.reason ?? uiT('正在探设备桥')}>
          <span
            data-testid="rail-bridge-offline"
            className="flex h-[34px] w-[34px] cursor-help items-center justify-center rounded-tps border border-line bg-white text-t3 [&>svg]:block"
          >
            <Cable size={16} strokeWidth={1.75} />
          </span>
        </Tooltip>
      </div>
    )

  const click = (layer: BridgeLayer, t: BridgeTool) => {
    const action = TOOL_REDLINE[t.name]
    if (layer === 'action' && action) {
      redline(action, {
        title: `${REDLINE_LABEL[action]}（设备桥工具 ${t.name}）`,
        prompt: t.risk ?? t.description ?? '这是一条红线动作，执行前必须由人确认。',
        argsSummary: `设备 ${bridge.device?.id ?? 'bench'} · 工具 ${t.name}`,
        danger: action === 'estop',
        onApprove: () => setNotice(`设备桥工具 ${t.name} 已经人工批准并执行`),
      })
      return
    }
    onOpen({ tool: t, layer })
    void callBridgeTool(bridge.device?.id ?? 'bench', t.name)
      .then((r) => setNotice(`${t.title ?? t.name}：${r.mode ? `mode=${r.mode}` : '已返回'}`))
      .catch((e: unknown) => setNotice(`${t.title ?? t.name} 调用失败：${e instanceof Error ? e.message : String(e)}`))
  }

  return (
    <>
      {(Object.keys(LAYER_SHORT) as BridgeLayer[]).map((layer) => {
        const tools = bridge.device?.tool_groups?.[layer] ?? []
        if (!tools.length) return null
        const LayerIcon = LAYER_ICON[layer]
        return (
          <div
            key={layer}
            className="flex w-full flex-col items-center gap-1.5 border-t border-line-soft px-2 pt-3"
          >
            <Tooltip content={uiT("设备桥 · {v1} · {v2} 个工具", { v1: BRIDGE_LAYER_TITLE[layer], v2: tools.length })}>
              <span className="mb-0.5 flex items-center justify-center gap-1 text-[12px] leading-none whitespace-nowrap text-t3">
                <LayerIcon size={11} strokeWidth={1.9} />
                {uiT(LAYER_SHORT[layer])}
              </span>
            </Tooltip>
            {tools.map((t) => (
              <Tooltip
                key={t.name}
                content={uiT("{v1} · {v2}{v3}", { v1: t.title ?? t.name, v2: t.description ?? '', v3: t.guarded ? uiT(' · 红线动作：点下去只拿凭据，执行要人再确认一次') : '' })}
              >
                <button
                  type="button"
                  aria-label={t.title ?? t.name}
                  data-bridge-tool={t.name}
                  onClick={() => click(layer, t)}
                  className={cn(
                    'flex h-[34px] w-[34px] items-center justify-center rounded-tps border',
                    'shadow-[0_1px_2px_rgba(31,42,36,.05)] transition-all duration-150 [&>svg]:block',
                    'hover:-translate-y-px hover:shadow-tp1',
                    t.guarded ? 'border-alert/50 bg-alert-wash text-alert' : 'border-p300 bg-p50 text-p700',
                  )}
                >
                  <LayerIcon size={16} strokeWidth={1.75} />
                </button>
              </Tooltip>
            ))}
          </div>
        )
      })}
    </>
  )
}

export function ToolRail({ groups }: { groups: ToolGroup[] }) {
  const uiT = useT()
  const toolLabel = (tool: ToolItem) => {
    const translated = uiT(tool.label)
    if (translated !== tool.label || !tool.label.endsWith('…')) return translated
    // The scene adapter already clipped these captions; recover their approved UI topics.
    const original = tool.hint?.split(' · ')[0] ?? tool.label
    for (const topic of ['同电压同转速常态', '程控电源读回']) {
      if (original.startsWith(topic)) return uiT(topic)
    }
    if (original.startsWith('本轮 /api/')) {
      return `${uiT('本轮')} ${/^本轮 (\/api\/[^\s]+)/.exec(original)?.[1] ?? ''}`
    }
    return uiT(original)
  }

  const [active, setActive] = useState<{ tool: ToolItem; group: string } | null>(null)
  const [bridgeTool, setBridgeTool] = useState<{ tool: BridgeTool; layer: BridgeLayer } | null>(null)
  const [busy, setBusy] = useState(false)

  /** 重新枚举设备：探一次网关，探不通就维持原状，不假报在线 */
  const refresh = () => {
    setBusy(true)
    void probeDevice('bench')
      .catch(() => null)
      .finally(() => window.setTimeout(() => setBusy(false), 500))
  }

  return (
    <>
      <aside className="fade-tb no-scrollbar flex w-[56px] shrink-0 flex-col items-center gap-3 overflow-y-auto border-l border-line-soft bg-p50/50 py-3">
        <Tooltip content={uiT("重新枚举设备")}>
          <button
            type="button"
            aria-label={uiT("刷新设备")}
            onClick={refresh}
            className={cn(
              'flex h-[28px] w-[40px] items-center justify-center rounded-tps border border-line bg-white',
              'text-t2 transition-colors duration-150 hover:border-p300 hover:bg-p50 hover:text-p700 [&>svg]:block',
            )}
          >
            <RefreshCw size={14} strokeWidth={1.8} className={busy ? 'animate-spin' : undefined} />
          </button>
        </Tooltip>

        {groups.map((g, gi) => {
          const icons = iconsOf(g)
          return (
            <div
              key={g.id}
              className={cn(
                'flex w-full flex-col items-center gap-1.5 px-2',
                gi > 0 && 'border-t border-line-soft pt-3',
              )}
            >
              <Tooltip content={uiT(g.title)}>
                <span className="mb-0.5 flex items-center justify-center gap-1 text-[12px] leading-none whitespace-nowrap text-t3">
                  {createElement(TOOL_GROUP_ICON[g.id] ?? Wind, { size: 11, strokeWidth: 1.9 })}
                  {uiT(GROUP_SHORT[g.id] ?? '')}
                </span>
              </Tooltip>
              {g.tools.map((t, ti) => {
                const Icon = icons[ti]
                const type = nodeTypeOf(g, t)
                return (
                  <Tooltip
                    key={t.id}
                    content={uiT("{v1} · {v2}{v3} · 可拖入画板建「{v4}」节点", { v1: toolLabel(t), v2: uiT(STATE_TEXT[t.state]), v3: t.hint ? ` · ${uiT('原文')}: ${t.hint}` : '', v4: uiT(CANVAS_NODE_META[type].label) })}
                  >
                    <button
                      type="button"
                      aria-label={toolLabel(t)}
                      draggable
                      onDragStart={(e) => {
                        const payload: CanvasDragPayload = { type, label: t.label }
                        e.dataTransfer.setData(CANVAS_DND_MIME, JSON.stringify(payload))
                        e.dataTransfer.effectAllowed = 'copy'
                      }}
                      onClick={() => setActive({ tool: t, group: g.title })}
                      className={cn(
                        'flex h-[34px] w-[34px] cursor-grab items-center justify-center rounded-tps border',
                        'shadow-[0_1px_2px_rgba(31,42,36,.05)] transition-all duration-150 [&>svg]:block',
                        'hover:-translate-y-px hover:shadow-tp1 active:cursor-grabbing',
                        STATE_RING[t.state],
                      )}
                    >
                      <Icon size={16} strokeWidth={1.75} />
                    </button>
                  </Tooltip>
                )
              })}
            </div>
          )
        })}

        <BridgeRail onOpen={setBridgeTool} />
      </aside>

      <Drawer
        open={!!bridgeTool}
        onClose={() => setBridgeTool(null)}
        title={bridgeTool ? (bridgeTool.tool.title ?? bridgeTool.tool.name) : ''}
        meta={bridgeTool ? uiT("设备桥 · {v1}", { v1: BRIDGE_LAYER_TITLE[bridgeTool.layer] }) : ''}
      >
        {bridgeTool ? (
          <div className="space-y-3">
            <p className="text-[13px] leading-6 text-t2">{bridgeTool.tool.description ?? uiT('桥未给描述')}</p>
            <div className="surface-2 p-3">
              <div className="tick">{uiT("工具名")}</div>
              <div className="num mt-1 text-[13px] text-t2">{bridgeTool.tool.name}</div>
            </div>
            <div className="surface-2 p-3">
              <div className="tick">{uiT("红线")}</div>
              <div className="mt-1 text-[13px] leading-6 text-t2">
                {bridgeTool.tool.guarded
                  ? uiT("受人工闸口约束：{v1}", { v1: bridgeTool.tool.risk ?? '执行前必须由人在确认卡上批准一张凭据' })
                  : uiT('不受闸口约束，只读，模型与人都可以直接调')}
              </div>
            </div>
            <p className="text-[12px] leading-5 text-t3">
              {uiT("调用结果的摘要在页面底部那条提示里；完整返回见设备桥自己的日志 （[源] evidence/bridge.log）。")}</p>
          </div>
        ) : null}
      </Drawer>

      <Drawer
        open={!!active}
        onClose={() => setActive(null)}
        title={active ? toolLabel(active.tool) : ''}
        meta={active?.group}
      >
        {active ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <StatusDot
                status={
                  active.tool.state === 'online' ? 'done' : active.tool.state === 'fault' ? 'alert' : 'empty'
                }
                label={uiT(STATE_TEXT[active.tool.state])}
              />
              <span className="text-[12px] text-t3">{active.tool.hint ?? '—'}</span>
            </div>
            <p className="text-[13px] leading-6 text-t2">
              {uiT("设备一律以 MCP 节点的形式落在画板上：节点只显示挂了几个工具、健康状态与接入形态， 取数走设备侧采集出口，跑脚本走命令行会话，要看原生界面走远程桌面。终端只在节点放大态里出现。 连接参数与凭据由场景包的设备记录提供，不写在前端。")}</p>
            <div className="surface-2 p-3">
              <div className="tick">{uiT("拖入画板")}</div>
              <div className="num mt-1 text-[13px] text-t2">{uiT("按住本工具拖到画板落点即建节点")}</div>
            </div>
          </div>
        ) : null}
      </Drawer>
    </>
  )
}
