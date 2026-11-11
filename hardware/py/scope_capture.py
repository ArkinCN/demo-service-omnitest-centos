"""示波器采集与波形推算（Python 重写，对应原 src/ScopeCapture.psm1）。

逐条复刻原 SCPI 命令序列、preamble 解析、波形推算算法、CSV/BMP 导出与 capture.json 结构。
算法口径**严格对齐**（频率/占空比/RPM/削波/25kHz 频带/电流换算），不美化不降级。
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any

from scope_visa import ScopeDevice, VisaError, block_payload


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num(v: float) -> str:
    """数值格式化：对齐原 Number()（往返最短表示）。"""
    return repr(float(v))


# ---------------------------------------------------------------------------
# 通道 / 触发 / 初始化
# ---------------------------------------------------------------------------
def _set_channel(scope: ScopeDevice, channel: int, settings: dict) -> dict:
    scope.write(f":CHANnel{channel}:DISPlay ON")
    scope.write(f":CHANnel{channel}:COUPling DC")
    scope.write(f":CHANnel{channel}:UNIT VOLT")
    scope.write(f":CHANnel{channel}:PROBe {_num(settings['probeRatio'])}")
    scope.write(f":CHANnel{channel}:SCALe {_num(settings['scaleVoltsPerDiv'])}")
    scope.write(f":CHANnel{channel}:OFFSet {_num(settings['offsetV'])}")

    if (scope.query(f":CHANnel{channel}:COUPling?") != "DC"
            or scope.query(f":CHANnel{channel}:UNIT?") != "VOLT"
            or scope.query(f":CHANnel{channel}:DISPlay?") != "1"):
        raise VisaError(f"readback mismatch: CH{channel}")

    return {
        "channel": channel,
        "probeRatio": _check_num(scope, f":CHANnel{channel}:PROBe?", settings["probeRatio"]),
        "scaleVoltsPerDiv": _check_num(scope, f":CHANnel{channel}:SCALe?", settings["scaleVoltsPerDiv"]),
        "offsetV": _check_num(scope, f":CHANnel{channel}:OFFSet?", settings["offsetV"]),
        "coupling": "DC",
        "unit": "VOLT",
        "physicalProbeRatioConfirmed": settings["physicalProbeRatioConfirmed"],
    }


def _read_num(scope: ScopeDevice, command: str) -> float:
    n = float(scope.query(command))
    if math.isnan(n) or math.isinf(n):
        raise VisaError(f"Non-finite readback: {command}")
    return n


def _check_num(scope: ScopeDevice, command: str, expected: float) -> float:
    actual = _read_num(scope, command)
    if abs(actual - expected) > max(1e-9, abs(expected) * 1e-5):
        raise VisaError(f"Scope readback mismatch: {command} expected {expected} got {actual}")
    return actual


# 错误队列响应的**有效形状**：`<code>,<message>`，如 `0,"No error"` / `-113,"..."`。
# 只有先匹配这个形状，内容才可信；否则一律按「响应错位」处理（见 _assert_no_scope_error）。
ERR_RESP_SHAPE = re.compile(r"^\s*(-?\d+)\s*,")

# 脏响应重查的最大轮数。DS1104Z 在高速切源/切时基后偶发把上一次查询的**尾部**
# 留在输出缓冲里（实测返回 `=@ @` 这类乱码，既不是 "0,..." 也不是超时），
# 清空缓冲再查一次即可拿到真响应；连查 3 轮仍脏才判定为真故障。
ERR_RECHECK_ROUNDS = 3


def _hexdump(text: str) -> str:
    """把原始响应转成可被日志/终端安全承载的形式（乱码时十进制不可读）。

    终端代码页会把非 ASCII 字节渲染成 `锟?` 之类，等于丢失定位信息；
    这里同时给 backslash-escape 与 hex，两者都能反推出原始字节。
    """
    raw = text.encode("utf-8", errors="backslashreplace")
    escaped = text.encode("unicode_escape").decode("ascii", errors="replace")
    hexed = raw[:64].hex(" ")
    return f"{escaped!r} (hex: {hexed})"


def _drain_input_buffer(inst: Any) -> None:
    """按极短超时把输入缓冲读空，丢弃错位残留的脏字节。

    ⚠️ 刻意**不用 `*CLS`**（会清掉真实错误队列，等于掩盖故障）、
    也**不用 `inst.clear()`**（部分后端会连带复位采集配置）。
    只读不写，不改变设备状态。
    """
    original = inst.timeout
    try:
        inst.timeout = 80
        while True:
            try:
                if not inst.read_raw(64):
                    break
            except Exception:  # noqa: BLE001 - 无数据可读即缓冲已空
                break
    finally:
        inst.timeout = original


def _clear_scope_error_queue(scope: ScopeDevice, max_rounds: int = 60) -> int:
    """轮次开始前把示波器错误队列读空，返回清掉的条数。

    为什么需要（2026-10-11 修）：
      DS1104Z 的错误队列是**设备级持久状态**，跨采集轮次存活，容量约 30 条。
      上一轮遗留的错误（尤其是人为调试时塞进去的非法命令，如 `-113 Undefined header`）
      会被下一轮的 `_assert_no_scope_error` 读到，于是新一轮刚开始就报
      「Scope configuration error: -113」，而本轮其实一条命令都没发错。

      本函数只做「读」——读 `:SYSTem:ERRor?` 本身就会弹出一条队列项，
      连续读到 `0,"No error"` 即视为清空。不下发 `*CLS`，因此**不影响本轮**
      真实产生的错误（那类仍会被 `_assert_no_scope_error` 如实抛出）。

    幂等；队列本就为空时立即返回。

    ⚠️ 超时必须收紧（2026-10-11 修，第二个性能坑）：
      设备刚被 USB 复位 / 刚打开会话后的**首次** `:SYSTem:ERRor?` 会一直阻塞到
      `inst.timeout` 才返回（实测正好 15.00s = `scope_visa.ScopeDevice` 的默认 timeout）。
      于是 `initialize_scope` 一进来就先白等 15 秒 —— 这是「点启动后很久才出数据」
      的**头号原因**（实测初始化总耗时 20.4s，其中 15s 全耗在这一条命令上）。
      而设备稳定后清队列本身只要 0.02 秒（实测）。

      故：把读取超时压到 700ms。超时即视为「队列为空 / 设备尚未就绪」，直接结束；
      随后的 `initialize_scope` 正文（`*IDN?` 与配通道）本身就会与设备完成握手，
      届时队列状态自然稳定，真正的错误仍会被 `_assert_no_scope_error` 如实抛出。
    """
    inst = getattr(scope, "_inst", None)
    original = getattr(inst, "timeout", None) if inst is not None else None
    try:
        if inst is not None:
            inst.timeout = 1200
        cleared = 0
        zeros = 0
        # ⚠️ 2026-10-12 重写（关键修复）：**遇到 -350 或超时必须继续读，不能 break**。
        #
        # 实测数据（连读 35 次，本机 @ivi 后端）：
        #   #1-3 超时 → #4 -350 → #5-6 超时 → #7 -350 → **#8 `0,"No error"`**
        #   → 之后 28 次全部正常。
        # 结论：`-350 Queue overflow` **可以纯软件清空**，只是要连续读到第 8 次左右；
        # 期间交替出现的「超时」与「-350」都是**正常中间态**，不是终点。
        #
        # 这推翻了两个此前的错误假设（旧代码因此永远清不掉 -350）：
        #   ① 遇 -350 就 break（误以为「队列锁死、只能物理拔插」）；
        #   ② 遇超时就 break（误以为「超时=队列空」）→ 实际第 1 次就退出了。
        #
        # 现在：只有**连续两次**读到 `0,"No error"` 才判清空（单次 0 可能是抖动）；
        # 其余一律继续读，最多 max_rounds 次。
        # 超时压到 1200ms：实测有效读取仅需 1ms，超时那几次是设备在吐错误，
        # 短超时可避免 60 次读里白等 6 秒×N。
        for _ in range(max_rounds):
            try:
                err = (scope.query(":SYSTem:ERRor?") or "").strip()
            except Exception:  # noqa: BLE001 - 中间态超时，继续读
                zeros = 0
                continue
            if err.startswith("0,"):
                zeros += 1
                if zeros >= 2:
                    break
                continue
            zeros = 0
            cleared += 1
        return cleared
    finally:
        if inst is not None and original is not None:
            try:
                inst.timeout = original
            except Exception:  # noqa: BLE001
                pass


def _assert_no_scope_error(scope: ScopeDevice, timeout_ms: int = 1500) -> None:
    """检查示波器错误队列；**空队列阻塞按「无错误」、脏响应按「响应错位」处理**。

    为什么需要这层包装（2026-10-09 修）：本台 DS1104Z（固件 00.04.05.SP2）的
    `:SYSTem:ERRor?` 在**错误队列为空时不返回 "0,No error"，而是不响应**
    （NI-VISA 后端下表现为 `VI_ERROR_TMO`）。原实现直接断言 `startswith("0,")`，
    于是**每一档采集都在这一步超时**、整轮 failed：
    实测连续三次实验（含 tach 关闭、改动前的配置）全部挂在
    `Read :SYSTem:ERRor? failed: VI_ERROR_TMO (-1073807339)`，
    而同一条会话下 `*IDN?` / `:TIMebase:MAIN:SCALe?` / `:CHANnel3:DISPlay?`
    全部正常 —— 证明不是 USB 或资源名问题，就是这条命令的阻塞行为。

    2026-10-09 二次修（脏响应）：错误队列回读还出现过**内容乱码**，
    消息形如 `Scope configuration error: =@ @` / `L;...` / `锟?锟紷`。
    该类返回**既不匹配 `0,` 前缀、也不是超时**，被原逻辑判为真错误 →
    整轮 failed。时间线（run `aa87fd70f11b49e8be130e1abfd53da6`）：
    10:44:51 pwm 档完成 → 10:44:55 tach 档完成（rpm 710）→ 10:45:04 报错，
    正是 tach 采完后 `finally: _set_capture_profile(scope, cfg, "pwm")`
    **切回时基**那一刻 —— 属查询响应错位（上一次读的尾巴留在缓冲里），
    不是设备真错误。

    处置口径（保留真报错通路，不放弃错误检测）：
      · 把超时临时收紧到 1.5s（默认 15s 太长，空队列时白等 15 秒×每档）；
      · 超时 → 视为「队列为空 = 无错误」，静默通过；
      · 读到内容 → **先按 `ERR_RESP_SHAPE` 校验形状**：
          - 形状合法且 code == 0 → 无错误，通过；
          - 形状合法且 code != 0 → **真错误，原样抛出**（如实报错）；
          - 形状非法（乱码）→ 按响应错位处理：读空输入缓冲 → 短暂等待 → 重查，
            最多 `ERR_RECHECK_ROUNDS` 轮；仍非法才抛错，并把原始字节以
            backslash-escape + hex 打印（现有消息无法定位）。
    """
    inst = getattr(scope, "_inst", None)
    if inst is None:  # 非标准实现（测试替身）→ 退回原行为（无缓冲可清，不做重查）
        err = scope.query(":SYSTem:ERRor?")
        if not ERR_RESP_SHAPE.match(err or ""):
            raise VisaError(f"Scope configuration error: {_hexdump(err or '')}")
        if not err.startswith("0,"):
            raise VisaError(f"Scope configuration error: {err}")
        return

    original = inst.timeout
    last_bad = ""
    try:
        inst.timeout = timeout_ms
        for _ in range(ERR_RECHECK_ROUNDS):
            try:
                err = scope.query(":SYSTem:ERRor?")
            except Exception as e:  # noqa: BLE001 - 超时即队列空，按无错误处理
                msg = str(e)
                if "VI_ERROR_TMO" in msg or "Timeout" in msg:
                    return
                raise
            if not err:
                return
            m = ERR_RESP_SHAPE.match(err)
            if m:
                if m.group(1).lstrip("-").strip("0") == "":  # code == 0
                    return
                # 形状合法且非零 → 真实设备错误，如实抛出（不做重查，避免掩盖故障）
                raise VisaError(f"Scope configuration error: {err}")
            # 形状非法 = 响应错位：清缓冲、等一拍、重查
            last_bad = err
            _drain_input_buffer(inst)
            time.sleep(0.08)
    finally:
        inst.timeout = original
    raise VisaError(
        f"Scope configuration error: 连续 {ERR_RECHECK_ROUNDS} 次回读均非合法响应码，"
        f"最后一次原始返回 {_hexdump(last_bad)}"
    )


def _set_capture_profile(scope: ScopeDevice, cfg: dict, profile: str) -> None:
    if profile == "pwm":
        source = cfg["channels"]["pwm"]["channel"]
        timebase = cfg["pwmTimebaseSecondsPerDiv"]
        level = cfg["triggerLevelV"]
    else:
        timebase = cfg["tach"]["timebaseSecondsPerDiv"]
        # ⚠️ 触发源可配置（2026-10-12 增）：转速通道信号弱时，**用它自己触发会永远
        #   等不到触发点** —— 实测本机 CH4 信号峰值仅 0.12~0.16V，而触发电平配的 0.9V，
        #   边沿条件永不满足 → 整个 tach 档 0 点（`no_trigger_signal`）。
        #   把触发源指向**始终有信号的 PWM 通道**即可：波形数据与被测通道无关，
        #   照样能把 CH4 采下来（实测 4/4 全成功、每次 1200 点）。
        #   配置写法：tach.triggerSource = "pwm"（用 pwm 通道的源与电平）
        #                             或 <1..4> 的整数（用该通道，电平仍取 tach.triggerLevelV）
        #                             缺省 = 原行为（用 tach 自己的通道）。
        trig = cfg["tach"].get("triggerSource")
        if trig == "pwm":
            source = cfg["channels"]["pwm"]["channel"]
            level = cfg["triggerLevelV"]
        elif isinstance(trig, int):
            source = trig
            level = cfg["tach"]["triggerLevelV"]
        else:
            source = cfg["tach"]["channel"]
            level = cfg["tach"]["triggerLevelV"]
    scope.write(f":TIMebase:MAIN:SCALe {_num(timebase)}")
    scope.write(":TRIGger:MODE EDGE")
    scope.write(f":TRIGger:EDGE:SOURce CHANnel{source}")
    scope.write(f":TRIGger:EDGE:LEVel {_num(level)}")
    scope.write(":TRIGger:SWEep AUTO")
    _check_num(scope, ":TIMebase:MAIN:SCALe?", timebase)
    if scope.query(":TRIGger:EDGE:SOURce?") != f"CHAN{source}":
        raise VisaError("Trigger source readback mismatch.")
    _check_num(scope, ":TRIGger:EDGE:LEVel?", level)
    _assert_no_scope_error(scope)


def initialize_scope(scope: ScopeDevice, cfg: dict) -> dict:
    """识别身份 → 配通道 → 配触发 → RUN；返回 settings（写 scope-settings.json）。"""
    # 先清空上一轮遗留的错误队列，再做本轮的身份校验与配置。
    # 不清的话：上轮（或人工调试）留下的 -113 等错误会被本轮的
    # _assert_no_scope_error 当成本轮故障抛出，导致「一条命令都没发错也整轮失败」。
    stale = _clear_scope_error_queue(scope)
    if stale:
        print(f"[scope] 清空上一轮遗留错误 {stale} 条")

    ident = scope.query("*IDN?")
    if ident != cfg["expectedIdentity"]:
        raise VisaError(f"Unvalidated scope identity: {ident}")
    import re
    if not re.match(r"^RIGOL TECHNOLOGIES,DS1104Z Plus,DS1ZC[0-9]+,", ident):
        raise VisaError(f"Unvalidated scope identity: {ident}")

    settings: dict[str, Any] = {
        "identity": ident,
        "inputImpedanceOhm": 1000000,
        "channels": {},
        "configuredUtc": _now(),
        "timebaseSecondsPerDiv": cfg["pwmTimebaseSecondsPerDiv"],
    }
    active: list[int] = []
    for role in ("current", "voltage", "pwm"):
        ch = cfg["channels"][role]
        settings["channels"][role] = _set_channel(scope, int(ch["channel"]), ch)
        active.append(int(ch["channel"]))

    if cfg.get("tach", {}).get("enabled"):
        t = cfg["tach"]
        pseudo = {
            "probeRatio": t["probeRatio"],
            "scaleVoltsPerDiv": t["scaleVoltsPerDiv"],
            "offsetV": 0,
            "physicalProbeRatioConfirmed": t["physicalProbeRatioConfirmed"],
        }
        settings["channels"]["tach"] = _set_channel(scope, int(t["channel"]), pseudo)
        active.append(int(t["channel"]))

    for ch in (1, 2, 3, 4):
        if ch not in active:
            scope.write(f":CHANnel{ch}:DISPlay OFF")
            if scope.query(f":CHANnel{ch}:DISPlay?") != "0":
                raise VisaError("Inactive channel not disabled.")

    _set_capture_profile(scope, cfg, "pwm")
    scope.write(":RUN")
    return settings


# ---------------------------------------------------------------------------
# 波形推算（严格对齐原 Get-WaveMetrics）
# ---------------------------------------------------------------------------
# 转速脉冲「同包络」合并窗口（秒）。
#
# 实测依据（2026-10-09，probe_ch4_007）：一次转动在示波器上会呈现 2 个子尖峰，
# 子尖峰间隔 6~14ms；而转动周期为 70~85ms（30% 档）到 28ms（100% 档）。
# 取 12ms 能把多数子尖峰并成一个脉冲事件，又小于最小转动周期（28ms）的一半以上，
# 不会把相邻两次转动并到一起。用**时间**而非采样点数：本台架 0.02/0.05 s/div
# 两档采样间隔分别是 200µs/500µs，按点数写死会在另一档失效。
PULSE_MERGE_S = 0.012

# 脉冲阈值相对幅度（占「基线到最小值」的比例）与噪声底倍数（稳健标准差）。
#
# thr = 基线 - max(0.35*幅度, min(3*稳健σ, 0.6*幅度))：
#   · 有真脉冲时：0.35*幅度 落在纹波带以下、脉冲深处以上（实测取到约 -0.9V，
#     而基线纹波约 ±0.5V、脉冲最深处约 -2.7V）；
#   · 纯噪声时：幅度≈噪声峰峰 → 0.35*幅度 小于 3σ → 退化为 3σ 门限，
#     跨过的点极少，由「脉冲数 ≥ 4」的校验如实拒绝，不会把噪声算成转速；
#   · 上限 min(..., 0.6*幅度)：防止「双极性方波」这类信号的 MAD 偏大
#     （一半样本离中位数很远）把门限推到信号范围之外（离线回归实测的 bug）。
PULSE_LEVEL_FRACTION = 0.35
PULSE_NOISE_SIGMA = 3.0
PULSE_NOISE_CLAMP_FRACTION = 0.6

# 最少脉冲数（合并后）与周期一致性上限。
#
# ⚠️ 一致性用「**每个**间隔都必须落在中位周期 ±25% 内」而不是「MAD/中位 ≤ 20%」：
# 后者只要求「多数间隔接近」，随机点偶尔会蒙混过关——离线压力测试（60 随机种子 ×
# 5 档噪声 × 打乱/尖刺噪声 = 420 例负样本）中，MAD 判据误报 49~56 例，本判据 0 例；
# 同一批条件下正样本（四档真实采集）两者都是全对，故采用更严的本判据。
# ⚠️ PULSE_MIN_COUNT 现仅用于「低于阈值的**原始点数**下限」（下方 below 检查）：
# 那一步只是挡退化的空/近恒定波形，2 个点足够表达「有下穿结构」。
PULSE_MIN_COUNT = 2
# 合并后的**事件数**下限（2026-10-12 增，3）。
# 为什么不是 2：2 个事件 = 1 个间隔 = 没有重复证据。实测（1000 例 5 族噪声离线：
# 高斯/漂移/打乱真实/尖刺/小幅）中，「2 个相距 ~55ms 的随机事件」频繁凑出
# 「一致性通过」的假周期（55~60ms ≈ 整窗，自相关在那种滞后上只剩几毫秒重叠、
# 数值不可靠）——修复 span 后若门槛为 2，噪声误报率高达 68%。
# 3 个事件 = 2 个独立间隔才构成「重复了至少一次」的证据。
# ⚠️ 2026-10-12 晚（时基回 50ms/div、600ms 窗）后：正常运行最低档
# （30%·周期 ~81ms）在窗内也有 **7 个**事件，本下限只作为兜底。
PULSE_MIN_EVENTS = 3
# 周期性（自相关）校验下限（2026-10-12 增）。
# 对「合并后事件数 < 6」的检出，要求**在候选周期处存在真实的自相关峰**，
# 否则视为噪声凑出的假周期，如实拒发（edgeStatus=weak_periodicity）。
# 为什么需要：小脉冲数下幅度/间隔类校验统计强度不足——离线 1000 例噪声中
# 「count>=3 且现有校验通过」者 167 例，加本校验后误报 0 例（那 167 例的 r
# 最大仅 0.341）；本机真实信号 r=0.93~0.99，余量巨大。为什么 count>=6 豁免：
# 深脉冲型信号（如历史 probe_ch4_008、21 个脉冲）的自相关在周期处天然接近 0
# （脉冲占空比低），但其 ≥5 个间隔的一致性本身已是强证据，维持放行
# （回归：probe_ch4_008 仍输出 2182rpm）。600ms 窗下真实数据事件数 ≥7，
# 本校验基本只在极端情况兜底。
PULSE_PERIODICITY_MIN = 0.5

# ===== 「2 事件」（单间隔）分支判据（2026-10-12 增）=====
#
# 历史背景：该分支为 **60ms 短窗时代** 设计（当时 tach 受 5ms/div 限制）。
# 时基回 50ms/div（600ms 窗）后正常运行不再需要它（最低档 30% 也有 7 个事件），
# 故现在**仅短窗（≤PULSE_TWO_EVENT_MAX_WINDOW_S）启用**——长窗下「恰好 2 个
# 事件」只可能是转速低于 ~200rpm（超出台架工作域）或信号异常，一律如实拒。
#
# 原 60ms 窗时代的判据（短窗仍按此执行）：为恰好 2 个事件开一条严格通道，
# 用形态与周期性证据弥补统计强度的不足——
#   ① 间隔在 [10ms, 0.85×窗] 内——上界挡「整窗假周期」（自相关滞后接近窗长时
#      重叠区过小、数值不可靠）；
#   ② 候选周期处自相关 r ≥ 0.80——实测真信号 0.80~0.88，噪声 2 事件案例的 r
#      几乎不超 0.5；
#   ③ 凹陷宽度 / 周期 ≤ PULSE_DEPRESSION_WIDTH_FRACTION_MAX——反射条角宽是
#      物理常量（实测本机真实脉冲宽/周期 0.02~0.20），正弦干扰的"谷"宽/周期
#      ≈ 0.29 更大，被此闸挡下；
#   ④ 幅度/合并等前置条件沿用主路径。
PULSE_TWO_EVENT_MIN_S = 0.010
PULSE_TWO_EVENT_WINDOW_FRACTION = 0.85
PULSE_TWO_EVENT_MIN_R = 0.80
#: 2 事件分支的窗口上限（秒）：超过此窗不再启用该分支（见上方说明）。
PULSE_TWO_EVENT_MAX_WINDOW_S = 0.12
#: 凹陷宽度/周期 上限（2026-10-12 复核后收紧 0.30 → 0.22）。
#: 物理依据：真实转速脉冲的「凹陷宽/周期」反映反光条角宽——本机实测：现役采集
#: （四档 500µs 采样）0.02~0.08；历史深脉冲（Windows 时代、500µs）0.18~0.20。
#: 而 50Hz 市电干扰（探头线拾取）的"谷宽/周期"约 0.29~0.30——纯正弦同样"周期性"，
#: 仅靠间隔一致性区分不开（离线 500 例纯 50Hz 有 478 例能通过其余全部校验）。
#: 本守卫把这条误报路径关掉：离线 3000 例噪声（6 族）误报 481 → 17（0.57%）。
#: 0.22 的取值：对历史深脉冲（0.20）留 10% 余量，对 50Hz（0.29+）封门。
PULSE_DEPRESSION_WIDTH_FRACTION_MAX = 0.22
PULSE_PERIOD_TOLERANCE = 0.25


def get_tach_pulse_metrics(values: list[float], increment: float) -> dict:
    """转速（tach）脉冲定周期：稳健阈值找脉冲包络 → 取间隔中位数 → 一致性校验。

    为什么不能沿用 get_wave_metrics 的「数穿越点」判法（2026-10-09 实测依据）：
      · CH4 基线上叠着约 ±0.5V 的 PWM 串扰纹波，而 (最小值+最大值)/2 这条水平线
        正好落在纹波带里 → 产生几十个假穿越（实测 30% 档出现 33~123 个上升沿，
        而真实脉冲只有 7~21 个）；
      · 每次转动会呈现 2 个子尖峰（实测间隔 7~14ms），一个真实脉冲被数成多次。
      两者叠加使周期一致性校验必然失败（edgeStatus=unstable_periods），
      而同一批数据里真实周期其实高度规整（实测 100% 档 21 个间隔全为 28.0ms）。

    判法（对「纹波 + 多尖峰」信号稳健，且不依赖探头倍率等绝对幅值）：
      1. 基线 base = 中位数；稳健离散 mad = 1.4826 * MAD；
         幅度 span = base - **平滑序列**最小值（2026-10-12 修：原用原始序列最小值，
         与检测信号不同源，小信号下阈值被单点噪声尖峰推穿 → 恒 0 脉冲）；
      2. 阈值 thr = base - max(PULSE_LEVEL_FRACTION*span,
                               min(PULSE_NOISE_SIGMA*mad, PULSE_NOISE_CLAMP_FRACTION*span))；
      3. 低于 thr 且彼此间隔 ≤ PULSE_MERGE_S 的采样合并为同一「脉冲包络」，
         取包络内最小点作为脉冲中心（一次转动的多个子尖峰 → 一个事件）；
      4. 间隔 = 相邻脉冲中心之差（秒）；先取中位数 period0，再把比 0.5*period0
         更近的中心合并一次（处理个别跨包络的漏合并，保留更深的点），重算中位周期；
      5. 通过条件（全部满足才给数字，否则如实报未采集并写明原因）：
           · 合并后事件数 ≥ 2（<2 无间隔可谈，如实拒）；
           · **每个**间隔都落在中位周期 ±PULSE_PERIOD_TOLERANCE(25%) 内
             （2026-10-12 恢复严格口径，配 600ms 窗，见下方主路径注释）；
           · 中位周期 ≥ 20 个采样点（低于此说明时间分辨不足以可信定位尖峰）；
           · 凹陷宽度/周期 ≤ PULSE_DEPRESSION_WIDTH_FRACTION_MAX(0.22)
             （2026-10-12 增：挡「纯 50Hz 市电干扰」的宽谷假周期）；
           · 事件数 ≥ 3 且 < 6 时，还要求候选周期处自相关 ≥ PULSE_PERIODICITY_MIN(0.5)；
           · 事件数 == 2 时（仅短窗 ≤120ms 启用；长窗直接如实拒）：
             走**严格分支**——间隔 ∈ [10ms, 0.85×窗] 且 自相关 ≥ 0.80
             且 凹陷宽/周期 ≤ 0.22（判据校准见 PULSE_TWO_EVENT_* 注释）；
      6. frequencyHz = 1/中位周期；转速由调用方按 PPR 换算（rpm = 60*f/PPR）。

    离线回归（2026-10-09，`_tmp_test_tach.py` / `_tmp_stress.py`，只读历史 CSV 与合成信号）：
      · 正样本——probe_ch4_007（10×、1V/div、0.05 s/div）：30%/50%/70%/100% →
        710/1200/1633/2143 rpm，单调上升且同档重复性一致；
        probe_ch4_005/006/07654f（0.02 s/div、240ms 窗）：50%/70%/100% →
        1215/1648/2162~2174 rpm（与人工逐个定位尖峰的结果一致）。
      · 窗口不足者如实拒绝：0.02 s/div 下 30% 档窗内只有 2~3 个脉冲 →
        报脉冲数不足（不做「用 2 个间隔硬算」的将就）。
      · 负样本 420 例（60 随机种子 × 5 档高斯噪声 + 真实波形打乱 + 尖刺噪声）：
        **零误报**；恒定值与缓慢漂移同样不给数字。
      · 2026-10-12 复验（本机现役信号，5ms/div 60ms 窗）：正样本——现行真实采集
        12 次 + 现场单独探测 9 组，全部检出（周期 ≈20ms、自相关 r=0.93~0.99、
        3 个事件）；负样本 1000 例（高斯/漂移/打乱/尖刺/小幅 5 族）在
        「事件数≥3 + 自相关校验」下**零误报**；历史大信号回归 probe_ch4_008
        仍输出 21 个脉冲 → 2182rpm（对历史口径 2142.9 同档）。

    ⚠️ dutyPercent 有意不设：该脉冲宽度是「反光条角宽」，不是 PWM 占空比，
    写进去会被下游误读成占空比。
    """
    n = len(values)
    total = 0.0
    sq = 0.0
    mn = float("inf")
    mx = float("-inf")
    for v in values:
        total += v
        sq += v * v
        mn = min(mn, v)
        mx = max(mx, v)
    metric: dict[str, Any] = {
        "points": n,
        "sampleIntervalS": increment,
        "windowS": (n - 1) * increment,
        "minimumV": mn,
        "maximumV": mx,
        "meanV": total / n,
        "rmsV": math.sqrt(sq / n),
        "frequencyHz": None,
        "dutyPercent": None,
        "edgeStatus": "insufficient_amplitude_or_edges",
        "pulseCount": 0,
        "medianPeriodS": None,
    }
    if n < 40:
        return metric

    # ⚠️ 2026-10-12 增：**检测前先做移动平均平滑**。
    #   根因（实测本机 CH4）：信号是「带噪声的方波」—— 1ms 尺度包络清晰
    #   （周期 ~20ms、幅度 ~0.1V），但逐点噪声达 ±0.05V。直接拿原始点做阈值检测，
    #   低于阈值的点碎成 **182 个零散短段**（每段仅 1~2 点），经 12ms 合并窗口后
    #   只剩 1 个「脉冲」→ 转速恒为 None。
    #   平滑后（1ms 窗）同样的数据得到 **2 个清晰的长段（9.2ms / 8.9ms）**，
    #   间隔 10.85ms → 周期 ≈20ms → 转速 ≈3000rpm，与 70% 档工况相符。
    #   窗口取 1ms：对 20ms 周期只引入 ±0.5ms 边沿误差（2.5% 精度），可接受。
    #   ⚠️ 平滑仅用于**脉冲定位**；minimumV/maximumV/meanV 等仍用原始值，不改测量数据。
    _win = max(3, int(round(0.001 / increment))) if increment > 0 else 3
    if _win >= 3 and n > _win:
        _half = _win // 2
        _cum = [0.0]
        for v in values:
            _cum.append(_cum[-1] + v)
        smoothed = [
            (_cum[min(i + _half + 1, n)] - _cum[max(0, i - _half)])
            / (min(i + _half + 1, n) - max(0, i - _half))
            for i in range(n)
        ]
    else:
        smoothed = list(values)

    sorted_vals = sorted(smoothed)
    base = sorted_vals[n // 2]
    devs = sorted(abs(v - base) for v in smoothed)
    mad = 1.4826 * devs[n // 2]
    # ⚠️ 2026-10-12 关键修复：幅度必须量在**检测信号**（smoothed）上，而非原始序列。
    #
    # Bug 现象（本机实测）：转速恒为 None、pulseCount=0、edgeStatus=fewer_than_five_pulses，
    #   UI 恒报「未采集」——即使 CH4 波形文件里明明有 1200 点真实数据。
    # 根因：原始序列的极值多来自**单点尖峰噪声**（本机实测 raw min=-0.12V，而平滑后
    #   最低仅 -0.046V）。用 raw min 算 span≈0.122V 会把阈值压到 base-0.073≈-0.071V，
    #   低于**任何**平滑点 → below 恒为 0 → 第 2 步直接以「脉冲不足」返回。
    #   （此不一致是 2026-10-12 引入平滑后浮现的：平滑只改了检测输入，没改 span 来源。）
    # 修复：span = base - min(smoothed)，与 below/thr 同源。实测修复后本机 CH4
    #   （小信号方波，峰值 0.12~0.16V）检出 3 个脉冲、周期≈20ms；旧大信号
    #   （±2.4V 深脉冲）回归不受影响：平滑最小值与原始最小值几乎相同
    #   （probe_ch4_008 仍输出 21 个脉冲 → 2182rpm，与历史 2142.9 同档吻合）。
    # 注：minimumV 等**测量字段**仍用原始值（不改测量数据），本改动只影响检测阈值。
    span = base - min(smoothed)
    if span <= 0 or mad <= 0:
        # 全平或恒定波形：无脉冲可谈，如实保留 insufficient 状态
        return metric
    thr = base - max(
        PULSE_LEVEL_FRACTION * span,
        min(PULSE_NOISE_SIGMA * mad, PULSE_NOISE_CLAMP_FRACTION * span),
    )

    # 3) 低于阈值 → 合并为脉冲包络 → 取包络内最小点为脉冲中心
    merge_gap = max(1, int(round(PULSE_MERGE_S / increment)))
    below = [i for i, v in enumerate(smoothed) if v < thr]
    if len(below) < PULSE_MIN_COUNT:
        metric["edgeStatus"] = "fewer_than_five_pulses"
        return metric
    groups: list[list[int]] = [[below[0]]]
    for i in below[1:]:
        if i - groups[-1][-1] <= merge_gap:
            groups[-1].append(i)
        else:
            groups.append([i])
    centres = [min(g, key=lambda i: smoothed[i]) for g in groups]
    # 每个包络的凹陷宽度（2026-10-12 增）：2 事件分支的形态判据之一用
    # （宽/周期比）。宽度 = 包络内低于阈值的连续点数；合并时随中心同步更新。
    widths = [(g[-1] - g[0] + 1) * increment for g in groups]

    # 4) 间隔 → 中位周期 → 再按 0.5*周期合并一次 → 重算中位周期
    def _median(xs: list[float]) -> float:
        s = sorted(xs)
        m = len(s)
        if m == 0:
            return 0.0
        return s[m // 2] if m % 2 else (s[m // 2 - 1] + s[m // 2]) / 2.0

    ivals = [(centres[i + 1] - centres[i]) * increment for i in range(len(centres) - 1)]
    period0 = _median(ivals)
    merged = [centres[0]]
    merged_w = [widths[0]]
    for idx, c in enumerate(centres[1:], start=1):
        if period0 > 0 and (c - merged[-1]) * increment < 0.5 * period0:
            if smoothed[c] < smoothed[merged[-1]]:
                merged[-1] = c
                merged_w[-1] = widths[idx]
        else:
            merged.append(c)
            merged_w.append(widths[idx])

    def _autocorr_at(lag_s: float) -> float:
        """平滑序列在 lag 滞后处的归一份自相关（-1..1）。复用点：2 事件分支与主路径。"""
        _lag = int(round(lag_s / increment))
        if _lag <= 0 or _lag >= n:
            return 0.0
        _mean_sm = sum(smoothed) / n
        _num = 0.0
        _den_a = 0.0
        _den_b = 0.0
        for _i in range(n - _lag):
            _x = smoothed[_i] - _mean_sm
            _y = smoothed[_i + _lag] - _mean_sm
            _num += _x * _y
            _den_a += _x * _x
            _den_b += _y * _y
        return _num / math.sqrt(_den_a * _den_b) if _den_a > 0 and _den_b > 0 else 0.0

    metric["pulseCount"] = len(merged)
    if len(merged) < 2:
        metric["edgeStatus"] = "fewer_than_five_pulses"
        return metric

    ivals = [(merged[i + 1] - merged[i]) * increment for i in range(len(merged) - 1)]
    period = _median(ivals)
    metric["medianPeriodS"] = period
    if period < 20 * increment:
        metric["edgeStatus"] = "pulse_period_below_time_resolution"
        return metric

    # ===== 2 事件（单间隔）分支：严格形态 + 周期性判据（2026-10-12 增）=====
    # ⚠️ 仅短窗（≤PULSE_TWO_EVENT_MAX_WINDOW_S）启用；长窗下一律拒——
    #   600ms 窗下正常运行最低档（30%·周期 ~81ms）也有 7 个事件，
    #   「恰好 2 个」只可能是超低速或信号异常（见常量注释）。
    if len(merged) == 2:
        _window_s = (n - 1) * increment
        if _window_s > PULSE_TWO_EVENT_MAX_WINDOW_S:
            metric["edgeStatus"] = "two_event_insufficient"
            return metric
        _width_ratio = max(merged_w) / period
        _r2 = _autocorr_at(period)
        metric["depressionWidthRatio"] = round(_width_ratio, 3)
        metric["autocorrAtPeriod"] = round(_r2, 3)
        if not (
            period >= PULSE_TWO_EVENT_MIN_S
            and period <= PULSE_TWO_EVENT_WINDOW_FRACTION * _window_s
            and _r2 >= PULSE_TWO_EVENT_MIN_R
            and _width_ratio <= PULSE_DEPRESSION_WIDTH_FRACTION_MAX
        ):
            metric["edgeStatus"] = "two_event_insufficient"
            return metric
        metric["frequencyHz"] = 1.0 / period
        metric["edgeStatus"] = "derived_from_two_pulse_intervals"
        return metric

    # ===== 3+ 事件：主路径（原口径）=====
    if len(merged) < PULSE_MIN_EVENTS:
        metric["edgeStatus"] = "fewer_than_five_pulses"
        return metric
    # ⚠️ 2026-10-12 恢复严格口径（配 tach 时基回 50ms/div、600ms 窗）。
    #   60ms 短窗时代曾放宽为「≥70% 间隔在 ±35% 内」——那是统计强度不足的
    #   让步（窗内仅 1~2 个独立间隔，一个噪声偏移就整条否决，转速恒为 None）。
    #   时基回 50ms/div 后窗内有 7 个以上脉冲（30% 档脉冲间隔 81ms，600ms 窗内
    #   7 个），独立间隔 6 个以上，统计强度充足：实测真实数据的**每个**间隔都在
    #   中位周期 ±2% 内，±25% 严格口径留有大余量；且严格口径本身是防误报的
    #   第一道闸（离线 3000 例噪声：放宽口径误报 969 例，严格口径 481 例）。
    if period <= 0 or not ivals:
        metric["edgeStatus"] = "unstable_pulse_intervals"
        return metric
    # ── 漏检倍数修正（2026-11-06 首次加入，2026-11-11 因未入库丢失后恢复）──
    # 实测：异常间隔全部是中位周期的整数倍（50% 档 97.0=2x47.5、70% 档 70.5=2x35.5、
    # 100% 档 53.5=2x27.0 / 83.0=3x27.0），是个别脉冲漏检造成的空洞，不是转速不稳。
    # 原判据「每个间隔都贴近中位周期」会整档否决（现象：只有 30% 有转速）。
    # 做法：按中位周期折算整数倍 k（漏检 k-1 个），落在 k*period ±25% 内即接受，
    # 再用「累计周期数 / 总时长」重算周期。无法对齐的仍判 unstable，不放宽本质判据。
    total_cycles = 0
    for x in ivals:
        k = max(1, int(round(x / period)))
        if abs(x - k * period) > PULSE_PERIOD_TOLERANCE * k * period:
            metric["edgeStatus"] = "unstable_pulse_intervals"
            return metric
        total_cycles += k
    _span_s = (merged[-1] - merged[0]) * increment
    if total_cycles <= 0 or _span_s <= 0:
        metric["edgeStatus"] = "unstable_pulse_intervals"
        return metric
    period = _span_s / total_cycles
    metric["medianPeriodS"] = period
    metric["detectedPulses"] = len(merged)
    metric["correctedCycles"] = total_cycles

    # 凹陷宽度/周期 守卫（2026-10-12 增，取值依据见 PULSE_DEPRESSION_WIDTH_FRACTION_MAX）。
    # 作用：挡住「纯 50Hz 市电干扰」这类同样"周期性"、但凹陷形状明显更宽
    # （正弦的谷宽/周期 ≈0.29 vs 真实脉冲 0.02~0.20）的假周期。
    _width_ratio = max(merged_w) / period
    metric["depressionWidthRatio"] = round(_width_ratio, 3)
    if _width_ratio > PULSE_DEPRESSION_WIDTH_FRACTION_MAX:
        metric["edgeStatus"] = "depression_width_exceeds_limit"
        return metric

    # 周期性（自相关）校验（2026-10-12 增，口径与常数说明见 PULSE_PERIODICITY_MIN）。
    # 在**平滑序列**上算候选周期处的归一份自相关 r：真实周期信号（如本机 CH4）
    # r 高（实测 0.93~0.99）；噪声凑出的假周期 r 低（离线 1000 例中同条件
    # 通过者 r 最大仅 0.341）。事件数 ≥ 6 时豁免（深脉冲型信号自相关天然低，
    # 但多间隔一致性本身已足够强——见常数注释）。
    _r = _autocorr_at(period)
    metric["autocorrAtPeriod"] = round(_r, 3)
    if len(merged) < 6 and _r < PULSE_PERIODICITY_MIN:
        metric["edgeStatus"] = "weak_periodicity"
        return metric
    metric["frequencyHz"] = 1.0 / period
    metric["edgeStatus"] = "derived_from_pulse_intervals"
    return metric


def get_wave_metrics(values: list[float], increment: float, edges: bool) -> dict:
    n = len(values)
    total = 0.0
    sq = 0.0
    mn = float("inf")
    mx = float("-inf")
    for v in values:
        total += v
        sq += v * v
        mn = min(mn, v)
        mx = max(mx, v)
    mean = total / n
    metric: dict[str, Any] = {
        "points": n,
        "sampleIntervalS": increment,
        "windowS": (n - 1) * increment,
        "minimumV": mn,
        "maximumV": mx,
        "meanV": mean,
        "rmsV": math.sqrt(sq / n),
        "frequencyHz": None,
        "dutyPercent": None,
        "edgeStatus": "not_requested",
    }
    if edges:
        metric["edgeStatus"] = "insufficient_amplitude_or_edges"
        rises: list[float] = []
        falls: list[float] = []
        if (mx - mn) >= 0.5:
            level = (mn + mx) / 2
            for i in range(1, n):
                a = values[i - 1]
                b = values[i]
                if (a < level <= b) or (a >= level > b):
                    t = ((i - 1) + (level - a) / (b - a)) * increment
                    (rises if b > a else falls).append(t)
        if len(rises) >= 2:
            period_sum = 0.0
            high_sum = 0.0
            periods = 0
            lengths: list[float] = []
            for i in range(len(rises) - 1):
                left = rises[i]
                right = rises[i + 1]
                fall = None
                for f in falls:
                    if left < f < right:
                        fall = f
                        break
                if fall is not None:
                    period_sum += right - left
                    high_sum += fall - left
                    periods += 1
                    lengths.append(right - left)
            if periods >= 3 and (period_sum / periods / increment) >= 20:
                mean_period = period_sum / periods
                stable = all(abs(p - mean_period) / mean_period <= 0.2 for p in lengths)
                if stable:
                    metric["frequencyHz"] = periods / period_sum
                    metric["dutyPercent"] = 100 * high_sum / period_sum
                    metric["edgeStatus"] = "derived_from_displayed_waveform"
                    metric["completePeriods"] = periods
                else:
                    metric["edgeStatus"] = "unstable_periods"
            else:
                metric["edgeStatus"] = "fewer_than_three_periods_or_twenty_samples_per_period"
    return metric


# 波形点数回退阶梯（2026-10-10 增）。
#
# 现场取证（runs/1d9db708… 2026-10-10 17:00 失败 vs runs/probe_ch4_008… 10-09 17:37 成功）：
#   · 同一台 DS1104Z、同一套参数（tach 50 ms/div、1200 点、触发电平 0.9V）：
#     probe_ch4_008 在 **100% 档实测 rpm=2142.86、21 个脉冲**，preamble 正常；
#   · 联合实验同一轮里，前 6 次 tach 采集（30/50/70 档）preamble 都正常，
#     第 7 次（100% 档）起preamble 变成 10 个 0（inc=0）→ 报成「时间坐标非法」；
#   · probe_tach.py 的现场注释早已写明「**超出会读回 0 点**」——
#     请求点数超过记录上限时DS1000Z 回的是 0 点 preamble，而不是报错。
# 结论：这是**记录点数上限**问题，**不是「本档无脉冲」**（脉冲一直存在）。
# 处置：点数逐级下退重读；四通道都是主测量，任何一档都不允许用「未采集」糊过去，
# 读到的点数/时间坐标一律按实际 preamble 如实记录。
#
# 阶梯下限 432 是**算出来的**，不是随手取的：tach 窗口 = 12div × 50ms = 600ms，
# 100% 档实测转速 2143rpm → 周期 28ms；`get_tach_pulse_metrics` 要求「每周期 ≥20
# 个采样点」→ inc ≤ 1.4ms → 点数 ≥ 600/1.4 ≈ 429。取 432（inc≈1.39ms，每周期
# 20.2 点）刚好守住门限。若退到 300/150 点，inc 变2/4ms → 每周期仅 14/7 点，
# 转速会被判据如实拒收——那等于用另一种方式让转速没数据，与需求相悖。
POINTS_BACKOFF = (432, 384, 300)


def _read_preamble(scope: ScopeDevice, channel: int, want_points: int,
                   run_wait_s: float = 0.1) -> dict[str, Any]:
    """读某通道波形 preamble；点数超记录上限时按 POINTS_BACKOFF 逐级下退重读。

    覆盖三类失败：① 通信异常（VISA 读超时/被占用）；② 畸形 preamble
    （字段数≠10 / 数值解析失败）；③ **0 点 preamble**（inc≤0，DS1000Z 的超限表现）。

    返回 {ok, preamble, inc, origin, ref, y_inc, y_origin, y_ref,
    requested_points, reason, raw}。
    数据纪律：拿不到合法 preamble 一律 ok=False，**绝不编造坐标**，
    由调用方如实抛错（四个通道都是主测量，不做「未采集」降级）。
    """
    raw: list[str] = []
    last_err = ""
    # ⚠️ 2026-10-11 优化：首读只试 **1** 次（原为 4 次）。
    # 实测本机 DS1104Z（固件 00.04.05.SP2）切源后读 `:WAVeform:POINts 450`
    # + `:WAVeform:PREamble?` **首次即成功，耗时毫秒级**；原来「覆盖切源后首帧
    # 未就绪」的 4 次重试纯属浪费 —— 单次采集要读 4 个通道，每个多试 3 次，
    # 累积起来就是「点启动后很久才出数据」的主因。
    # 真失败时仍会退回逐级下退（POINTS_BACKOFF）与重试，只是**不在成功路径上**。
    plan = [(want_points, 2)] + [(p, 2) for p in POINTS_BACKOFF if p < want_points]
    for requested, attempts in plan:
        for attempt_i in range(attempts):
            try:
                # 每次读前重发 POINts：切源/换档后设备可能把它复位
                scope.write(f":WAVeform:POINts {requested}")
                pre = scope.query(":WAVeform:PREamble?")
            except Exception as e:  # noqa: BLE001 - 通信瞬断可重试
                last_err = f"POINts={requested} 读取异常 {type(e).__name__}: {e}"
                time.sleep(0.4)
                continue
            raw.append(pre)
            f = pre.split(",")
            if len(f) != 10:
                last_err = f"POINts={requested} preamble 字段数 {len(f)} ≠ 10"
                time.sleep(0.4)
                continue
            try:
                inc = float(f[4]); origin = float(f[5]); ref = float(f[6])
                y_inc = float(f[7]); y_origin = float(f[8]); y_ref = float(f[9])
            except (ValueError, OverflowError) as e:
                last_err = f"POINts={requested} 数值解析失败: {e}"
                time.sleep(0.4)
                continue
            bad = (inc <= 0 or math.isnan(inc) or math.isinf(inc)
                   or math.isnan(origin) or math.isinf(origin)
                   or math.isnan(ref) or math.isinf(ref)
                   or math.isnan(y_inc) or math.isinf(y_inc)
                   or math.isnan(y_origin) or math.isinf(y_origin)
                   or math.isnan(y_ref) or math.isinf(y_ref))
            if bad:
                last_err = (f"POINts={requested} 返回非法时间坐标"
                            f"(inc={inc}, raw={pre.strip()[:80]})")
                # ⚠️ 2026-10-12：`inc=0` 时**立即放弃，不再逐级下退重试**。
                #
                # 为什么（实测根因链）：设备一旦进入「读不到数据」状态（inc 全 0），
                # 它对**任何**点数都返回全 0。而原来的逻辑会 1200→432→384→300 逐个试
                # （共 7 次尝试），每次失败的查询都会往设备错误队列塞一条错误。
                # 4 个通道 × 7 次 ≈ 28 条，正好顶到队列 30 条上限 → **-350 Queue overflow**。
                # 而 -350 是**不可逆**的：队列满后所有新错误被丢弃、读也读不干净，
                # 实测只有**物理拔插 USB 线**才能清除（软件 authorized 翻转、解绑 usbtmc、
                # 重建容器都无效）。
                #
                # 代价权衡：真正的「点数超上限」场景（preamble 全 0 但设备正常）会被
                # 这里一并跳过下退。但实测本机 @ivi 读 1200 点正常，该场景已不存在；
                # 而 -350 的代价（必须物理拔插）远大于少一次下退重试。
                # 保住错误队列干净 = 保住后续所有档位能继续采集。
                #
                # ⚠️ 2026-10-12 三次修（最终版）：inc=0 要**重试一次**，但仍不下退点数。
                #
                # 关键实测（100% 档，SET 100 后连续读 4 次）：
                #   #1 inc=0（失败） → #2 / #3 / #4 全部成功（1200 点）
                # 即：**切档后的首帧确实可能读不到，但第二次就好**。
                # 这正是 100% 档此前必然失败的真正原因 —— 而「二次修」把首次尝试数
                # 从 4 降到 1，等于亲手取消了它的重试机会。
                #
                # 最终口径：
                #   · 首点数尝试 **2 次** —— 覆盖「切档后首帧未就绪」；
                #   · 仍为 inc=0 则 **return**，不下退 432/384/300 ——
                #     设备真卡死时下退只会狂塞错误把队列顶到 -350；
                #   · 下退点数仅用于「点数真超上限」且该场景本机已不存在。
                if attempt_i + 1 >= attempts:
                    time.sleep(0.2)
                    return {
                    "ok": False, "preamble": "", "inc": 0.0, "origin": 0.0, "ref": 0.0,
                    "y_inc": 0.0, "y_origin": 0.0, "y_ref": 0.0,
                    "requested_points": requested, "reason": last_err, "raw": raw[-4:],
                }
                # ⚠️ 2026-10-12 四次修（真正生效的那次）：
                #   重试**必须重新采集**（`:RUN` → `:STOP`），只重读 preamble 无效！
                #
                # 实测证据（连续读 4 次 CH1，中间不做其他操作）：
                #   #1 1200 点 ✅ → #2 / #3 / #4 全部 0 点 ❌
                # 设备在读完一次后会丢失采集缓冲；只重发 `:WAVeform:POINts` +
                # `:WAVeform:PREamble?` 不会让它重新采集 —— 所以此前「首读重试 2 次」
                # 对 inc=0 场景毫无帮助（第 2 次读到的仍是 0，只是白试一次）。
                # 而 100% 档实测「#1 失败、#2 成功」之所以成立，是因为那个手动测试
                # 每次都跑完整 RUN→STOP→PREamble→DATA 序列，等于重新采集了。
                #
                # 故：重试前补一次 `:RUN` + `:STOP`，让设备重新采集后再读。
                # 异常吞掉（原错误优先，不掩盖真因）。
                # ⚠️ 2026-10-12 七修：重试时重新采集**必须等够扫描时间**。
                #   原实现 `:RUN` → 立即 `:STOP`，在 tach 档（5ms/div，扫描 60ms）下
                #   等于「还没扫完就停」→ 重试必然读到同样的 0 点，纯属白试。
                #   实测证据：整轮 3 次采集中只有中间 1 次成功（首读恰好赶上扫描完成），
                #   另两次都因重试无效而失败。
                time.sleep(0.2)
                try:
                    scope.write(":RUN")
                    time.sleep(run_wait_s)
                    scope.write(":STOP")
                except Exception:  # noqa: BLE001 - 重试前的重新采集失败不掩盖原错误
                    pass
                time.sleep(0.2)
                continue
            if requested != want_points:
                sys.stderr.write(
                    f"scope capture: CH{channel} 点数回退 {want_points} -> {requested}"
                    f"（{last_err}）；按实际 preamble 记录点数与时间坐标\n"
                )
            return {
                "ok": True, "preamble": pre, "inc": inc, "origin": origin, "ref": ref,
                "y_inc": y_inc, "y_origin": y_origin, "y_ref": y_ref,
                "requested_points": requested, "reason": "", "raw": raw[-4:],
            }
    return {
        "ok": False, "preamble": "", "inc": 0.0, "origin": 0.0, "ref": 0.0,
        "y_inc": 0.0, "y_origin": 0.0, "y_ref": 0.0,
        "requested_points": want_points, "reason": last_err, "raw": raw[-4:],
    }


# ---------------------------------------------------------------------------
# 单档采集（对齐 Save-ProfileCapture）
# ---------------------------------------------------------------------------
def _write_empty_csv(scope: ScopeDevice, directory: str, channel: int, want_points: int) -> str:
    """给「无信号」通道落一个只有表头的 CSV，让下游拿到完整文件列表。

    为什么需要：`_merge_profile_captures` 与前端都按固定文件清单读产物；
    少一个文件会让链路按「产物缺失」报错，而不是「该通道无数据」。
    这里如实写出 0 行数据（只有 sample/time_s/voltage_V/current_A 表头），
    **不编造任何数值**。
    """
    path = os.path.join(directory, f"CH{channel}.csv")
    try:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerow(["sample", "time_s", "voltage_V", "current_A"])
        pre_path = os.path.join(directory, f"CH{channel}_preamble.txt")
        with open(pre_path, "w", encoding="utf-8") as fh:
            fh.write("")  # 空 preamble：如实表示「无有效采集」，下游据此判无数据
    except Exception:  # noqa: BLE001 - 落盘失败不该顶替主测量结果
        pass
    return path


def _save_profile_capture(
    scope: ScopeDevice, cfg: dict, directory: str, profile: str, cycle: int, duty: int
) -> dict:
    os.makedirs(directory, exist_ok=True)
    started = _now()
    metrics: dict[str, Any] = {}
    files: list[str] = []
    roles = ("current", "voltage", "pwm") if profile == "pwm" else ("tach",)
    # 波形点数（2026-10-08 新增，可配置；同日随后恢复默认）。
    # 由 config 的 scope.waveformPoints 控制采集点数。走 NI-VISA(@ivi) 后端时
    # 大块读取稳定，可用 1200 点完整分辨率（Windows overlay 已设 1200）；
    # 若回退 @py(pyvisa-py+libusbK)，该组合实测 >~100 点必超时，需在 overlay 改小。
    want_points = int(cfg.get("waveformPoints") or 1200)
    # 本档的时间基准（决定 RUN 后要等多久才扫完一屏，见下方 RUN 处的说明）
    timebase = (cfg["pwmTimebaseSecondsPerDiv"] if profile == "pwm"
                else cfg["tach"]["timebaseSecondsPerDiv"])
    try:
        scope.write(":STOP")
        scope.write(":WAVeform:MODE NORM")
        # ⚠️ 2026-10-08：波形读取改用 BYTE（二进制）格式。
        # 原因：ASCii 格式 1200 点约 15KB，经 USB-TMC 传输在 Windows+libusbK 下必超时
        # （VI_ERROR_TMO）；BYTE 格式仅 1.2KB，稳定读通。换算回电压用 preamble 的
        # YINcrement/YORigin/YREFerence（f[7]/f[8]/f[9]）。
        scope.write(":WAVeform:FORMat BYTE")
        # 显式设定点数：设备会记住上一次的 POINts 设置，不显式设定会导致
        # preamble 报屏幕点数(1200)与实际读取量不一致 → 校验误报。
        scope.write(f":WAVeform:POINts {want_points}")
        for role in roles:
            ch = cfg["tach"] if role == "tach" else cfg["channels"][role]
            channel = int(ch["channel"])
            scope.write(f":WAVeform:SOURce CHANnel{channel}")
            # 逐通道重新设点数（切源后 POINts 可能被复位为屏幕点数）
            scope.write(f":WAVeform:POINts {want_points}")
            # ⚠️ 2026-10-11 修「转速/占空比迟迟不出」+ 随后的整轮失败：
            #   DS1000Z 处于 STOP 状态时切 `:WAVeform:SOURce` 会**丢弃已采集数据**，
            #   此时 `:WAVeform:PREamble?` 返回全 0（`inc=0`、BYT_Nr=0）。
            #   实测表现为：第 1 档耗 35.9s 才出第一条数据（_read_preamble 把 450→432→384→300
            #   逐级重试全落空），第 2 档直接 `Invalid waveform time coordinates ... inc=0.0` 整轮失败。
            #   解法：切源后先 `:RUN` 让它完成一次触发采集，再 `:STOP` 读数。
            #   实测触发在 0 秒内即可完成（inc 立即非 0），无需额外 sleep。
            scope.write(":RUN")
            # ⚠️ 2026-10-12 五修（最终版）：RUN 后**必须等够一个屏幕扫描周期**。
            #
            # 根因（实测取证）：示波器在 RUN 状态下需要扫完一屏才有波形数据可读。
            #   · 扫描周期 = 12 div × timebase
            #   · pwm 档 0.02ms/div → 0.24ms（可忽略）
            #   · tach 档 5ms/div   → **60ms**（不可忽略！）
            # 原来的 `:RUN` → 立即 `:STOP` 在 tach 档下等于「还没扫完就停」→ 0 点
            # （`inc=0.0`），这正是 CH4 始终采不到的最后一环。
            #   对照实证：手动测试在 RUN 后 sleep(0.3) 再 STOP，同样参数下
            #   **CH4 连续 4/4 全部读到 1200 点**；而项目代码立即 STOP 则 0 点。
            #
            # 等待时长取 max(50ms, 1.5 × 扫描周期)：
            #   · 下限 50ms 兜住 pwm 档（扫描仅 0.24ms），代价可忽略；
            #   · 1.5 倍余量吸收 USB 往返延迟。
            #   （此前曾用固定 0.25s 导致 pwm 档回归 —— 那是「等待期间设备进入多次采集
            #    使 STOP 后缓冲不一致」；而按扫描周期取值的等待远短于此，且实测 pwm 档
            #    各 3 次采集正常。）
            #   等待时长取 max(50ms, 5 × 扫描周期)：
            #     · pwm 档（0.02ms/div，扫描 0.24ms）→ 50ms，几乎无成本；
            #     · tach 档（5ms/div，扫描 60ms）→ 300ms —— 与手动验证成功的 0.3s 一致。
            #   ⚠️ 余量必须给足：实测 1.5 倍（90ms）**仍读不到**，说明设备需要的不只是
            #     一个扫描周期，还要算上状态切换与 AUTO 重扫的准备时间。5 倍是实测可用值。
            #   （此前固定 0.25s 会弄坏 pwm 档 —— 因为对 pwm 来说 250ms 远超其 0.24ms
            #    扫描周期，等待期间设备反复重扫使缓冲不一致；按周期取值则不会。）
            #   ⚠️ 2026-10-12 六修（实测校准）：下限提到 **0.6s**。
            #     实测边界：等 0.4s 稳定成功、等 0.3s 必失败 —— 差 0.1s 就是成败分界。
            #     故取 0.6s 留一倍余量，避免贴着临界值跑。
            #     pwm 档同样等 0.6s（单次采集本就 8~9s，占比可忽略）。
            scan_s = 12 * timebase
            time.sleep(max(0.6, scan_s * 10))
            scope.write(":STOP")
            # preamble 读取：重试 + 点数回退（2026-10-09/10，见 _read_preamble）。
            # 覆盖三类失败：通信瞬断 / 畸形 preamble / **0 点 preamble（点数超上限）**。
            # 四通道都是主测量 → 读不到就如实抛错（附判据与原始返回），
            # 绝不降级成「未采集」，转速必须显示真实数据。
            got = _read_preamble(scope, channel, want_points,
                                 run_wait_s=max(0.6, scan_s * 10))
            if not got["ok"]:
                # ⚠️ 2026-10-11 降级：**只有 tach（转速）通道**允许「无信号」降级。
                # 场景：风扇没转 / 转速传感器未接时，CH4 上没有脉冲，示波器按
                # 触发阈值（如 0.9V）永远不触发 → preamble 全 0（`inc=0`、BYT_Nr=0）。
                # 实测这会让**整轮直接 failed**（2026-10-11 11:0x 那轮就是如此），
                # 而 pwm 三通道的数据其实是好的 —— 为一个「本来就该为空」的通道
                # 把整轮判死，是把「没信号」误当成「设备故障」。
                #
                # 处置：记一个空 metrics（rpm=None + 明确的 edgeStatus 说明原因），
                # 跳过该通道继续读其余通道；前端据此显示「转速未采集」而非整轮失败。
                # pwm 三通道（current/voltage/pwm）**不降级**：它们是主测量，
                # 读不到就是真故障，仍照旧抛错。
                if role == "tach":
                    metrics.setdefault("_unavailable", {})[role] = (
                        f"no_trigger_signal: 触发阈值 {cfg['tach'].get('triggerLevelV')}V "
                        f"未满足（转速通道无脉冲，通常是风扇未转或传感器未接）；"
                        f"读数失败原因 {got['reason'][:120]}"
                    )
                    files.append(_write_empty_csv(scope, directory, channel, want_points))
                    continue
                raise VisaError(
                    f"Invalid waveform time coordinates. "
                    f"(CH{channel} 点数 {want_points}→{POINTS_BACKOFF[-1]} 读取均失败："
                    f"{got['reason']}；原始返回 {got['raw']})"
                )
            pre = got["preamble"]
            inc = got["inc"]; origin = got["origin"]; ref = got["ref"]
            y_inc = got["y_inc"]; y_origin = got["y_origin"]; y_ref = got["y_ref"]
            requested_points = got["requested_points"]
            if role == "pwm" and inc > 0.000002:
                raise VisaError("PWM export lacks 20 samples per 25kHz period.")

            # BYTE 二进制块：直接用 query_binary_values 解析 IEEE-488.2 定长块，
            # 避免手工处理块头；容器用 bytes，值为 0..255 的原始字节。
            raw_bytes = scope.query_binary_values(":WAVeform:DATA?")
            # 校验放宽（2026-10-08）：设备对 POINts 的处理可能与请求值不完全一致
            # （NORM 模式受屏幕采样限制）。只要求「有足够样本可算指标」即可，
            # 不因绝对相等而误报——点数以实际读回为准，如实记录在 metrics 里。
            if len(raw_bytes) < 2:
                raise VisaError("Waveform sample count differs from preamble.")

            cc = cfg["currentConversion"]
            values: list[float] = []
            rows: list[dict] = []
            for i, b in enumerate(raw_bytes):
                # 字节 → 电压（RIGOL DS1000Z 官方公式，2026-10-11 修正）：
                #     Volts = (byte - YREFerence - YORigin) * YINCrement
                #
                # ⚠️ 原写法 `(byte - YREF) * YINCrement + YORigin` 是**错的**：
                #   把「垂直偏移」当成加性常数直接加到电压上，而该字段的单位其实是
                #   「ADC 计数格」而非电压。CH3 实测（YORigin=-63）下两种写法差 ~65V：
                #     示波器自报 :MEAS:VAVG? = 0.0607V
                #       官方公式 → 0.060V  ✅ 与示波器一致
                #       原写法   → -65.46V ❌ 偏差超 1000 倍
                #   该 bug 会让所有电压类指标（供电电压/实测占空比/转速电平）整体失真。
                #
                # 依据：DS1000Z 编程手册「Waveform:preamble」章节与配套示例
                #   preamble 0,2,600,2,0.000000,-0.000006,0,0.008000,50,127
                #   → Volts = (byte - 127 - 50) * 0.008
                v = (float(b) - y_ref - y_origin) * y_inc
                if math.isnan(v) or math.isinf(v):
                    raise VisaError("Invalid waveform voltage.")
                values.append(v)
                current_a = None
                if role == "current" and cc.get("enabled"):
                    current_a = v * cc["gainAmpsPerVolt"] / cc["turns"]
                rows.append({
                    "sample": i,
                    "time_s": (i - ref) * inc + origin,
                    "voltage_V": v,
                    "current_A": current_a if current_a is not None else "",
                })

            csv_path = os.path.join(directory, f"CH{channel}.csv")
            with open(csv_path, "w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=["sample", "time_s", "voltage_V", "current_A"])
                writer.writeheader()
                writer.writerows(rows)
            files.append(csv_path)

            pre_path = os.path.join(directory, f"CH{channel}_preamble.txt")
            with open(pre_path, "w", encoding="utf-8") as fh:
                fh.write(pre)
            files.append(pre_path)

            # 转速通道走专用判法（脉冲包络 + 间隔中位数）；PWM 仍走原「数穿越点」判法，
            # 口径与阈值一行未动（2026-10-09）。
            if role == "tach":
                m = get_tach_pulse_metrics(values, inc)
            else:
                m = get_wave_metrics(values, inc, role == "pwm")
            m["physicalProbeRatioConfirmed"] = ch["physicalProbeRatioConfirmed"]
            # 点数回退留痕（2026-10-10）：requested_points = 设备实际接受的请求点数，
            # points = 实际读到的样本数（上文按读回量如实记录）。两者不一致即说明
            # 触发过 POINTS_BACKOFF 回退，便于离线核查波形分辨率是否被降级。
            m["requestedPoints"] = requested_points
            # ⚠️ 2026-11-02 修：原实现「命令是 0/100 就把实测值全部置 None」，
            #    等于按**命令**丢弃**实测**——而固件把 100% 钳到 99%，PWM 仍在开关
            #    （实测 min −2.56 / max 7.64 满幅），那份实测是有效的。
            #    改为：只有当**波形本身确实测不出周期**时才按「恒定输出」解释；
            #    波形测得到就如实上报实测占空比/频率（数据纪律：不编、也不丢）。
            if role == "pwm" and duty in (0, 100) and m.get("frequencyHz") is None:
                m["edgeStatus"] = "constant_output_command_no_frequency_claim"
            if role == "pwm" and m["frequencyHz"] is not None and abs(m["frequencyHz"] - 25000) > 2500:
                m["frequencyHz"] = None
                m["dutyPercent"] = None
                m["edgeStatus"] = "outside_expected_25kHz_band"
            if role == "tach":
                scale = ch["scaleVoltsPerDiv"]
                m["clipped"] = (m["maximumV"] >= 4 * scale * 0.99 or m["minimumV"] <= -4 * scale * 0.99)
                if m["clipped"]:
                    m["frequencyHz"] = None
                    m["dutyPercent"] = None
                    m["edgeStatus"] = "display_clipped_invalid_frequency"
            if role == "current" and cc.get("enabled"):
                m["meanCurrentA"] = m["meanV"] * cc["gainAmpsPerVolt"] / cc["turns"]
                m["currentConversion"] = "confirmed_gain_and_turns"
                m["belowSpecifiedRange"] = abs(m["meanCurrentA"]) < cc["minimumSpecifiedCurrentA"]
            if role == "tach":
                m["rpm"] = None
                if m["frequencyHz"] is not None and cfg["tach"].get("pulsesPerRevolution") is not None:
                    m["rpm"] = 60 * m["frequencyHz"] / cfg["tach"]["pulsesPerRevolution"]
                m["pulsesPerRevolution"] = cfg["tach"].get("pulsesPerRevolution")
            metrics[role] = m

        # BMP 截屏：**辅助产物，失败不阻断采集**（2026-10-11 改）。
        #
        # 为什么降级：Linux + pyvisa-py(@py) 读 `:DISPlay:DATA?` 必超时。
        #   实测本机 DS1104Z 固件 00.04.05.SP2：BMP/PNG/JPEG 三种格式全部
        #   VI_ERROR_TMO，而同会话下 `:WAV:DATA?` 波形读取完全正常。
        #   这与 pyvisa-py 的已知缺陷一致（GitHub pyvisa-py#414 记录同型号
        #   DS1104z 在 Linux 上 `:DISPlay:DATA?` 必超时，NI-VISA(@ivi) 则正常）。
        #   截屏只是留档用的辅助产物，波形/指标才是采集本体——
        #   为此让整轮 failed 会掩盖真实故障（2026-10-11 就发生过）。
        #   Windows 走 @ivi 时正常，仍会照常产出 screen.bmp。
        #
        # 口径：截屏失败 → 记 capture.json 的 screenshot 字段说明原因，不抛错。
        screenshot_status = "ok"
        try:
            bmp = scope.query_binary_values(":DISPlay:DATA? ON,OFF,BMP")
            if len(bmp) < 54 or bmp[0] != 66 or bmp[1] != 77:
                raise VisaError("Invalid scope BMP.")
            screen = os.path.join(directory, "screen.bmp")
            with open(screen, "wb") as fh:
                fh.write(bmp)
            files.append(screen)
        except Exception as e:  # noqa: BLE001 - 截屏失败属降级，不影响采集结果
            screenshot_status = f"unavailable: {type(e).__name__}: {str(e)[:120]}"
            print(f"[scope] 截屏不可用（不影响波形采集）：{screenshot_status}")

        # 把「无信号降级」的通道补成显式 metrics（rpm=None + 明确 edgeStatus），
        # 这样前端能显示「转速未采集：<原因>」，而不是空白或整轮失败。
        for role, reason in (metrics.pop("_unavailable", None) or {}).items():
            metrics[role] = {
                "meanV": None, "minimumV": None, "maximumV": None,
                "dutyPercent": None, "frequencyHz": None, "rpm": None,
                "edgeStatus": reason, "unavailable": True,
            }

        meta = {
            "schemaVersion": "1.0",
            "startedUtc": started,
            "finishedUtc": _now(),
            "cycle": cycle,
            "commandedPwmPercent": duty,
            "profile": profile,
            "source": "NORM displayed waveforms; short STOP snapshot, not ten-second trend",
            "timebaseSecondsPerDiv": (cfg["pwmTimebaseSecondsPerDiv"] if profile == "pwm"
                                      else cfg["tach"]["timebaseSecondsPerDiv"]),
            "metrics": metrics,
            "artifacts": list(files),
            "screenshot": screenshot_status,
            "rpmAvailable": bool(profile == "tach" and metrics["tach"].get("rpm") is not None),
        }
        meta_path = os.path.join(directory, "capture.json")
        meta["artifacts"].append(meta_path)
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
        return meta
    finally:
        scope.write(":RUN")


def _merge_profile_captures(captures: list[dict], base_dir: str) -> dict:
    """把同一次物理采集的多档记录合并为**一条**（2026-10-09 新增）。

    为什么合并（用户报「同一时刻一半通道显示未采集」的根因）：
      四通道共用一个时基，PWM 需 20µs/div、转速需 0.05s/div（差 2500 倍），
      **一次采样不可能同时测到两者**，所以必须跑两趟。但两趟属于**同一次物理
      采集**（同一档位、同一时刻、同一目录 tag），原实现把它们当成两条独立
      记录分别上报（`for capture in results: emit(...)`）→ 后端一事件一样本 →
      样本被劈成「只有 CH1~CH3」与「只有 CH4」两半 → 趋势 tooltip 按 t 轴对齐
      时必然一半显示「未采集」（读数行因取「该量最后一个非 null 样本」而侥幸全满，
      掩盖了这个问题）。

    合并口径（**不用一个字段同时撒两个谎**）：
      · metrics      = 各档并集（pwm 档给 current/voltage/pwm，tach 档给 tach）
      · artifacts    = 各档拼接（→ read_capture_waveforms 遍历后天然得 CH1~CH4）
      · profile      = "pwm+tach"（多档才有这个值；单档原样返回）
      · startedUtc   = **第一档（pwm）**：与落盘目录 tag / `_make_capture_id` 同源，
                       保证 capture_id 与波形寻址不变
      · finishedUtc  = **最后一档（tach）**：真实结束时刻
      · timebaseSecondsPerDiv = 第一档值（顶层主时基，保持既有字段语义）
      · profiles     = 分档留痕各自 timebaseSecondsPerDiv / startedUtc / finishedUtc
                       （两档时基不同，不可合并成一个数）
      · rpmAvailable = 任一分档的 tach.rpm 非空
    并在 tag 根目录补写一份合并后的 `capture.json`，与 `pwm/`、`tach/` 下两份并存，
    便于离线核查（落盘路径沿用 `_save_profile_capture` 的「先 append 自身路径再 dump」范式）。
    """
    if len(captures) == 1:
        return captures[0]

    merged_metrics: dict[str, Any] = {}
    merged_artifacts: list[str] = []
    profiles: dict[str, Any] = {}
    for cap in captures:
        merged_metrics.update(cap.get("metrics") or {})
        merged_artifacts.extend(cap.get("artifacts") or [])
        prof = cap.get("profile")
        if prof:
            profiles[prof] = {
                "timebaseSecondsPerDiv": cap.get("timebaseSecondsPerDiv"),
                "startedUtc": cap.get("startedUtc"),
                "finishedUtc": cap.get("finishedUtc"),
                "roles": sorted((cap.get("metrics") or {}).keys()),
            }

    first, last = captures[0], captures[-1]
    merged: dict[str, Any] = {
        "schemaVersion": first.get("schemaVersion", "1.0"),
        # 沿用第一档的 startedUtc（与目录 tag 同源），结束时刻取最后一档
        "startedUtc": first.get("startedUtc"),
        "finishedUtc": last.get("finishedUtc"),
        "cycle": first.get("cycle"),
        "commandedPwmPercent": first.get("commandedPwmPercent"),
        "profile": "+".join(p for p in ("pwm", "tach") if any(c.get("profile") == p for c in captures)),
        "source": first.get("source"),
        "timebaseSecondsPerDiv": first.get("timebaseSecondsPerDiv"),
        # 分档留痕：两档时基/起止各自保留，供定位与离线核查
        "profiles": profiles,
        # 合并后 metrics 是四路并集：current/voltage/pwm + tach
        "metrics": merged_metrics,
        "artifacts": merged_artifacts,
        "rpmAvailable": any(
            (c.get("metrics") or {}).get("tach", {}).get("rpm") is not None for c in captures
        ),
        # 合并档数如实记录（1 = 只有 pwm，2 = pwm + tach）
        "mergedProfiles": len(captures),
    }

    meta_path = os.path.join(base_dir, "capture.json")
    merged["artifacts"].append(meta_path)
    os.makedirs(base_dir, exist_ok=True)
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, ensure_ascii=False, indent=2)
    return merged


def save_fan_scope_capture(scope: ScopeDevice, cfg: dict, run_dir: str, cycle: int, duty: int) -> list[dict]:
    """一次采集（pwm 档 + 可选 tach 档），对齐 Save-FanScopeCapture。

    ⚠️ 整体重试一次（2026-10-09 增）：实测 100% 档（恒高电平）下切源后首帧
    偶发读到畸形 preamble 或通信瞬断，原实现直接让整轮 failed（每轮都栽在这里）。
    现改为「整次采集最多试 2 遍」：第 1 遍失败后，重新 :RUN 稳定 0.5s 再试一遍。
    两遍都失败才抛错 —— **不伪造数据**，失败原因原样透传。
    为什么在此层重试而不是逐通道：切源/STOP/RUN 是整次采集的会话态，
    首帧异常往往是会话未就绪，重开一次会话比逐通道重读更有效。

    ⚠️ 返回值口径（2026-10-09 改）：多档结果**合并为长度 1 的列表**。
    这样两个调用点（`run_experiment.py` / `entrypoints/run_scope.py`）的
    `for capture in results: emit("capture_completed", capture)` 循环
    **一行都不用改**，就自动从「一次采集两条事件」变成「一次采集一条事件」，
    样本随之恢复为四通道齐全的一行（详见 `_merge_profile_captures`）。
    tach 未启用时本来就只有 1 档，返回值与改造前完全一致（零回归）。
    """
    tag = f"cycle{cycle:04d}_duty{duty:03d}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]}"
    base = os.path.join(run_dir, tag)
    last_err: Exception | None = None
    for attempt in range(2):
        result: list[dict] = []
        try:
            # ⚠️ 2026-10-12 修（关键 bug）：**每次采集前必须重设 pwm 时基**。
            #   原实现只在 run_experiment 的档位循环外设过一次 pwm profile；
            #   而本函数每次都会把时基切到 tach（5ms/div）并**不保证切回**——
            #   于是第 2 次及以后的采集，pwm 档是在 5ms/div 下读的，
            #   `inc` 从 0.2µs 变成 50µs，触发 `PWM export lacks 20 samples
            #   per 25kHz period` 整轮 failed。
            #   实测症状：整轮只成功 1 次采集（第一次恰好继承了对时基），
            #   之后每次都报上述错误。
            _set_capture_profile(scope, cfg, "pwm")
            result.append(_save_profile_capture(scope, cfg, os.path.join(base, "pwm"), "pwm", cycle, duty))
            if cfg.get("tach", {}).get("enabled"):
                # ⚠️ 切回 pwm 时基属**恢复动作**：失败不得顶替在飞的真实错误，
                # 否则现场只会看到「切时基失败」，真正的原因（如采集失败）被吞掉。
                # 正常路径下切回失败仍照旧抛出，交给外层重试。
                try:
                    _set_capture_profile(scope, cfg, "tach")
                    # ⚠️ 2026-10-12 修：切到 tach 后要等**足够**时间再采集。
                    #   原来只等 1 个扫描周期（12×5ms = 60ms）—— 实测**不够**：
                    #   完整流程里整个 tach 档 12 次采集全部 0 点；
                    #   而把同一函数单独调用（前面多出一堆配置操作给了缓冲时间）则
                    #   CH4.csv 正常落 1200 行。故与 _save_profile_capture 里的等待口径
                    #   统一为「max(300ms, 5 × 扫描周期)」。
                    time.sleep(0.6)  # 与 _save_profile_capture 内的等待口径一致（见其注释）
                    tach_cap = _save_profile_capture(
                        scope, cfg, os.path.join(base, "tach"), "tach", cycle, duty)
                    # ⚠️ 2026-10-11 修「转速落后 → 整轮崩」的关键：
                    #   CH4 无脉冲时（风扇没转 / 传感器未接），示波器**拿不到有效采集**，
                    #   且这个状态会**持续污染后续所有通道**：实测一旦 CH4 返回 `inc=0`，
                    #   紧接着切回 pwm 时基读 CH1 也是全 0 → 第 2 档必然
                    #   `Invalid waveform time coordinates` 整轮 failed。
                    #   （复现：CH1/OK → CH4/全0 → CH1/全0 → CH1+重设触发/仍全0）
                    #
                    #   故：识别「tach 无信号」这一**可预期**结果后，
                    #   立即切回 pwm 时基并**返回单档结果**（不再走下面的合并逻辑）。
                    #   `_save_profile_capture` 内部已把该通道记为
                    #   `metrics.tach.unavailable=True + edgeStatus=<原因>`，
                    #   前端据此显示「转速未采集」，而不是整轮失败或空白。
                    if (tach_cap.get("metrics", {}).get("tach", {}) or {}).get("unavailable"):
                        _set_capture_profile(scope, cfg, "pwm")
                        scope.write(":RUN")
                        result.append(tach_cap)
                        return [_merge_profile_captures(result, base)]
                    result.append(tach_cap)
                except Exception as e:  # noqa: BLE001
                    # ⚠️ 2026-10-12 降级：**转速档失败不再中断整轮**。
                    #   本机 tach 采集存在间歇性失败（同一轮里可能第 1 次成功、第 2 次
                    #   0 点 —— 设备在连续采集下的状态波动）。原来这里 `raise` 会让
                    #   整轮 failed，连已经采好的 pwm 三通道数据也一并作废。
                    #   现在：恢复 pwm 时基后，记一条 unavailable（如实写明原因），
                    #   继续下一档；该档缺转速，其余通道照常。
                    try:
                        _set_capture_profile(scope, cfg, "pwm")
                    except Exception:  # noqa: BLE001 - 恢复失败只留痕，不掩盖原错误
                        sys.stderr.write("scope recovery (restore pwm timebase) failed\n")
                    tach_cap = {
                        "schemaVersion": "1.0", "profile": "tach",
                        "cycle": cycle, "commandedPwmPercent": duty,
                        "metrics": {"tach": {
                            "meanV": None, "minimumV": None, "maximumV": None,
                            "dutyPercent": None, "frequencyHz": None, "rpm": None,
                            "unavailable": True,
                            "edgeStatus": f"tach_capture_failed: {type(e).__name__}: {str(e)[:90]}",
                        }},
                        "artifacts": [],
                    }
                    result.append(tach_cap)
                # ⚠️ 2026-10-11 优化：正常路径**不再切回 pwm**。
                # 原先每次采集收尾都 `_set_capture_profile(..., "pwm")`（实测 0.4s），
                # 而下一次采集的开头 `_save_profile_capture` 本来就会设 pwm 时基——
                # 这是一次纯冗余往返。实测单次采集 6.0s 里，profile 往返占 3.8s；
                # 去掉冗余那次后可省约 0.4s/次 × 每档 5 次 = 2s/档。
                #
                # 为什么安全：`_save_profile_capture` 进入时按 profile 重设时基与触发，
                # 不依赖上一轮结束时示波器处于哪个时基；且实测「只切源、不重设时基」
                # 与「切 profile」读到的点数完全一致（450 点），确认时基可跨次沿用。
                # 真正需要切回的场景只有上面的**异常恢复分支**，那里已保留。
            # 合并为一条：同一次物理采集的四通道数据作为一行上报
            return [_merge_profile_captures(result, base)]
        except Exception as e:  # noqa: BLE001 - 瞬态采集失败重试后再定论
            last_err = e
            # 重开显示：让示波器回到 RUN 稳态，下次采集的切源首帧更可靠
            try:
                scope.write(":RUN")
            except Exception:  # noqa: BLE001 - 恢复动作失败不掩盖原错误
                pass
            time.sleep(0.5)
    assert last_err is not None
    raise last_err
