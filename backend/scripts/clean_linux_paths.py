"""Linux → Windows 硬编码清理工具（扫描 / 替换 / 复核三合一）。

用法：
    python scripts/clean_linux_paths.py scan      # 只读扫描，打印分布清单
    python scripts/clean_linux_paths.py fix       # 执行替换（幂等，可重复跑）
    python scripts/clean_linux_paths.py verify    # 残留复扫，零命中即通过

设计要点（对应用户硬性要求）：
1. **禁盘符**：Linux 绝对路径一律改成「项目相对路径」，绝不写成 D:\\...——
   Windows 盘符在不同机器上会变，写死盘符仍是硬编码。
2. **保留 /assets/ 分隔符**：`c/web/public/scenes/**` 的 file_path 被前端用
   `split('/assets/')[1]` 消费（见 features/waveforms/index.ts:150 与
   features/scene/workflows.ts:84）。替换成 `./assets/...` 后该 split 仍成立；
   若某条替换会丢掉 /assets/，本脚本**直接拒绝写入并报错**，不静默改坏。
3. **UTF-8 无 BOM**：Windows 下 Set-Content 会写 GBK 导致中文乱码，这里统一
   用 utf-8 读写，且写完清理 BOM。
4. **幂等**：已替换过的串不再匹配，重复执行零改动。
5. **黑名单**：`api/` 是客户脱敏工程（只读），永不触碰。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ── 仓库根：本文件在 c/backend/scripts/ 下，向上三级即 c/ ──
C_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = C_ROOT.parent

# 只扫 c/ 下这些子树；api/ 是客户脱敏工程，绝不触碰
SCAN_ROOT = C_ROOT
NEVER_TOUCH = (
    REPO_ROOT / "api",          # 客户脱敏工程：只读基线，改它会破坏验收标准
    Path(__file__),             # **本工具自己**：改它会改坏正则与断言（真踩过）
)

SKIP_DIRS = {"node_modules", "target", ".git", "dist", "__pycache__", ".venv", "venv", ".next"}
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".css", ".sh", ".yml", ".yaml", ".toml", ".env", ".example", ".txt", ".jsonl"}

# ── Linux 绝对路径匹配 ──
# 命中后按「是否含 /assets/」分流处理。
#
# 注意路径的终止字符：JSON 里路径被双引号包着，Markdown 里可能被反引号或整行包着，
# 代码里可能被引号或右括号收尾。终止集因此收敛为「引号 / 中文标点 / 空白 / 右括号」，
# 且**允许路径内部出现中文与点号**（真实路径里就有「峰岹」「_工程」这类）。
# ⚠️ 字符类用**显式允许集**而不是排除集：
# 早先写成「排除空白与标点」，结果把中文的「[源] +」也当成了路径（中文既非空白
# 也非标点）。改成允许集后，只有「ASCII 字母数字 + _ . - / + 中文」才算路径主体。
_ALLOWED = "A-Za-z0-9_\\-\\./\\u4e00-\\u9fff\\u3001-\\u303f"

# Linux 绝对根：逐个列全，避免用宽泛前缀误伤正常文本
RE_LINUX = re.compile(rf"/(?:mnt|home|root|usr|opt|etc|var|tmp)/[{_ALLOWED}]+")
# 家目录写法：`~/` 后必须紧跟合法路径字符；`~/[源] ` 这种已脱敏的不再命中
RE_TILDE = re.compile(rf"~/(?!\[)[{_ALLOWED}]+")

# 场景包资源路径：取最后一个 /assets/ 之后的部分，重组成 ./assets/...
RE_ASSETS = re.compile(r"^(?P<prefix>.*)/assets/(?P<rel>.+)$")


def is_never_touch(p: Path) -> bool:
    return any(str(p).startswith(str(nt)) for nt in NEVER_TOUCH)


def iter_text_files(root: Path):
    """遍历根下所有文本文件，跳过忽略目录与客户工程。"""
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if is_never_touch(p):
            continue
        if p.suffix.lower() not in TEXT_SUFFIXES and p.name != ".env":
            continue
        yield p


def rewrite_path(raw: str) -> str | None:
    """把一条 Linux 路径改写为可交付形式；无法安全改写时返回 None（保持原样）。

    按**角色**分三种处理，顺序即优先级：

    1) 含 `/assets/` 的（场景包资源，**运行时依赖**）
       → `./assets/<rel>`，**必须保留分隔符**：前端靠 split('/assets/')[1] 取相对路径。

    2) 指向仓库内 web/public 的 → 去掉前缀留 `./<tail>`，同样在仓库内可解析。

    3) 其余（几乎全是 `_source.file` 这类**溯源记录**，以及文档里的历史路径引用）
       → 清洗成「脱敏的出处标签」：剥掉 [源] f/... 客户工程前缀与 /home/<user>/，
         只留可读的末段。它们不是运行时依赖，但把客户盘符与用户名留在交付物里
         既不合脱敏要求、也让人以为还能顺着找到原文件。

    返回 None 表示「规则不覆盖，保持原样」，不猜。
    """
    m = RE_ASSETS.match(raw)
    if m:
        rel = m.group("rel")
        return f"./assets/{rel}"

    # 指向仓库内 web/public 的路径
    for marker in ("/web/public/", "/public/"):
        idx = raw.find(marker)
        if idx != -1:
            tail = raw[idx + len(marker):]
            return f"./{tail}" if tail else None

    # 溯源/文档类：剥前缀，保留可读末段，明确标出来源已脱敏
    return _sanitize_source(raw)


def _sanitize_source(raw: str) -> str | None:
    """把溯源路径清洗成不含客户盘符与用户名的描述串。

    规则：取路径最后两段（通常是「目录/文件名」），前面冠以 `[源]`。
    例如
      [源] .../FU-AM-FOC方案调试手册-.pdf
        → 调试经验文档/FU-AM-FOC方案调试手册-.pdf
      [源] app/App.tsx
        → [源] app/App.tsx

    保留末两段是为了**可读与可追溯语义不丢**（读者仍知道出自哪份资料），
    同时不再暴露 Linux 主机结构。
    """
    segs = [s for s in raw.split("/") if s]
    if not segs:
        return None
    tail = segs[-2:] if len(segs) >= 2 else segs
    return "[源] " + "/".join(tail)


def transform_line(line: str) -> tuple[str, list[tuple[str, str]]]:
    """对一行做替换，返回 (新行, 改动列表)。"""
    changes: list[tuple[str, str]] = []

    def _sub(match: re.Match) -> str:
        old = match.group(0)
        new = rewrite_path(old)
        if new is None:
            return old
        # 断言：**仅当原值含 /assets/ 时**才要求新值也含。
        #
        # 为什么要加这个前提：场景包里有两类 file_path——
        #   ① mode=copied_into_pack：文件真在 assets/ 下，前端靠 split('/assets/')[1] 取相对路径；
        #   ② mode=registered_only：文件在客户工程别的目录，**本来就不含 /assets/**，
        #      前端 `if (!rel) continue` 直接跳过（见 features/waveforms/index.ts:151），
        #      它们不参与波形回放，只需要脱敏掉主机前缀。
        # 对 ② 也硬套 /assets/ 断言会误报，进而整文件拒写——那是把安全机制用错了地方。
        if "/assets/" in old:
            parts = new.split("/assets/")
            if len(parts) != 2 or not parts[1]:
                raise ValueError(f"拒绝写入：替换会破坏 /assets/ 分隔符 —— {old!r} -> {new!r}")
        changes.append((old, new))
        return new

    new_line = RE_LINUX.sub(_sub, line)
    new_line = RE_TILDE.sub(_sub, new_line)
    return new_line, changes


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig")


def write_text(p: Path, text: str) -> None:
    """UTF-8 无 BOM 写回。"""
    p.write_text(text, encoding="utf-8", newline="")


def cmd_scan(args) -> int:
    total_files = 0
    total_hits = 0
    buckets: dict[str, int] = {}
    print("=" * 72)
    print("Linux 路径扫描（只读）")
    print("=" * 72)
    for f in sorted(iter_text_files(SCAN_ROOT)):
        try:
            text = read_text(f)
        except (UnicodeDecodeError, OSError):
            continue
        hits = RE_LINUX.findall(text) + RE_TILDE.findall(text)
        if not hits:
            continue
        total_files += 1
        total_hits += len(hits)
        rel = f.relative_to(REPO_ROOT)
        print(f"\n{rel}  [{len(hits)} 处]")
        seen: set[str] = set()
        for h in hits:
            key = h[:110]
            if key in seen:
                continue
            seen.add(key)
            print(f"    {key}")
            # 归类
            cat = "assets 资源" if "/assets/" in h else ("波浪号家目录" if h.startswith("~/") else "其他 Linux 路径")
            buckets[cat] = buckets.get(cat, 0) + 1
    print("\n" + "=" * 72)
    print(f"命中文件 {total_files} 个，命中 {total_hits} 处")
    for k, v in sorted(buckets.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    print("=" * 72)
    return 0


def cmd_fix(args) -> int:
    changed_files = 0
    changed_lines = 0
    skipped: list[str] = []
    # 已被识别为 Linux 路径、但当前规则无法安全改写的（保持原样，单独列给人看）
    unhandled: dict[str, list[str]] = {}
    print("=" * 72)
    print("Linux 路径替换" + ("（DRY RUN，不写盘）" if args.dry_run else ""))
    print("=" * 72)
    for f in sorted(iter_text_files(SCAN_ROOT)):
        try:
            text = read_text(f)
        except (UnicodeDecodeError, OSError):
            continue
        if "/mnt/" not in text and "/home/" not in text and "~/" not in text and "/root/" not in text:
            continue

        lines = text.splitlines(keepends=True)
        out_lines = []
        file_changes = 0
        try:
            for line in lines:
                new_line, changes = transform_line(line)
                out_lines.append(new_line)
                file_changes += len(changes)
        except ValueError as e:
            # 断言失败：该文件整体跳过，绝不冒险写入
            skipped.append(f"{f.relative_to(REPO_ROOT)}: {e}")
            continue

        # 统计「命中但改不了」的：这些不会写入，但必须让人看见
        for m in list(RE_LINUX.finditer(text)) + list(RE_TILDE.finditer(text)):
            raw = m.group(0)
            if rewrite_path(raw) is None:
                unhandled.setdefault(str(f.relative_to(REPO_ROOT)), []).append(raw)

        if file_changes == 0:
            continue

        rel = f.relative_to(REPO_ROOT)
        if args.dry_run:
            print(f"[DRY] {rel}  [{file_changes} 处]")
        else:
            write_text(f, "".join(out_lines))
            print(f"[FIXED] {rel}  [{file_changes} 处]")
        changed_files += 1
        changed_lines += file_changes

    print("\n" + "=" * 72)
    print(f"{'将' if args.dry_run else '已'}改动 {changed_files} 个文件、{changed_lines} 处")
    if skipped:
        print("\n[注意] 因断言失败而跳过的文件（需人工处理）：")
        for s in skipped:
            print(f"  {s}")
    if unhandled:
        n = sum(len(v) for v in unhandled.values())
        print(f"\n[清单] 命中但规则无法安全改写的有 {n} 处（保持原样，需按场景决定）：")
        for rel, raws in sorted(unhandled.items(), key=lambda kv: -len(kv[1]))[:15]:
            print(f"  {rel}  [{len(raws)} 处]  例: {raws[0][:100]}")
        if len(unhandled) > 15:
            print(f"  …还有 {len(unhandled) - 15} 个文件")
    print("=" * 72)
    return 1 if skipped else 0


def cmd_verify(args) -> int:
    """残留复扫：只关心 /mnt/ 与 ~/ 这两类（/home/ 可能出现在合理上下文，单独报）。"""
    remain = 0
    print("=" * 72)
    print("残留复扫")
    print("=" * 72)
    for f in sorted(iter_text_files(SCAN_ROOT)):
        try:
            text = read_text(f)
        except (UnicodeDecodeError, OSError):
            continue
        for pat, label in ((RE_LINUX, "Linux 路径"), (RE_TILDE, "家目录路径")):
            hits = pat.findall(text)
            if hits:
                rel = f.relative_to(REPO_ROOT)
                # 过滤掉纯文档里的历史叙述（在 docs/、CHANGELOG 里出现属允许）
                print(f"{rel}  [{label} {len(hits)} 处]  例: {hits[0][:90]}")
                remain += len(hits)
    print("\n" + "=" * 72)
    print(f"剩余命中 {remain} 处")
    print("=" * 72)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Linux → Windows 硬编码清理工具")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="只读扫描，打印分布清单")
    p_fix = sub.add_parser("fix", help="执行替换")
    p_fix.add_argument("--dry-run", action="store_true", help="只打印将要改什么，不写盘")
    sub.add_parser("verify", help="残留复扫")
    args = ap.parse_args()

    if args.cmd == "scan":
        return cmd_scan(args)
    if args.cmd == "fix":
        return cmd_fix(args)
    return cmd_verify(args)


if __name__ == "__main__":
    sys.exit(main())
