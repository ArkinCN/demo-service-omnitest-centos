"""验证「知识库取数切到服务端」后三轴计数与切换前一致。

为什么要有这个脚本：
    主文档阶段 3 验收 6 的原话是「前端把知识库取数切到服务端后，三轴筛选计数
    与切前一致（散热风扇包 85 条、用途轴 8/12/65）」。这句话里藏着一个陷阱：
    **切前与切后是两个数据源**，任何一处口径不一致（用途轴中文→英文码、
    usage 缺失时回落、归属三级反查）都会让数字对不上，而界面不会报错，
    只会「看着少了」。所以必须程序化比对，不能靠眼睛。

比对方式：
    左：**直接读场景包 JSON**（切换前的口径，照抄前端 data.ts 的映射规则）
    右：**服务端 GET /api/kb/entries?owner=<三级名>**（切换后的口径）
    两边逐项比，任一项不等就报出来。

用法：
    python scripts/verify_kb_counts.py
    python scripts/verify_kb_counts.py --base http://localhost:5173   # 经 vite 代理
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.paths import scenes_dir  # noqa: E402

# 与前端 data.ts 的 USAGE_CODE 一致
USAGE_CODE = {"产品说明书": "spec", "测试需求": "requirement", "工艺": "process"}
DEFAULT_USAGE = "process"

_failed = 0


def check(cond: bool, label: str, detail: str = "") -> bool:
    """必须返回 cond：调用方靠返回值决定走不走下一步。"""
    global _failed
    if cond:
        print(f"[OK]  {label}" + (f"  {detail}" if detail else ""))
    else:
        _failed += 1
        print(f"[NG]  {label}" + (f"  {detail}" if detail else ""))
    return cond


def http_list(base: str, **qs) -> dict:
    url = base + "/api/kb/entries"
    if qs:
        url += "?" + "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in qs.items())
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))["data"]
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code} {raw[:200]}")


def fetch_upload_prefixes(base: str) -> set[str]:
    """取「上传登记」的 doc_id 前缀集合（形如 `<doc_id>#`）。

    为什么要它：本脚本的口径是「**场景包**里的条目数与服务端一致」。但阶段 3
    补全后，在线转化会把用户上传的文档也写成条目（stage_index 真写 kb_entries），
    这些条目**不属于场景包**。若不排除，上传过几份资料后本脚本必然报「总数不一致」
    ——那是**假失败**，会掩盖真正的口径漂移（项目怕「狼来了」式的误报，
    见 3-R 教训：断言要接受合法多态）。

    取不到登记表时返回空集，调用方据 key 形态兜底判断。
    """
    try:
        with urllib.request.urlopen(f"{base}/api/kb/documents?limit=1000", timeout=30) as r:
            items = json.loads(r.read().decode("utf-8"))["data"]["items"]
        return {f"{d['doc_id']}#" for d in items if d.get("doc_id")}
    except Exception as e:  # noqa: BLE001
        print(f"[注意] 读上传登记失败，将按 key 形态判断上传产出：{e}")
        return set()


def is_upload_derived(entry_key: str, prefixes: set[str]) -> bool:
    """这条条目是否来自上传文档转化。

    优先用登记表前缀精确匹配；取不到时按 key 形态兜底：
    上传产出是 `<doc_id>#<chunk_id>`，场景包导入是 `<scene_id>:<原 id>`
    （见 import_kb_from_scenes.py）。所以「含 `#` 且不含 `:`」判为上传产出。
    """
    if prefixes:
        return entry_key.startswith(tuple(prefixes))
    return "#" in entry_key and ":" not in entry_key


def local_counts(scene_id: str) -> dict:
    """切换前的口径：直接数场景包 JSON（照抄前端 data.ts 的映射）。"""
    base = scenes_dir() / scene_id
    docs = json.loads((base / "documents.json").read_text(encoding="utf-8"))["documents"]
    exps = json.loads((base / "experience.json").read_text(encoding="utf-8"))["experiences"]
    usage = {"spec": 0, "requirement": 0, "process": 0}
    for x in docs + exps:
        usage[USAGE_CODE.get(x.get("usage") or "", DEFAULT_USAGE)] += 1
    return {
        "total": len(docs) + len(exps),
        "usage": usage,
        "origin": {"doc": len(docs), "experience": len(exps)},
    }


def owner_of(scene_id: str) -> tuple[str, str, str]:
    """与前端 ownerOf 一致：从 index.json 三级目录反查。"""
    idx = json.loads((scenes_dir() / "index.json").read_text(encoding="utf-8"))
    for a in idx.get("catalog", []):
        for b in a.get("children", []):
            for c in b.get("children", []):
                if c.get("sceneId") == scene_id:
                    return (a.get("label", ""), b.get("label", ""), c.get("label", ""))
    parts = scene_id.split(".")
    return (parts[0] if parts else scene_id, parts[1] if len(parts) > 1 else "",
            parts[2] if len(parts) > 2 else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8011")
    ap.add_argument("--scene", default="motor.cooling-fan.fortior-fu6832")
    args = ap.parse_args()

    print("=" * 74)
    print(f"知识库三轴计数比对   目标：{args.base}")
    print("=" * 74)

    left = local_counts(args.scene)
    o1, o2, o3 = owner_of(args.scene)
    print(f"场景包：{args.scene}")
    print(f"归属：{o1} / {o2} / {o3}")
    print(f"切换前（场景包 JSON 直数）：total={left['total']} "
          f"usage={left['usage']} origin={left['origin']}")

    try:
        right = http_list(args.base, owner=o3)
    except Exception as e:
        print(f"[NG]  服务端取数失败：{e}")
        return 1

    rc = right["counts"]
    print(f"切换后（服务端 /api/kb/entries）：total={rc['total']} "
          f"usage={rc['usage']} origin={rc['origin']}")

    # ── 排除「上传文档转化」产出的条目（阶段 3 补全后新增的一类）──
    # 它们不属于场景包，混在一起数会让本脚本永远报假失败。
    prefixes = fetch_upload_prefixes(args.base)
    items = right.get("items") or []
    imported = [i for i in items if not is_upload_derived(str(i.get("entry_key") or ""), prefixes)]
    uploaded = [i for i in items if is_upload_derived(str(i.get("entry_key") or ""), prefixes)]
    if uploaded:
        print(f"（另有上传文档转化产出的条目 {len(uploaded)} 条，不属场景包，已单独列出不计入比对）")

    # 场景包那一部分的口径：按导入条目重算（与 left 同口径）
    imp_usage = {"spec": 0, "requirement": 0, "process": 0}
    imp_origin = {"doc": 0, "experience": 0}
    for it in imported:
        u = it.get("usage")
        if u in imp_usage:
            imp_usage[u] += 1
        o = it.get("origin")
        if o in imp_origin:
            imp_origin[o] += 1
    print(f"其中场景包导入：total={len(imported)} usage={imp_usage} origin={imp_origin}")
    print("-" * 74)

    check(len(imported) == left["total"], "总数一致（仅场景包导入部分）",
          f"{len(imported)} vs {left['total']}")
    for k in ("spec", "requirement", "process"):
        check(imp_usage[k] == left["usage"][k], f"用途轴 {k} 一致",
              f"{imp_usage[k]} vs {left['usage'][k]}")
    for k in ("doc", "experience"):
        check(imp_origin[k] == left["origin"][k], f"来源轴 {k} 一致",
              f"{imp_origin[k]} vs {left['origin'][k]}")

    # 过滤是否真起作用：按 doc 过滤后，导入条目的 doc 数应与 left 的 doc 数一致
    filtered = http_list(args.base, owner=o3, origin="doc")
    f_imported = [i for i in (filtered.get("items") or [])
                  if not is_upload_derived(str(i.get("entry_key") or ""), prefixes)]
    check(len(f_imported) == left["origin"]["doc"], "按来源过滤生效",
          f"{len(f_imported)} vs {left['origin']['doc']}")

    # 跨包不串：另一个包的条目不应出现在本包结果里
    others = [p.name for p in scenes_dir().iterdir()
              if p.is_dir() and p.name != args.scene and (p / "documents.json").is_file()]
    if others:
        other_owner = owner_of(others[0])[2]
        cross = http_list(args.base, owner=other_owner)
        cross_items = cross.get("items") or []
        cross_imported = [i for i in cross_items
                          if not is_upload_derived(str(i.get("entry_key") or ""), prefixes)]
        check(len(cross_imported) == local_counts(others[0])["total"],
              f"另一包（{others[0]}）计数也正确且未串包",
              f"{len(cross_imported)} vs {local_counts(others[0])['total']}")

    print("=" * 74)
    print("结论：本轮用例全部通过" if not _failed else f"结论：{_failed} 项未通过")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
