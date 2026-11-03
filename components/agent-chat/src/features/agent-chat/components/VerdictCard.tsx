import type { Verdict } from '../types';

interface Props {
  verdict: Verdict;
  onOpenEvidence: (ids: string[]) => void;
  onDistill: (verdict: Verdict) => void;
}

export function VerdictCard({ verdict, onOpenEvidence, onDistill }: Props) {
  return (
    <div className="ac-card ac-verdict" data-pass={String(verdict.pass)}>
      <div className="ac-verdict__head">
        <span className="ac-verdict__title">{verdict.title}</span>
        <span className="ac-badge" data-pass={String(verdict.pass)}>
          {verdict.pass ? '合格' : '不合格'}
        </span>
      </div>
      <div className="ac-verdict__expr">判据　{verdict.expression}</div>
      <div className="ac-meas">
        {verdict.measurements.map((m) => (
          <span className="ac-meas__item" key={m.label}>
            <span className="ac-meas__k">{m.label}</span>
            <span className="ac-meas__v">
              {m.value}
              {m.unit ? <span className="ac-meas__u">{m.unit}</span> : null}
            </span>
          </span>
        ))}
      </div>
      <div className="ac-verdict__concl">{verdict.conclusion}</div>
      <div className="ac-verdict__foot">
        <button type="button" className="ac-btn" onClick={() => onOpenEvidence(verdict.evidenceIds)}>
          依据 ▸
        </button>
        <button type="button" className="ac-btn ac-btn--ghost" onClick={() => onDistill(verdict)}>
          沉淀为经验
        </button>
      </div>
    </div>
  );
}
