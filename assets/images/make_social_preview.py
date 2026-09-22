# -*- coding: utf-8 -*-
"""
Build the GitHub social preview card (1280x640, GitHub's required size).

GitHub has no API for this, so the file is generated here and uploaded by hand:
Settings -> General -> Social preview.

Design rationale: the auto-generated card shows only the repo name and description.
This one carries the two facts a reader actually needs to decide whether to click —
that three unrelated domains are covered, and that two of the three can be checked
without an API key — plus the headline number.
"""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "..", "assets", "images"))
os.makedirs(OUT, exist_ok=True)

W, H = 1280, 640
BG = (13, 17, 23)          # GitHub dark canvas
FG = (240, 246, 252)
MUTED = (139, 148, 158)
ACCENT = (95, 214, 255)    # the player-blue from the game
GOLD = (255, 199, 56)      # the meme/KPI accent

FONTS = {
    "bold": [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"],
    "regular": [r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"],
    "mono": [r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\cour.ttf"],
}


def font(kind, size):
    for p in FONTS[kind]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def main():
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    # a thin accent rule down the left edge, echoing the game's palette
    d.rectangle([0, 0, 7, H], fill=ACCENT)

    x = 74
    y = 74

    # kicker
    d.text((x, y), "TYPESAFE JEV  ·  SYSTEM ONE", font=font("bold", 21), fill=ACCENT)
    y += 52

    # title (two lines, hand-broken so it never wraps badly)
    ft = font("bold", 62)
    d.text((x, y), "Field notes on Jev", font=ft, fill=FG)
    y += 76
    d.text((x, y), "Applications & boundaries", font=ft, fill=FG)
    y += 104

    # description
    fd = font("regular", 25)
    for line in [
        "A real-time fighting game, parametric speech synthesis, and a",
        "vector-drawing probe — three unrelated domains, one division of labour:",
        "code owns the truth tables, Jev is asked only what has no table.",
    ]:
        d.text((x, y), line, font=fd, fill=MUTED)
        y += 37

    y += 34

    # stat row
    stats = [
        ("3", "applications"),
        ("2", "run offline, no key"),
        ("52", "tests, no network"),
        ("16", "measured findings"),
    ]
    sx = x
    fn = font("bold", 40)
    fl = font("regular", 19)
    for i, (num, label) in enumerate(stats):
        d.text((sx, y), num, font=fn, fill=GOLD if i == 0 else FG)
        d.text((sx, y + 48), label, font=fl, fill=MUTED)
        sx += 268

    # footer
    d.line([(x, H - 74), (W - 74, H - 74)], fill=(48, 54, 61), width=1)
    d.text((x, H - 56), "github.com/scd13150/jev-field-notes",
           font=font("mono", 20), fill=MUTED)

    out = os.path.join(OUT, "social_preview.png")
    im.save(out, format="PNG", optimize=True)
    print("wrote", out, "(%d KB, %dx%d)" % (os.path.getsize(out) / 1024, W, H))


if __name__ == "__main__":
    main()
