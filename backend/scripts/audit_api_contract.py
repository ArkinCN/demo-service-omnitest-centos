"""前后端接口契约审查：后端实际挂载的端点 vs 前端实际调用的路径。

用途：一次性找出三类问题，避免靠肉眼翻文件：
  1. 前端调了但后端没有的端点（会 404）
  2. 后端有但前端从未调用的端点（可能是死代码，或前端漏接）
  3. 路径前缀不一致（前端 /api/x 而后端挂 /api/v1/x 之类）

只读，不修改任何文件。

实现要点（踩过的坑，别改回去）：
  · include_router 的第一个实参可能是 `mod.router`、`mod.admin_router`、`mod.proxy_router`，
    必须按**router 变量名**去模块文件里找对应装饰器（`@admin_router.get`），
    只认 `@router.` 会把一批端点整个漏掉。
  · prefix 可能是 f-string（f"{settings.API_V1_PREFIX}/updates"）或直接字面量，
    要先解析 API_V1_PREFIX 的实参再代入。
  · 前端大多不写 fetch('/api/x')，而是把路径存在常量或模板字符串里再传给 fetch，
    所以采「所有以 /api 开头的字面量」比只采 fetch 首参准得多。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
C = REPO / "c"
BACKEND = C / "backend"
WEB = C / "web"

SKIP = {"node_modules", "target", "dist", "__pycache__", ".git", ".venv"}
METHODS = "get|post|put|patch|delete|websocket"

# ── 后端采集 ──
# include_router(vibe_coding.admin_router, prefix=f"{settings.API_V1_PREFIX}/updates", tags=[...])
# ⚠️ prefix 是**可选的**：本项目新增的 interlocks / reports / evaluate 三处写的是
#    `include_router(x.router)`，不带 prefix（前缀写在各自 APIRouter(prefix="/api") 里）。
#    早期版本把 prefix 写成必选，导致这三个模块的端点整个漏采。
RE_INCLUDE = re.compile(
    r"include_router\(\s*([\w.]+)\s*(?:,\s*prefix\s*=\s*(.*?))?\s*(?:,\s*tags|\))",
    re.S,
)
# admin_router = APIRouter(prefix="/admin", tags=[...])
# 只匹配到左括号，参数串用括号配对提取（见 _extract_args）——
# 正则 `(.*?)\)` 会被 tags=["x"] 里的方括号/嵌套搞坏。
RE_ROUTER_DECL = re.compile(r"^(\w+)\s*=\s*APIRouter\(", re.M)
RE_ROUTER_PREFIX = re.compile(r'prefix\s*=\s*["\']([^"\']*)["\']')
# @admin_router.get("/xxx")
RE_ROUTE = re.compile(rf"@(\w+)\.({METHODS})\(\s*[\"']([^\"']*)[\"']")


def _api_v1_prefix() -> str:
    """从 config.py 取 API_V1_PREFIX 的实参（include_router 里引用的是 settings.API_V1_PREFIX）。"""
    cfg = (BACKEND / "app" / "core" / "config.py").read_text(encoding="utf-8")
    m = re.search(r'API_V1_PREFIX:\s*str\s*=\s*"([^"]+)"', cfg)
    return m.group(1) if m else "/api/v1"


def _extract_args(src: str, open_idx: int) -> str:
    """从 open_idx 处的 '(' 开始做括号配对，返回里面的参数串。

    为什么要手写配对而不是正则：APIRouter(...) 的参数里可能出现
    tags=["a"] 这类带方括号、甚至嵌套括号的表达式，正则的 `\\(.*?\\)`
    会在第一个右括号就收尾，取到半截参数。
    """
    depth = 0
    for j in range(open_idx, len(src)):
        if src[j] == "(":
            depth += 1
        elif src[j] == ")":
            depth -= 1
            if depth == 0:
                return src[open_idx + 1 : j]
    return ""


def _resolve_prefix(expr: str | None, api_v1: str) -> str:
    """把 prefix= 后面的表达式解析成实际字符串。

    支持三种写法：
      None                                          → ""（未指定，前缀由 APIRouter 自带）
      settings.API_V1_PREFIX                        → /api/v1
      f"{settings.API_V1_PREFIX}/updates"           → /api/v1/updates
      "/api"                                        → /api
    解析不了就原样返回（宁可显示原始表达式，也不要静默当成空）。
    """
    if expr is None:
        return ""
    expr = expr.strip()
    if "API_V1_PREFIX" in expr:
        s = expr[1:] if expr.startswith("f") else expr
        s = s.strip().strip("\"'")
        # 两种形态都要换：f-string 里是 {settings.API_V1_PREFIX}，
        # 直接引用时是裸标识符 settings.API_V1_PREFIX（少了这一步，tasks 的前缀会原样输出）
        return s.replace("{settings.API_V1_PREFIX}", api_v1).replace(
            "settings.API_V1_PREFIX", api_v1
        )
    q = re.search(r'["\']([^"\']*)["\']', expr)
    return q.group(1) if q else ""


def collect_backend() -> list[tuple[str, str, str]]:
    """返回 [(方法, 完整路径, 模块文件)]。"""
    main = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    api_v1 = _api_v1_prefix()
    v1_dir = BACKEND / "app" / "api" / "v1"

    out: list[tuple[str, str, str]] = []
    for m in RE_INCLUDE.finditer(main):
        qual, expr = m.group(1), m.group(2)
        base = _resolve_prefix(expr, api_v1)

        parts = qual.split(".")
        if len(parts) == 1:
            mod_file, router_var = parts[0], "router"
        else:
            mod_file, router_var = parts[0], parts[1]

        f = v1_dir / f"{mod_file}.py"
        if not f.exists():
            out.append(("?", f"{base}/*[{mod_file}.py 未找到]", str(f.name)))
            continue

        src = f.read_text(encoding="utf-8")
        # 该 router 变量自带的 prefix
        sub = ""
        for dm in RE_ROUTER_DECL.finditer(src):
            if dm.group(1) != router_var:
                continue
            args = _extract_args(src, dm.end() - 1)
            pm = RE_ROUTER_PREFIX.search(args)
            sub = pm.group(1) if pm else ""
            break

        for rm in RE_ROUTE.finditer(src):
            if rm.group(1) != router_var:
                continue  # 别的 router，不属于本次挂载
            full = f"{base}{sub}{rm.group(3)}"
            out.append((rm.group(2).upper(), full or "/", f.name))
    return out


# ── 前端采集 ──
# 采所有以 /api 开头的字面量：单引号、双引号、模板字符串都算。
# 模板里的 ${x} 后面归一成 {p}，正好与后端的 {param} 对齐。
RE_PATH_LIT = re.compile(r"""[`'"](/(?:api|scenes|kb|data)[^`'"\s]*)[`'"]""")


