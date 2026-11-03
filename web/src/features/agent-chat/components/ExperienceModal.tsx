import { useT } from '../../../i18n'
import { useState } from 'react';
import type { ExperienceDraft } from '../types';

interface Props {
  draft: ExperienceDraft;
  onCancel: () => void;
  onSubmit: (d: ExperienceDraft) => void;
}

const FIELDS: { key: keyof Omit<ExperienceDraft, 'tags'>; label: string; area?: boolean }[] = [
  { key: 'title', label: '标题' },
  { key: 'phenomenon', label: '现象', area: true },
  { key: 'cause', label: '原因', area: true },
  { key: 'action', label: '动作', area: true },
  { key: 'result', label: '结果', area: true },
];

export function ExperienceModal({ draft, onCancel, onSubmit }: Props) {
  const uiT = useT()

  const [form, setForm] = useState<ExperienceDraft>(draft);
  const [tagInput, setTagInput] = useState(draft.tags.join('、'));

  return (
    <div className="ac-modal-mask" role="dialog" aria-modal="true" aria-label={uiT("沉淀为经验")}>
      <div className="ac-modal">
        <div className="ac-modal__head">
          <span className="ac-modal__title">{uiT("沉淀为经验")}</span>
        </div>
        <div className="ac-modal__body">
          {FIELDS.map((f) => (
            <div className="ac-form-row" key={f.key}>
              <label htmlFor={`ac-exp-${f.key}`}>{uiT(f.label)}</label>
              {f.area ? (
                <textarea
                  id={`ac-exp-${f.key}`}
                  className="ac-area"
                  value={form[f.key]}
                  onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                />
              ) : (
                <input
                  id={`ac-exp-${f.key}`}
                  className="ac-input"
                  value={form[f.key]}
                  onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                />
              )}
            </div>
          ))}
          <div className="ac-form-row">
            <label htmlFor="ac-exp-tags">{uiT("标签")}</label>
            <div>
              <input
                id="ac-exp-tags"
                className="ac-input"
                value={tagInput}
                placeholder={uiT("以顿号或逗号分隔")}
                onChange={(e) => setTagInput(e.target.value)}
              />
              <div className="ac-tags">
                {tagInput
                  .split(/[、,，\s]+/)
                  .filter(Boolean)
                  .map((t) => (
                    <span className="ac-tag" key={t}>
                      {t}
                    </span>
                  ))}
              </div>
            </div>
          </div>
        </div>
        <div className="ac-modal__foot">
          <button type="button" className="ac-btn ac-btn--ghost" onClick={onCancel}>
            {uiT("取消")}</button>
          <button
            type="button"
            className="ac-btn ac-btn--solid"
            onClick={() =>
              onSubmit({ ...form, tags: tagInput.split(/[、,，\s]+/).filter(Boolean) })
            }
          >
            {uiT("存入经验库")}</button>
        </div>
      </div>
    </div>
  );
}
