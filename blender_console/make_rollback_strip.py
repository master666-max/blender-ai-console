"""make_rollback_strip.py — 回退演示四帧拼条（A/B/C/D 横排 + 状态标注）
产出：showcase/rollback-strip.png（README 门面嵌入用）
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FR = ROOT / "showcase" / "rollback"
OUT = ROOT / "showcase" / "rollback-strip.png"

frames = [
    ("A.png", "A  body ready", "#8a8f98"),
    ("B.png", "B  + handle", "#8a8f98"),
    ("C.png", "C  AI mistake (gouge)", "#e5534b"),
    ("D.png", "D  rollback == B (sha match)", "#57ab5a"),
]
SRC = 512
LABEL_H = 56
GAP = 4
W = SRC * 4 + GAP * 3
H = SRC + LABEL_H

strip = Image.new("RGB", (W, H), "#1c2128")
font = None
for cand in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arialbd.ttf",
             "C:/Windows/Fonts/arial.ttf"):
    try:
        font = ImageFont.truetype(cand, 30)
        break
    except OSError:
        continue
if font is None:
    font = ImageFont.load_default()

draw = ImageDraw.Draw(strip)
x = 0
for fname, label, color in frames:
    im = Image.open(FR / fname).convert("RGB")
    strip.paste(im, (x, LABEL_H))
    tw = draw.textlength(label, font=font)
    draw.text((x + (SRC - tw) / 2, 12), label, fill=color, font=font)
    x += SRC + GAP

OUT.parent.mkdir(parents=True, exist_ok=True)
strip.save(OUT, optimize=True)
print(f"strip -> {OUT} ({OUT.stat().st_size // 1024}KB, {W}x{H})")
