"""知识条目写入服务（阶段 3 补全新增）。

为什么要有这个文件
------------------
此前 `kb_entries` 的**写库逻辑全部内联在路由函数里**（`api/v1/kb_entries.py`
的 `create_entry` / `update_entry`），没有一层可被非 HTTP 调用方复用的函数。
在线转化流水线的 `stage_index` 要把切片登记成条目——它跑在 service 层、
手里只有一个 `Session`，没有 `Request`。「让 service 去发一个 HTTP 请求给自己」
是循环依赖，不可取。

所以这里把「三轴条目写入 + 版本递增 + 引用禁删判定」抽成**纯函数**，
路由与转化服务共用同一份实现。**不新建表、不绕过既有 KbEntry 模型**——
项目已有三轴 + 版本化 + 引用禁删，另建一套必然双源漂移（3-I 已因此吃过亏）。

口径（与路由完全一致，改动必须两边同步）
---------------------------------------
- `entry_key` 唯一性：本模块强制**带文档/场景维度前缀**，见 `doc_entry_key()`。
  3-I 教训：两个场景包的 `EXP-001…018` **完全重号**，只拿原 id 当 key 会
  **静默串包**（先导入的占位、后导入的静默少 18 条且挂到别人名下）。
- `origin` 只认 `doc` / `experience`；`usage` 只认 `spec` / `requirement` / `process`。
  这两个枚举是**下游只认识的值**，改之前先查消费方（项目栽过两次：
  `evidence.kind`、`artifact_kind`）。
- 更新 = 出新版本（不原地覆盖）；经验改动的 `change_reason` 必填。
"""
from __future__ import annotations

from sqlmodel import Session, select

from app.core.exceptions import ConflictException
from app.core.logger import logger
from app.models.kb_entry import KbEntry, KbRef

# 下游只认这三个值，不要扩展（见模块 docstring）
VALID_USAGE = ("spec", "requirement", "process")
VALID_ORIGIN = ("doc", "experience")


def doc_entry_key(doc_id: str, chunk_id: str) -> str:
    """由「文档 id + 切片 id」拼出稳定、不重号的 entry_key。

    形态：`<doc_id>#<chunk_id>`

    为什么用 `#`：`entry_key` 会出现在 URL 路径里，`#` 在路径段内是合法字符
    （不合法的是 `/`、`?`），而 `_upload_worker` 产出的 chunk_id 本身就是
    `<doc_id>#c0001` 形态，这里再拼一次会让前缀重复但不影响唯一性与可读性。
    真正要保证的是**唯一**与**可溯源**：从 key 能直接看出它属于哪份上传文档，
    删除这份文档时可以按前缀批量定位它产出的条目。
    """
    cid = (chunk_id or "").strip()
    # chunk_id 已是 `<doc_id>#cNNNN` 形态时不再重复拼前缀，避免 `a#a#c1`
    if cid.startswith(f"{doc_id}#"):
        return cid
    return f"{doc_id}#{cid}"


def upsert_entry(
    session: Session,
    *,
    entry_key: str,
    origin: str,
    title: str,
    usage: str,
    owner_l1: str = "",
    owner_l2: str = "",
    owner_l3: str = "",
    content: dict | None = None,
    change_reason: str = "",
) -> tuple[KbEntry, bool]:
    """写入一条条目。已存在则出**新版本**（不原地覆盖）。

    返回 `(最新条目, 是否新建)`。

    为什么不做「原地更新」：项目契约是版本化——改内容必须出新版本并留改动理由，
    这样「这条知识是谁什么时候改的」有据可查。流水线重跑同一份文档时应产出
    新版本而不是覆盖（人能看出资料更新过）。

    并发：这里是「先查后写」，没有行锁。单 worker 部署（项目已定，见 README
    的「必须单 worker」）下不存在并发写同一 key，故不加锁；若将来多 worker，
    需要在这里补唯一约束 + 冲突重试。
    """
    if origin not in VALID_ORIGIN:
        raise ConflictException(f"origin 必须是 {' / '.join(VALID_ORIGIN)}")
    if usage not in VALID_USAGE:
        raise ConflictException(f"usage 必须是 {' / '.join(VALID_USAGE)}")

    existing = session.exec(
        select(KbEntry).where(KbEntry.entry_key == entry_key)
        .order_by(KbEntry.version.desc())  # type: ignore[attr-defined]
    ).first()

    created = existing is None
    version = (existing.version + 1) if existing else 1

    # 内容变了才值得出新版本。内容相同则**不产生新版本**——
    # 否则每次重跑流水线都会给同一份内容堆一个版本，版本链会变成噪声。
    if existing is not None and (existing.content or {}) == (content or {}):
        return existing, False

    entry = KbEntry(
        entry_key=entry_key,
        version=version,
        origin=origin,
        title=(title or "")[:500],
        usage=usage,
        owner_l1=owner_l1,
        owner_l2=owner_l2,
        owner_l3=owner_l3,
        content=content or {},
        status="active",
        change_reason=change_reason or ("首次写入" if created else "内容更新"),
    )
    session.add(entry)
    session.flush()  # 拿到 id 但不提交：由调用方决定事务边界（批量写入只需 commit 一次）
    return entry, created


def count_doc_entries(session: Session, doc_id: str) -> int:
    """这份文档已经产出了多少条「活跃」条目（按 key 前缀认领）。

    删除/重跑前用它报数，让调用方知道会影响到多少条，而不是给一个空对象。
    """
    prefix = f"{doc_id}#"
    rows = session.exec(select(KbEntry)).all()
    latest: dict[str, KbEntry] = {}
    for e in rows:
        if not e.entry_key.startswith(prefix) or e.status == "deleted":
            continue
        cur = latest.get(e.entry_key)
        if cur is None or e.version > cur.version:
            latest[e.entry_key] = e
    return len(latest)


def referrers_of(session: Session, entry_key: str) -> list[dict]:
    """引用方列表。空表示可删。与路由删除判定的**同一口径**，避免两处不一致。"""
    refs = session.exec(select(KbRef).where(KbRef.target_entry_key == entry_key)).all()
    return [{"ref_key": r.ref_key, "ref_label": r.ref_label} for r in refs]
