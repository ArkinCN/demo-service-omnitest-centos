# -*- coding: utf-8 -*-
"""合成三条示例时序波形。

**这些数据是合成的，不是实测。** 汽车低压执行器电机（雨刮、车窗、天窗、座椅、EPS、
节气门）的专用公开波形数据集，在十三个数据平台上确认为空白（素材综述文档 B 第 286 行、
第 466 行与第 9.3 节）。因此本场景包的时序数据只能走参数化仿真这一路。

模型：一阶有刷直流电机电气-机械耦合模型，与 gym-electric-motor（德国帕德博恩大学
电驱动系统教研室，MIT 许可，https://github.com/upb-lea/gym-electric-motor）所用的
直流电机模型同型，但本文件不引入该依赖，直接用显式欧拉积分实现，便于审阅每一行。

    L di/dt = U·duty − R·i − Ke·ω
    J dω/dt = Kt·i − B·ω − T_load
    dx/dt   = k_arm·ω                        （旋转 → 玻璃托架直线位移）
    F_out   = Kt·i·η / k_arm_m               （输出力，η 为蜗杆传动机械效率）

参数标定口径：电气参数取到让稳态量落在 QC/T 626-2019 征求意见稿给的量级上——
堵转电流 U/R ≈ 26 A（低于 5.4.1 b) 的 28 A 上限）、上升速度约 120 mm/s（落在 5.4.1 d) 的
80~160 mm/s 区间中部）、堵转力约 240 N（高于 5.4.1 c) 的 212 N 下限）。
**这是「让示例数据看起来合理」的标定，不是任何真实产品的参数辨识结果。**

采样：内部按 20 kHz 积分，箱式平均降采样到 2000 Sa/s 输出，24000 行 = 12.0 s。
降采样等效于一阶抗混叠，因此输出里的换向纹波已被大幅衰减——
2 kHz 只够看电流包络，不够做纹波计数测速（纹波基频在本模型下约 600~700 Hz）。
"""
import csv
import math
import os

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "assets/waveforms")

# ---- 模型参数（标定依据见模块 docstring）----
U_BUS = 13.5          # V，试验电压 13.5 ± 0.3 V（QC/T 626 征求意见稿 6.1 b)）
R_ARM = 0.52          # Ω，电枢电阻，标定到 U/R ≈ 26 A，叠加纹波后峰值仍低于 28 A 上限
L_ARM = 0.80e-3       # H，电枢电感
KE = 0.020            # V·s/rad
KT = 0.020            # N·m/A
J_ROT = 2.0e-5        # kg·m²
B_VIS = 2.0e-6        # N·m·s/rad
K_ARM_MM = 0.226      # mm/rad，减速与绳轮折算
K_ARM_M = K_ARM_MM * 1e-3
ETA = 0.105           # 蜗杆传动机械效率，标定到堵转力约 240 N
RIPPLE_PER_REV = 8    # 每转换向纹波数 = 2N
RIPPLE_DEPTH = 0.06   # 纹波深度（占电流的比例）

F_STATIC_UP = 55.0    # N，上升时的额定负载：玻璃重量 + 胶条滑动阻力
F_STATIC_DOWN = -15.0  # N，下降时：玻璃重量 − 胶条滑动阻力，方向助力
TRAVEL_MM = 420.0     # mm，玻璃托架总行程（示例值）
ROD_STIFFNESS = 10.0  # N/mm，GB 11552-2009 §4.8.3.1.3 测量工具刚度 (10 ± 0.5) N/mm

FS_INT = 20000.0      # Hz，内部积分频率
DECIM = 10            # 降采样倍数 → 输出 2000 Sa/s
N_OUT = 24000         # 输出行数 → 12.0 s

COLUMNS = [
    ("time_s", "时间（秒，t=0 为控制器收到上升指令的时刻）"),
    ("current_a", "电枢电流（安培，正值为上升方向）"),
    ("bus_voltage_v", "母线电压（伏特）"),
    ("position_mm", "玻璃托架位置（毫米，0 为下止点，420 为上止点）"),
    ("opening_mm", "开口量（毫米，= 420 − position_mm，法规 4~200 mm 判据用的就是这个量）"),
    ("speed_mm_s", "托架线速度（毫米/秒，正值为上升）"),
    ("force_n", "电机输出力（牛顿，由电流与传动效率换算；回缩瞬间的制动涌流会让它短暂冲高）"),
    ("pinch_force_n", "夹持力（牛顿，= 试验棒刚度 10 N/mm × 侵入量；非防夹工况恒为 0）"),
    ("ripple_pulse", "换向纹波过零脉冲（0/1，2 kHz 下已严重欠采样，仅作示意）"),
    ("phase", "工况标记"),
]


