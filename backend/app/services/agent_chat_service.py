"""
AI 对话 Agent Loop 服务（阶段②）

后端多轮工具循环：构建 Anthropic messages → 调上游模型（经统一网关的服务层，
非自调 HTTP）→ 解析 tool_use → 执行检索工具 → 回填 tool_result → 再调模型，
直到 stop_reason != tool_use 或达 max_iterations。

`run_agent_chat` 是 async generator，逐步 yield 过程事件（dict），由 SSE 端点转发：
  {"type": "reasoning_delta", "text": "..."}          # 推理增量（思考过程，流式）
  {"type": "content_delta",  "text": "..."}          # 正文增量（流式）
  {"type": "tool_call",      "id", "name", "input"}
  {"type": "tool_executing", "id", "name"}
  {"type": "tool_result",    "id", "name", "summary": {count, sources}}
  {"type": "sources",        "sources": [...]}          # 累计去重来源
  {"type": "content",        "content": "..."}          # 最终答复正文（一次性）
  {"type": "done"}
  {"type": "error",          "message": "..."}
"""
import asyncio
import json
from typing import Any, AsyncGenerator, Optional

import httpx
from sqlmodel import Session

from app.core.config import settings
from app.core.logger import logger
from app.db.session import engine
from app.services.gateway_service import GatewayService
from app.services.credits_service import CreditsService
from app.services.content_safety_service import content_safety
from app.services.agent_context import build_context_summary
from app.services import agent_tools


SYSTEM_PROMPT = (
    "你是 MotorDebug 的智能助手，服务于半导体、电机控制、嵌入式硬件等技术领域。\n\n"
    "你有三个工具：\n"
    "- KnowledgeSearch：内部知识库，回答技术/原理/参数/用法等「内容型」问题的首选。\n"
    "- DocLibrarySearch：本公司产品资料库，用于「获取资料文件」——数据手册、产品手册、"
    "应用笔记、用户指南、推广资料、开发工具、demo 等的下载/预览链接。\n"
    "- WebSearch：联网搜索，兜底。\n\n"
    "工作方式：\n"
    "1. 用户想「下载/获取某型号的手册/数据手册/资料/工具」或问「有没有 XX 的资料」时，"
    "必须调用 DocLibrarySearch，并把它返回的下载/预览链接（形如 https://docs.example.internal:...）"
    "原样完整地给用户。【重要】此类「要资料」的需求，下载链接只能来自 DocLibrarySearch；"
    "绝不能用 KnowledgeSearch 返回的文件名（如 xxx.pdf）冒充下载链接，也不要编造链接。\n"
    "2. 回答技术内容问题，优先 KnowledgeSearch；首次结果不充分就换关键词再检索（可多次）。\n"
    "3. 只有内部资料不足时才用 WebSearch。\n"
    "4. 基于检索到的资料作答并引用来源；资料确实没有就如实说明。\n"
    "用与用户相同的语言作答。"
)

# 各工具在 system prompt 里的介绍句 + 使用规则句，按当前实际启用的工具动态拼装，
# 避免用户关闭某工具后 system prompt 仍暗示「你有该工具」，导致模型仍尝试调用。
_TOOL_INTROS = {
    "KnowledgeSearch": "- KnowledgeSearch：内部知识库，回答技术/原理/参数/用法等「内容型」问题的首选。\n",
    "DocLibrarySearch": (
        "- DocLibrarySearch：本公司产品资料库，用于「获取资料文件」——数据手册、产品手册、" "应用笔记、用户指南、推广资料、开发工具、demo 等的下载/预览链接。\n"
    ),
    "WebSearch": "- WebSearch：联网搜索，兜底。\n",
    "ReadField": (
        "- ReadField：查询**当前页面**字段的当前值、取值范围、是否可编辑与出处路径。"
        "读操作**无需人工确认**，立即返回。\n"
    ),
    "WriteField": (
        "- WriteField：增/改/清空**当前页面**的可编辑字段值"
        "（本体属性、控制参数、报告表头三类）。"
        "按现场上下文给的完整层级路径定位，支持一次改多项。"
        "这是写操作，调用后会先弹人工确认卡。\n"
    ),
    "WriteReportHeader": (
        "- WriteReportHeader：填写/修改测试报告的**报告表头字段**（客户名称、工程师、Email 等）。"
        "这是写操作，调用后会先弹人工确认卡。\n"
    ),
}
_TOOL_RULES = {
    "DocLibrarySearch": (
        "用户想「下载/获取某型号的手册/数据手册/资料/工具」或问「有没有 XX 的资料」时，"
        "必须调用 DocLibrarySearch，并把它返回的下载/预览链接（形如 https://docs.example.internal:...）"
        "原样完整地给用户。【重要】此类「要资料」的需求，下载链接只能来自 DocLibrarySearch；"
        "绝不能用 KnowledgeSearch 返回的文件名（如 xxx.pdf）冒充下载链接，也不要编造链接。\n"
    ),
    "KnowledgeSearch": "回答技术内容问题，优先 KnowledgeSearch；首次结果不充分就换关键词再检索（可多次）。\n",
    "WebSearch": "只有内部资料不足时才用 WebSearch。\n",
    "ReadField": (
        "用户问「这一页有哪些字段 / 哪些还没填 / 某项当前是多少 / 某项能不能改 / 某项在哪」时，"
        "优先调用 ReadField：问单项传 field（用现场上下文给的完整层级路径），"
        "问全量传 all=true。**读操作不需要确认，直接调用即可**，不要因为「不确定能不能查」而改用猜测作答。\n"
    ),
    "WriteField": (
        "用户要求「把某项改成某值 / 帮我填上某项 / 清空某项」（**不限报告表头**，"
        "本体属性与控制参数同样适用，例如「把风扇外形尺寸改为 20mm，风扇厚度改为 3mm」）时，"
        "调用 WriteField：每个字段一项放进 changes，field 用现场上下文给的**完整层级路径**"
        "（如「被测对象 → 机械外形 → 风扇外形尺寸」），value **只填数值或文本本身、不要带单位后缀**"
        "（写 20 而不是「20mm」）。**用户一句话要改多项时必须合并成一次调用**，"
        "让人只确认一次，不要拆成多次调用。"
        "调用后**等待人工确认与执行结果**：只有工具返回「已写入」才算成功；"
        "若返回被取消、部分失败或全部失败，必须**如实分条转述**"
        "（哪一项成功、哪一项失败、失败原因），绝不可谎称已写好。\n"
    ),
    "WriteReportHeader": (
        "用户要求「填写/修改报告表头字段」（如「帮我填写客户名称为李123」「把工程师改成张三」）时，"
        "调用 WriteReportHeader，field 传字段中文名或英文键、value 传值。"
        "（WriteField 也能覆盖表头字段；两个都可用时优先用 WriteField，口径更统一。）"
        "调用后**等待人工确认与执行结果**：只有工具返回「已写入」才算成功；"
        "若返回未执行/被取消/失败，必须如实转述，绝不可谎称已写好。\n"
    ),
}

