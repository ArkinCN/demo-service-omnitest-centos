"""验证「采纳落库」这条链路：写一份 param-change → 按场景取最近一轮 → 读回。

为什么要单独验一个 artifact_kind：
    七值里 `param-change` 是第一次被真正使用（流程 3 的 persistRun 落的五份里
    没有它）。它是 tune 流程的产物，主文档 4.1 收发表里就是这么定的，
    但「后端认不认这个 kind、读回来是不是同一份内容」必须实测——
    上一阶段的教训是：**看起来成功的写入，可能整份被 409 拒掉。**

本脚本复刻前端 `adoptApi.ts` 的两个动作：
    persistAdoption → PUT  /api/runs/{run_id}/param-change
    loadAdoption    → GET  /api/runs?scene_id=&limit=1 → GET /api/runs/{run_id}

用法：
    python scripts/verify_adopt_persist.py
    python scripts/verify_adopt_persist.py --base http://localhost:5173   # 经 vite 代理
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

ARTIFACT_KIND = "param-change"
_failed = 0


def check(cond: bool, label: str, detail: str = "") -> bool:
    """断言并留痕。**必须返回 cond**：调用方靠返回值决定走不走下一步。

    返回 None 会让 `if not check(...)` 恒为真，脚本在第一条用例后就悄悄退出，
    症状是「只输出第一行、退出码看着还正常」——这个坑踩过一次，别再犯。
    """
    global _failed
    if cond:
        print(f"[OK]  {label}" + (f"  {detail}" if detail else ""))
    else:
        _failed += 1
        print(f"[NG]  {label}" + (f"  {detail}" if detail else ""))
    return cond


def http(method: str, url: str, body: dict | None = None):
    data = None
    headers: dict[str, str] = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"message": raw[:200]}


def data_of(resp: dict | None):
    return (resp or {}).get("data")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8011")
    ap.add_argument("--scene", default="motor.cooling-fan.fortior-fu6832")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    print("=" * 74)
    print(f"采纳落库端到端验证   目标：{base}")
    print("=" * 74)

    # 1 · 建一轮（采纳要挂在轮次上）
    code, resp = http("POST", f"{base}/api/runs", {"scene_id": args.scene, "mode": "mock"})
    run = data_of(resp) or {}
    if not check(code == 200 and run.get("run_id"),
                 "建轮次 POST /api/runs", f"HTTP {code} {resp.get('message', '')}"):
        return 1
    run_id = run["run_id"]
    print(f"      run_id={run_id}")

    # 2 · 写 param-change（后端七值白名单里必须有它，否则 409）
    items = [
        {"key": "speed_kp", "name": "速度环 Kp", "from": "120", "to": "150"},
        {"key": "deadtime", "name": "死区时间", "from": "1.5", "to": "2.0"},
    ]
    content = {
        "items": items,
        "count": len(items),
        "operator": "张工",
        "adopted_at": "2026-09-24T00:00:00.000Z",
        "note": "采纳记录：人勾选的建议值。",
    }
    code, resp = http("PUT", f"{base}/api/runs/{run_id}/{ARTIFACT_KIND}", {"content": content})
    art = data_of(resp) or {}
    check(code == 200, f"写产物 PUT /api/runs/{{id}}/{ARTIFACT_KIND}",
          f"HTTP {code} {resp.get('message', '')}")
    check(art.get("artifact_kind") == ARTIFACT_KIND, "产物 kind 回显正确", str(art.get("artifact_kind")))

    # 3 · 按场景取最近一轮（刷新后 runId 已丢，靠这一步定位）
    code, resp = http("GET", f"{base}/api/runs?scene_id={args.scene}&limit=1")
    runs = data_of(resp) or []
    check(code == 200 and runs and runs[0].get("run_id") == run_id,
          "按场景取最近一轮 GET /api/runs", f"HTTP {code} 命中 {len(runs)} 条")

    # 4 · 读回整轮产物，从中挑 param-change
    code, resp = http("GET", f"{base}/api/runs/{run_id}")
    got = data_of(resp) or {}
    artifacts = got.get("artifacts") or []
    hit = next((a for a in artifacts if a.get("artifact_kind") == ARTIFACT_KIND), None)
    check(code == 200 and hit is not None, "刷新后读回 param-change", f"HTTP {code}")

    if hit:
        back = hit.get("content") or {}
        check(back.get("count") == len(items), "条目数与写入一致",
              f"{back.get('count')} vs {len(items)}")
        keys = [i.get("key") for i in back.get("items") or []]
        check(keys == [i["key"] for i in items], "条目内容逐项一致", str(keys))
        check(back.get("operator") == "张工", "采纳人署名保留", str(back.get("operator")))

    # 5 · 覆盖写：重复采纳不应堆出第二条
    content2 = dict(content, items=items[:1], count=1)
    code, _ = http("PUT", f"{base}/api/runs/{run_id}/{ARTIFACT_KIND}", {"content": content2})
    code2, resp2 = http("GET", f"{base}/api/runs/{run_id}")
    arts2 = (data_of(resp2) or {}).get("artifacts") or []
    n = sum(1 for a in arts2 if a.get("artifact_kind") == ARTIFACT_KIND)
    check(code == 200 and n == 1, "重复采纳为覆盖而非堆叠", f"同 kind 产物 {n} 条")

    # 不清理：后端还没有删轮次的路由，与其写一段假装删除的代码，
    # 不如如实留下这条测试轮次，人在界面上还能顺手看一眼产物。
    print(f"      （测试轮次 {run_id} 保留在库内；后端暂无删轮次接口，未做假清理）")

    print("=" * 74)
    print("结论：本轮用例全部通过" if not _failed else f"结论：{_failed} 项未通过")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
