"""以客户模板为基底出报告（2026-10-13 用户口径「报告使用这个模板出」）。

## 这个模块做什么

`report_workbook.py` 是**从零造一本工作簿**（自建版式）。本模块是它的**替代路径**：
把用户给的 `测试报告模板-v1.xlsm` 当**基底**，把本轮真实数据**写进模板已有的
「待填写」位**，再把趋势图 / 波形图插进模板预留的图位，最后另存为正式报告。

模板文件见 `core/paths.py` 的 `builtin_report_template()`
（随代码交付的资产，与用户上传模板目录**严格分开**）。

## 三条不可逾越的口径

1. **只填模板上有的位**（用户 2026-10-13 原话「只填写报告上有的参数或问题」）：
   本模块只写 `_WHITELIST` 里列出的单元格 + 图表锚点 + 新增隐藏数据页；
   **不新增区块、不造字段**。系统表头有 10 项而模板封面只有 6 个位，
   另外 4 项（客户名称 / 客户工程师 / Email / 联系电话）**不填、也不补**——
   只在返回值 `warnings` 里如实记一笔，不改报告纸面。

   **两条落笔细则（2026-10-13 用户口径补充）**：
   - **「本台架不适用」的判定行不写入**：判据 ID 与名称（模板原文）保留，
     **只把结论格留空**；封面判定汇总里的「本台架不适用」**计数行照旧保留**。
   - **表头来自别的轮次时要标注**：表头确认与报告生成可能落在两轮，取数层会回退到
     「本场景最近一份已确认实例」；此时「报告来源」行写成
     `系统内置模板（表头取自轮次 xxxxxxxx）`，让读者知道表头不是本轮产生的。
2. **数据纪律**：只写已核实的真实数据；缺测点**留空**（Excel 图表遇空值自动断线），
   **绝不补 0 / 不插值**；数据不齐时如实写「（无）」+ 原因；通过率沿用
   `report_workbook._fmt_rate`（分母为 0 → 「—」，绝不写 0%）。
3. **保留原实例**：「报告概要」（含原 10 张原生图表）与 `_图表数据` 两页
   **一字不改**；本批图表数据另落**新增隐藏页** `_图表数据-本次`。

## 版位表（实测坐标，2026-10-13 核对）

| 页 | 位置 | 内容 |
|---|---|---|
| 报告封面 | C7/C8/C9/C10 | 轮次号 / 生成时间 / 报告状态 / 报告来源 |
| 报告封面 | C13:C18 | 表头 6 项（模板仅此 6 位） |
| 报告封面 | C21:C28 | 判定汇总 8 项 |
| 判定明细 | G7:G40 | 34 条判据结论（**以 A 列 ID 为锚**，不按行序硬套） |
| 判定明细 | C43 / C46:C50 | 配置快照摘要 / 本轮产物清单 5 项 |
| 趋势图 | C6 / A11 / A23 | 数据点数 / 两张趋势图的插图锚点 |
| 波形与截图 | A7/A20/A39/A52/A71/A84/A103/A116 | 8 张波形图的插图锚点 |

## 图块排版（怎么避免「图压住标题」）

模板每个图块是 **10 行合并区**，块内文字（标题 + 两行填写指示）在合并区里
**垂直居中**——直接插图必然压字。故填充时：

- 块内文字**只保留第一行标题**（去掉「待插入…」「建议约 24×6 cm…」两行指示，
  它们是给填写人的，不是报告内容）；标题**垂直对齐改靠上**，落在块首行；
- 图表锚在**标题行的下一行**（该处起共 9 行空白），与标题零重叠；
- 图高 6 cm = 170.08 pt，而 9 行默认行高合计只有 144.45 pt（16.05×9）→
  按差值把这些行调到 18.9 pt（合计 170.1 pt），**只调行高、不插行**
  （模板合并区 121 处，插行会错位）。

## 图宽为什么是 14.5 cm 而不是模板建议的 24 cm

模板占位写「建议约 24 × 6 cm」，但该页**打印区是 `$A$1:$H$xx`**，A:H 合计约
14.7 cm——24 cm 宽的图打印/导 PDF 时右侧会被**截掉**（超出打印区的图形不打印）。
2026-10-13 用户裁决：**图宽适配打印区 = 14.5 × 6 cm**（屏幕与打印都完整）。

## 自检（本模块自带，不靠外部脚本发现漏填）

落盘前统计四页里**精确等于**「待填写」的单元格：非零即抛 `RuntimeError`，
把残留坐标全部列出。宁可不产文件，也不交一份还带着占位符的报告。
（注意用**精确相等**判定，不能用子串：封面 A35 的说明文案里就含「待填写」三个字。）
"""
from __future__ import annotations

from copy import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.chart import LineChart

from app.services import report_charts
# ⚠️ 刻意复用 report_workbook 的这两个私有口径函数：
#   · `_fmt_rate`      —— 通过率格式化（分母 0 → 「—」）的**唯一实现**；
#   · `_to_simplified` —— 繁简逐字映射的**唯一实现**。
# 复制一份会立刻产生两套口径（改一处忘另一处），故宁可跨模块引用私有名。
from app.services.report_workbook import (
    ARTIFACT_LABEL,
    HEADER_LABEL,
    STATE_CN,
    _fmt_rate,
    _to_simplified,
)

# ---------------------------------------------------------------- 常量

SHEET_COVER = "报告封面"
SHEET_DETAIL = "判定明细"
SHEET_TREND = "趋势图"
SHEET_WAVE = "波形与截图"
SHEET_SUMMARY = "报告概要"      # 原实例：一字不改
SHEET_DATA_OLD = "_图表数据"    # 原实例数据源：一字不改
#: 本次图表数据落到**新增**隐藏页（不覆盖原实例，用户口径 2026-10-13）
DATA_SHEET_NEW = "_图表数据-本次"

