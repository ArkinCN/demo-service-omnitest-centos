"""代码质量审查：静默吞异常 / 硬编码 / 过时注释 / 遗留文件 / 死代码。

与 audit_api_contract.py（协议）、audit_enum_contract.py（枚举）并列，
三者合起来覆盖本次全量审查的静态部分。

为什么这几项要专门扫：
  · **静默吞异常**：本轮审查的导火索就是它——前端用错的 artifact_kind 落盘
    被后端 409 拒掉，而调用处 `catch {}` 把异常吞了，界面上看不出任何问题，
    「刷新后找回轮次」这项验收因此长期挂着却查不到原因。
  · **硬编码**：本项目已定「配置全外置」规范，但规范靠人守不住，要靠工具复查。
  · **过时注释**：改造后注释没跟着改，会误导后来者按错的假设去改代码。

只读，不修改任何文件。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
C = REPO / "c"
BACKEND = C / "backend"
WEB = C / "web"

SKIP_DIRS = {"node_modules", "dist", "__pycache__", "target", ".git", ".venv", "build"}


def iter_files(root: Path, suffixes: tuple[str, ...]):
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix not in suffixes:
            continue
        if any(x in p.parts for x in SKIP_DIRS):
            continue
        yield p


# ── 1. 静默吞异常 ──
# Python: except 块内只有 pass 或只有注释
RE_PY_EXCEPT = re.compile(r"^\s*except[^\n:]*:\s*$", re.M)
# TS/JS: catch {} 或 catch (e) {} —— 空块或块内只有注释
RE_TS_CATCH_EMPTY = re.compile(r"catch\s*\([^)]*\)?\s*\{\s*(?://[^\n]*\s*)*\}")
RE_TS_CATCH_COMMENT = re.compile(
    r"catch\s*\([^)]*\)?\s*\{(?:[^{}]|\{[^{}]*\})*?\}", re.S
)


def scan_silent_py() -> list[tuple[str, int, str]]:
    """Python 里 except 块内无语句的（pass / 只有注释 / 空）。"""
    out = []
    for p in iter_files(BACKEND / "app", (".py",)):
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        for i, line in enumerate(lines):
            if not RE_PY_EXCEPT.match(line):
                continue
            # 收集该 except 块的主体（缩进大于 except 的连续行）
            indent = len(line) - len(line.lstrip())
            body: list[str] = []
            for nxt in lines[i + 1 :]:
                if not nxt.strip():
                    body.append("")
                    continue
                cur = len(nxt) - len(nxt.lstrip())
                if cur <= indent:
                    break
                body.append(nxt.strip())
            real = [b for b in body if b and not b.startswith("#")]
            if not real:
                out.append((str(p.relative_to(C)), i + 1, line.strip()))
            elif real == ["pass"]:
                out.append((str(p.relative_to(C)), i + 1, line.strip() + "  → pass"))
    return out


def scan_silent_ts() -> list[tuple[str, int, str]]:
    """TS/TSX 里 catch 块为空或只有注释的。"""
    out = []
    for p in iter_files(WEB / "src", (".ts", ".tsx")):
        src = p.read_text(encoding="utf-8", errors="ignore")
        for m in RE_TS_CATCH_COMMENT.finditer(src):
            block = m.group(0)
            # 去掉 catch(...) 与花括号，看里面有没有实际语句
            inner = block[block.index("{") + 1 : -1]
            stripped = re.sub(r"//[^\n]*", "", inner)          # 行注释
            stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.S)  # 块注释
            if not stripped.strip():
                ln = src[: m.start()].count("\n") + 1
                out.append((str(p.relative_to(C)), ln, block[:70].replace("\n", " ")))
    return out


# ── 2. 硬编码 ──
# 排除：.env / .env.example / config.py（那是外置配置本身，出现数字是正常的）
RE_PORT = re.compile(r"(?<![\w.])(?:80\d{2}|5173|3080|3000|5000|8080)(?![\w.])")
RE_URL = re.compile(r"https?://[\w.\-:]+")
# 盘符必须**不在 :// 之后**——否则 https://api.deepseek.com 里的 "s://a" 会被
# 当成 `s:` 盘符（首轮就是这么误报的，一次刷出二十多条）。
RE_ABS_WIN = re.compile(r"(?<![:/\w])[A-Za-z]:[\\/](?![\w\\/\-.]*//)[\w\\/\-.]*")
RE_ROOT_LINUX = re.compile(r"/(?:mnt|home|root|usr|opt|etc|var|tmp)/[\w\-./]*")
RE_TIMEOUT = re.compile(r"(?:timeout|TIMEOUT|DELAY|RETRY|LIMIT)\s*[:=]\s*(\d+(?:\.\d+)?)")


def scan_hardcode() -> list[tuple[str, int, str, str]]:
    out = []
    excludes = {".env", ".env.example", "config.py", "paths.py"}
    for p in list(iter_files(BACKEND / "app", (".py",))) + list(
        iter_files(WEB / "src", (".ts", ".tsx"))
    ):
        if p.name in excludes:
            continue
        src = p.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(src.splitlines(), 1):
            s = line.strip()
            if s.startswith("#") or s.startswith("//") or s.startswith("*"):
                continue  # 注释里的示例不算硬编码
            for kind, pat in (
                ("端口", RE_PORT),
                ("URL", RE_URL),
                ("Windows 绝对盘符", RE_ABS_WIN),
                ("Linux 根路径", RE_ROOT_LINUX),
                ("超时/重试/限额", RE_TIMEOUT),
            ):
                m = pat.search(line)
                if m:
                    out.append((str(p.relative_to(C)), i, kind, m.group(0)[:60]))
    return out


# ── 3. 过时注释 ──
RE_STALE = re.compile(r"绝对路径|源目录|/mnt/|~/lab|未实现|尚未接入|恒为\s*null|暂时写死|TODO\s*待接")


def scan_stale_comments() -> list[tuple[str, int, str]]:
    out = []
    for p in list(iter_files(BACKEND / "app", (".py",))) + list(
        iter_files(WEB / "src", (".ts", ".tsx"))
    ):
        src = p.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(src.splitlines(), 1):
            s = line.strip()
            if not (s.startswith("#") or s.startswith("//") or s.startswith("*")):
                continue
            if RE_STALE.search(line):
                out.append((str(p.relative_to(C)), i, s[:100]))
    return out


# ── 4. 遗留文件 ──
def scan_legacy() -> list[tuple[str, str]]:
    out = []
    for p in sorted(BACKEND.rglob("*")):
        if not p.is_file() or any(x in p.parts for x in SKIP_DIRS):
            continue
        name = p.name
        # __init__.py 是 Python 包的必需文件，不是遗留脚本——排除掉，
        # 否则一报就是十几个，把真正的遗留物淹掉。
        if name == "__init__.py":
            continue
        if name.startswith("_") and p.suffix in (".py", ".ps1", ".sh"):
            out.append((str(p.relative_to(C)), "下划线前缀（临时脚本命名）"))
        elif p.suffix == ".sh":
            out.append((str(p.relative_to(C)), "bash 脚本（本项目已全改 .py）"))
        elif p.suffix in (".ps1",):
            out.append((str(p.relative_to(C)), "PowerShell 脚本"))
        elif p.suffix == ".pyc":
            out.append((str(p.relative_to(C)), "字节码（应为构建产物）"))
    return out


def main() -> int:
    print("=" * 74)
    print("代码质量审查")
    print("=" * 74)

    sections = [
        ("① 静默吞异常（最高优先）", None),
        ("② 硬编码", None),
        ("③ 过时注释", None),
        ("④ 遗留文件", None),
    ]

    py_silent = scan_silent_py()
    ts_silent = scan_silent_ts()
    print(f"\n{'─' * 74}\n① 静默吞异常  （Python {len(py_silent)} 处 / TS {len(ts_silent)} 处）")
    for rel, ln, snip in py_silent:
        print(f"   [PY]  {rel}:{ln}   {snip}")
    for rel, ln, snip in ts_silent:
        print(f"   [TS]  {rel}:{ln}   {snip}")
    if not py_silent and not ts_silent:
        print("   （无）")

    hc = scan_hardcode()
    print(f"\n{'─' * 74}\n② 硬编码  （{len(hc)} 处）")
    for rel, ln, kind, snip in hc:
        print(f"   [{kind}]  {rel}:{ln}   {snip}")
    if not hc:
        print("   （无）")

    st = scan_stale_comments()
    print(f"\n{'─' * 74}\n③ 过时注释  （{len(st)} 处）")
    for rel, ln, snip in st:
        print(f"   {rel}:{ln}   {snip}")
    if not st:
        print("   （无）")

    lg = scan_legacy()
    print(f"\n{'─' * 74}\n④ 遗留文件  （{len(lg)} 个）")
    for rel, why in lg:
        print(f"   {rel}   ← {why}")
    if not lg:
        print("   （无）")

    print("\n" + "=" * 74)
    print(
        f"小结：吞异常 {len(py_silent) + len(ts_silent)} | "
        f"硬编码 {len(hc)} | 过时注释 {len(st)} | 遗留文件 {len(lg)}"
    )
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
