#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场景包契约校验器 v1.1：拿 schema/*.schema.json 校验任意一个场景包目录。

用法

    python3 validate.py <场景包目录> [<场景包目录> ...]
    python3 validate.py --all           # 校验 packs.json 登记的全部场景包

    可选参数
    --schema-dir <目录>   指定 schema 目录，缺省取本文件同级的 schema/
    --packs-config <文件> 指定 --all 用的登记文件，缺省取本文件同级的 packs.json
    --template            被校验目录是模板目录（目录名不必是合法场景标识）
    --quiet               只打印每个文件一行结论，不展开错误明细
    --max-errors N        每份文件最多展开多少条错误，缺省 10

退出码：全部通过为 0，有任何 FAIL 为 1。

两个阶段
    第一阶段 · 结构：十一份 JSON 的字段、类型、封闭枚举、条件依赖（JSON Schema draft 2020-12）。
    第二阶段 · 跨文件与业务：X1 到 X9 九组检查，见下方 cross_file_checks() 与 README 第 9.1 节。

它仍然不负责什么
    判据表达式的 JS 语法与位运算优先级陷阱、包自己 README.md 的计数对账——
    那两类留在各场景包的 _build/selfcheck.py，分工见 README-场景包契约-v1.1.md 第 9 节。

依赖：jsonschema >= 4.18（用到 referencing 注册表解析 common.schema.json 的 $ref）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

try:
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012
except ImportError:  # pragma: no cover
    sys.stderr.write("缺依赖：pip install 'jsonschema>=4.18'\n")
    raise

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SCHEMA_DIR = os.path.join(HERE, "schema")
DEFAULT_PACKS_CONFIG = os.path.join(HERE, "packs.json")

#: 场景包的十一份 JSON。顺序即校验与报告顺序。
PACK_FILES = [
    "scene.json",
    "product-attributes.json",
    "control-parameters.json",
    "safety-interlocks.json",
    "test-requirements.json",
    "workflows.json",
    "datasets.json",
    "experience.json",
    "documents.json",
    "report-template.json",
    "copilot-actions.json",
]

#: 副驾按钮定义里固定的六个作用域键（五条流程 + 知识库模块）。
COPILOT_SCOPES = ["init", "req", "run", "tune", "report", "knowledge"]

#: 场景 id 的形状，与 schema/common.schema.json 的 $defs.sceneId 保持一致。
SCENE_ID_RE = r"^[a-z0-9][a-z0-9-]*\.[a-z0-9][a-z0-9-]*\.[a-z0-9][a-z0-9-]*$"

#: 骨架包里用来占位的分类键与产品文案。第三个包忘了换会被 X2 点名。
SKELETON_TAXONOMY_KEYS = {"example", "minimal", "skeleton"}
SKELETON_PRODUCT_MARK = "最小骨架示例产品"

#: 「未采集」不等于「不通过」：理由里不许出现判定词。
VERDICT_WORDS = ["不通过", "不合格", "判负", "FAIL", "fail"]


# ----------------------------------------------------------------- schema 装载
def load_registry(schema_dir: str):
    """把 schema 目录下的全部 *.schema.json 装进 referencing 注册表。

    每份 schema 以两个名字登记：文件内声明的 $id（绝对 URI），以及裸文件名
    （common.schema.json）。后者让各文件里的相对 $ref 不依赖网络也能解析。
    """
    resources = {}
    for name in sorted(os.listdir(schema_dir)):
        if not name.endswith(".schema.json"):
            continue
        with open(os.path.join(schema_dir, name), encoding="utf-8") as fh:
            body = json.load(fh)
        res = Resource.from_contents(body, default_specification=DRAFT202012)
        resources[name] = res
        if "$id" in body:
            resources[body["$id"]] = res
    return Registry().with_resources(resources.items()), resources


def validator_for(schema_dir: str, registry, stem: str) -> Draft202012Validator:
    with open(os.path.join(schema_dir, stem + ".schema.json"), encoding="utf-8") as fh:
        body = json.load(fh)
    return Draft202012Validator(body, registry=registry)


# ----------------------------------------------------------------- 错误定位
def where(err) -> str:
    """把一条校验错误的位置写成 JSON 路径，例如 $.parameters[3].min。"""
    parts = ["$"]
    for token in err.absolute_path:
        parts.append("[%d]" % token if isinstance(token, int) else "." + str(token))
    return "".join(parts)


