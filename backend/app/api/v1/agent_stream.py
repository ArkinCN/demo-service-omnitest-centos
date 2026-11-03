"""
助手会话兼容适配层（阶段 3 引入，P4）。

前端 `c/web` 调的是 `/api/agent/stream`（无 /v1 前缀），发六事件协议：
  message_delta / tool_call / tool_result / verdict / evidence / done。
客户后端已有 `/api/v1/agent-chat`（事件名与字段完全不同）。

本模块做协议适配，把前端协议映射到客户后端 `run_agent_chat`，不新写一套
模型调用/工具循环/计费。字段严格照抄前端 `agent-chat/api.ts` 的定义，一个不增删。

映射关系（精确）：
  客户后端事件                         → 前端六事件
  content_delta {text}                 → message_delta {messageId, delta}
  tool_call {id,name,input}            → tool_call {callId,name,title,args,argsSummary,mutating:false}
  tool_result {id,name,summary}        → tool_result {callId,status,durationMs,resultSummary,result}
  sources {sources}                    → evidence {items:[...]}
  done / done{cancelled:true} / error  → done {reason: complete/aborted/error}
  stream_start/reasoning_delta/tool_executing/ping → 丢弃（前端会忽略协议外行）

阶段 3 客户工具全是检索类（KnowledgeSearch/DocLibrarySearch/WebSearch），
无动作类红线工具，因此 mutating 恒为 false、不推 confirm 字段、confirm 端点
暂返回 404（动作类工具的确认闸门在阶段 5 接设备桥后才有）。
"""
import json
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import get_current_user, get_db
from app.core.logger import logger
from app.db.session import engine
from app.models.user import User
from app.models.agent_chat_memory import get_history, append_turn
from app.services.agent_chat_service import run_agent_chat

router = APIRouter(prefix="/agent", tags=["Agent Compat"])

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _sse(d: dict) -> str:
    return f"data: {json.dumps(d, ensure_ascii=False)}\n\n"


# ── 请求模型（字段与前端 SendRequest 对齐）──
class AgentStreamRequest(BaseModel):
    text: str
    model: Optional[str] = None
    permission: str = "readonly"
    auto_run: bool = True
    session_id: Optional[str] = None
    # 前端下发的检索工具开关；缺省 None 时后端不启用任何工具（纯回答）
    enabled_tools: Optional[list[str]] = None
    # 上下文包（envelope v1，前端 features/copilot/context.ts 的 buildEnvelope 产出）。
    # 主文档 3.2.2：前端已经算出来了，但此前一个字节都没上送。
    # 后端把它压成一段现场摘要写进 system prompt——**只影响模型看到什么**，
    # 不改工具、不改计费、不改事件协议。缺省 None 时行为与以前完全一致。
    context: Optional[dict] = None
    # 界面当前语言（`en` / `zh-CN`，2026-10-13 新增）。现场上下文恒为中文，
    # 仅靠「按提问语言猜」在短问句上会判错 → 作为权威声明写进 system prompt。
    # 缺省 None 时不加该声明，行为与老版完全一致。
    locale: Optional[str] = None


class AgentConfirmRequest(BaseModel):
    call_id: str
    approved: bool
    actor: str
    confirm_token: Optional[str] = None
    # 前端执行类工具的**真实执行结果**（2026-10-10 新增）：
    # {ok: bool, summary: str, data?: any}。设备桥凭据流（带 confirm_token）不传此字段，
    # 缺省 None 时行为与以前一致。
    result: Optional[dict] = None


