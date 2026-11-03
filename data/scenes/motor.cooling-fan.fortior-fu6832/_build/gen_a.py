# -*- coding: utf-8 -*-
"""生成 scene.json / product-attributes.json / control-parameters.json /
safety-interlocks.json / test-requirements.json。"""
import os
import re
import shutil

from common import (AITIOR, BENCH_MEMO, BUILD_DATE, CAPTURE_INFO_SAMPLE, CUSTOMER_H,
                    DATASHEET, DOC_A, DOC_NEED, FLOWS, GENERATED_BY, HW_NODIODE_PDF,
                    HW_STD_PDF, HW_VSP_PDF, MOTOR_PROT_H, OUT, PROTECT_H,
                    REPORT_XLSM, SCENE_ID, SPEEDTEST_WFW, TAXONOMY,
                    WRITEFILE_README, dump, src)

# ---------------------------------------------------------------- 宏定位工具
_CACHE = {}


def _scan(path):
    if path not in _CACHE:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            _CACHE[path] = f.readlines()
    return _CACHE[path]


def macro_line(path, macro):
    """返回宏在文件中的 1-based 行号，找不到返回 None。"""
    pat = re.compile(r"^\s*#define\s+" + re.escape(macro) + r"\s")
    for i, ln in enumerate(_scan(path), 1):
        if pat.match(ln):
            return i
    return None


def macro_src(path, macro):
    n = macro_line(path, macro)
    base = os.path.basename(path)
    return src(path, "%s:%s (#define %s)" % (base, n if n else "未命中", macro))


MISSING = []


def chk(path, macro):
    if macro_line(path, macro) is None:
        MISSING.append("%s 中未命中宏 %s" % (os.path.basename(path), macro))
    return macro_src(path, macro)


# ---------------------------------------------------------------- 1. scene.json
def render_schematic():
    """把标准方案原理图 PDF 首页渲成 PNG 放 assets/。"""
    import fitz
    out_png = os.path.join(OUT, "assets", "schematic-standard-p1.png")
    doc = fitz.open(HW_STD_PDF)
    page = doc[0]
    pix = page.get_pixmap(dpi=150)
    pix.save(out_png)
    doc.close()
    return out_png, pix.width, pix.height


def gen_scene():
    png, w, h = render_schematic()
    rel = os.path.relpath(png, OUT)
    scene = {
        "schema": "scene/v1",
        "id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "taxonomy": {
            "level1_scene": TAXONOMY["level1"],
            "level2_category": TAXONOMY["level2"],
            "level3_product_type": TAXONOMY["level3"],
            "_source": src(DOC_NEED, "「体系三级：一级场景（汽车/芯片/电机/…），二级，三级=产品类型」段"),
        },
        "product": {
            "name": "FU6832 散热风扇驱动板（峰岹 AI_散热风扇开发资料 CoolingFan_Program 工程）",
            "chip": "FU6832N（峰岹科技三相电机控制 MCU，含 Pre-driver 与运放）",
            "control_scheme": "无感 FOC + Open-Omega 起转 + 速度闭环，PWM 占空比调速，FG 转速回报",
            "_source": [
                src(CUSTOMER_H, "Customer.h:1-40 文件头 @brief FU6832_CONFIGURATION FU/PU6832 參數配置檔"),
                src(DATASHEET, "第 1 页 封面「三相电机控制MCU FU6832」"),
            ],
        },
        "summary": (
            "峰岹散热风扇参考工程：以 FU6832N 为主控的三相无感 FOC 风扇驱动板，"
            "Open-Omega 强拖起转后切速度闭环，PWM 占空比调速、FG 脉冲回报转速，"
            "带过欠压/过流/堵转/缺相保护与顺逆风重启。"
            "本场景包把该产品的本体属性、控制参数、安全联锁、测试判据、归档工作流、"
            "可回放时序数据、经验条目、文档清单与报告模板字段整理成前端可直接加载的 JSON。"
        ),
        "images": [
            {
                "id": "schematic-standard-p1",
                "title": "标准方案原理图（首页）",
                "path": rel.replace(os.sep, "/"),
                "width": w,
                "height": h,
                "render": "PyMuPDF get_pixmap(dpi=150) 渲染 PDF 第 1 页",
                "_source": src(HW_STD_PDF, "第 1 页"),
            }
        ],
        "schematic_variants": [
            {"name": "標準方案", "file": HW_STD_PDF,
             "note": "目录名为「標準方案」，但文件名写作 FU6832N-Diode-VSP-V1.0，按原样登记不改名"},
            {"name": "VSP調速方案", "file": HW_VSP_PDF},
            {"name": "無二極體方案", "file": HW_NODIODE_PDF},
        ],
        "flows": [{"id": k, "name": v} for k, v in FLOWS.items()],
        "_source": src(DOC_NEED, "全文（六个流程与三级知识库体系）"),
    }
    return dump("scene.json", scene)


# ------------------------------------------------- 2. product-attributes.json
def attr(key, name, value, unit=None, vmin=None, vmax=None, step=None,
         source=None, group=None, editable=True, placeholder=False, note=None):
    d = {"key": key, "name": name, "value": value}
    if unit is not None:
        d["unit"] = unit
    d["min"] = vmin
    d["max"] = vmax
    d["step"] = step
    d["editable"] = editable
    if group:
        d["group"] = group
    if note:
        d["note"] = note
    d["_source"] = source
    if placeholder:
        d["_placeholder"] = True
    return d


def gen_product_attributes():
    items = [
        # --- 电机本体电气参数（Customer.h 电机参数相关配置段）---
        attr("pole_pairs", "极对数", 2, "对", 1, 8, 1,
             chk(CUSTOMER_H, "Pole_Pairs"), group="电机本体"),
        attr("rs", "相电阻 Rs", 0.098667, "Ω", 0.001, 10.0, 0.001,
             chk(CUSTOMER_H, "RS"), group="电机本体"),
        attr("ld", "d 轴电感 Ld", 0.000044, "H", 0.000001, 0.01, 0.000001,
             chk(CUSTOMER_H, "LD"), group="电机本体"),
        attr("lq", "q 轴电感 Lq", 0.000044, "H", 0.000001, 0.01, 0.000001,
             macro_src(CUSTOMER_H, "LQ"), group="电机本体",
             note="源文件写作 #define LQ (LD)，取值跟随 LD"),
        attr("ke", "反电动势常数 Ke", 0.288201, "V/kRPM", 0.001, 10.0, 0.001,
             chk(CUSTOMER_H, "Ke"), group="电机本体"),
        attr("motor_speed_base", "速度基准值", 50000, "RPM", 1000, 100000, 1000,
             chk(CUSTOMER_H, "MOTOR_SPEED_BASE"), group="电机本体",
             note="典型值 = 电机最高转速 × 2"),
        attr("motor_direction", "电机旋向", "FORWARD", None, None, None, None,
             chk(CUSTOMER_H, "MOTOR_DIRECTION"), group="电机本体",
             note="枚举 FORWARD 正转 / BACKWARD 反转"),

        # --- 转速规格（PWM 调速模式下的工作区间）---
        attr("motor_min_speed", "最低工作转速", 18000, "RPM", 1000, 40000, 100,
             chk(CUSTOMER_H, "MOTOR_MIN_SPEED"), group="转速规格",
             note="SPEED_MODE 为 PWMMODE 时有效"),
        attr("motor_max_speed", "最高工作转速", 28000, "RPM", 1000, 40000, 100,
             chk(CUSTOMER_H, "MOTOR_MAX_SPEED"), group="转速规格",
             note="SPEED_MODE 为 PWMMODE 时有效"),
        attr("rated_speed", "额定转速", 28000, "RPM", 1000, 40000, 100,
             chk(CUSTOMER_H, "MOTOR_MAX_SPEED"), group="转速规格",
             placeholder=True,
             note="源材料未单独给「额定转速」，此处按 MOTOR_MAX_SPEED 暂取，待客户确认"),

        # --- 电压规格 ---
        attr("rated_voltage", "额定母线电压", 12.0, "V", 5.0, 28.0, 0.1,
             src(SPEEDTEST_WFW,
                 "definition.nodes[hid_preset_voltage_set].data.paramValues.voltage = 12.5"),
             group="电压规格", placeholder=True,
             note="源材料无「额定电压」明文。依据：归档工作流把母线设到 12.5 V；"
                  "Protect.h 过压 18.0 V / 欠压 7.0 V 的窗口也指向 12 V 级母线。数值待客户确认"),
        attr("vcc_operating_min", "芯片 VCC 工作电压下限", 5, "V", None, None, None,
             src(DATASHEET, "PDF 第 56 页 表5-2 全局电气特性「VCC 工作电压 单电源高压模式」"),
             group="芯片规格", editable=False),
        attr("vcc_operating_max", "芯片 VCC 工作电压上限", 28, "V", None, None, None,
             src(DATASHEET, "PDF 第 56 页 表5-2 全局电气特性「VCC 工作电压 单电源高压模式」"),
             group="芯片规格", editable=False),
        attr("vcc_abs_max", "芯片 VCC 绝对最大额定值", 36, "V", None, None, None,
             src(DATASHEET, "PDF 第 56 页 表5-1 绝对最大额定值「VCC 相对VSS 的电压」"),
             group="芯片规格", editable=False),
        attr("ambient_temp_range", "工作环境温度 TA", "-40 ~ 85", "℃", -40, 85, None,
             src(DATASHEET, "PDF 第 56 页 表5-1 绝对最大额定值「工作时环境温度TA」"
                            "（PyMuPDF 抽文实测该行与「工作时结温TJ」「储存温度」"
                            "「VCC 相对VSS 的电压」同属表5-1，旧 locator 写作表5-2 有误）"),
             group="芯片规格", editable=False),
        attr("junction_temp_max", "工作结温 TJ 上限", 150, "℃", None, None, None,
             src(DATASHEET, "PDF 第 56 页 表5-1「工作时结温TJ」"),
             group="芯片规格", editable=False),

        # --- 电流规格 ---
        attr("ivcc_typ", "芯片 IVCC 工作电流（典型）", 20, "mA", None, None, None,
             src(DATASHEET, "PDF 第 56 页 表5-2「IVCC工作电流」典型值"),
             group="芯片规格", editable=False),
        attr("ivcc_max", "芯片 IVCC 工作电流（最大）", 40, "mA", None, None, None,
             src(DATASHEET, "PDF 第 56 页 表5-2「IVCC工作电流」最大值"),
             group="芯片规格", editable=False),
        attr("rated_current", "整机额定相电流", 0.6, "A", 0.1, 10.0, 0.1,
             chk(CUSTOMER_H, "MOTOR_RUN_IQ_CURRENT"), group="电流规格",
             placeholder=True,
             note="源材料无「额定电流」明文。此处按运行阶段 Q 轴初始电流 I_Value(0.6) 暂取，待客户确认"),

        # --- 采样链路（板级硬件常数）---
        attr("hw_shunt_mode", "采样电阻模式", "SINGLE_SHUNT", None, None, None, None,
             chk(CUSTOMER_H, "HW_SHUNT_MODE"), group="采样链路", editable=False),
        attr("hw_rshunt", "采样电阻阻值", 0.01, "Ω", 0.002, 0.05, 0.001,
             chk(CUSTOMER_H, "HW_RSHUNT"), group="采样链路",
             note="源注释建议值 0.02 ~ 0.005。与原理图交叉核对一致：标准方案原理图上 "
                  "RS1、RS2 各 0.02R/1206/1%，两只并联得 0.01 Ω"),
        attr("hw_ampgain", "内部运放放大倍率", "GAIN_16", None, None, None, None,
             chk(CUSTOMER_H, "HW_AMPGAIN"), group="采样链路",
             note="枚举 GAIN_2 / GAIN_4 / GAIN_8 / GAIN_16 / GAIN_32"),
        attr("hw_rv_mode", "母线电压量测来源", "RVEXT", None, None, None, None,
             chk(CUSTOMER_H, "HW_RV_MODE"), group="采样链路", editable=False),
        attr("rv1", "母线分压电阻 RV1", 100.0, "kΩ", 1.0, 1000.0, 1.0,
             chk(CUSTOMER_H, "RV1"), group="采样链路"),
        attr("rv2", "母线分压电阻 RV2", 30.0, "kΩ", 1.0, 1000.0, 1.0,
             chk(CUSTOMER_H, "RV2"), group="采样链路"),

        # --- 转速信号 ---
        attr("rotate_signal_type", "转速信号输出类型", "FG_TYPE", None, None, None, None,
             chk(CUSTOMER_H, "ROTATE_SIGNAL_TYPE"), group="转速信号",
             note="枚举 NO_TYPE / RD_TYPE / FG_TYPE"),
        attr("fg_pulse_period", "FG 每转脉波数", 2, "pulse/rev", 1, 8, 1,
             chk(CUSTOMER_H, "FG_PULSE_PERIOD"), group="转速信号"),

        # --- 机械尺寸：源材料确无 ---
        attr("fan_outer_size", "风扇外形尺寸", "未知", "mm", None, None, None,
             src(DOC_A, "第六节「跑通散热风扇一条流程的输入」——界面只填 5 项，不含机械尺寸"),
             group="机械", placeholder=True,
             note="缺口：本地源材料（Customer.h、数据手册、原理图、调研文档 A/B）均无风扇机械尺寸，需向客户索取"),
        attr("fan_thickness", "风扇厚度", "未知", "mm", None, None, None,
             src(DOC_A, "第六节「跑通散热风扇一条流程的输入」——界面只填 5 项，不含机械尺寸"),
             group="机械", placeholder=True,
             note="缺口：同上"),
    ]
    obj = {
        "schema": "product-attributes/v1",
        "scene_id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "belongs_to_flow": "F2 初始化配置（产品本体属性，读取文档→呈现→左右加减号调整）",
        "groups": ["电机本体", "转速规格", "电压规格", "电流规格", "芯片规格", "采样链路", "转速信号", "机械"],
        "attributes": items,
    }
    return dump("product-attributes.json", obj)


