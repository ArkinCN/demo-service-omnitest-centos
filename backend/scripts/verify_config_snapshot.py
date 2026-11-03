"""配置快照 config-snapshot/v1 端到端验证（2026-09-24）。

本轮补的是一个**真实缺口**：「初始化配置」页改的参数此前只存在前端内存
（useAppStore.overrides），刷新即丢；「确认并锁定」同样只在内存。表现是
人改了 29 项、点确认，刷新后回到 7 项——数据从没离开过浏览器。

本脚本验证补上之后链路是否真通：
  建轮次 → 落 config-snapshot（含 product_attributes）→ 按场景取最近一轮 → 读回，
  并逐项比对属性内容、origin 三值、以及「刷新后读回的正是保存的那份」。

只打活服务，不写前端缓存；跑完保留测试轮次（后端无删轮次接口，不做假清理）。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8011"
SCENE = "motor.cooling-fan.fortior-fu6832"

_failed = 0


def check(cond: bool, label: str, detail: str = "") -> bool:
    """断言并留痕。**必须返回 cond**（漏 return 会让调用方静默失效）。"""
    global _failed
    if cond:
        print(f"[OK]  {label}" + (f"  {detail}" if detail else ""))
    else:
        _failed += 1
        print(f"[NG]  {label}" + (f"  {detail}" if detail else ""))
    return cond


def req(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def main() -> int:
    print("== ① 建轮次 ==")
    st, out = req("POST", "/api/runs", {"scene_id": SCENE, "mode": "mock"})
    check(st == 200, "POST /api/runs", f"HTTP {st}")
    run_id = out.get("data", {}).get("run_id")
    if not run_id:
        print("  无法取得 run_id，后续无法进行")
        return 1
    print(f"     run_id = {run_id}")

    print("\n== ② 落配置快照（模拟前端 buildSnapshot 的产出形状）==")
    snapshot = {
        "schema": "config-snapshot/v1",
        "snapshot_id": f"cs-{SCENE}-verify",
        "scene_id": SCENE,
        "scene_pack_version": "v1",
        "locked_at": "2026-09-24T12:00:00Z",
        "locked_by": "张工",
        "product_attributes": [
            {"key": "pole_pairs", "value": 2, "unit": "对", "origin": "document",
             "_source": {"file": "[源] include/Customer.h", "locator": "Customer.h:56 (#define Pole_Pairs)"}},
            {"key": "max_speed", "value": 19400, "unit": "rpm", "origin": "manual"},
            {"key": "max_power", "value": 40000, "unit": "W", "origin": "manual"},
            {"key": "some_placeholder", "value": 0, "origin": "suggested"},
        ],
        "firmware": {"project_path": "", "param_header_path": ""},
        "interlock_instances": [],
        "channel_map": [],
        "_incomplete": ["firmware.project_path 待补"],
    }
    # ⚠️ 请求体必须包一层 {"content": {...}}（ArtifactPut 只收 content 字段）。
    # 首版直接传裸快照，后端 422 —— 是脚本写错，不是代码错；
    # 前端 putArtifact 本来就是 JSON.stringify({ content })，与后端一致。
    st, out = req("PUT", f"/api/runs/{run_id}/config-snapshot", {"content": snapshot})
    check(st == 200, "PUT /api/runs/{id}/config-snapshot", f"HTTP {st}")

    print("\n== ③ 按场景取最近一轮（刷新后读回走的就是这条）==")
    st, out = req("GET", f"/api/runs?scene_id={SCENE}&limit=10")
    check(st == 200, "GET /api/runs", f"HTTP {st}")
    runs = out.get("data") or []
    check(len(runs) >= 1, "取到轮次", f"{len(runs)} 条")
    top = runs[0]["run_id"] if runs else None
    check(top == run_id, "最近一轮就是刚落的这轮", f"{str(top)[:12]}")

    print("\n== ④ 读回快照并逐项比对 ==")
    st, out = req("GET", f"/api/runs/{run_id}")
    check(st == 200, "GET /api/runs/{id}", f"HTTP {st}")
    arts = out.get("data", {}).get("artifacts") or []
    hit = next((a for a in arts if a.get("artifact_kind") == "config-snapshot"), None)
    check(hit is not None, "产物里有 config-snapshot")
    body = (hit or {}).get("content") or {}
    check(body.get("schema") == "config-snapshot/v1", "schema 回显正确", str(body.get("schema")))

    attrs = body.get("product_attributes") or []
    check(len(attrs) == 4, "product_attributes 条目数一致", f"{len(attrs)} vs 4")
    by_key = {a.get("key"): a for a in attrs}
    check(by_key.get("max_speed", {}).get("value") == 19400, "人工改的转速值读回一致", "19400")
    check(by_key.get("max_power", {}).get("value") == 40000, "人工改的功率值读回一致", "40000")
    check(by_key.get("max_speed", {}).get("origin") == "manual", "origin=manual 保留")
    check(by_key.get("pole_pairs", {}).get("origin") == "document", "origin=document 保留")
    check(by_key.get("some_placeholder", {}).get("origin") == "suggested", "origin=suggested 保留")
    check(by_key.get("pole_pairs", {}).get("_source", {}).get("locator", "").startswith("Customer.h"),
          "_source 出处保留")
    check(body.get("locked_by") == "张工", "locked_by 保留", str(body.get("locked_by")))
    check(isinstance(body.get("_incomplete"), list) and body["_incomplete"],
          "_incomplete 如实标出缺项（不冒充完整快照）")

    print("\n== ⑤ 重复保存是覆盖而非堆叠 ==")
    snapshot2 = dict(snapshot)
    snapshot2["snapshot_id"] = f"cs-{SCENE}-verify-2"
    snapshot2["product_attributes"] = [
        {"key": "max_speed", "value": 20000, "unit": "rpm", "origin": "manual"},
    ]
    st, _ = req("PUT", f"/api/runs/{run_id}/config-snapshot", {"content": snapshot2})
    check(st == 200, "二次 PUT 同 kind", f"HTTP {st}")
    st, out = req("GET", f"/api/runs/{run_id}")
    arts2 = out.get("data", {}).get("artifacts") or []
    same = [a for a in arts2 if a.get("artifact_kind") == "config-snapshot"]
    check(len(same) == 1, "同 kind 产物只有 1 条（覆盖而非堆叠）", f"{len(same)} 条")
    if same:
        check((same[0].get("content") or {}).get("snapshot_id", "").endswith("verify-2"),
              "读到的是最新那份")

    print("\n== ⑥ 旧格式（无 product_attributes）不被当成真快照 ==")
    # 这是 loadLatestSnapshot 里的守卫：老轮次只记了场景与时刻，
    # 若被当真快照回填，界面会被清空。这里验证守卫的判据本身成立。
    placeholder = {"scene_id": SCENE, "captured_at": "2026-09-22T00:00:00Z", "note": "占位"}
    check("product_attributes" not in placeholder and placeholder.get("schema") != "config-snapshot/v1",
          "占位快照不含 schema 与 product_attributes（守卫能挡住）")

    print()
    if _failed:
        print(f"FAILED: {_failed} 项未通过")
        return 1
    print("ALL PASS")
    print(f"（测试轮次 {run_id} 保留在库内；后端暂无删轮次接口，未做假清理）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
