import { useT } from '../../i18n'
/* ===========================================================================
   红线动作确认卡。

   六个红线动作——启动、停止、急停、写回参数、导出、归档——点下去一律先落到
   这张卡，人再点一次「确认执行」才真走。副驾不能自己点，它只能把动作排到
   useAppStore 的 redline 上。

   接了设备桥时，卡上多一行凭据信息：桥已经拒绝执行并签发了一张 pending 凭据，
   「确认执行」做的事是调 POST /confirmations/{token}/approve 把它批到 approved，
   再带票重调工具。所以这张卡不是前端自己加的一层礼貌询问，而是后端明确拒绝
   之后必须走的一步。依据：[源] spike-device-mcp/README.md 第 3 节。

   2026-09-20 起卡上多一个批准 PIN 输入框。理由：桥的调用票（VITE_BRIDGE_TOKEN）
   会被打进浏览器包，光有它谁都能自签自批；批准权因此另立一份只在桥服务端的秘密
   BRIDGE_APPROVER_PIN，由人在这里现场敲。PIN 只活在本组件的 useState 里，
   关卡即清，不写 localStorage、不进构建产物；它的边界是"浏览器内存里短暂存在"。
   =========================================================================== */
import { useState } from 'react'
import { AlertOctagon, ShieldCheck } from 'lucide-react'
import { Badge, Button, Modal } from '../../components/ui'
import { useAppStore } from '../../state/useAppStore'

export function RedlineConfirm() {
  const uiT = useT()

  const req = useAppStore((s) => s.redline)
  const busy = useAppStore((s) => s.redlineBusy)
  const error = useAppStore((s) => s.redlineError)
  const approve = useAppStore((s) => s.approveRedline)
  const reject = useAppStore((s) => s.rejectRedline)
  const operator = useAppStore((s) => s.operator)
  // PIN 只活在这个 useState 里。换一张票就在渲染期重置，不用 effect——
  // 与 ActionBar 的「按身份重置」同一写法，也省掉一条 set-state-in-effect 告警。
  const token = req?.confirmToken ?? null
  const [pinBox, setPinBox] = useState<{ key: string | null; v: string }>({ key: token, v: '' })
  if (pinBox.key !== token) setPinBox({ key: token, v: '' })
  const pin = pinBox.v
  const setPin = (v: string) => setPinBox({ key: token, v })

  if (!req) return null
  const Icon = req.danger ? AlertOctagon : ShieldCheck
  // ⚠️ 急停（emergency）**免现场 PIN**（2026-10-05 用户口径「来不及」）：
  // 仍弹这张卡防误触，但不显示 PIN 框、不要求输入；点「确认执行」直接走
  // 自动化放行 token（approveRedline 内部据 req.emergency 分流）。
  const needPin = Boolean(req.confirmToken) && !req.emergency
  const canApprove = !busy && (!needPin || pin.trim().length > 0)
  const submit = () => {
    if (!canApprove) return
    void approve(pin).then(() => setPin(''))
  }

  return (
    <Modal
      open
      onClose={busy ? () => undefined : reject}
      title={uiT("确认执行 · {v1}", { v1: uiT(req.title) })}
      meta={uiT("红线动作 · 确认人 {v1}", { v1: operator })}
      width={520}
      footer={
        <>
          <Button size="md" variant="default" disabled={busy} onClick={reject} data-testid="redline-cancel">
            {uiT("取消")}</Button>
          <Button
            size="md"
            variant={req.danger ? 'danger' : 'primary'}
            disabled={!canApprove}
            title={needPin && !pin.trim() ? uiT('先输入批准 PIN') : undefined}
            onClick={submit}
            data-testid="redline-approve"
          >
            {busy ? uiT('批准中…') : uiT('确认执行')}
          </Button>
        </>
      }
    >
      <div className="redline-confirm space-y-3">
        <div className="flex items-start gap-2.5">
          <Icon
            size={18}
            strokeWidth={1.9}
            className={req.danger ? 'mt-0.5 shrink-0 text-alert' : 'mt-0.5 shrink-0 text-p700'}
          />
          <p className="text-[13px] leading-6 text-t1">{uiT(req.prompt)}</p>
        </div>

        <dl className="surface-2 space-y-1.5 p-3 text-[12px] leading-5">
          <div className="flex gap-2">
            <dt className="w-[52px] shrink-0 text-t3">{uiT("参数")}</dt>
            <dd className="num min-w-0 flex-1 text-t2">{uiT(req.argsSummary) || uiT('无参数')}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-[52px] shrink-0 text-t3">{uiT("凭据")}</dt>
            <dd className="num min-w-0 flex-1 break-all text-t2">
              {req.confirmToken ? (
                <>
                  {req.confirmToken}
                  <Badge tone="soft" className="ml-1.5">
                    {uiT("设备桥已签发")}</Badge>
                </>
              ) : (
                <>
                  {uiT("本轮无设备凭据")}<Badge tone="neutral" className="ml-1.5">
                    {uiT("回放")}</Badge>
                </>
              )}
            </dd>
          </div>
        </dl>

        {needPin ? (
          <div className="surface-2 space-y-1.5 p-3">
            <label
              htmlFor="redline-pin"
              className="block text-[12px] font-medium leading-5 text-t1"
            >
              {uiT("批准 PIN")}</label>
            <input
              id="redline-pin"
              type="password"
              value={pin}
              autoFocus
              autoComplete="new-password"
              autoCorrect="off"
              spellCheck={false}
              data-testid="redline-pin"
              disabled={busy}
              onChange={(e) => setPin(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') submit()
              }}
              placeholder={uiT("输入设备桥的批准 PIN")}
              className="num w-full rounded-tps border border-line bg-bg px-2.5 py-1.5 text-[13px] leading-5 text-t1 outline-none focus:border-p700"
            />
            <p className="text-[12px] leading-5 text-t3">
              {uiT("PIN 取自设备桥 .env 的 BRIDGE_APPROVER_PIN，只在桥的服务端，不在本页面、也不在构建产物里。 页面里那份 token 只是调用票，批不动任何红线动作。输错 5 次桥会锁 60 秒。")}</p>
          </div>
        ) : null}

        <p className="text-[12px] leading-5 text-t3">
          {req.emergency
            ? uiT('急停为安全动作，**免现场 PIN**（来不及敲）：点「确认执行」即走安全放行通道切断驱动输出，台账记 emergency_auto。现场仍须保留物理急停回路。')
            : req.confirmToken
              ? uiT('点「确认执行」等于在设备桥上人工批准这张凭据：凭据单次使用、180 秒过期、绑定工具名与参数指纹，批准后才允许带票执行；台账会把这次放行记成 human_pin。')
              : uiT('设备桥未接入，本次只驱动页面回放，不向台架下发任何控制命令。')}
        </p>

        {error ? (
          <p className="rounded-tps border border-alert/40 bg-alert-wash px-2.5 py-2 text-[12px] leading-5 text-alert">
            {uiT("执行失败：")}{uiT(error)}
          </p>
        ) : null}
      </div>
    </Modal>
  )
}