# ------------------------------------------------ 3. control-parameters.json
def cp(key, name, value, unit, vmin, vmax, step, source, group, flows,
       default=None, shell=None, note=None, placeholder=False, editable=True,
       options=None, range_estimated=False, value_below_min=False):
    d = {
        "key": key, "name": name, "value": value, "default": default if default is not None else value,
        "unit": unit, "min": vmin, "max": vmax, "step": step,
        "group": group, "adjustable_in_flows": flows, "editable": editable,
    }
    if options is not None:
        # L5 枚举型参数：min/max/step 不适用，取值集合放 options
        d["options"] = options
    if range_estimated:
        # L6 源文件未给范围注释，min/max 是本包推定的
        d["range_estimated"] = True
    if value_below_min:
        # M1 实配值低于源注释自己写的范围下限，源材料自身不一致
        d["value_below_min"] = True
    if shell:
        d["value_shell"] = shell
    if note:
        d["note"] = note
    d["_source"] = source
    if placeholder:
        d["_placeholder"] = True
    return d


F4 = "F4 启动测试及结果分析"
F5 = "F5 调优确认及运行"
F2 = "F2 初始化配置"
F3 = "F3 测试需求确认"


def gen_control_parameters():
    items = [
        # --- 启动（Open-Omega）---
        cp("motor_start_mode", "启动模式", "OPEN_OMEGA_START", None, None, None, None,
           chk(CUSTOMER_H, "MOTOR_START_MODE"), "启动", [F2, F5],
           options=[{"value": "OPEN_OMEGA_START", "label": "Omega 强拖启动"},
                    {"value": "SQUARE_START", "label": "方波启动（实验性功能）"}],
           note="枚举型参数，取值集合见 options；min/max/step 不适用"),
        cp("motor_start_iq_current", "启动电流（启动阶段 Q 轴电流）", 1.3, "A", 0.1, 20.0, 0.1,
           chk(CUSTOMER_H, "MOTOR_START_IQ_CURRENT"), "启动", [F4, F5], shell="I_Value(x)",
           note="范围 0.1~20 A 取自 coolingfan-openloop-debug 规程 inputs 映射表；"
                "分诊动作：过流 −20%，起不来 +0.1~0.2 A"),
        cp("motor_loop_rpm", "进入闭环转速（FOC 切换转速）", 900, "RPM", 500, 2000, 10,
           chk(CUSTOMER_H, "MOTOR_LOOP_RPM"), "启动", [F5],
           note="Customer.h 注释：Open-Omega 启动操作范围 500~2000；方波启动为 100~800。"
                "规程口径为「只读记录，仅切闭环失败分诊命中时才动，幅度 ±20%」"),
        cp("motor_min_smo_speed", "SMO 最小估算转速", 900, "RPM", 100, 5000, 10,
           chk(CUSTOMER_H, "MOTOR_MIN_SMO_SPEED"), "启动", [F5]),
        cp("motor_start_dqkp", "启动阶段 DQ 轴 PID Kp（DKP）", 1.0, None, 0.0, 7.0, 0.1,
           chk(CUSTOMER_H, "MOTOR_START_DQKP"), "电流环 PI", [F5], shell="_Q12(x)"),
        cp("motor_start_dqki", "启动阶段 DQ 轴 PID Ki（DKI）", 0.01, None, 0.0, 0.999, 0.005,
           chk(CUSTOMER_H, "MOTOR_START_DQKI"), "电流环 PI", [F5], shell="_Q15(x)"),
        cp("motor_start_times", "启动 ATO 运行时间", 700, "ms", 700, 2500, 50,
           chk(CUSTOMER_H, "MOTOR_START_TIMES"), "启动", [F5]),
        cp("motor_open_acc", "强拖启动增量", 0.009, None, 0.0, 0.1, 0.001,
           chk(CUSTOMER_H, "MOTOR_OPEN_ACC"), "启动", [F5], shell="_Q15(x)"),
        cp("motor_open_acc_cnt", "强拖启动执行次数", 65, "次", 1, 500, 1,
           chk(CUSTOMER_H, "MOTOR_OPEN_ACC_CNT"), "启动", [F5]),
        cp("motor_omega_ramp_acc", "Omega 启动增量", 2, None, 1, 50, 1,
           chk(CUSTOMER_H, "MOTOR_OMEGA_RAMP_ACC"), "启动", [F5]),
        cp("motor_omega_acc_min", "Omega 启动最低数值", 0.015, None, 0.0, 0.5, 0.001,
           chk(CUSTOMER_H, "MOTOR_OMEGA_ACC_MIN"), "启动", [F5], shell="_Q15(x)"),
        cp("motor_omega_acc_end", "Omega 启动限制数值", 0.035, None, 0.0, 0.5, 0.001,
           chk(CUSTOMER_H, "MOTOR_OMEGA_ACC_END"), "启动", [F5], shell="_Q15(x)"),

        # --- 预定位（98 次实验注入故障的参数组）---
        cp("motor_align_enabled", "预定位使能", 1, None, 0, 1, 1,
           chk(CUSTOMER_H, "MOTOR_ALIGN_ENABLED"), "预定位", [F2, F5]),
        cp("motor_alignment_dout", "预定位 D 轴输出强度", 0.06, None, 0.01, 0.4, 0.01,
           chk(CUSTOMER_H, "MOTOR_ALIGNMENT_DOUT"), "预定位", [F5], shell="_Q15(x)",
           note="98 次启动故障实验注入的就是本参数偏弱（align_weak）"),
        cp("motor_alignment_degrees", "预定位角度", 50.0, "度", -60.0, 60.0, 1.0,
           chk(CUSTOMER_H, "MOTOR_ALIGNMENT_DEGREES"), "预定位", [F5]),
        cp("motor_alignment_times", "预定位时间", 450, "ms", 300, 2000, 10,
           chk(CUSTOMER_H, "MOTOR_ALIGNMENT_TIMES"), "预定位", [F5]),

        # --- 观测器带宽 ---
        cp("ato_bw", "角度观测器带宽 ATO_BW", 20.0, None, 5.0, 100.0, 1.0,
           chk(CUSTOMER_H, "ATO_BW"), "观测器", [F5],
           range_estimated=True,
           note="Customer.h 未给 ATO_BW 的范围注释；min/max 借 SPD_BW 的 [5 ~ 40] 并放宽到 100 覆盖 ATO_BW_RUN1~4 的实配值（30/53/65/65），属推定区间",
           placeholder=False),
        cp("ato_bw_run", "运行段观测器带宽 ATO_BW_RUN", 20.0, None, 5.0, 100.0, 1.0,
           chk(CUSTOMER_H, "ATO_BW_RUN"), "观测器", [F5]),
        cp("ato_bw_run1", "运行段观测器带宽 1", 30.0, None, 5.0, 100.0, 1.0,
           chk(CUSTOMER_H, "ATO_BW_RUN1"), "观测器", [F5]),
        cp("ato_bw_run2", "运行段观测器带宽 2", 53.0, None, 5.0, 100.0, 1.0,
           chk(CUSTOMER_H, "ATO_BW_RUN2"), "观测器", [F5]),
        cp("ato_bw_run3", "运行段观测器带宽 3", 65.0, None, 5.0, 100.0, 1.0,
           chk(CUSTOMER_H, "ATO_BW_RUN3"), "观测器", [F5]),
        cp("ato_bw_run4", "运行段观测器带宽 4", 65.0, None, 5.0, 100.0, 1.0,
           chk(CUSTOMER_H, "ATO_BW_RUN4"), "观测器", [F5]),
        cp("spd_bw", "速度带宽滤波 SPD_BW", 20.0, None, 5.0, 40.0, 1.0,
           chk(CUSTOMER_H, "SPD_BW"), "观测器", [F5]),
        cp("smothecomp_degrees", "SMO 估算器角度补偿量", 5.0, "度", -30.0, 30.0, 0.5,
           chk(CUSTOMER_H, "SMOTHECOMP_DEGREES"), "观测器", [F5],
           note="仅 SMOTHECOMP_ENABLED = 1 时生效，当前为 0"),

        # --- 运行电流环 ---
        cp("motor_run_dqkp", "运行阶段 DQ 轴 PID Kp（DKP）", 0.8, None, 0.0, 7.0, 0.1,
           chk(CUSTOMER_H, "MOTOR_RUN_DQKP"), "电流环 PI", [F5], shell="_Q12(x)"),
        cp("motor_run_dqki", "运行阶段 DQ 轴 PID Ki（DKI）", 0.01, None, 0.0, 0.999, 0.005,
           chk(CUSTOMER_H, "MOTOR_RUN_DQKI"), "电流环 PI", [F5], shell="_Q15(x)"),
        cp("motor_run_iq_current", "运行阶段 Q 轴初始电流", 0.6, "A", 0.1, 10.0, 0.1,
           chk(CUSTOMER_H, "MOTOR_RUN_IQ_CURRENT"), "电流环 PI", [F5], shell="I_Value(x)"),
        cp("dout_max", "运行 D 轴最大幅值", 0.98, None, 0.2, 0.999, 0.01,
           chk(CUSTOMER_H, "DOUT_MAX"), "限幅", [F5], shell="_Q15(x)"),
        cp("qout_max", "运行 Q 轴最大幅值", 0.98, None, 0.2, 0.999, 0.01,
           chk(CUSTOMER_H, "QOUT_MAX"), "限幅", [F5], shell="_Q15(x)"),

        # --- 速度外环 PI ---
        cp("outloop_enabled", "外环控制使能", 1, None, 0, 1, 1,
           chk(CUSTOMER_H, "OUTLOOP_ENABLED"), "速度外环 PI", [F2, F5]),
        cp("speed_kp", "速度环 PID Kp（SKP）", 0.8, None, 0.0, 6.999, 0.1,
           chk(CUSTOMER_H, "SPEED_KP"), "速度外环 PI", [F5], shell="_Q12(x)",
           note="规程分诊：稳态转速振荡（3 次极差 > 3%）时 SKP −20%，一次只动一项"),
        cp("speed_ki", "速度环 PID Ki（SKI）", 0.015, None, 0.0, 0.999, 0.005,
           chk(CUSTOMER_H, "SPEED_KI"), "速度外环 PI", [F5], shell="_Q15(x)",
           note="规程分诊：稳态转速偏差超容限但稳定时 SKI +20%"),
        cp("speed_kd", "速度环 PID Kd", 0.004, None, 0.0, 0.999, 0.001,
           chk(CUSTOMER_H, "SPEED_KD"), "速度外环 PI", [F5], shell="_Q15(x)"),
        cp("sout_min", "速度环 PID 幅值下限", 0.1, "A", 0.0, 10.0, 0.1,
           chk(CUSTOMER_H, "SOUT_MIN"), "速度外环 PI", [F5], shell="I_Value(x)"),
        cp("sout_max", "速度环 PID 幅值上限", 10.0, "A", 0.1, 20.0, 0.1,
           chk(CUSTOMER_H, "SOUT_MAX"), "速度外环 PI", [F5], shell="I_Value(x)"),
        cp("speed_refresh_times", "转速侦测刷新时间（外环周期 LOOP_TIME 对应项）", 15, "ms", 5, 200, 1,
           chk(CUSTOMER_H, "SPEED_REFRESH_TIMES"), "速度外环 PI", [F5],
           note="吸尘器规程里的 LOOP_TIME 在本散热风扇工程对应 SPEED_REFRESH_TIMES；"
                "本工程无 LOOP_TIME 宏"),
        cp("speed_jerk_times", "加加速执行时间", 400, "ms", 100, 1000, 10,
           chk(CUSTOMER_H, "SPEED_JERK_TIMES"), "速度外环 PI", [F5]),
        cp("speed_jerk_max_value", "加加速最大增量", 80, None, 10, 120, 1,
           chk(CUSTOMER_H, "SPEED_JERK_MAX_VALUE"), "速度外环 PI", [F5]),
        cp("speed_dec", "速度环递减量", 20, None, 1, 120, 1,
           chk(CUSTOMER_H, "SPEED_DEC"), "速度外环 PI", [F5]),

        # --- 载波 / 死区 ---
        cp("pwm_frequency", "PWM 载波频率", 25.0, "kHz", 10.0, 90.0, 0.5,
           chk(CUSTOMER_H, "PWM_FREQUENCY"), "载波与死区", [F2, F5],
           note="min/max 取自 Customer.h「PWM 寬頻支援: 10hz ~ 90khz」注释中的 kHz 量级上下限"),
        cp("pwm_deadtime", "PWM 死区时间", 0.6, "us", 0.1, 3.0, 0.1,
           chk(CUSTOMER_H, "PWM_DEADTIME"), "载波与死区", [F5],
           range_estimated=True,
           note="Customer.h 未给死区范围注释，min/max 为按 MIN_WIND_TIME/PWM_MIN_WIDTH 量级推定的可调区间",
           placeholder=False),
        cp("pwm_dt_offset", "死区时间补偿", 0.4, "us", 0.0, 2.0, 0.1,
           chk(CUSTOMER_H, "PWM_DT_OFFSET"), "载波与死区", [F5],
           note="仅 HW_SHUNT_MODE 为 DUAL_SHUNT / THREE_SHUNT 时有效；本工程为 SINGLE_SHUNT"),
        cp("pwm_min_width", "最小脉宽时间", 1.3, "us", 0.1, 5.0, 0.1,
           chk(CUSTOMER_H, "PWM_MIN_WIDTH"), "载波与死区", [F5]),
        cp("trgdly_position", "采样位置", 8, None, -127, 127, 1,
           chk(CUSTOMER_H, "TRGDLY_POSITION"), "载波与死区", [F5],
           note="时间换算 41.67 ns × TRGDLY_POSITION，正数为延迟"),
        cp("svpwm_mode", "SVPWM 输出模式", "SEG7_SVPWM_MODE", None, None, None, None,
           chk(CUSTOMER_H, "SVPWM_MODE"), "载波与死区", [F5],
           options=[{"value": "SEG7_SVPWM_MODE", "label": "七段式 SVPWM"},
                    {"value": "SEG5_SVPWM_MODE", "label": "五段式 SVPWM"}],
           note="枚举型参数，取值集合见 options；min/max/step 不适用"),

        # --- 调速 ---
        cp("speed_mode", "调速控制模式", "PWMMODE", None, None, None, None,
           chk(CUSTOMER_H, "SPEED_MODE"), "调速", [F2, F4],
           options=[{"value": "NONEMODE", "label": "无调速输入，按 NONEMODE_SPEED 定速"},
                    {"value": "PWMMODE", "label": "PWM 占空比调速"},
                    {"value": "VSPMODE", "label": "VSP 模拟电压调速"}],
           note="枚举型参数，取值集合见 options；min/max/step 不适用。"
                "coolingfan-openloop-debug 规程要求改成 NONEMODE 做速度闭环调试"),
        cp("nonemode_speed", "无调速模式目标转速", 4000, "RPM", 1000, 40000, 100,
           chk(CUSTOMER_H, "NONEMODE_SPEED"), "调速", [F4],
           note="coolingfan-openloop-debug 的「闭环目标转速」写入目标宏族之一"),
        cp("motor_min_duty", "最小输出占空比", 0.1, None, 0.0, 1.0, 0.01,
           chk(CUSTOMER_H, "MOTOR_MIN_DUTY"), "调速", [F5], shell="_Q15(x)"),
        cp("motor_max_duty", "最大输出占空比", 0.9, None, 0.0, 1.0, 0.01,
           chk(CUSTOMER_H, "MOTOR_MAX_DUTY"), "调速", [F5], shell="_Q15(x)"),

        # --- 顺逆风 ---
        cp("motor_tailwind_enabled", "顺逆风启动使能", 1, None, 0, 1, 1,
           chk(CUSTOMER_H, "MOTOR_TAILWIND_ENABLED"), "顺逆风", [F2, F4]),
        cp("motor_tailwind_detect_min_speed", "最小顺逆风检测阈值", 900, "RPM", 100, 10000, 50,
           chk(CUSTOMER_H, "MOTOR_TAILWIND_DETECT_MIN_SPEED"), "顺逆风", [F5]),
        cp("motor_tailwind_detect_times", "顺逆风检测时间", 150, "ms", 100, 1000, 10,
           chk(CUSTOMER_H, "MOTOR_TAILWIND_DETECT_TIMES"), "顺逆风", [F5]),
        cp("tailwind_dqkp", "顺风启动 DQ 轴 Kp", 3.5, None, 0.0, 7.0, 0.1,
           chk(CUSTOMER_H, "TAILWIND_DQKP"), "顺逆风", [F5], shell="_Q12(x)"),
        cp("tailwind_dqki", "顺风启动 DQ 轴 Ki", 0.4, None, 0.0, 1.0, 0.05,
           chk(CUSTOMER_H, "TAILWIND_DQKI"), "顺逆风", [F5], shell="_Q15(x)"),
        cp("tailwind_start_uq", "顺风启动 UQ 初始值", 8000, None, 0, 32767, 100,
           chk(CUSTOMER_H, "TAILWIND_START_UQ"), "顺逆风", [F5],
           range_estimated=True,
           note="Customer.h 未给范围，min/max 按 Q15 全量程推定"),
        cp("tailwind_start_iq_current", "顺风启动 IQ 电流", 0.8, "A", 0.1, 10.0, 0.1,
           chk(CUSTOMER_H, "TAILWIND_START_IQ_CURRENT"), "顺逆风", [F5], shell="I_Value(x)"),
        cp("tailwind_start_angle", "顺风启动角度", 0, "度", -80, 80, 1,
           chk(CUSTOMER_H, "TAILWIND_START_ANGLE"), "顺逆风", [F5]),
        cp("headwind_lowspeed_threshold", "低速逆风检测阈值", 4000, "RPM", 100, 20000, 100,
           chk(CUSTOMER_H, "HEADWIND_LOWSPEED_THRESHOLD"), "顺逆风", [F5],
           note="HEADWIND_IQ_BRAKE_ENABLED = 1 时不得高于 IQ_BRAKE_START_SPEED"),
        cp("headwind_brake_time_base", "逆风制动时间基础", 1000, "ms", 800, 60000, 100,
           chk(CUSTOMER_H, "HEADWIND_BRAKE_TIME_BASE"), "顺逆风", [F5]),
        cp("headwind_alignment_times", "逆风预定位时间", 1000, "ms", 800, 60000, 100,
           chk(CUSTOMER_H, "HEADWIND_ALIGNMENT_TIMES"), "顺逆风", [F5]),
        cp("headwind_alignment_dout", "逆风预定位 D 轴输出强度", 0.1, None, 0.01, 0.4, 0.01,
           chk(CUSTOMER_H, "HEADWIND_ALIGNMENT_DOUT"), "顺逆风", [F5], shell="_Q15(x)"),
        cp("headwind_start_iq_current", "逆风启动电流", 2.5, "A", 0.1, 10.0, 0.1,
           chk(CUSTOMER_H, "HEADWIND_START_IQ_CURRENT"), "顺逆风", [F5], shell="I_Value(x)"),
        cp("iq_brake_start_speed", "逆转启动触发转速", 4000, "RPM", 100, 20000, 100,
           chk(CUSTOMER_H, "IQ_BRAKE_START_SPEED"), "顺逆风", [F5]),
        cp("iq_brake_dqkp", "逆转启动 DQ 轴 Kp", 2.8, None, 0.0, 7.0, 0.1,
           chk(CUSTOMER_H, "IQ_BRAKE_DQKP"), "顺逆风", [F5], shell="_Q12(x)"),
        cp("iq_brake_dqki", "逆转启动 DQ 轴 Ki", 0.1, None, 0.0, 1.0, 0.05,
           chk(CUSTOMER_H, "IQ_BRAKE_DQKI"), "顺逆风", [F5], shell="_Q15(x)"),
        cp("iq_brake_start_degrees", "逆转启动初始角度", 135.0, "度", -180.0, 180.0, 1.0,
           chk(CUSTOMER_H, "IQ_BRAKE_START_DEGREES"), "顺逆风", [F5]),

        # --- 限流限功率 ---
        cp("current_limiter_mode", "电流限制器模式", "NONE", None, None, None, None,
           chk(CUSTOMER_H, "CURRENT_LIMITER_MODE"), "限流限功率", [F2, F5],
           options=[{"value": "NONE", "label": "不启用电流限制器"},
                    {"value": "LEGACY", "label": "传统单点限流"},
                    {"value": "MULTI", "label": "多段限流"}],
           note="枚举型参数，取值集合见 options；min/max/step 不适用"),
        cp("current_limiter_threshold", "电流限制阈值", 0.6, "A", 1.0, 15.625, 0.1,
           chk(CUSTOMER_H, "CURRENT_LIMITER_THRESHOLD"), "限流限功率", [F5],
           value_below_min=True,
           note="源注释范围写作 [1.0 ~ HW_BOARD_CURR_MAX]。上限 15.625 A 是按 Parameter.h:42 的公式 "
                "HW_BOARD_CURR_MAX = HW_ADC_REF / 2.0 / HW_AMPGAIN / HW_RSHUNT 实算得出："
                "HW_ADC_REF = 5.0 V（Parameter.h:106，因 Customer.h:87 HW_ADC_REF_TYPE = REF_5V0）、"
                "HW_AMPGAIN = 16（Customer.h:86 GAIN_16）、HW_RSHUNT = 0.01 Ω（Customer.h:85），"
                "5.0 / 2 / 16 / 0.01 = 15.625。"
                "实配值 0.6 A 低于源注释自己写的下限 1.0 A，源材料自身不一致，按原样登记并置 "
                "value_below_min: true，前端不得把 0.6 当成落在合法区间内的值"),
        cp("power_limiter_mode", "功率限制器模式", "NONE", None, None, None, None,
           chk(CUSTOMER_H, "POWER_LIMITER_MODE"), "限流限功率", [F2, F5],
           options=[{"value": "NONE", "label": "不启用功率限制器"},
                    {"value": "LEGACY", "label": "传统单点限功率"},
                    {"value": "MULTI", "label": "多段限功率"}],
           note="枚举型参数，取值集合见 options；min/max/step 不适用"),
        cp("power_limiter_threshold", "功率限制阈值", 3.0, "W", 1.0, None, 0.5,
           chk(CUSTOMER_H, "POWER_LIMITER_THRESHOLD"), "限流限功率", [F5],
           note="上限 MAX_PWOER（源注释原文拼写）在本工程头文件未定义"),
    ]
    obj = {
        "schema": "control-parameters/v1",
        "scene_id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "belongs_to_flow": "主放 F4 启动测试及结果分析 / F5 调优确认及运行；"
                           "使能类开关在 F2 初始化配置确认",
        "groups": ["启动", "预定位", "观测器", "电流环 PI", "速度外环 PI", "限幅",
                   "载波与死区", "调速", "顺逆风", "限流限功率"],
        "notes": [
            "全部取值与范围来自本地可达的 Customer.h（41 KB，202 条 #define）与 25 份 dc-skills 规程，"
            "不来自记忆。min/max/step 优先用源文件行尾 [範圍: a ~ b] 注释；"
            "源文件没给范围的，note 字段写明是推定区间。",
            "value_shell 字段保留源文件的数值外壳（I_Value / _Q12 / _Q15），"
            "回写 Customer.h 时必须沿用原外壳，只改括号内数字。",
            "枚举型参数（带 options 数组）与缺口型参数不适用 min/max/step，这三个字段一律为 null，"
            "前端应渲染成下拉选择而不是加减号。",
            "range_estimated: true 表示该项的 min/max 是本包推定的，Customer.h 行尾没有 [範圍: a ~ b] 注释。",
            "value_below_min: true 表示实配值低于源注释自己写的下限，属源材料自身不一致，"
            "本包按原样登记未做修正，前端要显式标出。",
        ],
        "parameters": items,
    }
    return dump("control-parameters.json", obj)


