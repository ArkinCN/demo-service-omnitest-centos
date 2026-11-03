"""把前端上送的上下文包（envelope v1）压成一段给模型看的短摘要。

为什么要有这个模块，为什么不直接把整个 envelope 塞进 system prompt：
    上下文包有九个段，其中 zoneB.values / control_params 这类字段能把场景包的
    七十余项控制参数整包带进来。整包塞进去有三个坏处：
      ① 每轮多耗数千 token，且绝大多数与用户问的那句话无关；
      ② 模型被一堆同名参数淹没，反而抓不住「现在在测什么产品、在哪一步」；
      ③ 上下文窗口有限，挤掉的是真正有用的历史对话。
    所以这里**只挑模型答这一句用得上的那几项**，压成十来行。

两条纪律（与前端 context.ts 同源）：
    一、只写真取得到的东西。取不到的字段**不写**，而不是写「未知」——
        模型看到「未知」会自己去猜，看到缺项反而会问人。
    二、**不替模型下结论**。这里只陈述现场状态（产品名、流程、选中项、
        未采到的量），判定结果与建议一律由模型基于检索作答。

「换任务上下文跟着变」这条验收靠的就是这份摘要里的 product / flow / zoneB
三块：换场景包或换流程，这三块跟着变，模型的回答自然跟着变。
"""
from __future__ import annotations

from typing import Any

# 流程 id → 中文名。与前端 `c/web/src/features/data/flows.ts` 的 FLOWS 一一对应，
# 五流程是固定契约（主文档 3.2），写死在此供摘要翻译——直接输出 init/req 这类
# 英文 id 会被模型照抄进回答（用户截图反馈：`已确认的流程：[init [已勾选]]`）。
FLOW_CN: dict[str, str] = {
    "init": "初始化配置",
    "req": "测试需求确认",
    "run": "启动测试及结果分析",
    "tune": "调优确认及运行",
    "report": "测试报告及产出",
}

# 英文版流程名（2026-10-14）。与前端 catalog.ts 的英文文案保持一致，
# 否则英文界面下摘要里出现中文流程名，模型会原样搬进英文回答。
FLOW_EN: dict[str, str] = {
    "init": "Initial setup",
    "req": "Confirm test requirements",
    "run": "Run tests and analyze results",
    "tune": "Confirm and run tuning",
    "report": "Test report and artifacts",
}


def _get(d: Any, *path: str) -> Any:
    """按路径安全取值，取不到返回 None（不抛）。"""
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


# 权限档位 → 给模型看的中文能力描述。
#
# 关键：**明写作用域与边界**。只写「readonly」这种英文词，模型会把它当解释素材
# 到处引用（实测会拿它解释「为什么我改不动」，把无关字段当理由）；写清「能做什么、
# 不能做什么」才能让模型在只读档明确拒写、在可改参数档正常调用写工具。
PERMISSION_CN: dict[str, str] = {
    "readonly": (
        "只读。你可以检索资料与回答问题，但**不能**执行任何写操作"
        "（填写报告字段、修改参数、控制硬件）。用户要求写操作时，"
        "如实说明当前是只读档、请其先在下方权限处切到「可改参数」，不要假装已执行。"
    ),
    "params": (
        "可改参数。除检索外，你**可以**调用写类工具修改报告表头字段等数据；"
        "写操作会先弹人工确认卡，操作员点了「确认执行」才算数——"
        "确认前不得声称已写好，被取消或失败要如实转述。"
        "控制硬件（下发硬件指令）仍不在本档范围内。"
    ),
    "hardware": (
        "可控硬件。除检索与写数据外，你还可以就硬件控制类指令与操作员协作；"
        "所有写/控操作同样先经人工确认卡。"
    ),
}

