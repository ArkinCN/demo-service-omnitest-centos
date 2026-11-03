"""
AI 对话 Agent Loop 的检索工具（阶段②）

三个工具，对模型而言都是「输入 query → 返回带来源的资料片段」：
- KnowledgeSearch  : 内网精简检索服务（半导体/电机控制等领域知识，PRIMARY）
- DocLibrarySearch : 文档平台资料库（FastGPT 纯检索端点 searchTest）
- WebSearch        : 火山引擎联网搜索（兜底）

每个执行器返回 (text_for_model, sources)：
- text_for_model: 拼好的资料文本，作为 tool_result 回填给模型
- sources       : 归一化来源列表 [{title, url?, source, score?}]，供前端「引用来源」展示
"""

import httpx
from typing import Any, List, Optional

from app.core.config import settings
from app.core.logger import logger

# ── 工具定义（Anthropic tools schema）──

# 与 mdebug-code CLI 的同名工具定义逐字对齐（crates/tools/src/lib.rs 的 KnowledgeSearch），
# 改动请两边同步。
#
# ⚠️ 本平台增补（2026-10-05，CLI 侧同步再议）：
#   descript 末尾加了「Scope to the current page」一段（流程语义约束）。
#   起因：流程 5（测试报告及产出）页的助手把流程 1 的文档（Customer.h 解析出的
#   本体属性/工程宏条目）当成依据挂到了报告页的依据卡上，并据此答出了流程 1 的
#   占位清单（用户实测「阶段五引用错误的阶段一数据并违规展示」）。
#   检索本身是**全量语义检索**（datasets 固定七库、不做路由，这是设计如此），
#   所以约束只能下在「怎么用召回结果」这一层——即告诉模型「跨阶段的片段不能当本页依据」。
#   这是本平台的增补段，`input_schema` 结构一字未动。
KNOWLEDGE_SEARCH = {
    "name": "KnowledgeSearch",
    "description": (
        """Search ALL internal company knowledge bases. Call this FIRST for any question about
semiconductors, motor control (BLDC/FOC), home appliances, or company products.
Do NOT call it for casual chat, arithmetic, or general world knowledge.

The system always searches all datasets with rerank enabled — you get a unified,
ranked result list of 5-15 chunks. No routing or configuration needed.

## How to call

- question: ALWAYS query in Chinese, no matter what language the user asked in
  (the Chinese corpus is the most complete). Keep it as a NATURAL SENTENCE:
  * Translate the user's question to Chinese, preserving its sentence form.
    Do NOT compress into bare keywords — the hybrid engine needs the full
    sentence for semantic matching, and key-term extraction is automatic.
  * Preserve all chip model numbers — any model mentioned by the user MUST
    appear verbatim (with prefix, e.g. "6815" → "FU6815"). Acronyms
    (PFC, PWM, FOC...) stay as-is; they are language-neutral.
  * Only strip pure noise: greetings and prefixes like "请问", "我想知道".
- keyword: ALWAYS set to true — enables automatic key-term extraction and
  boosting on top of semantic search.
- datasets: ALWAYS pass ALL knowledge bases to maximize coverage:
  ["master_notebook", "general_notebook", "coolingfan_notebook",
   "refrigerator_notebook", "promotion_notebook", "seatfan_notebook",
   "cleaner_notebook"]
- rerank: ALWAYS set to true for best result ordering.
- vector_similarity_weight / similarity_threshold: leave at defaults;
  filter results yourself.
- Do NOT narrate what you are doing (e.g. "让我先搜一下", "让我再试试…").
  Execute the calls silently and present only the final answer.

## Self-check before calling (DO THIS BEFORE EVERY CALL)

Search only when necessary — do NOT repeat an identical search:

1. If you have already called KnowledgeSearch in this turn with the SAME
   question (or a question that only differs in word order), do NOT call it
   again. Answer from the results you already have.
2. If the previous call returned useful chunks (any with >= 0.4), stop and
   answer from them. Do NOT call again.
3. If the previous call returned nothing useful, you may make AT MOST ONE
   more call, this time using bare keywords (e.g. "FU6815 PFC PWM 最小脉宽").
   After that, stop searching regardless of the outcome and answer from what
   you have.
4. If the previous call returned an error, stop searching immediately and
   fall back to your own knowledge or WebSearch.

## Chip model filtering (CRITICAL)

When the question asks about a SPECIFIC chip model:
- RULE 1: NEVER mention, reference, or compare with other chip models in your
  answer. Not in passing, not as context, not as a note. Zero cross-chip content.
  If the user asks about FU6815, your answer contains ONLY FU6815 information.
- BEFORE using any chunk, check its source document name. Does it belong to the target chip?
- A chunk is VALID only if its document name contains the target model string (e.g.
  "FU6815" for a FU6815 question). If the document name contains a DIFFERENT model
  number (e.g. "FU7512"), that chunk is INVALID — discard it completely. Different
  chip = different hardware = different answer.
- If valid chunks partially cover the answer but key details are missing, still give a
  brief answer based on what IS known, then point out what's missing and invite the user
  to narrow the question.
- Exception: master_notebook Q&A pairs that explicitly mention the target chip are valid
  even if the document name doesn't contain the model number.
- NEVER claim that registers from another chip are "identical" or "架构一致" to fill gaps.
  You don't know that. The fact that two chips share a series prefix does NOT mean their
  registers are the same. Only the chip's own datasheet is authoritative.
- If valid chunks partially cover the answer but key details are missing, still give a
  brief answer based on what IS known, then point out what's missing and invite the user
  to narrow the question.

## Similarity thresholds for citing results

- >= 0.7: cite directly with confidence
- 0.4-0.7: use with judgment
- < 0.4: treat as unreliable; if all chunks are below this, say "知识库未找到直接相关的内容"

## Citing

Every fact from a chunk MUST cite its source document: [来源: <document_name>].

## Scope to the current page (IMPORTANT)

The 现场上下文 in your system prompt tells you WHICH page/flow the user is on
(e.g. 初始化配置 / 测试需求确认 / 启动测试及结果分析 / 调优确认及运行 / 测试报告及产出).

- When you cite chunks, they must support the CURRENT page's subject.
- If a retrieved chunk belongs to a DIFFERENT flow's subject (e.g. the user is on
  the report page but the chunk is about 本体属性 / 控制参数 / 工程宏 / 占位字段),
  do NOT present it as evidence for this page, and do NOT build a field list from it.
  Cross-flow chunks may only be used if the user explicitly asks about that other flow.
- Never enumerate another flow's field list (e.g. 本体属性占位清单) on the current page.
"""
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "minLength": 1,
                "description": "The search query. Follow the question rules in the tool description above.",
            },
            "top_k": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "description": "Per tool description: system returns 5-15 chunks by default; adjust only if you need more or fewer.",
            },
            "datasets": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Per tool description: pass all knowledge bases for maximum coverage.",
            },
            "rerank": {
                "type": "boolean",
                "description": "Per tool description: always set to true.",
            },
            "similarity_threshold": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Per tool description: leave at default 0.2 and filter results yourself.",
            },
            "vector_similarity_weight": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Per tool description: leave at default; omit this parameter.",
            },
            "keyword": {
                "type": "boolean",
                "description": "Per tool description: ALWAYS set to true — enables automatic key-term extraction and boosting.",
            },
        },
        "required": ["question"],
        "additionalProperties": False,
    },
}