# ------------------------------------------------- 4. safety-interlocks.json
def gen_safety_interlocks():
    RULES = os.path.join(AITIOR, "dc-rules/vacuum-flow-discipline.md")
    items = [
        {
            "id": "SI-HW-01", "name": "母线过压保护阈值", "type": "硬件",
            "threshold": {"value": 18.0, "unit": "V", "min": None, "max": 30.0,
                          "recover": 14.0, "recover_unit": "V"},
            "action": "超过阈值触发 FAULT_OVP(0x0008)，停机并按恢复阈值自动恢复",
            "blocking": True,
            "_source": [macro_src(PROTECT_H, "PROTECTION_OV_PROTECT_THRESHOLD"),
                        macro_src(PROTECT_H, "PROTECTION_OV_RECOVER_THRESHOLD"),
                        macro_src(MOTOR_PROT_H, "FAULT_OVP")],
            "quote": "PROTECTION_OV_PROTECT_THRESHOLD (18.0) 過電壓保護觸發閾值 "
                     "[範圍: (PROTECTION_OV_RECOVER_THRESHOLD + 0.5) ~ 30.0]",
        },
        {
            "id": "SI-HW-02", "name": "母线欠压保护阈值", "type": "硬件",
            "threshold": {"value": 7.0, "unit": "V", "min": 6.0, "max": None,
                          "recover": 8.0, "recover_unit": "V"},
            "action": "低于阈值触发 FAULT_UVP(0x0004)，停机并按恢复阈值自动恢复",
            "blocking": True,
            "_source": [macro_src(PROTECT_H, "PROTECTION_UV_PROTECT_THRESHOLD"),
                        macro_src(PROTECT_H, "PROTECTION_UV_RECOVER_THRESHOLD"),
                        macro_src(MOTOR_PROT_H, "FAULT_UVP")],
            "quote": "PROTECTION_UV_PROTECT_THRESHOLD (7.0) 欠電壓保護觸發閾值 "
                     "[範圍: (6.0 ~ (PROTECTION_UV_RECOVER_THRESHOLD - 0.5)]",
        },
        {
            "id": "SI-HW-03", "name": "下电保护阈值", "type": "硬件",
            "threshold": {"value": 6.5, "unit": "V", "min": 5.0, "max": 6.5},
            "action": "低于阈值触发 FAULT_POWERLOSE(0x0200)",
            "blocking": True,
            "_source": [macro_src(PROTECT_H, "PROTECTION_POWERLOSE_THRESHOLD"),
                        macro_src(MOTOR_PROT_H, "FAULT_POWERLOSE")],
        },
        {
            "id": "SI-HW-04", "name": "软件过流阈值", "type": "硬件",
            "threshold": {"value": 10.0, "unit": "A", "min": None, "max": None},
            "action": "超过阈值触发 FAULT_SW_OCP(0x0002)；硬件过流走 DAC 比较触发 FAULT_HW_OCP(0x0001)，"
                      "过流恢复时间 1500 ms",
            "blocking": True,
            "_source": [macro_src(PROTECT_H, "PROTECTION_OC_SOFT_THRESHOLD"),
                        macro_src(PROTECT_H, "PROTECTION_OC_DAC_VALUE"),
                        macro_src(PROTECT_H, "PROTECTION_OC_RECOVER_TIMES"),
                        macro_src(MOTOR_PROT_H, "FAULT_SW_OCP")],
        },
        {
            "id": "SI-HW-05", "name": "堵转保护超时与重启", "type": "硬件",
            "threshold": {"trig_count": 25, "trig_count_range": [5, 60],
                          "recover_times_ms": 6000, "recover_range_ms": [1000, 60000],
                          "retry_enabled": 0, "retry_count": 1},
            "action": "堵转计数达阈值触发 FAULT_STALL_*（0x0020 / 0x0040 / 0x0060 / 0x0080 四种算法），"
                      "6000 ms 后恢复；当前工程堵转重启尝试为禁用",
            "blocking": True,
            "_source": [macro_src(PROTECT_H, "PROTECTION_STALL_ENABLED"),
                        macro_src(PROTECT_H, "PROTECTION_TRIG_COUNT_THRESHOLD"),
                        macro_src(PROTECT_H, "PROTECTION_STALL_RECOVER_TIMES"),
                        macro_src(PROTECT_H, "PROTECTION_RETRY_START_ENABLED"),
                        macro_src(MOTOR_PROT_H, "FAULT_STALL_METHOD_SPDES")],
        },
        {
            "id": "SI-HW-06", "name": "缺相保护", "type": "硬件",
            "threshold": {"enabled": 1, "recover_times_ms": 3000,
                          "recover_range_ms": [1000, 60000]},
            "action": "触发 FAULT_PHASELOSS(0x0010)。规程口径：判到缺相立即停止迭代，转人工查接线",
            "blocking": True,
            "_source": [macro_src(PROTECT_H, "PROTECTION_PHASELOSS_ENABLED"),
                        macro_src(MOTOR_PROT_H, "FAULT_PHASELOSS"),
                        src(os.path.join(AITIOR, "dc-skills/coolingfan-openloop-debug/SKILL.md"),
                            "第 5 节 失败分诊表「fault=5(缺相) → 停止迭代，反问用户检查接线」")],
        },
        {
            "id": "SI-HW-07", "name": "温度上限", "type": "硬件",
            # L3：旧键名 ambient_max_dual_supply_c 只说了双电源一种情形，
            # 数据手册实际给的是「满足以下任一供电条件即可放宽到 105 ℃」的两种条件。
            "threshold": {
                "ambient_max_c": 85,
                "junction_max_c": 150,
                "ambient_max_derated_c": 105,
                "ambient_derate_conditions": [
                    {"key": "dual_supply",
                     "text": "双电源模式：VCC_MODE = 1，VDD5 = 5 V，VCC < 28 V"},
                    {"key": "single_supply",
                     "text": "单电源模式：VCC_MODE = 0，VCC < 15 V"},
                ],
                "ambient_derate_logic": "any_of",
            },
            "action": "超出即超规格运行，测试台架必须停测",
            "blocking": True,
            "_placeholder": True,
            "note": "两层缺口。其一，本工程 Customer.h / Protect.h 无 NTC 或过温保护宏"
                    "（已 grep TEMP / NTC 零命中），此处温度上限取自 FU6832 数据手册的器件级规格，"
                    "不是驱动板的整机过温联锁，整机过温判据待客户确认。"
                    "其二，105 ℃ 不是无条件上限：数据手册给的是双电源与单电源两种供电条件，"
                    "满足其一才放宽（ambient_derate_logic = any_of），"
                    "两种条件都不满足时上限仍是 85 ℃。"
                    "本板走哪种供电模式、VCC 实际值多少，本包未核实，前端不得直接按 105 ℃ 放行",
            "_source": src(DATASHEET,
                           "PDF 第 56 页 表5-1 绝对最大额定值：「工作时环境温度TA」三行"
                           "（无条件 -40~85 ℃；双电源模式 VCC_MODE=1、VDD5=5V、VCC<28V 时 -40~105 ℃；"
                           "单电源模式 VCC_MODE=0、VCC<15V 时 -40~105 ℃）与「工作时结温TJ」-40~150 ℃"),
        },
        {
            "id": "SI-PROC-01", "name": "PASS 基线禁改", "type": "流程",
            # M5：本条摘自 dc-rules/vacuum-flow-discipline.md（标题即「吸尘器调试通用铁律」）
            "source_product_line": "vacuum",
            "applies_to_cooling_fan_note": "纪律本身与产品线无关，可直接沿用；但条款里点名的工具链与阶段清单是吸尘器线的，迁到散热风扇要重新核对",
            "threshold": None,
            "action": "已判 PASS 的参数视为基线，后续阶段不得擅自改动；确需改动先说明理由并征得用户同意",
            "blocking": True,
            "_source": src(os.path.join(AITIOR, "dc-rules/vacuum-flow-discipline.md"),
                           "第 3 条铁律"),
            "quote": "**PASS 基线禁擅改**:已判 PASS 的参数视为基线,后续阶段不得擅自改动;"
                     "确需改动先说明理由并征得同意。",
        },
        {
            "id": "SI-PROC-02", "name": "跑完必停机", "type": "流程",
            # M5：本条摘自 dc-rules/vacuum-flow-discipline.md（标题即「吸尘器调试通用铁律」）
            "source_product_line": "vacuum",
            "applies_to_cooling_fan_note": "纪律本身与产品线无关，可直接沿用；但条款里点名的工具链与阶段清单是吸尘器线的，迁到散热风扇要重新核对",
            "threshold": None,
            "action": "任何让电机运转的流程，所有退出路径必须把使能拉低（吸尘器线为 GD32 CMD24 控制 PG0 关断）；"
                      "debug / reset / run / freerun 都不得用于启停电机",
            "blocking": True,
            "_source": src(os.path.join(AITIOR, "dc-rules/vacuum-flow-discipline.md"),
                           "第 5 条铁律"),
            "quote": "**跑完必停机**:任何让电机运转的流程都只允许由原子工具使用 GD32 CMD24 控制 PG0 启停,"
                     "所有退出路径必须 PG0-off;`debug` / `reset` / `run` / `freerun` 都不得用于启停电机。",
        },
        {
            "id": "SI-PROC-03", "name": "改参先问用户", "type": "流程",
            # M5：本条摘自 dc-rules/vacuum-flow-discipline.md（标题即「吸尘器调试通用铁律」）
            "source_product_line": "vacuum",
            "applies_to_cooling_fan_note": "纪律本身与产品线无关，可直接沿用；但条款里点名的工具链与阶段清单是吸尘器线的，迁到散热风扇要重新核对",
            "threshold": None,
            "action": "改任何源码或参数前先向用户说明并征得同意，拿到明确答复再动手",
            "blocking": True,
            "_source": src(os.path.join(AITIOR, "dc-rules/vacuum-flow-discipline.md"), "第 2 条铁律"),
            "quote": "**改参先问用户**:改任何源码 / 参数前先向用户说明并征得同意,拿到明确答复再动手。",
        },
        {
            "id": "SI-PROC-04", "name": "阶段顺序不可乱（功率标定必须排在运行稳定前）", "type": "流程",
            # M5：本条摘自 dc-rules/vacuum-flow-discipline.md（标题即「吸尘器调试通用铁律」）
            "source_product_line": "vacuum",
            "applies_to_cooling_fan_note": "纪律本身与产品线无关，可直接沿用；但条款里点名的工具链与阶段清单是吸尘器线的，迁到散热风扇要重新核对",
            "threshold": None,
            "action": "识别 → 灌默认基线 →（验板 → 验采样）→ 启动 → 顺风 → 功率标定 → 运行稳定 → 保护 → 启停测试",
            "blocking": True,
            "_source": src(os.path.join(AITIOR, "dc-rules/vacuum-flow-discipline.md"), "第 9 条铁律"),
            "quote": "**阶段順序**:识别 → 灌默认基线 → (验板 → 验采样) → 启动 → 顺风 → 功率标定 → "
                     "运行稳定 → 保护 → 启停测试。**功率标定(Power_k)必须排在运行稳定之前**,"
                     "否则 sweep 全是错工作点。",
            "note": "调研文档 A 已记录缺口：power-calibration 在场景清单里仍是 planned，流程链有断点",
        },
        {
            "id": "SI-PROC-05", "name": "保护阈值严禁在线改写", "type": "流程",
            "threshold": None,
            "action": "OVP / UVP / LVW 验证一律只读 RAM 观测，禁止用 writemem 写阈值变量；"
                      "触发条件只能由用户手动调电源产生",
            "blocking": True,
            "_source": [src(os.path.join(AITIOR, "dc-skills/protect-verify-ovp/SKILL.md"),
                            "设计约束段"),
                        src(os.path.join(AITIOR, "dc-skills/protect-verify-uvp/SKILL.md"),
                            "设计约束段")],
            "quote": "设计约束:**严禁在线改 OVP 阈值**(writemem 写阈值变量是违规)。"
                     "所有触发依赖用户手动调电源,本 skill 只做观测 + 调回校验。",
        },
        {
            "id": "SI-PROC-06", "name": "改固件前工作区必须 clean，中断即还原", "type": "流程",
            "threshold": None,
            "action": "超速 / 启动失败保护验证走 protect-verify/* 临时分支隔离；"
                      "任一步骤失败立即进中断保护，git reset + 重编重烧回 baseline，"
                      "不得让用户在临时分支固件上下机",
            "blocking": True,
            "_source": src(os.path.join(AITIOR, "dc-skills/protect-verify-overspeed/SKILL.md"),
                           "设计前提段与「## 中断保护」小节"),
        },
        {
            "id": "SI-PROC-07", "name": "电源调回复检（±5%）", "type": "流程",
            "threshold": {"tolerance_pct": 5},
            "action": "过压/欠压/低压告警验证结束后，必须提示用户把电源调回原母线电压，"
                      "等用户明确回「已调回」，再读母线 ADC 复检；偏差 > 5% 判定降级",
            "blocking": True,
            "_source": src(os.path.join(AITIOR, "dc-skills/protect-verify-ovp/SKILL.md"),
                           "第 2 节 Vbus 复检(强约束)"),
        },
        {
            "id": "SI-EQ-01", "name": "示波器在线校验", "type": "硬件",
            "threshold": {"expected_idn": "RIGOL TECHNOLOGIES,DS1104Z",
                          "visa_resource_pattern": "USB0::0x1AB1::0x04CE::<serial>::INSTR"},
            "action": "开跑前用 rigol_measure 试探示波器；返回数值记「示波器模式」，"
                      "失败或用户选「无示波器」记「降级模式」并改用用户回报转速口径。不中断流程",
            "blocking": False,
            "_source": [src(os.path.join(AITIOR, "dc-skills/coolingfan-openloop-debug/SKILL.md"),
                            "第 0 节 前置检查"),
                        src(CAPTURE_INFO_SAMPLE, "idn / resource 字段")],
        },
        {
            "id": "SI-EQ-02", "name": "程控电源在线校验", "type": "硬件",
            "threshold": None,
            "action": "保护验证与开关电源类场景要求程控电源在册可控；"
                      "场景清单标注 hw-selfcheck、protect-verify、reliability 三类需要程控电源",
            "blocking": True,
            "_source": src(DOC_A, "第一节 场景表「需要设备」列"),
        },
        {
            "id": "SI-EQ-03", "name": "台架信号接线校验（FG1/FG2/PWM1/PWM2）", "type": "硬件",
            "threshold": {"ch1": "FG1（电气转速）", "ch2": "FG2（红外机械真值，1 脉冲/转）",
                          "ch3": "PWM1（驱动被测风扇）", "ch4": "PWM2（驱动逆风风扇）或 48V"},
            "action": "开跑前核对示波器四通道接线；FG 多为开漏，可能需上拉才能看到方波",
            "blocking": True,
            "_source": src(BENCH_MEMO, "「示波器接线」段"),
        },
        {
            "id": "SI-PERSON-01", "name": "人员离场确认", "type": "人员",
            "threshold": {"confirm_required": True},
            "action": "启动测试前必须由操作者显式确认「人已离开设备旁」，未确认不得启动",
            "blocking": True,
            "_source": src(DOC_NEED, "典型流程 2「测试保护/不能违背的原则（如人不能在设备旁否则不能启动、"
                                     "电压绝对不能大于多少伏——名字待定）」"),
            "note": "来自用户需求原话，属产品需求而非现有规程条款；现有 25 份 dc-skills 无对应实现",
        },
        {
            "id": "SI-PERSON-02", "name": "半自动步骤的人工确认闸口", "type": "人员",
            "threshold": {"accepted_replies": ["已调回", "done"]},
            "action": "半自动验证（OVP / UVP / LVW）必须等用户明确回复确认，"
                      "不允许模型自行脑补已完成；烧录完成后不得自动发 debug 启动电机，"
                      "须等用户确认已上电",
            "blocking": True,
            "_source": [src(os.path.join(AITIOR, "dc-skills/protect-verify-ovp/SKILL.md"),
                            "第 2 节第 2 步「不要 AI 自己脑补已调回」"),
                        src(os.path.join(AITIOR, "dc-skills/coolingfan-openloop-debug/SKILL.md"),
                            "第 3 节第 3 步")],
        },
    ]
    obj = {
        "schema": "safety-interlocks/v1",
        "scene_id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "belongs_to_flow": "F2 初始化配置（呈现与确认）+ F4 启动测试及结果分析（不确认不允许运行）",
        "types": {"硬件": "由固件阈值或仪器状态判定", "流程": "由规程纪律约束执行顺序与动作",
                  "人员": "需要操作者显式确认才能放行"},
        "fault_bitmap": {
            "_source": src(MOTOR_PROT_H, "Motor_Protection.h:49-61 FAULT_* 位定义"),
            "total": 13,
            "value_range": "0x0000 ~ 0x8000",
            "matching_rule": (
                "13 条不是 13 个互斥的独立位，查表要分两步："
                "第一步先拿 fault 整值去 bits 做精确匹配，命中就用该条的名字——"
                "0x0000（FAULT_NONE 无错误）与 0x0060（FAULT_STALL_METHOD_UQOF）必须走这一步，"
                "前者按位与任何掩码都为 0，后者是 0x0020 | 0x0040 的复合常量而不是独立位；"
                "第二步整值未命中时才按位拆，逐位与 bits 里的单位常量做 & 运算列出全部命中项。"
                "堵转一族（0x0020 / 0x0040 / 0x0060 / 0x0080）合起来占 bit5~bit7，"
                "按位判定用掩码 0xE0 即可全覆盖，无须再单列 0x0060。"),
            "composite_values": {
                "0x0060": "FAULT_STALL_METHOD_UQOF = FAULT_STALL_METHOD_SPDES(0x0020) "
                          "| FAULT_STALL_METHOD_START(0x0040)，复合常量，不是独立位",
            },
            "masks": {
                "0xE0": "堵转保护一族（0x0020 | 0x0040 | 0x0080），已覆盖复合值 0x0060",
            },
            "bits": {
                "0x0000": "FAULT_NONE 無錯誤",
                "0x0001": "FAULT_HW_OCP 硬體過電流保護",
                "0x0002": "FAULT_SW_OCP 軟體過電流保護",
                "0x0004": "FAULT_UVP 欠電壓保護",
                "0x0008": "FAULT_OVP 過電壓保護",
                "0x0010": "FAULT_PHASELOSS 缺相保護",
                "0x0020": "FAULT_STALL_METHOD_SPDES 堵轉保護（轉速-反電動勢比值演算法）",
                "0x0040": "FAULT_STALL_METHOD_START 堵轉保護（演算法）",
                "0x0060": "FAULT_STALL_METHOD_UQOF 堵轉保護（演算法）",
                "0x0080": "FAULT_STALL_METHOD_OFR 堵轉保護（演算法）",
                "0x0100": "FAULT_CURROFFSET_OFR 偏置電流異常",
                "0x0200": "FAULT_POWERLOSE 輸入電源遺失保護",
                "0x8000": "FAULT_TEST 測試用保護",
            },
        },
        "interlocks": items,
    }
    return dump("safety-interlocks.json", obj)


