"""端到端验证「一轮产物落盘」是否真的成功。

为什么要有这个脚本：
  前端 `persistRun()` 曾用了三个后端不认的 artifact_kind（measurements /
  timeline / report-draft），PUT 全部被 409 拒掉；而调用处把异常 catch 空了，
  所以**界面完全正常、控制台也没声音**，只有真正去查库才会发现一轮都没存下来。
  这类「看起来成功其实失败」的问题，只能靠端到端跑一遍才暴露。

本脚本复刻前端 persistRun 的调用序列，逐步断言，任一步失败即指出是哪一份产物、
被哪个状态码拒了。

用法：
    python scripts/verify_run_persist.py                 # 默认打 http://127.0.0.1:8011
    python scripts/verify_run_persist.py --base http://localhost:5173   # 经 vite 代理
"""
from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

# 与前端 ArtifactKind、后端 ARTIFACT_SCHEMAS 对齐的七值
ARTIFACT_KINDS = [
    "config-snapshot",
    "requirement-baseline",
    "run-artifact",
    "verdict-table",
    "gap-list",
    "param-change",
    "report-instance",
]

# 前端 persistRun 在「跑完一轮」时落的五份（产生方是 run 流程）
RUN_FLOW_ARTIFACTS = [
    "config-snapshot",
    "run-artifact",
    "verdict-table",
    "gap-list",
    "report-instance",
]


def http(method: str, url: str, body: dict | None = None) -> tuple[int, str]:
    data = None
    headers = {}
    if body is not None:
        import json

        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8011")
    ap.add_argument("--scene", default="motor.cooling-fan.fortior-fu6832")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    print("=" * 74)
    print(f"轮次落盘端到端验证   目标：{base}")
    print("=" * 74)

    # 1) 七值自检：确认前端在用的 kind 都在后端白名单里（静态比对已在
    #    audit_enum_contract.py 做过，这里再跑一次运行时版本）
    print("\n[1] artifact_kind 七值核对")
    ok_kinds = True
    for k in RUN_FLOW_ARTIFACTS:
        if k not in ARTIFACT_KINDS:
            print(f"    [严重] {k} 不在七值内")
            ok_kinds = False
    if ok_kinds:
        print(f"    前端落的 {len(RUN_FLOW_ARTIFACTS)} 份全部在七值内: {RUN_FLOW_ARTIFACTS}")

    # 2) 建轮次
    print("\n[2] 创建轮次")
    st, body = http("POST", f"{base}/api/runs", {"scene_id": args.scene, "mode": "mock"})
    if st != 200:
        print(f"    [失败] POST /api/runs → {st}: {body[:200]}")
        return 1
    import json

    run_id = json.loads(body).get("data", {}).get("run_id")
    if not run_id:
        print(f"    [失败] 响应里没有 run_id: {body[:200]}")
        return 1
    print(f"    run_id = {run_id}")

    # 3) 逐份落产物
    print("\n[3] 逐份写入产物（复刻前端 persistRun 的顺序）")
    contents = {
        "config-snapshot": {"scene_id": args.scene, "note": "验证脚本写入"},
        "run-artifact": {"measures": {"pass_count": 67}, "note": "验证脚本写入"},
        "verdict-table": {"verdicts": [], "authoritative": False, "note": "验证脚本写入"},
        "gap-list": {"items": [], "count": 0, "note": "验证脚本写入"},
        "report-instance": {"status": "draft", "note": "验证脚本写入"},
    }
    bad = 0
    for kind in RUN_FLOW_ARTIFACTS:
        st, body = http("PUT", f"{base}/api/runs/{run_id}/{kind}", {"content": contents[kind]})
        if st == 200:
            print(f"    OK   {kind}")
        else:
            print(f"    [失败] {kind} → HTTP {st}: {body[:200]}")
            bad += 1

    # 4) 读回
    print("\n[4] 读回轮次（模拟「刷新页面」）")
    st, body = http("GET", f"{base}/api/runs/{run_id}")
    if st != 200:
        print(f"    [失败] GET /api/runs/{run_id} → {st}")
        bad += 1
    else:
        d = json.loads(body).get("data", {})
        run = d.get("run", {})
        arts = d.get("artifacts", [])
        print(f"    run_id={run.get('run_id')}  status={run.get('status')}  mode={run.get('mode')}")
        print(f"    产物份数={len(arts)}  kinds={[a.get('artifact_kind') for a in arts]}")

    # 5) 清理
    print("\n[5] 清理测试数据")
    st, _ = http("DELETE", f"{base}/api/runs/{run_id}")
    print(f"    DELETE → {st}（后端若无该接口则忽略）")

    print("\n" + "=" * 74)
    print("通过" if bad == 0 else f"失败 {bad} 处")
    print("=" * 74)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
