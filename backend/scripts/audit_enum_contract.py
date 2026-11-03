"""枚举契约审查：前端类型允许的取值 vs 后端实际产出的取值，做**双向差集**。

为什么需要这个脚本：
  2026-09-23 全量审查时发现 `artifact_kind` 前后端七值里**只有两个对得上**
  （后端 config-snapshot/requirement-baseline/run-artifact/verdict-table/gap-list/
  param-change/report-instance，前端却写成 precheck/timeline/measurements/
  tuning-record/report-draft）。后果：前端落盘时后 4 份产物被后端 409 拒掉，
  而调用处把异常 catch 空了 —— 界面上看不出任何问题，但「刷新后找回轮次」
  这项验收永远过不了。

  这类「枚举值不在对方集合里」的问题**编译不报错**（TS 联合类型只在本文件生效，
  后端是运行时校验），只能靠程序化比对发现。

双向差集的两个方向都要看：
  · 前端认了后端不产出 → 该分支永远走不到（死代码 / 误以为支持）
  · 后端产出了前端不认 → **数据被静默丢弃或整条请求 409**（更危险）

只读，不修改任何文件。
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
C = REPO / "c"

RE_STR = r"['\"]([^'\"]+)['\"]"


def ts_union(path: str, var: str) -> set[str]:
    """提取 TS 联合类型的字面量：`export type X = | 'a' | 'b'`（可跨多行）。"""
    p = C / path
    if not p.exists():
        return set()
    src = p.read_text(encoding="utf-8")
    m = re.search(rf"export type {var}\s*=(.*?)(?=\n\S|\n\s*\*/|\Z)", src, re.S)
    if not m:
        # 也可能写成 `export type X = 'a' | 'b'` 单行
        m = re.search(rf"export type {var}\s*=([^\n]+)", src)
    if not m:
        return set()
    return set(re.findall(RE_STR, m.group(1)))


def py_dict_keys(path: str, var: str) -> set[str]:
    """提取 Python 字典的键：`ARTIFACT_SCHEMAS = { "a": "a/v1", ... }`。"""
    p = C / path
    if not p.exists():
        return set()
    src = p.read_text(encoding="utf-8")
    m = re.search(rf"^{var}\s*=\s*\{{", src, re.M)
    if not m:
        return set()
    # 从 { 处做括号配对，避免被嵌套结构截断
    depth = 0
    body = ""
    for j in range(m.end() - 1, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                body = src[m.end() : j]
                break
    # 键行有缩进，必须用 ^\s* 而不是 ^（早期版本漏了这点，导致整个取值为空）
    return set(re.findall(rf"^[ \t]*{RE_STR}\s*:", body, re.M))


def py_literal_set(path: str, var: str) -> set[str]:
    """提取 Python 集合/元组的字面量：`_EVIDENCE_KINDS = {"a", "b"}` 或 `X = ("a", "b")`。"""
    p = C / path
    if not p.exists():
        return set()
    src = p.read_text(encoding="utf-8")
    m = re.search(rf"^{var}\s*[=:]\s*[\{{\(](.*?)[\}})]", src, re.S | re.M)
    if not m:
        return set()
    return set(re.findall(RE_STR, m.group(1)))


def py_values_of(path: str, key: str) -> set[str]:
    """用 AST 提取某个键/变量在后端实际可能取到的**全部字符串值**。

    覆盖三种产出形态，正则都会漏其中至少一种：
      1. 字典字面量：  {"type": "done", "reason": "error"}
      2. 变量赋值：    reason = "aborted"
      3. 三元表达式：  reason = "aborted" if ev.get("cancelled") else "complete"
         ← 第三种的 else 分支里藏着 complete，正则按行扫必然漏掉。

    用 AST 而不是正则，是为了拿到 IfExp 的 body 与 orelse 两支，
    且不会把 `ev.get("cancelled")` 这种无关字符串误当成取值。
    """
    p = C / path
    if not p.exists():
        return set()

    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()

    out: set[str] = set()

    def consts(node: ast.AST) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.add(node.value)
        elif isinstance(node, ast.IfExp):
            consts(node.body)
            consts(node.orelse)

    for node in ast.walk(tree):
        # {"reason": "..."}
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == key:
                    consts(v)
        # reason = "..."
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == key:
                    consts(node.value)
    return out


# ── 审查的枚举契约 ──
# (名称, 前端取值集, 后端取值集, 备注)
def contracts() -> list[tuple[str, set[str], set[str], str]]:
    return [
        (
            "artifact_kind（七份产物）",
            ts_union("web/src/features/flow-run/api.ts", "ArtifactKind"),
            py_dict_keys("backend/app/models/run.py", "ARTIFACT_SCHEMAS"),
            "主文档 656-661 行明列七值，后端为准；前端错值会导致 PUT 产物被 409 拒",
        ),
        (
            "evidence.kind（依据分类）",
            ts_union("web/src/features/agent-chat/types.ts", "EvidenceKind"),
            py_literal_set("backend/app/api/v1/agent_stream.py", "_EVIDENCE_KINDS"),
            "前端 EvidencePanel 的 ORDER 只认三值，不在集合里的条目不渲染",
        ),
        (
            "done.reason（收尾原因）",
            {"complete", "aborted", "error"},  # 前端 api.ts 的 done 分支判断
            py_values_of("backend/app/api/v1/agent_stream.py", "reason"),
            "前端按 reason 决定是否显示错误气泡",
        ),
        (
            "verdict.state（判定状态）",
            ts_union("web/src/features/flow-run/evaluate.ts", "VerdictState"),
            py_values_of("backend/app/services/evaluate.py", "state"),
            "判定放后端，前端预览与后端结果必须同枚举，否则覆盖时落空",
        ),
        (
            "run status（轮次状态机）",
            set(),  # 前端未定义联合类型，只报后端侧供参考
            py_literal_set("backend/app/models/run.py", "RUN_STATUSES"),
            "前端未类型化；仅列出后端取值，供核对 transition 的 to_status",
        ),
    ]


def main() -> int:
    print("=" * 74)
    print("枚举契约审查（双向差集）")
    print("=" * 74)

    total = 0
    for name, fe, be, note in contracts():
        print(f"\n── {name} ──")
        print(f"   说明：{note}")
        print(f"   前端取值({len(fe)}): {sorted(fe) if fe else '（未定义联合类型）'}")
        print(f"   后端取值({len(be)}): {sorted(be) if be else '（未采到）'}")

        if not fe:
            print("   → 跳过比对（前端未定义）")
            continue

        bad = 0
        for v in sorted(be - fe):
            print(f"   [严重] 后端产出「{v}」但前端不认 → 数据被丢弃或请求被拒")
            bad += 1
        for v in sorted(fe - be):
            print(f"   [提示] 前端认「{v}」但后端不产出 → 该分支走不到")
            bad += 1
        if bad == 0:
            print("   OK 两端取值一致")
        total += bad

    print("\n" + "=" * 74)
    print(f"合计问题数：{total}")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
