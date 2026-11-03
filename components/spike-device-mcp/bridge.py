"""最小 HTTP 桥：把 device-bench MCP 工具暴露成 C 区画布节点能直接 fetch 的 JSON。

桥不是第二套业务逻辑。它在同一进程里持有那个 MCPServer 对象，
所有工具调用都走 `MCPServer.call_tool`，与 MCP 客户端走的是同一条代码路径，
所以红线闸口不可能被桥绕过。

桥比 MCP 多出来的只有一样东西：**人工批准接口**。
批准只能从这里进，MCP 工具面上没有任何方法能改凭据状态，模型因此无法自批。

鉴权分两级（2026-09-20 起）：
  · x-bridge-token  调用票。列设备、查状态、调工具、驳回。它会随前端构建产物发出去，
                    所以只当它是公开的：拿到它最多能让桥签发一张 pending 凭据。
  · x-approver-pin  批准权。只有 POST /confirmations/{token}/approve 要它，
                    值取自桥 .env 的 BRIDGE_APPROVER_PIN，绝不进任何 VITE_ 变量。
                    连续错 BRIDGE_APPROVER_PIN_MAX_FAILS 次锁 BRIDGE_APPROVER_PIN_LOCK_SECONDS 秒。

    python bridge.py            # 默认 127.0.0.1:8031
"""
from __future__ import annotations

import hmac
import json
import os
import threading
import time
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from device_bench import config
from device_bench.confirm import GUARDED_ACTIONS, REGISTRY
from device_bench.server import server

TOKEN = os.environ.get("BRIDGE_TOKEN", "")
if not TOKEN:
    raise SystemExit(
        "[bridge] 致命错误：未设置 BRIDGE_TOKEN，拒绝以无鉴权方式启动。参见 .env.example"
    )

APPROVER_PIN = config.APPROVER_PIN
if not APPROVER_PIN:
    raise SystemExit(
        "[bridge] 致命错误：未设置 BRIDGE_APPROVER_PIN，批准接口将没有第二道闸口，"
        "拒绝启动。参见 .env.example"
    )
if APPROVER_PIN == TOKEN:
    raise SystemExit(
        "[bridge] 致命错误：BRIDGE_APPROVER_PIN 与 BRIDGE_TOKEN 同值。"
        "BRIDGE_TOKEN 会被打进浏览器包，两者同值等于没有第二道闸口。"
    )

app = FastAPI(title="device-bench bridge", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get(
        "BRIDGE_CORS_ORIGIN", "http://localhost:5173,http://localhost:3080").split(",") if o],
    allow_headers=["content-type", "x-bridge-token", "x-approver-pin", "x-automation-token"],
    allow_methods=["GET", "POST", "OPTIONS"],
)


def auth(x_bridge_token: str | None = Header(default=None)) -> None:
    """调用票。只证明"这是我们那个页面"，不代表有权批准任何红线动作。"""
    if not hmac.compare_digest((x_bridge_token or "").encode("utf-8"), TOKEN.encode("utf-8")):
        raise HTTPException(status_code=401, detail="bad token")


