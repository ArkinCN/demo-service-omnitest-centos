# -*- coding: utf-8 -*-
"""生成 workflows.json / datasets.json / experience.json / documents.json /
report-template.json。"""
import glob
import gzip
import json
import os
import shutil

from common import (AITIOR, ATTEMPTS, BENCH_MEMO, BUILD_DATE, CASE_XLSX, CF_ROOT,
                    CUSTOMER_H, DATA_0627, DATA_0701, DATASHEET, DOC_A, DOC_B,
                    DOC_NEED, EXP_DOC_DIR, GENERATED_BY, HW_NODIODE_PDF,
                    HW_STD_PDF, HW_VSP_PDF, MOTOR_PROT_H, OUT, PKG98,
                    PREALIGN_REPORT, PROTECT_H, REPO, REPORT_XLSM, SCENE_ID,
                    TEMPLATE_XLSM, WFW_MAIN, WFW_SUB, WRITEFILE_README, dump, src)

NOT_FOUND = []


# ---------------------------------------------------------------- 6. workflows
GROUP_MEANING = {
    "HEADWINDTEST": ("逆风测试", "在涵道内用前置风扇制造逆风，验证被测风扇的逆风识别、制动与重启"),
    "OPENCLOSEPOWER": ("上下电测试", "反复通断母线电源，验证上电启动与下电停机的可靠性"),
    "OTHERTEST": ("其他专项测试", "母线电压跌落、示波器采集与整机全项串跑等专项流程"),
    "PWMDUTY_0TO100": ("PWM 占空比 0→100 扫描", "占空比从 0% 逐档升到 100%，记录各档转速与电流"),
    "PWMDUTY_100TO0": ("PWM 占空比 100→0 扫描", "占空比从 100% 逐档降到 0%，验证降速不停转"),
    "PWMDUTY_HIGHTOLOW": ("PWM 高速切低速", "占空比由高档直接切到低档，测阶跃降速响应"),
    "PWMDUTY_LOWTOHIGH": ("PWM 低速切高速", "占空比由低档直接切到高档，测阶跃升速响应"),
    "StaticStart": ("静止启动测试", "风扇静止状态下按各档占空比启动，测起动成功率与起动时间"),
    "TAILWINDWIND": ("顺风测试", "被测风扇带残速时重新启动，验证顺风识别与接管"),
    "writingpaper_scope": ("报告素材归档", "示波器截图与报告模板的归档目录，非工作流"),
    "子流程": ("可复用子流程", "被主工作流以 subworkflow 节点引用的原子测试片段"),
    "WORKINGflow": ("未分组主流程", "直接放在 WORKINGflow 根目录的工作流"),
}

NODE_MEANING = {
    "start": "开始", "end": "结束", "delay": "延时等待",
    "subworkflow": "调用子流程", "variable": "变量赋值", "loop": "循环",
    "loop_break": "跳出循环", "curve_lookup": "曲线查表",
    "report_generator": "生成报告", "agent_debug": "交给 Agent 调试",
    "rigol_oscilloscope": "RIGOL 示波器采集",
    "hid_preset_voltage_set": "设置母线电压", "hid_preset_speed_test": "转速测试",
    "hid_preset_relay_open": "继电器通断", "hid_preset_power_on": "上电",
    "hid_preset_power_off": "下电", "hid_preset_fan_start_test": "风扇启动测试",
    "hid_query_speed": "查询转速", "hid_query_current": "查询电流",
    "hid_preset_headwind_set": "设置逆风", "hid_preset_tailwind_set": "设置顺风",
    "hid_preset_tailwind_exit": "退出顺风", "hid_preset_wind_close": "关闭风源",
    "hid_preset_start_stop_test": "启停测试", "hid_preset_pwm_speed_set": "设置 PWM 调速",
}


def _voltage_level(name, relpath):
    up = (name + "/" + relpath).upper()
    hits = []
    for tag, full in (("HV", "高压"), ("SV", "标准电压"), ("LV", "低压")):
        for probe in ("_" + tag, tag + "_", "/" + tag + "/", "/" + tag + "."):
            if probe in up:
                hits.append(tag)
                break
    hits = sorted(set(hits), key=["LV", "SV", "HV"].index)
    if not hits:
        return None, "未标电压等级"
    if len(hits) == 1:
        return hits[0], {"HV": "高压", "SV": "标准电压", "LV": "低压"}[hits[0]]
    return "+".join(hits), "三档电压串跑（" + "、".join(hits) + "）"


def _purpose(group_cn, group_desc, vol_cn, is_sub, types):
    head = group_desc
    tail = []
    if vol_cn and vol_cn != "未标电压等级":
        tail.append("在%s下执行" % vol_cn)
    if is_sub:
        tail.append("本文件是被主流程引用的子流程")
    marks = []
    if "rigol_oscilloscope" in types:
        marks.append("带示波器采集")
    if "report_generator" in types:
        marks.append("自动出报告")
    if "loop" in types:
        marks.append("含循环回归")
    if marks:
        tail.append("，".join(marks))
    return head + ("；" + "；".join(tail) if tail else "") + "。"


def gen_workflows():
    roots = [(WFW_MAIN, "WORKINGflow/WORKINGflow"), (WFW_SUB, "子流程/子流程")]
    items = []
    for root, label in roots:
        if not os.path.isdir(root):
            NOT_FOUND.append("工作流目录不存在：%s" % root)
            continue
        for p in sorted(glob.glob(os.path.join(root, "**", "*.wfw"), recursive=True)):
            rel = os.path.relpath(p, root)
            raw = open(p, "rb").read()
            gz = False
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
                gz = True
            j = json.loads(raw.decode("utf-8-sig"))
            d = j.get("definition", {})
            nodes = d.get("nodes", [])
            edges = d.get("edges", [])
            types = sorted(set(n.get("type") for n in nodes))
            meta = j.get("metadata", {})
            if label.startswith("子流程"):
                gkey = "子流程"
            else:
                parts = rel.replace(os.sep, "/").split("/")
                gkey = parts[0] if len(parts) > 1 else "WORKINGflow"
            gcn, gdesc = GROUP_MEANING.get(gkey, (gkey, gkey))
            vol, volcn = _voltage_level(os.path.basename(p), rel.replace(os.sep, "/"))
            is_sub = ("_SUB" in os.path.basename(p).upper()
                      or "_Sub" in os.path.basename(p)
                      or label.startswith("子流程"))
            items.append({
                "id": "WF-%03d" % (len(items) + 1),
                "name": os.path.splitext(os.path.basename(p))[0].strip(),
                "metadata_name": meta.get("name"),
                "group": {"key": gkey, "name": gcn},
                "voltage_level": vol,
                "voltage_level_name": volcn,
                "is_subworkflow": is_sub,
                "file_path": p,
                "file_size_bytes": os.path.getsize(p),
                "gzip": gz,
                "format_version": j.get("formatVersion"),
                "tags": meta.get("tags", []),
                "updated_at": meta.get("updatedAt"),
                "node_count": len(nodes),
                "edge_count": len(edges),
                "node_types": [{"type": t, "name": NODE_MEANING.get(t, t),
                                "count": sum(1 for n in nodes if n.get("type") == t)}
                               for t in types],
                "purpose": _purpose(gcn, gdesc, volcn, is_sub, types),
                "purpose_derived": True,
                "_source": src(p, "definition.nodes 长度 = %d，definition.edges 长度 = %d，"
                                  "metadata.name / metadata.tags" % (len(nodes), len(edges))),
            })
    groups = {}
    for it in items:
        groups.setdefault(it["group"]["key"], 0)
        groups[it["group"]["key"]] += 1
    obj = {
        "schema": "workflows/v1",
        "scene_id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "belongs_to_flow": "F3 测试需求确认（工作流一步步运转、可调整）+ F4 启动测试及结果分析（执行）",
        "source_roots": [r for r, _ in roots],
        "total": len(items),
        "count_by_group": groups,
        "node_type_legend": NODE_MEANING,
        "notes": [
            ".wfw 实测是明文 UTF-8 JSON（带 BOM），不是 gzip；脚本仍保留 gzip 探测分支。"
            "顶层三键：formatVersion / metadata / definition，节点在 definition.nodes。",
            "任务书写「58 个归档工作流」，与 WORKINGflow/WORKINGflow 下的 .wfw 数量一致；"
            "加上 子流程/子流程 下的 9 个，本索引共 %d 条。"
            "调研文档 B 记的是「63 个主工作流 + 9 个子流程」，与本次实测不符，以本次实测为准。" % len(items),
            "purpose 字段由目录分组、电压等级、节点类型组合生成（purpose_derived=true），"
            "不是源文件里的原话。",
        ],
        "workflows": items,
    }
    return dump("workflows.json", obj)