# ------------------------------------------------- 5. test-requirements.json
# --- H1 判据可求值化：变量表构造器 ---
def vrt(name, desc, unit=None):
    """自由变量解析到运行时测量量（由采集/判定工具在执行时产出）。"""
    d = {"source": "runtime.measure", "ref": "runtime.measure.%s" % name, "desc": desc}
    if unit:
        d["unit"] = unit
    return d


def vth(key, desc, unit=None):
    """自由变量解析到本条 requirement 自己的 threshold 字段。"""
    d = {"source": "threshold", "ref": "threshold.%s" % key, "desc": desc}
    if unit:
        d["unit"] = unit
    return d


def vcp(key, desc, unit=None):
    """自由变量解析到 control-parameters.json 的某个 parameters[].key。"""
    d = {"source": "control-parameters",
         "ref": "control-parameters.%s" % key, "desc": desc}
    if unit:
        d["unit"] = unit
    return d


def vbit(hexkey, desc):
    """自由变量解析到 safety-interlocks.json 的 fault_bitmap 单个位常量。"""
    return {"source": "constant", "value": int(hexkey, 16), "hex": hexkey,
            "ref": "safety-interlocks.fault_bitmap.%s" % hexkey, "desc": desc}


def vmask(hexval, parts, desc):
    """自由变量解析到若干 fault_bitmap 位常量按位或出来的掩码。"""
    return {"source": "constant", "value": int(hexval, 16), "hex": hexval,
            "derived_from": ["safety-interlocks.fault_bitmap.%s" % p for p in parts],
            "desc": desc}


