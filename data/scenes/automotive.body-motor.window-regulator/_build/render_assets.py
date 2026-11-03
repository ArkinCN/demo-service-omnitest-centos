# -*- coding: utf-8 -*-
"""渲染场景包的两张图片资产。

1. product-photo-nhtsa-fig5-1.png
   从 NHTSA FMVSS 118 合规报告 REPORT NUMBER 118-GTL-11-002 的 PDF 第 19 页
   （报告正文第 15 页，FIGURE 5.1）用 PyMuPDF 按 150 dpi 渲染。
   照片主体是整车 2011 NISSAN JUKE S，不是升降器总成——公开渠道拿不到
   升降器总成的可授权产品照，故只作「被测对象」示意。

2. regulator-schematic.png
   本包手排 SVG → cairosvg 转 PNG。画的是判据涉及的量测点位，不是任何厂商的真实结构。
   配色按 CLAUDE.md R10 §6：骨架 #2E5E45，弱化 #A8C5B5，强调 #A6353A（≤2 处），
   淡填充 #EAF2EC，不做实色填充，不引第三色相。
"""
import os

from common import NHTSA_PDF

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

INK = "#2E5E45"
WEAK = "#A8C5B5"
ACCENT = "#A6353A"
TINT = "#EAF2EC"
TXT = "#2C2C2C"
TXT2 = "#555555"
RULE = "#C8C5BD"

SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="760" viewBox="0 0 1200 760">
<rect width="1200" height="760" fill="#FFFFFF"/>
<text x="40" y="48" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="26" fill="{TXT}">玻璃升降器台架结构简图</text>
<text x="40" y="76" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="15" fill="{TXT2}">示意图，非真实产品结构。标出的是本场景判据涉及的量测点位。</text>
<line x1="40" y1="94" x2="1160" y2="94" stroke="{RULE}" stroke-width="1"/>

<!-- 车门框 / 玻璃行程通道 -->
<rect x="80" y="130" width="330" height="560" fill="none" stroke="{INK}" stroke-width="1.5"/>
<text x="90" y="152" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="15" fill="{INK}">车门与玻璃导轨</text>

<!-- 上止点 -->
<line x1="80" y1="185" x2="410" y2="185" stroke="{INK}" stroke-width="1.5"/>
<text x="418" y="181" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="15" fill="{INK}">上止点</text>
<text x="418" y="201" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="13" fill="{TXT2}">开口 0 mm，位置归零点</text>

<!-- 法规防夹区间 4~200 mm -->
<rect x="80" y="185" width="330" height="200" fill="{TINT}" stroke="none"/>
<line x1="80" y1="189" x2="410" y2="189" stroke="{ACCENT}" stroke-width="1"
      stroke-dasharray="6 4"/>
<line x1="80" y1="385" x2="410" y2="385" stroke="{ACCENT}" stroke-width="1"
      stroke-dasharray="6 4"/>
<text x="418" y="300" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="16" fill="{ACCENT}">法规防夹区间</text>
<text x="418" y="322" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="14" fill="{ACCENT}">开口 4 mm 至 200 mm</text>
<text x="418" y="344" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="13" fill="{TXT2}">夹持力超过 100 N 前必须回缩</text>

<!-- 玻璃托架 -->
<rect x="120" y="420" width="250" height="34" fill="none" stroke="{INK}" stroke-width="1.5"/>
<text x="132" y="443" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="15" fill="{INK}">玻璃托架</text>
<text x="132" y="484" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="13" fill="{TXT2}">自锁试验在此垂直加载 600 N，保持 5 s</text>
<text x="132" y="506" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="13" fill="{TXT2}">下降量须不大于 5 mm</text>

<!-- 下止点 -->
<line x1="80" y1="655" x2="410" y2="655" stroke="{INK}" stroke-width="1.5"/>
<text x="418" y="660" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="15" fill="{INK}">下止点</text>

<!-- 行程标注 -->
<line x1="100" y1="185" x2="100" y2="655" stroke="{WEAK}" stroke-width="1"/>
<text x="106" y="560" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="13" fill="{TXT2}">总行程</text>

<!-- 传动链：绳轮 → 蜗杆减速 → 电机 -->
<circle cx="560" cy="437" r="46" fill="none" stroke="{INK}" stroke-width="1.5"/>
<text x="524" y="432" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="15" fill="{INK}">绳轮</text>
<text x="518" y="452" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="13" fill="{TXT2}">或剪式传动</text>
<line x1="370" y1="437" x2="514" y2="437" stroke="{INK}" stroke-width="1.5"/>

