# -*- coding: utf-8 -*-
"""场景包生成：scene / product-attributes / control-parameters /
safety-interlocks / test-requirements。

数值口径三档，与素材综述文档 B 的口径表一致：
  - 已核实：来自标准正文原件或法规原文，_status 不设
  - 待核实：来自征求意见稿或第三方转述，_status 写明理由
  - 占位  ：源材料没有真实值，本包编的示例，_placeholder: true
"""
import os

from common import (BUILD_DATE, DOC_B, DOC_NEED, DRAFT_STATUS, EV,
                    FLOWS, GENERATED_BY, GB11552_TXT, ISO16750_2_PDF,
                    ISO16750_4_PDF, LV124_PDF, NHTSA_PDF, QC626_TXT, SCENE_ID,
                    TAXONOMY, VW80000_PDF, Q100_PDF, b, dump, src)

MISSING = []


# ============================ scene.json ============================

def gen_scene():
    img_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "assets/product-photo-nhtsa-fig5-1.png")
    images = []
    if os.path.exists(img_path):
        try:
            from PIL import Image
            w, h = Image.open(img_path).size
        except Exception:
            w = h = None
        images.append({
            "id": "product-photo-nhtsa-fig5-1",
            "title": "被测对象实车照片（NHTSA FMVSS 118 合规报告 FIGURE 5.1）",
            "path": "assets/product-photo-nhtsa-fig5-1.png",
            "width": w,
            "height": h,
            "render": "PyMuPDF get_pixmap(dpi=150) 渲染 PDF 第 19 页",
            "note": "照片主体是整车（2011 NISSAN JUKE S），不是升降器总成本体。"
                    "公开渠道拿不到升降器总成的可授权产品照，故用该合规报告的实车照片页作示意，"
                    "并另附一张手绘结构简图。",
            "_source": src(NHTSA_PDF,
                           "第 19 页（报告正文第 15 页）FIGURE 5.1，2011 NISSAN JUKE S，"
                           "NHTSA NO. CB5201"),
        })
    else:
        MISSING.append("assets/product-photo-nhtsa-fig5-1.png 未生成")

    svg_png = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "assets/regulator-schematic.png")
    if os.path.exists(svg_png):
        try:
            from PIL import Image
            w2, h2 = Image.open(svg_png).size
        except Exception:
            w2 = h2 = None
        images.append({
            "id": "regulator-schematic",
            "title": "玻璃升降器台架结构简图（本包手绘）",
            "path": "assets/regulator-schematic.png",
            "width": w2,
            "height": h2,
            "render": "_build/render_assets.py 手排 SVG → cairosvg 转 PNG",
            "_placeholder": True,
            "note": "示意图，非任何厂商的真实产品结构。画的是本包判据涉及的量测点位："
                    "有刷直流电机、蜗杆减速、绳轮/剪式传动、玻璃托架、上下止点、"
                    "力传感器与试验棒、位移传感器、噪音测点 300 mm。",
            "_source": [
                b(126, "堵转力 ≥212 N，力传感器量程选型依据"),
                b("326-328", "噪音测点：升降器电机出力轴正上方 300 mm"),
                src(QC626_TXT, "qc636.txt:326-328 工作噪音试验测点描述"),
            ],
        })

    return dump("scene.json", {
        "schema": "scene/v1",
        "id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "taxonomy": {
            "level1_scene": {"key": TAXONOMY["level1"]["key"],
                             "name": TAXONOMY["level1"]["name"]},
            "level2_category": {"key": TAXONOMY["level2"]["key"],
                                "name": TAXONOMY["level2"]["name"]},
            "level3_product_type": {"key": TAXONOMY["level3"]["key"],
                                    "name": TAXONOMY["level3"]["name"]},
            "_source": src(DOC_NEED,
                           "「体系三级：一级场景（汽车/芯片/电机/…），二级，三级=产品类型」段"),
        },
        "product": {
            "name": "汽车电动玻璃升降器总成（含防夹功能）",
            "chip": "本场景不锁定具体主控。公开可查的同类方案有四家："
                    "德州仪器 TIDA-01389（DRV8703-Q1 栅极驱动 + 两颗 DRV5013-Q1 锁存霍尔）、"
                    "恩智浦 RDS12VR（S12VR 混合信号微控制器）、"
                    "微芯 APGRD002、"
                    "英飞凌 TLE9855QX（MOTIX TLE985x 系列 H 桥驱动片上系统）",
            "control_scheme": "12 V 有刷直流电机 + H 桥 PWM 调速，机械换向；"
                              "位置反馈走霍尔锁存脉冲计数或电流纹波计数；"
                              "防夹判据取电流突变斜率或霍尔脉冲周期变化，"
                              "在 4 mm 至 200 mm 开口区间内于夹紧力超过 100 N 前回缩",
            "_source": [
                b("140-146", "四家参考设计的编号、器件与特征"),
                b(166, "防夹力判据 GB 11552-2009 §4.8.3.1.1"),
                b("437-443", "与峰岹案例的技术差异表：有刷直流 / 机械换向 / 直线往复 / 纹波计数"),
            ],
        },
        "summary": "汽车车身电机场景的电动玻璃升降器参考案例：12 V 有刷直流电机经蜗杆减速与"
                   "绳轮（或剪式）传动驱动玻璃托架直线往复，带防夹回缩功能。"
                   "与场景一（峰岹散热风扇）的关键差异在于电机类型（有刷 vs 无刷）、"
                   "运动形式（直线有限行程 vs 单向连续旋转）、主判据量纲"
                   "（mm/s 与 N 与 dB(A) vs rpm 与 A 与 K）、"
                   "以及安全属性（人身安全，受中美欧三地法规约束 vs 设备安全）。"
                   "本场景包把该产品的本体属性、控制参数、安全联锁、测试判据、"
                   "示例工作流、合成时序数据、经验条目、标准文档清单与报告模板字段"
                   "整理成前端可直接加载的 JSON。",
        "images": images,
        "regulation_matrix": [
            {
                "region": "中国",
                "regulation": "GB 11552-2009《乘用车内部凸出物》第 4.8 条",
                "force_limit_n": 100,
                "opening_range_mm": [4, 200],
                "rod_stiffness_n_per_mm": 10.0,
                "rod_stiffness_tolerance_n_per_mm": 0.5,
                "retract_options": [
                    "允许穿过开口放置直径 200 mm 的半刚性柱状试验棒的位置",
                    "关闭之前的最初位置",
                    "比开始回缩时的位置至少多开 50 mm 的位置",
                    "天窗倾斜运动时的最大角度开启位置",
                ],
                "_source": [
                    src(GB11552_TXT,
                        "gb11552.txt:440 「开口从200mm 到4mm 范围内，在夹紧力大于100N 之前，"
                        "该装置应回缩车窗/天窗/隔断系统。」；:449 「测量工具的刚度应为(10±0.5)N/mm」"),
                    b(215, "三地防夹对照表 GB 11552-2009 行"),
                ],
            },
            {
                "region": "美国",
                "regulation": "FMVSS 118（49 CFR § 571.118）Standard No. 118; "
                              "Power-operated window, partition, and roof panel systems",
                "force_limit_n": 100,
                "opening_range_mm": [4, 200],
                "rod_stiffness_n_per_mm": 20.0,
                "rod_stiffness_status": "待核实（25–200 mm 试棒取 20 N/mm，"
                                        "来自素材综述转述，未从法条逐字确认）",
                "retract_options": [
                    "至少开到关闭开始时的位置",
                    "比反向时的位置至少多开 125 mm",
                ],
                "_source": [
                    b(216, "三地防夹对照表 FMVSS 118 行"),
                    b(69, "49 CFR § 571.118 全名、机构与 URL"),
                ],
            },
            {
                "region": "欧洲",
                "regulation": "UN ECE R21 §5.8 — Uniform Provisions Concerning the Approval "
                              "of Vehicles with Regard to Their Interior Fittings",
                "force_limit_n": 100,
                "opening_range_mm": [4, 200],
                "rod_stiffness_n_per_mm": 10.0,
                "rod_stiffness_status": "待核实",
                "retract_options": ["三种可选位置之一（原文未逐字确认）"],
                "_status": "待核实（未打开 UNECE 原文逐字确认）",
                "_source": [
                    b(217, "三地防夹对照表 UN ECE R21 行"),
                    b(70, "UN ECE R21 全名、机构与 URL"),
                ],
            },
        ],
        "regulation_note": {
            "text": "中国、美国、欧洲三地现行法规都不强制要求配备防夹功能，"
                    "只在配备时才对其性能作规定。因此「是否测防夹」本身就是"
                    "流程 3 测试需求确认要由 Agent 与用户确认的分支条件。",
            "_status": "待核实（来源为智能汽车资源网法规解读页，非标准原文）",
            "_source": b(221, "一条对项目定位有影响的事实"),
        },
        "flows": [{"id": k, "name": v} for k, v in sorted(FLOWS.items())],
        "_source": src(DOC_NEED, "全文（六个流程与三级知识库体系）"),
    })


# ====================== product-attributes.json ======================

PA_GROUPS = ["电机本体", "电气额定", "工作电流", "机械性能", "运行速度",
             "声学", "结构与行程", "环境与等级"]


_OPT_LABELS = {
    ("str", "BRUSHED_DC"): "有刷直流", ("str", "BLDC"): "无刷直流", ("str", "PMSM"): "永磁同步",
    ("str", "MECHANICAL_COMMUTATOR"): "机械换向（电刷 + 换向器）",
    ("str", "ELECTRONIC_SIX_STEP"): "电子换向（六步方波）",
    ("str", "ELECTRONIC_FOC"): "电子换向（磁场定向控制）",
    ("str", "HALL_LATCH_PULSE"): "霍尔锁存脉冲计数",
    ("str", "CURRENT_RIPPLE_COUNT"): "电流纹波计数",
    ("str", "HALL_AND_RIPPLE_FUSION"): "霍尔与纹波融合",
    ("str", "WORM_GEAR_PLUS_CABLE_DRUM"): "蜗杆减速 + 绳轮",
    ("str", "WORM_GEAR_PLUS_SCISSOR"): "蜗杆减速 + 剪式", ("str", "OTHER"): "其他",
    ("str", "FRONT_DOOR"): "前门（耐久 10 000 循环）",
    ("str", "REAR_DOOR"): "后门（耐久 5 000 循环）",
    ("str", "QCT413_SWEEP"): "QC/T 413-2002 扫频振动",
    ("str", "VW80000_M04_PROFILE_D"): "VW 80000 M-04 谱型 D（簧上质量挂装件）",
    ("str", "GB28046_3"): "GB/T 28046.3 机械负荷",
    ("str", "ROD_200MM_PASS"): "开到可穿过直径 200 mm 试验棒的位置",
    ("str", "INITIAL_POSITION"): "关闭之前的最初位置",
    ("str", "PLUS_50MM"): "比触发位置多开 50 mm（中国四选一之一）",
    ("str", "PLUS_125MM"): "比触发位置多开 125 mm（美国二选一之一）",
    ("str", "TILT_MAX_ANGLE"): "天窗倾斜的最大角度开启位置",
    ("str", "CURRENT_SLOPE"): "电流突变斜率", ("str", "HALL_PULSE_PERIOD"): "霍尔脉冲周期变化",
    ("str", "TORQUE_RATE"): "转矩变化率", ("str", "MECHANICAL_POWER"): "机械功率",
    ("str", "CURRENT_HALL_FUSION"): "电流与霍尔双判据",
    ("str", "SIGN_MAGNITUDE"): "符号-幅值调制", ("str", "LOCKED_ANTIPHASE"): "锁定反相调制",
    ("str", "CURRENT_LOOP_FIRST"): "先整定电流环，再调开闭环切换",
    ("str", "SPEED_LOOP_FIRST"): "先整定速度环",
    ("str", "Grade 0"): "Grade 0（−40 至 +150 ℃）",
    ("str", "Grade 1"): "Grade 1（−40 至 +125 ℃）",
    ("str", "Grade 2"): "Grade 2（−40 至 +105 ℃）",
    ("str", "Grade 3"): "Grade 3（−40 至 +85 ℃）",
    ("str", "IPX4"): "IPX4 防溅水", ("str", "IP5K4K"): "IP5K4K 车用防尘防溅",
    ("str", "IPX9K"): "IPX9K 高温高压水喷射",
    ("str", "A"): "代码 A", ("str", "B"): "代码 B", ("str", "C"): "代码 C",
    ("str", "D"): "代码 D", ("str", "E"): "代码 E", ("str", "F"): "代码 F",
    ("str", "G"): "代码 G", ("str", "H"): "代码 H", ("str", "I"): "代码 I",
    ("str", "J"): "代码 J",
    ("bool", True): "启用", ("bool", False): "关闭",
    ("int", 12): "12 V 系统", ("int", 24): "24 V 系统",
    ("float", 550.0): "550 V 交流，历时 1 min",
    ("float", 660.0): "660 V 交流，历时 1 s（批量生产替代方案）",
    ("float", 60.0): "60 s（配 550 V）", ("float", 1.0): "1 s（配 660 V）",
    ("float", 10.0): "10 N/mm（GB 11552-2009 与 UN ECE R21）",
    ("float", 20.0): "20 N/mm（FMVSS 118，待核实）",
}


def _norm_options(opts, key=""):
    """把裸标量 options 规范成 [{value,label}]，与第一个场景包的形状一致。"""
    if opts is None:
        return None
    out = []
    for o in opts:
        if isinstance(o, dict):
            out.append(o)
        else:
            out.append({"value": o, "label": _OPT_LABELS.get((type(o).__name__, o), str(o))})
    return out


def _a(key, name, value, unit=None, mn=None, mx=None, step=None,
       editable=True, group="电气额定", source=None, status=None,
       placeholder=False, note=None, options=None, est=False,
       not_applicable=False):
    d = {"key": key, "name": name, "value": value, "unit": unit,
         "min": mn, "max": mx, "step": step, "editable": editable,
         "group": group}
    if options is not None:
        d["options"] = _norm_options(options, key)
        d["min"] = d["max"] = d["step"] = None   # 枚举型不适用加减号
    if not_applicable:
        d["not_applicable"] = True
    if est:
        d["range_estimated"] = True
    if note:
        d["note"] = note
    if status:
        d["_status"] = status
    if placeholder:
        d["_placeholder"] = True
    d["_source"] = source
    return d


