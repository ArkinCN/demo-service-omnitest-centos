"""八个文档类型的结构化抽取模板（主文档附录 A.3「结构化」阶段）。

背景与范围
----------
附录 A.3 明写：结构化阶段「按八个文档类型各写一份模板」，置信度低于阈值的条目
进「需人工校对」，**不允许静默通过**。

本轮（阶段 3 补全）**只真做三类**——数据手册、调试手册、源码参数配置，
它们覆盖现有两个场景包里的绝大多数材料；其余五类**保持骨架并如实标注
「模板待补」**，不冒充已精抽。这是用户明确拍板的范围，不是遗漏。

为什么抽不到就降置信度、而不是编一个值
--------------------------------------
结构化阶段的产物会进「需人工校对」判定，下游（索引）据此决定条目要不要人看一眼。
若这里为了「看起来齐」而用默认值填满字段，界面会显示一份「完整」的结构，
而人根本不知道哪些是真抽到的、哪些是编的——这比留空危险得多。
所以本模块的铁律是：**抽不到就留空 + 降 confidence + 记进 missing_keys**。

产物形状（与 kb_convert_service.stage_struct 的约定）
---------------------------------------------------
每个抽取函数返回::

    {
      "fields": [{"key": str, "value": str, "page": int | None, "evidence": str}],
      "hit_keys": [str],        # 命中的关键字段名
      "missing_keys": [str],    # 未命中的关键字段名
      "confidence": float,      # 0.0 ~ 1.0
      "notes": [str],           # 给人看的说明（例如「扫描件未开 OCR」）
    }

`confidence` 的计算口径见 `score_confidence()`：类型判定是否命中 + 关键字段命中率 +
层级完整度三项加权。三项都能解释、都能复算，不拍脑袋给一个 0.9。
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- 通用工具

# 表格行：docling 导出的 Markdown 表格形如 `| A | B |`
_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
# 表格分隔行：| --- | --- |（不是数据）
_TABLE_SEP_RE = re.compile(r"^\s*\|[\s:\-|]+\|\s*$")


def _iter_table_rows(markdown: str):
    """产出 Markdown 表格里的数据行（(表头列表, 单元格列表)）。

    表格以空行 / 非表格行分段；每段第一行是表头，其余是数据行。
    数据手册两种常见版式都能覆盖：
      A. 列式 —— 表头就是字段名（`| 额定电压 | 额定电流 |`），值在下一行；
      B. 行式 —— 表头是通用的「参数/额定值/单位」，**字段名在首列**。
    所以调用方既看表头、也看首列，两种都不漏。
    """
    header: list[str] = []
    for line in markdown.splitlines():
        if not _TABLE_ROW_RE.match(line):
            # 表格结束，表头作废（下一张表有自己的表头）
            header = []
            continue
        if _TABLE_SEP_RE.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not header:
            header = cells
            continue
        yield header, cells


def _norm(s: str) -> str:
    """归一：去多余空白与全角空格，便于做关键词匹配。"""
    return re.sub(r"[\s\u3000]+", " ", (s or "")).strip()


def _find_page(chunks: list[dict], needle: str) -> int | None:
    """在哪一页找到这段文字。找不到返回 None——**不猜页码**（页码要给人工核对用）。"""
    if not needle:
        return None
    n = _norm(needle)[:40]
    if not n:
        return None
    for c in chunks:
        if n in _norm(c.get("text") or ""):
            return c.get("page")
    return None


def _evidence(text: str, limit: int = 160) -> str:
    """证据片段：从正文里截一段原文，供人核对抽得对不对。"""
    return _norm(text)[:limit]


# ------------------------------------------------- 1. 数据手册（datasheet）

# 数据手册的关键字段：抽到哪些、缺哪些要如实报出来
_DS_KEYS = [
    "额定电压", "额定电流", "额定转速", "工作温度", "封装",
]

# 「字段名 → 正则」：先认表头语义，再从同一行取右邻单元格的值。
# 刻意用宽松的中文关键词：不同厂商数据手册用词不同（有的写「额定电压」，
# 有的写「供电电压 VDD」），过窄的正则会一条都抽不到。
_DS_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("额定电压", re.compile(r"(额定|工作|供电|电源)?电压|VDD|VCC|VBAT", re.I)),
    ("额定电流", re.compile(r"(额定|工作|静态|峰值)?电流|IVDD|ICC", re.I)),
    ("额定转速", re.compile(r"(额定|最高|最大)?转速|RPM|SPEED", re.I)),
    ("工作温度", re.compile(r"(工作|存储|环境)?温度|Temp(erature)?", re.I)),
    ("封装", re.compile(r"封装|Package|LQFP|QFN|SOP|TSSOP", re.I)),
]


def extract_datasheet(chunks: list[dict], markdown: str) -> dict:
    """数据手册：抽额定参数 / 电气特性 / 封装三类表格行。

    数据手册的参数**几乎都在表格里**，所以主策略是扫 Markdown 表格：
    表头命中某个关键字段语义时，取该列在同一表其余行里的首个非空值。
    表格扫不到时退回「字段名：值」的正文行（少数手册这么写）。
    """
    fields: list[dict] = []
    hit: list[str] = []
    notes: list[str] = []

    # ── 主策略：表格（两种版式都覆盖）──
    #
    # 版式 B（行式，最常见）：字段名在**首列**，`| 额定电压 | 24 | V |`
    #   → 首列命中语义时，取该行第二个非空单元格作值。
    # 版式 A（列式）：表头是字段名，`| 额定电压 | 额定电流 |`
    #   → 表头命中语义时，取本行对应列的值。
    # 两种都要求「取到的值不是字段名自己」——否则会造出一个看起来对、
    # 其实是列名的假字段。
    for header, cells in _iter_table_rows(markdown):
        if len(cells) < 2:
            continue
        for name, pat in _DS_PATTERNS:
            if name in hit:
                continue

            # 版式 B：首列即字段名
            if pat.search(cells[0]):
                for j in range(1, len(cells)):
                    val = cells[j].strip()
                    # 跳过空单元格、单位列、分隔符。
                    # ⚠️ 刻意**不用** `pat.search(val)` 挡：那样会把 `LQFP48`
                    # 这类本身含关键词（LQFP）的合法值一起挡掉（实测踩过）。
                    # 只需挡住「值等于字段名自己」这一种自指情况。
                    if not val or _norm(val) == _norm(cells[0]):
                        continue
                    if val in ("单位", "Unit", "单位/Unit", "-", "—", "/"):
                        continue
                    fields.append({
                        "key": name,
                        "value": val,
                        "page": _find_page(chunks, f"{cells[0]} {val}") or _find_page(chunks, cells[0]),
                        "evidence": _evidence(f"{cells[0]} | {val}"),
                    })
                    hit.append(name)
                    break
                continue

            # 版式 A：表头是字段名
            for idx, col in enumerate(header):
                if not pat.search(col):
                    continue
                val = cells[idx].strip() if idx < len(cells) else ""
                if not val or _norm(val) == _norm(col):
                    continue
                fields.append({
                    "key": name,
                    "value": val,
                    "page": _find_page(chunks, f"{col} {val}") or _find_page(chunks, col),
                    "evidence": _evidence(f"{col} | {val}"),
                })
                hit.append(name)
                break

    # ── 兜底：正文「字段名：值」行 ──
    for name, pat in _DS_PATTERNS:
        if name in hit:
            continue
        for line in markdown.splitlines():
            line = _norm(line)
            if ":" not in line and "：" not in line:
                continue
            for sep in (":", "："):
                if sep in line:
                    left, _, right = line.partition(sep)
                    break
            if pat.search(left) and right.strip():
                fields.append({
                    "key": name,
                    "value": right.strip()[:120],
                    "page": _find_page(chunks, line),
                    "evidence": _evidence(line),
                })
                hit.append(name)
                break

    missing = [k for k in _DS_KEYS if k not in hit]
    if not hit:
        notes.append("未从正文或表格中识别出任何数据手册关键参数，请人工核对材料是否确为数据手册")

    return {
        "fields": fields,
        "hit_keys": hit,
        "missing_keys": missing,
        "notes": notes,
    }


# --------------------------------------------- 2. 调试手册（debug-manual）

# 调试手册的关键字段：步骤 / 判据 / 故障处置
_DM_KEYS = ["调试步骤", "判据", "故障现象", "处置"]

# 调试步骤的行首标记。**必须放宽**：docling 把每个段落切成一个 chunk，
# 且手册里的章节标记五花八门。只在「第 N 步」上匹配会一条都抽不到
# （实测：一份写着「第 1 节 额定参数」的真手册命中 0 条）。
# 覆盖：第N步 / 第N节 / 第N章 / 阿拉伯数字列表 / 中文序号 / 「步骤N」/ 无序号动词开头。
_DM_STEP_RE = re.compile(
    r"^\s*(?:"
    r"第\s*[0-9一二三四五六七八九十百]+\s*[步節节章条条款]"
    r"|[0-9]+\s*[\.、)）]"
    r"|[（(]\s*[0-9一二三四五六七八九十]+\s*[)）]"
    r"|[一二三四五六七八九十]+\s*[、\.]"
    r"|步骤\s*[0-9一二三四五六七八九十]*"
    r"|(?:首先|然后|接着|随后|最后|下一步)"
    r")"
)
_DM_JUDGE_RE = re.compile(r"(判据|判据条件|合格|通过标准|验收标准|expect|assert)", re.I)
_DM_FAULT_RE = re.compile(r"(故障|异常|现象|报错|error|fail)", re.I)
_DM_FIX_RE = re.compile(r"(处置|处理|解决|对策|建议|修复)", re.I)


def extract_debug_manual(chunks: list[dict], markdown: str) -> dict:
    """调试手册：抽调试步骤、判据、故障现象与处置。

    这类材料的价值在**条目化**：一条「现象 → 成因 → 动作 → 结果」是可复用的
    调试经验，所以要按行切出来，而不是整段塞进一个字段。
    抽不到某类就如实留空——手册里没有某一类内容是正常的。

    ⚠️ 两种版式都要覆盖（docling 常把每个段落切成独立 chunk，标题与正文分离）：
      版式 A：同一段里既有标记又有内容（`1. 上电前检查母线电压`）；
      版式 B：标题段单独成 chunk（`第 2 节 启动测试`），正文在**后续** chunk 里。
    只认版式 A 会漏掉大量真实手册（实测踩过：一份分段式手册命中 0 条）。
    """
    fields: list[dict] = []
    hit: list[str] = []

    steps: list[str] = []
    judges: list[str] = []
    faults: list[str] = []
    fixes: list[str] = []

    # 当前所处的章节标题（版式 B 用）：见到章节标记就更新，
    # 后续无标记的正文段落按「属于该章节」归类。
    section = ""

    for c in chunks:
        page = c.get("page")
        for raw_line in (c.get("text") or "").splitlines():
            line = _norm(raw_line)
            if len(line) < 4:
                continue

            is_section = bool(_DM_STEP_RE.match(line))
            if is_section:
                # 章节标题本身也作为一条「步骤」记下来（它标出了调试的环节）
                section = line
                steps.append(line)
                fields.append({"key": "调试步骤", "value": line[:200],
                               "page": page, "evidence": _evidence(line)})
                continue

            # 判据 / 故障 / 处置按关键词识别（与是否在章节内无关）
            if _DM_JUDGE_RE.search(line):
                judges.append(line)
                fields.append({"key": "判据", "value": line[:200],
                               "page": page, "evidence": _evidence(line)})
            elif _DM_FAULT_RE.search(line):
                faults.append(line)
                fields.append({"key": "故障现象", "value": line[:200],
                               "page": page, "evidence": _evidence(line)})
            elif _DM_FIX_RE.search(line):
                fixes.append(line)
                fields.append({"key": "处置", "value": line[:200],
                               "page": page, "evidence": _evidence(line)})
            elif section and len(line) >= 8:
                # 版式 B：无标记正文段落，归到当前章节名下。
                # 只在**已有章节上下文**时才归——否则会把文档开头无关段落
                # 也算成调试步骤（那是在编字段）。
                steps.append(line)
                fields.append({
                    "key": "调试步骤",
                    "value": line[:200],
                    "page": page,
                    "evidence": _evidence(line),
                    "section": section[:60],
                })

    if steps:
        hit.append("调试步骤")
    if judges:
        hit.append("判据")
    if faults:
        hit.append("故障现象")
    if fixes:
        hit.append("处置")
    notes: list[str] = []
    if not steps and not judges:
        notes.append("未识别出调试步骤与判据，材料可能是原理说明而非调试手册")

    missing = [k for k in _DM_KEYS if k not in hit]
    return {
        "fields": fields,
        "hit_keys": hit,
        "missing_keys": missing,
        "notes": notes,
        "counts": {
            "调试步骤": len(steps), "判据": len(judges),
            "故障现象": len(faults), "处置": len(fixes),
        },
    }


# --------------------------------------- 3. 源码参数配置（header-config）

# 源码类材料的关键字段：宏名 / 默认值 / 注释
_HC_KEYS = ["宏定义", "默认值", "注释说明"]

# C 宏定义：`#define NAME  value   // 注释`
# 分三组：名字、值（可空）、行尾注释（// 或 /* */）
_HC_DEFINE_RE = re.compile(
    r"^\s*#\s*define\s+([A-Za-z_][A-Za-z0-9_]*)\s+([^/\r\n]*?)\s*(?://\s*(.*)|/\*\s*(.*?)\s*\*/)?\s*$"
)


def extract_header_config(chunks: list[dict], markdown: str) -> dict:
    """源码参数配置：抽宏名 + 默认值 + 注释说明。

    现有 Customer.h 这类材料在场景包里是「一条宏一行」，抽取目标就是**宏表**：
    宏名（可检索、可引用）、默认值（可核对）、注释（中文语义，检索命中率最高）。
    """
    fields: list[dict] = []
    macros: list[dict] = []

    for c in chunks:
        text = c.get("text") or ""
        for raw_line in text.splitlines():
            m = _HC_DEFINE_RE.match(raw_line)
            if not m:
                continue
            name = m.group(1)
            value = (m.group(2) or "").strip()
            comment = (m.group(3) or m.group(4) or "").strip()
            page = c.get("page")
            macros.append({"name": name, "value": value, "comment": comment, "page": page})
            fields.append({
                "key": "宏定义",
                "value": name,
                "page": page,
                "evidence": _evidence(raw_line),
            })
            if value:
                fields.append({
                    "key": "默认值",
                    "value": f"{name} = {value}",
                    "page": page,
                    "evidence": _evidence(raw_line),
                })
            if comment:
                fields.append({
                    "key": "注释说明",
                    "value": f"{name}: {comment}",
                    "page": page,
                    "evidence": _evidence(raw_line),
                })

    hit: list[str] = []
    if macros:
        hit.append("宏定义")
        if any(m["value"] for m in macros):
            hit.append("默认值")
        if any(m["comment"] for m in macros):
            hit.append("注释说明")

    missing = [k for k in _HC_KEYS if k not in hit]
    notes: list[str] = []
    if not macros:
        notes.append("未识别出 #define 宏定义，材料可能不是 C 头文件类的参数配置")

    return {
        "fields": fields,
        "hit_keys": hit,
        "missing_keys": missing,
        "notes": notes,
        "macro_count": len(macros),
        "macros": macros[:200],
    }


# --------------------------------------------------------- 置信度与注册表

# 五项权重：类型判定 / 关键字段命中率 / 层级完整度。
# 为什么类型判定权重不低：模板套错时，即使抽出一堆字段也是错的，
# 必须让「类型没判准」这件事显著拉低置信度，把文件推进人工校对。
W_TYPE = 0.4
W_KEYS = 0.4
W_HEADING = 0.2


def score_confidence(
    *,
    typed: bool,
    hit_keys: list[str],
    key_total: int,
    chunks: list[dict],
) -> tuple[float, dict]:
    """三因子置信度。返回 (confidence, 明细)，明细进产物供人复查。

    1. typed        —— 类型判定是否命中（命中率见 kb_convert_service._guess_template）
    2. key_ratio    —— 关键字段命中率 = 命中数 / 该类型关键字段总数
    3. heading_ratio—— 层级完整度 = 带 heading_path 的切片占比

    三项都是可复算的确定量，不引入随机或模型打分；明细一并落盘，
    人工校对时能看到「这个 0.55 是怎么来的」。
    """
    key_ratio = (len(hit_keys) / key_total) if key_total else 0.0
    with_heading = sum(1 for c in chunks if c.get("heading_path"))
    heading_ratio = (with_heading / len(chunks)) if chunks else 0.0
    conf = W_TYPE * (1.0 if typed else 0.0) + W_KEYS * key_ratio + W_HEADING * heading_ratio
    detail = {
        "typed": typed,
        "weight_type": W_TYPE,
        "key_ratio": round(key_ratio, 3),
        "weight_keys": W_KEYS,
        "key_hit": len(hit_keys),
        "key_total": key_total,
        "heading_ratio": round(heading_ratio, 3),
        "weight_heading": W_HEADING,
        "formula": "0.4*typed + 0.4*key_ratio + 0.2*heading_ratio",
    }
    return round(conf, 3), detail


# 模板注册表：模板名 → (抽取函数, 该类型的关键字段清单, 中文类型名)
# **只登记真做好的三类**；其余五类不在表里，stage_struct 会据此如实标注「模板待补」。
TEMPLATES: dict[str, tuple] = {
    "datasheet": (extract_datasheet, _DS_KEYS, "数据手册"),
    "debug-manual": (extract_debug_manual, _DM_KEYS, "调试手册"),
    "header-config": (extract_header_config, _HC_KEYS, "源码参数配置"),
}

# 附录 A.3 的八个文档类型全表。**这里保留完整八项**，
# 是为了让界面能如实说出「有哪几类还没做模板」，而不是假装只有三类。
ALL_DOC_TYPES: dict[str, str] = {
    "datasheet": "数据手册",
    "debug-manual": "调试手册",
    "app-note": "应用手册",
    "principle": "原理文档",
    "training": "培训材料",
    "issue-summary": "问题汇总",
    "exam": "考核题库",
    "header-config": "源码参数配置",
}


def is_implemented(template: str) -> bool:
    """该类型是否已有真抽模板。未实现的三类走骨架并标注「模板待补」。"""
    return template in TEMPLATES


def extract(template: str, chunks: list[dict], markdown: str) -> dict:
    """按模板名抽取。未实现的模板抛 KeyError，由调用方决定如何标注。"""
    fn, _keys, _label = TEMPLATES[template]
    return fn(chunks, markdown)
