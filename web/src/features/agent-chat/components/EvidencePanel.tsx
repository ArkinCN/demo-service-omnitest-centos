import { useT } from '../../../i18n'
import { useNavigate } from 'react-router';
import { EVIDENCE_KIND_LABEL, type EvidenceItem, type EvidenceKind } from '../types';
import { useAppStore } from '../../../state/useAppStore';
import { useKnowledge } from '../../knowledge/data';

const ORDER: EvidenceKind[] = ['procedure', 'case', 'document'];

/**
 * 规范化文档名，用于把依据卡的来源与知识库条目对上。
 *
 * 两边的名字来自不同数据源（依据卡取检索语料的 doc_title，知识库取场景包
 * 的 title），标点与空格会有出入（如「FU-AM-FOC 方案调试手册」vs
 * 「FU-AM-FOC方案调试手册」）。只做保守的归一：去空白、去连接号与括号，
 * 不做同义词替换——宁可匹配不上（退回不可点），也不要张冠李戴跳到别的文档。
 */
function normDoc(s: string): string {
  return (s || '')
    .replace(/[\s\-_·・、，,。.：:()（）[\]【】]/g, '')
    .toLowerCase();
}

interface Props {
  items: EvidenceItem[];
  onClose: () => void;
}

export function EvidencePanel({ items, onClose }: Props) {
  const uiT = useT()

  const nav = useNavigate();
  // 知识库条目：用知识库自己的取数 hook（含缓存与订阅），不另存一份到 store，
  // 也不在这里单独 fetch——取数口径只能有一处。
  const { entries } = useKnowledge();

  /**
   * 依据卡 → 知识库页定位。
   *
   * 本地知识库的原文 PDF 未随交付包提供，没有可点的 href；但**条目本身在知识库里**。
   * 点这里跳到 /knowledge 并选中对应条目，人就能看到它的三轴取值、转化状态与源文件，
   * 比显示「原文未接入」（会被误读成「原文没检索到」）有用得多。
   * 匹配不上时返回 null，按钮退回不可点——不硬跳到一个空详情。
   */
  const locate = (it: EvidenceItem): (() => void) | null => {
    // 优先按来源名匹配；依据卡的 source 存的是源文件路径，title 才是文档名
    const key = normDoc(it.title || it.source);
    if (!key) return null;
    const hit = entries.find((e) => {
      const a = normDoc(e.title);
      return a && (a === key || key.includes(a) || a.includes(key));
    });
    if (!hit) return null;
    return () => {
      useAppStore.getState().setKbSelectedId(hit.id);
      nav('/knowledge');
    };
  };

  return (
    <aside className="ac-drawer" aria-label={uiT("依据面板")}>
      <div className="ac-drawer__head">
        <span className="ac-drawer__title">{uiT("依据")}</span>
        <span className="ac-group__count">{uiT("共 ")}{items.length} {uiT(" 条")}</span>
        <span className="ac-drawer__spacer" />
        <button type="button" className="ac-iconbtn" onClick={onClose}>
          {uiT("关闭 ✕")}</button>
      </div>
      <div className="ac-drawer__body">
        {ORDER.map((kind) => {
          const group = items.filter((it) => it.kind === kind);
          return (
            <section className="ac-group" key={kind}>
              <div className="ac-group__head">
                <span className="ac-group__name">{uiT(EVIDENCE_KIND_LABEL[kind])}</span>
                <span className="ac-group__count">{group.length} {uiT(" 条")}</span>
              </div>
              {group.length === 0 ? (
                <div className="ac-empty">{uiT("本次判定未命中该类依据")}</div>
              ) : (
                group.map((it) => {
                  const go = locate(it);
                  return (
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
                            {uiT("查看原文")}</a>
                        ) : go ? (
                          // 无 PDF 链接但知识库有这条：跳到知识库页并选中它
                          <button type="button" className="ac-link" onClick={go}>
                            {uiT("查看知识库条目")}</button>
                        ) : (
                          // 知识库里也没有（如经验条目）：如实说明，不假装能点
                          <span className="ac-empty">{uiT("原文未随包提供")}</span>
                        )}
                      </div>
                    </article>
                  );
                })
              )}
            </section>
          );
        })}
      </div>
    </aside>
  );
}