# 英文版（2026-10-14）：英文界面下若仍输出中文权限描述，模型会把其中的中文按钮名
# （「可改参数」）原样搬进英文回答（用户实测反馈）。此处给出等义英文描述，
# 按钮名与前端 i18n 的英文文案保持一致（Parameter editing / Hardware control）。
PERMISSION_EN: dict[str, str] = {
    "readonly": (
        "Read-only. You can search materials and answer questions, but you **cannot** "
        "perform any write operation (filling report fields, changing parameters, "
        "controlling hardware). When the user asks for a write, state plainly that the "
        "current level is read-only and ask them to switch to \u201cParameter editing\u201d "
        "at the permission selector below; do not pretend it was executed."
    ),
    "params": (
        "Parameter editing. Besides searching, you **may** call write tools to modify "
        "report header fields and similar data; write operations first raise a manual "
        "confirmation card, and only count once the operator clicks \u201cConfirm\u201d. "
        "Do not claim success before confirmation; report cancellations or failures "
        "faithfully. Hardware control (issuing hardware commands) is still out of scope."
    ),
    "hardware": (
        "Hardware control. Besides searching and writing data, you may collaborate with "
        "the operator on hardware control commands; all write/control operations also go "
        "through the manual confirmation card first."
    ),
}


def _permission_line(permission: Any, locale: str = "") -> str:
    """把档位英文值翻成能力描述行。未知值按只读口径描述（安全默认）。

    locale：界面语言。`en` 时用英文描述（避免中文按钮名渗进英文回答），
    其余（含缺省空串）用中文 —— 与改动前行为完全一致。
    """
    key = str(permission or "readonly").strip().lower()
    if locale == "en":
        desc = PERMISSION_EN.get(key) or PERMISSION_EN["readonly"]
        return f"Current permission level: {desc}"
    desc = PERMISSION_CN.get(key)
    if desc is None:
        desc = PERMISSION_CN["readonly"]
    return f"当前权限档位：{desc}"


# ---------------------------------------------------------------------------
# 摘要的「骨架标签」双语表（2026-10-14 补完）
#
# 为什么必须做：本文件此前只有权限描述做了英文，其余标签全是硬编码中文。
# 英文界面下模型拿到的摘要长这样：
#     【当前现场上下文…】被测产品：…  当前流程：…  源材料没给、**至今仍没填**的…
# 后果有二（用户实测截图反馈）：
#   ① 模型会把这些**中文标签**原样搬进英文回答（如 `Switch to "切换闭环转速"`）；
#   ② 标签是中文、值是英文，半中半英，看着像翻译没做完。
# 处置：所有固定标签一律走 `_T(zh, en, locale)`，中文口径逐字保持原样（零破坏）。
# ---------------------------------------------------------------------------
def _T(zh: str, en: str, locale: str = "") -> str:
    """按界面语言取标签。`locale == "en"` 取英文，其余（含缺省空串）取中文。

    缺省空串 = 改动前行为（全中文），保证旧调用方与既有测试零破坏。
    """
    return en if locale == "en" else zh


def _fmt_list(v: Any, limit: int = 12, locale: str = "") -> str:
    """列表转「a、b、c」；超长截断并写明还有几条，不让摘要无限膨胀。"""
    if not isinstance(v, list):
        return ""
    items = [str(x) for x in v if x is not None and x != ""]
    if not items:
        return ""
    shown = items[:limit]
    tail = (
        _T(f" 等 {len(items)} 项", f" … and {len(items) - limit} more", locale)
        if len(items) > limit
        else ""
    )
    return ("、" if locale != "en" else ", ").join(shown) + tail


