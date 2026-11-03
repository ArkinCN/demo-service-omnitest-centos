import { ArrowRight, BookOpen, CircleHelp, FileText, ListChecks, RefreshCw, SlidersHorizontal, Sparkles } from 'lucide-react'
import { Button } from '../../components/ui'
import { useLocale, useT } from '../../i18n'
import type { Proposal, Snapshot, Stage } from './protocol'
import { formatSuggestionValue, uniqueEvidenceIds, visibleQuestions } from './presentation'

export function SuggestionProposalView({ stage, snapshot, proposal, model, selected, disabled, onToggle, onRegenerate, regenerateDisabled }: {
  stage: Stage; snapshot: Snapshot; proposal: Proposal; model: string
  selected: readonly string[]; disabled: boolean; onToggle: (fieldId: string, checked: boolean) => void
  onRegenerate: () => void; regenerateDisabled: boolean
}) {
  // 界面文案统一走共享词典（uiT）；值格式化仍需 locale 判断「纳入/不纳入本轮」与单位。
  const { locale } = useLocale()
  const uiT = useT()
  const questions = visibleQuestions(proposal.questions)
  return <>
    <section className="config-suggestion-overview" aria-label={uiT('建议概览')}>
      <div className="config-suggestion-overview-heading"><Sparkles size={20} aria-hidden="true" /><h3>{uiT('建议概览')}</h3>
        <Button variant="default" icon={<RefreshCw size={14} aria-hidden="true" />} disabled={regenerateDisabled} onClick={onRegenerate}>{uiT('重新生成')}</Button>
      </div>
      <p>{proposal.summary}</p>
      <div className="config-suggestion-meta">{uiT('模型：')}{model}</div>
      <div className="config-suggestion-counts"><span>{uiT(`建议修改 {v1} 项`, { v1: proposal.changes.length })}</span><span>{uiT(`待确认 {v1} 项`, { v1: questions.length })}</span><span>{uiT(`已选 {v1} 项`, { v1: selected.length })}</span></div>
    </section>
    <section className="config-suggestion-changes" aria-label={uiT('建议修改')}>
      <h3 className="config-suggestion-section-heading"><SlidersHorizontal size={18} aria-hidden="true" />{uiT('建议修改')}</h3>
      {stage === 'req' ? <p className="config-suggestion-meta">{uiT('仅调整本轮测试范围，不修改判据和阈值。')}</p> : null}
      {!proposal.changes.length ? <div className="config-suggestion-state"><ListChecks size={24} aria-hidden="true" /><h3>{uiT('暂无可填入的修改建议')}</h3><p>{uiT('请查看建议概览和待确认事项，必要时补充依据后重新生成。')}</p></div> : null}
      {proposal.changes.map(change => {
        const field = snapshot.fields.find(item => item.id === change.field_id)!
        const FieldIcon = field.kind === 'selection' ? ListChecks : SlidersHorizontal
        return <article className="config-suggestion-change" key={field.id} data-selected={selected.includes(field.id)}>
          <div className="config-suggestion-change-header"><label><input type="checkbox" checked={selected.includes(field.id)} disabled={disabled} onChange={event => onToggle(field.id, event.target.checked)} /><FieldIcon size={17} aria-hidden="true" /><strong>{uiT(field.name)}</strong></label></div>
          <div className="config-suggestion-comparison"><div className="config-suggestion-value" data-side="before"><span>{uiT('当前值')}</span><strong>{formatSuggestionValue(field, change.before, locale)}</strong></div><ArrowRight size={18} aria-hidden="true" /><div className="config-suggestion-value" data-side="after"><span>{uiT('建议值')}</span><strong>{formatSuggestionValue(field, change.after, locale)}</strong></div></div>
          <div className="config-suggestion-reason"><strong>{uiT('修改理由')}</strong><p>{change.reason}</p></div>
          <div className="config-suggestion-evidence">{uniqueEvidenceIds(change.evidence_ids).map(id => {
            const item = snapshot.evidence.find(evidence => evidence.id === id)!
            const category = id.startsWith('field:') ? uiT('字段说明') : id.startsWith('criterion:') ? uiT('测试判据') : id.startsWith('experience:') ? uiT('经验记录') : uiT('依据')
            const Icon = id.startsWith('experience:') ? BookOpen : FileText
            return <details key={id}><summary><Icon size={14} aria-hidden="true" /><span>{category} · {uiT(item.title)}</span></summary><p>{item.text}</p></details>
          })}</div>
        </article>
      })}
    </section>
    {questions.length ? <section className="config-suggestion-questions" aria-label={uiT('待确认事项')}><h3 className="config-suggestion-section-heading"><CircleHelp size={18} aria-hidden="true" />{uiT('待确认事项')}</h3><ol>{questions.map((question, index) => <li key={index}>{question}</li>)}</ol></section> : null}
  </>
}