def brief(err) -> str:
    msg = err.message.replace("\n", " ")
    return msg if len(msg) <= 240 else msg[:237] + "…"


# ----------------------------------------------------------------- 小工具
def as_list(v):
    """把「单值或数组」统一成列表，None 归成空列表。"""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def tier_members(tiers) -> list[str]:
    """把 group_tiers 三层骨架里点名的全部条目 key / id 摊平成一张表。"""
    out = []
    for tier in tiers or []:
        if not isinstance(tier, dict):
            continue
        for grp in tier.get("groups") or []:
            if not isinstance(grp, dict):
                continue
            out += [x for x in (grp.get("members") or []) if isinstance(x, str)]
            out += [x for x in (grp.get("items") or []) if isinstance(x, str)]
            for sub in grp.get("subgroups") or []:
                if isinstance(sub, dict):
                    out += [x for x in (sub.get("items") or []) if isinstance(x, str)]
    return out


def dup(names) -> list[str]:
    seen, bad = set(), []
    for n in names:
        if n in seen and n not in bad:
            bad.append(n)
        seen.add(n)
    return bad


def in_pack(path: str, pack_dir: str) -> str | None:
    """把一条资产路径归到场景包内的绝对路径；指向包外的外部材料返回 None。

    包外材料（客户工程目录里的模板、标准原文）换机器就不在了，按路径存在与否判 FAIL
    会让契约绑死在一台机器上，所以只检查落在包内的那些。
    """
    if not isinstance(path, str) or not path:
        return None
    full = path if os.path.isabs(path) else os.path.join(pack_dir, path)
    full = os.path.normpath(full)
    root = os.path.normpath(os.path.abspath(pack_dir))
    return full if os.path.abspath(full).startswith(root + os.sep) else None


