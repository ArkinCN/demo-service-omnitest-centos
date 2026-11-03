"""阶段 2 验收脚本：建任务 → 改字段 → 保存 → 读回，外加四项回归与越权校验。

覆盖主文档阶段 2 的五条验收动作：
    1. 从接口建任务 → 改字段 → 保存；
    2. 刷新（重新读一次）后仍能读回；
    3. 重启服务后仍能读回（用 --resume，重启前后各跑一次）；
    4. 换另一个无权限用户读不到（--strict 模式真造两个账号去读）；
    5. 原登录 / 权限 / 聊天保存 / 额度四项回归不被破坏。

为什么拆两种模式：
    本机当前 `.env` 是 `AUTH_DISABLED=true`（无密码单机模式），此时
    `get_current_user` 一律放行本地管理员，**任何 token 都被忽略**，
    越权用例在 HTTP 层根本构造不出来——不是代码没做，是开关把门拆了。
    所以：`--strict` 在进程内把开关置 false，用 TestClient 走**真实鉴权链路**
    造两个账号互读，验证的是真实代码路径；默认模式打活服务，验证落库与读回。

用法（在 c/backend 目录下）：
    python scripts/verify_stage2.py                 # 打活服务：建→改→读回 + 四项回归
    python scripts/verify_stage2.py --resume 12     # 重启服务后再跑：只读回第 12 号任务
    python scripts/verify_stage2.py --strict        # 进程内真鉴权：401 / 403 / 登录 / 聊天 / 额度
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PASS = "[OK]  "
FAIL = "[NG]  "
INFO = "      "

_failed = 0


def check(cond: bool, label: str, detail: str = "") -> bool:
    """断言并留痕。失败不中断，跑完全部用例再汇总——一条红不影响看全貌。"""
    global _failed
    if cond:
        print(f"{PASS}{label}" + (f"  {detail}" if detail else ""))
    else:
        _failed += 1
        print(f"{FAIL}{label}" + (f"  {detail}" if detail else ""))
    return cond


def http(method: str, url: str, body: dict | None = None, token: str | None = None):
    """统一请求。返回 (状态码, 解析后的 dict 或 None, 原始文本)。"""
    data = None
    headers: dict[str, str] = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw), raw
        except Exception:
            return e.code, None, raw
    try:
        return 200, json.loads(raw), raw
    except Exception:
        return 200, None, raw


def data_of(resp: dict | None):
    """取统一包装里的 data。"""
    return (resp or {}).get("data")


# ==================================================================== 默认模式

def live_flow(base: str, scene_id: str) -> None:
    print("=" * 74)
    print(f"阶段 2 · 活服务验证   目标：{base}")
    print("=" * 74)

    code, resp, _ = http("GET", f"{base}/health")
    check(code == 200, "服务可达 /health", f"HTTP {code}")

    code, resp, _ = http("GET", f"{base}/api/v1/auth/mode")
    mode = data_of(resp) or {}
    print(f"{INFO}鉴权模式：auth_disabled={mode.get('auth_disabled')}"
          f" default_username={mode.get('default_username')}")
    if mode.get("auth_disabled"):
        print(f"{INFO}（无密码模式：越权用例在此模式下无法构造，请用 --strict 单独验证）")

    # 1 · 建任务
    title0 = "阶段2联调任务"
    code, resp, raw = http("POST", f"{base}/api/v1/tasks",
                           {"title": title0, "scene_id": scene_id, "version": "v0", "status": "draft"})
    task = data_of(resp) or {}
    if not check(code == 200 and task.get("id"), "建任务 POST /api/v1/tasks", f"HTTP {code} {raw[:120]}"):
        return
    tid = task["id"]
    print(f"{INFO}task_id={tid}  user_id={task.get('user_id')}  created_at={task.get('created_at')}")

    # 2 · 改字段（只改标题与状态，验证 PATCH 只更新传入字段）
    code, resp, raw = http("PATCH", f"{base}/api/v1/tasks/{tid}",
                           {"title": "阶段2联调任务-已改", "status": "confirmed"})
    t2 = data_of(resp) or {}
    check(code == 200, "改字段 PATCH /api/v1/tasks/{id}", f"HTTP {code} {raw[:120]}")
    check(t2.get("title") == "阶段2联调任务-已改", "标题已更新", str(t2.get("title")))
    check(t2.get("status") == "confirmed", "状态已更新", str(t2.get("status")))
    check(t2.get("version") == "v0", "未传字段保持原值（exclude_unset 生效）", str(t2.get("version")))

    # 3 · 读回（等价于刷新页面）
    code, resp, raw = http("GET", f"{base}/api/v1/tasks/{tid}")
    t3 = data_of(resp) or {}
    check(code == 200, "读回 GET /api/v1/tasks/{id}", f"HTTP {code}")
    check(t3.get("title") == "阶段2联调任务-已改", "刷新后标题与保存一致", str(t3.get("title")))
    check(t3.get("status") == "confirmed", "刷新后状态与保存一致", str(t3.get("status")))

    # ---- 四项回归：登录态 / 权限 / 聊天保存 / 额度
    print("-" * 74)
    print("四项回归（原功能不被新增功能破坏）")
    code, resp, raw = http("GET", f"{base}/api/v1/auth/me")
    me = data_of(resp) or {}
    check(code == 200 and me.get("id") is not None, "回归① 登录态可读 /auth/me",
          f"HTTP {code} user={me.get('username')}")

    code, resp, raw = http("POST", f"{base}/api/v1/chats", {"title": "阶段2回归-聊天保存"})
    chat = data_of(resp) or {}
    if check(code == 200 and chat.get("id"), "回归② 聊天保存 POST /chats", f"HTTP {code} {raw[:120]}"):
        cid = chat["id"]
        code2, resp2, _ = http("GET", f"{base}/api/v1/chats/{cid}")
        c2 = data_of(resp2) or {}
        check(code2 == 200 and c2.get("title") == "阶段2回归-聊天保存",
              "回归② 聊天可读回", f"HTTP {code2} title={c2.get('title')}")
        http("DELETE", f"{base}/api/v1/chats/{cid}")
        print(f"{INFO}测试聊天已清理（id={cid}）")

    code, resp, raw = http("GET", f"{base}/api/v1/credits/overview")
    ov = data_of(resp) or {}
    check(code == 200 and ov.get("balance") is not None, "回归③ 额度查询 /credits/overview",
          f"HTTP {code} balance={ov.get('balance')} plan={ov.get('plan_key')}")

    code, resp, raw = http("GET", f"{base}/api/v1/credits/transactions?page=1&page_size=5")
    check(code == 200, "回归③ 额度流水 /credits/transactions", f"HTTP {code}")

    code, resp, raw = http("GET", f"{base}/api/v1/auth/mode")
    check(code == 200, "回归④ 权限模式接口 /auth/mode", f"HTTP {code}")

    print("-" * 74)
    print(f"重启服务后复核读回：python scripts/verify_stage2.py --resume {tid}")


def resume_flow(base: str, task_id: str) -> None:
    print("=" * 74)
    print(f"阶段 2 · 重启后读回   目标：{base}  task_id={task_id}")
    print("=" * 74)
    code, resp, raw = http("GET", f"{base}/api/v1/tasks/{task_id}")
    t = data_of(resp) or {}
    check(code == 200, "重启后仍能读回", f"HTTP {code} {raw[:160]}")
    if code == 200:
        print(f"{INFO}title={t.get('title')}  status={t.get('status')}  version={t.get('version')}")
        print(f"{INFO}created_at={t.get('created_at')}  updated_at={t.get('updated_at')}")


# ================================================================== strict 模式

def strict_flow() -> None:
    """进程内真鉴权：临时关掉 AUTH_DISABLED，造两个账号互读。

    只改本进程的 settings，不动 .env、不影响已在运行的 uvicorn。
    TestClient 不套 with，因此不触发 startup（建表/seed 都跳过，表已由活服务建好）。
    """
    print("=" * 74)
    print("阶段 2 · 严格鉴权验证（进程内临时关闭 AUTH_DISABLED）")
    print("=" * 74)

    sys.path.insert(0, str(BACKEND_ROOT))
    from app.core.config import settings
    try:
        settings.AUTH_DISABLED = False
    except Exception as e:  # pydantic 冻结字段时会抛，此时只能停下让人改 .env
        print(f"{FAIL}无法在进程内关闭 AUTH_DISABLED：{e}")
        print(f"{INFO}请手动把 c/backend/.env 的 AUTH_DISABLED 改 false 并重启服务后重跑")
        return

    from sqlmodel import Session, select
    from fastapi.testclient import TestClient

    from app.db.session import engine
    from app.main import app
    from app.models.task import Task
    from app.models.user import User

    OWNER = ("s2_owner", "s2_owner@example.internal")
    OTHER = ("s2_other", "s2_other@example.internal")
    PWD = "S2test123456"

    def ensure_user(session: Session, username: str, email: str) -> User:
        u = session.exec(select(User).where(User.username == username)).first()
        if u:
            return u
        u = User(username=username, nickname=username, email=email, auth_type="EMAIL",
                 role="user", is_active=True, email_verified=True)
        u.set_password(PWD)
        session.add(u)
        session.commit()
        session.refresh(u)
        return u

    with Session(engine) as session:
        owner = ensure_user(session, *OWNER)
        other = ensure_user(session, *OTHER)
        print(f"{INFO}owner={owner.username}(id={owner.id})  other={other.username}(id={other.id})")

    client = TestClient(app)
    V1 = "/api/v1"

    # ① 无 token 一律 401
    code, resp, raw = http_status(client, "GET", f"{V1}/tasks/1")
    check(code == 401, "无凭据访问任务被拒 401", f"HTTP {code}")

    # ② 登录拿 token（真实 AuthService 校验密码）
    r = client.post(f"{V1}/auth/login", json={"username": OWNER[0], "password": PWD})
    tok_owner = token_of(r)
    check(r.status_code == 200 and tok_owner, "回归① 登录成功并签发 token", f"HTTP {r.status_code}")

    r2 = client.post(f"{V1}/auth/login", json={"username": OWNER[0], "password": "wrong-password"})
    check(r2.status_code in (400, 401, 403), "回归① 错误密码被拒", f"HTTP {r2.status_code}")

    r3 = client.post(f"{V1}/auth/login", json={"username": OTHER[0], "password": PWD})
    tok_other = token_of(r3)
    check(r3.status_code == 200 and tok_other, "第二个账号登录成功", f"HTTP {r3.status_code}")

    if not (tok_owner and tok_other):
        print(f"{FAIL}token 缺失，后续越权用例无法进行")
        return

    # ③ 归属校验：owner 建 → owner 读改 → other 读改均 403
    r = client.post(f"{V1}/tasks", json={"title": "strict-建", "scene_id": "s2", "version": "v0"},
                    headers=auth(tok_owner))
    task = (r.json().get("data") or {})
    if not check(r.status_code == 200 and task.get("id"), "owner 建任务", f"HTTP {r.status_code}"):
        return
    tid = task["id"]
    check(task.get("user_id") == owner.id, "user_id 取登录态而非前端传参",
          f"task.user_id={task.get('user_id')} owner.id={owner.id}")

    r = client.get(f"{V1}/tasks/{tid}", headers=auth(tok_owner))
    check(r.status_code == 200 and (r.json().get("data") or {}).get("title") == "strict-建",
          "owner 读回自己的任务", f"HTTP {r.status_code}")

    r = client.patch(f"{V1}/tasks/{tid}", json={"title": "strict-已改"}, headers=auth(tok_owner))
    check(r.status_code == 200 and (r.json().get("data") or {}).get("title") == "strict-已改",
          "owner 改自己的任务", f"HTTP {r.status_code}")

    r = client.get(f"{V1}/tasks/{tid}", headers=auth(tok_other))
    check(r.status_code == 403, "验收④ 另一无权限用户读不到（GET 403）", f"HTTP {r.status_code}")

    r = client.patch(f"{V1}/tasks/{tid}", json={"title": "被别人改了"}, headers=auth(tok_other))
    check(r.status_code == 403, "验收④ 另一无权限用户改不动（PATCH 403）", f"HTTP {r.status_code}")

    r = client.get(f"{V1}/tasks/{tid}", headers=auth(tok_owner))
    check((r.json().get("data") or {}).get("title") == "strict-已改",
          "越权尝试后数据未被改动", str((r.json().get("data") or {}).get("title")))

    # ④ 聊天保存与隔离
    r = client.post(f"{V1}/chats", json={"title": "strict-聊天"}, headers=auth(tok_owner))
    cid = (r.json().get("data") or {}).get("id")
    check(r.status_code == 200 and cid, "回归② owner 建聊天", f"HTTP {r.status_code}")
    if cid:
        r = client.get(f"{V1}/chats/{cid}", headers=auth(tok_owner))
        check(r.status_code == 200, "回归② owner 读回聊天", f"HTTP {r.status_code}")
        r = client.get(f"{V1}/chats/{cid}", headers=auth(tok_other))
        check(r.status_code in (403, 404), "回归② 另一用户读不到该聊天", f"HTTP {r.status_code}")
        r = client.get(f"{V1}/chats?page=1&page_size=50", headers=auth(tok_other))
        items = (r.json().get("data") or {}).get("items") or (r.json().get("data") or {}).get("chats") or []
        check(all(str(c.get("id")) != str(cid) for c in items),
              "回归② 另一用户列表里没有该聊天", f"other 可见 {len(items)} 条")

    # ⑤ 额度
    r = client.get(f"{V1}/credits/overview", headers=auth(tok_owner))
    ov = r.json().get("data") or {}
    check(r.status_code == 200 and ov.get("balance") is not None,
          "回归③ owner 额度可读", f"HTTP {r.status_code} balance={ov.get('balance')}")

    # 清理：测试任务、测试聊天、两个测试账号
    with Session(engine) as session:
        t = session.get(Task, tid)
        if t:
            session.delete(t)
        session.commit()
    if cid:
        client.delete(f"{V1}/chats/{cid}", headers=auth(tok_owner))
    with Session(engine) as session:
        for name in (OWNER[0], OTHER[0]):
            u = session.exec(select(User).where(User.username == name)).first()
            if u:
                session.delete(u)
        session.commit()
    print(f"{INFO}已清理：任务 {tid}、聊天 {cid}、账号 {OWNER[0]}/{OTHER[0]}")
    print(f"{INFO}注：本模式只改了本进程的 settings，运行中的 uvicorn 仍是 AUTH_DISABLED=true")


def http_status(client, method: str, url: str, **kw):
    r = client.request(method, url, **kw)
    return r.status_code, None, r.text


def token_of(resp) -> str | None:
    try:
        d = resp.json().get("data") or {}
        tok = d.get("tokens") or {}
        return tok.get("access_token") or tok.get("accessToken")
    except Exception:
        return None


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8011")
    ap.add_argument("--scene", default="motor.cooling-fan.fortior-fu6832")
    ap.add_argument("--resume", default="", help="重启服务后按 task_id 复核读回")
    ap.add_argument("--strict", action="store_true", help="进程内真鉴权：造两账号验 401/403")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    if args.strict:
        strict_flow()
    elif args.resume:
        resume_flow(base, args.resume)
    else:
        live_flow(base, args.scene)

    print("=" * 74)
    if _failed:
        print(f"结论：{_failed} 项未通过（见上方 [NG]）")
    else:
        print("结论：本轮用例全部通过")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
