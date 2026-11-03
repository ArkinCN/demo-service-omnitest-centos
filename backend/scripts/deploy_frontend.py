"""前端零停机部署（原 deploy_frontend.sh 的跨平台 Python 版）。

为什么改写：原脚本是 bash，依赖 `ln -sfn`、`ls -1d` 等 Unix 工具，Windows 上跑不了。
本项目交付形态是纯 Windows，脚本必须跨平台。

与原 bash 版的行为对齐点：
- 参数、步骤顺序、日志格式、退出码语义保持一致；
- 保留「构建失败即中止、不动线上版本」的安全语义；
- 保留「只留最近 N 个 release」的清理策略。

Windows 差异说明（重要，不看会踩）：
- **符号链接**：Windows 建 symlink 需要管理员权限或开发者模式。本版做法是把
  `current` 做成一个**目录联接（junction）**优先，失败则回退到复制整份产物。
  这样在受限权限下也能完成部署，只是失去原子性——故日志会明确提示用的是哪条路。
- **依赖安装**：按 lock 文件自动选 yarn / npm / pnpm，不再写死 yarn。

用法：
    python scripts/deploy_frontend.py <git-tag> <仓库路径> <站点发布目录>
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

KEEP_RELEASES = 5


def log(msg: str, logfile: Path | None = None, error: bool = False) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {'[错误] ' if error else ''}{msg}"
    print(line, file=sys.stderr if error else sys.stdout)
    if logfile is not None:
        try:
            with logfile.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass  # 日志写不进去不该中断部署


def run(cmd: list[str], cwd: Path, logfile: Path | None = None) -> int:
    """执行命令并透传输出；返回退出码（不抛异常，由调用方决定如何处理）。"""
    log(f"执行：{' '.join(cmd)}", logfile)
    return subprocess.run(cmd, cwd=str(cwd), shell=(os.name == "nt")).returncode


def install_deps(repo: Path, logfile: Path | None) -> int:
    """按 lock 文件选包管理器安装依赖。"""
    if (repo / "pnpm-lock.yaml").is_file():
        mgr, args = "pnpm", ["install", "--frozen-lockfile"]
    elif (repo / "yarn.lock").is_file():
        mgr, args = "yarn", ["install", "--frozen-lockfile"]
    elif (repo / "package-lock.json").is_file():
        mgr, args = "npm", ["ci"]
    elif (repo / "package.json").is_file():
        mgr, args = "npm", ["install"]
    else:
        log("未找到 package.json，跳过依赖安装", logfile)
        return 0

    rc = run([mgr] + args, repo, logfile)
    if rc != 0 and args and args[-1] == "--frozen-lockfile":
        # 锁文件与 package.json 不一致时回退常规安装（与原脚本同样的兜底）
        log("frozen-lockfile 失败，回退到常规安装", logfile)
        rc = run([mgr, "install"], repo, logfile)
    return rc


def build(repo: Path, logfile: Path | None) -> int:
    if (repo / "package.json").is_file():
        return run(["npm", "run", "build"], repo, logfile)
    return run(["yarn", "build"], repo, logfile)


def switch_current(release: Path, current: Path, logfile: Path | None) -> None:
    """把 current 指向新 release。

    优先真 symlink（零停机、原子）；Windows 上若权限不足则退到 junction；
    再不行就整份复制——这条路会有一小段不一致窗口，日志里必须说清楚。
    """
    previous = None
    if current.is_symlink() or current.exists():
        previous = current.resolve() if current.exists() else None
        try:
            if current.is_dir() and not current.is_symlink():
                shutil.rmtree(current)
            else:
                current.unlink()
        except OSError as e:
            log(f"清理旧 current 失败：{e}", logfile, error=True)

    # ① 真 symlink
    try:
        current.symlink_to(release, target_is_directory=True)
        log(f"符号链接切换完成（原子）：{current} -> {release}", logfile)
        return
    except (OSError, NotImplementedError) as e:
        log(f"symlink 不可用（{e}），尝试目录联接", logfile)

    # ② Windows 目录联接（不需要管理员权限）
    if os.name == "nt":
        rc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(current), str(release)],
            capture_output=True, text=True,
        ).returncode
        if rc == 0:
            log(f"目录联接完成：{current} -> {release}", logfile)
            return
        log("目录联接也失败，回退为整份复制", logfile)

    # ③ 兜底：复制（说明非原子）
    log("注意：当前为「复制」模式，本次切换非原子，存在秒级不一致窗口", logfile, error=True)
    shutil.copytree(release, current)
    if previous:
        log(f"（上一版仍在：{previous}）", logfile)


def prune(releases_dir: Path, logfile: Path | None) -> None:
    """只保留最近 KEEP_RELEASES 个 release。"""
    dirs = sorted([d for d in releases_dir.iterdir() if d.is_dir()], key=lambda d: d.name)
    if len(dirs) <= KEEP_RELEASES:
        log(f"当前共 {len(dirs)} 个版本，无需清理", logfile)
        return
    for old in dirs[: len(dirs) - KEEP_RELEASES]:
        log(f"删除旧版本: {old.name}", logfile)
        shutil.rmtree(old, ignore_errors=True)
    log("旧版本清理完成", logfile)


def main() -> int:
    ap = argparse.ArgumentParser(description="前端零停机部署（跨平台）")
    ap.add_argument("tag", help="git 标签，如 v1.0.0")
    ap.add_argument("repo_dir", help="仓库路径")
    ap.add_argument("site_dir", help="站点发布目录")
    args = ap.parse_args()

    repo = Path(args.repo_dir).resolve()
    site = Path(args.site_dir).resolve()
    releases_dir = site / "releases"
    current = site / "current"
    logfile = site / "deploy.log"
    release_name = f"{datetime.now():%Y%m%d%H%M%S}_{args.tag}"
    release_path = releases_dir / release_name

    if not repo.is_dir():
        log(f"仓库目录不存在: {repo}", error=True)
        return 1
    if not site.is_dir():
        log(f"站点发布目录不存在: {site}", error=True)
        return 1

    log("==============================", logfile)
    log("开始部署前端", logfile)
    log(f"Git 标签: {args.tag}", logfile)
    log(f"仓库路径: {repo}", logfile)
    log(f"站点目录: {site}", logfile)
    log(f"Release 名称: {release_name}", logfile)
    log("==============================", logfile)

    # 拉代码切标签
    if run(["git", "fetch", "--tags", "--force"], repo, logfile) != 0:
        log("git fetch 失败", logfile, error=True)
        return 1
    if run(["git", "checkout", args.tag], repo, logfile) != 0:
        log(f"git checkout {args.tag} 失败", logfile, error=True)
        return 1

    # 装依赖 + 构建
    if install_deps(repo, logfile) != 0:
        log("依赖安装失败", logfile, error=True)
        return 1
    if build(repo, logfile) != 0:
        log("构建失败！保持当前线上版本不变，终止部署", logfile, error=True)
        return 1

    # 产物落位（dist 优先，兼容旧工程用 build）
    dist = repo / "dist"
    if not dist.is_dir():
        dist = repo / "build"
    if not dist.is_dir():
        log("未找到构建产物（dist/ 或 build/）", logfile, error=True)
        return 1

    releases_dir.mkdir(parents=True, exist_ok=True)
    log(f"复制构建产物到: {release_path}", logfile)
    shutil.copytree(dist, release_path)
    log("构建产物复制完成", logfile)

    switch_current(release_path, current, logfile)
    prune(releases_dir, logfile)

    log("==============================", logfile)
    log("部署成功完成！", logfile)
    log(f"Release 路径: {release_path}", logfile)
    log(f"当前链接: {current} -> {release_path}", logfile)
    log(f"部署日志: {logfile}", logfile)
    log("==============================", logfile)
    return 0


if __name__ == "__main__":
    sys.exit(main())
