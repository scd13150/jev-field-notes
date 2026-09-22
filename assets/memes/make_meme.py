# -*- coding: utf-8 -*-
"""
Regenerate the caption on the meme.

The base image is a third-party meme template and is NOT redistributed in this
repository, so this script takes it as an argument. Everything else about the
treatment is pinned here so the committed file can be reproduced exactly.

Usage:
    python make_meme.py path\\to\\base.jpg [out.jpg]

The committed caption (spare_tokens.jpg) was produced from the 1053x1008 version
of the template with these exact settings. Sizes are in pixels and are absolute,
not relative, so a different-resolution base will place the text differently --
adjust SIZE and the width ceiling together if you swap the source.
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont

TEXT = "谁还有多余token"

# Treatment, chosen to match the original meme's look and the image's own accents.
SIZE = 128              # largest size at which all 9 glyphs fit this width
FILL = (255, 199, 56)   # gold: picks up the chain and watch, reads on the navy suit
OUTLINE = (28, 16, 0)   # near-black, warm, so the edge does not look pasted on
STROKE = 9              # outline width
BOTTOM_PAD = 2          # px of clearance under the baseline
WIDTH_CEILING = 0.985   # never let the caption exceed this fraction of the width

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",     # Microsoft YaHei Bold -- the committed file
    r"C:\Windows\Fonts\simhei.ttf",     # SimHei, heavier and squarer
    r"C:\Windows\Fonts\msyh.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]


def pick_font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit("no CJK font found; add one to FONT_CANDIDATES")


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "spare_tokens.jpg")

    im = Image.open(src).convert("RGB")
    W, H = im.size
    font = ImageFont.truetype(pick_font(), SIZE)
    d = ImageDraw.Draw(im)

    bb = d.textbbox((0, 0), TEXT, font=font, stroke_width=STROKE)
    tw = bb[2] - bb[0]
    if tw > W * WIDTH_CEILING:
        raise SystemExit(
            f"caption is {tw}px wide, over the {int(W * WIDTH_CEILING)}px ceiling for a "
            f"{W}px image -- lower SIZE and re-run rather than clipping the text")

    x = (W - tw) / 2 - bb[0]
    y = H - bb[3] - BOTTOM_PAD          # glyph bottoms sit just above the edge
    d.text((x, y), TEXT, font=font, fill=FILL, stroke_width=STROKE, stroke_fill=OUTLINE)

    im.save(dst, format="JPEG", quality=92, optimize=True)
    print(f"wrote {dst}  ({im.size[0]}x{im.size[1]}, caption {tw}px wide)")


if __name__ == "__main__":
    main()