# 运行时测量量登记表：criterion 里 source 为 runtime.measure 的自由变量必须登记在这里
RUNTIME_MEASURES = {
    "pass_count": {"name": "启停回归通过次数", "unit": "次",
                   "obtained_by": "motor_startup_judge 逐次判定累加"},
    "fault_flag": {"name": "保护标志字（mcFaultState.faultFlag 整值）", "unit": None,
                   "obtained_by": "breakrun + readmem，或虚拟示波器 fault_flag 同窗采集"},
    "fg2_rpm_min_observed": {"name": "全部回合中 FG2 机械转速的最小值", "unit": "RPM",
                             "obtained_by": "CMD7 FG2 红外转速逐次采集取最小"},
    "probe_pass": {"name": "probe 阶段通过次数", "unit": "次",
                   "obtained_by": "auto-startup-tune probe 阶段计数"},
    "full_pass": {"name": "full 阶段通过次数", "unit": "次",
                  "obtained_by": "auto-startup-tune full 阶段计数"},
    "fg1_freq_hz": {"name": "FG1 电气转速信号频率", "unit": "Hz",
                    "obtained_by": "rigol_measure FREQ（CH1→FG1）"},
    "fg2_freq_hz": {"name": "FG2 机械转速信号频率", "unit": "Hz",
                    "obtained_by": "rigol_measure FREQ（CH2→FG2）"},
    "rpm_mean": {"name": "稳态转速 3 次测量均值", "unit": "RPM",
                 "obtained_by": "rigol_measure FREQ ×3 换算 RPM = FREQ × 60 / 极对数"},
    "target_rpm": {"name": "本次测试设定的目标转速", "unit": "RPM",
                   "obtained_by": "NONEMODE 下等于 control-parameters.nonemode_speed；"
                                  "PWMMODE 下由占空比查调速曲线得到"},
    "freq_range_over_mean_pct": {"name": "3 次频率测量的极差 / 均值", "unit": "%",
                                 "obtained_by": "rigol_measure FREQ ×3 现场计算"},
    "monotonic_drift_detected": {"name": "3 次测量是否呈单调漂移", "unit": None,
                                 "obtained_by": "rigol_measure FREQ ×3 现场判定，布尔"},
    "rpm_fg": {"name": "FG 脉冲换算转速", "unit": "RPM",
               "obtained_by": "FG 脉冲频率换算"},
    "rpm_real": {"name": "红外测速机械真值", "unit": "RPM",
                 "obtained_by": "红外转速计 / CMD7 FG2"},
    "t_start_to_steady_s": {"name": "启动到全速稳定时间", "unit": "s",
                            "obtained_by": "rigol_waveform_analyze 稳态起始时间"},
    "t_high_to_low_s": {"name": "高转到低转切换时间", "unit": "s",
                        "obtained_by": "FG 转速时序"},
    "t_low_to_high_s": {"name": "低转到高转切换时间", "unit": "s",
                        "obtained_by": "FG 转速时序"},
    "stalled": {"name": "切换过程中是否停转", "unit": None,
                "obtained_by": "FG 转速时序，布尔"},
    "i_peak_a": {"name": "启动过程母线峰值电流", "unit": "A",
                 "obtained_by": "示波器母线电流通道 VMAX"},
    "i_steady_a": {"name": "稳态母线电流", "unit": "A",
                   "obtained_by": "示波器母线电流通道稳态段均值"},
    "max_abs_rpm_error_pct": {"name": "11 个占空比档位中 RPM 误差绝对值的最大值", "unit": "%",
                              "obtained_by": "PWM·VSP 性能测试表 D 列（公式列）逐档取绝对值最大"},
    "max_overshoot_pct": {"name": "11 个占空比档位中过冲的最大值", "unit": "%",
                          "obtained_by": "PWM·VSP 性能测试表 G 列（公式列）逐档取最大"},
    "steady_current_over_limit_count": {"name": "稳态电流超过该档稳态上限的档位数", "unit": "档",
                                        "obtained_by": "PWM·VSP 性能测试表 F 列与 H 列逐档比较计数"},
    "stall_count_lv": {"name": "低电压档降 Duty 过程中的停转次数", "unit": "次",
                       "obtained_by": "FG 转速时序"},
    "stall_count_sv": {"name": "标准电压档降 Duty 过程中的停转次数", "unit": "次",
                       "obtained_by": "FG 转速时序"},
    "stall_count_hv": {"name": "高电压档降 Duty 过程中的停转次数", "unit": "次",
                       "obtained_by": "FG 转速时序"},
    "t_step_s": {"name": "每 10% PWM 阶跃的转速跳变时间", "unit": "s",
                 "obtained_by": "FG 转速时序"},
    "gears_restarted": {"name": "12 档残速重启中成功重启的档数", "unit": "档",
                        "obtained_by": "tailwind-restart-test 逐档判定累加"},
    "overshoot_peak_v": {"name": "顺/逆风过程相电压过冲峰值", "unit": "V",
                         "obtained_by": "示波器相电压通道 VMAX"},
    "overshoot_peak_a": {"name": "顺/逆风过程相电流过冲峰值", "unit": "A",
                         "obtained_by": "示波器相电流通道 VMAX 换算"},
    "max_normal_running_peak_v": {"name": "常态运行相电压最高值（同工况基线）", "unit": "V",
                                  "obtained_by": "同电压同转速常态运行段示波器基线采集"},
    "max_normal_running_peak_a": {"name": "常态运行相电流最高值（同工况基线）", "unit": "A",
                                  "obtained_by": "同电压同转速常态运行段示波器基线采集"},
    "t_windmilling_exit_s": {"name": "顺逆风处理到强制退出的时间", "unit": "s",
                             "obtained_by": "mcState 时序"},
    "vbus_0_v": {"name": "改动前的母线电压", "unit": "V",
                 "obtained_by": "程控电源读回 / 母线 ADC 换算"},
    "vbus_back_v": {"name": "调回后复检的母线电压", "unit": "V",
                    "obtained_by": "程控电源读回 / 母线 ADC 换算"},
    "stall_trig_count": {"name": "堵转触发计数实测值", "unit": "次",
                         "obtained_by": "readmem 堵转计数变量"},
    "vbus_measured_v": {"name": "母线 ADC 换算出的电压", "unit": "V",
                        "obtained_by": "breakrun + readmem 母线 ADC"},
    "vbus_expected_v": {"name": "用户填写的实际母线电压", "unit": "V",
                        "obtained_by": "F2 初始化配置时由用户录入"},
    "max_phase_error_deg": {"name": "三相输出相位互差与 120° 的最大偏差", "unit": "度",
                            "obtained_by": "示波器 CH2/CH3/CH4 三相输出相位测量"},
    "onoff_pass_count_lv": {"name": "最低运行电压下 ON/OFF 通过次数", "unit": "次",
                            "obtained_by": "ON-OFF LV 分页波形逐次判定"},
    "onoff_pass_count_sv": {"name": "额定运行电压下 ON/OFF 通过次数", "unit": "次",
                            "obtained_by": "ON-OFF SV 分页波形逐次判定"},
    "onoff_pass_count_hv": {"name": "最高运行电压下 ON/OFF 通过次数", "unit": "次",
                            "obtained_by": "ON-OFF HV 分页波形逐次判定"},
    "run_duration_min": {"name": "无异常连续运行时长", "unit": "min",
                         "obtained_by": "长跑计时 + fault 轮询"},
}

