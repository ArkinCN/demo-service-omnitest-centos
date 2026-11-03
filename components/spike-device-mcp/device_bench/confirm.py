"""人工确认闸口。

红线：启动、停止、急停、写回参数、导出、归档这六个动作只能人点。
MCP 可以把这六个动作做成工具（模型需要知道它们存在、需要能提出请求），
但工具自身不执行，除非拿到一张**经人工批准过的**一次性凭据。

三段式：
  1. 模型调动作工具，不带 confirm_token  → 工具拒绝执行，返回一张 pending 凭据；
  2. 人在 C 区看板上点"确认"，前端调桥的 approve 接口 → 凭据转 approved；
  3. 模型带着这张 token 重调同一工具同一参数 → 执行，凭据作废。

关键点一：批准接口只挂在桥的 HTTP 面上，不做成 MCP 工具。
模型能调到的东西里没有任何一个能把凭据从 pending 推到 approved，所以模型无法自批。

关键点二（2026-09-20 加）：桥的鉴权拆成两级，光有浏览器里那份 token 批不动。
  · BRIDGE_TOKEN        —— 调用票。列设备、查状态、调工具、驳回自己发起的票。
                           它随 VITE_BRIDGE_TOKEN 进浏览器包，等于公开。
  · BRIDGE_APPROVER_PIN —— 批准权。只存在桥的 .env 与进程内存，不进任何构建产物。
                           approve 请求必须另带 x-approver-pin 头，桥用常量时间比较。
凭据上的 approve_channel 记下这次是怎么放行的：human_pin 表示有人现场敲了 PIN。
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass, field

# 红线六动作。键是工具名，值是给人看的一句话说明。
GUARDED_ACTIONS: dict[str, str] = {
    "start": "启动被测电机：台架会真的转起来",
    "stop": "停止被测电机",
    "estop": "急停：立即切断驱动输出",
    "write_param": "把参数写回驱动板：改变被测对象的行为",
    "export": "导出本轮产物：落盘成对外交付文件",
    "archive": "归档本轮结果：写入不可随意回退的存档",
}

TTL_SECONDS = 180.0


@dataclass
class Ticket:
    token: str
    tool: str
    args_digest: str
    args_preview: dict
    prompt: str
    created_at: float
    expires_at: float
    state: str = "pending"          # pending | approved | consumed | rejected | expired
    approved_by: str | None = None
    approved_at: float | None = None
    # 放行渠道。human_pin 表示批准请求带了正确的 BRIDGE_APPROVER_PIN，
    # 即现场有人在确认卡上敲过那串只存在于服务端的秘密。别的值一律不是真人现场批准。
    approve_channel: str | None = None
    rejected_reason: str | None = None
    history: list[dict] = field(default_factory=list)

    def public(self) -> dict:
        return {
            "confirm_token": self.token,
            "tool": self.tool,
            "state": self.effective_state(),
            "prompt": self.prompt,
            "args_preview": self.args_preview,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "seconds_left": max(0.0, round(self.expires_at - time.time(), 1)),
            "approved_by": self.approved_by,
            "approve_channel": self.approve_channel,
            "rejected_reason": self.rejected_reason,
        }

    def effective_state(self) -> str:
        if self.state in ("consumed", "rejected"):
            return self.state
        if time.time() > self.expires_at:
            return "expired"
        return self.state


def digest(args: dict) -> str:
    """参数指纹。批准的是"这一组参数"，换了参数就得重新确认。"""
    payload = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class ConfirmRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tickets: dict[str, Ticket] = {}

    def issue(self, tool: str, args: dict, prompt: str) -> Ticket:
        with self._lock:
            self._sweep()
            now = time.time()
            t = Ticket(
                token="ct_" + secrets.token_urlsafe(18),
                tool=tool,
                args_digest=digest(args),
                args_preview={k: v for k, v in args.items() if k != "confirm_token"},
                prompt=prompt,
                created_at=now,
                expires_at=now + TTL_SECONDS,
            )
            t.history.append({"at": now, "event": "issued"})
            self._tickets[t.token] = t
            return t

    def approve(self, token: str, operator: str, channel: str = "human_pin") -> Ticket:
        with self._lock:
            t = self._require(token)
            st = t.effective_state()
            if st != "pending":
                raise ValueError(f"凭据当前状态为 {st}，不能批准")
            if not operator or not operator.strip():
                raise ValueError("必须写明批准人")
            t.state = "approved"
            t.approved_by = operator.strip()
            t.approve_channel = channel
            t.approved_at = time.time()
            t.history.append({
                "at": t.approved_at, "event": "approved",
                "by": t.approved_by, "channel": channel,
            })
            return t

    def reject(self, token: str, reason: str) -> Ticket:
        with self._lock:
            t = self._require(token)
            t.state = "rejected"
            t.rejected_reason = reason or "未给理由"
            t.history.append({"at": time.time(), "event": "rejected", "reason": t.rejected_reason})
            return t

    def redeem(self, token: str, tool: str, args: dict) -> Ticket:
        """核销。工具执行前调它；任何不符都抛错，工具据此拒绝执行。"""
        with self._lock:
            t = self._tickets.get(token)
            if t is None:
                raise PermissionError("confirm_token 不存在或已被清理")
            st = t.effective_state()
            if st == "pending":
                raise PermissionError("该 confirm_token 尚未经人工批准，拒绝执行")
            if st != "approved":
                raise PermissionError(f"confirm_token 状态为 {st}，拒绝执行")
            if t.tool != tool:
                raise PermissionError(f"confirm_token 是为 {t.tool} 批的，不能用于 {tool}")
            if t.args_digest != digest(args):
                raise PermissionError("参数与批准时不一致，拒绝执行；请重新申请确认")
            t.state = "consumed"
            t.history.append({"at": time.time(), "event": "consumed"})
            return t

    def get(self, token: str) -> Ticket:
        with self._lock:
            return self._require(token)

    def list(self, include_done: bool = False) -> list[dict]:
        with self._lock:
            self._sweep()
            out = []
            for t in self._tickets.values():
                if not include_done and t.effective_state() != "pending":
                    continue
                out.append(t.public())
            return sorted(out, key=lambda d: d["created_at"], reverse=True)

    def _require(self, token: str) -> Ticket:
        t = self._tickets.get(token)
        if t is None:
            raise KeyError(f"未知 confirm_token：{token}")
        return t

    def _sweep(self) -> None:
        cutoff = time.time() - 3600
        for k in [k for k, v in self._tickets.items() if v.created_at < cutoff]:
            self._tickets.pop(k, None)


REGISTRY = ConfirmRegistry()
