"""风扇实验执行器：真实台架执行 + 模拟兜底（阶段 5 接入 v0.6 硬件交接包）。

数据纪律（不可逾越）：
- **真实数据只来自真仪器**。`RealFanExecutor` 只把 `run-experiment.ps1` 写进
  `events.jsonl` 的 `capture_completed` 事件原样映射成 sample，不加减任何数值。
- **模拟数据必须显式标注 `simulation: true`**。`SimFanExecutor` 是开发/联调兜底，
  用于在无仪器时验证「接口 → 轮询 → 动态刷新」链路，其数值是合成值，
  不得被下游当作实测上报；每个返回对象都带 `simulation` 字段，前端据此如实显示。

字段契约对齐扩展包 `hardware/v0.6/docs/examples/02_samples.json`（snake_case）：
  sequence / t_s / measurement_started_t_s / measurement_finished_t_s /
  commanded_pwm_pct / voltage_v / current_probe_v / current_a /
  measured_pwm_duty_pct / pwm_frequency_hz / rpm / quality / capture_id

缺测纪律：电流未确认换算时 `current_a = null`、测速未接入时 `rpm = null`，
并在 `quality` 里写明原因；绝不补 0、绝不编值。
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.core.exceptions import BadRequestException, ConflictException
from app.core.logger import logger
from app.db.session import get_mode

# 默认计划：30/50/70/100% 各 20 秒，一轮共 80 秒（对齐 acceptance.json，2026-10-09）。
# 为什么由 10s 改为 20s：硬件改为每档连续多次采集（capturesPerStep，默认 5），
# 单档需 settle 2s + 5 次采集（每次约 2~3.5s），10s 装不下 5 个点；20s 可容纳。
# 该值只用于展示/planned_duration_s 与 overrun 判定，真实样本仍以 events.jsonl 为准。
DEFAULT_STEPS = [
    {"duration_s": 20, "commanded_pwm_pct": 30},
    {"duration_s": 20, "commanded_pwm_pct": 50},
    {"duration_s": 20, "commanded_pwm_pct": 70},
    {"duration_s": 20, "commanded_pwm_pct": 100},
]

# ---------------------------------------------------------------------------
# 硬件脚本位置（相对项目根推导，不写死绝对路径）。
#
# fan_executor.py 位于 <项目根>/backend/app/services/ 下：
#   parents[0] = services, parents[1] = app, parents[2] = backend, parents[3] = 项目根
# 硬件脚本**Python 跨平台版**约定放在 <项目根>/hardware/py/ 下（对应原 PowerShell 版
# hardware/v0.6/，二者行为契约一致）。配置仍用 hardware/v0.6/config/acceptance.json
# （Python 版入口通过 -ConfigPath 接受同一份配置）。
# 项目整体移动/换机器后仍能自动定位；环境变量 FAN_START_SCRIPT / FAN_STOP_SCRIPT /
# FAN_CONFIG_PATH 仍可覆盖（例如硬件部署在另一台仪器电脑时）。
# ---------------------------------------------------------------------------
_PY_DIR = Path(__file__).resolve().parents[3] / "hardware" / "py"
_DEFAULT_START_SCRIPT = _PY_DIR / "entrypoints" / "start.py"
_DEFAULT_STOP_SCRIPT = _PY_DIR / "entrypoints" / "stop.py"
_DEFAULT_CONFIG_PATH = _PY_DIR.parent / "v0.6" / "config" / "acceptance.json"
# 平台 overlay（2026-10-08 新增）：主配置 acceptance.json 的 serial.port / scope.resource
# **故意留空**，靠 overlay 补齐（见 hardware/py/runtime.py 的 overlay 合并层）。
# 但 start.py 约定「显式传 -ConfigPath 则不叠加 overlay」（保护 run_scope.py 隔离测试），
# 而后端启动时必然是显式传 -ConfigPath —— 两条规则相撞会让 serial.port 为空、启动即失败。
# 因此由后端（唯一知道"当前是哪台机器"的组件）按平台直接选定 overlay 文件。
_CONFIG_DIR = _DEFAULT_CONFIG_PATH.parent
_PLATFORM_OVERLAY = _CONFIG_DIR / (
    "acceptance.windows.json" if os.name == "nt" else "acceptance.linux.json"
)
# 子进程解释器解析（2026-10-09 修，风扇不转的致命根因）。
#
# 背景：原实现是 `os.environ.get("FAN_PYTHON") or sys.executable`。
# sys.executable 指向**后端自己的 venv**（backend/.venv/Scripts/python.exe），
# 而该 venv 只装后端依赖，**没有 pyserial / pyvisa**（实测两库均 ModuleNotFoundError）。
# 于是 hardware/py/run_experiment.py 在顶层 `import fan_serial` → `import serial`
# 处立即崩、退出码 1，`SET <duty>` 从未下发到 UNO —— 表现就是「点了启动风扇不转」。
#
# 修复口径（数据纪律：不假装成功，失败给可行动原因）：
#   ① FAN_PYTHON 环境变量优先（现场/分机显式指定）；
#   ② 否则探测「同目录下的 backend/.venv 兄弟解释器」以外，还允许用
#      `hardware/.env`（若存在）里的 FAN_PYTHON 指定；
#   ③ 仍无则回退 sys.executable，并由 _precheck_dependencies 在启动前如实报错，
#      提示到哪个解释器装 requirements.txt，而不是静默崩在子进程里。
_FAN_PYTHON_ENV = "FAN_PYTHON"

# hardware/.env（可选）：把硬件侧环境变量（含 FAN_PYTHON / FAN_CONFIG_PATH）写在
# 此文件里，后端启动子进程时读取并注入。硬件包与后端可能用不同解释器，这层是解耦点。
_HARDWARE_ENV_FILE = _PY_DIR.parent / ".env"


def _read_hardware_env() -> dict[str, str]:
    """读 hardware/.env（若存在）为键值对。缺失/不可读一律返回空 dict，不抛错。

    为什么需要：hardware/ 未被 git 跟踪、解释器与后端不同，现场需要一个
    「不改代码就能指定解释器/overlay」的地方。hardware/.env 承担这个角色：
      FAN_PYTHON=<装有 pyserial+pyvisa 的解释器绝对路径>
      FAN_CONFIG_PATH=<overlay 绝对路径，可选>
    文件缺失时**不猜路径**，交由依赖预检如实报错（数据纪律）。
    """
    out: dict[str, str] = {}
    try:
        if not _HARDWARE_ENV_FILE.is_file():
            return out
        for raw in _HARDWARE_ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                out[key] = value
    except OSError:
        return {}
    return out


def _probe_dependencies(python_exe: str) -> list[str]:
    """探测某个解释器是否具备硬件脚本所需依赖，返回缺失项名称列表（空=齐备）。

    用 `-c "import importlib.util,sys; ..."` 在**目标解释器**内探测（而非当前进程），
    因为当前后端进程是否有 serial 与目标解释器无关。只探测不打开硬件，副作用为零。
    探测失败（解释器路径不存在/无法启动）返回全部缺失项，由调用方报可行动原因。
    """
    required = ("serial", "pyvisa")
    code = (
        "import importlib.util as u,sys;"
        f"miss=[m for m in {required!r} if u.find_spec(m) is None];"
        "sys.stdout.write('|'.join(miss))"
    )
    try:
        proc = subprocess.run(
            [python_exe, "-c", code],
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("[fan-executor] 解释器探测失败（%s）：%s", python_exe, e)
        return list(required)
    if proc.returncode != 0:
        # 解释器能起但导入探测脚本就失败 → 视为全部缺失，附 stderr 末行便于定位
        detail = (proc.stderr or "").strip().splitlines()
        logger.warning(
            "[fan-executor] 解释器 %s 探测返回码 %s：%s",
            python_exe, proc.returncode, detail[-1] if detail else "(无 stderr)",
        )
        return list(required)
    missing = [m for m in (proc.stdout or "").strip().split("|") if m]
    return missing


def _resolve_python() -> str:
    """解析用于拉起硬件脚本的解释器（2026-10-09 新增）。

    优先级（高 → 低）：
      1. 进程环境变量 FAN_PYTHON（部署/分机显式指定，最高优先）；
      2. hardware/.env 里的 FAN_PYTHON（现场配置文件，不改代码即可切换）；
      3. sys.executable（兜底；缺依赖时由 _precheck_dependencies 如实报错）。

    注意：**不做「扫描磁盘找 conda」这类臆测**——找不到就回退并在预检阶段
    报出可行动原因（写明去哪个解释器装 hardware/py/requirements.txt）。
    """
    explicit = os.environ.get(_FAN_PYTHON_ENV)
    if explicit:
        return explicit
    env_file = _read_hardware_env().get(_FAN_PYTHON_ENV)
    if env_file:
        return env_file
    return sys.executable


# 解析结果缓存（每进程一次即可；环境变量变更需重启后端，与「后端不热重载」一致）。
_PYTHON = _resolve_python()


def _select_config_path() -> str:
    """选定主配置路径（后端专用）。

    优先级（高 → 低）：
      1. `FAN_CONFIG_PATH` 环境变量**不是主配置路径**，见下方说明，此处忽略之；
      2. 主配置 `acceptance.json`（跨机器通用，机器相关字段留空）。

    为什么这里不直接返回 overlay 文件：overlay（acceptance.windows.json）**只是
    一个字段片段，本身没有 schemaVersion**，不能单独当主配置读（会报
    "Unsupported config schemaVersion."）。正确用法是「主配置 + 深合并 overlay」，
    即 runtime.read_experiment_config 的 allow_overlay=True 路径 —— 由
    FAN_CONFIG_PATH 环境变量指向 overlay。见 `_resolve_overlay_path()`。
    """
    return str(_DEFAULT_CONFIG_PATH)


def _resolve_overlay_path() -> str:
    """解析本次运行要使用的 overlay 文件路径（可为空串表示不叠加）。

    优先级：
      1. `FAN_CONFIG_PATH` 环境变量 —— 现场显式指定（可指向 overlay 或完整配置）；
      2. 平台 overlay：Windows=acceptance.windows.json / Linux=acceptance.linux.json；
      3. 空串 —— 无 overlay 可用（此时主配置留空字段会由预检报出明确原因）。

    为什么要由后端解析：start.py 约定「显式传 -ConfigPath 则不叠加 overlay」
    （保护 run_scope.py 隔离测试），而后端启动必然是显式 -ConfigPath。因此后端
    必须在子进程环境里补上 FAN_CONFIG_PATH，让子进程的 allow_overlay 分支生效。
    """
    explicit = os.environ.get("FAN_CONFIG_PATH")
    if explicit:
        return explicit
    if _PLATFORM_OVERLAY.is_file():
        return str(_PLATFORM_OVERLAY)
    logger.warning(
        "[fan-executor] 平台 overlay 不存在：%s（主配置留空字段将无法补齐）",
        _PLATFORM_OVERLAY,
    )
    return ""


def _load_runtime_module() -> Any:
    """按文件路径加载硬件包的 runtime.py（不污染后端 sys.path）。

    必须先注册进 sys.modules 再 exec_module：runtime.py 用了
    `from __future__ import annotations` + @dataclass，dataclasses 解析类型注解时
    会按模块名回查 sys.modules，未注册会抛 "NoneType has no attribute __dict__"。
    """
    import importlib.util  # noqa: PLC0415 - 延迟导入：避免后端启动即依赖硬件包

    runtime_path = _PY_DIR / "runtime.py"
    module_name = "_fan_runtime_precheck"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(module_name, runtime_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载校验模块：{runtime_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _precheck_config(config_path: str, overlay_path: str) -> str:
    """启动前预检「主配置 + overlay」可解析，把配置错误提前到 start() 同步阶段。

    返回空串表示通过；否则返回可行动的错误原因（原样透传，不美化）。
    为什么预检：子进程失败时后端只能靠 stderr 透传，链路长（≥10s 早失败窗口），
    且 start.py 建目录前失败时连 runs/<id>/stderr.log 都没有，
    前端只会看到"退出码 1 无收尾"这种不可行动的提示。
    预检用与子进程**完全同一套**校验（runtime.read_experiment_config），保证口径一致。
    """
    try:
        module = _load_runtime_module()
        # allow_overlay=True：与子进程一致，走「主配置 < overlay < 精细环境变量」链路。
        # 通过临时设置 FAN_CONFIG_PATH 让 runtime 完成深合并（它读的就是这个环境变量）。
        previous = os.environ.get("FAN_CONFIG_PATH")
        try:
            if overlay_path:
                os.environ["FAN_CONFIG_PATH"] = overlay_path
            else:
                os.environ.pop("FAN_CONFIG_PATH", None)
            module.read_experiment_config(config_path, allow_overlay=True)
        finally:
            if previous is None:
                os.environ.pop("FAN_CONFIG_PATH", None)
            else:
                os.environ["FAN_CONFIG_PATH"] = previous
        return ""
    except Exception as e:  # noqa: BLE001 - 预检失败不抛异常，改为透传原因
        return str(e)


def _precheck_dependencies(python_exe: str) -> str:
    """启动前预检「选定解释器是否装了 hardware/py 依赖」。

    返回空串表示依赖齐备；否则返回可行动原因（含解释器路径与安装指引）。
    为什么必须在后端侧预检：解释器错了的话，子进程会在 `import fan_serial` 处
    立刻崩，而后端只能靠 stderr 透传（链路长、且早失败窗口约 10s）；
    预检把这一步提前到 start() 同步阶段，前端 ≤1s 就能看到「哪个解释器缺哪个包」。

    数据纪律：**如实报错**，不因缺依赖就回退到模拟执行器（那会造成
    「图在动、风扇没转」的误导）。
    """
    missing = _probe_dependencies(python_exe)
    if not missing:
        return ""
    return (
        f"硬件脚本解释器缺少依赖 {missing}（解释器：{python_exe}）。"
        "请在**该解释器**下执行 "
        f"`\"{python_exe}\" -m pip install -r "
        f"{str(_PY_DIR / 'requirements.txt')}`，"
        "或在 hardware/.env 写 FAN_PYTHON=<已装 pyserial/pyvisa 的解释器绝对路径> "
        "后重启后端。"
    )


# ---------------------------------------------------------------------------
# 运行磁盘态工具（2026-10-12 新增：修「worker 重启丢状态 / 丢单设备锁」）
#
# 背景（2026-10-12 实测）：gunicorn `max_requests=2000` 到阈值时会**优雅替换 worker**
# （uvicorn 把该值透传为 limit_max_requests；实测某 worker 服务到第 2099 个请求时被换下，
# master 存活、日志无异常字样）。而本执行器的运行状态（单设备锁、样本、波形索引）
# 原先**只存进程内存** → 替换即失忆，连锁反应：
#   ① 前端轮询旧轮次 → 404「运行不存在」→ 自动化编排器误判失败并自动重试；
#   ② 单设备锁同步失守 → 重试被放行，与仍在跑（硬件子进程还活着、示波器仍被持有）
#      的旧轮次撞车 → `VI_ERROR_RSRC_BUSY`（2026-10-12 自动化失败事故根因）。
# 修法：运行状态以磁盘 `runs/<id>/` 为准**可重建**；单设备锁**跨进程**判定。
# 磁盘读取只读、不猜不编：events.jsonl / summary.json / 进程表。
# ---------------------------------------------------------------------------

def _runs_root_path() -> Path:
    """运行根目录（= 配置文件同级 `hardware/v0.6/runs`）。

    与 start.py 的推导一致：config 在 `hardware/v0.6/config/`，output.root="../runs"
    解析到 `hardware/v0.6/runs`。FAN_RUNS_ROOT 环境变量可覆盖（分机部署 / 隔离测试用）。
    """
    override = os.environ.get("FAN_RUNS_ROOT")
    if override:
        return Path(override)
    return _CONFIG_DIR.parent / "runs"


def _parse_demo_capture_id(capture_id: str) -> tuple[int, int] | None:
    """解析演示用的 capture_id（形如 `c1_d030`）为 (cycle, duty)。

    约定与 `demo_capture.write_demo_capture` 的目录命名同源：
    `c{cycle}_d{duty:03d}` ↔ `cycle{cycle:04d}_duty{duty:03d}`。
    这样从样本上的 capture_id 就能直接定位到磁盘目录，不需要额外映射表。

    格式不符返回 None —— 未知 id 一律交给路由层回 404，不猜、不编路径。
    """
    try:
        cycle_part, duty_part = capture_id.split("_", 1)
    except (AttributeError, ValueError):
        return None
    if not cycle_part.startswith("c") or not duty_part.startswith("d"):
        return None
    try:
        cycle = int(cycle_part[1:])
        duty = int(duty_part[1:])
    except ValueError:
        return None
    if cycle <= 0 or not 0 <= duty <= 100:
        return None
    return cycle, duty


def _step_response(prev: float, target: float, dt: float,
                   tau: float = 0.12, zeta: float = 0.65) -> float:
    """二阶欠阻尼系统的阶跃响应，用于模拟档位切换时的真实过渡。

    为什么不用一阶惯性：一阶响应是**单调**趋近，画出来仍然是"圆角阶梯"，
    还是假。真实电机/风扇闭环在阶跃指令下会**先冲过头再回落**（超调），
    这是最能一眼看出"真的在控制"的特征。

    tau=0.12 / zeta=0.65 的依据：
      · 超调量 Mp = exp(-pi*zeta/sqrt(1-zeta^2)) ≈ 5%（落在 3~5% 目标区间）
      · 峰值时间 tp = pi/wd = pi/((1/tau)*sqrt(1-zeta^2)) ≈ 0.5s
        —— 0.12 而不是更大的值，是因为档位只持续几秒；tau 太大会让超调峰
        落到下一个档位里，曲线上根本看不到"冲高回落"，等于白做。

    t=0 时返回 prev，t→∞ 时收敛到 target。
    """
    if dt <= 0:
        return prev
    delta = target - prev
    if delta == 0:
        return target
    wn = 1.0 / max(tau, 1e-6)
    wd = wn * math.sqrt(max(1.0 - zeta * zeta, 1e-9))
    dt = min(dt, 8.0 * tau)  # 8τ 后视为稳态，避免 exp 下溢到无意义值
    envelope = math.exp(-zeta * wn * dt)
    return target - delta * envelope * (
        math.cos(wd * dt) + (zeta * wn / wd) * math.sin(wd * dt)
    )


def _iter_events(events_path: Path) -> list[dict]:
    """容错解析 events.jsonl 为事件列表（坏行跳过；文件缺失/不可读返回空表）。"""
    try:
        text = events_path.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict):
            out.append(ev)
    return out


def _run_dir_freshness(run_dir: Path) -> float:
    """运行目录的「最后活动时刻」（epoch 秒）：目录与 events.jsonl mtime 取较大者。

    为什么要 max：运行中 events.jsonl 每 ~10s 追加一次，而目录 mtime 只在新子目录
    （cycleXXX_...）创建时才变化 —— 只看目录 mtime 会把正在跑的轮次误判为"老旧"。
    """
    best = 0.0
    for p in (run_dir, run_dir / "events.jsonl"):
        try:
            best = max(best, p.stat().st_mtime)
        except OSError:
            continue
    return best


def _runner_alive(run_id: str) -> bool:
    """扫 /proc 判断 run_experiment 子进程是否仍存活（cmdline 同时含脚本名与 run_id）。

    为什么扫进程表而不是只信事件里的 processId：processId 可被复用，且存在
    「目录刚建、首事件还没写」的窗口；按 cmdline 精确匹配（run_id 为 32 位 hex，
    几乎不可能误撞）同时覆盖这两种情况。非 Linux（无 /proc）返回 False，
    由调用方按事件文件的新鲜度兜底。
    """
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return False
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if not raw:
            continue
        cmd = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace")
        if "run_experiment" in cmd and run_id in cmd:
            return True
    return False


# ---------------------------------------------------------------------------
# 波形读取（GET /api/fan-tests/{run_id}/captures/{capture_id} 的数据源）
#
# 示波器每次采集把每通道的**真实时序波形**写成 runs/<tag>/<profile>/CH{n}.csv，
# 列为：sample,time_s,voltage_V,current_A（见 scope_capture._save_profile_capture）。
# 这里按需读取，映射成前端可直接绘图的数组。
#
# 数据纪律：文件不存在 / 解析失败 / 列缺失 → 该通道如实返回 available=false + reason，
# **绝不返回伪造或补零数组**；通道未接（如 tach 关闭）同样如实标注。
# ---------------------------------------------------------------------------
# 角色 → 通道语义（与 acceptance.json 的 scope.channels 对应；仅在缺失时作展示名兜底）
_CHANNEL_ROLES = {1: "current", 2: "voltage", 3: "pwm", 4: "tach"}


def _read_wave_csv(csv_path: str) -> dict:
    """读一个 CH{n}.csv 为 {time_s: [...], voltage_v: [...], current_a: [...]|None, points}。

    失败（不存在/空/无表头/无数据行）抛 OSError/ValueError，由调用方转成 available=false。
    只读 4 列里的 3 列（sample 列不用于绘图），逐行 float 解析，非数字行跳过并计数。
    """
    import csv as _csv  # noqa: PLC0415 - 仅此函数用，避免顶层多一个 import

    with open(csv_path, "r", encoding="utf-8", newline="") as fh:
        reader = _csv.DictReader(fh)
        if not reader.fieldnames or "time_s" not in reader.fieldnames or "voltage_V" not in reader.fieldnames:
            raise ValueError("CSV 缺少 time_s / voltage_V 列")
        time_s: list[float] = []
        voltage_v: list[float] = []
        current_a: list[float | None] = []
        has_current = "current_A" in reader.fieldnames
        skipped = 0
        for row in reader:
            try:
                t = float(row["time_s"])
                v = float(row["voltage_V"])
            except (TypeError, ValueError):
                skipped += 1
                continue
            time_s.append(t)
            voltage_v.append(v)
            if has_current:
                raw_c = (row.get("current_A") or "").strip()
                try:
                    current_a.append(float(raw_c) if raw_c else None)
                except ValueError:
                    current_a.append(None)
    if not time_s:
        raise ValueError("CSV 无有效数据行")
    return {
        "time_s": time_s,
        "voltage_v": voltage_v,
        "current_a": current_a if has_current else None,
        "points": len(time_s),
        "skippedRows": skipped,
    }


def _resolve_run_artifact(path: str) -> str:
    """把 artifacts 里的绝对路径重新定位到**本进程可见**的 runs 根目录。

    背景（2026-11-02）：硬件采集改由宿主 sidecar 执行后，`start.py` 写入 events 的
    artifacts 是**宿主绝对路径**（如 /opt/demo-hub/.../runs/<id>/cycle.../CH1.csv），
    而 backend 跑在容器里，同一批文件挂在 /srv/omnitest/c/hardware/v0.6/runs。
    直接 open 必然 ENOENT —— 外部现象就是「波形图一个都拿不到」。

    做法：路径本身可读则原样返回；否则按「runs 之后的相对段」拼到本进程的 runs 根上。
    仍然找不到时返回原路径，让调用方给出真实的错误信息（不掩盖问题）。
    """
    try:
        if os.path.exists(path):
            return path
    except OSError:
        pass
    parts = str(path).replace("\\", "/").split("/")
    if "runs" in parts:
        tail = parts[len(parts) - 1 - parts[::-1].index("runs") + 1:]
        if tail:
            candidate = _runs_root_path().joinpath(*tail)
            try:
                if candidate.exists():
                    return str(candidate)
            except OSError:
                pass
    return path


def read_capture_waveforms(meta: dict) -> dict:
    """按 capture 元数据（含 artifacts 绝对路径）读取各通道真实波形。

    返回 {'available': bool, 'channels': [...], 'notes': [...]}：
      - available=True 表示至少有一个通道读到真实数据；
      - 每个 channel 项：{channel, role, available, reason?, time_s[], voltage_v[], points}
      - 缺通道（如 tach 未开）不出现在 channels 里，notes 里写明原因。
    artifacts 里可能有 pwm/ 与 tach/ 两套（各含 CH{n}.csv）；本接口按文件实际存在读取。
    """
    artifacts = meta.get("artifacts") or []
    channels_out: list[dict] = []
    notes: list[str] = []
    seen_channels: set[int] = set()
    for art in artifacts:
        name = str(art)
        base = os.path.basename(name)
        if not (base.startswith("CH") and base.endswith(".csv")):
            continue
        ch_tag = base[2:-4]
        if not ch_tag.isdigit():
            continue
        channel = int(ch_tag)
        if channel in seen_channels:
            continue
        seen_channels.add(channel)
        role = _CHANNEL_ROLES.get(channel, f"ch{channel}")
        try:
            wave = _read_wave_csv(_resolve_run_artifact(name))
        except (OSError, ValueError) as e:
            channels_out.append({
                "channel": channel, "role": role, "available": False,
                "reason": f"波形文件不可读：{e}", "time_s": [], "voltage_v": [], "points": 0,
            })
            continue
        channels_out.append({
            "channel": channel, "role": role, "available": True,
            "time_s": wave["time_s"], "voltage_v": wave["voltage_v"],
            "current_a": wave.get("current_a"),
            "points": wave["points"], "skippedRows": wave["skippedRows"],
        })

    if not channels_out:
        notes.append("本次采集的 artifacts 里没有可读的 CH{n}.csv（可能未配示波器或采集失败）。")

    channels_out.sort(key=lambda c: c["channel"])
    available = any(c.get("available") for c in channels_out)
    return {"available": available, "channels": channels_out, "notes": notes}


@dataclass
class FanRunState:
    """一次运行的内存态。本阶段不落库，进程重启即失效（与桥凭据同为内存态）。"""

    run_id: str
    simulation: bool
    mode: str  # "finite" | "rolling"
    planned_duration_s: float
    default_duration_s: float
    cycles: int
    steps: list[dict]
    status: str  # preparing / running / stopping / stopped / completed / failed
    samples: list[dict] = field(default_factory=list)
    started_at: float | None = None
    finished_at: float | None = None
    next_sequence: int = 1
    overrun: bool = False
    stop_requested: bool = False
    error: str = ""
    # 是否已到达权威终态（stopped/completed/failed）。前端据此停止轮询，
    # 不再硬编码 status 字符串判断，避免后端新增状态时前端失配。
    terminal: bool = False
    # 真实执行器记录的 run 首事件 startedUtc，作为 t_s 换算基准（ISO 8601 字符串）。
    t0_utc: str | None = None
    # 波形索引（2026-10-09 新增）：capture_id → 该次采集的元数据与真实 CSV 路径。
    # 数据来源为 capture_completed 事件的 data（含 artifacts 绝对路径），只缓存索引，
    # 波形本体在 GET /captures/{id} 时才从磁盘读取（单文件 ~1200 行，按需读）。
    captures: dict[str, dict] = field(default_factory=dict)


class FanExecutor(Protocol):
    """执行器协议。路由层只依赖这组方法，不关心真实/模拟。"""

    def start(self, run_id: str, plan: dict) -> FanRunState:
        """启动一次运行，返回初始状态。"""

    def stop(self, run_id: str) -> None:
        """请求停止一次运行。"""

    def status(self, run_id: str) -> FanRunState:
        """读取当前状态。"""

    def samples(self, run_id: str, after_sequence: int) -> tuple[list[dict], int]:
        """返回 sequence > after_sequence 的增量点，及**已交付样本的最大 sequence**。

        ⚠️ 契约（2026-10-09 修）：返回的游标必须与筛选字段（`s["sequence"]`）**同源**。
        原实现返回 `st.next_sequence`（已追加样本的计数器），而 RealFanExecutor 里样本
        的 sequence 取自 events.jsonl 的**事件序号**（run_started/step_started/
        capture_completed 混编，如 3、7、11…），两者不同源 → 客户端拿计数器当游标
        回头再问，会收到**已经交付过的样本**，曲线上出现重复斜坡、「已采 N 条」虚高。
        """

    def capture_meta(self, run_id: str, capture_id: str) -> dict | None:
        """返回某次采集的波形索引（含真实 CSV 绝对路径），未知则 None。"""

    def has_active_run(self) -> bool:
        """是否已有 running/stopping 状态的运行（单设备锁依据）。"""


def _quality(voltage: str | None, current: str | None, rpm: str | None) -> dict[str, Any]:
    """拼 quality 对象，缺测项附原因（对齐 02_samples.json 的 quality 语义）。"""
    q: dict[str, Any] = {}
    if voltage:
        q["voltage"] = voltage
    if current:
        q["current"] = current
    if rpm:
        q["rpm"] = rpm
    return q


def _planned_duration(steps: list[dict], cycles: int) -> float:
    """计划总时长 = 各步 duration_s 之和 × cycles；cycles<=0 视为无限（返回 0 表示不可算）。"""
    total = sum(float(s.get("duration_s", 0)) for s in steps)
    if cycles <= 0:
        return 0.0
    return total * cycles


class SimFanExecutor:
    """模拟执行器（默认兜底）：后台线程按计划每秒产一个合成点。

    仅用于无仪器时验证链路，产出全部标 `simulation=True`。数值是合成值：
    电压约 4.95V、实测占空比在命令值附近小幅抖动，电流与转速保持 null（未确认）。
    """

    _lock = threading.Lock()
    _runs: dict[str, FanRunState] = {}

    # ---- 以下常量与逻辑**只服务演示执行器**，真实台架（RealFanExecutor）完全不参与 ----
    #: 演示轮次超时余量：超过「计划时长 + 该余量」仍未收敛，判为失控并强制收尾。
    STALE_GRACE_S = 30.0
    #: 采样间隔（秒）。真机约 1s 一点，但演示要"看得见在动"，压到 100ms；
    #: 80 秒计划 → 约 800 点，前端轮询 samples 即可滚动刷新。
    # 2026-11-11 改：0.1 → 10.0。
    # 真机一轮是「4 档 × 每档 2 次采集」= 8 个样本（单次采集约 10s）；
    # 0.1s 产点会在 80s 内堆出 ~800 个点，趋势图变成密线，与真机形态完全不同，
    # 一眼就能看出是假的。改成 10s 后每档 2 点、一轮 8 点，与真机同构。
    SAMPLE_INTERVAL_S = 10.0
    #: 合成波形采样点数。取真实示波器单文件量级（约 1200 行），
    #: 这样前端「每个数据都显示」时是一条有细节的曲线，而不是几根折线。
    DEMO_WAVE_POINTS = 1200
    #: 合成波形时间窗与 PWM 频率（25kHz × 48ms ≈ 1200 点，覆盖整周期群）。
    DEMO_WAVE_WINDOW_S = 0.048
    DEMO_PWM_FREQ_HZ = 25000
    #: 与真实样本一致的量级（见 _run_loop 里的 sample 构造）。
    DEMO_VOLTAGE_BASE_V = 4.95
    DEMO_CURRENT_PROBE_V = 0.003
    DEMO_PWM_HIGH_V = 3.3

    def _reap_stale_runs(self) -> list[str]:
        """把明显超时且仍未收敛的**演示**轮次强制收尾，返回被收尾的 run_id。

        为什么需要它：`_run_loop` 跑在后台 daemon 线程里，一旦它因为意外退出
        而没有落终态，内存里的 status 会永远停在 running，单设备锁再也不释放 ——
        演示时的表现就是「409 已有风扇实验在进行」，而且重启前端毫无作用，
        只能重启后端。有了这一步，锁会自己恢复。

        只处理演示执行器自己的内存态；planned_duration_s<=0（rolling 模式）
        不参与回收，避免把「本来就该一直跑」的轮次误杀。
        """
        now = time.monotonic()
        reaped: list[str] = []
        with self._lock:
            for rid, st in self._runs.items():
                if st.status not in ("running", "stopping"):
                    continue
                planned = float(st.planned_duration_s or 0)
                if planned <= 0:
                    continue
                started = st.started_at or now
                if now - started <= planned + self.STALE_GRACE_S:
                    continue
                st.status = "completed"
                st.terminal = True
                st.stop_requested = True
                st.finished_at = now
                st.overrun = True
                st.error = "演示轮次超时未收尾，已由单设备锁自愈回收"
                reaped.append(rid)
        if reaped:
            logger.warning("[fan-executor] sim 自愈回收超时轮次: %s", ", ".join(reaped))
        return reaped

    def has_active_run(self) -> bool:
        with self._lock:
            return any(s.status in ("running", "stopping") for s in self._runs.values())

    def active_runs(self) -> list[dict]:
        """列出当前占用单设备锁的**演示**轮次摘要。

        前端据此显示「实验进行中（还剩 xx 秒）」，避免演示时盲点再点一次、
        拿到 409 还不知道为什么。真实执行器不带这个方法，路由层用 getattr 兜底
        返回空列表 —— 演示与真实在这里也是隔离的。
        """
        now = time.monotonic()
        items: list[dict] = []
        with self._lock:
            for rid, st in self._runs.items():
                if st.status not in ("running", "stopping"):
                    continue
                elapsed = now - (st.started_at or now)
                planned = float(st.planned_duration_s or 0)
                items.append({
                    "run_id": rid,
                    "status": st.status,
                    "simulation": st.simulation,
                    "elapsed_s": round(elapsed, 1),
                    "planned_duration_s": planned,
                    "remain_s": max(0.0, round(planned - elapsed, 1)) if planned else 0.0,
                    "samples": len(st.samples),
                })
        items.sort(key=lambda x: x["elapsed_s"], reverse=True)
        return items

    def _takeover_active_runs(self) -> list[str]:
        """把仍在 running/stopping 的**演示**轮次收尾，允许新轮次直接接管。

        为什么演示允许抢占、真机不允许
        ------------------------------
        真机上「同一时刻只能有一轮实验」是**硬件硬约束**，抢了就是两台实验互相干扰，
        所以 RealFanExecutor 的 409 必须保留。
        但演示里用户点两次「自动测试」是正常操作（甚至流程会自动重跑），
        弹「409 已有风扇实验在进行」纯属把真机的物理限制泄漏到演示体验里。

        为什么是"真收尾"而不是"假装拿到锁"
        --------------------------------
        若只改锁标志而旧轮次还在跑，两轮会同时往同一条 samples 队列写，
        前端图会花、报告也会串档。这里置 stop_requested=True，
        旧轮次的 _run_loop 下一拍就会退出，不再产样本。
        """
        now = time.monotonic()
        taken: list[str] = []
        with self._lock:
            for rid, st in self._runs.items():
                if st.status not in ("running", "stopping"):
                    continue
                st.status = "stopped"
                st.stop_requested = True
                st.terminal = True
                st.finished_at = now
                st.error = "演示重跑：旧轮次已被新轮次接管"
                taken.append(rid)
        if taken:
            logger.info("[fan-executor] 演示接管，已收尾旧轮次: %s", ", ".join(taken))
        return taken

    def start(self, run_id: str, plan: dict) -> FanRunState:
        # 演示语义：重跑是常态，不是冲突。先接管旧轮次，再启动新的。
        # （超时自愈在 takeover 里已覆盖；单独保留 reap 是为了清理"没有新轮次也要收"的场景）
        self._reap_stale_runs()
        self._takeover_active_runs()
        steps = plan.get("steps") or DEFAULT_STEPS
        cycles = int(plan.get("cycles", 1))
        duration = _planned_duration(steps, cycles)
        state = FanRunState(
            run_id=run_id,
            simulation=True,
            mode=plan.get("mode", "finite"),
            planned_duration_s=duration or float(plan.get("default_duration_s", 60)),
            default_duration_s=float(plan.get("default_duration_s", 60)),
            cycles=cycles,
            steps=steps,
            status="running",
            started_at=time.monotonic(),
        )
        with self._lock:
            self._runs[run_id] = state

        # 运行中就把合成波形落盘（只写波形+标记，不写 events）：
        # 演示时启动后立刻能看到波形，不必等整轮结束。
        # events=False 是为了不写入 run_finished —— 否则磁盘态会把"还在跑"判成已收尾。
        # 失败不影响运行：少一张图不该让整轮实验失败。
        try:
            from app.db.session import get_demo_dataset  # noqa: PLC0415 - 避免模块级循环导入
            from app.services.demo_capture import write_demo_capture  # noqa: PLC0415

            write_demo_capture(run_id, steps, get_demo_dataset(), events=False)
        except BaseException as exc:  # noqa: BLE001 - 出图失败不得拖垮实验
            logger.warning("[fan-executor] sim 预生成波形失败（不影响运行）：%r", exc)

        threading.Thread(target=self._run, args=(run_id,), daemon=True).start()
        logger.info("[fan-executor] sim run %s started (simulation=True)", run_id)
        return state

    def stop(self, run_id: str) -> None:
        with self._lock:
            st = self._runs.get(run_id)
            if not st or st.terminal:
                return
            st.stop_requested = True
            st.status = "stopping"

    def status(self, run_id: str) -> FanRunState:
        with self._lock:
            return self._runs.get(run_id, FanRunState(run_id=run_id, simulation=True, mode="finite", planned_duration_s=0, default_duration_s=60, cycles=0, steps=[], status="unknown"))

    def samples(self, run_id: str, after_sequence: int) -> tuple[list[dict], int]:
        with self._lock:
            st = self._runs.get(run_id)
            if st is None:
                return [], after_sequence
            picked = [s for s in st.samples if s["sequence"] > after_sequence]
            # 游标 = 已交付样本的最大 sequence（与筛选字段同源，见 Protocol 说明）。
            # sim 的 sequence 本就是 1,2,3…（与 next_sequence 同源），故行为等价。
            latest = picked[-1]["sequence"] if picked else after_sequence
            return picked, max(after_sequence, latest)

    def capture_meta(self, run_id: str, capture_id: str) -> dict | None:
        """从演示采集目录里解析某档位的波形索引。

        波形文件由 `demo_capture.write_demo_capture` 按**与真实采集同构**的目录结构落盘
        （`cycle{idx}_duty{duty}/pwm/CH*.csv` + `tach/CH4.csv`），所以这里只负责
        「capture_id → 目录 → 文件清单」这一步索引，波形本体仍由路由层既有的
        `read_capture_waveforms` 读取 —— 演示与真实共用同一条读取链路，不开后门。

        capture_id 形如 `c1_d030`（第 1 档 / 占空比 30%）。
        目录不存在（本轮还没落盘、或已清理）时返回 None，由路由层如实回 404，
        绝不编造路径。
        """
        parsed = _parse_demo_capture_id(capture_id)
        if parsed is None:
            return None
        cycle, duty = parsed
        run_dir = _runs_root_path() / run_id
        cycle_dir = run_dir / f"cycle{cycle:04d}_duty{duty:03d}"
        if not cycle_dir.is_dir():
            return None
        artifacts = sorted(str(p) for p in cycle_dir.rglob("CH*.csv"))
        if not artifacts:
            return None
        stamp = None
        marker = run_dir / ".demo-marker"
        if marker.is_file():
            try:
                stamp = json.loads(marker.read_text(encoding="utf-8")).get("generatedAt")
            except (OSError, ValueError):
                stamp = None
        return {
            "capture_id": capture_id,
            "cycle": cycle,
            "profile": f"duty{duty:03d}",
            "commanded_pwm_pct": duty,
            "artifacts": artifacts,
            "startedUtc": stamp,
            "finishedUtc": stamp,
            # 演示标记贯穿到 meta：排查时一眼能看出这是合成数据
            "simulation": True,
        }

    def _run(self, run_id: str) -> None:
        """线程入口：**无论正常结束还是异常，都必须把内存态落到终态**。

        `_run_loop` 跑在 daemon 线程里，抛出的异常不会回传到请求线程。
        如果不在这里兜底，一旦异常，status 会永久停在 running，
        单设备锁再也不释放 —— 这正是「409 已有风扇实验在进行」的来源。
        """
        try:
            self._run_loop(run_id)
        except BaseException as exc:  # noqa: BLE001 - 线程入口必须兜住一切
            logger.exception("[fan-executor] sim run %s 异常终止", run_id)
            with self._lock:
                st = self._runs.get(run_id)
                if st is not None and not st.terminal:
                    st.status = "failed"
                    st.terminal = True
                    st.error = repr(exc)
                    st.finished_at = time.monotonic()
        finally:
            # 二次保险：任何路径退出都要有终态，绝不留 running 占着锁
            with self._lock:
                st = self._runs.get(run_id)
                if st is not None and not st.terminal:
                    st.status = "completed"
                    st.terminal = True
                    st.finished_at = st.finished_at or time.monotonic()

    # 真机实测转速锚点（2026-11-06/11-11 两次采集一致）：
    #   30% → 745  |  50% → 1245  |  70% → 1690  |  100% → 2226 rpm
    # 演示要「像真的」，转速必须随档位单调上升且落在真机量级，不能是 None。
    _DEMO_RPM_ANCHORS = ((0, 0), (30, 745), (50, 1245), (70, 1690), (100, 2226))

    @classmethod
    def _demo_rpm(cls, pwm: int, seq: int) -> int | None:
        """按档位插值出合成转速，叠加 ±0.6% 抖动（真机同档重复性 <1%）。"""
        if pwm <= 0:
            return None  # 0% 档风扇停转，真实数据同样是 None
        pts = cls._DEMO_RPM_ANCHORS
        for i in range(1, len(pts)):
            x0, y0 = pts[i - 1]
            x1, y1 = pts[i]
            if pwm <= x1:
                ratio = (pwm - x0) / (x1 - x0) if x1 > x0 else 0.0
                base = y0 + (y1 - y0) * ratio
                break
        else:
            base = pts[-1][1]
        jitter = 1.0 + 0.006 * ((seq * 37 % 21) - 10) / 10.0
        return int(round(base * jitter))

    def _run_loop(self, run_id: str) -> None:
        with self._lock:
            st = self._runs[run_id]
        # 展开计划：cycles<=0 视为 rolling（无限循环），此处按单轮有限时长生成
        step_list: list[dict] = []
        cycles = st.cycles if st.cycles > 0 else 1
        for _ in range(cycles):
            step_list.extend(st.steps)

        # 以启动时刻为单调时钟原点；每 SAMPLE_INTERVAL_S 产一个点，t_s 取测量中点
        start_mono = st.started_at or time.monotonic()
        step_idx = 0
        t_in_step = 0.0
        current_pwm = None
        # 当前档位对应的合成波形 capture_id；每切换档位重新生成一份
        current_capture_id: str | None = None

        # 确定性噪声（与 demo_capture 共用同一份实现，避免两套随机源行为不一致）
        from app.services.demo_capture import _noise as _demo_noise  # noqa: PLC0415

        # 阶跃过渡状态：档位切换时从「上一拍的实测值」出发，按二阶响应逼近新目标
        last_pwm: int | None = None
        transit_started = 0.0
        transit_from = 0.0
        measured_prev = 0.0
        while True:
            with self._lock:
                if st.stop_requested:
                    st.status = "stopped"
                    st.finished_at = time.monotonic()
                    st.terminal = True
                    break
                if st.status not in ("running", "stopping"):
                    break

            elapsed = time.monotonic() - start_mono
            # 推进当前档位
            if step_idx < len(step_list):
                step = step_list[step_idx]
                current_pwm = int(step.get("commanded_pwm_pct", 0))
                # 该档位对应的合成波形 capture_id（目录由 write_demo_capture 落盘）。
                # 多轮时按档位序号取模，映射回同一批目录 —— 演示通常 cycles=1。
                cycle_no = step_idx % max(len(st.steps), 1) + 1
                current_capture_id = f"c{cycle_no}_d{current_pwm:03d}"
                if elapsed >= step.get("duration_s", 10) + t_in_step:
                    t_in_step += step.get("duration_s", 10)
                    step_idx += 1
                    continue
            else:
                # 计划跑完，标记 completed 后退出
                with self._lock:
                    st.status = "completed"
                    st.finished_at = time.monotonic()
                    st.terminal = True
                    # 若实际耗时超计划，标 overrun
                    if _planned_duration(st.steps, st.cycles) and elapsed > _planned_duration(st.steps, st.cycles):
                        st.overrun = True
                break

            # ---- 合成采样点 ----
            # 三条原则（都是为了消掉"一眼假"）：
            #   ① 档位切换不走直角：按二阶欠阻尼响应过渡，带 3~5% 超调后回落
            #   ② 稳态值叠加白噪声：模拟传感器抖动与 ADC 量化
            #   ③ 电压/探针电压随占空比变化：不是写死的常量
            t_s = round(elapsed, 3)
            pwm = current_pwm if current_pwm is not None else 0
            seq = st.next_sequence

            if last_pwm != pwm:
                transit_started = elapsed
                transit_from = measured_prev
                last_pwm = pwm

            # 真机每档采样间隔约 10s，早已越过阶跃过渡期，采到的都是稳态值；
            # 若照搬过渡曲线，切换后首点会读到「上一档的值」（实测出现命令 50 而实测 30），
            # 与真机形态不符。故演示点直接取稳态目标 + 噪声。
            # 另：真机固件会把 100% 钳到 99%，实测落在 98.0~98.2，这里一并还原。
            base_duty = 98.0 if pwm >= 100 else float(pwm)
            measured_cmd = base_duty
            # clamp 到 [0,100]：二阶超调会把低档起始值算成负数（实测出现过 -0.01%），
            # 物理上不存在负占空比，真机数据也从未出现。
            measured = round(min(100.0, max(0.0, measured_cmd + _demo_noise(seq, 0, 0.22))), 2)
            measured_prev = measured

            # 母线电压：4.95V 基线 + 纹波噪声（恒定值画出来是一条死直线）
            # 母线电压随负载下降（真机实测 30%→5.05V、100%→4.92V，负载压降约 0.13V）。
            # 之前用恒定 4.95 画出来是一条死平线，与真机「随档位轻微下滑」的趋势不符，容易被看出。）
            voltage = round(5.06 - 0.0014 * pwm + _demo_noise(seq, 1, 0.011), 3)
            # 电流探头电压：随占空比抬升（保持 mV 量级）+ 噪声
            probe = round(0.003 + 0.00004 * pwm + _demo_noise(seq, 2, 0.00018), 5)

            sample = {
                "sequence": seq,
                "t_s": t_s,
                # 测量窗口按采样间隔的一半计，比固定 0.1s 更贴近实际节奏
                "measurement_started_t_s": round(t_s - self.SAMPLE_INTERVAL_S / 2, 3),
                "measurement_finished_t_s": round(t_s + self.SAMPLE_INTERVAL_S / 2, 3),
                "commanded_pwm_pct": pwm,
                "voltage_v": voltage,
                "current_probe_v": probe,
                "current_a": None,  # 换算未确认，不编值
                "measured_pwm_duty_pct": measured,
                # 真机 100% 档同样能测到频率（实测 24945~24969Hz），
                # 只有 0% 档因无开通脉冲才为 None —— 与真机对齐。
                "pwm_frequency_hz": round(24955 + _demo_noise(seq, 3, 12)) if pwm > 0 else None,
                # 转速按真机实测曲线合成（30/50/70/100% → 745/1245/1690/2226 rpm）
                "rpm": self._demo_rpm(pwm, seq),
                # simulation 必须显式为 True：项目数据纪律要求模拟数据可被下游识别，
                # 之前缺这个字段导致前端拿到 None，无法区分真假。
                "simulation": True,
                "quality": _quality("provisional_probe_ratio", "conversion_not_confirmed",
                                    "synthesized" if pwm > 0 else "not_connected"),
                # 关联到该档位的合成波形，前端点样本即可取到 CH1-CH4
                "capture_id": current_capture_id,
            }
            with self._lock:
                st.samples.append(sample)
                st.next_sequence += 1
            time.sleep(self.SAMPLE_INTERVAL_S)


class RealFanExecutor:
    """真实执行器（`FAN_EXECUTOR=real` 启用）：调用仪器电脑硬件脚本，读真实事件流。

    脚本与配置路径：默认按项目相对位置推导（Python 跨平台版 `hardware/py/entrypoints/`），
    项目整体移动/换机器后无需改路径。环境变量可覆盖（例如硬件部署在另一台仪器电脑时）：
      FAN_START_SCRIPT    start.py 路径（可选，默认 hardware/py/entrypoints/start.py）
      FAN_STOP_SCRIPT     stop.py 路径（可选，默认 hardware/py/entrypoints/stop.py）
      FAN_CONFIG_PATH     config 路径（可选，默认 hardware/v0.6/config/acceptance.json）
      FAN_PYTHON          Python 解释器（可选，默认 sys.executable；分机场景指定仪器机 Python）

    数据只来自 `events.jsonl` 里 `capture_completed` 事件的 `data.metrics`，原样映射，
    不加减数值。终态以 `summary.json` 的 `terminalPublished:true` 为准。
    """

    _lock = threading.Lock()
    _runs: dict[str, FanRunState] = {}
    # 缺 sequence 事件的告警去重集合（按 event type），避免每轮轮询刷屏。
    _warned_missing_seq: set[str] = set()
    # _watch 等待终态的总超时（秒）：超过即强制收敛为 failed，杜绝无限轮询。
    # 2026-10-09 上调 120 → 240：硬件改为每档连续多次采集（capturesPerStep，默认 5），
    # 单轮时长明显变长（每档 settle + 多次 VISA 采集），120s 会把正常在跑的轮次
    # 误判为超时失败。上限用「实际时长 + 余量」估算：4 档 × (2s settle + 5 × ~3s 采集)
    # ≈ 70s，再叠加 CH4 档与抖动，240s 足够；仍可被环境变量 FAN_WATCH_TIMEOUT_S 覆盖。
    WATCH_TIMEOUT_S = float(os.environ.get("FAN_WATCH_TIMEOUT_S") or 240.0)
    # 早失败窗口（秒）：启动后此时间内既无事件流文件、进程也已退出 → 不等满超时，
    # 立即透传可行动原因（查 runs/<id>/stderr.log），让前端 ≤10s 看到真实失败。
    EARLY_FAIL_S = 10.0
    # ---- 磁盘态判定窗口（2026-10-12 新增，供 _rebuild_state / 跨进程锁共用）----
    # DISK_FRESH_S：运行中 events.jsonl 每 ~10s 追加一次，45s 无更新基本可判"已停"；
    # DISK_SETTLING_S：收尾宽限 —— 进程刚退出、终态文件可能正在落盘，先按 running 报，
    #                 下一轮轮询就会读到终态（宁可晚一拍，也不误报"中断"）。
    DISK_FRESH_S = 45.0
    DISK_SETTLING_S = 30.0

    def _cfg(self) -> tuple[str, str, str, str]:
        """返回 (start_script, stop_script, config_path, overlay_path)。

        config_path 是**主配置**（跨机器通用）；overlay_path 是本机差异片段，
        通过子进程环境变量 FAN_CONFIG_PATH 注入，让 start.py 的 allow_overlay
        分支完成深合并（见 _resolve_overlay_path 的设计说明）。
        """
        # 环境变量优先（覆盖场景：硬件部署在别处）；未设则用项目相对路径推导。
        start = os.environ.get("FAN_START_SCRIPT") or str(_DEFAULT_START_SCRIPT)
        stop = os.environ.get("FAN_STOP_SCRIPT") or str(_DEFAULT_STOP_SCRIPT)
        config = _select_config_path()
        overlay = _resolve_overlay_path()
        return start, stop, config, overlay

    def has_active_run(self) -> bool:
        """单设备锁：内存活跃 OR 磁盘上有活跃运行（2026-10-12 跨进程化）。

        为什么必须含磁盘判定：worker 被 gunicorn 优雅替换后内存锁清空，但硬件子进程
        （run_experiment）仍在跑、示波器仍被持有 —— 只信内存会放行并发启动，直接撞出
        `VI_ERROR_RSRC_BUSY`（2026-10-12 自动化失败事故的根因链之一）。
        """
        return self._active_run_id() is not None

    def _active_run_id(self) -> str | None:
        """当前活跃（running/stopping）运行的 run_id；无则 None。内存优先、磁盘兜底。"""
        with self._lock:
            for rid, s in self._runs.items():
                if s.status in ("running", "stopping"):
                    return rid
        return self._disk_active_run_id()

    def _disk_active_run_id(self) -> str | None:
        """扫 runs/ 目录找「仍在跑」的轮次：无终态证据 且（进程存活 或 文件新鲜）。

        只扫最近更新的前 20 个目录 —— 活跃轮次每 ~10s 写一次事件，必然在列；
        更旧的目录（>1h 无更新）按列表有序性直接短路。判定**只读**，不写任何文件。
        """
        runs_root = _runs_root_path()
        if not runs_root.is_dir():
            return None
        try:
            cands: list[tuple[float, Path]] = []
            for p in runs_root.iterdir():
                if p.is_dir():
                    cands.append((_run_dir_freshness(p), p))
        except OSError:
            return None
        cands.sort(key=lambda t: t[0], reverse=True)
        with self._lock:
            in_memory_active = {
                rid for rid, s in self._runs.items() if s.status in ("running", "stopping")
            }
        now = time.time()
        for mtime, d in cands[:20]:
            rid = d.name
            if rid in in_memory_active:
                continue  # 内存检查已覆盖（防御性：正常不会走到）
            if now - mtime > 3600:
                break  # 列表按新鲜度降序，后面只会更旧
            if self._dir_has_terminal(d):
                continue
            if _runner_alive(rid):
                return rid
            if now - mtime < self.DISK_FRESH_S:
                return rid
        return None

    @staticmethod
    def _dir_has_terminal(run_dir: Path) -> bool:
        """该运行目录是否已有终态证据（summary.json terminalPublished 或 run_finished 事件）。

        有终态 = 该轮已收尾：不占单设备锁、重建时直接落终态。
        """
        try:
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
            if summary.get("terminalPublished"):
                return True
        except (OSError, json.JSONDecodeError):
            pass
        for ev in _iter_events(run_dir / "events.jsonl"):
            if ev.get("type") == "run_finished":
                return True
        return False

    def _rebuild_state(self, run_id: str) -> FanRunState | None:
        """从磁盘重建一次运行的状态（2026-10-12 新增：修 worker 重启后「运行不存在」）。

        使用场景：worker 被优雅替换后内存失忆，但前端仍会轮询（status / samples /
        capture_meta）。此时按 `runs/<run_id>/` 的**真实文件**重建：
          · events.jsonl   —— 计划参数（run_started）、样本与波形索引（capture_completed）、
                              终态（run_finished）；
          · summary.json   —— 权威终态（terminalPublished:true）；
          · 进程表 / mtime —— 无终态证据时二分「仍在跑」还是「被中断」，如实标注，不假装。
        返回 None 表示磁盘上也没有该运行的痕迹（调用方维持 unknown → 404）。

        ⚠️ 重建结果**不缓存**：运行可能仍在推进，每次调用按最新文件重建（事件文件
        40KB 级、轮询 1Hz，成本可忽略），避免「缓存了却无人更新」把状态冻死。
        """
        run_dir = _runs_root_path() / run_id
        if not run_dir.is_dir():
            return None
        events_path = run_dir / "events.jsonl"
        events = _iter_events(events_path)

        st = FanRunState(
            run_id=run_id, simulation=False, mode="finite",
            planned_duration_s=0.0, default_duration_s=60.0, cycles=0, steps=[],
            status="running",
        )
        # 计划参数与终态：从事件流读取（run_started / run_finished，后到者覆盖）。
        started_ev: dict = {}
        finished_ev: dict = {}
        for ev in events:
            etype = ev.get("type")
            if etype == "run_started" and not started_ev:
                started_ev = ev.get("data") or {}
            elif etype == "run_finished":
                finished_ev = ev.get("data") or {}

        steps = [
            {"duration_s": float(started_ev.get("holdSeconds") or 0), "commanded_pwm_pct": d}
            for d in (started_ev.get("dutiesPercent") or [])
        ]
        st.cycles = int(started_ev.get("requestedCycles") or 1)
        st.default_duration_s = float(started_ev.get("holdSeconds") or 60)
        if steps:
            st.steps = steps
            st.planned_duration_s = _planned_duration(steps, st.cycles)

        # 样本与波形索引：复用 _drain_events（与实时路径同一套映射，不另写第二实现）。
        self._drain_events(st, str(events_path), 0)

        # 终态三级判定：summary（权威）→ run_finished → 进程/新鲜度兜底。
        summary: dict | None
        try:
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            summary = None
        if summary and summary.get("terminalPublished"):
            state = summary.get("state")
            st.status = state if state in ("completed", "stopped", "failed") else "failed"
            if st.status == "failed":
                st.error = summary.get("failureMessage") or "运行失败（未提供原因）"
            st.terminal = True
        elif finished_ev:
            state = finished_ev.get("state")
            st.status = state if state in ("completed", "stopped", "failed") else "failed"
            if st.status == "failed":
                st.error = finished_ev.get("failureMessage") or ""
            st.terminal = True
        else:
            # 无终态证据：按「仍在跑 or 被中断」二分，如实标注（不假装成功/失败）。
            age = time.time() - _run_dir_freshness(run_dir)
            if _runner_alive(run_id) or age < self.DISK_SETTLING_S:
                st.status = "running"
            else:
                st.status = "failed"
                st.error = (
                    "运行被中断：采集进程已退出，且未产出收尾事件"
                    "（多为服务/容器重启或脚本异常终止；已采数据仍可读）。"
                )
                st.terminal = True
        self._restore_timing(st, events)
        return st

    @staticmethod
    def _restore_timing(st: FanRunState, events: list[dict]) -> None:
        """用事件流时间戳回推 started_at / finished_at（仅供展示的时长换算）。

        FanRunState 的起止时刻与 time.monotonic() 同尺度（实时路径如此），这里反推
        一个等价基准，使 _status_dict 的 actual_duration_s 对重建出来的轮次同样成立：
          · 终态：started_at = now - (末事件时刻 - 首事件时刻)，finished_at = now → 时长为真实跨度；
          · 运行中：started_at = now - (当前时刻 - 首事件时刻) → 时长随真实时间继续增长。
        只用事件里真实存在的 timestampUtc；一个都没解析出来时保持 None（显示 0）。
        """
        from datetime import datetime, timezone  # noqa: PLC0415 - 仅此处使用

        def _epoch(s: Any) -> float | None:
            try:
                return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
            except (ValueError, TypeError):
                return None

        stamps = [t for t in (_epoch(ev.get("timestampUtc")) for ev in events) if t is not None]
        if not stamps:
            return
        now_mono = time.monotonic()
        if st.terminal:
            span = max(0.0, stamps[-1] - stamps[0])
            st.started_at = now_mono - span
            st.finished_at = now_mono
        else:
            now_epoch = datetime.now(timezone.utc).timestamp()
            st.started_at = now_mono - max(0.0, now_epoch - stamps[0])
            st.finished_at = None

    def start(self, run_id: str, plan: dict) -> FanRunState:
        active = self._active_run_id()
        if active:
            raise ConflictException(f"已有风扇实验在进行（{active}），请先停止再启动")
        start_script, stop_script, config_path, overlay_path = self._cfg()
        # 启动前预检：配置解析失败（如 serial.port 为空、overlay 缺失）时同步返回明确原因，
        # 不让子进程退出码 1 静默失败（那样要等 ≥10s 早失败窗口且原因可能缺失）。
        problem = _precheck_config(config_path, overlay_path)
        if problem:
            logger.warning(
                "[fan-executor] 配置预检未通过（config=%s, overlay=%s）：%s",
                config_path, overlay_path or "(无)", problem,
            )
            raise BadRequestException(f"风扇实验配置无效：{problem}")
        # 依赖预检（2026-10-09 新增，风扇不转的致命根因防线）：
        # 选定解释器必须能 import serial + pyvisa，否则子进程会立刻崩、风扇不转。
        # 放在配置预检之后：配置错先报配置，依赖错再报依赖，原因逐层收敛。
        dep_problem = _precheck_dependencies(_PYTHON)
        if dep_problem:
            logger.warning(
                "[fan-executor] 依赖预检未通过（python=%s）：%s", _PYTHON, dep_problem,
            )
            raise BadRequestException(f"风扇实验无法启动：{dep_problem}")
        logger.info(
            "[fan-executor] 使用配置：主配置=%s，overlay=%s，解释器=%s",
            config_path, overlay_path or "(无)", _PYTHON,
        )
        steps = plan.get("steps") or DEFAULT_STEPS
        cycles = int(plan.get("cycles", 1))
        state = FanRunState(
            run_id=run_id,
            simulation=False,
            mode=plan.get("mode", "finite"),
            planned_duration_s=_planned_duration(steps, cycles) or float(plan.get("default_duration_s", 60)),
            default_duration_s=float(plan.get("default_duration_s", 60)),
            cycles=cycles,
            steps=steps,
            status="running",
            started_at=time.monotonic(),
        )
        with self._lock:
            self._runs[run_id] = state
        threading.Thread(
            target=self._watch,
            args=(run_id, start_script, stop_script, config_path, overlay_path),
            daemon=True,
        ).start()
        logger.info("[fan-executor] real run %s started via %s", run_id, start_script)
        return state

    def stop(self, run_id: str) -> None:
        """请求停止一次运行。

        ⚠️ 已到终态（terminal）的运行**不再改动状态**（2026-10-09 修）：
        原实现无条件 `status = "stopping"`，会把已经 failed/completed/stopped 的运行
        「复活」成非终态；而 `has_active_run()` 依据 status in (running, stopping) 判单设备锁，
        于是这一复活会让锁**永久占住** → 之后每次启动都 409「已有风扇实验在进行」。
        实测复现：前端在 run 失败（terminal）后仍会调一次 /stop（running→estopped 边沿），
        正好命中该路径。修法：终态直接返回，不改状态、不置 stop_requested。

        2026-10-12 补：内存无记录（worker 重启后）的运行走**磁盘重建**分支 ——
        确认该轮仍活跃后直接调 stop.py 下发停止请求（stop.request + SET 0 等 ACK），
        稍后 status 轮询由重建读到 run_finished(state=stopped) 如实收敛。
        """
        with self._lock:
            st = self._runs.get(run_id)
            if st is not None:
                if st.terminal:
                    return
                st.stop_requested = True
                st.status = "stopping"
                return
        rebuilt = self._rebuild_state(run_id)
        if rebuilt is None or rebuilt.terminal:
            return
        threading.Thread(target=self._stop_rebuilt, args=(run_id,), daemon=True).start()

    def _stop_rebuilt(self, run_id: str) -> None:
        """对「磁盘重建出来的活跃运行」下发停止请求（后台线程，不阻塞请求线程）。

        _request_stop 内部 subprocess.run 可能阻塞数秒~60s，必须在锁外/线程内执行。
        run 目录按运行根目录推导（与 _rebuild_state 同源），meta 只带 directory。
        """
        try:
            _start, stop_script, config_path, _overlay = self._cfg()
            run_dir = _runs_root_path() / run_id
            self._request_stop(stop_script, run_id, config_path, {"directory": str(run_dir)})
            logger.info("[fan-executor] 磁盘重建运行 %s 已下发停止请求", run_id)
        except Exception as e:  # noqa: BLE001 - 后台线程须吞异常
            logger.warning("[fan-executor] 磁盘重建运行 %s 停止请求失败：%s", run_id, e)

    def status(self, run_id: str) -> FanRunState:
        with self._lock:
            st = self._runs.get(run_id)
        if st is not None:
            return st
        # worker 重启后内存失忆 → 从磁盘重建（不缓存，见 _rebuild_state 说明）
        rebuilt = self._rebuild_state(run_id)
        if rebuilt is not None:
            return rebuilt
        return FanRunState(run_id=run_id, simulation=False, mode="finite", planned_duration_s=0, default_duration_s=60, cycles=0, steps=[], status="unknown")

    def samples(self, run_id: str, after_sequence: int) -> tuple[list[dict], int]:
        def _pick(st: FanRunState) -> tuple[list[dict], int]:
            picked = [s for s in st.samples if s["sequence"] > after_sequence]
            # ⚠️ 游标必须取「已交付样本的最大 sequence」，**不能**用 st.next_sequence：
            # 样本的 sequence 取自 events.jsonl 事件序号（见 _drain_events 的 `"sequence": seq`），
            # 而 next_sequence 是「已追加样本的计数器」，两者不同源。用计数器当游标会让
            # 客户端下一轮收到已交付过的样本 → 曲线重复、「已采 N 条」虚高（2026-10-09 修）。
            latest = picked[-1]["sequence"] if picked else after_sequence
            return picked, max(after_sequence, latest)

        with self._lock:
            st = self._runs.get(run_id)
            if st is not None:
                return _pick(st)
        # worker 重启后内存失忆 → 磁盘重建（复用同一套映射与游标口径）
        rebuilt = self._rebuild_state(run_id)
        if rebuilt is None:
            return [], after_sequence
        return _pick(rebuilt)

    def capture_meta(self, run_id: str, capture_id: str) -> dict | None:
        """返回某次采集的波形索引（含真实 CSV 绝对路径）；未采到的 id 返回 None。

        内存有记录时读内存索引（由 _drain_events 从 capture_completed 事件的 artifacts
        建立）；worker 重启后内存无记录时按磁盘重建（2026-10-12 补），仍**不做路径猜测、
        不猜文件名**——未知即 None，由路由层如实返回 available=false。
        """
        with self._lock:
            st = self._runs.get(run_id)
        if st is None:
            st = self._rebuild_state(run_id)
        if st is None:
            return None
        return st.captures.get(capture_id)

    def _watch(
        self, run_id: str, start_script: str, stop_script: str,
        config_path: str, overlay_path: str = "",
    ) -> None:
        """后台线程：spawn entrypoints/start.py → 轮询 events.jsonl → 解析 capture_completed → 收敛终态。

        终态收敛三重兜底（2026-10-06 补，修「脚本已失败但前端无限轮询」）：
          ① 进程已退出（proc.poll() 非空）→ 按 summary 收敛，summary 缺失按事件流；
          ② _drain_events 见到 run_finished 事件 → 标记脚本已收尾，下一轮强制判定；
          ③ 总超时 120 秒仍无终态 → 置 failed + terminal，error 写明超时。
        任一兜底命中即收敛，绝不无限轮询。
        """
        with self._lock:
            st = self._runs[run_id]
        stderr_file: Any = None
        try:
            # 启动硬件脚本（Python 版）。stderr 改为**捕获到临时文件**（2026-10-08 改）：
            # 原用 DEVNULL，但 start.py 在「建运行目录之前」失败时（如配置为空）不会写出
            # runs/<id>/stderr.log，后端便无法透传真实原因，前端只看到"退出码 1 无收尾"。
            # 为什么用临时文件而非 PIPE：stderr=PIPE 若不持续读满会撑满管道缓冲导致子进程
            # 阻塞（死锁隐患）；落文件既不阻塞子进程，又能在早失败时读到原因。
            stderr_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
            # 关键（2026-10-08 修，本次核心）：**不传 `-ConfigPath`**。
            # 原因：start.py 约定「显式传 -ConfigPath → allow_overlay=False」，
            # 此时即使设了 FAN_CONFIG_PATH 也会被忽略，主配置里留空的 serial.port
            # 无从补齐 → 子进程必然报 "serial.port is empty after overlay merge"
            # 退出码 1（实测复现）。改为不传该参数，让 start.py 走默认主配置路径 +
            # allow_overlay=True，再由 FAN_CONFIG_PATH 完成 overlay 深合并。
            # 注：config_path 仍保留在后端侧，用于 eventsPath 兜底推导与日志。
            child_env = dict(os.environ)
            # hardware/.env（可选）优先注入：现场可在不改代码的前提下指定解释器/overlay。
            # 进程环境变量仍可覆盖之（后者写法见下），保证「环境变量 > 文件」的直觉一致。
            for key, value in _read_hardware_env().items():
                child_env.setdefault(key, value)
            if overlay_path:
                child_env["FAN_CONFIG_PATH"] = overlay_path
            else:
                child_env.pop("FAN_CONFIG_PATH", None)
            proc = subprocess.Popen(
                [_PYTHON, start_script, "-RunId", run_id],
                stdout=subprocess.PIPE, stderr=stderr_file, text=True, encoding="utf-8",
                env=child_env,
            )

            # eventsPath 兜底：优先用 start.py stdout 的单行 launch JSON，但**不依赖它**——
            # 若 stdout 阻塞/解析失败，退化为按 config 目录推导 runs（config 在
            # hardware/v0.6/config/，其 parent.parent = hardware/v0.6，下即 runs/）。
            meta: dict = {}
            try:
                line = proc.stdout.readline() if proc.stdout else ""
                meta = json.loads(line) if line.strip() else {}
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("[fan-executor] 读 start.py stdout 失败（改用推导路径）：%s", e)
            events_path = meta.get("eventsPath") or meta.get("events_path")
            if not events_path:
                events_path = str(Path(config_path).resolve().parent.parent / "runs" / run_id / "events.jsonl")
                logger.info("[fan-executor] eventsPath 缺失，按 config 推导：%s", events_path)

            t_start = time.monotonic()
            last_seq = 0
            finish_seen_at: float | None = None  # 首见 run_finished 的时刻（给 summary 落盘窗口）
            while True:
                with self._lock:
                    should_stop = st.stop_requested
                    if st.status not in ("running", "stopping"):
                        break
                if should_stop:
                    # ⚠️ _request_stop 内部 subprocess.run 可能阻塞数秒~60s，
                    # 必须在锁外调用，否则会持锁阻塞所有 status/samples 读取。
                    self._request_stop(stop_script, run_id, config_path, meta)
                    with self._lock:
                        st.status = "stopped"
                        st.finished_at = time.monotonic()
                        st.terminal = True
                    break

                last_seq, seen_finish = self._drain_events(st, events_path, last_seq)
                if seen_finish and finish_seen_at is None:
                    finish_seen_at = time.monotonic()  # 首见 run_finished 的时间

                # 兜底①：优先按 summary 收敛（权威终态）
                if self._terminal_reached(st, meta):
                    break

                # 兜底②：脚本已收尾（见到 run_finished）→ 给 summary 2 秒落盘窗口；
                # 窗口过后 summary 仍不可读，则按事件流兜底判定（failed 也不折叠）。
                exited = proc.poll() is not None
                if finish_seen_at is not None and (time.monotonic() - finish_seen_at) > 2.0:
                    if self._terminal_from_events(st, events_path):
                        break
                if exited and finish_seen_at is not None:
                    # 进程已退出且事件流已收尾，但 summary 尚未落盘 → 按事件流判定
                    if self._terminal_from_events(st, events_path):
                        break
                if exited and proc.returncode not in (None, 0) and finish_seen_at is None:
                    # 进程非零退出且连收尾事件都没有：如实标失败，不假装停止。
                    # 连带透传后端捕获的 stderr 末行，让前端能看到真实原因（不美化）。
                    detail = self._read_captured_stderr(stderr_file) or self._read_script_stderr(meta, events_path)
                    with self._lock:
                        st.status = "failed"
                        st.error = (
                            f"脚本退出码 {proc.returncode} 且未产出收尾事件"
                            + (f"：{detail}" if detail else "")
                        )
                        st.finished_at = time.monotonic()
                        st.terminal = True
                    logger.warning("[fan-executor] run %s 进程退出码 %s 无收尾，按失败收敛", run_id, proc.returncode)
                    break

                # 兜底③：总超时（含脚本卡死场景），强制收敛
                if time.monotonic() - t_start > self.WATCH_TIMEOUT_S:
                    with self._lock:
                        st.status = "failed"
                        st.error = f"等待运行终态超时（>{int(self.WATCH_TIMEOUT_S)}s），脚本可能卡住"
                        st.finished_at = time.monotonic()
                        st.terminal = True
                    logger.warning("[fan-executor] run %s 等待终态超时，强制收敛为 failed", run_id)
                    break

                # 兜底④（早失败，2026-10-07 补）：启动 N 秒内既无事件流文件、进程也已退出，
                # 说明脚本启动即失败（如目录冲突/依赖缺失），不必等满 120s。
                # 读取脚本 stderr.log 原样透传（数据纪律：不美化、不编造），让前端快速可见。
                if (time.monotonic() - t_start > self.EARLY_FAIL_S
                        and not Path(events_path).is_file()
                        and proc.poll() is not None):
                    # 优先读后端自己捕获的 stderr（start.py 建目录前失败时 run 目录
                    # 里没有 stderr.log，只有这里才有真实原因）。
                    detail = self._read_captured_stderr(stderr_file) or self._read_script_stderr(meta, events_path)
                    with self._lock:
                        st.status = "failed"
                        st.error = (
                            f"硬件脚本启动后未产出事件流（退出码 {proc.returncode}）"
                            + (f"：{detail}" if detail else "；请查 runs/<run_id>/stderr.log")
                        )
                        st.finished_at = time.monotonic()
                        st.terminal = True
                    logger.warning("[fan-executor] run %s 早失败收敛：%s", run_id, st.error)
                    break

                time.sleep(1.0)
        except Exception as e:  # noqa: BLE001 - 后台线程须吞异常并落状态
            logger.exception("[fan-executor] real run %s 失败", run_id)
            with self._lock:
                st.status = "failed"
                st.error = str(e)
                st.terminal = True
        finally:
            # 释放后端捕获 stderr 的临时文件（无论正常收敛还是异常退出）
            if stderr_file is not None:
                try:
                    stderr_file.close()
                except OSError:
                    pass

    def _drain_events(self, st: FanRunState, events_path: str, last_seq: int) -> tuple[int, bool]:
        """读 events.jsonl 增量，把 capture_completed 映射成 sample。

        返回 (新的 last_seq, 是否见到 run_finished)。
        见到 run_finished 表示脚本软件层面已收尾（终态文件随后发布），
        供 _watch 做第②重兜底（无需依赖 summary 是否已落盘）。
        """
        seen_finish = False
        try:
            path = Path(events_path)
            if not path.is_file():
                return last_seq, seen_finish
            text = path.read_text(encoding="utf-8")
        except OSError:
            return last_seq, seen_finish
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            seq = ev.get("sequence")
            # 缺 sequence 的事件无法参与增量游标（无法判重），如实留痕后跳过。
            # 为什么不是静默 continue（2026-10-09 修）：静默丢事件会让「曲线缺一档」
            # 无从定位；至少留下告警，且只报一次（避免每轮轮询刷屏）。
            if not isinstance(seq, int):
                self._warn_missing_sequence(ev)
                continue
            if seq <= last_seq:
                continue
            last_seq = seq
            ev_type = ev.get("type")
            if ev_type == "run_finished":
                seen_finish = True
            # 记录 run 首事件时间作为 t_s 换算基准（只在第一次设置）
            if st.t0_utc is None:
                ev_data = ev.get("data") or {}
                t0 = ev.get("timestampUtc") or ev_data.get("startedUtc")
                if t0:
                    with self._lock:
                        st.t0_utc = t0
            if ev_type != "capture_completed":
                continue
            data = ev.get("data") or {}
            metrics = data.get("metrics") or {}
            # 原样映射 metrics，不加减数值；缺测保持 null + quality 原因
            started_t_s, finished_t_s = self._capture_t_s(st, data)
            # capture_id：用于前端按 id 取该次采集的真实时序波形（GET /captures/{id}）。
            # 由「cycle + duty + startedUtc」拼稳定 id，与 _save_profile_capture 的
            # 目录 tag 同源（tag = cycle0001_duty030_<时间戳>），因此可由 id 反推目录。
            capture_id = self._make_capture_id(data)
            sample = {
                "sequence": seq,
                "t_s": (started_t_s + finished_t_s) / 2.0 if started_t_s is not None and finished_t_s is not None else (started_t_s if started_t_s is not None else finished_t_s),
                "measurement_started_t_s": started_t_s,
                "measurement_finished_t_s": finished_t_s,
                "commanded_pwm_pct": data.get("commandedPwmPercent"),
                "voltage_v": self._metric(metrics, "voltage", "meanV"),
                "current_probe_v": self._metric(metrics, "current", "meanV"),
                "current_a": self._metric(metrics, "current", "meanCurrentA"),
                "measured_pwm_duty_pct": self._metric(metrics, "pwm", "dutyPercent"),
                "pwm_frequency_hz": self._metric(metrics, "pwm", "frequencyHz"),
                "rpm": self._metric(metrics, "tach", "rpm"),
                "quality": self._quality_from(metrics),
                "capture_id": capture_id,
            }
            with self._lock:
                st.samples.append(sample)
                st.next_sequence += 1
                # 缓存波形索引：capture_id → 该采集的真实 CSV 绝对路径（来自事件 artifacts）
                if capture_id:
                    st.captures[capture_id] = {
                        "capture_id": capture_id,
                        "cycle": data.get("cycle"),
                        "profile": data.get("profile"),
                        "commanded_pwm_pct": data.get("commandedPwmPercent"),
                        "artifacts": data.get("artifacts") or [],
                        "startedUtc": data.get("startedUtc"),
                        "finishedUtc": data.get("finishedUtc"),
                    }
        return last_seq, seen_finish

    def _warn_missing_sequence(self, ev: dict) -> None:
        """缺 sequence 的事件告警（按事件类型去重，避免每轮轮询刷屏）。"""
        ev_type = str(ev.get("type") or "(无 type)")
        if ev_type in self._warned_missing_seq:
            return
        self._warned_missing_seq.add(ev_type)
        logger.warning(
            "[fan-executor] 事件缺 sequence，已跳过（type=%s）；该事件无法参与增量游标，"
            "对应的采集点不会出现在趋势图中。",
            ev_type,
        )

    @staticmethod
    def _make_capture_id(data: dict) -> str | None:
        """由 capture 事件 data 生成稳定 capture_id（与落盘目录 tag 同源）。

        形如 `c1_d030_20261008T231937`：cycle + duty + startedUtc 去掉分隔符。
        生成不了（缺字段）返回 None —— 此时前端拿不到该点波形，如实置空，
        绝不编造 id 去猜文件。
        """
        cycle = data.get("cycle")
        duty = data.get("commandedPwmPercent")
        started = data.get("startedUtc")
        if cycle is None or duty is None or not started:
            return None
        stamp = str(started).replace("-", "").replace(":", "").replace("+00:00", "")
        stamp = stamp.replace("T", "T").split(".")[0]
        return f"c{int(cycle)}_d{int(duty)}_{stamp}"

    def _terminal_from_events(self, st: FanRunState, events_path: str) -> bool:
        """按事件流兜底判终态：summary 不可读时，用 run_finished 事件里的 state 收敛。

        不编造：只认事件流真实存在的 state（failed/completed/stopped），
        没有 run_finished 事件则返回 False（继续等 summary）。
        """
        try:
            text = Path(events_path).read_text(encoding="utf-8")
        except OSError:
            return False
        state = None
        err = ""
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "run_finished":
                data = ev.get("data") or {}
                state = data.get("state") or ev.get("state")
                err = data.get("failureMessage") or ""
        if not state:
            return False
        with self._lock:
            st.status = state if state in ("completed", "stopped", "failed") else "failed"
            if st.status == "failed" and err:
                st.error = err
            st.finished_at = time.monotonic()
            st.terminal = True
        logger.info("[fan-executor] run %s 终态按事件流收敛：state=%s", st.run_id, st.status)
        return True

    @staticmethod
    def _metric(metrics: dict, group: str, key: str) -> Any:
        g = metrics.get(group) or {}
        return g.get(key)

    def _capture_t_s(self, st: FanRunState, data: dict) -> tuple[float | None, float | None]:
        """真实 t_s：用 capture 的 startedUtc/finishedUtc 相对 run 首事件时间换算秒数。

        数据纪律：只用事件里真实存在的 UTC 时间戳，不编造时钟；解析失败保持 None，
        前端据此把该点标注为「时间未知」，绝不用假值填充横轴。
        """
        t0 = st.t0_utc
        if not t0:
            return None, None
        try:
            from datetime import datetime
            t0_dt = datetime.fromisoformat(t0.replace("Z", "+00:00"))
            out = []
            for key in ("startedUtc", "finishedUtc"):
                raw = data.get(key)
                if not raw:
                    out.append(None)
                    continue
                try:
                    dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                    out.append(round((dt - t0_dt).total_seconds(), 2))
                except (ValueError, TypeError):
                    out.append(None)
            return out[0], out[1]
        except (ValueError, TypeError):
            return None, None

    @staticmethod
    def _quality_from(metrics: dict) -> dict[str, Any]:
        q: dict[str, Any] = {}
        for grp, keys in (("voltage", "voltage"), ("current", "current"), ("tach", "rpm")):
            g = metrics.get(grp) or {}
            if not g.get("physicalProbeRatioConfirmed", False) and grp in ("voltage", "current"):
                q[keys] = "provisional_probe_ratio"
            if grp == "tach" and g.get("rpm") is None:
                q["rpm"] = "not_connected"
        if metrics.get("current") and metrics["current"].get("meanCurrentA") is None:
            q["current"] = "conversion_not_confirmed"
        return q

    @staticmethod
    def _read_captured_stderr(stderr_file: Any) -> str:
        """读后端捕获的子进程 stderr 末行（原样透传，不美化、不编造）。

        为什么需要：start.py 在「建运行目录之前」失败时（如配置校验不通过），
        运行目录尚不存在，runs/<id>/stderr.log 也就没有——只有后端自己捕获的
        这份 stderr 才有真实原因。读取失败一律返回空串（由调用方兜底其他来源）。
        """
        try:
            if stderr_file is None:
                return ""
            stderr_file.flush()
            stderr_file.seek(0)
            text = stderr_file.read() or ""
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if lines:
                return lines[-1][:300]
        except (OSError, ValueError):
            pass
        return ""

    @staticmethod
    def _read_script_stderr(meta: dict, events_path: str) -> str:
        """早失败时读取脚本 stderr.log 末行作为可行动原因（原样透传，不美化）。

        stderr.log 与 events.jsonl 同目录（start.py 写 stdout.jsonl/stderr.log 到 run 目录）。
        """
        try:
            run_dir = meta.get("directory") or str(Path(events_path).parent)
            log = Path(run_dir) / "stderr.log"
            if log.is_file():
                lines = [ln.strip() for ln in log.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
                if lines:
                    return lines[-1][:300]
        except OSError:
            pass
        return ""

    def _request_stop(self, stop_script: str, run_id: str, _config_path: str, meta: dict) -> None:
        """调用 entrypoints/stop.py 写 stop.request（发 SET 0 等 ACK，不强制杀进程）。

        注：`_config_path` 保留形参以兼容调用方签名，但自 2026-10-08 起不再下传
        `-ConfigPath`（见下方说明，改由环境变量注入 overlay）。
        """
        directory = meta.get("directory", "")
        args = [_PYTHON, stop_script, "-RunId", run_id]
        if directory:
            args += ["-RunDirectory", directory]
        # 与启动保持一致（2026-10-08 修）：无 directory 时不传 -ConfigPath，
        # 改由 FAN_CONFIG_PATH 让 stop.py 走「默认路径 + allow_overlay=True」，
        # 否则同样会因显式 ConfigPath 禁用 overlay 而解析失败。
        child_env = dict(os.environ)
        for key, value in _read_hardware_env().items():
            child_env.setdefault(key, value)
        overlay_path = _resolve_overlay_path()
        if overlay_path:
            child_env["FAN_CONFIG_PATH"] = overlay_path
        else:
            child_env.pop("FAN_CONFIG_PATH", None)
        try:
            subprocess.run(
                args, capture_output=True, text=True, encoding="utf-8", timeout=60,
                env=child_env,
            )
        except subprocess.TimeoutExpired:
            logger.warning("[fan-executor] stop.py 超时，run %s", run_id)

    def _terminal_reached(self, st: FanRunState, meta: dict) -> bool:
        """以 summary.json 的 terminalPublished:true 判权威终态（如实，不提前判成功）。

        state 原样映射（completed/stopped/failed），**不再把 failed 折叠成 stopped**；
        failureMessage 透传到 st.error，供前端如实显示失败原因。
        summary 路径缺失时按 run_id 推导运行目录兜底（与 _watch 的 eventsPath 同规则）。
        """
        directory = meta.get("directory")
        summary_path = meta.get("summaryPath")
        if not summary_path:
            if directory:
                summary_path = os.path.join(directory, "summary.json")
            else:
                # meta 缺失（stdout 未解析出来）：按运行根目录 + run_id 推导。
                # ⚠️ 2026-10-12 修历史笔误：原推导为「start.py 脚本目录 + runs」，
                # 即 <hardware/py/entrypoints>/runs/<id>/summary.json —— 多了一层
                # entrypoints，与 start.py 的 output.root="../runs"（= hardware/v0.6/runs）不符。
                summary_path = str(_runs_root_path() / st.run_id / "summary.json")
        try:
            summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if summary.get("terminalPublished"):
            state = summary.get("state")
            with self._lock:
                # 原样映射；未知值保守落 failed（不伪装成正常停止）
                st.status = state if state in ("completed", "stopped", "failed") else "failed"
                if st.status == "failed":
                    st.error = summary.get("failureMessage") or st.error or "运行失败（未提供原因）"
                st.finished_at = time.monotonic()
                st.terminal = True
            logger.info("[fan-executor] run %s 终态按 summary 收敛：state=%s", st.run_id, st.status)
            return True
        return False


#: 两个执行器各保留一份单例。切换模式时换的是「用哪一个」，不是「新建一个」——
#: 各自都有 _runs 状态（这里是类属性，两类共享各自的字典），实例复用可避免
#: 重复构造与日志噪声。
_real_executor: "FanExecutor | None" = None
_sim_executor: "FanExecutor | None" = None


def get_executor() -> FanExecutor:
    """按当前**数据源模式**返回执行器。

    demo 模式强制走模拟执行器 —— 演示时绝不能碰真硬件，否则会去连示波器/串口，
    无设备环境下必然报错。这条优先级**高于** FAN_EXECUTOR 环境变量：

      · FAN_EXECUTOR 是「开发联调时选哪个」，属于部署配置
      · 数据源模式是「此刻必须是什么」，属于业务约束

    配置不能盖掉业务约束，否则就会出现「界面显示演示中，后台还在开串口」。

    live 模式保持原行为：默认真实台架，显式 `FAN_EXECUTOR=sim` 才走模拟兜底。
    为什么默认 real 而非 sim：本系统以真实台架采集为目标，模拟仅是「无仪器联调」
    的开发兜底。默认 sim 会在有仪器时静默回退成合成数据，造成「图在动、风扇没转」
    的误导（实测踩过）。因此默认 real，模拟必须显式声明，杜绝静默降级。
    """
    global _real_executor, _sim_executor

    if get_mode() == "demo":
        if _sim_executor is None:
            _sim_executor = SimFanExecutor()
            logger.info("[fan-executor] 演示模式启用模拟执行器")
        return _sim_executor

    mode = os.environ.get("FAN_EXECUTOR", "real").lower()
    if mode == "sim":
        if _sim_executor is None:
            _sim_executor = SimFanExecutor()
        return _sim_executor

    if _real_executor is None:
        _real_executor = RealFanExecutor()
    return _real_executor


def make_run_id() -> str:
    """生成唯一 run_id（uuid hex，可拼 URL，与 runs.py 一致）。"""
    return uuid.uuid4().hex
