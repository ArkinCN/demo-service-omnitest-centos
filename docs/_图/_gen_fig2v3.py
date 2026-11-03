# -*- coding: utf-8 -*-
"""fig2 v3 两版草案：知识库降为承托五条流程的基础模块层带。
A 版保留原编号（1 号位空出），B 版重排为 1-5。版式语言沿用 _图/_gen.py。"""
import os

OUT = "docs/20260919-通用Agent测试系统v2.0/_图"
F = "Microsoft YaHei, Noto Sans CJK SC, WenQuanYi Zen Hei, sans-serif"

GREEN = "#2E5E45"
GREEN_W = "#A8C5B5"
TINT = "#EAF2EC"
RED = "#A6353A"
T1 = "#2C2C2C"
T2 = "#555555"
T3 = "#9A9A9A"
SEP = "#C8C5BD"

DEFS = f"""<defs>
<marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{GREEN}"/></marker>
<marker id="ahw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{GREEN_W}"/></marker>
<marker id="ahr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{RED}"/></marker>
</defs>"""

WARN = []


def tw(s, fs):
    w = 0.0
    for c in s:
        w += fs if ord(c) > 0x2E80 else fs * 0.55
    return w


class Fig:
    def __init__(self, name, w, h):
        self.name, self.w, self.h = name, w, h
        self.p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                  DEFS, f'<rect width="{w}" height="{h}" fill="#FFFFFF"/>']
        self.tint_area = 0.0

    def rect(self, x, y, w, h, stroke=GREEN, sw=1.5, fill="none", rx=6, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        if fill != "none":
            self.tint_area += w * h
        self.p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def t(self, x, y, s, fs=12, fill=T1, anchor="start", weight="400", box=None):
        if box is not None:
            width = tw(s, fs)
            if width > box:
                WARN.append(f"[{self.name}] 文本超宽 {width:.0f}>{box}: {s[:34]}")
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.p.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="{F}" font-size="{fs}" font-weight="{weight}" fill="{fill}">{s}</text>')

    def line(self, x1, y1, x2, y2, stroke=SEP, sw=1, dash=None, me=None, ms=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        a = f' marker-end="url(#{me})"' if me else ""
        b = f' marker-start="url(#{ms})"' if ms else ""
        self.p.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{sw}"{d}{a}{b}/>')

    def poly(self, pts, stroke=GREEN, sw=2, dash=None, me=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        a = f' marker-end="url(#{me})"' if me else ""
        s = " ".join(f"{x},{y}" for x, y in pts)
        self.p.append(f'<polyline points="{s}" fill="none" stroke="{stroke}" stroke-width="2"{d}{a}/>')

    def save(self):
        self.p.append("</svg>")
        path = os.path.join(OUT, self.name + ".svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.p))
        pct = self.tint_area / (self.w * self.h) * 100
        print(f"{path}　淡底占比 {pct:.1f}%")
        return path


BW, BH = 196, 152
BY = 210
BAND_Y, BAND_H = 470, 214

# 五条流程：序号在 A / B 两版里不同，故只存正文
FLOWS = [
    ("初始化配置", None, "入　产品文档与工程", "出　锁定配置与联锁实例"),
    ("测试需求确认", None, "入　标准与工作流模板", "出　冻结的需求基线"),
    ("启动测试", "及结果分析", "入　配置快照与需求基线", "出　轮次产物与判定表"),
    ("调优确认", "及运行", "入　未达标项与经验库", "出　参数改动与重跑指令"),
    ("测试报告", "及产出", "入　模板与全部产物", "出　报告成品与归档记录"),
]

AXES = [
    ("归属轴", "挂在哪个产品下", "场景 / 子类 / 产品类型，三级，已实装"),
    ("来源轴", "谁产生的", "文档类外部上传；经验类系统自己长出来"),
    ("用途轴", "回答什么问题", "产品说明书 / 测试需求 / 工艺，本轮新增"),
]


def flow_box(g, x, num, name, sub, tin, tout):
    g.rect(x, BY, BW, BH, GREEN, 1.5)
    cx = x + BW / 2
    g.t(cx, BY + 34, f"{num} {name}", 17, T1, anchor="middle", weight="600", box=BW - 20)
    if sub:
        g.t(cx, BY + 54, sub, 11, T3, anchor="middle", box=BW - 20)
    g.line(x + 14, BY + 68, x + BW - 14, BY + 68, SEP, 1)
    g.t(cx, BY + 92, tin, 11, T2, anchor="middle", box=BW - 16)
    g.t(cx, BY + 122, tout, 11, T2, anchor="middle", box=BW - 16)


def band(g, x0, x1, note_red=None):
    """知识库层带。x0/x1 为层带左右边界。"""
    g.rect(x0, BAND_Y, x1 - x0, BAND_H, GREEN, 1.5)
    g.t(x0 + 20, BAND_Y + 32, "基础模块 · 知识库", 15, GREEN, weight="600")
    g.t(x0 + 176, BAND_Y + 32, "不编号，五条流程共用；三轴正交，一条知识同时落在三个轴上", 11, T2)
    if note_red:
        g.t(x1 - 20, BAND_Y + 32, note_red, 11, RED, anchor="end", weight="600")
    # 三个轴：唯一用淡底的地方
    inner = x1 - x0 - 40
    w = (inner - 56) / 3
    for i, (a, b, c) in enumerate(AXES):
        x = x0 + 20 + i * (w + 28)
        g.rect(x, BAND_Y + 48, w, 96, GREEN_W, 1, TINT, rx=4)
        g.t(x + 16, BAND_Y + 76, a, 14, GREEN, weight="600", box=w - 32)
        g.t(x + 16 + tw(a, 14) + 12, BAND_Y + 76, b, 11, T3, box=w - 32)
        g.t(x + 16, BAND_Y + 106, c, 11, T2, box=w - 32)
    g.line(x0 + 20, BAND_Y + 164, x1 - 20, BAND_Y + 164, SEP, 1)
    g.t(x0 + 20, BAND_Y + 190, "转化流水线　识别 → 抽取 → 切片 → 结构化 → 索引　　转化后才可被流程检索；每个流程页的 B 区顶部都有上传入口与条目数", 11, T2)


def link(g, cx):
    """流程与层带之间的一条虚线：上行取知识，下行存产物。"""
    g.line(cx, BY + BH + 6, cx, BAND_Y - 6, GREEN_W, 1, dash="5 4", me="ahw", ms="ahw")


def gate(g, cx):
    g.line(cx - 8, BY + 56, cx - 8, BY + 96, GREEN, 3)
    g.line(cx + 8, BY + 56, cx + 8, BY + 96, GREEN, 3)
    g.t(cx, BY + 122, "安全联锁闸门", 12, GREEN, anchor="middle", weight="600")
    g.t(cx, BY + 140, "三项全绿才可启动", 11, T2, anchor="middle")


def legend(g, y, extra):
    g.line(40, y, g.w - 40, y, SEP, 1)
    g.t(40, y + 24, "实线粗箭头＝主链顺序　　绿虚线折回＝调优回环　　淡绿虚线双向＝流程与知识库之间：上行取知识（填参数 / 抽判据 / 套模板），下行存产物（沉淀经验 / 归档报告）", 12, T2)
    g.t(40, y + 48, "墨绿双竖线＝安全联锁闸门，卡在「测试需求确认」与「启动测试」之间：联锁项全满足、预检全通过、现场安全总闸已开，启动按钮才可点。", 12, T2)
    g.t(40, y + 72, extra, 12, T2)


def build(variant):
    if variant == "A":
        g = Fig("fig2v3A_知识库层带_保留编号", 1540, 820)
        g.t(40, 52, "五流程主线与知识库层带　保留原编号，1 号位空出", 18, GREEN, weight="600")
        g.t(40, 78, "② ~ ⑥ 为流程序号，沿用原图不动；知识库不再占流程序号，下沉为承托五条流程的基础模块", 12, T3)
        xs = [270, 500, 836, 1066, 1296]
        nums = ["②", "③", "④", "⑤", "⑥"]
        # 空出的 1 号位（暗红一处）
        g.rect(40, BY, BW, BH, RED, 1.5, "none", 6, "6 4")
        g.t(138, BY + 44, "① 位空出", 16, RED, anchor="middle", weight="600", box=BW - 20)
        g.t(138, BY + 76, "知识库原占此位", 11, T2, anchor="middle", box=BW - 16)
        g.t(138, BY + 100, "现移出流程列", 11, T2, anchor="middle", box=BW - 16)
        g.t(138, BY + 124, "下沉为基础模块", 11, T2, anchor="middle", box=BW - 16)
        # 下沉箭头（暗红第二处）
        g.line(138, BY + BH + 6, 138, BAND_Y - 6, RED, 1.5, dash="6 4", me="ahr")
        band(g, 40, 1500)
        extra = "暗红＝本版唯一的变化点：原 ① 知识库管理已移出流程列。两版差别只在编号，层带与连线完全相同。"
    else:
        g = Fig("fig2v3B_知识库层带_重排编号", 1540, 820)
        g.t(40, 52, "五流程主线与知识库层带　流程重排为 ① ~ ⑤", 18, GREEN, weight="600")
        g.t(40, 78, "知识库不再占流程序号，下沉为承托五条流程的基础模块；其余五个流程顺次重排，不留空位", 12, T3)
        xs = [154, 384, 720, 950, 1180]
        nums = ["①", "②", "③", "④", "⑤"]
        band(g, 40, 1500, "原 ① 知识库管理：已移出流程列")
        extra = "暗红＝本版唯一的变化点标注：原 ① 知识库管理已移出流程列。两版差别只在编号，层带与连线完全相同。"

    for x, num, (name, sub, ti, to) in zip(xs, nums, FLOWS):
        flow_box(g, x, num, name, sub, ti, to)
        link(g, x + BW / 2)

    # 主链箭头
    mid = BY + BH / 2
    for i in range(4):
        a, b = xs[i] + BW, xs[i + 1]
        g.line(a + 4, mid, b - 8, mid, GREEN, 2, me="ah")
    # 闸门卡在第 2 与第 3 个流程之间
    gate(g, (xs[1] + BW + xs[2]) / 2)
    # 调优回环：第 4 个流程回到第 3 个
    c4, c3 = xs[3] + BW / 2, xs[2] + BW / 2
    g.poly([(c4, BY - 6), (c4, BY - 54), (c3, BY - 54), (c3, BY - 8)], GREEN, 2, dash="6 4", me="ah")
    g.t((c4 + c3) / 2, BY - 64, "有未达标项 → 改参数 → 重跑", 12, GREEN, anchor="middle", weight="600")

    legend(g, BAND_Y + BAND_H + 36, extra)
    return g.save()


if __name__ == "__main__":
    for v in ("A", "B"):
        build(v)
    print("\n".join(WARN) if WARN else "无超宽告警")
