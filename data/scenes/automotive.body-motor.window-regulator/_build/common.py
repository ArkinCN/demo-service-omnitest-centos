# -*- coding: utf-8 -*-
"""场景包生成脚本共用常量与工具。只读源材料，不写回源材料。

场景二：汽车 / 车身电机 / 电动玻璃升降器（含防夹）。
与场景一（motor.cooling-fan.fortior-fu6832）同构，字段口径完全照抄。
"""
import json
import os

# ---- 源材料根路径（全部绝对路径，便于 _source 可独立定位）----
REPO = "[源] 2_Projects/峰岹"

# 素材综述文档（本包绝大多数条目的一级来源，_source 指其行号）
DOC_B = os.path.join(
    REPO,
    "峰岹agent/09-实验室demo线/20260919-通用Agent测试系统v2.0/_调研/B-汽车场景测试案例素材.md")
DOC_NEED = os.path.join(
    REPO, "峰岹agent/09-实验室demo线/20260919-通用Agent测试系统v2.0/00-用户需求原话-20260919.md")

# 证据原件目录
EV = os.path.join(REPO, "10_外部资料/汽车场景素材-20260919")
QC626_TXT = os.path.join(EV, "qc636.txt")          # QC/T 626 征求意见稿提取文本
GB11552_TXT = os.path.join(EV, "gb11552.txt")      # GB 11552-2009 报批稿提取文本
NHTSA_PDF = os.path.join(EV, "nhtsa118-gtl-11-002.pdf")  # NHTSA FMVSS 118 合规报告全文
ISO16750_2_PDF = os.path.join(EV, "ls16750_2.pdf")
ISO16750_3_PDF = os.path.join(EV, "p167503.pdf")
ISO16750_4_PDF = os.path.join(EV, "iso16750-4.pdf")
ISO16750_5_PDF = os.path.join(EV, "iso16750-5.pdf")
ISO16750_1_PDF = os.path.join(EV, "p167501.pdf")
CISPR25_PDF = os.path.join(EV, "cispr25p.pdf")
LV124_PDF = os.path.join(EV, "lv124.pdf")
LV148_PDF = os.path.join(EV, "lv148.pdf")
VW80000_PDF = os.path.join(EV, "vw80000.pdf")
GMW3172_PDF = os.path.join(EV, "gmwhb.pdf")
BMW_GS_PDF = os.path.join(EV, "bmw.pdf")
Q100_PDF = os.path.join(EV, "q100.pdf")
Q101_PDF = os.path.join(EV, "q101.pdf")
Q102_PDF = os.path.join(EV, "q102.pdf")
Q104_PDF = os.path.join(EV, "q104.pdf")
Q200_PDF = os.path.join(EV, "q200.pdf")
ISO20653_PDF = os.path.join(EV, "p20653.pdf")
ISO7637_2_PDF = os.path.join(EV, "p76372.pdf")
ISO10605_PDF = os.path.join(EV, "p10605.pdf")
ISO11452_1_PDF = os.path.join(EV, "p114522.pdf")
IEC60034_1_PDF = os.path.join(EV, "iec60034_1.pdf")
IEC60034_5_PDF = os.path.join(EV, "iec60034_5.pdf")
CISPR12_PDF = os.path.join(EV, "cispr12.pdf")
ISO19453_PDF = os.path.join(EV, "iso19453.pdf")

# 场景一（对照基准，README 第八节引用）
SCENE1 = os.path.join(
    REPO, "40_工程/agent-test-web-data/scenes/motor.cooling-fan.fortior-fu6832")

OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- 三级分类（任务书固定）----
TAXONOMY = {
    "level1": {"key": "automotive", "name": "汽车"},
    "level2": {"key": "body-motor", "name": "车身电机"},
    "level3": {"key": "window-regulator", "name": "电动玻璃升降器（含防夹）"},
}
SCENE_ID = "automotive.body-motor.window-regulator"

# ---- 六个流程（与需求原话一一对应，两个场景共用）----
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

# ---- 征求意见稿数值的统一待核实标记（任务书硬性要求）----
DRAFT_STATUS = "待核实（QC/T 626-2019 正式版可能调整）"


def src(path, locator=None, note=None):
    """构造 _source 结构：全路径 + 行/位置 + 备注。"""
    d = {"file": path}
    if locator:
        d["locator"] = locator
    if note:
        d["note"] = note
    return d


def b(line, what):
    """指向素材综述文档 B 的某一行。line 可以是 int 或 'a-b' 区间字符串。"""
    return src(DOC_B, "第 %s 行：%s" % (line, what))


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


def count_status(obj):
    """递归统计带 _status 的对象数（即标了待核实的条目）。"""
    n = 0
    if isinstance(obj, dict):
        if obj.get("_status"):
            n += 1
        for v in obj.values():
            n += count_status(v)
    elif isinstance(obj, list):
        for v in obj:
            n += count_status(v)
    return n