def _fmt_fields(v: Any, limit: int = 12, locale: str = "") -> str:
    """字段列表转中文摘要：`{key, name, source}` → 「额定转速(rated_speed)｜出处：数据手册·第3节」。

    三层信息各有用处，缺一不可：

    1. **中文名**——此前这里直接把 `a.key` 塞进来（rated_speed 这种），
       模型照着念，回答里全是用户看不懂的英文键名（用户反馈过）。
       中文名是界面左栏用的那一套，与菜单对齐。
    2. **英文键括在后面**——模型用宏名检索知识库更容易命中，不能丢。
    3. **出处**（2026-09-28 用户要求）——用户要求回答里每个字段带出处
       （格式如「机械外形：风扇厚度」）。模型只能复述我们给的上下文，
       **上下文里没有出处，它就写不出出处**（只能省略或含糊），
       所以这里必须把前端送来的 `source` 一并附上。
       没有 source 的（老前端只传 key/name）就不写这一段，不编造。

    另：前端 2026-10-05 起对**有值的**字段会多带一个 `value`（当前实际值）。
    有值就写成「中文名(键)=值」，让模型能直接说出「额定转速已填 18100」，
    而不是只念字段名、让人再去左栏找。**没值就不写等号**，不编一个空值。

    兼容旧的纯字符串元素（老前端可能还在传 key 数组），字符串按原名输出。
    """
    if not isinstance(v, list):
        return ""
    out: list[str] = []
    for x in v:
        if isinstance(x, dict):
            name = str(x.get("name") or "").strip()
            key = str(x.get("key") or "").strip()
            src = str(x.get("source") or "").strip()
            label = f"{name}({key})" if name and key and name != key else (name or key)
            # value 只在真取到时写（0 是合法值，用 is not None 判）
            val = x.get("value")
            if label and val is not None and val != "":
                label = f"{label}={val}"
            if label and src:
                # 2026-10-14：前端已按界面语言翻译 source（英文界面下是英文路径），
                # 此处若仍写死中文「出处：」会与英文值混搭。改用语言无关的箭头形式，
                # 模型据 system prompt 的语言规则自然输出对应语言。
                label = f"{label}｜{src}"
            if label:
                out.append(label)
        elif x is not None and x != "":
            out.append(str(x))
    if not out:
        return ""
    shown = out[:limit]
    tail = (
        _T(f" 等 {len(out)} 项", f" … and {len(out) - limit} more", locale)
        if len(out) > limit
        else ""
    )
    return ("、" if locale != "en" else ", ").join(shown) + tail


