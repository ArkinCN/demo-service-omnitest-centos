"""临时：查 config-snapshot 里到底有哪些 key，为何表头 6 项都没取到。

现象：占位报告里「报告表头」6 项全显示「由上游带入（未提供）」，
但该轮确实有 config-snapshot 且含 product_attributes。
怀疑：快照里存的是**场景包字段 key**（如 rated_speed），
而报告表头要的是**模板字段 key**（如 model / project_name），两者根本不是同一批 key。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlmodel import Session, select  # noqa: E402

from app.db.session import engine  # noqa: E402
from app.models.run import Artifact  # noqa: E402

RUN = sys.argv[1] if len(sys.argv) > 1 else "d5c08959241847798ab15884d0ae141a"
OUT = Path(__file__).resolve().parents[1] / "_probe_out.txt"
lines: list[str] = []

with Session(engine) as s:
    arts = s.exec(select(Artifact).where(Artifact.run_id == RUN)).all()
    for a in arts:
        lines.append(f"kind={a.artifact_kind}")
        if a.artifact_kind != "config-snapshot":
            continue
        c = a.content or {}
        attrs = c.get("product_attributes") or []
        lines.append(f"  product_attributes 条数 = {len(attrs)}")
        keys = [x.get("key") for x in attrs if isinstance(x, dict)]
        lines.append(f"  前 40 个 key: {keys[:40]}")
        lines.append(f"  含 _class 的: {[(x.get('key'), x.get('_class')) for x in attrs if isinstance(x, dict) and x.get('_class')][:20]}")
        # 报告表头要找的 6 个 key 是否在其中
        want = ["model", "project_name", "firmware_version", "inlet_start_addr", "bootloader", "outlet_start_addr"]
        lines.append(f"  表头 key 命中情况: {[(k, k in keys) for k in want]}")
        lines.append(f"  content 顶层键: {list(c.keys())}")
        # 看看有没有别的地方存了表头
        for k in ("report_header", "header", "header_fields"):
            if k in c:
                lines.append(f"  !! content.{k} = {json.dumps(c[k], ensure_ascii=False)[:400]}")
    # 同时看 report-template.json 里的 header_fields
    rt = Path(__file__).resolve().parents[2] / "web" / "public" / "scenes" / "motor.cooling-fan.fortior-fu6832" / "report-template.json"
    if rt.exists():
        d = json.loads(rt.read_text(encoding="utf-8"))
        hf = d.get("header_fields") or []
        lines.append(f"\nreport-template.json header_fields 条数 = {len(hf)}")
        for f in hf:
            lines.append(f"  {f.get('key')} | {f.get('name')} | from_flow={f.get('from_flow')}")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"WROTE {OUT}")
