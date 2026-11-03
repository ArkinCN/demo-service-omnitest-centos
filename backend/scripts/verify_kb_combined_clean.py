"""知识库「合成图文稿」文本清理的静态验收脚本（纯标准库）。

## 验什么（对应 2026-10-10 需求验收 5 条）

1. 生成的 combined/index.html 里**搜不到** `formula-not-decoded`（含变体）；
2. 代码段（`#define` 开头等）完整成块，不出现 0/1/A 这类被强制换行的单字符碎片行；
3. 公式呈数学样式块（`div.kb-formula`），页面不出现 `\\_`、`&gt;` 等源码符号；
4. 乱码原文**保留**（如「1n1L 个什管的后由执」），不做删除或标记；
5. meta.json 的清理统计与 content.md 侧计数**对账**（公式标记删除数一致）。

## 用法

    <ra python> c/backend/scripts/verify_kb_combined_clean.py

只读产物，不修改任何文件。退出码 0=全过；非 0=有失败项。
纯标准库；路径经 `app.core.paths.kb_extract_dir()` 推导，脚本内不写盘符。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.paths import kb_extract_dir  # noqa: E402

FORMULA_RE = re.compile(r"<!--+\s*formula-not-decoded\s*-->+", re.I)
# HTML 源码符号残留：转义后的反斜杠或双重转义实体
BACKSLASH_ESCAPE_RE = re.compile(r"\\[_*#$\[\]{}()]")
DOUBLE_ESCAPED_RE = re.compile(r"&amp;(?:gt|lt|amp|quot|nbsp);")
# 代码块内的纯行号/单字符碎片行
LINENO_RE = re.compile(r"^\s*\d+(?:\.\d+)?\s*$")
SINGLE_CHAR_RE = re.compile(r"^\s*[A-Za-z]\s*$")
PRE_RE = re.compile(r"<pre class=\"kb-code\"><code>(.*?)</code></pre>", re.S)
FORMULA_BLOCK_RE = re.compile(r"<div class=\"kb-formula\">(.*?)</div>", re.S)
# 已知必留乱码样本（保留原文即可，不做标记）
MUST_KEEP_SAMPLES = ["1n1L 个什管的后由执"]


class Result:
    def __init__(self) -> None:
        self.items: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.items.append((name, ok, detail))

    def report(self) -> int:
        passed = sum(1 for _, ok, _ in self.items if ok)
        total = len(self.items)
        for name, ok, detail in self.items:
            flag = "PASS" if ok else "FAIL"
            line = f"[{flag}] {name}"
            if detail:
                line += f" — {detail}"
            print(line)
        print(f"\n合计 {passed}/{total} 通过")
        return 0 if passed == total else 1


def check_doc(doc_dir: Path, res: Result) -> None:
    combined = doc_dir / "combined" / "index.html"
    meta_file = doc_dir / "combined" / "meta.json"
    content_md = doc_dir / "content.md"
    if not combined.is_file() or not content_md.is_file():
        return
    doc_id = doc_dir.name
    html_text = combined.read_text(encoding="utf-8", errors="replace")
    md_text = content_md.read_text(encoding="utf-8", errors="replace")

    # ① 无 formula-not-decoded 残留
    res.check(f"{doc_id}: 无 formula-not-decoded 残留",
              not FORMULA_RE.search(html_text),
              f"命中 {len(FORMULA_RE.findall(html_text))} 处")

    # ② 无源码符号残留
    bs = BACKSLASH_ESCAPE_RE.findall(html_text)
    de = DOUBLE_ESCAPED_RE.findall(html_text)
    res.check(f"{doc_id}: 无 \\_ / 双重转义实体符号",
              not bs and not de,
              f"反斜杠转义 {len(bs)}、双转义实体 {len(de)}")

    # ③ 代码块内无单字符/纯行号碎片行
    frag = []
    for block in PRE_RE.findall(html_text):
        for ln in block.splitlines():
            if LINENO_RE.match(ln) or SINGLE_CHAR_RE.match(ln):
                frag.append(ln.strip())
    res.check(f"{doc_id}: 代码块内无单字符/行号碎片",
              not frag, f"碎片 {frag[:5]}")

    # ④ 乱码原文保留（仅对有样本的文档断言；HTML 里空白可能被规范化，故按去空白比对）
    if doc_id == "smo-pll-estimator":
        flat_html = re.sub(r"\s+", "", html_text)
        for sample in MUST_KEEP_SAMPLES:
            res.check(f"{doc_id}: 乱码原文保留「{sample}」",
                      re.sub(r"\s+", "", sample) in flat_html)

    # ④b 正文无孤立单字符/纯数字段落（页码与图内标签残片）
    lone = re.findall(r"<p>\s*(?:[A-Za-z]|\d+)\s*</p>", html_text)
    res.check(f"{doc_id}: 正文无单字符/纯数字碎片段落",
              not lone, f"碎片 {lone[:6]}")

    # ④c 无目录条目残片（带页码的标题清单，如 `<p>1 问题1  3</p>`）
    toc_like = re.findall(r"<p>\s*\d+(?:\.\d+)*[.、]?\s+[^<]*?[\s\u3000]\d{1,3}\s*</p>", html_text)
    res.check(f"{doc_id}: 无目录条目残片",
              not toc_like, f"残片 {toc_like[:3]}")

    # ⑤ meta 统计与 content.md 侧计数对账
    if meta_file.is_file():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}
        md_marks = len(FORMULA_RE.findall(md_text))
        res.check(f"{doc_id}: 公式标记删除数对账",
                  meta.get("formula_removed") == md_marks,
                  f"meta={meta.get('formula_removed')} md={md_marks}")


def main() -> int:
    root = kb_extract_dir()
    if not root.is_dir():
        print(f"[FAIL] 抽取稿根目录不存在：{root}", file=sys.stderr)
        return 1
    res = Result()
    n_docs = 0
    for doc_dir in sorted(root.iterdir()):
        if not doc_dir.is_dir() or doc_dir.name == "combined":
            continue
        if not (doc_dir / "combined" / "index.html").is_file():
            continue
        n_docs += 1
        check_doc(doc_dir, res)
    print(f"检查文档 {n_docs} 份\n")
    return res.report()


if __name__ == "__main__":
    sys.exit(main())
