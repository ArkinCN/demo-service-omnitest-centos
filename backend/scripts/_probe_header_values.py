"""临时：查表头 6 个 key 在快照里的**实际值**，确认为何报告里显示「未提供」。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlmodel import Session, select  # noqa: E402

from app.db.session import engine  # noqa: E402
from app.models.run import Artifact  # noqa: E402

RUN = sys.argv[1] if len(sys.argv) > 1 else "d5c08959241847798ab15884d0ae141a"
OUT = Path(__file__).resolve().parents[1] / "_probe_out2.txt"
WANT = ["model", "project_name", "firmware_version", "inlet_start_addr", "bootloader", "outlet_start_addr"]
lines: list[str] = []

with Session(engine) as s:
    arts = s.exec(select(Artifact).where(Artifact.run_id == RUN)).all()
    for a in arts:
        if a.artifact_kind != "config-snapshot":
            continue
        c = a.content or {}
        attrs = {x.get("key"): x for x in (c.get("product_attributes") or []) if isinstance(x, dict)}
        for k in WANT:
            x = attrs.get(k)
            if x is None:
                lines.append(f"{k}: 快照里没有这个 key")
            else:
                lines.append(
                    f"{k}: value={x.get('value')!r} type={type(x.get('value')).__name__} "
                    f"_class={x.get('_class')!r} unit={x.get('unit')!r}"
                )
        lines.append(f"\nCounts: {c.get('_counts')}")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"WROTE {OUT}")