# 引用纪律（两个分支共用，改这里即可同步）。
#
# 为什么单列这一段：曾出现「检索明明返回了 8 条（工具卡可见），模型却在正文里写
# 『知识库未检索到与本页工作流对应的文档内容』」——事实层面没错（库里确实没有
# 「工作流说明」这类文档，只有产品手册），但措辞会被人读成「知识库坏了/是空的」，
# 与本项目「错在措辞也要修」的口径不符。所以定死两条：
#   ① 检索到相关内容就写清来自哪几份资料的哪个位置（文档名 + 页码/章节）；
#   ② 命中不足时，说「知识库中暂无『某某主题』类资料」，并说明这一段的依据到底
#      来自哪里（产品手册 / 现场上下文），**禁止**说「知识库未检索到」这种会被
#      误读成「知识库为空或故障」的话。
# 输出格式与用语纪律（2026-10-04 用户三条规范之一：可读性 + 回复异常治理）。
# 两个分支共用，改这里即可同步。
#
# 逐条对应实测反馈：
#   · 「模型告示」「模型需进一步核实」这类措辞——模型自称「模型」、术语腔，
#     操作员读不懂 → 定死「你是测试助手，面向台架操作员说人话」。
#   · 回答里裸奔 `|---|---|`——模型输出 GFM 表格但没用规范语法/混用代码块
#     → 前端已支持表格渲染（Markdown.tsx），这里明确「表格用 Markdown 表格
#     语法、每行以 | 开头以 | 结尾」；不用表格时用短句分点，不塞代码块。
#   · 「已确认的流程：[init [已勾选]]」——流程/参数写英文名 → 重申只用
#     上下文里给的名字（与 _CITE_RULE ③ 呼应）。
#   · 2026-10-13（用户反馈）：英文提问仍答中文 → 原本这里的「全文一律用简体中文」
#     与 _LANG_RULE 直接冲突，模型被前面那句压住，产出半中半英。
#     → 现改为「全篇使用与用户提问相同的语言」，并把 _LANG_RULE 提到最前、声明最高优先级。
_FORMAT_RULE = (
    "【输出格式与用语纪律】\n"
    "① 你是电机测试系统的测试助手，读者是台架操作员。"
    "**全篇使用与用户提问相同的语言**：用户用中文提问就通篇简体中文，"
    "用户用英文提问就通篇英文——正文、表格表头、表格单元格、脚注、出处路径**必须同一语言**，"
    "不要半中半英。"
    "不要自称「模型」「AI」「系统检测到」这类术语腔；直接说结论与建议。\n"
    "② **排版清晰、结构分明**：先结论后依据；并列内容用「- 」短句分点，"
    "一项一行；需要对照多条数据时用 Markdown 表格——**表格每一行都要以 | 开头、"
    "以 | 结尾，第二行写成 |---|---| 分隔行**（界面会把表格渲染成表格）。\n"
    "**禁止**把普通文字塞进代码块（``` ```）里输出，除非用户明确要代码。\n"
    "③ **所有流程、参数、字段一律用与回答语言一致的名字**，且**优先沿用现场上下文里"
    "给的那一份名字**（它已经按界面语言备好，直接照用即可，不要自己重译）。"
    "不要输出 init / req / run / tune / report 这类裸代号。"
    "两种语言下括号里的英文键都不要写进正文。\n"
    "④ 回答只围绕**当前页面**：现场上下文里没有的信息不要主动展开，"
    "更不要把其它测试阶段的参数情况混进当前阶段的回答。\n"
    "④' **不得复述其它流程的清单**：每个页面的「缺什么 / 有哪些字段 / 什么状态」都不一样，"
    "**只讲当前页面**。特别地，站在「测试报告及产出」页时，**不许**再列出初始化配置页的"
    "本体属性或控制参数清单（如额定转速、额定母线电压、整机额定相电流、风扇外形尺寸、"
    "风扇厚度、斜坡时间、整定使能），也不许给它们的出处路径——那与本页无关，"
    "属于把上一个阶段的内容搬到本页（用户实测反馈过）。"
    "若现场上下文没有给本页的对应数据，就如实说「本页上下文里没有这项」，不要拿别页的顶上。\n"
    "⑤ **现场上下文是当前唯一权威**：它以页面实时状态为准（人改过的值、已确认的项、"
    "本页缺哪些）。若你先前轮次的回答与本次现场上下文不一致（例如你之前说某项缺失、"
    "而上下文显示它已有值），**以现场上下文为准**，直接按新情况作答，不要沿用旧结论，"
    "也不要因为历史对话里出现过某个清单就把它再复述一遍。\n"
    "⑥ **分清「已填」与「没填」**：上下文里凡标了「人已经填好值」的项，"
    "**不许**再列为缺失、占位或待确认；只把标为「至今仍没填」「取不到有效值」的项"
    "说成缺项。数量必须按上下文给的分段计数说，不要自己另算一个数。\n"
)

