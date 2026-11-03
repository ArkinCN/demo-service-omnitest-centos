"""清理文档与注释里残留的旧仓库路径引用（一次性脚本，用完可留作备查）。

清理对象：
  c        →  c          （旧仓库相对写法）
  c →  c          （旧仓库绝对写法，含用户名）
  [源] ...            →  [源] ...    （其他家目录引用，脱敏）

为什么单独一个脚本：主清洗工具（clean_linux_paths.py）追求通用与可复用，
这些是「特定旧仓库名」的历史残留，用一次性脚本处理更直接，也便于在书面记录里
说明「到底改了什么」。

只处理 .md / .ts / .tsx / .js / .mjs / .py 这些文本载体，不碰数据 JSON
（数据 JSON 的路径已由主工具处理完）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
C_ROOT = REPO / "c"
SKIP = {"node_modules", "target", ".git", "dist", "__pycache__", ".venv", "venv", ".next"}
SUFFIXES = {".md", ".ts", ".tsx", ".js", ".mjs", ".py", ".txt"}

# 顺序有讲究：先替换更长的 c，再处理裸 c，
# 否则短模式先命中会把长模式拆坏。
RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"c"), "c"),
    (re.compile(r"c"), "c"),
    (re.compile(r"[源] "), "[源] "),
    (re.compile(r"[源] "), "[源] "),
]


def main() -> int:
    changed = 0
    total_hits = 0
    for p in sorted(C_ROOT.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in SUFFIXES:
            continue
        if any(part in SKIP for part in p.parts):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        new = text
        hits = 0
        for pat, repl in RULES:
            new, n = pat.subn(repl, new)
            hits += n
        if hits == 0:
            continue

        p.write_text(new, encoding="utf-8")  # UTF-8 无 BOM
        changed += 1
        total_hits += hits
        print(f"[FIXED] {p.relative_to(REPO)}  [{hits} 处]")

    print(f"\n共改动 {changed} 个文件、{total_hits} 处旧仓库引用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
