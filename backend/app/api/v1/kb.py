"""
知识库检索路由（阶段 3.1 引入，P3）。

`POST /api/kb/search`：关键词检索，响应复用前端 search-samples.json 里 samples 元素
的形状（query/k/hits/hit_docs/pages_cited/results），前端已有的 KbSample 与 KbHit
类型一行都不用改（见 c/web/src/features/scene/kb.ts）。

三条约束（主文档 C-5）：
1. k 设上限 20（当前离线版没有上限）；
2. scene_id 参与归属校验，不匹配返回空命中，不跨产品套用；
3. 语料进程内懒加载单例，禁止每次请求重建 BM25。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.deps import get_current_user, get_db
from app.models.kb_entry import KbRef
from app.models.user import User
from app.schemas.common import success_response
from app.schemas.kb_entry import KbRefCreate
from app.services.kb_search import get_engine, taxonomy_scene_id

# 鉴权门禁：本模块原先两个路由都没挂鉴权（2026-09-23 全量审查发现）。
# 知识语料是共享的，只要求「已登录」一层，不按人过滤，故参数命名为 `_`。
# AUTH_DISABLED=true 时 get_current_user 回退本地管理员，不影响单机运行。
router = APIRouter(prefix="/kb", tags=["Knowledge Base"])


class KbSearchRequest(BaseModel):
    query: str = Field(..., max_length=500, description="检索语句")
    k: int = Field(default=5, ge=1, le=20, description="返回条数上限")
    scene_id: str | None = Field(default=None, description="归属校验用场景 ID")


@router.post("/search")
async def kb_search(
    body: KbSearchRequest,
    _: User = Depends(get_current_user),  # 门禁
):
    """关键词检索。scene_id 不匹配当前语料归属时返回空命中。"""
    kb_scene = taxonomy_scene_id()
    if body.scene_id and kb_scene and body.scene_id != kb_scene:
        return {
            "query": body.query, "k": body.k,
            "hits": 0, "hit_docs": [], "pages_cited": [], "results": [],
        }

    engine = get_engine()
    results = engine.search(body.query, k=body.k)
    return {
        "query": body.query,
        "k": body.k,
        "hits": len(results),
        "hit_docs": sorted({r["doc_id"] for r in results}),
        "pages_cited": sorted({r["page"] for r in results if r["page"]}),
        "results": results,
    }


@router.post("/refs")
async def create_ref(
    payload: KbRefCreate,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),  # 门禁
):
    """登记一条引用关系（供引用禁删校验）。"""
    ref = KbRef(
        ref_key=payload.ref_key,
        ref_label=payload.ref_label,
        target_entry_key=payload.target_entry_key,
    )
    session.add(ref)
    session.commit()
    session.refresh(ref)
    return success_response(data={
        "ref_key": ref.ref_key,
        "target_entry_key": ref.target_entry_key,
    }, message="引用已登记")


# ------------------------------------------------- 向量索引管理（阶段 3 补全）


@router.get("/vector/stat")
async def vector_stat(
    _: User = Depends(get_current_user),  # 门禁
):
    """向量索引现状：档位、条数、是否与语料一致。

    为什么要有这个查询：双路检索降级时人第一句会问「向量那路怎么了」。
    没有这个接口就只能去翻服务器日志或手工跑脚本。
    """
    from app.services.kb_embed_service import index_stale, probe
    from app.services.kb_search import get_engine

    corpus_count = len(get_engine().corpus)
    stale, reason = index_stale(corpus_count)
    return success_response(data={
        **probe(),
        "corpus_count": corpus_count,
        "stale": stale,
        "stale_reason": reason,
    })


@router.post("/vector/rebuild")
async def vector_rebuild(
    _: User = Depends(get_current_user),  # 门禁
):
    """重建向量索引（一次性成本，577+ 单元起步）。

    产物是**落盘文件**（不是关系表），所以这里没有事务语义：
    重建失败时旧索引仍可查询，符合「宁可暂时用旧的，也不要没有」。

    ⚠️ 同步执行、可能耗时几十秒到几分钟（取决于语料量与 embedding 档位）。
    调用方（界面/脚本）应据此设置足够超时。
    """
    from app.services.kb_embed_service import build, corpus_to_rows
    from app.services.kb_search import get_engine

    rows = corpus_to_rows(get_engine().corpus)
    if not rows:
        return success_response(
            data={"ok": False, "reason": "语料为空，未重建"},
            message="语料为空，未重建",
        )

    res = build(rows)
    if not res.get("ok"):
        # 失败**不抛异常**而是如实返回：重建失败不是请求错误，
        # 旧索引仍在、检索照常，界面应显示原因而不是弹一个 500。
        return success_response(
            data={**res, "rebuilt": False},
            message=f"重建失败：{res.get('error')}",
        )
    return success_response(
        data={**res, "rebuilt": True},
        message=f"索引已重建：{res.get('count')} 条（{res.get('tier')}）",
    )
