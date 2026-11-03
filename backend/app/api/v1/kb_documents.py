"""知识库文档上传与五阶段转化路由（主文档 3.1，P3）。

端点：
  POST   /api/kb/documents                 上传一份原件（存盘 + 登记，状态 pending）
  GET    /api/kb/documents                 列表（可按场景/状态过滤）
  GET    /api/kb/documents/{doc_id}        单份详情（含五阶段进度与产物摘要）
  POST   /api/kb/documents/{doc_id}/run    推进流水线（可指定只跑到某个阶段 / 重跑某阶段）
  DELETE /api/kb/documents/{doc_id}        软删除登记（原件保留，见下）

三条设计口径（都对着主文档 3.1 的原文落）：
1. **阶段之间只传文件与 JSON，不共享内存状态**。每个阶段的产物写到
   `kb_uploads_dir()/<doc_id>/<stage>.json`，重跑就是从该阶段起重算。
   所以这里**不缓存转换器实例**——那是「共享内存状态」，正是要避免的。
2. **docling 在本机独立 venv 里**（`c/kb-pipeline/.venv`，见 3-K 的环境事故），
   后端环境**没有** docling，也不该有（会顶掉锁定的 pydantic/httpx）。
   所以转化是靠 **子进程调 venv 解释器**跑的，不是 import。
3. **失败必须给「哪一步、为什么」**。主文档明写「转化失败（给失败阶段与原因）」，
   只写一个 failed 不合格——所以 failed_stage / fail_reason 两个字段是非空要求。

⚠️ 本文件当前实现到「上传 + 登记 + 状态机骨架 + 阶段产物读写」；
   真正的 docling 调用在 services/kb_convert_service.py 里，**识别/抽取/切片**
   复用 kb-pipeline 的 01_convert_docs.py，「结构化/索引」按八模板与三轴建模推进。
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select
from starlette.background import BackgroundTask

from app.api.deps import get_current_user, get_db
from app.api.v1.kb_entries import latest_active_scoped
from app.core.exceptions import BadRequestException, NotFoundException
from app.core.logger import logger
from app.core.paths import PROJECT_ROOT, kb_extract_dir, kb_uploads_dir
from app.schemas.kb_entry import KbEntryRead
from app.models.kb_document import (
    KB_STAGES,
    STAGE_LABEL,
    STATUS_LABEL,
    KbDocument,
)
from app.models.user import User
from app.schemas.common import success_response

router = APIRouter(prefix="/kb/documents", tags=["Knowledge Base · Documents"])

# 允许的原件类型。与 kb-pipeline 的 registry 登记口径一致（pdf / docx / doc / 源码）。
ALLOWED_EXT = {".pdf", ".docx", ".doc", ".md", ".txt", ".h", ".c"}
# 单份原件上限。客户手册多为 3–20 MB，数据手册到 20 MB，给到 100 MB 足够且防滥用。
MAX_BYTES = 100 * 1024 * 1024


def _docs_dir(doc_id: str) -> Path:
    """某份文档的产物目录。**所有阶段产物都落在这里**（阶段间只传文件与 JSON）。"""
    return kb_uploads_dir() / doc_id


def _rel(p: Path) -> str:
    """转成相对项目根的路径：换机器后仍然可用，不写死盘符（见 paths.py 的纪律）。"""
    try:
        return str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def _slug(name: str) -> str:
    """文件名 → 稳定的 doc_id 片段。中文保留（它是有效字符），只清掉路径分隔与空白。"""
    stem = Path(name).stem.strip()
    s = re.sub(r"[\\/:*?\"<>|\s]+", "-", stem)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:60] or "doc"


def _to_dict(d: KbDocument) -> dict:
    """对外形状。status 是五值、stage 是阶段名，两者都给，且都附中文标签。"""
    return {
        "doc_id": d.doc_id,
        "title": d.title,
        "file_name": d.file_name,
        "file_type": d.file_type,
        "size_bytes": d.size_bytes,
        "sha256": d.sha256,
        "owner_l1": d.owner_l1,
        "owner_l2": d.owner_l2,
        "owner_l3": d.owner_l3,
        "usage": d.usage,
        "usage_label": d.usage_label,
        "status": d.status,
        "status_label": STATUS_LABEL.get(d.status, d.status),
        "stage": d.stage,
        "stage_label": STAGE_LABEL.get(d.stage, "") if d.stage else "",
        # 五阶段各自的完成情况，前端进度条直接用
        "stages": [
            {
                "key": s,
                "label": STAGE_LABEL[s],
                "done": _stage_done(d, s),
                "artifact": (d.artifacts or {}).get(s),
            }
            for s in KB_STAGES
        ],
        "failed_stage": d.failed_stage,
        "fail_reason": d.fail_reason,
        "entry_count": d.entry_count,
        "confidence": d.confidence,
        "uploaded_by": d.uploaded_by,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _stage_done(d: KbDocument, stage: str) -> bool:
    return bool((d.artifacts or {}).get(stage))


@router.post("")
async def upload_document(
    file: UploadFile = File(..., description="原件（pdf/docx/doc/md/txt/源码）"),
    title: str = Form(default="", description="标题；留空取文件名"),
    owner_l1: str = Form(default=""),
    owner_l2: str = Form(default=""),
    owner_l3: str = Form(default=""),
    usage: str = Form(default="process", description="spec / requirement / process（固定三类）"),
    usage_label: str = Form(default="", description="自定义用途标签，可空；不占三轴"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # 门禁
):
    """上传一份原件：存盘 + 登记，状态 pending（不在这里跑转化）。

    为什么上传与转化分开：转化可能跑几分钟（那份 VML docx 实测 651 秒），
    挂在 HTTP 请求里会让上传超时、重试还会重复落盘。所以上传只做两件确定的事，
    转化由 /run 显式触发（或前端上传后立刻调一次）。
    """
    name = file.filename or ""
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise BadRequestException(
            f"不支持的文件类型 {ext or '(无扩展名)'}；支持：{' / '.join(sorted(ALLOWED_EXT))}"
        )

    data = await file.read()
    if not data:
        raise BadRequestException("文件是空的（0 字节）")
    if len(data) > MAX_BYTES:
        raise BadRequestException(f"文件超过上限 {MAX_BYTES // 1024 // 1024} MB")

    digest = hashlib.sha256(data).hexdigest()

    # 同场景内按 sha256 去重：同一份文件重复上传没有意义，且会重复产出条目。
    # 命中已存在的就把那条**原样返回**并标注，不新建（前端据此提示「已存在」）。
    existing = session.exec(
        select(KbDocument).where(
            KbDocument.sha256 == digest, KbDocument.owner_l3 == owner_l3
        )
    ).first()
    if existing is not None:
        return success_response(
            data=_to_dict(existing),
            message=f"这份文件已经上传过了（{existing.file_name}），未重复入库",
        )

    doc_id = f"{_slug(name)}-{uuid.uuid4().hex[:8]}"
    dest_dir = _docs_dir(doc_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / (Path(name).name or f"{doc_id}{ext}")
    dest.write_bytes(data)

    doc = KbDocument(
        doc_id=doc_id,
        title=(title or Path(name).stem or doc_id).strip(),
        file_name=Path(name).name,
        file_path=_rel(dest),
        size_bytes=len(data),
        sha256=digest,
        file_type=ext.lstrip("."),
        owner_l1=owner_l1,
        owner_l2=owner_l2,
        owner_l3=owner_l3,
        usage=usage if usage in ("spec", "requirement", "process") else "process",
        usage_label=(usage_label or "").strip()[:100],
        status="pending",
        stage="",
        uploaded_by=getattr(current_user, "username", "") or "",
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    logger.info(f"kb document uploaded: {doc_id} ({doc.file_name}, {len(data)} bytes)")
    return success_response(data=_to_dict(doc), message="已上传，等待转化", code=201)


@router.get("")
async def list_documents(
    owner_l3: str = "",
    status: str = "",
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),  # 门禁
):
    """文档列表。按最近上传倒序——人最关心刚传的那份。"""
    q = select(KbDocument)
    if owner_l3:
        q = q.where(KbDocument.owner_l3 == owner_l3)
    if status:
        q = q.where(KbDocument.status == status)
    rows = list(session.exec(q).all())
    rows.sort(key=lambda d: d.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return success_response(data={
        "items": [_to_dict(d) for d in rows[:limit]],
        "total": len(rows),
        # 各状态的计数，供界面顶部筛选显示（口径同 kb/entries：不做范围外统计）
        "counts": {
            s: sum(1 for d in rows if d.status == s)
            for s in ("pending", "converting", "indexed", "failed", "needs_review")
        },
    })


# ---------------------------------------------------------------- 抽取稿读取
#
# ⚠️ 这两个端点必须注册在 `@router.get("/{doc_id}")` **之前**：FastAPI 按注册顺序匹配，
# `/{doc_id}` 会把 `content-by-title` 当成 doc_id 抢走。
#
# 数据来源：数据侧 `c/data/kb/documents/<doc_id>/content.md`（docling 抽取的 Markdown 正文）。
# ⚠️ 这是**系统抽取稿，不是客户原件**——客户原始 PDF 是脱敏占位路径（`[源] ...`），
# 文件在客户内网盘、从未进本机。接口返回 `is_extract: true` + note 如实标注这一点。

def _kb_extract_root() -> Path:
    return kb_extract_dir()


def _resolve_doc_id_by_title(title: str, owner_l3: str = "") -> str | None:
    """按文档标题反查抽取稿 doc_id。

    钥匙顺序（先精确、后兜底，**不猜**）：
      ① 遍历数据侧 index.json 的 documents[]，title **精确等值**匹配；
      ② 若命中**多个**（同名不同产品），才用 owner_l3 消歧；
      ③ 若只命中一个，**直接返回**——不因 owner 形式不一致而误判「没有」。

    ⚠️ owner_l3 消歧要做**宽松**匹配：数据侧 `taxonomy.l3` 是英文 slug（如 `fortior-fu6832`），
    而前端传的是中文产品名（如「FU6832 散热风扇驱动板」），两边**必然不等**。
    早前写成严格等值，导致唯一匹配也被排除 → 一律 404（实测踩过）。
    这里改为：中文字名双方**互为子串**（忽略大小写/空格）即视为同一产品。
    """
    root = _kb_extract_root()
    idx = root / "index.json"
    if not idx.is_file():
        return None
    try:
        data = json.loads(idx.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    hits = [
        d for d in (data.get("documents") or [])
        if isinstance(d, dict) and (d.get("title") or "").strip() == title.strip()
    ]
    if not hits:
        return None
    if len(hits) == 1:
        return str(hits[0].get("doc_id") or "") or None

    # 多个同名：用 owner_l3 宽松消歧
    def _norm(s: str) -> str:
        return re.sub(r"[\s_\-]+", "", (s or "").lower())

    if owner_l3:
        want = _norm(owner_l3)
        for d in hits:
            l3 = _norm(str((d.get("taxonomy") or {}).get("l3") or ""))
            if l3 and (l3 in want or want in l3):
                return str(d.get("doc_id") or "") or None
    logger.warning(f"kb: title「{title}」命中 {len(hits)} 个，取第一个")
    return str(hits[0].get("doc_id") or "") or None


def _extract_file(doc_id: str) -> Path | None:
    """取某 doc_id 的 content.md；**防路径穿越**：doc_id 只当目录名，且结果必须落在根内。"""
    if not doc_id or "/" in doc_id or "\\" in doc_id or ".." in doc_id:
        return None
    root = _kb_extract_root().resolve()
    target = (root / doc_id / "content.md")
    try:
        target = target.resolve()
    except OSError:
        return None
    if root not in target.parents and target.parent != root:
        return None  # 越界，拒绝
    return target if target.is_file() else None


@router.get("/content-by-title")
async def get_content_by_title(
    title: str = Query(..., description="文档标题（与数据侧 index.json 的 title 精确匹配）"),
    owner_l3: str = Query(default="", description="三级产品类型名，用于同名消歧（可选）"),
    _: User = Depends(get_current_user),  # 门禁
):
    """按标题读抽取稿全文（Markdown）。查不到返回 404 + 明确原因，不返回空串。"""
    doc_id = _resolve_doc_id_by_title(title, owner_l3)
    if not doc_id:
        raise NotFoundException(f"本机无「{title}」的抽取稿（原件在客户侧，未随包交付）")
    f = _extract_file(doc_id)
    if f is None:
        raise NotFoundException(f"「{title}」的抽取稿文件缺失（doc_id={doc_id}）")
    try:
        text = f.read_text(encoding="utf-8")
    except OSError as exc:
        raise NotFoundException(f"读取抽取稿失败：{exc}") from exc
    logger.info(f"kb extract content: {doc_id} ({len(text)} chars)")
    return success_response(data={
        "doc_id": doc_id,
        "title": title,
        "text": text,
        "is_extract": True,
        "note": "内容为系统抽取稿（Markdown），非客户原件 PDF。",
    })


@router.get("/{doc_id}/download")
async def download_extract(
    doc_id: str,
    _: User = Depends(get_current_user),  # 门禁
):
    """下载抽取稿 content.md（附件名为「<doc_id>-抽取稿.md」）。

    ⚠️ 不是客户原件——原件是脱敏占位路径，本机无字节。文件名与前端提示都如实标注。
    """
    f = _extract_file(doc_id)
    if f is None:
        raise NotFoundException(f"doc_id={doc_id} 的抽取稿不存在")
    logger.info(f"kb extract download: {doc_id} ({f.stat().st_size} bytes)")
    # media_type 不带 charset：FileResponse/starlette 会按需补，重复写会出现
    # `text/markdown; charset=utf-8; charset=utf-8`。
    return FileResponse(
        path=str(f),
        media_type="text/markdown",
        filename=f"{doc_id}-抽取稿.md",
        headers={"Content-Disposition": f'attachment; filename="{doc_id}-extract.md"'},
    )


def _combined_file(doc_id: str) -> Path | None:
    """取某 doc_id 的合成图文稿 combined/index.html（防穿越：结果必须落在根内）。"""
    if not doc_id or "/" in doc_id or "\\" in doc_id or ".." in doc_id:
        return None
    root = _kb_extract_root().resolve()
    target = (root / doc_id / "combined" / "index.html")
    try:
        target = target.resolve()
    except OSError:
        return None
    if root not in target.parents:
        return None
    return target if target.is_file() else None


@router.get("/combined")
async def get_combined(
    title: str = Query(..., description="文档标题（与数据侧 index.json 的 title 精确匹配）"),
    owner_l3: str = Query(default="", description="三级产品类型名，用于同名消歧（可选）"),
    _: User = Depends(get_current_user),  # 门禁
):
    """按标题读**合成图文稿**（正文 + 按序插图）。

    合成稿由 `scripts/build_kb_combined.py` 离线生成到 `<doc_id>/combined/index.html`。
    查不到（未合成或文档无 content.md）回 404，前端据此回退纯 Markdown 预览。
    """
    doc_id = _resolve_doc_id_by_title(title, owner_l3)
    if not doc_id:
        raise NotFoundException(f"本机无「{title}」的抽取稿（原件在客户侧，未随包交付）")
    f = _combined_file(doc_id)
    if f is None:
        raise NotFoundException(f"「{title}」暂无合成图文稿（可先跑 build_kb_combined.py）")
    try:
        page = f.read_text(encoding="utf-8")
    except OSError as exc:
        raise NotFoundException(f"读取合成稿失败：{exc}") from exc
    meta: dict = {}
    mj = f.parent / "meta.json"
    if mj.is_file():
        try:
            meta = json.loads(mj.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}
    logger.info(f"kb combined: {doc_id} ({len(page)} chars)")
    return success_response(data={
        "doc_id": doc_id,
        "title": title,
        "html": page,
        "meta": meta,
        "is_extract": True,
        "note": "系统合成图文稿（由抽取产物重建，非客户原件 PDF）。",
    })


@router.get("/{doc_id}/figure")
async def get_figure(
    doc_id: str,
    name: str = Query(..., description="插图文件名，如 p001_x6.png"),
    _: User = Depends(get_current_user),  # 门禁
):
    """按图名返回单张插图（合成稿里的 <img> 指向这里）。

    **防穿越**：name 只取 basename（拒绝路径分隔与 ..），校验结果落在该 doc 的 figures/ 内。
    """
    safe = Path(name).name
    if not safe or safe != name or "/" in name or "\\" in name or ".." in name:
        raise BadRequestException("非法图名")
    root = _kb_extract_root().resolve()
    fig_dir = (root / doc_id / "figures")
    try:
        target = (fig_dir / safe).resolve()
    except OSError:
        raise NotFoundException(f"插图不存在：{safe}") from None
    if fig_dir.resolve() not in target.parents or not target.is_file():
        raise NotFoundException(f"插图不存在：{safe}")
    suffix = target.suffix.lower()
    media = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
        ".svg": "image/svg+xml",
    }.get(suffix, "application/octet-stream")
    return FileResponse(path=str(target), media_type=media)


# ---------------------------------------------------------------- 整包导出
#
# 知识库页顶栏「导出」按钮此前是**空壳**（只有图标文字、无 onClick）。这里给它
# 一个真后端：按产品把「全量条目清单 + 有产物的文档文件」打包成 zip 下载。
#
# ⚠️ 必须注册在 `@router.get("/{doc_id}")` **之前**：FastAPI 按注册顺序匹配，
# `/{doc_id}` 会把 `export` 当成 doc_id 抢走。
#
# ⚠️ 诚实边界（写进包内 README，不假装齐全）：
#   ① 134 条是**条目数**，不等于 134 个文件——只有十余份文档有真实文件产物；
#   ② 客户原始 PDF/Office **不在本机**（`[源]` 脱敏占位前缀），包内是抽取稿与合成稿；
#   ③ 插图受转换上限截断（每份最多 20 张），超出的从未被抽出。

#: 单份文档**常见**的产物文件名（说明用）。实际打包不按这个清单挑——
#: 见下方「打包文档目录顶层所有文件」的说明，清单式挑文件会漏产物。
_DOC_FILES = ("source.json", "content.md", "chunks.jsonl", "entities.json", "params.json")


def _safe_doc_id(doc_id: str) -> str:
    """doc_id 只当目录名：拒绝路径分隔与 `..`（防 zip 内路径穿越）。"""
    d = (doc_id or "").strip()
    if not d or "/" in d or "\\" in d or ".." in d:
        return ""
    return d


def _scene_id_of(owner: str) -> str:
    """由产品三级**中文名**反查 sceneId（如「FU6832 散热风扇驱动板」→
    `motor.cooling-fan.fortior-fu6832`）。

    为什么需要：数据侧 `index.json` 的 taxonomy 是**英文 slug**（l3=fortior-fu6832），
    而入参 owner 是中文名，两者互为子串也对不上（实测踩过）。拿到 sceneId 才能
    与 taxonomy 做**精确**匹配——这是"文档不漏"的关键。查不到返回空串。
    """
    f = PROJECT_ROOT / "c" / "web" / "public" / "scenes" / "index.json"
    if not f.is_file():
        return ""
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""
    want = (owner or "").strip()

    def walk(nodes: list) -> str:
        for n in nodes:
            if not isinstance(n, dict):
                continue
            if n.get("sceneId") and (n.get("label") or "").strip() == want:
                return str(n["sceneId"])
            hit = walk(n.get("children") or [])
            if hit:
                return hit
        return ""

    return walk(data.get("catalog") or [])


def _entry_rows(entries) -> list[dict]:
    """条目 → 可序列化 dict（与列表接口 `_to_dict` 同一形状，口径不漂）。"""
    return [KbEntryRead.model_validate(e).model_dump(mode="json") for e in entries]


def _csv_bytes(rows: list[dict]) -> bytes:
    """条目表格。用 **utf-8-sig**（带 BOM）——否则 Excel 打开中文会乱码。"""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "条目ID", "标题", "用途", "来源", "一级归属", "二级归属", "三级归属",
        "文档类型", "转化状态", "源文件", "大小(字节)", "备注",
    ])
    for r in rows:
        c = r.get("content") or {}
        if not isinstance(c, dict):
            c = {}
        w.writerow([
            r.get("entry_key", ""),
            r.get("title", ""),
            r.get("usage", ""),
            r.get("origin", ""),
            r.get("owner_l1", ""),
            r.get("owner_l2", ""),
            r.get("owner_l3", ""),
            c.get("type", ""),
            c.get("conversion_status", ""),
            c.get("path", ""),
            c.get("size_bytes", ""),
            c.get("note") or c.get("action") or "",
        ])
    return buf.getvalue().encode("utf-8-sig")


def _md_bytes(rows: list[dict], owner: str) -> bytes:
    """可读清单：按「用途 → 来源」分组，人打开就能看。"""
    usage_label = {"spec": "产品说明书", "requirement": "测试需求", "process": "工艺"}
    origin_label = {"doc": "文档", "experience": "经验"}
    lines: list[str] = [
        f"# 知识库导出清单 · {owner}",
        "",
        f"- 条目总数：**{len(rows)}**",
        f"- 导出时间：{datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "本清单含该产品的**全部条目**；其中只有部分文档另有文件产物，见包内 `documents/`。",
        "",
    ]
    for u in ("spec", "requirement", "process"):
        sub = [r for r in rows if r.get("usage") == u]
        if not sub:
            continue
        lines.append(f"## {usage_label.get(u, u)}（{len(sub)} 条）")
        lines.append("")
        for o in ("doc", "experience"):
            g = [r for r in sub if r.get("origin") == o]
            if not g:
                continue
            lines.append(f"### {origin_label.get(o, o)}（{len(g)} 条）")
            lines.append("")
            for r in g:
                c = r.get("content") or {}
                if not isinstance(c, dict):
                    c = {}
                lines.append(f"- **{r.get('title', '')}**")
                lines.append(f"  - 条目ID：`{r.get('entry_key', '')}`")
                if c.get("type"):
                    lines.append(f"  - 类型：{c['type']}")
                if c.get("conversion_status"):
                    lines.append(f"  - 转化状态：{c['conversion_status']}")
                if c.get("path"):
                    lines.append(f"  - 源文件：{c['path']}")
                if c.get("note") or c.get("action"):
                    lines.append(f"  - 备注：{c.get('note') or c.get('action')}")
            lines.append("")
    return "\n".join(lines).encode("utf-8")


def _readme_bytes(owner: str, total: int, doc_ids: list[str], fig_count: int) -> bytes:
    """包内说明。**诚实边界必须写在这里**——拿到包的人不该误判包里有什么。"""
    doc_line = (
        "、".join(doc_ids) if doc_ids
        else "（本产品条目在数据侧没有对应文档产物，包内只有清单）"
    )
    return "\n".join([
        f"# 知识库导出包 · {owner}",
        "",
        f"- 条目总数：**{total}** 条（见 `entries.json` / `entries.csv` / `entries.md`）",
        f"- 有文件产物的文档：**{len(doc_ids)}** 份（见 `documents/`）",
        f"- 插图：**{fig_count}** 张",
        f"- 导出时间：{datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 包里有什么",
        "",
        "```",
        "README.md          本说明",
        "entries.json       全量条目原始数据（结构化）",
        "entries.csv        全量条目表格（Excel 可直接打开）",
        "entries.md         全量条目可读清单（按用途/来源分组）",
        "documents/<doc_id>/",
        "  source.json      原件元信息（页数/大小/sha256/原路径）",
        "  content.md       正文全文（系统抽取稿 Markdown）",
        "  figures/*.png    手册插图",
        "  chunks.jsonl     检索切片",
        "  entities.json    抽出的参数/寄存器",
        "  combined/        合成图文稿（正文+插图就位，浏览器可直接打开 index.html）",
        "```",
        "",
        f"本次导出的文档：{doc_line}",
        "",
        "## ⚠️ 三处必须知道的边界（如实标注，不假装齐全）",
        "",
        f"1. **{total} 是条目数，不等于 {total} 个文件**。",
        "   清单里每条都在；但只有上面列出的文档另有真实文件产物，其余条目（经验类等）",
        "   本身就没有独立文件，它们的数据在 `entries.json` 的 `content` 字段里。",
        "",
        "2. **这不是客户原件**。客户原始 PDF/Office 文件未随包交付",
        "   （条目里 `[源] ...` 是脱敏占位前缀，原件在客户内网盘）。",
        "   包内 `content.md` 是系统抽取稿，`combined/index.html` 是由抽取产物合成的图文稿。",
        "",
        "3. **插图数量受转换上限截断**。转换脚本每份文档最多抽 20 张图，",
        "   超出部分从未被抽出，本机补不了（需原始 PDF 重跑转换）。",
        "   所以插图不是「手册里的全部图」，是「已抽取出来的全部图」。",
        "",
    ]).encode("utf-8")


@router.get("/export")
async def export_knowledge(
    owner: str = Query(..., description="产品三级归属中文名，如「FU6832 散热风扇驱动板」"),
    scene: str = Query(default="", description="场景 ID（如 motor.cooling-fan.fortior-fu6832），"
                                               "给了就用它精确匹配文档归属，不给则由 owner 反查"),
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),  # 门禁
):
    """按产品打包整个知识库为 zip：**全量条目清单 + 有产物的文档文件（含插图）**。

    只读：不写业务库、不改状态、不驱动设备。可重复调用。
    """
    owners = [x.strip() for x in owner.split(",") if x.strip()]
    if not owners:
        raise BadRequestException("owner 不能为空")

    # ① 条目：与列表接口共用同一把钥匙（防「页面 134 条、导出 120 条」）
    entries = latest_active_scoped(session, owners)
    if not entries:
        raise NotFoundException(f"归属「{owner}」下没有知识条目")
    rows = _entry_rows(entries)

    # ② 文档范围：**taxonomy 精确匹配 ∪ 条目标题匹配（取并集）**。
    #
    #    只靠 title 会漏：实测数据侧 13 份文档里 3 份的 title 与库里的条目 title 不一致
    #    （如文档「FOC 方案考核题」↔ 条目「考试题」、「MCU-DS-14 …V2.1（2023-06-21）」↔
    #    条目带后缀「…，峰岹科技三相电机控制 MCU」）→ 精确等值匹配不上，导出就漏 3 份。
    #    只靠 taxonomy 又拿不到（数据侧是英文 slug，入参是中文名）。
    #    ⇒ 先用 owner 反查 sceneId，再按 taxonomy 精确命中；title 匹配作兜底。
    scene_key = (scene or "").strip() or _scene_id_of(owner)
    want_l3 = scene_key.split(".")[-1] if scene_key else ""

    entry_titles = {(e.title or "").strip() for e in entries}
    root = _kb_extract_root()
    doc_ids: list[str] = []
    idx_file = root / "index.json"
    if idx_file.is_file():
        try:
            data = json.loads(idx_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        for d in data.get("documents") or []:
            if not isinstance(d, dict):
                continue
            sid = _safe_doc_id(str(d.get("doc_id") or ""))
            if not sid or not (root / sid).is_dir():
                continue
            tax = d.get("taxonomy") or {}
            l3 = str(tax.get("l3") or "")
            # 命中 A：taxonomy 拼出的 sceneId 与当前场景完全一致（最准，不会跨产品）
            hit_scene = bool(scene_key) and \
                f"{tax.get('l1', '')}.{tax.get('l2', '')}.{l3}" == scene_key
            # 命中 B：标题能对上条目，且归属一致（sceneId 拿不到时不按 l3 过滤）
            hit_title = (d.get("title") or "").strip() in entry_titles and \
                (not want_l3 or l3 == want_l3)
            if hit_scene or hit_title:
                doc_ids.append(sid)

    # ③ 先扫描待打包文件（顺带统计插图数）——README 要写准图数，所以不能边打包边数
    plan: list[tuple[Path, str]] = []  # (本地路径, zip 内路径)
    fig_count = 0
    for doc_id in doc_ids:
        d = root / doc_id
        # 顶层产物**全打包**，不按固定文件名挑：源码参数配置类的产物是 params.json，
        # 只认 (source/content/chunks/entities) 会把它整份漏掉（实测踩过）。
        # 只收顶层常规文件（子目录单独处理），不递归——路径仍只由已知 doc_id 拼出。
        for p in sorted(d.iterdir()):
            if p.is_file():
                plan.append((p, f"documents/{doc_id}/{p.name}"))
        fig = d / "figures"
        if fig.is_dir():
            for img in sorted(fig.iterdir()):
                if img.is_file():
                    plan.append((img, f"documents/{doc_id}/figures/{img.name}"))
                    fig_count += 1
        cb = d / "combined"
        if cb.is_dir():
            for f2 in sorted(cb.iterdir()):
                if f2.is_file():
                    plan.append((f2, f"documents/{doc_id}/combined/{f2.name}"))

    # ④ 打包（落临时文件，不用 BytesIO 常驻内存——含上百张图，体积不小）
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    tmp_dir = tempfile.mkdtemp(prefix="kb-export-")
    zip_path = Path(tmp_dir) / f"kb-export-{ts}.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("README.md", _readme_bytes(owner, len(rows), doc_ids, fig_count))
            zf.writestr("entries.json", json.dumps(rows, ensure_ascii=False, indent=2))
            zf.writestr("entries.csv", _csv_bytes(rows))
            zf.writestr("entries.md", _md_bytes(rows, owner))
            for src, arc in plan:
                zf.write(src, arc)
    except Exception as exc:  # noqa: BLE001 —— 打包失败必须如实报，不返回空包
        logger.exception(f"kb export failed for owner={owner}")
        _cleanup_dir(tmp_dir)
        raise NotFoundException(f"导出打包失败：{type(exc).__name__}: {exc}") from exc

    size = zip_path.stat().st_size
    logger.info(
        f"kb export: owner={owner} entries={len(rows)} docs={len(doc_ids)} "
        f"figures={fig_count} size={size}"
    )

    zh_name = f"知识库导出-{owner}-{ts}.zip"
    ascii_name = f"kb-export-{ts}.zip"
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=zh_name,
        headers={
            "Content-Disposition":
                f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(zh_name)}"
        },
        background=BackgroundTask(_cleanup_dir, tmp_dir),
    )


def _cleanup_dir(path: str) -> None:
    """响应发完后删掉临时目录（导出 zip 是一次性产物，不留盘堆积）。"""
    import shutil

    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


@router.get("/{doc_id}")
async def get_document(
    doc_id: str,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),  # 门禁
):
    """单份详情。前端上传后轮询这个接口看五阶段推进到哪一步。"""
    doc = session.exec(select(KbDocument).where(KbDocument.doc_id == doc_id)).first()
    if doc is None:
        raise NotFoundException("文档不存在")
    return success_response(data=_to_dict(doc))


@router.post("/{doc_id}/run")
async def run_pipeline(
    doc_id: str,
    until: str = Query(default="index", description="跑到哪个阶段为止，取值见五阶段"),
    only: str = Query(default="", description="只重跑这一个阶段（从它开始直到 until）"),
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),  # 门禁
):
    """推进五阶段流水线。`until` 控跑到哪，`only` 控从哪重跑（每阶段可单独重跑）。

    ⚠️ 本单元只落**状态机骨架与产物读写**，真正的 docling 调用在下一个单元接。
    这里对未实现的阶段**如实返回 501 语义的状态**（status 不假装成 indexed），
    绝不把「还没做」表现成「做完了」。
    """
    if until not in KB_STAGES:
        raise BadRequestException(f"until 必须是五阶段之一：{' / '.join(KB_STAGES)}")
    if only and only not in KB_STAGES:
        raise BadRequestException(f"only 必须是五阶段之一：{' / '.join(KB_STAGES)}")

    doc = session.exec(select(KbDocument).where(KbDocument.doc_id == doc_id)).first()
    if doc is None:
        raise NotFoundException("文档不存在")

    start = only or "recognize"
    if KB_STAGES.index(start) > KB_STAGES.index(until):
        raise BadRequestException(f"起始阶段 {start} 在 {until} 之后，没有可跑的阶段")

    from app.services.kb_convert_service import run_stages

    doc.status = "converting"
    doc.failed_stage = None
    doc.fail_reason = None
    doc.updated_at = datetime.now(timezone.utc)
    session.add(doc)
    session.commit()

    try:
        # 索引阶段要真写 kb_entries，必须把本请求的 db 会话传下去。
        # 同会话写库的好处：索引阶段的写入与文档状态的更新在**同一事务边界**附近，
        # 失败时不会只落了一半。注意 run_stages 内部已 commit 条目写入，
        # 所以下面 doc 的状态更新是第二次提交（原子性由「失败即落 failed 状态」兜住）。
        result = run_stages(doc, start=start, until=until, session=session)
    except Exception as exc:  # noqa: BLE001
        # 失败必须带阶段与原因（主文档 3.1）。这里接住所有异常是为了**留下记录**，
        # 不是因为失败可以忽略——状态会落成 failed，调用方立刻能看到。
        doc.status = "failed"
        doc.failed_stage = getattr(exc, "stage", start)
        doc.fail_reason = f"{type(exc).__name__}: {exc}"
        doc.updated_at = datetime.now(timezone.utc)
        session.add(doc)
        session.commit()
        logger.error(f"kb convert failed at {doc.failed_stage} for {doc_id}: {exc}")
        raise

    doc.stage = result["stage"]
    doc.artifacts = {**(doc.artifacts or {}), **result["artifacts"]}
    doc.entry_count = result.get("entry_count", doc.entry_count)
    doc.confidence = result.get("confidence", doc.confidence)
    # 五值判定：结构化置信度低于阈值 → needs_review（不允许静默通过）
    if result.get("needs_review"):
        doc.status = "needs_review"
    else:
        doc.status = "indexed" if result["stage"] == "index" else "converting"
    doc.updated_at = datetime.now(timezone.utc)
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return success_response(data=_to_dict(doc), message="阶段完成")


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),  # 门禁
):
    """删掉这份文档的**登记**（原件与产物保留在磁盘）。

    这里与条目侧不同：主文档的「软删除 + 原件保留 90 天」说的是**条目**，
    文档侧目前只做登记项移除，盘上文件不动——删盘是不可逆的，
    在客户现场误删一份手册的代价远大于多占几十 MB。
    真要清盘，由运维按目录清，代码不代办。
    """
    doc = session.exec(select(KbDocument).where(KbDocument.doc_id == doc_id)).first()
    if doc is None:
        raise NotFoundException("文档不存在")
    file_path = doc.file_path
    session.delete(doc)
    session.commit()
    return success_response(
        data={"doc_id": doc_id, "file_path": file_path, "files_kept": True},
        message="登记已删除；原件与产物保留在磁盘，未做不可逆的删除",
    )