DOC_LIBRARY_SEARCH = {
    "name": "DocLibrarySearch",
    "description": (
        "查询并获取示例科技的产品资料：数据手册、产品手册、应用笔记、"
        "用户指南、推广资料、开发工具、demo 程序等。当用户想要「下载/获取某型号的"
        "手册/数据手册/资料/工具」或询问「有没有 XX 的资料/手册」时，调用此工具。"
        "返回的内容通常是带下载/预览链接的 Markdown 表格（链接形如 "
        "https://docs.example.internal:...），请把这些资料链接原样、完整地转述给用户，"
        "不要伪造或修改链接。支持型号模糊匹配。Query 用中文或英文均可。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "用户想要的资料描述，如「FU6832 数据手册」「FU6815 应用方案」。",
            },
        },
        "required": ["question"],
    },
}

WEB_SEARCH = {
    "name": "WebSearch",
    "description": (
        "Search the public web for up-to-date or general information. Use ONLY as a "
        "fallback when the internal knowledge base and document library do not contain "
        "enough information to answer, or for general/current-events questions."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        "required": ["query"],
    },
}

# ── 写类工具（2026-10-10 新增，权限切换修复）──
#
# 与三个检索工具不同，本工具**不在后端执行**：模型发起调用后，后端把这次调用
# 挂起并推 tool_call(mutating=true) 给前端弹人工确认卡，人点「确认执行」后由
# **前端**真正写入（写 store + 落库 report-instance），执行结果经 /api/agent/confirm
# 回传，再作为 tool_result 回填模型继续作答。见 agent_chat_service 的挂起分支。
#
# 名字登记在 FRONTEND_EXECUTED_TOOLS，loop 据此走「挂起-回填」而非本地执行。
#
# ── 通用字段工具（2026-10-14 新增：自然语言增删改查当前页面字段）──
#
# 与 WriteReportHeader 的差别：后者只覆盖「报告表头」一类字段，前者覆盖**当前页面上
# 全部可编辑字段**（本体属性 pa / 控制参数 cp / 报告表头 rp.header），按四段键寻址。
# 键口径的唯一真源是前端 `features/copilot/context.ts` 的 leafKey()：
#   ${flow}.pa.${group}.${key} / ${flow}.cp.${group}.${key} / ${flow}.rp.header.${key}
# 后端**不解析键**（不重复实现一套寻址逻辑），只负责下发 tool_call、前端解析并执行、
# 如实回执。解析失败时前端会返回相似候选，模型据此自纠或如实告知。
READ_FIELD = {
    "name": "ReadField",
    "description": (
        "查询【当前页面】字段的当前值、取值范围、是否可编辑与出处路径。\n"
        "· all=true：列出本页全部可编辑字段（含当前值、单位、可选值）。"
        "用户问「这页有哪些字段/哪些还没填/某项等于多少」时用这个。\n"
        "· all 省略或 false：按 field 查单个字段。\n"
        "【重要】读操作无副作用，**无需人工确认**，会立即返回结果。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "field": {
                "type": "string",
                "description": "字段的完整层级路径（如「被测对象 → 机械外形 → 风扇外形尺寸」）、字段名或键。all=true 时可省略。",
            },
            "all": {"type": "boolean", "description": "true 时列出本页全部可编辑字段清单。"},
        },
    },
}