#: 模板里等待被填的占位符（精确相等才算）
PLACEHOLDER = "待填写"
#: 表头位取不到时写的文案（与 `report_workbook` 的历史口径逐字一致）
HEADER_MISSING_TEXT = "由上游带入（未提供）"
#: 缺口位填不出时的统一记号（用户口径：填不出写「—」，不许编）
DASH = "—"

#: 封面页第 3 行那句填写说明（**删除**，用户 2026-10-13 口径）——
#: 「空白填写模板｜原测试参数逐项继承；原报告实例在「报告概要」中留存」。
#: 同一句还出现在「判定明细」「趋势图」两页的 A3，一并删（三页口径一致）。
TEMPLATE_HINT_TEXT = "空白填写模板｜原测试参数逐项继承；原报告实例在「报告概要」中留存"
TEMPLATE_HINT_CELLS: tuple[tuple[str, str], ...] = (
    (SHEET_COVER, "A3"),
    (SHEET_DETAIL, "A3"),
    (SHEET_TREND, "A3"),
)

#: 封面页「数据来源」写什么（用户口径 2026-10-13：去掉「（权威）」后缀）
COVER_DATA_SOURCE = "后端判定"
#: 封面页通过率口径说明（用户口径 2026-10-13：删掉「未采集与本台架不适用不计入分母」半句，
#: 保留后半句关于「未采集 ≠ 不通过」的解释）
COVER_NOTE = (
    "通过率 = 通过 ÷（通过 + 不通过）。"
    "「未采集」不等于「不通过」：相应现场实测量缺失时，无法据此判出通过或不通过。"
)
COVER_NOTE_CELL = "A30"

#: 封面「报告标识」四行：语义 → 值单元格
COVER_ID: dict[str, str] = {
    "run_id": "C7",
    "generated_at": "C8",
    "report_status": "C9",
    "source": "C10",
}
#: 封面「报告表头」：**只有模板给出的 6 位**（另外 4 项系统表头无位，不填也不新增）
COVER_HEADER: dict[str, str] = {
    "model": "C13",
    "project_name": "C14",
    "firmware_version": "C15",
    "inlet_start_addr": "C16",
    "bootloader": "C17",
    "outlet_start_addr": "C18",
}
#: 封面「判定汇总」8 行
COVER_SUMMARY: dict[str, str] = {
    "pass_rate": "C21",
    "total": "C22",
    "pass": "C23",
    "fail": "C24",
    "missing": "C25",
    "not_applicable": "C26",
    "manual": "C27",
    "source": "C28",
}

#: 判定明细的判据行区间与列（A 判据 / C 名称 / G 结论；内容以 A 列为锚）
DETAIL_ROW_FIRST = 7
DETAIL_ROW_LAST = 40
DETAIL_ID_COL = 1
DETAIL_STATE_COL = 7
#: 配置快照摘要单元格
DETAIL_SNAPSHOT_CELL = "C43"
#: 本轮产物清单：产物 kind → 值单元格（模板行序固定，标签在 A 列）
DETAIL_ARTIFACT_CELLS: dict[str, str] = {
    "config-snapshot": "C46",
    "run-artifact": "C47",
    "verdict-table": "C48",
    "gap-list": "C49",
    "report-instance": "C50",
}

#: 趋势图页：数据点数 + 两个版位（标题行 / 插图锚点 / 图注行）
TREND_COUNT_CELL = "C6"

# ── 「报告概要」页（模板带来的上一轮实例）按口径处理的几处 ──
#
# 该页整体**保留原实例**（用户 2026-10-13 口径），但下面几处例外：
#   ① 判定明细里「本台架不适用」的结论格留空：只清结论，判据 ID 与名称保留；
#   ② 判定汇总的「本台架不适用」**整行删除且不留空行**——该行删掉后，
#      其下的「人工判定 / 数据来源 / 说明」**整体上移一行**补齐（用户 2026-10-13
#      追加口径：「第 21 行不要留空行」）。概要页**无合并区**（实测 `[]`），
#      上移安全；汇总区在第 15~24 行之间，与下方明细区之间还隔着第 25 行空行。
#   ③ 通过率口径说明**缩短**为一句公式；
#   ④ 汇总区的**表头字段（机型/项目名称/固件版本/Inlet/Bootloader/Outlet）同步本轮数据**
#      （用户 2026-10-13：「报告封面已经拿到表头数据了，报告概要还没改」）。
#
# ⚠️ 判定汇总的「本台架不适用」标签格是 **A21**、计数格是 **B21**：
#    它与明细里的同名结论（C 列）**语义不同**——前者是汇总项，后者是逐条结论。
#    要删的是**汇总那一行**，不要顺手把明细的行也删了。
SUMMARY_SHEET_UNAPPLICABLE_ROW = 21
#: 汇总区里该删除行**之后**、需要整体上移的行（行号按**模板原始**坐标写）
SUMMARY_SHEET_SHIFT_ROWS = (22, 23, 24)
#: 上移后「口径说明」落在哪一行（= 24 - 1）
SUMMARY_SHEET_NOTE_ROW = 23