# ----------------------------------------------------------------- 第二阶段
def cross_file_checks(pack_dir: str, data: dict, is_template: bool) -> list[str]:
    """九组跨文件与业务检查。每条返回一句可直接照着改的话。"""
    problems: list[str] = []
    g = lambda name: data.get(name) if isinstance(data.get(name), dict) else {}

    scene = g("scene.json")
    pa, cp = g("product-attributes.json"), g("control-parameters.json")
    si, tr = g("safety-interlocks.json"), g("test-requirements.json")
    wf, ds = g("workflows.json"), g("datasets.json")
    exp, doc = g("experience.json"), g("documents.json")
    rt, ca = g("report-template.json"), g("copilot-actions.json")

    # ---------------------------------------------------------- X1 文件齐全
    missing = [f for f in PACK_FILES if f not in data]
    if missing:
        problems.append("X1 缺文件：%s" % "、".join(missing))

    # -------------------------------------------- X2 场景标识与三级分类一致
    sid = scene.get("id")
    if sid:
        dirname = os.path.basename(os.path.normpath(os.path.abspath(pack_dir)))
        # v1.1 起把条件反过来：目录名不合三段式本身就是错，除非显式声明是模板目录。
        # v1.0 写的是「目录名像场景标识时才比对」，逻辑反了——目录名写坏反而整条跳过。
        if not is_template:
            if not re.match(SCENE_ID_RE, dirname):
                problems.append(
                    "X2 目录名「%s」不是合法场景标识（三段点分小写，段内连字符）。"
                    "模板目录请加 --template 豁免" % dirname)
            elif sid != dirname:
                problems.append("X2 scene.json 的 id「%s」与目录名「%s」不一致" % (sid, dirname))
        for name, body in data.items():
            if not isinstance(body, dict) or name == "scene.json":
                continue
            got = (body.get("applies_to") or {}).get("scene_id") if name == "copilot-actions.json" \
                else body.get("scene_id")
            if got is not None and got != sid:
                problems.append("X2 %s 的 scene_id「%s」与 scene.json 的 id「%s」不一致"
                                % (name, got, sid))
        # taxonomy 三级 key 与场景标识三段逐段对齐
        tx = scene.get("taxonomy") or {}
        seg = sid.split(".")
        for i, key in enumerate(["level1_scene", "level2_category", "level3_product_type"]):
            got = (tx.get(key) or {}).get("key")
            if got is not None and i < len(seg) and got != seg[i]:
                problems.append("X2 taxonomy.%s.key「%s」与场景标识第 %d 段「%s」不一致"
                                % (key, got, i + 1, seg[i]))
        if not is_template:
            names = {(tx.get(k) or {}).get("key") for k in
                     ("level1_scene", "level2_category", "level3_product_type")}
            if names & SKELETON_TAXONOMY_KEYS:
                problems.append("X2 taxonomy 还留着骨架包的分类键 %s，换包必须整段改写"
                                % "、".join(sorted(names & SKELETON_TAXONOMY_KEYS)))
            if SKELETON_PRODUCT_MARK in str((scene.get("product") or {}).get("name", "")):
                problems.append("X2 product.name 还是骨架包文案，换包必须改成真实产品全名")

    # ------------------------------------------ X3 副驾作用域键齐全且无多余
    # 与 copilot-actions.schema.json 的 flows.required + additionalProperties 重复，
    # 保留的理由只有一条：schema 报「'knowledge' is a required property」不指人，这里指人。
    if isinstance(ca.get("flows"), dict):
        keys = set(ca["flows"])
        lack = [k for k in COPILOT_SCOPES if k not in keys]
        extra = sorted(keys - set(COPILOT_SCOPES))
        if lack:
            problems.append("X3 copilot-actions.json 的 flows 缺作用域：%s" % "、".join(lack))
        if extra:
            problems.append("X3 copilot-actions.json 的 flows 有前端不认的作用域：%s" % "、".join(extra))

    # ------------------------------------------ X4 同文件内键引用一致性
    def keyset(body, arr, field):
        return {x.get(field) for x in (body.get(arr) or []) if isinstance(x, dict)}

    pa_keys = keyset(pa, "attributes", "key")
    cp_keys = keyset(cp, "parameters", "key")
    si_ids = keyset(si, "interlocks", "id")
    tr_ids = keyset(tr, "requirements", "id")
    ds_ids = keyset(ds, "datasets", "id")
    exp_ids = keyset(exp, "experiences", "id")
    doc_ids = keyset(doc, "documents", "id")
    wf_ids = keyset(wf, "workflows", "id")

    # X4a group_tiers 两层点名都必须落地。
    # 注意两层语义不同：groups[].members 点的是本文件的分组名（product-attributes 与
    # control-parameters 的 groups 清单、test-requirements 的 categories），
    # subgroups[].items 与 itemTier 的 groups[].items 点的才是条目 key / id。
    # v1.0 的 common.schema.json 把两者都说成「条目的 key 或 id」，与两个实物包的实际写法不符，
    # v1.1 一并改正。
    def tier_split(tiers):
        members, items = [], []
        for tier in tiers or []:
            if not isinstance(tier, dict):
                continue
            for grp in tier.get("groups") or []:
                if not isinstance(grp, dict):
                    continue
                members += [x for x in (grp.get("members") or []) if isinstance(x, str)]
                items += [x for x in (grp.get("items") or []) if isinstance(x, str)]
                for sub in grp.get("subgroups") or []:
                    if isinstance(sub, dict):
                        items += [x for x in (sub.get("items") or []) if isinstance(x, str)]
        return members, items

    for fname, body, pool, gpool in [
            ("product-attributes.json", pa, pa_keys, set(pa.get("groups") or [])),
            ("control-parameters.json", cp, cp_keys, set(cp.get("groups") or [])),
            ("safety-interlocks.json", si, si_ids, set(si.get("types") or [])),
            ("test-requirements.json", tr, tr_ids, set(tr.get("categories") or []))]:
        mem, its = tier_split(body.get("group_tiers"))
        bad = sorted({m for m in mem if gpool and m not in gpool})
        if bad:
            problems.append("X4 %s 的 group_tiers 的 members 点名了本文件没有的分组：%s"
                            % (fname, "、".join(bad[:8])))
        bad = sorted({i for i in its if i not in pool})
        if bad:
            problems.append("X4 %s 的 group_tiers 点名了不存在的条目：%s"
                            % (fname, "、".join(bad[:8])))
    # X4b demo_profile 点名的条目必须存在（它驱动前端 tiers.ts 的 demoFilter，悬挂会静默退回全量）
    for fname, body, spec in [
            ("control-parameters.json", cp, [("parameters", cp_keys),
                                             ("groups", set(cp.get("groups") or []))]),
            ("safety-interlocks.json", si, [("interlocks", si_ids)]),
            ("test-requirements.json", tr, [("requirements", tr_ids)]),
            ("datasets.json", ds, [("datasets", ds_ids)])]:
        prof = body.get("demo_profile")
        if not isinstance(prof, dict):
            continue
        for field, pool in spec:
            bad = sorted({x for x in (prof.get(field) or []) if x not in pool})
            if bad:
                problems.append("X4 %s 的 demo_profile.%s 点名了不存在的条目：%s"
                                "（演示模式会静默退回全量，不报错）"
                                % (fname, field, "、".join(bad[:8])))

    # X4c legend / 清单类键引用
    def legend_ok(value, legend):
        """值本身是 legend 的键；或用「 + 」拼了几个键；或落在某个以 … 结尾的通配键下。

        两个实物包都出现过这两种写法（包二的「文献综合 + 法规条款」与
        「已解析为 control-parameters.json + experience.json」），所以这里按它们的实际口径判。
        """
        if not isinstance(value, str) or not legend:
            return True
        if value in legend:
            return True
        if all(part.strip() in legend for part in value.split(" + ")):
            return True
        return any(k.endswith("…") and value.startswith(k[:-1].rstrip()) for k in legend)

    lv = set(exp.get("evidence_levels") or {})
    bad = sorted({x.get("evidence_level") for x in (exp.get("experiences") or [])
                  if isinstance(x, dict) and not legend_ok(x.get("evidence_level"), lv)})
    if bad:
        problems.append("X4 experience.json 的 evidence_level 不在本文件 evidence_levels 内：%s"
                        % "、".join(str(b) for b in bad[:8]))
    lg = set(doc.get("conversion_status_legend") or {})
    bad = sorted({x.get("conversion_status") for x in (doc.get("documents") or [])
                  if isinstance(x, dict) and not legend_ok(x.get("conversion_status"), lg)})
    if bad:
        problems.append("X4 documents.json 的 conversion_status 不在本文件 "
                        "conversion_status_legend 内：%s" % "、".join(str(b) for b in bad[:8]))
    ct = set(doc.get("count_by_type") or {})
    bad = sorted({x.get("type") for x in (doc.get("documents") or [])
                  if isinstance(x, dict) and ct and x.get("type") not in ct})
    if bad:
        problems.append("X4 documents.json 的 type 不在本文件 count_by_type 的键里：%s"
                        % "、".join(str(b) for b in bad[:8]))
    for fname, body, arr, field in [("product-attributes.json", pa, "attributes", "group"),
                                    ("control-parameters.json", cp, "parameters", "group")]:
        pool = set(body.get("groups") or [])
        bad = sorted({x.get(field) for x in (body.get(arr) or [])
                      if isinstance(x, dict) and pool and x.get(field) not in pool})
        if bad:
            problems.append("X4 %s 的 %s 不在本文件 groups 清单内：%s"
                            % (fname, field, "、".join(str(b) for b in bad[:8])))
    cats = set(tr.get("categories") or [])
    bad = sorted({x.get("category") for x in (tr.get("requirements") or [])
                  if isinstance(x, dict) and cats and x.get("category") not in cats})
    if bad:
        problems.append("X4 test-requirements.json 的 category 不在本文件 categories 内：%s"
                        % "、".join(str(b) for b in bad[:8]))

    # X4d 同一文件内条目标识不得重复
    for fname, body, arr, field in [("product-attributes.json", pa, "attributes", "key"),
                                    ("control-parameters.json", cp, "parameters", "key"),
                                    ("safety-interlocks.json", si, "interlocks", "id"),
                                    ("test-requirements.json", tr, "requirements", "id"),
                                    ("datasets.json", ds, "datasets", "id"),
                                    ("experience.json", exp, "experiences", "id"),
                                    ("documents.json", doc, "documents", "id"),
                                    ("workflows.json", wf, "workflows", "id")]:
        bad = dup([x.get(field) for x in (body.get(arr) or []) if isinstance(x, dict)])
        if bad:
            problems.append("X4 %s 的 %s.%s 重复：%s" % (fname, arr, field, "、".join(map(str, bad[:8]))))
    btn_ids = []
    for scope, blk in (ca.get("flows") or {}).items():
        if isinstance(blk, dict):
            btn_ids += [b.get("id") for b in (blk.get("buttons") or []) if isinstance(b, dict)]
    bad = dup(btn_ids)
    if bad:
        problems.append("X4 copilot-actions.json 的按钮 id 重复：%s" % "、".join(map(str, bad[:8])))

    # ------------------------------------------ X5 跨文件引用目标存在性
    miss = set()
    for w in wf.get("workflows") or []:
        if isinstance(w, dict):
            miss |= {r for r in as_list(w.get("covers_requirements")) if r not in tr_ids}
    if miss:
        problems.append("X5 workflows.json 的 covers_requirements 指向不存在的判据 id：%s"
                        % "、".join(sorted(miss)[:8]))
    # tags.parameters 对参数 key 大小写不敏感：包一的经验标签抄的是固件宏名（大写），
    # control-parameters 的 key 是蛇形小写，两者是同一个量。
    cp_lower = {k.lower() for k in cp_keys if isinstance(k, str)}
    miss = set()
    for x in exp.get("experiences") or []:
        if not isinstance(x, dict) or x.get("parameters_resolved") is False:
            continue  # 明示「这条的参数名还没解析到 key」，不算悬挂引用
        tags = x.get("tags")
        if isinstance(tags, dict):
            miss |= {p for p in as_list(tags.get("parameters"))
                     if isinstance(p, str) and p.lower() not in cp_lower}
    if miss:
        problems.append("X5 experience.json 的 tags.parameters 对不上 control-parameters.json 的 key："
                        "%s" % "、".join(sorted(miss)[:8]))
    # maps_to 与各类 note 里点名的 *.json 必须是本包十一份之一
    ref_re = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\.json")
    miss = set()
    for s in rt.get("spec_sections") or []:
        if isinstance(s, dict) and isinstance(s.get("maps_to"), str):
            miss |= {t for t in ref_re.findall(s["maps_to"]) if t not in PACK_FILES}
    if miss:
        problems.append("X5 report-template.json 的 maps_to 指向本包没有的文件：%s"
                        % "、".join(sorted(miss)[:8]))
    # 判据变量四类来源逐一解析到目标
    rm = set(tr.get("runtime_measures") or {})
    bits = set((si.get("fault_bitmap") or {}).get("bits") or {})
    for r in tr.get("requirements") or []:
        if not isinstance(r, dict):
            continue
        rid = r.get("id")
        th = set(r.get("threshold") or {}) if isinstance(r.get("threshold"), dict) else set()
        for vname, v in (r.get("variables") or {}).items():
            if not isinstance(v, dict):
                continue
            src, ref = v.get("source"), v.get("ref")
            tail = ref.split(".")[-1] if isinstance(ref, str) else None
            if src == "runtime.measure" and tail and tail not in rm:
                problems.append("X5 %s 的变量 %s 指向 runtime_measures 里没有的 %s" % (rid, vname, tail))
            elif src == "threshold" and tail and tail not in th:
                problems.append("X5 %s 的变量 %s 指向本条 threshold 里没有的 %s" % (rid, vname, tail))
            elif src == "control-parameters" and tail and tail.lower() not in cp_lower:
                problems.append("X5 %s 的变量 %s 指向 control-parameters.json 里没有的参数 %s"
                                % (rid, vname, tail))
            elif src == "constant":
                for df in as_list(v.get("derived_from")):
                    if isinstance(df, str) and df.split(".")[-1] not in bits:
                        problems.append("X5 %s 的变量 %s 的 derived_from「%s」指向 fault_bitmap 里"
                                        "没有的位" % (rid, vname, df))
    # 判据表达式里的自由标识符必须在 variables 或 criterion_globals 里声明
    glob = set(tr.get("criterion_globals") or []) | {"true", "false", "null", "Math"}
    ident = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
    for r in tr.get("requirements") or []:
        if not isinstance(r, dict) or not isinstance(r.get("criterion"), str):
            continue
        declared = set(r.get("variables") or {}) | glob
        # 先抹掉字符串字面量：包二的判据用 retract_mode === 'ROD_200MM_PASS' 这种枚举比较，
        # 引号里的是取值不是变量，不抹掉会被误判成未声明标识符。
        expr = re.sub(r"'[^']*'|\"[^\"]*\"|`[^`]*`", " '' ", r["criterion"])
        free = {t for t in ident.findall(expr) if t not in declared}
        # 属性访问的右半段（Math.abs 的 abs）不算自由标识符
        free -= {m for m in free if re.search(r"\.\s*%s\b" % re.escape(m), expr)}
        if free:
            problems.append("X5 %s 的 criterion 用了未声明的标识符：%s"
                            % (r.get("id"), "、".join(sorted(free)[:8])))

    # ------------------------------------------ X6 顶层计数与实际条数
    for fname, body, field, arr in [("documents.json", doc, "total", "documents"),
                                    ("experience.json", exp, "count", "experiences"),
                                    ("workflows.json", wf, "total", "workflows")]:
        want, got = body.get(field), len(body.get(arr) or [])
        if isinstance(want, int) and want != got:
            problems.append("X6 %s 的 %s 写 %d，实际 %d 条" % (fname, field, want, got))
    reqs = [r for r in (tr.get("requirements") or []) if isinstance(r, dict)]
    if reqs:
        for field, want_n in [("evaluable_count", sum(1 for r in reqs if r.get("evaluable"))),
                              ("not_evaluable_count", sum(1 for r in reqs if not r.get("evaluable")))]:
            if isinstance(tr.get(field), int) and tr[field] != want_n:
                problems.append("X6 test-requirements.json 的 %s 写 %d，实际 %d 条"
                                % (field, tr[field], want_n))
    cbg = wf.get("count_by_group")
    if isinstance(cbg, dict):
        real: dict[str, int] = {}
        for w in wf.get("workflows") or []:
            grp = w.get("group") if isinstance(w, dict) else None
            key = grp.get("key") if isinstance(grp, dict) else grp
            if isinstance(key, str):
                real[key] = real.get(key, 0) + 1
        if real and real != {k: v for k, v in cbg.items() if k in real or True}:
            diff = sorted({k for k in set(cbg) | set(real) if cbg.get(k) != real.get(k)})
            if diff:
                problems.append("X6 workflows.json 的 count_by_group 与实际不符，分组：%s"
                                % "、".join(diff[:8]))
    cbt = doc.get("count_by_type")
    if isinstance(cbt, dict) and doc.get("documents"):
        real = {}
        for x in doc["documents"]:
            if isinstance(x, dict) and isinstance(x.get("type"), str):
                real[x["type"]] = real.get(x["type"], 0) + 1
        diff = sorted({k for k in set(cbt) | set(real) if cbt.get(k) != real.get(k)})
        if diff:
            problems.append("X6 documents.json 的 count_by_type 与实际不符，类型：%s"
                            % "、".join(diff[:8]))
    elc = exp.get("evidence_level_counts")
    if isinstance(elc, dict) and exp.get("experiences"):
        real = {}
        for x in exp["experiences"]:
            if isinstance(x, dict) and isinstance(x.get("evidence_level"), str):
                real[x["evidence_level"]] = real.get(x["evidence_level"], 0) + 1
        diff = sorted({k for k in set(elc) | set(real) if elc.get(k) != real.get(k)})
        if diff:
            problems.append("X6 experience.json 的 evidence_level_counts 与实际不符，档位：%s"
                            % "、".join(diff[:8]))

    # ------------------------------------------ X7 包内资产文件存在性
    # 只查落在场景包目录内的路径；指向客户工程或标准原文的包外绝对路径不查，换机器就不在了。
    for label, path in ([("scene.json images[].path", i.get("path"))
                         for i in (scene.get("images") or []) if isinstance(i, dict)]
                        + [("datasets.json datasets[].file_path", d.get("file_path"))
                           for d in (ds.get("datasets") or []) if isinstance(d, dict)]
                        + [("workflows.json workflows[].file_path", w.get("file_path"))
                           for w in (wf.get("workflows") or []) if isinstance(w, dict)]):
        full = in_pack(path, pack_dir)
        if full and not os.path.exists(full):
            problems.append("X7 %s 指向包内不存在的文件：%s" % (label, path))

    # ------------------------------------------ X8 业务红线
    # 红线三 · 合成数据不得进合规报告
    syn_ids = {d.get("id") for d in (ds.get("datasets") or [])
               if isinstance(d, dict) and d.get("synthetic") is True}
    has_syn = bool(syn_ids) or ds.get("all_synthetic") is True
    if has_syn:
        if not ds.get("why_synthetic"):
            problems.append("X8 红线三：本包有合成时序，datasets.json 必须写 why_synthetic "
                            "交代为什么没有真实数据")
        compliance_txt = json.dumps(
            {k: rt.get(k) for k in ("compliance_basis", "conclusion_binding",
                                    "technical_report_documentation_page")},
            ensure_ascii=False)
        hit = sorted({i for i in syn_ids if isinstance(i, str) and i in compliance_txt})
        if hit:
            problems.append("X8 红线三：合成数据集 %s 被 report-template.json 的合规字段直接点名，"
                            "合成数据的派生结论只能进演示与内部分析" % "、".join(hit[:5]))
        if not (rt.get("known_gap") or rt.get("compliance_note")):
            problems.append("X8 红线三：本包有合成时序，report-template.json 必须写 known_gap "
                            "明示这份报告不能拿来当合规证据用")
    # 红线四 · 「未采集」不等于「不通过」
    for r in reqs:
        if r.get("evaluable") is False:
            why = r.get("not_evaluable_reason") or ""
            hit = [w for w in VERDICT_WORDS if w in why]
            if hit:
                problems.append("X8 红线四：%s 的 not_evaluable_reason 里出现判定词「%s」，"
                                "未采集既不算通过也不算不通过" % (r.get("id"), hit[0]))
    # 参数区间自洽
    for p in cp.get("parameters") or []:
        if not isinstance(p, dict):
            continue
        key, lo, hi, val = p.get("key"), p.get("min"), p.get("max"), p.get("value")
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > hi:
            problems.append("X8 control-parameters.json 的 %s：min %s 大于 max %s" % (key, lo, hi))
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            if isinstance(lo, (int, float)) and val < lo and not p.get("value_below_min"):
                problems.append("X8 control-parameters.json 的 %s：value %s 低于 min %s 却没挂 "
                                "value_below_min" % (key, val, lo))
            if isinstance(hi, (int, float)) and val > hi:
                problems.append("X8 control-parameters.json 的 %s：value %s 高于 max %s"
                                % (key, val, hi))
        opts = p.get("options")
        if isinstance(opts, list) and opts:
            vals = [o.get("value") for o in opts if isinstance(o, dict)]
            if val is not None and val not in vals:
                problems.append("X8 control-parameters.json 的 %s：value %r 不在 options 里" % (key, val))
    for n in ("evaluable_count", "not_evaluable_count"):
        if isinstance(tr.get(n), int) and tr[n] < 0:
            problems.append("X8 test-requirements.json 的 %s 为负数" % n)

    # ------------------------------------------ X9 副驾红线降级
    for scope, blk in (ca.get("flows") or {}).items():
        if not isinstance(blk, dict):
            continue
        for b in blk.get("buttons") or []:
            if not isinstance(b, dict):
                continue
            bid = b.get("id")
            # knowledge 作用域的按钮沿用草案里的 kb 前缀：README 第 6.2 节把按钮 id 列为
            # 不得改名的编排层字段，前端按它做埋点与折叠记忆，所以这里认这一个历史别名。
            ok_prefix = (scope + ".", "kb.") if scope == "knowledge" else (scope + ".",)
            if isinstance(bid, str) and not bid.startswith(ok_prefix):
                problems.append("X9 按钮 %s 落在作用域 %s 下，id 前缀必须是作用域键（knowledge "
                                "另认历史别名 kb）" % (bid, scope))
            if b.get("touches_redline") and b.get("degraded_to") != "prepare_and_wait":
                problems.append("X9 按钮 %s 触碰红线却没降级成 prepare_and_wait" % bid)
            if b.get("type") == "execute" and b.get("confirm_required") is not True:
                problems.append("X9 按钮 %s 是执行类，confirm_required 必须为 true" % bid)
    return problems


