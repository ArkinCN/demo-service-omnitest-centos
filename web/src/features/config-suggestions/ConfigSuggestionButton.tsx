import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { AlertCircle, FlaskConical, LoaderCircle, Sparkles } from 'lucide-react'
import { STAGE_PRESENTATION } from '../../app/configPresentation'
import { Button, Modal } from '../../components/ui'
import { useLocale, useT } from '../../i18n'
import { useAppStore } from '../../state/useAppStore'
import { fetchModels } from '../agent-chat/models'
import { applyChanges, assertEditable, snapshotFor } from './context'
import { fingerprint, validateProposal, type Change, type Proposal, type Snapshot, type Stage } from './protocol'
import { SuggestionProposalView } from './SuggestionProposalView'
import { createDemoChanges } from './demo'

/**
 * 「载入待修正示例」开关。
 *
 * 这是演示能力：会把人为偏差写进**当前草稿**。现场误点会改坏已填好的配置
 * （交接坑 #7），因此默认只在开发服务器可见；生产构建必须显式设置
 * `VITE_ENABLE_DEMO_DRAFT=true` 才会出现。
 */
const DEMO_DRAFT_ENABLED = import.meta.env.DEV || import.meta.env.VITE_ENABLE_DEMO_DRAFT === 'true'

export function ConfigSuggestionButton({ stage, getSelection, updateSelection, pending = false }: {
  stage: Stage; getSelection?: () => ReadonlySet<string>; updateSelection?: (changes: Change[]) => void; pending?: boolean
}) {
  // 界面文案统一走共享词典（uiT）；locale 仍用于上报给后端（决定模型答复语言）与重置评审结果。
  const { locale } = useLocale()
  const uiT = useT()
  const locked = useAppStore(state => !!state.confirmed[stage])
  const running = useAppStore(state => state.runPhase === 'running' || state.automationRunStatus === 'running')
  const sceneId = useAppStore(state => state.sceneId)
  // Re-render the review when another editor changes draft or inherited values.
  useAppStore(state => state.overrides)
  useAppStore(state => state.snapshotValues)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<{ snapshot: Snapshot; proposal: Proposal; model: string } | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const demoKey = `${sceneId}:${stage}`
  const demoLoaded = useAppStore(state => !!state.configSuggestionDemoDrafts[demoKey])
  const requestId = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const pendingRef = useRef(pending)
  useLayoutEffect(() => { pendingRef.current = pending }, [pending])
  useEffect(() => {
    setOpen(false); setBusy(false); setError(''); setResult(null); setSelected([])
    return () => { requestId.current += 1; controller.current?.abort() }
  }, [sceneId, stage, locale])
  const close = () => {
    requestId.current += 1; controller.current?.abort()
    setOpen(false); setBusy(false); setError(''); setResult(null); setSelected([])
  }
  const guard = () => {
    assertEditable(stage)
    if (pendingRef.current) throw new Error(uiT('配置正在保存，请稍后重试。'))
  }
  let stale = false
  if (result && !locked && !running && !pending) {
    try { stale = fingerprint(result.snapshot) !== fingerprint(snapshotFor(stage, getSelection?.())) }
    catch { stale = true }
  }
  const unavailable = locked || running || pending
  const loadDemo = () => {
    try {
      guard()
      const snapshot = snapshotFor(stage, getSelection?.())
      const changes = createDemoChanges(snapshot)
      if (!changes.length) {
        useAppStore.getState().setNotice(uiT('本阶段没有适用的演示字段，未修改配置。'))
        return
      }
      close()
      applyChanges(snapshot, changes, snapshotFor(stage, getSelection?.()), updateSelection)
      useAppStore.setState(state => ({ configSuggestionDemoDrafts: { ...state.configSuggestionDemoDrafts, [demoKey]: true } }))
      useAppStore.getState().setNotice(uiT('已载入人为偏差的演示草稿，请让模型检查；未保存或操作设备。'))
    } catch (reason) {
      useAppStore.getState().setNotice(reason instanceof Error ? reason.message : uiT('未能载入演示配置。'))
    }
  }
  const generate = async () => {
    controller.current?.abort()
    const operation = ++requestId.current
    const abort = new AbortController()
    controller.current = abort
    setOpen(true); setBusy(true); setError(''); setResult(null); setSelected([])
    const timeout = setTimeout(() => abort.abort(), 190000)
    try {
      guard()
      const snapshot = snapshotFor(stage, getSelection?.())
      if (DEMO_DRAFT_ENABLED && demoLoaded) snapshot.evidence.push({ id: 'demo:deliberate-draft', title: uiT('人为偏差演示'), text: 'This stage previously loaded a synthetic draft with deliberately changed settings or an omitted test. Current values may already be corrected. Review the current editable values against the scenario-package references and criteria; propose only remaining supported repairs. These are demo inputs, not measurements or device recommendations.' })
      const models = await fetchModels(abort.signal)
      if (!models.length) throw new Error(uiT('当前没有可用的大模型。'))
      // 模型 id 由后端 .env 的 MOTORDEBUG_LLM_MODEL 派生，前端不能写死
      // （写死过 'deepseek-flash'，换模型后按钮直接报「当前渠道未提供」）。
      // 列表按 sort_order 升序，首项即平台主模型：固定用它，不随机挑，
      // 失败时不静默换别的模型（否则用户会误以为结果来自所选模型）。
      const model = models[0].value
      guard()
      const response = await fetch('/api/agent/config-suggestions', {
        method: 'POST', signal: abort.signal, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...snapshot, model, locale }),
      })
      if (!response.ok) throw new Error(uiT(`建议服务暂不可用（HTTP {v1}），未修改配置。`, { v1: response.status }))
      const data = await response.json() as { model?: unknown; proposal?: unknown }
      if (data.model !== model) throw new Error('Unexpected model identity')
      const proposal = validateProposal(data.proposal, snapshot)
      if (operation !== requestId.current || abort.signal.aborted) return
      setResult({ snapshot, proposal, model })
    } catch (reason) {
      if (operation === requestId.current) setError(abort.signal.aborted ? uiT('请求已取消或超时，未修改配置。') : uiT('无法生成有效建议，未修改配置。请检查后端、模型配置及登录状态。') + ' ' + (reason instanceof Error ? reason.message : ''))
    } finally {
      clearTimeout(timeout)
      if (operation === requestId.current) setBusy(false)
    }
  }
  const apply = () => {
    if (!result) return
    try {
      guard()
      applyChanges(result.snapshot, result.proposal.changes.filter(change => selected.includes(change.field_id)), snapshotFor(stage, getSelection?.()), updateSelection)
      useAppStore.getState().setNotice(uiT(`已填入 {v1} 项建议。请核对并按原流程确认配置；未启动检测或写入设备。`, { v1: selected.length }))
      close()
    } catch (reason) { setError(reason instanceof Error ? reason.message : uiT('应用失败，未修改配置。')) }
  }
  const footer = <div className="config-suggestion-footer"><span>{uiT('仅填入草稿')}</span><Button variant="default" onClick={close}>{uiT('取消')}</Button>
    {result ? <Button disabled={!selected.length || unavailable || stale || busy} aria-label={uiT(`确认填入所选的 {v1} 项建议`, { v1: selected.length })} onClick={apply}>{uiT(`填入 {v1} 项`, { v1: selected.length })}</Button> : null}
  </div>
  return <>
    <div className="config-suggestion-entry">
      <Button block variant="secondary" size="lg" icon={<Sparkles size={17} />} disabled={unavailable || busy} onClick={() => void generate()}>{uiT('大模型设置建议')}</Button>
      <p>{pending ? uiT('正在保存配置，请稍后。') : locked ? uiT('先解除本阶段确认，再生成建议。') : running ? uiT('请等待当前测试结束。') : uiT('查看修改说明，勾选确认后填入配置。')}</p>
      {DEMO_DRAFT_ENABLED ? <div className="config-suggestion-demo"><Button variant="ghost" size="sm" icon={<FlaskConical size={14} />} disabled={unavailable || busy} onClick={loadDemo}>{uiT('载入待修正示例')}</Button>
        {demoLoaded ? <span role="status">{uiT('本阶段已载入人为偏差示例，草稿仅供演示。')}</span> : null}
      </div> : null}
    </div>
    <Modal open={open} onClose={close} title={uiT('大模型设置建议')} meta={`${STAGE_PRESENTATION[stage].index} · ${uiT(STAGE_PRESENTATION[stage].title)}`} footer={footer}>
      <div className="config-suggestion-dialog" aria-busy={busy}>
        {busy ? <div className="config-suggestion-state" role="status"><LoaderCircle className="animate-spin" size={26} aria-hidden="true" /><h3>{uiT('正在分析当前配置')}</h3><p>{uiT('大模型正在结合当前字段和依据生成建议，请稍候。')}</p></div> : null}
        {error ? <div role="alert" className="config-suggestion-error"><AlertCircle size={20} aria-hidden="true" /><p>{error}</p></div> : null}
        {stale ? <div role="alert" className="config-suggestion-error"><AlertCircle size={20} aria-hidden="true" /><p>{uiT('配置已变化，请重新生成建议后再填入。')}</p></div> : null}
        {result ? <SuggestionProposalView stage={stage} {...result} selected={selected} disabled={unavailable || stale || busy} onToggle={(id, checked) => setSelected(previous => checked ? [...new Set([...previous, id])] : previous.filter(item => item !== id))} onRegenerate={() => void generate()} regenerateDisabled={unavailable || busy} /> : null}
        {!busy && !result ? <div className="config-suggestion-state"><Button disabled={unavailable} onClick={() => void generate()}>{uiT('重试')}</Button></div> : null}
      </div>
    </Modal>
  </>
}