WRITE_FIELD = {
    "name": "WriteField",
    "description": (
        "增/改/清空【当前页面】的可编辑字段值，覆盖三类：本体属性、控制参数、报告表头。\n"
        "· 定位：优先用现场上下文给出的**完整层级路径**（如「被测对象 → 机械外形 → 风扇外形尺寸」），"
        "也可用字段名或键。\n"
        "· 批量：用户一句话要求改多项时，**合并成一次调用**，changes 里放多条，"
        "操作员只确认一次。\n"
        "· 取值：只填数值/文本本身，**不要带单位后缀**（写 20 而不是「20mm」）。\n"
        "· 清空：把 value 传空串（仅占位项或人工填过的项允许清空）。\n"
        "【重要】这是**写操作**：调用后会先弹人工确认卡，确认后才真正写入页面。"
        "确认前不要声称已经写好；工具返回被取消或失败时，必须如实转述，"
        "并把「哪一项失败、为什么」讲清楚，绝不谎称已完成。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "changes": {
                "type": "array",
                "description": "要写入的字段列表（批量修改时放多条）。",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "description": "字段的完整层级路径、字段名或键。",
                        },
                        "value": {
                            "type": "string",
                            "description": "新值（按字段自身单位，不带单位后缀）；清空该字段传空串。",
                        },
                    },
                    "required": ["field", "value"],
                },
            },
        },
        "required": ["changes"],
    },
}

