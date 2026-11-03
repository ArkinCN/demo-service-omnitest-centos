"""CH4 测速通道现场探测脚本（2026-10-09 新增，长期保留的现场工具）。

为什么需要：acceptance.json 的 scope.tach 九项全是 null/false，enabled=false，
所以趋势图上的「转速 (rpm)」恒为「未采集」；而 runtime.py 在 enabled=true 时
**强制**要求 7 个数字字段 + 2 个人工确认位，缺一即抛 ConfigError、启动同步失败。
这些值只能是现场量出来的 —— 本脚本就是那把尺。

纪律（不可逾越）：
- 不自动置 wiringConfirmed / physicalProbeRatioConfirmed（人工确认项，脚本无权放行）
- 默认只打印、不写文件；加 --apply 才回填 acceptance.json
- 量到什么报什么：采不到周期性脉冲就明确报「未采到有效转速脉冲」，不硬填、不开采集
- 探头倍率是**推定**：第 1 遍用 ×1 读原始显示幅度，再按 NPN 开路+上拉时
  「高电平应接近供电电压」推定倍率，raw 与 true 两个值都打印，不把推定当实测

用法：
  cd d:/Task4/OmniTest/hardware
  python py/probe_tach.py            # 只探测并打印（默认）
  python py/probe_tach.py --apply    # 探测通过时回填配置（enabled 仍保持 false）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runtime  # noqa: E402
import scope_capture  # noqa: E402
from fan_serial import IDENTITY, FanSession, SerialWire  # noqa: E402
from scope_visa import ScopeDevice  # noqa: E402

DEFAULT_DUTIES = (30, 50, 70, 100)
HOLD_S = 10.0
PROBE_TIMEBASE_S_PER_DIV = 0.02   # 200ms 窗口；1800rpm 周期 33ms，够 3 个周期
PROBE_POINTS = 1200              # 与 config 的 waveformPoints 同值：超出会读回 0 点
MIN_AMPLITUDE_V = 0.2            # 折算幅度下限：低于此=噪声量级
MIN_RISING_RPM = 50.0            # 相邻档最小上升幅度，用来区分趋势与噪声

# 现场控制台可能是 GBK（中文 Windows 默认），打印特殊符号会抛 UnicodeEncodeError。
# 切 UTF-8 + 无法编码时降级，保证诊断脚本在任何环境都跑得完、如实报完。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 - 旧解释器没有 reconfigure，忽略
    pass
OK_MARK = "[OK]"
NG_MARK = "[NG]"


def fmt(v, d=3):
    return "—" if v is None else f"{v:.{d}f}"


def read_ch4(scope, probe):
    """在 CH4 采一段窗口，返回实测指标。推算复用 scope_capture.get_wave_metrics（与联合实验同口径）。"""
    scale = float(probe["scaleVoltsPerDiv"])
    scope.write(":STOP")
    scope.write(":WAVeform:MODE NORM")
    scope.write(":WAVeform:FORMat BYTE")
    # 必须显式开 CH4 的 DISPlay：联合实验的 initialize_scope 会把「不在 active 列表里」
    # 的通道一律 DISPlay OFF（当前 active 只有 1/2/3），所以进到本脚本时 CH4 是关着的
    # —— 波形源指向一个关闭的通道会**读回 0 点**（实测踩过：4 档全部 0 点）。
    scope.write(":CHANnel4:DISPlay ON")
    scope.write(":CHANnel4:COUPling DC")
    scope.write(":CHANnel4:UNIT VOLT")
    scope.write(f":CHANnel4:PROBe {probe['probeRatio']}")
    scope.write(f":CHANnel4:SCALe {scale}")
    scope.write(":CHANnel4:OFFSet 0")
    if scope.query(":CHANnel4:DISPlay?") != "1":
        raise RuntimeError("CH4 未能打开（:CHANnel4:DISPlay? 读回非 1）")
    scope.write(f":TIMebase:MAIN:SCALe {PROBE_TIMEBASE_S_PER_DIV}")
    scope.write(":TRIGger:MODE EDGE")
    scope.write(":TRIGger:EDGE:SOURce CHAN4")
    scope.write(f":TRIGger:EDGE:LEVel {probe['triggerLevelV']}")
    scope.write(":TRIGger:SWEep AUTO")
    scope.write(":RUN")
    time.sleep(0.3)
    scope.write(":STOP")
    scope.write(":WAVeform:SOURce CHANnel4")
    scope.write(f":WAVeform:POINts {PROBE_POINTS}")
    f = scope.query(":WAVeform:PREamble?").split(",")
    if len(f) != 10:
        raise RuntimeError("Invalid waveform preamble.")
    inc, y_inc, y_origin, y_ref = float(f[4]), float(f[7]), float(f[8]), float(f[9])
    raw = scope.query_binary_values(":WAVeform:DATA?")
    if len(raw) < 8:
        # 0 点的两个常见成因：① CH4 关着（已在上方 DISPlay ON + 读回校验兜住）；
        # ② 请求点数超过面板上限（DS1100Z 在 NORM 下按屏幕点数截断，超限返回空块）。
        raise RuntimeError(
            f"读回 {len(raw)} 个点（请求 {PROBE_POINTS}）。"
            f"若 CH4 已确认打开，则多为请求点数超过面板上限 —— "
            f"用 :WAVeform:POINts? 读回设备实际支持值后调小 PROBE_POINTS。"
        )
    values = [(float(b) - y_ref) * y_inc + y_origin for b in raw]
    m = scope_capture.get_wave_metrics(values, inc, True)
    m["clipped"] = m["maximumV"] >= 4 * scale * 0.99 or m["minimumV"] <= -4 * scale * 0.99
    if m["clipped"]:
        m["frequencyHz"] = None
        m["edgeStatus"] = "display_clipped_invalid_frequency"
    m["points"] = len(raw)
    m["windowS"] = round((len(raw) - 1) * inc, 4)
    return m


def judge(rows):
    """判定是否采到有效转速脉冲：幅度量级 + 随占空比的单调性（PPR=1 的线性自洽）。"""
    reasons = []
    if not rows:
        return False, ["四档全部采集失败"], "[NG] 未采到有效转速脉冲"
    good = [r for r in rows if (r.get("ampV") or 0) >= MIN_AMPLITUDE_V]
    if not good:
        peak = max((r.get("ampV") or 0) for r in rows)
        return False, [f"折算幅度峰值仅 {peak:.3f}V < {MIN_AMPLITUDE_V}V（噪声量级）",
                       "NPN 集电极开路需上拉：确认是否装上拉电阻，或用万用表量 CH4 空闲电平"], \
               "[NG] 未采到有效转速脉冲"
    reasons.append(f"折算幅度 ≥ {MIN_AMPLITUDE_V}V 的档位：{[r['duty'] for r in good]}")
    rpm_rows = [r for r in rows if r.get("rpm") is not None]
    if len(rpm_rows) < 3:
        return False, reasons + [f"只有 {len(rpm_rows)} 档算出转速（需 ≥3），多半是噪声跳变"], \
               "[NG] 未采到有效转速脉冲"
    rising = sum(1 for i in range(1, len(rpm_rows))
                 if rpm_rows[i]["rpm"] - rpm_rows[i - 1]["rpm"] >= MIN_RISING_RPM)
    need = len(rpm_rows) - 1
    detail = "、".join(f"{r['duty']}%={r['rpm']:.0f}" for r in rpm_rows)
    if rising < need:
        return False, reasons + [f"转速未随占空比单调上升（{need} 对里只满足 {rising} 对）：{detail}",
                                 "→ 采到的可能不是转速脉冲（PWM 串扰 / 悬空噪声 / 反光条未装好）"], \
               "[NG] 采到的不是有效转速信号"
    reasons.append(f"转速随占空比单调上升：{detail}")
    return True, reasons, "[OK] 采到有效转速脉冲（PPR=1 线性自洽）"


def candidate(rows, ratio, true_high):
    """按实测值算候选 tach 配置（**不含**两个人工确认位）。"""
    scale = 2.0 if true_high <= 16 else 5.0
    return {
        "enabled": False,   # 探测脚本不擅自开
        "channel": 4,
        "supplyVoltageV": None,        # 示波器测不到 —— 需你按传感器铭牌填（范围 12~24V）
        "outputVoltageV": round(true_high, 2),
        "probeRatio": ratio,
        "scaleVoltsPerDiv": scale,
        "triggerLevelV": round(max(0.5, true_high * 0.5), 2),
        "timebaseSecondsPerDiv": PROBE_TIMEBASE_S_PER_DIV,
        "pulsesPerRevolution": 1,      # 用户现场事实：只贴一条反光条 → 每转 1 脉冲
    }


def apply_config(path, tach_patch):
    """把候选值回填 acceptance.json 的 scope.tach（保留未测字段与人工确认位）。"""
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    old = cfg["scope"].get("tach", {})
    for k, v in tach_patch.items():
        if v is not None:
            old[k] = v
    old["_probe_note"] = ("2026-10-09 由 probe_tach.py 实测回填：outputVoltageV / probeRatio / "
                          "scaleVoltsPerDiv / triggerLevelV / timebaseSecondsPerDiv / "
                          "pulsesPerRevolution。supplyVoltageV 需按铭牌人工填；"
                          "wiringConfirmed 与 physicalProbeRatioConfirmed 仍为 false，"
                          "人工核实后方可置 true 并把 enabled 置 true。")
    cfg["scope"]["tach"] = old
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def emit_probe_config(main_path, ov_path):
    """生成 acceptance.probe.json：合并 overlay + 开 tach，供**真实实验代码**采集。

    为什么需要这一步：手写探针的 SCPI 序列在 CH3（PWM，已知可读）上也读回 0 点，
    说明问题在序列而非通道。与其继续猜 SCPI，不如走**已被真机验证过**的
    run_experiment.py / scope_capture.py 路径，让它自己去采、采到什么报什么。

    本副本的 tach 数值是**探测用猜测值**（倍率/量程/触发电平均未实测），
    只用于试一次看采不采得到脉冲；**不回写 acceptance.json**。
    """
    with open(main_path, encoding="utf-8") as fh:
        base = json.load(fh)
    if ov_path and os.path.isfile(ov_path):
        with open(ov_path, encoding="utf-8") as fh:
            ov = json.load(fh)
        base["serial"]["port"] = ov["serial"]["port"]
        base["scope"]["resource"] = ov["scope"]["resource"]
        if "waveformPoints" in ov.get("scope", {}):
            base["scope"]["waveformPoints"] = ov["scope"]["waveformPoints"]
    base["scope"]["tach"].update({
        "enabled": True, "supplyVoltageV": 12, "outputVoltageV": 5,
        "probeRatio": 10, "scaleVoltsPerDiv": 2, "triggerLevelV": 2.5,
        "pulsesPerRevolution": 1,
        # 人工确认位：仅在这份一次性副本里置 true，否则 runtime.py 会拒绝启动。
        # 正式配置 acceptance.json 不会被本脚本触碰。
        "wiringConfirmed": True, "physicalProbeRatioConfirmed": True,
    })
    out = os.path.join(os.path.dirname(main_path), "acceptance.probe.json")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(base, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    loaded = runtime.read_experiment_config(out, allow_overlay=False)
    print("OK ->", out)
    print("   port    =", loaded.config["serial"]["port"])
    print("   resource=", loaded.config["scope"]["resource"])
    print("   tach.on =", loaded.config["scope"]["tach"]["enabled"])
    return out


def main():
    ap = argparse.ArgumentParser(description="探测 CH4 测速通道，输出候选配置（默认不写文件）")
    ap.add_argument("--apply", action="store_true", help="探测通过时把候选值回填 acceptance.json")
    ap.add_argument("--emit-probe-config", action="store_true", help="只生成 acceptance.probe.json 后退出")
    ap.add_argument("--config", default=None)
    ap.add_argument("--duties", default=",".join(str(d) for d in DEFAULT_DUTIES))
    ap.add_argument("--hold", type=float, default=HOLD_S)
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    cfg_path = args.config or os.path.join(here, "..", "v0.6", "config", "acceptance.json")
    duties = [int(x) for x in args.duties.split(",") if x.strip()]

    loaded = runtime.read_experiment_config(cfg_path)
    cfg = loaded.config
    scfg, scfg_ser = cfg["scope"], cfg["serial"]
    t0 = scfg.get("tach", {})
    if args.emit_probe_config:
        emit_probe_config(
            os.path.abspath(cfg_path),
            os.path.join(os.path.dirname(os.path.abspath(cfg_path)), "acceptance.windows.json"),
        )
        return 0

    print("=" * 72)
    print("CH4 测速通道探测（现场实测，不编数据）")
    print("=" * 72)
    print(f"配置    : {loaded.path}")
    print(f"串口    : {scfg_ser['port']} @ {scfg_ser['baud']}")
    print(f"当前 tach: enabled={t0.get('enabled')} PPR={t0.get('pulsesPerRevolution')}")
    print(f"待测档位: {duties}（每档 {args.hold}s）")
    print()

    try:
        wire = SerialWire(scfg_ser["port"], scfg_ser["baud"])
        session = FanSession(wire)
        session.identify()
        print(f"[串口] 已识别 {IDENTITY}")
    except Exception as e:  # noqa: BLE001 - 现场诊断如实报因
        print(f"[串口] [NG] 失败：{type(e).__name__}: {e}")
        print("       → 确认 UNO 已刷 uno_fan.ino、CH340 驱动在位、端口号与配置一致。")
        return 2

    try:
        scope = ScopeDevice(scfg.get("resource") or "", scfg.get("expectedIdentity"))
        print(f"[示波器] {scope.query('*IDN?')}")
        print(f"[示波器] 资源 {scope.resource} · 后端 {scope.backend}")
    except Exception as e:  # noqa: BLE001
        print(f"[示波器] [NG] 失败：{type(e).__name__}: {e}")
        print("       → 确认已开机、USB 为 IVI Foundation USBTMC 驱动，或设 FAN_SCOPE_RESOURCE。")
        try:
            session.command("SET 0")
            wire.close()
        except Exception:  # noqa: BLE001
            pass
        return 3

    probe = {"probeRatio": 1, "scaleVoltsPerDiv": 2.0, "triggerLevelV": 1.0}
    rows = []
    try:
        print("\n--- ① 原始幅度（probeRatio=1，未折算）---")
        raw_high = None
        for duty in duties:
            session.command(f"SET {duty}")
            time.sleep(args.hold)
            try:
                m = read_ch4(scope, probe)
            except Exception as e:  # noqa: BLE001
                print(f"  占空比 {duty:3d}%  采集失败：{type(e).__name__}: {e}")
                rows.append({"duty": duty})
                continue
            rows.append({"duty": duty, "rawHighV": m["maximumV"], "rawLowV": m["minimumV"],
                         "rawFreqHz": m["frequencyHz"], "clipped": m["clipped"],
                         "edgeStatus": m["edgeStatus"], "points": m["points"], "windowS": m["windowS"]})
            r = rows[-1]
            if raw_high is None and r["rawHighV"] is not None:
                raw_high = r["rawHighV"]
            print(f"  占空比 {duty:3d}%  高 {_fmt(r['rawHighV'])}V 低 {_fmt(r['rawLowV'])}V "
                  f"幅度 {_fmt(r['rawHighV'] - r['rawLowV'])}V 频率 {_fmt(r['rawFreqHz'], 2)}Hz "
                  f"削波={r['clipped']} 边沿={r['edgeStatus']} 点数={r['points']} 窗口={r['windowS']}s")

        ratio = 10 if (raw_high is not None and raw_high < 3.0) else 1
        true_high = (raw_high or 0.0) * ratio
        print("\n--- ② 折算与判定（倍率按物理事实推定，非实测）---")
        print(f"  原始高电平 {fmt(raw_high)}V → 推定 probeRatio=×{ratio}"
              f"（依据：NPN 开路+上拉时高电平应接近供电电压）")
        probe["probeRatio"] = ratio
        probe["triggerLevelV"] = max(0.5, true_high * 0.5)
        good = [r for r in rows if "rawHighV" in r]
        for r in good:
            r["trueHighV"] = r["rawHighV"] * ratio
            r["ampV"] = (r["rawHighV"] - r["rawLowV"]) * ratio
            r["rpm"] = None if r["rawFreqHz"] is None else round(60.0 * r["rawFreqHz"], 1)
            print(f"  占空比 {r['duty']:3d}%  折算高电平 {fmt(r['trueHighV'])}V "
                  f"幅度 {fmt(r['ampV'])}V  折算转速(PPR=1) {fmt(r['rpm'], 1)} RPM")

        ok, reasons, verdict = judge(good)
        print(f"\n  信号有效性：{verdict}")
        for line in reasons:
            print(f"    - {line}")

        cand = candidate(good, ratio, true_high)
        print("\n--- ③ 候选配置（**不含** wiringConfirmed / physicalProbeRatioConfirmed）---")
        print(json.dumps(cand, ensure_ascii=False, indent=2))
        print("\n需你人工确认后自行填入：")
        print(f"  supplyVoltageV             = ?  （传感器供电，范围 12~24V，示波器测不到，按铭牌填）")
        print(f"  wiringConfirmed            = ?  （{t0.get('signalWire')}）")
        print(f"  physicalProbeRatioConfirmed= ?  （倍率 {ratio} 是推定，建议用万用表点测 CH4 空闲电平复核）")
        print(f"  enabled                    = ?  （上面两项都 true 之后才能置 true）")

        if args.apply:
            if not ok:
                print("\n探测未通过：**不写任何文件、不开 enabled**（按纪律如实停在报告）")
                return 4
            apply_config(loaded.path, cand)
            print(f"\n已按实测值回填 {loaded.path}（enabled 保持 false，待人工确认后由你置 true）")
        return 0
    finally:
        try:
            session.command("SET 0")
            print("\n[收尾] 已发 SET 0，风扇归零")
        except Exception as e:  # noqa: BLE001
            print(f"\n[收尾] [NG] SET 0 失败：{type(e).__name__}: {e}（风扇状态未知，请手动断电确认）")
        for closer in (lambda: scope.dispose(), lambda: wire.close()):
            try:
                closer()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    raise SystemExit(main())
