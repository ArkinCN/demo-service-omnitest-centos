"""重启设备 HTTP 桥（原 run-bridge.sh 的跨平台 Python 版）。

为什么改写：原脚本依赖 bash、`setsid`、`nohup`、`kill -0`、`. ./.env` 等 Unix 机制，
Windows 上跑不了。本项目交付形态是纯 Windows。

与原 bash 版的行为对齐点：
- 重启前先杀掉旧进程（按 pidfile），避免端口占用；
- 起桥后**主动调一次 connect**，并把 mode 如实打出来
  （live=真连台架 / mock=连不上返回合成数据 / unknown=连都没试成）；
- 传 --no-connect 时跳过自动 connect，并提示 status 会是 unknown。

Windows 差异说明：
- `setsid` / `nohup` 不存在：改用 subprocess 的 DETACHED_PROCESS 让桥脱离本终端；
- `/dev/null` → `subprocess.DEVNULL`；
- pidfile 里的 pid 用 `tasklist` 校验存活（Windows 无 `kill -0`）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIDFILE = HERE / ".bridge.pid"


def is_running(pid: int) -> bool:
    """进程是否存活。Windows 用 tasklist 查，其他平台用 signal 0。"""
    if pid <= 0:
        return False
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True,
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_old() -> None:
    if not PIDFILE.is_file():
        return
    try:
        pid = int(PIDFILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return
    if not is_running(pid):
        return
    print(f"[bridge] 停掉旧进程 pid={pid}")
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    else:
        os.kill(pid, 15)
    time.sleep(2)


def load_dotenv() -> dict[str, str]:
    """读 ./.env 注入进程环境（原脚本的 `set -a; . ./.env`）。

    只解析 KEY=VALUE 行，忽略注释与空行；不引入 python-dotenv 依赖，
    因为这个脚本要在最干净的环境下也能跑起来。
    """
    env: dict[str, str] = {}
    envfile = HERE / ".env"
    if not envfile.is_file():
        return env
    for line in envfile.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def pick_python() -> str:
    for cand in (HERE / ".venv" / "Scripts" / "python.exe",
                 HERE / ".venv" / "bin" / "python"):
        if cand.is_file():
            return str(cand)
    return sys.executable


def http(url: str, token: str | None = None, payload: dict | None = None, timeout: float = 15.0):
    """极简 HTTP 调用，返回解析后的 JSON；失败返回 None。"""
    req = urllib.request.Request(url, method="POST" if payload is not None else "GET")
    if payload is not None:
        req.add_header("content-type", "application/json")
        data = json.dumps(payload).encode("utf-8")
    else:
        data = None
    if token:
        req.add_header("x-bridge-token", token)
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="重启设备 HTTP 桥")
    ap.add_argument("--no-connect", action="store_true",
                    help="跳过自动 connect（status 会停在 unknown）")
    args = ap.parse_args()

    os.chdir(HERE)
    stop_old()

    # 环境：先 .env，再让已有环境变量优先（与原 `set -a` 后的行为一致）
    for k, v in load_dotenv().items():
        os.environ.setdefault(k, v)

    logdir = HERE / "evidence"
    logdir.mkdir(exist_ok=True)
    logfile = open(logdir / "bridge.log", "a", encoding="utf-8")  # noqa: SIM115

    py = pick_python()
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    proc = subprocess.Popen(
        [py, "bridge.py"],
        stdout=logfile, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=flags,
        cwd=str(HERE),
    )
    PIDFILE.write_text(str(proc.pid), encoding="utf-8")
    time.sleep(5)

    base = f"http://127.0.0.1:{os.environ.get('BRIDGE_PORT', '8031')}"
    if http(f"{base}/health") is None:
        print("[bridge] /health 未响应，桥可能没起来；看 evidence/bridge.log", file=sys.stderr)
        return 1
    print("[bridge] /health OK")

    if args.no_connect:
        print("[bridge] 已跳过自动 connect，status 里的 mode 会是 unknown。")
        print(f"[bridge] 需要连台架时执行：POST {base}/devices/bench/tools/connect")
        return 0

    tok = os.environ.get("BRIDGE_TOKEN", "")
    print("[bridge] 正在重建到台架的 SSH 会话（connect 不是红线动作，不需要凭据）…")
    res = http(f"{base}/devices/bench/tools/connect", token=tok, payload={"arguments": {}})
    mode = (res or {}).get("mode", "unknown")
    print(f"[bridge] connect 返回 mode={mode}")

    if mode == "live":
        print("[bridge] 已真连上台架，status 会报 live。")
    elif mode == "mock":
        print("[bridge] 连不上台架，桥进入 mock：返回的全部是合成数据，不得当实测上报。")
    else:
        print(f"[bridge] 连接未建立，status 仍为 unknown。手动重试：POST {base}/devices/bench/tools/connect")

    st = http(f"{base}/devices/bench/status", token=tok) or {}
    print(f"[bridge] 当前 status：mode={st.get('mode')} connected={st.get('connected')} "
          f"hostname={st.get('hostname')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
