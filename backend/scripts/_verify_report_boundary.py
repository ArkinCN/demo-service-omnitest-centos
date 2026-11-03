"""验证：流程 5（测试报告及产出）页的助手边界是否写死（2026-10-05 用户实测）。

背景（用户原话：「阶段一的ai助手正常，阶段五的AI助手边界不明而且还引用错误的
阶段一数据并违规展示」）：
    数据层其实已经隔离干净（init 三段只在 init 输出、report 只出表头缺项），
    但模型仍然答出了流程 1 的本体属性占位清单。原因是**边界没写死**：
      · `_CITE_RULE ④` 的示例字段（风扇厚度）与措辞（占位值/待现场确认）都是流程 1 的；
      · 摘要里只说了「本页有什么」，从没说过「本页不许答什么」。

本脚本用**对抗性输入**验证：即使 envelope 里被塞满流程 1 的数据
（missing / placeholders_pending / placeholders_filled 三段 + 全量 control_params），
流程 5 的摘要与 system prompt 也必须：
    ① 出现「本页只回答 / 本页不得出现」的正向白名单与反向禁令；
    ② 不出现任何流程 1 的本体属性名与控制参数名；
    ③ 保留本页数据锚点（报告表头未填项）；
    ④ system prompt 两个分支（有工具 / 无工具）都带上这些约束；
    ⑤ `_CITE_RULE` 不再给出指向单一流程的示例（风扇厚度那类）。

纪律：`check()` 必须 return cond（不返回会让统计造假，项目历史教训）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.agent_context import build_context_summary  # noqa: E402
from app.services.agent_chat_service import _build_system_prompt  # noqa: E402

# 流程 1 的字段名（本体属性 + 控制参数）——本页**一个都不许出现**
INIT_FIELD_NAMES = [
    "额定转速",
    "额定母线电压",
    "整机额定相电流",
    "风扇外形尺寸",
    "风扇厚度",
    "斜坡时间",
    "整定使能",
]
# 流程 1 的出处路径片段——同样不许出现
INIT_SOURCE_FRAGMENTS = [
    "被测对象 → 额定工况",
    "被测对象 → 机械外形",
]


def check(name: str, cond: bool, detail: str = "") -> bool:
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  {detail}" if detail else ""))
    return cond


def main() -> int:
    results = []

    # ── 对抗性 envelope：故意把流程 1 的三段与全量控制参数都塞进来 ──
    # 正常情况下前端已按 flow 裁剪（这三段在 report 流程是空数组），
    # 但这里**故意违反**，验证摘要侧能不能兜住——双层防线，任何一层失效都不该漏。
    adversarial_env = {
        "product": {"product_name": "FU6832 散热风扇驱动板", "taxonomy_path": ["电机", "散热风扇", "FU6832 散热风扇驱动板"]},
        "flow": {"id": "report", "label": "测试报告及产出", "confirmed": {"init": True, "req": True}},
        "zoneB": {
            # ↓↓↓ 这三段是流程 1 的，正常不该出现在 report（故意塞入做对抗测试）
            "missing": [
                {"key": "fan_outer_size", "name": "风扇外形尺寸", "source": "被测对象 → 机械外形 → 风扇外形尺寸"},
            ],
            "placeholders_pending": [
                {"key": "fan_thickness", "name": "风扇厚度", "source": "被测对象 → 机械外形 → 风扇厚度"},
            ],
            "placeholders_filled": [
                {"key": "rated_speed", "name": "额定转速", "value": 18100, "source": "被测对象 → 额定工况 → 额定转速"},
                {"key": "rated_voltage", "name": "额定母线电压", "value": 12.1, "source": "被测对象 → 额定工况 → 额定母线电压"},
                {"key": "rated_current", "name": "整机额定相电流", "value": 0.7, "source": "被测对象 → 额定工况 → 整机额定相电流"},
            ],
            # ↓ 全量控制参数（流程 1/调优语境）
            "control_params": [
                {"key": "ramp_time", "name": "斜坡时间", "unit": "s"},
                {"key": "tuning_flag", "name": "整定使能", "unit": ""},
            ],
            # ↓ 本页数据（应当保留）
            "report_header_missing": [
                {"key": "customer_name", "name": "客户名称", "value_slot": "C4", "source": "交付对象 → 客户方 → 客户名称"},
                {"key": "email", "name": "Email", "value_slot": "E5", "source": "交付对象 → 联系方式 → Email"},
            ],
        },
    }

    s = build_context_summary(adversarial_env)
    print("---- 流程5 摘要全文（对抗性输入）----")
    print(s)
    print("------------------------------------")

    # ① 正向白名单与反向禁令必须出现
    results.append(
        check(
            "①摘要含「本页只回答」（正向白名单）",
            "本页（测试报告及产出）只回答" in s,
        )
    )
    results.append(
        check(
            "①摘要含「本页不得出现」（反向禁令）",
            "本页**不得出现**" in s,
        )
    )
    results.append(
        check(
            "①禁令写明这些字段属于「初始化配置」流程",
            "属于「初始化配置」流程" in s,
        )
    )
    results.append(
        check(
            "①禁令给了「用户问到时怎么答」的处置办法",
            "本页只处理报告表头与产出" in s,
        )
    )

    # ② 流程 1 的字段名与出处只允许出现在**禁令句**里
    #
    # ⚠️ 断言口径（本轮踩过）：禁令必须**点名**这些字段（否则模型不知道禁什么），
    # 所以不能简单地断言「全文不含」。正确口径是：**把禁令句那段摘掉之后**，
    # 剩下的正文里一个流程 1 字段都不该有（= 摘要没有把流程 1 的**数据**喂给模型）。
    def strip_ban_sentence(text: str) -> str:
        """摘掉两段白名单/禁令句，只留「实际数据」部分。"""
        kept = []
        for line in text.split("\n"):
            if line.startswith("本页（测试报告及产出）只回答"):
                continue
            if line.startswith("本页**不得出现**"):
                continue
            kept.append(line)
        return "\n".join(kept)

    data_only = strip_ban_sentence(s)
    leaked_names = [n for n in INIT_FIELD_NAMES if n in data_only]
    results.append(
        check(
            "②摘要在禁令句之外不出现流程 1 字段名（没把流程 1 数据喂给模型）",
            len(leaked_names) == 0,
            f"泄露={leaked_names}" if leaked_names else "",
        )
    )
    # 禁令句必须真的点名（否则模型不知道禁什么）——正向断言，防「把禁令改空」蒙混过关
    results.append(
        check(
            "②禁令句确实点名了这些字段（否则模型无从遵守）",
            all(n in s for n in ("额定转速", "风扇外形尺寸", "斜坡时间")),
        )
    )
    leaked_src = [x for x in INIT_SOURCE_FRAGMENTS if x in data_only]
    results.append(
        check(
            "②摘要在禁令句之外不出现流程 1 的出处路径片段",
            len(leaked_src) == 0,
            f"泄露={leaked_src}" if leaked_src else "",
        )
    )
    # 反向对照：确认对抗输入里的东西确实进了 envelope（否则上面的断言是空过）
    results.append(
        check(
            "②（对照）对抗输入确实在 envelope 里（断言非空过）",
            adversarial_env["zoneB"]["missing"][0]["name"] == "风扇外形尺寸",
        )
    )

    # ③ 本页数据锚点保留
    results.append(
        check(
            "③摘要保留本页数据：报告表头未填项",
            "报告表头还没有填的项" in s and "客户名称(customer_name)" in s,
        )
    )
    results.append(
        check(
            "③本页表头缺项带了出处（交付对象 → 客户方）",
            "交付对象 → 客户方 → 客户名称" in s,
        )
    )

    # ④ system prompt 两个分支都要带白名单与禁令（历史坑：只在有工具分支追加）
    sp_no_tool = _build_system_prompt([], s)
    sp_with_tool = _build_system_prompt([{"name": "KnowledgeSearch"}], s)
    for label, sp in (("无工具", sp_no_tool), ("有工具", sp_with_tool)):
        results.append(
            check(
                f"④system prompt（{label}）含正向白名单",
                "本页（测试报告及产出）只回答" in sp,
            )
        )
        results.append(
            check(
                f"④system prompt（{label}）含反向禁令",
                "本页**不得出现**" in sp,
            )
        )
        results.append(
            check(
                f"④system prompt（{label}）仍含上下文摘要（不能丢）",
                "【当前现场上下文" in sp,
            )
        )

    # ⑤ 引用纪律的示例不再指向单一流程
    #
    # ⚠️ 同 ② 的口径：「风扇厚度」在 system prompt 里**允许出现在禁令句**（那是在禁止它），
    # 但**不允许出现在示例句**（那才是在教模型套用）。所以断的是「示例里没有它」。
    results.append(
        check(
            "⑤_CITE_RULE 的示例不再给流程 1 专属模板（示例句里无「风扇厚度」）",
            "被测对象 → 机械外形 → 风扇厚度" not in sp_no_tool,
            "示例字段已中性化" if "被测对象 → 机械外形 → 风扇厚度" not in sp_no_tool else "仍在给跨界模板",
        )
    )
    results.append(
        check(
            "⑤示例改成了中性占位写法（<一级类> → <二级组> → <字段名>）",
            "<一级类> → <二级组> → <字段名>" in sp_no_tool,
        )
    )
    results.append(
        check(
            "⑤_CITE_RULE 明确「出处只写本页字段」",
            "出处只写本页字段" in sp_no_tool,
        )
    )

    # ⑥ 禁止复述其它流程清单的纪律（_FORMAT_RULE ④'）
    results.append(
        check(
            "⑥_FORMAT_RULE 含「不得复述其它流程的清单」",
            "不得复述其它流程的清单" in sp_no_tool,
        )
    )
    results.append(
        check(
            "⑥该纪律点名了报告页与初始化配置页的关系",
            "测试报告及产出" in sp_no_tool and "本体属性或控制参数清单" in sp_no_tool,
        )
    )

    # ⑦ 回归保护：init 流程的行为不能被这轮改动带偏（它此前是「正常」的）
    init_env = {
        "flow": {"id": "init", "label": "初始化配置", "confirmed": {}},
        "zoneB": {
            "placeholders_pending": [
                {"key": "fan_thickness", "name": "风扇厚度", "source": "被测对象 → 机械外形 → 风扇厚度"},
            ],
        },
    }
    s_init = build_context_summary(init_env)
    results.append(
        check(
            "⑦回归：init 流程仍正常输出流程 1 字段（用户确认其行为正常）",
            "风扇厚度(fan_thickness)" in s_init and "至今仍没填" in s_init,
        )
    )
    results.append(
        check(
            "⑦回归：init 流程**不**被注入 report 的白名单段",
            "本页（测试报告及产出）只回答" not in s_init,
        )
    )

    passed = sum(results)
    total = len(results)
    print(f"\n==== {passed}/{total} PASS ====")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