def _simulate(profile):
    """按 profile 给的分段指令积分。profile(t, x, v) 返回 (duty, f_ext, phase)。"""
    dt = 1.0 / FS_INT
    n_int = N_OUT * DECIM
    i = 0.0
    w = 0.0
    x = 0.0
    theta = 0.0
    buf = []
    rows = []
    for k in range(n_int):
        t = k * dt
        ret = profile(t, x, w * K_ARM_MM)
        duty, f_ext, phase = ret[0], ret[1], ret[2]
        f_pinch = ret[3] if len(ret) > 3 else 0.0
        # 电气回路
        u = U_BUS * duty
        di = (u - R_ARM * i - KE * w) / L_ARM
        i += di * dt
        # 机械回路：外力折算到轴上的负载转矩
        t_load = f_ext * K_ARM_M / ETA if ETA > 0 else 0.0
        dw = (KT * i - B_VIS * w - t_load) / J_ROT
        w += dw * dt
        # 机械止点：下止点与上止点都不允许越过
        x += w * K_ARM_MM * dt
        if x <= 0.0:
            x = 0.0
            if w < 0:
                w = 0.0
        if x >= TRAVEL_MM:
            x = TRAVEL_MM
            if w > 0:
                w = 0.0
        theta += w * dt
        # 换向纹波：叠加在电流上，频率正比于转速
        ripple = 1.0 + RIPPLE_DEPTH * math.sin(theta * RIPPLE_PER_REV)
        i_meas = i * ripple
        buf.append((t, i_meas, x, w * K_ARM_MM, phase, theta, f_pinch))
        if len(buf) == DECIM:
            # 箱式平均降采样（等效一阶抗混叠）
            t0 = buf[0][0]
            ia = sum(b[1] for b in buf) / DECIM
            xa = sum(b[2] for b in buf) / DECIM
            va = sum(b[3] for b in buf) / DECIM
            ph = buf[-1][4]
            th = buf[-1][5]
            fp = max(b[6] for b in buf)
            f_out = KT * abs(ia) * ETA / K_ARM_M
            pulse = 1 if int(th * RIPPLE_PER_REV / math.pi) % 2 == 0 else 0
            rows.append({
                "time_s": round(t0, 6),
                "current_a": round(ia, 4),
                "bus_voltage_v": round(U_BUS, 3),
                "position_mm": round(xa, 3),
                "opening_mm": round(TRAVEL_MM - xa, 3),
                "speed_mm_s": round(va, 3),
                "force_n": round(f_out, 2),
                "pinch_force_n": round(fp, 2),
                "ripple_pulse": pulse,
                "phase": ph,
            })
            buf = []
    return rows[:N_OUT]


# ---------------- 三条工况 ----------------

def _profile_normal(t, x, v):
    """正常升降：怠速 → 上升 → 上止点堵转 1 s → 停 4 s → 下降 → 停。
    时间轴照 QC/T 626 征求意见稿 6.9.1 注 3 的耐久单循环波形排（上止点堵转 1 s 停 4 s）。"""
    if t < 0.5:
        return 0.0, 0.0, "IDLE"
    if t < 4.0:
        return 1.0, F_STATIC_UP, "UP"
    if t < 5.0:
        return 1.0, F_STATIC_UP, "STALL_TOP_1S"      # 上止点堵转 1 s
    if t < 9.0:
        return 0.0, 0.0, "DWELL_OFF_4S"              # 断电停 4 s
    if t < 11.6:
        return -1.0, F_STATIC_DOWN, "DOWN"
    return 0.0, 0.0, "IDLE_END"