WRITE_REPORT_HEADER = {
    "name": "WriteReportHeader",
    "description": (
        "填写/修改测试报告的**报告表头字段**（如客户名称、工程师、Email 等抬头信息）。"
        "当用户要求「填写/填写客户名称/改一下报告抬头里的某个字段」时调用此工具。\n"
        "参数 field 用字段的中文名或英文键都行（如「客户名称」或 customer_name），"
        "value 是要写入的值。\n"
        "【重要】这是**写操作**：调用后会先由操作员人工确认，确认后才真正写入；"
        "确认前不要声称已经写好。若工具返回未执行/失败，必须如实转述，不得谎称完成。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "field": {
                "type": "string",
                "description": "要填写的报告表头字段，中文名（如「客户名称」）或英文键（如 customer_name）。",
            },
            "value": {"type": "string", "description": "要写入该字段的值。"},
        },
        "required": ["field", "value"],
    },
}

ALL_TOOLS = [
    KNOWLEDGE_SEARCH,
    DOC_LIBRARY_SEARCH,
    WEB_SEARCH,
    READ_FIELD,
    WRITE_FIELD,
    WRITE_REPORT_HEADER,
]

# 由**前端**执行的工具名集合。
#
# ⚠️ 分两类（2026-10-14 通用增删改查改造）：
#   · 变更类（_MUTATING_FRONTEND_TOOLS）—— 有副作用，**必须**弹人工确认卡；
#   · 读取类（ReadField）—— 无副作用，**不弹卡**，前端直接执行并回执。
# loop 遇 FRONTEND_EXECUTED_TOOLS 里的名字走「挂起-回填」，不本地执行；
# 是否 mutating 由 agent_chat_service 按 _MUTATING_FRONTEND_TOOLS 判定。
FRONTEND_EXECUTED_TOOLS = {"ReadField", "WriteField", "WriteReportHeader"}

# 变更类前端工具（需人工确认）。不在本集合内的前端工具按「只读、免确认」处理。
MUTATING_FRONTEND_TOOLS = {"WriteField", "WriteReportHeader"}

# ── 权限档位 → 允许的工具名（**服务端硬上限**，不信任前端）──
#
# 三重防线中的第 2 层（第 1 层是 select_tools 的按档过滤让模型根本看不到写工具，
# 第 3 层是 loop 内的 allowed_names 拦截 + 前端确认卡）。未知档位一律按只读处理
# （安全默认），绝不因为传了个没见过的值就放开写能力。
#
# ReadField 放只读档（查无副作用）；WriteField 只进写档。
_READONLY_TOOLS = {"KnowledgeSearch", "DocLibrarySearch", "WebSearch", "ReadField"}
_WRITE_TOOLS = {"WriteField", "WriteReportHeader"}

PERMISSION_TOOLS = {
    "readonly": _READONLY_TOOLS,
    "params": _READONLY_TOOLS | _WRITE_TOOLS,
    "hardware": _READONLY_TOOLS | _WRITE_TOOLS,  # 设备控制工具下一批再接
}


def allowed_tool_names(permission: Optional[str]) -> set:
    """按权限档位取允许的工具名集合（服务端权威口径）。未知档位 → 只读。"""
    return PERMISSION_TOOLS.get((permission or "readonly").strip().lower(), _READONLY_TOOLS)