# criterion 表达式里允许出现的非变量根标识符
CRITERION_GLOBALS = ["Math", "true", "false", "null"]


def gen_test_requirements():
    XLSM = REPORT_XLSM
    CFSKILL = os.path.join(AITIOR, "dc-skills/coolingfan-openloop-debug/SKILL.md")
    items = [
        {
            "id": "TR-START-01", "name": "起动成功率（100 次启停回归）",
            "category": "启动可靠性",
            "evaluable": True,
            "criterion": "pass_count === required_pass && fault_flag === 0 "
                         "&& fg2_rpm_min_observed > fg2_rpm_min",
            "criterion_text": "默认 100 次启停（可配 1~1000 次），每次都要启动成功且无 fault，"
                              "转速证据取 FG2 > 10000 RPM",
            "variables": {
                "pass_count": vrt("pass_count", "启停回归通过次数", "次"),
                "required_pass": vth("required_pass", "要求通过次数", "次"),
                "fault_flag": vrt("fault_flag", "保护标志字整值"),
                "fg2_rpm_min_observed": vrt("fg2_rpm_min_observed",
                                            "全部回合 FG2 转速最小值", "RPM"),
                "fg2_rpm_min": vth("fg2_rpm_min", "FG2 转速下限判据", "RPM"),
            },
            "threshold": {"runs": 100, "runs_range": [1, 1000],
                          "required_pass": 100, "fg2_rpm_min": 10000},
            "evidence": ["FG2 红外机械转速", "fault 标志位"],
            "flows": ["F3 测试需求确认", "F4 启动测试及结果分析"],
            "_source": [src(os.path.join(AITIOR, "dc-skills/startstop-with-scope/SKILL.md"),
                            "frontmatter description 与执行规则"),
                        src(DOC_A, "第二节第 4 类「startstop-with-scope（默认 100 次可 1~1000，"
                                   "FG2>10000rpm 且无 fault）」")],
        },
        {
            "id": "TR-START-02", "name": "自动启动盲试（probe 3 次 + full 100 次）",
            "category": "启动可靠性",
            "evaluable": True,
            "criterion": "probe_pass === probe_runs && full_pass === required_full_pass",
            "criterion_text": "先 probe 3 次确认可重复，再跑 full 100 次要求 100/100；"
                              "10 个固定候选按序盲试，每个候选只偏离 baseline 一个轴，耗尽则 need_human",
            "variables": {
                "probe_pass": vrt("probe_pass", "probe 阶段通过次数", "次"),
                "probe_runs": vth("probe_runs", "probe 阶段要求次数", "次"),
                "full_pass": vrt("full_pass", "full 阶段通过次数", "次"),
                "required_full_pass": vth("required_full_pass", "full 阶段要求通过次数", "次"),
            },
            "threshold": {"probe_runs": 3, "full_runs": 100, "required_full_pass": 100,
                          "max_candidates": 10},
            "evidence": ["motor_startup_judge 原子双证据（FG2 红外转速 + 虚拟示波器 fault_flag 同窗采集）"],
            "flows": ["F4 启动测试及结果分析", "F5 调优确认及运行"],
            "_source": [src(os.path.join(AITIOR, "dc-skills/auto-startup-tune/SKILL.md"),
                            "「## 固定候选」与候选推进小节"),
                        src(DOC_A, "第二节第 4 类")],
        },
        {
            "id": "TR-SPEED-01", "name": "FG1 / FG2 转速一致性",
            "category": "转速一致性",
            "evaluable": True,
            "criterion": "Math.abs(fg1_freq_hz / fg2_freq_hz - ratio) <= tolerance",
            "criterion_text": "该电机极对数为 2，电气频率 = 极对数 × 机械频率，"
                              "所以 FG1 频率应等于 2 × FG2 频率；比值偏离 2.00 超过 ±0.05 即判异常",
            "variables": {
                "fg1_freq_hz": vrt("fg1_freq_hz", "FG1 频率", "Hz"),
                "fg2_freq_hz": vrt("fg2_freq_hz", "FG2 频率", "Hz"),
                "ratio": vth("ratio", "标称比值（= 极对数）"),
                "tolerance": vth("tolerance", "比值容差"),
            },
            "threshold": {"ratio": 2.00, "tolerance": 0.05,
                          "derived_from_pole_pairs": 2},
            "evidence": ["示波器 CH1→FG1、CH2→FG2 同窗频率"],
            "flows": ["F4 启动测试及结果分析"],
            "_source": [src(BENCH_MEMO, "「核心判据:FG1 频率 = 2 × FG2 频率」段"),
                        macro_src(CUSTOMER_H, "Pole_Pairs")],
            "note": "±0.05 的容差带是本场景包给前端演示设定的判定带宽；"
                    "台架记忆只写了「FG1≠2×FG2 即异常」，未给容差数值",
            "_placeholder": True,
        },
        {
            "id": "TR-SPEED-02", "name": "稳态转速偏差",
            "category": "转速精度",
            "evaluable": True,
            "criterion": "Math.abs(rpm_mean - target_rpm) / target_rpm <= tolerance_pct / 100",
            "criterion_text": "闭环稳态转速与目标转速的相对偏差不超过容限（缺省 5%）；"
                              "RPM = FREQ × 60 / 极对数，取 3 次测量均值",
            "variables": {
                "rpm_mean": vrt("rpm_mean", "稳态转速 3 次均值", "RPM"),
                "target_rpm": vrt("target_rpm",
                                  "本次测试目标转速；NONEMODE 下取 control-parameters.nonemode_speed",
                                  "RPM"),
                "tolerance_pct": vth("tolerance_pct", "相对偏差容限", "%"),
            },
            "threshold": {"tolerance_pct": 5, "tolerance_pct_default": 5,
                          "samples": 3, "sample_interval_s": 2},
            "evidence": ["rigol_measure FREQ ×3", "降级模式下用户回报转速表读数"],
            "flows": ["F3 测试需求确认", "F4 启动测试及结果分析"],
            "_source": [src(CFSKILL, "第 4 节 证据二 判据「转速准确度」"),
                        src(XLSM, "sheet 測試程式規格表 行 29-30「最大/最低轉速範圍 ± 5%」"),
                        src(XLSM, "sheet PWM·VSP 性能測試 A3「※ 通過條件：RPM 誤差 ≤ ±5%」")],
        },
        {
            "id": "TR-SPEED-03", "name": "稳态转速稳定性（无振荡）",
            "category": "转速精度",
            "evaluable": True,
            "criterion": "freq_range_over_mean_pct <= range_over_mean_pct "
                         "&& monotonic_drift_detected === false",
            "criterion_text": "3 次频率测量的极差 / 均值不超过 3%，且无单调漂移",
            "variables": {
                "freq_range_over_mean_pct": vrt("freq_range_over_mean_pct",
                                                "3 次频率极差 / 均值", "%"),
                "range_over_mean_pct": vth("range_over_mean_pct", "极差比上限", "%"),
                "monotonic_drift_detected": vrt("monotonic_drift_detected",
                                                "是否单调漂移（布尔）"),
            },
            "threshold": {"range_over_mean_pct": 3, "samples": 3},
            "evidence": ["rigol_measure FREQ ×3"],
            "flows": ["F4 启动测试及结果分析", "F5 调优确认及运行"],
            "_source": src(CFSKILL, "第 4 节 证据二 判据「转速稳定性」"),
        },
        {
            "id": "TR-SPEED-04", "name": "FG 与实际转速误差",
            "category": "转速一致性",
            "evaluable": True,
            "criterion": "Math.abs(rpm_fg - rpm_real) < max_error_rpm",
            "criterion_text": "FG 回报转速与实际转速之差小于 50 RPM",
            "variables": {
                "rpm_fg": vrt("rpm_fg", "FG 脉冲换算转速", "RPM"),
                "rpm_real": vrt("rpm_real", "红外测速机械真值", "RPM"),
                "max_error_rpm": vth("max_error_rpm", "误差上限", "RPM"),
            },
            "threshold": {"max_error_rpm": 50},
            "evidence": ["FG 脉冲频率", "红外测速机械真值"],
            "flows": ["F3 测试需求确认", "F4 启动测试及结果分析"],
            "_source": src(XLSM, "sheet 測試程式規格表 行 65「FG 與實際轉速誤差 | 小於 50 RPM」"),
        },
        {
            "id": "TR-TIME-01", "name": "启动到全速稳定时间",
            "category": "动态响应",
            "evaluable": True,
            "criterion": "t_start_to_steady_s < max_s",
            "criterion_text": "从启动到全速稳定的时间需小于 10 秒",
            "variables": {
                "t_start_to_steady_s": vrt("t_start_to_steady_s", "启动到全速稳定时间", "s"),
                "max_s": vth("max_s", "时间上限", "s"),
            },
            "threshold": {"max_s": 10},
            "evidence": ["rigol_waveform_analyze 的稳态起始时间"],
            "flows": ["F3 测试需求确认", "F4 启动测试及结果分析"],
            "_source": src(XLSM, "sheet 測試程式規格表 行 31"),
        },
        {
            "id": "TR-TIME-02", "name": "高转↔低转切换时间且不停转",
            "category": "动态响应",
            "evaluable": True,
            "criterion": "t_high_to_low_s < max_s && t_low_to_high_s < max_s && stalled === false",
            "criterion_text": "高转到低转需在 10 秒内完成且不能停转；低转到高转需在 10 秒内完成",
            "variables": {
                "t_high_to_low_s": vrt("t_high_to_low_s", "高转到低转切换时间", "s"),
                "t_low_to_high_s": vrt("t_low_to_high_s", "低转到高转切换时间", "s"),
                "max_s": vth("max_s", "切换时间上限", "s"),
                "stalled": vrt("stalled", "切换过程中是否停转（布尔）"),
            },
            "threshold": {"max_s": 10},
            "evidence": ["FG 转速时序", "PWM 占空比时序"],
            "flows": ["F3 测试需求确认", "F4 启动测试及结果分析"],
            "_source": src(XLSM, "sheet 測試程式規格表 行 32-33"),
        },
        {
            "id": "TR-CURR-01", "name": "启动母线峰值电流",
            "category": "电流",
            "evaluable": True,
            "criterion": "i_peak_a <= peak_over_steady_ratio_max * i_steady_a",
            "criterion_text": "启动到稳态转速过程中，母线峰值电流不可超过稳态电流的 1.1 倍",
            "variables": {
                "i_peak_a": vrt("i_peak_a", "启动过程母线峰值电流", "A"),
                "i_steady_a": vrt("i_steady_a", "稳态母线电流", "A"),
                "peak_over_steady_ratio_max": vth("peak_over_steady_ratio_max", "峰值/稳态比上限"),
            },
            "threshold": {"peak_over_steady_ratio_max": 1.1},
            # 1.1 这个比值在源模板里没有出处：規格表行 93 只写「峰值电流不可过大」，
            # 没给具体倍数，1.1 是本包早先按工程惯例填的，属占位，须向客户确认。
            "_placeholder": True,
            "note": "待客户确认：峰值/稳态比上限 1.1 倍在 report.xlsm 行 93 里没有写死，"
                    "是本场景包按工程惯例填的占位值，不得据此判不通过。"
                    "另注意本判据要的是母线电流，与本轮回放的 CH1 相电流不是同一个量。",
            "evidence": ["示波器母线电流通道"],
            "flows": ["F4 启动测试及结果分析"],
            "_source": src(XLSM, "sheet 測試程式規格表 行 93"),
        },
        {
            "id": "TR-PWM-01", "name": "PWM 调速曲线全档位验证",
            "category": "调速",
            "evaluable": True,
            "criterion": "max_abs_rpm_error_pct <= rpm_error_pct_max "
                         "&& max_overshoot_pct <= overshoot_pct_max "
                         "&& steady_current_over_limit_count === 0",
            "criterion_text": "PWM 占空比 0/10/20/…/100 共 11 档，每档记录目标转速、实际转速、"
                              "RPM 误差、最大电流、稳态电流、过冲、稳态上限、加速时间；"
                              "三条通过条件同时成立才判 PASS："
                              "RPM 误差 ≤ ±5%、过冲 ≤ 10%、稳态电流 ≤ 该档稳态上限",
            "variables": {
                "max_abs_rpm_error_pct": vrt("max_abs_rpm_error_pct",
                                             "11 档中 RPM 误差绝对值最大值", "%"),
                "rpm_error_pct_max": vth("rpm_error_pct_max", "RPM 误差上限", "%"),
                "max_overshoot_pct": vrt("max_overshoot_pct", "11 档中过冲最大值", "%"),
                "overshoot_pct_max": vth("overshoot_pct_max", "过冲上限", "%"),
                "steady_current_over_limit_count": vrt("steady_current_over_limit_count",
                                                       "稳态电流超上限的档位数", "档"),
            },
            "threshold": {"duty_points": [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
                          "rpm_error_pct_max": 5, "overshoot_pct_max": 10},
            "evidence": ["PWM·VSP 性能測試 分頁 Inlet / Outlet 两组数据"],
            "flows": ["F3 测试需求确认", "F4 启动测试及结果分析", "F6 测试报告及产出"],
            "_source": [src(XLSM, "sheet PWM·VSP 性能測試 A8:J8 表头、A9:A19 占空比档位"),
                        src(XLSM, "sheet PWM·VSP 性能測試 A3「※ 通過條件：RPM 誤差 ≤ ±5% | "
                                  "過衝 (%) ≤ 10% | 穩態電流 ≤ 穩態上限」"),
                        src(WRITEFILE_README, "「CSV 格式说明 · 列定义」8 列")],
            "note": "三条通过条件与 report-template.json 的 performance_table.pass_condition 数组一一对应。"
                    "过冲 ≤10% 与稳态电流 ≤ 稳态上限两条此前只写在 Excel 的 A3 单元格里，未进判据",
        },
        {
            "id": "TR-PWM-02", "name": "PWM 100% → 最低运行 Duty 不停转",
            "category": "调速",
            "evaluable": True,
            "criterion": "stall_count_lv === 0 && stall_count_sv === 0 && stall_count_hv === 0",
            "criterion_text": "PWM 从 100% 降到最低运行占空比，在高、中、低三档电压下都不能停转",
            "variables": {
                "stall_count_lv": vrt("stall_count_lv", "低压档停转次数", "次"),
                "stall_count_sv": vrt("stall_count_sv", "标准电压档停转次数", "次"),
                "stall_count_hv": vrt("stall_count_hv", "高压档停转次数", "次"),
            },
            "threshold": {"voltage_levels": ["LV", "SV", "HV"]},
            "evidence": ["FG 转速时序"],
            "flows": ["F4 启动测试及结果分析"],
            "_source": src(XLSM, "sheet 測試程式規格表 行 95"),
        },
        {
            "id": "TR-PWM-03", "name": "每 10% PWM 阶跃响应时间",
            "category": "调速",
            "evaluable": False,
            "not_evaluable_reason": "threshold.max_s 在模板里是空白待填项，表达式写得出来但求不出结果",
            "criterion": "t_step_s < max_s",
            "criterion_text": "每 10% 的 PWM 转速跳变（阶跃响应）时间需小于规定秒数",
            "variables": {
                "t_step_s": vrt("t_step_s", "单次 10% 阶跃的转速跳变时间", "s"),
                "max_s": vth("max_s", "阶跃时间上限（未定）", "s"),
            },
            "threshold": {"max_s": None},
            "evidence": ["FG 转速时序"],
            "flows": ["F3 测试需求确认"],
            "_source": src(XLSM, "sheet 測試程式規格表 行 94「時間需小於 _____ 秒」"),
            "_placeholder": True,
            "note": "模板里该阈值是空白待填项，源材料未给数值",
        },
        {
            "id": "TR-WIND-01", "name": "12 档顺风残速重启",
            "category": "顺逆风",
            "evaluable": True,
            "criterion": "gears_restarted === gears && fault_flag === 0",
            "criterion_text": "固定 12 档残速重启测试，断电到重启的间隔从 500 ms 扫到 6000 ms，"
                              "每档都要能重启成功，并区分真顺风与静止退化",
            "variables": {
                "gears_restarted": vrt("gears_restarted", "成功重启档数", "档"),
                "gears": vth("gears", "档数", "档"),
                "fault_flag": vrt("fault_flag", "保护标志字整值"),
            },
            "threshold": {"gears": 12, "interval_ms_min": 500, "interval_ms_max": 6000},
            "evidence": ["FG2 残速", "fault 标志"],
            "flows": ["F4 启动测试及结果分析"],
            "_source": [src(os.path.join(AITIOR, "dc-skills/tailwind-restart-test/SKILL.md"),
                            "frontmatter description"),
                        src(DOC_A, "第二节第 4 类「tailwind-restart-test（12 档 500~6000ms）」")],
        },
        {
            "id": "TR-WIND-02", "name": "顺逆风相电压/电流过冲",
            "category": "顺逆风",
            "evaluable": True,
            "criterion": "overshoot_peak_v <= max_normal_running_peak_v "
                         "&& overshoot_peak_a <= max_normal_running_peak_a",
            "criterion_text": "在中心操作电压下，顺风与逆风的相电压、相电流过冲须小于常态运行的最高值；"
                              "高、中、低速三档都要确认",
            "variables": {
                "overshoot_peak_v": vrt("overshoot_peak_v", "顺/逆风相电压过冲峰值", "V"),
                "max_normal_running_peak_v": vrt("max_normal_running_peak_v",
                                                 "常态运行相电压最高值", "V"),
                "overshoot_peak_a": vrt("overshoot_peak_a", "顺/逆风相电流过冲峰值", "A"),
                "max_normal_running_peak_a": vrt("max_normal_running_peak_a",
                                                 "常态运行相电流最高值", "A"),
            },
            "threshold": {"speed_gears": ["高速", "中速", "低速"]},
            "evidence": ["示波器相电压/相电流"],
            "flows": ["F4 启动测试及结果分析"],
            "_source": src(XLSM, "sheet 測試程式規格表 行 89-90"),
            "note": "判据要逐个速度档、逐个风向（顺风/逆风）各求值一次，"
                    "常态运行最高值须取同电压同转速工况的基线采集",
        },
        {
            "id": "TR-WIND-03", "name": "顺逆风强制退出",
            "category": "顺逆风",
            "evaluable": False,
            "not_evaluable_reason": "threshold.max_s 在模板里是空白待填项，表达式写得出来但求不出结果",
            "criterion": "t_windmilling_exit_s < max_s",
            "criterion_text": "程序顺逆风处理超时后必须有强制退出",
            "variables": {
                "t_windmilling_exit_s": vrt("t_windmilling_exit_s", "顺逆风强制退出耗时", "s"),
                "max_s": vth("max_s", "强制退出时限（未定）", "s"),
            },
            "threshold": {"max_s": None},
            "evidence": ["mcState 时序"],
            "flows": ["F3 测试需求确认", "F4 启动测试及结果分析"],
            "_source": src(XLSM, "sheet 測試程式規格表 行 91「_____ 秒」"),
            "_placeholder": True,
            "note": "模板里该阈值是空白待填项，源材料未给数值",
        },
        {
            "id": "TR-PROT-01", "name": "过压保护验证",
            "category": "保护",
            "evaluable": True,
            "criterion": "(fault_flag & FAULT_OVP) !== 0 "
                         "&& Math.abs(vbus_back_v - vbus_0_v) / vbus_0_v <= recheck_tolerance_pct / 100",
            "criterion_text": "把电源调到过压阈值 + 1 V，读 fault 应含 OVP 位；"
                              "随后必须调回原母线电压并复检，偏差超 5% 判定降级",
            "variables": {
                "fault_flag": vrt("fault_flag", "保护标志字整值"),
                "FAULT_OVP": vbit("0x0008", "过电压保护位"),
                "vbus_back_v": vrt("vbus_back_v", "调回后复检母线电压", "V"),
                "vbus_0_v": vrt("vbus_0_v", "改动前母线电压", "V"),
                "recheck_tolerance_pct": vth("recheck_tolerance_pct", "复检偏差容限", "%"),
            },
            "threshold": {"trigger_offset_v": 1.0, "ovp_thr_v": 18.0, "recheck_tolerance_pct": 5},
            "evidence": ["breakrun + readmem fault", "母线 ADC 复读"],
            "flows": ["F4 启动测试及结果分析"],
            "_source": [src(os.path.join(AITIOR, "dc-skills/protect-verify-ovp/SKILL.md"),
                            "执行流程第 1、2 节"),
                        macro_src(PROTECT_H, "PROTECTION_OV_PROTECT_THRESHOLD")],
            "note": "位运算已加括号：C/JS 里 & 的优先级低于 !==，"
                    "写成 fault_flag & FAULT_OVP !== 0 会先算比较再按位与，判据恒为 0",
        },
        {
            "id": "TR-PROT-02", "name": "欠压保护验证",
            "category": "保护",
            "evaluable": True,
            "criterion": "(fault_flag & FAULT_UVP) !== 0 "
                         "&& Math.abs(vbus_back_v - vbus_0_v) / vbus_0_v <= recheck_tolerance_pct / 100",
            "criterion_text": "把电源调到欠压阈值 − 1 V，读 fault 应含 UVP 位；随后调回并复检",
            "variables": {
                "fault_flag": vrt("fault_flag", "保护标志字整值"),
                "FAULT_UVP": vbit("0x0004", "欠电压保护位"),
                "vbus_back_v": vrt("vbus_back_v", "调回后复检母线电压", "V"),
                "vbus_0_v": vrt("vbus_0_v", "改动前母线电压", "V"),
                "recheck_tolerance_pct": vth("recheck_tolerance_pct", "复检偏差容限", "%"),
            },
            "threshold": {"trigger_offset_v": -1.0, "uvp_thr_v": 7.0, "recheck_tolerance_pct": 5},
            "evidence": ["breakrun + readmem fault", "母线 ADC 复读"],
            "flows": ["F4 启动测试及结果分析"],
            "_source": [src(os.path.join(AITIOR, "dc-skills/protect-verify-uvp/SKILL.md"),
                            "执行流程第 1、2 节"),
                        macro_src(PROTECT_H, "PROTECTION_UV_PROTECT_THRESHOLD")],
            "note": "位运算已加括号，理由同 TR-PROT-01",
        },
        {
            "id": "TR-PROT-03", "name": "低压告警 LVW 验证",
            "category": "保护",
            "evaluable": False,
            "not_evaluable_reason": "本工程 Protect.h 无 LVW 阈值宏，Motor_Protection.h 的 13 个 "
                                    "FAULT_* 位里也没有低压告警位，既无阈值也无可取的标志位，写不出表达式",
            "criterion": None,
            "criterion_text": "把电源调到低压告警阈值 − 0.5 V，读 warning（可能不在 fault 字段）应抬起；"
                              "阈值宏扫不到时由规程反问用户，不得瞎猜",
            "variables": {},
            "threshold": {"trigger_offset_v": -0.5, "lvw_thr_v": None,
                          "recheck_tolerance_pct": 5},
            "evidence": ["breakrun + readmem warning_flag", "母线 ADC 复读"],
            "flows": ["F4 启动测试及结果分析"],
            "_source": src(os.path.join(AITIOR, "dc-skills/protect-verify-lvw/SKILL.md"),
                           "第 0 节 阈值缺失分支"),
            "_placeholder": True,
            "note": "本散热风扇工程 Protect.h 无 LVW 阈值宏（已 grep 零命中），"
                    "该项来自吸尘器线规程，散热风扇是否有低压告警待客户确认",
        },
        {
            "id": "TR-PROT-04", "name": "堵转保护验证",
            "category": "保护",
            "evaluable": True,
            "criterion": "(fault_flag & FAULT_STALL_MASK) !== 0 && stall_trig_count >= trig_count",
            "criterion_text": "人为堵转后，堵转计数达 25 次触发堵转保护，6000 ms 后恢复",
            "variables": {
                "fault_flag": vrt("fault_flag", "保护标志字整值"),
                "FAULT_STALL_MASK": vmask(
                    "0xE0", ["0x0020", "0x0040", "0x0080"],
                    "堵转保护位掩码 = FAULT_STALL_METHOD_SPDES(0x0020) | "
                    "FAULT_STALL_METHOD_START(0x0040) | FAULT_STALL_METHOD_OFR(0x0080)。"
                    "头文件里的 FAULT_STALL_METHOD_UQOF(0x0060) 是 0x0020|0x0040 的复合常量，"
                    "不是独立位，已被本掩码覆盖，无须再单列"),
                "stall_trig_count": vrt("stall_trig_count", "堵转触发计数实测值", "次"),
                "trig_count": vth("trig_count", "堵转触发计数阈值", "次"),
            },
            "threshold": {"trig_count": 25, "recover_times_ms": 6000},
            "evidence": ["readmem fault", "FG 停止"],
            "flows": ["F4 启动测试及结果分析"],
            "_source": [macro_src(PROTECT_H, "PROTECTION_TRIG_COUNT_THRESHOLD"),
                        macro_src(PROTECT_H, "PROTECTION_STALL_RECOVER_TIMES"),
                        macro_src(MOTOR_PROT_H, "FAULT_STALL_METHOD_SPDES")],
            "note": "旧掩码写作 0x0020|0x0040|0x0060|0x0080，其中 0x0060 冗余；"
                    "改用 0xE0 并加括号，见 variables.FAULT_STALL_MASK 的说明",
        },
        {
            "id": "TR-PROT-05", "name": "超速保护验证",
            "category": "保护",
            "evaluable": False,
            "not_evaluable_reason": "本工程 Protect.h 无超速保护宏，13 个 FAULT_* 位里也没有超速位；"
                                    "该项还要求临时改分支压低阈值，属操作规程而非可求值判据",
            "criterion": None,
            "criterion_text": "在 protect-verify/* 临时分支上压低超速阈值使保护必然触发，"
                              "读 fault 判定保护链路生效；跑完必须 git reset + 重编重烧还原",
            "variables": {},
            "threshold": None,
            "evidence": ["breakrun + readmem fault"],
            "flows": ["F4 启动测试及结果分析"],
            "_source": src(os.path.join(AITIOR, "dc-skills/protect-verify-overspeed/SKILL.md"),
                           "全文执行流程"),
            "_placeholder": True,
            "note": "该规程针对吸尘器工程的 OVER_SPEED_EN 宏；"
                    "本散热风扇工程 Protect.h 无超速保护宏，适用性待确认",
        },
        {
            "id": "TR-PROT-06", "name": "启动失败保护验证",
            "category": "保护",
            "evaluable": False,
            "not_evaluable_reason": "Motor_Protection.h 的 13 个 FAULT_* 位里没有启动失败位，"
                                    "取不到可按位判定的标志；该项是「改宏造条件 + 强制还原」的操作规程",
            "criterion": None,
            "criterion_text": "临时改宏制造启动失败条件，读 fault 判定启动失败保护是否抬起；"
                              "跑完强制还原源码与 baseline 固件",
            "variables": {},
            "threshold": None,
            "evidence": ["breakrun + readmem fault"],
            "flows": ["F4 启动测试及结果分析"],
            "_source": src(os.path.join(AITIOR, "dc-skills/protect-verify-start-fail/SKILL.md"),
                           "frontmatter description"),
        },
        {
            "id": "TR-PROT-07", "name": "过流保护验证（硬过流 / 软过流）",
            "category": "保护",
            "evaluable": True,
            "criterion": "(fault_flag & FAULT_HW_OCP) !== 0 || (fault_flag & FAULT_SW_OCP) !== 0",
            "criterion_text": "硬过流走 DAC 比较来源，软过流阈值 10.0 A；两者择一或同测",
            "variables": {
                "fault_flag": vrt("fault_flag", "保护标志字整值"),
                "FAULT_HW_OCP": vbit("0x0001", "硬件过电流保护位"),
                "FAULT_SW_OCP": vbit("0x0002", "软件过电流保护位"),
            },
            "threshold": {"soft_threshold_a": 10.0, "hw_source": "DAC_SOURCE",
                          "recover_times_ms": 1500},
            "evidence": ["readmem fault", "示波器相电流"],
            "flows": ["F4 启动测试及结果分析"],
            "_source": [macro_src(PROTECT_H, "PROTECTION_OC_SOFT_THRESHOLD"),
                        src(XLSM, "sheet 測試程式規格表 行 83")],
            "note": "位运算已加括号，理由同 TR-PROT-01",
        },
        {
            "id": "TR-HW-01", "name": "母线电压检测自检（Vbus ±10%）",
            "category": "硬件自检",
            "evaluable": True,
            "criterion": "Math.abs(vbus_measured_v - vbus_expected_v) / vbus_expected_v "
                         "<= tolerance_pct / 100",
            "criterion_text": "读母线 ADC 换算电压，与用户填写的实际母线电压比对，偏差不超过 ±10%",
            "variables": {
                "vbus_measured_v": vrt("vbus_measured_v", "母线 ADC 换算电压", "V"),
                "vbus_expected_v": vrt("vbus_expected_v", "用户填写的实际母线电压", "V"),
                "tolerance_pct": vth("tolerance_pct", "偏差容限", "%"),
            },
            "threshold": {"tolerance_pct": 10},
            "evidence": ["breakrun + readmem 母线 ADC"],
            "flows": ["F2 初始化配置", "F4 启动测试及结果分析"],
            "_source": [src(os.path.join(AITIOR, "dc-skills/hw-selfcheck-vbus/SKILL.md"),
                            "frontmatter description 与判据小节"),
                        src(DOC_A, "第二节第 2 类「hw-selfcheck-vbus ±10%」")],
        },
        {
            "id": "TR-HW-02", "name": "三相输出自检（IPM 相位 ±5°）",
            "category": "硬件自检",
            "evaluable": True,
            "criterion": "max_phase_error_deg <= tolerance_deg",
            "criterion_text": "三相输出相位互差 120°，实测偏差不超过 ±5°",
            "variables": {
                "max_phase_error_deg": vrt("max_phase_error_deg", "相位互差与 120° 的最大偏差", "度"),
                "tolerance_deg": vth("tolerance_deg", "相位偏差容限", "度"),
            },
            "threshold": {"tolerance_deg": 5, "nominal_phase_deg": 120},
            "evidence": ["示波器 CH2/CH3/CH4 三相输出"],
            "flows": ["F2 初始化配置", "F4 启动测试及结果分析"],
            "_source": [src(os.path.join(AITIOR, "dc-skills/hw-selfcheck-ipm/SKILL.md"),
                            "frontmatter description 与判据小节"),
                        src(DOC_A, "第二节第 2 类「hw-selfcheck-ipm 相位±5°」")],
        },
        {
            "id": "TR-ONOFF-01", "name": "三档电压 ON/OFF 次数回归",
            "category": "可靠性",
            "evaluable": False,
            "not_evaluable_reason": "threshold.required_count 在模板原文即写「客戶需求待確認」，"
                                    "表达式写得出来但求不出结果",
            "criterion": "onoff_pass_count_lv === required_count "
                         "&& onoff_pass_count_sv === required_count "
                         "&& onoff_pass_count_hv === required_count",
            "criterion_text": "额定、最低、最高运行电压下各做规定次数的 ON/OFF 测试",
            "variables": {
                "onoff_pass_count_lv": vrt("onoff_pass_count_lv", "最低电压 ON/OFF 通过次数", "次"),
                "onoff_pass_count_sv": vrt("onoff_pass_count_sv", "额定电压 ON/OFF 通过次数", "次"),
                "onoff_pass_count_hv": vrt("onoff_pass_count_hv", "最高电压 ON/OFF 通过次数", "次"),
                "required_count": vth("required_count", "要求次数（未定）", "次"),
            },
            "threshold": {"voltage_levels": ["LV", "SV", "HV"], "required_count": None},
            "evidence": ["ON-OFF LV / ON-OFF SV / ON-OFF HV 三个分页的波形"],
            "flows": ["F3 测试需求确认", "F4 启动测试及结果分析", "F6 测试报告及产出"],
            "_source": [src(XLSM, "sheet 測試程式規格表 行 38-40「_____ 次 (客戶需求待確認)」"),
                        src(XLSM, "sheets ON-OFF LV / ON-OFF SV / ON-OFF HV")],
            "_placeholder": True,
            "note": "模板原文即写「客戶需求待確認」，次数未定",
        },
        {
            "id": "TR-RUN-01", "name": "最大工作电压下最低转速长跑 5 分钟",
            "category": "可靠性",
            "evaluable": True,
            "criterion": "run_duration_min >= duration_min && fault_flag === 0 && outer_loop_min >= 0",
            "criterion_text": "程序中速度外环最小值不能为负值；在最大工作电压下以最低转速运行 5 分钟无异常",
            "variables": {
                "run_duration_min": vrt("run_duration_min", "无异常连续运行时长", "min"),
                "duration_min": vth("duration_min", "要求运行时长", "min"),
                "fault_flag": vrt("fault_flag", "保护标志字整值"),
                "outer_loop_min": vcp("sout_min", "速度环 PID 幅值下限 SOUT_MIN", "A"),
            },
            "threshold": {"duration_min": 5},
            "evidence": ["fault 标志", "FG 转速时序"],
            "flows": ["F4 启动测试及结果分析"],
            "_source": src(XLSM, "sheet 測試程式規格表 行 96"),
        },
    ]
    obj = {
        "schema": "test-requirements/v1",
        "scene_id": SCENE_ID,
        "generated_by": GENERATED_BY,
        "generated_at": BUILD_DATE,
        "belongs_to_flow": "F3 测试需求确认（标准与判据来源）→ F4 启动测试及结果分析（执行与判定）",
        "categories": ["启动可靠性", "转速一致性", "转速精度", "动态响应", "电流",
                       "调速", "顺逆风", "保护", "硬件自检", "可靠性"],
        "criterion_syntax": "JavaScript 表达式（ECMAScript），求值结果为布尔",
        "criterion_expression_note": (
            "每条判据带三个配套字段："
            "evaluable 说明这条能不能真的求值；"
            "criterion 是 JS 语法的判据表达式，散文式、无标志位可取的条目为 null；"
            "variables 把表达式里每个自由变量映射到确定的取值来源。"
            "variables[].source 四种取值："
            "runtime.measure 指向 runtime_measures 登记表里的运行时测量量；"
            "threshold 指向本条自己的 threshold 字段；"
            "control-parameters 指向 control-parameters.json 的 parameters[].key；"
            "constant 是编译期常量，ref 或 derived_from 指向 safety-interlocks.json 的 fault_bitmap。"
            "evaluable 为 false 时 not_evaluable_reason 写明卡在哪。"
            "位运算一律加括号：C/JS 里 & 的优先级低于比较运算符。"),
        "criterion_globals": CRITERION_GLOBALS,
        "runtime_measures": RUNTIME_MEASURES,
        "evaluable_count": sum(1 for it in items if it["evaluable"]),
        "not_evaluable_count": sum(1 for it in items if not it["evaluable"]),
        "requirements": items,
    }
    return dump("test-requirements.json", obj)