# ----------------------------------------------------------------- 主流程
def validate_pack(pack_dir: str, schema_dir: str, registry, quiet: bool,
                  max_errors: int, is_template: bool) -> bool:
    print("=" * 78)
    print("场景包：%s%s" % (pack_dir, "（模板目录）" if is_template else ""))
    print("=" * 78)

    data = {}
    all_ok = True

    for name in PACK_FILES:
        path = os.path.join(pack_dir, name)
        stem = name[: -len(".json")]
        if not os.path.exists(path):
            print("  FAIL  %-26s 文件不存在" % name)
            all_ok = False
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                body = json.load(fh)
        except ValueError as exc:
            print("  FAIL  %-26s JSON 解析失败：%s" % (name, exc))
            all_ok = False
            continue
        data[name] = body

        v = validator_for(schema_dir, registry, stem)
        errors = sorted(v.iter_errors(body), key=lambda e: list(e.absolute_path))
        if not errors:
            print("  PASS  %-26s" % name)
            continue
        all_ok = False
        print("  FAIL  %-26s %d 处不符" % (name, len(errors)))
        if not quiet:
            for err in errors[:max_errors]:
                print("          %s" % where(err))
                print("            %s" % brief(err))
            if len(errors) > max_errors:
                print("          …另有 %d 处未展开（--max-errors 调整）" % (len(errors) - max_errors))

    problems = cross_file_checks(pack_dir, data, is_template)
    if problems:
        all_ok = False
        print("  FAIL  %-26s %d 处不符" % ("跨文件与业务检查", len(problems)))
        for p in problems[:max_errors * 3]:
            print("          %s" % p)
        if len(problems) > max_errors * 3:
            print("          …另有 %d 处未展开" % (len(problems) - max_errors * 3))
    else:
        print("  PASS  %-26s" % "跨文件与业务检查")

    print("-" * 78)
    print("结论：%s" % ("全部通过" if all_ok else "有未通过项，见上"))
    print()
    return all_ok


