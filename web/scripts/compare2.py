#![源] bin/env python3
"""v2 收尾对照图：左电机包、右汽车包，两张 1920×1080 各缩到 960 宽横向拼成 1920 宽。
   先跑 scripts/shootfinal.mjs 出 final-run.png 与 final-auto-run.png，再跑本脚本。
     python3 scripts/compare2.py
   （scripts/compare.py 是 v1 的 shots/ 对照图脚本，仍在用，不要混。）
"""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

D = Path(__file__).resolve().parent.parent / 'shots2'
a = Image.open(D / 'final-run.png').convert('RGB')
b = Image.open(D / 'final-auto-run.png').convert('RGB')
W, BAND = 960, 44
h = int(a.height * W / a.width)
a, b = a.resize((W, h), Image.LANCZOS), b.resize((W, h), Image.LANCZOS)
out = Image.new('RGB', (2 * W, h + BAND), '#F6F8F6')
out.paste(a, (0, BAND))
out.paste(b, (W, BAND))
dr = ImageDraw.Draw(out)
dr.line([(W, BAND), (W, h + BAND)], fill='#C8C5BD', width=2)
dr.line([(0, BAND - 1), (2 * W, BAND - 1)], fill='#C8C5BD', width=1)
# 标题给中文产品名（读者一眼知道是什么被测件），场景包标识降为同行小字
CJK = [
    '[源] noto/NotoSansCJK-Bold.ttc',
    '[源] noto/NotoSansCJK-Bold.ttc',
    '[源] Fonts/msyhbd.ttc',
    '[源] Fonts/msyh.ttc',
]


def font(size, bold=True):
    for path in CJK:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    try:
        name = 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
        return ImageFont.truetype(f'[源] dejavu/{name}', size)
    except OSError:
        return None


FB, FS = font(19), font(13, bold=False)
PANELS = [
    (0, '散热风扇驱动板 FU6832', 'motor.cooling-fan.fortior-fu6832 · /run'),
    (W, '汽车电动玻璃升降器总成', 'automotive.body-motor.window-regulator · /run'),
]
for x, name, sub in PANELS:
    dr.text((24 + x, 9), name, fill='#2E5E45', font=FB)
    w = dr.textlength(name, font=FB)
    dr.text((24 + x + w + 12, 15), sub, fill='#9A9A9A', font=FS)
out.save(D / 'final-compare-run.png')
print('✓ final-compare-run.png', out.size)
