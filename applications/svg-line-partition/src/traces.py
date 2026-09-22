"""Drawing-trace experiment: can the *order the pen moved in* carry a partition?

Round one (`serialize.py`, `questions.py`) asked what geometry buys. This round
keeps the geometry true and varies **how the drawing trace is written into the
state**, because that is the signal a machine-redraw pipeline actually has: a
live2d rigger gets the strokes back in the order the artist drew them and has to
come up with a layer stack and a part split from that plus the coordinates.

Three things make this round harder than round one, on purpose:

* the fixtures are flat files - no `<g>` nesting carries any information, so the
  "copy the file structure" shortcut found in round one is gone;
* the parts are decorated with **open strokes** (hair, smoke, whiskers, fur
  hatching) that hold no outline information at all;
* `trace_house_interleaved` and `trace_cat_decor` were drawn with the order
  jumping between parts, so "the next stroke belongs to the same part" is a
  wrong rule on those sheets. A sticky-past predictor is computed in code and
  reported next to the model's numbers so the two can be told apart.

Conditions - the only variable is what the state says about the pen:

  order_named     authored stroke names (which contain the part word), pen order, geometry
  order_list      anonymous s-01.. numbered by pen order, pen order, geometry
  times_only      anonymous numbered by position, geometry, `trace_ms` carrying real times
  order_none      anonymous numbered by position, geometry only, no trace at all
  order_scrambled geometry stays true, but the listed order and the times are a fake
                  trace - the false-evidence control
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from .serialize import _feature_record
from .svggeom import Drawing, Element, load_svg, min_distance

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

TRACE_FIXTURES = ("trace_stick", "trace_house_interleaved", "trace_cat_decor")

CONDITIONS = (
    "order_named",
    "order_list",
    "times_only",
    "order_none",
    "order_scrambled",
)

# which conditions hand the model a trace it can read
ORDER_READABLE = ("order_named", "order_list", "times_only")
# where the trace it reads is the true one
ORDER_TRUE = ("order_named", "order_list", "times_only")

LAYERS = {
    "backdrop": {
        "what": "part of the setting the subject stands in: the surface things rest "
                "on, the sky, a distant disc",
        "not_for": "a mark on the subject itself, or a stroke whose only job is to "
                   "bound the sheet",
    },
    "body": {
        "what": "a stroke that is part of the subject's own shape: an outline or a "
                "limb, something the figure would be missing without it",
        "not_for": "a mark added on top for flavour, or a small line inside a bigger one",
    },
    "detail": {
        "what": "a small stroke that only makes sense on a bigger part of the subject: "
                "an eye, a crack, a fold, a mullion inside a frame",
        "not_for": "the boundary of a part, and a repeated mark doing decorative filler",
    },
    "decor": {
        "what": "a stroke drawn to enliven the picture - it could be recoloured, "
                "redrawn or left out and the object is still complete",
        "not_for": "anything that carries the shape of a part, and ground or sky",
    },
    "guide": {
        "what": "a construction mark the drawing was laid out with and that is not "
                "part of the picture",
        "not_for": "a visible edge of something in the scene",
    },
}

MOTION_FALLBACK = "follows-nothing"

EXTENT_DECOR_LEVELS = [
    "every stroke carries the shape of something; nobody added filler",
    "a handful of decorative marks sit on top of the structural strokes",
    "structural and decorative strokes are about even in number",
    "most of the strokes are decorative filler over a small structural core",
    "the picture is nearly all decoration; the objects are a few strokes",
]

COUNT_LEVELS = [
    "one single piece moves: the picture is a flat whole",
    "two or three pieces move independently of each other",
    "four to six pieces move, most limbs of the subject separate",
    "so many pieces move that the subject is a rig of parts",
]

DECOR_SHARE = "decor_share"


def fixture_path(name: str) -> Path:
    return FIXTURES / f"{name}.svg"


def load(name: str) -> Drawing:
    return load_svg(str(fixture_path(name)))


# --------------------------------------------------------------------------- #
# region truth: a per-fixture tiling, tuned to where the subject actually is.
# A stroke's region is the tile holding most of its drawn length, and
# "spans-several" when no tile reaches half. Code owns that definition, so the
# question the model is asked and the answer it is scored against agree.
#
# The tile names are deliberately spatial and never name a part: a tile called
# "head-area" would make the region question a second bite at the part question.
# --------------------------------------------------------------------------- #

TILES: dict[str, list[tuple[str, float, float, float, float]]] = {
    "trace_stick": [
        ("top-left", 0, 0, 93, 92),
        ("top-centre", 93, 0, 167, 92),
        ("top-right", 167, 0, 260, 92),
        ("middle-left", 0, 92, 93, 190),
        ("middle-centre", 93, 92, 167, 190),
        ("middle-right", 167, 92, 260, 190),
        ("lower-left", 0, 190, 93, 252),
        ("lower-centre", 93, 190, 167, 252),
        ("lower-right", 167, 190, 260, 252),
        ("bottom-band", 0, 252, 260, 300),
    ],
    "trace_house_interleaved": [
        ("top-left", 0, 0, 170, 58),
        ("top-right", 170, 0, 340, 58),
        ("upper-left", 0, 58, 170, 112),
        ("upper-right", 170, 58, 340, 112),
        ("middle-left", 0, 112, 170, 200),
        ("middle-right", 170, 112, 340, 200),
        ("bottom-band", 0, 200, 340, 260),
    ],
    "trace_cat_decor": [
        ("top-left", 0, 0, 120, 140),
        ("top-centre", 120, 0, 215, 140),
        ("top-right", 215, 0, 320, 140),
        ("bottom-left", 0, 140, 120, 240),
        ("bottom-centre", 120, 140, 215, 240),
        ("bottom-right", 215, 140, 320, 240),
    ],
}

SPAN_LABEL = "spans-several"


def _tile_of(x: float, y: float, tiles) -> str | None:
    for name, x0, y0, x1, y1 in tiles:
        if x0 <= x < x1 and y0 <= y < y1:
            return name
    return None


def region_truth(drawing: Drawing, e: Element, step: float = 1.0) -> str:
    """Tile holding the majority of this stroke's drawn length.

    Walked along the arc, not by segment midpoints: a single long straight
    stroke has one midpoint, which would hand it to whichever tile the middle
    happens to fall in even when it runs across three of them.
    """
    tiles = TILES[drawing.name]
    tally: dict[str, float] = {}
    for poly in e.polys:
        for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
            seg = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
            n = max(1, int(seg / step))
            for k in range(n):
                t = (k + 0.5) / n
                hit = _tile_of(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, tiles)
                if hit:
                    tally[hit] = tally.get(hit, 0.0) + seg / n
    total = sum(tally.values())
    if not total:
        return SPAN_LABEL
    best = max(tally, key=lambda k: tally[k])
    return best if tally[best] / total >= 0.5 else SPAN_LABEL


def check_tiling(name: str) -> list[str]:
    """Tiles must cover the canvas exactly: no gaps, no overlaps."""
    d = load(name)
    w, h = d.width, d.height
    bad = []
    step = 2.0
    for x in range(0, int(w), int(step)):
        for y in range(0, int(h), int(step)):
            hits = [n for n, x0, y0, x1, y1 in TILES[name]
                    if x0 <= x < x1 and y0 <= y < y1]
            if len(hits) != 1:
                bad.append(f"({x},{y}) covered by {hits}")
    area = sum((x1 - x0) * (y1 - y0) for _, x0, y0, x1, y1 in TILES[name])
    if abs(area - w * h) > 1:
        bad.append(f"tile area {area} != canvas {w * h}")
    return bad


# --------------------------------------------------------------------------- #
# trace facts owned by code
# --------------------------------------------------------------------------- #

def trace_ms(e: Element) -> int:
    return int(e.attrs.get("data-t", "0"))


def pen_order(drawing: Drawing) -> list[str]:
    """Document order is the pen order in these fixtures."""
    return [e.eid for e in drawing.elements]


def position_sort(drawing: Drawing) -> list[str]:
    """An order with no drawing information: top-to-bottom, then left-to-right."""
    return [e.eid for e in sorted(drawing.elements,
                                  key=lambda e: (round(e.centroid[1] / 10),
                                                 round(e.centroid[0] / 10)))]


# --------------------------------------------------------------------------- #
# states
# --------------------------------------------------------------------------- #

def _ids(drawing: Drawing, condition: str) -> dict[str, str]:
    """What the model sees as an id, and in which sequence the list is written."""
    if condition == "order_named":
        return {e.eid: e.eid for e in drawing.elements}
    if condition in ("order_list",):
        return {e.eid: f"s{i + 1:02d}" for i, e in enumerate(drawing.elements)}
    if condition == "times_only":
        return {eid: f"s{i + 1:02d}" for i, eid in enumerate(position_sort(drawing))}
    if condition == "order_none":
        return {eid: f"s{i + 1:02d}" for i, eid in enumerate(position_sort(drawing))}
    if condition == "order_scrambled":
        rng = random.Random(77)
        perm = list(drawing.elements)
        rng.shuffle(perm)
        return {e.eid: f"s{i + 1:02d}" for i, e in enumerate(perm)}
    raise ValueError(condition)


def _sequence(drawing: Drawing, condition: str) -> list[str]:
    """Fixture element ids, in the order the state lists them."""
    if condition == "order_scrambled":
        rng = random.Random(77)
        perm = list(drawing.elements)
        rng.shuffle(perm)
        return [e.eid for e in perm]
    if condition in ("times_only", "order_none"):
        return position_sort(drawing)
    return [e.eid for e in drawing.elements]


def build_state(drawing: Drawing, condition: str) -> dict[str, Any]:
    ids = _ids(drawing, condition)
    seq = _sequence(drawing, condition)
    by_eid = {e.eid: e for e in drawing.elements}
    real_t = {e.eid: trace_ms(e) for e in drawing.elements}
    rng = random.Random(1013)

    elements = []
    for pos, eid in enumerate(seq):
        e = by_eid[eid]
        rec = _feature_record(e, ids[eid])
        if condition in ("order_named", "order_list"):
            # the array order and the times both say the same true thing, which is
            # what a real recording of a drawing session would look like
            rec["trace_ms"] = real_t[eid]
        elif condition == "times_only":
            rec["trace_ms"] = real_t[eid]
        elif condition == "order_scrambled":
            # a self-consistent lie: the listed order and its times both say a
            # pen path that never happened
            rec["trace_ms"] = pos * (340 + rng.randint(0, 90))
        elements.append(rec)

    state: dict[str, Any] = {
        "canvas": {"width": int(drawing.width), "height": int(drawing.height)},
        "coordinate_note": "x grows rightward, y grows downward, in canvas points. "
                           "The picture is line art: every element is a stroke, no fills.",
        "view_note": "left and right name the viewer's sides.",
        "tiles": [{"name": n, "x_from": x0, "y_from": y0, "x_to": x1, "y_to": y1}
                  for n, x0, y0, x1, y1 in TILES[drawing.name]],
        "tile_note": "the tiles are a partition of the canvas: they cover it, "
                     "overlap nowhere, and each is a rectangle",
        "elements": elements,
    }
    if condition == "order_none":
        state["note"] = ("this state lists strokes in no particular drawing order and "
                         "records nothing about when each was drawn")
    elif condition == "times_only":
        # the sequence is here, just not as list position: saying so explicitly
        # keeps "it cannot read a timeline" apart from "the state never told it a
        # timeline was there"
        state["note"] = ("element ids are arbitrary labels and the list is sorted by "
                         "position, so the order on screen is not the drawing order; "
                         "trace_ms is the pen-down time of each stroke, so the order "
                         "the pen moved in can be recovered by comparing those numbers")
    elif condition in ("order_named", "order_list", "order_scrambled"):
        state["note"] = ("the elements array is in the order the pen laid these "
                         "strokes down; trace_ms is the pen-down time of that stroke")
    return state


TRACE_TOKENS = ("data-truth", "trace of", "author", "truth")


def leak_check(state: dict[str, Any], condition: str, drawing: Drawing) -> list[str]:
    """Nothing derived from the answer key may ride along.

    Under `order_named` the authored stroke *names* are the variable being
    ablated, so they are allowed; every condition is still checked for the truth
    fields themselves and for a `groups` tree.
    """
    blob = repr(state)
    leaks = [tok for tok in TRACE_TOKENS if tok in blob]
    for key in ("part", "layer", "motion", "region", "truth", "groups", "closed_note"):
        if f"'{key}'" in blob or f'"{key}"' in blob:
            leaks.append(f"field:{key}")
    if condition != "order_named":
        words = set()
        for e in drawing.elements:
            for field in ("part", "layer", "motion"):
                v = e.truth.get(field, "")
                if v and v != "none":
                    words.add(v)
        for w in sorted(words):
            if f'"{w}"' in blob or f"'{w}'" in blob:
                leaks.append(f"name:{w}")
    return sorted(set(leaks))


def serialize(drawing: Drawing, condition: str) -> dict[str, Any]:
    state = build_state(drawing, condition)
    leaks = leak_check(state, condition, drawing)
    if leaks:
        raise AssertionError(f"{condition}: answer key leaked into state: {leaks}")
    return state


def state_ids(drawing: Drawing, condition: str) -> dict[str, str]:
    """state id -> fixture element id"""
    return {v: k for k, v in _ids(drawing, condition).items()}


# --------------------------------------------------------------------------- #
# vocabularies and truth
# --------------------------------------------------------------------------- #

def parts_of(drawing: Drawing) -> list[str]:
    """Authored part vocabulary, minus the fallback the criteria add by name."""
    got = {e.truth.get("part", "") for e in drawing.elements} - {"", "none"}
    return sorted(got)


def motions_of(drawing: Drawing) -> list[str]:
    got = {e.truth.get("motion", "") for e in drawing.elements} - {"", "none"}
    return sorted(got) + [MOTION_FALLBACK]


def regions_of(name: str) -> list[str]:
    return [t[0] for t in TILES[name]] + [SPAN_LABEL]


def truth_of(drawing: Drawing) -> dict[str, dict[str, Any]]:
    order = {eid: i for i, eid in enumerate(pen_order(drawing))}
    out: dict[str, dict[str, Any]] = {}
    for e in drawing.elements:
        decor_open = (e.truth.get("layer") == "decor") and not e.closed
        motion = e.truth.get("motion", "")
        out[e.eid] = {
            "part": e.truth.get("part", ""),
            "layer": e.truth.get("layer", ""),
            "motion": MOTION_FALLBACK if motion in ("", "none") else motion,
            "region": region_truth(drawing, e),
            "loose_decor": int(decor_open),
            "index": order[e.eid],
            "trace_ms": trace_ms(e),
            "closed": bool(e.closed),
        }
    return out


# --------------------------------------------------------------------------- #
# pair candidates: quota-picked, class-balanced, directional ones mirrored
# --------------------------------------------------------------------------- #

def _mirror(f: dict[str, Any]) -> dict[str, Any]:
    return {**f, "why": f["why"] + " (handed over the other way round)",
            "a_index": f["b_index"], "b_index": f["a_index"],
            "a_after_b": f["b_after_a"], "b_after_a": f["a_after_b"],
            "adjacent": f["adjacent"]}


def pair_candidates(drawing: Drawing, budget: int = 18
                    ) -> list[tuple[str, str, dict[str, Any]]]:
    els = drawing.elements
    order = {eid: i for i, eid in enumerate(pen_order(drawing))}
    truth = truth_of(drawing)
    out: list[tuple[str, str, dict[str, Any]]] = []
    seen: set[frozenset[str]] = set()

    def add(a: Element, b: Element, why: str):
        if a is b or frozenset((a.eid, b.eid)) in seen or len(out) >= budget:
            return
        seen.add(frozenset((a.eid, b.eid)))
        ia, ib = order[a.eid], order[b.eid]
        out.append((a.eid, b.eid, {
            "why": why,
            "a_index": ia, "b_index": ib,
            "gap_steps": abs(ia - ib),
            "adjacent": abs(ia - ib) == 1,
            "a_after_b": ia > ib,
            "b_after_a": ib > ia,
            "same_part": truth[a.eid]["part"] == truth[b.eid]["part"]
                         and truth[a.eid]["part"] != "",
            "same_motion": truth[a.eid]["motion"] == truth[b.eid]["motion"],
            "same_family": bool(a.family and a.family == b.family),
            "both_open": not a.closed and not b.closed,
            "gap": round(min_distance(a.polys, b.polys), 1),
        }))

    def take(why: str, keep, budget_for: int):
        start = len(out)
        for i, a in enumerate(els):
            for b in els[i + 1:]:
                if len(out) - start >= budget_for or len(out) >= budget:
                    return
                if keep(a, b):
                    add(a, b, why)

    # hard negatives first: same repeated family, different part (the fur trap),
    # and neighbours in the pen order that belong to different parts
    take("same family different part",
         lambda a, b: bool(a.family and a.family == b.family)
         and truth_of_el(truth, a) != truth_of_el(truth, b), 4)
    take("pen-neighbours different part",
         lambda a, b: abs(order[a.eid] - order[b.eid]) == 1
         and truth_of_el(truth, a) != truth_of_el(truth, b), 5)
    # positives: same part, far apart in the pen (so contiguity is not what is
    # being rewarded), and same part, adjacent
    take("same part far apart",
         lambda a, b: truth_of_el(truth, a) == truth_of_el(truth, b)
         and abs(order[a.eid] - order[b.eid]) >= 4, 4)
    take("same part adjacent",
         lambda a, b: truth_of_el(truth, a) == truth_of_el(truth, b)
         and abs(order[a.eid] - order[b.eid]) == 1, 3)
    # far-apart different-part negative controls
    take("far apart different part",
         lambda a, b: truth_of_el(truth, a) != truth_of_el(truth, b)
         and min_distance(a.polys, b.polys) > 40, 3)

    return [(b, a, _mirror(f)) if i % 2 else (a, b, f)
            for i, (a, b, f) in enumerate(out)]


def truth_of_el(truth: dict[str, dict[str, Any]], e: Element) -> str:
    return truth[e.eid]["part"]


# --------------------------------------------------------------------------- #
# questions
# --------------------------------------------------------------------------- #

# The part vocabulary is handed to the model on purpose: in a machine-redraw
# pipeline the layer names are decided by the artist first, and the question is
# which named bucket a stroke belongs in. Glosses exist only where the labels are
# genuinely confusable in these drawings - hair versus head, fur versus
# whiskers, wall versus the openings cut into it - because a Choice criterion is
# judged on its own, without seeing its neighbours.
PART_GLOSSES: dict[str, dict[str, dict[str, str]]] = {
    "trace_stick": {
        "head": {"what": "the skull of the figure and the marks drawn on its surface",
                 "not_for": "the strands standing up off the top of it"},
        "hair": {"what": "one of the short strands drawn standing off the head",
                 "not_for": "a mark inside the head outline"},
        "torso": {"what": "the trunk of the figure, and cloth drawn on the trunk",
                  "not_for": "an arm, or the band wrapped at the neck"},
        "scarf": {"what": "the band wrapped around the neck and laid over the trunk",
                  "not_for": "the trunk line itself, or a fold on the shirt"},
        "arm-l": {"what": "the upper limb on the viewer's left, including its hand",
                  "not_for": "the limb on the other side"},
        "arm-r": {"what": "the upper limb on the viewer's right, including its hand",
                  "not_for": "the limb on the other side"},
        "leg-l": {"what": "the lower limb on the viewer's left, including its foot",
                  "not_for": "the limb on the other side"},
        "leg-r": {"what": "the lower limb on the viewer's right, including its foot",
                  "not_for": "the limb on the other side"},
        "ground": {"what": "the surface line the figure is standing on",
                   "not_for": "any mark on the figure itself"},
        "sparkle": {"what": "a small free ornament drawn in the empty space",
                    "not_for": "anything attached to the figure"},
    },
    "trace_house_interleaved": {
        "wall": {"what": "the front face of the house and marks drawn on that face",
                 "not_for": "an opening cut into it, or the roof above it"},
        "roof": {"what": "the sloped top of the house, including marks brushed on it",
                 "not_for": "the stack that pokes up through it"},
        "door": {"what": "the opening for walking through, its inner panel and its knob",
                 "not_for": "the wall around the opening"},
        "window": {"what": "the opening for light, its frame and its glazing bars",
                   "not_for": "the door, or the wall face"},
        "chimney": {"what": "the masonry stack rising above the roof line",
                    "not_for": "the drifting marks above it"},
        "smoke": {"what": "the drifting marks in the sky above the stack",
                  "not_for": "the stack itself"},
        "fence": {"what": "the barrier standing away from the house: its posts and rail",
                  "not_for": "a face of the house"},
        "grass": {"what": "short marks brushed on the ground surface",
                  "not_for": "the ground line itself"},
        "ground": {"what": "the long surface line everything stands on",
                   "not_for": "tufts drawn above it"},
        "sun": {"what": "the disc in the sky and the rays around it",
                "not_for": "anything on the ground"},
    },
    "trace_cat_decor": {
        "head": {"what": "the skull of the animal and the features drawn on it",
                 "not_for": "the ears on top of it, or lines coming off the muzzle"},
        "ear-left": {"what": "the ear triangle on the viewer's left side of the head",
                     "not_for": "the other ear, or a strand of coat"},
        "ear-right": {"what": "the ear triangle on the viewer's right side of the head",
                      "not_for": "the other ear, or a strand of coat"},
        "fur": {"what": "one of the short repeated strands brushed inside the outline "
                        "of the animal, all doing the same job",
                "not_for": "a long thin line that crosses the outline from the muzzle"},
        "whiskers": {"what": "one of the long thin lines that come out of the muzzle "
                             "and run past the outline",
                     "not_for": "a short strand lying inside the outline"},
        "body": {"what": "the trunk outline the legs and the tail attach to",
                 "not_for": "the head"},
        "legs": {"what": "one of the short uprights under the trunk",
                 "not_for": "the tail, or the trunk outline"},
        "tail": {"what": "the long curve coming off the rear of the trunk",
                 "not_for": "a leg"},
        "fly": {"what": "the small insect drawn away from the animal",
                "not_for": "any part of the animal"},
        "ground": {"what": "the surface line the animal stands on",
                   "not_for": "a mark on the animal"},
    },
}


def part_criteria(drawing: Drawing) -> dict[str, Any]:
    glosses = PART_GLOSSES[drawing.name]
    out: dict[str, Any] = {}
    for w in parts_of(drawing):
        if w in glosses:
            out[w] = dict(glosses[w])
        else:
            out[w] = {"what": f"it is a mark belonging to {w}",
                      "not_for": "marks belonging to any other single one of these"}
    out["none"] = {"what": "it belongs to no part of the drawn subject: a construction "
                           "mark, or a stroke that stands on its own",
                   "not_for": "a stroke that rides with some named part"}
    return out


def element_index(state: dict[str, Any]) -> dict[str, int]:
    return {el["id"]: i for i, el in enumerate(state["elements"])}


def _ref(idx: dict[str, int], sid: str) -> str:
    return f"`state.elements[{idx[sid]}]` (the stroke whose id is \"{sid}\")"


def build_questions(drawing: Drawing, state: dict[str, Any],
                    pairs: list[tuple[str, str, dict[str, Any]]],
                    condition: str) -> dict[str, Any]:
    idx = element_index(state)
    ids = _ids(drawing, condition)
    motions = motions_of(drawing)
    regions = regions_of(drawing.name)
    tile_box = {t["name"]: t for t in state["tiles"]}
    qs: dict[str, Any] = {}

    def motion_crit(words: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for w in words:
            if w == MOTION_FALLBACK:
                out[w] = {"what": "nothing of the subject carries it: it is the setting, "
                                  "or a mark that hangs where it is",
                          "not_for": "a stroke attached to some moving piece"}
            else:
                out[w] = {"what": f"it is attached to {w}, so {w} would take it along "
                                  f"when {w} turns, sways or breathes",
                          "not_for": "a stroke that some other single piece carries, "
                                     "and a stroke that stays put"}
        return out

    for eid in _sequence(drawing, condition):
        sid = ids[eid]
        r = _ref(idx, sid)
        qs[f"part::{eid}"] = {
            "type": "choice",
            "instructions": {
                "question": f"Which single part of the drawn subject is {r} a mark on?",
                "focus": "Group by what the stroke depicts and where it lies. If this "
                         "state records the order the pen moved in, that sequence may "
                         "help you decide; the stroke's own shape and position decide "
                         "in the end.",
            },
            "criteria": part_criteria(drawing),
        }
        qs[f"layer::{eid}"] = {
            "type": "choice",
            "instructions": {
                "question": f"What role does {r} play in the layer stack of this drawing?",
                "focus": "Ask what this stroke is for, not how big it is.",
            },
            "criteria": dict(LAYERS),
        }
        qs[f"region::{eid}"] = {
            "type": "choice",
            "instructions": {
                "question": f"Which single tile of `state.tiles` holds most of the drawn "
                            f"length of {r}?",
                "focus": "Add up how much of the stroke falls inside each rectangle; a "
                         "tile wins when it holds at least half of the length.",
            },
            "criteria": {**{name: {"what": f"the rectangle "
                                           f"`state.tiles` entry named \"{name}\" "
                                           f"(x {tile_box[name]['x_from']}-"
                                           f"{tile_box[name]['x_to']}, y "
                                           f"{tile_box[name]['y_from']}-"
                                           f"{tile_box[name]['y_to']}) holds at least "
                                           f"half of the stroke's length",
                             "not_for": "a stroke that runs on out of that rectangle"}
                         for name in regions if name != SPAN_LABEL},
                         SPAN_LABEL: {"what": "the stroke runs across tiles and no single "
                                              "tile holds half of its length",
                                      "not_for": "a stroke that lies mostly in one "
                                                 "rectangle, even near its edge"},
                         },
        }
        qs[f"motion::{eid}"] = {
            "type": "choice",
            "instructions": {
                "question": f"When this drawing is animated - the subject breathes, "
                            f"turns, sways - which moving piece should carry {r} along?",
                "focus": "Judge by what the stroke is attached to in the depicted "
                         "subject, the way a rigger would group strokes so they move "
                         "together.",
            },
            "criteria": motion_crit(motions),
        }
        qs[f"loose_decor::{eid}"] = {
            "type": "noul",
            "instructions": f"{r} is an open stroke added for decoration, so redrawing "
                            f"it as its own small floating layer would not take anything "
                            f"structural away from the subject.",
            "criteria": {"true": "it is open (not a closed outline) and it is decoration",
                         "false": "it closes a shape, or it carries the subject's structure"},
        }

    for a, b, facts in pairs:
        ra, rb = _ref(idx, ids[a]), _ref(idx, ids[b])
        qs[f"p_same_part::{a}|{b}"] = {
            "type": "noul",
            "instructions": f"Do {ra} and {rb} belong to the same single part of the "
                            f"drawn subject?",
            "criteria": {"true": "they are both marks on one part",
                         "false": "they sit on different parts, or one of them belongs "
                                  "to no part"},
        }
        qs[f"p_same_motion::{a}|{b}"] = {
            "type": "noul",
            "instructions": f"When the drawing is animated, would {ra} and {rb} move "
                            f"with the same piece?",
            "criteria": {"true": "a rigger would put both strokes on one moving piece",
                         "false": "they would move apart, or one of them stays put"},
        }
        qs[f"p_adjacent::{a}|{b}"] = {
            "type": "noul",
            "instructions": f"Were {ra} and {rb} drawn one right after the other, with "
                            f"no other stroke drawn in between?",
            "criteria": {"true": "they are consecutive in the drawing session",
                         "false": "other strokes were drawn between them, or the state "
                                  "does not say"},
        }
        qs[f"p_after::{a}|{b}"] = {
            "type": "noul",
            "instructions": f"Was {ra} drawn after {rb}?",
            "criteria": {"true": "the pen laid the first stroke down later than the second",
                         "false": "it laid it down earlier, or the state does not say"},
        }

    qs["g_order_readable"] = {
        "type": "noul",
        "instructions": "Taking this state as it is written, could you tell that one "
                        "particular stroke of `state.elements` was drawn before another "
                        "one?",
        "criteria": {"true": "the state carries the drawing sequence somehow",
                     "false": "the state says nothing about when strokes were drawn"},
    }
    qs["g_moving_parts"] = {
        "type": "score",
        "instructions": "How many independently moving pieces would a rigger cut this "
                        "drawing into before animating it?",
        "criteria": list(COUNT_LEVELS),
    }
    qs[DECOR_SHARE] = {
        "type": "score",
        "instructions": "How much of this drawing is made of decorative strokes rather "
                        "than strokes that carry the shape of something?",
        "criteria": list(EXTENT_DECOR_LEVELS),
    }
    return qs


# --------------------------------------------------------------------------- #
# code-side comparators, so the model's numbers can be read against a rule
# --------------------------------------------------------------------------- #

# The hand-written table a dumb pipeline is allowed to have: which closed
# outlines stand for which part, and which moving piece that outline rides on
# (a rig list an artist writes once). Beyond this table the rules below use only
# containment, point distances and the stroke sequence.
OUTLINE_OWNER: dict[str, dict[str, tuple[str, str]]] = {
    "trace_stick": {"head": ("head", "head")},
    "trace_house_interleaved": {"wall-front": ("wall", "wall"),
                                "roof": ("roof", "roof"),
                                "door-frame": ("door", "door"),
                                "door-panel": ("door", "door"),
                                "window-frame": ("window", "window"),
                                "chimney": ("chimney", "chimney"),
                                "sun": ("sun", "follows-nothing")},
    "trace_cat_decor": {"body-outline": ("body", "body"),
                        "head": ("head", "head"),
                        "ear-left": ("head", "head"),
                        "ear-right": ("head", "head")},
}

FIELD_COL = {"part": 0, "motion": 1}


def geometric_rule_part(drawing: Drawing, field: str = "part") -> dict[str, str]:
    """An outline names itself; otherwise the smallest outline containing it,
    else the nearest outline within 6 points, else "none".

    A stroke no closed outline can place comes back as "none", because a rule has
    no idea what a bare line depicts. This is what pure containment buys.
    """
    owner = OUTLINE_OWNER[drawing.name]
    col = FIELD_COL[field]
    closed = [e for e in drawing.elements if e.eid in owner]
    out: dict[str, str] = {}
    for e in drawing.elements:
        if e.eid in owner:
            best = e
        else:
            cands = [o for o in closed if e.eid in o.enclosers]
            if cands:
                best = min(cands, key=lambda o: o.area)
            else:
                best = min((o for o in closed if o is not e),
                           key=lambda o: min_distance(o.polys, e.polys), default=None)
                if best is None or min_distance(best.polys, e.polys) > 6:
                    out[e.eid] = "none"
                    continue
        out[e.eid] = owner[best.eid][col]
    return out


# The pen-travel cut-off used to decide "the pen moved somewhere else, so this is
# a new part". One round number for every fixture, not tuned per drawing: the
# report shows the travel distances themselves, so the reader can see that no
# single threshold separates same-part from different-part neighbours here.
PEN_JUMP = 25.0


def pen_travel(a: Element, b: Element) -> float:
    """How far the pen has to move from the end of one stroke to the start of the
    next. Direction matters, so this is not a distance between shapes."""
    from_ = a.polys[-1][-1]
    to = b.polys[0][0]
    return ((to[0] - from_[0]) ** 2 + (to[1] - from_[1]) ** 2) ** 0.5


def pen_run(drawing: Drawing, condition: str, field: str = "part",
            jump: float = PEN_JUMP) -> dict[str, str]:
    """The contiguity bet: consecutive strokes the pen did not travel between are
    one part.

    Within a run of close-together strokes, the first stroke the geometric rule
    can place names the whole run; strokes it cannot place inherit that name.
    A long travel starts a fresh run. Scored under each condition's own sequence,
    which is what makes it a test of what the order itself is worth to a rule.
    """
    seq = _sequence(drawing, condition)
    by = {e.eid: e for e in drawing.elements}
    geo = geometric_rule_part(drawing, field)
    out: dict[str, str] = {}
    cur, prev = "none", None
    for eid in seq:
        e = by[eid]
        if prev is not None and pen_travel(prev, e) > jump:
            cur = "none"
        if geo[eid] != "none":
            cur = geo[eid]
        out[eid] = cur
        prev = e
    return out


def pen_run_motion(drawing: Drawing, condition: str) -> dict[str, str]:
    return pen_run(drawing, condition, "motion")


def travel_separation(drawing: Drawing) -> dict[str, float]:
    """Do short pen travels even mean 'same part' in this drawing?

    Reported next to the rule's accuracy because it is the reason the rule can or
    cannot work: the AUC of travel distance as a same-part test, over the
    consecutive pairs of the real pen path.
    """
    seq = list(drawing.elements)
    truth = truth_of(drawing)
    pos = [pen_travel(a, b) for a, b in zip(seq, seq[1:])
           if truth[a.eid]["part"] == truth[b.eid]["part"]]
    neg = [pen_travel(a, b) for a, b in zip(seq, seq[1:])
           if truth[a.eid]["part"] != truth[b.eid]["part"]]
    wins = sum((p < n) + 0.5 * (p == n) for p in pos for n in neg)
    return {"n_same_runs": len(pos), "n_breaks": len(neg),
            "auc": round(wins / (len(pos) * len(neg)), 3) if pos and neg else None,
            "median_same": round(sorted(pos)[len(pos) // 2], 1) if pos else None,
            "median_diff": round(sorted(neg)[len(neg) // 2], 1) if neg else None}