#: 概要页「报告来源」一行（模板 B5）写什么——用户口径 2026-10-13：**标准版**
#: （模板原实例写的是「系统内置模板」，那是内部实现说法）。
SUMMARY_SHEET_SOURCE_CELL = "B5"
SUMMARY_SHEET_SOURCE_TEXT = "标准版"
#: 概要页「数据来源」一行写什么——用户口径 2026-10-13：**后端判定**（去掉「（权威）」）。
#: ⚠️ 该行在**删行上移后会挪位**（模板 B23 → 产物 B22），故一律**按 A 列标签定位**，
#: 不写死行号；标签文案按模板原文。
SUMMARY_SHEET_DATA_SOURCE_LABEL = "数据来源"
SUMMARY_SHEET_DATA_SOURCE_TEXT = "后端判定"
#: 汇总区表头：模板 B 列的行号（第 8~13 行），值来自本轮表头
SUMMARY_SHEET_HEADER: dict[str, int] = {
    "model": 8,
    "project_name": 9,
    "firmware_version": 10,
    "inlet_start_addr": 11,
    "bootloader": 12,
    "outlet_start_addr": 13,
}
#: 汇总区表头行对应的标签（A 列原文，用于校验对得上）
SUMMARY_SHEET_HEADER_LABEL: dict[str, str] = {
    "model": "机型",
    "project_name": "项目名称",
    "firmware_version": "固件版本",
    "inlet_start_addr": "Inlet 起始位址",
    "bootloader": "Bootloader",
    "outlet_start_addr": "Outlet 起始位址",
}
SUMMARY_SHEET_NOTE = "通过率 = 通过 ÷（通过 + 不通过）"

TREND_SLOTS: tuple[dict[str, Any], ...] = (
    {"key": "trend1", "title": "A10", "anchor": "A11", "caption": "A20"},
    {"key": "trend2", "title": "A22", "anchor": "A23", "caption": "A32"},
)

#: 波形页 8 个版位（顺序 = 模板自上而下）
WAVE_SLOTS: tuple[dict[str, Any], ...] = (
    {"ch": 1, "kind": "full", "title": "A6", "anchor": "A7", "caption": "A16"},
    {"ch": 1, "kind": "zoom", "title": "A19", "anchor": "A20", "caption": "A29"},
    {"ch": 2, "kind": "full", "title": "A38", "anchor": "A39", "caption": "A48"},
    {"ch": 2, "kind": "zoom", "title": "A51", "anchor": "A52", "caption": "A61"},
    {"ch": 3, "kind": "full", "title": "A70", "anchor": "A71", "caption": "A80"},
    {"ch": 3, "kind": "zoom", "title": "A83", "anchor": "A84", "caption": "A93"},
    {"ch": 4, "kind": "full", "title": "A102", "anchor": "A103", "caption": "A112"},
    {"ch": 4, "kind": "zoom", "title": "A115", "anchor": "A116", "caption": "A125"},
)
#: 四个通道块头的行号：句末「采集来源：待填写」只替换占位，其余原文保留
WAVE_SOURCE_ROWS: tuple[int, ...] = (3, 35, 67, 99)
WAVE_SOURCE_PLACEHOLDER = "采集来源：待填写"
#: 块头里「采集来源」那一段的前缀（替换时保留前缀写法）
WAVE_SOURCE_PREFIX = "采集来源："

#: 图注里的「原判据编号／名称」映射（用户在 2026-10-13 确认的口径）。
#: 找不到对应关系时写「—」，**不编**。
CAPTION_REQ: dict[str, str] = {
    "trend1": "TR-PWM-01",     # PWM 调速曲线全档位验证
    "trend2": "TR-BENCH-03",   # 供电电压稳定范围
    "wave1": "TR-BENCH-04",    # 波形采集有效性（CH1）
    "wave2": "TR-BENCH-04",    # 波形采集有效性（CH1 放大）
    "wave3": "TR-BENCH-04",    # 波形采集有效性（CH2）
    "wave4": "TR-BENCH-04",    # 波形采集有效性（CH2 放大）
    "wave5": "TR-BENCH-04",    # 波形采集有效性（CH3）
    "wave6": "TR-BENCH-04",    # 波形采集有效性（CH3 放大）
    "wave7": "TR-BENCH-06",    # 转速采集有效性（CH4）
    "wave8": "TR-BENCH-06",    # 转速采集有效性（CH4 放大）
}
#: 图注占位符（模板原文里连续 10 个下划线，共两处：判据编号、来源）
CAPTION_BLANK = "_" * 10

#: 默认插图尺寸（cm）：图宽适配模板打印区 A:H ≈ 14.7 cm（见模块头说明）
DEFAULT_CHART_W_CM = 14.5
DEFAULT_CHART_H_CM = 6.0
#: 1 cm ≈ 28.3465 pt，用于把图高换算成行高
PT_PER_CM = 28.3465

#: 只在这些工作表里检查「待填写」残留（报告概要/_图表数据 是原实例，本就不含占位）
CHECK_SHEETS: tuple[str, ...] = (SHEET_COVER, SHEET_DETAIL, SHEET_TREND, SHEET_WAVE)


# ---------------------------------------------------------------- 入参契约


@dataclass(frozen=True)
class ReportFillData:
    """填充器唯一入参：全部为**已核实**的真实数据，缺项以 None / 空容器表达。

    字段与 `report_workbook.build_report_workbook` 的入参一一对应，
    这样 `reports.py` 两条产出路径可以互换而不必各自装配一遍。
    """

    run_id: str
    header: dict[str, str] = field(default_factory=dict)
    missing_header_keys: list[str] = field(default_factory=list)
    verdict: dict[str, Any] | None = None
    verdict_items: list[dict[str, Any]] = field(default_factory=list)
    artifact_kinds: list[str] = field(default_factory=list)
    snapshot_counts: dict[str, int] | None = None
    #: 「报告来源」一行的文案（用户口径 2026-10-13 最终版：写「系统内置模板：标准版」；
    #: 此前一版曾短暂改成「标准版」，用户随后要求明确到「系统内置模板：标准版」）。
    source_note: str = "系统内置模板：标准版"
    chart_data: dict[str, Any] | None = None
    #: 生成时刻文本；留空则取当前本地时间（与 report_workbook 同一写法）
    generated_at: str = ""
    #: 表头取自哪一轮。等于 `run_id`（或为空）时正常写「报告来源」；
    #: **不等于本轮**时说明走的是「回退到最近已确认实例」，须在报告里标注来源轮次
    #: （用户口径 2026-10-13：「在报告里标注来源轮次」）。
    header_source_run_id: str | None = None


