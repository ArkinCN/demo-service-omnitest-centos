"""
判据求值服务（阶段 4 引入，判定放后端）。

照抄前端 `c/web/src/features/flow-run/evaluate.ts` 的算法，两边口径必须一致：
- 四种变量来源：runtime.measure / threshold / control-parameters / constant
- 未采集纪律：runtime.measure 取不到就判 missing，不拿别的数顶替
- 合取短路：顶层 && 拆分后，某子句所需变量已全部采到且算出为假 → 直接判 fail + partial
  （假 ∧ 任何 = 假）；已算子句全真仍有缺量 → 落 missing（真 ∧ 未知 = 未知）
- 顶层出现 || 不拆（或式无短路规则）
- 子句求值抛异常 → 吞掉回落 missing，不编结论
- 第五态 not_applicable（2026-10-08 新增）：场景包显式声明某判据在本台架无测量手段
  （bench_applicable:false + bench_inapplicable_reason），求值前短路返回该态，
  与 missing（本该采到却没采到）严格区分，不混入未达标与推荐。

判据表达式是 JS 语法（criterion 字段，来自场景包 test-requirements.json，非用户输入），
求值时转成受限的 Python 表达式，globals 只含 abs，无 builtins。
"""
from __future__ import annotations

import re
from typing import Any


def _js_to_py(expr: str) -> str:
    """把 JS 判据表达式转成受限 Python 表达式。

    只做机械替换，表达式来自场景包（受控配置，非用户输入）：
      ===  →  ==      !==  →  !=
      &&   →  and     ||   →  or
      Math.abs → abs    true/false/null → True/False/None
    """
    e = expr
    e = e.replace("!==", "!=")
    e = e.replace("===", "==")
    e = e.replace("&&", " and ").replace("||", " or ")
    e = e.replace("Math.abs", "abs")
    e = re.sub(r"\btrue\b", "True", e)
    e = re.sub(r"\bfalse\b", "False", e)
    e = re.sub(r"\bnull\b", "None", e)
    return e


def _eval(expr: str, scope: dict[str, Any]) -> bool:
    """受限求值。globals 只含 abs，无 builtins。"""
    py = _js_to_py(expr)
    return bool(eval(py, {"__builtins__": {}}, {"abs": abs, **scope}))  # noqa: S307 - 表达式来自场景包，非用户输入


def _to_scalar(v: Any) -> Any:
    """归一标量：数字/布尔/字符串/数字字符串数组直接返回，其余返回 None（当缺）。"""
    if isinstance(v, (int, float, bool, str)):
        return v
    if isinstance(v, (list, tuple)) and all(isinstance(x, (int, float, str)) for x in v):
        return list(v)
    return None


def resolve(req: dict, name: str, v: dict, measures: dict, control_params: dict) -> Any:
    """按 source 分派取值，取不到返回 None。"""
    source = v.get("source")
    if source == "threshold":
        return _to_scalar((req.get("threshold") or {}).get(name))
    if source == "constant":
        return _to_scalar(v.get("value"))
    if source == "control-parameters":
        key = (v.get("ref") or "").split(".")[-1] or name
        return _to_scalar(control_params.get(key))
    # runtime.measure 及其他
    if name == "target_rpm":
        # 与前端 evaluate.ts 同口径（见其注释）：场景包 target_rpm 自述
        # 「NONEMODE 下等于 control-parameters.nonemode_speed；PWMMODE 下由占空比查调速曲线」。
        # 真采到 target_rpm 用真值；没采到且 speed_mode=NONEMODE 时回落读 nonemode_speed。
        if control_params.get("speed_mode") == "NONEMODE" and control_params.get("nonemode_speed") is not None:
            return _to_scalar(control_params.get("nonemode_speed"))
    return _to_scalar(measures.get(name))


def clauses_of(expr: str) -> list[str]:
    """顶层 && 拆分；括号内不拆；顶层出现 || 直接返回整条不拆。"""
    out: list[str] = []
    depth = 0
    buf = ""
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth == 0 and ch == "&" and i + 1 < len(expr) and expr[i + 1] == "&":
            out.append(buf)
            buf = ""
            i += 1
        elif depth == 0 and ch == "|" and i + 1 < len(expr) and expr[i + 1] == "|":
            return [expr]
        else:
            buf += ch
        i += 1
    out.append(buf)
    return [x.strip() for x in out if x.strip()]