def resolve_all(config_path: str) -> list[tuple[str, bool]]:
    """读 packs.json，得到 --all 要校验的目录清单。

    v1.0 把两个实物包的绝对路径写死在代码里，换机器就失效（次-8）。
    v1.1 改成读同级的 packs.json，并允许 SCENE_PACK_ROOT 覆盖其中的 ${SCENE_PACK_ROOT}。
    """
    if not os.path.exists(config_path):
        sys.stderr.write("找不到登记文件 %s，--all 无从取目录\n" % config_path)
        return []
    with open(config_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    root = os.environ.get("SCENE_PACK_ROOT", cfg.get("scene_pack_root", ""))
    out = []
    for item in cfg.get("packs", []):
        path = item["path"].replace("${SCENE_PACK_ROOT}", root).replace("${HERE}", HERE)
        out.append((os.path.normpath(path), bool(item.get("template"))))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="场景包契约校验器 v1.1")
    ap.add_argument("packs", nargs="*", help="场景包目录")
    ap.add_argument("--all", action="store_true", help="校验 packs.json 登记的全部场景包")
    ap.add_argument("--schema-dir", default=DEFAULT_SCHEMA_DIR)
    ap.add_argument("--packs-config", default=DEFAULT_PACKS_CONFIG)
    ap.add_argument("--template", action="store_true",
                    help="被校验目录是模板目录，豁免「目录名 = 场景标识」与骨架文案检查")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--max-errors", type=int, default=10)
    args = ap.parse_args()

    targets: list[tuple[str, bool]] = [(os.path.abspath(p), args.template) for p in args.packs]
    if args.all:
        targets += resolve_all(args.packs_config)
    if not targets:
        ap.print_help()
        return 2

    registry, resources = load_registry(args.schema_dir)
    n = len([k for k in os.listdir(args.schema_dir) if k.endswith(".schema.json")])
    print("schema 目录：%s（%d 份）\n" % (args.schema_dir, n))

    results = [validate_pack(p, args.schema_dir, registry, args.quiet, args.max_errors, t)
               for p, t in targets]
    print("=" * 78)
    for (p, _), ok in zip(targets, results):
        print("  %s  %s" % ("PASS" if ok else "FAIL", p))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
