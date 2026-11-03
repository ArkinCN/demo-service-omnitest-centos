#!/usr/bin/env python3
"""Print the tool-call / hook timeline of one dsh session log.

Usage: tools_dump_session.py <path to session.v3.jsonl.zstd>

dsh persists sessions as zstd-compressed JSONL under
$DSH_HOME/sessions/<workspace-slug>/<session-id>/session.v3.jsonl.zstd.
Hook scripts cannot read it (the bridge always reports transcript_path as
null/empty), so this is the only way to recover an exact call sequence.
"""
import json, sys, zstandard

raw = zstandard.ZstdDecompressor().stream_reader(open(sys.argv[1], "rb")).read().decode("utf-8", "replace")
results = {}
events = []
for line in raw.splitlines():
    try:
        o = json.loads(line)
    except json.JSONDecodeError:
        continue
    t, d = o.get("type"), o.get("data", {})
    if t == "tool/call":
        events.append(("CALL", d.get("callId"), d.get("name"), d.get("arguments")))
    elif t == "tool/result":
        msg = d.get("message", {})
        for block in msg.get("content", []):
            txt = " ".join(c.get("text", "") for c in block.get("content", []) if c.get("type") == "text")
            results[block.get("toolCallId")] = (block.get("isError"), txt)
    elif t in ("hook/invoked", "hook/result"):
        events.append((t.upper(), d.get("dialect") or d.get("handlerId"), d.get("point"),
                       d.get("decision"), d.get("exitCode"), (d.get("stderrSummary") or "")[:200]))

n = 0
for e in events:
    if e[0] == "CALL":
        n += 1
        _, cid, name, args = e
        is_err, txt = results.get(cid, (None, "<no result captured>"))
        flag = "ERROR" if is_err else "ok"
        print(f"{n:>2}. {name}  args={args}")
        print(f"    -> [{flag}] {' '.join(txt.split())[:420]}")
    else:
        print(f"    ~~ {e[0]} bridge={e[1]} point={e[2]} decision={e[3]} exit={e[4]} {e[5]}")
