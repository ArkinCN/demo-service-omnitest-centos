"""修复前两轮清洗过度造成的文档损坏。

问题来源：上一轮 `clean_legacy_repo_refs.py` 把
    ~/lab/agent-test-web  →  c
    /home/zzz/agent-test-web →  c
但在某些文档里，原串是 `~/lab/agent-test-web/c`（仓库里的 c 子目录），
替换后变成 `c/c`；再叠加 `~/lab/` → `[源] ` 的规则，最终产出了
    `c/`
这类**无意义、且不可执行的命令片段**（例如 `cd c/`）。

修法：把这些已知的损坏形态按语义还原成**仓库相对路径**，让文档里的命令
真的能跑。文档里的路径是给人看的描述，写 `c/` 就够，不需要脱敏成 `[源]`。

处理的损坏形态：
    c/              →  c/
    cd c/           →  cd c
    c/components/spike-device-mcp →  c/components/spike-device-mcp
    c/xxx   →  c/xxx
    [源] 20260919-通用Agent…  →  docs/…（去掉前缀，保留文件名）
    (工作区) …        →  （去掉前缀）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
C_ROOT = REPO / "c"
SKIP = {"node_modules", "target", ".git", "dist", "__pycache__", ".venv", "venv", ".next"}
SUFFIXES = {".md", ".ts", ".tsx", ".js", ".mjs", ".py", ".txt"}

# 顺序有讲究：更具体的形态先处理
RULES: list[tuple[re.Pattern[str], str]] = [
    # 仓库根：把所有叠加形态统一成 `c/`
    (re.compile(r"\[源\]\s*\[源\]\s*c\b"), "c/"),
    # 桥组件：`c/components/spike-device-mcp` → 仓库内真实位置
    (re.compile(r"\[源\]\s*lab/spike-device-mcp"), "c/components/spike-device-mcp"),
    # 其他 lab 子组件
    (re.compile(r"\[源\]\s*lab/(timeseries|workflow|agent-chat|webssh|dsh-plugins|kb-pipeline)"),
     r"c/components/\1"),
    # 旧仓库名残留
    (re.compile(r"\[源\]\s*agent-test-web/?\.bak-src-[\w\-]+"), "（见交付包内备份）"),
    (re.compile(r"\[源\]\s*agent-test-web"), "c"),
    # 交接文档目录：保留文件名，去掉主机前缀
    (re.compile(r"\[源\]\s*(2026\d{4}-[^/\s`，。；]+/)"), r"docs/\1"),
    (re.compile(r"\[源\]\s*scratchpad/"), "(工作区) "),
    # 兜底：孤立的 `[源] ` 后紧跟中文文件名时，只去掉标记，保留文件名
    (re.compile(r"\[源\]\s+(?=[\u4e00-\u9fff])"), ""),
]


def main() -> int:
    changed = 0
    hits_total = 0
    for p in sorted(C_ROOT.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in SUFFIXES:
            continue
        if any(part in SKIP for part in p.parts):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "[源]" not in text:
            continue

        new = text
        hits = 0
        for pat, repl in RULES:
            new, n = pat.subn(repl, new)
            hits += n
        if hits == 0 or new == text:
            continue

        p.write_text(new, encoding="utf-8")
        changed += 1
        hits_total += hits
        print(f"[FIXED] {p.relative_to(REPO)}  [{hits} 处]")

    print(f"\n修复 {changed} 个文件、{hits_total} 处过度脱敏")

    # 复核：还有没有 `[源] [源]` 这种叠加残留
    left = 0
    for p in C_ROOT.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in SUFFIXES:
            continue
        if any(part in SKIP for part in p.parts):
            continue
        try:
            t = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        n = t.count("[源] [源]") + t.count("[源][源]")
        if n:
            print(f"  残留 {p.relative_to(REPO)}: {n} 处")
            left += n
    print(f"叠加残留检查：{left} 处" + ("（已清零）" if left == 0 else "（需人工看）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
