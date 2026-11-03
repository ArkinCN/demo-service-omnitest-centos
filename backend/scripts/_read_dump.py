"""临时：把 _dump.txt 以 UTF-8 安全读回并写一份无 BOM 的 UTF-8 文本。

Windows 控制台是 GBK，含 `⚠`（U+26A0）的内容打印必崩——
本项目记过这条坑。这里绕过控制台，直接落文件，再由工具读文件显示。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
here = Path(__file__).resolve().parent
src = here.parent / "_dump.txt"
dst = here.parent / "_dump_utf8.txt"
raw = src.read_bytes()
# 源文件可能是 GBK（脚本 reconfigure 前的 stdout 落盘）或 UTF-8，两种都试
for enc in ("utf-8", "gbk", "gb18030"):
    try:
        text = raw.decode(enc)
        break
    except UnicodeDecodeError:
        continue
else:
    text = raw.decode("utf-8", errors="replace")
dst.write_text(text, encoding="utf-8")
print(f"WROTE {dst} ({len(text)} chars)")
