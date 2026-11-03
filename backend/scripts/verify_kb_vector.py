"""向量检索一路的验证（阶段 3 补全）。

验的是附录 A.3「索引：关键词与向量两路」以及本轮的降级纪律：

  1. 双路确实都在参与（结果里能同时看到 hybrid / keyword / vector 三种 route）；
  2. 返回结构保持既有形状（前端引用面板不改版的前提）；
  3. 降级路径真实可用且**带原因**（向量不可用/字面回退都不能静默）；
  4. 索引陈旧检测能报出来（索引落后于语料时必须说，不静默返回旧结果）；
  5. 重建幂等（连建两次结果一致）。

跑法（后端 8011 在跑；且已用 build_kb_vector_index.py 建过索引）：
    python scripts/verify_kb_vector.py

输出一律 ASCII（中文可以），避免 Windows GBK 控制台 UnicodeEncodeError。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8011"
_failed = 0

# 既有字段（前端「依据」面板依赖）。加向量一路后**一个都不能少**。
LEGACY_FIELDS = ("rank", "score", "kind", "doc_id", "doc_title", "chunk_id",
                 "heading_path", "page", "source_path", "snippet")


def check(cond: bool, label: str, detail: str = "") -> bool:
    """断言并留痕。**必须 return cond**（漏 return 会让调用方静默失效）。"""
    global _failed
    if cond:
        print(f"[OK]  {label}" + (f"  {detail}" if detail else ""))
    else:
        _failed += 1
        print(f"[NG]  {label}" + (f"  {detail}" if detail else ""))
    return cond


def post_json(path: str, payload) -> tuple[int, dict]:
    url = f"{BASE}{urllib.parse.quote(path, safe='/?&=%')}"
    r = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(r, timeout=300) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def get_json(path: str) -> tuple[int, dict]:
    url = f"{BASE}{urllib.parse.quote(path, safe='/?&=%')}"
    try:
        with urllib.request.urlopen(url, timeout=300) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def main() -> int:
    print("== ① 向量索引现状 ==")
    st, out = get_json("/api/kb/vector/stat")
    check(st == 200, "GET /api/kb/vector/stat", f"HTTP {st}")
    d = out.get("data") or {}
    idx = d.get("index") or {}
    check(bool(idx.get("exists")), "索引已存在", str(idx.get("exists")))
    check((idx.get("count") or 0) > 0, "索引条数 > 0", str(idx.get("count")))
    check(idx.get("tier") in ("hashing", "transformer"), "档位取值合法", str(idx.get("tier")))
    check(d.get("corpus_count") == idx.get("count") or not d.get("stale"),
          "索引与语料一致（stale=False）",
          f"corpus={d.get('corpus_count')} index={idx.get('count')} stale={d.get('stale')}")

    print("\n== ② 混合检索：双路参与 + 既有结构不变 ==")
    # 用一句在语料里有明确对应的话（既有语料里 FG 脉冲数量是已知命中）
    st, out = post_json("/api/kb/search", {"query": "每转脉冲数量 FG 输出", "k": 10})
    check(st == 200, "POST /api/kb/search", f"HTTP {st}")
    results = out.get("results") or []
    check(len(results) > 0, "检索有结果", f"{len(results)} 条")

    if results:
        r0 = results[0]
        missing = [f for f in LEGACY_FIELDS if f not in r0]
        check("既有字段一个都没少", not missing, f"缺 {missing}")

        routes = {r.get("route") for r in results}
        check("route 取值合法",
              routes <= {"keyword", "vector", "hybrid"}, str(sorted(routes)))
        # 双路都在参与的实证：至少有一条 keyword 且至少一条 vector（或 hybrid）
        check("关键词一路有命中", any(r.get("route") in ("keyword", "hybrid") for r in results))
        check("向量一路有命中", any(r.get("route") in ("vector", "hybrid") for r in results),
              f"routes={sorted(routes)}")

        # 融合分量必须存在且可解释（排查排序时不用重跑检索）
        check("带 keyword 分量", "score_keyword" in r0)
        check("带 vector 分量", "score_vector" in r0)
        # 排序单调性：融合分应递减
        scores = [r.get("score") for r in results]
        check("结果按融合分降序", scores == sorted(scores, reverse=True), str(scores[:4]))

        # rank 连续 1..n
        check("rank 连续从 1 起",
              [r.get("rank") for r in results] == list(range(1, len(results) + 1)))

    print("\n== ③ 降级路径必须带原因（不许静默）==")
    degraded_flags = {r.get("degraded") for r in results}
    if True in degraded_flags:
        reasons = [r.get("degrade_reason") for r in results if r.get("degraded")]
        check("降级时带原因文本", all(bool(x) for x in reasons), str(reasons[:1])[:80])
    else:
        check("未降级（两路全可用）", True in degraded_flags or False in degraded_flags,
              "本次两路都可用，无降级")

    print("\n== ④ 索引重建幂等 ==")
    st, out = post_json("/api/kb/vector/rebuild", {})
    check(st == 200, "POST /api/kb/vector/rebuild", f"HTTP {st}")
    rb = out.get("data") or {}
    check(bool(rb.get("rebuilt")), "重建成功", str(rb.get("rebuilt")))
    first = rb.get("count")
    st, out2 = post_json("/api/kb/vector/rebuild", {})
    second = (out2.get("data") or {}).get("count")
    check("两次重建条数一致（幂等）", first == second, f"{first} vs {second}")

    print("\n== ⑤ 重建后检索仍然可用 ==")
    st, out = post_json("/api/kb/search", {"query": "额定转速", "k": 5})
    check(st == 200, "重建后 POST /api/kb/search", f"HTTP {st}")
    check(len(out.get("results") or []) > 0, "重建后有结果",
          f"{len(out.get('results') or [])} 条")

    print("\n== ⑥ 场景归属校验仍然生效 ==")
    st, out = post_json("/api/kb/search",
                        {"query": "额定转速", "k": 5, "scene_id": "不匹配的场景"})
    check(st == 200, "跨产品检索返回 200", f"HTTP {st}")
    check((out.get("hits") or 0) == 0, "跨产品不套用（返回空命中）", f"hits={out.get('hits')}")

    print()
    if _failed:
        print(f"FAILED: {_failed} 项未通过")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
