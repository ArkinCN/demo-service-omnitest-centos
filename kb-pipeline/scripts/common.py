"""KB pipeline 公共常量与小工具。"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

# 路径一律基于脚本位置推导，禁止写绝对路径（Windows 盘符随机器变，写死即硬编码）。
#   BASE      = c/kb-pipeline
#   PROJECT_C = c/
BASE = Path(__file__).resolve().parent.parent
PROJECT_C = BASE.parent

INPUT = BASE / "input"
CONFIG = BASE / "config"

# 流水线产物输出目录。默认写回前端 public/kb——前端就是从这个目录 fetch 的，
# 所以默认值指向它才能「跑完即生效」。部署方可用环境变量 KB_OUT 覆盖；
# 相对值按项目根 c/ 解析，绝对值（部署方显式指定）原样采用。
_KB_OUT_ENV = (os.environ.get("KB_OUT") or "").strip()
KB_OUT = (
    (Path(_KB_OUT_ENV) if Path(_KB_OUT_ENV).is_absolute() else PROJECT_C / _KB_OUT_ENV)
    if _KB_OUT_ENV
    else PROJECT_C / "web" / "public" / "kb"
)

TAXONOMY = {"l1": "motor", "l2": "cooling-fan", "l3": "fortior-fu6832"}
PROCESS_TAGS = ["初始化配置", "测试需求", "启动测试", "调优", "报告"]


def load_registry() -> dict:
    return json.loads((CONFIG / "registry.json").read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def est_tokens(text: str) -> int:
    """粗略 token 估计：CJK 字符按 1 个 token，其余按 4 字符 1 个 token。"""
    cjk = len(re.findall(r"[一-鿿]", text))
    rest = len(text) - cjk
    return cjk + max(1, rest // 4) if text else 0
