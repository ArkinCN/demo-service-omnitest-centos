"""把场景包里登记的知识条目导入 kb_entries 表（三轴分类落到服务端）。

为什么要导入，而不是让列表接口直接读场景包 JSON：
    主文档 3.1 要求「把只做在前端的三轴分类落到服务端」。若列表读 JSON、
    CRUD 改库，就变成**两套并存**——改了库界面不变，改了 JSON 库不知道，
    必然漂移。项目里已经因为这类双源吃过亏（判定前后端各算一份）。
    所以定死：**库是唯一权威源，场景包只作导入源**。

导入口径必须与前端 `features/knowledge/data.ts` 逐条对齐，否则
「切换前后计数一致」这条验收过不了：
  - 用途轴：中文三值映射 spec / requirement / process，**缺失时不猜，
    回落 process**（与前端 usageOf 一致）
  - 来源轴：documents.json → doc；experience.json → experience
  - 归属轴：从 scenes/index.json 三级目录按 sceneId 反查；查不到才按
    sceneId 的 '.' 拆段（与前端 ownerOf 一致）
  - entry_key = `{scene_id}:{原 id}`，保持可追溯，不另造 uuid

⚠️ **entry_key 必须带场景包维度**：两个场景包的经验条目用同一套编号
（`EXP-001`…`EXP-018` **两包完全重号**，实测 18 条）。只拿原 id 当 key，
先导入的包会占住这些号，后导入的包静默少 18 条，而且这些条目会**串到
另一个产品名下**——界面上看不出，数据却是错的。

幂等：同一 entry_key 已存在就跳过（按版本链里最大 version 判断）。
想强制重来：先删掉 kb_entries 表里对应行，再加 --force 重跑（--force 为覆盖写）。

用法：
    python scripts/import_kb_from_scenes.py                      # 全量导入
    python scripts/import_kb_from_scenes.py --scene <sceneId>    # 只导一个包
    python scripts/import_kb_from_scenes.py --force              # 已存在也覆盖
    python scripts/import_kb_from_scenes.py --dry-run            # 只报数不写库
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from app.core.paths import kb_data_dir, scenes_dir  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.models.kb_entry import KbEntry  # noqa: E402

# 与前端 data.ts 的 USAGE_CODE 一致：场景包写中文，服务端存英文码
USAGE_CODE = {"产品说明书": "spec", "测试需求": "requirement", "工艺": "process"}
DEFAULT_USAGE = "process"  # 缺失时回落，与前端「不猜，标待复核」同一口径

NODE_FAILED_USAGE = "process"


def read_json(p: Path):
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [warn] 读不了 {p.name}：{e}")
        return None


def owner_index(scenes: Path) -> dict[str, tuple[str, str, str]]:
    """从 scenes/index.json 的三级目录反查 sceneId → (一级, 二级, 三级) 中文名。"""
    idx = read_json(scenes / "index.json")
    out: dict[str, tuple[str, str, str]] = {}
    for a in (idx or {}).get("catalog", []):
        for b in a.get("children", []):
            for c in b.get("children", []):
                if c.get("sceneId"):
                    out[c["sceneId"]] = (a.get("label", ""), b.get("label", ""), c.get("label", ""))
    return out


def fallback_owner(scene_id: str) -> tuple[str, str, str]:
    """目录里查不到时按 sceneId 拆段（与前端 ownerOf 的兜底一致）。"""
    parts = scene_id.split(".")
    return (parts[0] if parts else scene_id, parts[1] if len(parts) > 1 else "",
            parts[2] if len(parts) > 2 else "")


def pipeline_pages(kb: Path) -> dict[str, dict]:
    """kb/documents/index.json 的页数与切片数，按标题匹配（与前端 pipeline 一致）。"""
    idx = read_json(kb / "documents" / "index.json")
    out: dict[str, dict] = {}
    for d in (idx or {}).get("documents", []):
        if d.get("title"):
            out[d["title"]] = {"pages": d.get("pages"), "chunks": d.get("chunks")}
    return out


def collect(scene_id: str, scenes: Path) -> list[dict]:
    """把一个场景包的两份 JSON 收成待导入条目。"""
    base = scenes / scene_id
    docs = (read_json(base / "documents.json") or {}).get("documents", [])
    exps = (read_json(base / "experience.json") or {}).get("experiences", [])
    owner = owner_index(scenes).get(scene_id) or fallback_owner(scene_id)
    pages = pipeline_pages(kb_data_dir())

    rows: list[dict] = []
    for d in docs:
        raw_usage = d.get("usage")
        usage = USAGE_CODE.get(raw_usage or "", DEFAULT_USAGE)
        content = dict(d)
        content.update(pages.get(d.get("title", ""), {}))
        rows.append({
            "entry_key": f"{scene_id}:{d.get('id') or d.get('title', '')}",
            "origin": "doc",
            "title": d.get("title", ""),
            "usage": usage,
            "owner": owner,
            "needs_review": not raw_usage or raw_usage not in USAGE_CODE,
            "content": content,
        })
    for e in exps:
        raw_usage = e.get("usage")
        usage = USAGE_CODE.get(raw_usage or "", DEFAULT_USAGE)
        rows.append({
            "entry_key": f"{scene_id}:{e.get('id') or e.get('symptom', '')}",
            "origin": "experience",
            "title": e.get("symptom", ""),
            "usage": usage,
            "owner": owner,
            "needs_review": not raw_usage or raw_usage not in USAGE_CODE,
            "content": dict(e),
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="", help="只导指定场景包")
    ap.add_argument("--force", action="store_true", help="已存在也覆盖（出新版本）")
    ap.add_argument("--dry-run", action="store_true", help="只报数不写库")
    args = ap.parse_args()

    scenes = scenes_dir()
    if not scenes.is_dir():
        print(f"场景包目录不存在：{scenes}")
        return 1

    scene_ids = [args.scene] if args.scene else sorted(
        p.name for p in scenes.iterdir() if p.is_dir() and (p / "documents.json").is_file()
    )
    print(f"场景包：{len(scene_ids)} 个（来自 {scenes}）")

    total_created = 0
    total_updated = 0
    total_skipped = 0

    with Session(engine) as session:
        for sid in scene_ids:
            rows = collect(sid, scenes)
            if not rows:
                print(f"  {sid}：没有可导入条目，跳过")
                continue
            created = updated = skipped = 0
            for r in rows:
                key = r["entry_key"]
                existing = session.exec(
                    select(KbEntry).where(KbEntry.entry_key == key).order_by(KbEntry.version.desc())
                ).first()
                if existing and not args.force:
                    skipped += 1
                    continue
                version = (existing.version + 1) if existing else 1
                if args.dry_run:
                    created += 1
                    continue
                session.add(KbEntry(
                    entry_key=key,
                    version=version,
                    origin=r["origin"],
                    title=r["title"],
                    usage=r["usage"],
                    owner_l1=r["owner"][0],
                    owner_l2=r["owner"][1],
                    owner_l3=r["owner"][2],
                    content=r["content"],
                    status="active",
                    change_reason="场景包导入" if version == 1 else "场景包重新导入",
                ))
                if existing:
                    updated += 1
                else:
                    created += 1
            if not args.dry_run:
                session.commit()
            total_created += created
            total_updated += updated
            total_skipped += skipped
            print(f"  {sid}：新建 {created} · 更新 {updated} · 跳过 {skipped}")

    print("-" * 60)
    print(f"合计：新建 {total_created} · 更新 {total_updated} · 跳过 {total_skipped}"
          + ("（dry-run，未写库）" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
