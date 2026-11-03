"""把 Customer.h 从「一堆 #define」转成前端/Agent 可直接消费的 params.json。

每条宏产出：name / value / raw_value / numeric / wrapper / unit / range / comment
/ line / group(所属分组) / editable 提示。分组来自文件里的 Doxygen 注释
（@defgroup 作一级分组、@brief 作二级分组）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import INPUT, KB_OUT, TAXONOMY, load_registry, sha256_file, write_json  # noqa: E402

RE_DEFINE = re.compile(r"^\s*#\s*define\s+(\w+)\s*(.*)$")
RE_DEFGROUP = re.compile(r"@defgroup\s+(\S+)\s*(.*)")
RE_BRIEF = re.compile(r"@brief\s*(.+)")
RE_TAIL_COMMENT = re.compile(r"/\*!?<?\s*(.*?)\s*\*/\s*$")
RE_WRAPPER = re.compile(r"^(_Q15|_Q12|_IQ|I_Value|S_Value|V_Value|U_Value)\s*\((.*)\)$")
RE_RANGE = re.compile(
    r"(?:範圍|范围|Range|range)\s*[:：]\s*([-+]?\d+(?:\.\d+)?)\s*(?:~|～|—|至|到)\s*([-+]?\d+(?:\.\d+)?)"
)
RE_UNIT = re.compile(r"[（(]?\s*(?:單位|单位|Unit)\s*[:：]\s*([^)）,，]+)[)）]?")
RE_NUM = re.compile(r"^[-+]?\d+(?:\.\d+)?$")


def parse(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    group_l1, group_l2 = "基礎與採樣配置", "基礎與採樣配置"
    out: list[dict] = []
    pending_brief: str | None = None

    for idx, line in enumerate(lines, start=1):
        if m := RE_DEFGROUP.search(line):
            group_l1 = (m.group(2) or m.group(1)).strip() or m.group(1)
            group_l2 = group_l1
            pending_brief = None
            continue
        if m := RE_BRIEF.search(line):
            brief = m.group(1).strip().rstrip("*/").strip()
            if brief and not brief.startswith(":"):
                group_l2 = brief
                pending_brief = brief
            continue

        m = RE_DEFINE.match(line)
        if not m:
            continue
        name, rest = m.group(1), m.group(2).strip()
        comment = ""
        if cm := RE_TAIL_COMMENT.search(rest):
            comment = cm.group(1).strip()
            rest = rest[: cm.start()].strip()
        raw_value = rest.strip()

        wrapper, inner = None, raw_value
        if wm := RE_WRAPPER.match(raw_value):
            wrapper, inner = wm.group(1), wm.group(2).strip()
        elif raw_value.startswith("(") and raw_value.endswith(")"):
            inner = raw_value[1:-1].strip()

        numeric = float(inner) if RE_NUM.match(inner) else None
        rng = None
        if rm := RE_RANGE.search(comment):
            rng = {"min": float(rm.group(1)), "max": float(rm.group(2))}
        unit = None
        if um := RE_UNIT.search(comment):
            unit = um.group(1).strip()

        out.append({
            "name": name,
            "value": numeric if numeric is not None else inner,
            "raw_value": raw_value,
            "numeric": numeric,
            "value_kind": "number" if numeric is not None
                          else ("macro_ref" if re.fullmatch(r"[A-Za-z_]\w*", inner) else "expression"),
            "wrapper": wrapper,
            "unit": unit,
            "range": rng,
            "comment": comment,
            "line": idx,
            "group": {"l1": group_l1, "l2": group_l2},
            "editable": numeric is not None,
        })
        pending_brief = pending_brief  # 保留当前二级分组直到下一个 @brief
    return out


def main() -> None:
    reg = load_registry()
    cfg = reg["code_configs"][0]
    src = INPUT / cfg["file"]
    params = parse(src)

    groups: dict[str, set] = {}
    for p in params:
        groups.setdefault(p["group"]["l1"], set()).add(p["group"]["l2"])

    out_dir = KB_OUT / "documents" / cfg["doc_id"]
    write_json(out_dir / "params.json", {
        "doc_id": cfg["doc_id"],
        "title": cfg["title"],
        "doc_type": cfg["doc_type"],
        "taxonomy": TAXONOMY,
        "process_tags": cfg["process_tags"],
        "source": {
            "path": str(src),
            "origin": "10_外部资料/客户材料/AI_散热风扇开发资料/AI_散热风扇开发资料/"
                      "CoolingFan_Program/Software/User/include/Customer.h",
            "sha256": sha256_file(src),
            "bytes": src.stat().st_size,
            "lines": len(src.read_text(encoding="utf-8", errors="replace").splitlines()),
        },
        "summary": {
            "macro_count": len(params),
            "numeric_editable": sum(1 for p in params if p["editable"]),
            "with_range": sum(1 for p in params if p["range"]),
            "with_unit": sum(1 for p in params if p["unit"]),
            "group_l1_count": len(groups),
        },
        "groups": [{"l1": k, "l2": sorted(v)} for k, v in groups.items()],
        "params": params,
    })
    print(f"[customer.h] {len(params)} macros -> {out_dir/'params.json'}")


if __name__ == "__main__":
    main()