# ---------------------------------------------------------------- 小工具


def _now_text() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _cell_text(ws, coord: str) -> str:
    v = ws[coord].value
    return v.strip() if isinstance(v, str) else ""


def _write(ws, coord: str, text: str) -> None:
    """写单元格值。**不动既有样式**（模板的字体/边框/底色原样保留）。"""
    ws[coord] = text


def _rewrite_title(ws, coord: str, suffix: str = "") -> str:
    """块标题：只保留首行（去掉给填写人的指示行），并把垂直对齐改靠上。

    为什么必须改对齐：标题原在 10 行合并区里**垂直居中**，图插在标题下方时
    会被文字压住（见模块头「图块排版」）。

    返回实际写入的标题文本（供调用方记录），取不到首行时返回空串（不改）。
    """
    text = _cell_text(ws, coord)
    first = text.split("\n")[0].strip() if text else ""
    if not first:
        return ""
    _write(ws, coord, first + suffix)
    al = copy(ws[coord].alignment)
    al.vertical = "top"
    ws[coord].alignment = al
    return first + suffix


def _append_title_note(ws, coord: str, note: str) -> None:
    """给（没有图的）块标题追加一句如实说明，例如「（无）本轮未采集到该通道」。"""
    text = _cell_text(ws, coord)
    if text:
        _write(ws, coord, f"{text.split(chr(10))[0]}（{note}）")


def _fit_rows(ws, row_from: int, row_to: int, need_pt: float) -> float:
    """把 [row_from, row_to] 的行高合计调到 ≥ `need_pt`；**只加不减**。

    只调行高、不插行：模板合并区多（判定明细 121 处），插行不会同步移动合并区
    与图表锚点，风险远高于收益（2026-10-13 实测确认）。

    返回实际增加的高度（pt）；已够高时返回 0。
    """
    rows = list(range(row_from, row_to + 1))
    if not rows:
        return 0.0
    default_h = ws.sheet_format.defaultRowHeight or 16.05
    cur = sum((ws.row_dimensions[r].height or default_h) for r in rows)
    if cur >= need_pt:
        return 0.0
    per = need_pt / len(rows)
    for r in rows:
        ws.row_dimensions[r].height = round(per, 2)
    return round(need_pt - cur, 2)


def _fill_caption(ws, coord: str, req_id: str, source: str) -> bool:
    """图注：把两处下划线占位依次换成判据编号与来源。

    占位形态与预期不符（不是两处）时**不改**并返回 False——宁可留原样，
    也不按猜想替换（模板原文是这份报告的一部分，不许改错）。
    """
    old = ws[coord].value
    if not isinstance(old, str):
        return False
    parts = old.split(CAPTION_BLANK)
    if len(parts) != 3:
        return False
    ws[coord] = parts[0] + req_id + parts[1] + source + parts[2]
    return True


def _workbook_content_type(path: Path) -> str:
    """取 `[Content_Types].xml` 里 workbook 主部件那一条 Override（原样字符串）。

    取不到（结构异常）时返回空串，调用方按「不为空才动」处理。
    """
    import zipfile

    try:
        with zipfile.ZipFile(path) as z:
            ct = z.read("[Content_Types].xml").decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return ""
    for part in ct.split("<Override"):
        if "/xl/workbook.xml" in part:
            return "<Override" + part.split(">")[0] + "/>"
    return ""


def _preserve_main_content_type(template: Path, out: Path) -> bool:
    """把产物的主部件内容类型改成与**模板一致**（保住 .xlsm 的 macroEnabled 声明）。

    为什么必须做（2026-10-13 实测）：openpyxl 只在「模板里真有 `vbaProject.bin`」时
    才写 macroEnabled 内容类型；本模板虽是 .xlsm、却没有宏部件 → 直接 `save()` 会把
    主内容类型写成普通 xlsx 的，而文件扩展名仍是 `.xlsm`，Excel 打开会提示
    「文件格式与扩展名不符」。这里只在 zip 层替换 `[Content_Types].xml` 里 workbook
    那一条 Override，其余部件原样搬运（解压/重打包，内容逐字节保留）。

    返回 True 表示确实打了补丁。
    """
    import shutil
    import zipfile

    tpl_ct = _workbook_content_type(template)
    out_ct = _workbook_content_type(out)
    if not tpl_ct or not out_ct or tpl_ct == out_ct:
        return False
    tmp = out.with_name(out.name + ".cttmp")
    with zipfile.ZipFile(out) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = data.replace(out_ct.encode("utf-8"), tpl_ct.encode("utf-8"))
            zout.writestr(item, data)
    shutil.move(str(tmp), str(out))
    return True


def _iter_placeholders(wb) -> list[str]:
    """四页里**精确等于**「待填写」的单元格清单（"页!格"）。

    ⚠️ 必须用精确相等而非子串：封面 A35 的说明文案里含「待填写」三个字。
    """
    left: list[str] = []
    for name in CHECK_SHEETS:
        if name not in wb.sheetnames:
            continue
        for row in wb[name].iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.strip() == PLACEHOLDER:
                    left.append(f"{name}!{c.coordinate}")
    return left


# ---------------------------------------------------------------- 主体填充