def select_tools(enabled: Optional[List[str]], permission: Optional[str] = None) -> List[dict]:
    """按「前端 enabled 列表 ∩ 权限档位允许集」过滤 ALL_TOOLS。

    不再做「enabled 缺省 = 全开」的兼容——未显式声明启用的工具一律视为关闭，
    避免请求丢字段/漏传时静默放开全部工具（含用户已关闭的）。

    ⚠️ permission 是**服务端硬上限**：即使前端 enabled 里混进了写工具，只要当前
    档位是只读，这里也不会把它放进去。前端那层 enabled_tools 只是「用户开关」，
    权限边界由后端这道兜底决定（不信任前端）。permission=None → 按只读处理。
    - enabled = None/[]  → 返回空列表（不启用任何工具，模型纯回答）。
    - 其余          → 仅保留「在 enabled 里」且「属于该档位允许集」的工具，保持原顺序。
    """
    allow = allowed_tool_names(permission)
    enabled_set = set(enabled or [])
    return [t for t in ALL_TOOLS if t["name"] in enabled_set and t["name"] in allow]


# ── 执行器 ──


async def run_tool(client: httpx.AsyncClient, name: str, tool_input: dict) -> tuple[str, list[dict]]:
    """按工具名分发执行。返回 (text_for_model, sources)。出错返回错误文本 + 空来源。"""
    try:
        if name == "KnowledgeSearch":
            return await _knowledge_search(client, tool_input)
        if name == "DocLibrarySearch":
            return await _doc_library_search(client, tool_input)
        if name == "WebSearch":
            return await _web_search(client, tool_input)
        return f"未知工具: {name}", []
    except httpx.TimeoutException:
        return f"工具 {name} 超时，未取得结果。", []
    except Exception as e:
        logger.error(f"tool {name} failed: {e}")
        return f"工具 {name} 执行失败: {e}", []


async def _knowledge_search(client: httpx.AsyncClient, ti: dict) -> tuple[str, list[dict]]:
    question = (ti.get("question") or "").strip()
    if not question:
        return "KnowledgeSearch 需要非空 question。", []
    # 后端可切换：单机/离线部署走本地 BM25（内网服务在客户网络之外不可达）。
    # 这个分支只换「去哪儿检索」，对模型看到的文本与 sources 结构保持不变，
    # 因此前端「依据」面板无需改动。
    if (settings.KB_BACKEND or "local").strip().lower() == "local":
        return _knowledge_search_local(question, ti.get("top_k") or 8)
    # datasets,rerank临时写死，规避chatbox模型能力不足导致的用户传入不符合要求的值。
    payload = {
        "question": question,
        "top_k": ti.get("top_k") or 8,
        "datasets": [
            "master_notebook",
            "general_notebook",
            "coolingfan_notebook",
            "refrigerator_notebook",
            "promotion_notebook",
            "seatfan_notebook",
            "cleaner_notebook",
        ],
        "rerank": True,
    }
    # 其余可选参数只在模型显式给出时透传，缺省交由检索服务用其默认值。
    for key in ("similarity_threshold", "vector_similarity_weight", "keyword"):
        if ti.get(key) is not None:
            payload[key] = ti[key]
    url = f"{settings.KB_SEARCH_BASE_URL.rstrip('/')}/search"
    resp = await client.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {settings.KB_SEARCH_API_KEY}"},
        timeout=settings.KB_SEARCH_TIMEOUT,
    )
    if not resp.is_success:
        return f"KnowledgeSearch 后端错误 {resp.status_code}。", []
    data = resp.json()
    chunks = data.get("chunks") or []
    if not chunks:
        return f"知识库未找到与「{question}」相关的内容。", []

    lines, sources = [], []
    for i, c in enumerate(chunks, 1):
        content = (c.get("content") or "").strip()
        doc = c.get("document") or ""
        sim = c.get("similarity")
        lines.append(f"[{i}] (来源: {doc}, 相似度: {sim})\n{content}")
        sources.append(
            {
                "title": doc or f"片段{i}",
                "source": doc,
                "score": sim,
                "type": "knowledge",
            }
        )
    text = f"知识库检索「{question}」返回 {len(chunks)} 条：\n\n" + "\n\n".join(lines)
    return text, sources


