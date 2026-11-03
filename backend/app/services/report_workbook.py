"""报告 xlsm 生成（2026-09-28 新增；2026-10-10 升格为正式产出）。

## 这个模块现在是什么

本模块产出的 xlsm **就是正式报告**（2026-10-10 用户拍板：系统内置模板即客户认可的
正式报告模板，不再有「客户模板替换」这条链路）。

口径变更的来龙去脉（重要，别按旧注释理解代码）：

| 时间 | 口径 | 产物身份 |
|---|---|---|
| 2026-09-28 ~ 2026-10-09 | 「模板缺失」一档用本模块补一份看得见的文件 | **占位件**：文件名带 placeholder、首行琥珀横幅、接口 status=placeholder |
| **2026-10-10 起** | **本模块即正式报告的唯一产出路径** | **正式报告**：文件名 `report-<id>.xlsm`、无横幅、status=ok |

- 首行那条琥珀「可替换」横幅**已按用户要求删除**（原话：这份就是客户模板，不再需要替换提示）。
- 历史遗留的 `report-<id>.placeholder.xlsm` 仍可下载（`reports.py` 的下载兜底顺序保留），
  但**新生成的报告一律用正式名**。

## 客户模板通路（保留但不默认走）

`writeFile_rust` 那条路仍在 `reports.py` 里：**只有用户真的上传了客户模板**才会走。
它需要客户模板 .xlsm 与填充程序 `write-file-rust.exe` 同时到位；缺程序时如实报 `blocked`，
**不静默降级**成系统内置模板（那会让人以为拿到的是客户模板版式）。

## 为什么不用 openpyxl 去模仿客户模板版式

`writeFile_rust/README.md` 说明了客户模板自带 VBA 宏、多工作表（LV/SV/HV 測試波型）
与特定单元格映射；这些**只能从模板继承**，凭空造不出来。本模块因此只做
「忠实呈现本轮真实数据」这一件事：不模仿客户版式、不改写任何判定结论。

## 繁体处理（用户口径「一律用中文，繁体进行优化」）

- 工作表名 / 表头 / 标签一律**简体**；
- 数据值里若含繁体（来自模板原文或场景包旧字段），经 `_to_simplified` 归一。

⚠️ 这与 `c/web/DESIGN.md` 第 10.7 节的「模板原文只在报告预览纸面按原样出现」
**口径不同**：那条约束的是**前端预览的纸面**，本模块产出的是**独立文件**，
用户明确要求全中文简体。两处不冲突（不同产物），但**改任一处前先看清是哪一处**。

## 依赖

只用 `openpyxl`（后端**已有** 3.1.5，实测无需新增依赖）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.services import report_charts

# ---------------------------------------------------------------- 常量

#: 工作表名（简体；客户模板里是「LV 測試波型」这种繁体名）
SHEET_MAIN = "报告概要"

#: 产物种类的中文名。与前端 `flow-report/assemble.ts` 的 `ARTIFACT_LABEL` 同口径，
#: 未知 kind 原样显示（不编中文名）。
ARTIFACT_LABEL: dict[str, str] = {
    "config-snapshot": "配置快照",
    "requirement-baseline": "需求基线",
    "run-artifact": "轮次产物包",
    "verdict-table": "判定结果表",
    "gap-list": "未达标项清单",
    "param-change": "参数改动版本",
    "report-instance": "报告实例",
}

#: 表头字段的中文名（简体）。模板原文是繁体（客戶名稱 / 韌體版本），
#: 用户要求报告一律简体，故在此显式映射——**不做通用繁简转换**（见 `_to_simplified` 说明）。
HEADER_LABEL: dict[str, str] = {
    "model": "机型",
    "project_name": "项目名称",
    "firmware_version": "固件版本",
    "inlet_start_addr": "Inlet 起始位址",
    "outlet_start_addr": "Outlet 起始位址",
    "bootloader": "Bootloader",
    "customer_name": "客户名称",
    "customer_engineer": "客户工程师",
    "email": "Email",
    "phone": "联系电话",
}


# ---------------------------------------------------------------- 繁简归一

#: 常用繁体 → 简体的**逐字映射**。
#:
#: ⚠️ 为什么只做逐字映射、不引第三方库：
#:   ① 依赖纪律——后端已锁定依赖清单，为一个显示需求引 `opencc` 不划算；
#:   ② 项目里前端同类需求（`c/web/src/features/shared/zh.ts` 的 `simp()`）**也是逐字映射**，
#:      口径保持一致，两处改一起改。
#: 覆盖范围：项目里**实际出现过**的繁体字（模板字段、场景包文案、工作表名）。
_S2T: dict[str, str] = {
    "稱": "称", "電": "电", "壓": "压", "轉": "转", "速": "速", "測": "测",
    "試": "试", "波": "波", "型": "型", "韌": "韧", "體": "体", "聯": "联",
    "繫": "系", "話": "话", "戶": "户", "員": "员", "產": "产", "項": "项",
    "規": "规", "範": "范", "設": "设", "計": "计", "參": "参", "數": "数",
    "結": "结", "論": "论", "報": "报", "告": "告", "樣": "样", "張": "张",
    "錄": "录", "檔": "档", "軟": "软", "執": "执", "啟": "启", "動": "动",
    "過": "过", "程": "程", "驗": "验", "證": "证", "確": "确", "認": "认",
    "檢": "检", "環": "环", "節": "节", "點": "点", "線": "线", "馬": "马",
    "達": "达", "軸": "轴", "極": "极", "對": "对", "頻": "频", "率": "率",
    "載": "载", "諧": "谐", "誤": "误", "差": "差", "範": "范", "圍": "围",
    "值": "值", "單": "单", "位": "位", "態": "态", "監": "监", "護": "护",
    "觸": "触", "發": "发", "溫": "温", "興": "兴", "業": "业", "務": "务",
    "術": "术", "機": "机", "構": "构", "處": "处", "顯": "显", "示": "示",
}


def _to_simplified(s: str) -> str:
    """把字符串里的繁体字按 `_S2T` 逐字换成简体。

    未登记的字符原样保留——**宁可少转，不可错转**。
    少数繁体字与简体字是「一词多形」或香港用字（如「著/着」「裡/里」），
    机械替换会出错，所以不放进表里；这类靠上面的 `HEADER_LABEL` 显式命名兜住。
    """
    return "".join(_S2T.get(c, c) for c in s)


def _fmt_rate(rate: Any) -> str:
    """通过率显示（本模块唯一出口，与前端 `assemble.ts:fmtPassRate` 同口径）：

      无判定数据 → 「—」；整数值 → 「100%」；非整数 → 保留 1 位小数（「66.7%」）。

    ⚠️ 分母为 0（入参是 `None`）时**不许写成 0%**：0% 会被读成「全不通过」，
    与实际语义完全相反。缺数就如实写「—」，并由调用方在下一行说明为什么没有这个数。

    ⚠️ 也不做「四舍五入成假整数」：66.6% 不许写成 67%。
    """
    if not isinstance(rate, (int, float)) or isinstance(rate, bool):
        return "—"
    pct = float(rate) * 100
    if abs(pct - round(pct)) < 1e-9:
        return f"{round(pct)}%"
    return f"{pct:.1f}%"


# ---------------------------------------------------------------- 样式

_TITLE_FONT = Font(name="微软雅黑", size=14, bold=True, color="1F2A24")
_LABEL_FONT = Font(name="微软雅黑", size=10, bold=True, color="5B6B62")
_VALUE_FONT = Font(name="微软雅黑", size=10, color="1F2A24")
_SECTION_FONT = Font(name="微软雅黑", size=11, bold=True, color="2E5E45")

#: 通过率专用字体（2026-10-10 编号 4 美化）：判定汇总**第一行**要压得住版面，
#: 用 14px 墨绿加粗与前端报告页「通过率大号数字」同一口径。
_LEAD_FONT = Font(name="微软雅黑", size=14, bold=True, color="2E5E45")

_FILL_HEAD = PatternFill("solid", fgColor="EAF2EC")
_FILL_ZEBRA = PatternFill("solid", fgColor="FBFCFB")

# ── 判定明细里的「不通过」降权（2026-10-10 编号 4 美化） ──
#
# ⚠️ 为什么不用正红 #A6353A：一页里出现多处正红，报告会被读成「报错单」，
# 与「绿为主、灰为辅、红降权」的口径冲突（效果图已确认）。
# 改为浅陶土底 + 深陶土字 + 左侧陶土细色条——保留可读性与警示性，但不刺眼。
# ⚠️ 判定状态**文字**仍是「不通过」原词，降的是颜色不是措辞。
_FILL_FAIL = PatternFill("solid", fgColor="FBF4F3")
_FAIL_FONT = Font(name="微软雅黑", size=10, color="97504B")
_FAIL_BAR = Side(style="thick", color="C58F8B")

_THIN = Side(style="thin", color="E3E8E4")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_FAIL_BORDER = Border(left=_FAIL_BAR, right=_THIN, top=_THIN, bottom=_THIN)

_WRAP = Alignment(vertical="top", wrap_text=True)
_LEFT = Alignment(vertical="center", horizontal="left")


# ---------------------------------------------------------------- 主体


def build_report_workbook(
    *,
    run_id: str,
    header: dict[str, str],
    missing_header_keys: list[str],
    verdict: dict[str, Any] | None,
    verdict_items: list[dict[str, Any]] | None = None,
    artifact_kinds: list[str],
    snapshot_counts: dict[str, int] | None,
    source_note: str,
    output: Path,
    chart_data: dict[str, Any] | None = None,
) -> Path:
    """生成报告 xlsm，写到 `output`，返回该路径。

    ⚠️ 函数名 2026-10-10 由 `build_placeholder_workbook` 改为现名：产出的文件
    **就是正式报告**（用户拍板：系统内置模板即客户认可的正式模板），不再是「占位件」。

    入参全部是**已装配好的真题数据**（由 `reports.py` 从轮次产物里取），
    本函数**不读库、不猜值**：缺的字段就写「由上游带入（未提供）」，绝不编。

    Args:
        run_id: 轮次号（写进文件，便于与库中记录对应）
        header: 表头字段 → 值（只含取到的）
        missing_header_keys: 未取到的表头字段 key（显示为「未提供」）
        verdict: 判定汇总 `{total,pass,fail,missing,not_applicable,manual,pass_rate,authoritative}`。
            `pass_rate` 是 B 口径通过率（0~1）；分母为 0 时上游给 `None`，
            本函数显示「—」并补一行口径说明。None = 本轮**没有判定数据**（另一回事）。
            `not_applicable` / `manual` 各有值时单独成行，让总数能对上账。
        verdict_items: 逐条判定 `[{req_id,name,state}]`（2026-10-10 编号 4 美化新增）。
            「三、判定明细」一节据此渲染，让「哪几条判了什么」在纸面上一眼可见；
            空列表或 None 时该节仍出现（写「（无）」），以保持分节序号稳定。
        artifact_kinds: 该轮实际有的产物 kind 列表
        snapshot_counts: 配置快照的三类计数 `{本体属性,控制参数,报告表头}`
        source_note: 「报告来源」一行写什么（如「系统内置模板」）。**如实填**，
            不要写成自我表扬的话；这一行是给人核对出处用的。
        output: 输出路径（父目录会自动创建）
        chart_data: 报告图表数据（2026-10-12 新增，`report_charts.collect` 的产出）。
            `{"trend": [...折点...], "waves": {...}, "warnings": [...]}`。
            None 或缺数据时，「六、趋势图」「七、波形图」两节如实写「（无）」，
            **不产出空白图表**；图表数据落在隐藏数据表 `_图表数据` 里可审计。
    """
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_MAIN

    col_a_width = 22
    col_b_width = 52
    ws.column_dimensions[get_column_letter(1)].width = col_a_width
    ws.column_dimensions[get_column_letter(2)].width = col_b_width
    # 第三列只给「判定明细」的名称用（其余各节都是两列）
    ws.column_dimensions[get_column_letter(3)].width = 40

    r = 1  # 行游标

    # ── ① 标题与轮次信息
    # 原首行那条琥珀「可替换」横幅已于 2026-10-10 **按用户要求删除**：
    # 本模板即客户认可的正式报告模板，不再有「可替换」这层意思。
    ws.cell(row=r, column=1, value="测试报告").font = _TITLE_FONT
    r += 1
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    for label, value in (
        ("轮次号", run_id),
        ("生成时间", now),
        ("报告状态", "正式报告"),
        ("报告来源", _to_simplified(source_note)),
    ):
        ws.cell(row=r, column=1, value=label).font = _LABEL_FONT
        ws.cell(row=r, column=2, value=value).font = _VALUE_FONT
        ws.cell(row=r, column=2).alignment = _WRAP
        r += 1
    r += 1

    # ── ③ 报告表头（来自 config-snapshot）
    r = _section(ws, r, "一、报告表头")
    order = list(header.keys())
    # 未取到的排后面，且**按模板字段顺序**显示——不按字典序，人读起来才是模板的顺序
    for k, v in header.items():
        r = _kv(ws, r, HEADER_LABEL.get(k, k), _to_simplified(str(v)))
    for k in missing_header_keys:
        r = _kv(ws, r, HEADER_LABEL.get(k, k), "由上游带入（未提供）", muted=True)
    if not order and not missing_header_keys:
        r = _kv(ws, r, "（无）", "本轮没有任何表头字段", muted=True)
    r += 1

    # ── ④ 判定汇总
    r = _section(ws, r, "二、判定汇总")
    if verdict:
        # 通过率排第一行（2026-10-10 需求单编号 3）：这是看报告的人最先要的那个数。
        # 分母为 0 时 _fmt_rate 给「—」，并补一行口径说明，绝不写成 0%。
        rate = verdict.get("pass_rate")
        # 14px 墨绿加粗（改动点 ①）：与前端报告页的「通过率大号数字」同一口径
        r = _kv(ws, r, "通过率", _fmt_rate(rate), value_font=_LEAD_FONT)
        if rate is None:
            r = _kv(
                ws,
                r,
                "通过率口径",
                "本轮没有可判定的「通过/不通过」项，因此暂不给出通过率"
                "（「未采集」与「本台架不适用」都不计入分母）",
                muted=True,
            )
        r = _kv(ws, r, "判据总数", str(verdict.get("total", 0)))
        r = _kv(ws, r, "通过", str(verdict.get("pass", 0)))
        r = _kv(ws, r, "不通过", str(verdict.get("fail", 0)))
        # 「未采集」单独一行并加说明：它**不是**「不通过」，
        # 混在一起会让人以为「没测的就是不合格」
        r = _kv(ws, r, "未采集", str(verdict.get("missing", 0)))
        # 「本台架不适用」与「人工判定」各自成行，**有才显示**（2026-10-10 随通过率一并补）。
        # 为什么必须补：通过率的分母把这两类排除了，报告里若看不见它们，
        # 「判据总数 34、通过 + 不通过才 8」会被读成「少了 26 条没交代」。
        # 0 条时不占版面，不制造噪音。
        if verdict.get("not_applicable"):
            r = _kv(ws, r, "本台架不适用", str(verdict["not_applicable"]))
        if verdict.get("manual"):
            r = _kv(ws, r, "人工判定", str(verdict["manual"]))
        r = _kv(
            ws,
            r,
            "数据来源",
            "后端判定（权威）" if verdict.get("authoritative") else "前端预览（非权威）",
        )
        ws.cell(row=r, column=1, value="说明").font = _LABEL_FONT
        ws.cell(
            row=r,
            column=2,
            value="通过率 = 通过 ÷（通过 + 不通过），「未采集」与「本台架不适用」均不计入分母。"
            "「未采集」也不等于「不通过」：这些判据所需的现场实测量本轮一条都没采到，"
            "因此既判不出通过也判不出不通过。",
        ).font = _VALUE_FONT
        ws.cell(row=r, column=2).alignment = _WRAP
        r += 2
    else:
        r = _kv(ws, r, "（无）", "本轮没有判定数据（未产出判定结果表）", muted=True)
        r += 1

    # ── ⑤ 判定明细（2026-10-10 编号 4 美化新增，改动点 ⑥）
    #
    # 为什么要有这一节：上面只给了五类**计数**。客户拿到纸面时看不到「哪几条判了什么」，
    # 而判据总数与通过数之间隔着未采集 / 不适用 / 人工，要逐条才能核对。
    # 逐条列出 判据 / 名称 / 结论；结论文字取自 STATE_CN，与前端逐字一致。
    #
    # ⚠️ 与其余各节同一口径：**永远出现**（空则写「（无）」）。
    # 不写「有才显示」——那会让分节序号随数据跳号（二 → 四），
    # 「第几节」就失去了指代意义，引用与核对都会错位。
    r = _section(ws, r, "三、判定明细")
    if verdict_items:
        r = _detail_head(ws, r)
        for i, it in enumerate(verdict_items):
            if isinstance(it, dict):
                r = _detail_row(ws, r, it, zebra=(i % 2 == 1))
    else:
        r = _kv(ws, r, "（无）", "本轮没有判定数据", muted=True)
    r += 1

    # ── ⑥ 配置快照摘要
    r = _section(ws, r, "四、配置快照摘要")
    if snapshot_counts:
        for k, v in snapshot_counts.items():
            r = _kv(ws, r, k, f"{v} 项")
    else:
        r = _kv(ws, r, "（无）", "本轮没有配置快照", muted=True)
    r += 1

    # ── ⑦ 产物清单
    r = _section(ws, r, "五、本轮产物清单")
    if artifact_kinds:
        for k in artifact_kinds:
            r = _kv(ws, r, ARTIFACT_LABEL.get(k, k), k, muted=True)
    else:
        r = _kv(ws, r, "（无）", "本轮没有落任何产物", muted=True)
    r += 1

    # ── ⑧ 趋势图与波形图（2026-10-12 新增：报告自带图表）
    #
    # 「在报告中会自带生成的趋势图和波形图」（用户需求原话）。
    # 图表的生成方式、数据来源与「为什么用 Excel 原生图表而非 PNG」见
    # `report_charts` 模块头。这里只负责排版与锚定：
    #   · 图表数据落在一张**隐藏数据表**（_图表数据）里——可审计、可复算；
    #   · 图表是活对象：客户在 Excel 里悬停即可读点、可缩放；
    #   · 没数据时如实写「（无）」+ 原因，**不产出空白图表**。
    #
    # 行推进按图表物理高度估算（行高 15pt ≈ 0.53cm）：
    #   趋势图 8.5cm ≈ 16 行 → 留 18 行；波形图 7cm ≈ 13 行 → 留 15 行。
    _TREND_CHART_ROWS = 18
    _WAVE_CHART_ROWS = 15

    trend = (chart_data or {}).get("trend") or []
    waves = (chart_data or {}).get("waves") or {}
    chart_warnings = list((chart_data or {}).get("warnings") or [])

    data_ws = None  # 隐藏数据表（有图才建）
    data_row = 1

    r = _section(ws, r, "六、趋势图")
    if trend:
        if data_ws is None:
            data_ws = wb.create_sheet(report_charts.DATA_SHEET)
            data_ws.sheet_state = "hidden"
        ref = report_charts.write_trend_block(data_ws, data_row, trend)
        data_row += len(trend) + 2
        r = _kv(ws, r, "数据点数", f"{len(trend)} 个采集点（源：本轮 events.jsonl 逐次采集）")
        # 纵轴口径**按实际出的图生成**（空列不再被写进说明，避免"说明里有、图里没有"）
        r = _kv(ws, r, "纵轴口径", report_charts.trend_axis_note(ref))
        r = _kv(ws, r, "缺测口径", "未采到的点为空白（图上断线），不补 0、不插值。", muted=True)
        # 整列无数据的系列不绘图，但**必须写明**——否则读者会把"没采到"读成"值为 0"
        skip_notes = report_charts.trend_skip_notes(ref)
        if skip_notes:
            r = _kv(ws, r, "未出图说明", "；".join(skip_notes) + "（缺测不等于 0）", muted=True)
        trend_charts = report_charts.build_trend_chart(data_ws, ref)
        if not trend_charts:
            r = _kv(ws, r, "（无图）", "趋势数据每一列都是空白，无法成图（仅写入数据表备查）", muted=True)
        for c in trend_charts:
            ws.add_chart(c, f"A{r}")
            r += _TREND_CHART_ROWS
    else:
        r = _kv(ws, r, "（无）", "本轮没有趋势数据（未找到 events.jsonl 或其中无采集记录）", muted=True)
        r += 1

    r = _section(ws, r, "七、波形图")
    if waves.get("channels"):
        if data_ws is None:
            data_ws = wb.create_sheet(report_charts.DATA_SHEET)
            data_ws.sheet_state = "hidden"
        r = _kv(ws, r, "采集来源", str(waves.get("cycle") or "（未知）"))
        r = _kv(
            ws, r, "纵轴口径",
            "每通道两张图：前一张为**全程**（整采集窗），后一张为**放大**"
            "（时间范围更小、便于人眼读数）——"
            "PWM 三通道放大到 80 μs（≈2 个 25 kHz 周期，方波边沿完整展开），"
            "转速通道放大到 10 ms 并对准脉冲谷底（全程视图下脉冲只占宽度约 3%，肉眼难辨）。"
            "四通道量程差异大，故一通道一图（同轴会把小信号压平）；"
            "横轴单位按窗口自适应（μs/ms）。",
        )
        info = report_charts.write_wave_block(data_ws, data_row, waves)
        for c in report_charts.build_wave_charts(data_ws, info):
            ws.add_chart(c, f"A{r}")
            r += _WAVE_CHART_ROWS
    else:
        r = _kv(ws, r, "（无）", "本轮没有可用的波形数据（未做示波器采集或采集文件缺失）", muted=True)
        r += 1

    if chart_warnings:
        # 图表数据的诚实说明（缺文件/空文件等）——不吞、不美化。
        r = _kv(ws, r, "图表数据说明", "；".join(chart_warnings)[:500], muted=True)

    # ── 收尾：冻结标题行 + 页签色
    #
    # 原「六、如何换成正式报告」一节（列客户模板三步操作）已于 2026-10-10 **删除**：
    # 本模板即正式模板，报告里再写「怎么换成正式报告」自相矛盾。
    # 若将来真要用客户模板，操作留在这里备查（不再印进报告）：
    #   ① 把客户 .xlsm 放进 backend/uploads/report_templates/（或调 POST /api/reports/template 上传）；
    #   ② 把 write-file-rust.exe 放到 `reports.py` 的 WRITE_FILE_RUST 指向的位置；
    #   两者齐备时 generate_report 会自动改走 writeFile_rust，无需改代码。
    ws.freeze_panes = "A2"
    ws.sheet_properties.tabColor = "2E5E45"  # 墨绿：正式报告的页签色（原为琥珀，那是「占位件」标识）

    output.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output))
    return output


def _section(ws, row: int, title: str) -> int:
    """写一个分节标题，返回下一行行号。"""
    c = ws.cell(row=row, column=1, value=title)
    c.font = _SECTION_FONT
    c.fill = _FILL_HEAD
    ws.cell(row=row, column=2).fill = _FILL_HEAD
    return row + 1


def _kv(
    ws,
    row: int,
    key: str,
    value: str,
    *,
    muted: bool = False,
    value_font: Font | None = None,
) -> int:
    """写一行「标签 | 值」，返回下一行行号。

    `muted` 用浅灰，表示「这项没取到」；`value_font` 供个别需要**加大字号**的行使用
    （目前只有判定汇总的「通过率」），缺省即普通值字体。
    """
    kc = ws.cell(row=row, column=1, value=key)
    kc.font = _LABEL_FONT
    kc.alignment = _LEFT
    kc.border = _BORDER
    vc = ws.cell(row=row, column=2, value=value)
    vc.font = value_font or (
        Font(name="微软雅黑", size=10, color="9AA69F") if muted else _VALUE_FONT
    )
    vc.alignment = _WRAP
    vc.border = _BORDER
    return row + 1


#: 判定状态的中文（与前端 `flow-report/panel.tsx` 的 `STATE_TEXT` 逐字一致）。
#: ⚠️ 两端必须同词：判定的说法在屏幕与纸面上不许出现两种叫法。
STATE_CN: dict[str, str] = {
    "pass": "通过",
    "fail": "不通过",
    "missing": "未采集",
    "manual": "人工判定",
    "not_applicable": "本台架不适用",
}


def _detail_head(ws, row: int) -> int:
    """判定明细表头（改动点 ⑥）：浅墨绿底 + 中性字，与分节标题同一套体系。"""
    for col, text in ((1, "判据"), (2, "名称"), (3, "结论")):
        c = ws.cell(row=row, column=col, value=text)
        c.font = _LABEL_FONT
        c.fill = _FILL_HEAD
        c.border = _BORDER
    return row + 1


def _detail_row(ws, row: int, item: dict, *, zebra: bool) -> int:
    """判定明细一行（改动点 ⑥）。

    `fail` 行用「浅陶土底 + 左侧陶土细色条 + 深陶土结论字」，**不整行标红**；
    其余行走斑马纹。结论文字取自 `STATE_CN`，与前端逐字一致。
    """
    state = str(item.get("state") or "")
    is_fail = state == "fail"
    cells = (
        (1, str(item.get("req_id") or "—"), _VALUE_FONT),
        (2, _to_simplified(str(item.get("name") or "—")), _VALUE_FONT),
        (3, STATE_CN.get(state, state or "—"), _FAIL_FONT if is_fail else _VALUE_FONT),
    )
    for col, text, font in cells:
        c = ws.cell(row=row, column=col, value=text)
        c.font = font
        c.border = _BORDER
        if is_fail:
            c.fill = _FILL_FAIL
            if col == 1:
                c.border = _FAIL_BORDER
        elif zebra:
            c.fill = _FILL_ZEBRA
    return row + 1