_CITE_RULE = (
    "【引用纪律】\n"
    "① 只要检索到了支撑本条结论的内容，就必须写清它出自哪几份资料、哪一处"
    "（资料名 + 页码或章节号），让人能顺着回查；不要只写「根据知识库」这类含糊说法。\n"
    "② 若知识库里确实没有与问题主题对应的资料，要说明「知识库中暂无『某某主题』类资料」，"
    "并交代你这一段依据实际来自哪里（如产品手册、本页现场上下文、你自身的通用知识）。"
    "**禁止**使用「知识库未检索到」「知识库没有相关内容」这类字眼——它们会被读成"
    "「知识库为空或故障」，与实际不符（检索本身是成功的，只是没有该主题的资料）。\n"
    "③ **字段名优先照用现场上下文给的那一份**（它已按当前界面语言备好，"
    "英文界面下给的就是英文名，直接原样沿用，**不要再译回中文**、也不要加中文括注）。"
    "上下文没给对应名字时才按回答语言自己表达。"
    "两种语言下都**不要**把 rated_speed / fan_outer_size 这类裸英文键名单独写进正文；"
    "确有必要点出编码时写成「名称（rated_speed）」——"
    "即把名称按回答语言写出，编码用括号原样附上。\n"
    "④ **按条目列字段时，必须带出处**（用户明确要求的格式）。"
    "这里是**出处的定义**，照做别改："
    "**出处 = 该字段在左侧菜单里的完整层级路径**（一级类 → 二级组 → 字段名）。\n"
    "   正确写法：「**<一级类> → <二级组> → <字段名>**：<该项在本页的状态>」——"
    "路径与状态**都以现场上下文给的那一份为准**，不要自己拼、不要拿别处的示例套；"
    "层级分隔符固定用 →。**上下文给的路径已是英文时直接原样沿用**（不要译回中文）；"
    "仅在上下文给的是中文、而回答语言是英文时，才把它译成英文。"
    "两种语言下都**不许省略出处**。\n"
    "   ⚠️ **出处只写本页字段**：本页上下文里给了哪几个字段，就只写那几个字段的出处。"
    "**不得**把其它流程的字段（例如初始化配置的本体属性、控制参数）连同它的层级路径"
    "一起列进本页回答——那不是本页的数据，属于跨界复述（用户明确否掉过）。\n"
    "   **禁止**把 `.md` / `.h` / `.wfw` 这类**文件名、行号、代码定位**当出处写出来"
    "（如 `Customer.h:244`、`XXX操作手册.md 第六节`）——"
    "使用者不打开源码文件，这些对他没有意义（用户已明确否掉）。\n"
    "   上下文里给你的字段会带「出处：…」这一段，"
    "**路径内容以上下文给的那一份为准**（那就是左栏菜单的完整层级），不要自己拼；"
    "**但表达随回答语言**：英文作答时译成英文，中文作答时保留中文。"
    "上下文没给就写「出处：未登记」（英文作答写「Source: not registered」），"
    "**不许省略出处**，也不许自己编一个文件名顶上。"

)

# 语言约束（两个分支共用，改这里即可同步）
_LANG_RULE = (
    "【语言规则·优先级最高】必须使用与用户提问相同的语言回答："
    "用户用中文提问就通篇简体中文作答，用户用英文提问就通篇英文作答；"
    "即使检索到的资料、现场上下文、字段出处路径是中文，"
    "也要翻译成用户的语言后再作答。"
    "**本条优先级高于上文所有格式与引用规则**：上文凡出现「一律用简体中文」"
    "「中文名」「原样照抄」「照抄那串路径」等表述，一律理解为"
    "「按本条确定的语言表达」——中文提问时用中文，英文提问时用英文。"
    "**判定依据**：以用户本条提问使用的语言为准；"
    "提问是英文时（含界面为英文、用户只打了几个英文单词的情况）必须全英文作答。"
    "⚠️ **禁止把上下文里已是英文的内容译回中文**："
    "若现场上下文给的字段名/出处路径本身已是英文，直接原样沿用，不要翻译、不要加中文括注。"
)


def _build_system_prompt(
    tools: list[dict],
    context_summary: str = "",
    permission: str = "readonly",
    locale: str = "",
) -> str:
    """按本次请求实际启用的工具 + 权限档位动态生成 system prompt。

    只描述、只允许模型使用当前 tools 里声明的工具，避免用户关闭知识库等开关后，
    system prompt 仍暗示模型「你有该工具」而误导模型尝试调用已禁用的工具。

    permission：当前权限档位（readonly / params / hardware）。写成**权威的能力边界
    声明**——这是模型判断「我能不能写」的第一依据（2026-10-10 权限修复）。
    与 agent_context 的档位行同源同口径（都用中文能力描述），避免两处口径打架。

    locale（2026-10-13 新增）：界面当前语言（`en` / `zh-CN`）。前端的现场上下文
    （字段出处路径等）始终是中文，若只让模型「按提问语言猜」，短问句（如单个英文
    单词）容易判错语言 → 实测英文界面下 AI 回复仍夹中文。这里把界面语言作为
    **权威声明**写进 prompt，模型不必猜。缺省空串时行为与老版完全一致。

    context_summary：前端上送的上下文包压成的现场摘要（见 agent_context.py）。
    为空表示前端没上送上下文，此时不加这一段——模型退回通用回答即可。
    """
    names = [t.get("name") for t in tools if t.get("name") in _TOOL_INTROS]
    header = "你是 MotorDebug 的测试助手，面向电机测试台架的操作员作答。\n\n"
    # 权限声明放在最前：它是「能做什么」的硬边界，先于工具清单被模型读到。
    perm_line = _build_permission_rule(permission)
    # 界面语言声明（2026-10-13）：前端的现场上下文恒为中文，光靠「按提问语言猜」
    # 在短问句上会判错（实测英文界面下 AI 仍夹中文）。这里给一句权威声明，
    # 与 _LANG_RULE 同向、优先级也最高。locale 缺省（空串）时不加，行为不变。
    # ⚠️ 2026-10-14 重写（用户实测「英文界面 + 英文提问仍答中文」）。
    #
    # 旧版在英文分支写的是「**但答复语言以用户提问语言为准**……不要因为界面是英文
    # 就一律用英文作答」——本意是「界面语言不等于答话语言」，但连起来读，模型抓到
    # 的强信号是**「不要用英文作答」**。实测：英文界面 + 英文提问，模型通篇中文，
    # 且**主动把上下文里的英文出处（Device under test → ...）译回中文**
    # （「被测设备 → 机械外形 → 风扇厚度」），说明它确实读到了英文数据却选择中文输出。
    # 现在把「界面语言」与「作答语言」的关系写成**单向、无歧义**的一句话：
    #   英文界面 → 默认英文作答；仅当用户明显用中文提问时才切中文。
    # 这样既保住「界面是英文但用户用中文问 → 答中文」的既有能力，又消除了反向诱导。
    locale_line = ""
    if locale == "en":
        locale_line = (
            "【界面语言：英文】用户当前使用英文界面。"
            "**默认用英文作答**；只有当用户本条提问本身明显是中文时，才改用中文作答。"
            "提问是英文（哪怕只有一两个单词）时，一律用英文作答，"
            "包括表格表头、单元格与出处路径——**不要译回中文**。\n"
        )
    elif locale in ("zh-CN", "zh"):
        locale_line = (
            "【界面语言：简体中文】用户当前使用中文界面。"
            "**默认用中文作答**；只有当用户本条提问本身明显是英文时，才改用英文作答。\n"
        )
    # ⚠️ 2026-10-14 语言规则**提到正文最前**（先于权限声明与工具清单）。
    # 起因：英文界面 + 英文提问时，模型仍通篇中文，并把上下文里的英文出处译回中文。
    # 系统提示词是「位置越靠前权重越高」，而 _LANG_RULE 原先排在第 3~4 位、前面还压着
    # 一整段中文权限声明与工具介绍，被稀释掉了。现在 locale_line + _LANG_RULE 前置。
    lang_head = f"{locale_line}{_LANG_RULE}\n"
    if not names:
        body = (
            lang_head
            + f"{perm_line}\n"
            "当前没有可用的检索工具，直接基于你自己的知识作答；资料不足就如实说明，不要编造。\n"
            + _FORMAT_RULE
            + _CITE_RULE
        )
    else:
        intros = "".join(_TOOL_INTROS[n] for n in names)
        rules = "".join(f"{i}. {_TOOL_RULES[n]}" for i, n in enumerate(names, start=1))
        tail = (
            f"{len(names) + 1}. 基于检索到的资料作答并引用来源；资料确实没有就如实说明。\n"
            f"{len(names) + 2}. {_FORMAT_RULE}"
            f"{len(names) + 3}. {_CITE_RULE}"
        )
        body = f"{lang_head}{perm_line}\n你有以下工具：\n{intros}\n工作方式：\n{rules}{tail}"

    # ⚠️ 上下文摘要必须在**所有分支之后**统一追加。
    # 首版只在「有工具」那条路上追加，而「无工具」分支提前 return 了——
    # 结果关掉工具时模型完全看不到上下文，端到端表现为「模型说没有上下文」，
    # 而单元测摘要本身是通过的（所以只测摘要不够，必须端到端验一次）。
    if context_summary:
        body += f"\n\n{context_summary}"
    return header + body


