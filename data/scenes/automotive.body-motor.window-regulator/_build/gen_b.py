# -*- coding: utf-8 -*-
"""场景包生成：workflows / datasets / experience / documents / report-template。

workflows 与场景一的根本差异：场景一有 67 个客户真实 .wfw 文件可解析，
本场景**没有任何现成工作流文件**。所以这里造 4 条示例工作流索引（全部 _placeholder: true），
节点用六类抽象（设置 / 激励 / 采集 / 判定 / 控制流 / 数据处理），
并把画布可直接加载的内部模型写到 assets/workflows/*.json。
"""
import json
import os

import gen_waveforms
import render_assets
from common import (BUILD_DATE, CISPR25_PDF, DOC_B, EV, GB11552_TXT,
                    GENERATED_BY, GMW3172_PDF,
                    ISO16750_1_PDF, ISO16750_2_PDF, ISO16750_3_PDF,
                    ISO16750_4_PDF, ISO16750_5_PDF, ISO10605_PDF,
                    ISO11452_1_PDF, ISO19453_PDF, ISO20653_PDF, ISO7637_2_PDF,
                    IEC60034_1_PDF, IEC60034_5_PDF, CISPR12_PDF,
                    LV124_PDF, LV148_PDF, NHTSA_PDF, Q100_PDF, Q101_PDF,
                    Q102_PDF, Q104_PDF, Q200_PDF, QC626_TXT, SCENE_ID,
                    VW80000_PDF, BMW_GS_PDF, b, dump, src)

NOT_FOUND = []
OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF_DIR = os.path.join(OUT, "assets/workflows")


# ============================ workflows.json ============================

NODE_GROUPS = {
    "设置": "把台架与被测件置于试验要求的初始状态（电压、温度、配重、工装位置、固件参数）",
    "激励": "对被测件施加动作或应力（升降指令、施加障碍物、施加加载力、施加过压）",
    "采集": "从传感器与被测件读数（电流、位移、力、声压、故障字）",
    "判定": "拿采集到的量与 test-requirements.json 的判据比对，出 PASS / FAIL",
    "控制流": "流程骨架（开始、结束、延时、循环、跳出、条件分支）",
    "数据处理": "从原始时序算出判据需要的派生量（速度、峰值、偏差、纹波计数），以及导出报告",
}

NODE_TYPE_LEGEND = {
    # 控制流
    "start": ("开始", "控制流"),
    "end": ("结束", "控制流"),
    "error_exit": ("异常出口", "控制流"),
    "delay": ("延时等待", "控制流"),
    "loop": ("循环", "控制流"),
    "loop_break": ("跳出循环", "控制流"),
    "branch": ("条件分支", "控制流"),
    # 设置
    "set_supply": ("设置程控电源", "设置"),
    "set_harness_resistance": ("设置回路串联电阻", "设置"),
    "set_chamber": ("设置环境箱温湿度", "设置"),
    "set_load": ("设置模拟工装配重", "设置"),
    "set_rod": ("布置防夹试验棒", "设置"),
    "set_antipinch_params": ("下发防夹参数", "设置"),
    "set_force_actuator": ("设置加载作动器", "设置"),
    # 激励
    "cmd_up": ("下发上升指令", "激励"),
    "cmd_down": ("下发下降指令", "激励"),
    "cmd_stop": ("下发停止指令", "激励"),
    "apply_obstacle": ("投入障碍物（试验棒）", "激励"),
    "apply_static_load": ("施加静态加载力", "激励"),
    # 采集
    "acq_current": ("采集电流时序", "采集"),
    "acq_position": ("采集位移时序", "采集"),
    "acq_force": ("采集力时序", "采集"),
    "acq_noise": ("采集声压级", "采集"),
    "acq_fault": ("读取故障字", "采集"),
    # 数据处理
    "calc_speed": ("换算运行速度", "数据处理"),
    "calc_peak": ("提取峰值与平台值", "数据处理"),
    "calc_retract": ("换算回缩量与触发开口", "数据处理"),
    "calc_deviation": ("与基线比对求偏差", "数据处理"),
    "ripple_count": ("纹波计数换算位置", "数据处理"),
    "export_report": ("导出报告数据段", "数据处理"),
    # 判定
    "judge_speed": ("判定运行速度", "判定"),
    "judge_current": ("判定工作与堵转电流", "判定"),
    "judge_force": ("判定堵转力", "判定"),
    "judge_pinch": ("判定防夹力与回缩", "判定"),
    "judge_self_lock": ("判定自锁下降量", "判定"),
    "judge_noise": ("判定工作噪音", "判定"),
    "judge_deviation": ("判定性能偏差", "判定"),
}


def _n(nid, ntype, params, x, y, label=None):
    name, group = NODE_TYPE_LEGEND[ntype]
    return {"id": nid, "type": ntype, "label": label or name, "group": group,
            "params": params, "position": {"x": x, "y": y}}


def _e(src_id, dst_id, handle="output"):
    return {"id": "e-%s-%s-%s" % (src_id, dst_id, handle),
            "source": src_id, "target": dst_id,
            "sourceHandle": handle, "targetHandle": "input"}


def _chain(nodes, err_node=None, skip_err=()):
    """把节点按顺序串成主干；除起止与异常节点外，每个节点再拉一条 error 边到异常出口。"""
    edges = []
    for a, bb in zip(nodes, nodes[1:]):
        edges.append(_e(a["id"], bb["id"]))
    if err_node:
        for nd in nodes:
            if nd["type"] in ("start", "end", "error_exit") or nd["id"] in skip_err:
                continue
            edges.append(_e(nd["id"], err_node["id"], "error"))
    return edges


def _wf_basic_cycle():
    """WF-001 上升下降循环（基本性能）。10 个节点，六类抽象齐全。"""
    N = [
        _n("n1", "start", {}, 0, 0),
        _n("n2", "set_supply",
           {"voltage_v": 13.5, "tolerance_v": 0.3, "ripple_pp_mv_max": 100,
            "harness_resistance_ohm": 0.15, "harness_tolerance_ohm": 0.02}, 0, 0),
        _n("n3", "set_load",
           {"mode": "RATED_LOAD",
            "up_definition": "玻璃重量 + 胶条滑动阻力",
            "down_definition": "玻璃重量 − 胶条滑动阻力",
            "cycles": 5,
            "note": "耐高温与耐低温条款各要求在目标温度下跑 5 个工作循环"}, 0, 0),
        _n("n4", "cmd_up",
           {"from": "下止点", "to": "上止点", "then_down": True,
            "stop_on_stall": True, "dwell_s": 4.0}, 0, 0),
        _n("n5", "acq_current",
           {"sample_rate_sa_per_s": 2000,
            "channels": ["current_a", "bus_voltage_v", "position_mm", "speed_mm_s"]}, 0, 0),
        _n("n6", "calc_speed",
           {"formula": "travel_mm / duration_s", "directions": ["UP", "DOWN"],
            "displacement_resolution_mm": 0.05}, 0, 0),
        _n("n7", "judge_speed",
           {"requirement_ids": ["TR-BASIC-05", "TR-BASIC-06"],
            "up_min_mm_s": 80.0, "up_max_mm_s": 160.0, "down_max_mm_s": 200.0}, 0, 0),
        _n("n8", "judge_current",
           {"requirement_id": "TR-BASIC-02", "max_a": 12.0}, 0, 0),
        _n("n9", "end", {}, 0, 0),
    ]
    err = _n("n99", "error_exit",
             {"on_fault": "停机并置本次试验为 INVALID，不计入 5 个循环"}, 0, 0)
    N.append(err)
    E = _chain([x for x in N if x["id"] != "n99"], err)
    return {"nodes": N, "edges": E}


def _wf_stall():
    """WF-002 堵转试验。10 个节点，六类抽象齐全。"""
    N = [
        _n("n1", "start", {}, 0, 0),
        _n("n2", "set_force_actuator",
           {"mode": "REACTION_MEASURE", "range_n": 500.0, "trip_n": 700.0,
            "supply_voltage_v": 13.5, "supply_tolerance_v": 0.3}, 0, 0),
        _n("n3", "cmd_up",
           {"to": "上止点", "hold_after_stall_s": 1.0,
            "max_stall_s": 30.0,
            "note": "征求意见稿 6.9.1 注 3 的单循环波形就是上止点堵转 1 s；"
                    "台架侧的堵转持续上限 30 s 见 SI-HW-03"}, 0, 0),
        _n("n4", "acq_current",
           {"sample_rate_sa_per_s": 2000, "window": "堵转平台段"}, 0, 0),
        _n("n5", "acq_force",
           {"sample_rate_sa_per_s": 2000, "window": "堵转平台段"}, 0, 0),
        _n("n6", "calc_peak",
           {"targets": ["stall_current_a", "stall_force_n"],
            "method": "平台段均值与峰值双出"}, 0, 0),
        _n("n7", "judge_current",
           {"requirement_id": "TR-BASIC-03", "max_a": 28.0,
            "max_a_80c": 29.0, "max_a_minus30c": 30.0}, 0, 0),
        _n("n8", "judge_force",
           {"requirement_id": "TR-BASIC-04", "min_n": 212.0,
            "min_n_80c": 164.0, "min_n_minus30c": 190.0,
            "note": "与上一节点方向相反：电流判上限、力判下限，同一段波形出两个反向判据"}, 0, 0),
        _n("n9", "end", {}, 0, 0),
    ]
    err = _n("n99", "error_exit",
             {"on_fault": "立即断电。堵转连续施加不得超过 30 s（SI-HW-03）"}, 0, 0)
    N.append(err)
    E = _chain([x for x in N if x["id"] != "n99"], err)
    return {"nodes": N, "edges": E}


def _wf_antipinch():
    """WF-003 防夹试验。10 个节点，六类抽象齐全，含一个真正的条件分支。"""
    N = [
        _n("n1", "start", {}, 0, 0),
        _n("n2", "set_antipinch_params",
           {"force_threshold_n": 80.0, "window_lower_mm": 4.0,
            "window_upper_mm": 200.0, "retract_mode": "PLUS_50MM",
            "retract_distance_mm": 60.0, "startup_blanking_ms": 150.0,
            "target_market": "CN"}, 0, 0),
        _n("n3", "cmd_up", {"from": "开口 200 mm 以上", "to": "上止点"}, 0, 0),
        _n("n4", "apply_obstacle",
           {"mode": "FIXED_ROD", "opening_mm": 170.0,
            "rod_stiffness_n_per_mm": 10.0, "rod_tolerance_n_per_mm": 0.5,
            "rod_diameter_mm": 200.0,
            "note": "棒的圆柱面与构成车窗边界的车辆结构部分接触；"
                    "整个试验期间棒相对于边框及关闭方向的位置保持不变"}, 0, 0),
        _n("n5", "acq_force",
           {"sample_rate_sa_per_s": 2000,
            "channels": ["pinch_force_n", "position_mm", "opening_mm", "current_a"]}, 0, 0),
        _n("n6", "branch",
           {"condition": "retract_triggered == True",
            "true_to": "n7", "false_to": "n99",
            "note": "没触发回缩不是「判据不达标」而是「防夹功能未工作」，"
                    "两者在报告里的定性不同，所以走异常出口而不是 FAIL 分支"}, 0, 0),
        _n("n7", "calc_retract",
           {"outputs": ["peak_pinch_force_n", "opening_at_trigger_mm",
                        "opening_after_mm", "detect_latency_ms"]}, 0, 0),
        _n("n8", "judge_pinch",
           {"requirement_id_by_market": {"CN": "TR-PINCH-01 + TR-PINCH-02",
                                         "US": "TR-PINCH-03",
                                         "EU": "TR-PINCH-04"},
            "max_force_n": 100.0, "opening_range_mm": [4.0, 200.0],
            "note": "同一次采集，换目标市场即换判据表——本场景最有演示价值的一屏"}, 0, 0),
        _n("n9", "end", {}, 0, 0),
    ]
    err = _n("n99", "error_exit",
             {"on_fault": "力越过 100 N 立即切断被测件供电（SI-HW-01），"
                          "本次判 FAIL 且不可自动重试"}, 0, 0)
    N.append(err)
    main = [x for x in N if x["id"] != "n99"]
    E = _chain(main, err, skip_err=("n6",))
    E.append(_e("n6", "n99", "false"))
    return {"nodes": N, "edges": E}


def _wf_durability():
    """WF-004 耐久试验。10 个节点，六类抽象齐全，含温度分段的外层循环。"""
    N = [
        _n("n1", "start", {}, 0, 0),
        _n("n2", "set_chamber",
           {"stages": [["常温", 23.0, None, 3000], ["高温", 80.0, None, 1500],
                       ["湿热", 60.0, 90, 2500], ["低温湿", 10.0, 95, 1000],
                       ["低温", -30.0, None, 1000], ["常温", 23.0, None, 1000]],
            "load_mode": "MAX_RATED_LOAD",
            "pretreatment": "托架升至上止点堵转 1 s、切断电源、90 ℃ 放置 2 h",
            "mud_water": {"water_pct": 92.5, "dust_pct": 7.5,
                          "dust_spec": "ISO 12103-1，50 % A2 + 50 % A4"},
            "note": "表 7 的 13 道工序，各段之间喷洒泥水"}, 0, 0),
        _n("n3", "loop",
           {"count": 10000, "rear_door_count": 5000, "back_to": "n4",
            "counter": "total_cycles",
            "break_condition": "gear_slip == True or jam_detected == True "
                               "or plastic_crack == True"}, 0, 0),
        _n("n4", "cmd_up",
           {"to": "上止点", "stall_s": 1.0, "dwell_s": 4.0,
            "note": "单循环波形：起始位置 → 上止点堵转 1 s 停 4 s → 1/3 位置 "
                    "→ 下止点堵转 1 s 停 4 s，末次停 60 s"}, 0, 0),
        _n("n5", "cmd_down",
           {"to": "下止点", "via": "1/3 位置", "stall_s": 1.0,
            "dwell_s": 4.0, "last_cycle_dwell_s": 60.0}, 0, 0),
        _n("n6", "acq_current",
           {"sample_rate_sa_per_s": 2000,
            "channels": ["current_a", "position_mm", "speed_mm_s"],
            "sampling_policy": "每 500 个循环抽录一整条波形，不全程录",
            "note": "10 000 个循环全程按 2 kHz 录是 TB 级，必须抽样。"
                    "抽样间隔是台架口径，标准没有规定"}, 0, 0),
        _n("n7", "calc_deviation",
           {"baseline": "试验前基本性能基线", "allowed_deviation": 0.20,
            "items": ["工作电流", "堵转力", "运行速度", "工作噪音"]}, 0, 0),
        _n("n8", "judge_deviation",
           {"requirement_id": "TR-DUR-01", "max_deviation": 0.20,
            "also_checks": ["功能正常", "无异响", "无跳齿打滑", "无卡滞",
                            "塑料件无裂纹"]}, 0, 0),
        _n("n9", "end", {}, 0, 0),
    ]
    err = _n("n99", "error_exit",
             {"on_fault": "中止并保留已完成循环数，报告里如实写实际循环数而不是目标数"}, 0, 0)
    N.append(err)
    main = [x for x in N if x["id"] != "n99"]
    E = _chain(main, err)
    E.append(_e("n3", "n4", "true"))
    return {"nodes": N, "edges": E}


WF_DEFS = [
    ("WR-WF-001", "上升下降循环（基本性能）", "基本性能", _wf_basic_cycle,
     "在试验电压 13.5 ± 0.3 V、额定负载下跑完整上升与下降，"
     "换算运行速度并判定速度区间与工作电流上限。耐高温与耐低温条款各跑 5 个循环。",
     ["TR-BASIC-01", "TR-BASIC-02", "TR-BASIC-05", "TR-BASIC-06",
      "TR-ENV-01", "TR-ENV-02"]),
    ("WR-WF-002", "堵转试验", "堵转", _wf_stall,
     "托架升到上止点使电机堵转，同步测堵转电流与堵转力，"
     "两项判据一个是上限（≤28 A）一个是下限（≥212 N），方向相反。",
     ["TR-BASIC-03", "TR-BASIC-04"]),
    ("WR-WF-003", "防夹试验", "防夹", _wf_antipinch,
     "在开口 170 mm 处布置刚度 10 N/mm 的半刚性试验棒，"
     "验证夹持力超过 100 N 之前是否回缩、回缩后是否达到法规要求的位置。"
     "目标市场不同则判据换表（中国 TR-PINCH-01 / 美国 TR-PINCH-03 / 欧洲 TR-PINCH-04）。",
     ["TR-PINCH-01", "TR-PINCH-02", "TR-PINCH-03", "TR-PINCH-04", "TR-PINCH-05"]),
    ("WR-WF-004", "耐久试验", "耐久", _wf_durability,
     "最大额定负载下按表 7 的 13 道工序累计 10 000 个循环（后门 5 000），"
     "各温度段之间喷洒泥水，试验后与基线比对求偏差。",
     ["TR-DUR-01", "TR-DUR-02"]),
]


