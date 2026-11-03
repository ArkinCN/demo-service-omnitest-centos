"""知识库转化流水线 · 全量重跑（原 run_all.sh 的跨平台 Python 版）。

为什么改写：原脚本是 bash，Windows 上跑不了（本项目的交付形态是纯 Windows）。
Python 版在 Windows / macOS / Linux 上行为一致，且能直接复用同目录的 .py 步骤。

与原 bash 版的行为对齐点：
- **步骤顺序一致**：02 先跑（供文档实体抽取比对宏名），再 01 → 03 → 04 → 05 → 06 → 07。
- **可透传参数**：额外参数原样交给 01_convert_docs.py（原脚本的 "$@"）。
- **环境变量默认值一致**：HF_HUB_OFFLINE 默认 1（模型已缓存，断网跑）；
  TABLEFORMER_MODE 默认 FAST。
- **退出码语义一致**：任一步失败即中止，退出码非 0（原 set -euo pipefail）。

用法：
    python run_all.py                 # 全量重跑
    python run_all.py --some-flag     # 额外参数透传给 01_convert_docs.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 步骤顺序有讲究：02 必须在 01 之前——文档实体抽取会拿 Customer.h 的宏名表做比对。
STEPS = [
    ("02_parse_customer_h.py", "解析 Customer.h，供后续实体抽取比对宏名", False),
    ("01_convert_docs.py", "文档转换（PDF/DOCX → markdown + 切片）", True),
    ("03_build_index.py", "汇总文档索引", False),
    ("04_search.py", "构建 BM25 检索样例", False),
    ("05_build_experience.py", "构建经验条目", False),
    ("06_build_taxonomy.py", "构建经验分类体系", False),
    ("07_write_readme.py", "生成 README", False),
]


def pick_python() -> str:
    """选解释器：优先仓库内 .venv，没有就用当前解释器。

    原脚本写死 `../.venv/bin/python`（Linux 路径），Windows 的 venv 解释器在
    Scripts/python.exe，路径不同——直接调 sys.executable 最稳。
    """
    for cand in (HERE.parent / ".venv" / "Scripts" / "python.exe",
                 HERE.parent / ".venv" / "bin" / "python"):
        if cand.is_file():
            return str(cand)
    return sys.executable


def main() -> int:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TABLEFORMER_MODE", "FAST")
    py = pick_python()
    extra = sys.argv[1:]

    print(f"[run_all] 解释器：{py}")
    print(f"[run_all] HF_HUB_OFFLINE={os.environ['HF_HUB_OFFLINE']} "
          f"TABLEFORMER_MODE={os.environ['TABLEFORMER_MODE']}")

    for script, desc, takes_extra in STEPS:
        path = HERE / script
        if not path.is_file():
            print(f"[run_all] 跳过（文件不存在）：{script}", file=sys.stderr)
            continue
        cmd = [py, str(path)] + (extra if takes_extra else [])
        print(f"\n[run_all] >>> {script} —— {desc}")
        rc = subprocess.run(cmd).returncode
        if rc != 0:
            print(f"[run_all] 步骤失败（退出码 {rc}）：{script}", file=sys.stderr)
            return rc  # 与原 set -e 一致：任一步失败即中止

    # 输出目录：与 common.py 的 KB_OUT 同源（那里支持环境变量覆盖）
    try:
        sys.path.insert(0, str(HERE))
        from common import KB_OUT  # type: ignore

        print(f"\n[run_all] 完成 -> {KB_OUT}")
    except Exception:
        print("\n[run_all] 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