# ── 工具标题（前端 title 显示用）──
#
# ⚠️ 这里给的是**后端来源**的 title，前端 `ToolCallCard` 对后端来源**不套 uiT()**
# （见该文件 L37 的 `call.uiAuthored ? uiT(call.title) : call.title`，与私有注释
# 「Translation provenance belongs to local UI producers」一致）——所以英文界面下
# 若这里只给中文，卡片标题就会漏翻。故按 locale 直接给对应语言。
_TOOL_TITLES = {
    "KnowledgeSearch": "知识库检索",
    "DocLibrarySearch": "资料库检索",
    "WebSearch": "联网搜索",
    "ReadField": "查询字段",
    "WriteField": "修改字段",
    "WriteReportHeader": "填写报告表头",
}
_TOOL_TITLES_EN = {
    "KnowledgeSearch": "Knowledge search",
    "DocLibrarySearch": "Document library search",
    "WebSearch": "Web search",
    "ReadField": "Read field",
    "WriteField": "Write field",
    "WriteReportHeader": "Fill report header",
}


def _tool_title(name: str, locale: Optional[str]) -> str:
    """按界面语言取工具标题；未知工具回落到工具名本身。"""
    table = _TOOL_TITLES_EN if locale == "en" else _TOOL_TITLES
    return table.get(name, name)


def _summarize_args(name: str, input_: Any, locale: Optional[str] = None) -> str:
    """生成 argsSummary（前端不渲染参数，摘要由后端给）。

    ⚠️ `locale="en"` 时必须给英文摘要：前端 `ToolCallCard` 对**后端来源**的文案
    **不套 uiT()**（它按 `uiAuthored` 区分来源），只给中文会在英文界面下漏翻
    —— 实测：报告页工具卡片残留「列出本页全部可编辑字段」。
    缺省 None 走中文口径，与改动前行为完全一致（向后兼容）。
    """
    en = locale == "en"
    if not input_:
        return f"Call {name}" if en else f"调用 {name}"
    # 通用字段写（2026-10-14）：一次调用可带多项变更，逐项列出来，
    # 让确认卡上「改哪几项、各改成什么」一眼看全（用户要求批量合并成一张卡）。
    if name == "WriteField":
        try:
            changes = input_.get("changes") or []
            pairs = [
                f"{c.get('field')} → {c.get('value')}"
                for c in changes
                if isinstance(c, dict) and c.get("field")
            ]
            if pairs:
                head = (
                    f"Will change {len(pairs)} item(s): "
                    if en
                    else f"将改 {len(pairs)} 项："
                )
                return head + ("; " if en else "；").join(pairs)
        except AttributeError:
            pass
    if name == "ReadField":
        try:
            if input_.get("all"):
                return "List all editable fields on this page" if en else "列出本页全部可编辑字段"
            fld = input_.get("field") or ""
            if fld:
                return f'Look up "{fld}"' if en else f"查询「{fld}」"
        except AttributeError:
            pass
    # 写类工具：把「字段=值」点出来，让人在半秒内看清这条确认卡要写什么
    if name == "WriteReportHeader":
        try:
            field = input_.get("field") or ""
            value = input_.get("value")
            if field:
                return (
                    f'Fill "{field}" with "{value}"'
                    if en
                    else f"将「{field}」填写为「{value}」"
                )
        except AttributeError:
            pass
    try:
        q = input_.get("query") or input_.get("q") or ""
        if q:
            return f'Search "{q}"' if en else f"检索「{q}」"
    except AttributeError:
        # input_ 不是 dict（模型偶尔给成字符串或列表），没有 .get。
        # 这不是异常路径而是**已知的正常分支**，下面那行兜底就是它的处理，
        # 所以这里不记日志——写了反而每次都刷屏。保留注释说明，避免被误读成吞异常。
        pass
    # 兜底：参数对象精简成一行
    return json.dumps(input_, ensure_ascii=False)[:120]


