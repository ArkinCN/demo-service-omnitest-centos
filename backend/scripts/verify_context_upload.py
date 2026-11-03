"""验证上下文包上送：前端发得出来、后端收得到、换了任务摘要跟着变。

覆盖主文档 3.2.2 与阶段 3 验收 5「换任务后上下文跟着变」。

分三层，缺一不可：
  ① 单元：build_context_summary 对不同 envelope 产出不同摘要（不花钱、秒级）
  ② 兼容：请求不带 context 时行为不变（防改坏老通路）
  ③ 端到端：带两份不同 context 各问一句「现在在测什么产品、在哪个流程」，
     两次回答里应各自出现对应的产品名 / 流程名（**真调模型，会耗额度**）

为什么③必须真跑：只验证「字段没被拒」是不够的——字段收下但没进 system prompt，
模型照样不知道当前在测什么，界面上却一切正常。这与本项目吃过的最大的亏
（「界面正常」≠「功能正常」）是同一类。

用法：
    python scripts/verify_context_upload.py              # ①+②（不花钱）
    python scripts/verify_context_upload.py --live       # 再加③（真调模型）
    python scripts/verify_context_upload.py --live --base http://localhost:5173
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

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


def envelope(scene_id: str, product: str, flow: str, flow_label: str,
             kb_sel=None, fail_sel=None) -> dict:
    """构造一份与前端 buildEnvelope 同形状的 envelope（够验摘要即可）。"""
    return {
        "envelope_version": "1",
        "action": None,
        "session": {"session_id": f"shell-{scene_id}-{flow}", "operator": "张工",
                    "started_at": "2026-09-24T00:00:00Z", "transcript_summary": None},
        "product": {"scene_id": scene_id, "taxonomy_path": ["电机", "散热风扇", product],
                    "taxonomy_name": f"电机 / 散热风扇 / {product}", "product_name": product},
        "flow": {"id": flow, "label": flow_label, "step": None, "confirmed": {}},
        "zoneB": {
            "selected_document": kb_sel,
            "selected_fail_item": fail_sel,
            "selected_candidate": None,
            "values": {}, "missing": [], "placeholders": [],
        },
        "zoneC": {"view": "grid", "selected_node": None},
        "lastRun": None,
        "history": None,
        "kb": {"hits": []},
        "policy": {"permission": "readonly", "auto_run": True, "redline_actions": []},
    }


def unit_layer() -> None:
    print("=" * 74)
    print("① 单元：摘要生成")
    print("=" * 74)
    from app.services.agent_context import build_context_summary

    a = build_context_summary(envelope("s1", "FU6832 散热风扇驱动板", "run", "启动测试"))
    b = build_context_summary(envelope("s2", "电动玻璃升降器", "tune", "调优确认"))
    print(f"  摘要 A（散热风扇 / run）：\n    " + a.replace("\n", "\n    "))
    print(f"  摘要 B（玻璃升降器 / tune）：\n    " + b.replace("\n", "\n    "))

    check(bool(a) and bool(b), "两份 envelope 都能产出摘要")
    check("FU6832 散热风扇驱动板" in a, "摘要 A 含产品名")
    check("电动玻璃升降器" in b, "摘要 B 含产品名")
    check("启动测试" in a and "调优确认" in b, "流程名各自正确")
    check(a != b, "换任务后摘要确实不同（这是验收的关键）")

    # 选中项要进摘要
    c = build_context_summary(
        envelope("s1", "FU6832 散热风扇驱动板", "tune", "调优确认",
                 kb_sel="DOC-MAN-001", fail_sel="TR-START-01")
    )
    check("DOC-MAN-001" in c, "选中的文档进摘要", "zoneB.selected_document")
    check("TR-START-01" in c, "选中的未达标判据进摘要", "zoneB.selected_fail_item")

    # 空 / 空字典 → 空串（不是报错）
    check(build_context_summary(None) == "", "envelope 为 None 时返回空串（向后兼容）")
    check(build_context_summary({}) == "", "envelope 为空字典时返回空串")


def http_layer(base: str) -> None:
    print("=" * 74)
    print("② 兼容：不带 context 的旧请求仍然可用")
    print("=" * 74)
    body = {
        "text": "只回一个字：好",
        "model": "deepseek-v4-flash",
        "permission": "readonly",
        "auto_run": True,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/agent/stream", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8", "replace")
        ok = "message_delta" in raw or "done" in raw
        check(ok, "不带 context 仍返回事件流", f"HTTP 200，收到 {len(raw)} 字节")
    except Exception as e:
        check(False, "不带 context 仍返回事件流", str(e))


def live_layer(base: str) -> None:
    print("=" * 74)
    print("③ 端到端：换任务后模型的回答跟着变（真调模型，耗额度）")
    print("=" * 74)

    def ask(env: dict, question: str) -> str:
        body = {
            "text": question,
            "model": "deepseek-v4-flash",
            "permission": "readonly",
            "auto_run": True,
            "session_id": env["session"]["session_id"],
            "context": env,
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/api/agent/stream", data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=180) as r:
            raw = r.read().decode("utf-8", "replace")
        # 拼回正文：只取 message_delta 的 delta
        text = []
        for line in raw.splitlines():
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except Exception:
                continue
            if ev.get("type") == "message_delta":
                text.append(ev.get("delta", ""))
            if ev.get("type") == "done" and ev.get("reason") == "error":
                text.append(f"[error]{ev.get('message', '')}")
        return "".join(text)

    q = "只根据你拿到的现场上下文回答：我现在测的产品叫什么、在哪个流程？不要检索，一句话答。"
    a = ask(envelope("s1", "FU6832 散热风扇驱动板", "run", "启动测试"), q)
    b = ask(envelope("s2", "电动玻璃升降器", "tune", "调优确认"), q)
    print(f"  回答 A：{a[:180]}")
    print(f"  回答 B：{b[:180]}")

    check(bool(a) and not a.startswith("[error]"), "请求 A 正常返回", a[:60])
    check(bool(b) and not b.startswith("[error]"), "请求 B 正常返回", b[:60])
    check("FU6832" in a or "散热风扇" in a, "回答 A 提到了 A 的产品")
    check("玻璃升降器" in b, "回答 B 提到了 B 的产品")
    check(a != b, "两次回答不同（上下文确实生效）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8011")
    ap.add_argument("--live", action="store_true", help="真调模型（耗额度）")
    args = ap.parse_args()

    unit_layer()
    http_layer(args.base.rstrip("/"))
    if args.live:
        live_layer(args.base.rstrip("/"))
    else:
        print("-" * 74)
        print("（跳过③：加 --live 才真调模型）")

    print("=" * 74)
    print("结论：本轮用例全部通过" if not _failed else f"结论：{_failed} 项未通过")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