def _knowledge_search_local(question: str, top_k: int) -> tuple[str, list[dict]]:
    """本地 BM25 检索（KB_BACKEND=local）。

    语料是前端 `public/kb/` 下的流水线产物（文档切片 + Customer.h 宏），
    由 `app/services/kb_search.py` 在进程内建一次索引后复用。

    与远端分支保持两点一致，前端才不用改：
    1. 给模型的文本形态一致（编号 + 来源 + 内容）；
    2. `sources` 的元素含 title / source / score / type，
       且 source 里带得出处（文档标题与页码），供前端「依据」面板回指。
    """
    from app.services.kb_search import get_engine

    try:
        hits = get_engine().search(question, k=top_k)
    except FileNotFoundError as e:
        # 语料目录缺失：如实说明是环境问题，不伪装成「没找到内容」
        return f"本地知识库不可用（{e}）。", []
    except Exception as e:  # noqa: BLE001
        logger.error(f"local kb search failed: {e}")
        return f"本地知识库检索失败：{e}", []

    if not hits:
        return f"知识库未找到与「{question}」相关的内容。", []

    lines, sources = [], []
    for h in hits:
        title = h.get("doc_title") or h.get("doc_id") or "资料"
        page = h.get("page")
        heading = " > ".join(h.get("heading_path") or [])
        where = f"{title}" + (f" 第 {page} 页" if page else "")
        # 宏名类命中把它点出来，模型更容易引用具体标识符
        if h.get("kind") == "param":
            where += "（参数宏）"
        lines.append(f"[{h['rank']}] (来源: {where}, 相似度: {h['score']})\n{h['snippet']}")
        sources.append({
            "title": where,
            "source": h.get("source_path") or h.get("doc_id") or title,
            "score": h.get("score"),
            "type": "knowledge",
            "page": page,
            "kind": h.get("kind"),
            # doc_id：资料标识。前端依据卡据此跳到知识库页定位该文档，
            # 替代不存在的 PDF 链接（见 agent_stream._sources_to_evidence）。
            "doc_id": h.get("doc_id") or "",
            # ── 以下两项供前端「依据」面板显示，此前为空导致面板无内容 ──
            # excerpt：原文片段。前端 ac-ev__excerpt 直接渲染它，
            #          留空会让每条依据只有标题、看不出检索到了什么。
            "excerpt": h.get("snippet") or "",
            # locator：定位信息（页码 + 章节路径），供人回查原文档。
            #          **不填 href**：原文 PDF 在客户工程里、未随交付包提供，
            #          伪造一个打不开的链接更糟；改由 doc_id 跳知识库页定位。
            "locator": " · ".join(x for x in (
                (f"第 {page} 页" if page else ""),
                heading,
            ) if x) or (h.get("chunk_id") or ""),
        })

    text = f"知识库检索「{question}」返回 {len(hits)} 条：\n\n" + "\n\n".join(lines)

    # ── 降级说明（阶段 3 补全：检索改为关键词 + 向量双路）──
    #
    # 为什么要把「降级」写进给模型的文本里：
    # 双路检索的召回边界与单路不同（向量一路缺失，或只用了字面哈希回退而非语义模型）。
    # 若不说明，模型会把「这次只召回了这几条」当成「知识库里就只有这些」，
    # 于是用肯定语气下结论——而实际是检索侧能力受限。这与 3-O 那次
    # 「知识库未检索到」被读成「库坏了」是同一类问题，必须显式交代。
    degrade = next((h.get("degrade_reason") for h in hits if h.get("degrade_reason")), "")
    if degrade:
        text += f"\n\n（检索说明：{degrade}）"

    return text, sources


