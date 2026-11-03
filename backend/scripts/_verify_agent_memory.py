"""验证助手记忆机制 + 轮内短路逻辑（纯函数级，不依赖真实模型/网络）。

覆盖：
1. AgentChatMemory 表可建（SQLite 临时库）。
2. get_history / append_turn 读写闭环：无→有→追加。
3. 超轮数裁剪（AGENT_CHAT_MEMORY_MAX_TURNS=8）丢最早一轮。
4. 答复截断（_MAX_REPLY_CHARS=2000）。
5. 无 session_id 不写、空内容不写。
6. 短路签名归一：字段顺序不同 → 同一签名；内容不同 → 不同签名。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 用临时 SQLite 库，避免污染真实库
_tmpdir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmpdir, 'test.db')}"

from sqlmodel import Session, SQLModel, create_engine  # noqa: E402
from app.models.agent_chat_memory import (  # noqa: E402
    AgentChatMemory,
    get_history,
    append_turn,
    _MAX_REPLY_CHARS,
)
from app.core.config import settings  # noqa: E402

_engine = create_engine(os.environ["DATABASE_URL"])


def check(name: str, cond: bool) -> bool:
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    return cond


def main() -> int:
    SQLModel.metadata.create_all(_engine)
    results = []

    # 1. 建表成功
    with Session(_engine) as s:
        results.append(check("建表 + 初始无历史", get_history(s, 1, "shell-a-init") is None))

    # 2. 写入一轮 → 读回
    with Session(_engine) as s:
        append_turn(s, 1, "shell-a-init", "Q1", "A1")
    with Session(_engine) as s:
        h = get_history(s, 1, "shell-a-init")
        results.append(check("写入一轮后读回 2 条", h is not None and len(h) == 2))
        results.append(check("读回 user 内容正确", h and h[0] == {"role": "user", "content": "Q1"}))
        results.append(check("读回 assistant 内容正确", h and h[1] == {"role": "assistant", "content": "A1"}))

    # 3. 追加第二轮
    with Session(_engine) as s:
        append_turn(s, 1, "shell-a-init", "Q2", "A2")
    with Session(_engine) as s:
        h = get_history(s, 1, "shell-a-init")
        results.append(check("追加后共 4 条", h is not None and len(h) == 4))

    # 4. 超轮数裁剪：MAX_TURNS=8，写 10 轮应只剩 8 轮（16 条）
    sid_crop = "shell-a-crop"
    with Session(_engine) as s:
        for i in range(10):
            append_turn(s, 1, sid_crop, f"Q{i}", f"A{i}")
    with Session(_engine) as s:
        h = get_history(s, 1, sid_crop)
        results.append(
            check(f"超轮数裁剪到 {settings.AGENT_CHAT_MEMORY_MAX_TURNS} 轮",
                  h is not None and len(h) == settings.AGENT_CHAT_MEMORY_MAX_TURNS * 2)
        )
        # 最早被丢，剩下应从 Q2..Q9（丢 Q0/Q1）
        results.append(check("裁剪丢的是最早一轮", h and h[0] == {"role": "user", "content": "Q2"}))

    # 5. 答复截断
    sid_trunc = "shell-a-trunc"
    long_a = "x" * (_MAX_REPLY_CHARS + 500)
    with Session(_engine) as s:
        append_turn(s, 1, sid_trunc, "Q", long_a)
    with Session(_engine) as s:
        h = get_history(s, 1, sid_trunc)
        results.append(
            check("答复截断到上限", h and len(h[1]["content"]) == _MAX_REPLY_CHARS)
        )

    # 6. 无 session_id 不写 / 空内容不写
    with Session(_engine) as s:
        append_turn(s, 1, "", "Q", "A")  # 无 key
        append_turn(s, 1, "shell-a-empty", "", "")  # 空内容
    with Session(_engine) as s:
        results.append(check("无 session_id 不落库", get_history(s, 1, "") is None))
        results.append(check("空内容不落库", get_history(s, 1, "shell-a-empty") is None))

    # 7. 短路签名归一（复现 agent_chat_service 里的 sig 生成逻辑）
    def sig(name, inp):
        return (name, json.dumps(inp, sort_keys=True, ensure_ascii=False, default=str))

    s1 = sig("KnowledgeSearch", {"question": "FU6815 PFC", "datasets": ["a", "b"]})
    s2 = sig("KnowledgeSearch", {"datasets": ["a", "b"], "question": "FU6815 PFC"})
    s3 = sig("KnowledgeSearch", {"question": "FU6832 PFC", "datasets": ["a", "b"]})
    results.append(check("字段顺序不同→同一签名", s1 == s2))
    results.append(check("内容不同→不同签名", s1 != s3))

    passed = sum(results)
    total = len(results)
    print(f"\n==== {passed}/{total} PASS ====")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
