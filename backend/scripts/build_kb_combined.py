"""知识库「合成图文稿」构建脚本。

## 解决什么问题

一份知识库文档在数据侧是**零散存放**的：
    <doc_id>/content.md      正文（docling 抽的 Markdown，图位置留 `<!-- image -->` 占位）
    <doc_id>/figures/*.png   插图（PyMuPDF 按页抽，命名 p<页码>_x<序号>）
    <doc_id>/chunks.jsonl    检索切片
    <doc_id>/entities.json   抽出的参数
    <doc_id>/source.json     元信息

前端弹窗要「图文并茂」地看，就得把正文和插图**合成一份文件**。本脚本在每份文档
目录下新建 `combined/`：
    combined/index.html   正文 + 按序插入的插图（干净、可读）
    combined/meta.json    合成元信息（对位统计，供追溯；页面不显示）

## 图与文对位规则（用户 2026-09-29 定稿）

`content.md` 里的 `<!-- image -->` 占位符**按出现顺序**与 `figures/`（按 `p页码_x序号`
排序）**一一对应**：
  - 第 N 个占位 → 第 N 张可用图（若是浏览器能渲染的格式：png/jpg/jpeg/gif/webp）；
  - **配不上图的占位符直接删除**（不留「图略」之类字样，保证文章干净、不影响阅读）；
  - **多余的图不追加**（保持文档干净）；
  - 只处理 `<!-- image -->` 这一种占位；其它 HTML 注释（docling 的结构标记）**原样保留**；
  - 非浏览器可渲染格式（如 `.emf`）视为「配不上」，对应占位删除。

## 文本清理规则（用户 2026-10-10 定稿）

目标：让合成稿从「源码与文字的混合体」变成「给人读的」文档。清理**只在内存行列表上做**，
`content.md` 原稿只读、不动；产出即重跑即可复现（幂等）。规则按三阶段：

1. **行级规范化**
   - 删除公式解析失败占位 `<!--- formula-not-decoded -->`（含连字符/空白/大小写变体）：
     整行是它则整行删除，行内出现则删该子串；它是**报错信息**，按要求不留任何痕迹。
   - 反转义 Markdown 反斜杠转义：`\_`→`_`、`\*`→`*`、`\#`→`#`、`\$`→`$`、`\[`/`\]` 等，
     消除页面上的 `\_` 字面量。
   - `html.unescape` 解码源文本里的 HTML 实体（`&gt;`→`>`、`&amp;`→`&`），输出层再统一
     `html.escape`，避免 `&gt;` 在页面上二次显形。
2. **结构识别**
   - **代码簇**：以 `#define`/`_Q15(`/`_Q12(`/`_Q11(`/`_Q8(` 等为种子，向邻近行扩展（可跨空行），
     收纳代码型行与行号列（`0`/`1`/`2`/`3`…）、单字符碎片；遇图片占位、标题、表格、围栏代码块边界停止。
   - **公式块**：含数学信号（`=`、`·`、`×`、`∆`、`θ`、`ω`、`π`、`∫`、`Σ`、`_Q15(` 等）的行，
     去掉纯数字/单字符噪声行后，若仍保留 ≥1 行数学内容，则收成一块。
3. **重写渲染**
   - 代码簇：剔除纯行号/单字符噪声行；`#define 宏名` 与紧随的值行合并为完整语句（形如
     `#define OBS_FBASE  BASE_FREQ*TPWM_VALUE*32768`）；`//` 注释并入行尾；同一行内多个 `#define`
     按边界拆行；宏名空格粘连（`OBS KLPF`→`OBS_KLPF`）**仅当**归一结果命中
     `customer-h-fu6832/params.json` 的已知宏名白名单时才归一，未命中一律原文保留（不编造）。
     输出为 `<pre class="kb-code">`，保证代码整体成块、不被拆散。
   - 公式块：输出为 `<div class="kb-formula">`（居中、衬线、留白），页面不再出现散乱残片。
   - 孤立单字符/纯数字行（页码、图内标签残片，如 `S`/`A`/`Q`/`8`）不进入正文——
     它们正是「0、1、A 被强制换行的单字符碎片」；原文仍在 content.md，可追溯。
   - 无法修复的残片留在代码块/公式块内**原文保留**；乱码按普通正文原样保留、**不做任何标记**
     （用户拍板：观感优先）。

## 诚实边界

⚠️ 这是**抽取稿重建成稿**，不是客户原件 PDF。且**插图可能不全**：转换阶段
`kb-pipeline/scripts/01_convert_docs.py` 有 `MAX_FIGURES=20` 上限，每份文档最多抽 20 张
——超出部分根本没被抽出。故合成稿只保证「把现有产物合成、能配上就配上、配不上就清干净」，
**不假装图全**（meta.json 里的 dropped/unused 字段如实记录差额）。

## 图片引用方式

HTML 里图片 `src` 用**后端端点 URL**（`/api/kb/documents/<doc_id>/figure?name=...`）而非
相对路径——因为前端用 iframe `srcdoc` 渲染时相对路径没有基准 URL，绝对路径才可解析。

## 用法

    <ra python> c/backend/scripts/build_kb_combined.py [--only <doc_id>]

纯标准库；路径经 `app.core.paths.kb_extract_dir()` 推导，脚本内不写盘符。
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# 让脚本能 import 到 app.core.paths（c/backend 加入 sys.path）
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.paths import kb_extract_dir  # noqa: E402

# 浏览器能直接渲染的图片格式；其余（如 .emf）视为配不上
WEB_IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
# 占位符：只认 docling 的 `<!-- image -->`（允许空白变体）
PLACEHOLDER_RE = re.compile(r"<!--\s*image\s*-->", re.I)
# 图名排序钥匙：p<页码>_x<序号>
FIG_NAME_RE = re.compile(r"^p(\d+)_x(\d+)", re.I)


def _fig_sort_key(name: str) -> tuple[int, int, str]:
    """图片排序：p页码_x序号 优先（按数值），非该命名的排最后按名字典序。"""
    m = FIG_NAME_RE.match(name)
    if m:
        return (0, int(m.group(1)), f"{int(m.group(2)):08d}")
    return (1, 0, name.lower())


def _usable_figures(fig_dir: Path) -> list[str]:
    """可用插图文件名（按对位顺序排序；过滤非浏览器可渲染格式）。"""
    if not fig_dir.is_dir():
        return []
    names = [
        p.name
        for p in fig_dir.iterdir()
        if p.is_file() and p.suffix.lower() in WEB_IMG_EXT
    ]
    names.sort(key=_fig_sort_key)
    return names


def _load_known_macros() -> set[str]:
    """已知宏名白名单（两处证据，不编造）。

    1. `customer-h-fu6832/params.json` 的 `name` 字段（Customer.h 全部宏名）；
    2. 全部 `content.md` 里以 `#define NAME` 形式出现过的宏名（文档自身写的宏名）。

    仅用于「宏名空格粘连归一」：`OBS KLPF` → `OBS_KLPF` 只有当归一结果命中白名单时才做，
    否则一律原文保留（不编造）。读不到证据时返回空集，此时不做任何归一。
    """
    names: set[str] = set()
    root = kb_extract_dir()
    # 证据 1：params.json
    p = root / "customer-h-fu6832" / "params.json"
    if p.is_file():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = None

        def walk(node) -> None:
            if isinstance(node, dict):
                name = node.get("name")
                if isinstance(name, str) and name:
                    names.add(name)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        if raw is not None:
            walk(raw)
    # 证据 2：各 content.md 里出现过的宏名——`#define NAME` 与正文中的大写宏字面量
    # （形如 `ABC_DEF`，至少含一个下划线、2 个以上大写字母；这是文档自身写出的名字，非推断）。
    if root.is_dir():
        define_re = re.compile(r"#\s*define\s+([A-Za-z_][A-Za-z0-9_]*)")
        # ⚠️ 不能用 `\b`：Python 的 `\b` 视中文为单词字符，`用宏定义OBS_KLPF表示` 这类
        # 中英相邻处判定不出边界，宏名会整片漏掉（2026-10-10 实测）。改用 ASCII 专用环视。
        macro_lit_re = re.compile(
            r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)(?![A-Za-z0-9_])")
        for md in root.glob("*/content.md"):
            try:
                text = md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            # ⚠️ content.md 里的宏名多写成转义形态（`OBS\_KLPF`），必须先反转义再抽取，
            # 否则正则匹配不到，白名单会漏（2026-10-10 实测：归一因此全部失效）。
            text = MD_ESCAPE_RE.sub(r"\1", text)
            for m in define_re.finditer(text):
                names.add(m.group(1))
            for m in macro_lit_re.finditer(text):
                names.add(m.group(1))
    return names


# 公式解析失败占位：`<!--- formula-not-decoded -->`，容错连字符数量/空白/大小写。
FORMULA_RE = re.compile(r"<!--+\s*formula-not-decoded\s*-->+", re.I)
# Markdown 反斜杠转义：\ 后跟 ASCII 标点（CommonMark 可转义字符集）。
MD_ESCAPE_RE = re.compile(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])")
# 双反斜杠转义（`\\_` → `\_`），docling 偶发再转义一层。
DOUBLE_BACKSLASH_RE = re.compile(r"\\\\([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])")
# 代码种子行：以 #define / _Qn( 打头（允许前导空白）。
CODE_SEED_RE = re.compile(r"^\s*(#\s*define|_[Qq]\d+\s*\()")
# 纯行号行：仅由数字（可含小数点）组成。
LINENO_RE = re.compile(r"^\s*\d+(?:\.\d+)?\s*$")
# 单字符噪声行：单个 ASCII 字母/符号（如 A、S、Q、中 视为正文例外，不在此列）。
SINGLE_CHAR_RE = re.compile(r"^\s*[A-Za-z]\s*$")
# 标题行。
HEADING_RE = re.compile(r"^#{1,6}\s+\S")
# 表格行。
TABLE_ROW_RE = re.compile(r"^\s*\|")
# 围栏代码块。
FENCE_RE = re.compile(r"^\s*```")
# 公式信号：出现其一即视为数学内容。
FORMULA_SIGN_CHARS = set("=·×∆θωπ∫Σ≈≤≥∑∞∂√±→↓−*(){}[]^_")
FORMULA_SIGN_TOKENS = ("_Q15(", "_Q12(", "_Q11(", "_Q8(", "_Q7(")
# 中文句子特征（含连续 2 个及以上汉字）——含此特征的行不并入公式块。
CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
# 公式编号行（如 `(2-5)`、`（1-5）`）——单独成行时不当作公式内容，交给普通段落。
FORMULA_NO_RE = re.compile(r"^[（(]\s*\d+\s*[-–—]\s*\d+\s*[）)]$")
# 短噪声碎片（`(UE`、`UUE`、`P //M`、`BP  //` 这类提取残渣）：全 ASCII、不含数字与中文、
# 长度很短 → 既不是公式也不是代码；贴着代码清单出现时原样并入代码块（保留原文、不标记）。
BRACKET_NOISE_RE = re.compile(r"^[A-Za-z\s/\\()\[\]{}<>|._:,\-]{1,12}$")
# 空格粘连的宏名对（`BASE FREQ` → `BASE_FREQ`），仅按白名单还原。
PAIR_GLUE_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9]*)[ \t]+([A-Z][A-Z0-9]*)(?![A-Za-z0-9_])")
# 宏名规整：仅用于白名单命中判断（去空白/下划线/大小写）。
_MACRO_NORM_RE = re.compile(r"[\s_]+")
# 页脚页码行（`2 / 55`、`3/55`——当前页/总页数），无正文信息 → 丢弃。
PAGE_FOOTER_RE = re.compile(r"^\**\s*\d{1,4}\s*/\s*\d{1,4}\s*\**$")
# 目录标题行（`目  录` / `目录` / `Contents`）：可为 `## 目录` 标题、`**目录**`、或
# `**目录\t2**`（目录标题本身也带页码）。允许前置 `#`/`*` 与页码。
TOC_HEAD_RE = re.compile(
    r"^[#*\s]*\**(目\s*录|Contents)\**[#*\s]*(?:[\s\u3000\t]+\d{1,3})?\**\s*$", re.I)
# 目录条目行（带页码的标题清单，如 `**1 问题1\t3**` / `1 概述  3` / `1.2 速度环\t5`）：
# 行首编号 + 标题文字 + 空白 + 由 1~3 位数字组成的页码，且**不含句末标点**。
TOC_ENTRY_RE = re.compile(
    r"^[#*\s]*\d+(?:\.\d+)*[.、]?\s+\S.*?[\s\u3000\t]+\d{1,3}\**\s*$")


def _is_toc_entry(line: str) -> bool:
    """目录条目行判定（保守：需行尾是个小页码数字，且无句末标点）。"""
    s = line.strip()
    if not s:
        return False
    if not TOC_ENTRY_RE.match(s):
        return False
    return not re.search(r"[。！？；：,.!?;:]$", s.strip("*").strip())


def _clean_inline(text: str) -> str:
    """行级规范化（不转义、不判结构）：删公式占位、反转义、解 HTML 实体。"""
    text = FORMULA_RE.sub("", text)
    # 双反斜杠转义（`\\_`、`\\*`——docling 对反斜杠再转义一层）先收敛为单反斜杠转义，
    # 再由 MD_ESCAPE_RE 去掉（否则页面上会露出 `\\_` 字面量）。
    text = DOUBLE_BACKSLASH_RE.sub(r"\\\1", text)
    text = MD_ESCAPE_RE.sub(r"\1", text)
    # 反复解实体，消除双重转义（`&amp;` 先解成 `&` 后，`&amp;=` 才能正确显示为 `&=`）。
    # 输出层仍统一 html.escape 一次（单个 `&` 会变回 `&amp;`，页面上显示为 `&`）。
    prev = None
    while prev != text:
        prev = text
        text = html.unescape(text)
    return text


def _strip_math_delims(text: str) -> str:
    """剥离 LaTeX 数学定界符 `$$...$$` / `$...$`（不引 KaTeX，只留干净文本）。"""
    s = text.strip()
    if s.startswith("$$") and s.endswith("$$") and len(s) > 4:
        return s[2:-2].strip()
    if s.startswith("$") and s.endswith("$") and len(s) > 2:
        return s[1:-1].strip()
    return text


def _is_code_like(line: str) -> bool:
    """代码型行：含 C 语法特征或已反转义后的宏名/函数调用。"""
    s = line.strip()
    if not s:
        return False
    if CODE_SEED_RE.match(s):
        return True
    if s.startswith("//") or s.startswith("*"):
        return True
    if re.search(r"[{};]", s):
        return True
    if re.search(r"_Q\d+", s) or re.search(r"_Q\d+\s*\(", s):
        return True
    # 形如 `A*B*C` / `X/Y` / 含两个以上大写宏词与运算符的行。
    if re.search(r"[A-Za-z_]{2,}\s*[*+\-/]\s*[A-Za-z0-9_(]", s):
        return True
    return False


def _looks_like_formula(line: str) -> bool:
    """公式候选：含数学信号，且不是纯代码种子行、不含中文句子特征。"""
    s = line.strip()
    if not s:
        return False
    if CJK_RUN_RE.search(s):
        return False
    if CODE_SEED_RE.match(s):
        return False
    if FORMULA_NO_RE.match(s):
        return False
    if BRACKET_NOISE_RE.match(s):
        return False
    if any(tok in s for tok in FORMULA_SIGN_TOKENS):
        return True
    if not any(ch in FORMULA_SIGN_CHARS for ch in s):
        return False
    # 至少含一个变量/符号特征，避免「1+2」这类纯数字算式误判——但纯数字算式本就是公式，故保留。
    return True


def _normalize_macro_name(name: str, known_macros: set[str]) -> str:
    """宏名空格粘连归一：仅当归一结果命中白名单才归一，否则原文返回。"""
    cand = re.sub(r"\s+", "_", name.strip())
    for macro in known_macros:
        if _MACRO_NORM_RE.sub("", macro).lower() == _MACRO_NORM_RE.sub("", cand).lower():
            return macro
    return name.strip()


def _merge_define(lines: list[str], known_macros: set[str]) -> list[str]:
    """把代码簇内「#define 宏名」与其后紧随的值/表达式行合并为完整语句。

    规则：
      - 一行里出现多个 `#define` 时按边界拆行（`#define A ... #define B ...`）；
      - `#define NAME` 独占一行且下一行是值/表达式 → 合并为 `#define NAME 值`；
      - `//` 注释行并入前一条语句行尾（若前一行已含 `//` 则另起注释行）。
    """
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        s = raw.strip()
        if not s:
            i += 1
            continue
        # 一行多个 #define：按边界拆开
        if s.count("#define") + s.count("# define") > 1:
            parts = re.split(r"(?=#\s*define\s)", s)
            for part in parts:
                if part.strip():
                    out.append(part.strip())
            i += 1
            continue
        # 注释行：并入前一行行尾
        if s.startswith("//"):
            if out:
                out[-1] = f"{out[-1]}  {s}"
            else:
                out.append(s)
            i += 1
            continue
        # `#define NAME` 独占一行，且下一非空行是值 → 合并
        # 宏名允许最多 4 段空格分隔（`OBSW KP GAIN` 这类粘连），是否还原成 `_` 连接
        # 仍由白名单决定（无据不改）。
        m = re.match(
            r"^#\s*define\s+([A-Za-z_][A-Za-z0-9_]*(?:\s+[A-Za-z_][A-Za-z0-9_]*){0,3})\s*$", s)
        if m and i + 1 < n:
            nxt = lines[i + 1].strip()
            # 下一行必须是「像值的东西」：排除宏定义行、注释、行号/单字符与短噪声碎片
            # （否则 `#define OBS_KLPF` 会把噪声 `(UE` 当成值拼进去，2026-10-10 实测）。
            if nxt and not nxt.startswith("#") and not nxt.startswith("//") and not LINENO_RE.match(nxt) \
                    and not SINGLE_CHAR_RE.match(nxt) and not BRACKET_NOISE_RE.match(nxt):
                name = _normalize_macro_name(m.group(1), known_macros)
                out.append(f"#define {name}  {nxt}")
                i += 2
                continue
        # 裸 `#define NAME`（无值行可并，如文档里的半截清单）→ 至少把宏名归一
        if m:
            out.append(f"#define {_normalize_macro_name(m.group(1), known_macros)}")
            i += 1
            continue
        out.append(s)
        i += 1
    return out


def _extract_code_cluster(lines: list[str], start: int) -> tuple[list[str], int]:
    """从 start 行（代码种子）向后扩展，收纳代码型行 / 行号 / 单字符碎片。

    遇图片占位、标题、表格、围栏代码块、中文长句正文则停止。返回 (簇行, 结束下标)。
    """
    cluster: list[str] = []
    i = start
    n = len(lines)
    while i < n:
        raw = lines[i]
        s = raw.strip()
        if not s:
            # 允许跨空行继续（向前看：下一个非空行仍是代码型/碎片行才算同簇）
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n and (_is_code_like(lines[j]) or LINENO_RE.match(lines[j].strip())
                          or SINGLE_CHAR_RE.match(lines[j].strip())
                          or BRACKET_NOISE_RE.match(lines[j].strip())):
                i += 1
                continue
            break
        if PLACEHOLDER_RE.fullmatch(s) or HEADING_RE.match(s) or TABLE_ROW_RE.match(s) or FENCE_RE.match(s):
            break
        if _is_code_like(s) or LINENO_RE.match(s) or SINGLE_CHAR_RE.match(s):
            cluster.append(s)
            i += 1
            continue
        # 短噪声碎片：只有「其后仍跟着代码内容」时才并入（避免把块尾的孤立噪声吞进来）
        if BRACKET_NOISE_RE.match(s):
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n and (_is_code_like(lines[j]) or LINENO_RE.match(lines[j].strip())
                          or SINGLE_CHAR_RE.match(lines[j].strip())
                          or BRACKET_NOISE_RE.match(lines[j].strip())):
                cluster.append(s)
                i += 1
                continue
        break
    return cluster, i


def _reglue_macro_pairs(text: str, known_macros: set[str]) -> str:
    """还原代码里空格粘连的宏名对（`BASE FREQ`→`BASE_FREQ`、`TPWM VALUE`→`TPWM_VALUE`）。

    仅当 `A_B` 命中白名单时才替换，未命中原文保留（不编造）。只在代码簇内调用。
    """
    def repl(m: re.Match) -> str:
        joined = f"{m.group(1)}_{m.group(2)}"
        return joined if joined in known_macros else m.group(0)

    return PAIR_GLUE_RE.sub(repl, text)


def _clean_code_cluster(cluster: list[str], known_macros: set[str]) -> list[str]:
    """剔除纯行号/单字符噪声行、还原粘连宏名、合并 #define 语句。

    短噪声碎片（`(UE`/`UUE`/`P //M` 等）**原样保留在代码块内**：它们本就来自原文档的
    代码清单区，留在块内既保住「代码区整体」，又满足「乱码保留原文、不加标记」。
    """
    kept = [ln for ln in cluster
            if not LINENO_RE.match(ln.strip()) and not SINGLE_CHAR_RE.match(ln.strip())]
    kept = [_reglue_macro_pairs(ln, known_macros) for ln in kept]
    return _merge_define(kept, known_macros)


def scan_rows(md: str) -> tuple[list[tuple[str, object]], dict]:
    """把清理后的 Markdown 行扫成「渲染行」序列。

    返回 (rows, stats)：
      rows 元素为 (kind, payload)：
        ("raw", str)          —— 普通行（已规范化），交给下游原有转换逻辑；
        ("placeholder", None) —— 图片占位行（原对位逻辑照旧处理）；
        ("code", list[str])   —— 代码簇（整体成块渲染）；
        ("formula", list[str])—— 公式块（居中衬线渲染）。
      stats：清理审计计数（formula_removed / code_blocks / formula_blocks）。
    """
    known_macros = _load_known_macros()
    raw_lines = md.splitlines()
    cleaned = [_clean_inline(ln) for ln in raw_lines]
    stats = {
        "formula_removed": sum(1 for ln in raw_lines if FORMULA_RE.search(ln)),
        "code_blocks": 0,
        "formula_blocks": 0,
        "fragments_dropped": 0,
        "toc_dropped": 0,
    }
    rows: list[tuple[str, object]] = []
    i = 0
    n = len(cleaned)
    while i < n:
        s = cleaned[i].strip()
        # 空行
        if not s:
            rows.append(("raw", ""))
            i += 1
            continue
        # 图片占位（原对位逻辑；必须原样保留，不得吞并）
        if PLACEHOLDER_RE.fullmatch(s):
            rows.append(("placeholder", None))
            i += 1
            continue
        # 围栏代码块：整体交给下游按 <pre> 渲染（属于「原本就成块」的代码，不拆散）
        if FENCE_RE.match(s):
            rows.append(("raw", cleaned[i]))
            i += 1
            continue
        # 页脚页码行（`2 / 55`）：无正文信息 → 丢弃（原文仍在 content.md）。
        if PAGE_FOOTER_RE.match(s):
            stats["toc_dropped"] += 1
            i += 1
            continue
        # 目录区块：`目 录` 标题 + 带页码的条目标题清单（`**1 问题1  3**` 之类）——
        # 对正文无信息量、混进正文影响观感 → 整块丢弃（原文仍在 content.md，可追溯）。
        if TOC_HEAD_RE.match(s):
            stats["toc_dropped"] += 1
            i += 1
            while i < n:
                t = cleaned[i].strip()
                if not t:
                    i += 1
                    continue
                if _is_toc_entry(t) or HEADING_RE.match(t):
                    stats["toc_dropped"] += 1
                    i += 1
                    continue
                break
            continue
        if _is_toc_entry(s) and i + 1 < n and _is_toc_entry(cleaned[i + 1].strip()):
            # 连续目录条目（首页目录标题本身可能已被抽丢）→ 整段丢弃
            while i < n and _is_toc_entry(cleaned[i].strip()):
                stats["toc_dropped"] += 1
                i += 1
            continue
        # 标题/表格：原样交给下游
        if HEADING_RE.match(s) or TABLE_ROW_RE.match(s):
            rows.append(("raw", cleaned[i]))
            i += 1
            continue
        # 代码簇
        if CODE_SEED_RE.match(s):
            cluster, end = _extract_code_cluster(cleaned, i)
            fixed = _clean_code_cluster(cluster, known_macros)
            if fixed:
                rows.append(("code", fixed))
                stats["code_blocks"] += 1
            i = end
            continue
        # 行号/单字符碎片「先导」串：本行是这类碎片、其后（可跨空行与连续碎片）紧跟代码种子
        # → 整串碎片丢弃，从种子处按代码簇渲染（否则会散落成 `<p>0</p>`、`<p>A</p>`）。
        if LINENO_RE.match(s) or SINGLE_CHAR_RE.match(s):
            k = i
            while k < n:
                t = cleaned[k].strip()
                if not t or LINENO_RE.match(t) or SINGLE_CHAR_RE.match(t):
                    k += 1
                    continue
                break
            if k < n and CODE_SEED_RE.match(cleaned[k].strip()):
                cluster, end = _extract_code_cluster(cleaned, k)
                fixed = _clean_code_cluster(cluster, known_macros)
                if fixed:
                    rows.append(("code", fixed))
                    stats["code_blocks"] += 1
                i = end
                continue
            # 不与代码相邻的孤立行号/单字符行 = 页码或图内标签残片 → 不进入正文
            # （原文仍在 content.md，可追溯；这里只影响阅读版排版）
            rows_skip_start = i
            while i < n:
                t = cleaned[i].strip()
                if not t:
                    i += 1
                    continue
                if LINENO_RE.match(t) or SINGLE_CHAR_RE.match(t):
                    stats["fragments_dropped"] += 1
                    i += 1
                    continue
                break
            if i == rows_skip_start:
                i += 1
            continue
        # 公式块：连续探测（允许中间夹空行/噪声行）
        if _looks_like_formula(cleaned[i]):
            block: list[str] = []
            j = i
            while j < n:
                t = cleaned[j].strip()
                if not t:
                    # 向前看：下一个非空行是否仍是公式候选
                    k = j + 1
                    while k < n and not cleaned[k].strip():
                        k += 1
                    if k < n and _looks_like_formula(cleaned[k]):
                        j += 1
                        continue
                    break
                if PLACEHOLDER_RE.fullmatch(t) or HEADING_RE.match(t) or FENCE_RE.match(t):
                    break
                if _looks_like_formula(cleaned[j]) or LINENO_RE.match(t) or SINGLE_CHAR_RE.match(t):
                    if not LINENO_RE.match(t) and not SINGLE_CHAR_RE.match(t):
                        block.append(_strip_math_delims(cleaned[j].strip()))
                    j += 1
                    continue
                break
            if block:
                rows.append(("formula", block))
                stats["formula_blocks"] += 1
            i = j
            continue
        # 普通行
        rows.append(("raw", cleaned[i]))
        i += 1
    return rows, stats


def _md_to_html_body(md: str, doc_id: str, figures: list[str]) -> tuple[str, dict]:
    """把 Markdown 正文转成干净 HTML：占位符按序换成 <img>，配不上的占位删除。

    ⚠️ 这是**轻量转换**，不引库：只处理合成稿需要的几样（标题/段落/表格/列表/代码/图片占位）。
    正文来自 content.md（受控数据），仍做 HTML 转义，避免正文里的 `<` 破坏结构。
    """
    used = 0
    dropped = 0
    out: list[str] = []

    def render_placeholder() -> str:
        nonlocal used, dropped
        if used < len(figures):
            name = figures[used]
            used += 1
            url = f"/api/kb/documents/{doc_id}/figure?name={html.escape(name, quote=True)}"
            return f'<figure class="kb-fig"><img src="{url}" alt="插图 {used}" loading="lazy"></figure>'
        dropped += 1
        return ""  # 配不上图 → 占位直接删除

    # 先过清理管线（删公式占位、修转义实体、重组代码簇、识别公式块），再逐行渲染。
    # ⚠️ placeholder 行必须还原成 `<!-- image -->` 文本交回下游原有对位逻辑——
    # 若映射成空串，占位会被吞掉（图片全部失配、figure 计数归零，2026-10-10 实测踩过）。
    rows, clean_stats = scan_rows(md)
    lines: list[str] = []
    for kind, payload in rows:
        if kind == "raw":
            lines.append(payload)  # type: ignore[arg-type]
        elif kind == "placeholder":
            lines.append("<!-- image -->")
        else:
            lines.append("")
    i = 0
    in_code = False
    in_table = False
    in_ul = False
    in_ol = False

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def close_table() -> None:
        nonlocal in_table
        if in_table:
            out.append("</tbody></table>")
            in_table = False

    while i < len(lines):
        line = lines[i]
        kind, payload = rows[i]
        # 代码簇：整体成块渲染（不拆散、不逐行成段）
        if kind == "code":
            close_lists()
            close_table()
            code_lines = payload if isinstance(payload, list) else [str(payload)]
            body = "\n".join(html.escape(ln) for ln in code_lines)
            out.append(f'<pre class="kb-code"><code>{body}</code></pre>')
            i += 1
            continue
        # 公式块：居中衬线文本块（不引排版引擎）
        if kind == "formula":
            close_lists()
            close_table()
            body = "\n".join(html.escape(ln) for ln in payload)  # type: ignore[union-attr]
            out.append(f'<div class="kb-formula">{body}</div>')
            i += 1
            continue
        # 图片占位单独成行（docling 常见）→ 直接替换
        if not in_code and PLACEHOLDER_RE.fullmatch(line.strip()):
            frag = render_placeholder()
            if frag:
                close_lists()
                close_table()
                out.append(frag)
            i += 1
            continue
        # 代码块
        if line.strip().startswith("```"):
            close_lists()
            close_table()
            out.append("<pre><code>" if not in_code else "</code></pre>")
            in_code = not in_code
            i += 1
            continue
        if in_code:
            out.append(html.escape(line))
            i += 1
            continue
        # 表格（`| a | b |`；紧跟 `|---|` 的分隔行）
        if line.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            close_lists()
            close_table()
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            out.append("<table><thead><tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in header) + "</tr></thead><tbody>")
            in_table = True
            i += 2
            continue
        if in_table and line.lstrip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            out.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>")
            i += 1
            continue
        close_table()
        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            close_lists()
            lvl = min(len(m.group(1)) + 1, 6)  # 文中标题整体降一级（h1 留给文档标题）
            out.append(f"<h{lvl}>{html.escape(m.group(2).strip())}</h{lvl}>")
            i += 1
            continue
        # 无序列表
        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m:
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                close_table()
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{html.escape(m.group(1).strip())}</li>")
            i += 1
            continue
        # 有序列表
        m = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                close_table()
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{html.escape(m.group(1).strip())}</li>")
            i += 1
            continue
        # 分隔线
        if re.fullmatch(r"\s*-{3,}\s*", line):
            close_lists()
            out.append("<hr>")
            i += 1
            continue
        # 空行
        if not line.strip():
            close_lists()
            out.append("")
            i += 1
            continue
        # 普通段落：行内处理（粗体 / 行内代码），其余转义
        close_lists()
        txt = html.escape(line)
        txt = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", txt)
        txt = re.sub(r"`([^`]+)`", r"<code>\1</code>", txt)
        out.append(f"<p>{txt}</p>")
        i += 1

    close_lists()
    close_table()
    if in_code:
        out.append("</code></pre>")

    meta = {
        "placeholder_count": used + dropped,
        "figure_count": len(figures),
        "matched": used,
        "dropped_placeholders": dropped,
        "unused_figures": max(0, len(figures) - used),
        # 文本清理审计（2026-10-10）：供静态验收对账
        "formula_removed": clean_stats["formula_removed"],
        "code_blocks": clean_stats["code_blocks"],
        "formula_blocks": clean_stats["formula_blocks"],
        "fragments_dropped": clean_stats["fragments_dropped"],
        "toc_dropped": clean_stats["toc_dropped"],
    }
    return "\n".join(out), meta


_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 20px 22px 40px; background: #fff; color: #1f2a24;
  font-family: "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
  font-size: 13px; line-height: 1.75;
}
h1 { font-size: 19px; margin: 4px 0 14px; }
h2 { font-size: 16px; margin: 22px 0 10px; padding-bottom: 4px; border-bottom: 1px solid #e3e8e4; }
h3 { font-size: 14px; margin: 18px 0 8px; }
h4, h5, h6 { font-size: 13px; margin: 14px 0 6px; color: #2e5e45; }
p { margin: 8px 0; }
ul, ol { margin: 8px 0; padding-left: 22px; }
li { margin: 3px 0; }
code { background: #f4f7f4; border: 1px solid #e3e8e4; border-radius: 3px; padding: 0 4px; font-size: 12px; }
pre { background: #f7f9f7; border: 1px solid #e3e8e4; border-radius: 4px; padding: 10px; overflow-x: auto; }
pre code { background: none; border: none; padding: 0; }
table { border-collapse: collapse; margin: 10px 0; width: 100%; font-size: 12px; }
th, td { border: 1px solid #e3e8e4; padding: 5px 8px; text-align: left; vertical-align: top; }
th { background: #f0f5f1; font-weight: 600; }
hr { border: none; border-top: 1px solid #e3e8e4; margin: 16px 0; }
.kb-fig { margin: 14px 0; text-align: center; }
.kb-fig img { max-width: 100%; height: auto; border: 1px solid #e3e8e4; border-radius: 4px; }
/* 代码块：整体成块，保留原始换行与缩进 */
.kb-code {
  background: #f7f9f7; border: 1px solid #e3e8e4; border-left: 3px solid #9bb8a8;
  border-radius: 4px; padding: 10px 12px; margin: 12px 0; overflow-x: auto;
  white-space: pre; font-size: 12px; line-height: 1.65;
}
.kb-code code { background: none; border: none; padding: 0; font-size: 12px; }
/* 公式块：居中、衬线、留白（干净文本样式，不引排版引擎） */
.kb-formula {
  margin: 12px auto; padding: 8px 12px; max-width: 100%; text-align: center;
  font-family: "Cambria Math", "Times New Roman", "Georgia", serif;
  font-size: 14px; line-height: 2; color: #22302a;
  background: #fbfcfb; border-radius: 4px; white-space: pre-wrap; word-break: break-word;
}
"""


