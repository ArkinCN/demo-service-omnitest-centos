"""验证：助手上下文摘要的英文字段已翻成中文（2026-10-04 用户反馈）。

覆盖四处（对照截图反馈）：
  ① 「人已改过的参数」输出「中文名(英文键)=值」，不再裸英文键；
  ② 「已勾选的候选改动」输出中文名，不再英文参数键；
  ③ 「最近一轮判为不通过的项」输出中文判据名，不再 Python dict 原文；
  ④ 「最近一轮未采集到的实测量」输出「中文名(英文键)」（前端 legend 传入）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.agent_context import build_context_summary  # noqa: E402


def check(name: str, cond: bool, detail: str = "") -> bool:
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  {detail}" if detail else ""))
    return cond


def main() -> int:
    env = {
        "product": {"product_name": "FU6832 散热风扇驱动板", "taxonomy_path": ["电机", "散热风扇", "FU6832 散热风扇驱动板"]},
        "flow": {"id": "report", "label": "测试报告及产出", "confirmed": {"init": True, "req": True}},
        "zoneB": {
            "values": {
                "run.cp.调速.ramp_time": 0.072,
                "run.cp.调速.tuning_flag": 1,
            },
            "control_params": [
                {"key": "ramp_time", "name": "斜坡时间", "unit": "s"},
                {"key": "tuning_flag", "name": "整定使能", "unit": ""},
            ],
            "selected_candidate": {
                "count": 2,
                "keys": ["start_align_current", "preposition_time"],
                "items": [
                    {"key": "start_align_current", "name": "启动电流", "from": "1.3", "to": "1.04", "group": "启动"},
                    {"key": "preposition_time", "name": "预定位时间", "from": "450", "to": "540", "group": "启动"},
                ],
            },
        },
        "lastRun": {
            "run_id": "abc123",
            "missing_measures": ["母线电流峰值(bus_current_peak_a)", "稳态转速(rpm_mean)"],
            "failed_items": [
                {"req_id": "TR-SPEED-02", "name": "稳态转速偏差", "state": "fail"},
                {"req_id": "TR-START-01", "name": "启动电流峰值", "state": "fail"},
            ],
        },
    }
    s = build_context_summary(env)
    print("---- 摘要全文 ----")
    print(s)
    print("------------------")

    results = []
    results.append(check("①「人已改过的参数」含中文「斜坡时间(ramp_time)」", "斜坡时间(ramp_time)" in s))
    results.append(check("①「人已改过的参数」含中文「整定使能(tuning_flag)」", "整定使能(tuning_flag)" in s))
    results.append(check("①不再裸输出「ramp_time=」（无中文名包裹）", "ramp_time=0.072" not in s.replace("斜坡时间(ramp_time)=0.072", "")))
    results.append(check("②「已勾选的候选改动」含中文「启动电流」", "启动电流" in s))
    # 口径 =「中文名(英文键)」（_CITE_RULE：正文只取中文名），禁止的是裸英文键无中文
    results.append(check("②英文键都在中文名后的括号里（无裸键）", "启动电流(start_align_current)" in s))
    results.append(check("③「判为不通过的项」含中文「稳态转速偏差」", "稳态转速偏差" in s))
    results.append(check("③不再输出 Python dict 原文（req_id）", "'req_id'" not in s and '"req_id"' not in s))
    results.append(check("④「未采集到的实测量」含中文「母线电流峰值(bus_current_peak_a)」", "母线电流峰值(bus_current_peak_a)" in s))
    results.append(check("④不再裸输出 rpm_mean（无中文包裹）", " rpm_mean" not in s.replace("稳态转速(rpm_mean)", "")))

    # 向后兼容：无 control_params / 无 legend 时降级不崩
    env_min = {"zoneB": {"values": {"run.cp.x.k": 1}}, "lastRun": {"missing_measures": ["rpm_mean"], "failed_items": ["文本项"]}}
    s2 = build_context_summary(env_min)
    results.append(check("兼容：无 control_params 时退回英文键不崩", "k=1" in s2))
    results.append(check("兼容：failed_items 为字符串数组时原样输出", "文本项" in s2))

    # ── 2026-10-04 追加：流程中文化 + 跨页隔离 ──
    env_flow = {
        "flow": {"id": "report", "label": "测试报告及产出", "confirmed": {"init": True, "req": True, "tune": True}},
        "zoneB": {
            # 流程5 的摘要不应含流程1 的占位/缺值字段（跨页隔离）
            "missing": [{"key": "fan_outer_size", "name": "风扇外形尺寸"}],
            "placeholders": [{"key": "preposition_strength", "name": "预定位强度", "source": "被测对象 → 启动 → 预定位强度"}],
        },
    }
    s3 = build_context_summary(env_flow)
    results.append(check("⑤隔离：report 流程摘要不出现「待现场确认」段", "待现场确认" not in s3))
    results.append(check("⑤隔离：report 流程摘要不出现「取不到有效值」段", "取不到有效值" not in s3))
    results.append(check("⑤隔离：report 流程不出现「预定位强度」", "预定位强度" not in s3))

    env_init = dict(env_flow)
    env_init["flow"] = {"id": "init", "label": "初始化配置", "confirmed": {}}
    s4 = build_context_summary(env_init)
    results.append(check("⑤隔离：init 流程仍输出占位/缺值段（本页数据）", "预定位强度" in s4 and "取不到有效值" in s4))

    # 流程 id → 中文名
    env_cf = {"flow": {"id": "report", "label": "测试报告及产出", "confirmed": {"init": True, "req": True}}}
    s5 = build_context_summary(env_cf)
    results.append(check("②「已确认的流程」输出中文流程名", "初始化配置、测试需求确认" in s5))
    results.append(check("②不裸输出英文流程 id", "[init" not in s5 and "、req" not in s5 and "、tune" not in s5))

    # system prompt 含格式纪律
    from app.services.agent_chat_service import _build_system_prompt
    sp = _build_system_prompt([], "")
    results.append(check("⑥system prompt 含格式纪律（简体中文/表格语法）", "输出格式与用语纪律" in sp and "|---|" in sp))
    sp2 = _build_system_prompt([{"name": "KnowledgeSearch"}], "")
    results.append(check("⑥有工具分支也含格式纪律", "输出格式与用语纪律" in sp2))

    # ── 2026-10-04 追加②：流程 5 本页表头未填项（隔离的正面补齐）──
    env_rep = {
        "flow": {"id": "report", "label": "测试报告及产出", "confirmed": {}},
        "zoneB": {
            "report_header_missing": [
                {"key": "customer_name", "name": "客户名称", "value_slot": "C4"},
                {"key": "email", "name": "Email", "value_slot": "E5"},
            ],
            # 这些流程 1 字段即使混进 envelope 也不该出现在 report 摘要里
            "placeholders": [{"key": "fan_thickness", "name": "风扇厚度", "source": "被测对象 → 机械外形 → 风扇厚度"}],
        },
    }
    s6 = build_context_summary(env_rep)
    results.append(check("⑤' report 摘要输出「报告表头未填项」（本页数据）", "报告表头还没有填的项" in s6 and "客户名称(customer_name)" in s6))
    # ⚠️ 口径修正（2026-10-05）：report 摘要现在**必须**在禁令句里点名流程 1 的字段
    # （「本页不得出现：…风扇厚度…」），否则模型不知道要禁什么。所以不能断言
    # 「全文不含风扇厚度」，而要断言「**数据部分**不含」——把两段白名单/禁令摘掉再看。
    data_only = "\n".join(
        ln for ln in s6.split("\n")
        if not ln.startswith("本页（测试报告及产出）只回答") and not ln.startswith("本页**不得出现**")
    )
    results.append(
        check(
            "⑤' report 摘要的数据部分不含流程 1 的占位字段（禁令句除外）",
            "风扇厚度" not in data_only,
            f"数据部分={'含' if '风扇厚度' in data_only else '不含'}",
        )
    )
    results.append(
        check("⑤' report 摘要含正向白名单段", "本页（测试报告及产出）只回答" in s6)
    )
    results.append(
        check("⑤' report 摘要含反向禁令段", "本页**不得出现**" in s6)
    )

    env_rep_full = {
        "flow": {"id": "report", "label": "测试报告及产出", "confirmed": {}},
        "zoneB": {"report_header_missing": []},
    }
    s7 = build_context_summary(env_rep_full)
    results.append(check("⑤' 表头全填时该段不出现（助手如实答已全部填写）", "报告表头还没有填的项" not in s7))

    # ── 2026-10-05 追加：缺值三段拆分（修「填了还说缺」）──
    #
    # 这一段是本轮修复的核心断言：前端把 init 的缺值段按左栏同口径拆成
    # missing / placeholders_pending / placeholders_filled 三段，
    # 后端必须**分开措辞**，尤其「人已经填好值」的项绝不能被说成缺失。
    env_seg = {
        "flow": {"id": "init", "label": "初始化配置", "confirmed": {}},
        "zoneB": {
            "missing": [
                {"key": "fan_outer_size", "name": "风扇外形尺寸", "source": "被测对象 → 机械外形 → 风扇外形尺寸"},
            ],
            "placeholders_pending": [
                {"key": "fan_thickness", "name": "风扇厚度", "source": "被测对象 → 机械外形 → 风扇厚度"},
            ],
            "placeholders_filled": [
                {"key": "rated_speed", "name": "额定转速", "value": 18100, "source": "被测对象 → 转速规格 → 额定转速"},
                {"key": "rated_voltage", "name": "额定母线电压", "value": 12.1, "source": "被测对象 → 电压规格 → 额定母线电压"},
            ],
        },
    }
    s8 = build_context_summary(env_seg)
    print("---- 三段拆分摘要 ----")
    print(s8)
    print("----------------------")
    results.append(check("⑦「取不到有效值」段存在且含风扇外形尺寸", "取不到有效值" in s8 and "风扇外形尺寸(fan_outer_size)" in s8))
    results.append(check("⑦「至今仍没填」段存在且含风扇厚度", "至今仍没填" in s8 and "风扇厚度(fan_thickness)" in s8))
    results.append(
        check(
            "⑦「人已经填好值」段存在、标明 2 项、且带具体数值",
            "人已经填好值" in s8 and "2 项" in s8 and "额定转速(rated_speed)=18100" in s8,
        )
    )
    results.append(check("⑦「已填」段明确写了不要列为缺失（防模型误报）", "不要列为缺失" in s8))
    results.append(
        check(
            "⑦已填项不出现在「取不到有效值」段",
            "取不到有效值" in s8 and "额定转速(rated_speed)" not in s8.split("取不到有效值")[1].split("\n")[0],
        )
    )
    # 旧前端（只有 placeholders、无 pending 键）时的向后兼容
    env_legacy = {
        "flow": {"id": "init", "label": "初始化配置", "confirmed": {}},
        "zoneB": {"placeholders": [{"key": "fan_thickness", "name": "风扇厚度"}]},
    }
    s9 = build_context_summary(env_legacy)
    results.append(check("⑦兼容：老前端只有 placeholders 时按「还没填」输出", "至今仍没填" in s9 and "风扇厚度" in s9))
    results.append(check("⑦老前端无 filled 段时不出现「已填好值」段", "人已经填好值" not in s9))

    # 冲突优先级纪律必须进 system prompt（两个分支）
    sp3 = _build_system_prompt([], "")
    sp4 = _build_system_prompt([{"name": "KnowledgeSearch"}], "")
    results.append(check("⑧system prompt 含「现场上下文是当前唯一权威」", "现场上下文是当前唯一权威" in sp3))
    results.append(check("⑧system prompt 含「已填不许列为缺失」纪律", "不许" in sp3 and "列为缺失" in sp3))
    results.append(check("⑧有工具分支同样含冲突优先级纪律", "现场上下文是当前唯一权威" in sp4))

    passed = sum(results)
    total = len(results)
    print(f"\n==== {passed}/{total} PASS ====")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
