"""离线关键词检索（BM25，rank_bm25）。

语料 = 全部文档切片（chunks.jsonl）+ Customer.h 每条宏（params.json）。
中文用「字 unigram + bigram」切分，英文/宏名用下划线保留的小写词元，
不依赖分词模型，完全离线。

向量检索按需求只留接口不实现：见 VectorIndex。
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import KB_OUT, write_json  # noqa: E402

RE_ASCII = re.compile(r"[a-z0-9_]+")
RE_CJK = re.compile(r"[一-鿿]")
STOP = {"怎么", "如何", "什么", "的", "了", "是", "在", "和", "与", "选", "配置"}


def tokenize(text: str) -> list[str]:
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


def load_corpus() -> list[Doc]:
    index = json.loads((KB_OUT / "documents" / "index.json").read_text(encoding="utf-8"))
    titles = {d["doc_id"]: d["title"] for d in index["documents"]}
    paths = {d["doc_id"]: d.get("source_path") for d in index["documents"]}
    corpus: list[Doc] = []

    for d in sorted((KB_OUT / "documents").iterdir()):
        cj = d / "chunks.jsonl"
        if cj.exists():
            for line in cj.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                c = json.loads(line)
                head = " > ".join(c.get("heading_path") or [])
                corpus.append(Doc(c["id"], c["doc_id"], titles.get(c["doc_id"], c["doc_id"]),
                                  "chunk", f"{head}\n{c['text']}", c.get("page"),
                                  c.get("heading_path") or [], paths.get(c["doc_id"], "")))
        pj = d / "params.json"
        if pj.exists():
            p = json.loads(pj.read_text(encoding="utf-8"))
            for i, m in enumerate(p["params"]):
                text = (f"{m['name']} = {m['raw_value']} {m['comment']} "
                        f"{m['group']['l1']} {m['group']['l2']}")
                corpus.append(Doc(f"{p['doc_id']}#m{i:04d}", p["doc_id"], p["title"],
                                  "param", text, None,
                                  [m["group"]["l1"], m["group"]["l2"]],
                                  p["source"]["path"]))
    return corpus


class KnowledgeSearch:
    def __init__(self) -> None:
        from rank_bm25 import BM25Okapi

        self.corpus = load_corpus()
        self.bm25 = BM25Okapi([tokenize(d.text) for d in self.corpus])

    def search(self, query: str, k: int = 5) -> list[dict]:
        q = [t for t in tokenize(query) if t not in STOP]
        scores = self.bm25.get_scores(q)
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
        out = []
        for rank, i in enumerate(order, start=1):
            d = self.corpus[i]
            if scores[i] <= 0:
                continue
            snippet = re.sub(r"\s+", " ", d.text).strip()
            out.append({
                "rank": rank, "score": round(float(scores[i]), 4),
                "kind": d.kind, "doc_id": d.doc_id, "doc_title": d.doc_title,
                "chunk_id": d.chunk_id, "heading_path": d.heading_path,
                "page": d.page, "source_path": d.source_path,
                "snippet": snippet[:420],
            })
        return out


class VectorIndex:
    """向量检索占位：本轮不实现，只固定调用契约，便于后续接入。"""

    def build(self, corpus: list[Doc]) -> None:
        raise NotImplementedError("向量检索本轮不做，接口预留")

    def search(self, query: str, k: int = 5) -> list[dict]:
        raise NotImplementedError("向量检索本轮不做，接口预留")


SAMPLE_QUERIES = ["启动电流怎么选", "FG 输出配置", "过压保护阈值", "极对数", "SMO 估算器"]


def main() -> None:
    engine = KnowledgeSearch()
    samples = []
    for q in SAMPLE_QUERIES:
        res = engine.search(q, k=5)
        samples.append({
            "query": q, "k": 5, "hits": len(res),
            "hit_docs": sorted({r["doc_id"] for r in res}),
            "pages_cited": sorted({r["page"] for r in res if r["page"]}),
            "results": res,
        })
        print(f"[search] {q}: {len(res)} hits -> "
              f"{[ (r['doc_id'], r['page']) for r in res ]}")
    write_json(KB_OUT / "search-samples.json", {
        "engine": "rank_bm25.BM25Okapi",
        "tokenizer": "ASCII 词元（含下划线拆分）+ 中文 unigram/bigram，无分词模型，离线",
        "corpus": {
            "documents": len({d.doc_id for d in engine.corpus}),
            "units": len(engine.corpus),
            "chunks": sum(1 for d in engine.corpus if d.kind == "chunk"),
            "params": sum(1 for d in engine.corpus if d.kind == "param"),
        },
        "vector_search": "接口预留未实现（scripts/04_search.py 的 VectorIndex）",
        "samples": samples,
    })


if __name__ == "__main__":
    if len(sys.argv) > 1:
        e = KnowledgeSearch()
        for r in e.search(" ".join(sys.argv[1:]), k=5):
            print(r["score"], r["doc_id"], r["page"], r["snippet"][:120])
    else:
        main()
