"""经验性质知识：从 98 次启动实验数据包 + 客户规程，提炼结构化经验条目。

两个来源：
  A. 实验沉淀 —— 30 例失败案例（CF-L-0001~0030），逐例带实测波形特征与工具判定。
  B. 规程沉淀 —— coolingfan-openloop-debug 规程的 8 行现象分诊表。
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import KB_OUT, TAXONOMY, write_json  # noqa: E402

PKG = Path("峰岹agent/数据"
           "20260811_启动故障98次实验与30例对照数据包")
SKILL = Path("[源] data/dc-skills"
             "coolingfan-openloop-debug/SKILL.md")
EVIDENCE_DOC = Path("峰岹agent/09-实验室demo线"
                    "20260917-产品故事与分工v1.0/_调研/A-DebugCopilot场景与知识库取证.md")


def load_rows(name: str) -> list[dict]:
    with open(PKG / name, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_experiment_entries() -> list[dict]:
    meta = {r["attempt_id"]: r for r in load_rows("metadata.csv")}
    feats = {r["attempt_id"]: r for r in load_rows("features_all.csv")}
    by_case = {r["case_id"]: aid for aid, r in meta.items() if r["case_id"]}

    profile = json.loads(
        next((PKG / "01_实验原始数据").rglob("motor_profile.json")).read_text(encoding="utf-8")
    )
    good = profile["known_good"]["MOTOR_ALIGNMENT_DOUT"]

    entries = []
    for case_id in sorted(by_case):
        aid = by_case[case_id]
        m, f = meta[aid], feats.get(aid, {})
        diag_p = PKG / "02_30例工具增强结果" / "cases" / case_id / "tool_output" / "diagnosis.json"
        diag = json.loads(diag_p.read_text(encoding="utf-8"))
        pf = diag.get("primary_fault") or {}
        cur = None
        for det in diag.get("atomic_detectors", []):
            if det["detector_id"] == "A02_ALIGNMENT_STRENGTH":
                for ev in det.get("supporting_evidence", []):
                    if mm := re.search(r"當前DOUT=|当前DOUT=([\d.]+)", ev["fact"]):
                        cur = fnum(mm.group(1))
        cur = cur if cur is not None else 0.01

        failed = [d["name"] for d in diag.get("atomic_detectors", []) if d["status"] == "FAIL"]
        entries.append({
            "id": f"EXP-RUN-{case_id}",
            "title": f"{case_id}：静止启动未起转，预定位强度过弱",
            "capture_mode": "实验沉淀",
            "phenomenon": {
                "text": "现场人员确认未进入持续稳定旋转；示波器 CH1 相电流上可见预定位段，"
                        "但末端仍有较强动态、未观察到充分稳定。",
                "measured": {
                    "align_duration_s": fnum(m.get("align_duration_s")),
                    "align_mean_a": fnum(m.get("align_mean_a")),
                    "align_n_stage": fnum(m.get("align_n_stage")),
                    "start_env_decay_ratio": fnum(m.get("start_env_decay_ratio")),
                    "v_absmax_a": fnum(m.get("v_absmax")),
                    "fs_hz": fnum(m.get("fs_hz")),
                    "window_coverage": m.get("window_coverage"),
                },
                "failed_detectors": failed,
            },
            "root_cause": {
                "fault_id": pf.get("fault_id"),
                "label": pf.get("label"),
                "stage": diag.get("stage"),
                "rationale": pf.get("rationale"),
                "independent_sources": pf.get("independent_sources", []),
            },
            "action": {
                "parameter": pf.get("parameter"),
                "direction": pf.get("repair_direction"),
                "current_value": cur,
                "target_baseline": good,
                "step": "按 0.01 量级小步增加；接近振荡边界时减半步长",
                "verified_range": profile["verified_ranges"]["MOTOR_ALIGNMENT_DOUT"],
            },
            "result": {
                "status": "未验证",
                "note": "本数据包只采集了故障态，没有把修复值回灌重测；"
                        "修复方向来自型号健康基线对比，不是实测闭环结果。",
            },
            "confidence": fnum(pf.get("score")),
            "source": {
                "attempt_path": f"01_实验原始数据/batch_20260811_113726_010/attempts/{aid}",
                "waveform": m.get("relpath"),
                "diagnosis_report": f"02_30例工具增强结果/cases/{case_id}/tool_output/diagnosis_report.md",
                "package": str(PKG),
            },
            "tags": {
                "scenario": TAXONOMY["l1"], "product": TAXONOMY["l3"],
                "process": "启动测试",
                "parameters": [pf.get("parameter")],
                "fault_type": "起动失败",
            },
            "time": "2026-08-11",
        })
    return entries


TRIAGE_ROWS = [
    ("fault=1/2（过流）", "起转电流偏大", "启动电流", "decrease", "−20%", "保护误触发"),
    ("fault=6（堵转）或起转即停", "起转力矩不足或负载偏重", "启动电流", "increase",
     "反问用户确认负载后 +0.1~0.2 A", "起动失败"),
    ("fault=5（缺相）", "接线问题", None, None, "停止迭代，反问用户检查接线", "设备连接"),
    ("无 fault 但 FREQ≈0 / 电机不转", "起转电流不足", "启动电流", "increase", "+0.1~0.2 A", "起动失败"),
    ("起转起来但切闭环瞬间掉速/失步", "闭环切换点不合适", "MOTOR_LOOP_RPM 类切换转速",
     "both", "±20%，并复核起转电流", "波形异常"),
    ("mcState 停在开环态、转速上不到目标", "未进闭环或目标转速超能力",
     "OPENLOOP_ENABLED / SPEED_MODE", "set",
     "先确认 OPENLOOP_ENABLED=0、SPEED_MODE=NONEMODE 已生效；仍不行则反问目标转速是否超能力",
     "转速不达"),
    ("稳态转速偏差 > 容限但稳定", "外环增益或目标换算问题", "SPD_KI / SKI", "increase",
     "先复核目标转速宏外壳与极对数换算，确认无误后经用户同意 +20%", "转速不达"),
    ("稳态转速振荡（3 次 FREQ 极差 > 3%）", "外环增益偏高", "SPD_KP / SKP", "decrease",
     "−20%，一次只动一项", "波形异常"),
]


def build_procedure_entries() -> list[dict]:
    entries = []
    for i, (phen, cause, param, direction, step, ftype) in enumerate(TRIAGE_ROWS, start=1):
        entries.append({
            "id": f"EXP-SOP-{i:02d}",
            "title": f"开环→闭环调试分诊：{phen}",
            "capture_mode": "规程沉淀",
            "phenomenon": {"text": phen, "measured": None, "failed_detectors": []},
            "root_cause": {"fault_id": None, "label": cause, "stage": "open-loop 闭环调试",
                           "rationale": cause, "independent_sources": ["SOP"]},
            "action": {"parameter": param, "direction": direction, "current_value": None,
                       "target_baseline": None, "step": step, "verified_range": None},
            "result": {"status": "规程约定",
                       "note": "来自客户软件随装规程，最多 3 轮迭代；3 轮仍 NG 则用 .bak 还原并重烧原版固件。"},
            "confidence": 0.6,
            "source": {
                "attempt_path": None, "waveform": None, "diagnosis_report": None,
                "sop_file": str(SKILL),
                "sop_section": "## 5. 失败分诊迭代（最多 3 轮）· 现象分诊表",
                "cross_reference": str(EVIDENCE_DOC) + "（二、规程层第 7 类：散热风扇 1 份 coolingfan-openloop-debug，带 8 现象分诊表）",
            },
            "tags": {"scenario": TAXONOMY["l1"], "product": TAXONOMY["l3"],
                     "process": "调优", "parameters": [param] if param else [],
                     "fault_type": ftype},
            "time": "2026-09-17",
        })
    return entries


def main() -> None:
    exp = build_experiment_entries()
    sop = build_procedure_entries()
    entries = exp + sop
    write_json(KB_OUT / "experience" / "index.json", {
        "taxonomy": TAXONOMY,
        "summary": {
            "total": len(entries),
            "by_capture_mode": {"实验沉淀": len(exp), "规程沉淀": len(sop), "对话沉淀": 0},
            "by_fault_type": {t: sum(1 for e in entries if e["tags"]["fault_type"] == t)
                              for t in sorted({e["tags"]["fault_type"] for e in entries})},
        },
        "caveats": [
            "30 条实验沉淀全部来自同一个注入故障（align_weak，预定位强度过弱），"
            "本数据包正常样本 0 条；条目之间的差异在实测波形特征，不在根因。",
            "实验沉淀的 result.status 一律为『未验证』：数据包只采了故障态，未回灌修复值复测。",
            "8 条规程沉淀是客户软件随装规程的约定动作，不是我方实测结论。",
            "对话沉淀为 0：本轮没有可引用的真实对话记录，字段模板见 taxonomy.json。",
        ],
        "entries": entries,
    })
    print(f"[experience] {len(entries)} entries (实验 {len(exp)} / 规程 {len(sop)})")


if __name__ == "__main__":
    main()