class PinGate:
    """批准 PIN 的校验与限速。

    连续错 MAX_FAILS 次锁 LOCK_SECONDS 秒；锁定期间即使 PIN 正确也一律拒。
    任何一次成功都把失败计数清零。计数是全进程一份——这是一台单人用的台架桥，
    按来[源] IP 分桶只会给攻击者留下换源绕过的口子。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fails = 0
        self._locked_until = 0.0

    def state(self) -> dict:
        with self._lock:
            left = max(0.0, self._locked_until - time.time())
            return {
                "locked": left > 0,
                "retry_after_s": round(left, 1),
                "fails": self._fails,
                "max_fails": config.APPROVER_PIN_MAX_FAILS,
            }

    def check(self, pin: str | None) -> None:
        with self._lock:
            now = time.time()
            left = self._locked_until - now
            if left > 0:
                raise HTTPException(
                    403,
                    f"批准已被锁定：连续输错 {config.APPROVER_PIN_MAX_FAILS} 次，"
                    f"{round(left, 1)} 秒后才能再试。凭据保持 pending。",
                )
            if pin and hmac.compare_digest(pin.encode("utf-8"), APPROVER_PIN.encode("utf-8")):
                self._fails = 0
                return
            self._fails += 1
            detail = (
                "缺 x-approver-pin 头：批准红线动作需要现场输入批准 PIN，"
                "浏览器里那份 token 不含批准权。凭据保持 pending。"
                if not pin
                else f"批准 PIN 不正确（第 {self._fails} 次）。凭据保持 pending。"
            )
            if self._fails >= config.APPROVER_PIN_MAX_FAILS:
                self._locked_until = now + config.APPROVER_PIN_LOCK_SECONDS
                self._fails = 0
                detail += f" 已锁定 {config.APPROVER_PIN_LOCK_SECONDS:.0f} 秒。"
            raise HTTPException(403, detail)


PIN_GATE = PinGate()


def _unwrap(result: Any) -> dict:
    """把 CallToolResult 拆成普通 dict。优先用结构化输出，退回文本块。"""
    sc = getattr(result, "structuredContent", None)
    if isinstance(sc, dict):
        return sc.get("result", sc) if set(sc.keys()) == {"result"} else sc
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
    return {"raw": str(result)}


async def _call(name: str, args: dict) -> dict:
    res = await server.call_tool(name, args)
    payload = _unwrap(res)
    if getattr(res, "isError", False):
        payload = {"status": "error", **payload}
    return payload


# ---------- 设备与工具清单 ----------

@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "ts": time.time(),
        "server": server.name,
        # 批准要第二道秘密这件事本身不是秘密，写出来省得前端猜为什么 403。
        "approve_requires_pin": True,
        "approver_pin_gate": PIN_GATE.state(),
    }


@app.get("/devices", dependencies=[Depends(auth)])
async def devices() -> dict:
    """C 区画布拿这一份就能把设备节点画出来：名字、型号、连接状态、分层工具菜单。"""
    tools = await server.list_tools()
    groups: dict[str, list[dict]] = {}
    for t in tools:
        meta = t.meta or {}
        g = meta.get("group", "other")
        groups.setdefault(g, []).append({
            "name": t.name,
            "title": t.title,
            "description": t.description,
            "layer": meta.get("layer"),
            "guarded": bool(meta.get("guarded")),
            "human_gate": meta.get("human_gate"),
            "risk": meta.get("risk"),
            "input_schema": t.input_schema,
        })
    st = await _call("status", {})
    return {
        "devices": [{
            "id": d.id,
            "name": d.name,
            "model": d.model,
            "kind": d.kind,
            "via": d.via,
            "tags": d.tags,
            "transport": "mcp:device-bench",
            "backend": "ssh",
            "target": f"{d.user}@{d.host}:{d.port}",
            "status": st if d.id == "bench" else {"mode": st.get("mode"), "via": d.via},
            "tool_groups": groups if d.id == "bench" else {},
        } for d in config.DEVICES.values()],
        "guarded_actions": GUARDED_ACTIONS,
        "server": {"name": server.name, "version": server.version,
                   "tool_count": len(tools)},
    }


@app.get("/devices/{device_id}/status", dependencies=[Depends(auth)])
async def device_status(device_id: str) -> dict:
    if device_id not in config.DEVICES:
        raise HTTPException(404, f"未知设备 {device_id}")
    st = await _call("status", {})
    st["device_id"] = device_id
    st["pending"] = REGISTRY.list()
    st["approve_requires_pin"] = True
    st["approver_pin_gate"] = PIN_GATE.state()
    return st


class ToolCall(BaseModel):
    arguments: dict = {}


@app.post("/devices/{device_id}/tools/{name}", dependencies=[Depends(auth)])
async def call_tool(device_id: str, name: str, body: ToolCall | None = None) -> dict:
    if device_id not in config.DEVICES:
        raise HTTPException(404, f"未知设备 {device_id}")
    known = {t.name for t in await server.list_tools()}
    if name not in known:
        raise HTTPException(404, f"未知工具 {name}")
    return await _call(name, (body.arguments if body else {}) or {})


# ---------- 人工确认闸口（红线的落点，只在桥上，不在 MCP 面上） ----------

class Approval(BaseModel):
    operator: str
    note: str = ""


class Rejection(BaseModel):
    reason: str = ""


@app.get("/confirmations", dependencies=[Depends(auth)])
async def list_confirmations(include_done: bool = False) -> dict:
    return {"confirmations": REGISTRY.list(include_done=include_done)}


@app.get("/confirmations/{token}", dependencies=[Depends(auth)])
async def get_confirmation(token: str) -> dict:
    try:
        return REGISTRY.get(token).public()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/confirmations/{token}/approve", dependencies=[Depends(auth)])
async def approve(
    token: str,
    body: Approval,
    x_approver_pin: str | None = Header(default=None),
) -> dict:
    """人在确认卡上敲了批准 PIN、点了"确认"之后前端调这里。

    两道门：x-bridge-token 证明请求来自我们的页面，x-approver-pin 证明现场有人。
    PIN 错或没带一律 403，凭据留在 pending，不消耗、不降级。
    operator 由前端带上，只做署名；能不能批由 PIN 决定，不由这个名字决定。
    """
    PIN_GATE.check(x_approver_pin)
    try:
        return REGISTRY.approve(token, body.operator, channel="human_pin").public()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/confirmations/{token}/auto-approve", dependencies=[Depends(auth)])
async def auto_approve(
    token: str,
    body: Approval,
    x_automation_token: str | None = Header(default=None),
) -> dict:
    """一键自动化测试流程的自动放行通道（2026-09-30 加）。

    红线**没有被废**，只是多开了一条受独立 token 保护的自动化通道：
      · x-bridge-token 证明请求来自我们的页面（同 approve）；
      · x-automation-token 证明「这是自动化流程在放行」，其值取自桥 .env 的
        BRIDGE_AUTOMATION_TOKEN，绝不进浏览器包（与 APPROVER_PIN 同级秘密）。
    通过后凭据 approve_channel 记 "automation"（区别于 human_pin），留痕可审计。

    安全边界：
      · 未配置 BRIDGE_AUTOMATION_TOKEN → 本端点恒 503，自动化无法无 PIN 放行；
      · token 缺失或不对 → 403，凭据留在 pending，不消耗、不降级；
      · 只放行「已在 pending 的凭据」，仍受 redeem 的 tool/参数指纹约束——
        自动化能做的，只是把人现场敲 PIN 这一步换成「持有自动化 token」。
    """
    if not config.AUTOMATION_TOKEN:
        raise HTTPException(
            503,
            "桥未配置 BRIDGE_AUTOMATION_TOKEN，自动化自动放行关闭；"
            "如需一键自动化真下发设备，请在桥 .env 配置该 token。",
        )
    if not x_automation_token or not hmac.compare_digest(
        x_automation_token.encode("utf-8"), config.AUTOMATION_TOKEN.encode("utf-8")
    ):
        raise HTTPException(403, "缺 x-automation-token 头或自动化 token 不正确，凭据保持 pending")
    try:
        return REGISTRY.approve(token, body.operator or "automation", channel="automation").public()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/confirmations/{token}/reject", dependencies=[Depends(auth)])
async def reject(token: str, body: Rejection) -> dict:
    try:
        return REGISTRY.reject(token, body.reason).public()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("BRIDGE_HOST", "127.0.0.1"),
        port=int(os.environ.get("BRIDGE_PORT", "8031")),
        log_level="info",
    )
