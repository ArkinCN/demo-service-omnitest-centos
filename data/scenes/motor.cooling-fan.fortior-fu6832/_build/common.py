# -*- coding: utf-8 -*-
"""场景包生成脚本共用常量与工具。只读源材料，不写回源材料。"""
import json
import os

# ---- 源材料根路径（全部绝对路径，便于 _source 可独立定位）----
REPO = "[源] 2_Projects/峰岹"
AITIOR = "[源] resources/data"

CF_ROOT = os.path.join(
    REPO, "10_外部资料/客户材料/AI_散热风扇开发资料/AI_散热风扇开发资料/CoolingFan_Program")
CUSTOMER_H = os.path.join(CF_ROOT, "Software/User/include/Customer.h")
PROTECT_H = os.path.join(CF_ROOT, "Software/User/include/Protect.h")
MOTOR_PROT_H = os.path.join(CF_ROOT, "Software/User/include/Motor_Protection.h")
DATASHEET = os.path.join(CF_ROOT, "Document/MCU-DS-14_FU6832_V2.1_20230621.pdf")
HW_STD_PDF = os.path.join(CF_ROOT, "Hardware/標準方案/FU6832N-Diode-VSP-V1.0.pdf")
HW_VSP_PDF = os.path.join(CF_ROOT, "Hardware/VSP調速方案/FU6832N-Diode-VSP-V2.0.pdf")
HW_NODIODE_PDF = os.path.join(CF_ROOT, "Hardware/無二極體方案/FU6832N-nonDiode-V1.4.pdf")
EXP_DOC_DIR = os.path.join(
    REPO, "10_外部资料/客户材料/AI_散热风扇开发资料/AI_散热风扇开发资料/调试经验文档")

WFW_MAIN = os.path.join(REPO, "archive-POC/40_工程/ClientSoftware/WORKINGflow/WORKINGflow")
WFW_SUB = os.path.join(REPO, "archive-POC/40_工程/ClientSoftware/子流程/子流程")

DATA_0701 = os.path.join(REPO, "archive-POC/40_工程/测试数据_20260701/faithful_norm1200.csv")
DATA_0627 = os.path.join(REPO, "archive-POC/40_工程/测试数据_20260627/fullrun_v2b_20260627.csv")
REPORT_XLSM = os.path.join(REPO, "archive-POC/40_工程/测试数据_20260622/report.xlsm")
TEMPLATE_XLSM = os.path.join(
    REPO, "archive-POC/40_工程/ClientSoftware/Fortior_Motor_Checklist_公用模板_7(1).xlsm")
WRITEFILE_README = os.path.join(REPO, "平台代码/writeFile_rust/README.md")
SPEEDTEST_WFW = os.path.join(REPO,
    "archive-POC/40_工程/ClientSoftware/WORKINGflow/WORKINGflow/SPEEDTEST.wfw")

PKG98 = os.path.join(REPO, "峰岹agent/数据/20260811_启动故障98次实验与30例对照数据包")
ATTEMPTS = os.path.join(PKG98, "01_实验原始数据/batch_20260811_113726_010/attempts")
PREALIGN_REPORT = os.path.join(PKG98, "分析报告-预定位太弱判定-20260812.md")
CAPTURE_INFO_SAMPLE = os.path.join(ATTEMPTS, "TRY-0010/capture/采集信息.json")

CASE_XLSX = os.path.join(REPO, "10_外部资料/典型案例/1_散热风扇训练知识库-8月12日.xlsx")

DOC_A = os.path.join(
    REPO, "峰岹agent/09-实验室demo线/20260917-产品故事与分工v1.0/_调研/A-DebugCopilot场景与知识库取证.md")
DOC_B = os.path.join(
    REPO, "峰岹agent/09-实验室demo线/20260917-产品故事与分工v1.0/_调研/B-本地文件资产盘点.md")
DOC_NEED = os.path.join(
    REPO, "峰岹agent/09-实验室demo线/20260919-通用Agent测试系统v2.0/00-用户需求原话-20260919.md")
BENCH_MEMO = "[源] memory/fortior-test-bench-hardware.md"

OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- 三级分类（任务书固定）----
TAXONOMY = {
    "level1": {"key": "motor", "name": "电机"},
    "level2": {"key": "cooling-fan", "name": "散热风扇"},
    "level3": {"key": "fortior-fu6832", "name": "FU6832 散热风扇驱动板"},
}
SCENE_ID = "motor.cooling-fan.fortior-fu6832"

# ---- 六个流程（与需求原话一一对应）----
FLOWS = {
    "F1": "知识库管理",
    "F2": "初始化配置",
    "F3": "测试需求确认",
    "F4": "启动测试及结果分析",
    "F5": "调优确认及运行",
    "F6": "测试报告及产出",
}

GENERATED_BY = "_build/build_scene_pack.py"
BUILD_DATE = "2026-09-19"


def src(path, locator=None, note=None):
    """构造 _source 结构：全路径 + 行/位置 + 备注。"""
    d = {"file": path}
    if locator:
        d["locator"] = locator
    if note:
        d["note"] = note
    return d


def dump(name, obj):
    p = os.path.join(OUT, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return p


def count_placeholders(obj):
    """递归统计带 _placeholder: true 的对象数与对象总数。"""
    total = 0
    ph = 0
    if isinstance(obj, dict):
        if "_source" in obj or "_placeholder" in obj:
            total += 1
            if obj.get("_placeholder") is True:
                ph += 1
        for v in obj.values():
            t, p = count_placeholders(v)
            total += t
            ph += p
    elif isinstance(obj, list):
        for v in obj:
            t, p = count_placeholders(v)
            total += t
            ph += p
    return total, ph
