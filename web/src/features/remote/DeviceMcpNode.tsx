import { useT } from '../../i18n'
/* ===========================================================================
   设备 MCP 节点的两个视图：画板上的节点体、放大态。

   第四轮把数据源从 SSH 网关（c/components/webssh，8022，GET /probe/bench）换成设备桥
   （[源] spike-device-mcp/bridge.py，8031，GET /devices 与 /devices/{id}/status）。
   换的理由是桥一次就给全节点要的三样东西：设备元信息、live/mock 模式、按层分组
   的工具清单；网关那条只回一个布尔量，节点上除了「通/不通」什么都显示不了。
   依据：[源] spike-device-mcp/README.md 第 5 节、08c-部署联调与演示SOP-v1.0.md 第 1.2 节。

   SSH 网关保留，但只剩「命令行会话」一个用途，即放大态里那个终端。
   =========================================================================== */
import { useState } from 'react'
import { Badge, Button, Tooltip } from '../../components/ui'
import type { ScenePackage } from '../../data/types'
import { RemoteDeviceCard } from './RemoteDeviceCard'
import { RemoteTerminal } from './RemoteTerminal'
import { ACCESS_FORMS, BENCH_DEVICE, deviceToolStat, useDeviceState } from './device'
import { BRIDGE_LAYER_TITLE, useBridgeDevice, type BridgeLayer, type BridgeState } from './bridge'

/** 模式徽章文案：mock 一律显式标「合成」，不让它冒充实测 */
const MODE_TEXT: Record<string, string> = {
  live: 'live 真连台架',
  mock: 'mock 合成数据',
  unknown: '未连过',
}

/**
 * 画板上的节点体：只有三行事实，没有终端。
 * 节点高度 168 只放得下三行 + 底栏，第四行会被裁掉半截，所以地址退进 tooltip。
 */
export function DeviceMcpNodeBody({ scene, bridge }: { scene: ScenePackage; bridge: BridgeState }) {
  const uiT = useT()
  const stat = deviceToolStat(scene)
  const st = bridge.device?.status
  const online = bridge.link === 'online'
  const addr = bridge.device?.target ?? `${BENCH_DEVICE.user}@${BENCH_DEVICE.host}:${BENCH_DEVICE.port}`
  const linkText = online ? '已连通' : bridge.link === 'loading' ? '探测中' : '未连通'
  const rows: [string, string, string, string?][] = [
    [
      '工具',
      online ? `${bridge.toolCount} 个 · 三层` : `${stat.total} 个 · 在线 ${stat.online}`,
      online
        ? Object.entries(bridge.device?.tool_groups ?? {})
            .map(([k, v]) => `${BRIDGE_LAYER_TITLE[k as BridgeLayer] ?? k} ${v?.length ?? 0}`)
            .join(' · ')
        : '设备桥未接入，这里退回场景包工具条的登记数',
    ],
    [
      '模式',
      online ? (MODE_TEXT[st?.mode ?? 'unknown'] ?? (st?.mode ?? '—')) : ACCESS_FORMS.slice(0, 2).map((form) => uiT(form)).join(' · '),
      online
        ? `${st?.mock_warning ?? `主机名 ${st?.hostname ?? '未取到'}`} · ${addr}`
        : `${ACCESS_FORMS.map((form) => uiT(form)).join(' / ')} · ${addr}`,
    ],
    [
      '网关',
      linkText,
      bridge.reason ?? `设备桥可达，节点状态每 5 秒轮一次 GET /devices/{id}/status · ${addr}`,
      'device-link',
    ],
  ]
  return (
    <div className="flex h-full flex-col justify-center gap-1.5 px-1">
      {rows.map(([k, v, tip, testid]) => (
        <div key={k} className="flex items-baseline gap-2 text-[12px] leading-none">
          <span className="w-[30px] shrink-0 text-t3">{uiT(k)}</span>
          <Tooltip content={uiT(tip)}>
            <span className="num truncate text-t2" data-testid={testid}>
              {uiT(v)}
            </span>
          </Tooltip>
        </div>
      ))}
    </div>
  )
}

