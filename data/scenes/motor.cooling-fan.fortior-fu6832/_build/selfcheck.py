#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场景包自检：跑完 build_scene_pack.py 之后用它验收。

    python3 _build/selfcheck.py

检查项（任一 FAIL 退出码非 0）：
  C1  11 个 JSON 全部可解析
  C2  _source / _placeholder 对象数不低于基线，构建没把来源字段弄丢
  C3  test-requirements 的 criterion 语法：evaluable 为 true 的用 node 做 JS 语法检查
  C4  criterion 里每个自由标识符都在 variables 或 criterion_globals 里
  C5  variables 每个变量都能解析到目标（runtime_measures / threshold / control-parameters / fault_bitmap）
  C6  evaluable 为 true 的条目，其 threshold 型变量必须有非 null 取值
  C7  可调参数 min <= value <= max，越界须带 value_below_min
  C8  枚举型参数：min/max/step 为 null 且 options 非空；options 必须含当前 value
  C9  README 里的各项计数与实际数据一致
  C10 位运算优先级：& / | 的运算元所在括号层里不得同时出现比较运算符
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.dirname(HERE)

JSON_FILES = [
    "scene.json", "product-attributes.json", "control-parameters.json",
    "safety-interlocks.json", "test-requirements.json", "workflows.json",
    "datasets.json", "experience.json", "documents.json", "report-template.json",
    "copilot-actions.json",
]

# copilot-actions.json 的条目级对象（buttons）按契约第 3.4 节不要求带 _source，
# 它在顶层用 _derived_from 交代来源，所以 C2 的「本文件至少有一个带源对象」不适用于它。
NO_SOURCE_FILES = {"copilot-actions.json"}

# 基线：改动前 build_scene_pack.py 报的「带 _source/_placeholder 的对象」数与占位数
BASELINE_SOURCED = 331
BASELINE_PLACEHOLDER = 13

FAILS = []
NOTES = []


def fail(code, msg):
    FAILS.append("[%s] %s" % (code, msg))


def ok(code, msg):
    NOTES.append("[%s] OK  %s" % (code, msg))


def count_sourced(obj):
    total = ph = 0
    if isinstance(obj, dict):
        if "_source" in obj or "_placeholder" in obj:
            total += 1
            if obj.get("_placeholder") is True:
                ph += 1
        for v in obj.values():
            t, p = count_sourced(v)
            total += t
            ph += p
    elif isinstance(obj, list):
        for v in obj:
            t, p = count_sourced(v)
            total += t
            ph += p
    return total, ph


# ---------------------------------------------------------------- C1 可解析
DATA = {}
for name in JSON_FILES:
    path = os.path.join(OUT, name)
    if not os.path.exists(path):
        fail("C1", "文件不存在：%s" % name)
        continue
    try:
        DATA[name] = json.load(open(path, encoding="utf-8"))
    except ValueError as e:
        fail("C1", "%s 解析失败：%s" % (name, e))
if len(DATA) == len(JSON_FILES):
    ok("C1", "%d 个 JSON 全部可解析" % len(DATA))

if len(DATA) != len(JSON_FILES):
    print("\n".join(FAILS))
    sys.exit(1)

# ---------------------------------------------------------------- C2 _source 未丢
tot = ph = 0
for name, obj in DATA.items():
    t, p = count_sourced(obj)
    tot += t
    ph += p
    if t == 0 and name not in NO_SOURCE_FILES:
        fail("C2", "%s 里没有任何带 _source 的对象" % name)
if tot < BASELINE_SOURCED:
    fail("C2", "带 _source/_placeholder 的对象数 %d，低于基线 %d，来源字段有丢失"
         % (tot, BASELINE_SOURCED))
elif ph != BASELINE_PLACEHOLDER:
    fail("C2", "占位对象数 %d，基线 %d，占位口径变了但 README 第五节未同步？"
         % (ph, BASELINE_PLACEHOLDER))
else:
    ok("C2", "带源对象 %d 个（基线 %d），占位 %d 个（基线 %d）"
       % (tot, BASELINE_SOURCED, ph, BASELINE_PLACEHOLDER))

# ------------------------------------------------- C3~C6 test-requirements
TR = DATA["test-requirements.json"]
CP = DATA["control-parameters.json"]
SI = DATA["safety-interlocks.json"]
CP_KEYS = {p["key"] for p in CP["parameters"]}
BITS = set(SI["fault_bitmap"]["bits"].keys())
MEASURES = set(TR["runtime_measures"].keys())
GLOBALS_OK = set(TR["criterion_globals"])

