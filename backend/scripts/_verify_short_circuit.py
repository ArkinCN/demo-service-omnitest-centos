"""验证轮内重复检索短路 + 无进展收口（monkeypatch _stream_model 与 run_tool，不碰网络）。

模拟：模型连续 3 轮都返回同一个 KnowledgeSearch tool_use（同参）。
预期：
- 第 1 次真实执行 run_tool（run_tool 被调 1 次）。
- 第 2、3 次被短路（run_tool 不再被调），tool_result 带 skipped 标记。
- 无进展达到阈值（AGENT_CHAT_NO_PROGRESS_LIMIT=2）后 force_finish 置位，下一轮起
  iter_tools 置空 → 模型被迫作答（stop_reason=end_turn）→ 收口 done。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio  # noqa: E402
import app.services.agent_chat_service as svc  # noqa: E402


# 统计 run_tool 真实执行次数 + 短路 tool_result 条数
real_run_count = 0
skipped_count = 0
collected_events = []


async def fake_run_tool(client, name, tinput):
    global real_run_count
    real_run_count += 1
    return f"检索结果 for {name}", [{"source": "doc-a", "title": "t", "url": ""}]


async def fake_stream_model(client, session, model, messages, tools, user_id, ip, context_summary):
    """模拟模型：只要还带 tools 就返回一个 tool_use；不带 tools 就返回纯文本收口。"""
    if tools:
        blocks = [
            {
                "type": "tool_use",
                "id": "tu-1",
                "name": "KnowledgeSearch",
                "input": {"question": "FU6815 PFC 最小脉宽", "datasets": ["a", "b"]},
            }
        ]
        yield {"type": "_result", "content_blocks": blocks, "stop_reason": "tool_use"}
    else:
        # 无工具 → 模型直接作答
        yield {"type": "content_delta", "text": "根据已有检索，答案是……"}
        yield {
            "type": "_result",
            "content_blocks": [{"type": "text", "text": "答案"}],
            "stop_reason": "end_turn",
        }


def check(name: str, cond: bool) -> bool:
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    return cond


async def main() -> int:
    # monkeypatch
    svc._stream_model = fake_stream_model
    import app.services.agent_tools as agent_tools

    agent_tools.run_tool = fake_run_tool

    # 伪造 client/session 参数（run_agent_chat 里 Session(engine) 需要 engine，但
    # 我们的 fake_stream_model 不用 session 对象；run_tool 也换成 fake 了，不会真开 DB）
    events = []
    async for ev in svc.run_agent_chat(
        client=None,
        user_id=1,
        user_message="查 FU6815 PFC 最小脉宽",
        history=None,
        model="deepseek-chat",
        ip=None,
        enabled_tools=["KnowledgeSearch"],
        context=None,
    ):
        events.append(ev)

    global real_run_count, skipped_count
    tool_results = [e for e in events if e.get("type") == "tool_result"]
    skipped_results = [e for e in tool_results if (e.get("summary") or {}).get("skipped")]
    done_events = [e for e in events if e.get("type") == "done"]
    content_deltas = [e for e in events if e.get("type") == "content_delta"]

    results = []
    results.append(check("真实 run_tool 只执行 1 次", real_run_count == 1))
    results.append(check("短路 tool_result 有 skipped 标记", len(skipped_results) >= 2))
    results.append(check("最终收口有 done", len(done_events) >= 1))
    results.append(check("收口后模型产出了正文", len(content_deltas) >= 1))

    passed = sum(results)
    total = len(results)
    print(f"\n==== {passed}/{total} PASS ====")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
