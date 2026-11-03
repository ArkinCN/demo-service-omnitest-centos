"""跑一遍全部取证（原 run-evidence.sh 的跨平台 Python 版）。

四段与 bash 版逐段对应：
  [1/4] 连接层 + 设备清单
  [2/4] 观测层（真台架）
  [3/4] 动作层红线：无 token 拒绝 → 人工批准 → 放行 → 重放被拒
  [4/4] mock 路径：断开真连接，强制 mock，同样的观测工具再跑一遍

产物落 `evidence/`，文件名与 bash 版保持一致（便于既往记录对照）。

⚠️ 本脚本会**真的调用设备桥**（connect / read_* / start / write_param / estop）。
在真台架上跑 start 是会引起动作的，只在明确要取证时执行。
桥未起或未连台架时，桥自身会回 mock 并如实标注，不会静默冒充实测。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
E = HERE / "evidence"

sys.path.insert(0, str(HERE))
from run_bridge import http, load_dotenv  # noqa: E402


def dump(name: str, obj) -> None:
    """把一次调用结果落成一个 JSON 文件；调用失败也落盘，写明失败原因。"""
    E.mkdir(exist_ok=True)
    payload = obj if obj is not None else {"error": "调用失败或无响应"}
    (E / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    mark = "ok" if obj is not None else "FAILED"
    print(f"    {name}  [{mark}]")


def main() -> int:
    for k, v in load_dotenv().items():
        os.environ.setdefault(k, v)

    base = f"http://127.0.0.1:{os.environ.get('BRIDGE_PORT', '8031')}"
    token = os.environ.get("BRIDGE_TOKEN", "")

    def call_tool(name: str, args: dict):
        return http(f"{base}/devices/bench/tools/{name}", token=token, payload={"arguments": args})

    def get(path: str):
        return http(f"{base}{path}", token=token)

    print("[1/4] 连接层 + 设备清单")
    dump("02-connect-live.json", call_tool("connect", {}))
    dump("01-devices.json", get("/devices"))
    dump("03-status-live.json", get("/devices/bench/status"))

    print("[2/4] 观测层（真台架）")
    dump("04-read_fg-live.json", call_tool("read_fg", {"samples": 3, "interval_s": 0.5}))
    dump("05-read_pwm-live.json", call_tool("read_pwm", {}))
    dump("06-tail_log-live.json", call_tool("tail_log", {"lines": 12}))
    dump("07-capture_scope-dryrun.json", call_tool("capture_scope", {}))

    print("[3/4] 动作层红线：无 token 拒绝 → 人工批准 → 放行 → 重放被拒")
    r8 = call_tool("start", {"duty_percent": 60, "duration_s": 30})
    dump("08-start-no-token-REFUSED.json", r8)
    tok = (r8 or {}).get("confirm_token", "")
    if tok:
        dump("09-start-unapproved-token-REFUSED.json",
             call_tool("start", {"duty_percent": 60, "duration_s": 30, "confirm_token": tok}))
        dump("10-approve-by-human.json",
             http(f"{base}/confirmations/{quote(tok, safe='')}/approve", token=token,
                  payload={"operator": "张工（spike 取证）", "note": "台架空载，仅验证闸口"}))
        dump("11-start-approved-EXECUTED.json",
             call_tool("start", {"duty_percent": 60, "duration_s": 30, "confirm_token": tok}))
        # 同一张票再放一次：必须被拒（单次使用）
        dump("12-start-replay-REFUSED.json",
             call_tool("start", {"duty_percent": 60, "duration_s": 30, "confirm_token": tok}))
    else:
        for n in ("09-start-unapproved-token-REFUSED", "10-approve-by-human",
                  "11-start-approved-EXECUTED", "12-start-replay-REFUSED"):
            print(f"    {n}.json  [SKIPPED] 上一步未签发凭据")
            dump(f"{n}.json", {"skipped": "上一步未签发凭据（桥可能未起）"})

    # 参数被换掉：拿为 A 参数批的票去执行 B 参数，必须拒
    r13 = call_tool("write_param", {"key": "kp_speed", "value": 1.25})
    dump("13-write_param-no-token-REFUSED.json", r13)
    tok2 = (r13 or {}).get("confirm_token", "")
    if tok2:
        http(f"{base}/confirmations/{quote(tok2, safe='')}/approve", token=token,
             payload={"operator": "张工（spike 取证）"})
        dump("14-write_param-args-tampered-REFUSED.json",
             call_tool("write_param", {"key": "kp_speed", "value": 9.99, "confirm_token": tok2}))
    else:
        print("    14-write_param-args-tampered-REFUSED.json  [SKIPPED] 无凭据")
        dump("14-write_param-args-tampered-REFUSED.json", {"skipped": "无凭据"})

    dump("15-estop-no-token-REFUSED.json", call_tool("estop", {"reason": "演示"}))
    dump("16-confirmations-audit-trail.json", get("/confirmations?include_done=true"))

    print("[4/4] mock 路径：断开真连接，强制 mock，同样的观测工具再跑一遍")
    dump("17-connect-mock.json", call_tool("connect", {"force_mock": True}))
    dump("18-read_fg-mock.json", call_tool("read_fg", {"samples": 3, "interval_s": 0.3}))
    dump("19-read_pwm-mock.json", call_tool("read_pwm", {}))
    call_tool("connect", {})  # 复位回真连接
    print(f"done -> {E}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
