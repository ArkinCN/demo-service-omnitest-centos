"""验证「依据卡 → 知识库条目」链路的三处改动（2026-09-24）。

三件事：
1. system prompt 两条新规则是否两个分支都在（有工具 / 无工具）；
2. evidence 的 doc_id 是否从检索 sources 透传到前端事件；
3. 依据卡 title 与知识库条目 title 能否按规范化规则对上（决定「查看知识库条目」
   按钮点不点得动）。

只读不改：本脚本不写库、不调模型。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_failed = 0


def check(cond: bool, label: str, detail: str = "") -> bool:
    """断言并留痕。**必须返回 cond**（返回 None 会让调用方逻辑静默失效）。"""
    global _failed
    if cond:
        print(f"[OK]  {label}" + (f"  {detail}" if detail else ""))
    else:
        _failed += 1
        print(f"[NG]  {label}" + (f"  {detail}" if detail else ""))
    return cond


def norm_doc(s: str) -> str:
    """与前端 EvidencePanel.normDoc 同一套归一（去空白与连接/括号标点）。"""
    return re.sub(r"[\s\-_·・、，,。.：:()（）\[\]【】]", "", s or "").lower()


def main() -> int:
    from app.services.agent_chat_service import _build_system_prompt

    print("== ① system prompt 两条新规则 ==")
    with_tools = _build_system_prompt([{"name": "KnowledgeSearch"}])
    without = _build_system_prompt([])
    check("引用纪律" in with_tools, "有工具分支含【引用纪律】")
    check("引用纪律" in without, "无工具分支也含【引用纪律】（防「提前 return」旧坑）")
    check("禁止" in with_tools and "知识库未检索到" in with_tools,
          "明确禁止「知识库未检索到」这类误导措辞")
    check("页码或章节号" in with_tools, "要求写清确切出处（资料名 + 页码/章节）")

    print("\n== ② evidence doc_id 透传 ==")
    from app.api.v1.agent_stream import _sources_to_evidence

    raw = [{
        "title": "FU-AM-FOC 方案调试手册 第 27 页",
        "doc_id": "foc-debug-manual",
        "kind": "chunk",
        "excerpt": "5.6.1 注意事项…",
        "source": "[源] manuals/FU-AM-FOC方案调试手册-.pdf",
        "locator": "第 27 页 · 5.6.1 注意事项",
    }]
    ev = _sources_to_evidence(raw)[0]
    check(ev.get("doc_id") == "foc-debug-manual", "doc_id 透传到前端 evidence", str(ev.get("doc_id")))
    check(ev.get("href") is None, "本地知识库无 href（改由前端跳知识库页）")
    check(ev.get("kind") == "document", "kind 归一为 document", str(ev.get("kind")))

    print("\n== ③ 依据名 / 知识库条目名 匹配 ==")
    # 依据卡标题（截取到文档名部分）与知识库条目名，归一后应能互相包含
    card = "FU-AM-FOC 方案调试手册 第 27 页"
    entry = "FU-AM-FOC 方案调试手册"
    a, b = norm_doc(card), norm_doc(entry)
    check(bool(b) and (a == b or a.startswith(b) or b in a),
          "依据卡标题能匹配到知识库条目", f"{a!r} contains {b!r}")
    # 反向：不该把别的文档误配进来
    other = norm_doc("散热风扇单霍尔方案应用手册")
    check(not (other in a), "不会误配到无关文档", f"{other!r}")

    print()
    if _failed:
        print(f"FAILED: {_failed} 项未通过")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
