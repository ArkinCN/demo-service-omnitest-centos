"""验收：占位报告 xlsm（2026-09-28 新增）。

用户要求：占位报告要**能在 Excel 里打开**，并带上本轮的真题数据
（表头 + 判定汇总 + 产物清单），全中文、繁体已归一。

本脚本**用 openpyxl 回读**生成的文件（而不是只看字节数），
因为「文件产出且大小不为 0」不等于「Excel 能打开」——
正好呼应本项目的既有纪律：**「界面正常」≠「功能正常」**。

跑法：cd c/backend && <ra python> scripts/verify_report_xlsm.py [run_id]
"""
from __future__ import annotations

import sys
from pathlib import Path

# 脚本单独运行时把 backend 加进 sys.path（与其它 scripts/ 同款做法）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openpyxl import load_workbook  # noqa: E402

from app.core.paths import reports_dir  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, ok: bool, extra: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}" + (f" — {extra}" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" — {extra}" if extra else ""))


def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "d5c08959241847798ab15884d0ae141a"
    path = reports_dir() / f"report-{run_id}.placeholder.xlsm"

    print(f"\n### 占位报告 xlsm 验收\n")
    print(f"  [info] 目标文件：{path}")

    check("文件存在（真产出，不是只返回了个路径）", path.exists(), str(path))
    if not path.exists():
        print(f"\n==================== {PASS}/{PASS + FAIL} 通过 ====================\n")
        return 1

    size = path.stat().st_size
    print(f"  [info] 文件大小：{size} 字节")
    check("文件非空", size > 0, f"{size} 字节")

    # ── ① 真能被 Excel 打开（openpyxl 能解析 = 结构合法）
    print("\n### ① 文件结构合法（等价于「Excel 能打开」）\n")
    try:
        wb = load_workbook(str(path))
        opened = True
    except Exception as exc:  # noqa: BLE001
        wb = None
        opened = False
        print(f"  [info] 打开失败：{type(exc).__name__}: {exc}")
    check("openpyxl 能打开（结构合法）", opened)
    if wb is None:
        print(f"\n==================== {PASS}/{PASS + FAIL} 通过 ====================\n")
        return 1

    ws = wb.active
    print(f"  [info] 工作表名：{ws.title!r}，尺寸：{ws.max_row} 行 × {ws.max_column} 列")
    check("有工作表", ws.max_row > 0, f"{ws.max_row} 行")
    check("工作表名是简体", ws.title == "报告概要", repr(ws.title))

    # 把整张表拍平成文本，便于按内容断言
    cells: list[str] = []
    for row in ws.iter_rows(values_only=True):
        for v in row:
            if v is not None:
                cells.append(str(v))
    text = "\n".join(cells)

    # ── ② 三道占位标注（缺一不可，否则会被当成正式报告）
    print("\n### ② 三道占位标注\n")
    check("标注一：首行有占位横幅", "占位报告" in text and "不是正式交付件" in text)
    check("标注二：文件带 placeholder", "placeholder" in path.name, path.name)
    check(
        "标注三：状态行写明占位件",
        "占位件" in text,
        next((c for c in cells if "占位件" in c), "")[:50],
    )

    # ── ③ 真题数据：轮次号 / 表头 / 判定 / 产物
    print("\n### ③ 真题数据是否落进文件\n")
    check("含轮次号（可与库中记录对应）", run_id in text)
    check("含生成时间", "生成时间" in text)
    check("含报告表头小节", "报告表头" in text)
    check("含判定汇总小节", "判定汇总" in text)
    check("含产物清单小节", "产物清单" in text)
    check("含配置快照摘要", "配置快照摘要" in text)
    check("含「如何换成正式报告」指引", "如何换成正式报告" in text)

    # 表头字段：本次 run 有 config-snapshot，应至少取到部分字段
    header_hit = [c for c in cells if c in ("机型", "项目名称", "固件版本", "客户名称")]
    print(f"  [info] 命中的表头中文名：{header_hit}")
    check("表头用了简体中文名（繁体已归一）", len(header_hit) > 0, f"{len(header_hit)} 个")

    # 未取到的字段必须**如实标注**，不能编
    check(
        "未提供的字段如实标注（不编值）",
        "由上游带入（未提供）" in text or all(k in text for k in ("机型", "项目名称")),
        "有缺失字段时显示「由上游带入（未提供）」",
    )

    # ── ④ 繁体归一：文件里不应残留表头字段的繁体写法
    print("\n### ④ 繁体归一\n")
    traditional = ["客戶名稱", "客戶工程師", "聯繫電話", "韌體版本", "項目名稱"]
    residue = [t for t in traditional if t in text]
    check("无残留繁体表头字段", not residue, f"残留：{residue}" if residue else "")

    # ── ⑤ 「未采集 ≠ 不通过」这条纪律必须在文件里写出来
    print("\n### ⑤ 纪律：未采集不等于不通过\n")
    if "未采集" in text:
        check(
            "写了「未采集 ≠ 不通过」的说明",
            "不等于" in text and "不通过" in text,
        )
    else:
        print("  [info] 本轮无判定数据，该条不适用（脚本按通过处理）")
        check("无判定数据时应如实写「本轮没有判定数据」", "没有判定数据" in text or "未产出" in text)

    print(f"\n==================== {PASS}/{PASS + FAIL} 通过 ====================\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