def _vars_in(clause: str, names: list[str]) -> list[str]:
    """子句里用到的、已在 variables 登记过的自由变量名。"""
    return [n for n in names if re.search(r"\b" + re.escape(n) + r"\b", clause)]


def _declared_not_applicable(req: dict) -> str | None:
    """场景包显式声明「本台架不具备该测量手段」时返回原因，否则 None。

    与前端 evaluate.ts 的 declaredNotApplicable 同口径（2026-10-08 新增）。

    为什么用显式声明而非运行时推断：推断会随本轮数据波动，同一判据时而不适用、
    时而未采集，结论不可复现；声明一次稳定复现，原因可追溯到缺哪台设备。

    与 missing 的区别（必须守住）：missing=本该采到却没采到（可能采集链路有问题）；
    not_applicable=本台架结构上不具备该能力（需要加装设备，不是故障）。
    """
    if req.get("bench_applicable") is False:
        return req.get("bench_inapplicable_reason") or "本台架未配置该项测量手段"
    return None


def evaluate_one(req: dict, measures: dict, control_params: dict) -> dict:
    """求值单条判据，返回与前端 Evaluated 对齐的结果。"""
    req_id = req.get("id")
    name = req.get("name", "")
    # 本台架不适用：显式声明优先于一切求值（含 evaluable 检查），与前端同序。
    na_reason = _declared_not_applicable(req)
    if na_reason:
        return {
            "req_id": req_id, "name": name, "state": "not_applicable",
            "used": [], "missing": [], "notApplicableReason": na_reason,
        }
    if req.get("evaluable") is False or not req.get("criterion") or not req.get("variables"):
        return {"req_id": req_id, "name": name, "state": "manual", "used": [], "missing": []}

    scope: dict[str, Any] = {}
    used: list[dict] = []
    missing: list[str] = []
    for var_name, v in req["variables"].items():
        value = resolve(req, var_name, v, measures, control_params)
        if value is None:
            missing.append(var_name)
            continue
        scope[var_name] = value
        if v.get("source") not in ("threshold", "constant"):
            used.append({
                "name": v.get("desc") or var_name,
                "value": value,
                "unit": v.get("unit"),
            })

    all_names = list(req["variables"].keys())
    criterion = req["criterion"]

    if missing:
        # 合取短路：缺量的判据里，已采全的子句算一遍，有一个为假就判 fail + partial
        try:
            for clause in clauses_of(criterion):
                need = _vars_in(clause, all_names)
                if not need or any(n not in scope for n in need):
                    continue
                if not _eval(clause, scope):
                    return {
                        "req_id": req_id, "name": name, "state": "fail",
                        "used": used, "missing": missing, "partial": True,
                        "note": f"按已采到的量判：「{clause}」不成立，合取式已有一项为假，补齐也翻不过来。",
                    }
        except Exception:
            pass  # 子句算不动就当没算，回落 missing
        return {"req_id": req_id, "name": name, "state": "missing", "used": used, "missing": missing}

    try:
        ok = _eval(criterion, scope)
        return {"req_id": req_id, "name": name, "state": "pass" if ok else "fail",
                "used": used, "missing": []}
    except Exception as e:
        return {"req_id": req_id, "name": name, "state": "missing", "used": used,
                "missing": [], "error": str(e)}


def evaluate_all(requirements: list[dict], measures: dict, control_params: dict) -> list[dict]:
    """主入口：对全部判据求值。"""
    return [evaluate_one(req, measures, control_params) for req in requirements]


def package_stats_measures(datasets: dict) -> dict:
    """从场景包 datasets.json 的 package_stats 提取默认实测量。

    与前端 evaluate.ts 的 runtimeMeasures 一致：pass_count 取自已标注批次。
    这是既有批次的标注结果（不是本轮现场重采），mode 标历史。
    """
    st = datasets.get("package_stats") or {}
    out: dict = {}
    if isinstance(st.get("pass"), (int, float)) and isinstance(st.get("labeled"), (int, float)):
        out["pass_count"] = st["pass"]
    return out
