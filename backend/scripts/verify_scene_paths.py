"""场景包路径合规校验（交付验收用）。

校验规则（与前端的消费逻辑逐条对齐，见 features/waveforms/index.ts:150
与 features/scene/workflows.ts:84）：

  mode == copied_into_pack / generated_into_pack
      文件真在 assets/ 下，前端靠 `file_path.split('/assets/')[1]` 取相对路径。
      要求：恰好一个 '/assets/'，且其后非空，且前缀为空或 '.'。

  mode == registered_only
      文件在客户工程别的目录，不在本包 assets/ 下，前端 `if (!rel) continue`
      直接跳过。要求：**不含** '/assets/'（否则会误判成可加载资源）。
      同时不应残留 Linux 主机前缀（/mnt、/home 等）——应已脱敏为 '[源] ...'。

  其余字段（source_file_path / template_file / filler_tool.path）
      只做「无 Linux 主机前缀」检查，不做 /assets/ 约束。

用法：
    python scripts/verify_scene_paths.py        # 通过返回 0，失败返回 1
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCENES = REPO_ROOT / "c" / "web" / "public" / "scenes"

LINUX_PREFIXES = ("/mnt/", "/home/", "/root/", "/usr/", "/opt/", "/etc/", "/var/", "/tmp/", "~/")


def has_linux_prefix(s: str) -> bool:
    return isinstance(s, str) and s.startswith(LINUX_PREFIXES)


def check() -> int:
    problems: list[str] = []
    n_copied = n_registered = n_other = 0

    for p in sorted(SCENES.rglob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            problems.append(f"{p.relative_to(REPO_ROOT)}: JSON 解析失败 {e}")
            continue

        rel = p.relative_to(REPO_ROOT)

        # 1) datasets[].file_path
        for d in data.get("datasets", []) or []:
            fp = d.get("file_path", "")
            mode = d.get("mode", "")
            did = d.get("id", "?")
            if mode in ("copied_into_pack", "generated_into_pack"):
                n_copied += 1
                parts = fp.split("/assets/")
                if len(parts) != 2 or not parts[1] or parts[0] not in ("", "."):
                    problems.append(f"{rel} datasets[{did}] mode={mode} file_path 不合规: {fp!r}")
            elif mode == "registered_only":
                n_registered += 1
                if "/assets/" in fp:
                    problems.append(f"{rel} datasets[{did}] registered_only 不应含 /assets/: {fp!r}")
                if has_linux_prefix(fp):
                    problems.append(f"{rel} datasets[{did}] 残留 Linux 前缀: {fp!r}")
            else:
                n_other += 1
                if has_linux_prefix(fp):
                    problems.append(f"{rel} datasets[{did}] mode={mode!r} 残留 Linux 前缀: {fp!r}")

        # 2) workflows[].file_path
        #
        # .wfw 工作流文件**本来就不在场景包 assets/ 下**（源在客户工程的
        # archive-POC/.../WORKINGflow/），所以只有两种合法形态：
        #   a) 包内副本：`./assets/<rel>`（前端拼 pack.base + 'assets/<rel>' 加载）
        #   b) 包外登记：已脱敏的 `[源] ...`
        # 前端对 b) 是容错的——assetPath 为空时 loadPackWorkflow 直接 return null
        # （见 features/scene/workflows.ts:113），画布降级但不报错。
        # 因此这里只拦「残留 Linux 主机前缀」与「形态四不像」两类。
        for w in data.get("workflows", []) or []:
            fp = w.get("file_path", "")
            if not fp:
                continue
            wid = w.get("id", "?")
            if has_linux_prefix(fp):
                problems.append(f"{rel} workflows[{wid}] 残留 Linux 前缀: {fp!r}")
                continue
            if fp.startswith("[源] "):
                continue  # 包外登记，合法
            parts = fp.split("/assets/")
            if len(parts) != 2 or not parts[1] or parts[0] not in ("", "."):
                problems.append(f"{rel} workflows[{wid}] file_path 形态不合法: {fp!r}")

        # 3) 其余登记类字段：只查 Linux 前缀
        for key in ("source_file_path", "template_file"):
            v = data.get(key)
            if has_linux_prefix(v or ""):
                problems.append(f"{rel} {key} 残留 Linux 前缀: {v!r}")

    print(f"场景包校验：copied/generated {n_copied} 条、registered_only {n_registered} 条、其他 {n_other} 条")
    if problems:
        print(f"\n发现 {len(problems)} 个问题：")
        for x in problems[:40]:
            print("  -", x)
        if len(problems) > 40:
            print(f"  …还有 {len(problems) - 40} 条")
        return 1
    print("全部合规")
    return 0


if __name__ == "__main__":
    sys.exit(check())
