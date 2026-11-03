"""文档性质知识的转化流水线：PDF / DOCX → content.md + chunks.jsonl + entities.json + figures/。

转换器：Docling（IBM，2.129.0）。选型理由见 kb/README.md。
图片抽取用 PyMuPDF（PDF）与 zipfile 读 word/media（DOCX），不依赖联网。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import shutil
import sys
import traceback
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import INPUT, KB_OUT, TAXONOMY, est_tokens, load_registry, sha256_file, write_json  # noqa: E402
from entities import extract as extract_entities  # noqa: E402

DOC_TIMEOUT_S = int(os.environ.get("DOC_TIMEOUT_S", "1200"))
MAX_FIGURES = 20
MAX_CHUNK_CHARS = 1200
MIN_CHUNK_CHARS = 40
WORK = Path(__file__).resolve().parent.parent / "work"


def known_macros() -> set[str]:
    p = KB_OUT / "documents" / "customer-h-fu6832" / "params.json"
    if not p.exists():
        return set()
    return {m["name"] for m in json.loads(p.read_text(encoding="utf-8"))["params"]}


def text_density(src: Path, sample_pages: int = 5) -> float:
    """前若干页平均每页可抽取的文字字符数。极低说明是扫描件或 PPT 导出的图片型 PDF。"""
    import pymupdf

    with pymupdf.open(src) as doc:
        n = min(sample_pages, doc.page_count)
        if not n:
            return 0.0
        return sum(len(doc[i].get_text().strip()) for i in range(n)) / n


def clip_pdf(src: Path, pages: int) -> Path:
    """只取前 N 页，另存到 work/，源文件不动。"""
    import pymupdf

    WORK.mkdir(parents=True, exist_ok=True)
    dst = WORK / f"{src.stem}__first{pages}p.pdf"
    if not dst.exists():
        with pymupdf.open(src) as doc:
            out = pymupdf.open()
            out.insert_pdf(doc, from_page=0, to_page=min(pages, doc.page_count) - 1)
            out.save(dst)
            out.close()
    return dst


def extract_figures(src: Path, out_dir: Path) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    figures: list[dict] = []
    if src.suffix.lower() == ".pdf":
        import pymupdf

        with pymupdf.open(src) as doc:
            for pno in range(doc.page_count):
                for xref, *_ in doc.get_page_images(pno, full=True):
                    if len(figures) >= MAX_FIGURES:
                        return figures
                    info = doc.extract_image(xref)
                    if len(info["image"]) < 8000:      # 跳过图标/分隔线一类小图
                        continue
                    name = f"p{pno+1:03d}_x{xref}.{info['ext']}"
                    (out_dir / name).write_bytes(info["image"])
                    figures.append({"file": f"figures/{name}", "page": pno + 1,
                                    "width": info.get("width"), "height": info.get("height"),
                                    "bytes": len(info["image"])})
    else:  # docx
        with zipfile.ZipFile(src) as zf:
            for item in sorted(n for n in zf.namelist() if n.startswith("word/media/")):
                if len(figures) >= MAX_FIGURES:
                    break
                data = zf.read(item)
                if len(data) < 8000:
                    continue
                name = Path(item).name
                (out_dir / name).write_bytes(data)
                figures.append({"file": f"figures/{name}", "page": None,
                                "width": None, "height": None, "bytes": len(data)})
    return figures


def split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    parts, buf = [], ""
    for seg in re.split(r"(?<=[。；！？\n])", text):
        if len(buf) + len(seg) > MAX_CHUNK_CHARS and buf:
            parts.append(buf)
            buf = ""
        buf += seg
    if buf.strip():
        parts.append(buf)
    return parts


def build_chunks(doc, doc_id: str) -> list[dict]:
    from docling.chunking import HierarchicalChunker

    chunks: list[dict] = []
    for raw in HierarchicalChunker().chunk(doc):
        headings = list(getattr(raw.meta, "headings", None) or [])
        pages = sorted({
            prov.page_no
            for item in getattr(raw.meta, "doc_items", [])
            for prov in getattr(item, "prov", [])
        })
        for piece in split_long(raw.text.strip()):
            piece = piece.strip()
            if len(piece) < MIN_CHUNK_CHARS:
                continue
            chunks.append({
                "id": f"{doc_id}#c{len(chunks):04d}",
                "doc_id": doc_id,
                "heading_path": headings,
                "text": piece,
                "page": pages[0] if pages else None,
                "pages": pages,
                "tokens": est_tokens(piece),
            })
    return chunks


def convert_one(cfg: dict, converter) -> dict:
    src = INPUT / cfg["file"]
    doc_id = cfg["doc_id"]
    out_dir = KB_OUT / "documents" / doc_id
    conv_src = clip_pdf(src, cfg["page_limit"]) if cfg.get("page_limit") else src
    # 平均每页不足 120 个可抽字符就当图片型 PDF，开 OCR；有文字层的不开，省时也避免重复
    need_ocr = conv_src.suffix.lower() == ".pdf" and text_density(conv_src) < 120

    # 单份文档的硬超时由**外层驱动（main）用子进程 + kill 兜底**实现，跨平台可靠；
    # 这里不再用 signal.SIGALRM / signal.alarm —— Windows 既无 SIGALRM 也无 alarm，
    # 在 worker 子进程里一调用就直接抛 ValueError，会让整份文档转换在还没开始就失败。
    # 原注释已说明 docling 会吞掉 SIGALRM 抛出的异常，故这段 in-process 超时本就是
    # 冗余且会害 Windows 跑不起来的，删除后功能零损失：文档级死锁（如 msword 后端
    # 在 VML 旧式图形上卡死）由 main 的 subprocess.run(timeout=DOC_TIMEOUT_S + 120)
    # 强制终止子进程覆盖。
    result = converter.convert(conv_src, ocr=need_ocr)
    doc = result.document
    md = doc.export_to_markdown()
    chunks = build_chunks(doc, doc_id)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "content.md").write_text(md, encoding="utf-8")
    with open(out_dir / "chunks.jsonl", "w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")

    fig_dir = out_dir / "figures"
    if fig_dir.exists():
        shutil.rmtree(fig_dir)
    figures = extract_figures(conv_src, fig_dir)

    ents = extract_entities(chunks, known_macros())
    write_json(out_dir / "entities.json", {"doc_id": doc_id, **ents})

    n_pages = len(getattr(doc, "pages", {}) or {}) or None
    n_tables = sum(1 for _ in getattr(doc, "tables", []) or [])
    source = {
        "doc_id": doc_id,
        "title": cfg["title"],
        "doc_type": cfg["doc_type"],
        "taxonomy": TAXONOMY,
        "process_tags": cfg["process_tags"],
        "format": src.suffix.lstrip(".").lower(),
        "pages": n_pages,
        "page_limit": cfg.get("page_limit"),
        "tables": n_tables,
        "source_path": str(src),
        "staged_input": str(conv_src),
        "sha256": sha256_file(src),
        "bytes": src.stat().st_size,
        "converter": "docling",
        "ocr": need_ocr,
        "note": cfg.get("note"),
    }
    write_json(out_dir / "source.json", source)
    return {**source, "chunks": len(chunks), "figures": len(figures),
            "markdown_chars": len(md), "status": "ok"}


def build_converter():
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.do_ocr = False                      # 手册是数字版 PDF，关 OCR 以保速度与可复现
    opts.do_table_structure = True
    # TableFormer 权重按可用情况选档：ACCURATE 表格保真更好，缺权重时退 FAST，不阻塞流水线
    mode = os.environ.get("TABLEFORMER_MODE", "").upper()
    if mode not in ("FAST", "ACCURATE"):
        acc = list(Path.home().glob(
            ".cache/huggingface/hub/models--ds4sd--docling-models/snapshots/*/"
            "model_artifacts/tableformer/accurate/tableformer_accurate.safetensors"))
        mode = "ACCURATE" if acc else "FAST"
    print(f"[config] TableFormer mode = {mode}", flush=True)
    opts.table_structure_options.mode = getattr(TableFormerMode, mode)

    ocr_opts = opts.model_copy(deep=True)
    ocr_opts.do_ocr = True                   # 图片型 PDF 才走，用 RapidOCR 自带的中文模型

    simple = DocumentConverter()             # docx/pptx 等，无需版面与表格模型

    class LazyConverter:
        """PDF 才构建带模型的 converter，其余格式走轻量 converter；OCR 版单独缓存。"""

        def __init__(self):
            self._pdf = {}

        def convert(self, path, ocr: bool = False):
            if Path(path).suffix.lower() != ".pdf":
                return simple.convert(path)
            if ocr not in self._pdf:
                self._pdf[ocr] = DocumentConverter(
                    format_options={InputFormat.PDF: PdfFormatOption(
                        pipeline_options=ocr_opts if ocr else opts)}
                )
            return self._pdf[ocr].convert(path)

    return LazyConverter()


def run_worker(doc_ids: list[str]) -> int:
    """子进程模式：转换给定文档，逐份把结果 JSON 写到 work/status/<doc-id>.json。"""
    reg = load_registry()
    by_id = {c["doc_id"]: c for c in reg["documents"]}
    converter = build_converter()
    status_dir = WORK / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    for doc_id in doc_ids:
        cfg = by_id[doc_id]
        try:
            info = convert_one(cfg, converter)
            print(f"[ok] {doc_id}: {info['chunks']} chunks, {info['pages']} pages, "
                  f"{info['tables']} tables, {info['figures']} figures", flush=True)
        except Exception as exc:                        # noqa: BLE001
            info = {"doc_id": doc_id, "title": cfg["title"], "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}"}
            print(f"[FAIL] {doc_id}: {exc}", flush=True)
            traceback.print_exc()
        write_json(status_dir / f"{doc_id}.json", info)
    return 0


def main() -> None:
    """驱动模式：每份文档起一个子进程并硬超时，避免个别文件把整条流水线卡死。

    docling 的 msword 后端在带 VML 旧式图形的 docx 上会陷入死循环，
    且它自己会吞掉 SIGALRM 抛出的异常，所以只能用子进程 + kill 兜底。
    """
    reg = load_registry()
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    targets = [c["doc_id"] for c in reg["documents"] if not only or c["doc_id"] in only]

    status_dir = WORK / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    report = []
    for doc_id in targets:
        sf = status_dir / f"{doc_id}.json"
        if sf.exists():
            sf.unlink()
        try:
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker", doc_id],
                timeout=None if os.environ.get("NO_TIMEOUT") else DOC_TIMEOUT_S + 120,
                capture_output=True, text=True, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            proc = subprocess.CompletedProcess(
                exc.cmd, returncode=-9,
                stdout=(exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
                stderr="子进程超时未退出，已被强制终止",
            )
        for line in proc.stdout.splitlines():
            if line.startswith(("[ok]", "[FAIL]", "[config]")):
                print(line, flush=True)
        if sf.exists():
            report.append(json.loads(sf.read_text(encoding="utf-8")))
        else:
            cfg = next(c for c in reg["documents"] if c["doc_id"] == doc_id)
            tail = (proc.stderr.strip().splitlines() or [""])[-1][:200]
            info = {
                "doc_id": doc_id, "title": cfg["title"], "status": "failed",
                "error": f"子进程未产出状态文件：超时 {DOC_TIMEOUT_S}s 被终止或崩溃"
                         f"（returncode={proc.returncode}）",
                "stderr_tail": tail,
            }
            write_json(sf, info)          # 失败也落一份状态，供 index 记录原因
            report.append(info)
            print(f"[FAIL] {doc_id}: 子进程超时/崩溃", flush=True)
    write_json(WORK / "convert_report.json", report)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        sys.exit(run_worker(sys.argv[2:]))
    main()