async def _doc_library_search(client: httpx.AsyncClient, ti: dict) -> tuple[str, list[dict]]:
    """文档资料库检索。走 FastGPT 问答工作流(/v1/chat/completions, detail=true)：
    工作流内部已用「资料检索专家提示词」把命中资料整理成带下载/预览链接的 Markdown，
    直接取最终 content 作为给模型的资料文本；来源从 quoteList 的 sourceName 去重提取。
    """
    question = (ti.get("question") or "").strip()
    if not question:
        return "DocLibrarySearch 需要非空 question。", []
    url = f"{settings.DOC_LIBRARY_BASE_URL.rstrip('/')}/v1/chat/completions"
    resp = await client.post(
        url,
        json={
            "stream": False,
            "detail": True,
            "messages": [{"role": "user", "content": question}],
        },
        headers={
            "Authorization": f"Bearer {settings.DOC_LIBRARY_API_KEY}",
            "Content-Type": "application/json",
        },
        timeout=settings.DOC_LIBRARY_TIMEOUT,
    )
    if not resp.is_success:
        return f"DocLibrarySearch 后端错误 {resp.status_code}。", []
    body = resp.json()

    # 最终答案（已是带链接的 Markdown 资料表格）
    content = ""
    choices = body.get("choices") or []
    if choices:
        content = (choices[0].get("message") or {}).get("content") or ""
    content = content.strip()

    # 来源：从 quoteList 提取去重的 sourceName
    sources, seen = [], set()
    for module in body.get("responseData") or []:
        for it in module.get("quoteList") or []:
            src = it.get("sourceName")
            if src and src not in seen:
                seen.add(src)
                sources.append({"title": src, "source": src, "type": "doc_library"})

    if not content:
        return f"文档资料库未找到与「{question}」相关的资料。", sources
    text = f"文档资料库针对「{question}」返回如下资料（含下载/预览链接，请原样完整转述给用户）：\n\n" + content
    return text, sources


async def _web_search(client: httpx.AsyncClient, ti: dict) -> tuple[str, list[dict]]:
    query = (ti.get("query") or "").strip()
    if not query:
        return "WebSearch 需要非空 query。", []
    if not settings.VOLC_WEB_SEARCH_API_KEY:
        return "联网搜索未配置（VOLC_WEB_SEARCH_API_KEY 缺失）。", []
    max_results = min(ti.get("max_results") or 8, 50)
    resp = await client.post(
        settings.VOLC_WEB_SEARCH_BASE_URL,
        json={
            "Query": query[:100],
            "SearchType": settings.VOLC_WEB_SEARCH_TYPE,
            "Count": max_results,
            "Filter": {"NeedUrl": True},
            "NeedSummary": True,
        },
        headers={"Authorization": f"Bearer {settings.VOLC_WEB_SEARCH_API_KEY}", "Content-Type": "application/json"},
        timeout=settings.VOLC_WEB_SEARCH_TIMEOUT,
    )
    if not resp.is_success:
        return f"WebSearch 后端错误 {resp.status_code}。", []
    result = resp.json().get("Result") or {}
    hits = result.get("WebResults") or []
    if not hits:
        return f"联网搜索「{query}」未找到结果。", []

    lines, sources = [], []
    for i, h in enumerate(hits, 1):
        if not isinstance(h, dict):
            continue
        title = h.get("Title") or ""
        url = h.get("Url") or ""
        site = h.get("SiteName") or ""
        summary = (h.get("Summary") or h.get("Snippet") or "").strip()
        lines.append(f"[{i}] {title} ({site})\n{url}\n{summary}")
        sources.append({"title": title, "url": url, "source": site, "type": "web"})
    text = f"联网搜索「{query}」返回 {len(sources)} 条：\n\n" + "\n\n".join(lines)
    return text, sources