def gen_product_attributes():
    D = DRAFT_STATUS
    A = []
    # ---- 电机本体 ----
    A += [
        _a("motor_type", "电机类型", "BRUSHED_DC", None, editable=False,
           group="电机本体",
           options=["BRUSHED_DC", "BLDC", "PMSM"],
           note="有刷直流，机械换向。这是与场景一（无刷直流 / 永磁同步，电子换向）最根本的差异。",
           source=b(437, "与峰岹案例的技术差异表「电机类型」行")),
        _a("commutation", "换向方式", "MECHANICAL_COMMUTATOR", None, editable=False,
           group="电机本体",
           options=["MECHANICAL_COMMUTATOR", "ELECTRONIC_SIX_STEP", "ELECTRONIC_FOC"],
           note="电刷与换向器机械换向，因此电流里天然带换向纹波，纹波频率正比于转速——"
                "这正是纹波计数测速的物理基础。",
           source=[b(437, "技术差异表「电机类型」行"),
                   b(146, "TI 纹波计数参考设计 TIDA-01421：纹波与换向器极一一对应")]),
        _a("pole_pairs", "极对数", None, "对", editable=False, group="电机本体",
           not_applicable=True,
           note="有刷直流电机不做无刷意义上的极对数配置，控制器不需要该参数，故标 not_applicable。"
                "与之对应的可配量是换向器极数（每转纹波数 = 2N，N 为绕组对数），"
                "见 control-parameters.json 的 ripple_pulses_per_rev。",
           source=[b(439, "技术差异表「位置反馈」行：霍尔锁存脉冲计数，或电流纹波计数"),
                   b(146, "纹波频率对应换向器极数，为 2N")]),
        _a("position_feedback", "位置反馈方式", "HALL_LATCH_PULSE", None,
           editable=True, group="电机本体",
           options=["HALL_LATCH_PULSE", "CURRENT_RIPPLE_COUNT", "HALL_AND_RIPPLE_FUSION"],
           note="TIDA-01389 用两颗 DRV5013-Q1 锁存霍尔构成位置编码（带宽 30 kHz）；"
                "无霍尔方案走电流纹波计数。",
           source=[b(140, "TIDA-01389 两颗 DRV5013-Q1 锁存霍尔，带宽 30 kHz"),
                   b(146, "TI 车规有刷电机纹波计数参考设计")]),
        _a("reduction_type", "减速与传动形式", "WORM_GEAR_PLUS_CABLE_DRUM", None,
           editable=True, group="电机本体",
           options=["WORM_GEAR_PLUS_CABLE_DRUM", "WORM_GEAR_PLUS_SCISSOR", "OTHER"],
           placeholder=True,
           note="示例值。征求意见稿只规定性能不规定结构，具体机型由产品图样定。"
                "蜗杆减速是升降器实现自锁（5.5 条 600 N / 5 mm）的常见做法，"
                "但本包没有任何一份材料明文写这一点，不得当结论用。",
           source=b(131, "自锁能力 5.5 条：托架中心垂直施加 600 N 保持 5 s，下降量 ≤5 mm")),
    ]
    # ---- 电气额定 ----
    A += [
        _a("system_voltage", "系统标称电压", 12, "V", 12, 24, 12,
           editable=False, group="电气额定", options=[12, 24],
           note="本场景固定 12 V 系统。24 V 档留给商用车衍生机型，判据需整套换表。",
           source=[b(122, "工作电压范围 5.4.1 a) 9 V 至 16 V"),
                   b(231, "ISO 16750-2:2023 电压代码 C：12 V 系统 9 至 16 V")]),
        _a("operating_voltage_min", "工作电压下限", 9.0, "V", 6.0, 12.0, 0.1,
           group="电气额定", status=D,
           note="9 至 16 V 正好落在 ISO 16750-2:2023 供电电压代码 C（已核实）上，两处互证。",
           source=[src(QC626_TXT, "qc636.txt:117-118 5.4.1 a) 「升降器在9V～16V 电压下应运行平稳」"),
                   b(122, "工作电压范围 5.4.1 a)"),
                   b(231, "ISO 16750-2:2023 代码 C = 9 至 16 V（已核实）")]),
        _a("operating_voltage_max", "工作电压上限", 16.0, "V", 12.0, 18.0, 0.1,
           group="电气额定", status=D,
           source=[src(QC626_TXT, "qc636.txt:117-118 5.4.1 a)"), b(122, "工作电压范围")]),
        _a("test_voltage", "试验电压", 13.5, "V", 13.2, 13.8, 0.1,
           group="电气额定", status=D,
           note="允差 ±0.3 V。台架程控电源的设定值。",
           source=[src(QC626_TXT, "qc636.txt:284 6.1 b) 「试验电压：（13.5±0.3）V」"),
                   b(123, "试验电压 6.1 b)")]),
        _a("test_voltage_tolerance", "试验电压允差", 0.3, "V", 0.1, 0.5, 0.05,
           group="电气额定", status=D,
           source=src(QC626_TXT, "qc636.txt:284 6.1 b)")),
        _a("harness_resistance", "试验回路接线电阻", 0.15, "Ω", 0.13, 0.17, 0.01,
           group="电气额定", status=D,
           note="允差 ±0.02 Ω。接线电阻直接影响堵转电流实测值，是复现性的关键项。",
           source=[src(QC626_TXT, "qc636.txt:284 6.1 b) 「接线电阻为：（0.15±0.02）Ω」"),
                   b(123, "接线电阻 0.15 ± 0.02 Ω")]),
        _a("start_voltage_max", "启动电压上限", 9.0, "V", 6.0, 12.0, 0.1,
           group="电气额定", status=D,
           note="低压启动能力判据。−30 ℃ 下放宽到 10 V。",
           source=[src(QC626_TXT, "qc636.txt:127-128 5.4.1 f) 「升降器的启动电压应不大于9V」"),
                   b(130, "启动电压 5.4.1 f)")]),
        _a("voltage_code_iso16750", "ISO 16750-2 供电电压代码", "C", None,
           editable=True, group="电气额定",
           options=["A", "B", "C", "D", "E", "F", "G", "H"],
           note="代码 C = 12 V 系统 9 至 16 V。玻璃升降器与刮水电动机均落在此档。已核实。",
           source=[b(231, "ISO 16750-2:2023 供电电压代码表 C 行"),
                   src(ISO16750_2_PDF, "ISO 16750-2:2023 正式预览件开放正文页 供电电压代码表")]),
    ]
    # ---- 工作电流 ----
    A += [
        _a("working_current_max", "工作电流上限（常温）", 12.0, "A", 5.0, 20.0, 0.5,
           group="工作电流", status=D,
           note="过流保护阈值的基准。5.4.1 b) 只给一个上限，不分升降方向；"
                "分方向的数值出现在耐高温（上升 ≤12 A、下降 ≤7 A）与"
                "耐低温（上升 ≤20 A、下降 ≤16 A）两张表里。",
           source=[src(QC626_TXT, "qc636.txt:119-120 5.4.1 b) 「工作电流不大于12A」"),
                   b(124, "工作电流上限 5.4.1 b)")]),
        _a("working_current_up_max_80c", "上升工作电流上限（80 ℃）", 12.0, "A",
           5.0, 20.0, 0.5, group="工作电流", status=D,
           source=b(192, "耐高温特性 5.6.1 / 6.6.1 判据行")),
        _a("working_current_down_max_80c", "下降工作电流上限（80 ℃）", 7.0, "A",
           3.0, 15.0, 0.5, group="工作电流", status=D,
           source=b(192, "耐高温特性 5.6.1 / 6.6.1 判据行")),
        _a("working_current_up_max_m30c", "上升工作电流上限（−30 ℃）", 20.0, "A",
           10.0, 30.0, 0.5, group="工作电流", status=D,
           note="低温下润滑脂黏度上升、阻力增大，电流上限随之从 12 A 放宽到 20 A。",
           source=b(193, "耐低温特性 5.6.2 / 6.6.2 判据行")),
        _a("working_current_down_max_m30c", "下降工作电流上限（−30 ℃）", 16.0, "A",
           8.0, 25.0, 0.5, group="工作电流", status=D,
           source=b(193, "耐低温特性 5.6.2 / 6.6.2 判据行")),
        _a("stall_current_max", "堵转电流上限（常温）", 28.0, "A", 15.0, 40.0, 0.5,
           group="工作电流", status=D,
           note="堵转判据与过流保护阈值的共同基准。",
           source=[src(QC626_TXT, "qc636.txt:119-120 5.4.1 b) 「堵转电流不大于28A」"),
                   b(125, "堵转电流上限 5.4.1 b)"),
                   b(161, "堵转电流 ≤28 A（常温）；80 ℃ ≤29 A；−30 ℃ ≤30 A")]),
        _a("stall_current_max_80c", "堵转电流上限（80 ℃）", 29.0, "A", 15.0, 40.0, 0.5,
           group="工作电流", status=D,
           source=b(161, "堵转电流温度分档")),
        _a("stall_current_max_m30c", "堵转电流上限（−30 ℃）", 30.0, "A", 15.0, 40.0, 0.5,
           group="工作电流", status=D,
           source=b(161, "堵转电流温度分档")),
    ]
    # ---- 机械性能 ----
    A += [
        _a("stall_force_min", "堵转力下限（常温）", 212.0, "N", 100.0, 400.0, 1.0,
           group="机械性能", status=D,
           note="力传感器量程选型依据：量程需覆盖 212 N 以上，同时在 100 N 附近有足够分辨率"
                "（防夹判据用的是同一支传感器）。",
           source=[src(QC626_TXT, "qc636.txt:121-122 5.4.1 c) 「升降器堵转力应不小于212N」"),
                   b(126, "堵转力 5.4.1 c)")]),
        _a("stall_force_min_80c", "堵转力下限（80 ℃）", 164.0, "N", 80.0, 400.0, 1.0,
           group="机械性能", status=D,
           source=b(192, "耐高温特性判据行「堵转力 ≥164 N」")),
        _a("stall_force_min_m30c", "堵转力下限（−30 ℃）", 190.0, "N", 80.0, 400.0, 1.0,
           group="机械性能", status=D,
           source=b(193, "耐低温特性判据行「堵转力 ≥190 N」")),
        _a("self_lock_load", "自锁试验加载力", 600.0, "N", 300.0, 900.0, 10.0,
           group="机械性能", status=D,
           note="在玻璃托架上垂直向下施加，上止点与半行程两处各做一次。",
           source=[src(QC626_TXT, "qc636.txt:142-144 5.5 「施加600N负载时，不应损坏，玻璃托架下降量不大于5mm」"),
                   b(131, "自锁能力 5.5")]),
        _a("self_lock_hold_time", "自锁保持时间", 5.0, "s", 1.0, 30.0, 1.0,
           group="机械性能", status=D,
           source=b(191, "自锁性 5.5 / 6.5「垂直向下 600 N 保持 5 s」")),
        _a("self_lock_drop_max", "自锁允许下降量", 5.0, "mm", 0.5, 20.0, 0.5,
           group="机械性能", status=D,
           source=[src(QC626_TXT, "qc636.txt:142-144 5.5"), b(131, "自锁能力 5.5")]),
    ]
    # ---- 运行速度 ----
    A += [
        _a("rise_speed_min", "上升运行速度下限", 80.0, "mm/s", 40.0, 160.0, 1.0,
           group="运行速度", status=D,
           note="速度是本场景的主判据量纲之一，与场景一的 rpm 不同量纲——"
                "证明判据模型必须是「量纲 + 条件 + 阈值」三元组而不是写死转速。",
           source=[src(QC626_TXT, "qc636.txt:123-124 5.4.1 d) 「上升运行速度应在80mm/s～160mm/s 之间」"),
                   b(127, "上升运行速度 5.4.1 d)"),
                   b(440, "技术差异表「主判据量纲」行")]),
        _a("rise_speed_max", "上升运行速度上限", 160.0, "mm/s", 80.0, 300.0, 1.0,
           group="运行速度", status=D,
           source=[src(QC626_TXT, "qc636.txt:123-124 5.4.1 d)"), b(127, "上升运行速度")]),
        _a("down_speed_max", "下降运行速度上限", 200.0, "mm/s", 100.0, 300.0, 1.0,
           group="运行速度", status=D,
           source=[src(QC626_TXT, "qc636.txt:123-124 5.4.1 d) 「下降运行速度应不大于200mm/s」"),
                   b(128, "下降运行速度 5.4.1 d)")]),
        _a("rise_speed_min_m30c", "上升运行速度下限（−30 ℃）", 60.0, "mm/s",
           30.0, 160.0, 1.0, group="运行速度", status=D,
           source=b(193, "耐低温特性判据行「上升速度 ≥60 mm/s」")),
        _a("down_speed_min_m30c", "下降运行速度下限（−30 ℃）", 70.0, "mm/s",
           30.0, 200.0, 1.0, group="运行速度", status=D,
           source=b(193, "耐低温特性判据行「下降速度 ≥70 mm/s」")),
    ]
    # ---- 声学 ----
    A += [
        _a("noise_max", "工作噪音上限", 60.0, "dB(A)", 40.0, 80.0, 0.5,
           group="声学", status=D,
           source=[src(QC626_TXT, "qc636.txt:125-126 5.4.1 e) 「工作噪音应小于60dB（A）」"),
                   b(129, "工作噪音 5.4.1 e)")]),
        _a("noise_mic_distance", "噪音测点距离", 300.0, "mm", 100.0, 1000.0, 10.0,
           group="声学", status=D,
           note="传声器置于升降器电机出力轴正上方。背景噪音须低于测试噪音 10 dB(A)。",
           source=[src(QC626_TXT, "qc636.txt:326-328 6.4.1 e) 工作噪音试验测点"),
                   b(129, "声学测点：电机出力轴正上方 300 mm")]),
        _a("noise_background_margin", "背景噪音要求裕量", 10.0, "dB(A)", 5.0, 20.0, 1.0,
           group="声学", status=D,
           source=src(QC626_TXT, "qc636.txt:325-326 「在背景噪音低于测试噪音10dB（A）的环境中进行测试」")),
    ]
    # ---- 结构与行程 ----
    A += [
        _a("glass_travel", "玻璃托架总行程", 420.0, "mm", 200.0, 700.0, 1.0,
           group="结构与行程", placeholder=True,
           note="示例值。征求意见稿只按「下止点到上止点」定义行程、不给具体数字，"
                "实际值由产品图样定。这个数只用来让前端的位移轴有刻度，不得当判据。",
           source=src(QC626_TXT, "qc636.txt:312-314 6.4.1 d) 「测量玻璃托架从下止点到上止点的运行时间和行程」")),
        _a("rated_load_up", "上升额定负载定义", "玻璃重量 + 胶条滑动阻力", None,
           editable=False, group="结构与行程", status=D,
           note="模拟工装配重的设定依据。具体数值随车型玻璃与密封条变，本包不给数。",
           source=b(133, "额定负载计算式 6.1 d)")),
        _a("rated_load_down", "下降额定负载定义", "玻璃重量 − 胶条滑动阻力", None,
           editable=False, group="结构与行程", status=D,
           source=b(133, "额定负载计算式 6.1 d)")),
        _a("door_position", "安装位置", "FRONT_DOOR", None, editable=True,
           group="结构与行程",
           options=["FRONT_DOOR", "REAR_DOOR"],
           note="前门与后门的耐久循环数不同（前门 10 000、后门 5 000），"
                "VW 80000 M-06 的机械冲击次数也按门位分档"
                "（驾驶员门 100 000 次、前排乘客门与后门 50 000 次）。",
           source=[b(196, "耐久性（电动，前门）累计 10 000 个循环周期"),
                   b(197, "耐久性（电动，后门）累计 5 000 个循环周期"),
                   b(242, "VW 80000 M-06 冲击次数按安装位置分档")]),
    ]
    # ---- 环境与等级 ----
    A += [
        _a("ambient_normal", "常温定义", 23.0, "℃", 21.0, 25.0, 0.5,
           group="环境与等级", status=D,
           note="允差 ±2 ℃。环境基线。",
           source=[src(QC626_TXT, "qc636.txt 6.1 c) 常温定义"), b(132, "常温定义 6.1 c)")]),
        _a("temp_code_iso16750", "ISO 16750-4 工作温度代码", "C", None,
           editable=True, group="环境与等级",
           options=["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"],
           note="代码 C = −40 / 65 ℃。已核实。注意与 QC/T 626 征求意见稿的 −30 / 80 ℃ 档不重合，"
                "两套温度口径并存时必须显式选一套，不能混用。",
           source=[b(238, "ISO 16750-4:2023 工作温度代码 A 至 J"),
                   src(ISO16750_4_PDF, "ISO 16750-4:2023 正式预览件 工作温度代码表")]),
        _a("high_temp_soak", "耐高温试验温度", 80.0, "℃", 60.0, 100.0, 1.0,
           group="环境与等级", status=D,
           note="放置 2 h 后在该温度下空载不堵转运行 5 个工作循环。",
           source=b(192, "耐高温特性 5.6.1 / 6.6.1 条件列")),
        _a("low_temp_soak", "耐低温试验温度", -30.0, "℃", -40.0, -10.0, 1.0,
           group="环境与等级", status=D,
           source=b(193, "耐低温特性 5.6.2 / 6.6.2 条件列")),
        _a("vibration_profile", "振动谱型", "VW80000_M04_PROFILE_D", None,
           editable=True, group="环境与等级",
           options=["QCT413_SWEEP", "VW80000_M04_PROFILE_D", "GB28046_3"],
           note="车门上的玻璃升降器属 VW 80000 M-04 谱型 D（簧上质量挂装件）："
                "宽带随机振动，每轴 8 h，加速度均方根 30.8 m/s²。已核实。"
                "QC/T 626 征求意见稿自己引的是 QC/T 413-2002 的扫频振动条件。",
           source=[b(240, "VW 80000 机械试验 M-04 谱型 D"),
                   b(194, "耐振动性 5.7 / 6.7 按 QC/T 413-2002"),
                   src(VW80000_PDF, "VW 80000 Issue 2022-12 机械试验 M-04 章节")]),
        _a("shock_count", "连续机械冲击次数", 100000, "次", 3000, 100000, 1000,
           group="环境与等级",
           note="峰值 300 m/s²、6 ms 半正弦。驾驶员车门 100 000 次、前排乘客门与后门 50 000 次。已核实。",
           source=[b(242, "VW 80000 机械试验 M-06 连续机械冲击"),
                   src(VW80000_PDF, "VW 80000 Issue 2022-12 机械试验 M-06 章节")]),
        _a("aec_q100_grade", "主控芯片 AEC-Q100 温度等级", "Grade 1", None,
           editable=True, group="环境与等级",
           options=["Grade 0", "Grade 1", "Grade 2", "Grade 3"],
           placeholder=True,
           note="示例值。车门内属客舱外但非机舱环境，业界常见取 Grade 1（−40 至 +125 ℃）"
                "或 Grade 2（−40 至 +105 ℃），本包没有任何材料指明该产品实取哪一档。"
                "等级表本身（Grade 0 至 3 的温度范围与应力条件）已核实。",
           source=[b("246-251", "AEC-Q100 Rev J1 温度等级与关键应力条件表"),
                   src(Q100_PDF, "AEC-Q100 Rev J1（2026-03-24）温度等级表")]),
        _a("ip_rating", "防护等级", "IPX4", None, editable=True,
           group="环境与等级", placeholder=True,
           options=["IPX4", "IP5K4K", "IPX9K"],
           note="示例值。QC/T 626 征求意见稿走的是自定义喷水试验"
                "（0.1 MPa、φ1.2 mm 孔 40 个、20 L/min、30 min），不直接引 IP 代码。"
                "这里给 IPX4 只是为了让前端的等级下拉框有内容。",
           source=[b(203, "防水性 5.12.1 / 6.12.1 表 9 喷水条件"),
                   b(83, "GB/T 4208-2017 外壳防护等级（IP 代码）"),
                   b(84, "GB/T 30038 车用版 IP 代码，增设 IPX9K")]),
    ]

    return dump("product-attributes.json", {
        "schema": "product-attributes/v1",
        "scene_id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "belongs_to_flow": "F2 初始化配置（产品本体属性，读取文档→呈现→左右加减号调整）",
        "groups": PA_GROUPS,
        "value_source_note": "本文件的数值来自三处：QC/T 626-2019 征求意见稿（整体标待核实）、"
                             "ISO 16750 与 VW 80000 与 AEC-Q100 的已核实条款、"
                             "以及本包为让前端有刻度而编的示例值（标 _placeholder）。"
                             "带 _status 的条目不得直接作为出厂判定阈值。",
        "attributes": A,
    })


# ====================== control-parameters.json ======================

CP_GROUPS = ["防夹算法", "位置与行程", "驱动与调制", "保护与热管理",
             "电流环整定", "台架与工装", "数据采集"]

F3 = "F3 测试需求确认"
F4 = "F4 启动测试及结果分析"
F5 = "F5 调优确认及运行"
F2 = "F2 初始化配置"


