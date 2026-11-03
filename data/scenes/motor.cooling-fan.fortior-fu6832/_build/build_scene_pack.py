#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""峰岹散热风扇场景包生成入口。

只读源材料，产物全部写到本脚本上级目录。
    python3 _build/build_scene_pack.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gen_a
import gen_b
from common import OUT, count_placeholders

ORDER = [
    ("scene.json", gen_a.gen_scene),
    ("product-attributes.json", gen_a.gen_product_attributes),
    ("control-parameters.json", gen_a.gen_control_parameters),
    ("safety-interlocks.json", gen_a.gen_safety_interlocks),
    ("test-requirements.json", gen_a.gen_test_requirements),
    ("workflows.json", gen_b.gen_workflows),
    ("datasets.json", gen_b.gen_datasets),
    ("experience.json", gen_b.gen_experience),
    ("documents.json", gen_b.gen_documents),
    ("report-template.json", gen_b.gen_report_template),
]

# 每个文件里「条数」该数哪个数组
COUNT_KEY = {
    "scene.json": "images",
    "product-attributes.json": "attributes",
    "control-parameters.json": "parameters",
    "safety-interlocks.json": "interlocks",
    "test-requirements.json": "requirements",
    "workflows.json": "workflows",
    "datasets.json": "datasets",
    "experience.json": "experiences",
    "documents.json": "documents",
    "report-template.json": "spec_sections",
}


def main():
    rows = []
    for name, fn in ORDER:
        path = fn()
        if path is None:
            rows.append((name, None, 0, 0, 0))
            continue
        obj = json.load(open(path, encoding="utf-8"))
        arr = obj.get(COUNT_KEY.get(name, ""), [])
        n = len(arr) if isinstance(arr, list) else 0
        total, ph = count_placeholders(obj)
        rows.append((name, os.path.getsize(path), n, total, ph))

    print("=" * 78)
    print("场景包生成报告  scene id = motor.cooling-fan.fortior-fu6832")
    print("输出目录：%s" % OUT)
    print("=" * 78)
    print("%-26s %10s %8s %10s %10s" % ("文件", "字节", "主条数", "带源对象", "占位对象"))
    for name, size, n, total, ph in rows:
        print("%-26s %10s %8d %10d %10d" % (
            name, size if size is not None else "生成失败", n, total, ph))
    tot_obj = sum(r[3] for r in rows)
    tot_ph = sum(r[4] for r in rows)
    print("-" * 78)
    print("合计：带 _source/_placeholder 的对象 %d 个，其中占位 %d 个，占位比例 %.1f%%"
          % (tot_obj, tot_ph, 100.0 * tot_ph / tot_obj if tot_obj else 0))

    miss = gen_a.MISSING + gen_b.NOT_FOUND
    print("-" * 78)
    if miss:
        print("未找到 / 未命中的项（%d）：" % len(miss))
        for m in miss:
            print("  - %s" % m)
    else:
        print("未找到的项：无")

    assets = []
    adir = os.path.join(OUT, "assets")
    for root, _, files in os.walk(adir):
        for f in sorted(files):
            p = os.path.join(root, f)
            assets.append((os.path.relpath(p, OUT), os.path.getsize(p)))
    print("-" * 78)
    print("assets 资产（%d 个）：" % len(assets))
    for rel, size in assets:
        print("  %-52s %10d" % (rel, size))


if __name__ == "__main__":
    main()
