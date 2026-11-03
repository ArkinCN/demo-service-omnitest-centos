#![源] bin/env python3
"""Per-session tool-call count and token totals for every dsh session on disk."""
import collections, glob, json, os, sys, zstandard

pattern = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "[源] */session.v3.jsonl.zstd")


def walk(x, tot):
    if isinstance(x, dict):
        for k, v in x.items():
            if isinstance(v, int) and "oken" in k:
                tot[k] += v
            walk(v, tot)
    elif isinstance(x, list):
        for v in x:
            walk(v, tot)


for f in sorted(glob.glob(pattern), key=os.path.getmtime):
    raw = zstandard.ZstdDecompressor().stream_reader(open(f, "rb")).read().decode("utf-8", "replace")
    tot = collections.Counter()
    calls = 0
    title = ""
    for line in raw.splitlines():
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if o.get("type") == "tool/call":
            calls += 1
        if o.get("type") == "session/title":
            title = o.get("data", {}).get("title", title)
        if "usage" in line:
            walk(o.get("usage", o), tot)
    print(f"{os.path.basename(os.path.dirname(f))[:22]}  calls={calls:<3} {title[:28]:<30} {dict(tot)}")