def _p(key, name, value, default=None, unit=None, mn=None, mx=None, step=None,
       group="防夹算法", flows=None, editable=True, note=None, source=None,
       status=None, placeholder=False, options=None, est=False):
    d = {"key": key, "name": name, "value": value,
         "default": default if default is not None else value,
         "unit": unit, "min": mn, "max": mx, "step": step, "group": group,
         "adjustable_in_flows": flows or [F5], "editable": editable}
    if options is not None:
        d["options"] = _norm_options(options, key)
        d["min"] = d["max"] = d["step"] = None   # 枚举型不适用加减号
    if est:
        d["range_estimated"] = True
    if note:
        d["note"] = note
    if status:
        d["_status"] = status
    if placeholder:
        d["_placeholder"] = True
    d["_source"] = source
    return d


def gen_control_parameters():
    D = DRAFT_STATUS
    P = []
    # ---- 防夹算法（本场景的主戏）----
    P += [
        _p("antipinch_enable", "防夹功能使能", True, True, None,
           group="防夹算法", flows=[F2, F3], options=[True, False],
           note="三地法规都不强制配备防夹，只在配备时规定性能。因此这个开关本身就是"
                "流程 3 要与用户确认的分支条件：关掉则整条防夹判据链不执行，"
                "改走 GB 11552-2009 §4.8.2 的无防夹替代要求（开口 ≤4 mm 才允许关闭、"
                "遥控作用距离 ≤6 m 或可直接看见时 ≤11 m、一键关闭仅限驾驶员侧与天窗）。",
           source=[b(221, "三地法规都不强制要求配备防夹功能"),
                   b(219, "无防夹功能时的替代要求 GB 11552-2009 §4.8.2")]),
        _p("antipinch_force_threshold", "防夹力阈值", 80.0, 80.0, "N",
           20.0, 100.0, 1.0, group="防夹算法", flows=[F5],
           note="法规上限 100 N 是硬顶，不是目标值：实测必须在超过 100 N 之前回缩，"
                "所以固件门限要留裕量。调大逼近或超出 100 N 判不合格；"
                "调小则误触发率升高，正常密封阻力被误判为夹持。默认 80 N 是本包给的裕量示例值。",
           source=[b(349, "防夹调参清单「防夹力阈值」行"),
                   b(166, "防夹力 GB 11552-2009 §4.8.3.1.1 已核实"),
                   src(GB11552_TXT, "gb11552.txt:440 「在夹紧力大于100N 之前，该装置应回缩」")]),
        _p("antipinch_window_lower", "防夹生效区间下沿", 4.0, 4.0, "mm",
           0.0, 20.0, 0.5, group="防夹算法", flows=[F5],
           note="法规下沿 4 mm，对应幼儿手指宽度。下沿高于 4 mm 即不合规。",
           source=[b(350, "防夹生效区间（行程窗口）行"),
                   b(71, "Federal Register E9-21042：4 mm 对应幼儿手指"),
                   src(GB11552_TXT, "gb11552.txt:440 「开口从200mm 到4mm 范围内」")]),
        _p("antipinch_window_upper", "防夹生效区间上沿", 200.0, 200.0, "mm",
           100.0, 300.0, 1.0, group="防夹算法", flows=[F5],
           note="法规上沿 200 mm，对应第 95 百分位成年男性头部最大宽度。",
           source=[b(350, "防夹生效区间行"),
                   b(71, "Federal Register E9-21042：200 mm 对应第 95 百分位成年男性头部最大宽度")]),
        _p("antipinch_retract_mode", "回缩后位置策略", "PLUS_50MM", "PLUS_50MM", None,
           group="防夹算法", flows=[F3, F5],
           options=["ROD_200MM_PASS", "INITIAL_POSITION", "PLUS_50MM",
                    "PLUS_125MM", "TILT_MAX_ANGLE"],
           note="按目标市场选：PLUS_50MM 与 ROD_200MM_PASS 与 INITIAL_POSITION 与 TILT_MAX_ANGLE "
                "是 GB 11552-2009 §4.8.3.1.2 的四选一；PLUS_125MM 与 INITIAL_POSITION "
                "是 FMVSS 118 的二选一。选 PLUS_50MM 则同时满足中欧、不满足美国。",
           source=[src(GB11552_TXT, "gb11552.txt:445-452 §4.8.3.1.2.1 至 4.8.3.1.2.4 四选一"),
                   b(215, "GB 11552-2009 回缩后要求四选一"),
                   b(216, "FMVSS 118 回缩后要求二选一")]),
        _p("antipinch_retract_distance", "回缩行程量", 60.0, 60.0, "mm",
           30.0, 200.0, 1.0, group="防夹算法", flows=[F5],
           note="默认 60 mm 是本包给的裕量示例值（法规底线 50 mm）。"
                "调大无合规风险但用户体验差；低于 50 mm 或未达法规要求的位置之一即不合规。"
                "目标美国市场时该值需 ≥125 mm。",
           source=[b(354, "防夹调参清单「回缩行程量」行"),
                   src(GB11552_TXT, "gb11552.txt:448 「比开始回缩时的位置至少多开50mm 的位置」")]),
        _p("antipinch_detect_method", "防夹检测判据", "CURRENT_SLOPE", "CURRENT_SLOPE",
           None, group="防夹算法", flows=[F5],
           options=["CURRENT_SLOPE", "HALL_PULSE_PERIOD", "TORQUE_RATE",
                    "MECHANICAL_POWER", "CURRENT_HALL_FUSION"],
           status="待核实（各判据的出处论文本次未打开正文逐字确认）",
           note="四种公开判据各有出处：电流突变门限自整定（IJECE 2018）、"
                "转矩变化率（IEEE 会议论文 1600781，文中指出转矩变化率对电机参数不确定性的敏感度"
                "低于转矩或角速度本身）、霍尔脉冲与机械功率联合（ICMSE 2018）、"
                "霍尔与电流采样双判据（恩智浦 RDS12VR）。",
           source=[b(338, "Automatic Threshold on Current based Anti-pinch Mechanism for Power Windows"),
                   b(339, "Practical pinch detection algorithm：基于转矩变化率"),
                   b(340, "Power Window Anti-Pinch Control Based on Hall Pulse Signal and Mechanical Power"),
                   b(343, "恩智浦 RDS12VR：霍尔与电流采样双判据")]),
        _p("current_slope_window", "电流斜率检测窗口", 20.0, 20.0, "ms",
           5.0, 100.0, 1.0, group="防夹算法", flows=[F5], est=True,
           placeholder=True,
           note="示例值。窗口太短则纹波与换向噪声进入斜率计算，太长则夹持响应滞后、"
                "力峰值可能已越过 100 N。源材料只给出「电流突变门限的自适应设定方法」这一定性描述，"
                "没有给窗口长度的数值，本包按 2 kHz 采样下 40 个点取 20 ms 作起点。"
                "range_estimated 表示 5 至 100 ms 这个区间是本包推定的，不是源材料给的。",
           source=b(338, "电流突变门限的自适应设定方法；阈值随工况自整定")),
        _p("current_slope_threshold", "电流斜率门限", 150.0, 150.0, "A/s",
           20.0, 800.0, 5.0, group="防夹算法", flows=[F5], est=True,
           placeholder=True,
           note="示例值，与本包合成波形 assets/waveforms/antipinch-trigger.csv 的注入幅度配套。"
                "真实值必须在实物台架上按 100 N 反推标定。",
           source=b(338, "电流突变门限的自适应设定方法")),
        _p("startup_blanking_time", "启动段屏蔽时间", 150.0, 150.0, "ms",
           0.0, 500.0, 10.0, group="防夹算法", flows=[F5], est=True,
           placeholder=True,
           note="示例值。启动瞬间的浪涌电流会掩盖夹持特征，是防夹算法最难的一段。"
                "调大则启动瞬间夹持漏检，调小则浪涌被误判为夹持。"
                "源材料确认了这个参数的存在与两侧后果，但没给数值。",
           source=[b(351, "防夹调参清单「启动段屏蔽时间」行"),
                   b(341, "基于纹波电机的车窗启动阶段防夹控制策略研究")]),
        _p("antipinch_confirm_count", "夹持连续确认次数", 3, 3, "次",
           1, 10, 1, group="防夹算法", flows=[F5], est=True, placeholder=True,
           note="示例值。去抖用，与 current_slope_window 一起决定最坏响应延迟。",
           source=b("349-354", "防夹调参清单（本文档的综合，非任一来源原文）")),
    ]
    # ---- 位置与行程 ----
    P += [
        _p("soft_stop_position", "软停位置（距上止点）", 15.0, 15.0, "mm",
           0.0, 60.0, 1.0, group="位置与行程", flows=[F5], est=True,
           placeholder=True,
           note="示例值。进入密封压紧段前降速，避免把密封阻力的电流上翘误判成夹持。"
                "这个位置必须高于防夹生效区间下沿 4 mm，否则法规要求的最后 4 mm 内无防夹保护。",
           source=b(350, "防夹生效区间：进入密封压紧段仍生效则无法正常关窗")),
        _p("soft_stop_speed_ratio", "软停段降速比例", 50, 50, "%",
           10, 100, 5, group="位置与行程", flows=[F5], est=True, placeholder=True,
           note="示例值。降速后仍须满足上升速度 80 至 160 mm/s 的全程判据，"
                "或在判据里显式排除软停段——这一点标准没写，是台架口径要与客户确认的事。",
           source=b(127, "上升运行速度 80 至 160 mm/s")),
        _p("ripple_filter_bandwidth", "纹波提取滤波带宽", 2000.0, 2000.0, "Hz",
           200.0, 20000.0, 100.0, group="位置与行程", flows=[F5], est=True,
           placeholder=True,
           note="示例值。从电流交流分量提取转速脉冲的带通带宽。"
                "调大引入噪声计数、位置漂移；调小则低速段丢脉冲、位置累计误差。",
           source=[b(352, "纹波计数滤波带宽与迟滞行"),
                   b(342, "TI TIDUD30A：纹波提取的高通/带通滤波参数、比较器迟滞、脉冲整形门限")]),
        _p("ripple_comparator_hysteresis", "纹波比较器迟滞", 20.0, 20.0, "mV",
           2.0, 200.0, 1.0, group="位置与行程", flows=[F5], est=True,
           placeholder=True,
           note="示例值。同上，出处只给了参数名与作用，没给数值。",
           source=b(342, "TI TIDUD30A 比较器迟滞")),
        _p("ripple_pulses_per_rev", "每转纹波数", 8, 8, "个/转",
           2, 24, 2, group="位置与行程", flows=[F2], est=True, placeholder=True,
           note="示例值。等于 2N，N 为绕组对数。有刷直流电机用这个量代替无刷电机的极对数。",
           source=b(146, "纹波频率对应换向器极数，为 2N（N 为绕组对数）")),
        _p("hall_pulses_per_mm", "霍尔脉冲密度", 4.0, 4.0, "脉冲/mm",
           0.5, 20.0, 0.5, group="位置与行程", flows=[F2], est=True,
           placeholder=True,
           note="示例值。两颗锁存霍尔正交输出，可辨向。TIDA-01389 用的 DRV5013-Q1 带宽 30 kHz。",
           source=b(140, "TIDA-01389：两颗 DRV5013-Q1 锁存霍尔构成位置编码，带宽 30 kHz")),
        _p("position_reset_at_top", "上止点位置归零", True, True, None,
           group="位置与行程", flows=[F2], options=[True, False],
           note="每次上止点堵转后把累计位置清零，抵消纹波计数的长期漂移。"
                "耐久试验的单循环波形本身就包含上止点堵转 1 s，正好提供归零时机。",
           source=b(200, "耐久单循环波形 6.9.1 注 3：起始位置 → 上止点堵转 1 s 停 4 s → …")),
    ]
    # ---- 驱动与调制 ----
    P += [
        _p("pwm_duty", "PWM 占空比", 100, 100, "%", 0, 100, 1,
           group="驱动与调制", flows=[F4, F5],
           note="升降器正常工作是全占空比直驱，PWM 主要用在软启动斜坡与软停降速两段。"
                "台架做速度一致性复现时可用它把上升速度压进 80 至 160 mm/s 区间。",
           source=[b(145, "英飞凌 MOTIX TLE985x：12 V 电机控制片上系统，自适应栅极电流控制"),
                   b(127, "上升运行速度判据区间")]),
        _p("pwm_frequency", "PWM 载波频率", 20000, 20000, "Hz",
           1000, 25000, 500, group="驱动与调制", flows=[F5], est=True,
           placeholder=True,
           note="示例值。20 kHz 在人耳听阈之上，对 60 dB(A) 噪音判据友好；"
                "载波也直接决定电流环带宽的可取范围（典型取载波的 5 % 至 15 %）。",
           source=[b(375, "电流环带宽典型取 PWM 频率的 5 % 至 15 %（20 kHz PWM 对应 1 至 3 kHz）"),
                   b(129, "工作噪音 <60 dB(A)")]),
        _p("deadtime", "H 桥死区", 500, 500, "ns", 100, 3000, 50,
           group="驱动与调制", flows=[F5], est=True, placeholder=True,
           note="示例值。死区的必要性与死区导致的损耗见罗姆 TechWeb 条目 346；"
                "TI SLLA567 讲自动死区补偿与 PWM 调制方式对声学表现的影响。",
           source=[b(365, "罗姆 TechWeb 条目 346：死区的必要性与死区导致的损耗"),
                   b(364, "TI SLLA567：自动死区补偿、PWM 调制方式对声学表现的影响")]),
        _p("soft_start_ramp", "软启动斜坡时长", 120.0, 120.0, "ms",
           0.0, 1000.0, 10.0, group="驱动与调制", flows=[F5], est=True,
           placeholder=True,
           note="示例值。斜坡越长浪涌越小、启动段屏蔽时间可以越短，两个参数要一起调。",
           source=b(361, "UM3259：对齐与启动、单段或多段加速斜坡；大惯量电机先缓斜坡后陡斜坡")),
        _p("hbridge_mode", "H 桥调制方式", "SIGN_MAGNITUDE", "SIGN_MAGNITUDE", None,
           group="驱动与调制", flows=[F5],
           options=["SIGN_MAGNITUDE", "LOCKED_ANTIPHASE"],
           placeholder=True,
           note="示例值。两种方式对电流纹波形态影响很大，会直接改变纹波计数的可用性——"
                "换调制方式后纹波滤波带宽与迟滞必须重标。本包没有材料指明实际方案取哪种。",
           source=b(140, "TIDA-01389：DRV8703-Q1 栅极驱动器，驱动能力 15 A，耐压 47 V")),
    ]
    # ---- 保护与热管理 ----
    P += [
        _p("stall_current_threshold", "堵转判定电流门限", 24.0, 24.0, "A",
           10.0, 30.0, 0.5, group="保护与热管理", flows=[F5],
           note="必须低于堵转电流上限 28 A 才能在越限前动作。"
                "调大则遇障后仍继续加力、力峰值超标；调小则到达上止点被误判为夹持、无法关到位。"
                "默认 24 N 留 4 A 裕量是本包给的示例。",
           source=[b(353, "堵转判定电流门限与去抖时间行"),
                   b(125, "堵转电流上限 ≤28 A")]),
        _p("stall_debounce_time", "堵转去抖时间", 60.0, 60.0, "ms",
           10.0, 500.0, 5.0, group="保护与热管理", flows=[F5], est=True,
           placeholder=True,
           note="示例值。与防夹的 antipinch_confirm_count 是同一类去抖，但两者判定目标不同："
                "防夹区内出夹持判定，防夹区外出堵转判定（恩智浦 RDS12VR 的分区做法）。",
           source=[b(353, "堵转判定电流门限与去抖时间行"),
                   b(343, "RDS12VR：防夹区外做堵转检测")]),
        _p("stall_hold_time", "堵转允许持续时间", 30.0, 30.0, "s",
           1.0, 60.0, 1.0, group="保护与热管理", flows=[F3, F4],
           status="已核实但取自备选产品标准（QC/T 29090-2023 刮水电动机 4.18/5.18），"
                  "玻璃升降器的对应条款是耐久预处理的上止点堵转 1 s，两者不是一回事",
           note="台架侧的堵转施加时长上限。QC/T 626 征求意见稿里升降器自身只有"
                "「上止点堵转 1 s」（耐久预处理）与「堵转 1 s 停 4 s」（耐久单循环），"
                "30 s 连续堵转是刮水电动机标准的项目，本包把它作为台架保护的通用上限沿用，"
                "这是本包的推断，不是升降器标准的原文结论。",
           source=[b(270, "QC/T 29090-2023 堵转 4.18 / 5.18：试验电压下连续通电 30 s 堵转"),
                   b(198, "耐久试验预处理：托架升至上止点堵转 1 s"),
                   b(200, "耐久单循环波形：上止点堵转 1 s 停 4 s")]),
        _p("ovp_threshold", "过压保护阈值", 16.5, 16.5, "V", 14.0, 20.0, 0.1,
           group="保护与热管理", flows=[F2, F5], status=D,
           note="耐过负载操作强度试验就是在最大额定负载下施加 16.5 V 跑 10 个工作循环，"
                "所以固件的过压保护点不能低于 16.5 V，否则试验做不下去。",
           source=[b(202, "耐过负载操作强度 5.11.1 / 6.11.1：施加 16.5 V，跑 10 个工作循环"),
                   b(156, "过压保护判据 6.11.1")]),
        _p("uvp_threshold", "欠压保护阈值", 8.5, 8.5, "V", 5.0, 10.0, 0.1,
           group="保护与热管理", flows=[F2, F5], est=True, placeholder=True,
           note="示例值。必须低于启动电压判据 9 V，否则 9 V 启动试验会被自家欠压保护挡掉。"
                "8.5 V 是按这个约束反推的，不是标准给的数。",
           source=b(130, "启动电压 5.4.1 f) ≤9 V")),
        _p("ocp_threshold", "过流保护阈值", 30.0, 30.0, "A", 15.0, 45.0, 0.5,
           group="保护与热管理", flows=[F2, F5],
           note="必须高于 −30 ℃ 堵转电流上限 30 A，否则低温堵转试验会被保护挡掉；"
                "同时要低于 H 桥驱动能力（TIDA-01389 为 15 A，该方案就需要另配功率级）。",
           source=[b(161, "堵转电流 −30 ℃ 时 ≤30 A"),
                   b(140, "TIDA-01389 驱动能力 15 A")]),
        _p("thermal_trip_temp", "热保护跳闸温度", 140.0, 140.0, "℃",
           80.0, 180.0, 1.0, group="保护与热管理", flows=[F5], est=True,
           placeholder=True,
           note="示例值。征求意见稿只规定热保护的行为时序（首次启动循环数、恢复时间、再启动循环数），"
                "不规定跳闸温度，实际由 PTC 或热敏开关的选型决定。",
           source=b(162, "热保护（首次启动 / 恢复 / 再启动）表 5")),
        _p("thermal_first_start_cycles_normal", "热保护前首次启动循环数（常温与 −40 ℃）",
           30, 30, "循环", 1, 100, 1, group="保护与热管理", flows=[F3], status=D,
           note="判据是「不少于」：热保护必须撑过 30 个循环才允许动作。",
           source=b(162, "热保护表 5：−40 ℃ 与常温首次启动 ≥30 循环")),
        _p("thermal_first_start_cycles_80c", "热保护前首次启动循环数（80 ℃）",
           15, 15, "循环", 1, 100, 1, group="保护与热管理", flows=[F3], status=D,
           source=b(162, "热保护表 5：80 ℃ 首次启动 ≥15 循环")),
        _p("thermal_recovery_time_normal", "热保护恢复时间上限（常温与 −40 ℃）",
           60.0, 60.0, "s", 10.0, 300.0, 5.0, group="保护与热管理",
           flows=[F3], status=D,
           note="判据是「不大于」：60 s 内必须能恢复。与首次启动循环数方向相反，"
                "一个要「够久才跳」、一个要「够快才回」，两头夹住热保护元件的选型窗口。",
           source=b(162, "热保护表 5：恢复 ≤60 s")),
        _p("thermal_recovery_time_80c", "热保护恢复时间上限（80 ℃）",
           100.0, 100.0, "s", 10.0, 300.0, 5.0, group="保护与热管理",
           flows=[F3], status=D,
           source=b(162, "热保护表 5：80 ℃ 恢复 ≤100 s")),
        _p("thermal_restart_cycles", "热保护恢复后再启动循环数", 2, 2, "循环",
           1, 20, 1, group="保护与热管理", flows=[F3], status=D,
           source=b(162, "热保护表 5：再启动 ≥2 循环")),
        _p("reverse_polarity_voltage", "反极性试验电压", -4.0, -4.0, "V",
           -14.0, 0.0, 0.5, group="保护与热管理", flows=[F3],
           note="10.8 V 到 −4.0 V，持续 60 s（若继电器在极性反接时切断供电则改为 8 ms），3 个循环。"
                "LV 124 / VW 80000 试验 E-15 原文明确要求反极性期间不得触发任何安全相关功能，"
                "并点名电动车窗、天窗、起动机——这是本场景直接对号入座的条款。已核实。",
           source=[b(160, "反极性 LV 124 / VW 80000 试验 E-15"),
                   src(LV124_PDF, "MBN LV 124-1: 2013-03 试验 E-15 反极性")]),
    ]
    # ---- 电流环整定（跨场景复用，来自 Microchip MCAF）----
    P += [
        _p("current_loop_kp", "电流环比例增益 Kp", None, None, None,
           group="电流环整定", flows=[F5], placeholder=True,
           note="由相位裕度与 PI 相位滞后两项设计指标反算，不直接给数。"
                "MCAF 文档里的变量名是 motor.idCtrl.kp / motor.iqCtrl.kp。"
                "有刷直流单环电流控制没有 d/q 分解，只保留一路，但整定方法论可直接套用。",
           source=b(371, "Microchip MCAF 7.0.2 电流环整定参数表「电流环比例增益 Kp」行")),
        _p("current_loop_ki", "电流环积分增益 Ki", None, None, None,
           group="电流环整定", flows=[F5], placeholder=True,
           note="同上。变量名 motor.idCtrl.ki / motor.iqCtrl.ki。决定向给定值收敛的速度。",
           source=b(372, "Microchip MCAF 7.0.2 电流环整定参数表「电流环积分增益 Ki」行")),
        _p("phase_margin", "相位裕度 φm", 60.0, 80.0, "°", 40.0, 90.0, 1.0,
           group="电流环整定", flows=[F5],
           note="MCAF 默认 80°，实测后推荐 50° 至 70°，本包取中值 60°。"
                "调小则 Kp 与 Ki 同时变大，响应更快但超调风险升高；"
                "调大则增益下降、稳定性提高、带宽降低。已核实。",
           source=b(373, "Microchip MCAF 7.0.2「相位裕度 φm」行")),
        _p("pi_phase_lag", "PI 在穿越频率处的相位滞后 φz", 14.0, 45.0, "°",
           5.0, 45.0, 1.0, group="电流环整定", flows=[F5],
           note="MCAF 默认 45°，实测后推荐 8° 至 20°，低于 5° 不建议，本包取 14°。"
                "调小则 Kp 变大、Ki 变小，短期响应改善。已核实。",
           source=b(374, "Microchip MCAF 7.0.2「PI 在穿越频率处的相位滞后 φz」行")),
        _p("current_loop_bandwidth", "电流环带宽", 2000.0, 2000.0, "Hz",
           200.0, 3750.0, 50.0, group="电流环整定", flows=[F5],
           note="典型取 PWM 频率的 5 % 至 15 %（20 kHz PWM 对应 1 至 3 kHz）；"
                "良好整定目标约为采样率的 1/10。约束条件：机械时间常数 × 带宽须大于 1。已核实。",
           source=b(375, "Microchip MCAF 7.0.2「电流环带宽」行")),
        _p("tuning_order", "整定顺序", "CURRENT_LOOP_FIRST", "CURRENT_LOOP_FIRST",
           None, group="电流环整定", flows=[F5],
           options=["CURRENT_LOOP_FIRST", "SPEED_LOOP_FIRST"],
           note="MCAF 文档明确：若正常启动时序跑不通或无法正确切入闭环换相，"
                "电流环整定需在开环换相下进行。这条直接规定了「先整定电流环、再调开闭环切换」。已核实。",
           source=b(377, "同一文档另外明确：先整定电流环、再调开闭环切换")),
    ]
    # ---- 台架与工装 ----
    P += [
        _p("bench_supply_voltage", "台架程控电源设定电压", 13.5, 13.5, "V",
           9.0, 18.0, 0.1, group="台架与工装", flows=[F2, F4], status=D,
           source=b(123, "试验电压 6.1 b) 13.5 ± 0.3 V")),
        _p("bench_harness_resistance", "台架回路串入电阻", 0.15, 0.15, "Ω",
           0.13, 0.17, 0.01, group="台架与工装", flows=[F2], status=D,
           source=b(123, "接线电阻 0.15 ± 0.02 Ω")),
        _p("supply_ripple_max", "电源纹波峰峰值上限", 100.0, 100.0, "mV",
           10.0, 500.0, 10.0, group="台架与工装", flows=[F2], status=D,
           note="仪器选型门槛，不是被测件判据。",
           source=b(134, "仪器精度 6.1 a)：电源纹波峰峰值 ≤100 mV")),
        _p("test_rod_stiffness", "防夹试验棒刚度", 10.0, 10.0, "N/mm",
           9.5, 20.5, 0.1, group="台架与工装", flows=[F2, F3],
           options=[10.0, 20.0],
           note="GB 11552-2009 与 UN ECE R21 取 (10 ± 0.5) N/mm；"
                "FMVSS 118 的 25 至 200 mm 试棒取 20 N/mm（该值待核实）。"
                "刚度直接改变力-位移关系，换市场必须换棒，否则 100 N 的判定点会偏。",
           source=[src(GB11552_TXT, "gb11552.txt:449 「测量工具的刚度应为(10±0.5)N/mm」"),
                   b(215, "GB 11552-2009 试验棒刚度 (10 ± 0.5) N/mm"),
                   b(216, "FMVSS 118 试验棒刚度 20 N/mm（待核实）")]),
        _p("test_rod_diameter", "回缩验证试验棒直径", 200.0, 200.0, "mm",
           4.0, 200.0, 1.0, group="台架与工装", flows=[F3],
           note="用于验证 ROD_200MM_PASS 这一档回缩后位置：回缩后开口须能让直径 200 mm 的"
                "半刚性柱状试验棒穿过。已核实。",
           source=src(GB11552_TXT,
                      "gb11552.txt:445-446 §4.8.3.1.2.1 「允许穿过开口放置直径200mm 的"
                      "半刚性柱状试验棒的位置」")),
        _p("chamber_temperature", "环境箱温度设定", 23.0, 23.0, "℃",
           -40.0, 90.0, 1.0, group="台架与工装", flows=[F2, F4],
           note="耐久试验的 13 道工序要在这个参数上按表 7 走位："
                "常温 3000 次 → 80 ℃ 1500 → 60 ℃/90 %RH 2500 → 10 ℃/95 %RH 1000 "
                "→ −30 ℃ 1000 → 常温 1000。",
           source=[b(196, "耐久性（电动，前门）5.9.1 / 6.9.1 表 7 的 13 道工序"),
                   b(132, "常温定义 23 ± 2 ℃")]),
        _p("durability_cycle_target", "耐久目标循环数", 10000, 10000, "循环",
           1000, 20000, 500, group="台架与工装", flows=[F3, F4], status=D,
           note="前门 10 000、后门 5 000（各段次数减半）。",
           source=[b(196, "前门累计 10 000 个循环周期"),
                   b(197, "后门累计 5 000 个循环周期")]),
        _p("durability_dwell_time", "耐久单循环止点停留时间", 4.0, 4.0, "s",
           1.0, 60.0, 1.0, group="台架与工装", flows=[F4], status=D,
           note="单循环波形：起始位置 → 上止点堵转 1 s 停 4 s → 1/3 位置 → 下止点堵转 1 s 停 4 s，"
                "末次停 60 s。试验中允许对电机风冷或水冷。",
           source=b(200, "耐久单循环波形 6.9.1 注 3")),
        _p("durability_stall_time", "耐久单循环止点堵转时间", 1.0, 1.0, "s",
           0.5, 5.0, 0.5, group="台架与工装", flows=[F4], status=D,
           source=b(200, "耐久单循环波形 6.9.1 注 3")),
        _p("mud_water_dust_ratio", "耐久泥水粉尘配比", 7.5, 7.5, "%",
           0.0, 20.0, 0.5, group="台架与工装", flows=[F4], status=D,
           note="92.5 % 蒸馏水或去离子水 + 7.5 % 粉尘；粉尘按 ISO 12103-1 取 50 % A2 + 50 % A4。"
                "各温度段之间喷洒。",
           source=b(199, "耐久泥水配比 6.9.1 注")),
        _p("water_spray_pressure", "防水试验喷水压力", 0.1, 0.1, "MPa",
           0.05, 0.5, 0.01, group="台架与工装", flows=[F4], status=D,
           note="孔径 φ1.2 mm、孔数 40、喷水量 20 L/min、时间 30 min。判据是拆机后电机内部不应进水。",
           source=b(203, "防水性 5.12.1 / 6.12.1 表 9")),
        _p("dielectric_test_voltage", "绝缘介电强度试验电压", 550.0, 550.0, "V",
           500.0, 700.0, 10.0, group="台架与工装", flows=[F4], status=D,
           options=[550.0, 660.0],
           note="550 V、50 Hz 正弦交流历时 1 min；批量生产可用 660 V / 1 s 替代。"
                "选 660 V 时 dielectric_test_duration 必须同步改成 1 s，两者绑定。",
           source=[b(204, "绝缘介电强度 5.12.2 / 6.12.2"), b(163, "绝缘介电强度判据")]),
        _p("dielectric_test_duration", "绝缘介电强度试验时长", 60.0, 60.0, "s",
           1.0, 120.0, 1.0, group="台架与工装", flows=[F4], status=D,
           options=[60.0, 1.0],
           source=b(204, "绝缘介电强度 5.12.2 / 6.12.2")),
    ]
    # ---- 数据采集 ----
    P += [
        _p("sample_rate", "电流与位移采样率", 2000, 2000, "Sa/s",
           100, 100000, 100, group="数据采集", flows=[F2, F4],
           note="本包合成波形用的就是 2000 Sa/s × 12 s = 24000 行，与场景一的示波器"
                "深存储导出口径（2000 Sa/s、24000 行）刻意对齐，好让前端的时序组件不用改。"
                "真实台架若要做纹波计数，采样率须远高于纹波频率，2 kHz 只够看包络不够数纹波。",
           source=[src(os.path.join(os.path.dirname(os.path.dirname(
               os.path.abspath(__file__))), "assets/waveforms"),
               "本包三条合成 CSV 的生成参数，见 _build/gen_waveforms.py"),
               b(146, "纹波频率正比于实际转速")]),
        _p("force_sensor_range", "力传感器量程", 500.0, 500.0, "N",
           250.0, 2000.0, 50.0, group="数据采集", flows=[F2], est=True,
           placeholder=True,
           note="示例值。须同时覆盖堵转力 ≥212 N 与自锁加载 600 N 两个量级，"
                "还要在 100 N 处有足够分辨率。500 N 覆盖不了 600 N 的自锁工位，"
                "这两个工位实际上要分开选型——这正是前端该暴露给用户确认的冲突。",
           source=[b(126, "堵转力 ≥212 N，力传感器量程选型依据"),
                   b(131, "自锁能力：600 N 保持 5 s")]),
        _p("displacement_resolution", "长度器具最小刻度", 0.05, 0.05, "mm",
           0.01, 0.5, 0.01, group="数据采集", flows=[F2], status=D,
           note="仪器选型门槛。自锁判据的 5 mm 下降量要靠它测。",
           source=b(134, "仪器精度 6.1 a)：长度器具最小刻度 ≤0.05 mm")),
        _p("torque_meter_resolution", "扭矩仪最小刻度", 0.01, 0.01, "N·m",
           0.001, 0.1, 0.001, group="数据采集", flows=[F2], status=D,
           source=b(134, "仪器精度 6.1 a)：扭矩仪最小刻度 ≤0.01 N·m")),
    ]

    return dump("control-parameters.json", {
        "schema": "control-parameters/v1",
        "scene_id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "belongs_to_flow": "主放 F5 调优确认及运行 / F4 启动测试及结果分析；"
                           "使能类开关与台架设定在 F2 初始化配置确认",
        "groups": CP_GROUPS,
        "notes": [
            "adjustable_in_flows 标这个参数在哪个流程里允许改。同一个参数可能在多个流程出现，"
            "但含义不同：F2 是确认初值，F5 是未达标后回调。",
            "options 非空表示这是枚举参数，前端应出下拉框而不是加减号；"
            "此时 min/max/step 为 null。",
            "range_estimated: true 表示 min/max 区间是本包按物理约束推定的，源材料没给区间，"
            "前端不应把它当成标准规定的可调范围。",
            "防夹组的六个参数（力阈值、生效区间上下沿、启动屏蔽时间、纹波滤波、堵转门限、回缩行程）"
            "是本场景相对场景一全新的一组，场景一没有任何对应物；"
            "电流环整定那五个参数则是两个场景共用的通用层。",
        ],
        "parameters": P,
    })