def _fill_cover(ws, data: ReportFillData, generated_at: str, warnings: list[str]) -> None:
    """报告封面 19 处「待填写」全部落值。"""
    _write(ws, COVER_ID["run_id"], data.run_id)
    _write(ws, COVER_ID["generated_at"], generated_at)
    _write(ws, COVER_ID["report_status"], "正式报告")
    # 报告来源：表头若来自**别的轮次**（回退到最近已确认实例），必须标注来源轮次，
    # 否则读者会以为表头就是本轮的（2026-10-13 用户口径）。
    src = _to_simplified(data.source_note)
    fb = (data.header_source_run_id or "").strip()
    if fb and fb != data.run_id:
        src = f"{src}（表头取自轮次 {fb[:8]}）"
        warnings.append(
            f"本轮（{data.run_id[:8]}）没有已确认的表头，报告表头沿用本场景最近"
            f"已确认实例（轮次 {fb[:8]}）——已在报告「报告来源」行标注"
        )
    _write(ws, COVER_ID["source"], src)

    # 表头：模板只有 6 位；系统表头里多出来的项**不填也不新增**，只在 warnings 记一笔
    for key, coord in COVER_HEADER.items():
        if key in data.header and data.header[key] not in (None, ""):
            _write(ws, coord, _to_simplified(str(data.header[key])))
        else:
            _write(ws, coord, HEADER_MISSING_TEXT)
    extra = [k for k in data.header if k not in COVER_HEADER]
    if extra:
        warnings.append(
            "模板封面只有 6 个表头位，以下表头字段在模板上无对应位置、未填写（未新增区块）："
            + "、".join(HEADER_LABEL.get(k, k) for k in extra)
        )
    # 上游没给、但模板有位的字段：照实写「未提供」，并留一条可核对的痕
    miss_with_slot = [k for k in data.missing_header_keys if k in COVER_HEADER]
    if miss_with_slot:
        warnings.append(
            "这些表头字段本轮未取到，模板对应位如实写「由上游带入（未提供）」："
            + "、".join(HEADER_LABEL.get(k, k) for k in miss_with_slot)
        )

    # 判定汇总 8 行
    v = data.verdict
    if not v:
        _write(ws, COVER_SUMMARY["pass_rate"], "（无）")
        for key in ("total", "pass", "fail", "missing", "not_applicable", "manual"):
            _write(ws, COVER_SUMMARY[key], DASH)
        _write(ws, COVER_SUMMARY["source"], "本轮没有判定数据（未产出判定结果表）")
        warnings.append("本轮无判定数据，封面判定汇总按「（无）/—」如实填写（不补 0）")
        return
    _write(ws, COVER_SUMMARY["pass_rate"], _fmt_rate(v.get("pass_rate")))
    for key in ("total", "pass", "fail", "missing"):
        _write(ws, COVER_SUMMARY[key], str(v.get(key, 0)))
    # 「本台架不适用 / 人工判定」模板给了固定行，故 0 也照实写 0（不隐藏）
    _write(ws, COVER_SUMMARY["not_applicable"], str(v.get("not_applicable", 0) or 0))
    _write(ws, COVER_SUMMARY["manual"], str(v.get("manual", 0) or 0))
    _write(
        ws,
        COVER_SUMMARY["source"],
        COVER_DATA_SOURCE if v.get("authoritative") else "前端预览（非权威）",
    )
    # 通过率口径说明缩短（用户口径 2026-10-13）
    if ws[COVER_NOTE_CELL].value is not None:
        _write(ws, COVER_NOTE_CELL, COVER_NOTE)


def _fill_detail(ws, data: ReportFillData, warnings: list[str]) -> None:
    """判定明细：34 条判据结论 + 配置快照摘要 + 产物清单。"""
    by_id: dict[str, dict[str, Any]] = {}
    for it in data.verdict_items:
        if isinstance(it, dict) and it.get("req_id"):
            by_id[str(it["req_id"])] = it

    used: set[str] = set()
    unmatched_rows: list[str] = []
    #: 结论留空的「本台架不适用」判据 ID（用户口径：这类明细不写入结论）
    na_rows: list[str] = []
    for row in range(DETAIL_ROW_FIRST, DETAIL_ROW_LAST + 1):
        req_id = _cell_text(ws, f"A{row}")
        if not req_id:
            # 模板这一行没有判据 ID：结构不符，如实记，不当成「空行」跳过
            unmatched_rows.append(f"A{row}（无判据 ID）")
            continue
        item = by_id.get(req_id)
        if item is None:
            # 模板有、本轮判定没有：按「未采集」落值（它确实没有可判的实测数据），
            # 并在 warnings 写明是哪些 ID —— 不静默
            _write(ws, f"G{row}", STATE_CN["missing"])
            warnings.append(f"判据 {req_id} 在模板中、但本轮判定表里没有 → 结论按「未采集」填写")
            continue
        state = str(item.get("state") or "")
        used.add(req_id)
        if state == "not_applicable":
            # 「本台架不适用」**不写入**（用户口径 2026-10-13）：判据 ID 与名称
            # （模板原文）保留，只把结论格**留空**。
            # ⚠️ 必须显式写 None 清掉模板里的「待填写」占位，否则落盘自检会拦下来。
            # ⚠️ 封面判定汇总里的「本台架不适用」**计数行照旧保留**（那是汇总，
            #    不是明细）；两者别混。
            ws[f"G{row}"] = None
            na_rows.append(req_id)
            continue
        _write(ws, f"G{row}", STATE_CN.get(state, state or DASH))

    extra_ids = sorted(set(by_id) - used)
    if extra_ids:
        warnings.append(
            "本轮判定里有、但模板没有对应行的判据（未写入报告，模板结构不动）："
            + "、".join(extra_ids)
        )
    if unmatched_rows:
        warnings.append("模板判定行结构异常：" + "、".join(unmatched_rows))
    if na_rows:
        warnings.append(
            f"{len(na_rows)} 条「本台架不适用」的结论列按口径留空（判据编号与名称保留，"
            "模板原文不动）：" + "、".join(na_rows)
        )

    # 配置快照摘要（口径与 report_workbook 同：逐项写「N 项」，这里合并到一格）
    if data.snapshot_counts:
        _write(
            ws,
            DETAIL_SNAPSHOT_CELL,
            " · ".join(f"{k} {v} 项" for k, v in data.snapshot_counts.items()),
        )
    else:
        _write(ws, DETAIL_SNAPSHOT_CELL, "（无）本轮没有配置快照")
        warnings.append("本轮没有配置快照，判定明细页「配置快照摘要」如实写「（无）」")

    # 本轮产物清单：有则写 kind（与 report_workbook 的取值口径一致），无则写「（无）」
    kinds = set(data.artifact_kinds or [])
    missing_artifacts: list[str] = []
    for kind, coord in DETAIL_ARTIFACT_CELLS.items():
        if kind in kinds:
            _write(ws, coord, kind)
        else:
            _write(ws, coord, "（无）")
            missing_artifacts.append(ARTIFACT_LABEL.get(kind, kind))
    if missing_artifacts:
        warnings.append("本轮未落这些产物，产物清单如实写「（无）」：" + "、".join(missing_artifacts))
    extra_kinds = sorted(kinds - set(DETAIL_ARTIFACT_CELLS))
    if extra_kinds:
        warnings.append(
            "本轮产物里有、但模板清单没有对应行（未写入报告）：" + "、".join(extra_kinds)
        )