def build_context_summary(env: dict | None, locale: str = "") -> str:
    """上下文包 → 一段给模型的现场摘要。envelope 为空（前端未上送）时返回空串。

    返回空串是正常态不是错误：调用方据此「不加这段」，模型退回通用回答。

    locale（2026-10-14 新增）：界面语言。`en` 时摘要里的**固定标签**（权限描述等）
    用英文，避免中文按钮名（如「可改参数」）被模型原样搬进英文回答。
    缺省空串时行为与改动前完全一致（全中文标签）。
    """
    if not isinstance(env, dict) or not env:
        return ""

    lines: list[str] = [_T("【当前现场上下文（由页面实时给出，据此作答）】",
                           "[Live site context (provided by the page in real time; answer based on it)]",
                           locale)]

    # ① 测的是什么产品
    # 只写「产品名（一级 / 二级）」：taxonomy_path 的第三段通常就是产品名本身，
    # 照抄会变成「FU6832 散热风扇驱动板 / … / FU6832 散热风扇驱动板」，
    # 同一个名字出现两次，白占 token 也干扰模型。
    product_name = _get(env, "product", "product_name")
    taxonomy_path = _get(env, "product", "taxonomy_path")
    if product_name:
        uppers = [str(x) for x in (taxonomy_path or [])[:2] if x]
        suffix = f"（{' / '.join(uppers)}）" if uppers else ""
        lines.append(f"{_T('被测产品：', 'Product under test: ', locale)}{product_name}{suffix}")

    # ② 现在在哪一步
    flow_id = _get(env, "flow", "id")
    flow_label = _get(env, "flow", "label")
    if flow_id or flow_label:
        # ⚠️ 英文界面下**优先用 FLOW_EN**，不能先用 flow_label：
        # flow.label 是前端上送的中文名（「初始化配置」），先取它就会把中文留在英文摘要里
        # （实测踩到：`Current step: 初始化配置（init）`）。中文口径仍以 flow_label 优先。
        table = FLOW_EN if locale == "en" else FLOW_CN
        named = table.get(str(flow_id), "")
        if locale == "en":
            shown = named or flow_label or flow_id
        else:
            shown = flow_label or named or flow_id
        tail = f"（{flow_id}）" if flow_id and named and named != flow_id else ""
        lines.append(f"{_T('当前流程：', 'Current step: ', locale)}{shown}{tail}")
    confirmed = _get(env, "flow", "confirmed")
    if isinstance(confirmed, dict) and confirmed:
        # 流程 id 一律翻成界面语言的名字（init/req 会被模型照抄进回答，用户看不懂）
        table = FLOW_EN if locale == "en" else FLOW_CN
        done = [table.get(str(k), str(k)) for k, v in confirmed.items() if v]
        if done:
            lines.append(
                f"{_T('已确认的流程：', 'Confirmed steps: ', locale)}{_fmt_list(done, locale=locale)}"
            )

    # ③ 人改过哪些值（只送 diff，不送全量——这是前端那边的纪律，这里照单陈述）
    #
    # ⚠️ 键必须翻成中文名：zoneB.values 的键形如 `run.cp.调速.ramp_time`，
    # 旧实现 `k.split('.')[-1]` 输出英文键（ramp_time），模型照抄进回答——
    # 用户看到的是「控机板参数表里一排英文」，看不懂（2026-10-04 反馈）。
    # envelope 的 zoneB.control_params 带 {key, name(中文名), unit}，据此反查；
    # 查不到中文名的键保留英文键（不编）。
    values = _get(env, "zoneB", "values")
    if isinstance(values, dict) and values:
        ctrl = _get(env, "zoneB", "control_params")
        name_by_key: dict[str, str] = {}
        if isinstance(ctrl, list):
            for c in ctrl:
                if isinstance(c, dict) and c.get("key") and c.get("name"):
                    name_by_key[str(c["key"])] = str(c["name"])
        pairs: list[str] = []
        for k, v in values.items():
            leaf = k.split(".")[-1]
            cn = name_by_key.get(leaf, "")
            label = f"{cn}({leaf})" if cn and cn != leaf else leaf
            pairs.append(f"{label}={v}")
        lines.append(
            f"{_T('人已改过的参数：', 'Parameters edited by the operator: ', locale)}"
            f"{_fmt_list(pairs, locale=locale)}"
        )

    # ④ 选中项：这些是「人正在看什么」，决定模型该答哪一条
    sel_doc = _get(env, "zoneB", "selected_document")
    if sel_doc:
        lines.append(f"{_T('知识库中选中的文档：', 'Document selected in the knowledge base: ', locale)}{sel_doc}")
    sel_fail = _get(env, "zoneB", "selected_fail_item")
    if sel_fail:
        lines.append(f"{_T('选中的未达标判据：', 'Selected failing criterion: ', locale)}{sel_fail}")
    sel_cand = _get(env, "zoneB", "selected_candidate")
    if isinstance(sel_cand, dict):
        # 候选改动用 items 的中文名（{key,name,from,to}），不用 keys——
        # keys 是英文参数键，模型会照抄（同 ③ 的教训）。
        cand_label = _T("已勾选的候选改动：", "Selected candidate changes: ", locale)
        cand_items = sel_cand.get("items")
        if isinstance(cand_items, list) and cand_items:
            lines.append(f"{cand_label}{_fmt_fields(cand_items, locale=locale)}")
        elif sel_cand.get("keys"):
            lines.append(f"{cand_label}{_fmt_list(sel_cand.get('keys'), locale=locale)}")

    # ⑤ 空的/占位的/缺的量：让模型知道哪些问了也答不了，从而改问人。
    # 用 _fmt_fields 输出「中文名(英文键)」——**别直接输出 key**，
    # 模型会把 rated_speed 这类键名原样写进回答，用户看不懂（已反馈）。
    #
    # ⚠️⚠️ 跨页数据隔离（2026-10-04 用户明确口径）：三段都来自**流程 1
    # （初始化配置）的现场数据**——前端 context.ts 的 leaves（本体属性 + 控制参数
    # + 报告表头）。此前任何流程的摘要都带这两段，用户在流程 5 问报告相关问题时，
    # 助手会答出「预定位强度」等第一阶段参数（用户截图反馈：跨页信息混淆）。
    # 口径：**数据可流通，但回答只关联当前页面**——三段只在 init 流程输出；
    # 其它流程各自的问题不涉及它们，缺了也不影响作答。
    #
    # ⚠️⚠️ 口径重构（2026-10-05 用户实测「助手不按真实情况回答」）：
    # 旧实现是两段——「当前取不到值的字段」+「仍是占位值、待现场确认的字段」。
    # 两个问题同时存在：
    #   ① 第二段把「人已经填过的占位项」也列进去了（前端那时只判源材料的
    #      _placeholder、没扣掉人工填的值），助手于是答「这些还缺」——
    #      用户看着左栏明明有值，读起来就是「我填了你还说缺」；
    #   ② 两段都只看本体属性，数字与左栏菜单口径对不上。
    # 现在前端已按左栏同口径拆成三段，这里**如实照搬三段**，并且措辞必须让模型
    # 分清「已填」与「没填」——**绝不能把 placeholders_filled 说成缺失**。
    if str(flow_id or "") == "init":
        missing = _get(env, "zoneB", "missing")
        if missing:
            lines.append(
                _T(
                    "当前取不到有效值的字段（源材料没给、人也没填）：",
                    "Fields with no valid value (not provided by source material and not filled by the operator): ",
                    locale,
                )
                + _fmt_fields(missing, locale=locale)
            )
        pending = _get(env, "zoneB", "placeholders_pending")
        # 兼容老前端：没有 pending 键时退回 placeholders（旧包只有这一份、语义等同）
        if not pending:
            pending = _get(env, "zoneB", "placeholders")
        if pending:
            lines.append(
                _T(
                    f"源材料没给、**至今仍没填**的待现场确认项（{len(pending)} 项）：",
                    f"Items pending on-site confirmation that source material did not provide and are **still unfilled** ({len(pending)} item(s)): ",
                    locale,
                )
                + _fmt_fields(pending, locale=locale)
            )
        filled = _get(env, "zoneB", "placeholders_filled")
        if filled:
            # 这一段是「已经有着落」的项，措辞必须与上面两段明确区分：
            # 说成「待确认」会让模型把它列进缺失清单（用户实测反馈过）。
            lines.append(
                _T(
                    f"源材料没给、但**人已经填好值**的项（{len(filled)} 项，不要列为缺失）：",
                    f"Items source material did not provide but the **operator has filled in** ({len(filled)} item(s); do NOT list them as missing): ",
                    locale,
                )
                + _fmt_fields(filled, locale=locale)
            )

    # ⑤' 报告表头未填项：**流程 5 的本页数据**（envelope 的
    # zoneB.report_header_missing，由前端用 store.reportHeader 对比
    # pack.report.header_fields 算出）。流程 5 助手的开场白是
    # 「按模板填一遍，哪些字段还没填上」——隔离掉流程 1 字段后，
    # 它对本页问题仍要有据可答；全填时此段不出现，助手会如实答「已全部填写」。
    #
    # ⚠️⚠️⚠️ 2026-10-05 用户实测「阶段五助手边界不明、引用错误的阶段一数据」：
    # 数据层其实**已经隔离干净**（上面 init 三段只在 init 输出、report 只出表头缺项），
    # 但模型仍然答出了流程 1 的本体属性占位清单——**问题是「边界」没写死**：
    #   · `_CITE_RULE ④` 的示例字段（风扇厚度）与措辞（占位值/待现场确认）**都是流程 1 的**，
    #     等于给了模型一个可以直接套用的跨界模板；
    #   · 摘要里只说了「本页有什么」，**从没说过「本页不许答什么」**，模型于是自由发挥。
    # 所以这里补**正向白名单 + 反向禁令**两段（用户原话「注入正向白名单」），
    # 把边界写死在本页数据旁边——模型没有「哪些不能提」的显式清单时，光靠
    # 「只围绕当前页面」这类泛约束是拦不住的（实测两次都栽在这）。
    if str(flow_id or "") == "report":
        lines.append(
            _T(
                "本页（测试报告及产出）只回答：报告模板与它的分节、报告表头的字段"
                "（含取值位、由哪条流程写入、是否已填）、上游带入情况、判定汇总与产物留档、"
                "结论草稿、以及导出前检查。",
                "This page (Test report and artifacts) answers ONLY about: the report template and its sections, "
                "report header fields (including value slots, which step writes them, whether filled), upstream carry-in, "
                "verdict summary and artifact archiving, conclusion drafts, and pre-export checks.",
                locale,
            )
        )
        lines.append(
            _T(
                "本页**不得出现**：被测对象的本体属性（如额定转速、额定母线电压、整机额定相电流、"
                "风扇外形尺寸、风扇厚度）与控制参数（如斜坡时间、整定使能），"
                "以及它们在左栏菜单里的出处路径——那些属于「初始化配置」流程，与本页无关。"
                "若用户问的正是这些，如实说明「这些属于初始化配置流程，本页只处理报告表头与产出」，"
                "不要把它们列成表或清单。",
                "This page **must NOT** mention: intrinsic properties of the device under test (e.g. rated rotational speed, "
                "rated bus voltage, rated phase current, fan outer size, fan thickness) or control parameters "
                "(e.g. ramp time, tuning enable), nor their source paths in the left menu — those belong to the "
                "\u201cInitial setup\u201d step and are irrelevant here. If the user asks exactly about them, state plainly that "
                "\u201cthey belong to the Initial setup step; this page only handles report header fields and artifacts\u201d, "
                "and do not list them as a table or list.",
                locale,
            )
        )
        rhm = _get(env, "zoneB", "report_header_missing")
        if rhm:
            lines.append(
                _T("报告表头还没有填的项（本页数据）：", "Unfilled report header fields (this page's data): ", locale)
                + _fmt_fields(rhm, locale=locale)
            )

    # ⑥ 上一轮跑到哪、哪些量没采到
    #
    # ⚠️ failed_items 是对象数组（BackendVerdict：{req_id,name,state,...}），
    # 旧实现直接 _fmt_list → 对 dict 逐个 str()，模型收到的是一串 Python dict
    # 原文。这里取它的 name（中文判据名，前端 verdict 表自带）。
    # missing_measures 前端已输出「中文名(英文键)」（loadLatestRun 的 legend），
    # 直接列出即可。
    last = _get(env, "lastRun")
    if isinstance(last, dict) and last:
        run_id = last.get("run_id")
        if run_id:
            lines.append(f"{_T('最近一轮：', 'Latest run: ', locale)}{run_id}")
        miss = last.get("missing_measures")
        if miss:
            lines.append(
                _T("最近一轮未采集到的实测量：", "Measures not acquired in the latest run: ", locale)
                + _fmt_list(miss, locale=locale)
                + _T("（未采集不等于不合格）", " (not acquired does not mean failed)", locale)
            )
        failed = last.get("failed_items")
        if isinstance(failed, list) and failed:
            names = [
                str(v.get("name") or v.get("req_id") or "")
                for v in failed
                if isinstance(v, dict)
            ]
            flabel = _T("最近一轮判为不通过的项：", "Criteria judged as failing in the latest run: ", locale)
            if names:
                lines.append(flabel + _fmt_list(names, locale=locale))
            else:
                lines.append(flabel + _fmt_list(failed, locale=locale))

    # ⑦ 权限档位：服务端另有拦截（工具集按档过滤），这里只让模型知道它能做到哪一步。
    #
    # ⚠️ 2026-10-10 修复：此前 envelope.policy.permission 是前端**写死的常量
    # readonly**，与 UI 选择无联动 → 模型永远自述只读、拒绝一切写指令。
    # 现在前端改为动态读当前档位，这里把英文档位名翻成中文能力描述：
    # 用中文名 + 明写作用域，避免模型把「readonly」误解成「我什么都改不了」
    # （故此前实测教训：模型会把无关字段当解释素材）。
    permission = _get(env, "policy", "permission")
    if permission:
        lines.append(_permission_line(permission, locale))

    if len(lines) == 1:
        return ""  # 一个字段都没取到，不如不给
    if locale == "en":
        # 英文界面下摘要标签已是英文，但**字段名可能仍是中文**（来自场景包原文），
        # 所以仍要要求模型按提问语言作答，而不是照抄字段名。
        lines.append(
            "Treat the above as authoritative; do not invent anything not written here. "
            "\u26a0\ufe0f Some field names above may still be in Chinese (they come from the scenario package). "
            "**Answer in the same language as the user's question**: translate Chinese field names and source paths "
            "into English when the user asks in English, and keep them as-is when the user asks in Chinese."
        )
    else:
        lines.append(
            "回答时以这些为准；上下文里没写的，不要自己补。"
            "⚠️ 上面的字段名与出处路径是中文原文，**表达语言服从用户的提问语言**："
            "用户用英文提问就把这些中文译成英文，用中文提问就原样保留。"
        )
    return "\n".join(lines)