HAVE_NODE = subprocess.call(["which", "node"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL) == 0
if not HAVE_NODE:
    fail("C3", "找不到 node，无法做 JS 语法检查")

IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
CMP_OPS = ("===", "!==", "==", "!=", "<=", ">=", "<", ">")


def bitwise_precedence_hazard(expr):
    """C10：JS 里 & 和 | 的优先级低于比较运算符。

    `a & B !== 0` 会先算 `B !== 0` 再与 a 按位与，判据静默失真且语法完全合法，
    node 检不出来。这里按括号层扫：某一层里同时出现按位运算符与比较运算符，
    就说明位运算没被括起来，判为隐患。返回出问题的层的文本列表。
    """
    layers = []

    def split(seg):
        depth = 0
        own = []
        start = None
        for i, ch in enumerate(seg):
            if ch == "(":
                if depth == 0:
                    start = i + 1
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    split(seg[start:i])
                    own.append(" ")
            elif depth == 0:
                own.append(ch)
        layers.append("".join(own))

    split(expr)
    bad = []
    for layer in layers:
        # 去掉 && 与 ||，它们是逻辑运算符不是按位运算符
        probe = layer.replace("&&", "  ").replace("||", "  ")
        has_bit = "&" in probe or "|" in probe
        if not has_bit:
            continue
        if any(op in probe for op in CMP_OPS):
            bad.append(layer.strip())
    return bad


def js_syntax_check(expr, names):
    """用 node 把表达式编成一个函数体，语法错会非 0 退出。"""
    script = ("try{new Function(%s,'return (%s);');}"
              "catch(e){console.error(e.message);process.exit(1);}"
              % (json.dumps(",".join(sorted(names))), expr.replace("\\", "\\\\")
                 .replace("'", "\\'")))
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or "").strip()


n_eval = n_noeval = 0
for req in TR["requirements"]:
    rid = req["id"]
    evaluable = req.get("evaluable")
    crit = req.get("criterion")
    variables = req.get("variables")
    thr = req.get("threshold") or {}

    if evaluable is None:
        fail("C3", "%s 缺 evaluable 字段" % rid)
        continue
    if variables is None:
        fail("C3", "%s 缺 variables 字段" % rid)
        continue
    if evaluable:
        n_eval += 1
        if not crit:
            fail("C3", "%s 标了 evaluable: true 却没有 criterion" % rid)
            continue
    else:
        n_noeval += 1
        if not req.get("not_evaluable_reason"):
            fail("C3", "%s 标了 evaluable: false 却没写 not_evaluable_reason" % rid)

    # --- C3 语法 ---
    if crit and HAVE_NODE:
        good, err = js_syntax_check(crit, variables.keys())
        if not good:
            fail("C3", "%s 的 criterion 不是合法 JS 表达式：%s" % (rid, err))

    # --- C4 自由标识符全部有交代 ---
    if crit:
        idents = set(IDENT.findall(crit))
        # 去掉属性访问的右半（Math.abs 里的 abs）
        for m in re.finditer(r"\.\s*([A-Za-z_$][A-Za-z0-9_$]*)", crit):
            idents.discard(m.group(1))
        unknown = idents - set(variables.keys()) - GLOBALS_OK
        if unknown:
            fail("C4", "%s 的 criterion 有未登记的自由标识符：%s"
                 % (rid, "、".join(sorted(unknown))))
        unused = set(variables.keys()) - idents
        if unused:
            fail("C4", "%s 的 variables 有表达式里用不到的条目：%s"
                 % (rid, "、".join(sorted(unused))))
    elif variables:
        fail("C4", "%s 的 criterion 为 null 却还留着 variables" % rid)

    # --- C10 位运算优先级 ---
    if crit:
        hazards = bitwise_precedence_hazard(crit)
        if hazards:
            fail("C10", "%s 的 criterion 位运算没加括号，& / | 与比较运算符同层："
                        "%s —— JS 里 & 优先级更低，会先算比较再按位与"
                 % (rid, " ；".join(hazards)))

    # --- C5 / C6 变量解析 ---
    for vname, v in variables.items():
        srcname = v.get("source")
        ref = v.get("ref", "")
        if srcname == "runtime.measure":
            key = ref.split("runtime.measure.", 1)[-1]
            if key not in MEASURES:
                fail("C5", "%s 的变量 %s 指向未登记的运行时测量量 %s"
                     % (rid, vname, key))
        elif srcname == "threshold":
            key = ref.split("threshold.", 1)[-1]
            if key not in thr:
                fail("C5", "%s 的变量 %s 指向不存在的 threshold.%s" % (rid, vname, key))
            elif evaluable and thr.get(key) is None:
                fail("C6", "%s 标了 evaluable: true，但它的 threshold.%s 是 null，求不出结果"
                     % (rid, key))
        elif srcname == "control-parameters":
            key = ref.split("control-parameters.", 1)[-1]
            if key not in CP_KEYS:
                fail("C5", "%s 的变量 %s 指向不存在的 control-parameters key「%s」"
                     % (rid, vname, key))
        elif srcname == "constant":
            refs = v.get("derived_from") or ([ref] if ref else [])
            if not refs:
                fail("C5", "%s 的常量 %s 既无 ref 也无 derived_from" % (rid, vname))
            for r in refs:
                hexkey = r.split("safety-interlocks.fault_bitmap.", 1)[-1]
                if hexkey not in BITS:
                    fail("C5", "%s 的常量 %s 指向 fault_bitmap 里没有的 %s"
                         % (rid, vname, hexkey))
            if v.get("derived_from"):
                want = 0
                for r in v["derived_from"]:
                    want |= int(r.rsplit(".", 1)[-1], 16)
                if want != v.get("value"):
                    fail("C5", "%s 的掩码 %s 的 value %s 与 derived_from 按位或 %s 对不上"
                         % (rid, vname, v.get("value"), want))
        else:
            fail("C5", "%s 的变量 %s 用了未知 source「%s」" % (rid, vname, srcname))

