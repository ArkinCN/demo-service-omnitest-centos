#![源] bin/env python3
"""把两个场景包的同一条流程截图并排拼成一张对照图。

用法：
    python3 scripts/compare.py                 # 默认拼启动测试页（run）
    python3 scripts/compare.py tune            # 换一条流程

左电机（散热风扇）、右汽车（玻璃升降器），各缩到 800 宽，顶上留一条题注带标注
说明这是同一份前端代码在两个场景包下的渲染结果。
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SHOTS = Path(__file__).resolve().parent.parent / "shots"
INK = (46, 94, 69)
TEXT = (44, 44, 44)
MUTE = (154, 154, 154)
LINE = (200, 197, 189)
BG = (250, 250, 248)

PANEL_W = 800
HEADER_H = 96
GAP = 12
PAD = 12


def font(size: int, bold: bool = False):
    """找一个能渲中文的本机字体；找不到就退回 PIL 默认位图字体。"""
    candidates = [
        "[源] noto/NotoSansCJK-Bold.ttc" if bold else
        "[源] noto/NotoSansCJK-Regular.ttc",
        "[源] noto/NotoSansCJK-Regular.ttc",
        "[源] Fonts/msyhbd.ttc" if bold else "[源] Fonts/msyh.ttc",
        "[源] Fonts/simhei.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def main() -> int:
    route = sys.argv[1] if len(sys.argv) > 1 else "run"
    left_path = SHOTS / f"flow-{route}.png"
    right_path = SHOTS / f"auto-flow-{route}.png"
    for p in (left_path, right_path):
        if not p.exists():
            print(f"缺少 {p}，先跑 node scripts/shoot.mjs")
            return 1

    panels = []
    for p in (left_path, right_path):
        im = Image.open(p).convert("RGB")
        h = round(im.height * PANEL_W / im.width)
        panels.append(im.resize((PANEL_W, h), Image.LANCZOS))

    body_h = max(im.height for im in panels)
    W = PAD * 2 + PANEL_W * 2 + GAP
    H = PAD + HEADER_H + body_h + PAD

    out = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(out)

    f_title = font(19, bold=True)
    f_sub = font(13)
    f_cap = font(14, bold=True)
    f_capsub = font(12)

    d.text((PAD, PAD), "换场景只换包：同一份前端代码，两个场景包", font=f_title, fill=TEXT)
    d.text(
        (PAD, PAD + 25),
        f"流程「{route}」同一页面 · 左：电机 › 散热风扇 › FU6832 驱动板 ｜ 右：汽车 › 车身电机 › 电动玻璃升降器（含防夹）",
        font=f_sub,
        fill=MUTE,
    )

    captions = [
        ("场景一 · 散热风扇（峰岹 FU6832）", "实测示波器时序 · 客户私有文档与 .wfw 工作流"),
        ("场景二 · 玻璃升降器（含防夹）", "合成时序（已标注） · 公开标准条款与包内示例工作流"),
    ]
    y = PAD + HEADER_H
    for i, (im, (cap, capsub)) in enumerate(zip(panels, captions)):
        x = PAD + i * (PANEL_W + GAP)
        d.text((x, y - 40), cap, font=f_cap, fill=INK)
        d.text((x, y - 21), capsub, font=f_capsub, fill=MUTE)
        out.paste(im, (x, y))
        d.rectangle([x, y, x + PANEL_W - 1, y + im.height - 1], outline=LINE, width=1)

    dst = SHOTS / f"compare-{route}.png"
    out.save(dst)
    print(f"✓ {dst.name}  {out.width}×{out.height}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