def collect_frontend() -> list[tuple[str, int, str]]:
    """返回 [(相对路径, 行号, 字面量)]。"""
    out: list[tuple[str, int, str]] = []
    for p in sorted(WEB.rglob("*")):
        if not p.is_file() or p.suffix not in (".ts", ".tsx"):
            continue
        if any(x in p.parts for x in SKIP):
            continue
        # vite.config.ts 里的 /api 是**代理规则**不是运行时调用，参与比对纯属误报
        if p.name in ("vite.config.ts", "vite.config.js"):
            continue
        src = p.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(src.splitlines(), 1):
            for m in RE_PATH_LIT.finditer(line):
                out.append((str(p.relative_to(WEB)), i, m.group(1)))
    return out


def norm(p: str) -> str:
    """归一路径参数：/api/runs/${id} 与 /api/runs/{run_id} 都变成 /api/runs/{p}。"""
    p = p.split("?")[0]
    p = re.sub(r"\$\{[^}]*\}", "{p}", p)
    p = re.sub(r"\{[^}]*\}", "{p}", p)
    return p.rstrip("/") or "/"


def main() -> int:
    endpoints = collect_backend()
    calls = collect_frontend()

    be = {}  # 归一路经 -> [(方法, 原始, 模块)]
    for method, path, mod in endpoints:
        be.setdefault(norm(path), []).append((method, path, mod))

    fe: dict[str, list[tuple[str, int, str]]] = {}
    for rel, ln, raw in calls:
        if not raw.startswith("/api"):
            continue  # 只比对后端 API，静态资源路径不参与
        fe.setdefault(norm(raw), []).append((rel, ln, raw))

    print("=" * 74)
    print(f"后端挂载端点: {len(endpoints)} 个（归一后 {len(be)} 条）")
    print(f"前端 API 字面量: {len([c for c in calls if c[2].startswith('/api')])} 处（归一后 {len(fe)} 条）")
    print("=" * 74)

    # ① 前端调了、后端没有
    # 前端清单先打出来：便于人工核对有没有采漏（例如路径常量拼接、跨行模板串）
    print("\n【前端 API 调用清单】")
    for n in sorted(fe):
        for rel, ln, raw in fe[n]:
            print(f"   {rel}:{ln}  →  {raw}")

    print("\n【① 前端调用了但后端无对应端点】")
    miss = 0
    for n in sorted(fe):
        if n in be:
            continue
        for rel, ln, raw in fe[n]:
            print(f"   {rel}:{ln}  →  {raw}")
            miss += 1
    if miss == 0:
        print("   （无）")

    # ② 后端有、前端没调（只报本项目新增的 /api 无 v1 前缀那批，客户原有模块本就没接）
    print("\n【② 后端有但前端从未调用（限本项目新增模块）】")
    # ⚠️ 白名单必须与 main.py 里挂 /api 前缀的本项目模块**一一对应**，新模块要记得加。
    # 曾漏 kb_documents.py：它是 2026-09-24 后新增的模块，漏进白名单导致它的 12 个
    # 路由在「②」里整模块漏检（漏检 ≠ 无缺口）。
    own_mods = {"agent_stream.py", "kb.py", "kb_entries.py", "kb_documents.py",
                "runs.py", "interlocks.py", "reports.py", "evaluate.py"}
    # 预留端点：后端为「阶段 5 接设备桥」或「运维/内部」先行实现、前端本就不该 fetch 的
    # 端点。它们出现在「②」里是**预期**，不是缺口——单列出来，避免每次审查都当问题报。
    # 依据见各模块文件头注释（interlocks/runs「阶段5接设备桥后补真实执行」、kb「调用方是界面/脚本」等）。
    reserved = {
        # 安全联锁 + 闸门 + 急停（阶段 5 接设备桥，前端当前读场景包 pack.interlocks）
        "/api/interlocks", "/api/interlocks/{p}", "/api/interlocks/{p}/confirm",
        "/api/gates/{p}", "/api/gates/{p}/check", "/api/estop",
        # 动作记录（阶段 4 只记录不真下发，阶段 5 补真实执行）
        "/api/runs/{p}/actions",
        # 引用登记 + 向量索引管理（内部/运维端点，前端无对应 UI）
        "/api/kb/refs", "/api/kb/vector/stat", "/api/kb/vector/rebuild",
        # 检索走后端 agent 工具链（enabled_tools=KnowledgeSearch），非前端直接 fetch
        "/api/kb/search",
        # 条目详情冗余（列表已带全 content）；版本历史前端暂无 UI
        "/api/kb/entries/{p}", "/api/kb/entries/{p}/versions",
        # 脚本盲区（前端实际已接，只是调用方式采不到字面量）：
        #   · run  → uploadApi.ts runPipeline 用模板串 + query 动态拼，RE_PATH_LIT 归一后对不上
        #   · figure → KnowledgeModule.tsx 合成稿 iframe 里 <img> 用绝对 URL（HTML 字符串内动态拼）
        "/api/kb/documents/{p}/run", "/api/kb/documents/{p}/figure",
    }
    unused = 0
    reserved_hits = 0
    for n in sorted(be):
        if n in fe:
            continue
        methods, raw, mod = be[n][0]
        if mod not in own_mods:
            continue
        if n in reserved:
            print(f"   [预留] {methods:6} {raw}   [{mod}]")
            reserved_hits += 1
            continue
        print(f"   [未接] {methods:6} {raw}   [{mod}]")
        unused += 1
    if unused == 0 and reserved_hits == 0:
        print("   （无）")

    print("\n" + "=" * 74)
    print(f"小结：① {miss} 处  |  ② 未接 {unused} 处、预留 {reserved_hits} 处")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