def _summarize_result(name: str, summary: Any) -> str:
    """生成 resultSummary（前端不渲染，后端给）。"""
    if isinstance(summary, dict) and summary.get("skipped"):
        # 重复检索被短路（agent_chat_service 里同名同参跳过），前端卡片据此标注，
        # 让人一眼看出「模型曾尝试重复、已被拦截」，留痕完整。
        return f"{name} 已跳过重复检索（复用上一条结果）"
    # 前端执行类工具（写类，2026-10-10）：摘要走 detail，如实转述
    # 已写入 / 失败 / 未执行——卡面直接把这句话给操作员看。
    if isinstance(summary, dict) and "detail" in summary:
        return str(summary.get("detail") or f"{name} 完成")
    if isinstance(summary, dict) and "count" in summary:
        return f"{name} 返回 {summary.get('count', 0)} 条来源"
    return f"{name} 完成"


# 前端「依据」面板只认三类，见 features/agent-chat/types.ts 的 EvidenceKind：
#   procedure 规程条目 / case 相似案例 / document 资料段落
# 它按 kind 三向过滤分组（EvidencePanel.tsx:22-23 ORDER），落在三类之外的一律不显示。
_EVIDENCE_KINDS = {"procedure", "case", "document"}


def _to_evidence_kind(raw: str | None) -> str:
    """把检索层的 kind 归一到前端的三分类。

    ⚠️ 这里必须做映射，不能直接透传：检索层给的是 chunk（文档切片）/ param
    （Customer.h 宏），**两者都不在前端的三分类里**。曾一度直接透传，结果
    「依据 共 12 条」但三个分类全显示「本次判定未命中」——条目被算进了总数，
    却因为 kind 不匹配而一条都不渲染。

    归类依据：
      chunk / param / document → document（资料段落）：
        前者是文档切片、后者是工程参数宏，来源都是随包的资料文件。
      procedure（规程）与 case（相似案例）本知识库暂无对应数据源，保持空即可。
    """
    k = (raw or "").strip().lower()
    if k in ("chunk", "param", "document", ""):
        return "document"
    return k if k in _EVIDENCE_KINDS else "document"


def _sources_to_evidence(sources: list) -> list[dict]:
    """把检索结果映射成前端 evidence items。

    四个字段的取法（对应前端 EvidencePanel 的四处渲染）：

    - title    → 卡面标题。取不到标题就用来源或兜底「资料」。
    - excerpt  → 卡面副标题，**显示原文片段**。此前写死空串，导致每条依据
                 只有标题、看不出检索到了什么（用户反馈过这一点）。
    - locator  → 底部定位信息（页码 / 章节路径），供人回查原文档。
    - href     → 有**真链接**（如资料库预览地址）才给；本地知识库没有可点的
                 PDF 地址，留空的处理改由前端「跳到知识库页并选中该文档」承担，
                 不再显示会让人误解成「原文没检索到」的旧文案。
    - kind     → 必须归一（见 `_to_evidence_kind`），否则前端分组时全部落空。
    - doc_id   → **新增**：资料的 doc_id（如 fu6832-datasheet）。前端依据卡据此
                 跳到 /knowledge 并选中对应条目，替代原来不存在的 PDF 链接。
                 取不到就留空，前端退回不可点。
    """
    items = []
    for i, src in enumerate(sources):
        if not isinstance(src, dict):
            continue
        items.append({
            "id": f"ev-{i}",
            "kind": _to_evidence_kind(src.get("kind")),
            "title": src.get("title") or src.get("source") or "资料",
            "excerpt": src.get("excerpt") or "",
            "source": src.get("source") or "",
            "locator": src.get("locator") or "",
            "href": src.get("url") or src.get("href"),
            # 供前端跳到知识库页定位该文档；本地检索器在 source 里已带 doc_id。
            "doc_id": src.get("doc_id") or "",
        })
    return items


