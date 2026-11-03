"""
知识库三轴分类条目 CRUD（阶段 3.1 引入，P3）。

覆盖主文档 3.1 验收 3（引用禁删 409）与验收 4（版本化 + 改动理由必填）：

- POST   /api/kb/entries                      创建（version=1）
- GET    /api/kb/entries                      列表（三轴过滤 + 三轴计数）
- GET    /api/kb/entries/{entry_key}          读最新活跃版本
- PUT    /api/kb/entries/{entry_key}          更新（出新版本，经验改动理由必填）
- GET    /api/kb/entries/{entry_key}/versions 查版本链
- DELETE /api/kb/entries/{entry_key}          软删除（被引用返回 409 + 引用方列表）
- POST   /api/kb/refs                          登记引用关系

三轴字段：origin（doc/experience）、usage（spec/requirement/process）、owner_l1/l2/l3。
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from app.api.deps import get_current_user, get_db
from app.core.exceptions import ConflictException, NotFoundException
from app.models.kb_entry import KbEntry, KbRef
from app.models.user import User
from app.schemas.common import success_response
from app.schemas.kb_entry import KbEntryCreate, KbEntryRead, KbEntryUpdate

# ⚠️ 鉴权门禁（2026-09-23 全量审查补上）
#
# 原先本模块五个路由一个鉴权都没挂：AUTH_DISABLED 切成 false 之后，
# 任何人都能增删改知识库条目（含软删除）。这是真实的安全缺口。
#
# 知识条目是**共享**的、不按人隔离，所以只需要「已登录」这一层，
# 不拿 user 做归属过滤。据此参数命名为 `_` 并在下面每个路由里写明它是门禁。
# get_current_user 在无密码模式下回退本地管理员（见 app/api/deps.py:63），
# 所以加上它**不会破坏单机运行**，只在 AUTH_DISABLED=false 时生效。
router = APIRouter(prefix="/kb/entries", tags=["Knowledge Base Entries"])


def _latest(session: Session, entry_key: str) -> KbEntry:
    """取条目最新版本；不存在 404。"""
    entry = session.exec(
        select(KbEntry).where(KbEntry.entry_key == entry_key).order_by(KbEntry.version.desc())
    ).first()
    if entry is None:
        raise NotFoundException("知识条目不存在")
    return entry


def latest_active_scoped(session: Session, owners: list[str] | None = None) -> list[KbEntry]:
    """「归属收窄 + 只取最新活跃版本」——列表与导出**共用同一把钥匙**。

    为什么抽出来：这两步的口径历史上踩过坑（counts 曾跟着筛选变、曾串包、
    曾把历史版本与软删除一起返回）。导出端点若另写一份，迟早与列表漂移——
    那就是「页面显示 134 条、导出只有 120 条」这类难查的不一致。

    口径（与 list_entries 文档字符串一致）：
      · 每个 entry_key 只保留 version 最大的一条；
      · `status == "deleted"`（软删除）一律排除；
      · owners 是**范围不是筛选**：给定时要求 owners 里每一项都在该条目的
        (owner_l1, owner_l2, owner_l3) 中出现（全包含才命中）。

    返回按 entry_key 排序，保证多次调用顺序稳定（导出包内容可复现）。
    """
    all_rows = session.exec(select(KbEntry)).all()
    latest: dict[str, KbEntry] = {}
    for e in all_rows:
        if e.status == "deleted":
            continue
        cur = latest.get(e.entry_key)
        if cur is None or e.version > cur.version:
            latest[e.entry_key] = e

    scoped = list(latest.values())
    if owners:
        scoped = [e for e in scoped
                  if all(o in (e.owner_l1, e.owner_l2, e.owner_l3) for o in owners)]
    scoped.sort(key=lambda e: e.entry_key)
    return scoped


def _to_dict(entry: KbEntry) -> dict:
    return KbEntryRead.model_validate(entry).model_dump(mode="json")


@router.post("")
async def create_entry(
    payload: KbEntryCreate,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),  # 门禁：仅要求已登录，见文件头说明
):
    """创建条目。entry_key 后端生成（origin 前缀 + uuid8）。"""
    if payload.origin not in ("doc", "experience"):
        raise ConflictException("origin 必须是 doc 或 experience")
    if payload.usage not in ("spec", "requirement", "process"):
        raise ConflictException("usage 必须是 spec / requirement / process")

    prefix = "EXP" if payload.origin == "experience" else "DOC"
    entry_key = f"{prefix}-{uuid.uuid4().hex[:12]}"
    entry = KbEntry(
        entry_key=entry_key,
        version=1,
        origin=payload.origin,
        title=payload.title,
        usage=payload.usage,
        owner_l1=payload.owner_l1,
        owner_l2=payload.owner_l2,
        owner_l3=payload.owner_l3,
        content=payload.content,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return success_response(data=_to_dict(entry), message="条目已创建")


@router.get("")
async def list_entries(
    owner: str = "",
    usage: str = "",
    origin: str = "",
    limit: int = 500,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),  # 门禁
):
    """知识条目列表 + 三轴计数（前端知识库页的取数入口）。

    为什么要有这一条：此前前端直接 fetch 场景包的静态 JSON，三轴分类只做在
    前端，服务端的 kb_entries 表形同虚设——CRUD 改的是表、列表读的是 JSON，
    两套并存必然漂移。这里定成**库是唯一权威源**，场景包只作导入源。

    三轴语义（与前端 KnowledgeFilter 对齐）：
      owner  —— 归属三级，逗号分隔；**全包含才命中**（与前端 `every` 一致）
      usage  —— 用途，逗号分隔，任一命中
      origin —— 来源，逗号分隔，任一命中

    计数口径（⚠️ 容易写错）：
      **counts 在「归属范围」内统计，不受 usage/origin 筛选影响。**
      归属（owner）决定「这是哪个场景包的知识库」，是范围；
      usage / origin 是筛选器。若 counts 跟着筛选变，勾一个筛选器
      就会看到其余轴的计数归零，人会以为条目消失了。
      反过来若 counts 用全库统计，两个场景包同时在库时就会把别人的
      条目也算进来——界面上是「本产品 186 条」，数据其实串包了。

    只返回**每个 entry_key 的最新活跃版本**（软删除与历史版本都不出）。
    """
    def split(v: str) -> list[str]:
        return [x.strip() for x in v.split(",") if x.strip()]

    owners, usages, origins = split(owner), split(usage), split(origin)

    # ① 先按归属收窄到「本场景包」，这是范围不是筛选。
    #    收窄与「取最新活跃版本」共用 latest_active_scoped（导出端点也用它，防口径漂移）
    scoped = latest_active_scoped(session, owners)

    # ② 计数在这个范围内算，不受 usage / origin 筛选影响
    counts = {
        "total": len(scoped),
        "usage": {"spec": 0, "requirement": 0, "process": 0},
        "origin": {"doc": 0, "experience": 0},
    }
    for e in scoped:
        if e.usage in counts["usage"]:
            counts["usage"][e.usage] += 1
        if e.origin in counts["origin"]:
            counts["origin"][e.origin] += 1

    # ③ 再按用途 / 来源筛选，只影响返回哪些条目
    items = scoped
    if usages:
        items = [e for e in items if e.usage in usages]
    if origins:
        items = [e for e in items if e.origin in origins]

    items.sort(key=lambda e: e.entry_key)
    return success_response(data={
        "items": [_to_dict(e) for e in items[:limit]],
        "total": len(items),
        "counts": counts,
    })


@router.get("/{entry_key}")
async def get_entry(
    entry_key: str,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),  # 门禁
):
    """读最新活跃版本。软删除的条目返回 404。"""
    entry = _latest(session, entry_key)
    if entry.status == "deleted":
        raise NotFoundException("知识条目已删除")
    return success_response(data=_to_dict(entry))


@router.put("/{entry_key}")
async def update_entry(
    entry_key: str,
    payload: KbEntryUpdate,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),  # 门禁
):
    """更新 = 出新版本（不原地覆盖）。经验（origin=experience）改动理由必填。"""
    current = _latest(session, entry_key)
    if current.status == "deleted":
        raise NotFoundException("知识条目已删除")

    if payload.usage is not None and payload.usage not in ("spec", "requirement", "process"):
        raise ConflictException("usage 必须是 spec / requirement / process")

    # 经验改动理由必填（验收 4）
    if current.origin == "experience" and not (payload.change_reason or "").strip():
        raise ConflictException("经验的改动理由（change_reason）为必填字段")

    new_version = current.version + 1
    entry = KbEntry(
        entry_key=entry_key,
        version=new_version,
        origin=current.origin,
        title=payload.title if payload.title is not None else current.title,
        usage=payload.usage if payload.usage is not None else current.usage,
        owner_l1=current.owner_l1,
        owner_l2=current.owner_l2,
        owner_l3=current.owner_l3,
        content=payload.content if payload.content is not None else current.content,
        status="active",
        change_reason=payload.change_reason or "",
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return success_response(data=_to_dict(entry), message="已出新版本")


@router.get("/{entry_key}/versions")
async def list_versions(
    entry_key: str,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),  # 门禁
):
    """查版本链（从新到旧）。"""
    entries = session.exec(
        select(KbEntry).where(KbEntry.entry_key == entry_key).order_by(KbEntry.version.desc())
    ).all()
    if not entries:
        raise NotFoundException("知识条目不存在")
    return success_response(data=[_to_dict(e) for e in entries])


@router.delete("/{entry_key}")
async def delete_entry(
    entry_key: str,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),  # 门禁
):
    """软删除。被引用（引用计数 >0）时返回 409 并逐条列出引用方。"""
    entry = _latest(session, entry_key)
    if entry.status == "deleted":
        raise NotFoundException("知识条目已删除")

    # 引用禁删（验收 3）
    refs = session.exec(
        select(KbRef).where(KbRef.target_entry_key == entry_key)
    ).all()
    if refs:
        referrers = [{"ref_key": r.ref_key, "ref_label": r.ref_label} for r in refs]
        # 验收 3：被引用禁删，返回 409 且响应体逐条列出引用方
        return JSONResponse(
            status_code=409,
            content={
                "success": False,
                "code": 409,
                "message": f"条目被 {len(refs)} 处引用，禁止删除",
                "data": {"referrers": referrers},
            },
        )

    entry.status = "deleted"
    entry.deleted_at = datetime.now(timezone.utc)
    entry.updated_at = datetime.now(timezone.utc)
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return success_response(data=_to_dict(entry), message="已软删除")
