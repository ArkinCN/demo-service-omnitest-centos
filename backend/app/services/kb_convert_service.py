"""知识库五阶段转化服务（主文档 3.1，P3）。

五阶段：识别 → 抽取 → 切片 → 结构化 → 索引，串行，**每阶段可单独重跑**。

三条硬约束（都来自主文档原文，别改）：
1. **阶段之间只传文件与 JSON，不共享内存状态**。
   每个阶段把产物写成 `<doc_dir>/<stage>.json`，下一阶段读文件、不读内存。
   所以这个模块**不缓存 converter**、不存全局状态——这正是约束要的效果。
2. **前三个阶段直接调 kb-pipeline 的 Docling 链路，不要换成别的解析器**。
   具体做法是**子进程**调 `c/kb-pipeline/.venv` 的解释器跑
   `scripts/01_convert_docs.py --worker`，而不是在后端进程里 import docling：
   后端环境**没有也不该有** docling（装它会顶掉 requirements.txt 锁定的
   pydantic/httpx，见 3-K 记录的那次环境事故）。
3. **失败必须给「哪一步、为什么」**。异常上带 `.stage`，路由据此落 failed_stage。

⚠️ 本单元（单元 1）的范围：上传 + 登记 + 状态机 + 产物读写骨架。
   其中**识别/抽取/切片**三阶段已真接 docling（子进程）；
   **结构化/索引**两阶段按八模板与三轴建模落地，本单元先产出可用的中间产物，
   八个文档类型的模板在单元 3 补全。
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.core.logger import logger
from app.core.paths import PROJECT_ROOT, kb_uploads_dir
from app.models.kb_document import KB_STAGES, STAGE_LABEL
from app.services.kb_struct_templates import (
    TEMPLATES,
    extract,
    is_implemented,
    score_confidence,
)

# kb-pipeline 的位置与它的独立 venv（见 3-K：docling 只装在这个 venv 里）
KB_PIPELINE = PROJECT_ROOT / "c" / "kb-pipeline"
KB_VENV_PY = KB_PIPELINE / ".venv" / "Scripts" / "python.exe"

# 单份文档的转化硬超时。registry 里记着那份 VML docx 实测 651 秒，
# 这里给到 900 秒以上，与 kb-pipeline 自己的 DOC_TIMEOUT_S 口径一致。
CONVERT_TIMEOUT_S = 1200

# 结构化阶段的置信度阈值：低于它进「需人工校对」（主文档 3.1 明写不允许静默通过）
CONFIDENCE_THRESHOLD = 0.6


class ConvertError(RuntimeError):
    """带阶段标记的转化失败。路由据此把 failed_stage 落对，而不是笼统一个 failed。"""

    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


def _doc_dir(doc_id: str) -> Path:
    return kb_uploads_dir() / doc_id


def _artifact_path(doc_id: str, stage: str) -> Path:
    return _doc_dir(doc_id) / f"{stage}.json"


def _write_artifact(doc_id: str, stage: str, payload: dict) -> str:
    p = _artifact_path(doc_id, stage)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        return str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def _read_artifact(doc_id: str, stage: str) -> dict:
    p = _artifact_path(doc_id, stage)
    if not p.exists():
        raise ConvertError(stage, f"缺少上一阶段产物 {stage}.json，无法继续（先跑该阶段）")
    return json.loads(p.read_text(encoding="utf-8"))


def _source_path(doc) -> Path:
    """原件路径。库里存的是相对项目根的路径（换机器可用），这里还原成绝对路径。"""
    raw = Path(doc.file_path)
    return raw if raw.is_absolute() else (PROJECT_ROOT / raw)


# ---------------------------------------------------------------- 阶段 1：识别

def stage_recognize(doc, prev: dict | None = None) -> dict:
    """识别：这份文件是什么（类型、页数/字数、是否图片型需 OCR）。

    「识别」这一阶段的产出是**对文件的判断**，不是正文——正文在抽取阶段。
    所以这里只读元信息，不做重解析（用轻量探针，不启动 docling）。
    """
    src = _source_path(doc)
    if not src.exists():
        raise ConvertError("recognize", f"原件不在盘上：{src}")

    info: dict = {
        "file_name": doc.file_name,
        "file_type": doc.file_type,
        "size_bytes": doc.size_bytes,
        "sha256": doc.sha256,
        "recognized_at": datetime.now(timezone.utc).isoformat(),
    }

    ext = doc.file_type.lower()
    if ext == "pdf":
        try:
            import pymupdf  # 轻量，后端环境本就有（requirements 里带）

            with pymupdf.open(src) as pdf:
                pages = pdf.page_count
                sample = min(5, pages)
                chars = sum(len(pdf[i].get_text().strip()) for i in range(sample))
                density = chars / sample if sample else 0.0
                info.update({
                    "pages": pages,
                    "text_density": round(density, 1),
                    # 平均每页不足 120 个可抽字符 → 图片型 PDF，抽取阶段要开 OCR
                    "needs_ocr": density < 120,
                })
        except ImportError:
            # 探针不可用不该让整条流水线停：如实标注，交给抽取阶段判断
            info.update({"pages": None, "needs_ocr": None,
                         "note": "pymupdf 不可用，页数与 OCR 判断留空"})
    elif ext in ("docx", "doc"):
        info.update({"pages": None, "needs_ocr": False,
                     "note": "word 文档，页数由 docling 在抽取阶段给出"})
    else:
        info.update({"pages": None, "needs_ocr": False})

    return info


# ------------------------------------------------- 阶段 2/3：抽取 + 切片（docling）

def _run_docling_worker(doc) -> dict:
    """用 kb-pipeline 的 venv 跑 01_convert_docs.py 的 worker，拿回 content/chunks。

    为什么要子进程 + 独立 venv：
      - 后端环境没有 docling（装它会顶掉锁定的 pydantic/httpx，3-K 有记录）；
      - docling 在个别 docx 上会卡死，子进程 + 超时是唯一可靠的兜底（脚本自己的注释也这么说）。
    """
    if not KB_VENV_PY.exists():
        raise ConvertError(
            "extract",
            f"docling 运行环境不存在：{KB_VENV_PY}。"
            f"按 kb-pipeline/README 建 venv 并装 docling==2.129.0 后再试。",
        )

    src = _source_path(doc)
    out_dir = _doc_dir(doc.doc_id)
    # 把原件复制到脚本期待的 input/ 结构下（脚本按 registry 的相对路径找文件），
    # 这里改为直接传绝对路径给 worker：见下面 _worker_entry 的说明。
    cmd = [
        str(KB_VENV_PY), str(KB_PIPELINE / "scripts" / "_upload_worker.py"),
        "--src", str(src),
        "--out", str(out_dir),
        "--doc-id", doc.doc_id,
        "--title", doc.title,
    ]
    logger.info(f"kb convert: running docling worker for {doc.doc_id}")
    try:
        _run_kwargs = dict(
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=CONVERT_TIMEOUT_S, check=False,
        )
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            _run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.run(cmd, **_run_kwargs)
    except subprocess.TimeoutExpired:
        raise ConvertError(
            "extract",
            f"docling 转换超过 {CONVERT_TIMEOUT_S}s 被终止"
            f"（该 docx 带 VML 旧式图形时实测可达 651s，若确认是这类文件可调大超时）",
        )
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
        raise ConvertError("extract", f"docling 退出码 {proc.returncode}：{tail[0][:300]}")

    result_file = out_dir / "docling_result.json"
    if not result_file.exists():
        raise ConvertError("extract", "docling 跑完但没有产出 docling_result.json")
    return json.loads(result_file.read_text(encoding="utf-8"))


def _docling_result(doc) -> dict:
    """取（或生成）本次文档的 docling 结果。

    ⚠️ **docling 只跑一次**：extract 与 chunk 都要用它，若各跑一次就是同一份文件
    白转两遍（那份 VML docx 一次 651 秒，跑两遍就是 20 分钟）。所以第一次跑完
    把结果缓存到 `docling_result.json`，后续阶段直接读文件——这也正好符合
    「阶段之间只传文件与 JSON」的约束（缓存的是**文件**，不是内存对象）。
    """
    p = _doc_dir(doc.doc_id) / "docling_result.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            p.unlink()  # 坏文件重跑，别拿它当结果
    return _run_docling_worker(doc)


def stage_extract(doc, prev: dict | None = None) -> dict:
    """抽取：调 docling 把原件转成 Markdown 正文（落 content.md）。"""
    res = _docling_result(doc)
    md = res.get("markdown") or ""
    if not md.strip():
        raise ConvertError("extract", "docling 抽出的正文为空（可能是纯扫描件且未开 OCR）")
    out_dir = _doc_dir(doc.doc_id)
    (out_dir / "content.md").write_text(md, encoding="utf-8")
    return {
        "markdown_chars": len(md),
        "tables": res.get("tables", 0),
        "figures": res.get("figures", 0),
        "ocr": res.get("ocr", False),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }


def _fallback_chunks(md: str, doc_id: str) -> list[dict]:
    """按段落降级切分。

    为什么需要它：`HierarchicalChunker` 按**文档层级**切块，对没有标题结构的
    极简文档（或抽出来只有平铺段落的文件）会返回 0 块。此时若直接失败，
    表现就是「正文明明抽到了，却卡在切片」——而正文是有的，不该卡。
    所以按空行分段兜底，**并在产物里标明是降级切分**，不冒充层级切片。
    """
    chunks: list[dict] = []
    # 先按空行分块；再按单行分（很多手册是一行一条，没有空行）
    blocks = [b.strip() for b in md.split("\n\n") if b.strip()]
    if not blocks:
        blocks = [ln.strip() for ln in md.splitlines() if ln.strip()]
    for b in blocks:
        for piece in _split_long(b):
            if len(piece.strip()) < 10:
                continue
            chunks.append({
                "id": f"{doc_id}#f{len(chunks):04d}",
                "heading_path": [],
                "text": piece.strip(),
                "page": None,
                "pages": [],
                "tokens": max(1, len(piece) // 2),
                "fallback": True,
            })
    return chunks


def _split_long(text: str, limit: int = 1200) -> list[str]:
    """长段按句读切，避免单个块过大。与 01_convert_docs.py 的 split_long 同口径。"""
    import re as _re

    if len(text) <= limit:
        return [text]
    parts, buf = [], ""
    for seg in _re.split(r"(?<=[。；！？\n])", text):
        if len(buf) + len(seg) > limit and buf:
            parts.append(buf)
            buf = ""
        buf += seg
    if buf.strip():
        parts.append(buf)
    return parts


def stage_chunk(doc, prev: dict | None = None) -> dict:
    """切片：把正文按层级切成可检索单元（落 chunks.jsonl）。"""
    out_dir = _doc_dir(doc.doc_id)
    chunks_file = out_dir / "chunks.jsonl"
    res = _docling_result(doc)
    chunks = res.get("chunks") or []

    degraded = False
    if not chunks:
        # 层级切不出块（极简文档 / 无标题结构）→ 按段落降级，而不是直接失败。
        # 「正文在、却切不出」是切分策略问题，不该让整条流水线停在半路。
        md = res.get("markdown") or ""
        if not md.strip():
            raise ConvertError("chunk", "正文为空，无法切片（先跑 extract 阶段）")
        chunks = _fallback_chunks(md, doc.doc_id)
        degraded = True
        if not chunks:
            raise ConvertError("chunk", "按段落降级后仍切不出任何单元，正文可能只有空白")

    with chunks_file.open("w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    return {
        "count": len(chunks),
        "max_chars": max((len(c.get("text", "")) for c in chunks), default=0),
        # 降级切分要标出来：下游/人看到 fallback 就知道这些块没有层级信息
        "degraded": degraded,
        "note": (
            "层级切分未产出块，已按段落降级切分（块无层级信息，置信度会相应偏低）"
            if degraded else "层级切分"
        ),
        "chunked_at": datetime.now(timezone.utc).isoformat(),
    }


# ------------------------------------------------------------ 阶段 4：结构化

# 八个文档类型 → 结构化模板名（主文档附录 A.3：八个类型各一份模板）
#
# ⚠️ 现状：**只有三类有真抽模板**（数据手册 / 调试手册 / 源码参数配置，
# 实现在 `kb_struct_templates.py`）。其余五类**仍是骨架**，产物里会如实标
# `template_pending: true`，不冒充已精抽。这是本轮与用户共同确认的范围。
DOC_TYPE_TEMPLATES = {
    "数据手册": "datasheet",
    "调试手册": "debug-manual",
    "应用手册": "app-note",
    "原理文档": "principle",
    "培训材料": "training",
    "问题汇总": "issue-summary",
    "考核题库": "exam",
    "源码参数配置": "header-config",
}


def _skeleton_fields(chunks: list[dict]) -> list[dict]:
    """未实现模板的五类走骨架：只给「切片 → 带层级的字段骨架」。

    刻意保留这个函数而不是删掉：骨架仍有价值（人能顺着层级看到正文分布），
    但它**不是结构化字段**，产物里会明确标出来，别让下游当成精抽结果用。
    """
    out: list[dict] = []
    for c in chunks[:200]:
        h = " > ".join(c.get("heading_path") or [])
        out.append({
            "chunk_id": c.get("id"),
            "heading": h,
            "page": c.get("page"),
            "text": (c.get("text") or "")[:400],
        })
    return out


def stage_struct(doc, prev: dict | None = None) -> dict:
    """结构化：按文档类型套模板抽结构化字段，并给置信度。

    ⚠️ 置信度低于阈值的**进「需人工校对」**，不允许静默通过（主文档 3.1）。

    两条分支（见 `kb_struct_templates.TEMPLATES`）：
      - 三类**已实现**：走真抽模板，产出 `fields` 为真实业务字段（键值对），
        并附 `hit_keys` / `missing_keys` / `confidence_detail` 供人工复算。
      - 其余五类**未实现**：走骨架，标 `template_pending: true` 并在 note 里
        写清「模板待补，本产物不是精抽结果」。**不假装做完了。**

    置信度随之换口径：已实现的三类用 `score_confidence()` 的**三因子**
    （类型判定 0.4 + 关键字段命中率 0.4 + 层级完整度 0.2）；未实现的三类
    仍用旧的单一判据（带层级标题的切片占比），并在产物里注明用的是哪一个。
    """
    chunks = _read_chunk_lines(doc.doc_id)
    if not chunks:
        raise ConvertError("struct", "没有切片可结构化（先跑 chunk 阶段）")

    # 类型判定：先看标题里的关键词，判不出用「未分类」——**不硬凑一个类型**。
    tpl = _guess_template(doc.title, doc.file_name)
    typed = tpl != "unclassified"
    degraded = any(c.get("fallback") for c in chunks)

    # 正文：docling 抽出的 Markdown（表格抽取要靠它，chunks 里已按块切碎）
    md_file = _doc_dir(doc.doc_id) / "content.md"
    markdown = md_file.read_text(encoding="utf-8") if md_file.exists() else ""

    implemented = is_implemented(tpl)

    if implemented:
        # ── 真抽：三类各按自己的规则抽真实业务字段 ──
        raw = extract(tpl, chunks, markdown)
        fields = raw.get("fields", [])
        hit_keys = raw.get("hit_keys", [])
        missing_keys = raw.get("missing_keys", [])
        _fn, key_list, label = TEMPLATES[tpl]
        confidence, conf_detail = score_confidence(
            typed=typed,
            hit_keys=hit_keys,
            key_total=len(key_list),
            chunks=chunks,
        )
        note = (
            f"按「{label}」模板精抽，命中 {len(hit_keys)}/{len(key_list)} 个关键字段。"
            + (f"未命中：{'、'.join(missing_keys)}。" if missing_keys else "")
            + ("本文件走的是段落降级切分（无层级），层级完整度记为 0。"
               if degraded else "")
        )
        for n in raw.get("notes", []):
            note += " " + n
        extra = {k: v for k, v in raw.items()
                 if k not in ("fields", "hit_keys", "missing_keys", "notes")}
        return {
            "template": tpl,
            "doc_type": label,
            "template_pending": False,
            "fields": fields,
            "field_count": len(fields),
            "hit_keys": hit_keys,
            "missing_keys": missing_keys,
            "confidence": confidence,
            "confidence_detail": conf_detail,
            "confidence_basis": "三因子加权（类型判定/关键字段命中率/层级完整度）",
            "threshold": CONFIDENCE_THRESHOLD,
            "needs_review": confidence < CONFIDENCE_THRESHOLD,
            "degraded": degraded,
            "note": note,
            "structured_at": datetime.now(timezone.utc).isoformat(),
            **extra,
        }

    # ── 骨架：五类未实现模板，如实标注，不冒充精抽 ──
    #
    # 置信度仍用旧判据（带层级标题的切片占比）。这是**保守且可解释**的度量：
    # heading 缺失的切片多半是抽取出问题的。降级切分产出的块全都没 heading，
    # 置信度必然为 0 → 进「需人工校对」，这是**故意**的。
    with_heading = sum(1 for c in chunks if c.get("heading_path"))
    confidence = round(with_heading / len(chunks), 3) if chunks else 0.0
    label = _template_label(tpl)

    return {
        "template": tpl,
        "doc_type": label,
        # 这一位是给界面和下游看的：**模板没做**，产物不是精抽结果
        "template_pending": True,
        "fields": _skeleton_fields(chunks),
        "field_count": len(chunks[:200]),
        "hit_keys": [],
        "missing_keys": [],
        "confidence": confidence,
        "confidence_detail": {
            "heading_ratio": confidence,
            "formula": "1.0*heading_ratio（骨架口径）",
        },
        "confidence_basis": "骨架口径（带层级标题的切片占比）",
        "threshold": CONFIDENCE_THRESHOLD,
        "needs_review": confidence < CONFIDENCE_THRESHOLD,
        "degraded": degraded,
        "note": (
            f"「{label}」的结构化模板**待补**（本轮只做了数据手册/调试手册/"
            f"源码参数配置三类）；本产物是「切片 → 带层级的字段骨架」，"
            f"**不是精抽结果**，置信度 = 带层级标题的切片占比。"
            + ("本文件走的是段落降级切分（无层级），故置信度为 0、进人工校对。"
               if degraded else "")
        ),
        "structured_at": datetime.now(timezone.utc).isoformat(),
    }


def _read_chunk_lines(doc_id: str) -> list[dict]:
    p = _doc_dir(doc_id) / "chunks.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _guess_template(title: str, file_name: str) -> str:
    """按标题/文件名关键词猜模板。猜不出返回 unclassified——**不硬凑类型**。"""
    s = f"{title} {file_name}"
    rules = [
        ("数据手册", ("数据手册", "datasheet", "MCU-DS", "DS-")),
        ("调试手册", ("调试手册", "调试", "FOC方案")),
        ("应用手册", ("应用手册", "方案应用", "appnote", "app-note")),
        ("考核题库", ("考核", "考试题", "题库")),
        ("问题汇总", ("bug", "问题汇总", "修改原因")),
        ("培训材料", ("培训", "training")),
        ("源码参数配置", (".h", "customer", "宏", "参数配置")),
        ("原理文档", ("原理", "执行逻辑", "估算", "逻辑")),
    ]
    low = s.lower()
    for label, keys in rules:
        if any(k.lower() in low for k in keys):
            return DOC_TYPE_TEMPLATES.get(label, "unclassified")
    return "unclassified"


def _template_label(tpl: str) -> str:
    for label, t in DOC_TYPE_TEMPLATES.items():
        if t == tpl:
            return label
    return "未分类"


# ---------------------------------------------------------------- 阶段 5：索引

def stage_index(doc, prev: dict | None = None, session=None) -> dict:
    """索引：把切片**真正写入**知识条目（`kb_entries`），使其可被检索。

    为什么必须真写库（而不是只落一份清单）：
    阶段 3 的验收 1 是「上传资料 → 助手返回**有出处**的建议」。助手走的是
    `kb_search` → 语料是 `public/kb/` 下的流水线产物；而**用户上传的文档
    不在那份静态语料里**。所以「上传后可被检索到」这件事，必须真的把条目
    写进库、并让检索侧看得到（向量/关键词索引见 kb_embed_service）。

    复用既有三轴条目模型（`app/services/kb_entry_service.py`），**不另建一套**。

    参数 `session` 为 None 时**明确失败**，不静默跳过写库：
    静默跳过会造成「产物看着齐全、库里一条没有」——正是项目最贵的那类坑
    （界面正常但数据一条都没落）。宁可报错。
    """
    chunks = _read_chunk_lines(doc.doc_id)
    if not chunks:
        raise ConvertError("index", "没有切片可索引（先跑 chunk 阶段）")
    struct_art = _read_artifact(doc.doc_id, "struct")

    if session is None:
        raise ConvertError(
            "index",
            "索引阶段需要数据库会话（session）才能把条目写入 kb_entries；"
            "当前调用未传 session，拒绝静默跳过写库。",
        )

    # ⚠️ 延迟导入：本模块被 scripts 单独导入时不必然有 DB 上下文，
    # 放在函数内可避免「import 就得连库」。
    from app.services.kb_entry_service import doc_entry_key, upsert_entry

    owner = (doc.owner_l1, doc.owner_l2, doc.owner_l3)
    usage = doc.usage if doc.usage in ("spec", "requirement", "process") else "process"

    created = 0
    updated = 0
    keys: list[str] = []
    for c in chunks:
        cid = str(c.get("id") or "")
        if not cid:
            continue
        # entry_key 带**文档维度前缀**：两份文档的切片编号可能撞号，
        # 不带前缀会静默串包（3-I 教训：EXP-001…018 完全重号）。
        key = doc_entry_key(doc.doc_id, cid)
        # content 形状对齐前端 toEntry() 读法 + 场景包导入的 content 形状：
        # 文档类条目的可读正文放 `note`/`summary`，片段与出处放各自字段。
        content = {
            "id": key,
            "type": doc.file_type,
            "title": doc.title,
            "path": doc.file_path,
            "size_bytes": doc.size_bytes,
            "page": c.get("page"),
            "heading_path": c.get("heading_path") or [],
            "text": c.get("text") or "",
            "chunks": 1,
            "_status": "来自上传文档的在线转化",
            "conversion_status": "indexed",
            "conversion_status_label": "已入库",
            "source_doc_id": doc.doc_id,
        }
        _entry, is_new = upsert_entry(
            session,
            entry_key=key,
            origin="doc",
            title=doc.title,
            usage=usage,
            owner_l1=owner[0],
            owner_l2=owner[1],
            owner_l3=owner[2],
            content=content,
            change_reason=f"上传文档转化入库（{doc.file_name}）",
        )
        keys.append(key)
        if is_new:
            created += 1
        else:
            updated += 1

    session.commit()

    return {
        "chunk_count": len(chunks),
        "entry_count": len(keys),
        "entries_created": created,
        "entries_updated": updated,
        "entry_keys_sample": keys[:5],
        "template": struct_art.get("template"),
        "template_pending": struct_art.get("template_pending", False),
        "owner": {"l1": owner[0], "l2": owner[1], "l3": owner[2]},
        "usage": usage,
        "note": (
            f"已写入 kb_entries：新建 {created} 条、更新 {updated} 条"
            f"（entry_key 前缀 {doc.doc_id}#）。"
        ),
        "indexed_at": datetime.now(timezone.utc).isoformat(),
    }


_STAGE_FN = {
    "recognize": stage_recognize,
    "extract": stage_extract,
    "chunk": stage_chunk,
    "struct": stage_struct,
    "index": stage_index,
}


def run_stages(doc, start: str = "recognize", until: str = "index", session=None) -> dict:
    """从 start 跑到 until（含两端）。每阶段的产物落盘，重跑即从该阶段重算。

    返回 {"stage": 最后完成的阶段, "artifacts": {阶段: 产物路径}, ...}

    `session`：索引阶段要真写库，必须由调用方（路由）把自己的 db 会话传进来。
    不传时索引阶段会**明确报错**而不是静默跳过写库——见 stage_index 的说明。
    """
    i0, i1 = KB_STAGES.index(start), KB_STAGES.index(until)
    artifacts: dict = {}
    last_stage = start
    entry_count = 0
    confidence = None
    needs_review = False

    for stage in KB_STAGES[i0:i1 + 1]:
        fn = _STAGE_FN[stage]
        logger.info(f"kb convert: {doc.doc_id} → {stage}({STAGE_LABEL[stage]})")
        try:
            # 索引阶段需要 session；其余阶段的函数签名带默认值，传不传都可以。
            payload = fn(doc, None, session) if stage == "index" else fn(doc, None)
        except ConvertError:
            raise
        except Exception as exc:  # noqa: BLE001
            # 包成带阶段的错误，路由才能落对 failed_stage
            raise ConvertError(stage, f"{type(exc).__name__}: {exc}") from exc
        path = _write_artifact(doc.doc_id, stage, payload)
        artifacts[stage] = {
            "path": path,
            "done_at": datetime.now(timezone.utc).isoformat(),
            "summary": _summarize(stage, payload),
        }
        last_stage = stage
        if stage == "struct":
            confidence = payload.get("confidence")
            needs_review = bool(payload.get("needs_review"))
        if stage == "index":
            # 真写库后的条目数；取不到才退回切片数（并会在 note 里看出来）
            entry_count = int(payload.get("entry_count") or payload.get("chunk_count") or 0)

    return {
        "stage": last_stage,
        "artifacts": artifacts,
        "entry_count": entry_count,
        "confidence": confidence,
        "needs_review": needs_review,
    }


def _summarize(stage: str, payload: dict) -> str:
    """一句话摘要，给界面显示用。不塞整个产物（那会撑爆详情接口）。"""
    if stage == "recognize":
        return f"{payload.get('file_type')} · {payload.get('pages') or '—'} 页"
    if stage == "extract":
        return f"{payload.get('markdown_chars', 0)} 字 · {payload.get('tables', 0)} 表"
    if stage == "chunk":
        return f"{payload.get('count', 0)} 个切片"
    if stage == "struct":
        # 摘要必须让界面一眼分出「精抽」与「骨架」：模板没做的类型要显式写出来，
        # 否则人看到「置信度 0.0」会以为抽失败了，其实是模板还没做。
        label = payload.get("doc_type")
        if payload.get("template_pending"):
            return f"{label} · 模板待补（骨架）· 置信度 {payload.get('confidence')}"
        hit = len(payload.get("hit_keys") or [])
        total = hit + len(payload.get("missing_keys") or [])
        return f"{label} · 命中 {hit}/{total} 关键字段 · 置信度 {payload.get('confidence')}"
    if stage == "index":
        # 真写库之后要报「落了多少条」，而不是「多少条待入库」——
        # 后者是上一版的措辞，会让人以为还没写。
        n = payload.get("entry_count")
        if n is None:
            n = payload.get("chunk_count", 0)
        return f"已入库 {n} 条"
    return ""
