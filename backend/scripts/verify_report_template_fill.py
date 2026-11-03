"""离线验证：以模板为基底填充报告（`report_template_fill`）。

## 为什么要有这个脚本

`reports.py` 的正路是「DB 取轮次数据 → 找硬件运行目录 → 填模板」。跑一次真实生成
要起后端、发请求、还要有可用轮次；改一行填充逻辑都这样验太慢，而且**不好定位**。
本脚本把同一条装配链搬到离线：读库、找目录、收集图表数据，然后调填充器，
再对产物做**逐格比对**。

## 两种数据来源

1. `--run-id <flow 轮次号>`（**推荐，全真数据**）：走
   `_collect_report_data` + `_find_bench_run_dir` + `report_charts.collect`，
   与线上生成**同一条装配链**。
2. `--run-dir <硬件运行目录>`：只用真实采集数据练图表，
   判定/表头用**夹具**（明确标注，仅用于结构验证，不可当交付件）。

## 断言（任一不过即退出码 1）

- 产物存在、可被 openpyxl 打开，且仍是**宏启用格式**（.xlsm 主内容类型不变）；
- 五个可见工作表齐全（报告封面 / 判定明细 / 趋势图 / 波形与截图 / 报告概要）；
- 四页里**不再有**精确等于「待填写」的单元格；
- **无越界写入**：产物与模板的逐格差异必须落在写入白名单（映射表坐标 + 新隐藏页）内；
- 「报告概要」与「_图表数据」两页**逐格与模板一致**，且原 10 张图表仍在；
- 新图表张数与锚点正确（趋势页 ≤2、波形页 ≤8）；
- 缺数位置如实为「（无）/—」，不出现 0 冒充（抽查通过率与产物清单）。

用法：
    python scripts/verify_report_template_fill.py --run-id <flow_run_id>
    python scripts/verify_report_template_fill.py --run-dir hardware/v0.6/runs/<dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许以 `python scripts/xxx.py` 直接运行（把 backend/ 放进 sys.path）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openpyxl import load_workbook  # noqa: E402

from app.core.paths import C_DIR, builtin_report_template  # noqa: E402
from app.services import report_charts  # noqa: E402
from app.services import report_template_fill as fill  # noqa: E402

#: 产物与模板允许出现差异的单元格（写入白名单；其余任何差异都算越界）
ALLOWED_CELLS: dict[str, set[str]] = {
    fill.SHEET_COVER: set(fill.COVER_ID.values())
    | set(fill.COVER_HEADER.values())
    | set(fill.COVER_SUMMARY.values())
    # 封面：第 3 行说明删除位 + 通过率口径说明格（2026-10-13 用户口径）
    | {"A3", fill.COVER_NOTE_CELL},
    fill.SHEET_DETAIL: {f"G{r}" for r in range(fill.DETAIL_ROW_FIRST, fill.DETAIL_ROW_LAST + 1)}
    | {fill.DETAIL_SNAPSHOT_CELL}
    | set(fill.DETAIL_ARTIFACT_CELLS.values())
    # 判定明细页第 3 行说明删除位
    | {"A3"},
    fill.SHEET_TREND: {fill.TREND_COUNT_CELL}
    | {s["title"] for s in fill.TREND_SLOTS}
    | {s["caption"] for s in fill.TREND_SLOTS}
    # 趋势图页第 3 行说明删除位
    | {"A3"},
    fill.SHEET_WAVE: {f"A{r}" for r in fill.WAVE_SOURCE_ROWS}
    | {s["title"] for s in fill.WAVE_SLOTS}
    | {s["caption"] for s in fill.WAVE_SLOTS},
    # 「报告概要」页：原实例（用户口径「保留」）**只允许这几处**差异——
    # ① 报告来源 B5（改「标准版」）；
    # ② 汇总区第 8~13 行 B 列（本轮表头同步）；
    # ③ 汇总区第 21~24 行 A/B 列：删不适用行 + 其后各行上移（末行使原第 24 行清空）
    #    + 数据来源与口径说明改写；
    # ④ 判定明细结论列 C（不适用留空）。
    fill.SHEET_SUMMARY: {fill.SUMMARY_SHEET_SOURCE_CELL}
    | {f"B{r}" for r in fill.SUMMARY_SHEET_HEADER.values()}
    | {f"{col}{r}" for r in (21, 22, 23, 24) for col in ("A", "B")}
    | {f"C{r}" for r in range(21, 60)},
}

FAILED: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    mark = "OK  " if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f" —— {detail}" if detail else ""))
    if not ok:
        FAILED.append(label)


def values_of(wb) -> dict[str, object]:
    """全簿「页!格 → 值」快照（只取非空，够做差异比对）。"""
    out: dict[str, object] = {}
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.value is not None and str(c.value).strip() != "":
                    out[f"{ws.title}!{c.coordinate}"] = c.value
    return out


def build_data_from_db(run_id: str) -> tuple[fill.ReportFillData, str]:
    """全真数据：与 `reports.py` 的 `_self_built_report` 同一条装配链。"""
    from sqlmodel import Session, select

    from app.api.v1.reports import _collect_report_data, _find_bench_run_dir
    from app.db.session import engine
    from app.models.run import Run

    with Session(engine) as session:
        run = session.exec(select(Run).where(Run.run_id == run_id)).first()
        if run is None:
            raise SystemExit(f"轮次不存在：{run_id}")
        # scene_id 一并传：复刻线上「本轮无已确认表头 → 按场景回退」的行为
        data = _collect_report_data(session, run_id, run.scene_id)
        run_dir = _find_bench_run_dir(run_id, run.finished_at)

    chart_data = None
    note = "（无硬件运行目录：图表将为（无））"
    if run_dir is not None:
        chart_data = report_charts.collect(run_dir)
        note = f"硬件运行目录 {run_dir.name}（趋势 {len(chart_data['trend'])} 点）"
    src_run = data.get("header_source_run_id")
    if src_run and src_run != run_id:
        note += f"；表头回退自轮次 {src_run[:8]}"
    return (
        fill.ReportFillData(
            run_id=run_id,
            header=data.get("header") or {},
            missing_header_keys=data.get("missing_header_keys") or [],
            verdict=data.get("verdict"),
            verdict_items=data.get("verdict_items") or [],
            artifact_kinds=data.get("artifact_kinds") or [],
            snapshot_counts=data.get("snapshot_counts"),
            # 与生产路径同口径（用户 2026-10-13：「报告来源」写「系统内置模板：标准版」）
            source_note="系统内置模板：标准版",
            chart_data=chart_data,
            header_source_run_id=src_run,
        ),
        note,
    )


def build_data_fixture(run_dir: Path, scene_id: str) -> tuple[fill.ReportFillData, str]:
    """结构夹具：图表数据取真、判定/表头用夹具（只验结构，不当交付件）。"""
    chart_data = report_charts.collect(run_dir)
    scene = C_DIR / "web" / "public" / "scenes" / scene_id
    reqs: list[dict[str, str]] = []
    tr = scene / "test-requirements.json"
    if tr.is_file():
        payload = json.loads(tr.read_text(encoding="utf-8"))
        for item in payload.get("requirements") or payload.get("items") or []:
            rid = item.get("id") or item.get("req_id")
            if rid:
                reqs.append({"req_id": str(rid), "name": str(item.get("name") or ""), "state": ""})
    # 状态按词表轮转，把五种结论都渲染一遍（夹具，非实测结论）
    vocab = ["pass", "fail", "missing", "manual", "not_applicable"]
    for i, r in enumerate(reqs):
        r["state"] = vocab[i % len(vocab)]
    data = fill.ReportFillData(
        run_id="fixture0000" + run_dir.name[:8],
        header={
            "model": "夹具机型",
            "project_name": "夹具项目",
            "firmware_version": "FIXTURE-1.0",
            "inlet_start_addr": "0x0000",
            "outlet_start_addr": "0x1000",
            "bootloader": "0x2000",
            # 以下 4 项模板没有位：应当被忽略并进 warnings
            "customer_name": "夹具客户",
            "customer_engineer": "夹具工程师",
            "email": "fixture@example.com",
            "phone": "000-0000",
        },
        verdict={
            "total": len(reqs),
            "pass": vocab.count("pass") * max(1, len(reqs) // len(vocab)),
            "fail": 1,
            "missing": 2,
            "not_applicable": 3,
            "manual": 1,
            "pass_rate": 0.5 if reqs else None,
            "authoritative": True,
        },
        verdict_items=reqs,
        artifact_kinds=["config-snapshot", "requirement-baseline", "run-artifact", "verdict-table"],
        snapshot_counts={"本体属性": 29, "控制参数": 203, "报告表头": 10},
        source_note="系统内置模板：标准版",
        chart_data=chart_data,
    )
    return data, f"夹具模式（图表数据取真实目录 {run_dir.name}，判定为夹具）"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="", help="DB 里的 flow 轮次号（全真数据）")
    ap.add_argument("--run-dir", default="", help="硬件运行目录（夹具模式）")
    ap.add_argument("--scene", default="motor.cooling-fan.fortior-fu6832", help="场景包（夹具模式取判据清单）")
    ap.add_argument("--out", default="", help="产物路径（默认 backend/uploads/reports/_verify-template-fill.xlsm）")
    args = ap.parse_args()

    tpl = builtin_report_template()
    print(f"模板：{tpl}")
    if not tpl.is_file():
        print("模板不存在，终止")
        return 1

    if args.run_id:
        data, note = build_data_from_db(args.run_id)
    elif args.run_dir:
        data, note = build_data_fixture(Path(args.run_dir), args.scene)
    else:
        print("需给 --run-id 或 --run-dir")
        return 1
    print(f"数据来源：{note}")

    out = Path(args.out) if args.out else (C_DIR / "backend" / "uploads" / "reports" / "_verify-template-fill.xlsm")
    result = fill.fill_report_template(tpl, out, data)
    print(f"\n填充结果：status={result['status']} 图表 {result['charts']} 张，"
          f"行高增加 {result['row_growth_pt']} pt，产物 {out.stat().st_size} 字节")
    if result["warnings"]:
        print(f"warnings（{len(result['warnings'])} 条）：")
        for w in result["warnings"]:
            print(f"  - {w}")

    print("\n== 产物校验 ==")
    tpl_wb = load_workbook(str(tpl), keep_vba=True)
    out_wb = load_workbook(str(out), keep_vba=True)

    # ① 五个可见表齐全且可见
    visible = [ws.title for ws in out_wb.worksheets if ws.sheet_state == "visible"]
    check(
        all(s in visible for s in (fill.SHEET_COVER, fill.SHEET_DETAIL, fill.SHEET_TREND, fill.SHEET_WAVE, fill.SHEET_SUMMARY)),
        "五个可见工作表齐全",
        "、".join(visible),
    )

    # ② 宏启用格式保持（复用填充器里的解析，避免各写一套）
    tpl_ct = fill._workbook_content_type(tpl)
    out_ct = fill._workbook_content_type(out)
    check(
        bool(tpl_ct) and "macroEnabled" in out_ct and out_ct == tpl_ct,
        "产物仍是宏启用 .xlsm（主内容类型与模板一致）",
        f"模板={tpl_ct} 产物={out_ct}",
    )

    # ③ 无「待填写」残留
    left = fill._iter_placeholders(out_wb)
    check(not left, "四页「待填写」已清零", "、".join(left) if left else "")

    # ④ 无越界写入（逐格比对）
    tpl_vals, out_vals = values_of(tpl_wb), values_of(out_wb)
    changed = {k for k in set(tpl_vals) | set(out_vals) if tpl_vals.get(k) != out_vals.get(k)}
    overflow: list[str] = []
    for key in changed:
        sheet, _, coord = key.partition("!")
        if sheet == fill.DATA_SHEET_NEW:
            continue
        if coord in ALLOWED_CELLS.get(sheet, set()):
            continue
        overflow.append(key)
    check(not overflow, "无越界写入（差异全部落在白名单内）",
          f"越界 {len(overflow)} 格：" + "、".join(sorted(overflow)[:12]) if overflow else f"共 {len(changed)} 格差异")

    # ⑤.a 数据页仍与原实例**逐格一致**（一个字都不该动）
    old_data = {k: v for k, v in tpl_vals.items() if k.startswith(fill.SHEET_DATA_OLD + "!")}
    new_data = {k: v for k, v in out_vals.items() if k.startswith(fill.SHEET_DATA_OLD + "!")}
    check(old_data == new_data, f"「{fill.SHEET_DATA_OLD}」与模板逐格一致")

    # ⑤.b 「报告概要」：原实例保留，**只允许白名单那三处**例外（用户口径 2026-10-13）
    sum_old = {k: v for k, v in tpl_vals.items() if k.startswith(fill.SHEET_SUMMARY + "!")}
    sum_new = {k: v for k, v in out_vals.items() if k.startswith(fill.SHEET_SUMMARY + "!")}
    sum_diff = {k for k in set(sum_old) | set(sum_new) if sum_old.get(k) != sum_new.get(k)}
    sum_bad = sorted(k for k in sum_diff if k.split("!")[1] not in ALLOWED_CELLS[fill.SHEET_SUMMARY])
    check(not sum_bad, "「报告概要」仅按口径改了那三处（其余原实例不动）",
          f"越界 {len(sum_bad)} 格：" + "、".join(sum_bad[:8]) if sum_bad else f"共 {len(sum_diff)} 格差异")
    n_summary_charts = len(out_wb[fill.SHEET_SUMMARY]._charts)
    check(n_summary_charts == 10, "「报告概要」原 10 张图表仍在", f"实得 {n_summary_charts} 张")


    # ⑤.c 概要页口径落实：不适用行已删且**不留空行**、口径说明已缩短、明细不适用留空
    sum_ws = out_wb[fill.SHEET_SUMMARY]
    na_row = fill.SUMMARY_SHEET_UNAPPLICABLE_ROW
    # 删行后：第 21 行应已是「人工判定」（原第 22 行上移），即**不留空行**
    moved = str(sum_ws.cell(row=na_row, column=1).value or "").strip()
    check(
        moved == "人工判定",
        "概要页删掉「本台架不适用」后其后各行已上移（第 21 行不留空行）",
        f"第{na_row}行 A 列 = {moved!r}",
    )
    check(
        str(sum_ws.cell(row=na_row + 1, column=1).value or "").strip() == "数据来源"
        and str(sum_ws.cell(row=na_row + 2, column=1).value or "").strip() == "说明",
        "概要页汇总区后续行序为「数据来源 / 说明」",
    )
    note_val = str(sum_ws.cell(row=fill.SUMMARY_SHEET_NOTE_ROW, column=2).value or "")
    check(
        note_val.strip() == fill.SUMMARY_SHEET_NOTE,
        "概要页通过率口径说明已缩短",
        f"值：{note_val!r}",
    )
    # 概要页「报告来源 / 数据来源」两行文案（用户口径 2026-10-13）
    check(
        str(sum_ws[fill.SUMMARY_SHEET_SOURCE_CELL].value or "").strip()
        == fill.SUMMARY_SHEET_SOURCE_TEXT,
        "概要页「报告来源」为「标准版」",
        f"值：{sum_ws[fill.SUMMARY_SHEET_SOURCE_CELL].value!r}",
    )
    ds_row = na_row + 1  # 删行上移后：人工判定 21 / 数据来源 22 / 说明 23
    check(
        str(sum_ws.cell(row=ds_row, column=2).value or "").strip()
        == fill.SUMMARY_SHEET_DATA_SOURCE_TEXT,
        "概要页「数据来源」为「后端判定」（去「（权威）」）",
        f"值：{sum_ws.cell(row=ds_row, column=2).value!r}",
    )

    # 概要页表头同步本轮数据
    hdr_missing = [
        str(sum_ws.cell(row=r, column=2).value or "")
        for r in fill.SUMMARY_SHEET_HEADER.values()
    ]
    if data.header:
        check(
            any(v.strip() and v.strip() != fill.HEADER_MISSING_TEXT for v in hdr_missing),
            "概要页汇总区的表头已同步本轮数据",
            " | ".join(hdr_missing),
        )
    check(n_summary_charts == 10, "「报告概要」原 10 张图表仍在", f"实得 {n_summary_charts} 张")

    # ⑥ 新图表张数与锚点
    n_trend = len(out_wb[fill.SHEET_TREND]._charts)
    n_wave = len(out_wb[fill.SHEET_WAVE]._charts)
    check(n_trend <= len(fill.TREND_SLOTS), "趋势页图表张数不超过版位数", f"{n_trend} 张")
    check(n_wave <= len(fill.WAVE_SLOTS), "波形页图表张数不超过版位数", f"{n_wave} 张")
    check(n_trend + n_wave == result["charts"], "返回的图表张数与产物内一致",
          f"返回 {result['charts']}、产物 {n_trend + n_wave}")

    # ⑦ 抽查：缺数不写 0
    rate = out_wb[fill.SHEET_COVER][fill.COVER_SUMMARY["pass_rate"]].value
    check(rate is not None and str(rate) != "0%", "通过率不为伪造的 0%", f"值：{rate!r}")

    # ⑪ 三页第 3 行说明已删除 + 封面数据来源与口径说明按口径（2026-10-13）
    hint_left = [
        f"{n}!{c}"
        for n, c in fill.TEMPLATE_HINT_CELLS
        if str(out_wb[n][c].value or "").strip()
    ]
    check(not hint_left, "三页第 3 行「空白填写模板…」说明已删除", "、".join(hint_left) if hint_left else "")
    src_val = str(out_wb[fill.SHEET_COVER][fill.COVER_SUMMARY["source"]].value or "")
    check(
        src_val in (fill.COVER_DATA_SOURCE, "前端预览（非权威）"),
        "封面「数据来源」为「后端判定」（不带「（权威）」）",
        f"值：{src_val!r}",
    )
    note_cover = str(out_wb[fill.SHEET_COVER][fill.COVER_NOTE_CELL].value or "")
    check(
        note_cover.strip() == fill.COVER_NOTE,
        "封面通过率口径说明已按口径改写",
        f"值：{note_cover!r}",
    )
    src_row = str(out_wb[fill.SHEET_COVER][fill.COVER_ID["source"]].value or "")
    check(
        src_row.startswith(fill.ReportFillData.__dataclass_fields__["source_note"].default)
        or "标准版" in src_row,
        "封面「报告来源」为「系统内置模板：标准版」",
        f"值：{src_row!r}",
    )

    # ⑨ 表头真实落值（2026-10-13 修「表头空」的关键断言）
    cover_ws = out_wb[fill.SHEET_COVER]
    missing_slots = [
        f"{k}={cover_ws[coord].value!r}"
        for k, coord in fill.COVER_HEADER.items()
        if str(cover_ws[coord].value or "").strip() in ("", fill.HEADER_MISSING_TEXT)
    ]
    if data.header:
        check(
            len(missing_slots) < len(fill.COVER_HEADER),
            "封面表头位有真实落值（非全部「未提供」）",
            "；".join(missing_slots) if missing_slots else "6 位全部落值",
        )
    if getattr(data, "header_source_run_id", None) and data.header_source_run_id != data.run_id:
        src_cell = str(cover_ws[fill.COVER_ID["source"]].value or "")
        check(
            data.header_source_run_id[:8] in src_cell,
            "报告来源行标注了表头来源轮次",
            f"值：{src_cell!r}",
        )

    # ⑩ 「本台架不适用」的结论列必须留空（判据 ID 与名称保留）
    detail_ws = out_wb[fill.SHEET_DETAIL]
    na_states = {
        str(it.get("req_id")): str(it.get("state") or "")
        for it in (data.verdict_items or [])
        if isinstance(it, dict)
    }
    na_left: list[str] = []
    na_kept: list[str] = []
    na_bad: list[str] = []
    for r in range(fill.DETAIL_ROW_FIRST, fill.DETAIL_ROW_LAST + 1):
        req_id = str(detail_ws.cell(row=r, column=fill.DETAIL_ID_COL).value or "").strip()
        if not req_id or na_states.get(req_id) != "not_applicable":
            continue
        g_val = detail_ws.cell(row=r, column=fill.DETAIL_STATE_COL).value
        if g_val is None or str(g_val).strip() == "":
            na_left.append(req_id)
        else:
            na_bad.append(f"{req_id}→{g_val!r}")
        if str(detail_ws.cell(row=r, column=3).value or "").strip():
            na_kept.append(req_id)
    if na_states and any(s == "not_applicable" for s in na_states.values()):
        check(
            not na_bad,
            "「本台架不适用」行的结论列为空",
            f"留空 {len(na_left)} 条" + (f"；未留空：{'、'.join(na_bad[:6])}" if na_bad else ""),
        )
        check(
            len(na_kept) == len(na_left),
            "不适用行的判据 ID 与名称仍保留（模板原文不动）",
            f"保留名称 {len(na_kept)} / 留空 {len(na_left)}",
        )

    # ⑧ 新隐藏数据页
    check(
        fill.DATA_SHEET_NEW in out_wb.sheetnames
        and out_wb[fill.DATA_SHEET_NEW].sheet_state == "hidden",
        f"新增隐藏数据页 {fill.DATA_SHEET_NEW} 存在且隐藏",
    )

    print()
    if FAILED:
        print(f"结果：{len(FAILED)} 项未通过 —— " + "；".join(FAILED))
        return 1
    print("结果：全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