def _ensure_data_sheet(wb) -> Any:
    """取/建「本次图表数据」隐藏页（不覆盖同名的原实例数据页）。"""
    if DATA_SHEET_NEW in wb.sheetnames:
        ws_data = wb[DATA_SHEET_NEW]
        ws_data.sheet_state = "hidden"
        return ws_data
    ws_data = wb.create_sheet(DATA_SHEET_NEW)
    ws_data.sheet_state = "hidden"
    return ws_data


def _fill_trend_page(
    wb,
    data: ReportFillData,
    run_short: str,
    *,
    chart_w_cm: float,
    chart_h_cm: float,
    warnings: list[str],
) -> tuple[int, float]:
    """趋势图页：数据点数 + 两版位插图 + 图注。返回 (插图数, 行高增加量)。"""
    ws = wb[SHEET_TREND]
    trend = ((data.chart_data or {}).get("trend") or [])
    charts_added = 0
    grown = 0.0

    if not trend:
        _write(ws, TREND_COUNT_CELL, "（无）")
        for slot in TREND_SLOTS:
            _append_title_note(ws, slot["title"], "无：本轮没有趋势数据")
            _fill_caption(ws, slot["caption"], DASH, f"（无）轮次 {run_short}")
        warnings.append("本轮没有趋势数据（未找到 events.jsonl 或其中无采集记录），趋势图页如实写「（无）」")
        return 0, 0.0

    ws_data = _ensure_data_sheet(wb)
    ref = report_charts.write_trend_block(ws_data, 1, trend)
    _write(ws, TREND_COUNT_CELL, f"{len(trend)} 个采集点（源：本轮 events.jsonl 逐次采集）")

    has = ref.get("has_data") or {}
    # 版位判定必须与 build_trend_chart 内部的建图条件**同口径**：
    #   图一 = 占空比两列或转速列有数据；图二 = 电压或电流列有数据。
    slot_ok = (
        bool(has.get("cmd_duty") or has.get("meas_duty") or has.get("rpm")),
        bool(has.get("voltage_v") or has.get("current_v")),
    )
    charts = report_charts.build_trend_chart(
        ws_data, ref, width_cm=chart_w_cm, height_cm=chart_h_cm
    )
    expect = [i for i, ok in enumerate(slot_ok) if ok]
    if len(charts) != len(expect):
        # 数量对不上就一张都不插：宁缺，也不错位（错位的图比没图更糟）
        warnings.append(
            f"趋势图版位与生成张数不一致（预期 {len(expect)} 张、实得 {len(charts)} 张）：本次不插入趋势图，避免错位"
        )
        for slot in TREND_SLOTS:
            _append_title_note(ws, slot["title"], "无：版位校验未通过")
            _fill_caption(ws, slot["caption"], DASH, f"（无）轮次 {run_short}")
        return 0, 0.0

    for idx, chart in zip(expect, charts):
        slot = TREND_SLOTS[idx]
        _rewrite_title(ws, slot["title"])
        ws.add_chart(chart, slot["anchor"])
        anchor_row = int(slot["anchor"][1:])
        caption_row = int(slot["caption"][1:])
        grown += _fit_rows(ws, anchor_row, caption_row - 1, chart_h_cm * PT_PER_CM)
        charts_added += 1
        src = f"本轮采集记录（events.jsonl） · 轮次 {run_short}"
        if not _fill_caption(ws, slot["caption"], CAPTION_REQ.get(slot["key"], DASH), src):
            warnings.append(f"图注占位形态与预期不符，未替换：{SHEET_TREND}!{slot['caption']}")

    # 没出图的版位：标题如实标注原因（不删标题、不伪造图）
    for idx, ok in enumerate(slot_ok):
        if ok:
            continue
        slot = TREND_SLOTS[idx]
        _append_title_note(ws, slot["title"], "无：该组数据整列为空白")
        _fill_caption(ws, slot["caption"], DASH, f"（无）轮次 {run_short}")
        warnings.append(f"趋势图 {slot['key']} 整列无数据，未出图（报告内已如实标注）")

    skip = report_charts.trend_skip_notes(ref)
    if skip:
        warnings.append("趋势图未出系列：" + "；".join(skip))
    return charts_added, grown