def _build_permission_rule(permission: str) -> str:
    """权限档位 → system prompt 里的能力边界声明（与 agent_context._permission_line 同源）。

    与 agent_context 的档位行保持同一份文案（都取 PERMISSION_CN），
    确保模型从 system prompt 与现场上下文两处看到的权限口径完全一致。
    """
    from app.services.agent_context import PERMISSION_CN

    key = (permission or "readonly").strip().lower()
    desc = PERMISSION_CN.get(key, PERMISSION_CN["readonly"])
    return f"【当前权限档位】{desc}"


# 输出 + 工具定义 + 单轮检索回填 预留的 token 余量（从窗口里扣掉，给生成和工具留空间）
_CONTEXT_RESERVE_TOKENS = 6000
# 单次模型调用允许生成的最大 token 数
_MAX_OUTPUT_TOKENS = 64000
# 单张图片的粗估 token（上游视觉编码器按尺寸折算，典型约 1.5K~2K，取保守上限）。
# 关键：图片在 messages 里是超长 base64，绝不能按字符数估，否则一张图被估成几十万
# token，导致裁剪误判。计费仍以上游 usage 为准，这里只为「裁剪/窗口」判断。
_IMAGE_TOKEN_ESTIMATE = 2000


def _estimate_tokens(obj) -> int:
    """粗估 token 数，用于「是否超窗、要不要裁剪」的近似判断（非计费）。

    - 文本按字符数 / 3。
    - 图片块（Anthropic image / OpenAI image_url）按固定 _IMAGE_TOKEN_ESTIMATE，
      不计入 base64 字符数。
    - 容器（list/dict）递归累加。
    """
    import json as _json

    if isinstance(obj, str):
        return len(obj) // 3 + 1

    if isinstance(obj, dict):
        btype = obj.get("type")
        # 图片块：定额估算，忽略 base64 体积
        if btype in ("image", "image_url", "input_image"):
            return _IMAGE_TOKEN_ESTIMATE
        total = 0
        for k, v in obj.items():
            # 跳过纯二进制/base64 载荷字段，避免把 data URL 字符数算进去
            if k in ("source", "image_url", "data"):
                total += _IMAGE_TOKEN_ESTIMATE
                continue
            total += _estimate_tokens(v)
        return total + 1

    if isinstance(obj, list):
        return sum(_estimate_tokens(x) for x in obj)

    # 数字/布尔/None 等
    return 1