# ── 适配流：客户后端事件 → 前端六事件 ──
class _Compat:
    def __init__(self, run_token: str = "", locale: Optional[str] = None):
        # 每轮请求一个 token，拼进 messageId。
        #
        # 前端按 messageId 找气泡：id 首见即建气泡，再见即往同一气泡追加文本。
        # 适配器实例是每轮请求新建的，若 id 只按轮内序号生成（m-1、m-2…），
        # 第二轮又会从 m-1 开始，于是新回答被追加进上一轮那个 m-1 气泡里——
        # 界面上表现为「上一条回复被重新发了一遍、还接在旧文字后面」。
        # 加上请求级前缀后，跨轮不再撞 id。
        self.run_token = run_token
        # 界面语言：决定工具标题给中文还是英文（后端来源的 title 前端不套 uiT）。
        self.locale = locale
        self.msg_seq = 0
        self.cur_msg_id = None
        self.in_text = False
        self.tool_start: dict[str, float] = {}

    def _next_msg_id(self) -> str:
        self.msg_seq += 1
        return f"{self.run_token}-m{self.msg_seq}" if self.run_token else f"m-{self.msg_seq}"

    def map(self, ev: dict) -> list[dict]:
        """把单个客户后端事件映射成 0~N 个前端事件。"""
        t = ev.get("type")
        out: list[dict] = []

        if t == "content_delta":
            text = ev.get("text", "")
            if not text:
                return out
            if not self.in_text:
                # 上一段结束、新一段开始 → 换新 messageId（坑 1：工具卡后继续说话必须换 id）
                self.cur_msg_id = self._next_msg_id()
                self.in_text = True
            out.append({"type": "message_delta", "messageId": self.cur_msg_id, "delta": text})
            return out

        # 任何非 content_delta 事件都结束当前正文段
        self.in_text = False

        if t == "tool_call":
            call_id = ev.get("id", "")
            name = ev.get("name", "")
            input_ = ev.get("input") or {}
            # callId 同样加请求级前缀：模型两轮里可能给出同一个 call_id，
            # 前端按 callId 回填结果，撞上就会把本轮结果写进上一轮的卡片。
            call_id = f"{self.run_token}-{call_id}" if self.run_token else call_id
            self.tool_start[call_id] = time.monotonic()
            out.append({
                "type": "tool_call",
                "callId": call_id,
                "name": name,
                "title": _tool_title(name, self.locale),
                "args": input_,
                "argsSummary": _summarize_args(name, input_, self.locale),
                # mutating 透传（2026-10-10）：写类工具由后端置 True，前端据此弹人工
                # 确认卡；检索类工具仍为 False，行为不变。缺省 False 兼容旧事件。
                "mutating": bool(ev.get("mutating")),
            })
            return out

        if t == "tool_result":
            call_id = ev.get("id", "")
            # 与 tool_call 同一套前缀，才能取回那次调用的起始时刻算耗时
            call_id = f"{self.run_token}-{call_id}" if self.run_token else call_id
            name = ev.get("name", "")
            summary = ev.get("summary") or {}
            start = self.tool_start.pop(call_id, None)
            duration = int((time.monotonic() - start) * 1000) if start else 0
            # status 透传（2026-10-10）：写类工具可能以「未执行 / 失败」收场，
            # 前端卡片需如实显示；检索类工具恒为 ok，行为不变（缺省 ok 兼容旧事件）。
            raw_status = ev.get("status") or "ok"
            out.append({
                "type": "tool_result",
                "callId": call_id,
                "status": "ok" if raw_status == "ok" else "error",
                "durationMs": duration,
                "resultSummary": _summarize_result(name, summary),
                "result": summary,
            })
            return out

        if t == "sources":
            items = _sources_to_evidence(ev.get("sources") or [])
            if items:
                out.append({"type": "evidence", "items": items})
            return out

        if t == "done":
            reason = "aborted" if ev.get("cancelled") else "complete"
            out.append({"type": "done", "reason": reason})
            return out

        if t == "error":
            out.append({"type": "done", "reason": "error", "message": ev.get("message", "")})
            return out

        # stream_start / reasoning_delta / tool_executing / ping 等协议外事件 → 丢弃
        return out