/** 放大态：设备卡 + 接入形态 + 终端。终端按需打开，关掉即回画板。 */
export function DeviceMcpExpanded({ scene }: { scene: ScenePackage }) {
  const uiT = useT()

  const state = useDeviceState()
  const bridge = useBridgeDevice()
  const [term, setTerm] = useState(false)
  const stat = deviceToolStat(scene)
  const st = bridge.device?.status

  return (
    <div className="flex h-full min-h-0 w-full gap-3">
      <div className="flex w-[320px] shrink-0 flex-col gap-2">
        <RemoteDeviceCard device={BENCH_DEVICE} state={state} onOpenTerminal={() => setTerm(true)} />
        <div className="surface-2 p-3">
          <div className="tick">{uiT("接入形态")}</div>
          <ul className="mt-1.5 space-y-1 text-[12px] leading-5 text-t2">
            {ACCESS_FORMS.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </div>
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="surface-2 p-3">
          <div className="flex items-center gap-2">
            <span className="tick">{uiT("设备桥")}</span>
            <Badge tone={bridge.link === 'online' ? 'soft' : 'neutral'} dot className="ml-auto">
              {bridge.link === 'online' ? (MODE_TEXT[st?.mode ?? 'unknown'] ?? uiT('已连通')) : uiT('未连通')}
            </Badge>
          </div>
          {bridge.link === 'online' ? (
            <>
              <div className="num mt-1 text-[13px] text-t2">
                {bridge.toolCount} {uiT(" 个工具 ·")}{' '}
                {Object.entries(bridge.device?.tool_groups ?? {})
                  .map(([k, v]) => `${BRIDGE_LAYER_TITLE[k as BridgeLayer] ?? k} ${v?.length ?? 0}`)
                  .join(' · ')}
              </div>
              <p className="mt-2 text-[12px] leading-5 text-t3">
                {uiT("主机名 ")}{st?.hostname ?? uiT('未取到')}{uiT("，待确认凭据 ")}{st?.pending_confirmations ?? 0} {uiT(" 张。 动作层六个工具对应六条红线，点下去只会拿回一张待确认凭据，执行要人在确认卡上再点一次。")}</p>
            </>
          ) : (
            <p className="mt-2 text-[12px] leading-5 text-t3">{bridge.reason ?? uiT('正在探设备桥')}</p>
          )}
        </div>
        <div className="surface-2 p-3">
          <div className="tick">{uiT("场景包登记的工具")}</div>
          <div className="num mt-1 text-[13px] text-t2">
            {stat.total} {uiT(" 个 · 在线 ")}{stat.online} {uiT(" · 异常 ")}{stat.fault}
          </div>
          <p className="mt-2 text-[12px] leading-5 text-t3">
            {uiT("这一份取自当前场景包的工具条登记，与设备桥那份是两套来源：场景包讲的是本产品要用哪些能力， 设备桥讲的是这台机器现在真挂着哪些工具。凭据不进浏览器：桥侧只按环境变量名")}{' '}
            {BENCH_DEVICE.keyRef} {uiT(" 取私钥。")}</p>
        </div>
        {term ? (
          <div className="min-h-0 flex-1">
            <RemoteTerminal
              deviceId={BENCH_DEVICE.id}
              target={BENCH_DEVICE}
              title={BENCH_DEVICE.name}
              presets={BENCH_DEVICE.presets}
            />
          </div>
        ) : (
          <div className="surface-2 flex min-h-0 flex-1 flex-col items-center justify-center gap-2 p-3">
            <p className="text-[12px] text-t3">{uiT("终端只在放大态出现，画板层不开终端")}</p>
            <Button size="sm" variant="secondary" onClick={() => setTerm(true)}>
              {uiT("打开终端")}</Button>
          </div>
        )}
      </div>
    </div>
  )
}