def _trim_messages(messages: list[dict], window: int) -> list[dict]:
    """滑动窗口裁剪：window<=0 不裁。超窗时从最早开始成对丢弃历史，
    始终保留最后一条（最新用户输入或本轮 tool 链）。

    Anthropic 要求 tool_use 与其 tool_result 配对，且首条不能是 tool_result，
    故按「整段」从头丢：每次丢掉开头的一条 user/assistant，丢到不超窗为止；
    若丢到只剩最后一条仍超窗，则不再丢（交由上游报错，避免丢掉当前问题）。
    """
    if window <= 0:
        return messages
    # 预留输出/工具余量，但不超过窗口一半，避免小窗口下 budget 变负而放弃裁剪
    reserve = min(_CONTEXT_RESERVE_TOKENS, window // 2)
    budget = window - reserve
    if budget <= 0:
        return messages

    def total(msgs):
        return sum(_estimate_tokens(m) for m in msgs) + _estimate_tokens(SYSTEM_PROMPT)

    trimmed = list(messages)
    while len(trimmed) > 1 and total(trimmed) > budget:
        # 丢掉开头一条；若开头是 assistant(含 tool_use)，连同紧随的 user(tool_result)一起丢
        first = trimmed[0]
        drop = 1
        if (
            first.get("role") == "assistant"
            and len(trimmed) > 1
            and _has_tool_result(trimmed[1])
        ):
            drop = 2
        trimmed = trimmed[drop:]

    # 安全兜底：裁剪后首条不能是带 tool_result 的 user（Anthropic 会报错）
    while len(trimmed) > 1 and _has_tool_result(trimmed[0]):
        trimmed = trimmed[1:]
    return trimmed


def _has_tool_result(msg: dict) -> bool:
    content = msg.get("content")
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
    return False


_COMPRESSED_PLACEHOLDER = "[历史检索结果已省略，相关信息已用于先前回答]"


def _compress_stale_tool_results(messages: list[dict]) -> None:
    """就地压缩「过期」的 tool_result：检索原料用完一次（模型已据此作答）后，
    在后续轮次里不再需要完整内容，替换成一句话占位，避免多次检索把上下文吃光。

    保留「最后一条」含 tool_result 的 user 消息不压缩（那是当轮刚检索、模型即将
    据此作答的原料）；更早的全部压缩。压缩保留 tool_use_id 以维持配对。
    幂等：占位串已是目标值则跳过；不向块写入自定义字段（避免污染上游 payload）。
    """
    last_tr_idx = -1
    for i, m in enumerate(messages):
        if _has_tool_result(m):
            last_tr_idx = i

    for i, m in enumerate(messages):
        if i == last_tr_idx or not _has_tool_result(m):
            continue
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if (
                isinstance(b, dict)
                and b.get("type") == "tool_result"
                and b.get("content") != _COMPRESSED_PLACEHOLDER
            ):
                b["content"] = _COMPRESSED_PLACEHOLDER


def _call_model_payload(
    model: str, messages: list[dict], tools: list[dict], context_summary: str = "",
    permission: str = "readonly", locale: str = "",
) -> dict:
    """构造一次模型调用的 payload（Anthropic Messages，带 system + tools）。

    tools 为空时不写入 `tools` 键——部分上游对空 tools 列表报错。
    locale：界面语言（`en`/`zh-CN`），透传给 system prompt 的语言声明。
    """
    payload = {
        "model": model,
        "max_tokens": _MAX_OUTPUT_TOKENS,
        "system": _build_system_prompt(tools, context_summary, permission, locale),
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
    return payload


# ── Anthropic → OpenAI Chat 格式转换（供 openai_chat 协议模型复用同一 agent loop）──
# loop 内部一律用 anthropic 表示；仅在调 openai_chat 上游时转成 OpenAI 请求格式，
# 响应再归一化回 anthropic（见 _stream_openai_chat），因此 run_agent_chat 无需改动。

def _anthropic_tools_to_openai(tools: list[dict]) -> list[dict]:
    """Anthropic tools schema → OpenAI function-calling tools schema。"""
    out = []
    for t in tools:
        out.append({
            "type": "function",
            "function": {
                "name": t.get("name"),
                "description": t.get("description", ""),
                "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
            },
        })
    return out


def _anthropic_content_to_openai_parts(content: Any) -> Any:
    """把 anthropic user content(str 或 text/image 块)转成 OpenAI content。

    纯 str 原样返回;含 image 块时转成 OpenAI 多模态数组(image → image_url data URL)。
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return content
    parts = []
    for b in content:
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt == "text":
            parts.append({"type": "text", "text": b.get("text", "")})
        elif bt == "image":
            src = b.get("source") or {}
            if src.get("type") == "base64":
                url = f"data:{src.get('media_type','image/png')};base64,{src.get('data','')}"
            else:
                url = src.get("url", "")
            parts.append({"type": "image_url", "image_url": {"url": url}})
    # 只有一个纯文本时降级为字符串（部分上游对单元素数组更挑剔）
    if len(parts) == 1 and parts[0].get("type") == "text":
        return parts[0]["text"]
    return parts


def _anthropic_messages_to_openai(system_prompt: str, messages: list[dict]) -> list[dict]:
    """把 anthropic messages(含 tool_use/tool_result)转成 OpenAI chat messages。

    - system → 头部 system 消息;
    - user + str/文本图像块 → user 消息;
    - user + tool_result 块 → 每块一条独立的 tool 角色消息(OpenAI 规范,非 user);
    - assistant + 块 → assistant 消息(text 合并进 content;tool_use → tool_calls)。
    """
    out: list[dict] = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if role == "user":
            blocks = content if isinstance(content, list) else None
            if blocks and all(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks
            ):
                for b in blocks:
                    out.append({
                        "role": "tool",
                        "tool_call_id": b.get("tool_use_id"),
                        "content": b.get("content") if isinstance(b.get("content"), str)
                        else json.dumps(b.get("content"), ensure_ascii=False),
                    })
            else:
                out.append({"role": "user", "content": _anthropic_content_to_openai_parts(content)})
        elif role == "assistant":
            text_parts = []
            tool_calls = []
            if isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        text_parts.append(b.get("text", ""))
                    elif b.get("type") == "tool_use":
                        tool_calls.append({
                            "id": b.get("id"),
                            "type": "function",
                            "function": {
                                "name": b.get("name"),
                                "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False),
                            },
                        })
            elif isinstance(content, str):
                text_parts.append(content)
            m: dict = {"role": "assistant", "content": "".join(text_parts) or None}
            if tool_calls:
                m["tool_calls"] = tool_calls
            out.append(m)
    return out


async def _stream_model(
    client: httpx.AsyncClient, session: Session, model: str,
    messages: list[dict], tools: list[dict], user_id: int, ip: Optional[str],
    context_summary: str = "", permission: str = "readonly", locale: str = "",
) -> AsyncGenerator[dict, None]:
    """流式调一次上游模型，按模型绑定渠道的协议选择 anthropic / openai_chat 格式。

    两分支都 yield 统一的内部事件（content_delta / reasoning_delta / _result），
    并把结果归一化成 anthropic 格式的 content_blocks + stop_reason，故 run_agent_chat
    的循环逻辑对协议无感。计费在各分支流末按 usage 记账（与网关一致）。
    """
    protocol = GatewayService.resolve_protocol(session, model)
    base_url, api_key = GatewayService.resolve_upstream(session, model, protocol)
    url, headers = GatewayService.build_upstream(base_url, api_key, protocol)
    window = GatewayService.get_context_window(session, model)
    trimmed = _trim_messages(messages, window)

    if protocol == "openai_chat":
        gen = _stream_openai_chat(
            client, url, headers, model, trimmed, tools, user_id, ip, context_summary, permission, locale
        )
    else:
        gen = _stream_anthropic(
            client, url, headers, model, trimmed, tools, user_id, ip, context_summary, permission, locale
        )
    async for ev in gen:
        yield ev


async def _stream_anthropic(
    client: httpx.AsyncClient, url: str, headers: dict, model: str,
    trimmed: list[dict], tools: list[dict], user_id: int, ip: Optional[str],
    context_summary: str = "", permission: str = "readonly", locale: str = "",
) -> AsyncGenerator[dict, None]:
    """Anthropic Messages SSE 分支（带 tools）。归一化输出 anthropic content_blocks。"""
    payload = _call_model_payload(model, trimmed, tools, context_summary, permission, locale)
    payload["stream"] = True

    # 按 index 累积各 content block（text 累积 text，tool_use 累积 input json）
    blocks: dict[int, dict] = {}
    tool_json_buf: dict[int, str] = {}
    thinking_idx: set[int] = set()  # 标记为 thinking/redacted_thinking 的块（推理内容，不计入正文）
    stop_reason = None
    usage = {"input": 0, "output": 0, "cache": 0, "creation": 0}

    async with client.stream("POST", url, json=payload, headers=headers, timeout=120.0) as resp:
        resp.raise_for_status()
        cur_event = None
        async for raw in resp.aiter_lines():
            line = raw.strip()
            if line.startswith("event:"):
                cur_event = line[6:].strip()
                continue
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data:
                continue
            try:
                obj = json.loads(data)
            except Exception:
                continue

            etype = obj.get("type") or cur_event
            if etype == "message_start":
                # usage 取累计总值的 max：兼容「input 在 message_start」与「部分上游
                # input_tokens=0、真实值在 message_delta 才给」两种行为，且不会因多个
                # 事件而双计（Anthropic usage 是累计量，不是增量）。
                u = (obj.get("message") or {}).get("usage") or {}
                usage["input"] = max(usage["input"], u.get("input_tokens", 0) or 0)
                usage["cache"] = max(usage["cache"], u.get("cache_read_input_tokens", 0) or 0)
                usage["creation"] = max(
                    usage["creation"], u.get("cache_creation_input_tokens", 0) or 0
                )
            elif etype == "content_block_start":
                idx = obj.get("index", 0)
                blk = obj.get("content_block") or {}
                btype = blk.get("type")
                if btype == "tool_use":
                    blocks[idx] = {"type": "tool_use", "id": blk.get("id"),
                                   "name": blk.get("name"), "input": {}}
                    tool_json_buf[idx] = ""
                elif btype in ("thinking", "redacted_thinking"):
                    # 推理块：内容作为 reasoning 下发，不进 blocks（不混入正文/历史）
                    thinking_idx.add(idx)
                else:
                    blocks[idx] = {"type": "text", "text": ""}
            elif etype == "content_block_delta":
                idx = obj.get("index", 0)
                delta = obj.get("delta") or {}
                dtype = delta.get("type")
                if idx in thinking_idx:
                    # thinking_delta 用 thinking 字段；个别代理把推理放在 text_delta
                    rt = delta.get("thinking", "") if dtype == "thinking_delta" \
                        else (delta.get("text", "") if dtype == "text_delta" else "")
                    if rt:
                        yield {"type": "reasoning_delta", "text": rt}
                elif dtype == "text_delta":
                    t = delta.get("text", "")
                    if t:
                        blocks.setdefault(idx, {"type": "text", "text": ""})
                        blocks[idx]["text"] += t
                        yield {"type": "content_delta", "text": t}
                elif delta.get("type") == "input_json_delta":
                    tool_json_buf[idx] = tool_json_buf.get(idx, "") + delta.get("partial_json", "")
            elif etype == "content_block_stop":
                idx = obj.get("index", 0)
                if idx in tool_json_buf and idx in blocks:
                    raw_json = tool_json_buf[idx].strip()
                    try:
                        blocks[idx]["input"] = json.loads(raw_json) if raw_json else {}
                    except Exception:
                        blocks[idx]["input"] = {}
            elif etype == "message_delta":
                stop_reason = (obj.get("delta") or {}).get("stop_reason") or stop_reason
                # 该上游把最终准确 usage（含 input + cache）放在 message_delta，故这里
                # 一并兜底刷新；取 max 避免与 message_start 双计。
                u = obj.get("usage") or {}
                usage["output"] = max(usage["output"], u.get("output_tokens", 0) or 0)
                usage["input"] = max(usage["input"], u.get("input_tokens", 0) or 0)
                usage["cache"] = max(usage["cache"], u.get("cache_read_input_tokens", 0) or 0)
                usage["creation"] = max(
                    usage["creation"], u.get("cache_creation_input_tokens", 0) or 0
                )

    # 计费（prompt 含缓存命中，与 parse_usage 归一一致）
    GatewayService.record_and_charge(
        user_id, "ai_chat", model,
        usage["input"] + usage["cache"] + usage["creation"],
        usage["output"], usage["cache"], ip, success=True,
        cache_creation_tokens=usage["creation"],
    )

    content_blocks = [blocks[i] for i in sorted(blocks.keys())]
    yield {"type": "_result", "content_blocks": content_blocks, "stop_reason": stop_reason}


async def _stream_openai_chat(
    client: httpx.AsyncClient, url: str, headers: dict, model: str,
    trimmed: list[dict], tools: list[dict], user_id: int, ip: Optional[str],
    context_summary: str = "", permission: str = "readonly", locale: str = "",
) -> AsyncGenerator[dict, None]:
    """OpenAI Chat Completions SSE 分支。请求/工具/SSE 用 OpenAI 格式，
    结果归一化回 anthropic content_blocks + stop_reason（tool_calls→tool_use）。"""
    payload: dict = {
        "model": model,
        "max_tokens": _MAX_OUTPUT_TOKENS,
        "messages": _anthropic_messages_to_openai(
            _build_system_prompt(tools, context_summary, permission, locale), trimmed
        ),
        "stream": True,
        # OpenAI chat 流式默认末块不带 usage，须显式要求，否则 0 计费（同网关）。
        "stream_options": {"include_usage": True},
    }
    if tools:
        payload["tools"] = _anthropic_tools_to_openai(tools)

    text_acc = ""
    tc_buf: dict[int, dict] = {}   # tool_calls：index -> {id, name, args(str)}
    finish_reason = None
    usage_obj: dict = {}

    async with client.stream("POST", url, json=payload, headers=headers, timeout=120.0) as resp:
        resp.raise_for_status()
        async for raw in resp.aiter_lines():
            line = raw.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                obj = json.loads(data)
            except Exception:
                continue

            # include_usage 的末块 choices 为空、带 usage
            if obj.get("usage"):
                usage_obj = obj
            choices = obj.get("choices") or []
            if not choices:
                continue
            ch0 = choices[0]
            delta = ch0.get("delta") or {}

            rc = delta.get("reasoning_content")
            if rc:
                yield {"type": "reasoning_delta", "text": rc}
            content = delta.get("content")
            if content:
                text_acc += content
                yield {"type": "content_delta", "text": content}
            for tc in delta.get("tool_calls") or []:
                i = tc.get("index", 0)
                slot = tc_buf.setdefault(i, {"id": None, "name": None, "args": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["args"] += fn["arguments"]
            if ch0.get("finish_reason"):
                finish_reason = ch0["finish_reason"]

    # 计费：openai usage 里 prompt_tokens 已含缓存命中，parse_usage 已归一。
    pt, ct, cache, cache_creation = (
        GatewayService.parse_usage(usage_obj, "openai_chat")
        if usage_obj else (0, 0, 0, 0)
    )
    GatewayService.record_and_charge(
        user_id, "ai_chat", model, pt, ct, cache, ip, success=True,
        cache_creation_tokens=cache_creation,
    )

    # 归一化成 anthropic content_blocks：text 块 + tool_use 块
    content_blocks: list[dict] = []
    if text_acc:
        content_blocks.append({"type": "text", "text": text_acc})
    for i in sorted(tc_buf.keys()):
        slot = tc_buf[i]
        raw_args = (slot["args"] or "").strip()
        try:
            tinput = json.loads(raw_args) if raw_args else {}
        except Exception:
            tinput = {}
        content_blocks.append({
            "type": "tool_use", "id": slot["id"] or f"call_{i}",
            "name": slot["name"], "input": tinput,
        })
    stop_reason = "tool_use" if finish_reason == "tool_calls" else finish_reason
    yield {"type": "_result", "content_blocks": content_blocks, "stop_reason": stop_reason}


async def run_agent_chat(
    client: httpx.AsyncClient,
    user_id: int,
    user_message,  # str 或 Anthropic content 块数组（图文混合，含 image 块）
    history: Optional[list[dict]] = None,
    model: Optional[str] = None,
    ip: Optional[str] = None,
    enabled_tools: Optional[list[str]] = None,
    context: Optional[dict] = None,
    permission: Optional[str] = None,
    locale: Optional[str] = None,
) -> AsyncGenerator[dict, None]:
    """运行一轮对话的 agent loop，逐步 yield 过程事件。

    context：前端上送的上下文包（envelope v1，见前端 features/copilot/context.ts）。
    它只影响 system prompt 里多出的一段现场摘要，**不改变**工具、计费与事件协议。
    为 None（前端未上送）时行为与以前完全一致。

    permission：当前权限档位（readonly / params / hardware，2026-10-10 新增）。
    **服务端硬边界**：select_tools 按档过滤（只读档模型看不到写工具），未知档按
    只读处理。缺省 None 时等价只读——向后兼容旧调用方。

    locale：界面当前语言（`en` / `zh-CN`，2026-10-13 新增）。前端现场上下文恒为
    中文，仅靠「按提问语言猜」在短问句上会判错 → 把界面语言作为权威声明写进
    system prompt。缺省 None 时不加该声明，行为与老版一致。

    user_message 可为：
    - str：纯文本问题；
    - list：Anthropic content 块数组，如
        [{"type":"text","text":"这是什么芯片?"},
         {"type":"image","source":{"type":"base64","media_type":"image/png","data":"..."}}]
      用于图文混合输入（视觉模型）。
    """
    model = model or settings.agent_default_model
    # 按「前端开关 ∩ 权限档位」过滤工具（未显式启用一律视为关闭，见 select_tools）
    tools = agent_tools.select_tools(enabled_tools, permission)
    # 上下文包 → 现场摘要（为空表示前端没上送，模型退回通用回答）
    # locale 一并传入（2026-10-14）：英文界面下摘要里的固定标签（权限描述等）用英文，
    # 避免中文按钮名「可改参数」被模型原样搬进英文回答。
    context_summary = build_context_summary(context, locale or "")

    # 内容安全过滤·层 1 关键词（GB/T 45654）：命中即以正常助手回复形式拒答
    # （content_delta+done 经 AgentStreamManager 缓存下发，前端渲染并存为一条
    # 普通助手消息），不触达上游。层 2 消耗上游 tokens，放在余额校验之后。
    user_text = content_safety.extract_content_text(user_message)
    verdict = content_safety.screen_keywords(user_text)
    if verdict.blocked:
        content_safety.record_block(user_id, "ai_chat", model, verdict, ip, None, user_text)
        yield {"type": "content_delta", "text": settings.CONTENT_SAFETY_REFUSAL_TEXT}
        yield {"type": "done"}
        return

    # 余额校验
    with Session(engine) as s:
        if not CreditsService.has_balance(s, user_id):
            yield {"type": "error", "message": "Credits 不足，请升级或获取更多"}
            return
        if not GatewayService.is_model_allowed(s, model):
            yield {"type": "error", "message": f"模型不可用或未配置: {model}"}
            return

    # 内容安全过滤·层 2 大模型分类：语义级风险（意图型请求）
    verdict = await content_safety.screen_llm(client, user_text)
    if verdict.blocked:
        content_safety.record_block(user_id, "ai_chat", model, verdict, ip, None, user_text)
        yield {"type": "content_delta", "text": settings.CONTENT_SAFETY_REFUSAL_TEXT}
        yield {"type": "done"}
        return

    # 组装消息历史。压缩「历史对话」里的过期检索结果（它们已用于先前回答），
    # 但当前这个问题的 agent loop 全程不压缩——模型需要看到本问题已检索的内容
    # 才能判断是否够答、避免重复检索。
    messages: list[dict] = list(history or [])
    _compress_stale_tool_results(messages)
    # content 直接透传给上游（str 或 content 块数组，Anthropic 均接受）
    messages.append({"role": "user", "content": user_message})

    all_sources: list[dict] = []
    seen_src_keys: set = set()
    max_iter = settings.AGENT_CHAT_MAX_ITERATIONS

    # ── 轮内重复检索短路 + 无进展收口（2026-09-29）──
    # 用户实测：模型会对同一个查询连发多次一模一样的 KnowledgeSearch（同 query +
    # 同七个 datasets），每条约 8 秒，反复多次后才出答案。根因是循环里没有任何
    # 「同名同参已执行过就跳过」的判断。这里：
    #   · executed：本轮已执行过的 (工具名, 参数JSON 排序) 签名集合，命中即短路，
    #     不真发检索、回填一句「已跳过重复检索」，前端工具卡照常显示并标注。
    #   · no_progress：连续「重复短路」或「本轮未新增来源」的计数，达到阈值即把
    #     iter_tools 置空，强制模型基于已得内容作答，杜绝空转。
    executed: set[tuple[str, str]] = set()
    no_progress = 0
    no_progress_limit = max(1, settings.AGENT_CHAT_NO_PROGRESS_LIMIT)
    force_finish = False

    for iteration in range(1, max_iter + 1):
        # 最后一轮禁用工具：强制模型基于已检索到的内容作答，避免触达迭代上限时
        # 只回一句占位文案、前面所有检索白白浪费。传空 tools 后模型无法再发起
        # tool_use，stop_reason 自然变为 end_turn，由下方常规终止分支收尾。
        # 无进展收口也会提前触发：force_finish 置位后本轮起禁用工具。
        iter_tools = tools if (iteration < max_iter and not force_finish) else []

        # 流式调模型：转发 content_delta，收集 _result（content 块 + stop_reason）
        content_blocks = []
        stop_reason = None
        try:
            with Session(engine) as s:
                async for ev in _stream_model(
                    client, s, model, messages, iter_tools, user_id, ip, context_summary, permission, locale
                ):
                    if ev.get("type") in ("content_delta", "reasoning_delta"):
                        yield ev  # 透传文本/推理增量给前端打字机
                    elif ev.get("type") == "_result":
                        content_blocks = ev.get("content_blocks") or []
                        stop_reason = ev.get("stop_reason")
        except httpx.HTTPStatusError as e:
            yield {"type": "error", "message": f"模型服务错误: {e.response.status_code}"}
            return
        except Exception as e:
            logger.error(f"agent loop model call failed: {e}")
            yield {"type": "error", "message": f"模型调用失败: {e}"}
            return

        # 把本轮 assistant 消息（含 text + tool_use）加入历史
        messages.append({"role": "assistant", "content": content_blocks})

        # 提取 tool_use
        tool_uses = [b for b in content_blocks if b.get("type") == "tool_use"]

        if stop_reason != "tool_use" or not tool_uses:
            # 终止：文本已通过 content_delta 流式发出，这里只补 sources + done
            if all_sources:
                yield {"type": "sources", "sources": all_sources}
            yield {"type": "done"}
            return

        # 执行所有 tool_use（顺序执行；每个产出过程事件）。
        # 注意：一条 assistant 消息里的所有 tool_use，其 tool_result 必须收集到
        # 紧接的「同一条」user 消息里（Anthropic 规范），否则上游 400。
        allowed_names = {t.get("name") for t in iter_tools}
        tool_result_blocks = []
        for tu in tool_uses:
            tu_id = tu.get("id")
            name = tu.get("name")
            tinput = tu.get("input") or {}

            if name not in allowed_names:
                # 防御性拦截：无论上游模型是否严格遵守已声明的 tools schema，
                # 已被用户关闭的工具在这里一律不真正执行，也不下发过程事件给前端。
                tool_result_blocks.append({
                    "type": "tool_result", "tool_use_id": tu_id,
                    "content": f"{name} 当前不可用（用户已关闭），不要再尝试调用。",
                })
                continue

            # ── 前端执行类工具：挂起等前端回执，结果由前端带回（2026-10-10）──
            #
            # 这些工具不在这里本地执行（数据在前端 store 里）：下发 tool_call →
            # 挂起等待 /api/agent/confirm 回执 → 用前端真实执行结果作为 tool_result
            # 回填，再继续下一轮模型调用。超时/取消/断开一律如实回填「未执行」。
            #
            # ⚠️ 2026-10-14 分两类（通用字段工具引入）：
            #   · 变更类（WriteField / WriteReportHeader）：mutating=true，前端弹确认卡，
            #     人点确认后才执行（红线纪律：写操作必经确认）；
            #   · 读取类（ReadField）：mutating=false，**无副作用、无需确认**，
            #     前端看到「已注册执行器且非 mutating」会立即执行并直接回执。
            # 两条路径共用同一套挂起-回填机制，协议零新增。
            if name in agent_tools.FRONTEND_EXECUTED_TOOLS:
                from app.services import agent_confirm_bus

                is_mutating = name in agent_tools.MUTATING_FRONTEND_TOOLS
                yield {
                    "type": "tool_call", "id": tu_id, "name": name,
                    "input": tinput, "mutating": is_mutating,
                }
                fut = agent_confirm_bus.register(tu_id, user_id)
                try:
                    payload = await asyncio.wait_for(
                        fut, timeout=settings.AGENT_CONFIRM_TIMEOUT_SECONDS
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"agent frontend tool {name} confirm timeout: {tu_id}")
                    payload = {"approved": False, "reason": "timeout"}
                except asyncio.CancelledError:
                    agent_confirm_bus.unregister(tu_id)
                    raise
                finally:
                    agent_confirm_bus.unregister(tu_id)

                approved = bool(payload.get("approved"))
                result_data = payload.get("result") or {}
                if approved and result_data.get("ok"):
                    ok_summary = result_data.get("summary") or f"{name} 已执行"
                    yield {
                        "type": "tool_result", "id": tu_id, "name": name,
                        "status": "ok", "summary": {"ok": True, "detail": ok_summary},
                    }
                    content = f"[已执行并确认] {ok_summary}"
                elif approved:
                    # 放行了，但前端执行失败/落库失败——如实转述，别谎报成功
                    fail_summary = result_data.get("summary") or f"{name} 执行失败"
                    yield {
                        "type": "tool_result", "id": tu_id, "name": name,
                        "status": "error", "summary": {"ok": False, "detail": fail_summary},
                    }
                    content = f"[执行失败] {fail_summary}。请如实告知用户未成功，勿谎称完成。"
                else:
                    reason = payload.get("reason") or "cancelled"
                    if reason == "timeout":
                        content = f"[未执行] 等待人工确认超时，{name} 未执行。请如实告知用户未写入。"
                    else:
                        content = f"[未执行] 操作员取消了 {name}，未做任何写入。请如实告知用户。"
                    yield {
                        "type": "tool_result", "id": tu_id, "name": name,
                        "status": "cancelled", "summary": {"ok": False, "detail": content},
                    }
                tool_result_blocks.append({
                    "type": "tool_result", "tool_use_id": tu_id, "content": content,
                })
                continue

            # ── 重复检索短路 ──
            # 同一轮内「同名 + 同参」的调用不再真发检索（省 8 秒 + 省 token），
            # 直接回填占位结果，让模型拿到「你已经搜过了、请基于上一条结果作答」。
            # 参数 JSON 按 sort_keys 归一，避免字段顺序不同导致误判为「不同调用」。
            sig = (name, json.dumps(tinput, sort_keys=True, ensure_ascii=False, default=str))
            if sig in executed:
                no_progress += 1
                logger.info(
                    f"agent loop short-circuit duplicate tool: {name} (session progress {no_progress})"
                )
                yield {"type": "tool_call", "id": tu_id, "name": name, "input": tinput}
                yield {
                    "type": "tool_result",
                    "id": tu_id,
                    "name": name,
                    "summary": {"count": 0, "sources": [], "skipped": True},
                }
                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tu_id,
                    "content": (
                        f"[已跳过重复检索] 工具 {name} 以相同参数执行过，结果见上一条；"
                        "请直接基于已有检索结果作答，不要再重复调用。"
                    ),
                })
                continue
            executed.add(sig)

            yield {"type": "tool_call", "id": tu_id, "name": name, "input": tinput}
            yield {"type": "tool_executing", "id": tu_id, "name": name}

            text, sources = await agent_tools.run_tool(client, name, tinput)

            # 累计去重来源；本轮是否产生了「新」来源（用于无进展判定）
            new_sources = 0
            for src in sources:
                key = (src.get("source"), src.get("url"), src.get("title"))
                if key not in seen_src_keys:
                    seen_src_keys.add(key)
                    all_sources.append(src)
                    new_sources += 1

            if new_sources == 0:
                no_progress += 1
            else:
                no_progress = 0

            yield {
                "type": "tool_result", "id": tu_id, "name": name,
                "summary": {"count": len(sources), "sources": sources[:5]},
            }

            tool_result_blocks.append({
                "type": "tool_result", "tool_use_id": tu_id, "content": text,
            })

        # 无进展收口：连续重复/零新增来源达到阈值，下一轮起禁用工具，强制模型收口作答
        if no_progress >= no_progress_limit:
            force_finish = True
            logger.info(f"agent loop force-finish: no progress reached {no_progress}")

        # 一条 user 消息承载本轮所有 tool_result
        messages.append({"role": "user", "content": tool_result_blocks})
