"""报告内嵌图表：趋势图 + 波形图（Excel 原生图表）。

需求（用户 2026-10-12 紧急任务）：
    报告 xlsm 里**自带生成**的趋势图与波形图——打开报告即可看到，
    不依赖外部图片文件、不需要生成报告的人手工准备图片。

为什么用 **Excel 原生图表**（openpyxl.chart）而不是 PNG：
    ① 依赖纪律：后端镜像内没有 matplotlib，画 PNG 须新增依赖并重建镜像；
       openpyxl 原生图表零新增依赖（openpyxl 3.1.5 已在镜像内）。
    ② 可交互：在 Excel 里能悬停读点、缩放、筛选系列——PNG 做不到。
    ③ 可审计：图表数据落在隐藏数据表里，可核对、可复算；PNG 是死像素，
       出问题只能回到原始数据重画。
    ④ 体量：1200 点 × 4 通道进 xlsm 约几百 KB，可接受。

数据源（**全部取自本轮真实产物**，不编造）：
    - 趋势：`<run_dir>/events.jsonl` 里每个 `capture_completed` 一个折点。
      时间轴 = 该次采集 finishedUtc − run 起跑时刻（run_started 事件）；
      占空比/电压/电流/转速取自事件自带的 metrics（与前端趋势图同源同口径）。
    - 波形：`<run_dir>/cycle*/pwm/CH{1,2,3}.csv` 与 `tach/CH4.csv`，
      取**该轮最后一次采集**（含 tach 档者优先，与示波器"最后停在哪"一致）。
      每通道**两张图**：全程（整采集窗）+ 放大（更小时间范围，人眼可读，
      2026-10-12 用户需求「额外添加一个时间范围更小的图」——窗口口径见
      ZOOM_* 常量注释：PWM 通道 80 μs≈2 个 25kHz 周期，转速通道 10 ms 对准脉冲）。

数据纪律（与全项目一致，不可逾越）：
    - 缺测点**留空**（Excel 图表遇空值自动断线，connectNulls=false 的等价物），
      **绝不补 0**——补 0 会把「没采到」画成「是 0」；
    - 数据不齐（无 events.jsonl / 无 CSV）时如实返回缺失清单，由调用方
      在报告里写「（无）」与原因，不静默跳过。
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl.chart import LineChart, Reference
from openpyxl.chart.axis import ChartLines
from openpyxl.drawing.line import LineProperties
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.utils import get_column_letter

#: 隐藏数据表名（图表数据的落点；报表人不看，但可审计）
DATA_SHEET = "_图表数据"

#: 通道 → 显示（与前端 FanWaveChart.ROLE_LABEL 同口径）
CH_LABEL: dict[int, str] = {
    1: "CH1 电流探头",
    2: "CH2 供电电压",
    3: "CH3 PWM 驱动",
    4: "CH4 转速传感器",
}

#: 通道 → 线条颜色（与前端 CH_COLOR 同色系，纸面与屏幕对得上）
CH_COLOR: dict[int, str] = {
    1: "A6353A",  # 暗红
    2: "2E5E45",  # 墨绿
    3: "6B9E82",  # 浅绿
    4: "1F6F8B",  # 青蓝
}

#: 波形图一次最多写入的数据点（超长时的显示层截取上限）。
#: 1200 点是常规值，全部进图；4100 是 Excel 图表的舒适上限（再多打开变慢）。
WAVE_MAX_POINTS = 4100

#: 放大图（每通道第二张）的窗口时长（2026-10-12 用户需求：
#: 「在 CH1-4 都额外添加一个时间范围更小的图，人眼能清晰的看出波形」）。
#:
#: 口径依据：
#:   · PWM 三通道载波 25 kHz（周期 40 μs）→ 取 80 μs ≈ 2 个周期：
#:     方波边沿与纹波展开到整张图，肉眼可数周期；
#:   · 转速通道脉冲宽约 1.5~2 ms、周期 27~84 ms → 取 10 ms 并以**最深点**为心：
#:     一次转动的脉冲落在图中央（全程视图下脉冲只占宽度约 3%，肉眼难辨）。
ZOOM_PWM_DURATION_S = 80e-6
ZOOM_TACH_DURATION_S = 10e-3
#: 放大窗口最少采样点数；不足时以中心点扩窗补足，仍不足则不出该图。
ZOOM_MIN_POINTS = 30

#: 图表宽度（cm）。A4 纵向可打印宽约 17.2cm，原 20cm 会被打印断边；
#: 16.5cm 留出左右页边距后仍能整图落在一页内。高度 8.5cm（趋势）/ 7cm（波形）。
CHART_WIDTH_CM = 16.5


# ---------------------------------------------------------------------------
# 采集（纯数据，不碰工作簿）
# ---------------------------------------------------------------------------
def _parse_utc(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def load_trend_points(run_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """从 events.jsonl 取趋势折点。返回 (points, warnings)。

    每个 capture_completed → 一点：
      t_s        = finishedUtc − run 起跑时刻（秒，四舍五入 2 位）
      cmd_duty   = commandedPwmPercent（命令占空比 %）
      meas_duty  = metrics.pwm.dutyPercent（实测；缺→None）
      voltage_v  = metrics.voltage.meanV（缺→None）
      current_v  = metrics.current.meanV（电流探头电压；缺→None）
      rpm        = metrics.tach.rpm（缺→None；与前端"未采集"同语义）
    """
    warnings: list[str] = []
    ev_path = run_dir / "events.jsonl"
    if not ev_path.is_file():
        return [], [f"未找到 events.jsonl（{ev_path.name}），趋势图无数据"]

    t0: datetime | None = None
    points: list[dict[str, Any]] = []
    try:
        text = ev_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:  # noqa: BLE001
        return [], [f"events.jsonl 读取失败：{e}"]

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = ev.get("type")
        if etype == "run_started" and t0 is None:
            t0 = _parse_utc(ev.get("timestampUtc") or "")
            continue
        if etype != "capture_completed":
            continue
        data = ev.get("data") or {}
        m = data.get("metrics") or {}
        fin = _parse_utc(data.get("finishedUtc") or "")
        if t0 is None or fin is None:
            t_s: float | None = None
        else:
            t_s = round((fin - t0).total_seconds(), 2)

        def _m(group: str, key: str) -> float | None:
            g = m.get(group) or {}
            v = g.get(key)
            return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

        cmd_raw = data.get("commandedPwmPercent")
        points.append({
            "t_s": t_s,
            # 命令占空比来自事件顶层（数据纪律：非数即 None，不编造）
            "cmd_duty": float(cmd_raw)
            if isinstance(cmd_raw, (int, float)) and not isinstance(cmd_raw, bool) else None,
            "meas_duty": _m("pwm", "dutyPercent"),
            "voltage_v": _m("voltage", "meanV"),
            "current_v": _m("current", "meanV"),
            "rpm": _m("tach", "rpm"),
            "cycle": data.get("cycle"),
        })

    if not points:
        warnings.append("events.jsonl 里没有 capture_completed 事件，趋势图无数据")
    return points, warnings


def _read_wave_csv(path: Path) -> tuple[list[float], list[float]]:
    """读一个 CH{n}.csv → (time_s, voltage_v)。空/缺列的行如实跳过并计数。"""
    ts: list[float] = []
    vs: list[float] = []
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or "time_s" not in reader.fieldnames or "voltage_V" not in reader.fieldnames:
            raise ValueError("CSV 缺少 time_s / voltage_V 列")
        for row in reader:
            try:
                ts.append(float(row["time_s"]))
                vs.append(float(row["voltage_V"]))
            except (TypeError, ValueError):
                continue
    return ts, vs


def load_last_waveforms(run_dir: Path) -> tuple[dict[str, Any], list[str]]:
    """取该轮**最后一次**采集的 4 通道波形。返回 (waves, warnings)。

    waves = {"cycle": 目录名, "profile": "pwm+tach"|..., "channels": {1: {"t":[], "v":[]}, ...}}
    优先选含 tach/CH4.csv 的采集（四通道齐）；否则退到最后一个含 pwm 的采集。
    """
    warnings: list[str] = []
    cycles = sorted([p for p in run_dir.glob("cycle*") if p.is_dir()])
    if not cycles:
        return {}, [f"运行目录下没有 cycle*（{run_dir.name}），波形图无数据"]

    chosen: Path | None = None
    for c in reversed(cycles):
        if (c / "tach" / "CH4.csv").is_file():
            chosen = c
            break
    if chosen is None:
        for c in reversed(cycles):
            if (c / "pwm" / "CH1.csv").is_file():
                chosen = c
                break
    if chosen is None:
        return {}, ["所有 cycle 目录里都没有波形 CSV，波形图无数据"]

    channels: dict[int, dict[str, list[float]]] = {}
    subdirs = [("pwm", (1, 2, 3)), ("tach", (4,))]
    for sub, chans in subdirs:
        for ch in chans:
            p = chosen / sub / f"CH{ch}.csv"
            if not p.is_file():
                warnings.append(f"{chosen.name}/{sub}/CH{ch}.csv 不存在")
                continue
            try:
                ts, vs = _read_wave_csv(p)
            except (OSError, ValueError) as e:  # noqa: BLE001
                warnings.append(f"{chosen.name}/{sub}/CH{ch}.csv 读取失败：{e}")
                continue
            if not ts:
                warnings.append(f"{chosen.name}/{sub}/CH{ch}.csv 无数据行")
                continue
            channels[ch] = {"t": ts, "v": vs}

    if not channels:
        return {}, [f"{chosen.name} 下没有任何可读的波形数据"]
    return {"cycle": chosen.name, "channels": channels}, warnings


def collect(run_dir: Path) -> dict[str, Any]:
    """汇总图表所需数据。返回 {trend, waves, warnings}。"""
    trend, w1 = load_trend_points(run_dir)
    waves, w2 = load_last_waveforms(run_dir)
    return {"trend": trend, "waves": waves, "warnings": w1 + w2}


# ---------------------------------------------------------------------------
# 写入 + 建图（工作簿侧）
# ---------------------------------------------------------------------------
def _pick_time_unit(max_abs_s: float) -> tuple[float, str]:
    """时间轴单位自适应（与前端 FanWaveChart.pickTimeUnit 同口径）：
    <1ms → μs；<1s → ms；否则 s。"""
    if max_abs_s < 1e-3:
        return 1e6, "μs"
    if max_abs_s < 1:
        return 1e3, "ms"
    return 1.0, "s"


def _style_line(chart: LineChart, colors: list[str | None] | None = None, width: float = 1.2) -> None:
    """统一描线：无标记点（1200 点时标记会糊成一片）、线宽、逐条颜色。

    colors=None 或不传某条 → 该项不设色（用 Excel 默认主题色）。
    """
    for i, s in enumerate(chart.series):
        s.graphicalProperties = GraphicalProperties()
        col = colors[i] if colors and i < len(colors) else None
        s.graphicalProperties.line = LineProperties(solidFill=col, w=int(width * 12700))
        s.smooth = False


def write_trend_block(ws, row0: int, points: list[dict[str, Any]]) -> dict[str, Any]:
    """把趋势数据写入隐藏数据表，从 row0 行开始。返回列引用信息。

    返回的 `has_data` 是**逐列**的「是否有值」（该列至少一个非 None）——
    调用方据此决定该系列建不建：整列都是「未采集」时**不建系列、不建副轴**，
    否则会出现 xin.xlsm 里那种「图例有『转速 (rpm)』、图上却没有曲线」。
    """
    headers = ["时间 (s)", "命令占空比 (%)", "实测占空比 (%)", "供电电压 (V)", "电流探头 (V)", "转速 (rpm)"]
    keys = ["t_s", "cmd_duty", "meas_duty", "voltage_v", "current_v", "rpm"]
    for j, h in enumerate(headers, start=1):
        ws.cell(row=row0, column=j, value=h)
    for i, pt in enumerate(points, start=row0 + 1):
        for j, k in enumerate(keys, start=1):
            v = pt.get(k)
            ws.cell(row=i, column=j, value=v if v is not None else None)
    return {
        "row0": row0,
        "n": len(points),
        "cols": {k: j for j, k in enumerate(keys, start=1)},
        # 注意用 `is not None` 而非真值判断：0% / 0 V / 0 rpm 都是**真实测量值**，
        # 必须出线，不能被当成「没数据」丢掉。
        "has_data": {k: any(pt.get(k) is not None for pt in points) for k in keys},
    }


def build_trend_chart(
    ws,
    ref: dict[str, Any],
    *,
    width_cm: float = CHART_WIDTH_CM,
    height_cm: float = 8.5,
) -> list[LineChart]:
    """建趋势图（最多两张：占空比+转速；电压+电流）。返回图表列表（供锚定）。

    `width_cm` / `height_cm` 为**可选**尺寸（默认 = 本模块既有口径 16.5 × 8.5 cm）：
    模板填充器（`report_template_fill`）按模板预留位传更小的值；
    不传时行为与历史完全一致，既有调用方零影响。

    返回列表与「版位」的对应关系（模板填充器依赖这一确定关系，故在此写明）：
      · 第 1 张 = 图一（占空比 / 转速）；第 2 张 = 图二（供电电压 / 电流探头）；
      · 某张图出不来时它**不占位**（列表里没有该元素），调用方须按 `has_data`
        判定版位、不可按下标硬套。

    2026-10-12 增（P1-1）：「**整列无数据**」的系列**不建系列、也不为它建副轴**。
    此前只看「有没有采集点」就无条件画 5 条线，于是出现
    「图例里有『转速 (rpm)』、图上却没有曲线」——图例在说谎，读者会以为转速是 0。
    现在改为：缺哪列就不画哪列；跳过项由 `trend_skip_notes()` 在报告里写明原因。

    返回列表的语义（调用方据此锚定 + 写说明）：
      · `[]`      —— 每一列都空白，一张图都出不了（报告写「（无图）」+ 理由）；
      · 单张图    —— 副轴系列为空时不再合并副轴，图就只画主轴那几条线。
    """
    n = ref["n"]
    row1 = ref["row0"]
    row2 = row1 + n
    cols = ref["cols"]
    has = ref.get("has_data") or {}

    def col_ref(key: str) -> Reference:
        c = cols[key]
        return Reference(ws, min_col=c, max_col=c, min_row=row1, max_row=row2)

    cats = Reference(ws, min_col=cols["t_s"], min_row=row1 + 1, max_row=row2)
    charts: list[LineChart] = []

    # ── 图 1：占空比（主轴 %）+ 转速（副轴 rpm）
    # 命令占空比=灰（虚线，指令非测量）；实测占空比=墨绿实线；转速=青蓝
    duty_keys = [k for k in ("cmd_duty", "meas_duty") if has.get(k)]
    if duty_keys or has.get("rpm"):
        c1 = LineChart()
        c1.style = 2
        c1.x_axis.title = "时间 (s)"
        if duty_keys:
            # 标题同样只写图上真有的东西：转速列空时不该还叫「占空比与转速」
            c1.title = "趋势图（一）占空比与转速" if has.get("rpm") else "趋势图（一）占空比"
            c1.y_axis.title = "占空比 (%)"
            for k in duty_keys:
                c1.add_data(col_ref(k), titles_from_data=True)
            _style_line(c1, colors=[{"cmd_duty": "8A9A90", "meas_duty": "2E5E45"}[k] for k in duty_keys])
            if "cmd_duty" in duty_keys:
                c1.series[duty_keys.index("cmd_duty")].graphicalProperties.line.dashStyle = "dash"
        else:
            # 占空比两列全空、只有转速：转速改作主轴单独成图，**不丢数据**
            c1.title = "趋势图（一）转速"
            c1.y_axis.title = "转速 (rpm)"
            c1.add_data(col_ref("rpm"), titles_from_data=True)
            _style_line(c1, colors=["1F6F8B"])
        c1.set_categories(cats)
        if duty_keys and has.get("rpm"):
            # 只有主轴有数据时才合并副轴——空副轴会留下一个没有内容的右侧刻度
            c1b = LineChart()
            c1b.add_data(col_ref("rpm"), titles_from_data=True)
            c1b.y_axis.axId = 200
            c1b.y_axis.title = "转速 (rpm)"
            c1b.y_axis.majorGridlines = None
            _style_line(c1b, colors=["1F6F8B"])
            c1.y_axis.crosses = "max"
            c1 += c1b
        c1.height = height_cm
        c1.width = width_cm
        charts.append(c1)

    # ── 图 2：电压（主轴 V）+ 电流探头（副轴 V；两量程差千倍，双轴才都看得见）
    if has.get("voltage_v") or has.get("current_v"):
        c2 = LineChart()
        c2.style = 2
        c2.x_axis.title = "时间 (s)"
        if has.get("voltage_v"):
            c2.title = (
                "趋势图（二）供电电压与电流探头" if has.get("current_v") else "趋势图（二）供电电压"
            )
            c2.y_axis.title = "供电电压 (V)"
            c2.add_data(col_ref("voltage_v"), titles_from_data=True)
            _style_line(c2, colors=["2E5E45"])
        else:
            # 电压列全空、只有电流探头：改作主轴单独成图
            c2.title = "趋势图（二）电流探头"
            c2.y_axis.title = "电流探头 (V)"
            c2.add_data(col_ref("current_v"), titles_from_data=True)
            _style_line(c2, colors=["A6353A"])
        c2.set_categories(cats)
        if has.get("voltage_v") and has.get("current_v"):
            c2b = LineChart()
            c2b.add_data(col_ref("current_v"), titles_from_data=True)
            c2b.y_axis.axId = 200
            c2b.y_axis.title = "电流探头 (V)"
            c2b.y_axis.majorGridlines = None
            _style_line(c2b, colors=["A6353A"])
            c2.y_axis.crosses = "max"
            c2 += c2b
        c2.height = height_cm
        c2.width = width_cm
        charts.append(c2)

    return charts


#: 趋势列 key → 报告里用的中文名（与 `write_trend_block` 的表头一致）
_TREND_NAME: dict[str, str] = {
    "cmd_duty": "命令占空比",
    "meas_duty": "实测占空比",
    "voltage_v": "供电电压",
    "current_v": "电流探头",
    "rpm": "转速",
}


def trend_skip_notes(ref: dict[str, Any]) -> list[str]:
    """返回「因整列无数据而未出图」的系列说明（供报告如实写明，不静默省略）。

    数据纪律：这是报告里唯一能解释「为什么线少了一条」的地方——
    不写，读者会把「没采到」读成「值为 0」。
    """
    has = ref.get("has_data") or {}
    return [
        f"{name}（{key}）整列为空白，未绘图"
        for key, name in _TREND_NAME.items()
        if not has.get(key)
    ]


def trend_axis_note(ref: dict[str, Any]) -> str:
    """生成「纵轴口径」说明——**只描述实际出了的图**，避免说明与纸面不符。"""
    has = ref.get("has_data") or {}
    parts: list[str] = []

    duty = [n for k, n in (("cmd_duty", "命令占空比"), ("meas_duty", "实测占空比")) if has.get(k)]
    if duty or has.get("rpm"):
        if duty:
            seg = f"图一：主轴={'/'.join(duty)} %"
            if has.get("rpm"):
                seg += "，右副轴=转速 rpm"
        else:
            seg = "图一：主轴=转速 rpm"
        parts.append(seg)
    if has.get("voltage_v") or has.get("current_v"):
        seg = f"图二：主轴={'供电电压 V' if has.get('voltage_v') else '电流探头 V'}"
        if has.get("voltage_v") and has.get("current_v"):
            seg += "，右副轴=电流探头 V（两量程差千倍，双轴才都看得见）"
        parts.append(seg)

    if not parts:
        return "本轮趋势数据每一列都是空白，无可描述的纵轴。"
    return "；".join(parts) + "。" + (
        "命令占空比为灰色虚线（它是指令、不是测量值）。" if has.get("cmd_duty") else ""
    )


def _zoom_slice(
    ts: list[float], vs: list[float], ch: int
) -> tuple[list[float], list[float], str] | None:
    """裁出「放大窗口」（每通道第二张图的数据）。返回 (t, v, desc)，无法成图时 None。

    窗口口径见 ZOOM_* 常量注释：
      · CH1~CH3（PWM 三通道）：以采集窗中心为心取 80 μs（≈2 个 25 kHz 周期）；
      · CH4（转速）：以**最深点**（负脉冲谷底，实测 -2 V 级，远超噪声）为心取 10 ms。
    数据不足以形成 ≥ZOOM_MIN_POINTS 点的窗口时返回 None（调用方不出该图）。
    """
    n = min(len(ts), len(vs))
    if n < ZOOM_MIN_POINTS:
        return None
    if ch == 4:
        dur = ZOOM_TACH_DURATION_S
        center_i = min(range(n), key=lambda i: vs[i])
        center = ts[center_i]
        desc = "10 ms 窗口，对准转速脉冲"
    else:
        dur = ZOOM_PWM_DURATION_S
        center = (ts[0] + ts[n - 1]) / 2.0
        desc = "80 μs 窗口 ≈2 个 25 kHz 周期"
    lo, hi = center - dur / 2.0, center + dur / 2.0
    idx = [i for i in range(n) if lo <= ts[i] <= hi]
    if len(idx) < ZOOM_MIN_POINTS:
        # 窗口内点不足（数据稀疏 / 窗口错位）：以最接近中心的点为准扩窗补足
        ci = min(range(n), key=lambda i: abs(ts[i] - center))
        half = ZOOM_MIN_POINTS // 2
        a = max(0, ci - half)
        b = min(n, a + ZOOM_MIN_POINTS)
        a = max(0, b - ZOOM_MIN_POINTS)
        idx = list(range(a, b))
    if len(idx) < 3:
        return None
    return [ts[i] for i in idx], [vs[i] for i in idx], desc


def write_wave_block(ws, row0: int, waves: dict[str, Any]) -> dict[str, Any]:
    """把波形数据写入隐藏数据表：每通道**两块** —— 全程（row0 起）与放大（纵向另起）。

    时间单位按窗口自适应（μs/ms），在表头里写明——与前端波形图同口径。
    返回 {channel: {"col_t": …, "col_v": …, "row0": …, "n": …, "unit": …,
                    "zoom": {"col_t": …, "col_v": …, "row0": …, "n": …, "unit": …, "desc": …} | None}}
    """
    channels = waves.get("channels", {})
    # 全程块的最大行数：放大块要落在所有全程块**下面**（先算出来再写，防粘行）
    n_max = 0
    for ch in channels:
        n_max = max(n_max, min(len(channels[ch]["t"]), len(channels[ch]["v"]), WAVE_MAX_POINTS))
    zoom_row0 = row0 + n_max + 3

    info: dict[str, Any] = {}
    col = 1
    for ch in sorted(channels):
        data = channels[ch]
        ts, vs = data["t"], data["v"]
        n = min(len(ts), len(vs), WAVE_MAX_POINTS)
        max_abs = max((abs(t) for t in ts[:n]), default=0.0)
        scale, unit = _pick_time_unit(max_abs)
        ws.cell(row=row0, column=col, value=f"CH{ch} 时间 ({unit})")
        ws.cell(row=row0, column=col + 1, value=f"CH{ch} 电压 (V)")
        for i in range(n):
            ws.cell(row=row0 + 1 + i, column=col, value=round(ts[i] * scale, 6))
            ws.cell(row=row0 + 1 + i, column=col + 1, value=vs[i])
        ent: dict[str, Any] = {
            "col_t": col, "col_v": col + 1, "row0": row0, "n": n, "unit": unit, "zoom": None,
        }
        # 放大块（2026-10-12 增）：与全程块同列、纵向排开
        z = _zoom_slice(ts[:n], vs[:n], ch)
        if z is not None:
            zts, zvs, zdesc = z
            zscale, zunit = _pick_time_unit(max((abs(t) for t in zts), default=0.0))
            ws.cell(row=zoom_row0, column=col, value=f"CH{ch} 放大 时间 ({zunit})")
            ws.cell(row=zoom_row0, column=col + 1, value=f"CH{ch} 放大 电压 (V)")
            for i in range(len(zts)):
                ws.cell(row=zoom_row0 + 1 + i, column=col, value=round(zts[i] * zscale, 6))
                ws.cell(row=zoom_row0 + 1 + i, column=col + 1, value=zvs[i])
            ent["zoom"] = {
                "col_t": col, "col_v": col + 1, "row0": zoom_row0,
                "n": len(zts), "unit": zunit, "desc": zdesc,
            }
        info[str(ch)] = ent
        col += 3  # 留一列间隔，便于人工审阅
    return info


def _make_wave_chart(
    ws,
    block: dict[str, Any],
    title: str,
    ch: int,
    *,
    width_cm: float = CHART_WIDTH_CM,
    height_cm: float = 7,
) -> LineChart:
    """按数据块建一张波形折线图（全程/放大共用同一套样式口径）。

    `width_cm` / `height_cm` 可选（默认 = 既有口径 16.5 × 7 cm）；不传时行为不变。
    """
    c = LineChart()
    c.title = title
    c.style = 2
    c.y_axis.title = "电压 (V)"
    c.x_axis.title = f"时间 ({block['unit']})"
    c.add_data(
        Reference(
            ws,
            min_col=block["col_v"], max_col=block["col_v"],
            min_row=block["row0"], max_row=block["row0"] + block["n"],
        ),
        titles_from_data=True,
    )
    c.set_categories(
        Reference(ws, min_col=block["col_t"], min_row=block["row0"] + 1, max_row=block["row0"] + block["n"])
    )
    _style_line(c, colors=[CH_COLOR.get(ch)], width=1.0)
    # 波形是高频细节：网格只保留主轴横线
    c.x_axis.majorGridlines = None
    c.y_axis.majorGridlines = ChartLines()
    c.height = height_cm
    c.width = width_cm
    return c


def build_wave_chart(
    ws,
    info: dict[str, Any],
    ch: int,
    *,
    kind: str = "full",
    width_cm: float = CHART_WIDTH_CM,
    height_cm: float = 7,
) -> LineChart | None:
    """**按位**建一张波形图：`ch` = 通道号，`kind` = 'full'（全程）/ 'zoom'（放大）。

    为什么单独开这个入口（2026-10-13）：模板填充器要按**固定版位**插图
    （CH1 全程 / CH1 放大 / CH2 全程 …各占模板上预定的一块），不能像旧实现那样
    「按列表顺序依次往下排」。放在这里是为了**样式与标题口径只有一份**——
    填充器不自己拼标题、不自己描线。

    该位没有数据时返回 None（放大块缺失是最常见情况），由调用方在该位如实写「（无）」。
    """
    meta = (info or {}).get(str(ch))
    if not meta:
        return None
    block = meta if kind == "full" else meta.get("zoom")
    if not block:
        return None
    label = CH_LABEL.get(ch, f"CH{ch}")
    title = (
        f"波形图 {label}（{block['unit']} / V）"
        if kind == "full"
        else f"波形图 {label} · 放大（{block['desc']}）"
    )
    return _make_wave_chart(
        ws, block, title, ch, width_cm=width_cm, height_cm=height_cm
    )


def build_wave_charts(
    ws,
    info: dict[str, Any],
    *,
    width_cm: float = CHART_WIDTH_CM,
    height_cm: float = 7,
) -> list[LineChart]:
    """每通道**两张**图：① 全程（整采集窗）② 放大（更小时间范围，人眼可读）。

    返回图表列表（顺序即锚定顺序：CH1 全程 → CH1 放大 → CH2 全程 → CH2 放大 …）。
    实现委托给 `build_wave_chart()`，**顺序与标题口径与历史完全一致**。
    """
    charts: list[LineChart] = []
    for ch_s in info:
        ch = int(ch_s)
        for kind in ("full", "zoom"):
            c = build_wave_chart(
                ws, info, ch, kind=kind, width_cm=width_cm, height_cm=height_cm
            )
            if c is not None:
                charts.append(c)
    return charts
