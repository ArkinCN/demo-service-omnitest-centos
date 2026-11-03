/* ===========================================================================
   顶栏动作条与左栏确认按钮的行为表。

   第四轮之前这些按钮全是静态渲染，一个 onClick 都没有（08c-部署联调与演示SOP-v1.0.md
   第零节「点不动的三处」第 1、2、3 条）。本文件把它们逐个接上，并保证六个红线动作
   （启动、停止、急停、写回参数、导出、归档）一律先落确认卡再执行。

   接了设备桥时红线动作走三段式：
     1. 不带 confirm_token 调一次桥的工具 → 桥拒绝执行，回一张 pending 凭据；
     2. 人在确认卡上点「确认执行」→ 前端调 POST /confirmations/{token}/approve；
     3. 带同一张票、同一组参数重调工具 → 才真执行。
   桥不可达时第 1、3 步跳过，只驱动页面回放，确认卡照弹，红线口径不因此松掉。
   =========================================================================== */
import { useNavigate } from 'react-router'
import {
  useAppStore,
  type RedlineAction,
  type RedlineRequest,
} from '../../state/useAppStore'
import { callBridgeTool, previewArgs, useBridgeDevice } from '../remote/bridge'
import { persistAdoption } from '../flow-tune/adoptApi'
import {
  REPORT_STATUS_TEXT,
  downloadUrl,
  generateReport,
  resolveReportRunId,
} from '../flow-report/reportApi'

/** 一个动作按钮点下去要知道的三件事 */
export interface ActionBinding {
  onClick: () => void
  disabled: boolean
  /** 置灰理由，挂 tooltip */
  reason?: string
}

/**
 * 本地测试动作（2026-10-06）：start/stop 由本地风扇测试业务承担，
 * **不向设备桥取票**，确认卡因此无凭据、无 PIN 框，只剩「确认执行/取消」的二次确认。
 *
 * 为什么：风扇启动走的是本地 fan-tests 通道（hardware/v0.6 脚本 + UNO），与设备桥的
 * 电机工具（duty_percent 等）是两条链路。此前 start 经桥取票，确认卡带 PIN 且文案是
 * 「启动被测电机」，与实际执行的风扇脚本错位，误导现场。
 *
 * 设备桥本身**保留**：write_param / export / archive / estop 及画布节点、Agent 工具
 * 等照旧走桥取票；仅这两个动作改走本地二次确认。
 */
const LOCAL_TEST_ACTIONS: ReadonlySet<RedlineAction> = new Set<RedlineAction>(['start', 'stop'])

/** bridgeArgs 需要的运行时上下文（从 store 实时取，避免硬编码）。 */
export interface BridgeArgsCtx {
  /** 当前勾选采纳的项（流程 4 写回参数用）。 */
  adopted: { key: string; name: string; from: string; to: string; group: string }[]
}

/**
 * 六个红线动作在桥上对应的工具名与本次要送的参数。
 *
 * ⚠️ 2026-09-28 修 G-05：`export` / `archive` 的 `run_id` 原先**写死 `'demo-run'`**
 * ——不管当前实际是哪一轮。后果是导出的永远是「demo-run」这个不存在的轮次，
 * 下游（桥、报告）拿不到真实产物。改为**函数式取值**：`runId` 运行时传入。
 *
 * ⚠️ 2026-09-29 修真机链路：`start` / `write_param` 的**硬编码示例参数**（duty_percent:60、
 * key:'ALIGN_CURRENT'、value:0.6）被删掉——它们与实际运行态对不上，确认卡会显示误导性参数。
 *   - `start` 真下发走 FreeRun，FTGeneralUtils.dll 无运行时写参数接口，占空比/时长由固件
 *     内部控制，这里不编一个假占空比。
 *   - `write_param` 取**真实采纳列表**的第一项做桥参数指纹（桥的 write_param 是单参数签名；
 *     多参数采纳的完整清单由 opts.argsSummary 在确认卡上显示）。采纳为空时传空对象。
 */