if TR.get("evaluable_count") != n_eval or TR.get("not_evaluable_count") != n_noeval:
    fail("C3", "test-requirements 顶层计数与实际不符：声明 %s/%s，实际 %d/%d"
         % (TR.get("evaluable_count"), TR.get("not_evaluable_count"), n_eval, n_noeval))
else:
    ok("C3", "26 条判据：evaluable %d 条语法与变量全通过，not evaluable %d 条理由齐全"
       % (n_eval, n_noeval))

# ------------------------------------------------------- C7 / C8 可调参数
def check_ranges(tag, arr):
    for it in arr:
        key = it.get("key")
        val = it.get("value")
        vmin, vmax = it.get("min"), it.get("max")
        opts = it.get("options")
        if opts is not None:
            # C8 枚举型
            if not opts:
                fail("C8", "%s.%s 的 options 是空数组" % (tag, key))
            if any(x is not None for x in (vmin, vmax, it.get("step"))):
                fail("C8", "%s.%s 是枚举型却还带 min/max/step" % (tag, key))
            if val not in [o["value"] for o in opts]:
                fail("C8", "%s.%s 的当前值 %r 不在 options 里" % (tag, key, val))
            continue
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            continue
        below = it.get("value_below_min") is True
        if vmin is not None and val < vmin and not below:
            fail("C7", "%s.%s 的 value %s 低于 min %s，且没标 value_below_min"
                 % (tag, key, val, vmin))
        if vmin is not None and val >= vmin and below:
            fail("C7", "%s.%s 标了 value_below_min 但 value %s 并不低于 min %s"
                 % (tag, key, val, vmin))
        if vmax is not None and val > vmax:
            fail("C7", "%s.%s 的 value %s 高于 max %s" % (tag, key, val, vmax))


check_ranges("control-parameters", CP["parameters"])
check_ranges("product-attributes", DATA["product-attributes.json"]["attributes"])
n_opt = sum(1 for p in CP["parameters"] if p.get("options"))
n_below = sum(1 for p in CP["parameters"] if p.get("value_below_min"))
n_est = sum(1 for p in CP["parameters"] if p.get("range_estimated"))
if not [f for f in FAILS if f.startswith("[C7]") or f.startswith("[C8]")]:
    ok("C7/C8", "参数区间全部自洽：枚举型 %d 项、value_below_min %d 项、range_estimated %d 项"
       % (n_opt, n_below, n_est))

# ------------------------------------------------------------- C9 README 对账
README = open(os.path.join(OUT, "README.md"), encoding="utf-8").read()
SIL = DATA["safety-interlocks.json"]["interlocks"]
DOCS = DATA["documents.json"]["documents"]
WFS = DATA["workflows.json"]["workflows"]
RT = DATA["report-template.json"]

