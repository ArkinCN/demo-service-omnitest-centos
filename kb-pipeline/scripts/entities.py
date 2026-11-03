"""从转化后的正文里抽取结构化实体：参数名、阈值、单位、寄存器名、规程步骤。

纯正则 + 启发式，不调用任何模型，保证离线可复现。
"""
from __future__ import annotations

import re
from collections import Counter

# 形如 MOTOR_ALIGNMENT_DOUT、ATO_BW、PWM_FREQUENCY 的全大写下划线标识符
RE_IDENT = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
# 数值 + 单位；单位表覆盖电机调试常见量纲
UNITS = [
    "kHz", "MHz", "Hz", "mV", "kV", "V", "mA", "uA", "μA", "A",
    "mΩ", "Ω", "ohm", "mH", "uH", "μH", "H", "ms", "us", "μs", "ns", "s",
    "rpm", "RPM", "r/min", "°C", "℃", "°", "%", "mWb", "Wb", "W", "kW", "Nm", "bit",
]
RE_NUM_UNIT = re.compile(
    r"(?<![\w.])([-+]?\d+(?:\.\d+)?)\s*(" + "|".join(re.escape(u) for u in UNITS) + r")(?![A-Za-z一-鿿])"
)
# 阈值语境词：命中才把「数值+单位」升级为阈值证据
THRESHOLD_CUES = [
    "阈值", "門檻", "门槛", "保护", "保護", "上限", "下限", "最大", "最小", "不得",
    "范围", "範圍", "限制", "typ", "max", "min", "threshold", "limit", "rated",
]
RE_REG_CUE = re.compile(r"(寄存器|暫存器|寄存區|register|Register|REGISTER)")
RE_STEP = re.compile(
    r"^\s*(?:步骤|步驟|Step|STEP)\s*[:：]?\s*(\d+)[.、)]?\s*(.+)$|"
    r"^\s*(\d{1,2})[.、)]\s+(\S.{4,})$"
)
STEP_VERBS = (
    "设置", "設置", "配置", "打开", "打開", "关闭", "關閉", "确认", "確認", "检查", "檢查",
    "测量", "測量", "编译", "編譯", "烧录", "燒錄", "下载", "下載", "调整", "調整",
    "记录", "記錄", "启动", "啟動", "运行", "運行", "修改", "观察", "觀察", "选择", "選擇",
)

MAX_PER_KIND = 200


def _ctx(text: str, start: int, end: int, width: int = 60) -> str:
    return re.sub(r"\s+", " ", text[max(0, start - width): end + width]).strip()


def extract(chunks: list[dict], known_macros: set[str] | None = None) -> dict:
    known_macros = known_macros or set()
    params: dict[str, dict] = {}
    registers: dict[str, dict] = {}
    thresholds: list[dict] = []
    unit_counter: Counter = Counter()
    steps: list[dict] = []

    for ch in chunks:
        text = ch["text"]
        page = ch.get("page")
        cid = ch["id"]

        for m in RE_IDENT.finditer(text):
            name = m.group(0)
            if len(name) < 5:
                continue
            slot = params.setdefault(
                name,
                {"name": name, "count": 0, "in_customer_h": name in known_macros,
                 "first_chunk": cid, "first_page": page, "context": _ctx(text, m.start(), m.end())},
            )
            slot["count"] += 1
            # 紧邻出现「寄存器」字样的标识符另记一份为寄存器候选
            around = text[max(0, m.start() - 40): m.end() + 40]
            if RE_REG_CUE.search(around):
                reg = registers.setdefault(
                    name,
                    {"name": name, "count": 0, "first_chunk": cid, "first_page": page,
                     "context": _ctx(text, m.start(), m.end())},
                )
                reg["count"] += 1

        for m in RE_NUM_UNIT.finditer(text):
            unit_counter[m.group(2)] += 1
            around = text[max(0, m.start() - 40): m.end() + 40].lower()
            if any(cue.lower() in around for cue in THRESHOLD_CUES):
                thresholds.append({
                    "value": float(m.group(1)), "unit": m.group(2),
                    "chunk_id": cid, "page": page,
                    "context": _ctx(text, m.start(), m.end()),
                })

        for line in text.splitlines():
            m = RE_STEP.match(line)
            if not m:
                continue
            body = (m.group(2) or m.group(4) or "").strip()
            if len(body) < 6 or not any(v in body for v in STEP_VERBS):
                continue
            steps.append({
                "order": int(m.group(1) or m.group(3)),
                "text": body[:300],
                "chunk_id": cid,
                "page": page,
                "heading_path": ch.get("heading_path", []),
            })

    def top(d: dict, key="count"):
        return sorted(d.values(), key=lambda x: (-x[key], x["name"]))[:MAX_PER_KIND]

    return {
        "summary": {
            "parameters": len(params),
            "parameters_matching_customer_h": sum(1 for p in params.values() if p["in_customer_h"]),
            "registers": len(registers),
            "thresholds": len(thresholds),
            "units": len(unit_counter),
            "procedure_steps": len(steps),
        },
        "parameters": top(params),
        "registers": top(registers),
        "thresholds": thresholds[:MAX_PER_KIND],
        "units": [{"unit": u, "count": c} for u, c in unit_counter.most_common()],
        "procedure_steps": steps[:MAX_PER_KIND],
        "method": "regex+heuristic, no LLM; 参数名=全大写下划线标识符, 寄存器=标识符±40字符内出现『寄存器/register』, 阈值=数值+单位且±40字符内含阈值语境词, 规程步骤=编号行且含操作动词",
    }
