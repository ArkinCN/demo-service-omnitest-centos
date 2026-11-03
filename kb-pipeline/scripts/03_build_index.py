"""汇总 kb/documents/index.json：全部文档条目 + 三级分类 + 用途流程标签 + 转化状态。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import KB_OUT, TAXONOMY, load_registry, write_json  # noqa: E402


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path, encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def main() -> None:
    reg = load_registry()
    docs_root = KB_OUT / "documents"
    items = []

    for cfg in reg["documents"]:
        d = docs_root / cfg["doc_id"]
        src_p = d / "source.json"
        if src_p.exists():
            src = json.loads(src_p.read_text(encoding="utf-8"))
            ents = json.loads((d / "entities.json").read_text(encoding="utf-8"))
            figs = sorted((d / "figures").glob("*")) if (d / "figures").exists() else []
            items.append({
                "doc_id": cfg["doc_id"], "title": cfg["title"], "doc_type": cfg["doc_type"],
                "knowledge_class": "文档性质", "taxonomy": TAXONOMY,
                "process_tags": cfg["process_tags"], "format": src["format"],
                "pages": src["pages"], "page_limit": src.get("page_limit"),
                "tables": src["tables"], "chunks": count_lines(d / "chunks.jsonl"),
                "figures": len(figs),
                "entities": ents["summary"],
                "convert_status": "ok", "converter": src["converter"],
                "sha256": src["sha256"], "bytes": src["bytes"],
                "source_path": src["source_path"], "note": src.get("note"),
                "artifacts": ["source.json", "content.md", "chunks.jsonl",
                              "entities.json"] + (["figures/"] if figs else []),
            })
        else:
            status_f = (Path(__file__).resolve().parent.parent / "work" / "status"
                        / f"{cfg['doc_id']}.json")
            st = json.loads(status_f.read_text(encoding="utf-8")) if status_f.exists() else {}
            items.append({
                "doc_id": cfg["doc_id"], "title": cfg["title"], "doc_type": cfg["doc_type"],
                "knowledge_class": "文档性质", "taxonomy": TAXONOMY,
                "process_tags": cfg["process_tags"], "convert_status": "failed",
                "fail_reason": st.get("error", "未记录"),
                "fail_detail": st.get("stderr_tail"),
                "note": cfg.get("note"),
                "chunks": 0, "figures": 0, "artifacts": [],
            })

    for cfg in reg["code_configs"]:
        p = docs_root / cfg["doc_id"] / "params.json"
        params = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        items.append({
            "doc_id": cfg["doc_id"], "title": cfg["title"], "doc_type": cfg["doc_type"],
            "knowledge_class": "文档性质", "taxonomy": TAXONOMY,
            "process_tags": cfg["process_tags"], "format": "h",
            "pages": None, "tables": None, "chunks": 0, "figures": 0,
            "entities": params["summary"] if params else {},
            "convert_status": "ok" if params else "failed",
            "converter": "custom regex parser (02_parse_customer_h.py)",
            "sha256": params["source"]["sha256"] if params else None,
            "bytes": params["source"]["bytes"] if params else None,
            "source_path": params["source"]["path"] if params else None,
            "note": "转化产物是 params.json（结构化参数表），不是 markdown 切片",
            "artifacts": ["params.json"] if params else [],
        })

    ok = [i for i in items if i["convert_status"] == "ok"]
    write_json(docs_root / "index.json", {
        "taxonomy": TAXONOMY,
        "process_tags_vocab": reg["process_tags_vocab"],
        "summary": {
            "documents": len(items),
            "converted_ok": len(ok),
            "failed": len(items) - len(ok),
            "total_chunks": sum(i.get("chunks", 0) for i in items),
            "total_figures": sum(i.get("figures", 0) for i in items),
            "by_doc_type": {t: sum(1 for i in items if i["doc_type"] == t)
                            for t in sorted({i["doc_type"] for i in items})},
            "by_process_tag": {t: sum(1 for i in items if t in i["process_tags"])
                               for t in reg["process_tags_vocab"]},
        },
        "documents": items,
    })
    print(f"[index] {len(items)} docs, ok={len(ok)}, "
          f"chunks={sum(i.get('chunks',0) for i in items)}")


if __name__ == "__main__":
    main()