# ====================== safety-interlocks.json ======================

def gen_safety_interlocks():
    D = DRAFT_STATUS
    I = []

    def it(iid, name, typ, threshold, action, blocking, source,
           status=None, placeholder=False, quote=None, note=None):
        d = {"id": iid, "name": name, "type": typ, "threshold": threshold,
             "action": action, "blocking": blocking}
        if quote:
            d["quote"] = quote
        if note:
            d["note"] = note
        if status:
            d["_status"] = status
        if placeholder:
            d["_placeholder"] = True
        d["_source"] = source
        return d

    # ---- 硬件：被测件自身与台架仪器的阈值 ----
    I += [
        it("SI-HW-01", "防夹力上限（人身安全硬顶）", "硬件",
           {"max_force_n": 100, "opening_range_mm": [4, 200],
            "rod_stiffness_n_per_mm": 10.0},
           "开口 4 至 200 mm 区间内，夹紧力达到 100 N 之前必须回缩。"
           "台架侧：力传感器读数越过 100 N 立即切断被测件供电并置试验为 FAIL，不等固件动作。",
           True,
           [src(GB11552_TXT, "gb11552.txt:440 §4.8.3.1.1"),
            b(166, "防夹力 GB 11552-2009 §4.8.3.1.1（已核实）")],
           quote="开口从200mm 到4mm 范围内，在夹紧力大于100N 之前，该装置应回缩车窗/天窗/隔断系统。",
           note="这是本场景唯一一条「人身安全」性质的硬顶，也是它相对场景一"
                "（设备安全：过温、堵转）的本质差异。三地法规在这个数值上完全一致。"),
        it("SI-HW-02", "堵转电流上限", "硬件",
           {"normal_a": 28.0, "at_80c_a": 29.0, "at_minus30c_a": 30.0},
           "超过对应温度档的上限即判 FAIL 并停机。台架过流保护阈值须设在 30 A 以上，"
           "否则低温堵转试验会被台架自己挡掉。",
           True,
           [src(QC626_TXT, "qc636.txt:119-120 5.4.1 b)"),
            b(161, "堵转电流温度分档"), b(125, "堵转电流上限 5.4.1 b)")],
           status=D),
        it("SI-HW-03", "堵转持续时间上限", "硬件",
           {"max_seconds": 30.0, "durability_cycle_stall_s": 1.0},
           "连续堵转超过 30 s 强制断电。耐久单循环里的上止点/下止点堵转只有 1 s，"
           "正常流程不会触及这条，它挡的是控制流程跑飞。",
           True,
           [b(270, "QC/T 29090-2023 4.18/5.18 连续通电 30 s 堵转"),
            b(200, "耐久单循环波形：上止点堵转 1 s")],
           status="30 s 取自备选产品标准（刮水电动机），沿用到升降器台架是本包的推断，"
                  "不是升降器标准的原文结论"),
        it("SI-HW-04", "供电电压上限", "硬件",
           {"normal_max_v": 16.0, "overload_test_v": 16.5,
            "long_term_overvoltage_v": 18.0, "jump_start_v": 26.0},
           "超过当前试验项允许的电压上限立即降压。四个数对应四个不同试验项，"
           "切换试验项时这个阈值必须跟着换，不能取最大值一刀切——"
           "用 26 V 的门限去跑基本性能试验等于没有保护。",
           True,
           [b(122, "工作电压范围 9 至 16 V"),
            b(202, "耐过负载操作强度：施加 16.5 V"),
            b(157, "ISO 16750-2:2023 §4.3.1.1.2 长时过电压 18 V / 60 min（已核实）"),
            b(158, "ISO 16750-2:2023 §4.3.1.2.2 表 5 跨接启动 26 V / 60 ± 6 s（已核实）")]),
        it("SI-HW-05", "瞬态过电压", "硬件",
           {"peak_v": 18.0, "duration_ms": 400, "rise_fall_ms": 1,
            "interval_s": 1, "count": 5, "min_function_class": "B"},
           "按 ISO 16750-2:2023 §4.3.2.2 表 6 施加，要求最低功能状态 class B。已核实。",
           False,
           [b(159, "瞬态过电压 ISO 16750-2:2023 §4.3.2.2 表 6"),
            src(ISO16750_2_PDF, "ISO 16750-2:2023 §4.3.2.2 表 6")]),
        it("SI-HW-06", "反极性保护", "硬件",
           {"from_v": 10.8, "to_v": -4.0, "duration_s": 60,
            "duration_if_relay_cutoff_ms": 8, "cycles": 3},
           "反极性期间不得触发任何安全相关功能。LV 124 / VW 80000 试验 E-15 原文点名"
           "电动车窗、天窗、起动机，本场景直接对号入座：反接时车窗绝不能自己动。已核实。",
           True,
           [b(160, "反极性 LV 124 / VW 80000 试验 E-15"),
            src(LV124_PDF, "MBN LV 124-1: 2013-03 试验 E-15")]),
        it("SI-HW-07", "温度上限（环境箱与被测件外壳）", "硬件",
           {"chamber_max_c": 80.0, "chamber_min_c": -30.0,
            "iso16750_4_code_c": [-40.0, 65.0],
            "case_temp_max_c": 120.0},
           "环境箱越限报警并中止试验。case_temp_max_c 是台架加的外壳表面温度监视点。",
           True,
           [b(192, "耐高温特性 80 ℃"), b(193, "耐低温特性 −30 ℃"),
            b(238, "ISO 16750-4:2023 温度代码 C 为 −40/65 ℃（已核实）")],
           status="case_temp_max_c 120 ℃ 是本包编的台架监视门限，"
                  "征求意见稿与 ISO 16750-4 都没有给外壳表面温度限值",
           placeholder=True),
        it("SI-HW-08", "绝缘介电强度施加上限", "硬件",
           {"voltage_v": 550, "frequency_hz": 50, "duration_s": 60,
            "alt_voltage_v": 660, "alt_duration_s": 1},
           "高压工位施加期间被测区域必须无人；超时或超压立即断高压。",
           True,
           [b(204, "绝缘介电强度 5.12.2 / 6.12.2"), b(163, "绝缘介电强度判据")],
           status=D),
        it("SI-HW-09", "力传感器过载保护", "硬件",
           {"trip_n": 700.0, "self_lock_load_n": 600.0, "stall_force_min_n": 212.0},
           "超过 700 N 切断加载油缸/电缸。自锁工位加载 600 N，留 100 N 裕量。",
           True,
           [b(131, "自锁能力：600 N 保持 5 s"), b(126, "堵转力 ≥212 N")],
           status="700 N 的跳闸点是本包按 600 N 加载留裕量定的，源材料没有这个数",
           placeholder=True),
        it("SI-HW-10", "故障位图（示例）", "硬件",
           {"bitmap_ref": "fault_bitmap"},
           "台架从被测件读回的故障字。本场景没有客户固件源码，位定义是本包按"
           "本文件已登记的保护项编的示例，用于让前端的位运算判据（如 "
           "(fault_flags & 0x0008) == 0）有东西可解。不得当作任何真实产品的接口定义。",
           False,
           [b("156-166", "第一层被测件保护判据表，位定义按该表逐项编号")],
           placeholder=True),
    ]
    # ---- 流程 ----
    I += [
        it("SI-PR-01", "试验顺序不得打乱", "流程",
           {"group_count": 6, "min_samples_per_group": 2},
           "型式检验项目分组后按固定顺序执行，跨组样件不得混用。"
           "Agent 自动排程时必须把分组约束作为硬约束，不能为了省时间并行。",
           True,
           [b(414, "QC/T 626 征求意见稿第 7 章检验规则"),
            b(279, "QC/T 29090-2023 型式检验 6.3：20 个项目分 6 组，每组不少于 2 套")],
           status="分组数与每组样件数取自备选产品标准 QC/T 29090-2023；"
                  "QC/T 626 征求意见稿第 7 章的具体分组本次未逐条提取"),
        it("SI-PR-02", "耐久试验预处理不得跳过", "流程",
           {"stall_at_top_s": 1.0, "soak_temp_c": 90.0, "soak_hours": 2.0},
           "托架升至上止点堵转 1 s、切断电源、90 ℃ 环境放置 2 h。"
           "跳过预处理会让后续 10 000 次循环的结果不可比。",
           True,
           [b(198, "耐久试验预处理 6.9.1 表 7 序号 2")],
           status=D),
        it("SI-PR-03", "盐雾后的偏差口径必须先约定", "流程",
           {"allowed_deviation_pct": 20,
            "items": ["工作电流", "堵转力", "运行速度", "工作噪音"]},
           "耐腐蚀试验后工作电压项须合格，电流、堵转力、速度、噪音四项允许与试验前偏差 20 %。"
           "「与试验前偏差」意味着必须有试验前的同件基线数据，否则这条判据无法求值——"
           "Agent 排程时要保证前置基线测量已完成并留痕。",
           True,
           [b(195, "耐腐蚀性 5.8 / 6.8")],
           status=D),
        it("SI-PR-04", "引用标准换版核对", "流程",
           {"outdated_refs": ["GB/T 18655-2010 → GB/T 18655-2025",
                              "GB/T 21437.2-2008 → GB/T 21437.2-2021",
                              "GB/T 10125-2012 → GB/T 10125-2021"]},
           "征求意见稿引用的三本标准都已换版，落地前必须逐条改引现行版。"
           "知识库的换版预警元数据就是为这一步准备的。",
           True,
           [b(206, "电磁兼容性 5.12.4：两本引用标准均已换版"),
            b(85, "GB/T 10125-2021 全部代替 2012 版"),
            b(81, "GB/T 18655-2025 已代替 2018 版")]),
        it("SI-PR-05", "合成数据不得进正式报告", "流程",
           {"synthetic_datasets": 3},
           "本包 datasets.json 的三条波形全部是合成的（synthetic: true）。"
           "它们只能用于前端演示与算法联调，不得作为任何合规报告的试验数据。"
           "界面上必须显式标注来源。",
           True,
           [b(429, "与峰岹案例对照表流程 4 行：合成数据必须在界面标注来源"),
            b(286, "汽车低压执行器电机的专用公开波形数据集，在十三个平台上确认为空白")]),
        it("SI-PR-06", "非授权副本不得作为正式引用依据", "流程",
           {"affected": ["LV 124 / MBN LV 124-1: 2013-03", "VW 80000: 2022-12",
                         "MBN LV 148: 2013-11", "BMW GS 95024-3-1: 2010-01"]},
           "这四份 OEM 规范的本地副本均为公网流传的非授权版本，内容可信但不具备引用资格。"
           "正式报告引用前须经采购渠道取得授权原本复核。",
           True,
           [b(94, "LV 124：该 PDF 为公网流传的非授权副本"),
            b(95, "VW 80000：同为非授权副本"),
            b(464, "OEM 规范通道：内容可信但均为公网流传的非授权副本")]),
    ]
    # ---- 人员 ----
    I += [
        it("SI-PE-01", "防夹试验期间人员离场确认", "人员",
           {"confirm_required": True, "zone": "夹持工位 1 m 内"},
           "防夹试验要真实制造夹持工况，力最高可达 100 N。"
           "开始前操作者须显式确认夹持工位无人、无手部伸入，未确认不允许下发启动指令。",
           True,
           [b(166, "防夹力 100 N"),
            b(180, "把机械安全标准落到 Agent 自动施加过压、堵转、短路这一具体场景")],
           status="「人员离场确认」这个动作本身是本包按 GB/T 15706-2012 风险评估思路加的，"
                  "不是任何一本标准的原文条款"),
        it("SI-PE-02", "高压绝缘工位人员防护", "人员",
           {"confirm_required": True, "voltage_v": 550},
           "550 V 交流施加前须确认防护门闭合、人员离场。防护门联锁按 ISO 14119:2024 选型，"
           "2024 版新增的第 5 类钥匙转移式联锁适合「必须先切断动力才能开门」的工位。",
           True,
           [b(204, "绝缘介电强度 550 V / 50 Hz / 1 min"),
            b(176, "ISO 14119:2024 联锁装置设计与选择原则")],
           status="选型建议是基于标准适用范围的推断，不是标准原文结论"),
        it("SI-PE-03", "自动施加过压与堵转前的风险评估留痕", "人员",
           {"confirm_required": True,
            "basis": ["GB/T 15706-2012", "ISO 13849-1:2023", "IEC 62061:2021"]},
           "Agent 自动加载、自动切换工况、自动施加过压与堵转之前，"
           "须先按 GB/T 15706-2012 做风险评估，再按 ISO 13849-1 定性能等级"
           "或按 IEC 62061 定安全完整性等级，评估结论要有人签字留痕。",
           True,
           [b(173, "GB/T 15706-2012 机械安全 设计通则 风险评估与风险减小"),
            b(174, "ISO 13849-1:2023 性能等级 PL 分 a 至 e 五档"),
            b(175, "IEC 62061:2021 第 2.0 版"),
            b(180, "说明：这是基于标准适用范围的推断，不是任何一本标准的原文结论")],
           status="素材综述文档原文已声明：这一落地方式是基于标准适用范围的推断，"
                  "不是任何一本标准的原文结论"),
        it("SI-PE-04", "台架电气安全总则确认", "人员",
           {"confirm_required": True,
            "basis": ["GB/T 5226.1-2019（等同采用 IEC 60204-1:2016）",
                      "IEC 61010-1 Ed. 3.1 b:2017"]},
           "台架本体的电源断路开关、电击防护、控制电路与控制功能、标志与警告标识"
           "须符合 GB/T 5226.1-2019；测量与实验室设备部分按 IEC 61010-1。"
           "注意 GB/T 5226.1 的前缀由 GB 改为 GB/T，即由强制性改为推荐性。",
           False,
           [b(172, "GB/T 5226.1-2019 机械电气安全"),
            b(177, "IEC 61010-1：中国对应的 GB 4793.1-2007 落后两代")]),
        it("SI-PE-05", "实验室能力与报告签发资质", "人员",
           {"confirm_required": True, "basis": ["ISO/IEC 17025:2017 §7.8"]},
           "报告签发人须为授权签字人。ISO/IEC 17025:2017 第 7.8.2 条规定报告必含要素："
           "标题、实验室标识、每页唯一报告编号、客户信息、方法引用、样品描述、"
           "接收/试验/签发日期、带单位的结果、授权签字、修订条款。",
           True,
           [b(178, "ISO/IEC 17025:2017 第 3 版，第 7.8 条规定报告必含要素"),
            b(411, "ISO/IEC 17025:2017 第 7.8 条 Reporting of results")],
           status="7.8.2 的字段清单经 PJLA 培训讲义转述，标准正文本次未取得"),
    ]

    return dump("safety-interlocks.json", {
        "schema": "safety-interlocks/v1",
        "scene_id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "belongs_to_flow": "F2 初始化配置（呈现与确认）+ F4 启动测试及结果分析（不确认不允许运行）",
        "types": {
            "硬件": "由固件阈值或仪器状态判定",
            "流程": "由规程纪律约束执行顺序与动作",
            "人员": "需要操作者显式确认才能放行",
        },
        "fault_bitmap": {
            "_placeholder": True,
            "_source": b("156-166", "第一层被测件保护判据表，位定义按该表逐项编号"),
            "note": "本场景没有客户固件源码，位定义是本包按已登记的保护项编的示例。"
                    "判据表达式里对它做位运算时必须加括号，"
                    "如 (fault_flags & 0x0008) == 0，"
                    "否则 Python 与 C 的 & 优先级低于 == 会算错。",
            "bits": {
                "0x0000": "FAULT_NONE 无故障",
                "0x0001": "FAULT_OCP 过流（堵转电流越限）",
                "0x0002": "FAULT_STALL 堵转（电流门限 + 去抖确认）",
                "0x0004": "FAULT_PINCH 夹持（防夹判据触发，已执行回缩）",
                "0x0008": "FAULT_PINCH_FORCE_OVER 夹持力越过 100 N（人身安全，不可复位）",
                "0x0010": "FAULT_OVP 过压",
                "0x0020": "FAULT_UVP 欠压",
                "0x0040": "FAULT_THERMAL 热保护动作",
                "0x0080": "FAULT_REVERSE_POLARITY 反极性检出",
                "0x0100": "FAULT_POS_LOST 位置丢失（纹波/霍尔计数异常）",
                "0x0200": "FAULT_SOFTSTOP_MISS 软停位置未命中",
                "0x8000": "FAULT_TEST 测试用",
            },
        },
        "interlocks": I,
    })