function bridgeArgs(
  action: RedlineAction,
  runId: string | null,
  ctx: BridgeArgsCtx,
): { tool: string; args: Record<string, unknown> } | null {
  const rid = runId || ''
  switch (action) {
    case 'start':
      return { tool: 'start', args: {} }
    case 'stop':
      return { tool: 'stop', args: {} }
    case 'estop':
      return { tool: 'estop', args: { reason: '页面急停按钮' } }
    case 'write_param': {
      const first = ctx.adopted.find((x) => x.group) ?? ctx.adopted[0]
      return {
        tool: 'write_param',
        args: first && first.group ? { key: first.key, value: Number(first.to) } : {},
      }
    }
    case 'export':
      return { tool: 'export', args: { run_id: rid, fmt: 'xlsm' } }
    case 'archive':
      return { tool: 'archive', args: { run_id: rid, note: '页面归档按钮' } }
    default:
      return null
  }
}

/** 导出/归档这类动作要用的轮次号；没有时返回一句如实的说明，不糊弄。 */
function runIdNote(runId: string | null): string {
  return runId ? `run_id ${runId.slice(0, 8)} · 格式 xlsm` : '尚无轮次号（还没跑过一轮） · 格式 xlsm'
}

/**
 * 排一个红线动作。始终先弹确认卡；桥在线时先向桥要一张凭据，凭据拿不到就把
 * 原因写在卡上，不假装拿到了。
 */
export function useRedlineGate(deviceId = 'bench') {
  const bridge = useBridgeDevice(deviceId)
  const requestRedline = useAppStore((s) => s.requestRedline)
  /** G-05：按实时 runId 组装桥参数（不再用写死的 demo-run） */
  const runId = useAppStore((s) => s.runId)
  /** 采纳列表（write_param 的桥参数指纹要用真实采纳项，不再写死 ALIGN_CURRENT） */
  const adoptedKeys = useAppStore((s) => s.adoptedKeys)
  const adoptMeta = useAppStore((s) => s.adoptMeta)

  return (
    action: RedlineAction,
    opts: {
      title: string
      prompt: string
      argsSummary: string
      danger?: boolean
      /**
       * 急停专用：**免现场 PIN**（2026-10-05 用户口径「来不及」）。
       * 仍弹确认卡防误触，但放行走自动化 token 通道（台账记 emergency_auto）。
       * 见 useAppStore 的 RedlineRequest.emergency 与 approveRedline。
       */
      emergency?: boolean
      onApprove: () => void
    },
  ) => {
    const ctx: BridgeArgsCtx = {
      adopted: adoptedKeys.map((k) => ({
        key: k,
        name: adoptMeta[k]?.name ?? k,
        from: adoptMeta[k]?.from ?? '—',
        to: adoptMeta[k]?.to ?? '—',
        group: adoptMeta[k]?.group ?? '',
      })),
    }
    const call = bridgeArgs(action, runId, ctx)
    const base: RedlineRequest = {
      action,
      title: opts.title,
      prompt: opts.prompt,
      argsSummary: opts.argsSummary,
      danger: opts.danger,
      // 急停免 PIN：透传给确认卡与 store（见 opts.emergency 说明）
      emergency: opts.emergency,
      confirmToken: null,
      deviceId,
      onApprove: opts.onApprove,
    }
    // 本地测试动作（start/stop）：不向桥取票，直接弹本地二次确认卡（confirmToken=null）
    // → 确认卡无凭据行、无 PIN 框，只保留「确认执行/取消」。
    if (LOCAL_TEST_ACTIONS.has(action)) {
      requestRedline(base)
      return
    }
    if (bridge.link !== 'online' || !call) {
      requestRedline(base)
      return
    }
    // 第一段：不带票调一次，等桥拒绝并发票
    void callBridgeTool(deviceId, call.tool, call.args)
      .then((r) => {
        const token = r.confirm_token ?? null
        const preview = previewArgs(r.args_preview)
        requestRedline({
          ...base,
          confirmToken: token,
          prompt: r.prompt ? `${r.prompt}。${r.reason ?? '设备桥已拒绝执行并签发凭据'}` : base.prompt,
          argsSummary: preview ? `${preview}（设备桥绑定的参数指纹）` : base.argsSummary,
          onApprove: async () => {
            // 第三段：带同一张票、同一组参数重调。参数改一个字桥都会拒。
            if (token) await callBridgeTool(deviceId, call.tool, { ...call.args, confirm_token: token })
            opts.onApprove()
          },
        })
      })
      .catch((e: unknown) => {
        requestRedline({
          ...base,
          prompt: `${base.prompt}\n设备桥取票失败：${e instanceof Error ? e.message : String(e)}。确认后只驱动页面回放，不向台架下发命令。`,
        })
      })
  }
}

