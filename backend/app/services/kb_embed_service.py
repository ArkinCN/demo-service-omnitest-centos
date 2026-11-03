"""向量索引服务（阶段 3 补全，附录指定 LanceDB）。

职责
----
把「关键词检索」之外的第二路——**向量检索**——接起来：
  - 建索引 / 增量追加 / 重建：把语料向量化并写入 LanceDB（落盘）
  - 查询：给一句话，拿回近邻（chunk_id + 余弦距离）
  - 陈旧检测：索引与当前语料/模型档位不一致时**明确报 stale**，不静默返回旧结果

为什么全程走子进程（**这条不能改**）
----------------------------------
`lancedb` 依赖 `pyarrow` 且要求 `pydantic>=2.7.4`，而后端锁的是
**pydantic 2.5.0 / httpx 0.26.0**（客户原依赖逐字锁定，阶段 1 红线）。
3-K 记录过一次真实事故：往后端环境装 docling 把这两项**静默顶掉**。
所以 lancedb 与 embedding 一律装在 `c/kb-pipeline/.venv`，
后端只通过**子进程 + JSON** 交互，与 docling 那条路同范式。

失败可见（项目最贵教训 1）
------------------------
向量一路不可用时**不抛穿、不静默假装双路**：返回 `available=False` 与原因，
由检索层降级为单路并在结果里标注 `degraded`。落库/落盘这类会失败的动作
一律不许 `except: pass`。
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.logger import logger
from app.core.paths import kb_pipeline_dir, kb_pipeline_python, kb_vector_dir

# 向量化的子进程超时。建索引要跑完全部语料的 embedding（577+ 单元起步，
# 离线 hashing 档很快，transformer 档在 CPU 上可能几分钟）——给足余量。
VECTOR_TIMEOUT_S = 1800
# 查询超时：查询只编码一句话，正常毫秒级；给 120 秒是防模型冷启动加载。
QUERY_TIMEOUT_S = 120

# 子进程专用退出码语义（与 _vector_worker.py / _embed_worker.py 约定一致）
EXIT_UNAVAILABLE = 3


@dataclass
class VectorResult:
    """向量一路的结果。**available=False 是正常返回值，不是异常。**"""

    available: bool
    hits: list[dict] = field(default_factory=list)
    tier: str = ""
    reason: str = ""
    # 索引陈旧（与当前语料/档位不一致）：调用方可据此提示重建
    stale: bool = False


def _worker_path() -> Path:
    return kb_pipeline_dir() / "scripts" / "_vector_worker.py"


def _run_worker(args: list[str], timeout: int) -> tuple[int, dict, str]:
    """跑向量 worker，返回 (退出码, 解析后的 JSON, 原始 stderr)。

    统一在这里处理三件事，避免每个调用点各写一遍：
      1. venv 缺失 → 明确报「环境未就绪」，不抛看不懂的 FileNotFoundError；
      2. stdout 是 JSON（worker 已强制 UTF-8），解析失败要留原文便于排查；
      3. worker 把错误也写成 JSON，这里统一解出来给上层。
    """
    py = kb_pipeline_python()
    if not py.exists():
        return -1, {}, (
            f"向量化运行环境不存在：{py}。"
            f"按 kb-pipeline/requirements-vector.txt 在该 venv 装 lancedb 后再试。"
        )

    worker = _worker_path()
    if not worker.exists():
        return -1, {}, f"向量 worker 不存在：{worker}"

    cmd = [str(py), str(worker), *args]
    try:
        _run_kwargs = dict(
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False,
        )
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            _run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.run(cmd, **_run_kwargs)
    except subprocess.TimeoutExpired:
        return -1, {}, f"向量 worker 超过 {timeout}s 被终止"

    raw = (proc.stdout or "").strip()
    parsed: dict = {}
    if raw:
        # worker 可能在 JSON 之前打了一行 "[ok] ..."；取最后一个 JSON 对象。
        for line in reversed(raw.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    parsed = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
    return proc.returncode, parsed, (proc.stderr or "").strip()


def vector_dir() -> Path:
    """索引目录（可由 .env 的 KB_VECTOR_DIR 覆盖）。"""
    return kb_vector_dir()


def _cleanup_tmp(p: Path) -> None:
    """删掉传给 worker 的临时语料文件。

    刻意**不写 `except: pass`**：项目纪律是「不许对失败静默」，审计脚本
    （audit_code_quality）也会把裸吞异常标出来。删临时文件失败本身不影响
    业务，但**必须留一条日志**——否则临时文件会悄悄在索引目录里堆积，
    而人查目录时看到一堆 _corpus_for_worker*.json 完全不知道为什么来的。
    """
    try:
        p.unlink()
    except FileNotFoundError:
        return  # 已经不在了，这是预期情况，不算失败
    except OSError as e:
        logger.warning(f"临时语料文件删除失败（不影响索引，但会留残file）：{p} — {e}")


def stat() -> dict:
    """索引现状：是否存在、模型、档位、条数、构建时间。"""
    rc, data, err = _run_worker(["stat", "--dir", str(vector_dir())], 60)
    if rc != 0 and not data:
        return {"exists": False, "error": err or f"worker 退出码 {rc}"}
    return data


def manifest_count() -> int:
    """索引里登记了多少条。取不到返回 -1（区别于 0 条）。"""
    m = stat()
    try:
        return int(m.get("count", -1))
    except (TypeError, ValueError):
        return -1


def index_stale(corpus_count: int) -> tuple[bool, str]:
    """索引是否陈旧。返回 (是否陈旧, 原因)。

    三种陈旧（都必须能说出来，否则现场排查只能靠猜）：
      1. 索引不存在；
      2. 档位与当前配置不一致（换过 embedding 模型 → 向量空间变了）；
      3. 条数与语料不一致（库里新增/减少了单元 → 索引落后于库）。
    """
    m = stat()
    if not m.get("exists"):
        return True, "向量索引不存在"

    built_tier = (m.get("tier") or "").strip()
    # 单机默认 MOTORDEBUG_EMBED_MODEL 为空 → 走 hashing 档
    want_tier = "transformer" if (settings.MOTORDEBUG_EMBED_MODEL or "").strip() else "hashing"
    if built_tier and built_tier != want_tier:
        return True, f"索引档位为 {built_tier}，当前配置为 {want_tier}（需重建）"

    if corpus_count >= 0:
        try:
            have = int(m.get("count", -1))
        except (TypeError, ValueError):
            have = -1
        if have >= 0 and have != corpus_count:
            return True, f"索引 {have} 条，语料 {corpus_count} 条（索引落后，需重建）"
    return False, ""


def build(corpus: list[dict], model: str = "") -> dict:
    """全量重建索引。corpus 形如 [{"chunk_id","doc_id","text","page",...}]。"""
    if not corpus:
        return {"ok": False, "error": "语料为空，拒绝建空索引"}

    d = vector_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "_corpus_for_worker.json"
    tmp.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")

    rc, data, err = _run_worker(
        ["build", "--corpus", str(tmp), "--dir", str(d), "--model", model or settings.MOTORDEBUG_EMBED_MODEL or ""],
        VECTOR_TIMEOUT_S,
    )
    _cleanup_tmp(tmp)

    if rc != 0:
        msg = data.get("error") or err or f"worker 退出码 {rc}"
        logger.warning(f"kb vector build 失败：{msg}")
        return {"ok": False, "error": msg, "unavailable": rc == EXIT_UNAVAILABLE}
    logger.info(f"kb vector 索引已重建：{data}")
    return {"ok": True, **data}


def add(corpus: list[dict], model: str = "") -> dict:
    """增量追加（索引不存在时**明确失败**，由调用方决定是否改成全量 build）。"""
    if not corpus:
        return {"ok": True, "added": 0, "note": "没有新单元"}
    d = vector_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "_corpus_for_worker_add.json"
    tmp.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
    rc, data, err = _run_worker(
        ["add", "--corpus", str(tmp), "--dir", str(d), "--model", model or settings.MOTORDEBUG_EMBED_MODEL or ""],
        VECTOR_TIMEOUT_S,
    )
    _cleanup_tmp(tmp)
    if rc != 0:
        return {"ok": False, "error": data.get("error") or err or f"worker 退出码 {rc}"}
    return {"ok": True, **data}


def search(query: str, k: int = 10) -> VectorResult:
    """向量一路检索。**不可用时返回 available=False + reason，不抛异常。**

    注意 tier 会原样带回来：hashing 档是「字面回退」而非语义模型，
    上层要据此标记 degraded，让人知道这次召回的边界在哪。
    """
    if not (settings.KB_VECTOR_MODE or "").strip().lower() == "hybrid":
        return VectorResult(available=False, reason="KB_VECTOR_MODE 未启用向量一路")

    rc, data, err = _run_worker(
        ["query", "--dir", str(vector_dir()), "--query", query, "--k", str(k),
         "--model", settings.MOTORDEBUG_EMBED_MODEL or ""],
        QUERY_TIMEOUT_S,
    )
    if rc == EXIT_UNAVAILABLE:
        return VectorResult(available=False, reason=data.get("error") or "向量一路不可用")
    if rc != 0:
        return VectorResult(
            available=False,
            reason=data.get("error") or err or f"向量 worker 退出码 {rc}",
            stale="不一致" in (data.get("error") or ""),
        )
    return VectorResult(
        available=True,
        hits=data.get("hits") or [],
        tier=(data.get("tier") or "").strip(),
    )


def probe() -> dict:
    """探测向量环境：档位 + lancedb 是否可用。给运维/诊断用。"""
    rc, data, err = _run_worker(["stat", "--dir", str(vector_dir())], 60)
    from app.core.paths import kb_pipeline_python

    return {
        "pipeline_python": str(kb_pipeline_python()),
        "pipeline_python_exists": kb_pipeline_python().exists(),
        "vector_dir": str(vector_dir()),
        "embed_model": settings.MOTORDEBUG_EMBED_MODEL or "(空·走 hashing 回退)",
        "mode": settings.KB_VECTOR_MODE,
        "index": data if rc == 0 else {"exists": False, "error": err},
    }


def corpus_to_rows(corpus) -> list[dict]:
    """把 kb_search 的 Doc 列表转成 worker 要的行形状。

    单独抽出来是为了**只有一份转换逻辑**——建索引与增量追加都用它，
    两处各写一遍迟早分叉（分叉的症状是「检索得到但页码/出处丢了」）。
    """
    rows: list[dict] = []
    for d in corpus:
        rows.append({
            "chunk_id": getattr(d, "chunk_id", None) or "",
            "doc_id": getattr(d, "doc_id", "") or "",
            "text": getattr(d, "text", "") or "",
            "page": getattr(d, "page", None),
            "source_path": getattr(d, "source_path", "") or "",
            "heading_path": getattr(d, "heading_path", []) or [],
        })
    return rows