def build_one(doc_dir: Path) -> dict | None:
    """合成一份文档；无 content.md 返回 None。"""
    md_file = doc_dir / "content.md"
    if not md_file.is_file():
        return None
    doc_id = doc_dir.name
    md = md_file.read_text(encoding="utf-8", errors="replace")
    figures = _usable_figures(doc_dir / "figures")
    body, meta = _md_to_html_body(md, doc_id, figures)

    # 标题：优先 source.json 的 title
    title = doc_id
    sj = doc_dir / "source.json"
    if sj.is_file():
        try:
            title = (json.loads(sj.read_text(encoding="utf-8")).get("title") or doc_id)
        except (json.JSONDecodeError, OSError):
            pass

    page = (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)}（合成图文稿）</title><style>{_CSS}</style></head><body>"
        f"<h1>{html.escape(title)}</h1>"
        '<div style="margin:0 0 14px;padding:8px 10px;border:1px solid #e3e8e4;border-radius:4px;'
        'background:#f7faf8;color:#5b6b62;font-size:12px;">'
        "系统合成图文稿（由抽取产物重建，非客户原件 PDF）。"
        "</div>"
        f"{body}</body></html>"
    )

    out_dir = doc_dir / "combined"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    meta_full = {
        "doc_id": doc_id,
        "title": title,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "html_bytes": len(page.encode("utf-8")),
        **meta,
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta_full, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta_full


def main() -> int:
    ap = argparse.ArgumentParser(description="构建知识库合成图文稿")
    ap.add_argument("--only", default="", help="只处理该 doc_id")
    args = ap.parse_args()

    root = kb_extract_dir()
    if not root.is_dir():
        print(f"[FAIL] 抽取稿根目录不存在：{root}", file=sys.stderr)
        return 1

    done = 0
    for doc_dir in sorted(root.iterdir()):
        if not doc_dir.is_dir() or doc_dir.name == "combined":
            continue
        if args.only and doc_dir.name != args.only:
            continue
        # 幂等：先清空旧 combined/ 再生成
        old = doc_dir / "combined"
        if old.is_dir():
            shutil.rmtree(old)
        info = build_one(doc_dir)
        if info is None:
            continue
        done += 1
        print(
            f"[ok] {info['doc_id']}: 占位 {info['placeholder_count']} / 图 {info['figure_count']}"
            f" → 对位 {info['matched']}，删占位 {info['dropped_placeholders']}，"
            f"余图 {info['unused_figures']}，删公式标记 {info['formula_removed']}，"
            f"代码块 {info['code_blocks']}，公式块 {info['formula_blocks']}，"
            f"删碎片 {info['fragments_dropped']}，删目录 {info['toc_dropped']}，"
            f"html {info['html_bytes']}B"
        )
    print(f"\n完成 {done} 份。输出：<doc_id>/combined/index.html + meta.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