/* --------------------------------------------------------------- 动作绑定表 */

/**
 * 按动作 id 取绑定。TopBar 的动作条与左栏底部确认按钮共用同一份，
 * 同一条动作不会出现两种行为。
 */
export function useFlowActions(): (id: string) => ActionBinding {
  const nav = useNavigate()
  const redline = useRedlineGate()
  const bridge = useBridgeDevice()
  const s = useAppStore()

  const gateGreen = s.gateTotal > 0 && s.gateAcked.length >= s.gateTotal
  const gateLeft = Math.max(0, s.gateTotal - s.gateAcked.length)
  const adoptedCount = s.adoptedKeys.length
  const noop: ActionBinding = {
    onClick: () => undefined,
    disabled: true,
    reason: '该动作在当前原型里未接后端',
  }

  const adoptedList = () =>
    s.adoptedKeys.map((k) => ({
      key: k,
      name: s.adoptMeta[k]?.name ?? k,
      from: s.adoptMeta[k]?.from ?? '—',
      to: s.adoptMeta[k]?.to ?? '—',
      group: s.adoptMeta[k]?.group ?? '',
    }))

  const table: Record<string, ActionBinding> = {
    /* ------------------------------------------------------------- 流程 3 */
    start: {
      disabled: !gateGreen || s.runPhase === 'running',
      reason: !gateGreen
        ? `安全闸门还差 ${gateLeft} 条未逐条确认，确认前不可启动`
        : s.runPhase === 'running'
          ? '本轮正在运行，先停止再启动'
          : undefined,
      onClick: () =>
        redline('start', {
          title: '启动测试',
          prompt:
            '启动风扇测试：风扇将按 30/50/70/100% 各 20 秒运行，台架会真的转起来。确认前请确认现场无人接触旋转件。',
          argsSummary: `按默认计划 80 秒 · 驱动 hardware/v0.6 脚本 · 闸门 ${s.gateAcked.length}/${s.gateTotal} 全绿`,
          onApprove: () => {
            useAppStore.getState().beginRun()
            useAppStore.getState().setNotice('本轮已启动，风扇按计划运行，曲线将实时刷新')
          },
        }),
    },
    precheck: {
      disabled: false,
      onClick: () => {
        if (bridge.link === 'online' && bridge.device) {
          const st = bridge.device.status
          s.setNotice(
            `预检：设备桥 ${st.mode} 模式 · ${st.hostname ?? '主机名未取到'} · 工具 ${bridge.toolCount} 个 · 闸门 ${s.gateAcked.length}/${s.gateTotal}`,
          )
        } else {
          s.setNotice(`预检：设备桥未接入（${bridge.reason ?? '原因未知'}）· 闸门 ${s.gateAcked.length}/${s.gateTotal}`)
        }
      },
    },
    stop: {
      disabled: s.runPhase !== 'running',
      reason: s.runPhase !== 'running' ? '本轮没有在运行的测试' : undefined,
      onClick: () =>
        redline('stop', {
          title: '停止风扇测试',
          prompt: '按正常流程停止本轮风扇测试：风扇减速停转，已采到的数据保留。',
          argsSummary: `本轮进度 ${s.runProgress}%`,
          onApprove: () => {
            useAppStore.getState().setRunPhase('stopped')
            useAppStore.getState().setNotice('本轮已停止，已采数据保留')
          },
        }),
    },
    estop: {
      disabled: false,
      onClick: () =>
        redline('estop', {
          title: '急停',
          prompt: '立即切断驱动输出。软件急停只是补充手段，现场仍须有一条物理急停回路，不能拿它当唯一手段。',
          argsSummary: '原因：页面急停按钮',
          danger: true,
          // ⚠️ 急停免现场 PIN（2026-10-05 用户口径「来不及」）：仍弹确认卡防误触，
          // 但放行走自动化 token（emergency_auto），不要求现场敲 PIN。
          emergency: true,
          onApprove: () => {
            useAppStore.getState().setRunPhase('estopped')
            useAppStore.getState().setNotice('已急停：驱动输出切断')
          },
        }),
    },

    /* ------------------------------------------------------------- 流程 4 */
    'adopt-back': {
      disabled: adoptedCount === 0,
      reason: adoptedCount === 0 ? '先在推荐参数里勾选要采纳的项' : undefined,
      onClick: () =>
        redline('write_param', {
          title: '写回参数并回到启动测试',
          prompt: `把 ${adoptedCount} 项采纳的建议值写回驱动板，然后回到流程 3 重跑一轮。写回只改数值外壳括号内的数字，不换外壳、不动行尾注释。`,
          argsSummary: adoptedList()
            .map((c) => `${c.key.toUpperCase()} ${c.from}→${c.to}`)
            .join('；'),
          onApprove: async () => {
            const st = useAppStore.getState()
            const items = adoptedList()
            st.applyAdopt(items)
            st.confirmFlow('tune')
            st.setRunPhase('idle')
            // 落库与界面推进分开：采纳这件事在界面上已经生效，
            // 但落库失败必须说出来——否则人以为存住了，刷新却是空的。
            try {
              const { runId } = await persistAdoption({
                sceneId: st.sceneId,
                runId: st.runId,
                items,
                operator: st.operator,
              })
              st.setRunId(runId)
              st.setNotice(`已采纳 ${adoptedCount} 项并写回服务端（轮次 ${runId.slice(0, 8)}），可重新启动一轮`)
            } catch (e) {
              st.setNotice(
                `已采纳 ${adoptedCount} 项，但落库失败（刷新后找不回）：${e instanceof Error ? e.message : String(e)}`,
              )
            }
            nav('/run')
          },
        }),
    },
    'ignore-all': {
      disabled: adoptedCount === 0,
      reason: adoptedCount === 0 ? '当前没有勾选中的推荐项' : undefined,
      onClick: () => {
        const n = adoptedCount
        s.adoptedKeys.forEach((k) => s.toggleAdopt(k))
        s.setNotice(`已忽略 ${n} 条推荐，本轮不写回任何参数`)
      },
    },
    rollback: {
      disabled: s.adoptedApplied.length === 0,
      reason: s.adoptedApplied.length === 0 ? '本会话还没有写回过参数，没有可回滚的基线' : undefined,
      onClick: () =>
        redline('write_param', {
          title: '回滚基线',
          prompt: `把上一次写回的 ${s.adoptedApplied.length} 项参数改回原值。回滚同样是写回动作，走同一道红线。`,
          argsSummary: s.adoptedApplied.map((c) => `${c.key.toUpperCase()} ${c.to}→${c.from}`).join('；'),
          danger: true,
          onApprove: async () => {
            const st = useAppStore.getState()
            const prev = st.adoptedApplied
            // 4→3 回环：回滚要把写回的参数改回原值（from），不能只清展示态——
            // 否则流程 3 还会显示上一次采纳的值。
            st.applyAdopt(prev.map((x) => ({ ...x, to: x.from })))
            st.applyAdopt([])
            // 回滚也要落库（空 items 覆盖同轮 param-change）：否则刷新后壳层读回
            // 上一份「采纳」记录，采纳值又复活，回滚形同虚设。
            try {
              const { runId } = await persistAdoption({
                sceneId: st.sceneId,
                runId: st.runId,
                items: [],
                operator: st.operator,
                note: '回滚记录：已把上次写回的建议值改回原值，本轮不保留任何采纳。',
              })
              st.setNotice(`已回滚到写回前的基线（轮次 ${runId.slice(0, 8)}）`)
            } catch (e) {
              st.setNotice(
                `已回滚，但落库失败（刷新后采纳记录可能复活）：${e instanceof Error ? e.message : String(e)}`,
              )
            }
          },
        }),
    },
    'view-evidence': {
      disabled: false,
      onClick: () => nav('/knowledge'),
    },

    /* ------------------------------------------------------------- 流程 5 */
    'gen-report': {
      // 不因「本会话没点过启动」就置灰：没有内存 runId 时按场景取**最近一轮**
      // （与采纳同款兜底，见 reportApi.resolveReportRunId）。真的连一轮都没有，
      // 才在点击后如实报错——那才是"没有可生成的对象"。
      disabled: false,
      onClick: () => {
        const st = useAppStore.getState()
        // G-06：真调后端生成。**状态如实显示**——三档说法不同，
        // 把 placeholder 说成「已生成」等于把占位件当交付件。
        st.setNotice('正在生成报告…')
        nav('/report')
        void resolveReportRunId(st.sceneId, st.runId)
          .then((rid) => generateReport(rid).then((r) => ({ rid, r })))
          .then(({ rid, r }) => {
            st.setReportGenerated(r.status !== 'blocked')
            const t = REPORT_STATUS_TEXT[r.status]
            if (r.status === 'blocked') {
              st.setNotice(`${t.label}：${r.reason ?? '未给出原因'}`)
              return
            }
            // 生成成功（ok / placeholder）就**自动触发下载**——用户点「生成报告」的
            // 预期就是拿到文件，之前只弹通知不下载，是「提示可下载也不下载」的根因。
            const a = document.createElement('a')
            a.href = downloadUrl(rid)
            a.download = ''
            document.body.appendChild(a)
            a.click()
            a.remove()
            st.setNotice(
              r.status === 'ok'
                ? `${t.label}：${r.file ?? ''}（${r.bytes ?? 0} 字节），已开始下载`
                : // placeholder 只剩「改版前落的历史轮次」这一种来源，措辞里不再提「可替换」
                  `${t.label}：${r.file ?? ''}（${r.bytes ?? 0} 字节），已开始下载；该轮为历史占位版式`,
            )
          })
          .catch((e: unknown) => {
            st.setReportGenerated(false)
            st.setNotice(`报告生成失败：${e instanceof Error ? e.message : String(e)}`)
          })
      },
    },
    preview: {
      disabled: false,
      onClick: () => {
        // 2026-09-30：此前这里是**假动作**——只 setReportGenerated(true)（谎报已生成）
        // 再 nav('/report')，什么预览都没打开。现在改为「跳到报告页 + 打开整篇预览弹层」，
        // 弹层在报告页渲染（读 store 里已确认/已装配的表头与真判定行），可关闭。
        const st = useAppStore.getState()
        st.setReportPreviewOpen(true)
        nav('/report')
      },
    },
    // ⚠️ `export` 动作已删除（2026-09-30 用户口径）：生成报告成功后已一步到位自动下载，
    // 导出是重复的第二入口（其内部逻辑＝探活→没生成就先生成→下载）。
    // 设备桥的 export 工具映射（上面 bridgeArgs 的 case 'export'）**保留**，
    // 那是 AI 助手对话里的 export 动作，与本按钮无关；此表删掉绑定即可，
    // 顶栏也不再渲染该按钮（见 data/flows.ts 的 report.actions）。
    'archive-kb': {
      disabled: false,
      onClick: () =>
        redline('archive', {
          title: '归档到知识库',
          prompt: '把本轮产物与判定结论归档进知识库，归档后会被后续检索命中。',
          // G-05：同上，真实轮次号
          argsSummary: `${runIdNote(s.runId)} · 备注：页面归档按钮`,
          onApprove: () =>
            useAppStore.getState().setNotice(`归档已由 ${useAppStore.getState().operator} 确认执行`),
        }),
    },

    /* ------------------------------------------------- 流程 1 / 2 的确认类动作 */
    /**
     * ⚠️ `lock` 动作已随顶栏「提交并锁定」按钮一并移除（2026-09-29）。
     *
     * 历史：原实现 `confirmFlow('init')` 只改内存不落快照（2026-09-28 修成
     * 「跳到初始化页 + 弹提示」）；现用户要求彻底移除这颗顶栏按钮——
     * 该业务已在左栏页脚的「确认并锁定 · N 项」得到使用
     * （`ConfirmFooter` → `confirmAndSnapshot`，全站唯一落库入口）。
     * 与流程 2 移除顶栏「确认需求基线」同一口径：确认类动作只留一个入口。
     */
    /**
     * ⚠️ `baseline` 动作已随顶栏按钮一并移除（2026-09-28）。
     *
     * 原实现只 `confirmFlow('req')` 改内存 + 弹提示，**不落库、不跳转**；
     * 而左栏页脚那颗同义的「确认基线」是个空壳（没传 onClick）。
     * 两颗按钮都不到位，人不知道点哪个才对。
     * 现在统一到左栏页脚那一处：落 requirement-baseline + 跳转流程 3 + 刷新读回
     * （实现见 `features/flow-req/panel.tsx` 的 `confirmBaseline`，
     *   落库用 `features/flow-req/baselineApi.ts`）。
     * 这里刻意不保留一个空动作——留着会被别处 bind('baseline') 意外命中。
     */
    'import-std': {
      disabled: false,
      onClick: () => useAppStore.getState().setNotice('导入标准：本轮未接入，功能待排期'),
    },
  }

  return (id: string) => table[id] ?? noop
}
