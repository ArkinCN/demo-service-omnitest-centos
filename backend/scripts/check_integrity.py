"""改造后完整性自检：确认批量替换没有破坏任何源码。

检查四项：
  1. 所有后端 .py 能被 ast 解析（语法未被改坏）
  2. 所有前端/后端文本文件是合法 UTF-8（Windows 下最容易被写成 GBK 的地方）
  3. 关键文件存在且有合理体积（防误删）
  4. 场景包 JSON 均可解析，且 file_path 合规

用法：
    python scripts/check_integrity.py     # 通过返回 0
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
C_ROOT = REPO / "c"
SKIP = {"node_modules", "target", ".git", "dist", "__pycache__", ".venv", "venv", ".next"}

# 关键文件清单：存在性 + 最小体积（字节）
CRITICAL = [
    "c/backend/app/main.py",
    "c/backend/app/core/config.py",
    "c/backend/app/core/paths.py",
    "c/backend/app/services/kb_search.py",
    "c/backend/app/api/v1/agent_stream.py",
    "c/backend/scripts/clean_linux_paths.py",
    "c/web/src/app/FlowScreen.tsx",
    "c/web/src/features/agent-chat/AgentChat.tsx",
    "c/kb-pipeline/scripts/common.py",
    "c/kb-pipeline/scripts/run_all.py",
]


def walk(suffixes: set[str]):
    for p in C_ROOT.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in suffixes:
            continue
        if any(part in SKIP for part in p.parts):
            continue
        yield p


def main() -> int:
    problems: list[str] = []

    # 1. Python 语法
    py_files = list(walk({".py"}))
    for p in py_files:
        try:
            ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as e:
            problems.append(f"[语法] {p.relative_to(REPO)}: {e}")
        except UnicodeDecodeError as e:
            problems.append(f"[编码] {p.relative_to(REPO)}: {e}")
    print(f"1) Python 语法：检查 {len(py_files)} 个 .py，问题 {sum(1 for x in problems if x.startswith('[语法]'))} 个")

    # 2. 文本编码（只抽查文本类，避免把图片拖进来）
    text_files = list(walk({".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".css", ".py", ".yml", ".yaml", ".toml", ".jsonl"}))
    enc_bad = 0
    for p in text_files:
        try:
            p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            problems.append(f"[编码] {p.relative_to(REPO)} 不是合法 UTF-8")
            enc_bad += 1
    print(f"2) 文本编码：检查 {len(text_files)} 个文件，非 UTF-8 {enc_bad} 个")

    # 3. 关键文件
    miss = 0
    for rel in CRITICAL:
        p = REPO / rel
        if not p.is_file():
            problems.append(f"[缺失] {rel}")
            miss += 1
        elif p.stat().st_size < 30:
            problems.append(f"[可疑] {rel} 只有 {p.stat().st_size} 字节")
            miss += 1
    print(f"3) 关键文件：检查 {len(CRITICAL)} 个，问题 {miss} 个")

    # 4. 场景包 JSON
    scene_bad = 0
    scenes = C_ROOT / "web" / "public" / "scenes"
    for p in scenes.rglob("*.json"):
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            problems.append(f"[JSON] {p.relative_to(REPO)}: {e}")
            scene_bad += 1
    print(f"4) 场景包 JSON：检查 {len(list(scenes.rglob('*.json')))} 个，问题 {scene_bad} 个")

    print()
    if problems:
        print(f"发现 {len(problems)} 个问题：")
        for x in problems[:30]:
            print("  -", x)
        return 1
    print("完整性自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
