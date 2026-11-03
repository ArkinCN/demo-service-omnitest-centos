"""起 MCP server 的 streamable-http 传输（原 run-mcp-http.sh 的跨平台 Python 版）。

默认监听 127.0.0.1:8032，路径 /mcp。

与原 bash 版对齐：重启前按 pidfile 杀旧进程；端口可用 MCP_HTTP_PORT 覆盖；
日志写 evidence/mcp-http.log。

Windows 差异：setsid/nohup → DETACHED_PROCESS；kill -0 → tasklist 查存活。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIDFILE = HERE / ".mcphttp.pid"

sys.path.insert(0, str(HERE))
from run_bridge import is_running, load_dotenv, pick_python  # noqa: E402


def main() -> int:
    os.chdir(HERE)

    if PIDFILE.is_file():
        try:
            pid = int(PIDFILE.read_text(encoding="utf-8").strip())
            if is_running(pid):
                print(f"[mcp-http] 停掉旧进程 pid={pid}")
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
                else:
                    os.kill(pid, 15)
                time.sleep(2)
        except (ValueError, OSError):
            pass

    for k, v in load_dotenv().items():
        os.environ.setdefault(k, v)

    port = os.environ.get("MCP_HTTP_PORT", "8032")
    logdir = HERE / "evidence"
    logdir.mkdir(exist_ok=True)
    logfile = open(logdir / "mcp-http.log", "a", encoding="utf-8")  # noqa: SIM115

    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    proc = subprocess.Popen(
        [pick_python(), "-m", "device_bench.server", "--transport", "streamable-http", "--port", port],
        stdout=logfile, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, creationflags=flags, cwd=str(HERE),
    )
    PIDFILE.write_text(str(proc.pid), encoding="utf-8")
    time.sleep(4)
    print(f"mcp streamable-http on 127.0.0.1:{port}/mcp (pid {proc.pid})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