# ====================== test-requirements.json ======================

# 运行时测量量登记表：criterion 里 source=runtime.measure 的变量全部在此注册
RUNTIME_MEASURES = {}


def rm(key, name, unit, obtained_by):
    RUNTIME_MEASURES[key] = {"name": name, "unit": unit, "obtained_by": obtained_by}
    return key


# ---- 逐个登记（登记一次，判据里按 key 引用）----
_M = [
    ("voltage_min_v", "试验实际施加的最低电压", "V", "程控电源回读"),
    ("voltage_max_v", "试验实际施加的最高电压", "V", "程控电源回读"),
    ("abnormal_noise", "是否出现异音", None, "声学录音的频谱异常检出，布尔"),
    ("jam_detected", "是否出现卡滞", None, "电流突变与位移停滞联合判定，布尔"),
    ("working_current_up_a", "上升过程工作电流", "A", "电流传感器，取稳态段均值"),
    ("working_current_down_a", "下降过程工作电流", "A", "电流传感器，取稳态段均值"),
    ("stall_current_a", "堵转电流", "A", "电流传感器，取堵转平台段均值"),
    ("stall_force_n", "堵转力", "N", "力传感器，取堵转段峰值"),
    ("rise_speed_mm_s", "上升运行速度", "mm/s", "位移传感器测行程 ÷ 计时得运行时间"),
    ("down_speed_mm_s", "下降运行速度", "mm/s", "位移传感器测行程 ÷ 计时得运行时间"),
    ("noise_dba", "工作噪音", "dB(A)", "声级计置于电机出力轴正上方 300 mm，取升降全过程最大值"),
    ("background_noise_dba", "背景噪音", "dB(A)", "同一测点空场测量"),
    ("start_voltage_v", "启动电压", "V", "程控电源缓升，记录托架开始移动时的电压"),
    ("drop_mm", "自锁加载下托架下降量", "mm", "位移传感器，取加载 5 s 末与加载前之差"),
    ("damaged", "试验后是否损坏", None, "目视检查裂纹、变形、跳齿，布尔"),
    ("peak_pinch_force_n", "夹持力峰值", "N", "力传感器，取整个夹持过程最大值"),
    ("retract_triggered", "是否触发回缩（停止并反向）", None, "位移曲线出现反向，布尔"),
    ("opening_at_trigger_mm", "触发回缩时的开口量", "mm", "位移传感器换算"),
    ("opening_after_mm", "回缩完成后的开口量", "mm", "位移传感器换算"),
    ("opening_before_close_mm", "本次关闭动作开始时的开口量", "mm", "位移传感器换算"),
    ("tilt_at_max_angle", "天窗是否停在最大角度开启位置", None, "角度传感器，布尔"),
    ("detect_latency_ms", "从夹持开始到回缩动作的延迟", "ms", "力曲线起点与位移反向点的时间差"),
    ("pinch_detected_in_startup", "启动屏蔽窗内的夹持是否被检出", None, "回缩动作是否发生，布尔"),
    ("close_start_opening_mm", "允许开始关闭时的开口量", "mm", "位移传感器"),
    ("remote_range_m", "遥控器可触发关闭的最大作用距离", "m", "卷尺定距 + 遥控触发验证"),
    ("one_touch_limited_to_driver_and_roof", "一键关闭是否仅限驾驶员侧车窗与天窗",
     None, "逐个开关功能核对，布尔"),
    ("protection_auto_reset", "保护装置是否自动复位", None, "复位后再次下发指令能否正常动作，布尔"),
    ("motion_resumed_without_switch", "复位后是否未经操作开关即自行继续关闭",
     None, "复位后静置观察位移曲线，布尔"),
    ("post_vibration_basic_pass", "振动试验后基本性能是否全项合格",
     None, "复跑 TR-BASIC-01 至 TR-BASIC-08 取合取，布尔"),
    ("post_test_basic_pass", "本试验后基本性能是否全项合格",
     None, "复跑 TR-BASIC-01 至 TR-BASIC-08 取合取，布尔"),
    ("voltage_item_pass", "工作电压项是否合格", None, "复跑 TR-BASIC-01，布尔"),
    ("current_before_a", "试验前工作电流基线", "A", "盐雾/耐久前的同件基线测量"),
    ("current_after_a", "试验后工作电流", "A", "试验后复测"),
    ("force_before_n", "试验前堵转力基线", "N", "试验前的同件基线测量"),
    ("force_after_n", "试验后堵转力", "N", "试验后复测"),
    ("speed_before_mm_s", "试验前上升速度基线", "mm/s", "试验前的同件基线测量"),
    ("speed_after_mm_s", "试验后上升速度", "mm/s", "试验后复测"),
    ("noise_before_dba", "试验前工作噪音基线", "dB(A)", "试验前的同件基线测量"),
    ("noise_after_dba", "试验后工作噪音", "dB(A)", "试验后复测"),
    ("ferrous_surface_corrosion", "黑色金属零件主要表面是否有基体腐蚀物",
     None, "目视检查，布尔"),
    ("total_cycles", "累计完成的开闭循环数", "循环", "台架循环计数器"),
    ("function_normal", "试验后功能是否正常", None, "复跑基本性能，布尔"),
    ("gear_slip", "是否出现跳齿打滑", None, "位移与电流联合判定，布尔"),
    ("plastic_crack", "塑料件是否开裂", None, "拆机目视检查，布尔"),
    ("max_perf_deviation", "各性能项相对试验前基线的最大偏差", "比例",
     "逐项复测后按 |后−前| / 前 取最大"),
    ("no_crack_or_melt", "零部件是否无裂纹无融解", None, "拆机目视检查，布尔"),
    ("water_ingress_in_motor", "电机内部是否进水", None, "拆机目视检查，布尔"),
    ("dielectric_breakdown", "绝缘是否被击穿", None, "耐压仪判定，布尔"),
    ("ambient_c", "试验环境温度", "℃", "环境箱温度回读"),
    ("first_start_cycles", "热保护动作前完成的首次启动循环数", "循环", "台架循环计数器"),
    ("recovery_s", "热保护从跳闸到可再启动的恢复时间", "s", "计时"),
    ("restart_cycles", "热保护恢复后完成的再启动循环数", "循环", "台架循环计数器"),
    ("radiated_emission_level", "辐射发射等级", "级", "EMC 暗室测量后按限值表判级"),
    ("conducted_emission_level", "传导发射等级", "级", "EMC 测量后按限值表判级"),
    ("transient_conducted_level_roman", "沿电源线瞬态传导发射等级（罗马数字转整数）",
     "级", "按 GB/T 21437.2 附录判级后转整数，III → 3"),
    ("hazardous_substances_pass", "六项有害物质是否全部合格", None, "第三方检测报告，布尔"),
    ("function_class", "试验期间与试验后的功能状态等级", None,
     "按 ISO 16750-1 的功能状态分级 A/B/C/D 判定"),
    ("fault_flags", "被测件故障字回读整值", None,
     "台架读取被测件故障寄存器；位定义见 safety-interlocks.json fault_bitmap（示例）"),
    ("window_motion_detected", "反极性期间车窗是否发生移动", None, "位移传感器，布尔"),
]
for _k, _n, _u, _o in _M:
    rm(_k, _n, _u, _o)