def gen_workflows():
    os.makedirs(WF_DIR, exist_ok=True)
    wfs = []
    for wid, name, group, fn, purpose, reqs in WF_DEFS:
        model = fn()
        model["meta"] = {
            "id": wid,
            "name": name,
            "formatVersion": "1.0.0",
            "compressed": False,
            "tags": ["scene:%s" % SCENE_ID, "group:%s" % group, "placeholder:true"],
            "isSubsystem": False,
            "category": group,
            "isTemplate": True,
            "note": "示例工作流，不是任何客户的真实 .wfw 文件。"
                    "节点类型是本包定义的六类抽象，不是峰岹客户端 WorkflowNodeType 枚举里的成员。",
        }
        model["variables"] = []
        fname = "%s.json" % wid
        with open(os.path.join(WF_DIR, fname), "w", encoding="utf-8") as f:
            json.dump(model, f, ensure_ascii=False, indent=2)
            f.write("\n")
        counts = {}
        for nd in model["nodes"]:
            counts[nd["type"]] = counts.get(nd["type"], 0) + 1
        gcounts = {}
        for nd in model["nodes"]:
            gcounts[nd["group"]] = gcounts.get(nd["group"], 0) + 1
        wfs.append({
            "id": wid,
            "name": name,
            "metadata_name": name,
            "group": {"key": group, "name": group},
            "voltage_level": "12V",
            "voltage_level_name": "12 V 系统",
            "is_subworkflow": False,
            "file_path": os.path.join(WF_DIR, fname),
            "file_size_bytes": os.path.getsize(os.path.join(WF_DIR, fname)),
            "gzip": False,
            "format_version": "1.0.0",
            "tags": model["meta"]["tags"],
            "updated_at": BUILD_DATE,
            "node_count": len(model["nodes"]),
            "edge_count": len(model["edges"]),
            "node_types": [{"type": t, "name": NODE_TYPE_LEGEND[t][0], "count": c}
                           for t, c in sorted(counts.items())],
            "node_group_counts": gcounts,
            "purpose": purpose,
            "purpose_derived": False,
            "covers_requirements": reqs,
            "_placeholder": True,
            "_source": [
                b("188-207", "流程 3 判据表：本工作流覆盖的判据逐条出自该表"),
                src(os.path.join(OUT, "test-requirements.json"),
                    "requirements 数组中 id 为 %s 的条目" % " / ".join(reqs)),
            ],
        })

    return dump("workflows.json", {
        "schema": "workflows/v1",
        "scene_id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "belongs_to_flow": "F3 测试需求确认（工作流一步步运转、可调整）+ F4 启动测试及结果分析（执行）",
        "source_roots": [WF_DIR],
        "total": len(wfs),
        "count_by_group": {w["group"]["key"]: 1 for w in wfs},
        "all_placeholder": True,
        "node_groups": NODE_GROUPS,
        "node_type_legend": {k: v[0] for k, v in NODE_TYPE_LEGEND.items()},
        "model_format": {
            "note": "assets/workflows/*.json 用的是工作流画布组件的统一内部模型，"
                    "可直接喂给 WorkflowCanvas，不需要经过 parseWfw。",
            "shape": "{ nodes: [{id, type, label, group, params, position}], "
                     "edges: [{id, source, target, sourceHandle, targetHandle}], "
                     "meta: {...}, variables: [] }",
            "source_handles": {
                "output": "主干，画墨绿实线",
                "error": "异常出口，画暗红虚线",
                "true": "条件分支真支",
                "false": "条件分支假支，画暗红虚线",
            },
            "_source": src(os.path.expanduser("[源] workflow/README.md"),
                           "§2.2 结构层、§2.3 坑 2（sourceHandle 承载分支语义）、"
                           "§3.1 统一内部模型 WorkflowModel"),
        },
        "notes": [
            "**本场景没有任何现成的 .wfw 文件。** 这 4 条全部是本包按第一个场景包的结构造的示例，"
            "每条都带 _placeholder: true。它们证明的是「同一套画布与索引结构能装下新场景」，"
            "不是「客户已有这些工作流」。",
            "节点类型是本包定义的六类抽象（设置 / 激励 / 采集 / 判定 / 控制流 / 数据处理），"
            "与场景一里那 25 个峰岹客户端专有节点类型（hid_preset_* / rigol_oscilloscope 等）"
            "没有一个重合——这正是「换场景只换包」要证明的：画布与索引不变，节点词汇表随包走。",
            "每个非起止节点都拉一条 error 边到公共异常出口，所以连线数多于节点数。"
            "这个做法是从场景一的真实 .wfw 文件里学来的（14 节点 / 20 连线的图，多出的正是 error 边）。",
        ],
        "workflows": wfs,
    })


# ============================ datasets.json ============================

def gen_datasets():
    stats = gen_waveforms.build()
    by_name = {os.path.basename(s["file"]): s for s in stats}
    cols = [{"key": k, "name": v} for k, v in gen_waveforms.COLUMNS]

    model_note = (
        "一阶有刷直流电机电气-机械耦合模型，显式欧拉积分："
        "L·di/dt = U·duty − R·i − Ke·ω；J·dω/dt = Kt·i − B·ω − T_load；"
        "dx/dt = k_arm·ω；F_out = Kt·i·η / k_arm_m。"
        "参数：U=13.5 V、R=0.52 Ω、L=0.80 mH、Ke=Kt=0.020、J=2.0e−5 kg·m²、"
        "B=2.0e−6、k_arm=0.226 mm/rad、η=0.105、每转纹波 8 个、纹波深度 6 %。"
        "内部按 20 kHz 积分，箱式平均降采样到 2000 Sa/s 输出。"
    )
    calib_note = (
        "参数是标定到让稳态量落在 QC/T 626-2019 征求意见稿给的量级上的："
        "堵转电流 U/R ≈ 26 A（低于 5.4.1 b) 的 28 A 上限）、"
        "上升速度约 118 mm/s（落在 5.4.1 d) 的 80~160 mm/s 区间中部）、"
        "堵转力约 240 N（高于 5.4.1 c) 的 212 N 下限）。"
        "**这是「让示例数据看起来合理」的标定，不是任何真实产品的参数辨识结果。**"
    )

    def ds(key, fname, title, label, note):
        s = by_name[fname]
        return {
            "id": key,
            "name": title,
            "mode": "generated_into_pack",
            "synthetic": True,
            "_placeholder": True,
            "file_path": s["file"],
            "file_size_bytes": s["size"],
            "row_count": s["rows"],
            "columns": cols,
            "sample_rate_sa_per_s": 2000.0,
            "duration_s": 12.0,
            "generator": "_build/gen_waveforms.py",
            "synthesis_model": model_note,
            "calibration": calib_note,
            "measured_range": {
                "current_a": [round(s["i_min"], 2), round(s["i_max"], 2)],
                "speed_mm_s": [round(s["v_min"], 1), round(s["v_max"], 1)],
                "pinch_force_n_max": round(s["fp_max"], 1),
                "position_mm_max": round(s["x_max"], 1),
            },
            "phases": s["phases"],
            "label": label,
            "note": note,
            "_source": [
                b(286, "汽车低压执行器电机的专用公开波形数据集，在十三个平台上确认为空白"),
                b(314, "gym-electric-motor（帕德博恩大学，MIT）：直流电机模型与可配参数"),
                b("325", "参数锚点：工作电流 ≤12 A、堵转电流 ≤28 A、堵转力 ≥212 N、"
                         "上升速度 80–160 mm/s、工作电压 9–16 V"),
                src(os.path.join(OUT, "_build/gen_waveforms.py"),
                    "模块 docstring 与 PROFILES 里对应的 profile 函数"),
            ],
        }

    datasets = [
        ds("normal-up-down-cycle", "normal-up-down-cycle.csv",
           "正常升降电流曲线（合成）",
           {"expected_result": "PASS",
            "meaning": "上升速度与工作电流均在判据内，上止点堵转电流低于 28 A 上限"},
           "时间轴照 QC/T 626 征求意见稿 6.9.1 注 3 的耐久单循环波形排："
           "上升 3.5 s → 上止点堵转 1 s → 断电停 4 s → 下降。"
           "可直接喂给 WR-WF-001 与 WR-WF-004 做回放。"),
        ds("antipinch-trigger", "antipinch-trigger.csv",
           "防夹触发电流突增（合成）",
           {"expected_result": "PASS",
            "meaning": "在开口约 167 mm 处检出夹持，夹持力峰值约 42 N，"
                       "远低于 100 N 硬顶，随后回缩 60 mm"},
           "障碍物用刚度 10 N/mm 的半刚性试验棒建模（GB 11552-2009 §4.8.3.1.3 的测量工具刚度），"
           "夹持力 = 刚度 × 侵入量。pinch_force_n 列是给 TR-PINCH-01 判据直接取数用的。"
           "phase 列标出 UP → PINCH_CONTACT → PINCH_DETECTED → RETRACT → RETRACT_DONE 五相。"),
        ds("stall-saturation", "stall-saturation.csv",
           "堵转电流饱和平台（合成）",
           {"expected_result": "PASS（电流），但工况本身违反 SI-HW-03",
            "meaning": "电流爬到 U/R 的饱和平台约 26 A 并持续 5.3 s；"
                       "电流本身不越 28 A 上限，但堵转持续时间的台架保护另算"},
           "**本条刻意不启用堵转保护**，目的是录出完整的饱和平台，"
           "用来标定 control-parameters.json 的 stall_current_threshold（默认 24 A）与"
           "stall_debounce_time。真实台架上这样跑会撞上 SI-HW-03（堵转持续时间上限 30 s），"
           "本条 5.3 s 的堵转在限内，但不得把这条数据当成「允许长时间堵转」的依据。"),
    ]

    return dump("datasets.json", {
        "schema": "datasets/v1",
        "scene_id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "belongs_to_flow": "F4 启动测试及结果分析（时序曲线回放与判定）",
        "all_synthetic": True,
        "synthetic_banner": "本场景包的全部时序数据都是合成的，不是实测。"
                            "前端展示时必须显式标注「合成，非实测」，"
                            "并且不得进入任何合规报告（见 safety-interlocks.json SI-PR-05）。",
        "why_synthetic": {
            "text": "汽车低压执行器电机（雨刮、车窗、天窗、座椅、EPS、节气门）的专用公开波形数据集，"
                    "在十三个数据平台上检索确认为空白。这是检索证实的结论，不是遗漏。"
                    "本包因此走参数化仿真这一路。",
            "platforms_searched": [
                "Kaggle（含元数据 API）", "IEEE DataPort", "Zenodo（含 REST API）",
                "Figshare", "Mendeley Data", "Hugging Face Datasets",
                "UCI 机器学习仓库", "GitHub", "PHM Society 数据挑战",
                "NASA 预测数据仓库", "OpenML（含 REST API）", "Papers with Code",
                "科学数据银行 ScienceDB",
            ],
            "_source": [b(286, "核心结论先说：十三个平台确认为空白"),
                        b(466, "数据集平台（13 个）检索通道表")],
        },
        "real_data_alternatives": [
            {
                "id": "cartif-brushed-dc",
                "name": "F.A.I.R. open dataset of brushed DC motor faults for testing of "
                        "AI algorithms（有刷直流电机故障数据集）",
                "publisher": "西班牙 CARTIF 技术中心（Fundación CARTIF，巴利亚多利德），2020",
                "url": "https://zenodo.org/records/4314249",
                "doi": "10.5281/zenodo.4314249",
                "content": "振动（g）+ 电流（A）+ 电压（V）；小型有刷直流电机；"
                           "故障从 30 分钟演化到 6 小时",
                "format": "HDF5 + Excel，483 MB",
                "license": "CC BY 4.0",
                "mode": "registered_only",
                "note": "本次调研中离「汽车低压执行器」结构最近的真实集——"
                        "雨刮、车窗、座椅电机正是有刷直流。**本包只登记，未下载。**",
                "_source": b(297, "第一层真实实测表 CARTIF 行（已核实）"),
            },
            {
                "id": "paderborn-motor-temperature",
                "name": "Electric Motor Temperature（车用永磁同步电机台架温度与电气量数据集）",
                "publisher": "德国帕德博恩大学电驱动系统教研室（Universität Paderborn, LEA）；"
                             "Kaggle 账号 wkirgsn（Wilhelm Kirchgäßner）发布",
                "url": "https://www.kaggle.com/datasets/wkirgsn/electric-motor-temperature",
                "content": "12 通道，含 d/q 轴电流电压、转速、转矩、四处温度；"
                           "采样率 2 Hz，总时长 185 小时",
                "format": "CSV，约 286 MB",
                "license": "CC BY-SA 4.0，可商用，需署名 + 相同方式共享",
                "mode": "registered_only",
                "note": "真实车用数据，但采样率只有 2 Hz，且被测件是永磁同步机不是有刷直流，"
                        "只能做工况级慢速时序的参照，做不了本场景的电流波形判据。"
                        "**本包只登记，未下载。**",
                "_source": b(294, "第一层真实实测表 Electric Motor Temperature 行（已核实）"),
            },
            {
                "id": "paderborn-bearing",
                "name": "帕德博恩大学轴承数据中心数据集（KAt-DataCenter Bearing Dataset）",
                "publisher": "德国帕德博恩大学设计与传动技术教研室，Lessmeier 等，2016",
                "url": "https://groups.uni-paderborn.de/kat/BearingDataCenter/",
                "content": "电机相电流与振动加速度同步采集；32 种轴承状态 × 4 工况",
                "license": "CC BY-NC 4.0，**禁止商用**，商用需联系作者",
                "mode": "registered_only",
                "note": "若本案例属商业交付，该许可证是硬约束，不能用。登记在此是为了让"
                        "「许可证审查」这一步在知识库里有据可查。",
                "_source": b(299, "第一层真实实测表 帕德博恩轴承数据中心 行"),
            },
        ],
        "excluded_datasets": {
            "note": "已明确排除，避免后续重复捞。",
            "items": [
                "SiCWell Dataset（IEEE DataPort, DOI 10.21227/mnmw-8c42）：实为车规锂电池单体数据，不含电机量",
                "ziya07/bldc-motor-dataset（Kaggle）：页面自认 synthetic，且为设计参数表",
                "sabermalek/imfds（Kaggle）：链接 404",
                "Three Phase Induction Motor Stator Fault Data（IEEE DataPort, DOI 10.21227/0kwj-g017）：平台标注数据文件尚未上传",
                "Brushless DC Motor sound dataset for PdM（Mendeley, j4yr5fmhv4）：实为无人机 A2212 电机音频",
            ],
            "suspect_items": [
                "KoNAMIC Electronic Throttle Body Experimental Dataset（Zenodo, DOI 10.5281/zenodo.22096081）："
                "全网唯一命名匹配「电子节气门」的数据集，但记录页未给通道与采样率、文件仅 790 189 字节、"
                "其关联仓库实际内容是四旋翼与倒立摆的 Koopman 辨识。内容真实性存疑，使用前必须下载解包人工确认",
                "Fault Diagnosis Dataset for New Energy Vehicles（Kaggle 账号 ziya07）："
                "无台架、无车型、无机构说明；同一上传者的其他数据集自认为合成数据。高度怀疑为合成",
            ],
            "_source": [b(308, "已明确排除清单"), b("305-306", "存疑条目表")],
        },
        "datasets": datasets,
    })


# ============================ experience.json ============================

