"""鉴权覆盖审查：检查路由函数是否挂了鉴权依赖。

做法：找到 `@router.xxx("/path")` 之后最近的 `def`/`async def`，取其**完整签名**
（可能跨多行），检查里面有没有鉴权相关的依赖或参数。

为什么只看装饰器不够：本项目有些路由把依赖写在函数参数默认值里
（`user_id: int = Depends(get_current_user_id)`），装饰器上是空的。

⚠️ 归属：本项目新增模块（agent_stream/kb/kb_entries/runs/interlocks/reports/
evaluate/tasks）若缺鉴权**应当修**；客户原有 28 个模块属既有设计
（且 AUTH_DISABLED 单机模式下不生效），本次**只记录不改**。

只读，不修改任何文件。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
V1 = BACKEND / "app" / "api" / "v1"

# 本项目新增的模块（客户原有 28 个模块不在其中，见文件头的归属说明）。
#
# ⚠️ **新增路由文件必须加进这个集合**，否则它永远不会被审计到——
# 2026-09-24 加 kb_documents.py 时就漏过一次：脚本照报「未挂鉴权 0 / 已查 28」，
# 看起来全绿，其实新文件的 5 个路由一个都没查。
# 加完后要跑一次确认「已查」的条数确实涨了，别只看 0 就放心。
OWN_MODULES = {
    "agent_stream.py", "kb.py", "kb_entries.py", "kb_documents.py", "runs.py",
    "interlocks.py", "reports.py", "evaluate.py", "tasks.py",
}

RE_DECORATOR = re.compile(r"@(\w+)\.(get|post|put|patch|delete)\(\s*[\"']([^\"']*)[\"']")
RE_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(")
# 鉴权特征：依赖函数或参数名里带 user / auth / current / token
RE_AUTH = re.compile(r"(get_current_user|current_user|Depends\(\s*\w*[Uu]ser|user_id\s*:|require_)")


def signature(lines: list[str], start: int) -> tuple[str, str]:
    """从 def 所在行开始，取到括号配对的完整签名。"""
    depth = 0
    buf: list[str] = []
    for j in range(start, len(lines)):
        buf.append(lines[j])
        depth += lines[j].count("(") - lines[j].count(")")
        if depth <= 0 and buf:
            break
    return " ".join(x.strip() for x in buf), lines[start].strip()


def main() -> int:
    print("=" * 74)
    print("鉴权覆盖审查（本项目新增模块）")
    print("=" * 74)

    missing: list[tuple[str, str, str]] = []
    checked = 0
    for f in sorted(V1.glob("*.py")):
        if f.name not in OWN_MODULES:
            continue
        lines = f.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            m = RE_DECORATOR.match(line.strip())
            if not m:
                continue
            # 找装饰器之后的第一个 def（中间可能有别的装饰器行）
            for j in range(i + 1, min(i + 8, len(lines))):
                dm = RE_DEF.match(lines[j])
                if dm:
                    sig, first = signature(lines, j)
                    checked += 1
                    path = m.group(3) or "/"
                    if not RE_AUTH.search(sig):
                        missing.append((f.name, f"{m.group(2).upper()} {path}", dm.group(1)))
                    break

    print(f"\n本项目新增模块共 {checked} 个路由，其中未挂鉴权依赖的 {len(missing)} 个：")
    for mod, route, fn in missing:
        print(f"   {mod:16} {route:34} 函数 {fn}")
    if not missing:
        print("   （无）")

    print("\n" + "=" * 74)
    print(f"小结：未挂鉴权 {len(missing)} / 已查 {checked}")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