@router.get("/models")
async def list_agent_models(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """AI 助手面板的模型下拉候选。

    与 `GET /v1/gateway/models`（对外 CLI 用、走 api_key 鉴权）**同一套过滤口径**：
    仅 `chat_enabled=True` 且 `is_active=True` 的网关模型，按 `sort_order` 排序，
    再按模型级 visibility 权限过滤。差别只在鉴权：本路由挂在 `/api/agent/*` 下，
    与 `/api/agent/stream` 同源同门禁（`get_current_user`，AUTH_DISABLED 时回退
    本地管理员），这样助手页在免 token 模式下也能拿到列表。

    返回结构与前端 `types.ts` 的 `ModelOption` 对齐；`id` 即调用
    `/api/agent/stream` 时应上送的 `model` 字面量。前端取第一条作默认
    （local_admin_service._SEEDED_MODELS 的 sort_order 已保证主模型最小）。
    """
    from sqlmodel import select as _select
    from app.models.gateway import ModelPricing
    from app.models.user_group import UserGroupMember
    from app.services.permission import check_entity_permission

    user_id = current_user.id
    user_email = current_user.email or ""
    group_ids = [
        gm.group_id
        for gm in session.exec(
            _select(UserGroupMember).where(UserGroupMember.user_id == user_id)
        ).all()
    ]

    rows = session.exec(
        _select(ModelPricing)
        .where(ModelPricing.chat_enabled == True)  # noqa: E712
        .where(ModelPricing.is_active == True)  # noqa: E712
        .order_by(ModelPricing.sort_order, ModelPricing.id)
    ).all()

    data = []
    for m in rows:
        if not check_entity_permission(m, user_id, group_ids, user_email):
            continue
        data.append({
            "id": m.model_id,
            "name": m.display_name or m.model_id,
            "vision": m.vision,
            "reasoning": m.reasoning,
            "context_window": m.context_window,
            "provider_name": m.provider_name or "",
            "provider_icon": m.provider_icon or "",
            "provider_icon_size": m.provider_icon_size or "",
            "sort_order": m.sort_order,
            "is_tier": m.is_tier,
            "description": m.description or "",
        })
    return {"success": True, "code": 200, "message": "Success", "data": data}


@router.post("/stream")
async def agent_stream(
    body: AgentStreamRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """前端助手会话流：协议适配后转发客户后端 agent loop。

    user_id 从登录态取（主文档「身份从会话取得」红线）。AUTH_DISABLED=true 时
    前端不带 token，get_current_user 回退本地管理员；false 时需带 Bearer token。
    """
    client = request.app.state.ai_http_client
    # 请求级唯一前缀：前端按 id 找气泡/找工具卡，跨轮撞 id 会把新内容拼进旧卡片。
    compat = _Compat(
        run_token=f"r{int(time.time() * 1000) % 10_000_000}",
        locale=body.locale,
    )
    ip: Optional[str] = request.client.host if request.client else None
    user_id: int = current_user.id or 0

    # ── 跨轮会话记忆（2026-09-29）──
    # 前端 dshAdapter 已把 session_id（shell-<场景>-<流程>）随请求带来，此前这里
    # 硬编码 history=None，session_id 一个字节都没用上 → 模型每轮从零、跨轮重复检索。
    # 现在按 (user_id, session_id) 从 agent_chat_memory 读历史，喂给 run_agent_chat；
    # 轮结束后把「用户问题 + 最终答复」追加回记忆表。读不到（首次/无 session_id）
    # 时 history=None，行为与老版一致，不破坏向后兼容。
    history: Optional[list[dict]] = None
    if body.session_id:
        try:
            with Session(engine) as s:
                history = get_history(s, user_id, body.session_id)
        except Exception as e:  # noqa: BLE001 - 记忆读失败不阻断主链路，退回无历史
            logger.warning(f"agent memory load failed (session={body.session_id}): {e}")
            history = None

    async def event_stream():
        # 累积本轮最终答复正文，供轮结束后回写记忆（只写最终答复，不写过程流）
        final_text: list[str] = []
        try:
            async for ev in run_agent_chat(
                client=client,
                user_id=user_id,
                user_message=body.text,
                history=history,
                model=body.model,
                ip=ip,
                enabled_tools=body.enabled_tools,
                context=body.context,
                # 权限档位透传（2026-10-10 修复断点 A）：此前这里漏传，导致
                # 后端一直按只读过滤工具、模型也收不到档位。现在原样下传。
                permission=body.permission,
                # 界面语言透传（2026-10-13）：让 system prompt 明确声明该用哪种语言作答。
                locale=body.locale,
            ):
                if ev.get("type") == "content_delta":
                    final_text.append(ev.get("text") or "")
                for mapped in compat.map(ev):
                    yield _sse(mapped)
        except Exception as e:  # noqa: BLE001 - 任何未捕获异常都显式推 error，避免前端误判完成
            logger.error(f"agent stream compat failed: {e}")
            yield _sse({"type": "done", "reason": "error", "message": str(e)})
            return

        # 回写记忆：无 session_id 不写（无键可落）；正文为空（出错/被拒）也不写空轮
        if body.session_id and final_text:
            try:
                with Session(engine) as s:
                    append_turn(
                        s,
                        user_id,
                        body.session_id,
                        user_text=body.text,
                        assistant_text="".join(final_text),
                    )
            except Exception as e:  # noqa: BLE001 - 记忆写失败不阻断响应，只记日志
                logger.warning(f"agent memory save failed (session={body.session_id}): {e}")

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/confirm")
async def agent_confirm(
    body: AgentConfirmRequest,
    # 鉴权门禁（2026-09-23 全量审查补上）：本路由原先没挂鉴权。
    # 它现在会放行写类工具——更需鉴权：没门禁等于任何人都能放行写入。
    # user_id 也参与挂起项的归属校验（见 agent_confirm_bus.resolve）。
    current_user: User = Depends(get_current_user),
):
    """放行 / 取消回执（2026-10-10 实现挂起解析）。

    两类来源：
    1. **前端执行类工具**（WriteReportHeader 等）：agent loop 已把该 call_id 登记
       在挂起簿；这里 resolve 唤醒它，body.result 是前端真实执行结果（写成功/失败/
       被取消），loop 据此如实回填模型。
    2. **设备桥凭据流**（带 confirm_token，阶段 5）：当前后端无对应挂起项，
       保持原 404 行为（向后兼容，不破坏既有设备桥路径）。

    返回：
    - 命中挂起项 → 200 {ok: true, resolved: true}；
    - 无挂起项   → 404 {error: "no pending confirmation"}（与旧行为一致）。
    """
    from app.services import agent_confirm_bus

    user_id: int = current_user.id or 0

    # ⚠️ callId 前缀剥离：前端拿到的 callId 形如 "r{毫秒}-{模型原始id}"
    # （_Compat.map 加的请求级前缀，防跨轮撞 id）。挂起簿登记的是 loop 侧**原始**
    # tu_id，故这里必须先剥掉前缀再查，否则永远查不到。
    raw_call_id = body.call_id
    if raw_call_id and raw_call_id.startswith("r") and "-" in raw_call_id:
        head, _, tail = raw_call_id.partition("-")
        if head[1:].isdigit() and tail:
            raw_call_id = tail

    # 取消（approved=False）也要唤醒挂起位——否则 loop 会一直等到超时。
    payload = {
        "approved": bool(body.approved),
        "actor": body.actor,
        "result": body.result or {},
        "reason": "" if body.approved else "cancelled",
    }
    if agent_confirm_bus.resolve(raw_call_id, payload, user_id):
        return JSONResponse(status_code=200, content={"ok": True, "resolved": True})

    # 无挂起项：保持旧行为（设备桥凭据流尚未接，回 404）
    return JSONResponse(status_code=404, content={"error": "no pending confirmation"})
