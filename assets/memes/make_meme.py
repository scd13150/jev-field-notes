# -*- coding: utf-8 -*-
"""
Regenerate the caption on the meme.

The base image is a third-party meme template and is NOT redistributed in this
repository, so this script takes it as an argument. Everything else about the
treatment is pinned here so the committed file can be reproduced exactly.

Usage:
    python make_meme.py path\\to\\base.jpg [out.jpg]

The committed caption (spare_tokens.jpg) was produced from the 1053x1008 version
of the template with these exact settings. Sizes are absolute, not relative, so a
different-resolution base will place the text differently -- change SIZE and the
width ceiling together if you swap the source.

Language note: the caption is in English because the audience for this repository
is an English-speaking engineering team. A Chinese-only caption is a joke they
cannot read, which defeats the point. The two-line form exists because the full
question set on one line caps out around 76px, which is far too small to carry a
meme; splitting it allows 142px.
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont

# One string per line, top to bottom. The committed file uses these two.
LINES = ["anyone got", "spare tokens?"]

# Treatment, chosen to match the original meme's look and the image's own accents.
FILL = (255, 199, 56)     # gold: picks up the chain and watch, reads on the navy suit
OUTLINE = (28, 16, 0)     # near-black, warm, so the edge does not look pasted on
STROKE = 9                # outline width
BOTTOM_PAD = 4            # px of clearance below the last line
LINE_GAP_RATIO = 0.16     # leading between lines, as a fraction of the font size
WIDTH_CEILING = 0.955     # never let a line exceed this fraction of the width
HEIGHT_CEILING = 0.36     # sanity bound: the block must not swallow the picture.
                          # The committed two-line treatment is 343px of 1008 = 34%, which
                          # is deliberate -- this is meant to dominate, as the original did.

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",     # Microsoft YaHei Bold -- used for the committed file
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def pick_font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit("no bold font found; add one to FONT_CANDIDATES")


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "spare_tokens.jpg")

    im = Image.open(src).convert("RGB")
    W, H = im.size
    probe = ImageDraw.Draw(im)

    def width_at(text, size):
        f = ImageFont.truetype(pick_font(), size)
        bb = probe.textbbox((0, 0), text, font=f, stroke_width=STROKE)
        return bb[2] - bb[0]

    # largest size at which EVERY line fits the width
    size = None
    for s in range(30, 400, 2):
        if all(width_at(l, s) <= W * WIDTH_CEILING for l in LINES):
            size = s
        else:
            break
    if size is None:
        raise SystemExit("not even the smallest size fits; check LINES and WIDTH_CEILING")

    font = ImageFont.truetype(pick_font(), size)
    metrics = []
    for l in LINES:
        bb = probe.textbbox((0, 0), l, font=font, stroke_width=STROKE)
        metrics.append((l, bb, bb[3] - bb[1]))
    gap = int(size * LINE_GAP_RATIO)
    block_h = sum(m[2] for m in metrics) + gap * (len(LINES) - 1)

    if block_h > H * HEIGHT_CEILING:
        raise SystemExit(
            f"caption block is {block_h}px tall, over the {int(H * HEIGHT_CEILING)}px ceiling "
            f"for a {H}px image -- lower the size or use fewer lines")

    d = ImageDraw.Draw(im)
    y = H - block_h - BOTTOM_PAD
    for l, bb, h in metrics:
        tw = bb[2] - bb[0]
        x = (W - tw) / 2 - bb[0]
        d.text((x, y - bb[1]), l, font=font, fill=FILL, stroke_width=STROKE, stroke_fill=OUTLINE)
        y += h + gap

    im.save(dst, format="JPEG", quality=92, optimize=True)
    print(f"wrote {dst}  ({W}x{H}, size {size}px, block {block_h}px tall, "
          f"widest line {max(width_at(l, size) for l in LINES)}px)")


if __name__ == "__main__":
    main()
