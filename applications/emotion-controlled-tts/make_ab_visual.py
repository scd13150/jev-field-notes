# -*- coding: utf-8 -*-
"""
Build the README visuals from the A/B audio pairs.

Why this file exists rather than a one-off shell command:
  * The spectrograms must be normalized PER PAIR. Rendering A and B with different
    peak scales would make a loudness difference look like a spectral difference,
    which would be a fake piece of evidence. We measure the true loudness delta,
    report it, and then compare timbre at equal loudness.
  * The color scale and frequency range are fixed across the whole figure so panels
    are comparable to each other.
"""
import os, subprocess, tempfile
import numpy as np
import soundfile as sf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import gridspec

HERE = os.path.dirname(os.path.abspath(__file__))
# Canonical listening-room files (the ones README links). The local audio/ copies
# hold the same content under different names; this figure always renders the shared set.
AUDIO = os.path.abspath(os.path.join(HERE, "..", "..", "assets", "audio"))
OUT = os.path.abspath(os.path.join(HERE, "..", "..", "assets", "images"))
os.makedirs(OUT, exist_ok=True)

PAIRS = [
    ("1", "Self-reproach / self-loathing",
     "dominant axes —  depression 0.85 · self-disgust 0.75 · sorrow 0.70",
     "part1_self_reproach_A_no_emotion.wav", "part1_self_reproach_B_with_jev_emotion.wav"),
    ("2", "Cold resolve",
     "dominant axes —  wrath 0.85 · calm 0.65",
     "part2_cold_resolve_A_no_emotion.wav", "part2_cold_resolve_B_with_jev_emotion.wav"),
    ("3", "Domain invocation",
     "dominant axes —  pressure 0.92 · calm 0.70",
     "part3_domain_expansion_A_no_emotion.wav", "part3_domain_expansion_B_with_jev_emotion.wav"),
]

SPEC_W, SPEC_H = 1100, 420
FREQ_MAX = 8000          # Hz — covers the formant range that carries timbre
DB_RANGE = 78.0          # fixed dynamic range for every panel


def load(path):
    x, sr = sf.read(path, always_2d=True)
    return x.mean(axis=1).astype(np.float64), sr


def rms_db(x):
    r = np.sqrt(np.mean(x ** 2)) if x.size else 0.0
    return 20.0 * np.log10(r) if r > 0 else -120.0


