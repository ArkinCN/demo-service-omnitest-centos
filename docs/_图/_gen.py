# -*- coding: utf-8 -*-
"""手排 SVG 生成器：通用 Agent 测试系统 v2.0 六张图。"""
import os

OUT = "docs/20260919-通用Agent测试系统v2.0/_图"
F = "Microsoft YaHei, Noto Sans CJK SC, WenQuanYi Zen Hei, sans-serif"

GREEN = "#2E5E45"
GREEN_W = "#A8C5B5"
GREEN_D = "#1F4232"
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
    """粗略文本宽度：CJK 按 1em，拉丁按 0.55em。"""
    w = 0.0
    for c in s:
        w += fs if ord(c) > 0x2E80 else fs * 0.55
    return w


class Fig:
    def __init__(self, name, w, h):
        self.name, self.w, self.h = name, w, h
        self.p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                  DEFS, f'<rect width="{w}" height="{h}" fill="#FFFFFF"/>']

    def rect(self, x, y, w, h, stroke=GREEN, sw=1.5, fill="none", rx=6, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def t(self, x, y, s, fs=12, fill=T1, anchor="start", weight="400", box=None):
        if box is not None:
            width = tw(s, fs)
            if width > box:
                WARN.append(f"[{self.name}] 文本超宽 {width:.0f}>{box}: {s[:30]}")
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.p.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="{F}" font-size="{fs}" font-weight="{weight}" fill="{fill}">{s}</text>')

    def line(self, x1, y1, x2, y2, stroke=SEP, sw=1, dash=None, me=None, ms=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        a = f' marker-end="url(#{me})"' if me else ""
        b = f' marker-start="url(#{ms})"' if ms else ""
        self.p.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{sw}"{d}{a}{b}/>')

    def poly(self, pts, stroke=GREEN, sw=2, dash=None, me=None, ms=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        a = f' marker-end="url(#{me})"' if me else ""
        b = f' marker-start="url(#{ms})"' if ms else ""
        s = " ".join(f"{x},{y}" for x, y in pts)
        self.p.append(f'<polyline points="{s}" fill="none" stroke="{stroke}" stroke-width="{sw}"{d}{a}{b}/>')

    def head(self, title, sub):
        self.t(40, 52, title, 18, GREEN, weight="600")
        self.t(40, 78, sub, 12, T3)

    def save(self):
        self.p.append("</svg>")
        path = os.path.join(OUT, self.name + ".svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.p))
        return path


# ============================== fig1 ==============================
def fig1():
    g = Fig("fig1_页面四大块", 1320, 980)
    g.head("主界面四块封顶　A 顶栏 · B 左栏 24% · C 右上面板 · D 右下对话",
           "比例按 1600 × 1000 基准；圈码为块内层级，最深到四级，第五级换弹层、独立页或抽屉")

    X0, XR = 48, 1272
    # ---- A 区 ----
    g.rect(X0, 100, 1224, 142)
    g.line(X0, 148, XR, 148, SEP, 1)
    g.line(X0, 198, XR, 198, SEP, 1)
    g.t(64, 127, "① 产品选择器", 13, T1, weight="600")
    g.t(176, 127, "② 场景 › ③ 子类 › ④ 产品类型　选中即载入场景包", 11, T2, box=560)
    g.t(XR - 16, 127, "① 全局状态　② 场景包版本 · 台架占用 · 联锁总闸 · 账号", 11, T2, anchor="end")
    g.t(64, 178, "① 六流程标签", 12, T1, weight="600")
    tabs = ["1 知识库管理", "2 初始化配置", "3 测试需求确认", "4 启动测试及结果分析", "5 调优确认及运行", "6 测试报告及产出"]
    for i, s in enumerate(tabs):
        x = 190 + i * 168
        cur = (i == 3)
        g.rect(x, 158, 160, 30, GREEN if cur else GREEN_W, 1.5 if cur else 1, TINT if cur else "none", rx=4)
        g.t(x + 80, 178, s, 11, T1 if cur else T2, anchor="middle", weight="600" if cur else "400", box=150)
    g.t(64, 226, "① 动作条", 12, T1, weight="600")
    g.t(140, 226, "② 当前流程 2~4 个按钮，第一个为主动作，破坏性动作用暗红", 11, T2, box=620)
    acts = [("启动测试", GREEN, "600"), ("预检自检", GREEN_W, "400"), ("停止", GREEN_W, "400"), ("急停", RED, "600")]
    for i, (s, c, wt) in enumerate(acts):
        x = 874 + i * 98
        g.rect(x, 206, 88, 26, c, 1.5, "none", rx=4)
        g.t(x + 44, 224, s, 11, T1 if c != RED else RED, anchor="middle", weight=wt, box=80)

    # ---- B 区 ----
    g.rect(X0, 258, 294, 620)
    g.t(64, 286, "B 区 · 参数与确认", 14, GREEN, weight="600")
    g.t(64, 304, "宽 384（24%）· 随流程整屏更换", 11, T3, box=270)
    g.line(64, 314, 326, 314, SEP, 1)
    btree = [(0, "① 输入清单（定高不滚动）"), (1, "② 行：编号 · 名称 · 状态 · 定位"),
             (0, "① 参数分组（手风琴）"), (1, "② 参数子组"), (2, "③ 参数行"),
             (3, "④ 值控件 · 来源标记 · 依据链接"),
             (0, "① 确认条（常驻底部）"), (1, "② 完成度 · 校验一行 · 确认按钮")]
    for i, (lv, s) in enumerate(btree):
        g.t(64 + lv * 16, 340 + i * 28, s, 12, T1 if lv == 0 else T2, box=326 - (64 + lv * 16))
    g.line(64, 588, 326, 588, SEP, 1)
    for i, s in enumerate(["确认是有状态的：确认后该分组转", "只读并显示确认人与「已锁定」；", "解除确认需显式操作并记一条审计。"]):
        g.t(64, 612 + i * 20, s, 11, T3, box=266)
    for i, s in enumerate(["流程 4 的启动动作，检查的就是", "流程 2 / 3 的确认状态与联锁状态。"]):
        g.t(64, 692 + i * 20, s, 11, T3, box=266)

    # ---- C 区 ----
    g.rect(358, 258, 914, 390)
    g.t(374, 286, "C 区 · 面板", 14, GREEN, weight="600")
    g.t(374, 304, "高 496　网格 / 画布两种视图，同一批卡片两种摆法，默认网格", 11, T3, box=700)
    g.line(374, 314, 1256, 314, SEP, 1)
    g.t(374, 336, "① 视图切换：网格 / 画布　　① 卡片槽 ×4　② 卡片从卡片库（十五张，分四类）里换", 11, T2, box=720)
    cards = [("时序曲线", "多通道实时与回放"), ("判定卡", "判据逐条给结论与实测值"),
             ("工作流画布", "步骤图，当前步高亮"), ("安全联锁状态盘", "逐条联锁项的满足状态")]
    for i, (a, b) in enumerate(cards):
        x = 374 + (i % 2) * 364
        y = 348 + (i // 2) * 138
        g.rect(x, y, 350, 126)
        g.t(x + 16, y + 30, a, 13, T1, weight="600", box=318)
        g.line(x + 16, y + 44, x + 334, y + 44, SEP, 1)
        g.t(x + 16, y + 68, b, 11, T2, box=318)
        g.t(x + 16, y + 92, "卡头 32　卡体定高不滚动", 11, T3, box=318)
        g.t(x + 16, y + 112, "超出截断，点「展开查看」进放大态", 11, T3, box=318)
    g.t(374, 634, "③ 卡内视图切换 / 时间轴 / 图层　④ 放大态：全屏 · 独立窗口 · 远程会话", 11, T2, box=720)
    # 工具条
    g.rect(1120, 318, 136, 292, GREEN_W, 1)
    g.t(1188, 334, "① 竖向工具条", 11, GREEN, anchor="middle", weight="600", box=128)
    g.t(1188, 350, "② 四组　③ 按钮 + 状态点", 9, T3, anchor="middle", box=128)
    for i, (a, b) in enumerate([("数据采集", "取波形 · 取读数"), ("环境与激励", "调压 · 调速 · 控温"),
                                ("对象调试", "写参数 · 烧录 · 串口"), ("会话与远程", "远程桌面 · 命令行")]):
        y = 358 + i * 63
        if i:
            g.line(1128, y - 4, 1248, y - 4, SEP, 1)
        g.t(1188, y + 22, a, 11, T1, anchor="middle", weight="600", box=128)
        g.t(1188, y + 42, b, 10, T3, anchor="middle", box=128)

    # ---- D 区 ----
    g.rect(358, 664, 914, 214)
    g.t(374, 692, "D 区 · 对话（测试副驾）", 14, GREEN, weight="600")
    g.t(374, 710, "高 328　文字 + 语音；不使用人格化昵称，取消「自动调试」总开关，改为逐动作确认", 11, T3, box=880)
    g.line(374, 720, 1256, 720, SEP, 1)
    dtree = [(0, "① 消息流"), (1, "② 文本 / 工具调用卡 / 判定卡 / 参数建议卡"),
             (2, "③ 依据引用（默认收起）"), (3, "④ 原文定位：文档片段 · 规程条目 · 历史案例"),
             (0, "① 输入栏"), (1, "② 快捷指令片 3~5 个 · 多行文本（上限四行）· 语音按钮")]
    for i, (lv, s) in enumerate(dtree):
        g.t(374 + lv * 20, 744 + i * 24, s, 12, T1 if lv == 0 else T2, box=880)

    g.line(48, 908, 1272, 908, SEP, 1)
    g.t(48, 932, "①②③④ 为块内层级：任一块内最深到四级，第五级必须换承载方式。", 12, T2)
    g.t(48, 956, "淡绿底＝当前选中项；暗红＝破坏性动作（急停）。四块之间只靠留白与 1px 细线分隔，卡面无阴影。", 12, T2)
    return g.save()


# ============================== fig2 ==============================
def fig2():
    """五流程主线 + 知识库层带（第三轮改版，替代原六流程主线图）。"""
    g = Fig("fig2_五流程主线与知识库层带", 1540, 880)
    g.t(40, 52, "五流程主线与知识库层带　主线人一步步走，知识库在底下承托", 18, GREEN, weight="600")
    g.t(40, 78, "1 ~ 5 为流程序号；知识库不编号，下沉为五条流程共用的基础模块，与主线之间只有「取」与「回」两组通道", 12, T3)

    MX0, MX1, MY, MH = 40, 1500, 104, 290
    BW, BH, BY = 196, 152, 210
    xs = [60, 366, 672, 978, 1284]
    mid = BY + BH / 2

    # 主线层
    g.rect(MX0, MY, MX1 - MX0, MH, GREEN_W, 1)
    g.t(MX0 + 20, MY + 30, "主线　人一步步走", 14, GREEN, weight="600")

    flows = [("1 初始化配置", "", "入　产品文档与工程", "出　锁定配置与联锁实例"),
             ("2 测试需求确认", "", "入　标准与工作流模板", "出　冻结的需求基线"),
             ("3 启动测试", "及结果分析", "入　配置快照与需求基线", "出　轮次产物与判定表"),
             ("4 调优确认", "及运行", "入　未达标项与经验库", "出　参数改动与重跑指令"),
             ("5 测试报告", "及产出", "入　模板与全部产物", "出　报告成品与归档记录")]
    for x, (a, b, i_, o_) in zip(xs, flows):
        cx = x + BW / 2
        g.rect(x, BY, BW, BH)
        g.t(cx, BY + 34, a, 17, T1, anchor="middle", weight="600", box=BW - 20)
        if b:
            g.t(cx, BY + 54, b, 11, T3, anchor="middle", box=BW - 20)
        g.line(x + 14, BY + 68, x + BW - 14, BY + 68, SEP, 1)
        g.t(cx, BY + 92, i_, 11, T2, anchor="middle", box=BW - 16)
        g.t(cx, BY + 122, o_, 11, T2, anchor="middle", box=BW - 16)

    # 主链箭头
    for i in range(4):
        g.line(xs[i] + BW + 4, mid, xs[i + 1] - 8, mid, GREEN, 2, me="ah")

    # 安全联锁闸门：全图唯一一处暗红
    gx = (xs[1] + BW + xs[2]) / 2
    for dx in (-8, 8):
        g.line(gx + dx, BY + 56, gx + dx, BY + 96, RED, 3)
    g.t(gx, BY + 122, "安全联锁闸门", 12, RED, anchor="middle", weight="600", box=xs[2] - xs[1] - BW - 4)
    g.t(gx, BY + 140, "联锁全满足才放行", 11, T2, anchor="middle", box=xs[2] - xs[1] - BW - 4)

    # 4 ⇄ 3 调优回环（走框上方，不与主链相交）
    c4, c3 = xs[3] + BW / 2, xs[2] + BW / 2
    g.poly([(c4, BY - 6), (c4, 176), (c3, 176), (c3, BY - 8)], GREEN, 2, dash="6 4", me="ah")
    g.t((c3 + c4) / 2, 166, "有未达标项 → 改参数 → 重跑", 12, GREEN, anchor="middle", weight="600")

    # 主线与层带之间：上下两组通道
    BAND_Y, BAND_H = 500, 250
    g.line(380, 486, 380, 404, GREEN, 2, me="ah")
    g.t(400, 438, "取", 14, GREEN, weight="600")
    g.t(424, 438, "五条流程向知识库要东西", 11, T3)
    g.t(400, 462, "填参数 / 抽判据 / 套模板", 11, T2)
    g.line(1000, 404, 1000, 486, GREEN, 2, me="ah")
    g.t(1020, 438, "回", 14, GREEN, weight="600")
    g.t(1044, 438, "五条流程把用出来的东西送回", 11, T3)
    g.t(1020, 462, "沉淀经验 / 归档报告", 11, T2)

    # 知识库层带
    g.rect(MX0, BAND_Y, MX1 - MX0, BAND_H, GREEN, 1.5)
    g.t(MX0 + 20, BAND_Y + 32, "基础模块 · 知识库", 15, GREEN, weight="600")
    g.t(MX0 + 196, BAND_Y + 32, "不编号，五条流程共用；三轴正交，一条知识同时落在三个轴上", 11, T2)

    axes = [("归属轴", "挂在哪个产品下", "场景 › 子类 › 产品类型，三级，已实装"),
            ("来源轴", "谁产生的", "文档类外部上传；经验类系统自己长出来"),
            ("用途轴", "回答什么问题", "产品说明书 / 测试需求 / 工艺，本轮新增")]
    aw = (MX1 - MX0 - 40 - 56) / 3
    for i, (a, b, c) in enumerate(axes):
        x = MX0 + 20 + i * (aw + 28)
        g.rect(x, BAND_Y + 48, aw, 96, GREEN_W, 1, TINT, rx=4)
        g.t(x + 16, BAND_Y + 76, a, 14, GREEN, weight="600")
        g.t(x + 16 + tw(a, 14) + 12, BAND_Y + 76, b, 11, T3)
        g.t(x + 16, BAND_Y + 106, c, 11, T2, box=aw - 32)

    g.line(MX0 + 20, BAND_Y + 168, MX1 - 20, BAND_Y + 168, SEP, 1)
    g.t(MX0 + 20, BAND_Y + 210, "转化流水线", 13, GREEN, weight="600")
    steps = ["识别", "抽取", "切片", "结构化", "索引"]
    sw_, sy = 150, BAND_Y + 188
    for i, s in enumerate(steps):
        x = 180 + i * (sw_ + 26)
        g.rect(x, sy, sw_, 34, GREEN_W, 1, "none", rx=4)
        g.t(x + sw_ / 2, sy + 23, s, 12, T1, anchor="middle", box=sw_ - 12)
        if i:
            g.line(x - 22, sy + 17, x - 6, sy + 17, GREEN_W, 1, me="ahw")
    g.t(180 + 5 * sw_ + 4 * 26 + 24, sy + 23, "转化完才能被五条流程检索到", 11, T2)

    # 图注
    ly = BAND_Y + BAND_H + 36
    g.line(40, ly, 1500, ly, SEP, 1)
    g.t(40, ly + 24, "实线粗箭头＝主线顺序　　绿虚线折回＝调优回环（4 回 3，有未达标项就改参数重跑）　　中间两条粗箭头＝主线与知识库之间的取与回", 12, T2)
    g.t(40, ly + 48, "暗红双竖线＝安全联锁闸门，卡在「2 测试需求确认」与「3 启动测试及结果分析」之间：联锁项全满足、预检全通过、现场安全总闸已开，启动按钮才可点。", 12, T2)
    g.t(40, ly + 72, "层带不编号：知识库不是一条流程，是五条流程共用的底座；每个流程页 B 区顶部都有它的上传入口与筛选后的条目数。", 12, T2)
    return g.save()


# ============================== fig3 ==============================
def fig3():
    g = Fig("fig3_知识库体系", 1480, 800)
    g.head("知识库体系　两大类知识 × 三级分类树",
           "左：按知识来源分两大类；右：按对象归属分三级，不设第四级，二级即使只有一个分类也照常显示")

    # 左：两大类
    g.t(40, 118, "两大类知识　按来源分", 15, GREEN, weight="600")
    # A 文档性质
    g.rect(40, 134, 660, 186)
    g.t(56, 164, "文档性质　别人给的，基本不变，换版本才更新", 13, T1, weight="600", box=628)
    ch = [("上传 / 导入", "单文件 · 批量 · 目录"), ("五阶段转化", "识别→抽取→切片→结构化→索引"), ("可取字段的形态", "切片 · 参数表 · 判据表")]
    for i, (a, b) in enumerate(ch):
        x = 56 + i * 210
        g.rect(x, 178, 180, 54, GREEN_W, 1, rx=4)
        g.t(x + 90, 200, a, 12, T1, anchor="middle", weight="600", box=170)
        g.t(x + 90, 220, b, 9, T3, anchor="middle", box=172)
        if i:
            g.line(x - 28, 205, x - 6, 205, GREEN, 1.5, me="ah")
    for i, s in enumerate(["对象类　产品描述 · 驱动与固件 · 功能清单 · 原理图",
                           "规则类　标准与规范 · 测试规程",
                           "产出类　报告模板 · 历史报告"]):
        g.t(56, 258 + i * 22, s, 12, T2, box=628)
    # B 经验性质
    g.rect(40, 340, 660, 186)
    g.t(56, 370, "经验性质　自己用出来的，一直在长", 13, T1, weight="600", box=628)
    ch2 = [("对话与操作", "六个流程里一键沉淀"), ("沉淀为条目", "四个类型，分两组"), ("三种呈现", "标签树 · 时间线 · 引用榜")]
    for i, (a, b) in enumerate(ch2):
        x = 56 + i * 210
        g.rect(x, 384, 180, 54, GREEN_W, 1, rx=4)
        g.t(x + 90, 406, a, 12, T1, anchor="middle", weight="600", box=170)
        g.t(x + 90, 426, b, 9, T3, anchor="middle", box=172)
        if i:
            g.line(x - 28, 411, x - 6, 411, GREEN, 1.5, me="ah")
    for i, s in enumerate(["过程记录　问答 · 调参决策",
                           "问题记录　失败案例 · 判据修正",
                           "三个视图　标签树按维度筛 · 时间线看一个对象的全过程 · 引用榜找最有用的"]):
        g.t(56, 464 + i * 22, s, 12, T2, box=628)
    g.t(40, 556, "两类共用同一棵分类树：每个三级节点下固定挂两个抽屉 —— 文档、经验。", 12, T2)

    # 右：三级分类树
    g.t(740, 118, "三级分类树　场景 › 子类 › 产品类型", 15, GREEN, weight="600")
    g.rect(740, 140, 180, 40, GREEN, 1.5, rx=4)
    g.t(830, 165, "知识库根", 12, T1, anchor="middle", weight="600", box=164)

    def node(x, y, w, s, stroke=GREEN_W, fill="none", dash=None, bold="400"):
        g.rect(x, y, w, 40, stroke, 1, fill, rx=4, dash=dash)
        g.t(x + 10, y + 25, s, 12, T1, weight=bold, box=w - 20)

    rows_l1 = [(200, "一级 · 场景　电机"), (372, "一级 · 场景　汽车"), (436, "一级 · 场景　通用")]
    g.line(756, 180, 756, 220, GREEN_W, 1)
    g.poly([(756, 220), (756, 456)], GREEN_W, 1)
    for y, s in rows_l1:
        node(790, y, 200, s)
        g.line(756, y + 20, 786, y + 20, GREEN_W, 1)
    node(1010, 200, 200, "二级 · 子类　家电电机")
    node(1010, 372, 200, "二级 · 子类　车身电机")
    node(1010, 436, 200, "二级 · 子类　通用规范")
    for y in (220, 392, 456):
        g.line(990, y, 1006, y, GREEN_W, 1)
    node(1230, 200, 210, "三级 · 产品类型　散热风扇", GREEN, TINT, bold="600")
    node(1230, 254, 210, "三级　吸尘器（占位）")
    node(1230, 308, 210, "三级　吹风筒（占位）")
    node(1230, 372, 210, "三级　玻璃升降器（已选）", "#2E5E45", "none")
    node(1230, 436, 210, "三级　安全与电气通用")
    g.poly([(1220, 220), (1220, 328)], GREEN_W, 1)
    for y in (220, 274, 328):
        g.line(1210, y, 1226, y, GREEN_W, 1)
        g.line(1220, y, 1226, y, GREEN_W, 1)
    for y in (392, 456):
        g.line(1210, y, 1226, y, GREEN_W, 1)
    for i, s in enumerate(["散热风扇是第一个完整节点：FU6832 驱动板，文档与经验素材齐全，也是这套结构的验证样本。",
                           "汽车侧已定为电动玻璃升降器（含防夹），第二个场景包已生成。",
                           "具体型号、批次、样机编号不进分类树，放流程 2 初始化配置的参数里。"]):
        g.t(740, 500 + i * 22, s, 12, T2)

    # 底部工具带
    g.rect(40, 600, 1400, 92)
    g.t(56, 628, "增删改查　两类知识共用同一套操作", 14, GREEN, weight="600")
    g.line(56, 640, 1424, 640, SEP, 1)
    ops = ["增　上传文档 · 新建分类 · 沉淀为经验", "删　删条目与分类，需二次确认",
           "改　改分类归属 · 编辑标签 · 重跑转化", "查　关键词 + 四维筛选 + 引用榜排序"]
    for i, s in enumerate(ops):
        x = 56 + i * 344
        g.t(x, 670, s, 12, T2, box=330)
        if i:
            g.line(x - 20, 648, x - 20, 680, SEP, 1)
    g.t(40, 730, "四个筛选维度：场景与产品（来自三级体系）· 流程（六个）· 问题类型 · 结论。", 12, T2)
    g.t(40, 754, "经验的三种呈现是同一批数据的三个视图，不是三份数据。", 12, T2)
    return g.save()


# ============================== fig4 ==============================
def fig4():
    g = Fig("fig4_场景包结构", 1480, 1010)
    g.head("场景包结构　换场景只换包，系统侧一行代码不改",
           "中间列是通用结构，左右两列是同一结构在两个场景下的具体内容")

    # 系统侧
    g.rect(40, 104, 1400, 92)
    g.t(56, 130, "系统侧　与行业无关，装好不动", 13, GREEN, weight="600")
    for i, s in enumerate(["界面四块", "工作流引擎", "执行器", "报告引擎", "测试副驾"]):
        x = 56 + i * 272
        g.rect(x, 140, 250, 44, GREEN_W, 1, rx=4)
        g.t(x + 125, 168, s, 12, T1, anchor="middle", box=236)
    g.line(740, 196, 740, 244, GREEN, 2, me="ah")
    g.t(756, 226, "加载场景包", 12, GREEN, weight="600")

    cols = [(40, 440), (500, 440), (1000, 440)]
    TOP, ROWH, N = 250, 70, 9
    BOT = 306 + ROWH * N
    g.rect(40, TOP, 440, BOT - TOP)
    g.rect(500, TOP, 440, BOT - TOP)
    g.rect(1000, TOP, 440, BOT - TOP, GREEN_W, 1, dash="6 4")
    g.p.insert(3, f'<rect x="40" y="250" width="440" height="56" rx="6" fill="{TINT}"/>')

    g.t(60, 276, "峰岹散热风扇包", 13, T1, weight="600")
    g.t(60, 296, "motor.cooling-fan.fortior-fu6832　素材齐全", 10, T2)
    g.t(520, 276, "场景包通用结构　九样东西", 13, GREEN, weight="600")
    g.t(520, 296, "一个场景包对应三级分类树上的一个产品类型节点", 10, T2)
    g.t(1020, 276, "汽车包", 13, RED, weight="600")
    g.t(1020, 296, "automotive.body-motor.window-regulator　第二个包已生成", 10, T2)
    for x, w in cols:
        g.line(x, 306, x + w, 306, SEP, 1)

    rows = [("① 分类定位", "一级场景 / 二级子类 / 三级产品类型", "电机 › 散热风扇 › FU6832 驱动板", "", "汽车 › 车身电机 › 玻璃升降器"),
            ("② 文档集", "八个文档类型的文件与抽取模板", "FU6832 数据手册 · 三套原理图", "Keil 工程与 Customer.h · 11 份经验文档", "QC/T 626 · GB 11552 §4.8 · ISO 16750 · 83 份"),
            ("③ 参数模板", "本体属性 / 驱动固件 / 功能清单 / 控制参数", "Customer.h 解析出 202 条宏", "圈定 70 条为可调参数", "47 项属性 · 59 个控制参数（防夹阈值 100 N 等）"),
            ("④ 安全联锁模板", "联锁项定义 · 默认阈值 · 触发动作", "人员离场 · 母线过压 18 V", "跑完必停机 · PASS 基线禁改", "防夹试验棒刚度 · 堵转 30 s · 人员离场"),
            ("⑤ 工作流模板库", "六类节点：设置 · 激励 · 采集 · 判定 · 控制流 · 数据处理", "五十八个主流程 + 九个子流程", "启停回归 · 顺风重启十二档", "四条示例：升降循环 · 堵转 · 防夹 · 耐久"),
            ("⑥ 判据集", "指标 · 阈值 · 等级 · 整体结论规则", "频率比 2 ± 0.05（致命）", "启动成功率 · 稳态偏差 · 26 条", "上升速度 80–160 mm/s · 防夹 100 N 前回缩 · 34 条"),
            ("⑦ 报告模板与字段映射", "模板文件 + 字段到数据源的映射表", "Motor Checklist 公用模板（xlsm）", "字段映射参照已填充样例 report.xlsm", "FMVSS 118 合规报告：六节 + 13 字段"),
            ("⑧ 设备与工具集", "设备记录 · 工具定义 · 四种接入形态", "示波器 · 程控电[源] · 逆风风扇", "编译器与烧录器 · 台架机 SSH", "拉力计 · 测速 · 程控电源（待登记）"),
            ("⑨ 界面配置", "输入清单 · 默认卡片组合 · 画布版式", "六个流程各一套", "", "同一套，换包不换界面")]
    for i, (c1, c2, l1, l2, r1) in enumerate(rows):
        top = 306 + i * ROWH
        g.t(520, top + 28, c1, 13, T1, weight="600", box=400)
        g.t(520, top + 50, c2, 11, T2, box=400)
        g.t(60, top + 28, l1, 12, T1, box=400)
        if l2:
            g.t(60, top + 50, l2, 11, T2, box=400)
        g.t(1020, top + 28, r1, 12, T3, box=400)
        if i:
            for x, w in cols:
                g.line(x, top, x + w, top, SEP, 1)

    g.t(40, BOT + 34, "换场景只换中间这套结构里装的东西，系统侧五个部件一行代码不改。加一个新场景共八步，其中六步是纯配置。", 12, T2)
    g.t(40, BOT + 58, "只有两件事可能需要写代码：新的工作流节点实现、新的设备驱动。", 12, RED, weight="600")
    return g.save()


# ============================== fig5 ==============================
def fig5():
    g = Fig("fig5_系统分层", 1480, 1010)
    g.head("系统分层　浏览器 → 服务端 → 台架侧 → 硬件",
           "系统基于浏览器，不装客户端；单机设备的四种接入形态用四条不同线型标在台架侧与硬件之间")

    # L1
    g.rect(40, 104, 1400, 118)
    g.t(56, 130, "① 浏览器　网页四块，不装客户端", 13, GREEN, weight="600")
    for i, (a, b) in enumerate([("A 顶栏", "产品选择 · 六流程标签 · 动作条"), ("B 左栏", "参数配置与确认"),
                                ("C 右上", "面板卡片与竖向工具条"), ("D 右下", "测试副驾对话")]):
        x = 56 + i * 344
        g.rect(x, 144, 328, 62, GREEN_W, 1, rx=4)
        g.t(x + 164, 170, a, 13, T1, anchor="middle", weight="600", box=312)
        g.t(x + 164, 192, b, 11, T2, anchor="middle", box=312)
    g.line(740, 224, 740, 258, GREEN, 2, me="ah", ms="ah")
    g.t(756, 248, "HTTP / WebSocket", 11, T2)

    # L2
    g.rect(40, 262, 1400, 178)
    g.t(56, 288, "② 服务端", 13, GREEN, weight="600")
    g.line(748, 302, 748, 424, SEP, 1)
    g.t(56, 330, "FastAPI 应用服务", 13, GREEN, weight="600")
    for i, s in enumerate(["用户与权限　账号 · 三档权限 · 审计留痕",
                           "知识库　上传 · 五阶段转化 · 检索服务",
                           "场景包与会话　包加载 · 流程状态机 · 产物留档"]):
        g.t(56, 358 + i * 24, s, 12, T2, box=660)
    g.rect(768, 312, 200, 26, GREEN_D, 1, GREEN_D, rx=4)
    g.t(778, 330, "DeepSeek Harness 运行时", 13, "#FFFFFF", weight="600", box=180)
    for i, s in enumerate(["技能包　把规程与判据转成可调用技能",
                           "Hook　动作前置校验：联锁 · 权限 · 闸门",
                           "MCP 桥接　把设备工具挂成统一接口"]):
        g.t(768, 358 + i * 24, s, 12, T2, box=650)
    g.line(740, 442, 740, 476, GREEN, 2, me="ah", ms="ah")
    g.t(756, 466, "设备服务 API / SSH 网关", 11, T2)

    # L3
    g.rect(40, 480, 1400, 220)
    g.t(56, 506, "③ 台架侧　台架机与单机设备所在的那几台机器", 13, GREEN, weight="600")
    for i, (a, b) in enumerate([("设备服务", "台架机上的统一硬件接口，常驻采集出口"),
                                ("桌面版工具端口", "只能在单机上跑的原生软件，网页不重写它"),
                                ("SSH 网关", "凭据只存服务端，浏览器不直连远程会话")]):
        x = 56 + i * 460
        g.rect(x, 520, 440, 76, GREEN_W, 1, rx=4)
        g.t(x + 220, 550, a, 13, T1, anchor="middle", weight="600", box=420)
        g.t(x + 220, 574, b, 11, T2, anchor="middle", box=424)
    g.t(56, 634, "凡只能在某台机器上跑的设备，界面不重写它的控制面板，而是把那台机器的会话拉过来。", 12, T2)
    g.t(56, 658, "接入形态由场景包的设备记录声明。峰岹场景里示波器同时用三种：拉数值画曲线、开命令行跑深存储脚本、切远程桌面调游标。", 12, T2)
    g.t(56, 682, "凭据只存服务端，浏览器侧不管理任何凭据。", 12, RED, weight="600")

    # 四条接入形态
    styles = [(220, GREEN, 2, None, "数据拉取", "只取数值与波形，不控设备"),
              (564, GREEN, 1.5, "8 5", "命令行会话", "远程登录跑脚本 · 取文件 · 查日志"),
              (908, GREEN, 1.5, "2 4", "远程桌面内嵌", "卡内实时画面，放大态可交互"),
              (1252, GREEN_W, 1.5, "12 4 2 4", "独立窗口跳转", "新窗口拉起，网页侧接收回传产物")]
    for x, c, sw, dash, a, b in styles:
        g.line(x, 702, x, 754, c, sw, dash=dash, me="ah" if c == GREEN else "ahw")
        g.t(x + 12, 722, a, 11, T1, weight="600")
        g.t(x + 12, 740, b, 10, T3)

    # L4
    g.rect(40, 760, 1400, 118)
    g.t(56, 786, "④ 硬件　台架上的真实设备", 13, GREEN, weight="600")
    for i, (a, b) in enumerate([("电机与风洞台架", "被测风扇 · 逆风风扇 · 红外测速"), ("示波器", "四通道，只有单机图形软件"),
                                ("程控电源", "可编程调压与限流"), ("调试器与烧录器", "编译烧录 · 寄存器读写")]):
        x = 56 + i * 344
        g.rect(x, 800, 328, 62, GREEN_W, 1, rx=4)
        g.t(x + 164, 826, a, 13, T1, anchor="middle", weight="600", box=312)
        g.t(x + 164, 848, b, 11, T2, anchor="middle", box=312)

    g.line(40, 916, 1440, 916, SEP, 1)
    g.t(40, 940, "线型即接入形态：实线＝数据拉取　长虚线＝命令行会话　点线＝远程桌面内嵌　点划淡线＝独立窗口跳转。", 12, T2)
    g.t(40, 964, "四种形态按设备能力选，同一台设备可以同时用多种；接哪一种写在场景包的设备记录里，不写在前端。", 12, T2)
    return g.save()


# ============================== fig6 ==============================
def fig6():
    g = Fig("fig6_副驾边界", 1280, 880)
    g.head("副驾的边界　能做什么，什么必须人点",
           "统一规则：副驾可以读、可以算、可以建议、可以写草稿；凡是会改变被测对象状态或落盘生效的动作，必须人点按钮")

    g.rect(40, 104, 580, 380)
    g.p.insert(3, f'<rect x="40" y="104" width="580" height="44" rx="6" fill="{TINT}"/>')
    g.t(60, 132, "副驾可以自己做", 14, GREEN, weight="600")
    left = [("读", "检索知识库 · 解析文档 · 读设备读数与波形", "只读工具，调用不需要人逐次确认"),
            ("算", "曲线特征分析 · 逐条对判据 · 影响面检查", "计算不改变任何对象的状态"),
            ("建议", "参数候选与排序 · 工作流模板 · 分类归属", "建议只进队列，不自动生效"),
            ("写草稿", "结论段 · 异常说明 · 经验条目 · 报告字段", "草稿标「待复核」，不可直接导出")]
    for i, (a, b, c) in enumerate(left):
        y = 186 + i * 74
        g.t(60, y, a, 13, GREEN, weight="600", box=70)
        g.t(136, y, b, 12, T1, box=470)
        g.t(136, y + 22, c, 11, T3, box=470)
        if i:
            g.line(60, y - 32, 600, y - 32, SEP, 1)

    g.rect(660, 104, 580, 380)
    g.t(680, 132, "必须人点，副驾不能碰", 14, RED, weight="600")
    g.line(680, 148, 1220, 148, SEP, 1)
    right = [("落盘生效", "提交并锁定 · 冻结需求基线 · 写回参数 · 导出并归档", "副驾可备好草稿与差异，按钮由人点"),
             ("控设备", "启动 · 停止 · 急停 · 编译烧录", "有物理后果，人点之外还须联锁全绿"),
             ("删除与豁免", "删已有条目 · 联锁豁免 · 解除确认", "需二次确认并记一条审计")]
    for i, (a, b, c) in enumerate(right):
        y = 186 + i * 74
        g.t(680, y, a, 13, T1, weight="600", box=90)
        g.t(786, y, b, 12, T1, box=440)
        g.t(786, y + 22, c, 11, T3, box=440)
        if i:
            g.line(680, y - 32, 1220, y - 32, SEP, 1)
    g.t(680, 428, "共同点：都会产生不可逆后果，或改变别人看到的事实。", 12, T2, box=540)
    g.t(680, 452, "副驾在这一栏里的角色是「把材料备齐」，不是「替人决定」。", 12, T2, box=540)

    g.rect(40, 520, 1200, 270)
    g.t(56, 548, "权限三档　与安全联锁的关系", 14, GREEN, weight="600")
    g.line(56, 560, 1224, 560, SEP, 1)
    cells = [("第一档 · 自动执行", "只读与推断类工具", "副驾直接调用，事后可在审计里查到"),
             ("第二档 · 人工确认", "会落盘生效的动作", "副驾备好草稿与差异，人点按钮才生效"),
             ("第三档 · 闸门放行", "会动被测对象的动作", "人点之外，还须安全联锁与预检全绿")]
    for i, (a, b, c) in enumerate(cells):
        x = 56 + i * 388
        g.rect(x, 578, 370, 110, GREEN_W, 1, rx=4)
        g.t(x + 185, 608, a, 13, T1, anchor="middle", weight="600", box=350)
        g.t(x + 185, 636, b, 12, GREEN, anchor="middle", weight="600", box=350)
        g.t(x + 185, 662, c, 11, T2, anchor="middle", box=354)
    g.t(56, 736, "三档由服务端的 Hook 统一校验：前端只负责把不可点的按钮置灰，", 12, T2)
    g.t(56, 760, "并在按钮下方给一行说明，指出差在哪一项、点击直达该项。", 12, T2)
    g.rect(832, 720, 370, 54, RED, 1.5, "none", rx=4, dash="6 4")
    g.line(1017, 718, 1017, 694, RED, 1.5, me="ahr")
    g.t(1017, 744, "安全联锁闸门", 12, RED, anchor="middle", weight="600", box=350)
    g.t(1017, 762, "联锁项全满足 · 预检全通过 · 现场安全总闸已开", 11, T2, anchor="middle", box=354)

    g.t(40, 826, "第一档与第二档的差别是「会不会落盘」，第二档与第三档的差别是「会不会动被测对象」。", 12, T2)
    g.t(40, 850, "急停独立于三档与闸门：任何时刻可点，点后先发停机指令，再记录当时的全部状态快照。", 12, T2)
    return g.save()


if __name__ == "__main__":
    for fn in (fig1, fig2, fig3, fig4, fig5, fig6):
        print(fn())
    print("\n".join(WARN) if WARN else "无超宽告警")
