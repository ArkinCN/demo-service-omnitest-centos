"""向量索引 worker（供后端以子进程调用）。

职责（三种模式）：
  build   —— 全量建索引：读语料 JSON → 向量化 → 写入 LanceDB 表
  add     —— 增量追加：只处理传入的新单元（不重建整表）
  query   —— 查询：给一句话，返回近邻（chunk_id + 距离）

为什么走子进程而不是在后端进程里 import lancedb
-----------------------------------------------
1. `lancedb` 依赖 `pyarrow` 且要求 `pydantic>=2.7.4`，而**后端锁的是 pydantic 2.5.0**
   （客户原依赖逐字锁定，阶段 1 红线）。装进后端会**静默顶掉**它——
   3-K 记录过一次同类事故（装 docling 把 pydantic/httpx 顶了）。
2. 与 docling 同一条路（`_upload_worker.py`）：重依赖全在 `c/kb-pipeline/.venv`，
   后端只用子进程 + JSON 交互。范式统一，运维只需维护一个隔离环境。

索引布局（落盘目录，由后端 `KB_VECTOR_DIR` 传入）
------------------------------------------------
    <dir>/index.lance         LanceDB 表（含向量 + 元数据列）
    <dir>/manifest.json       {"model": ..., "dim": ..., "count": ..., "built_at": ...}

manifest 是**陈旧判定**的依据：后端比对 `model` 与当前配置是否一致、
`count` 与语料条数是否一致，不一致就报 stale 并触发重建——
**不静默返回旧索引的结果**（那会让人以为检索到了新资料）。

用法：
    <venv>/python.exe _vector_worker.py build --corpus <语料JSON> --dir <索引目录> [--model M]
    <venv>/python.exe _vector_worker.py add   --corpus <语料JSON> --dir <索引目录> [--model M]
    <venv>/python.exe _vector_worker.py query --dir <索引目录> --query "..." --k 10
    <venv>/python.exe _vector_worker.py stat  --dir <索引目录>

退出码：0 成功；2 参数/输入错；3 依赖或模型不可用（**专用码**，
让后端把「环境没准备好」与「跑崩了」分开报）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ⚠️ Windows 上 stdout 默认是 GBK 编码，而本脚本输出的 JSON 含中文
# （错误消息、note）。父进程按 UTF-8 读时就会把中文读成乱码，
# 导致「父进程以为脚本失败了」这种假故障（实测踩过）。
# 统一强制 UTF-8 输出，与后端子进程读取时的 encoding="utf-8" 对齐。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

EXIT_MODEL_UNAVAILABLE = 3
TABLE_NAME = "kb_chunks"


def _load_embed():
    """延迟导入同目录的 _embed_worker（它负责真正的向量化）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "embed_worker", str(Path(__file__).resolve().parent / "_embed_worker.py")
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _connect(dir_: Path):
    """连 LanceDB。返回 (db, available)。不可用返回 (None, False)。"""
    try:
        import lancedb
    except Exception:
        return None, False
    dir_.mkdir(parents=True, exist_ok=True)
    try:
        return lancedb.connect(str(dir_)), True
    except Exception:
        return None, False