def gen_experience():
    E = []

    def ex(eid, symptom, cause, action, result, tags, level, source, status=None):
        d = {"id": eid, "symptom": symptom, "cause": cause,
             "action": action, "result": result, "tags": tags,
             "evidence_level": level}
        if status:
            d["_status"] = status
        d["_source"] = source
        return d

    E += [
        ex("EXP-001",
           "正常关窗到最后几厘米就被判成夹持，窗关不上",
           "防夹生效区间的上沿或软停位置压进了密封压紧段，密封条阻力带来的电流上翘被当成夹持",
           "把 soft_stop_position 提到密封段之前，或把防夹力阈值上调；"
           "两者都不能把生效区间下沿抬到 4 mm 以上，那会直接不合规",
           "误触发消失且下沿仍守在 4 mm 则通过；若必须抬下沿才能关窗，说明密封设计要改，不是调参能解决的",
           {"参数": "antipinch_window_lower / soft_stop_position", "现象": "误触发",
            "流程": "F5 调优确认及运行"},
           "文献综合",
           [b(350, "防夹调参清单「防夹生效区间（行程窗口）」行：进入密封压紧段仍生效则无法正常关窗"),
            b(354, "回缩行程量行")],
           status="待核实（来源为素材综述文档对多份参考设计资料的综合，非任一来源原文）"),
        ex("EXP-002",
           "启动瞬间就报夹持，一按上升就回缩",
           "启动浪涌电流被误判为夹持特征",
           "延长 startup_blanking_time；同时把 soft_start_ramp 拉长以削低浪涌峰值，两个参数一起调",
           "屏蔽时间够长则误触发消失，但屏蔽窗内的真实夹持会漏检——必须用 TR-PINCH-05 复测启动段夹持",
           {"参数": "startup_blanking_time / soft_start_ramp", "现象": "误触发",
            "流程": "F5 调优确认及运行"},
           "文献综合",
           [b(351, "防夹调参清单「启动段屏蔽时间」行"),
            b(341, "Research on Anti-pinch Control Strategy of Window Start-up Phase "
                   "based on Ripple Motor，ResearchGate 2021，"
                   "https://www.researchgate.net/publication/349300884")],
           status="待核实（该文献未确认期刊/会议全名与作者）"),
        ex("EXP-003",
           "启动段的夹持检不出来，力已经压上去了才反应",
           "屏蔽时间设得太长，夹持发生在屏蔽窗内",
           "缩短 startup_blanking_time，改用对浪涌不敏感的判据——"
           "转矩变化率对电机参数不确定性的敏感度低于转矩或角速度本身",
           "换判据后启动段能检出且不误触发则通过；仍两难则说明启动浪涌本身要靠软启动斜坡压下去",
           {"参数": "startup_blanking_time / antipinch_detect_method", "现象": "漏检",
            "流程": "F5 调优确认及运行"},
           "文献",
           [b(339, "Practical pinch detection algorithm for low-cost anti-pinch window "
                   "control system，IEEE 会议论文，https://ieeexplore.ieee.org/document/1600781")],
           status="待核实（未打开正文逐字确认）"),
        ex("EXP-004",
           "夹持力实测逼近 100 N 才回缩，余量太小",
           "防夹力阈值设得太贴近法规上限，加上检出延迟，实际峰值冲过门限",
           "把 antipinch_force_threshold 从 100 N 往下压（本包默认 80 N），"
           "同时缩短 current_slope_window 与 antipinch_confirm_count 以减小检出延迟",
           "峰值退回 100 N 以下且误触发率不升则通过；若一压阈值就误触发，说明判据信噪比不够，要换判据",
           {"参数": "antipinch_force_threshold", "现象": "力峰值超标",
            "流程": "F5 调优确认及运行"},
           "文献综合 + 法规条款",
           [b(349, "防夹调参清单「防夹力阈值」行：调大逼近或超出 100 N 法规上限，判定不合格"),
            src(GB11552_TXT, "gb11552.txt:440 §4.8.3.1.1 100 N 硬顶")]),
        ex("EXP-005",
           "同一台被测件在中国判 PASS、在美国判 FAIL",
           "回缩后位置策略选了 PLUS_50MM。中国四选一里有「多开 50 mm」，"
           "美国二选一里最少要「多开 125 mm」",
           "把 antipinch_retract_mode 改成 PLUS_125MM 或 INITIAL_POSITION，两地同时满足",
           "改成 PLUS_125MM 后三地都过；代价是用户体验变差（回缩太多），要与整车厂确认能否接受",
           {"参数": "antipinch_retract_mode", "现象": "换市场即失效",
            "流程": "F3 测试需求确认"},
           "法规条款",
           [src(GB11552_TXT, "gb11552.txt:445-452 §4.8.3.1.2 四选一"),
            b(215, "GB 11552-2009 回缩后要求四选一"),
            b(216, "FMVSS 118 回缩后要求二选一（多开 125 mm）")]),
        ex("EXP-006",
           "低速段位置累计误差越跑越大，上止点位置对不上",
           "纹波计数在低速段丢脉冲——滤波带宽或比较器迟滞设得太保守",
           "降低 ripple_comparator_hysteresis 或放宽 ripple_filter_bandwidth；"
           "同时打开 position_reset_at_top，每次上止点堵转后清零",
           "误差被上止点归零截断则可接受；若单次行程内误差就已超标，说明纹波计数本身不够用，"
           "要上霍尔锁存脉冲",
           {"参数": "ripple_filter_bandwidth / ripple_comparator_hysteresis / position_reset_at_top",
            "现象": "位置漂移", "流程": "F5 调优确认及运行"},
           "文献",
           [b(352, "防夹调参清单「纹波计数滤波带宽与迟滞」行"),
            b(146, "Automotive Brushed-Motor Ripple Counter Reference Design，德州仪器，"
                   "设计指南 TIDUD30A，https://www.ti.com/lit/ug/tidud30a/tidud30a.pdf")],
           status="待核实（TI 设计指南本次未打开正文逐字确认）"),
        ex("EXP-007",
           "到达上止点被误判成夹持，窗关不到位",
           "堵转判定门限设得太低，或防夹生效区间盖住了上止点",
           "把 stall_current_threshold 上调（但必须低于 28 A 判据上限），"
           "并确认防夹区外切换成堵转检测而不是继续跑夹持判据",
           "到位不再误判且遇障仍能检出则通过",
           {"参数": "stall_current_threshold / stall_debounce_time", "现象": "误触发",
            "流程": "F5 调优确认及运行"},
           "文献综合",
           [b(353, "防夹调参清单「堵转判定电流门限与去抖时间」行"),
            b(343, "Anti-Pinch Window Lift Reference Design（RDS12VR），恩智浦半导体，"
                   "https://www.nxp.com/docs/en/fact-sheet/RDS12VRFS.pdf："
                   "防夹区外做堵转检测")],
           status="待核实（RDS12VR 资料单 PDF 超 10 MB 抓取失败，特征来自社区条目转述）"),
        ex("EXP-008",
           "遇障后电机仍继续加力，力峰值冲过 100 N",
           "堵转判定门限设得太高，去抖时间太长，保护动作来不及",
           "下调 stall_current_threshold 与 stall_debounce_time",
           "力峰值退回限内则通过；下调后若上止点被误判，说明两条判据的门限窗口太窄，"
           "必须靠位置信息分区而不是靠门限分",
           {"参数": "stall_current_threshold / stall_debounce_time", "现象": "力峰值超标",
            "流程": "F5 调优确认及运行"},
           "文献综合",
           [b(353, "防夹调参清单「堵转判定电流门限与去抖时间」行")]),
        ex("EXP-009",
           "电流环响应慢、跟不上给定",
           "相位裕度取得太大（MCAF 默认 80°），增益被压得太低",
           "把 phase_margin 从 80° 降到 50° 至 70°；"
           "把 pi_phase_lag 从默认 45° 降到 8° 至 20°，低于 5° 不建议",
           "响应变快；代价是超调风险升高，须复测有无振荡",
           {"参数": "phase_margin / pi_phase_lag", "现象": "响应慢",
            "流程": "F5 调优确认及运行"},
           "厂商文档（已核实）",
           [b(373, "Motor Control Application Framework (MCAF) 文档 5.1.6 节 Current loop tuning，"
                   "微芯科技 MCAF R7 RC37 文档版本 7.0.2，"
                   "https://microchiptech.github.io/mcaf-doc/7.0.2/algorithms/foc/tuning.html"),
            b(374, "同文档「PI 在穿越频率处的相位滞后 φz」行")]),
        ex("EXP-010",
           "电流环带宽设高了就振荡",
           "带宽超出了 PWM 载波与机械时间常数允许的窗口",
           "把 current_loop_bandwidth 收回到 PWM 频率的 5 % 至 15 %"
           "（20 kHz 载波对应 1 至 3 kHz），并校核约束：机械时间常数 × 带宽须大于 1",
           "振荡消失；若收到 5 % 仍振荡，问题不在带宽而在采样延迟或死区补偿",
           {"参数": "current_loop_bandwidth / pwm_frequency", "现象": "振荡",
            "流程": "F5 调优确认及运行"},
           "厂商文档（已核实）",
           [b(375, "MCAF 7.0.2「电流环带宽」行：典型取 PWM 频率的 5 % 至 15 %；"
                   "约束条件机械时间常数 × 带宽须大于 1")]),
        ex("EXP-011",
           "启动时序跑不通，无法切入闭环",
           "在闭环换相不稳的前提下整定电流环，两件事互相干扰",
           "按 MCAF 的明文顺序：先在开环换相下整定电流环，再调开闭环切换",
           "顺序对了之后两件事各自收敛；顺序反了则永远在互相打架",
           {"参数": "tuning_order", "现象": "启动失败", "流程": "F5 调优确认及运行"},
           "厂商文档（已核实）",
           [b(377, "同一文档另外明确：若正常启动时序跑不通或无法正确切入闭环换相，"
                   "电流环整定需在开环换相下进行")]),
        ex("EXP-012",
           "启动斜坡上不去，大惯量负载带不动",
           "单段加速斜坡对大惯量负载太陡",
           "改多段斜坡：大惯量电机先缓斜坡后陡斜坡；"
           "另一口径是把速度斜坡终值提到最大应用转速的 40 %、把最小启动输出转速降到 10 %",
           "起转成功率上升；斜坡过缓则启动时间变长，会影响上升速度判据的计时口径",
           {"参数": "soft_start_ramp", "现象": "启动失败", "流程": "F5 调优确认及运行"},
           "厂商文档",
           [b(361, "UM3259 — STM32 motor control SDK: 6-step firmware sensorless parameter "
                   "optimization，意法半导体"),
            b(362, "STM32 Motor Control Frequently Asked Questions：Speed ramp final value "
                   "提到最大应用转速的 40 %，Minimum startup output speed 降到 10 %")],
           status="待核实（UM3259 抓取超时；FAQ 页未逐字确认）"),
        ex("EXP-013",
           "工作噪音卡在 60 dB(A) 判据边上下不来",
           "PWM 调制方式与死区补偿没优化，开关噪声进了可听频段",
           "开自动死区补偿、调 PWM 调制方式；把载波推到人耳听阈之上（20 kHz）",
           "噪音下来则通过；载波提高会加大开关损耗与温升，要复测热保护相关判据",
           {"参数": "pwm_frequency / deadtime", "现象": "噪音超标",
            "流程": "F5 调优确认及运行"},
           "厂商文档",
           [b(364, "How to Reduce Motor Noise with Code-Free, Sensorless FOC，德州仪器，"
                   "文献号 SLLA567，https://www.ti.com/lit/an/slla567/slla567.pdf"),
            b(365, "Driving Brushed DC Motors Using PWM Output: Losses and Points to be Noted，"
                   "罗姆半导体 TechWeb 技术专栏条目 346，"
                   "https://techweb.rohm.com/product/motor/motor-types/346/")],
           status="待核实（两篇均未打开正文逐字确认）"),
        ex("EXP-014",
           "低温下上升速度掉到 80 mm/s 以下被判 FAIL",
           "拿常温判据去判低温工况。低温下润滑脂黏度上升、阻力增大，判据本身就该换表",
           "把判据从 TR-BASIC-05（80 至 160 mm/s）切到 TR-ENV-02（−30 ℃ 下 ≥60 mm/s）",
           "换表后合格；若在低温判据下仍不合格，才是真问题，该查润滑脂牌号与装配预紧",
           {"参数": "chamber_temperature", "现象": "误判 FAIL",
            "流程": "F3 测试需求确认"},
           "标准条款",
           [b(193, "耐低温特性 5.6.2 / 6.6.2：上升速度 ≥60 mm/s，工作电流放宽到 20 A"),
            b(127, "常温上升运行速度 80 至 160 mm/s")],
           status="待核实（QC/T 626-2019 正式版可能调整）"),
        ex("EXP-015",
           "EMC 报告按标准做完了，评审说引错了标准",
           "QC/T 626 征求意见稿引的 GB/T 18655-2010 与 GB/T 21437.2-2008 都已换版",
           "改引现行版：GB/T 18655-2025（已代替 2018 版）与 GB/T 21437.2-2021；"
           "盐雾条款引的 GB/T 10125-2012 同样要改成 2021 版",
           "改引后通过。知识库必须内置换版预警元数据，靠人记不住",
           {"参数": "无", "现象": "引用过期", "流程": "F1 知识库管理"},
           "标准状态（已核实）",
           [b(206, "电磁兼容性 5.12.4：两本引用标准均已换版"),
            b(81, "GB/T 18655-2025 已代替 GB/T 18655-2018"),
            b(85, "GB/T 10125-2021 全部代替 GB/T 10125-2012"),
            b("105-110", "换版预警表")]),
        ex("EXP-016",
           "想找实测波形来验证防夹算法，十三个平台都没搜到",
           "汽车低压执行器电机的专用公开波形数据集确实是空白，不是没搜到",
           "走三层数据方案：车用工况级慢速时序（真实但 2 Hz）+ 波形级有刷直流故障集"
           "（真实但非汽车执行器）+ 参数化仿真合成（补齐执行器空白）",
           "本包实际只落地了第三层（三条合成 CSV），前两层只登记不下载。"
           "合成数据必须在界面标注来源，且不得进合规报告",
           {"参数": "无", "现象": "数据缺口", "流程": "F4 启动测试及结果分析"},
           "检索结论（已核实）",
           [b(286, "核心结论先说：十三个平台确认为空白"),
            b(429, "与峰岹案例对照表流程 4 行：合成数据必须在界面标注来源")]),
        ex("EXP-017",
           "OEM 规范里的参数拿来就用，法务打回",
           "LV 124、VW 80000、LV 148、BMW GS 95024 的本地副本都是公网流传的非授权版本",
           "内容可做工程参考，正式引用前须经采购渠道取得授权原本复核",
           "取得授权原本后通过。知识库里这类文档要单独打「非授权副本」标记",
           {"参数": "无", "现象": "引用资格不足", "流程": "F1 知识库管理"},
           "来源状态（已核实）",
           [b(94, "LV 124：该 PDF 为公网流传的非授权副本"),
            b(95, "VW 80000：同为非授权副本"),
            b(464, "OEM 规范通道：内容可信但均为公网流传的非授权副本")]),
        ex("EXP-018",
           "力传感器一支想通吃所有工位，结果两头不讨好",
           "同一场景里有三个量级：防夹 100 N 要分辨率、堵转力 212 N 要量程、自锁 600 N 要更大量程",
           "分开选型：防夹工位用小量程高分辨率，自锁工位用大量程；不要用一支 500 N 的去凑",
           "分开后三项判据都能测准。这个冲突应该在 F2 初始化配置就暴露给用户确认，"
           "而不是等测出问题再回头查",
           {"参数": "force_sensor_range", "现象": "量程冲突", "流程": "F2 初始化配置"},
           "标准条款推断",
           [b(126, "堵转力 ≥212 N，力传感器量程选型依据"),
            b(131, "自锁能力 600 N 保持 5 s"),
            b(166, "防夹力 100 N")],
           status="「分开选型」是本包从三个量级并存这一事实推出的结论，不是标准原文"),
    ]

    levels = {}
    for e in E:
        levels[e["evidence_level"]] = levels.get(e["evidence_level"], 0) + 1

    return dump("experience.json", {
        "schema": "experience/v1",
        "scene_id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "belongs_to_flow": "F1 知识库管理（经验性质那一类的样例数据）；被 F4 / F5 在调参时检索命中",
        "count": len(E),
        "evidence_levels": {
            "厂商文档（已核实）": "来自芯片厂或框架厂的公开文档，本次调研已打开正文逐字确认",
            "厂商文档": "来自芯片厂公开文档，但本次未打开正文逐字确认",
            "文献": "来自单篇公开论文，未打开正文逐字确认",
            "文献综合": "本包对多份参考设计资料的综合，非任一来源原文",
            "法规条款": "来自 GB / FMVSS / ECE 法规原文，已逐字核实",
            "标准条款": "来自 QC/T 626-2019 征求意见稿，整体待核实",
            "标准条款推断": "由标准给出的多个数值推出的结论，不是标准原文",
            "标准状态（已核实）": "标准的发布、代替与换版关系，已在官方登记库核实",
            "来源状态（已核实）": "文档来源的授权状态，已核实",
            "检索结论（已核实）": "本次调研的检索覆盖与零命中结论",
        },
        "evidence_level_counts": levels,
        "schema_note": "每条 = 问题现象 symptom / 原因 cause / 调整动作 action / "
                       "结果 result / 标签 tags / 证据档位 evidence_level / 来[源] _source。"
                       "与场景一的差别：场景一的经验大多来自客户台架实测与成文规程，"
                       "本场景的经验全部来自公开文献与标准条款，一条实测都没有——"
                       "这正是「公开标准驱动」与「客户私有经验驱动」两类知识库的分野。",
        "difference_from_scene1": "场景一的 evidence_level 有「台架实测数据」「判定工具输出」两档，"
                                  "本场景一条都没有，因为没有实物台架。"
                                  "反过来本场景多出「法规条款」「标准状态」「来源状态」三档，"
                                  "因为它的知识全部是可被第三方复核的公开材料。",
        "experiences": E,
    })


