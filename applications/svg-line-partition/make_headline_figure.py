# -*- coding: utf-8 -*-
"""
The one figure worth having for the SVG probe.

The probe's headline is a falsification: permute the coordinates between elements and
region accuracy collapses below the drawing's own majority baseline, while confidence
barely moves. That is two measurements per drawing — accuracy and confidence — and the
argument only lands if both are on screen together, so both panels are drawn from the
same table.

Values are transcribed from the published results table (three decimals, as reported in
results/report.md) and are not recomputed here.
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import gridspec

OUT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "..", "assets", "images"))
os.makedirs(OUT, exist_ok=True)

# name, real acc, permuted acc, real conf, permuted conf, majority baseline
ROWS = [
    ("abstract_nesting", 0.857, 0.048, 0.868, 0.842, 0.286),
    ("house_scene",      0.812, 0.219, 0.782, 0.788, 0.250),
    ("kick_figure",      0.571, 0.000, 0.701, 0.638, 0.357),
]

C_REAL = "#1f6feb"      # real coordinates
C_PERM = "#d1495b"      # permuted coordinates
C_BASE = "#8b949e"      # majority-class baseline
C_CONF = "#3f8f5b"      # confidence

FL = 0.006              # floor so a true 0.000 is still visible on a log axis


def main():
    fig = plt.figure(figsize=(13.2, 6.6), dpi=130)
    fig.patch.set_facecolor("white")
    gs = gridspec.GridSpec(1, 2, figure=fig, width_ratios=[1.42, 1.0],
                           wspace=0.20, left=0.105, right=0.975,
                           top=0.795, bottom=0.145)

    y = np.arange(len(ROWS))
    h = 0.33

    # ---------------- panel 1: accuracy (log scale) ----------------
    ax = fig.add_subplot(gs[0, 0])
    real = [max(r[1], FL) for r in ROWS]
    perm = [max(r[2], FL) for r in ROWS]
    base = [r[5] for r in ROWS]

    ax.barh(y - h / 1.7, real, height=h, color=C_REAL, label="Real coordinates", zorder=3)
    ax.barh(y + h / 1.7, perm, height=h, color=C_PERM, label="Coordinates permuted", zorder=3)
    for yi, b in zip(y, base):
        ax.plot([b, b], [yi - 0.46, yi + 0.46], color=C_BASE, lw=2.0, ls=(0, (3, 2)),
                zorder=4, label="Its own majority-class baseline" if yi == y[0] else None)

    for yi, (r, p, b) in zip(y, [(r[1], r[2], r[5]) for r in ROWS]):
        ax.text(r + 0.012, yi - h / 1.7, "hit %.3f" % r, va="center", fontsize=9.4,
                color=C_REAL, fontweight="bold")
        ax.text(max(p, FL) + 0.012, yi + h / 1.7,
                ("hit %.3f" % p) + ("   (below baseline)" if p < b else ""),
                va="center", fontsize=9.4, color=C_PERM, fontweight="bold")

    ax.set_xscale("log")
    ax.set_xlim(FL, 4.2)
    ax.set_xticks([0.01, 0.05, 0.1, 0.25, 0.5, 1.0])
    ax.set_xticklabels(["0.01", "0.05", "0.1", "0.25", "0.5", "1.0"], fontsize=9)
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in ROWS], fontsize=10.5)
    ax.invert_yaxis()
    ax.set_ylim(len(ROWS) - 0.45, -0.95)
    ax.set_xlabel("Region classification hit rate  (log scale)", fontsize=10.2)
    ax.set_title("Accuracy collapses when the evidence is fake",
                 fontsize=12, fontweight="bold", loc="left", pad=9)
    ax.grid(axis="x", color="#e6e9ee", zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(loc="upper right", fontsize=8.8, frameon=True, framealpha=0.95)

    # ---------------- panel 2: confidence ----------------
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.barh(y - h / 1.7, [r[3] for r in ROWS], height=h, color=C_CONF, zorder=3,
             label="Real coordinates")
    ax2.barh(y + h / 1.7, [r[4] for r in ROWS], height=h, color="#9dc3ae", zorder=3,
             label="Coordinates permuted")

    for yi, r in zip(y, ROWS):
        ax2.text(r[3] + 0.012, yi - h / 1.7, "%.3f" % r[3], va="center", fontsize=9.4,
                 color="#2c6b45", fontweight="bold")
        ax2.text(r[4] + 0.012, yi + h / 1.7, "%.3f" % r[4], va="center", fontsize=9.4,
                 color="#5c8570", fontweight="bold")
        # sign convention: this is the CHANGE in confidence, so a drop reads negative
        ax2.text(0.012, yi + 0.37, "confidence change  %+.3f" % (r[4] - r[3]),
                 va="center", fontsize=8.6, color="#6a7078", style="italic")

    ax2.set_xlim(0, 1.62)
    ax2.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax2.set_xticklabels(["0", "0.25", "0.5", "0.75", "1.0"], fontsize=9)
    ax2.set_yticks(y)
    ax2.set_yticklabels([r[0] for r in ROWS], fontsize=10.5)
    ax2.invert_yaxis()
    ax2.set_ylim(len(ROWS) - 0.45, -0.95)
    ax2.set_xlabel("Stated confidence", fontsize=10.2)
    ax2.set_title("…and confidence barely notices",
                  fontsize=12, fontweight="bold", loc="left", pad=9)
    ax2.grid(axis="x", color="#e6e9ee", zorder=0)
    ax2.set_axisbelow(True)
    for s in ("top", "right"):
        ax2.spines[s].set_visible(False)
    ax2.legend(loc="upper right", fontsize=8.8, frameon=True, framealpha=0.95)

    # ---------------- framing ----------------
    fig.suptitle("Jev is not responsible for whether its evidence is true",
                 fontsize=16.5, fontweight="bold", color="#0d1117", y=0.965)
    fig.text(0.5, 0.895,
             "Same questions, same six drawings — only the coordinates change, randomly permuted between elements.",
             ha="center", fontsize=10.4, color="#4a505a")
    fig.text(0.5, 0.045,
             "Accuracy falls below each drawing's own majority-class baseline. Confidence changes by −0.026, +0.006 "
             "and −0.063 across the three drawings — a mean of −0.028.\n"
             "The model has no capacity to suspect that the state contradicts itself. "
             "Source: results/report.md · model pinned to jev-1.13.0 · reproduced by make_headline_figure.py",
             ha="center", fontsize=8.8, color="#5a6069", linespacing=1.8)

    out = os.path.join(OUT, "svg_false_evidence.png")
    fig.savefig(out, facecolor="white")
    plt.close(fig)

    from PIL import Image
    im = Image.open(out).convert("RGB")
    im.thumbnail((1500, 1500), Image.LANCZOS)
    im.save(out, format="PNG", optimize=True, compress_level=9)
    print("wrote", out, "(%d KB, %dx%d)" % (os.path.getsize(out) / 1024, im.size[0], im.size[1]))


if __name__ == "__main__":
    main()