def spectrogram_png(mono, sr, path):
    """Render via ffmpeg so every panel uses the identical filter chain."""
    pcm = (np.clip(mono, -1, 1) * 32767).astype("<i2").tobytes()
    # Option-name note: `scale` is the AMPLITUDE scale and `fscale` is the frequency
    # scale in ffmpeg 7.1. `mel` is valid for neither, and `dr` does not exist (it is
    # `drange`). Verified against `ffmpeg -h filter=showspectrumpic`.
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0",
        "-lavfi", (f"showspectrumpic=s={SPEC_W}x{SPEC_H}:mode=combined:scale=log"
                   f":fscale=log:stop={FREQ_MAX}:color=intensity:legend=disabled"
                   f":drange={DB_RANGE}"),
        "-frames:v", "1", path,
    ]
    p = subprocess.run(cmd, input=pcm, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8", "replace")[:400])
    return path


def main():
    tmp = tempfile.mkdtemp(prefix="jevsx_")
    rows = []

    for num, title, axes, fa, fb in PAIRS:
        xa, sr = load(os.path.join(AUDIO, fa))
        xb, _ = load(os.path.join(AUDIO, fb))
        dur_a, dur_b = len(xa) / sr, len(xb) / sr

        d_a, d_b = rms_db(xa), rms_db(xb)      # measured before any normalization
        delta = d_b - d_a

        target = 20.0 * np.log10(0.1)          # -20 dBFS, shared by both files of the pair
        na = xa * (10 ** ((target - d_a) / 20.0))
        nb = xb * (10 ** ((target - d_b) / 20.0))
        peak = max(np.max(np.abs(na)), np.max(np.abs(nb)), 1e-9)
        if peak > 0.99:                        # never clip the visualization
            na, nb = na * (0.99 / peak), nb * (0.99 / peak)

        rows.append(dict(
            num=num, title=title, axes=axes, dur_a=dur_a, dur_b=dur_b, delta=delta,
            pa=spectrogram_png(na, sr, os.path.join(tmp, f"p{num}a.png")),
            pb=spectrogram_png(nb, sr, os.path.join(tmp, f"p{num}b.png")),
        ))
        print(f"pair {num}: A {dur_a:5.2f}s {d_a:6.1f} dBFS | "
              f"B {dur_b:5.2f}s {d_b:6.1f} dBFS | B is {delta:+.1f} dB")

    # ---- compose ----------------------------------------------------------
    # One axes per spectrogram plus a dedicated caption strip beneath each row,
    # so nothing can collide with anything else.
    fig = plt.figure(figsize=(13.0, 10.6), dpi=125)
    fig.patch.set_facecolor("white")

    gs = gridspec.GridSpec(
        6, 2, figure=fig,
        height_ratios=[1, 0.20, 1, 0.20, 1, 0.20],
        hspace=0.13, wspace=0.05,
        left=0.095, right=0.968, top=0.905, bottom=0.062,
    )

    for r, row in enumerate(rows):
        gi = r * 2
        for c, (key, who) in enumerate([("pa", "A"), ("pb", "B")]):
            ax = fig.add_subplot(gs[gi, c])
            ax.imshow(plt.imread(row[key]), aspect="auto")
            ax.set_xticks([]); ax.set_yticks([])
            for s in ax.spines.values():
                s.set_color("#c2c7d0"); s.set_linewidth(1.1)
            dur = row["dur_a"] if c == 0 else row["dur_b"]
            ax.set_title(f"{who} — {'baseline, no emotion control' if c == 0 else 'Jev-controlled vector'}"
                         f"      {dur:.2f} s",
                         fontsize=9.8, color="#2b3038", pad=5,
                         loc="left" if c == 0 else "right")

        cap = fig.add_subplot(gs[gi + 1, :])
        cap.axis("off")
        cap.text(0.0, 1.02, f"pair {row['num']} · {row['title']}", transform=cap.transAxes,
                 fontsize=11.6, fontweight="bold", color="#14181d", ha="left", va="top")
        cap.text(0.0, 0.44, row["axes"], transform=cap.transAxes,
                 fontsize=9.0, color="#5b6270", ha="left", va="top")
        cap.text(1.0, 0.44, f"B is {row['delta']:+.1f} dB louder before normalization",
                 transform=cap.transAxes, fontsize=9.0, color="#8a5a00", ha="right", va="top")

    fig.suptitle("Jev emotion vector → IndexTTS 2.5: where the difference actually is",
                 fontsize=16, fontweight="bold", color="#0d1117", y=0.972)
    fig.text(0.5, 0.937,
             "Log-frequency spectrogram, 0–8 kHz (0 Hz at the bottom), intensity color, "
             "identical 78 dB dynamic range on every panel.",
             ha="center", fontsize=9.6, color="#4a505a")
    fig.text(0.5, 0.026,
             "Both files of each pair are normalized to the same loudness (−20 dBFS) before rendering, so the spectral "
             "difference shown is timbre, not volume.\nThe measured loudness difference is kept as a label rather than "
             "hidden.  Generated by make_ab_visual.py from the six files in assets/audio/.",
             ha="center", fontsize=8.6, color="#5a6069", linespacing=1.75)

    out = os.path.join(OUT, "ab_spectrograms.png")
    fig.savefig(out, facecolor="white")
    plt.close(fig)
    from PIL import Image
    im = Image.open(out).convert("RGB")
    im.thumbnail((1500, 1500), Image.LANCZOS)
    im.save(out, format="PNG", optimize=True, compress_level=9)
    print("\nwrote", out, f"({os.path.getsize(out)/1024:.0f} KB, {im.size[0]}x{im.size[1]})")


if __name__ == "__main__":
    main()
