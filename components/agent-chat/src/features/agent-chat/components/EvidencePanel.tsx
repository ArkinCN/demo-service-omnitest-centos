import { EVIDENCE_KIND_LABEL, type EvidenceItem, type EvidenceKind } from '../types';

const ORDER: EvidenceKind[] = ['procedure', 'case', 'document'];

interface Props {
  items: EvidenceItem[];
  onClose: () => void;
}

export function EvidencePanel({ items, onClose }: Props) {
  return (
    <aside className="ac-drawer" aria-label="依据面板">
      <div className="ac-drawer__head">
        <span className="ac-drawer__title">依据</span>
        <span className="ac-group__count">共 {items.length} 条</span>
        <span className="ac-drawer__spacer" />
        <button type="button" className="ac-iconbtn" onClick={onClose}>
          关闭 ✕
        </button>
      </div>
      <div className="ac-drawer__body">
        {ORDER.map((kind) => {
          const group = items.filter((it) => it.kind === kind);
          return (
            <section className="ac-group" key={kind}>
              <div className="ac-group__head">
                <span className="ac-group__name">{EVIDENCE_KIND_LABEL[kind]}</span>
                <span className="ac-group__count">{group.length} 条</span>
              </div>
              {group.length === 0 ? (
                <div className="ac-empty">本次判定未命中该类依据</div>
              ) : (
                group.map((it) => (
                  <article className="ac-ev" key={it.id}>
                    <div className="ac-ev__title">{it.title}</div>
                    <div className="ac-ev__excerpt">{it.excerpt}</div>
                    <div className="ac-ev__meta">
                      <span>{it.source}</span>
                      <span>·</span>
                      <span>{it.locator}</span>
                      <span className="ac-ev__spacer" />
                      {it.href ? (
                        <a className="ac-link" href={it.href}>
                          查看原文
                        </a>
                      ) : (
                        <span className="ac-empty">原文未接入</span>
                      )}
                    </div>
                  </article>
                ))
              )}
            </section>
          );
        })}
      </div>
    </aside>
  );
}