def _fill_wave_page(
    wb,
    data: ReportFillData,
    run_short: str,
    *,
    chart_w_cm: float,
    chart_h_cm: float,
    trend_rows: int,
    warnings: list[str],
) -> tuple[int, float]:
    """波形页：4 处采集来源 + 8 版位插图 + 8 行图注。返回 (插图数, 行高增加量)。"""
    ws = wb[SHEET_WAVE]
    waves = ((data.chart_data or {}).get("waves") or {})
    src_text = f"示波器采集 CSV · 轮次 {run_short}"

    # 块头「采集来源」：只替换占位，其余原文保留
    for row in WAVE_SOURCE_ROWS:
        cur = ws.cell(row=row, column=1).value
        if isinstance(cur, str) and WAVE_SOURCE_PLACEHOLDER in cur:
            ws.cell(row=row, column=1).value = cur.replace(
                WAVE_SOURCE_PLACEHOLDER, WAVE_SOURCE_PREFIX + src_text
            )
        else:
            warnings.append(f"波形页第 {row} 行的「采集来源」占位形态与预期不符，未替换")

    if not (waves.get("channels")):
        for slot in WAVE_SLOTS:
            _append_title_note(ws, slot["title"], "无：本轮没有可用波形数据")
            _fill_caption(ws, slot["caption"], DASH, f"（无）轮次 {run_short}")
        warnings.append("本轮没有可用的波形数据（未做示波器采集或采集文件缺失），波形页如实写「（无）」")
        return 0, 0.0

    ws_data = _ensure_data_sheet(wb)
    # 波形数据块排在趋势块下方（与 report_workbook 的排布口径一致：+2 行间隔）
    info = report_charts.write_wave_block(ws_data, trend_rows + 3, waves)

    charts_added = 0
    grown = 0.0
    for i, slot in enumerate(WAVE_SLOTS, start=1):
        key = f"wave{i}"
        chart = report_charts.build_wave_chart(
            ws_data,
            info,
            int(slot["ch"]),
            kind=str(slot["kind"]),
            width_cm=chart_w_cm,
            height_cm=chart_h_cm,
        )
        if chart is None:
            why = (
                "本轮未采集到该通道"
                if str(slot["ch"]) not in info
                else "放大窗口点数不足，未出图"
            )
            _append_title_note(ws, slot["title"], f"无：{why}")
            _fill_caption(ws, slot["caption"], DASH, f"（无）轮次 {run_short}")
            warnings.append(f"波形图 CH{slot['ch']}（{slot['kind']}）未出图：{why}")
            continue
        _rewrite_title(ws, slot["title"])
        ws.add_chart(chart, slot["anchor"])
        anchor_row = int(slot["anchor"][1:])
        caption_row = int(slot["caption"][1:])
        grown += _fit_rows(ws, anchor_row, caption_row - 1, chart_h_cm * PT_PER_CM)
        charts_added += 1
        if not _fill_caption(ws, slot["caption"], CAPTION_REQ.get(key, DASH), src_text):
            warnings.append(f"图注占位形态与预期不符，未替换：{SHEET_WAVE}!{slot['caption']}")
    return charts_added, grown


def _adjust_summary_sheet(ws, data: ReportFillData, warnings: list[str]) -> int:
    """按用户口径处理「报告概要」页（其余原实例内容一律不动）。

    该页是模板带来的**上一轮实例**（用户已确认「保留原实例」），但下列几处
    用户明确要求改（2026-10-13）：

      ① **同步本轮表头**到汇总区的机型/项目名称/固件版本/Inlet/Bootloader/Outlet
         （用户原话：「报告封面已经拿到表头数据了，报告概要还没改」）；
      ② 判定明细里「本台架不适用」的**结论格留空**——只清结论，判据 ID 与名称保留；
      ③ 判定汇总的「本台架不适用」**整行删除**，并让其下三行**整体上移**补齐
         （用户追加口径：「第 21 行不要留空行」）；
      ④ 通过率口径说明**缩短**为一句公式。

    返回留空的结论格数量。

    ⚠️ 只认「**整格文本恰好等于**『本台架不适用』」的格：
    概要页口径说明长句里含该词组，属**子串**，绝不能被清掉
    ——这正是必须用精确相等、不能用 `in` 的原因。
    ⚠️ 明细行只在**结论列（C 列）**清；判据 ID（A）与名称（B）不动。
    ⚠️ 上移只搬运**值**（不动行高/格式）：概要页无合并区，行高由行维度统一控制，
    「人工判定/数据来源/说明」三行格式相近，搬运值即得到正确的表。
    """
    # ⓪ 报告来源 / 数据来源两行的文案（用户口径 2026-10-13）
    # 报告来源：模板原实例写「系统内置模板」→ 改「标准版」
    if ws[SUMMARY_SHEET_SOURCE_CELL].value is not None:
        ws[SUMMARY_SHEET_SOURCE_CELL] = SUMMARY_SHEET_SOURCE_TEXT
    # 数据来源：模板原实例写「后端判定（权威）」→ 改「后端判定」（去「（权威）」）。
    # ⚠️ 必须在**删行上移之前**按标签找，否则行号会漂。
    src_row_found: int | None = None
    for r in range(1, 30):
        if str(ws.cell(row=r, column=1).value or "").strip() == SUMMARY_SHEET_DATA_SOURCE_LABEL:
            src_row_found = r
            break
    if src_row_found is not None:
        ws.cell(row=src_row_found, column=2).value = SUMMARY_SHEET_DATA_SOURCE_TEXT
    else:
        warnings.append(
            f"「报告概要」页未找到「{SUMMARY_SHEET_DATA_SOURCE_LABEL}」标签行，该行文案未按口径改写"
        )

    # ① 同步本轮表头（模板 B 列为值位）
    synced = 0
    for key, row in SUMMARY_SHEET_HEADER.items():
        label = str(ws.cell(row=row, column=1).value or "").strip()
        expect = SUMMARY_SHEET_HEADER_LABEL.get(key, "")
        if label != expect:
            # 行位与预期不符：不动它（宁可少改，也不错位搬到别的字段上）
            warnings.append(
                f"「报告概要」第 {row} 行标签为「{label}」、预期「{expect}」，{expect}未同步"
            )
            continue
        val = data.header.get(key)
        ws.cell(row=row, column=2).value = (
            _to_simplified(str(val)) if val not in (None, "") else HEADER_MISSING_TEXT
        )
        synced += 1
    if synced:
        warnings.append(f"「报告概要」页汇总区的表头已同步本轮数据（{synced} 项）")

    # ③ 判定汇总「本台架不适用」整行删除 + 其后三行整体上移（不留空行）
    row_na = SUMMARY_SHEET_UNAPPLICABLE_ROW
    ws.cell(row=row_na, column=1).value = None
    ws.cell(row=row_na, column=2).value = None
    for src_row in SUMMARY_SHEET_SHIFT_ROWS:
        ws.cell(row=src_row - 1, column=1).value = ws.cell(row=src_row, column=1).value
        ws.cell(row=src_row - 1, column=2).value = ws.cell(row=src_row, column=2).value
        ws.cell(row=src_row, column=1).value = None
        ws.cell(row=src_row, column=2).value = None

    # ④ 口径说明缩短（上移后落在第 23 行）
    ws.cell(row=SUMMARY_SHEET_NOTE_ROW, column=2).value = SUMMARY_SHEET_NOTE

    # ② 明细里「本台架不适用」结论格留空（精确相等 + 仅 C 列）
    blanked = 0
    for row in ws.iter_rows(min_col=3, max_col=3):
        for c in row:
            if isinstance(c.value, str) and c.value.strip() == STATE_CN["not_applicable"]:
                c.value = None
                blanked += 1
    warnings.append(
        f"「报告概要」页：表头同步 {synced} 项、判定明细 {blanked} 处「本台架不适用」结论留空、"
        "汇总的「本台架不适用」整行已删除（其后各行上移、不留空行）、"
        f"口径说明缩短为「{SUMMARY_SHEET_NOTE}」"
    )
    return blanked