# ============================ documents.json ============================

def _doc(did, dtype, title, path, flows, status, note=None, url=None,
         source=None, placeholder=False, doc_status=None):
    exists = bool(path) and os.path.exists(path)
    d = {"id": did, "type": dtype, "title": title, "path": path,
         "size_bytes": os.path.getsize(path) if exists else None,
         "exists": exists, "used_in_flows": flows,
         "conversion_status": status}
    if url:
        d["url"] = url
    if note:
        d["note"] = note
    if doc_status:
        d["_status"] = doc_status
    if placeholder:
        d["_placeholder"] = True
    d["_source"] = source
    return d


def gen_documents():
    F1 = "F1 知识库管理"
    F2 = "F2 初始化配置"
    F3 = "F3 测试需求确认"
    F4 = "F4 启动测试及结果分析"
    F5 = "F5 调优确认及运行"
    F6 = "F6 测试报告及产出"
    D = []

    # ---- 产品直接对口标准 ----
    D += [
        _doc("DOC-STD-001", "产品标准",
             "QC/T 626-2019《汽车玻璃升降器》（中华人民共和国工业和信息化部发布，"
             "全国汽车标准化技术委员会 SAC/TC 114 归口，起草单位重庆海德世拉索系统（集团）"
             "有限公司、汉阳专用汽车研究所；2019-11-11 发布 / 2020-04-01 实施，现行，"
             "同时代替 QC/T 626-2008 与 QC/T 636-2014）",
             None, [F1, F3], "未取得",
             note="行业标准信息服务平台以「潜在版权问题」不公开全文，需采购。"
                  "本包所有标注「待核实（QC/T 626-2019 正式版可能调整）」的数值，"
                  "等的就是这份正文。",
             url="https://hbba.sacinfo.org.cn/stdDetail/9ca3b738497da0d0d84ae02e3b7e1815"
                 "c9dd070e4233e5d3a3ba126dad340b73",
             doc_status="编号与代替关系已核实；正文未取得",
             source=b(64, "QC/T 626-2019 全名、机构、日期与代替关系")),
        _doc("DOC-STD-002", "产品标准（征求意见稿）",
             "《汽车玻璃升降器》行业标准征求意见稿（拟代替 QC/T 626-2008、QC/T 636-2014；"
             "中国汽车技术研究中心有限公司 CATARC 官网公开挂载，16 页 PDF）",
             QC626_TXT, [F1, F2, F3, F4], "已抽取纯文本",
             note="**本场景包的主要数值来源。** PDF 全文已下载并逐条提取为纯文本，"
                  "含第 5 章要求与第 6 章试验方法全部条款。"
                  "文件本身已核实（本次下载并逐条提取），"
                  "但其数值相对正式版可能调整，由它来的判据一律标待核实。",
             url="https://www.catarc.org.cn/upload/201807/13/201807131600519972.pdf",
             doc_status="文件已核实；数值待核实",
             source=b(65, "征求意见稿全名、来源、可用形态与可信度")),
        _doc("DOC-STD-003", "法规",
             "GB 11552-2009《乘用车内部凸出物》（英文名 The interior fittings of "
             "passenger car；国家质量监督检验检疫总局与国家标准化管理委员会联合发布，"
             "工业和信息化部归口；2009-09-30 发布 / 2012-01-01 实施，现行，代替 GB 11552-1999）",
             GB11552_TXT, [F1, F3, F6], "已抽取纯文本",
             note="**防夹判据的第一来源。** 报批稿全文 32 页已提取，"
                  "第 4.8 条「车窗、天窗及隔断系统的电操作」原文逐字可引，"
                  "含 4.8.2 无防夹时的替代要求、4.8.3 自动回缩要求、4.8.5 保护装置、"
                  "4.8.6 用户手册指南。",
             url="https://law.resource.org/pub/cn/ibr/gb.11552.c.2009.pdf",
             doc_status="已核实（第 4.8 条本次直接从 PDF 文本层提取）",
             source=b(67, "GB 11552-2009 全名、机构、日期与可用形态")),
        _doc("DOC-STD-004", "法规",
             "49 CFR § 571.118 — Standard No. 118; Power-operated window, partition, "
             "and roof panel systems（美国联邦机动车安全标准第 118 号：电动车窗、隔板与顶板系统；"
             "美国国家公路交通安全管理局 NHTSA）",
             None, [F1, F3], "未转化",
             note="网页全文，含试验方法与判据。100 N 与 4–200 mm 已核实；"
                  "条款编号 S4/S7/S8 待核实。",
             url="https://www.ecfr.gov/current/title-49/subtitle-B/chapter-V/part-571/"
                 "subpart-B/section-571.118",
             doc_status="100 N 与 4–200 mm 已核实；条款编号待核实",
             source=b(69, "49 CFR § 571.118 全名、机构与 URL")),
        _doc("DOC-STD-005", "法规",
             "UN ECE R21 — Uniform Provisions Concerning the Approval of Vehicles with "
             "Regard to Their Interior Fittings（联合国欧洲经济委员会第 21 号法规："
             "车辆内饰认证统一规定；联合国欧洲经济委员会 UNECE），第 5.8 条系列",
             None, [F1, F3], "未转化",
             url="https://unece.org/DAM/trans/main/wp29/wp29wgs/wp29grsp/grspinf/28/28-inf01.pdf",
             doc_status="待核实（未打开原文逐字确认）",
             source=b(70, "UN ECE R21 全名、机构与 URL")),
        _doc("DOC-STD-006", "法规立法背景",
             "Federal Motor Vehicle Safety Standards; Power-Operated Window, Partition, "
             "and Roof Panel Systems（FMVSS 118 规则制定文件；美国联邦公报 Federal Register，"
             "文件号 E9-21042，2009-09-01）",
             None, [F1, F3], "未转化",
             note="给出试验棒尺寸区间的立法理由：4 mm 对应幼儿手指，"
                  "200 mm 对应第 95 百分位成年男性头部最大宽度。"
                  "这是把「4 至 200 mm」这个数字讲清楚的唯一公开出处。",
             url="https://www.federalregister.gov/documents/2009/09/01/E9-21042/"
                 "federal-motor-vehicle-safety-standards-power-operated-window-partition-and-roof-panel",
             doc_status="已核实",
             source=b(71, "Federal Register 文件号 E9-21042 与立法理由")),
        _doc("DOC-STD-007", "法规",
             "GB 7258-2017《机动车运行安全技术条件》（国家标准化管理委员会，强制性国家标准）",
             None, [F1, F3], "未转化",
             note="整车级要求：车窗与天窗在移动中能在任意位置可靠停住，或遇障碍可自动下降回缩。",
             doc_status="待核实（未取得标准原文条款号，经第三方解读页转述）",
             source=b(68, "GB 7258-2017 整车级要求，经解读页转述")),
        _doc("DOC-STD-008", "沿革参照",
             "QC/T 636-2014《汽车电动玻璃升降器》（工业和信息化部，2014-05-06 发布 / "
             "2014-10-01 实施，**已废止**，被 QC/T 626-2019 代替）",
             None, [F1], "未转化",
             url="https://hbba.sacinfo.org.cn/stdDetail/479072c1dba6d1cf28a8c5a281020203",
             doc_status="已核实（已废止，仅作沿革参照）",
             source=b(66, "QC/T 636-2014 全名、日期与废止状态")),
    ]
    # ---- 通用底座与环境试验标准 ----
    D += [
        _doc("DOC-ENV-001", "环境试验标准",
             "ISO 16750-1:2023 Road vehicles — Environmental conditions and testing for "
             "electrical and electronic equipment — Part 1: General（道路车辆 电气电子设备的"
             "环境条件与试验 第 1 部分：一般规定；国际标准化组织 ISO，技术委员会 ISO/TC 22/SC 32）",
             ISO16750_1_PDF, [F1, F3], "PDF 可直接渲染",
             note="正式预览件，含完整目录与部分开放正文页。功能状态分级 class A/B/C/D 出自此部分。",
             url="https://www.iso.org/standard/77578.html",
             doc_status="编号、版次、页数、条款清单已核实",
             source=b(79, "ISO 16750 系列第 1 至 5 部分，均为 2023 版")),
        _doc("DOC-ENV-002", "环境试验标准",
             "ISO 16750-2:2023 — Part 2: Electrical loads（第 2 部分：电气负荷）",
             ISO16750_2_PDF, [F1, F2, F3], "PDF 可直接渲染",
             note="**本场景引用最密的一本。** 供电电压代码表（12 V 系统代码 C = 9 至 16 V）、"
                  "§4.3.1.1.2 长时过电压 18 V / 60 min、§4.3.1.2.2 表 5 跨接启动 26 V / 60 ± 6 s、"
                  "§4.3.2.2 表 6 瞬态过电压 18 V / 400 ms 五次，全部已核实。",
             url="https://www.iso.org/standard/76119.html",
             doc_status="已核实（开放正文页）",
             source=[b(79, "ISO 16750 系列"), b("229-236", "供电电压代码表"),
                     b("157-159", "长时过电压、跨接启动、瞬态过电压三条")]),
        _doc("DOC-ENV-003", "环境试验标准",
             "ISO 16750-3 — Part 3: Mechanical loads（第 3 部分：机械负荷）",
             ISO16750_3_PDF, [F1, F3], "PDF 可直接渲染",
             url="https://www.iso.org/standard/77579.html",
             doc_status="编号与条款清单已核实",
             source=b(79, "ISO 16750 系列第 3 部分")),
        _doc("DOC-ENV-004", "环境试验标准",
             "ISO 16750-4:2023 — Part 4: Climatic loads（第 4 部分：气候负荷）",
             ISO16750_4_PDF, [F1, F2, F3], "PDF 可直接渲染",
             note="工作温度代码表：A 为 −20/65 ℃、B 为 −30/65 ℃、C 为 −40/65 ℃，"
                  "D 至 J 上限依次 70 至 100 ℃。低温贮存 −40 ℃ / 24 h（class C）；"
                  "高温贮存 85 ℃ / 48 h（class C）；高温工作 Tmax / 96 h（class A）；"
                  "温度阶梯步长 5 ℃；温度循环 30 个、单循环 480 min。已核实。",
             url="https://www.iso.org/standard/77580.html",
             doc_status="已核实",
             source=[b(79, "ISO 16750 系列第 4 部分"), b(238, "工作温度代码与试验条件")]),
        _doc("DOC-ENV-005", "环境试验标准",
             "ISO 16750-5 — Part 5: Chemical loads（第 5 部分：化学负荷）",
             ISO16750_5_PDF, [F1, F3], "PDF 可直接渲染",
             url="https://www.iso.org/standard/77581.html",
             doc_status="编号与条款清单已核实",
             source=b(79, "ISO 16750 系列第 5 部分")),
        _doc("DOC-ENV-006", "环境试验标准",
             "GB/T 28046 系列《道路车辆 电气及电子设备的环境条件和试验》第 1 至 5 部分"
             "（工业和信息化部提出，全国汽车标准化技术委员会归口；"
             "第 1 部分 GB/T 28046.1-2011、第 2 部分 GB/T 28046.2-2019、"
             "第 3 部分 GB/T 28046.3-2011、第 4 部分 GB/T 28046.4-2011、"
             "第 5 部分 GB/T 28046.5-2013）",
             None, [F1, F3], "未取得",
             note="ISO 16750 系列的中国对应。全系列共五部分，无第 6 部分。"
                  "型式检验的项目顺序按其第 1 部分附录 A.1。",
             url="https://openstd.samr.gov.cn/bzgk/gb/std_list?p.p2=28046",
             doc_status="编号与状态已核实；谱表与温度点未取得",
             source=b(78, "GB/T 28046 系列第 1 至 5 部分编号与状态")),
        _doc("DOC-ENV-007", "通用底座标准",
             "QC/T 413-2002《汽车电气设备基本技术条件》（国家经济贸易委员会，"
             "2002-12-31 发布 / 2003-03-01 实施，现行，代替 QC/T 413-1999）",
             None, [F1, F3], "未取得",
             note="所有车用电机标准的公共底座。QC/T 626 的耐振动条款（5.7 / 6.7）"
                  "直接引它的扫频振动条件。",
             url="https://hbba.sacinfo.org.cn/stdDetail/4e925606f256d82d41af1bb0f8859f7d",
             doc_status="已核实；正文未取得",
             source=b(77, "QC/T 413-2002 全名、日期与引用关系")),
        _doc("DOC-ENV-008", "防护等级标准",
             "GB/T 4208-2017《外壳防护等级（IP代码）》（国家标准化管理委员会，"
             "2017-07-31 发布 / 2018-02-01 实施，现行）",
             None, [F1, F3], "未取得",
             url="https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno="
                 "09CCED55688D4116ED89659C1E7526F8",
             doc_status="部分核实（扫描件机器读取）",
             source=b(83, "GB/T 4208-2017 全名与日期")),
        _doc("DOC-ENV-009", "防护等级标准",
             "GB/T 30038-2013《道路车辆 电气电子设备防护等级（IP代码）》；"
             "换版为 GB/T 30038-2026（修改采用 ISO 20653:2023），2027-02-01 实施",
             None, [F1, F3], "未取得",
             note="车用版 IP 代码，相对 GB/T 4208 增设 IPX9K。**换版预警条目。**",
             url="https://openstd.samr.gov.cn/bzgk/gb/std_list?p.p2=30038",
             doc_status="编号与日期已核实；IPX9K 参数未取得",
             source=[b(84, "GB/T 30038 车用版 IP 代码与换版"), b(106, "换版预警表")]),
        _doc("DOC-ENV-010", "防护等级标准",
             "ISO 20653 Road vehicles — Degrees of protection (IP code) — Protection of "
             "electrical equipment against foreign objects, water and access",
             ISO20653_PDF, [F1, F3], "PDF 可直接渲染",
             doc_status="预览件，编号与目录已核实",
             source=b(84, "GB/T 30038-2026 修改采用 ISO 20653:2023")),
        _doc("DOC-ENV-011", "腐蚀试验标准",
             "GB/T 10125-2021《人造气氛腐蚀试验 盐雾试验》（国家标准化管理委员会，"
             "2021-08-20 发布 / 2022-03-01 实施，现行，全部代替 GB/T 10125-2012）",
             None, [F1, F3], "未取得",
             note="**换版预警条目。** QC/T 626 征求意见稿引的是 2012 版，已被 2021 版全部代替。",
             doc_status="已核实",
             source=[b(85, "GB/T 10125-2021 全名、日期与代替关系"), b(195, "耐腐蚀性条款")]),
        _doc("DOC-ENV-012", "电机试验方法标准",
             "GB/T 5171.22-2017《小功率电动机 第22部分：永磁无刷直流电动机试验方法》；"
             "配套 GB/T 5171.1-2014 通用技术条件、GB/T 5171.21-2016 通用试验方法",
             None, [F1, F3], "未取得",
             note="对汽车小电机的适用性高于三相异步机试验标准。"
                  "注意第 22 部分是无刷直流，本场景是有刷直流，适用的是 .1 与 .21 两部分。",
             doc_status="已核实",
             source=b(86, "GB/T 5171 系列编号与适用性")),
        _doc("DOC-ENV-013", "旋转电机标准",
             "IEC 60034-1 Rotating electrical machines — Part 1: Rating and performance，"
             "Edition 15.0 2026-03（国际电工委员会 IEC）",
             IEC60034_1_PDF, [F1], "PDF 可直接渲染",
             doc_status="预览件，编号与版次已核实",
             source=b(462, "IEC 与 CISPR 检索通道：取得 IEC 60034-1:2026 完整目录")),
        _doc("DOC-ENV-014", "旋转电机标准",
             "IEC 60034-5:2020 Rotating electrical machines — Part 5: Degrees of protection "
             "provided by the integral design of rotating electrical machines (IP code)",
             IEC60034_5_PDF, [F1], "PDF 可直接渲染",
             doc_status="预览件，编号与版次已核实",
             source=b(462, "取得 IEC 60034-5:2020 完整目录")),
    ]
    # ---- 电磁兼容 ----
    D += [
        _doc("DOC-EMC-001", "电磁兼容标准",
             "CISPR 25:2021 Vehicles, boats and internal combustion engines — Radio "
             "disturbance characteristics — Limits and methods of measurement for the "
             "protection of on-board receivers，第 5.0 版，372 页（国际电工委员会"
             "国际无线电干扰特别委员会 IEC/CISPR，分技术委员会 CIS/D，2021-12-16）",
             CISPR25_PDF, [F1, F3], "PDF 可直接渲染",
             note="频率范围 150 kHz 至 5 925 MHz。GB/T 18655 的国际对应。",
             url="https://webstore.iec.ch/publication/64645",
             doc_status="编号、版次、频率范围已核实；Class 1–5 限值数值未取得",
             source=b(82, "CISPR 25:2021 全名、机构、版次与频率范围")),
        _doc("DOC-EMC-002", "电磁兼容标准",
             "GB/T 18655-2025《车辆、船和内燃机 无线电骚扰特性 用于保护车载接收机的"
             "限值和测量方法》（全国无线电干扰标准化技术委员会，2025-02-28 发布并实施，"
             "现行，代替 GB/T 18655-2018）",
             None, [F1, F3], "未取得",
             note="**换版预警条目。** QC/T 626 征求意见稿引的是 GB/T 18655-2010，已两代过期。",
             url="https://openstd.samr.gov.cn/bzgk/gb/std_list?p.p2=18655",
             doc_status="已核实",
             source=[b(81, "GB/T 18655-2025 全名、日期与代替关系"), b(206, "EMC 条款引用过期")]),
        _doc("DOC-EMC-003", "电磁兼容标准",
             "GB/T 21437 系列《道路车辆 电气/电子部件对传导和耦合引起的电骚扰试验方法》"
             "第 1 至 3 部分（均为 2021 版）；第 4 部分为 GB/Z 21437.4-2025"
             "（全国汽车标准化技术委员会电子电磁兼容分技术委员会）",
             None, [F1, F3], "未取得",
             note="第 2 部分为沿电源线的电瞬态传导发射与抗扰性，是升降器 EMC 条款的引用对象。"
                  "征求意见稿引的是 2008 版，须改引 2021 版。",
             url="https://openstd.samr.gov.cn/bzgk/gb/std_list?p.p2=21437",
             doc_status="编号与状态已核实；脉冲幅值表待核实",
             source=[b(80, "GB/T 21437 系列编号与状态"), b(206, "EMC 条款引用过期")]),
        _doc("DOC-EMC-004", "电磁兼容标准",
             "ISO 7637-2:2011 Road vehicles — Electrical disturbances from conduction and "
             "coupling — Part 2: Electrical transient conduction along supply lines only，"
             "Third edition",
             ISO7637_2_PDF, [F1, F3], "PDF 可直接渲染",
             note="GB/T 21437.2 的国际对应。",
             doc_status="预览件，编号与版次已核实",
             source=b(461, "ISO 检索通道：ICS 43.040.10 全目录逐条解析")),
        _doc("DOC-EMC-005", "电磁兼容标准",
             "ISO 10605 Road vehicles — Test methods for electrical disturbances from "
             "electrostatic discharge（道路车辆 静电放电电骚扰试验方法）",
             ISO10605_PDF, [F1, F3], "PDF 可直接渲染",
             doc_status="预览件，编号与目录已核实",
             source=b(461, "ISO 检索通道")),
        _doc("DOC-EMC-006", "电磁兼容标准",
             "ISO 11452-1:2015 Road vehicles — Component test methods for electrical "
             "disturbances from narrowband radiated electromagnetic energy — Part 1: General",
             ISO11452_1_PDF, [F1, F3], "PDF 可直接渲染",
             doc_status="预览件，编号与版次已核实",
             source=b(461, "ISO 检索通道")),
        _doc("DOC-EMC-007", "电磁兼容标准",
             "CISPR 12 Edition 7.0 2025-07 Vehicles, boats and devices with internal "
             "combustion engines — Radio disturbance characteristics — Limits and methods "
             "of measurement for the protection of off-board receivers",
             CISPR12_PDF, [F1], "PDF 可直接渲染",
             note="保护车外接收机，与 CISPR 25（保护车载接收机）是一对。",
             doc_status="编号与版次已核实",
             source=b(462, "IEC 与 CISPR 检索通道：取得 CISPR 12:2025 完整目录")),
        _doc("DOC-EMC-008", "换版预警",
             "GB 34660-2026《道路车辆 电磁兼容性要求和试验方法》"
             "（将代替 GB 34660-2017，2027-07-01 实施）",
             None, [F1], "未取得",
             doc_status="已核实（换版预警）",
             source=b(105, "换版预警表 GB 34660-2026 行")),
    ]
    # ---- OEM 规范（非授权副本）----
    D += [
        _doc("DOC-OEM-001", "OEM 规范",
             "LV 124 — Elektrische und elektronische Komponenten in Kraftfahrzeugen bis "
             "3,5 t: Allgemeine Anforderungen, Prüfbedingungen und Prüfungen"
             "（3.5 t 以下机动车电气电子部件：通用要求、试验条件与试验；"
             "由奥迪 AUDI AG、宝马 BMW AG、戴姆勒 Daimler AG、保时捷 Porsche AG、"
             "大众 Volkswagen AG 五家在工作组 AK 4.9 内共同制定，基础版 Edition 2013-02-28，"
             "文档版本 2.2）。本地副本为梅赛德斯-奔驰企业标准 MBN LV 124-1: 2013-03",
             LV124_PDF, [F1, F3], "PDF 可直接渲染",
             note="**含 E-01 至 E-22 电气试验全部参数。** 本场景直接用到的有："
                  "E-15 反极性（原文点名电动车窗、天窗、起动机）、E-17 短路、E-18 绝缘电阻。"
                  "**该 PDF 为公网流传的非授权副本，正式引用须经采购渠道取得授权原本复核。**",
             url="https://www.etest-emc.com/uploads/soft/250506/LV124-12013.pdf",
             doc_status="制定方、工作组、版本日期已核实；**非授权副本，不具引用资格**",
             source=[b(94, "LV 124 全名、制定方与副本状态"),
                     b("160,164,165", "E-15 反极性 / E-18 绝缘电阻 / E-17 短路")]),
        _doc("DOC-OEM-002", "OEM 规范",
             "VW 80000 — Electrical and Electronic Components in Motor Vehicles up to "
             "3,5 t: General Requirements, Test Conditions, and Tests"
             "（大众汽车股份公司 Volkswagen AG，分类号 8MA00，Issue 2022-12）",
             VW80000_PDF, [F1, F3], "PDF 可直接渲染",
             note="含 E-01 至 E-24、M-01 至 M-09、K-01 至 K-19、C-01、L-01 至 L-03 全部试验目录与参数。"
                  "本场景直接用到的有：M-04 谱型 D（簧上质量挂装件的宽带随机振动，"
                  "车门上的玻璃升降器正属这一类）、M-06 连续机械冲击"
                  "（驾驶员车门 100 000 次、前排乘客门与后门 50 000 次）。"
                  "**同为非授权副本。**",
             url="https://www.etest-emc.com/uploads/soft/250707/VW80000_2022大众汽车零部件电性能标准.pdf",
             doc_status="已核实；**非授权副本，不具引用资格**",
             source=[b(95, "VW 80000 全名、机构与副本状态"),
                     b(240, "M-04 谱型 D"), b(242, "M-06 连续机械冲击")]),
        _doc("DOC-OEM-003", "OEM 规范",
             "MBN LV 148: 2013-11 — Electric and Electronic Components in Motor Vehicles: "
             "48 V On-Board Electrical System, Requirements and Test Conditions"
             "（戴姆勒 Daimler AG 采标版，基础版 LV 148 Edition 2013-07）",
             LV148_PDF, [F1], "PDF 可直接渲染",
             note="48 V 电网电压定义与 E48-01 至 E48-21 试验清单。"
                  "本场景是 12 V 系统，这本只在做 48 V 衍生机型时才用。**非授权副本。**",
             url="https://www.etest-emc.com/uploads/soft/250709/LV148MBN2013-11.pdf",
             doc_status="已核实；**非授权副本**",
             source=b(96, "MBN LV 148 全名、机构与副本状态")),
        _doc("DOC-OEM-004", "OEM 规范",
             "BMW Group Standard GS 95024-3-1: 2010-01 — Elektrische und elektronische "
             "Komponenten in Kraftfahrzeugen: Umweltanforderungen und Prüfungen"
             "（宝马集团标准：机动车电气电子部件 环境要求与试验；作者 Robert Maier；"
             "代替 GS 95003-1: 2008-11 等四份）",
             BMW_GS_PDF, [F1], "PDF 可直接渲染",
             note="以 LV 124 为基础的宝马采标版，正文内含 LV 124 全 83 页。**非授权副本。**",
             doc_status="编号、版次与作者已核实；**非授权副本**",
             source=b(464, "OEM 规范通道：szilassy.eu 托管的 BMW GS 95024-3-1: 2010-01")),
        _doc("DOC-OEM-005", "OEM 规范",
             "GMW3172 — General Specification for Electrical/Electronic Component "
             "Analytical/Development/Validation (A/D/V) Procedures for Conformance to "
             "Vehicle Environmental, Reliability, and Performance Requirements"
             "（通用汽车全球工程标准 General Motors Global Engineering Standards）。"
             "可取得原文级内容的是 The GMW3172 Users Guide, Revision 19, 2008-02-13，"
             "作者 Larry Edson",
             GMW3172_PDF, [F1], "PDF 可直接渲染",
             note="五位代码字母串定义部件试验等级（电气/机械/气候/温度/防护）。",
             url="https://www.atecorp.com/compliance-standards/gm/gmw3172-standard",
             doc_status="2008 版内容已核实；**当前现行版次待核实**，距今 18 年",
             source=b(97, "GMW3172 全名、机构、版本与作者")),
    ]
    # ---- 车规元器件 ----
    D += [
        _doc("DOC-AEC-001", "车规元器件标准",
             "AEC-Q100 Failure Mechanism Based Stress Test Qualification for Integrated "
             "Circuits in Automotive Applications，Rev J1，2026-03-24"
             "（汽车电子委员会 Automotive Electronics Council, AEC）",
             Q100_PDF, [F1, F2], "PDF 可直接渲染",
             note="温度等级表：Grade 0 为 −40 至 +150 ℃、Grade 1 为 −40 至 +125 ℃、"
                  "Grade 2 为 −40 至 +105 ℃、Grade 3 为 −40 至 +85 ℃。"
                  "静电放电目标：人体模型 2 kV（AEC-Q100-002）；"
                  "充电器件模型角引脚 750 V、其余引脚 500 V（AEC-Q100-011）。"
                  "官网 HTTPS 证书握手失败，须走 HTTP。",
             url="http://www.aecouncil.com/AECDocuments.html",
             doc_status="已核实（官方免费 PDF）",
             source=[b(92, "AEC-Q100 Rev J1 全名、机构与获取方式"),
                     b("246-253", "温度等级表与静电放电目标")]),
        _doc("DOC-AEC-002", "车规元器件标准",
             "AEC-Q101 Rev E（2021-03-01，分立半导体）", Q101_PDF, [F1], "PDF 可直接渲染",
             doc_status="已核实（官方免费 PDF）", source=b(93, "AEC-Q101 Rev E")),
        _doc("DOC-AEC-003", "车规元器件标准",
             "AEC-Q102 Rev A（2020-04-06，光电半导体）", Q102_PDF, [F1], "PDF 可直接渲染",
             doc_status="已核实（官方免费 PDF）", source=b(93, "AEC-Q102 Rev A")),
        _doc("DOC-AEC-004", "车规元器件标准",
             "AEC-Q104 Rev A（2025-11-28，多芯片模块）", Q104_PDF, [F1], "PDF 可直接渲染",
             doc_status="已核实（官方免费 PDF）", source=b(93, "AEC-Q104 Rev A")),
        _doc("DOC-AEC-005", "车规元器件标准",
             "AEC-Q200 Rev E（2023-03-20，被动元件）", Q200_PDF, [F1], "PDF 可直接渲染",
             note="**注意 Rev E 已取消 Grade 0–4 温度分级表**，"
                  "改为供应商自行声明且最低覆盖 −40 至 +85 ℃。",
             doc_status="已核实（官方免费 PDF）", source=b(93, "AEC-Q200 Rev E 与分级表取消")),
        _doc("DOC-FS-001", "功能安全标准",
             "ISO 26262 系列 Road vehicles — Functional safety，第 1 至 12 部分，"
             "均为 2018-12 第 2 版（Part 11、12 为第 1 版）；全部 12 个部分当前均有 ISO/DIS 修订在研",
             None, [F1], "未取得",
             url="https://www.iso.org/standard/68383.html",
             doc_status="已核实", source=b(98, "ISO 26262 系列版本与修订状态")),
        _doc("DOC-FS-002", "功能安全标准",
             "GB/T 34590 系列《道路车辆 功能安全》第 1 至 12 部分，均为 2022 版"
             "（国家标准化管理委员会，2022-12-30 发布 / 2023-07-01 实施，现行；"
             "2017 版第 1 至 10 部分已全部废止）",
             None, [F1], "未取得",
             url="https://openstd.samr.gov.cn/bzgk/gb/std_list?p.p2=GB%2FT%2034590",
             doc_status="已核实", source=b(99, "GB/T 34590 系列版本与废止关系")),
        _doc("DOC-ENV-015", "环境试验标准",
             "ISO 19453 Road vehicles — Environmental conditions and testing for electrical "
             "and electronic equipment for drive system of electric propulsion vehicles",
             ISO19453_PDF, [F1], "PDF 可直接渲染",
             doc_status="预览件，编号与目录已核实", source=b(461, "ISO 检索通道")),
    ]
    # ---- 台架与实验室安全 ----
    D += [
        _doc("DOC-SAFE-001", "台架安全标准",
             "GB/T 5226.1-2019《机械电气安全 机械电气设备 第1部分：通用技术条件》"
             "（国家市场监督管理总局与国家标准化管理委员会，2019-06-04 发布 / 2020-01-01 实施，"
             "现行，代替 GB 5226.1-2008，等同采用 IEC 60204-1:2016）",
             None, [F1, F2], "未取得",
             note="适用于额定电压不超过交流 1000 V 或直流 1500 V 的机械电气设备。"
                  "注意前缀由 GB 改为 GB/T，即由强制性改为推荐性。",
             url="https://www.ndls.org.cn/standard/detail/eb10a2db1aab4da873d16f763009371a",
             doc_status="已核实", source=b(172, "GB/T 5226.1-2019 全名、机构与采标关系")),
        _doc("DOC-SAFE-002", "台架安全标准",
             "GB/T 15706-2012《机械安全 设计通则 风险评估与风险减小》"
             "（国家标准化管理委员会，2012，现行，以翻译法等同采用 ISO 12100:2010）",
             None, [F1, F2], "未取得",
             note="A 类基础安全标准。Agent 自动施加过压、堵转、短路前的风险评估依据。",
             url="https://std.samr.gov.cn/gb/search/gbDetailed?id=7E2903B0D76C5A63E05397BE0A0AF660",
             doc_status="已核实", source=b(173, "GB/T 15706-2012 全名与采标关系")),
        _doc("DOC-SAFE-003", "台架安全标准",
             "ISO 13849-1:2023 Safety of machinery — Safety-related parts of control "
             "systems — Part 1: General principles for design（机械安全 控制系统安全相关部件 "
             "第1部分：设计通则；国际标准化组织 ISO，2023，代替 2015 版）",
             None, [F1, F2], "未取得",
             note="性能等级 PL 分 a 至 e 五档，每档对应一个每小时危险失效平均概率区间。",
             url="https://www.iso.org/standard/73481.html",
             doc_status="已核实", source=b(174, "ISO 13849-1:2023 全名与 PL 分档")),
        _doc("DOC-SAFE-004", "台架安全标准",
             "IEC 62061:2021 Safety of machinery — Functional safety of safety-related "
             "control systems（机械安全 安全相关控制系统的功能安全），第 2.0 版"
             "（国际电工委员会 IEC，2021，取代 2005 第 1 版及其两个修订案）",
             None, [F1, F2], "未取得",
             note="2021 版不再限于电气系统，可用于液压、气动等所有技术类型；"
                  "新增功能安全计划与周期性测试要求。",
             url="https://webstore.iec.ch/en/publication/59927",
             doc_status="已核实", source=b(175, "IEC 62061:2021 全名、版次与适用范围变化")),
        _doc("DOC-SAFE-005", "台架安全标准",
             "ISO 14119:2024 Safety of machinery — Interlocking devices associated with "
             "guards — Principles for design and selection（机械安全 与防护装置相关的联锁装置 "
             "设计与选择原则；ISO，2024，代替 2013 版）",
             None, [F1, F2], "未取得",
             note="2024 版在原四类基础上新增第 5 类钥匙转移式联锁装置，"
                  "适合「必须先切断动力才能开门」的工位——本场景的 550 V 绝缘工位正是这种。",
             url="https://www.iso.org/standard/75942.html",
             doc_status="已核实", source=b(176, "ISO 14119:2024 全名与第 5 类新增")),
        _doc("DOC-SAFE-006", "实验室设备安全标准",
             "IEC 61010-1 Safety requirements for electrical equipment for measurement, "
             "control, and laboratory use — Part 1: General requirements"
             "（IEC，第 3 版 2010；合订版 Ed. 3.1 b:2017）",
             None, [F1, F2], "未取得",
             note="适用于标称供电电压不超过交流 1000 V 或直流 1500 V 的设备。"
                  "中国对应的 GB 4793.1-2007 等同于 IEC 61010-1:2001，**落后两代**。",
             url="https://webstore.iec.ch/en/publication/4279",
             doc_status="已核实", source=b(177, "IEC 61010-1 版次与中国对应标准落后情况")),
        _doc("DOC-SAFE-007", "实验室能力标准",
             "ISO/IEC 17025:2017 General requirements for the competence of testing and "
             "calibration laboratories（检测和校准实验室能力的通用要求），第 3 版"
             "（ISO 与 IEC 联合，2017）",
             None, [F1, F6], "未取得",
             note="第 7.8 条规定报告必含要素，是 report-template.json 字段清单的合规依据。",
             url="https://www.iso.org/standard/66912.html",
             doc_status="标准编号与版次已核实；7.8.2 字段清单经 PJLA 培训讲义转述，待核实",
             source=[b(178, "ISO/IEC 17025:2017 全名与第 7.8 条"),
                     b(411, "7.8.2 必含要素清单")]),
        _doc("DOC-SAFE-008", "报告合规依据",
             "CNAS-EL-13《检测报告和校准证书相关要求的认可说明》"
             "（中国合格评定国家认可委员会 China National Accreditation Service for "
             "Conformity Assessment, CNAS，发布日期 2019-12-25）",
             None, [F1, F6], "未取得",
             note="国内报告字段合规性的主依据。",
             url="https://www.cnas.org.cn/cms_files/filemanager/328304128/attach/202412/"
                 "7AF84C12378754996D4B69CB95C50127.pdf",
             doc_status="待核实（PDF 文本层抽取失败，文件号与标题来自搜索结果标题行）",
             source=b(412, "CNAS-EL-13 全名、机构与日期")),
    ]
    # ---- 报告样张与测试程序 ----
    D += [
        _doc("DOC-REP-001", "报告样例",
             "REPORT NUMBER 118-GTL-11-002, SAFETY COMPLIANCE TESTING FOR FMVSS NO. 118, "
             "POWER-OPERATED WINDOW, PARTITION AND ROOF PANEL SYSTEMS — 2011 NISSAN JUKE S "
             "MPV, NHTSA NO. CB5201（检测方 General Testing Laboratories, Inc.，"
             "1623 Leedstown Road, Colonial Beach, Virginia 22443；"
             "委托方 美国交通部国家公路交通安全管理局车辆安全合规办公室 U.S. DOT / NHTSA, "
             "Office of Vehicle Safety Compliance, NVS-220；项目工程师 Grant Farrand，"
             "项目经理 Debbie Messick；最终报告日期 2011-03-17，试验日期 2011-03-15，"
             "合同号 DTNH22-06-C-00032）",
             NHTSA_PDF, [F1, F6], "已解析为 report-template.json + PDF 可直接渲染",
             note="**本场景报告模板的骨架来源，36 页全文在手。** "
                  "本包已从中提取六节结构与 13 字段技术著录页，并把第 19 页（FIGURE 5.1）"
                  "渲染成 assets/product-photo-nhtsa-fig5-1.png。",
             url="https://www.carsandracingstuff.com/library/reports/5683.pdf",
             doc_status="已核实（本次下载并提取文本）",
             source=[b(387, "报告全名、检测方、委托方、人员与日期"),
                     b("397-405", "章节结构与字段清单")]),
        _doc("DOC-REP-002", "报告样例",
             "REPORT NUMBER 118-GTL-20-003（2020 Ford Explorer XLT MPV）",
             None, [F1, F6], "未取得",
             note="同类报告，可做版式互校。",
             url="https://static.nhtsa.gov/odi/ctr/9999/TRTR-646394-2020-001.pdf",
             doc_status="已核实（链接与标题）", source=b(388, "同类报告 PDF 清单")),
        _doc("DOC-REP-003", "报告样例",
             "REPORT NUMBER 118-GTL-18-004（2018 BMW 530i 轿车）",
             None, [F1, F6], "未取得",
             url="https://static.nhtsa.gov/odi/ctr/9999/TRTR-645269-2018-001.pdf",
             doc_status="已核实（链接与标题）", source=b(388, "同类报告 PDF 清单")),
        _doc("DOC-REP-004", "报告样例",
             "REPORT NUMBER 118-GTL-08-004（2008 BMW 328i 轿车）",
             None, [F1, F6], "未取得",
             url="https://www.carsandracingstuff.com/library/reports/5109.pdf",
             doc_status="已核实（链接与标题）", source=b(389, "同类报告 PDF")),
        _doc("DOC-REP-005", "测试程序",
             "OVSC Laboratory Test Procedure TP-118-06（FMVSS 118 实验室测试程序），"
             "2006-04-12（美国交通部 NHTSA 车辆安全合规办公室）",
             None, [F1, F3, F6], "未取得",
             note="与报告配套的测试程序文件。报告正文明确声明"
                  "「所有试验按 TP-118-06 与 GTL 内部程序 TP-118-03A 执行」。",
             url="https://www.nhtsa.gov/sites/nhtsa.gov/files/documents/tp-118-06_tag.pdf",
             doc_status="链接与标题已核实；正文本次抓取失败（Socket closed），待核实",
             source=b(391, "TP-118-06 全名、机构与日期")),
        _doc("DOC-REP-006", "报告检索入口",
             "NHTSA Compliance Test Report Search（合规测试报告检索数据库；"
             "美国国家公路交通安全管理局）",
             None, [F1], "未转化",
             note="可按标准号检索历年公开报告。官方声明：报告公开是为信息交流，"
                  "其意见、发现与结论不应被视为产品是否合规的最终判定。",
             url="https://www.nhtsa.gov/compliance/",
             doc_status="已核实", source=b(390, "NHTSA 合规测试报告检索数据库")),
    ]
    # ---- 参考设计与调参文档 ----
    D += [
        _doc("DOC-REF-001", "参考设计",
             "Small-Footprint Sunroof Motor Module Reference Design"
             "（小尺寸天窗电机模块参考设计，含防夹检测；德州仪器 Texas Instruments "
             "Incorporated；设计编号 TIDA-01389；设计指南 TIDUCQ9 Rev. A，2017-07-21）",
             None, [F1, F2, F5], "未取得",
             note="可提参数：有刷直流电机、驱动能力 15 A、栅极驱动器 DRV8703-Q1 耐压 47 V、"
                  "两颗 DRV5013-Q1 锁存霍尔构成位置编码（带宽 30 kHz）、支持防夹检测与反接保护。"
                  "配套资料：原理图 TIDRQE4 / BOM TIDRQE5 / PCB TIDRQE7 / Gerber TIDCDA8。",
             url="https://www.ti.com/tool/TIDA-01389",
             doc_status="已核实", source=b(140, "TIDA-01389 全名、编号与可提参数")),
        _doc("DOC-REF-002", "参考设计",
             "Anti-Pinch Window Lift Reference Design（防夹车窗升降参考设计，"
             "与同济大学合作开发；恩智浦半导体 NXP Semiconductors N.V.；"
             "方案编号 RDS12VR；资料单文件 RDS12VRFS.pdf）",
             None, [F1, F2, F5], "未取得",
             note="特征：S12 MagniV S12VR 混合信号微控制器、霍尔与电流采样双判据防夹、"
                  "**防夹区间与防夹力可调**、防夹区外做堵转检测。"
                  "这是四家参考设计里唯一明示「哪两个参数可调」的。",
             url="https://www.nxp.com/docs/en/fact-sheet/RDS12VRFS.pdf",
             doc_status="待核实（PDF 超 10 MB 抓取失败，特征来自社区条目转述）",
             source=[b(141, "RDS12VR 全名、编号与特征"), b(343, "官方明示可调项")]),
        _doc("DOC-REF-003", "参考设计",
             "S12VR Window Lift StarterTRAK Reference Design（车窗升降与继电器式直流电机"
             "控制入门套件；恩智浦半导体；套件编号 TRK-S12VR-WLFT-1）",
             None, [F1, F2], "未取得",
             url="https://www.nxp.com/design/design-center/development-boards-and-designs/"
                 "s12vr-window-lift-startertrak-reference-design:TRK-S12VR-WLFT-1",
             doc_status="待核实", source=b(142, "TRK-S12VR-WLFT-1 全名与编号")),
        _doc("DOC-REF-004", "参考设计",
             "Window Lift with Anti-Pinch Reference Design（带防夹的车窗升降参考设计；"
             "微芯科技 Microchip Technology Inc.；开发工具编号 APGRD002）",
             None, [F1, F2], "未取得",
             url="https://www.microchip.com/en-us/development-tool/apgrd002",
             doc_status="待核实（该页对自动抓取返回 HTTP 403，仅由搜索结果确认存在）",
             source=b(143, "APGRD002 全名与编号")),
        _doc("DOC-REF-005", "参考设计",
             "TLE9855QX Window Lift Reference Design Guide，v01_01"
             "（英飞凌科技 Infineon Technologies AG，经贸泽电子 Mouser Electronics 镜像发布）",
             None, [F1, F2], "未取得",
             url="https://www.mouser.com/pdfDocs/Infineon-TLE9855QX_Window_Lift_Reference_"
                 "Design_Guide_Preview-UserManual-v01_01-EN.pdf",
             doc_status="待核实（infineon.com 本域在本次环境中被网络策略拦截）",
             source=b(144, "TLE9855QX 设计指南全名与版本")),
        _doc("DOC-REF-006", "参考设计",
             "Smart window lift module（智能车窗升降模块应用页，"
             "MOTIX™ TLE985x 系列 H 桥 MOSFET 驱动片上系统；英飞凌科技）",
             None, [F1, F2], "未取得",
             note="特征：12 V 电机控制片上系统、Arm Cortex-M0 内核、"
                  "片上电池电压与温度测量、自适应栅极电流控制。",
             url="https://www.infineon.com/cms/en/applications/automotive/body-electronics-"
                 "and-lighting/comfort-convenience-electronics/smart-window-lift-module/",
             doc_status="待核实", source=b(145, "TLE985x 应用页与特征")),
        _doc("DOC-REF-007", "参考设计",
             "Automotive Brushed-Motor Ripple Counter Reference Design"
             "（车规有刷电机纹波计数参考设计；德州仪器；设计指南文档号 TIDUD30A；"
             "关联设计 TIDA-01421）",
             None, [F1, F2, F5], "未取得",
             note="原理：电机电流交流分量中的纹波与换向器极经过电刷一一对应，"
                  "纹波频率正比于实际转速，可转成数字口可计的脉冲；纹波数为 2N（N 为绕组对数）。"
                  "可提参数：高通/带通滤波参数、比较器迟滞、脉冲整形门限。",
             url="https://www.ti.com/lit/ug/tidud30a/tidud30a.pdf",
             doc_status="待核实", source=[b(146, "TIDUD30A 全名、编号与原理"),
                                          b(342, "可提炼的滤波与迟滞参数")]),
        _doc("DOC-TUNE-001", "调参文档",
             "Motor Control Application Framework (MCAF) 文档 5.1.6 节 Current loop tuning"
             "（电流环整定；微芯科技 Microchip Technology Inc.，MCAF R7 RC37 文档，版本 7.0.2）",
             None, [F1, F5], "已解析为 control-parameters.json + experience.json",
             note="**本次调研中唯一给出「参数名 + 默认值 + 推荐区间 + 增减后果」完整闭环的公开文档。** "
                  "相位裕度默认 80°、推荐 50° 至 70°；PI 相位滞后默认 45°、推荐 8° 至 20°、"
                  "低于 5° 不建议；电流环带宽取 PWM 频率的 5 % 至 15 %。"
                  "另明确规定整定顺序：先在开环换相下整定电流环，再调开闭环切换。",
             url="https://microchiptech.github.io/mcaf-doc/7.0.2/algorithms/foc/tuning.html",
             doc_status="已核实", source=[b(360, "MCAF 文档全名、版本与评价"),
                                          b("371-375", "五个参数的默认值与推荐区间"),
                                          b(377, "整定顺序")]),
        _doc("DOC-TUNE-002", "调参文档",
             "UM3259 — STM32 motor control SDK: 6-step firmware sensorless parameter "
             "optimization（意法半导体 STMicroelectronics N.V.）",
             None, [F1, F5], "未取得",
             note="对齐与启动、单段或多段加速斜坡；大惯量电机先缓斜坡后陡斜坡。",
             url="https://www.st.com/resource/en/user_manual/um3259-stm32-motor-control-sdk--"
                 "6step-firmware-sensorless-parameter-optimization-stmicroelectronics.pdf",
             doc_status="待核实（抓取超时）", source=b(361, "UM3259 全名与可提炼参数")),
        _doc("DOC-TUNE-003", "调参文档",
             "STM32 Motor Control Frequently Asked Questions"
             "（意法半导体 STM32 微控制器 Wiki）",
             None, [F1, F5], "未取得",
             note="启动调参口径：将 Speed ramp final value 提高到最大应用转速的 40 %，"
                  "将 Minimum startup output speed 降到 10 %。",
             url="https://wiki.stmicroelectronics.cn/stm32mcu/wiki/"
                 "STM32MotorControl:Frequently_Asked_Questions",
             doc_status="待核实", source=b(362, "STM32 FAQ 启动调参口径")),
        _doc("DOC-TUNE-004", "调参文档",
             "iMOTION™ Motion Control Engine Software Reference Manual（含 MCEWizard "
             "全部可配参数），V 1.34，2021-09-17，203 页（英飞凌科技，社区镜像）",
             None, [F1, F5], "未取得",
             note="IS_Pulses、IS_Duty、IS_IqInit（由 MCEWizard 自动计算）；"
                  "初始角检测按六个角度注入电流脉冲；过压/欠压保护、过流检测、堵转防护。"
                  "注意这是无刷方案的参数体系，有刷直流用不上初始角检测那一段。",
             url="https://community.infineon.com/gfawx74859/attachments/gfawx74859/"
                 "jpmotixmcu/693/1/Infineon-MCESW-RM-UserManual-v01_03-EN.pdf",
             doc_status="待核实（infineon.com 本域被拦截，走社区镜像）",
             source=b(363, "iMOTION 参考手册全名、版本与可提炼参数")),
        _doc("DOC-TUNE-005", "调参文档",
             "How to Reduce Motor Noise with Code-Free, Sensorless FOC"
             "（用免代码无感磁场定向控制降低电机噪声；德州仪器，文献号 SLLA567）",
             None, [F1, F5], "未取得",
             note="自动死区补偿、PWM 调制方式对声学表现的影响。",
             url="https://www.ti.com/lit/an/slla567/slla567.pdf",
             doc_status="待核实", source=b(364, "SLLA567 全名与文献号")),
        _doc("DOC-TUNE-006", "调参文档",
             "Driving Brushed DC Motors Using PWM Output: Losses and Points to be Noted"
             "（用 PWM 驱动有刷直流电机：损耗与注意事项；罗姆半导体 ROHM Co., Ltd. "
             "TechWeb 技术专栏，条目 346）",
             None, [F1, F5], "未取得",
             note="死区的必要性与死区导致的损耗；开关损耗与效率折中。"
                  "**这是六份调参文档里唯一直接针对有刷直流的。**",
             url="https://techweb.rohm.com/product/motor/motor-types/346/",
             doc_status="待核实", source=b(365, "ROHM TechWeb 条目 346 全名与内容")),
    ]
    # ---- 防夹算法文献 ----
    D += [
        _doc("DOC-PAP-001", "算法文献",
             "Automatic Threshold on Current based Anti-pinch Mechanism for Power Windows"
             "（基于电流的电动车窗防夹机构自动阈值方法），刊于 International Journal of "
             "Electrical and Computer Engineering (IJECE)，2018",
             None, [F1, F5], "未取得",
             note="电流突变门限的自适应设定方法；阈值随工况自整定。",
             url="https://ijece.iaescore.com/index.php/IJECE/article/view/7702",
             doc_status="待核实（未打开正文逐字确认）",
             source=b(338, "IJECE 2018 论文全名、期刊与 URL")),
        _doc("DOC-PAP-002", "算法文献",
             "Practical pinch detection algorithm for low-cost anti-pinch window control "
             "system（低成本防夹车窗控制系统的实用夹持检测算法），IEEE 会议论文",
             None, [F1, F5], "未取得",
             note="基于转矩变化率（torque rate）的检测判据；文中指出转矩变化率对电机参数"
                  "不确定性的敏感度低于转矩或角速度本身。",
             url="https://ieeexplore.ieee.org/document/1600781",
             doc_status="待核实", source=b(339, "IEEE 会议论文全名与判据")),
        _doc("DOC-PAP-003", "算法文献",
             "Power Window Anti-Pinch Control Based on Hall Pulse Signal and Mechanical "
             "Power（基于霍尔脉冲信号与机械功率的车窗防夹控制），"
             "收录于 Atlantis Press，ICMSE 2018 会议论文集",
             None, [F1, F5], "未取得",
             note="霍尔脉冲计数与机械功率联合判据。",
             url="https://www.atlantis-press.com/proceedings/icmse-18/25895047",
             doc_status="待核实", source=b(340, "ICMSE 2018 论文全名与判据")),
        _doc("DOC-PAP-004", "算法文献",
             "Research on Anti-pinch Control Strategy of Window Start-up Phase based on "
             "Ripple Motor（基于纹波电机的车窗启动阶段防夹控制策略研究），"
             "ResearchGate 条目，2021",
             None, [F1, F5], "未取得",
             note="**启动阶段**的防夹策略——启动瞬间的浪涌电流会掩盖夹持特征，"
                  "是防夹算法最难的一段，也是调参重点。",
             url="https://www.researchgate.net/publication/349300884",
             doc_status="待核实（未确认期刊/会议全名与作者）",
             source=b(341, "ResearchGate 2021 条目与内容")),
    ]
    # ---- 仿真与数据工具 ----
    D += [
        _doc("DOC-SIM-001", "仿真工具",
             "gym-electric-motor（GEM），电机控制强化学习仿真环境"
             "（德国帕德博恩大学电驱动系统教研室 Universität Paderborn, "
             "Lehrstuhl für Elektrische Antriebssysteme, LEA）",
             None, [F1, F4], "未取得",
             note="可生成 abc 与 dq 三相电流、转速、转矩、端电压、直流母线电压；"
                  "内置逆变器与负载模型；支持多种直流电机；时间步长可配（微秒至毫秒级）。"
                  "定子电阻、电感、极对数、额定电压与电流全部开放为参数，可直接配到 12 V 车用量级。"
                  "**本包的合成波形与它用的直流电机模型同型，但没有引入该依赖**，"
                  "而是在 _build/gen_waveforms.py 里直接用显式欧拉积分实现，便于逐行审阅。",
             url="https://github.com/upb-lea/gym-electric-motor",
             doc_status="已核实（仓库活跃，427 星 / 1157 次提交）；许可证 MIT",
             source=b(314, "gym-electric-motor 全名、机构、能力与许可证")),
        _doc("DOC-SIM-002", "仿真工具",
             "Simscape Electrical — Electric Power Assisted Steering（电动助力转向示例；"
             "MathWorks）",
             None, [F1, F4], "未取得",
             note="**唯一开箱即为车规场景的模型。** 若项目已有 MATLAB 授权，"
                  "优先级高于开源方案。但被测对象是转向不是车窗，需改建。",
             url="https://www.mathworks.com/help/sps/ug/electric-power-assisted-steering.html",
             doc_status="已核实；需 MATLAB + Simscape Electrical 商业授权",
             source=b(315, "Simscape Electrical EPAS 示例全名与评价")),
        _doc("DOC-SIM-003", "仿真工具",
             "PyLEECAN（PYthon Library for Electrical Engineering Computational ANalysis；"
             "法国 EOMYS ENGINEERING 发起，现由 Green Forge Coop 支持）",
             None, [F1], "未取得",
             note="耦合有限元求解器 FEMM 做电磁仿真，输出磁场、转矩、损耗。"
                  "偏电机本体设计，要产出传感器级时序需自建电路外壳。",
             url="https://github.com/Eomys/pyleecan",
             doc_status="已核实；许可证 Apache 2.0", source=b(316, "PyLEECAN 全名、机构与能力")),
        _doc("DOC-SIM-004", "数据集与脚本",
             "ITSC — 三相感应电机匝间短路故障电流数据集（含读取脚本；GitHub 账号 ibarram；"
             "被测件 Baldor CM3542，0.75 hp）",
             None, [F1, F4], "未取得",
             note="三相电流实测；健康 + 12 种故障；1 kHz 采样，每次 5 秒，"
                  "60 Hz 空载稳态，每工况重复 5 次；附 Python/MATLAB/R/C 读取脚本。"
                  "被测件是感应电机，与本场景的有刷直流不同型，只能借读取脚本的工程做法。",
             url="https://github.com/ibarram/ITSC",
             doc_status="已核实（全部字段）；许可证 MIT", source=b(317, "ITSC 全名、被测件与参数")),
        _doc("DOC-SIM-005", "开发套件",
             "C2000Ware MotorControl SDK（含 InstaSPIN-FOC 有感与无感磁场定向控制方案；"
             "德州仪器）",
             None, [F1, F5], "未取得",
             url="https://www.ti.com/tool/C2000WARE-MOTORCONTROL-SDK",
             doc_status="已核实", source=b(318, "C2000Ware MotorControl SDK 全名与能力")),
        _doc("DOC-SIM-006", "开发套件",
             "X-CUBE-MCSDK（STM32 电机控制软件开发包）+ ST Motor Pilot（意法半导体）",
             None, [F1, F5], "未取得",
             note="Motor Pilot 支持实时绘图，右键选寄存器变量生成标准图与 XY 图，"
                  "可记录电流、转速等控制量。",
             url="https://www.st.com/en/embedded-software/x-cube-mcsdk.html",
             doc_status="已核实", source=b(319, "X-CUBE-MCSDK 与 Motor Pilot 全名与能力")),
    ]
    # ---- 备选产品（切换时启用）----
    D += [
        _doc("DOC-ALT-001", "备选产品标准",
             "QC/T 29090-2023《汽车用刮水电动机》（工业和信息化部发布，SAC/TC 114 归口，"
             "2023-04-21 发布 / 2023-11-01 实施，代替 QC/T 29090-1992）",
             None, [F1, F3], "未取得",
             note="**决赛候选 A 的标准全文，20 项判据全量化、全部已核实。** "
                  "本场景没选它，但它是「切三级分类」的现成下一个产品："
                  "同属汽车车身电机、同为有刷直流，判据体系可直接接上本包的骨架。"
                  "本包从它借了一条：堵转 4.18/5.18 的「连续通电 30 s 堵转」，"
                  "用作台架堵转持续时间的通用上限（已在 safety-interlocks.json SI-HW-03 标明出处）。",
             url="https://hbba.sacinfo.org.cn/stdDetail/fa7c67530404b45b4a1d5352bd5af501"
                 "6d98d799798d2fd0b4edd58ab79d4f22",
             doc_status="已核实（标准全文 PDF，20 项判据）",
             source=[b(257, "QC/T 29090-2023 全名、机构、日期与代替关系"),
                     b("259-281", "20 项判据表")]),
    ]

    # ---- 我方文档 ----
    D += [
        _doc("DOC-OURS-001", "我方文档",
             "B-汽车场景测试案例素材（20260919 通用 Agent 测试系统 v2.0 调研文档）",
             DOC_B, [F1, F2, F3, F4, F5, F6], "Markdown 原生",
             note="**本场景包绝大多数条目的一级来源。** 含选题论证、六流程素材表、"
                  "判据表、三地法规对照表、与峰岹案例的对照表、搜索范围与零命中。"
                  "本包的 _source 大量指向它的行号。",
             source=src(DOC_B, "全文")),
        _doc("DOC-OURS-002", "我方文档",
             "场景包生成脚本 _build/（common.py 常量与工具、gen_a.py 产品与判据、"
             "gen_b.py 工作流与文档、gen_waveforms.py 合成波形、render_assets.py 图片资产、"
             "build_scene_pack.py 入口）",
             os.path.join(OUT, "_build"), [F1], "本场景包自产",
             note="只读源材料，不写回源材料。重新生成命令见 README 末节。",
             source=src(os.path.join(OUT, "_build/build_scene_pack.py"), "ORDER 列表")),
    ]

    counts = {}
    for d in D:
        counts[d["type"]] = counts.get(d["type"], 0) + 1
    exists_n = sum(1 for d in D if d["exists"])

    return dump("documents.json", {
        "schema": "documents/v1",
        "scene_id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "belongs_to_flow": "F1 知识库管理（文档性质那一类：分类、呈现、增删改查、转化）",
        "total": len(D),
        "local_copy_count": exists_n,
        "count_by_type": counts,
        "evidence_root": EV,
        "conversion_status_legend": {
            "Markdown 原生": "本身就是 Markdown，可直接进知识库",
            "已抽取纯文本": "PDF 已提取为 .txt，可直接做条款抽取",
            "已解析为 …": "本场景包已把它解析成结构化 JSON",
            "PDF 可直接渲染": "PDF 在本地，可按页渲图给前端",
            "未转化": "链接与标题已登记，正文在本地没有",
            "未取得": "正文需采购或抓取失败，只有编号与元数据",
            "本场景包自产": "本包自己写的脚本或产物",
        },
        "difference_from_scene1": "场景一的 61 份文档里绝大多数是**客户私有文档**"
                                  "（25 份调试规程、8 份调试手册、Keil 工程、原理图），"
                                  "走「上传 → 解析 → 入库」链路。"
                                  "本场景的文档**全部是公开标准、法规、参考设计与论文**，"
                                  "走「标准编号 → 条款抽取 → 判据结构化」链路。"
                                  "两条链路的差别正是知识库要同时支持的两种入库方式。",
        "non_authorized_copies": {
            "note": "以下四份 OEM 规范的本地副本均为公网流传的非授权版本。"
                    "内容可信但不具备引用资格，正式报告引用前须经采购渠道取得授权原本复核。",
            "ids": ["DOC-OEM-001", "DOC-OEM-002", "DOC-OEM-003", "DOC-OEM-004"],
            "_source": b(464, "OEM 规范通道：内容可信但均为公网流传的非授权副本"),
        },
        "version_change_alerts": [
            {"standard": "GB 34660-2026《道路车辆 电磁兼容性要求和试验方法》",
             "change": "将代替 GB 34660-2017", "effective": "2027-07-01 实施"},
            {"standard": "GB/T 30038-2026《道路车辆 电气电子设备防护等级（IP代码）》",
             "change": "将代替 GB/T 30038-2013", "effective": "2027-02-01 实施"},
            {"standard": "GB/T 33012.5-2026《整车混响室法》",
             "change": "新增", "effective": "2027-03-01 实施"},
            {"standard": "GB/T 18655-2025", "change": "已代替 GB/T 18655-2018",
             "effective": "2025-02-28 已生效"},
            {"standard": "GB/T 755-2025《旋转电机 定额与性能》",
             "change": "已代替 GB/T 755-2019", "effective": "2026-02-01 实施"},
            {"standard": "QC/T 627-2025《汽车电动门锁装置》、"
                         "QC/T 777-2025《汽车冷却系统电磁离合器》",
             "change": "均已发布待实施", "effective": "2026-07-01 实施"},
            {"standard": "GB/T 10125-2021《人造气氛腐蚀试验 盐雾试验》",
             "change": "全部代替 GB/T 10125-2012（QC/T 626 征求意见稿引的是 2012 版）",
             "effective": "2022-03-01 已实施"},
        ],
        "version_change_alerts_source": [b("105-110", "换版预警表"), b(85, "GB/T 10125-2021")],
        "documents": D,
    })


