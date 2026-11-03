/* ===========================================================================
   设备 = 画板上的一个 MCP 节点。

   第三轮把「单机设备会话」这张独立卡撤掉：一台设备在画板上就是一个节点，
   节点上只显示挂了几个工具、健康状态、接入形态；终端只在放大态里出现，
   画板层不出现终端。SSH 网关（c/components/webssh，端口 8022）保留，但降级为
   「命令行会话」这一种接入形态的实现细节，不再对应任何卡或页面。
   依据：《第三轮需求变更方案 v0.1》第 2.3 节。

   RemoteDeviceCard 与 RemoteTerminal 的代码原样保留，只换挂载位置。
   =========================================================================== */
import { useEffect, useState } from 'react'
import type { ScenePackage } from '../../data/types'
import { probeDevice } from './api'
import type { ConnState, RemoteDevice } from './types'

/**
 * 台架工控机的**连接信息**。一律从环境变量取（变量名见 .env.example），
 * 不写在代码里。
 *
 * 为什么要外置：IP、端口、用户名、取图目录都随台架环境变，写死换一台机器就失效；
 * 而且把客户内网 IP 留在交付代码里本身就不合脱敏要求。
 * 2026-09-23 全量审查时发现这里写死了 172.25.5.166 / 5011 / administrator / C:\fc_pull。
 *
 * 默认值取中性值而不是原来的内网地址：没配置时宁可显示「未配置」，
 * 也不让一份脱敏交付物里躺着一个具体台架的地址。
 * 与 api.ts / bridge.ts 的写法保持一致（`import.meta.env.X ?? 默认值`）。
 *
 * 注：`model` 是展示用的设备标识，不是连接配置，故保留字面量。
 */
export const BENCH_HOST = (import.meta.env.VITE_BENCH_HOST ?? '').trim()
const BENCH_PORT = Number(import.meta.env.VITE_BENCH_PORT ?? 22)
const BENCH_USER = (import.meta.env.VITE_BENCH_USER ?? '').trim()
/** 台架取图目录。导出供界面文案复用，避免同一份配置在两个文件里各读一遍。 */
export const BENCH_PULL_DIR = (import.meta.env.VITE_BENCH_PULL_DIR ?? '').trim()

/**
 * 台架工控机。与 src/features/flow-run/panel.tsx 里那份是同一台机器的同一条记录：
 * 峰岹（Fortior）电机测试 Windows 工控机。
 * keyRef 写的是环境变量名，私钥本体只在网关一侧，浏览器不持有任何凭据。
 */
export const BENCH_DEVICE: RemoteDevice = {
  id: 'bench',
  name: '台架工控机',
  model: 'SK-20251218QPBB / Windows 11',
  host: BENCH_HOST,
  port: BENCH_PORT,
  user: BENCH_USER,
  keyRef: 'FORTIOR_WIN_KEY',
  kind: 'host',
  via: null,
  presets: [
    { label: '主机名', cmd: 'hostname' },
    // 取图目录没配就不给这条预设：否则会拼出 `dir ` 这种空命令，
    // 点了毫无反应，比不显示更难排查。
    ...(BENCH_PULL_DIR ? [{ label: '取图目录', cmd: `dir ${BENCH_PULL_DIR}` }] : []),
  ],
}

/** 四种接入形态。画板节点只报形态，不在画板层开任何会话。 */
export const ACCESS_FORMS = ['数据拉取', '命令行会话', '远程桌面', '独立窗口'] as const

/** 设备挂了哪些工具：取当前场景包工具条的登记，不另立一张表 */
export function deviceToolStat(scene: ScenePackage) {
  const tools = scene.toolGroups.flatMap((g) => g.tools)
  return {
    total: tools.length,
    online: tools.filter((t) => t.state === 'online').length,
    fault: tools.filter((t) => t.state === 'fault').length,
  }
}

/** 探一次网关。网关没起时落到「未接入」，不报错、不阻塞画板。 */
export function useDeviceState(id = BENCH_DEVICE.id) {
  const [state, setState] = useState<ConnState>('idle')
  useEffect(() => {
    let alive = true
    void probeDevice(id)
      .then((r) => alive && setState(r.online ? 'connected' : 'closed'))
      .catch(() => alive && setState('closed'))
    return () => {
      alive = false
    }
  }, [id])
  return state
}