# ---------------------------------------------------------------- 7. datasets
WAVE_PICKS = [
    ("TRY-0009", "PASS", None, "合格样本（本批次口径下为「太弱注入但侥幸启动成功」）"),
    ("TRY-0010", "FAIL", "CF-L-0003", "不合格样本 1（启动失败）"),
    ("TRY-0021", "FAIL", "CF-L-0007", "不合格样本 2（启动失败）"),
]


def gen_datasets():
    items = []

    # --- 登记型（大文件只登记不复制）---
    for path, name, note in [
        (DATA_0701, "faithful_norm1200 忠实降采样 1200 点时序",
         "1200 点降采样复现产物，用于核对客户软件的 1200 点显示口径"),
        (DATA_0627, "fullrun_v2b 六档变速全程深存储时序",
         "六档变速全程采集，峰岹时序汇报的主用数据源"),
    ]:
        if not os.path.exists(path):
            NOT_FOUND.append("时序数据缺失：%s" % path)
            continue
        with open(path, "r", encoding="utf-8-sig") as f:
            header = f.readline().strip()
        cols = header.split(",")
        items.append({
            "id": os.path.splitext(os.path.basename(path))[0],
            "name": name,
            "mode": "registered_only",
            "file_path": path,
            "file_size_bytes": os.path.getsize(path),
            "columns": [{"key": c, "name": {
                "time_s": "时间（秒，0 为上电时刻）",
                "ch1_current_V": "CH1 相电流（列名沿用示波器通道命名，物理量是电流）",
                "ch2_fg1_V": "CH2 FG1 电气转速反馈",
                "ch3_fg2_V": "CH3 FG2 红外机械转速（1 脉冲/转）",
                "ch4_pwm1_V": "CH4 PWM1 驱动输出",
            }.get(c, c)} for c in cols],
            "label": None,
            "note": note + "。文件为百 MB 级，本场景包只登记路径不复制。",
            "_source": [src(path, "第 1 行表头：%s" % header),
                        src(BENCH_MEMO, "通道定义与 FG1=2×FG2 判据")],
        })

    # --- 复制型（98 次实验里的 3 个 attempt）---
    wdir = os.path.join(OUT, "assets", "waveforms")
    os.makedirs(wdir, exist_ok=True)
    for tid, label, case_id, note in WAVE_PICKS:
        srcf = os.path.join(ATTEMPTS, tid, "capture", "CH1_上电时刻归一化.csv")
        infof = os.path.join(ATTEMPTS, tid, "capture", "采集信息.json")
        if not os.path.exists(srcf):
            NOT_FOUND.append("波形文件缺失：%s" % srcf)
            continue
        dst = os.path.join(wdir, "%s_CH1_powerup_normalized.csv" % tid)
        shutil.copyfile(srcf, dst)
        with open(srcf, "r", encoding="utf-8-sig") as f:
            header = f.readline().strip()
            nrows = sum(1 for _ in f)
        info = json.load(open(infof, encoding="utf-8-sig")) if os.path.exists(infof) else {}
        ss = info.get("scope_settings", {})
        wf = (info.get("waveforms") or [{}])[0]
        items.append({
            "id": tid,
            "name": "启动上电时刻归一化相电流波形（%s）" % tid,
            "mode": "copied_into_pack",
            "file_path": dst,
            "source_file_path": srcf,
            "file_size_bytes": os.path.getsize(dst),
            "row_count": nrows,
            "columns": [
                {"key": "time_s", "name": "时间（秒，t=0 为人工点击上电时刻，存在最多 1 秒操作误差）"},
                {"key": "voltage_v", "name": "CH1 相电流（安培；列名沿用示波器通道命名）"},
                {"key": "raw_byte", "name": "示波器原始字节"},
                {"key": "original_scope_time_s", "name": "归一化前的示波器时间"},
                {"key": "sample_source", "name": "样本来源标记（SYNTHETIC_PRE_POWER 为上电前人工 0V 补线）"},
            ],
            "sample_rate_sa_per_s": ss.get("sample_rate_sa_per_s"),
            "memory_depth": ss.get("memory_depth"),
            "scope": info.get("idn"),
            "y_increment_v": wf.get("x_increment_s") and wf.get("y_increment_v"),
            # M2：CH1 已确认采的是电流、voltage_v 列按安培读，但探头变比（是否 1 A/V）
            # 客户尚未确认。变比未定则所有绝对量级阈值不可对外引用，只能比形状与相对变化。
            "probe_ratio_confirmed": False,
            "probe_ratio_note": ("探头变比未确认。客户已澄清 CH1 采的就是电流、voltage_v 列按安培读，"
                                 "但若探头不是 1 A/V，全部数值要按客户给的 mV/A 系数整体缩放一次。"
                                 "不阻断判定链路（形状类判据不受影响），"
                                 "但 align_mean_a 一类绝对量级阈值在变比确认前不得对外引用。"),
            "label": {
                "operator_result": label,
                "case_id": case_id,
                "injected_fault": "align_weak（预定位太弱）",
                "meaning": note,
            },
            "note": "本批次 98 条登记样本的成因金标准全部是 align_weak，没有一条正常样本；"
                    "PASS 与 FAIL 的差别只是这一次启动成没成，不是固件参数正常还是故障。"
                    "t<0 的上电前窗口是人工 0 V 补线，不是示波器实测，不得据此评价噪声或零漂。",
            "_source": [
                src(srcf, "第 1 行表头：%s" % header),
                src(os.path.join(ATTEMPTS, tid, "operator_label.json"), "operator_result 字段"),
                src(infof, "scope_settings / idn / waveforms[0]"),
                src(PREALIGN_REPORT, "第 0.1 节口径修订、第 1.2 节每文件格式与量级"),
                src(PREALIGN_REPORT,
                    "分析报告-预定位太弱判定-20260812.md:450「| 探头变比 | 未确认 | "
                    "客户给出 mV/A 系数（或确认 1 A/V），整体缩放一次即可。不阻断判定链路，"
                    "但影响所有绝对量级阈值能不能对外引用 |」，另见同文件第 470 行待客户确认第 1 项"),
            ],
        })

    obj = {
        "schema": "datasets/v1",
        "scene_id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "belongs_to_flow": "F4 启动测试及结果分析（时序曲线回放与判定）",
        "package_root": PKG98,
        "package_stats": {
            "attempts_total": 101,
            "labeled": 98,
            "pass": 67,
            "fail": 30,
            "invalid": 1,
            "usable_for_waveform_analysis": 97,
            "_source": src(PREALIGN_REPORT, "第 1.1 节 交付包结构与登记口径 表"),
        },
        "datasets": items,
    }
    return dump("datasets.json", obj)


# -------------------------------------------------------------- 8. experience
CFSKILL = os.path.join(AITIOR, "dc-skills/coolingfan-openloop-debug/SKILL.md")
TRIAGE = os.path.join(AITIOR, "dc-skills/coolingfan-openloop-debug/SKILL.md")


def exp(eid, symptom, cause, action, result, source, tags, confidence="规程条款",
        note=None, parameters_resolved=True, status=None):
    d = {
        "id": eid, "symptom": symptom, "cause": cause,
        "action": action, "result": result,
        "tags": tags, "evidence_level": confidence,
    }
    # M4：parameters_resolved 说明 tags.parameters 里的宏名能不能在本场景包里解析到
    # control-parameters.json 的某个 key。false 表示前端「按参数检索经验」检索不到这一条。
    d["parameters_resolved"] = parameters_resolved
    if status:
        d["_status"] = status
    if note:
        d["note"] = note
    d["_source"] = source
    return d