<rect x="630" y="405" width="130" height="64" fill="none" stroke="{INK}" stroke-width="1.5"/>
<text x="648" y="432" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="15" fill="{INK}">蜗杆减速</text>
<text x="648" y="453" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="13" fill="{TXT2}">自锁来源</text>
<line x1="606" y1="437" x2="630" y2="437" stroke="{INK}" stroke-width="1.5"/>

<rect x="810" y="398" width="150" height="78" fill="none" stroke="{INK}" stroke-width="1.5"/>
<text x="828" y="426" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="15" fill="{INK}">有刷直流电机</text>
<text x="828" y="447" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="13" fill="{TXT2}">12 V，机械换向</text>
<text x="828" y="466" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="13" fill="{TXT2}">电流带换向纹波</text>
<line x1="760" y1="437" x2="810" y2="437" stroke="{INK}" stroke-width="1.5"/>

<!-- H 桥与控制器 -->
<rect x="1010" y="398" width="150" height="78" fill="none" stroke="{INK}" stroke-width="1.5"/>
<text x="1028" y="426" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="15" fill="{INK}">H 桥与控制器</text>
<text x="1028" y="447" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="13" fill="{TXT2}">PWM 调速</text>
<text x="1028" y="466" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="13" fill="{TXT2}">防夹判据在此运行</text>
<line x1="960" y1="437" x2="1010" y2="437" stroke="{INK}" stroke-width="1.5"/>

<!-- 试验棒（强调色第 2 处） -->
<rect x="150" y="270" width="190" height="26" fill="none" stroke="{ACCENT}" stroke-width="1.5"/>
<text x="162" y="288" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="14" fill="{ACCENT}">半刚性试验棒 10 N/mm</text>

<!-- 量测点位一览 -->
<line x1="560" y1="540" x2="1160" y2="540" stroke="{RULE}" stroke-width="1"/>
<text x="560" y="572" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="16" fill="{INK}">台架量测点位</text>
<text x="560" y="600" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="14" fill="{TXT}">力传感器　装在试验棒与托架两处，量夹持力与堵转力</text>
<text x="560" y="624" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="14" fill="{TXT}">位移传感器　量开口、行程与回缩量，分辨率 0.05 mm</text>
<text x="560" y="648" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="14" fill="{TXT}">电流传感器　量工作电流与堵转电流，兼作纹波计数源</text>
<text x="560" y="672" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="14" fill="{TXT}">声级计　置于电机出力轴正上方 300 mm</text>
<text x="560" y="696" font-family="Noto Sans CJK SC, DejaVu Sans, sans-serif"
      font-size="14" fill="{TXT}">程控电源　13.5 ± 0.3 V，回路串 0.15 ± 0.02 Ω</text>
</svg>""".format(TXT=TXT, TXT2=TXT2, INK=INK, WEAK=WEAK, ACCENT=ACCENT, TINT=TINT, RULE=RULE)


def build():
    os.makedirs(ASSETS, exist_ok=True)
    made = []

    # 1) NHTSA 报告照片页
    out1 = os.path.join(ASSETS, "product-photo-nhtsa-fig5-1.png")
    if os.path.exists(NHTSA_PDF):
        import fitz
        doc = fitz.open(NHTSA_PDF)
        pix = doc[18].get_pixmap(dpi=150)     # 0-based：第 19 页
        pix.save(out1)
        doc.close()
        made.append((out1, os.path.getsize(out1)))
    else:
        made.append((out1, None))

    # 2) 手排结构简图
    out2 = os.path.join(ASSETS, "regulator-schematic.png")
    svg_path = os.path.join(ASSETS, "regulator-schematic.svg")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(SVG)
    import cairosvg
    cairosvg.svg2png(bytestring=SVG.encode("utf-8"), write_to=out2,
                     output_width=1200, output_height=760)
    made.append((out2, os.path.getsize(out2)))
    made.append((svg_path, os.path.getsize(svg_path)))
    return made


if __name__ == "__main__":
    for p, s in build():
        print("%-64s %s" % (os.path.basename(p), s if s else "[源] PDF 缺失，未生成"))