type_n = {}
for i in SIL:
    type_n[i["type"]] = type_n.get(i["type"], 0) + 1
group_n = len({json.dumps(w["group"], sort_keys=True) for w in WFS})
status_n = {}
for d in DOCS:
    status_n[d["conversion_status"]] = status_n.get(d["conversion_status"], 0) + 1

CLAIMS = [
    ("README 4.4 硬件条数", r"\*\*硬件\*\*（(\d+) 条）", type_n.get("硬件")),
    ("README 4.4 流程条数", r"\*\*流程\*\*（(\d+) 条）", type_n.get("流程")),
    ("README 4.4 人员条数", r"\*\*人员\*\*（(\d+) 条）", type_n.get("人员")),
    ("README 4.4 联锁合计", r"合计 (\d+) 条 = 硬件", len(SIL)),
    ("README 4.4 fault 位数", r"13 条覆盖 `0x0000` 到 `0x8000`",
     13 if len(SI["fault_bitmap"]["bits"]) == 13 else -1),
    ("README 4.6 分组取值数", r"`group`（(\d+) 个取值", group_n),
    ("README 4.5 evaluable 数", r"本包 (\d+) 条 true", TR["evaluable_count"]),
    ("README 4.5 runtime_measures 数", r"顶层 `runtime_measures` 登记表（(\d+) 个）",
     len(TR["runtime_measures"])),
    ("README 4.9 markdown_native", r"`markdown_native` \| [^|]+\| (\d+)",
     status_n.get("markdown_native")),
    ("README 4.9 parsed_into_pack", r"`parsed_into_pack` \| [^|]+\| (\d+)",
     status_n.get("parsed_into_pack")),
    ("README 4.9 not_converted", r"`not_converted` \| [^|]+\| (\d+)",
     status_n.get("not_converted")),
    ("README 4.10 表头已填数", r"`header_filled_count` 为 (\d+)", RT["header_filled_count"]),
    ("README 2.1 文档条数", r"`documents.json` \|[^|]+\|\s*(\d+)\s*\|", len(DOCS)),
    ("README 2.1 工作流条数", r"`workflows.json` \|[^|]+\|\s*(\d+)\s*\|", len(WFS)),
    ("README 2.1 联锁条数", r"`safety-interlocks.json` \|[^|]+\|\s*(\d+)\s*\|", len(SIL)),
    ("README 2.1 判据条数", r"`test-requirements.json` \|[^|]+\|\s*(\d+)\s*\|",
     len(TR["requirements"])),
    ("README 2.1 参数条数", r"`control-parameters.json` \|[^|]+\|\s*(\d+)\s*\|",
     len(CP["parameters"])),
]
for label, pat, actual in CLAIMS:
    m = re.search(pat, README)
    if not m:
        fail("C9", "%s：README 里找不到这句话（正则 %s）" % (label, pat))
        continue
    if m.groups():
        claimed = int(m.group(1))
        if claimed != actual:
            fail("C9", "%s：README 写 %d，实际 %s" % (label, claimed, actual))
    elif actual == -1:
        fail("C9", "%s：README 的说法与实际不符" % label)

# 4.10 表头 10 项未填这句必须与 header_filled_count 一致
if RT["header_filled_count"] == 0 and "一项都没填" not in README:
    fail("C9", "README 4.10 没说清已填充样例的 10 项表头其实一项都没填")

if not [f for f in FAILS if f.startswith("[C10]")]:
    n_bit = sum(1 for r in TR["requirements"]
                if r.get("criterion") and ("&" in r["criterion"].replace("&&", "")
                                           or "|" in r["criterion"].replace("||", "")))
    ok("C10", "%d 条含位运算的判据全部正确加了括号" % n_bit)

if not [f for f in FAILS if f.startswith("[C9]")]:
    ok("C9", "README 的 %d 处计数声明与实际数据全部一致" % len(CLAIMS))

# ---------------------------------------------------------------- 汇总
print("=" * 78)
print("场景包自检  scene id = %s" % TR["scene_id"])
print("=" * 78)
for n in NOTES:
    print("  " + n)
if FAILS:
    print("-" * 78)
    print("FAIL %d 项：" % len(FAILS))
    for f in FAILS:
        print("  " + f)
    sys.exit(1)
print("-" * 78)
print("全部通过。")