def fill_report_template(
    template_path: Path,
    dest: Path,
    data: ReportFillData,
    *,
    chart_w_cm: float = DEFAULT_CHART_W_CM,
    chart_h_cm: float = DEFAULT_CHART_H_CM,
) -> dict[str, Any]:
    """以模板为基底填充本轮数据并插图，保存到 `dest`。

    返回 `{"status", "pages_filled", "charts", "row_growth_pt", "warnings"}`。

    失败语义（由调用方 `reports.py` 转成 blocked）：
      · 模板不存在 → `FileNotFoundError`（如实报「模板未就绪」，不降级成别的版式）；
      · 模板缺页 / 判据行结构异常 → `RuntimeError`（宁可挡住，也不出一份错版报告）；
      · 落盘后仍有「待填写」残留 → `RuntimeError`（把残留坐标全部列出）。
    """
    tpl = Path(template_path)
    if not tpl.is_file():
        raise FileNotFoundError(
            f"系统内置报告模板不存在：{tpl}\n"
            f"  排查：① 确认该文件已随代码交付；② 或用 .env 的 BUILTIN_REPORT_TEMPLATE 覆盖路径。"
        )

    # keep_vba=True：模板是 .xlsm（宏启用格式），原样保留其包结构
    wb = load_workbook(str(tpl), keep_vba=True)
    required = (SHEET_COVER, SHEET_DETAIL, SHEET_TREND, SHEET_WAVE, SHEET_SUMMARY, SHEET_DATA_OLD)
    missing = [s for s in required if s not in wb.sheetnames]
    if missing:
        raise RuntimeError(f"报告模板缺少工作表：{'、'.join(missing)}（当前页：{'、'.join(wb.sheetnames)}）")

    warnings: list[str] = []
    generated_at = data.generated_at or _now_text()
    run_short = (data.run_id or "")[:8]

    # 三页第 3 行的填写说明统一删除（用户口径 2026-10-13）：
    # 「空白填写模板｜原测试参数逐项继承；原报告实例在「报告概要」中留存」——
    # 它是写给填写人的指引，不是报告内容，纸面上不该出现。
    for sheet_name, coord in TEMPLATE_HINT_CELLS:
        ws_hint = wb[sheet_name]
        if isinstance(ws_hint[coord].value, str) and ws_hint[coord].value.strip():
            ws_hint[coord] = None

    _fill_cover(wb[SHEET_COVER], data, generated_at, warnings)
    _fill_detail(wb[SHEET_DETAIL], data, warnings)
    # 「报告概要」页：整体保留原实例，只按用户口径调整三处（不适用明细留空、
    # 汇总的不适用整行删除、口径说明缩短）
    _adjust_summary_sheet(wb[SHEET_SUMMARY], data, warnings)

    trend_charts, trend_grown = _fill_trend_page(
        wb, data, run_short,
        chart_w_cm=chart_w_cm, chart_h_cm=chart_h_cm, warnings=warnings,
    )
    trend_rows = len(((data.chart_data or {}).get("trend") or []))
    wave_charts, wave_grown = _fill_wave_page(
        wb, data, run_short,
        chart_w_cm=chart_w_cm, chart_h_cm=chart_h_cm,
        trend_rows=trend_rows, warnings=warnings,
    )

    # 图注/采集来源里引用的来源说明（供调用方写进返回体，便于对账）
    warnings.extend(
        f"图表数据采集侧提示：{w}" for w in ((data.chart_data or {}).get("warnings") or [])
    )

    # ── 落盘前自检：四页里不许再有「待填写」
    left = _iter_placeholders(wb)
    if left:
        raise RuntimeError(
            "报告模板仍有未填写的占位（拒绝产出半成品报告）：" + "、".join(left)
        )

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(dest))
    # 守住 .xlsm 的主内容类型（openpyxl 在「模板无宏部件」时会写成 xlsx 类型，
    # 扩展名与内容类型不符会让 Excel 报「格式与扩展名不符」）
    ct_patched = _preserve_main_content_type(tpl, dest)

    return {
        "status": "ok",
        "pages_filled": [SHEET_COVER, SHEET_DETAIL, SHEET_TREND, SHEET_WAVE],
        "charts": trend_charts + wave_charts,
        "row_growth_pt": round(trend_grown + wave_grown, 2),
        "content_type_patched": ct_patched,
        "warnings": warnings,
    }