def _read_corpus(path: Path) -> list[dict]:
    """语料 JSON：[{"chunk_id","doc_id","text","page","source_path","heading_path"}]。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("语料必须是数组")
    out: list[dict] = []
    for d in data:
        text = (d.get("text") or "").strip()
        if not text:
            continue
        out.append({
            "chunk_id": str(d.get("chunk_id") or ""),
            "doc_id": str(d.get("doc_id") or ""),
            "text": text,
            # LanceDB 列要类型稳定：page 用 int，缺就用 -1（读回时再还原成 None）
            "page": int(d["page"]) if d.get("page") is not None else -1,
            "source_path": str(d.get("source_path") or ""),
            "heading_path": json.dumps(d.get("heading_path") or [], ensure_ascii=False),
        })
    return out


def cmd_build(args) -> int:
    rows = _read_corpus(Path(args.corpus))
    if not rows:
        print(json.dumps({"error": "语料为空，拒绝建空索引"}, ensure_ascii=False))
        return 2

    db, ok = _connect(Path(args.dir))
    if not ok:
        print(json.dumps({"error": "lancedb 不可用（未安装或打不开索引目录）"}, ensure_ascii=False))
        return EXIT_MODEL_UNAVAILABLE

    ew = _load_embed()
    vecs, tier = ew.embed([r["text"] for r in rows], args.model)

    payload = []
    for r, v in zip(rows, vecs):
        payload.append({**r, "vector": v})

    # overwrite=True：build 是**全量重建**语义，不做增量合并。
    # 若要做增量请走 add 模式（避免「重建」与「追加」语义混在一个开关里）。
    db.create_table(TABLE_NAME, data=payload, mode="overwrite")

    dim = len(vecs[0]) if vecs else 0
    manifest = {
        "model": args.model,
        # tier 必须落盘：换档（transformer ↔ hashing）后向量空间不同，
        # 后端要靠它判断索引是否与当前配置一致（不一致就重建）
        "tier": tier,
        "dim": dim,
        "count": len(payload),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    (Path(args.dir) / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"ok": True, "mode": "build", **manifest}, ensure_ascii=False))
    return 0


def cmd_add(args) -> int:
    """增量追加：把新单元加进现有表。

    索引目录不存在或表不存在时**明确失败**，不偷偷退化成全量建——
    那样会让「增量」这个语义变得不可信，调用方也无法从结果里看出来。
    """
    if not (Path(args.dir) / "manifest.json").exists():
        print(json.dumps({
            "error": "索引不存在，无法增量追加；请先执行 build",
            "dir": str(args.dir),
        }, ensure_ascii=False))
        return 2

    rows = _read_corpus(Path(args.corpus))
    if not rows:
        print(json.dumps({"ok": True, "mode": "add", "added": 0, "note": "没有新单元"},
                         ensure_ascii=False))
        return 0

    db, ok = _connect(Path(args.dir))
    if not ok:
        print(json.dumps({"error": "lancedb 不可用"}, ensure_ascii=False))
        return EXIT_MODEL_UNAVAILABLE

    ew = _load_embed()
    vecs, tier = ew.embed([r["text"] for r in rows], args.model)

    # 已存在的 chunk_id 先删掉再加：同一切片重跑时不该堆两份（会重复召回）
    tbl = db.open_table(TABLE_NAME)
    ids = ",".join(f"'{r['chunk_id']}'" for r in rows if r["chunk_id"])
    if ids:
        try:
            tbl.delete(f"chunk_id IN ({ids})")
        except Exception:
            # 删除失败不该让追加中断，但**必须留痕**（否则重复条目静默累积）
            print(json.dumps({"warn": "按 chunk_id 去重删除失败，可能产生重复条目"},
                             ensure_ascii=False), file=sys.stderr)

    tbl.add([{**r, "vector": v} for r, v in zip(rows, vecs)])

    mpath = Path(args.dir) / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    manifest["count"] = int(manifest.get("count", 0)) + len(rows)
    manifest["built_at"] = datetime.now(timezone.utc).isoformat()
    manifest["model"] = args.model
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "mode": "add", "added": len(rows)}, ensure_ascii=False))
    return 0


def cmd_query(args) -> int:
    db, ok = _connect(Path(args.dir))
    if not ok:
        print(json.dumps({"error": "lancedb 不可用"}, ensure_ascii=False))
        return EXIT_MODEL_UNAVAILABLE

    try:
        tbl = db.open_table(TABLE_NAME)
    except Exception as e:
        print(json.dumps({"error": f"索引表不存在：{e}"}, ensure_ascii=False))
        return 2

    # ⚠️ 档位一致性检查（**这是最容易出错、且症状最隐蔽的一步**）：
    # 建索引用的是 transformer（384/768 维语义向量），查询时若落到 hashing
    # （384 维哈希向量），两向量**维度可能相同但语义空间完全不同** →
    # LanceDB 不会报错，只会返回一堆「有分数但毫不相关」的结果。
    # 所以这里比对 manifest.tier 与本次实际用的档位，不一致直接拒绝查询，
    # 让上层去重建索引，而不是给出一份看着正常的垃圾结果。
    ew = _load_embed()
    _probe_tier = "transformer" if ew._load_transformer(args.model) else "hashing"
    mpath = Path(args.dir) / "manifest.json"
    if mpath.exists():
        try:
            built_tier = json.loads(mpath.read_text(encoding="utf-8")).get("tier")
        except Exception:
            built_tier = None
        if built_tier and built_tier != _probe_tier:
            print(json.dumps({
                "error": "向量索引档位与当前编码档位不一致，需重建索引",
                "index_tier": built_tier,
                "current_tier": _probe_tier,
            }, ensure_ascii=False))
            return 3

    vecs, tier = ew.embed([args.query], args.model)

    hits = tbl.search(vecs[0]).limit(args.k).to_list()
    out = []
    for h in hits:
        page = h.get("page")
        out.append({
            "chunk_id": h.get("chunk_id"),
            "doc_id": h.get("doc_id"),
            # 写入时缺 page 存的是 -1，这里还原成 null（不把哨兵值漏给上层）
            "page": None if page in (-1, None) else page,
            "source_path": h.get("source_path"),
            "heading_path": json.loads(h.get("heading_path") or "[]"),
            "text": h.get("text"),
            # LanceDB 返回 _distance；余弦距离越小越近
            "distance": h.get("_distance"),
        })
    print(json.dumps({
        "ok": True, "mode": "query", "tier": tier, "hits": out,
    }, ensure_ascii=False))
    return 0


def cmd_stat(args) -> int:
    mpath = Path(args.dir) / "manifest.json"
    if not mpath.exists():
        print(json.dumps({"exists": False, "dir": str(args.dir)}, ensure_ascii=False))
        return 0
    m = json.loads(mpath.read_text(encoding="utf-8"))
    print(json.dumps({"exists": True, "dir": str(args.dir), **m}, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["build", "add", "query", "stat"])
    ap.add_argument("--corpus")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--query", default="")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--model", default="")
    args = ap.parse_args()

    if not args.model:
        import os
        args.model = os.environ.get(
            "MOTORDEBUG_EMBED_MODEL",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        )

    if args.mode in ("build", "add") and not args.corpus:
        print(json.dumps({"error": f"{args.mode} 需要 --corpus"}, ensure_ascii=False))
        return 2
    if args.mode == "query" and not args.query:
        print(json.dumps({"error": "query 需要 --query"}, ensure_ascii=False))
        return 2

    try:
        if args.mode == "build":
            return cmd_build(args)
        if args.mode == "add":
            return cmd_add(args)
        if args.mode == "query":
            return cmd_query(args)
        return cmd_stat(args)
    except Exception as e:  # noqa: BLE001
        # 不吞异常：把类型与消息原样给后端，附上模式便于定位
        print(json.dumps({"error": f"{type(e).__name__}: {e}", "mode": args.mode},
                         ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