def gen_experience():
    T = lambda flow, params, extra=None: {
        "scene": ["motor", "cooling-fan", "fortior-fu6832"],
        "flow": flow, "parameters": params, "topic": extra or [],
    }
    items = [
        exp("EXP-001",
            "读到 fault = 1 或 2（硬过流 / 软过流），电机起转即报保护",
            "起转电流偏大，超过过流阈值",
            "把启动电流（MOTOR_START_IQ_CURRENT）下调 20%，重编重烧后复测",
            "过流消失则继续判定闭环稳态；仍过流则按分诊表继续下一轮，最多 3 轮",
            src(TRIAGE, "第 5 节 失败分诊迭代 表 第 1 行"),
            T("F5 调优确认及运行", ["MOTOR_START_IQ_CURRENT"], ["过流", "启动"])),
        exp("EXP-002",
            "读到 fault = 6（堵转），或起转即停",
            "起转力矩不足，或负载偏重",
            "先反问用户确认负载状况，再把启动电流上调 0.1~0.2 A",
            "力矩足够后可正常起转；负载确实偏重时应先解决机械问题",
            src(TRIAGE, "第 5 节 失败分诊迭代 表 第 2 行"),
            T("F5 调优确认及运行", ["MOTOR_START_IQ_CURRENT"], ["堵转", "启动"])),
        exp("EXP-003",
            "读到 fault = 5（缺相）",
            "三相接线问题，不是参数问题",
            "立即停止参数迭代，反问用户检查接线",
            "参数侧无解；继续盲调只会浪费烧录轮次",
            src(TRIAGE, "第 5 节 失败分诊迭代 表 第 3 行"),
            T("F4 启动测试及结果分析", [], ["缺相", "接线"])),
        exp("EXP-004",
            "无 fault，但示波器读到相电流频率约等于 0，电机不转",
            "起转电流不足，转子没被拖起来",
            "把启动电流上调 0.1~0.2 A 后重试",
            "电流够了即可起转；配合观察起转包络确认是否切到闭环",
            src(TRIAGE, "第 5 节 失败分诊迭代 表 第 4 行"),
            T("F5 调优确认及运行", ["MOTOR_START_IQ_CURRENT"], ["不转", "启动"])),
        exp("EXP-005",
            "起转起来了，但切闭环瞬间掉速或失步",
            "开环切闭环的切换点不合适",
            "调整闭环切换转速（MOTOR_LOOP_RPM）±20%，并复核起转电流",
            "切换点匹配后可平滑过渡；Customer.h 注释给的 Open-Omega 操作范围是 500~2000 RPM",
            [src(TRIAGE, "第 5 节 失败分诊迭代 表 第 5 行"),
             src(CUSTOMER_H, "Customer.h:113 注释「MOTOR_LOOP_RPM 操作範圍: 500~2000」")],
            T("F5 调优确认及运行", ["MOTOR_LOOP_RPM", "MOTOR_START_IQ_CURRENT"],
              ["切闭环", "失步"])),
        exp("EXP-006",
            "mcState 一直停在开环态，转速上不到目标",
            "没真正进闭环，或目标转速超出电机/供电能力",
            "先确认 OPENLOOP_ENABLED=0、SPEED_MODE=NONEMODE 已生效；"
            "仍不行则反问用户目标转速是否超能力",
            "配置没生效是常见原因；确认生效后再谈能力边界",
            src(TRIAGE, "第 5 节 失败分诊迭代 表 第 6 行"),
            T("F4 启动测试及结果分析", ["OPENLOOP_ENABLED", "SPEED_MODE"], ["闭环", "配置未生效"]),
            parameters_resolved=False,
            note="tags.parameters 的两个宏里只有 SPEED_MODE 能解析到本包的 control-parameters.json"
                 "（key = speed_mode）。OPENLOOP_ENABLED 宏在本工程 Customer.h:220 确实存在"
                 "（当前值 0，开环调速禁用），但它不在本包登记的 70 个控制参数里——"
                 "本包登记的 outloop_enabled 对应的是 OUTLOOP_ENABLED（速度外环使能），"
                 "与 OPENLOOP_ENABLED（开环调速使能）是两个宏，名字只差一个字母，不可混用。"
                 "前端按参数检索时 OPENLOOP_ENABLED 这一维检索不到，需先补登记该宏"),
        exp("EXP-007",
            "稳态转速偏差超过容限（缺省 5%），但转速本身是稳定的",
            "外环增益不足，或目标转速换算口径错了",
            "先复核目标转速宏的数值外壳与换算（极对数、S_Value 单位），"
            "确认无误后经用户同意把速度环 Ki（SPEED_KI / SKI）上调 20%",
            "换算错是更常见的原因，先查换算再动 PI",
            src(TRIAGE, "第 5 节 失败分诊迭代 表 第 7 行"),
            T("F5 调优确认及运行", ["SPEED_KI", "Pole_Pairs"], ["稳态偏差", "外环 PI"]),
            parameters_resolved=False,
            status="待核实：Pole_Pairs 宏在客户头文件 Customer.h:56（#define Pole_Pairs (2)）确实存在，"
                   "本包也已登记，但登记位置是 product-attributes.json 的电机本体属性"
                   "（key = pole_pairs，极对数），不在 control-parameters.json 的 70 个可调控制参数里。"
                   "SPEED_KI 能解析到 control-parameters.json 的 key = speed_ki。"
                   "极对数是否应补登记为可调参数，待客户确认，确认前本条按未解析处理。"),
        exp("EXP-008",
            "稳态转速振荡，3 次频率测量的极差 / 均值超过 3%",
            "外环增益偏高",
            "经用户同意把速度环 Kp（SPEED_KP / SKP）下调 20%，一次只动一项",
            "一次只动一个 PI 项，否则无法归因",
            src(TRIAGE, "第 5 节 失败分诊迭代 表 第 8 行"),
            T("F5 调优确认及运行", ["SPEED_KP"], ["振荡", "外环 PI"])),
        exp("EXP-009",
            "98 次台架复现里，启动失败样本的相电流绝对峰值明显高于启动成功样本",
            "预定位太弱（align_weak）：预定位强度不足，转子初始位置没锁住，"
            "起转阶段要靠更大的电流去纠正",
            "把预定位 D 轴输出强度（MOTOR_ALIGNMENT_DOUT）加大，"
            "或延长预定位时间（MOTOR_ALIGNMENT_TIMES）",
            "实测：启动成功组峰值 0.2886~0.4916 A（中位 0.3847），"
            "启动失败组 0.3527~0.5771 A（中位 0.5291）",
            [src(PREALIGN_REPORT, "第 1.2 节 表「电流绝对峰值」行"),
             src(PREALIGN_REPORT, "第 0.1 节第 2 条：客户证实全部 98 条都是「预定位太弱」的复现")],
            T("F5 调优确认及运行", ["MOTOR_ALIGNMENT_DOUT", "MOTOR_ALIGNMENT_TIMES"],
              ["预定位", "启动故障"]),
            confidence="台架实测数据"),
        exp("EXP-010",
            "预定位诊断报告里 A03 预定位末端稳定性、A04 预定位振荡两项判失败，"
            "但 A01 时间、A02 强度、A05 观测器三项都与型号健康基线一致",
            "参数逐项比对不出问题，波形末端却仍有较强动态——"
            "单通道 CH1 证据不足以把电流波动等同于机械振荡",
            "结论只能下到 NO_CONFIRMED_MCALIGN_FAULT（未确认 mcAlign 首要故障），"
            "置信度 0.40，继续往下检查 mcStart 阶段",
            "不硬下结论；缺的证据要写进「缺失」栏（无连续 mcState、"
            "缺转子位置/FG/现场同步视频）",
            [src(os.path.join(ATTEMPTS, "TRY-0010/tool_output/diagnosis_report.md"),
                 "一、诊断结论 与 二、逐项检查 表"),
             src(os.path.join(ATTEMPTS, "TRY-0010/tool_output/diagnosis.json"),
                 "verdict / atomic_detectors[]")],
            T("F4 启动测试及结果分析",
              ["MOTOR_ALIGNMENT_TIMES", "MOTOR_ALIGNMENT_DOUT", "ATO_BW"],
              ["预定位", "证据不足"]),
            confidence="判定工具输出"),
        exp("EXP-011",
            "想用上电前那一段静止波形评估底噪或零漂",
            "一个 ADC 量化步是 0.0106875，而上电前那段包络均值只有约 0.0017，"
            "整段没跨过一个量化码——测到的是量化残差，不是底噪",
            "放弃用本批数据评底噪；要评底噪必须换更小的垂直档位重采",
            "知识库判据里以底噪为主判据的那一条，在本批数据上直接评不了",
            src(PREALIGN_REPORT, "第 1.2 节「量化分辨率的问题与单位无关」段"),
            T("F4 启动测试及结果分析", [], ["示波器档位", "量化分辨率", "判据失效"]),
            confidence="台架实测数据"),
        exp("EXP-012",
            "按启动成败重新标定出来的规则表 v0.2，判出的 FAULT 数反而比预注册的 v0.1 少很多",
            "v0.2 那条 start_env_decay_ratio 判别的是「这次启动成没成」，"
            "不是「为什么不行」——把结果当成因去标定，判据就退化了",
            "成因判据回退到预注册的 v0.1；v0.2 只当启动成败的辅助特征",
            "v0.1 原样跑，97 条可用样本判出 94 条 FAULT、3 条 UNCERTAIN、0 条 OK，"
            "对金标准检出率 96.9%；v0.2 只判出 39 条 FAULT，作为成因判据是倒退",
            src(PREALIGN_REPORT, "第 0.2 节 一句话结论 与 第 5.4 节"),
            T("F5 调优确认及运行", [], ["判据标定", "成因 vs 结果"]),
            confidence="台架实测数据"),
        exp("EXP-013",
            "本批 98 条数据想用来算成因误报率",
            "全部 98 条的成因金标准都是 align_weak，正常样本 0 条——"
            "能测的只有检出率，测不了误报率",
            "要评误报率必须另外采一批正常样本；现阶段报告只写检出率",
            "67 条 PASS 也是太弱注入下的样本，只是侥幸启动成功，按失效样本计",
            src(PREALIGN_REPORT, "第 0.1 节第 3 条 与 第 0.2 节"),
            T("F3 测试需求确认", [], ["数据集口径", "误报率"]),
            confidence="台架实测数据"),
        exp("EXP-014",
            "两个电机都不转，不知道从哪查起",
            "先分清信号方向：PWM1/PWM2 是板子的输出，FG1/FG2 是输入到板子的反馈",
            "先测 PWM1（板子输出给被测风扇的占空比），确认板子有没有成功输出",
            "板子没输出就不必往电机侧查；这是台架排查的第一刀",
            src(BENCH_MEMO, "「信号定义(方向是关键,易混)」段"),
            T("F4 启动测试及结果分析", [], ["台架", "排查顺序"]),
            confidence="台架经验"),
        exp("EXP-015",
            "示波器接到 FG 通道却看不到方波",
            "FG 输出多为开漏结构",
            "在 FG 线上加上拉电阻再测",
            "上拉后方波可见；转速 RPM = FG 频率 × 60 / 每转脉冲数",
            src(BENCH_MEMO, "「示波器接线」段"),
            T("F4 启动测试及结果分析", ["FG_PULSE_PERIOD"], ["台架", "开漏", "接线"]),
            confidence="台架经验",
            parameters_resolved=False,
            status="待核实：FG_PULSE_PERIOD 宏在客户头文件 Customer.h:334"
                   "（#define FG_PULSE_PERIOD (2)，注释「FG 每轉脈波數量」）确实存在，本包也已登记，"
                   "但登记位置是 product-attributes.json 的转速信号属性"
                   "（key = fg_pulse_period，FG 每转脉波数），不在 control-parameters.json 的 70 个可调控制参数里。"
                   "每转脉冲数是否应补登记为可调参数，待客户确认，确认前本条按未解析处理。"),
        exp("EXP-016",
            "运行稳定性逐档扫描（sweep）跑出来的工作点全不对",
            "功率标定（Power_k）还没做就先跑了运行稳定",
            "把功率标定排到运行稳定之前：识别 → 灌默认基线 →（验板 → 验采样）→ "
            "启动 → 顺风 → 功率标定 → 运行稳定 → 保护 → 启停测试",
            "顺序纠正后 sweep 才落在真实工作点上。"
            "已知缺口：power-calibration 场景在客户 manifest 里仍是 planned，流程链有断点",
            [src(os.path.join(AITIOR, "dc-rules/vacuum-flow-discipline.md"), "第 9 条铁律"),
             src(DOC_A, "第三节 纪律层 与 第七节 四个缺口")],
            T("F5 调优确认及运行", [], ["阶段顺序", "功率标定"])),
        exp("EXP-017",
            "改宏时把 I_Value(2.0) 直接改成了纯数字 2.0",
            "数值宏的外壳（I_Value / S_Value / _Q15 / _Q12）承载单位换算，换掉外壳等于换了量纲",
            "只改括号内数字，不换外壳、不动行尾注释；"
            "枚举型宏写 token 名不写数字，且 token 必须是工程内已有的枚举名",
            "外壳错会让参数量级整体偏掉，且编译未必报错，属静默故障",
            src(CFSKILL, "第 1 节 闭环配置定位 与 第 2 节 备份 + 改宏 纪律"),
            T("F5 调优确认及运行", [], ["改宏纪律", "量纲"])),
        exp("EXP-018",
            "宏名在本工程里找不到（跨程序宏名不一致）",
            "不同程序的宏名和文件不同，散热风扇线与吸尘器线的命名就有差异",
            "按宏族分组 grep 候选；全部候选未命中时列出语义相近的宏名反问用户，"
            "严禁假设宏名、严禁新增 #define、严禁自建 #if 块",
            "用户给不出就进中断保护判 NG，不要硬猜",
            src(CFSKILL, "第 1 节 闭环配置定位（宏族探测，跨程序差异核心节）"),
            T("F2 初始化配置", [], ["跨程序移植", "宏族探测"])),
        exp("EXP-019",
            "没有物理示波器，流程要不要停",
            "散热风扇线支持降级，示波器不是硬前提；吸尘器的四份规程才强制要示波器",
            "选「无示波器」直接进降级模式：请用户等转速稳定后用转速表或 FG 读实际转速回报，"
            "按同样的 5% 容限判",
            "结论里必须注明「无示波器证据」；启动调参要更保守，因为识不破假转",
            [src(CFSKILL, "第 0 节 前置检查 与 第 4 节 降级模式"),
             src(os.path.join(AITIOR, "dc-rules/vacuum-flow-discipline.md"), "第 10 条铁律"),
             src(DOC_A, "第六节「示波器非硬前提（散热风扇可降级；吸尘器四份规程强制）」")],
            T("F4 启动测试及结果分析", [], ["降级模式", "示波器"])),
        exp("EXP-020",
            "rigol_waveform_analyze 调多了，设备被抢、流程变慢",
            "该工具走 RAW 全内存深度读取，耗时数秒，且与波形流抢设备",
            "只在判定窗口里调用一次，不要轮询",
            "把它当一次性取证，不当监控手段",
            src(CFSKILL, "第 4 节 证据二 第 3 步"),
            T("F4 启动测试及结果分析", [], ["示波器", "工具调用纪律"])),
        exp("EXP-021",
            "烧录完成后直接发 debug 让电机转起来",
            "烧录完 MCU 停在 reset vector，此时自动启动等于在无人确认下上电跑电机",
            "不要自动发 debug；提示用户上电或给使能，明确回复后再发",
            "这一条与「人员离场确认」同源：让电机转起来之前必须有人工闸口",
            [src(CFSKILL, "第 3 节 编译 + 烧录 第 3 步"),
             src(DOC_NEED, "典型流程 2 测试保护原则")],
            T("F4 启动测试及结果分析", [], ["人工闸口", "烧录"])),
        exp("EXP-022",
            "自动启动盲试把 10 个候选跑完了还是不行",
            "固定候选是有边界的盲试空间，每个候选只偏离 baseline 一个轴",
            "判 need_human 转人工，不得创建第 11 个候选、不得自行扩大搜索区间",
            "盲试的价值在可复现，扩区间就失去了可复现性",
            src(os.path.join(AITIOR, "dc-skills/auto-startup-tune/SKILL.md"),
                "「## 固定候选」与候选推进小节（第 106 行「need_human 不得继续创建第 11 个候选」）"),
            T("F5 调优确认及运行", ["SquStartCurrent", "StartCurrentAddThreshold",
                                    "RealFOCSwitchSpeed"], ["盲试", "边界"]),
            parameters_resolved=False,
            note="tags.parameters 的三个宏名 SquStartCurrent / StartCurrentAddThreshold / "
                 "RealFOCSwitchSpeed 来自 auto-startup-tune 规程的固定候选表，属吸尘器产品线；"
                 "本散热风扇工程的 Customer.h / Protect.h / Motor_Protection.h 全量 grep 三者均零命中，"
                 "本包 70 个控制参数里也没有对应项。语义上最接近的散热风扇宏是"
                 "MOTOR_START_IQ_CURRENT（启动电流）与 MOTOR_LOOP_RPM（进入闭环转速），"
                 "但对应关系未经客户确认，本包不做映射。"
                 "这条经验的方法论（盲试候选有边界、耗尽即 need_human）可迁移，具体宏名不可迁移"),
        exp("EXP-023",
            "保护验证做完，下一张卡片的结果跟着跑偏",
            "上一张卡片把电源调到过压/欠压后没调回来",
            "强制走调回流程：提示用户调回原母线电压，等用户明确回「已调回」，"
            "再读母线 ADC 复检，偏差 > 5% 判定降级",
            "不能由模型脑补「应该已经调回了」",
            src(os.path.join(AITIOR, "dc-skills/protect-verify-ovp/SKILL.md"),
                "第 2 节 Vbus 复检(强约束)"),
            T("F4 启动测试及结果分析", [], ["保护验证", "复检"])),
        exp("EXP-024",
            "想通过 writemem 直接改保护阈值来让保护触发",
            "在线改阈值是违规操作，改完读到的 fault 不能证明真实保护链路",
            "只读 RAM 观测，触发条件由用户手动调电源产生；"
            "确需改阈值的（超速、启动失败）走 protect-verify/* 临时分支，跑完 git reset + 重编重烧还原",
            "保证用户不会停在改坏的固件上",
            [src(os.path.join(AITIOR, "dc-skills/protect-verify-ovp/SKILL.md"), "设计约束段"),
             src(os.path.join(AITIOR, "dc-skills/protect-verify-overspeed/SKILL.md"),
                 "设计前提与「## 中断保护」小节")],
            T("F4 启动测试及结果分析", [], ["保护验证", "还原纪律"])),
    ]
    obj = {
        "schema": "experience/v1",
        "scene_id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "belongs_to_flow": "F1 知识库管理（经验性质那一类的样例数据）；"
                           "被 F4 / F5 在调参时检索命中",
        "count": len(items),
        "evidence_levels": {
            "台架实测数据": "来自 98 次启动故障实验数据包与其分析报告，有实测数字",
            "判定工具输出": "来自判定工具 diagnosis.json / diagnosis_report.md 的结构化结论",
            "规程条款": "来自客户机 25 份 dc-skills 与 5 份 dc-rules 的成文规则",
            "台架经验": "来自本项目台架硬件记忆，未成文进规程",
        },
        "schema_note": "每条 = 问题现象 symptom / 原因 cause / 调整动作 action / "
                       "结果 result / 来[源] _source / 标签 tags（场景、流程、参数名、主题）",
        "experiences": items,
    }
    return dump("experience.json", obj)