def _profile_antipinch(t, x, v):
    """防夹触发：上升途中在开口 170 mm 处遇障，试验棒刚度 10 N/mm，
    电流突增 → 判据触发 → 回缩 60 mm。"""
    x_obs = TRAVEL_MM - 170.0          # 开口 170 mm 对应的托架位置，落在 4~200 mm 法规区间内
    x_detect = x_obs + 3.2             # 检出点：本模型下此处力约 32 N，远低于 100 N 硬顶
    x_retract_target = x_obs - 60.0    # 回缩 60 mm（法规底线 50 mm，本包留裕量）
    if t < 0.5:
        return 0.0, 0.0, "IDLE"
    # 记忆式状态机：用位置而不是时间判相，避免回缩后又被判成上升
    if not hasattr(_profile_antipinch, "_st"):
        _profile_antipinch._st = "UP"
        _profile_antipinch._t_det = None
    st = _profile_antipinch._st
    f_pinch = ROD_STIFFNESS * max(0.0, x - x_obs)   # 试验棒反力 = 刚度 × 侵入量
    f_ext = F_STATIC_UP + f_pinch
    if st == "UP":
        if x >= x_detect:
            _profile_antipinch._st = "RETRACT"
            _profile_antipinch._t_det = t
            return 0.0, f_ext, "PINCH_DETECTED", f_pinch
        return 1.0, f_ext, ("UP" if x < x_obs else "PINCH_CONTACT"), f_pinch
    if st == "RETRACT":
        # 检出后 50 ms 内标 PINCH_DETECTED，便于前端把「判据触发」这一刻标出来
        ph = "PINCH_DETECTED" if (t - _profile_antipinch._t_det) < 0.05 else "RETRACT"
        if x <= x_retract_target:
            _profile_antipinch._st = "DONE"
            return 0.0, 0.0, "RETRACT_DONE", 0.0
        return -1.0, (F_STATIC_DOWN - f_pinch), ph, f_pinch
    return 0.0, 0.0, "RETRACT_DONE", 0.0


def _profile_stall(t, x, v):
    """堵转电流饱和：上升到上止点后持续加压，电流爬升到 U/R 的饱和平台。
    本条刻意不启用堵转保护，目的是录出完整的饱和平台，
    用来标定 control-parameters.json 的 stall_current_threshold。"""
    if t < 0.5:
        return 0.0, 0.0, "IDLE"
    if t < 4.2:
        return 1.0, F_STATIC_UP, "UP"
    if t < 9.5:
        return 1.0, F_STATIC_UP, "STALL_SATURATED"   # 上止点持续堵转，无保护
    return 0.0, 0.0, "POWER_CUT"


PROFILES = [
    ("normal-up-down-cycle.csv", _profile_normal,
     "正常升降电流曲线（上升 → 上止点堵转 1 s → 停 4 s → 下降）"),
    ("antipinch-trigger.csv", _profile_antipinch,
     "防夹触发电流突增（开口 170 mm 处遇障，试验棒刚度 10 N/mm，检出后回缩 60 mm）"),
    ("stall-saturation.csv", _profile_stall,
     "堵转电流饱和平台（上止点持续堵转，刻意关闭堵转保护以录出完整平台）"),
]


def build():
    os.makedirs(OUT_DIR, exist_ok=True)
    out = []
    for fname, prof, title in PROFILES:
        for attr in ("_st", "_t_det"):
            if hasattr(prof, attr):
                delattr(prof, attr)
        rows = _simulate(prof)
        path = os.path.join(OUT_DIR, fname)
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[c[0] for c in COLUMNS])
            w.writeheader()
            w.writerows(rows)
        stats = {
            "file": path,
            "title": title,
            "rows": len(rows),
            "size": os.path.getsize(path),
            "i_max": max(r["current_a"] for r in rows),
            "i_min": min(r["current_a"] for r in rows),
            "v_max": max(r["speed_mm_s"] for r in rows),
            "v_min": min(r["speed_mm_s"] for r in rows),
            "f_max": max(r["force_n"] for r in rows),
            "fp_max": max(r["pinch_force_n"] for r in rows),
            "x_max": max(r["position_mm"] for r in rows),
            "phases": sorted({r["phase"] for r in rows}),
        }
        out.append(stats)
    return out


if __name__ == "__main__":
    for s in build():
        print("%-28s %6d 行 %9d 字节  Imax=%.2f A  Vmax=%.1f mm/s  Fmax=%.0f N  Fpinch=%.1f N  Xmax=%.0f mm"
              % (os.path.basename(s["file"]), s["rows"], s["size"], s["i_max"],
                 s["v_max"], s["f_max"], s["fp_max"], s["x_max"]))
        print("    工况标记：%s" % " / ".join(s["phases"]))
