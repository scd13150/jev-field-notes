"""Round four: it draws, I planned. A picture assembled from its choices.

The author's job here is *structure* - what marks exist, what each one is for,
which ones hang off which. The numbers that make a mark a particular mark are
left deliberately open: how tall the body, how flat the head, how hard the lid
curves. For every stroke the script enumerates a grid of realisations of the
recipe, shows one phase of them to Jev as geometry, and commits whichever one
it picks. The chosen numbers feed the next phase, so its early choices move the
later candidates' geometry - one drawing loop, not eighteen quizzes.

Three things make the result readable rather than just pretty:

* every knob is tagged **pinned** or **open**. A pinned knob is one my written
  note actually constrains ("the lid arcs down hard"), so agreement there asks
  whether it can read a spec into geometry. An open knob is one my note is
  silent about, so agreement there asks something closer to taste: does its
  drawing look like my drawing when nothing told it what I wanted.
* two code-only choosers run the identical grids: `random` (any candidate will
  do) and `middle` (always the tamest value on every knob). My authored figure
  is deliberately not the middle everywhere, so `middle` is a competitor a
  merely-average drawing would beat.
* mirrored pairs (two ears, two eyes, two whiskers, two paws, two breaths) are
  asked as separate questions, so self-consistency is measured, not assumed.

`mine` is the figure I authored, `jev` the one its choices assembled; both are
rendered to SVG so the difference can be looked at rather than argued about.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

Point = tuple[float, float]
Polys = list[list[Point]]

CANVAS = (260, 240)
PHASES = ("structure", "silhouette", "face", "flourish")

# --------------------------------------------------------------------------- #
# small geometry helpers
# --------------------------------------------------------------------------- #

def _arc(cx: float, cy: float, rx: float, ry: float,
         a0: float, a1: float, n: int = 24) -> list[Point]:
    """Sampled arc; degrees, y growing downward, so 90 is the bottom."""
    return [(cx + rx * math.cos(math.radians(a0 + (a1 - a0) * i / (n - 1))),
             cy + ry * math.sin(math.radians(a0 + (a1 - a0) * i / (n - 1))))
            for i in range(n)]


def _quad(p0: Point, c: Point, p1: Point, n: int = 18) -> list[Point]:
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t ** 2 * p1[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t ** 2 * p1[1])
            for t in [i / (n - 1) for i in range(n)]]


def _seg(*pts: Point) -> list[Point]:
    return list(pts)


def _one(pts: list[Point]) -> Polys:
    return [pts]


def _poly(ctx: dict[str, Any], mid: str) -> list[Point]:
    return ctx[mid][0]


def _box(pts: list[Point]) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _head(ctx: dict[str, Any]) -> tuple[float, float, float, float]:
    """Centre, radius and flatness of the committed head, read off its box,
    so the face hangs off whatever shape was actually chosen."""
    x0, y0, x1, y1 = _box(_poly(ctx, "head"))
    return (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / (x1 - x0)


# --------------------------------------------------------------------------- #
# recipes: each mark is a function of a few small integers
# --------------------------------------------------------------------------- #

def r_frame(ctx, w, h):
    x0 = CANVAS[0] / 2 - w / 2
    y0 = 170 - h + 26
    return [_seg((x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h), (x0, y0))]


def r_shelf(ctx, y, tilt, span):
    x0 = CANVAS[0] / 2 - span / 2
    return [_seg((x0, y + tilt), (x0 + span, y - tilt))]


def r_moon(ctx, r, phase):
    """Crescent: the far side of circle A, the near side of a shifted circle B."""
    cx, cy, d = 52, 46, float(phase)
    if d >= 2 * r:
        d = 2 * r - 1
    a = math.degrees(math.acos(d / (2 * r)))
    return [_seg(*_arc(cx, cy, r, r, a, 360 - a),
                   *_arc(cx + d, cy, r, r, 180 + a, 180 - a))]


def r_mullion(ctx, dx):
    x = CANVAS[0] / 2 + dx
    return [_seg((x, _box(_poly(ctx, "frame"))[1]), (x, 170))]


def r_body(ctx, h, w, lean):
    y0 = _poly(ctx, "shelf")[0][1]
    cx = CANVAS[0] / 2 + lean
    # the control point is twice out, because a quadratic only reaches half of it:
    # this way `h` is the height the arch actually draws, which is what the note
    # and its clause talk about
    return [_quad((cx - w, y0), (cx + 2 * lean, y0 - 2 * h), (cx + w, y0))]


def r_head(ctx, r, squash):
    top = min(p[1] for p in _poly(ctx, "body"))
    xs = [p[0] for p in _poly(ctx, "body")]
    cx = (min(xs) + max(xs)) / 2
    return [_seg(*_arc(cx, top - r * squash * 0.5, r, r * squash, 90, 450))]


def r_tail(ctx, curl, length):
    x, y = _poly(ctx, "body")[-1]
    return [_quad((x, y), (x + length * 0.75, y + length * 0.45),
                  (x + length * 0.6, y - curl))]


def _ear(side: int):
    """A triangle ear standing on the head outline: two base points on the
    circle and an apex outside it. `spread` leans the apex outward."""
    def rec(ctx, size, spread):
        cx, cy, r, sq = _head(ctx)
        def on_head(deg, out=0.0):
            a = math.radians(deg)
            return (cx + (r + out) * math.cos(a), cy + (r * sq + out) * math.sin(a))
        lean = side * (14 + spread * 0.8)
        return [_seg(on_head(270 + side * 26), on_head(270 + lean, size),
                     on_head(270 + side * 5))]
    return rec


def _eye(side: int):
    def rec(ctx, dip, width):
        cx, cy, r, sq = _head(ctx)
        x = cx + side * r * 0.38
        y = cy + r * sq * 0.05
        return [_quad((x - width / 2, y), (x, y + dip), (x + width / 2, y))]
    return rec


def r_nose(ctx, size):
    cx, cy, r, sq = _head(ctx)
    y = cy + r * sq * 0.4
    return [_seg((cx - size / 2, y), (cx, y + size * 0.7), (cx + size / 2, y))]


def _whisker(side: int):
    def rec(ctx, slope, length):
        cx, cy, r, sq = _head(ctx)
        x0, y0 = cx + side * r * 0.88, cy + r * sq * 0.42
        a = math.radians(slope)
        return [_seg((x0, y0), (x0 + side * length * math.cos(a),
                                y0 - length * math.sin(a)))]
    return rec


def _paw(side: int):
    def rec(ctx, width):
        y0 = _poly(ctx, "shelf")[0][1]
        xs = [p[0] for p in _poly(ctx, "body")]
        x = (min(xs) + max(xs)) / 2 + side * width * 0.95
        return [_seg((x - width / 2, y0), (x, y0 - width * 0.36), (x + width / 2, y0))]
    return rec


def r_shadow(ctx, length, gap):
    x0 = CANVAS[0] / 2 - 26
    y = _poly(ctx, "shelf")[0][1] + 5
    return [_seg((x0 + i * gap, y), (x0 + i * gap - length * 0.4, y + length))
            for i in range(3)]


def _breath(side: int):
    def rec(ctx, r, rise):
        cx, cy, hr, sq = _head(ctx)
        return [_arc(cx + side * (hr + 7 + r), cy + hr * sq * 0.5 - rise,
                     r, r, 140, 380, 10)]
    return rec


# --------------------------------------------------------------------------- #
# the plan
# --------------------------------------------------------------------------- #

@dataclass
class Knob:
    name: str
    values: list[float]
    mine: float
    pinned: bool


@dataclass
class Mark:
    mid: str
    phase: str
    recipe: Callable[..., Polys]
    knobs: list[Knob]
    brief: str
    detail: str = ""
    needs: tuple[str, ...] = ()

    def grid(self) -> list[dict[str, float]]:
        out: list[dict[str, float]] = [{}]
        for k in self.knobs:
            out = [dict(d, **{k.name: v}) for d in out for v in k.values]
        return out

    def params(self, which: str) -> dict[str, float]:
        return {k.name: {"mine": k.mine,
                         "middle": k.values[len(k.values) // 2],
                         "tame": min(k.values, key=lambda v: abs(v - k.mine))}[which]
                for k in self.knobs}


def _k(name, values, mine, pinned):
    return Knob(name, [float(v) for v in values], float(mine), pinned)


PLAN: list[Mark] = [
    # ---- structure --------------------------------------------------------- #
    Mark("frame", "structure", r_frame,
         [_k("w", [120, 150, 185], 150, False),
          _k("h", [120, 150, 180], 180, True)],
         "the window opening behind everything",
         "A rectangle standing on the sill, and it is tall: its height is larger "
         "than its width."),
    Mark("shelf", "structure", r_shelf,
         [_k("y", [164, 170, 176], 170, False),
          _k("tilt", [-6, -2, 2, 6], -2, True),
          _k("span", [120, 150, 180], 180, False)],
         "the sill the cat sits on",
         "One straight mark, longer than anything else near the bottom of the "
         "sheet, tipped so that its left end is the lower end.", ("frame",)),
    Mark("moon", "structure", r_moon,
         [_k("r", [10, 15, 21], 21, False),
          _k("phase", [3, 7, 12], 12, True)],
         "the moon, in the upper left of the window",
         "A crescent with a deep bite taken out of it, so what is left reads as a "
         "slim band of moon rather than a round disc."),
    Mark("mullion", "structure", r_mullion,
         [_k("dx", [-26, 0, 26], 26, False)],
         "one vertical bar across the window glass",
         "A single vertical stroke from the top of the frame down to the sill.",
         ("frame", "shelf")),

    # ---- silhouette -------------------------------------------------------- #
    Mark("body", "silhouette", r_body,
         [_k("h", [34, 44, 56, 68], 68, True),
          _k("w", [22, 30, 38], 22, True),
          _k("lean", [-8, 0, 8], 8, False)],
         "the cat's seated back: one curve up from the sill, over a hump, and down",
         "A tall narrow hump - its height is well over its width, and both ends "
         "come down onto the sill.", ("shelf",)),
    Mark("head", "silhouette", r_head,
         [_k("r", [13, 17, 22], 17, False),
          _k("squash", [0.86, 0.94, 1.02], 0.86, True)],
         "the head, resting on top of the back curve",
         "A closed rounded mark, wider than it is tall - a flattened, resting head "
         "- centred over the hump of the back.", ("body",)),
    Mark("tail", "silhouette", r_tail,
         [_k("curl", [-20, -6, 8, 22], 22, True),
          _k("length", [26, 36, 48], 26, False)],
         "the tail, leaving the near end of the body",
         "It leaves the body, dips, and its free end finishes above the lowest point "
         "it passed through: the tip hooks back upward.", ("body",)),

    # ---- face and paws (mirrored pairs, asked separately) ------------------ #
    Mark("ear-l", "face", _ear(-1),
         [_k("size", [7, 11, 15], 15, True), _k("spread", [-12, -2, 8], -12, False)],
         "the cat's ear on the viewer's left",
         "Two short strokes meeting at a point above the head. The point sits high: "
         "a tall ear, large compared with the head.", ("head",)),
    Mark("ear-r", "face", _ear(1),
         [_k("size", [7, 11, 15], 15, True), _k("spread", [-12, -2, 8], -12, False)],
         "the cat's ear on the viewer's right",
         "Two short strokes meeting at a point above the head. The point sits high: "
         "a tall ear, large compared with the head.", ("head",)),
    Mark("eye-l", "face", _eye(-1),
         [_k("dip", [2, 4, 7], 7, True), _k("width", [6, 9, 13], 9, False)],
         "the sleeping cat's eye on the viewer's left",
         "A short arc that bows downward in the middle, and bows hard: a shut lid, "
         "not an open eye.", ("head",)),
    Mark("eye-r", "face", _eye(1),
         [_k("dip", [2, 4, 7], 7, True), _k("width", [6, 9, 13], 9, False)],
         "the sleeping cat's eye on the viewer's right",
         "A short arc that bows downward in the middle, and bows hard: a shut lid, "
         "not an open eye.", ("head",)),
    Mark("nose", "face", r_nose,
         [_k("size", [2, 4, 6], 2, False)],
         "the nose, below and between the two lids"),
    Mark("whisker-l", "face", _whisker(-1),
         [_k("slope", [-16, -6, 4, 14], 14, False),
          _k("length", [14, 22, 30], 30, True)],
         "one whisker on the viewer's left",
         "A single straight mark starting at the face and reaching clearly past the "
         "outline of the head.", ("head",)),
    Mark("whisker-r", "face", _whisker(1),
         [_k("slope", [-16, -6, 4, 14], 14, False),
          _k("length", [14, 22, 30], 30, True)],
         "one whisker on the viewer's right",
         "A single straight mark starting at the face and reaching clearly past the "
         "outline of the head.", ("head",)),
    Mark("paw-l", "face", _paw(-1),
         [_k("width", [6, 10, 14, 18], 6, False)],
         "the front paw on the viewer's left, on the sill", "", ("body", "shelf")),
    Mark("paw-r", "face", _paw(1),
         [_k("width", [6, 10, 14, 18], 6, False)],
         "the front paw on the viewer's right, on the sill", "", ("body", "shelf")),

    # ---- flourish ---------------------------------------------------------- #
    Mark("shadow", "flourish", r_shadow,
         [_k("length", [8, 14, 22], 22, False), _k("gap", [10, 16, 24], 10, False)],
         "three short strokes under the sill, hinting at a shadow", "", ("shelf",)),
    Mark("breath-l", "flourish", _breath(-1),
         [_k("r", [3, 5, 8], 8, False), _k("rise", [6, 14, 24], 24, False)],
         "a small breath curl beside the head, on the viewer's left", "", ("head",)),
    Mark("breath-r", "flourish", _breath(1),
         [_k("r", [3, 5, 8], 8, False), _k("rise", [6, 14, 24], 24, False)],
         "a small breath curl beside the head, on the viewer's right", "", ("head",)),
]

PAIRS = (("ear-l", "ear-r"), ("eye-l", "eye-r"), ("whisker-l", "whisker-r"),
         ("paw-l", "paw-r"), ("breath-l", "breath-r"))

# What a reader would say about the finished sheet. The same list is asked of my
# figure and of the one it assembled, so a gap between the two answers is a
# claim about the drawings, not about the wording.
AUDIT = [
    ("cat", "the sheet contains a cat"),
    ("asleep", "the cat looks asleep rather than awake"),
    ("window", "there is a window behind the cat"),
    ("crescent", "there is a crescent moon"),
    ("sitting on something", "the cat is sitting on a horizontal surface"),
    ("indoors", "the scene reads as being indoors, looking out"),
    ("two ears", "the cat has two ears"),
    ("tail", "the cat has a tail"),
    ("shadow", "there is a shadow under the sill"),
    ("whiskers", "the cat has whiskers"),
]

BY_ID = {m.mid: m for m in PLAN}

# Each artist's note read as separate clauses a mark can be checked against.
# Only the pinned knobs get a clause: `body` says "tall and narrow" in prose,
# which is one judgment per adjective. The knobs I left to taste have no clause
# on purpose - that split is the measurement, and a clause invented after seeing
# the answer would just be the answer written twice.
#
# The clause states the condition, never the number. "Taller than wide" is true
# of two of the offered bodies, so it narrows rather than looks up.
CLAUSES: dict[str, list[str]] = {
    "frame": ["the window opening is clearly taller than it is wide",
              "the opening is tall enough to fill most of the sheet's height"],
    "shelf": ["the sill is nearly level: a tilt you would notice only if you measured it",
              "the right end of the sill sits lower than the left end"],
    "moon": ["the moon is a crescent with some body to it, not a thin sliver"],
    "body": ["the curled back is a tall arch: taller than it is wide",
             "the arch is narrow, so the cat reads as compact rather than sprawled"],
    "head": ["the head is a little wider than it is tall"],
    "tail": ["the tail ends raised above the sill, curling up rather than lying flat"],
    "ear-l": ["the ear is prominent: its apex stands well clear of the head outline"],
    "ear-r": ["the ear is prominent: its apex stands well clear of the head outline"],
    "eye-l": ["the eye is shut: a down-curved arc deep enough to read as asleep"],
    "eye-r": ["the eye is shut: a down-curved arc deep enough to read as asleep"],
    "whisker-l": ["the whisker sweeps well outside the head outline"],
    "whisker-r": ["the whisker sweeps well outside the head outline"],
}