# --------------------------------------------------------------- 9. documents
def _size(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return None


# L1：conversion_status 收成固定枚举，中文说明单独放 label，转化目标单独放 converted_into
CONVERSION_STATUS = {
    "markdown_native": "本身就是 Markdown，可直接进知识库",
    "markdown_extracted": "源目录已有同名 .md 抽取版",
    "parsed_into_pack": "本场景包已把它解析成结构化 JSON，目标见 converted_into",
    "pdf_renderable": "PDF 可按页渲图给前端",
    "not_converted": "尚未做文档→知识库的转化",
}


def doc(did, dtype, title, path, flows, status, note=None, placeholder=False,
        converted_into=None):
    sz = _size(path)
    if sz is None:
        NOT_FOUND.append("文档不存在：%s" % path)
    assert status in CONVERSION_STATUS, "未登记的 conversion_status: %s" % status
    if status == "parsed_into_pack":
        assert converted_into, "parsed_into_pack 必须给 converted_into：%s" % title
    d = {
        "id": did, "type": dtype, "title": title, "path": path,
        "size_bytes": sz, "exists": sz is not None,
        "used_in_flows": flows,
        "conversion_status": status,
        "conversion_status_label": CONVERSION_STATUS[status],
        "converted_into": list(converted_into) if converted_into else [],
    }
    if note:
        d["note"] = note
    d["_source"] = src(path)
    if placeholder:
        d["_placeholder"] = True
    return d


def gen_documents():
    items = []
    n = [0]

    def nid(pfx):
        n[0] += 1
        return "%s-%03d" % (pfx, n[0])

    # 8 份调试经验手册（目录里共 14 个主题，其中 8 份是 PDF/DOCX 手册类）
    manuals = [
        ("FU-AM-FOC方案调试手册-.pdf", "FU-AM-FOC 方案调试手册"),
        ("SMO和PLL估算器.pdf", "SMO 和 PLL 估算器"),
        ("有感无感顺逆风启动培训.pdf", "有感无感顺逆风启动培训"),
        ("散热风扇单霍尔方案应用手册.pdf", "散热风扇单霍尔方案应用手册"),
        ("FOC执行逻辑.pdf", "FOC 执行逻辑"),
        ("AO估算器.pdf", "AO 估算器"),
        ("OMEGA启动执行逻辑.pdf", "OMEGA 启动执行逻辑"),
        ("8080_bug修改原因汇总_20250414.docx", "8080 bug 修改原因汇总（2025-04-14）"),
    ]
    for fn, title in manuals:
        p = os.path.join(EXP_DOC_DIR, fn)
        md = os.path.splitext(p)[0] + ".md"
        has_md = os.path.exists(md)
        items.append(doc(nid("DOC-MAN"), "调试手册", title, p,
                         ["F1 知识库管理", "F5 调优确认及运行"],
                         "markdown_extracted" if has_md else "not_converted",
                         note=("同目录已有 Markdown 抽取版：%s" % md) if has_md
                              else "同目录无 Markdown 抽取版"))

    # 同目录另外几份（培训 PPTX 与考题），单列
    for fn, title, dtype in [
        ("1-SVPWM原理.pptx", "SVPWM 原理（培训 PPT）", "培训材料"),
        ("2-矢量控制原理.pptx", "矢量控制原理（培训 PPT）", "培训材料"),
        ("8.9-【FOC控制理论介绍】-Jamie.pptx", "FOC 控制理论介绍（Jamie，培训 PPT）", "培训材料"),
        ("SMO角度估算的原理介绍和部分寄存器说明.docx",
         "SMO 角度估算的原理介绍和部分寄存器说明", "原理说明"),
        ("运行逻辑.docx", "运行逻辑", "原理说明"),
        ("考试题.docx", "考试题", "培训材料"),
    ]:
        p = os.path.join(EXP_DOC_DIR, fn)
        items.append(doc(nid("DOC-TRN"), dtype, title, p,
                         ["F1 知识库管理"], "markdown_extracted"))

    # 数据手册
    items.append(doc(nid("DOC-DS"), "芯片数据手册",
                     "MCU-DS-14 FU6832 数据手册 V2.1（2023-06-21），峰岹科技三相电机控制 MCU",
                     DATASHEET, ["F1 知识库管理", "F2 初始化配置"],
                     "not_converted",
                     note="296 页；电气特性在 PDF 第 56 页起（绝对最大额定值 表5-1、全局电气特性 表5-2）"))

    # 3 套原理图
    for pdf, schdoc, title in [
        (HW_STD_PDF, os.path.join(CF_ROOT, "Hardware/標準方案/FU6832N-Diode-VSP-V1.0.SchDoc"),
         "标准方案原理图 FU6832N-Diode-VSP-V1.0"),
        (HW_VSP_PDF, os.path.join(CF_ROOT, "Hardware/VSP調速方案/FU6832N-Diode-VSP-V2.0.SchDoc"),
         "VSP 调速方案原理图 FU6832N-Diode-VSP-V2.0"),
        (HW_NODIODE_PDF, os.path.join(CF_ROOT, "Hardware/無二極體方案/FU6832N-nonDiode-V1.4.SchDoc"),
         "无二极体方案原理图 FU6832N-nonDiode-V1.4"),
    ]:
        d = doc(nid("DOC-SCH"), "原理图", title, pdf,
                ["F1 知识库管理", "F2 初始化配置"], "pdf_renderable")
        d["altium_schdoc_path"] = schdoc
        d["altium_schdoc_size_bytes"] = _size(schdoc)
        d["note"] = ("PDF 可直接用；同目录 .SchDoc 为 Altium 原生格式，需 Altium 才能开，"
                     "仓内无网表解析器")
        items.append(d)

    # 源码工程
    items.append(doc(nid("DOC-SRC"), "产品驱动程序",
                     "Customer.h 参数配置文件（FU6832_CONFIGURATION，202 条 #define）",
                     CUSTOMER_H, ["F2 初始化配置", "F5 调优确认及运行"],
                     "parsed_into_pack",
                     converted_into=["product-attributes.json", "control-parameters.json"]))
    items.append(doc(nid("DOC-SRC"), "产品驱动程序",
                     "Protect.h 保护参数配置文件",
                     PROTECT_H, ["F2 初始化配置", "F4 启动测试及结果分析"],
                     "parsed_into_pack", converted_into=["safety-interlocks.json"]))
    items.append(doc(nid("DOC-SRC"), "产品驱动程序",
                     "Motor_Protection.h 故障位定义（FAULT_* 位图）",
                     MOTOR_PROT_H, ["F4 启动测试及结果分析"],
                     "parsed_into_pack",
                     converted_into=["safety-interlocks.json#fault_bitmap"]))

    # 报告模板与案例表
    items.append(doc(nid("DOC-TPL"), "报告模板",
                     "Fortior Motor Checklist 公用模板 7（.xlsm，含 VBA 宏）",
                     TEMPLATE_XLSM, ["F6 测试报告及产出"], "parsed_into_pack",
                     converted_into=["report-template.json"]))
    items.append(doc(nid("DOC-TPL"), "报告样例",
                     "report.xlsm 已填充报告样例（2026-06-22 批次）",
                     REPORT_XLSM, ["F6 测试报告及产出"], "parsed_into_pack",
                     converted_into=["report-template.json"]))
    items.append(doc(nid("DOC-CASE"), "案例表",
                     "散热风扇训练知识库（2026-08-12 版，xlsx）",
                     CASE_XLSX, ["F1 知识库管理", "F5 调优确认及运行"], "not_converted",
                     note="14.6 MB；同目录另有 2026-08-04 与一份带 (1) 后缀的早期版本"))

    # 25 份规程 + 5 份纪律
    skill_dir = os.path.join(AITIOR, "dc-skills")
    rules_dir = os.path.join(AITIOR, "dc-rules")
    SKILL_FLOW = {
        "requirement-intake": "F3 测试需求确认",
        "vacuum-customer-h": "F2 初始化配置",
        "hw-selfcheck-vbus": "F4 启动测试及结果分析",
        "hw-selfcheck-ipm": "F4 启动测试及结果分析",
        "board-verify": "F4 启动测试及结果分析",
        "sample-verify": "F4 启动测试及结果分析",
        "tune-startup": "F5 调优确认及运行",
        "tune-runtime": "F5 调优确认及运行",
        "auto-startup-tune": "F5 调优确认及运行",
        "startstop-with-scope": "F4 启动测试及结果分析",
        "tailwind-restart-test": "F4 启动测试及结果分析",
        "tailwind-pi-tune": "F5 调优确认及运行",
        "run-current-pi-tune": "F5 调优确认及运行",
        "run-outer-pi-tune": "F5 调优确认及运行",
        "run-weak-mag-tune": "F5 调优确认及运行",
        "run-carrier-tune": "F5 调优确认及运行",
        "run-stability-sweep": "F4 启动测试及结果分析",
        "protect-verify-ovp": "F4 启动测试及结果分析",
        "protect-verify-uvp": "F4 启动测试及结果分析",
        "protect-verify-lvw": "F4 启动测试及结果分析",
        "protect-verify-overspeed": "F4 启动测试及结果分析",
        "protect-verify-start-fail": "F4 启动测试及结果分析",
        "pwm-speed-config": "F2 初始化配置",
        "fg-output-config": "F2 初始化配置",
        "coolingfan-openloop-debug": "F4 启动测试及结果分析",
    }
    if os.path.isdir(skill_dir):
        for name in sorted(os.listdir(skill_dir)):
            p = os.path.join(skill_dir, name, "SKILL.md")
            desc = ""
            if os.path.exists(p):
                for ln in open(p, encoding="utf-8", errors="replace"):
                    if ln.startswith("description:"):
                        desc = ln[len("description:"):].strip()
                        break
            d = doc(nid("DOC-SKILL"), "调试规程（dc-skills）", name, p,
                    ["F1 知识库管理", SKILL_FLOW.get(name, "F4 启动测试及结果分析")],
                    "not_converted")
            d["description"] = desc[:400]
            d["applies_to_cooling_fan"] = (name == "coolingfan-openloop-debug")
            d["source_product_line"] = ("cooling-fan"
                                        if name == "coolingfan-openloop-debug" else "vacuum")
            d["note"] = ("唯一面向散热风扇的规程，带 8 现象分诊表、支持无示波器降级"
                         if name == "coolingfan-openloop-debug"
                         else "面向吸尘器（vacuum）产品线，迁移到散热风扇需重新核对宏名与阈值")
            items.append(d)
    else:
        NOT_FOUND.append("dc-skills 目录不可达：%s" % skill_dir)

    # M5：5 份 dc-rules 逐份判定是否适用于散热风扇。判据是纪律正文本身指向哪条产品线，
    # 不是文件名——vacuum-flow-discipline 标题即「吸尘器调试通用铁律」，
    # scene-requirement 正文点名要调 vacuum-customer-h skill，这两份是吸尘器线。
    RULE_APPLIES = {
        "protect-config-check": (
            True, "generic",
            "正文明写「按语义识别，宏名可能因工程而异」，未绑定产品线；"
            "散热风扇工程照此检查保护使能宏即可，但工具链仍是吸尘器线的 keil-c51-tuning MCP"),
        "scene-hw-selfcheck": (
            True, "generic",
            "只做 MCU 连接、母线采样与三相输出自检，判据口径与产品线无关；"
            "它转调的 hw-selfcheck-vbus / hw-selfcheck-ipm 两份规程同样未绑定产品线"),
        "scene-protect-verify": (
            True, "generic",
            "只规定 protect-verify-* 规程的调用时机与回写格式，与产品线无关；"
            "但它列的 LVW / 超速两项在本散热风扇工程无对应宏与 fault 位，"
            "见 test-requirements.json 的 TR-PROT-03 / TR-PROT-05"),
        "scene-requirement": (
            False, "vacuum",
            "正文点名「改写 Customer.h 时先调 vacuum-customer-h skill」，"
            "该 skill 的宏名清单是吸尘器线的，迁到散热风扇要重新核对宏名"),
        "vacuum-flow-discipline": (
            False, "vacuum",
            "标题即「吸尘器调试通用铁律」，全文 10 条铁律面向吸尘器调优 / 测试场景；"
            "safety-interlocks.json 的 SI-PROC-01~04 四条联锁就是从这份摘的，"
            "已在那四条上标 source_product_line: vacuum"),
    }
    if os.path.isdir(rules_dir):
        for fn in sorted(os.listdir(rules_dir)):
            p = os.path.join(rules_dir, fn)
            stem = os.path.splitext(fn)[0]
            applies, line, why = RULE_APPLIES.get(
                stem, (False, "unknown", "未登记的 dc-rules 文件，适用性未判定"))
            d = doc(nid("DOC-RULE"), "调试纪律（dc-rules）", stem, p,
                    ["F1 知识库管理", "F4 启动测试及结果分析"], "not_converted")
            d["applies_to_cooling_fan"] = applies
            d["source_product_line"] = line
            d["note"] = why
            items.append(d)
    else:
        NOT_FOUND.append("dc-rules 目录不可达：%s" % rules_dir)

    # 我方产出的分析报告与数据包说明
    for p, title, flows in [
        (PREALIGN_REPORT, "分析报告：预定位太弱判定的真实台架数据验证（2026-08-12）",
         ["F1 知识库管理", "F4 启动测试及结果分析"]),
        (os.path.join(PKG98, "README.md"), "98 次启动故障实验数据包 README", ["F1 知识库管理"]),
        (os.path.join(PKG98, "README-我方元数据与分析说明.md"),
         "98 次启动故障实验数据包 · 我方元数据与分析说明", ["F1 知识库管理"]),
        (WRITEFILE_README, "writeFile_rust README（报告自动填充工具说明）",
         ["F6 测试报告及产出"]),
        (DOC_A, "调研 A：Debug Copilot 场景、两个辨识、输入文件、知识库取证",
         ["F1 知识库管理"]),
        (DOC_B, "调研 B：本地可用文件资产盘点", ["F1 知识库管理"]),
        (DOC_NEED, "用户需求原话（2026-09-19）", ["F1 知识库管理"]),
    ]:
        items.append(doc(nid("DOC-OWN"), "我方文档", title, p, flows, "markdown_native"))

    by_type = {}
    for it in items:
        by_type[it["type"]] = by_type.get(it["type"], 0) + 1
    obj = {
        "schema": "documents/v1",
        "scene_id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "belongs_to_flow": "F1 知识库管理（文档性质那一类：分类、呈现、增删改查、转化）",
        "total": len(items),
        "count_by_type": by_type,
        "conversion_status_legend": CONVERSION_STATUS,
        "conversion_status_note": "conversion_status 是固定枚举（5 个取值），"
                                  "中文说明在 conversion_status_label，"
                                  "转化目标在 converted_into 数组（只有 parsed_into_pack 非空）。"
                                  "converted_into 里的 a.json#b 表示落到 a.json 的 b 字段。",
        "documents": items,
    }
    return dump("documents.json", obj)


# --------------------------------------------------------- 10. report-template
def gen_report_template():
    import openpyxl
    if not os.path.exists(REPORT_XLSM):
        NOT_FOUND.append("报告样例不存在：%s" % REPORT_XLSM)
        return None
    wb = openpyxl.load_workbook(REPORT_XLSM, data_only=True)
    sheets = []
    for name in wb.sheetnames:
        ws = wb[name]
        sheets.append({
            "name": name,
            "max_row": ws.max_row,
            "max_column": ws.max_column,
            "image_count": len(getattr(ws, "_images", [])),
            "_source": src(REPORT_XLSM, "sheet「%s」" % name),
        })

    # H4：原先 cell 指的是标签格（B4 里写的是「客戶名稱」四个字），不是取值格。
    # openpyxl 实测两份 xlsm 的 測試程式規格表 布局完全一致：
    #   B 列、D 列是标签，底色灰 FFE7E6E6；C 列、E 列是取值格，底色黄 FFFFF2CC。
    # 因此标签 Bn 的取值格是 Cn，标签 Dn 的取值格是 En。
    ws_spec = wb["測試程式規格表"]

    def F(key, name, ftype, label_cell, value_cell, flow, note=None, placeholder=False):
        label_text = ws_spec[label_cell].value
        filled = ws_spec[value_cell].value
        d = {"key": key, "name": name, "type": ftype,
             "label_cell": label_cell, "value_cell": value_cell,
             "label_text_in_template": label_text,
             "filled_in_sample": filled not in (None, ""),
             "from_flow": flow,
             "_source": src(REPORT_XLSM,
                            "sheet 測試程式規格表 标签格 %s（实测内容 %r）→ 取值格 %s"
                            % (label_cell, label_text, value_cell))}
        if note:
            d["note"] = note
        if placeholder:
            d["_placeholder"] = True
        return d

    header_fields = [
        F("customer_name", "客戶名稱", "text", "B4", "C4", "F6 测试报告及产出"),
        F("model", "Model 机型", "text", "D4", "E4", "F2 初始化配置"),
        F("customer_engineer", "客戶工程師", "text", "B5", "C5", "F6 测试报告及产出"),
        F("email", "Email", "text", "D5", "E5", "F6 测试报告及产出"),
        F("project_name", "項目名稱", "text", "B6", "C6", "F2 初始化配置"),
        F("phone", "聯繫電話", "text", "D6", "E6", "F6 测试报告及产出"),
        F("firmware_version", "韌體版本", "text", "B7", "C7", "F2 初始化配置",
          note="对应 Customer.h 的 PROJECT_VERSION 宏（当前值 24805_Beta_STDCODE）"),
        F("inlet_start_addr", "Inlet 起始位址", "text", "D7", "E7", "F2 初始化配置"),
        F("bootloader", "Bootloader", "text", "B8", "C8", "F2 初始化配置"),
        F("outlet_start_addr", "Outlet 起始位址", "text", "D8", "E8", "F2 初始化配置"),
    ]
    header_filled_count = sum(1 for f in header_fields if f["filled_in_sample"])

    spec_sections = [
        {"section": "一、產品電機參數 Motor Parameters", "rows": "A11:E15",
         "fields": ["相電阻 Rs (Ω)", "相電感 Ld, Lq", "極對數 (對)", "感應電動勢常數 Ke"],
         "from_flow": "F2 初始化配置", "maps_to": "product-attributes.json"},
        {"section": "二、控制設計 Control Design", "rows": "A16:E26",
         "fields": ["有無 HALL 感測器", "HALL 個數", "HALL 與 B-EMF 關係", "HALL 類型",
                    "控制方式（方波120°/150°/正弦波/FOC）", "啟動方式（Omega/強拖/混合）",
                    "正/反轉（反轉等待時間）", "控制環方式（Open Loop/Close Loop）",
                    "電路採樣電阻大小 (mΩ)", "電路採樣運放電路倍數"],
         "from_flow": "F2 初始化配置", "maps_to": "product-attributes.json / control-parameters.json"},
        {"section": "三、轉速 Speed", "rows": "A27:E33",
         "fields": ["風扇轉速規格需求（Inlet/Outlet）", "最大轉速範圍 ±5%", "最低轉速範圍 ±5%",
                    "啟動到全速穩定時間 < 10 s", "高轉到低轉 < 10 s 且不停轉", "低轉到高轉 < 10 s"],
         "from_flow": "F3 测试需求确认", "maps_to": "test-requirements.json"},
        {"section": "四、電壓 Voltage", "rows": "A34:E40",
         "fields": ["正常啟動電壓值", "最低啟動電壓值", "最高啟動電壓值",
                    "額定/最低/最高運行電壓的 ON/OFF 測試次數要求"],
         "from_flow": "F3 测试需求确认", "maps_to": "test-requirements.json"},
        {"section": "五、調速方式 Speed Control（PWM 或 VSP 择一）", "rows": "A41:E61",
         "fields": ["PWM 訊號規格 (kHz / Vpp)", "調速 PWM 曲線各點轉速",
                    "最大/最小轉速對應 PWM 百分比", "風扇啟動/關閉 PWM 百分比",
                    "程式 PWM 讀取參數與實際輸入落差", "程式頻寬限制",
                    "99.99%/0.01% 上電功能", "VSP 電壓範圍", "VSP 輸入阻抗",
                    "VSP ADC 取樣精度", "VSP 上下邊界電壓功能"],
         "from_flow": "F3 测试需求确认 / F4 启动测试及结果分析",
         "maps_to": "control-parameters.json / test-requirements.json"},
        {"section": "六、FG / RD 訊號（择一）", "rows": "A62:E74",
         "fields": ["FG 訊號規格（電氣 Level、脈波數）", "FG 與實際轉速誤差 < 50 RPM",
                    "FG 停轉時輸出狀態", "上電到 FG 輸出時間",
                    "RD 訊號類型與翻轉等待時間", "Recovery 訊號類型與翻轉等待時間",
                    "RD/Recovery 邏輯配對"],
         "from_flow": "F3 测试需求确认", "maps_to": "test-requirements.json"},
        {"section": "七、保護 Protection", "rows": "A75:E83",
         "fields": ["啟動保護（秒內重啟）", "堵轉保護（秒內重啟）", "過壓保護 (V)",
                    "欠壓保護 (V)", "過壓 Recover (V)", "欠壓 Recover (V)",
                    "斷電偵測功能", "過流保護（硬過流/軟過流）"],
         "from_flow": "F4 启动测试及结果分析", "maps_to": "safety-interlocks.json"},
        {"section": "八、順逆風功能 Windmilling", "rows": "A84:E91",
         "fields": ["順風最高轉速", "逆風最高轉速", "順風其他轉速確認", "逆風其他轉速確認",
                    "順風相電壓電流過衝", "逆風相電壓電流過衝", "順逆風強制退出確認"],
         "from_flow": "F4 启动测试及结果分析", "maps_to": "test-requirements.json"},
        {"section": "九、其他必須測試功能", "rows": "A92:E96",
         "fields": ["啟動到穩態母線 Peak 電流 ≤ 穩態電流 1.1 倍",
                    "每 10% PWM 轉速跳變時間", "PWM 100%→最低運行 Duty 不停轉",
                    "速度外環最小值非負，最大工作電壓下最低速運行 5 分鐘"],
         "from_flow": "F4 启动测试及结果分析", "maps_to": "test-requirements.json"},
        {"section": "十、其他特殊需求（參考「特殊功能測試項庫」分頁）", "rows": "A97:E116",
         "fields": ["假轉速 (FG 虛擬輸出) 及對應曲線", "預定位時 PWM/VSP 為 0", "煞車功能等"],
         "from_flow": "F3 测试需求确认", "maps_to": "control-parameters.json"},
    ]

    # H3：E/F/I 三列的 CSV 单位与 Excel 表头单位差 1000 倍。
    #   CSV（writeFile_rust/README.md:143-152）：Max Current (A)、Steady Current (A)、Accel Time (ms)
    #   Excel 表头（report.xlsm 的 E8/F8/I8）：Max 電流 (mA)、穩態電流 (mA)、加速時間 (s)
    # scale_factor 是「CSV 数值 × scale_factor = 该写进 Excel 的数值」。
    # auto_filled_by_tool：excel_writer.rs:160-163 的列映射注释与其后五次 set_value_number 实测，
    # 工具只写 C / E / F / H / I 五列；D、G 是表内公式列；A、B、J 工具不写。
    def PC(col, key, name, csv_index, csv_name, auto, csv_unit=None, sheet_unit=None,
           scale=1.0, note=None):
        d = {"col": col, "cell": "%s8" % col, "key": key, "name": name,
             "csv_index": csv_index, "csv_name": csv_name,
             "csv_unit": csv_unit, "sheet_unit": sheet_unit,
             "scale_factor": scale, "auto_filled_by_tool": auto}
        if note:
            d["note"] = note
        return d

    UNIT_GAP = ("上游矛盾：writeFile_rust 把 CSV 数值原样 set_value_number 进单元格，"
                "没有做这一步换算，填出来的数比表头单位小 / 大 1000 倍")
    perf_columns = [
        PC("A", "duty_or_vsp", "PWM% / VSP V", 0, "PWM%", False,
           csv_unit="%", sheet_unit="% 或 V", scale=1.0,
           note="档位列，模板里已预置 0~100 十一档，工具不写"),
        PC("B", "target_rpm", "Target RPM", 1, "Target RPM", False,
           csv_unit="RPM", sheet_unit="RPM", scale=1.0,
           note="CSV 里有这一列，但 excel_writer.rs 不写 B 列，需人工或另行填入"),
        PC("C", "real_rpm", "Real RPM", 2, "Real RPM", True,
           csv_unit="RPM", sheet_unit="RPM", scale=1.0),
        PC("D", "rpm_error_pct", "RPM 誤差 (%)", None, None, False,
           csv_unit=None, sheet_unit="%", scale=1.0, note="表内公式列，工具不写"),
        PC("E", "max_current_ma", "Max 電流 (mA)", 3, "Max Current", True,
           csv_unit="A", sheet_unit="mA", scale=1000.0, note=UNIT_GAP),
        PC("F", "steady_current_ma", "穩態電流 (mA)", 4, "Steady Current", True,
           csv_unit="A", sheet_unit="mA", scale=1000.0, note=UNIT_GAP),
        PC("G", "overshoot_pct", "過衝 (%)", 5, "Overshoot%", False,
           csv_unit="%", sheet_unit="%", scale=1.0,
           note="表内公式列，工具不写；CSV 第 5 列虽有过冲数值也不会被写入"),
        PC("H", "steady_limit_ma", "穩態上限 (mA)", 6, "Steady Limit", True,
           csv_unit="A", sheet_unit="mA", scale=1000.0, note=UNIT_GAP),
        PC("I", "accel_time_s", "加速時間 (s)", 7, "Accel Time", True,
           csv_unit="ms", sheet_unit="s", scale=0.001, note=UNIT_GAP),
        PC("J", "fake_fg_target_rpm", "虛擬 FG 目標（假轉速設計 RPM）", None, None, False,
           csv_unit=None, sheet_unit="RPM", scale=1.0, note="人工填写，工具不写"),
    ]

    obj = {
        "schema": "report-template/v1",
        "scene_id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "belongs_to_flow": "F6 测试报告及产出（模板确认、信息确认）",
        "template_file": TEMPLATE_XLSM,
        "filled_sample_file": REPORT_XLSM,
        "filler_tool": {
            "name": "writeFile_rust（Fortior Motor Checklist 自动化填充工具）",
            "path": os.path.dirname(WRITEFILE_README),
            "purpose": "用 Rust 替代 VBA 宏，把示波器截图按文件名规则插进模板对应单元格，"
                       "并从 CSV 读转速数据写进 PWM·VSP 性能测试表，同时保留模板里的 VBA 宏",
            "cli": "write-file-rust --template <xlsm> --images <dir> [--csv <csv>] --output <xlsm>",
            "_source": src(WRITEFILE_README, "功能特性 / CLI 参数 / 图片文件名规则 / CSV 格式说明"),
        },
        "sheets": sheets,
        "header_fields": header_fields,
        "header_fields_note": ("label_cell 是模板里写标签文字的格（B/D 列，灰底 FFE7E6E6），"
                               "value_cell 才是该填内容的格（C/E 列，黄底 FFFFF2CC）。"
                               "旧版本的 cell 字段指的是 label_cell，会让前端把值写进标签格，已拆开。"
                               "filled_in_sample 是 openpyxl 实测已填充样例 report.xlsm 的取值格是否有内容。"),
        "header_filled_count": header_filled_count,
        "spec_sections": spec_sections,
        "performance_table": {
            "sheet": "PWM·VSP 性能測試",
            # M3：A3 单元格原文是三条并列的通过条件，此前只收了第一条
            "pass_condition": [
                {"key": "rpm_error", "text": "RPM 誤差 ≤ ±5%",
                 "maps_to": "test-requirements.json#TR-PWM-01.threshold.rpm_error_pct_max"},
                {"key": "overshoot", "text": "過衝 (%) ≤ 10%",
                 "maps_to": "test-requirements.json#TR-PWM-01.threshold.overshoot_pct_max"},
                {"key": "steady_current", "text": "穩態電流 ≤ 穩態上限（F 列 ≤ H 列，逐档比较）",
                 "maps_to": "test-requirements.json#TR-PWM-01.criterion "
                            "的 steady_current_over_limit_count === 0"},
            ],
            "pass_condition_source_text": "※ 通過條件：RPM 誤差 ≤ ±5%  |  過衝 (%) ≤ 10%  |  穩態電流 ≤ 穩態上限",
            "unit_conversion_note": (
                "E / F / H / I 四列的 CSV 单位与 Excel 表头单位不一致："
                "电流列 CSV 给安培、表头写毫安（×1000），加速时间 CSV 给毫秒、表头写秒（÷1000）。"
                "writeFile_rust 把 CSV 数值原样写入，没有做这一步换算——"
                "这是上游工具与模板之间的矛盾，本包如实登记 csv_unit / sheet_unit / scale_factor，"
                "不替上游决定谁对。README 第七节已把它列为上游缺口。"),
            "auto_fill_note": (
                "auto_filled_by_tool 为 true 的只有 C / E / F / H / I 五列，"
                "来自 excel_writer.rs:160-163 的列映射注释与其后五次 set_value_number；"
                "D、G 是表内公式列；A、B、J 工具不写。"
                "另有 K 列「虛擬 FG 讀取（FG 實測 RPM）」存在于 report.xlsm 的 K8，"
                "既不在 writeFile_rust 的写入集合里，也不在本 columns 数组里，属未登记列。"),
            "duty_rows": {"start_row": 9, "step_pct": 10,
                          "points": [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]},
            "regions": ["Inlet", "Outlet"],
            "columns": perf_columns,
            "_source": [src(REPORT_XLSM, "sheet PWM·VSP 性能測試 A3 通過條件、A8:J8 表头、A9 起档位行"),
                        src(WRITEFILE_README, "「CSV 格式说明 · 列定义」8 列表（README.md:143-152）"),
                        src(os.path.join(os.path.dirname(WRITEFILE_README),
                                         "src/excel_writer.rs"),
                            "excel_writer.rs:160-163 列映射注释与其后的 set_value_number 调用，"
                            "实测只写 C/E/F/H/I 五列（第 170 行起）")],
        },
        "waveform_image_slots": {
            "sheets_by_voltage": {"LV": "LV 測試波型", "SV": "SV 測試波型", "HV": "HV 測試波型"},
            "filename_rules": [
                {"pattern": "Duty_{PWM}_Start_{Voltage}.{ext}", "meaning": "静止启动测试",
                 "example": "Duty_50_Start_SV.png"},
                {"pattern": "Duty_{From}t{To}_{Voltage}.{ext}",
                 "meaning": "加速/减速测试（To > From 为加速，To < From 为减速）",
                 "example": "Duty_0t10_SV.png"},
                {"pattern": "Lock_{Voltage}.{ext}", "meaning": "堵转测试"},
                {"pattern": "HSPtLSP_{Voltage}.{ext}", "meaning": "高速切低速（100% 降至 0%）"},
                {"pattern": "HSP_BLow_{Voltage}.{ext}", "meaning": "高速制动（快速关开）"},
                {"pattern": "LSPtHSP_{Voltage}.{ext}", "meaning": "低速切高速（0% 升至 100%）"},
            ],
            "supported_formats": ["BMP", "PNG", "JPG", "JPEG"],
            "counted_images": {s["name"]: s["image_count"] for s in sheets
                               if s["image_count"]},
            "_source": [src(WRITEFILE_README, "「图片文件名规则」与「电压等级」两节"),
                        src(REPORT_XLSM, "各波型分页的内嵌图片计数（openpyxl ws._images）")],
        },
        "other_sheets": [
            {"name": "HP FCOL 波型", "from_flow": "F4 启动测试及结果分析",
             "note": "HP-FCOL 专用功能波形，对应 Customer.h 的 HPFCOL_* 宏族（当前 HPFCOL_ENABLED=0）"},
            {"name": "Dell 電流波型", "from_flow": "F4 启动测试及结果分析",
             "note": "Dell-CoastMode 专用波形，对应 DELL_COASTMODE_* 宏族（当前禁用）"},
            {"name": "ON-OFF LV / ON-OFF SV / ON-OFF HV", "from_flow": "F4 启动测试及结果分析",
             "note": "三档电压的 ON/OFF 次数回归结果，次数要求在模板里仍是待确认项"},
            {"name": "特殊功能測試項庫", "from_flow": "F3 测试需求确认",
             "note": "第十节「其他特殊需求」的选项库"},
        ],
    }
    return dump("report-template.json", obj)
