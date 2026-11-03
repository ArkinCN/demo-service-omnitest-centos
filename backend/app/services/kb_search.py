"""
知识库关键词检索服务（阶段 3.1 引入，P3）。

复用离线流水线 `c/kb-pipeline/scripts/04_search.py` 的 tokenize 与 BM25 口径：
- 中文用「字 unigram + bigram」切分，英文/宏名用下划线保留的小写词元，无分词模型；
- BM25Okapi（k1=1.5, b=0.75），自实现，避免新增 rank_bm25 依赖；
- 语料 = 全部文档切片（chunks.jsonl）+ Customer.h 每条宏（params.json）。

数据源：前端 `public/kb/documents/` 下的流水线产物（13 份文档目录 + index.json）。
进程内懒加载单例，首次请求构建一次，之后复用（禁止每次请求重建 BM25）。

**向量一路（阶段 3 补全）**：附录 A.3 的「索引」阶段要求「关键词与向量两路」。
向量一路走 LanceDB，但**不在本进程 import**——lancedb 依赖 pyarrow 且要求
pydantic>=2.7.4，而后端锁的是 pydantic 2.5.0（客户原依赖逐字锁定），
装进来会静默顶掉它（3-K 有同类事故）。所以走**子进程**调 kb-pipeline 的 venv，
见 `app/services/kb_embed_service.py`。

向量一路不可用时**降级为关键词单路并在结果里标注**（`degraded` /
`degrade_reason`），不报错、也不静默假装双路（项目纪律：失败必须可见）。

路径来源统一走 `app.core.paths`：不在本模块自行拼目录，避免层级调整时逐处改，
也避免出现写死盘符这类不可交付的写法。
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.logger import logger
from app.core.paths import kb_data_dir

# 知识库流水线产物目录。默认指向前端 public/kb；部署方可用 .env 的 KB_DATA_DIR 覆盖。
# 用函数取而不是 import 时的常量：路径要在真正用时才解析（见 paths.py 的说明）。
KB_DATA_DIR: Path = kb_data_dir()

RE_ASCII = re.compile(r"[a-z0-9_]+")
RE_CJK = re.compile(r"[一-鿿]")
STOP = {"怎么", "如何", "什么", "的", "了", "是", "在", "和", "与", "选", "配置"}


def tokenize(text: str) -> list[str]:
    """与 04_search.py 完全一致：ASCII 词元（含下划线拆分）+ 中文 unigram/bigram。"""
    low = text.lower()
    toks = RE_ASCII.findall(low)
    # 宏名再拆下划线段，让 "FG 输出" 能命中 FG_OUTPUT_ENABLE
    toks += [p for t in toks if "_" in t for p in t.split("_") if p]
    cjk = RE_CJK.findall(text)
    toks += cjk
    toks += ["".join(pair) for pair in zip(cjk, cjk[1:])]
    return toks


@dataclass
class Doc:
    chunk_id: str
    doc_id: str
    doc_title: str
    kind: str
    text: str
    page: int | None
    heading_path: list
    source_path: str


def _load_corpus(data_dir: Path) -> list[Doc]:
    """从流水线产物目录加载全部检索单元（chunks + params）。与 04_search.py 同构。"""
    index_path = data_dir / "documents" / "index.json"
    if not index_path.exists():
        return []

    index = json.loads(index_path.read_text(encoding="utf-8"))
    titles = {d["doc_id"]: d["title"] for d in index["documents"]}
    paths = {d["doc_id"]: d.get("source_path", "") for d in index["documents"]}

    corpus: list[Doc] = []
    docs_dir = data_dir / "documents"
    for d in sorted(docs_dir.iterdir()):
        if not d.is_dir():
            continue
        cj = d / "chunks.jsonl"
        if cj.exists():
            for line in cj.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                c = json.loads(line)
                head = " > ".join(c.get("heading_path") or [])
                corpus.append(Doc(
                    c["id"], c["doc_id"], titles.get(c["doc_id"], c["doc_id"]),
                    "chunk", f"{head}\n{c['text']}", c.get("page"),
                    c.get("heading_path") or [], paths.get(c["doc_id"], ""),
                ))
        pj = d / "params.json"
        if pj.exists():
            p = json.loads(pj.read_text(encoding="utf-8"))
            for i, m in enumerate(p["params"]):
                text = (f"{m['name']} = {m['raw_value']} {m['comment']} "
                        f"{m['group']['l1']} {m['group']['l2']}")
                corpus.append(Doc(
                    f"{p['doc_id']}#m{i:04d}", p["doc_id"], p["title"],
                    "param", text, None,
                    [m["group"]["l1"], m["group"]["l2"]],
                    p["source"]["path"],
                ))
    return corpus


class _BM25Okapi:
    """自实现 BM25Okapi（k1=1.5, b=0.75），与 rank_bm25.BM25Okapi 口径一致。"""

    K1 = 1.5
    B = 0.75

    def __init__(self, corpus_tokens: list[list[str]]):
        self.corpus = corpus_tokens
        self.n = len(corpus_tokens)
        self.doc_len = [len(t) for t in corpus_tokens]
        self.avgdl = (sum(self.doc_len) / self.n) if self.n else 0.0
        self.idf: dict[str, float] = {}
        self._build_idf()

    def _build_idf(self):
        df: dict[str, int] = {}
        for toks in self.corpus:
            for t in set(toks):
                df[t] = df.get(t, 0) + 1
        self.idf = {
            t: math.log((self.n - c + 0.5) / (c + 0.5) + 1.0)
            for t, c in df.items()
        }

    def get_scores(self, query_tokens: list[str]) -> list[float]:
        scores = [0.0] * self.n
        for t in query_tokens:
            if t not in self.idf:
                continue
            idf = self.idf[t]
            for i, toks in enumerate(self.corpus):
                tf = toks.count(t)
                if tf == 0:
                    continue
                denom = tf + self.K1 * (1 - self.B + self.B * self.doc_len[i] / self.avgdl)
                scores[i] += idf * (tf * (self.K1 + 1)) / denom
        return scores


class KnowledgeSearch:
    """进程内单例检索器。

    两路检索（阶段 3 补全，附录 A.3「索引：关键词与向量两路」）：
      - **关键词**：本进程内自实现 BM25（既有实现，口径与 04_search.py 一致）；
      - **向量**：LanceDB（走子进程调 kb-pipeline 的 venv，见 kb_embed_service）。

    `search()` 是唯一对外入口，返回结构与加向量之前**完全一致**
    （前端引用面板一行都不用改），只**新增** `route` / `degraded` 两个标注字段。
    """

    def __init__(self, data_dir: Path = KB_DATA_DIR):
        self.corpus = _load_corpus(data_dir)
        self.bm25 = _BM25Okapi([tokenize(d.text) for d in self.corpus])
        # chunk_id → 语料下标。向量一路只拿得到 chunk_id，
        # 要回填出 doc_id / page / source_path 这些出处字段就得有这张表。
        self.by_chunk: dict[str, int] = {
            d.chunk_id: i for i, d in enumerate(self.corpus)
        }
        logger.info(f"kb_search: loaded {len(self.corpus)} units from {data_dir}")

    # ------------------------------------------------------------ 关键词一路

    def _keyword(self, query: str, k: int) -> list[dict]:
        """既有 BM25 一路。返回 [{"idx", "score"}]，由统一装配层套成形。"""
        q = [t for t in tokenize(query) if t not in STOP]
        scores = self.bm25.get_scores(q)
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
        out = []
        for i in order:
            if scores[i] <= 0:
                continue
            out.append({"idx": i, "score": float(scores[i])})
        return out

    # -------------------------------------------------------------- 向量一路

    def _vector(self, query: str, k: int):
        """向量一路。返回 (results, tier, degraded_reason)。

        不可用时返回 ([], "", 原因)——**由调用方决定如何标注降级**，
        这里不抛异常，因为「向量不可用」在离线现场是**预期状态**而非故障。
        """
        from app.services.kb_embed_service import search as vec_search

        res = vec_search(query, k=k)
        if not res.available:
            return [], "", res.reason or "向量一路不可用"

        out = []
        for h in res.hits:
            cid = h.get("chunk_id") or ""
            idx = self.by_chunk.get(cid)
            # 距离 → 相似度：LanceDB 余弦距离越小越近。
            # 用 1/(1+d) 而不是 1-d：d 理论上 ∈[0,2]，1-d 会出现负数，
            # 融合时与 BM25 的正分数量纲不一致，归一化会失真。
            d = h.get("distance")
            sim = 1.0 / (1.0 + float(d)) if d is not None else 0.0
            out.append({"idx": idx, "chunk_id": cid, "score": sim, "raw": h})
        return out, res.tier, ""

    # -------------------------------------------------------- 混合与装配

    def search(self, query: str, k: int = 5) -> list[dict]:
        """检索入口。默认走混合；向量不可用时**降级为关键词单路并标注**。

        返回元素在既有字段之外新增：
          route     —— "keyword" / "vector" / "hybrid"（这条命中的来源）
          degraded  —— 是否降级过；true 时 `degrade_reason` 说明原因
          degrade_reason —— 降级原因（未降级为空串）

        前端「依据」面板读的是 title/source/score 那几个既有字段，
        对它而言这只是多了几个可忽略的键，**不需要改版**。
        """
        kw = self._keyword(query, max(k, 10))

        vec: list[dict] = []
        tier = ""
        vec_reason = ""
        mode = (getattr(settings, "KB_VECTOR_MODE", "hybrid") or "hybrid").strip().lower()
        if mode == "hybrid":
            vec, tier, vec_reason = self._vector(query, max(k, 10))

        degraded = bool(vec_reason)
        # 降级原因要拼成人能看懂、且能据此行动的一句话
        degrade_reason = ""
        if degraded:
            degrade_reason = f"向量一路未参与（{vec_reason}），本次为关键词单路结果"
        elif tier == "hashing":
            # hashing 档是**字面回退、不是语义模型**。必须标出来，
            # 否则人会以为向量一路在做语义召回，从而错判检索质量的边界。
            degraded = True
            degrade_reason = "向量一路使用字面哈希回退（非语义模型），仅具字面相近能力"

        weight_kw = float(getattr(settings, "KB_HYBRID_KEYWORD_WEIGHT", 0.6) or 0.6)
        weight_kw = min(max(weight_kw, 0.0), 1.0)
        weight_vec = 1.0 - weight_kw

        # ── 归一化后加权融合 ──
        # 必须归一化：BM25 分数是无上界的（随语料规模变化），向量相似度是 [0,1]，
        # 直接相加会让 BM25 一边倒。用「该路最高分」做分母是最小且可解释的做法
        # （不用 min-max：单路只有一个结果时 min==max，会除零）。
        kw_max = max((r["score"] for r in kw), default=0.0) or 1.0
        vec_max = max((r["score"] for r in vec), default=0.0) or 1.0

        merged: dict[object, dict] = {}
        for r in kw:
            key = r["idx"]
            merged[key] = {
                "idx": key,
                "kw_norm": r["score"] / kw_max,
                "vec_norm": 0.0,
                "routes": {"keyword"},
            }
        for r in vec:
            key = r["idx"] if r["idx"] is not None else r["chunk_id"]
            slot = merged.setdefault(key, {
                "idx": r["idx"], "kw_norm": 0.0, "vec_norm": 0.0, "routes": set(),
            })
            slot["vec_norm"] = r["score"] / vec_max
            slot["routes"].add("vector")
            # 向量一路能补出处（BM25 那边本来就有；这里兜底新上传的条目）
            if r["idx"] is None and r.get("raw"):
                slot["orphan"] = r["raw"]

        scored: list[tuple[float, dict]] = []
        for slot in merged.values():
            s = weight_kw * slot["kw_norm"] + weight_vec * slot["vec_norm"]
            scored.append((s, slot))
        scored.sort(key=lambda x: -x[0])

        out: list[dict] = []
        for rank, (score, slot) in enumerate(scored[:k], start=1):
            idx = slot["idx"]
            if idx is not None:
                d = self.corpus[idx]
                snippet = re.sub(r"\s+", " ", d.text).strip()
                item = {
                    "kind": d.kind, "doc_id": d.doc_id, "doc_title": d.doc_title,
                    "chunk_id": d.chunk_id, "heading_path": d.heading_path,
                    "page": d.page, "source_path": d.source_path,
                    "snippet": snippet[:420],
                }
            else:
                # 只在向量索引里、语料表里找不到的条目（例如索引比语料新）。
                # 用索引里带的元数据兜底，**不丢出处**；同时标注出来。
                raw = slot.get("orphan") or {}
                item = {
                    "kind": "chunk", "doc_id": raw.get("doc_id", "") or "",
                    "doc_title": raw.get("doc_id", "") or "",
                    "chunk_id": raw.get("chunk_id", "") or "",
                    "heading_path": raw.get("heading_path") or [],
                    "page": raw.get("page"),
                    "source_path": raw.get("source_path", "") or "",
                    "snippet": re.sub(r"\s+", " ", str(raw.get("text") or "")).strip()[:420],
                    "orphan_index_entry": True,
                }

            routes = slot["routes"]
            route = "hybrid" if len(routes) > 1 else next(iter(routes))
            item.update({
                "rank": rank,
                "score": round(float(score), 4),
                # 两路各自的原始归一化分量。**保留它们是为了可解释**：
                # 排查「为什么这条排前面」时不必重跑一次检索。
                "score_keyword": round(slot["kw_norm"], 4),
                "score_vector": round(slot["vec_norm"], 4),
                "route": route,
                "degraded": degraded,
                "degrade_reason": degrade_reason,
            })
            out.append(item)
        return out


# 全局单例（懒加载）
_engine: KnowledgeSearch | None = None


def get_engine() -> KnowledgeSearch:
    global _engine
    if _engine is None:
        _engine = KnowledgeSearch()
    return _engine


def taxonomy_scene_id(data_dir: Path = KB_DATA_DIR) -> str | None:
    """从 index.json 读 taxonomy，拼成 scene_id 用于归属校验。"""
    index_path = data_dir / "documents" / "index.json"
    if not index_path.exists():
        return None
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        t = index.get("taxonomy") or {}
        if t.get("l1") and t.get("l2") and t.get("l3"):
            return f"{t['l1']}.{t['l2']}.{t['l3']}"
    except Exception as e:  # noqa: BLE001
        # 归属校验取不到 taxonomy 就退回 None（调用方会拒绝归属），
        # 但**必须留一条日志**：原先是 except: pass，index.json 坏了或格式变了
        # 会静默退化成「没有归属」，排查时根本想不到是这里。
        logger.warning(f"taxonomy_scene_id 读取失败，归属校验将退回 None: {e}")
        return None
    return None
