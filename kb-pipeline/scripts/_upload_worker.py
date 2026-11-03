"""上传文件的 docling 转化 worker（供后端以子进程调用）。

为什么不复用 01_convert_docs.py 的 --worker：
    那个 worker 按 `config/registry.json` 找文件（`INPUT / cfg["file"]`），
    而上传的文件是**运行时**来的、不在 registry 里、文件名也任意。
    硬塞进 registry 会污染那份「客户交付清单」——它是契约文件，不该被运行时数据改写。
    所以这里写一个**只认绝对路径**的轻量入口，复用 01_convert_docs.py 里
    **已经封装好的 Docling 链路**（build_converter / build_chunks / extract_figures），
    不另写一套解析（主文档 3.1 明写「不要换成别的解析器」）。

用法（后端 kb_convert_service.py 调）：
    <kb-pipeline>/.venv/Scripts/python.exe _upload_worker.py \
        --src <原件绝对路径> --out <产物目录> --doc-id <id> --title <标题>

产出（写到 --out）：
    docling_result.json   本次转换的汇总：markdown / chunks / tables / figures / ocr
    （content.md 与 chunks.jsonl 由后端服务按自己的阶段落盘，此处不代劳）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 复用 01_convert_docs.py 的封装（同一目录下的模块）
sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "convert_docs", str(Path(__file__).resolve().parent / "01_convert_docs.py")
)
cd = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(cd)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="原件绝对路径")
    ap.add_argument("--out", required=True, help="产物目录")
    ap.add_argument("--doc-id", required=True)
    ap.add_argument("--title", default="")
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        print(json.dumps({"error": f"原件不存在：{src}"}, ensure_ascii=False))
        return 2

    # OCR 判定沿用 01 的口径：平均每页可抽字符数过低就当图片型
    need_ocr = False
    if src.suffix.lower() == ".pdf":
        try:
            need_ocr = cd.text_density(src) < 120
        except Exception:  # noqa: BLE001
            need_ocr = False

    converter = cd.build_converter()
    try:
        result = converter.convert(src, ocr=need_ocr)
    except TypeError:
        # 非 PDF 走 simple converter 时签名不同（01 里的 LazyConverter 已处理，
        # 这里兜底一档，避免不同 docling 小版本签名差异把整条链断掉）
        result = converter.convert(src)

    doc = result.document
    md = doc.export_to_markdown()
    chunks = cd.build_chunks(doc, args.doc_id)

    # 图片抽取：复用 01 的实现（PDF 用 PyMuPDF，docx 读 word/media）
    fig_dir = out / "figures"
    try:
        figures = cd.extract_figures(src, fig_dir)
    except Exception:  # noqa: BLE001
        figures = []

    payload = {
        "doc_id": args.doc_id,
        "title": args.title,
        "markdown": md,
        "chunks": chunks,
        "tables": sum(1 for _ in getattr(doc, "tables", []) or []),
        "figures": len(figures),
        "ocr": need_ocr,
        "pages": len(getattr(doc, "pages", {}) or {}) or None,
    }
    (out / "docling_result.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[ok] {args.doc_id}: {len(chunks)} chunks, {payload['pages']} pages, "
          f"{payload['tables']} tables, {payload['figures']} figures", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