def _vm(key, desc=None, unit="__auto__"):
    """runtime.measure 变量。desc / unit 默认取登记表里的值。"""
    reg = RUNTIME_MEASURES[key]
    d = {"source": "runtime.measure", "ref": "runtime.measure." + key,
         "desc": desc or reg["name"]}
    u = reg["unit"] if unit == "__auto__" else unit
    if u is not None:
        d["unit"] = u
    return d


def _vt(name, desc, unit=None):
    """threshold 变量，指向本条自己的 threshold 字段。"""
    d = {"source": "threshold", "ref": "threshold." + name, "desc": desc}
    if unit is not None:
        d["unit"] = unit
    return d


def _vc(key, desc, unit=None):
    """control-parameters 变量，指向 control-parameters.json 的 parameters[].key。"""
    d = {"source": "control-parameters", "ref": "control-parameters." + key, "desc": desc}
    if unit is not None:
        d["unit"] = unit
    return d


def gen_test_requirements():
    D = DRAFT_STATUS
    R = []

    def rq(rid, name, category, criterion, criterion_text, variables,
           threshold, evidence, flows, source, evaluable=True,
           not_evaluable_reason=None, status=None, placeholder=False, note=None):
        d = {"id": rid, "name": name, "category": category,
             "evaluable": evaluable, "criterion": criterion}
        if not evaluable:
            d["not_evaluable_reason"] = not_evaluable_reason
        d["criterion_text"] = criterion_text
        d["variables"] = variables
        d["threshold"] = threshold
        d["evidence"] = evidence
        d["flows"] = flows
        if note:
            d["note"] = note
        if status:
            d["_status"] = status
        if placeholder:
            d["_placeholder"] = True
        d["_source"] = source
        return d

    ALL = ["F3 测试需求确认", "F4 启动测试及结果分析"]

    # ---------- 基本性能 ----------
    R += [
        rq("TR-BASIC-01", "工作电压范围内运行平稳", "基本性能",
           "voltage_min_v >= v_min && voltage_max_v <= v_max && "
           "abnormal_noise === false && jam_detected === false",
           "在 9 V 至 16 V 全区间内运行平稳，不允许有异音和卡滞现象",
           {"voltage_min_v": _vm("voltage_min_v"),
            "voltage_max_v": _vm("voltage_max_v"),
            "v_min": _vt("v_min", "工作电压下限", "V"),
            "v_max": _vt("v_max", "工作电压上限", "V"),
            "abnormal_noise": _vm("abnormal_noise"),
            "jam_detected": _vm("jam_detected")},
           {"v_min": 9.0, "v_max": 16.0},
           ["程控电源电压回读", "声学录音", "电流波形", "位移曲线"], ALL,
           [src(QC626_TXT, "qc636.txt:117-118 5.4.1 a)"), b(122, "工作电压范围 5.4.1 a)")],
           status=D,
           note="abnormal_noise 与 jam_detected 在标准原文里是主观描述，"
                "本包把它们定义成布尔运行时量以便表达式可求值；"
                "怎么从波形算出这两个布尔值是判定工具的事，不是判据本身的事。"),
        rq("TR-BASIC-02", "上升工作电流上限", "基本性能",
           "working_current_up_a <= max_a",
           "上升工作电流不大于 12 A（常温，试验电压 13.5 ± 0.3 V）",
           {"working_current_up_a": _vm("working_current_up_a"),
            "max_a": _vt("max_a", "工作电流上限", "A")},
           {"max_a": 12.0, "test_voltage_v": 13.5, "ambient_c": 23.0},
           ["电流波形", "程控电源电压回读"], ALL,
           [src(QC626_TXT, "qc636.txt:119-120 5.4.1 b)"), b(124, "工作电流上限 5.4.1 b)")],
           status=D),
        rq("TR-BASIC-03", "堵转电流上限", "基本性能",
           "stall_current_a <= max_a",
           "堵转电流不大于 28 A（常温）。托架上升到上止点使电机堵转时测量",
           {"stall_current_a": _vm("stall_current_a"),
            "max_a": _vt("max_a", "常温堵转电流上限", "A")},
           {"max_a": 28.0, "max_a_80c": 29.0, "max_a_minus30c": 30.0},
           ["电流波形", "位移曲线（确认已到止点）"], ALL,
           [src(QC626_TXT, "qc636.txt:304-306 6.4.1 b) 堵转电流测量方法"),
            b(125, "堵转电流上限"), b(161, "堵转电流温度分档")],
           status=D,
           note="换温度档时把 threshold.max_a 换成 max_a_80c 或 max_a_minus30c，表达式不变。"),
        rq("TR-BASIC-04", "堵转力下限", "基本性能",
           "stall_force_n >= min_n",
           "堵转力不小于 212 N。无负载条件下托架上升到上止点时在运行反方向施加力使电机堵转，"
           "用力传感器测量",
           {"stall_force_n": _vm("stall_force_n"),
            "min_n": _vt("min_n", "常温堵转力下限", "N")},
           {"min_n": 212.0, "min_n_80c": 164.0, "min_n_minus30c": 190.0},
           ["力传感器曲线", "电流波形"], ALL,
           [src(QC626_TXT, "qc636.txt:307-310 6.4.1 c) 堵转力测量"),
            b(126, "堵转力 5.4.1 c)")],
           status=D,
           note="注意方向：堵转力是「越大越好」的下限判据，而防夹力是「越小越好」的上限判据"
                "（100 N）。同一支力传感器上两个方向相反的判据同时成立，"
                "因为它们发生在行程的不同区段——这是本场景判据模型比第一个包复杂的地方。"),
        rq("TR-BASIC-05", "上升运行速度区间", "基本性能",
           "rise_speed_mm_s >= min_mm_s && rise_speed_mm_s <= max_mm_s",
           "上升运行速度应在 80 mm/s 至 160 mm/s 之间。"
           "测量托架从下止点到上止点的运行时间和行程后按公式换算",
           {"rise_speed_mm_s": _vm("rise_speed_mm_s"),
            "min_mm_s": _vt("min_mm_s", "上升速度下限", "mm/s"),
            "max_mm_s": _vt("max_mm_s", "上升速度上限", "mm/s")},
           {"min_mm_s": 80.0, "max_mm_s": 160.0, "min_mm_s_minus30c": 60.0},
           ["位移曲线", "计时"], ALL,
           [src(QC626_TXT, "qc636.txt:312-315 6.4.1 d) 运行速度测量"),
            b(127, "上升运行速度 5.4.1 d)")],
           status=D),
        rq("TR-BASIC-06", "下降运行速度上限", "基本性能",
           "down_speed_mm_s <= max_mm_s",
           "下降运行速度不大于 200 mm/s。改变电源极性使托架下降后同法测量",
           {"down_speed_mm_s": _vm("down_speed_mm_s"),
            "max_mm_s": _vt("max_mm_s", "下降速度上限", "mm/s")},
           {"max_mm_s": 200.0, "min_mm_s_minus30c": 70.0},
           ["位移曲线", "计时"], ALL,
           [src(QC626_TXT, "qc636.txt:312-315 6.4.1 d)"), b(128, "下降运行速度 5.4.1 d)")],
           status=D),
        rq("TR-BASIC-07", "工作噪音上限", "基本性能",
           "noise_dba < max_dba && background_noise_dba <= noise_dba - background_margin_dba",
           "工作噪音小于 60 dB(A)。传声器置于电机出力轴正上方 300 mm，"
           "背景噪音须低于测试噪音 10 dB(A)，上升与下降过程均测",
           {"noise_dba": _vm("noise_dba"),
            "background_noise_dba": _vm("background_noise_dba"),
            "max_dba": _vt("max_dba", "工作噪音上限", "dB(A)"),
            "background_margin_dba": _vt("background_margin_dba",
                                         "背景噪音须低于测试噪音的裕量", "dB(A)")},
           {"max_dba": 60.0, "mic_distance_mm": 300.0, "background_margin_dba": 10.0},
           ["声级计读数", "背景噪音基线"], ALL,
           [src(QC626_TXT, "qc636.txt:324-328 6.4.1 e) 工作噪音试验"),
            b(129, "工作噪音 5.4.1 e)")],
           status=D,
           note="把背景噪音条件也写进表达式，是因为背景噪音不达标时噪音读数本身无效——"
                "不能先判 PASS 再补一句「环境不合格」。"),
        rq("TR-BASIC-08", "启动电压上限", "基本性能",
           "start_voltage_v <= max_v",
           "启动电压不大于 9 V。无负载条件下运行升降器使托架上升，记录托架上升时的启动电压值",
           {"start_voltage_v": _vm("start_voltage_v"),
            "max_v": _vt("max_v", "启动电压上限", "V")},
           {"max_v": 9.0, "max_v_minus30c": 10.0},
           ["程控电源电压回读", "位移曲线（判定起动时刻）"], ALL,
           [src(QC626_TXT, "qc636.txt:332-334 6.4.1 f) 启动电压"), b(130, "启动电压 5.4.1 f)")],
           status=D),
    ]
    # ---------- 自锁 ----------
    R += [
        rq("TR-LOCK-01", "自锁性（上止点与半行程）", "自锁",
           "drop_mm <= max_drop_mm && damaged === false",
           "上止点与一半行程两处，在玻璃托架上垂直向下施加 600 N 保持 5 s，"
           "托架下降量不大于 5 mm 且不应损坏",
           {"drop_mm": _vm("drop_mm"), "damaged": _vm("damaged"),
            "max_drop_mm": _vt("max_drop_mm", "允许下降量上限", "mm")},
           {"load_n": 600.0, "hold_s": 5.0, "max_drop_mm": 5.0,
            "positions": ["上止点", "一半玻璃托架行程处"]},
           ["位移传感器", "加载力曲线", "试验后目视检查"], ALL,
           [src(QC626_TXT, "qc636.txt:142-144 5.5；:372-374 6.5 自锁性试验"),
            b(131, "自锁能力 5.5"), b(191, "自锁性 5.5 / 6.5")],
           status=D),
    ]
    # ---------- 防夹 ----------
    R += [
        rq("TR-PINCH-01", "防夹力上限（中国 GB 11552-2009）", "防夹",
           "peak_pinch_force_n < max_force_n && retract_triggered === true && "
           "opening_at_trigger_mm >= opening_min_mm && "
           "opening_at_trigger_mm <= opening_max_mm",
           "开口从 200 mm 到 4 mm 范围内，夹紧力大于 100 N 之前必须回缩。"
           "试验棒刚度 (10 ± 0.5) N/mm，从车内穿过开口伸出车外，"
           "其圆柱面与构成车窗边界的车辆结构部分接触，整个试验期间位置保持不变",
           {"peak_pinch_force_n": _vm("peak_pinch_force_n"),
            "retract_triggered": _vm("retract_triggered"),
            "opening_at_trigger_mm": _vm("opening_at_trigger_mm"),
            "max_force_n": _vt("max_force_n", "法规夹持力上限", "N"),
            "opening_min_mm": _vt("opening_min_mm", "防夹生效区间下沿", "mm"),
            "opening_max_mm": _vt("opening_max_mm", "防夹生效区间上沿", "mm")},
           {"max_force_n": 100.0, "opening_min_mm": 4.0, "opening_max_mm": 200.0,
            "rod_stiffness_n_per_mm": 10.0, "rod_stiffness_tol_n_per_mm": 0.5},
           ["力传感器曲线", "位移曲线", "电流波形"], ALL,
           [src(GB11552_TXT, "gb11552.txt:440 §4.8.3.1.1；:446-452 §4.8.3.1.3 试验棒与刚度"),
            b(215, "三地防夹对照表 GB 11552-2009 行"), b(166, "防夹力判据（已核实）")],
           note="这是全包唯一一条直接关乎人身安全的判据，也是本场景相对第一个包"
                "（全部为设备安全判据）最有演示价值的一条。"),
        rq("TR-PINCH-02", "回缩后位置（中国四选一）", "防夹",
           "(retract_mode === 'ROD_200MM_PASS' && opening_after_mm >= rod_diameter_mm) || "
           "(retract_mode === 'INITIAL_POSITION' && "
           "opening_after_mm >= opening_before_close_mm) || "
           "(retract_mode === 'PLUS_50MM' && "
           "opening_after_mm >= opening_at_trigger_mm + plus_mm) || "
           "(retract_mode === 'TILT_MAX_ANGLE' && tilt_at_max_angle === true)",
           "自动回缩之后应开启到四个位置之一：允许穿过开口放置直径 200 mm 半刚性柱状试验棒的位置；"
           "关闭之前的最初位置；比开始回缩时的位置至少多开 50 mm 的位置；"
           "天窗倾斜运动时的最大角度开启位置",
           {"retract_mode": _vc("antipinch_retract_mode", "选定的回缩后位置策略"),
            "opening_after_mm": _vm("opening_after_mm"),
            "opening_before_close_mm": _vm("opening_before_close_mm"),
            "opening_at_trigger_mm": _vm("opening_at_trigger_mm"),
            "tilt_at_max_angle": _vm("tilt_at_max_angle"),
            "rod_diameter_mm": _vt("rod_diameter_mm", "验证用试验棒直径", "mm"),
            "plus_mm": _vt("plus_mm", "相对触发位置的额外开启量", "mm")},
           {"options": ["ROD_200MM_PASS", "INITIAL_POSITION", "PLUS_50MM", "TILT_MAX_ANGLE"],
            "plus_mm": 50.0, "rod_diameter_mm": 200.0},
           ["位移曲线", "试验棒穿过验证", "角度传感器（天窗机型）"], ALL,
           [src(GB11552_TXT, "gb11552.txt:445-452 §4.8.3.1.2.1 至 4.8.3.1.2.4"),
            b(215, "GB 11552-2009 回缩后要求四选一")],
           note="表达式用 || 把四档并起来，由 retract_mode 选中其中一支。"
                "每个分支的括号都是必需的：|| 的优先级低于 &&，不加括号会把条件串错。"),
        rq("TR-PINCH-03", "防夹力上限（美国 FMVSS 118）", "防夹",
           "peak_pinch_force_n < max_force_n && retract_triggered === true && "
           "opening_at_trigger_mm >= opening_min_mm && "
           "opening_at_trigger_mm <= opening_max_mm && "
           "((retract_mode === 'INITIAL_POSITION' && "
           "opening_after_mm >= opening_before_close_mm) || "
           "(retract_mode === 'PLUS_125MM' && "
           "opening_after_mm >= opening_at_trigger_mm + plus_mm))",
           "在接触试验棒之前，或在对半刚性圆柱试验棒施加 100 N 及以上挤压力之前，须停止并反向。"
           "回缩后制造商二选一：至少开到关闭开始时的位置；或比反向时的位置至少多开 125 mm",
           {"peak_pinch_force_n": _vm("peak_pinch_force_n"),
            "retract_triggered": _vm("retract_triggered", "是否停止并反向"),
            "opening_at_trigger_mm": _vm("opening_at_trigger_mm", "反向时的开口量"),
            "opening_after_mm": _vm("opening_after_mm"),
            "opening_before_close_mm": _vm("opening_before_close_mm"),
            "retract_mode": _vc("antipinch_retract_mode", "制造商选定的回缩后位置策略"),
            "max_force_n": _vt("max_force_n", "法规夹持力上限", "N"),
            "opening_min_mm": _vt("opening_min_mm", "防夹生效区间下沿", "mm"),
            "opening_max_mm": _vt("opening_max_mm", "防夹生效区间上沿", "mm"),
            "plus_mm": _vt("plus_mm", "相对反向位置的额外开启量", "mm")},
           {"max_force_n": 100.0, "opening_min_mm": 4.0, "opening_max_mm": 200.0,
            "plus_mm": 125.0, "rod_stiffness_n_per_mm": 20.0},
           ["力传感器曲线", "位移曲线"], ALL,
           [b(216, "三地防夹对照表 FMVSS 118 行"), b(69, "49 CFR § 571.118 全名与 URL")],
           status="100 N 与 4–200 mm 已核实；试验棒刚度 20 N/mm 与条款编号 S4/S7/S8 待核实",
           note="与 TR-PINCH-01 / TR-PINCH-02 的差别只在回缩后位置（125 mm vs 50 mm）"
                "与试验棒刚度（20 vs 10 N/mm）。选 PLUS_50MM 的产品过不了美国这一条——"
                "这就是「同一被测件、不同目标市场、判据自动换表」的演示点。"),
        rq("TR-PINCH-04", "防夹力上限（欧洲 UN ECE R21 §5.8）", "防夹",
           "peak_pinch_force_n <= max_force_n && retract_triggered === true && "
           "opening_at_trigger_mm >= opening_min_mm && "
           "opening_at_trigger_mm <= opening_max_mm",
           "夹紧力不超过 100 N；作用区间为上边缘上方 200 mm 至 4 mm；"
           "回缩后开到三种可选位置之一",
           {"peak_pinch_force_n": _vm("peak_pinch_force_n"),
            "retract_triggered": _vm("retract_triggered"),
            "opening_at_trigger_mm": _vm("opening_at_trigger_mm"),
            "max_force_n": _vt("max_force_n", "法规夹持力上限", "N"),
            "opening_min_mm": _vt("opening_min_mm", "防夹生效区间下沿", "mm"),
            "opening_max_mm": _vt("opening_max_mm", "防夹生效区间上沿", "mm")},
           {"max_force_n": 100.0, "opening_min_mm": 4.0, "opening_max_mm": 200.0,
            "rod_stiffness_n_per_mm": 10.0},
           ["力传感器曲线", "位移曲线"], ALL,
           [b(217, "三地防夹对照表 UN ECE R21 行"), b(70, "UN ECE R21 全名与 URL")],
           status="待核实（未打开 UNECE 原文逐字确认，回缩后的三种位置未取得具体表述）",
           note="回缩后位置这一半因为原文没取到，本条只把已知的力与区间写进表达式，"
                "没有像 TR-PINCH-02 那样展开位置分支。"),
        rq("TR-PINCH-05", "启动段夹持不漏检", "防夹",
           "pinch_detected_in_startup === true && peak_pinch_force_n < max_force_n && "
           "detect_latency_ms <= startup_blanking_time_ms + latency_margin_ms",
           "在启动屏蔽时间窗内制造夹持，仍须在 100 N 之前回缩。"
           "启动瞬间的浪涌电流会掩盖夹持特征，这是防夹算法最难的一段",
           {"pinch_detected_in_startup": _vm("pinch_detected_in_startup"),
            "peak_pinch_force_n": _vm("peak_pinch_force_n"),
            "detect_latency_ms": _vm("detect_latency_ms"),
            "startup_blanking_time_ms": _vc("startup_blanking_time",
                                            "启动段屏蔽时间设定值", "ms"),
            "max_force_n": _vt("max_force_n", "法规夹持力上限", "N"),
            "latency_margin_ms": _vt("latency_margin_ms", "允许的检出延迟裕量", "ms")},
           {"max_force_n": 100.0, "latency_margin_ms": 100.0},
           ["力传感器曲线", "位移曲线", "电流波形（浪涌段）"], ALL,
           [b(341, "基于纹波电机的车窗启动阶段防夹控制策略研究"),
            b(351, "防夹调参清单「启动段屏蔽时间」行")],
           status="待核实（该文献未确认期刊/会议全名与作者）",
           placeholder=True,
           note="latency_margin_ms 这个 100 ms 裕量是本包编的，"
                "任何标准都没有规定「检出延迟」这个量——法规只管力峰值。"
                "把它列成独立判据是为了让调参闭环有一个可优化的中间指标。"),
        rq("TR-PINCH-06", "无防夹功能时的替代要求", "防夹",
           "antipinch_enable === false && close_start_opening_mm <= max_opening_mm && "
           "remote_range_m <= remote_range_limit_m && "
           "one_touch_limited_to_driver_and_roof === true",
           "未装自动回缩装置时改判 GB 11552-2009 §4.8.2："
           "电动车窗从开口不超过 4 mm 处开始关闭时才允许关闭；"
           "遥控关闭作用距离不超过 6 m（车辆可直接看见时不超过 11 m）；"
           "一键关闭仅限驾驶员侧车门电动车窗与天窗，且仅在点火钥匙处于发动机运转位置期间",
           {"antipinch_enable": _vc("antipinch_enable", "防夹功能是否配备"),
            "close_start_opening_mm": _vm("close_start_opening_mm"),
            "remote_range_m": _vm("remote_range_m"),
            "one_touch_limited_to_driver_and_roof":
                _vm("one_touch_limited_to_driver_and_roof"),
            "max_opening_mm": _vt("max_opening_mm", "允许开始关闭的最大开口量", "mm"),
            "remote_range_limit_m": _vt("remote_range_limit_m", "遥控作用距离上限", "m")},
           {"max_opening_mm": 4.0, "remote_range_limit_m": 6.0,
            "remote_range_visible_m": 11.0},
           ["位移传感器", "遥控距离验证记录", "开关功能核对表"], ALL,
           [src(GB11552_TXT, "gb11552.txt:425-437 §4.8.2.6 至 §4.8.2.9"),
            b(219, "无防夹功能时的替代要求 GB 11552-2009 §4.8.2（已核实）")],
           note="这条与 TR-PINCH-01 互斥：antipinch_enable 决定走哪一支。"
                "把互斥关系写进判据本身而不是留给流程，是为了让 Agent 在 F3 的分支决策有据可依。"),
        rq("TR-PINCH-07", "保护装置自动复位", "防夹",
           "protection_auto_reset === true && motion_resumed_without_switch === false",
           "过载或自动关闭之后，所有用来防止超载或停止时动力源损坏的保护装置都应自动复位。"
           "保护装置复位后，除非有意去操纵控制开关，关闭方向的运动不应再继续",
           {"protection_auto_reset": _vm("protection_auto_reset"),
            "motion_resumed_without_switch": _vm("motion_resumed_without_switch")},
           {},
           ["位移曲线", "故障字回读", "静置观察记录"], ALL,
           [src(GB11552_TXT, "gb11552.txt:453-455 §4.8.5 保护装置")],
           note="第二个变量是反向判据，期望值为 false。写成 === false 而不是取反，"
                "是为了让前端展示时两个变量的取值方向一致可读。"),
    ]
    # ---------- 环境与耐久 ----------
    R += [
        rq("TR-ENV-01", "耐高温特性（80 ℃）", "环境与耐久",
           "working_current_up_a <= max_up_a && working_current_down_a <= max_down_a && "
           "stall_current_a <= max_stall_a && stall_force_n >= min_force_n && "
           "rise_speed_mm_s >= min_rise_mm_s && rise_speed_mm_s <= max_rise_mm_s && "
           "down_speed_mm_s <= max_down_mm_s && start_voltage_v <= max_start_v",
           "80 ℃ 放置 2 h 后，在该温度下空载不堵转运行 5 个工作循环，八项性能同时满足",
           {"working_current_up_a": _vm("working_current_up_a"),
            "working_current_down_a": _vm("working_current_down_a"),
            "stall_current_a": _vm("stall_current_a"),
            "stall_force_n": _vm("stall_force_n"),
            "rise_speed_mm_s": _vm("rise_speed_mm_s"),
            "down_speed_mm_s": _vm("down_speed_mm_s"),
            "start_voltage_v": _vm("start_voltage_v"),
            "max_up_a": _vt("max_up_a", "80 ℃ 上升工作电流上限", "A"),
            "max_down_a": _vt("max_down_a", "80 ℃ 下降工作电流上限", "A"),
            "max_stall_a": _vt("max_stall_a", "80 ℃ 堵转电流上限", "A"),
            "min_force_n": _vt("min_force_n", "80 ℃ 堵转力下限", "N"),
            "min_rise_mm_s": _vt("min_rise_mm_s", "上升速度下限", "mm/s"),
            "max_rise_mm_s": _vt("max_rise_mm_s", "上升速度上限", "mm/s"),
            "max_down_mm_s": _vt("max_down_mm_s", "下降速度上限", "mm/s"),
            "max_start_v": _vt("max_start_v", "启动电压上限", "V")},
           {"soak_temp_c": 80.0, "soak_hours": 2.0, "cycles": 5,
            "max_up_a": 12.0, "max_down_a": 7.0, "max_stall_a": 29.0,
            "min_force_n": 164.0, "min_rise_mm_s": 80.0, "max_rise_mm_s": 160.0,
            "max_down_mm_s": 200.0, "max_start_v": 9.0},
           ["电流波形", "力传感器曲线", "位移曲线", "环境箱温度记录"], ALL,
           [b(192, "耐高温特性 5.6.1 / 6.6.1")], status=D),
        rq("TR-ENV-02", "耐低温特性（−30 ℃）", "环境与耐久",
           "working_current_up_a <= max_up_a && working_current_down_a <= max_down_a && "
           "stall_current_a <= max_stall_a && stall_force_n >= min_force_n && "
           "rise_speed_mm_s >= min_rise_mm_s && down_speed_mm_s >= min_down_mm_s && "
           "start_voltage_v <= max_start_v",
           "−30 ℃ 放置 2 h 后同法运行 5 个工作循环，七项性能同时满足。"
           "注意低温下速度判据方向变了：变成「不低于」而不是区间",
           {"working_current_up_a": _vm("working_current_up_a"),
            "working_current_down_a": _vm("working_current_down_a"),
            "stall_current_a": _vm("stall_current_a"),
            "stall_force_n": _vm("stall_force_n"),
            "rise_speed_mm_s": _vm("rise_speed_mm_s"),
            "down_speed_mm_s": _vm("down_speed_mm_s"),
            "start_voltage_v": _vm("start_voltage_v"),
            "max_up_a": _vt("max_up_a", "−30 ℃ 上升工作电流上限", "A"),
            "max_down_a": _vt("max_down_a", "−30 ℃ 下降工作电流上限", "A"),
            "max_stall_a": _vt("max_stall_a", "−30 ℃ 堵转电流上限", "A"),
            "min_force_n": _vt("min_force_n", "−30 ℃ 堵转力下限", "N"),
            "min_rise_mm_s": _vt("min_rise_mm_s", "−30 ℃ 上升速度下限", "mm/s"),
            "min_down_mm_s": _vt("min_down_mm_s", "−30 ℃ 下降速度下限", "mm/s"),
            "max_start_v": _vt("max_start_v", "−30 ℃ 启动电压上限", "V")},
           {"soak_temp_c": -30.0, "soak_hours": 2.0, "cycles": 5,
            "max_up_a": 20.0, "max_down_a": 16.0, "max_stall_a": 30.0,
            "min_force_n": 190.0, "min_rise_mm_s": 60.0, "min_down_mm_s": 70.0,
            "max_start_v": 10.0},
           ["电流波形", "力传感器曲线", "位移曲线", "环境箱温度记录"], ALL,
           [b(193, "耐低温特性 5.6.2 / 6.6.2")], status=D),
        rq("TR-ENV-03", "耐振动性", "环境与耐久",
           "post_vibration_basic_pass === true",
           "按 QC/T 413-2002 的扫频振动条件试验后，仍符合 5.4 条基本性能。"
           "若改按 VW 80000 M-04 谱型 D，则为宽带随机振动、每轴 8 h、加速度均方根 30.8 m/s²",
           {"post_vibration_basic_pass": _vm("post_vibration_basic_pass")},
           {"profile_qct413": "QC/T 413-2002 扫频振动条件",
            "profile_vw80000_m04_d": {"hours_per_axis": 8, "grms_m_s2": 30.8,
                                      "psd_breakpoints": [[5, 0.884], [10, 20], [55, 6.5],
                                                          [180, 0.25], [300, 0.25],
                                                          [360, 0.14], [1000, 0.14],
                                                          [2000, 0.14]]}},
           ["振动台控制记录", "试验后基本性能复测"], ALL,
           [b(194, "耐振动性 5.7 / 6.7"), b(240, "VW 80000 M-04 谱型 D（已核实）"),
            b(77, "QC/T 413-2002 是所有车用电机标准的公共底座")],
           status="QC/T 413-2002 的扫频条件正文未取得；VW 80000 M-04 谱型 D 数值已核实",
           note="criterion 里只有一个布尔量，是因为「符合 5.4 条」本身是另外八条判据的合取。"
                "判定工具应把它展开成 TR-BASIC-01 至 TR-BASIC-08 的复跑，而不是让人去打勾。"),
        rq("TR-ENV-04", "耐腐蚀性（中性盐雾 120 h）", "环境与耐久",
           "voltage_item_pass === true && "
           "Math.abs(current_after_a - current_before_a) / current_before_a "
           "<= allowed_deviation && "
           "Math.abs(force_after_n - force_before_n) / force_before_n <= allowed_deviation && "
           "Math.abs(speed_after_mm_s - speed_before_mm_s) / speed_before_mm_s "
           "<= allowed_deviation && "
           "Math.abs(noise_after_dba - noise_before_dba) / noise_before_dba "
           "<= allowed_deviation && "
           "ferrous_surface_corrosion === false",
           "中性盐雾试验 120 h 后：工作电压项须合格；"
           "电流、堵转力、速度、噪音四项允许与试验前偏差 20 %；"
           "黑色金属零件主要表面无基体腐蚀物",
           {"voltage_item_pass": _vm("voltage_item_pass"),
            "current_before_a": _vm("current_before_a"),
            "current_after_a": _vm("current_after_a"),
            "force_before_n": _vm("force_before_n"),
            "force_after_n": _vm("force_after_n"),
            "speed_before_mm_s": _vm("speed_before_mm_s"),
            "speed_after_mm_s": _vm("speed_after_mm_s"),
            "noise_before_dba": _vm("noise_before_dba"),
            "noise_after_dba": _vm("noise_after_dba"),
            "ferrous_surface_corrosion": _vm("ferrous_surface_corrosion"),
            "allowed_deviation": _vt("allowed_deviation", "允许的性能偏差比例")},
           {"salt_spray_hours": 120, "allowed_deviation": 0.20},
           ["盐雾箱记录", "试验前基线数据", "试验后复测数据", "目视检查照片"], ALL,
           [b(195, "耐腐蚀性 5.8 / 6.8"), b(85, "GB/T 10125-2021 已代替 2012 版")],
           status=D + "；且征求意见稿引的 GB/T 10125-2012 已被 2021 版全部代替",
           note="这条判据必须有试验前基线才能求值，所以 evidence 里显式列了「试验前基线数据」。"
                "Agent 排程时若先做盐雾再想起要基线，这条就永远判不了。"),
        rq("TR-DUR-01", "耐久性（电动前门，10 000 循环）", "环境与耐久",
           "total_cycles >= target_cycles && function_normal === true && "
           "abnormal_noise === false && gear_slip === false && "
           "jam_detected === false && plastic_crack === false && "
           "max_perf_deviation <= allowed_deviation",
           "最大额定负载下按表 7 的 13 道工序累计 10 000 个循环："
           "常温 3000 次 → 80 ℃ 1500 → 60 ℃/90 %RH 2500 → 10 ℃/95 %RH 1000 "
           "→ −30 ℃ 1000 → 常温 1000，各段之间喷洒泥水。"
           "试验后功能正常、无异响跳齿打滑卡滞，塑料件无裂纹，性能允许偏差 20 %",
           {"total_cycles": _vm("total_cycles"),
            "function_normal": _vm("function_normal"),
            "abnormal_noise": _vm("abnormal_noise", "试验后是否有异响"),
            "gear_slip": _vm("gear_slip"),
            "jam_detected": _vm("jam_detected", "试验后是否卡滞"),
            "plastic_crack": _vm("plastic_crack"),
            "max_perf_deviation": _vm("max_perf_deviation"),
            "target_cycles": _vt("target_cycles", "目标循环数", "循环"),
            "allowed_deviation": _vt("allowed_deviation", "允许的性能偏差比例")},
           {"target_cycles": 10000, "rear_door_cycles": 5000,
            "stages": [["常温", 3000], ["80 ℃", 1500], ["60 ℃/90 %RH", 2500],
                       ["10 ℃/95 %RH", 1000], ["−30 ℃", 1000], ["常温", 1000]],
            "allowed_deviation": 0.20,
            "mud_water": {"water_pct": 92.5, "dust_pct": 7.5,
                          "dust_spec": "ISO 12103-1，50 % A2 + 50 % A4"}},
           ["循环计数器", "环境箱温湿度记录", "声学录音", "位移与电流波形", "拆机检查照片"],
           ALL,
           [b(196, "耐久性（电动，前门）5.9.1 / 6.9.1 表 7"),
            b(199, "耐久泥水配比 6.9.1 注"), b(200, "耐久单循环波形 6.9.1 注 3")],
           status=D,
           note="耐久是本场景与第一个包在「口径」上差得最远的一项：第一个包按连续运行小时数算，"
                "本场景按开闭循环次数算，而且循环本身还嵌在 13 道温湿度工序里。"
                "同一套工作流引擎要能表达这两种完全不同的时间轴。"),
        rq("TR-DUR-02", "耐高温高湿放置（480 h）", "环境与耐久",
           "no_crack_or_melt === true && max_perf_deviation <= allowed_deviation",
           "上止点堵转 1 s 关电源后，80 ℃ / 90 %RH 放置 480 h，"
           "取出后常温加最大额定负载跑 100 个工作循环；零部件无裂纹融解，性能允许偏差 20 %",
           {"no_crack_or_melt": _vm("no_crack_or_melt"),
            "max_perf_deviation": _vm("max_perf_deviation"),
            "allowed_deviation": _vt("allowed_deviation", "允许的性能偏差比例")},
           {"soak_temp_c": 80.0, "soak_rh_pct": 90, "soak_hours": 480,
            "post_cycles": 100, "allowed_deviation": 0.20},
           ["恒温恒湿箱记录", "试验前基线数据", "试验后复测数据", "拆机检查照片"], ALL,
           [b(201, "耐高温高湿放置 5.10 / 6.10")], status=D),
        rq("TR-DUR-03", "耐过负载操作强度", "环境与耐久",
           "post_test_basic_pass === true",
           "最大额定负载下施加 16.5 V，跑 10 个工作循环，试验后基本性能合格",
           {"post_test_basic_pass": _vm("post_test_basic_pass")},
           {"voltage_v": 16.5, "cycles": 10},
           ["程控电源电压回读", "循环计数", "试验后基本性能复测"], ALL,
           [b(202, "耐过负载操作强度 5.11.1 / 6.11.1"), b(156, "过压保护判据")],
           status=D),
    ]
    # ---------- 电气与防护 ----------
    R += [
        rq("TR-ELEC-01", "防水性", "电气与防护",
           "water_ingress_in_motor === false",
           "喷水压力 0.1 MPa、孔径 φ1.2 mm、孔数 40、喷水量 20 L/min、时间 30 min，"
           "拆机后电机内部不应进水",
           {"water_ingress_in_motor": _vm("water_ingress_in_motor")},
           {"pressure_mpa": 0.1, "nozzle_diameter_mm": 1.2, "nozzle_count": 40,
            "flow_l_per_min": 20, "duration_min": 30},
           ["喷淋台参数记录", "拆机检查照片"], ALL,
           [b(203, "防水性 5.12.1 / 6.12.1 表 9")], status=D),
        rq("TR-ELEC-02", "绝缘介电强度", "电气与防护",
           "dielectric_breakdown === false",
           "550 V、50 Hz 正弦交流历时 1 min，绝缘不被击穿；批量生产可用 660 V / 1 s 替代",
           {"dielectric_breakdown": _vm("dielectric_breakdown")},
           {"voltage_v": 550, "frequency_hz": 50, "duration_s": 60,
            "alt_voltage_v": 660, "alt_duration_s": 1},
           ["耐压仪记录"], ALL,
           [b(204, "绝缘介电强度 5.12.2 / 6.12.2"), b(163, "绝缘介电强度判据")],
           status=D),
        rq("TR-ELEC-03", "热保护性", "电气与防护",
           "((ambient_c <= hot_boundary_c && first_start_cycles >= cold_first_cycles && "
           "recovery_s <= cold_recovery_s) || "
           "(ambient_c > hot_boundary_c && first_start_cycles >= hot_first_cycles && "
           "recovery_s <= hot_recovery_s)) && restart_cycles >= min_restart_cycles",
           "最大额定负载下分 −40 ℃、常温、80 ℃ 三档："
           "−40 ℃ 与常温要求首次启动 ≥30 循环、恢复 ≤60 s、再启动 ≥2 循环；"
           "80 ℃ 要求首次启动 ≥15 循环、恢复 ≤100 s、再启动 ≥2 循环",
           {"ambient_c": _vm("ambient_c"),
            "first_start_cycles": _vm("first_start_cycles"),
            "recovery_s": _vm("recovery_s"),
            "restart_cycles": _vm("restart_cycles"),
            "hot_boundary_c": _vt("hot_boundary_c", "常温档与高温档的分界温度", "℃"),
            "cold_first_cycles": _vt("cold_first_cycles",
                                     "常温与 −40 ℃ 档首次启动循环数下限", "循环"),
            "cold_recovery_s": _vt("cold_recovery_s", "常温与 −40 ℃ 档恢复时间上限", "s"),
            "hot_first_cycles": _vt("hot_first_cycles", "80 ℃ 档首次启动循环数下限", "循环"),
            "hot_recovery_s": _vt("hot_recovery_s", "80 ℃ 档恢复时间上限", "s"),
            "min_restart_cycles": _vt("min_restart_cycles", "恢复后再启动循环数下限", "循环")},
           {"hot_boundary_c": 30.0, "cold_first_cycles": 30, "cold_recovery_s": 60.0,
            "hot_first_cycles": 15, "hot_recovery_s": 100.0, "min_restart_cycles": 2,
            "test_temps_c": [-40.0, 23.0, 80.0]},
           ["循环计数器", "环境箱温度记录", "恢复计时"], ALL,
           [b(205, "热保护性 5.12.3 / 6.12.3 表 5"), b(162, "热保护三档判据")],
           status=D,
           note="hot_boundary_c = 30 ℃ 这个分界是本包为了让表达式可求值而设的："
                "标准给的是 −40 ℃ / 常温 / 80 ℃ 三个离散点，不是连续区间。"
                "实际执行时应按试验项显式选档，而不是靠温度回读去猜。"),
        rq("TR-ELEC-04", "电磁兼容性", "电气与防护",
           "radiated_emission_level <= radiated_level && "
           "conducted_emission_level <= conducted_level && "
           "transient_conducted_level_roman <= transient_level",
           "辐射发射与传导发射满足等级 3；沿电源线的瞬态传导发射满足等级 III。"
           "征求意见稿引的是 GB/T 18655-2010 与 GB/T 21437.2-2008，"
           "两本均已换版，落地时须改引 GB/T 18655-2025 与 GB/T 21437.2-2021",
           {"radiated_emission_level": _vm("radiated_emission_level"),
            "conducted_emission_level": _vm("conducted_emission_level"),
            "transient_conducted_level_roman": _vm("transient_conducted_level_roman"),
            "radiated_level": _vt("radiated_level", "辐射发射允许等级", "级"),
            "conducted_level": _vt("conducted_level", "传导发射允许等级", "级"),
            "transient_level": _vt("transient_level",
                                   "瞬态传导发射允许等级（罗马数字 III 转整数 3）", "级")},
           {"radiated_level": 3, "conducted_level": 3, "transient_level": 3,
            "transient_level_roman": "III",
            "current_refs": ["GB/T 18655-2025", "GB/T 21437.2-2021"],
            "cited_refs": ["GB/T 18655-2010", "GB/T 21437.2-2008"]},
           ["EMC 暗室测试报告"], ALL,
           [b(206, "电磁兼容性 5.12.4 / 6.12.4"), b(81, "GB/T 18655-2025 已代替 2018 版"),
            b(80, "GB/T 21437 系列第 1 至 3 部分均为 2021 版")],
           status=D + "；且两本引用标准均已换版",
           note="罗马数字 III 在表达式里必须转成整数 3 才能比较，"
                "threshold 里同时保留 transient_level_roman 给前端回显，"
                "避免与阿拉伯数字等级混淆。"),
        rq("TR-ELEC-05", "有害物质限量", "电气与防护",
           "hazardous_substances_pass === true",
           "铅、汞、镉、六价铬、多溴联苯（PBBs）、多溴二苯醚（PBDEs）含量符合 GB/T 30512-2014",
           {"hazardous_substances_pass": _vm("hazardous_substances_pass")},
           {"substances": ["Pb", "Hg", "Cd", "Cr(VI)", "PBBs", "PBDEs"],
            "standard": "GB/T 30512-2014"},
           ["第三方有害物质检测报告"], ALL,
           [src(QC626_TXT, "qc636.txt:112-114 5.3 有害物质"), b(207, "有害物质 5.3 / 6.3")],
           status=D),
        rq("TR-ELEC-06", "长时过电压（ISO 16750-2）", "电气与防护",
           "allowed_classes.includes(function_class)",
           "12 V 系统施加 18 V 持续 60 min，环境温度为 Tmax 减 20 K，要求最低功能状态 class C",
           {"function_class": _vm("function_class"),
            "allowed_classes": _vt("allowed_classes", "允许的功能状态等级集合")},
           {"voltage_v": 18.0, "duration_min": 60, "temp": "Tmax − 20 K",
            "min_class": "C", "allowed_classes": ["A", "B", "C"]},
           ["程控电源记录", "功能状态观察记录"], ALL,
           [b(157, "ISO 16750-2:2023 §4.3.1.1.2 长时过电压（已核实）"),
            src(ISO16750_2_PDF, "ISO 16750-2:2023 §4.3.1.1.2")]),
        rq("TR-ELEC-07", "跨接启动（ISO 16750-2）", "电气与防护",
           "allowed_classes.includes(function_class)",
           "12 V 系统施加 26 V 持续 60 ± 6 s，最低功能状态 class C",
           {"function_class": _vm("function_class"),
            "allowed_classes": _vt("allowed_classes", "允许的功能状态等级集合")},
           {"voltage_v": 26.0, "duration_s": 60, "duration_tol_s": 6,
            "min_class": "C", "allowed_classes": ["A", "B", "C"]},
           ["程控电源记录", "功能状态观察记录"], ALL,
           [b(158, "ISO 16750-2:2023 §4.3.1.2.2 表 5 跨接启动（已核实）"),
            src(ISO16750_2_PDF, "ISO 16750-2:2023 §4.3.1.2.2 表 5")]),
        rq("TR-ELEC-08", "反极性期间不得触发安全相关功能", "电气与防护",
           "(fault_flags & FAULT_REVERSE_POLARITY) !== 0 && "
           "window_motion_detected === false && post_test_basic_pass === true",
           "10.8 V 到 −4.0 V 持续 60 s（继电器切断供电时改为 8 ms），3 个循环。"
           "标准原文明确要求反极性期间不得触发任何安全相关功能，并点名电动车窗、天窗、起动机",
           {"fault_flags": _vm("fault_flags"),
            "FAULT_REVERSE_POLARITY": {
                "source": "constant", "value": 128,
                "derived_from": ["safety-interlocks.fault_bitmap.0x0080"],
                "desc": "反极性检出位掩码（0x0080）"},
            "window_motion_detected": _vm("window_motion_detected"),
            "post_test_basic_pass": _vm("post_test_basic_pass")},
           {"from_v": 10.8, "to_v": -4.0, "duration_s": 60,
            "duration_if_relay_cutoff_ms": 8, "cycles": 3,
            "fault_bit": "0x0080 FAULT_REVERSE_POLARITY"},
           ["程控电源记录", "位移曲线", "故障字回读", "试验后基本性能复测"], ALL,
           [b(160, "反极性 LV 124 / VW 80000 试验 E-15（已核实）"),
            src(LV124_PDF, "MBN LV 124-1: 2013-03 试验 E-15")],
           status="试验条件已核实；fault_flags 的位定义是本包编的示例"
                  "（见 safety-interlocks.json fault_bitmap）",
           note="位运算必须加括号：JS 与 C 里 & 的优先级都低于 !==，"
                "写成 fault_flags & FAULT_REVERSE_POLARITY !== 0 会被解析成 "
                "fault_flags & (FAULT_REVERSE_POLARITY !== 0)，结果全错。"),
    ]
    # ---------- 不可求值的登记项 ----------
    R += [
        rq("TR-RULE-01", "型式检验分组与抽样规则", "检验规则",
           None,
           "型式检验项目按组执行、每组不少于 2 套样件、顺序按 GB/T 28046.1-2011 附录 A.1；"
           "出厂检验按 GB/T 2828.1-2012 一般检查水平 II、接收质量限 0.4 至 4.0、"
           "一次正常检查抽样方案",
           {}, {"groups": 6, "min_samples_per_group": 2,
                "sampling_standard": "GB/T 2828.1-2012",
                "inspection_level": "II", "aql_range": [0.4, 4.0]},
           ["抽样记录", "样件流转台账"], ["F3 测试需求确认", "F6 测试报告及产出"],
           [b(414, "QC/T 626 征求意见稿第 7 章检验规则"),
            b(415, "QC/T 29090-2023 第 6 章检验规则（已核实）"),
            b(279, "型式检验 6.3：20 个项目分 6 组")],
           evaluable=False,
           not_evaluable_reason="这是排程与抽样的规则，不是对单次测量结果的判定，"
                                "写不出布尔表达式。登记它是为了让 F3 的排程器有约束可读。",
           status="分组数与抽样方案取自备选产品标准 QC/T 29090-2023；"
                  "QC/T 626 征求意见稿第 7 章的具体分组本次未逐条提取"),
        rq("TR-RULE-02", "外观与涂镀层", "检验规则",
           None,
           "金属零件涂镀层和化学处理层应均匀、不得有明显缺陷；"
           "塑料零件表面应平整、无气泡、无龟裂、无影响使用的变形",
           {}, {},
           ["目视检查照片"], ALL,
           [src(QC626_TXT, "qc636.txt:110-111 5.2.1、5.2.2")],
           evaluable=False,
           not_evaluable_reason="「明显缺陷」「影响使用的变形」是人工目视判定，"
                                "标准没有给可测量的量，不硬凑成布尔表达式。"
                                "与 TR-BASIC-01 里的 abnormal_noise 不同："
                                "那个至少能从频谱算，这个不能。",
           status=D),
        rq("TR-RULE-03", "用户手册须含防夹相关说明", "检验规则",
           None,
           "车辆用户手册应包含电动车窗/天窗/隔断系统的明晰使用说明，包括："
           "被夹住的可能的说明；驾驶员控制开关的使用方法；"
           "指明危险的「警告」信息，尤其针对儿童错误使用/操作的情况",
           {}, {},
           ["用户手册相关页扫描件"], ["F6 测试报告及产出"],
           [src(GB11552_TXT, "gb11552.txt:456-462 §4.8.6 用户手册指南"),
            b(405, "NHTSA 报告第 6 节 Owner's Manual Information")],
           evaluable=False,
           not_evaluable_reason="文档合规性由人工核对，没有运行时测量量。"
                                "登记它是因为 NHTSA 合规报告的第 6 节就是这一项，"
                                "报告模板里必须给它留位置。"),
    ]

    categories = []
    for r in R:
        if r["category"] not in categories:
            categories.append(r["category"])

    n_eval = sum(1 for r in R if r["evaluable"])
    used = set()
    for r in R:
        for k, v in r["variables"].items():
            if v.get("source") == "runtime.measure":
                used.add(v["ref"].split(".")[-1])

    return dump("test-requirements.json", {
        "schema": "test-requirements/v1",
        "scene_id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "belongs_to_flow": "F3 测试需求确认（标准与判据来源）→ F4 启动测试及结果分析（执行与判定）",
        "categories": categories,
        "criterion_syntax": "JavaScript 表达式（ECMAScript），求值结果为布尔",
        "criterion_expression_note":
            "每条判据带四个配套字段：evaluable 说明这条能不能真的求值；"
            "criterion 是 JS 语法的判据表达式，散文式、无可测量量可取的条目为 null；"
            "variables 把表达式里每个自由变量映射到确定的取值来源；"
            "criterion_text 是人读版本。"
            "variables[].source 四种取值：runtime.measure 指向 runtime_measures 登记表里的"
            "运行时测量量；threshold 指向本条自己的 threshold 字段；"
            "control-parameters 指向 control-parameters.json 的 parameters[].key；"
            "constant 是编译期常量，derived_from 指向 safety-interlocks.json 的 fault_bitmap。"
            "evaluable 为 false 时 not_evaluable_reason 写明卡在哪。"
            "位运算一律加括号：C/JS 里 & 的优先级低于比较运算符。",
        "criterion_globals": ["Math", "true", "false", "null"],
        "runtime_measures": RUNTIME_MEASURES,
        "runtime_measures_note":
            "本表登记 %d 个运行时测量量，判据实际用到 %d 个。"
            "与第一个包的差别：那边的测量量大半由示波器与 HID 指令取"
            "（rigol_measure FREQ、breakrun + readmem 等），"
            "这边全部由台架传感器取（力、位移、电流、声级计、环境箱），"
            "还有一部分是人工检查的布尔量（拆机目视、遥控距离验证）。"
            % (len(RUNTIME_MEASURES), len(used)),
        "evaluable_count": n_eval,
        "not_evaluable_count": len(R) - n_eval,
        "regulation_switch_note":
            "TR-PINCH-01 / TR-PINCH-03 / TR-PINCH-04 是同一个物理试验在中、美、欧三地的三套判据，"
            "由目标市场选中其一。三地在 100 N 与 4 至 200 mm 上完全一致，"
            "差异只在试验棒刚度与回缩后位置。这是本场景包最有演示价值的一屏："
            "同一被测件、同一次采集，换目标市场即换判据表。"
            "报告聚合时不参与的两条标 N/A 而不是 PASS。",
        "requirements": R,
    })