# ========================= report-template.json =========================

def gen_report_template():
    F6 = "F6 测试报告及产出"

    # 技术著录页 13 个编号字段（NHTSA 报告第 3 页）
    tech_page = [
        (1, "report_no", "Report No.", "报告号", "text", "118-GTL-11-002"),
        (2, "gov_accession_no", "Government Accession No.", "政府入藏号", "text", None),
        (3, "recipients_catalog_no", "Recipient's Catalog No.", "接收方目录号", "text", None),
        (4, "title_and_subtitle", "Title and Subtitle", "标题与副标题", "text",
         "SAFETY COMPLIANCE TESTING FOR FMVSS NO. 118"),
        (5, "report_date", "Report Date", "报告日期", "date", "2011-03-17"),
        (6, "performing_org_code", "Performing Organization Code", "执行机构代码", "text", None),
        (7, "authors", "Author(s)", "作者", "text", "Grant Farrand / Debbie Messick"),
        (8, "performing_org_report_no", "Performing Organization Report No.",
         "执行机构报告号", "text", None),
        (9, "performing_org_name_address", "Performing Organization Name and Address",
         "执行机构名称与地址", "textarea",
         "General Testing Laboratories, Inc., 1623 Leedstown Road, "
         "Colonial Beach, Virginia 22443"),
        (10, "work_unit_no", "Work Unit No.", "工作单元号", "text", None),
        (11, "contract_or_grant_no", "Contract or Grant No.", "合同或资助号", "text",
         "DTNH22-06-C-00032"),
        (12, "sponsoring_agency_name_address", "Sponsoring Agency Name and Address",
         "主办机构名称与地址", "textarea",
         "U.S. Department of Transportation, National Highway Traffic Safety "
         "Administration, Office of Vehicle Safety Compliance (NVS-220)"),
        (13, "type_of_report_and_period", "Type of Report and Period Covered",
         "报告类型与周期", "text", "FINAL REPORT"),
    ]
    tp_fields = []
    for num, key, en, zh, ftype, sample in tech_page:
        tp_fields.append({
            "field_no": num,
            "key": key,
            "name_en": en,
            "name_zh": zh,
            "type": ftype,
            # 场景一用 Excel 单元格定位（label_cell / value_cell）；
            # 本场景是 PDF 报告结构，同一概念落成「节 / 字段」
            "label_section": "Technical Report Documentation Page",
            "label_slot": "字段 %d 标题" % num,
            "value_slot": "字段 %d 取值" % num,
            "sample_value": sample,
            "from_flow": F6,
            "required_by": "ISO/IEC 17025:2017 §7.8.2" if key in (
                "report_no", "report_date", "performing_org_name_address",
                "title_and_subtitle") else None,
            "_source": src(NHTSA_PDF, "第 3 页 Technical Report Documentation Page，字段 %d" % num),
        })

    sections = [
        {
            "section_no": "封面",
            "name_en": "Cover",
            "name_zh": "封面",
            "fields": [
                {"key": "report_no", "name": "报告编号", "value_slot": "封面首行"},
                {"key": "standard_no_title", "name": "标准号与标题",
                 "value_slot": "SAFETY COMPLIANCE TESTING FOR FMVSS NO. 118 / "
                               "POWER-OPERATED WINDOW, PARTITION AND ROOF PANEL SYSTEMS"},
                {"key": "vehicle_make_model", "name": "被测车辆制造商与型号",
                 "value_slot": "2011 NISSAN JUKE S MPV"},
                {"key": "nhtsa_no", "name": "NHTSA 编号", "value_slot": "CB5201"},
                {"key": "lab_name_address", "name": "检测实验室名称与地址",
                 "value_slot": "General Testing Laboratories, Inc. 及地址"},
                {"key": "date", "name": "日期", "value_slot": "最终报告日期"},
                {"key": "final_report_mark", "name": "FINAL REPORT 字样", "value_slot": "封面标记"},
                {"key": "sponsor_name_address", "name": "委托机构全称与地址",
                 "value_slot": "U.S. DOT / NHTSA, NVS-220 及地址"},
            ],
            "from_flow": F6,
            "maps_to": None,
            "_source": [src(NHTSA_PDF, "第 1 页 封面"), b(397, "封面字段清单")],
        },
        {
            "section_no": "免责声明页",
            "name_en": "Disclaimer",
            "name_zh": "免责声明页",
            "fields": [
                {"key": "distribution_statement", "name": "分发声明", "value_slot": "正文段"},
                {"key": "prepared_by", "name": "Prepared By 数字签名", "value_slot": "签名位"},
                {"key": "approved_by", "name": "Approved By 数字签名", "value_slot": "签名位"},
                {"key": "approval_date", "name": "批准日期", "value_slot": "日期位"},
            ],
            "from_flow": F6,
            "maps_to": None,
            "note": "双签名是 ISO/IEC 17025:2017 §7.8.2 的授权签字要求在本模板里的落点。",
            "_source": [src(NHTSA_PDF, "第 2 页 免责声明页"), b(398, "免责声明页字段")],
        },
        {
            "section_no": "技术著录页",
            "name_en": "Technical Report Documentation Page",
            "name_zh": "技术报告著录页",
            "fields": [{"key": f["key"], "name": f["name_zh"],
                        "value_slot": f["value_slot"]} for f in tp_fields],
            "from_flow": F6,
            "maps_to": "report-template.json technical_report_documentation_page",
            "note": "13 个编号字段，详见 technical_report_documentation_page 数组。",
            "_source": [src(NHTSA_PDF, "第 3 页"), b(399, "13 个编号字段清单")],
        },
        {
            "section_no": "1",
            "name_en": "Purpose of Compliance Test",
            "name_zh": "第 1 节 试验目的",
            "fields": [
                {"key": "purpose", "name": "1.0 试验目的", "value_slot": "正文段"},
                {"key": "vin", "name": "1.1 车辆识别代号 VIN", "value_slot": "字段"},
                {"key": "nhtsa_no", "name": "1.1 NHTSA 编号", "value_slot": "字段"},
                {"key": "manufacturer", "name": "1.1 制造商", "value_slot": "字段"},
                {"key": "manufacture_date", "name": "1.1 制造日期", "value_slot": "字段"},
                {"key": "color", "name": "1.1 颜色", "value_slot": "字段"},
                {"key": "test_date", "name": "1.2 试验日期", "value_slot": "字段"},
            ],
            "from_flow": F6,
            "maps_to": "scene.json product + product-attributes.json",
            "note": "被测件识别段。本场景若测的是升降器总成而不是整车，"
                    "VIN / 颜色 / 制造日期三个字段应换成总成件号、批次号与生产日期——"
                    "**这是模板从整车级移植到零部件级时必须改的一处**，本包只登记不擅改。",
            "_source": [src(NHTSA_PDF, "第 5 页 SECTION 1"), b(400, "第 1 节字段清单")],
        },
        {
            "section_no": "2",
            "name_en": "Test Procedure and Summary of Results",
            "name_zh": "第 2 节 试验程序与结果摘要",
            "fields": [
                {"key": "procedure_ref", "name": "2.0 试验程序引用",
                 "value_slot": "TP-118-06 与实验室内部程序 TP-118-03A"},
                {"key": "steps_a_to_h", "name": "2.0 八个步骤的执行序列 A 至 H",
                 "value_slot": "步骤表"},
                {"key": "summary_of_results", "name": "2.1 结果摘要", "value_slot": "摘要段"},
            ],
            "from_flow": F6,
            "maps_to": "workflows.json（执行序列）+ test-requirements.json（判定结论）",
            "_source": [src(NHTSA_PDF, "第 6 页 SECTION 2"), b(401, "第 2 节字段清单"),
                        b(391, "TP-118-06 与 TP-118-03A")],
        },
        {
            "section_no": "3",
            "name_en": "Test Data",
            "name_zh": "第 3 节 试验数据",
            "fields": [
                {"key": "data_sheet_1", "name": "DATA SHEET 1 内部锁止系统试验",
                 "value_slot": "数据表"},
                {"key": "data_sheet_2", "name": "DATA SHEET 2 钥匙拔出后的锁止试验",
                 "value_slot": "数据表"},
                {"key": "data_sheet_3", "name": "DATA SHEET 3 外部锁止系统试验",
                 "value_slot": "数据表"},
                {"key": "data_sheet_4", "name": "DATA SHEET 4 遥控促动装置",
                 "value_slot": "数据表"},
                {"key": "data_sheet_5", "name": "DATA SHEET 5 乘员舱促动装置试验（球体试验）",
                 "value_slot": "数据表"},
                {"key": "data_sheet_6", "name": "DATA SHEET 6 乘员舱促动装置试验（仅电动车窗）",
                 "value_slot": "数据表"},
                {"key": "data_sheet_7", "name": "DATA SHEET 7 物理接触反向能力",
                 "value_slot": "数据表"},
                {"key": "pre_operational_check", "name": "WPRP 预操作检查", "value_slot": "数据表"},
                {"key": "compliance_data_summary", "name": "合规数据汇总表", "value_slot": "汇总表"},
            ],
            "from_flow": F6,
            "maps_to": "test-requirements.json（判据）+ datasets.json（时序证据）",
            "note": "原报告的七张数据表全部是整车级的锁止与促动装置试验。"
                    "本场景若做零部件级的 QC/T 626 判据，这一节要整套换成"
                    "基本性能、自锁、防夹、环境与耐久五组数据表——"
                    "**换的是本节内容，不是报告骨架**，这正是模板可复用的证明。",
            "_source": [src(NHTSA_PDF, "第 7 至 16 页 SECTION 3"), b(402, "第 3 节数据表清单")],
        },
        {
            "section_no": "4",
            "name_en": "Test Equipment List",
            "name_zh": "第 4 节 试验设备清单",
            "fields": [
                {"key": "equipment_list", "name": "设备清单（名称、型号、序列号、校准日期）",
                 "value_slot": "设备表"},
            ],
            "from_flow": F6,
            "maps_to": "control-parameters.json 台架与工装组 + 数据采集组",
            "note": "本场景的设备清单应覆盖：程控电源（13.5 ± 0.3 V、纹波 ≤100 mV）、"
                    "力传感器（防夹与自锁两个量级分开选型）、位移传感器（最小刻度 ≤0.05 mm）、"
                    "电流传感器、声级计、环境箱、盐雾箱、振动台、耐压仪。",
            "_source": [src(NHTSA_PDF, "第 17 页 SECTION 4"), b(403, "第 4 节设备清单"),
                        b(134, "仪器精度 6.1 a)")],
        },
        {
            "section_no": "5",
            "name_en": "Photographs",
            "name_zh": "第 5 节 照片",
            "fields": [{"key": "figure_5_%d" % i, "name": "FIGURE 5.%d" % i,
                        "value_slot": "照片位 %d" % i} for i in range(1, 16)],
            "from_flow": F6,
            "maps_to": "scene.json images",
            "photo_count": 15,
            "photo_subjects": [
                "整车左前 3/4 视图", "整车右后 3/4 视图", "车辆认证标签特写",
                "轮胎信息标签特写", "四个车窗开关特写（4 张）", "钥匙", "点火开关",
                "仪器装配", "四处球体试验照片（4 张）",
            ],
            "note": "15 张编号照片。本包已把 FIGURE 5.1 渲染成 "
                    "assets/product-photo-nhtsa-fig5-1.png 作为场景示意图。"
                    "零部件级试验的照片清单应换成：总成件全貌、铭牌特写、"
                    "试验棒布置、力传感器安装、位移传感器安装、声级计测点、"
                    "试验前后对比、拆机检查照片。",
            "_source": [src(NHTSA_PDF, "第 18 至 33 页 SECTION 5"), b(404, "15 张编号照片清单")],
        },
        {
            "section_no": "6",
            "name_en": "Owner's Manual Information",
            "name_zh": "第 6 节 用户手册信息",
            "fields": [
                {"key": "owners_manual_pages", "name": "用户手册相关页", "value_slot": "扫描件"},
                {"key": "pinch_warning_present", "name": "被夹住可能性的说明是否存在",
                 "value_slot": "勾选"},
                {"key": "driver_switch_instruction", "name": "驾驶员控制开关使用方法",
                 "value_slot": "勾选"},
                {"key": "child_warning_present", "name": "针对儿童的警告信息是否存在",
                 "value_slot": "勾选"},
            ],
            "from_flow": F6,
            "maps_to": "test-requirements.json TR-RULE-03",
            "note": "对应 GB 11552-2009 §4.8.6 的用户手册要求。"
                    "这一节是 evaluable: false 那三条判据里唯一进报告的。",
            "_source": [src(NHTSA_PDF, "第 34 页 SECTION 6"), b(405, "第 6 节"),
                        src(GB11552_TXT, "gb11552.txt:456-462 §4.8.6")],
        },
    ]

    return dump("report-template.json", {
        "schema": "report-template/v1",
        "scene_id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "belongs_to_flow": "F6 测试报告及产出（模板确认、信息确认）",
        "template_source": {
            "kind": "PDF 报告样张（非 Excel 模板）",
            "file": NHTSA_PDF,
            "title": "REPORT NUMBER 118-GTL-11-002, SAFETY COMPLIANCE TESTING FOR "
                     "FMVSS NO. 118, POWER-OPERATED WINDOW, PARTITION AND ROOF PANEL "
                     "SYSTEMS — 2011 NISSAN JUKE S MPV, NHTSA NO. CB5201",
            "lab": "General Testing Laboratories, Inc., 1623 Leedstown Road, "
                   "Colonial Beach, Virginia 22443",
            "sponsor": "U.S. Department of Transportation, National Highway Traffic "
                       "Safety Administration, Office of Vehicle Safety Compliance (NVS-220)",
            "report_date": "2011-03-17",
            "test_date": "2011-03-15",
            "contract_no": "DTNH22-06-C-00032",
            "page_count": 36,
            "url": "https://www.carsandracingstuff.com/library/reports/5683.pdf",
            "_source": b(387, "报告全名、检测方、委托方、人员、日期与合同号"),
        },
        "cell_model_note":
            "场景一的报告模板是 Excel（.xlsm），字段定位用 label_cell / value_cell "
            "两个单元格地址。本场景的模板是 PDF 报告，没有单元格，"
            "同一个概念落成 **节（section）+ 字段（field）** 两级："
            "label_section 定位到哪一节，label_slot 与 value_slot 定位到节内的"
            "字段标题位与取值位。前端渲染器只要认「一个标题位 + 一个取值位」这个抽象，"
            "两个场景的模板就能共用同一套填充逻辑。",
        "section_count": len(sections),
        "technical_page_field_count": len(tp_fields),
        "photo_count": 15,
        "compliance_basis": [
            {"standard": "ISO/IEC 17025:2017 §7.8 Reporting of results",
             "required_elements": [
                 "标题", "实验室标识", "每页唯一报告编号", "客户信息", "方法引用",
                 "样品描述", "接收日期", "试验日期", "签发日期", "带单位的结果",
                 "授权签字", "修订条款",
             ],
             "_status": "标准编号与版次已核实；字段清单经 Perry Johnson Laboratory "
                        "Accreditation, Inc. (PJLA) 公开培训讲义转述，待核实",
             "_source": b(411, "ISO/IEC 17025:2017 第 7.8 条必含要素")},
            {"standard": "CNAS-EL-13《检测报告和校准证书相关要求的认可说明》（2019-12-25）",
             "required_elements": ["国内报告字段合规性的主依据，正文未取得"],
             "_status": "待核实（PDF 文本层抽取失败）",
             "_source": b(412, "CNAS-EL-13 全名、机构与日期")},
            {"standard": "45.2 Question on Amendments to Test Reports, ISO/IEC 17025 "
                         "Clause 7.8.8.1（欧洲认可合作组织 European Accreditation 官方问答）",
             "required_elements": ["报告修订与换版字段的设计依据"],
             "_status": "待核实",
             "_source": b(413, "European Accreditation 关于试验报告修订的官方问答")},
            {"standard": "QC/T 626 征求意见稿第 7 章检验规则",
             "required_elements": ["型式检验与出厂检验的分组、抽样与判定规则，"
                                   "是报告「结论」段的生成逻辑"],
             "_status": "待核实（QC/T 626-2019 正式版可能调整）",
             "_source": b(414, "QC/T 626 征求意见稿第 7 章检验规则")},
        ],
        "technical_report_documentation_page": tp_fields,
        "spec_sections": sections,
        "conclusion_binding": {
            "note": "报告「结论」段不是人写的自由文本，而是由 test-requirements.json 的"
                    "逐条判定结果按检验规则聚合出来的。本场景的聚合规则："
                    "型式检验按组判，组内任一项 FAIL 则该组 FAIL；"
                    "防夹三条（TR-PINCH-01/03/04）按目标市场只取其一参与聚合，"
                    "不参与的两条在报告里标 N/A 而不是 PASS。",
            "_source": [b(414, "QC/T 626 征求意见稿第 7 章检验规则"),
                        b(415, "QC/T 29090-2023 第 6 章检验规则（已核实）")],
        },
        "known_gap": {
            "text": "NHTSA 官方声明：合规报告公开是为信息交流，"
                    "其意见、发现与结论不应被视为产品是否合规的最终判定。"
                    "因此这份样张只能作为**版式与字段骨架**的来源，"
                    "不能把它的判定口径直接搬成本系统的判定口径。",
            "_source": b(390, "NHTSA 官方声明"),
        },
    })
