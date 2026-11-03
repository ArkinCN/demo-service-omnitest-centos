"""构建/重建知识库向量索引（阶段 3 补全）。

用法：
    python scripts/build_kb_vector_index.py            # 陈旧才重建
    python scripts/build_kb_vector_index.py --force    # 强制重建
    python scripts/build_kb_vector_index.py --probe    # 只看现状

为什么要一个脚本而不是只靠在线路径：
  向量索引是**一次性成本**（577+ 单元起步），应当在部署/资料更新时显式构建，
  而不是让第一个检索请求去等它。运维与验收都需要一个可重复执行的入口。
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from app.services.kb_embed_service import (  # noqa: E402
    build,
    corpus_to_rows,
    index_stale,
    probe,
)
from app.services.kb_search import get_engine  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="不看陈旧与否，强制重建")
    ap.add_argument("--probe", action="store_true", help="只打印现状，不建")
    args = ap.parse_args()

    if args.probe:
        import json
        print(json.dumps(probe(), ensure_ascii=False, indent=2))
        return 0

    engine = get_engine()
    rows = corpus_to_rows(engine.corpus)
    print(f"语料单元：{len(rows)}")

    stale, reason = index_stale(len(rows))
    print(f"索引陈旧：{stale}（{reason or '最新'}）")
    if not stale and not args.force:
        print("索引已是最新，未重建（如需强制重建加 --force）")
        return 0

    res = build(rows)
    if not res.get("ok"):
        # 失败必须可见：把原因打出来并以非零码退出，让 CI/运维能发现
        print(f"[FAIL] 建索引失败：{res.get('error')}")
        return 1
    print(f"[ok] 索引已构建：tier={res.get('tier')} dim={res.get('dim')} "
          f"count={res.get('count')}")

    # 建完立刻复核一次：陈旧判定应转为「最新」
    stale2, reason2 = index_stale(len(rows))
    print(f"复核陈旧：{stale2}（{reason2 or '最新'}）")
    return 0 if not stale2 else 1


if __name__ == "__main__":
    sys.exit(main())
