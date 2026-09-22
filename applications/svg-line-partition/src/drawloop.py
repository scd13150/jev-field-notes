"""Round three: judgment *inside* the drawing loop.

Rounds one and two judged a finished sheet. Here the questions are the ones an
author faces while the sheet is still open - which draft of this stroke do I
commit, which existing stroke is this one's partner, does the drawing still read
as containing what its names claim, which stroke does the pen lay down next.

What makes those testable without hand-labelling anything: **a wrong stroke can
be manufactured by code.** The real stroke plus a few semantic perturbations of
it is the same decision as "which curve do I commit", and it arrives with an
answer key and a 1/K baseline instead of a skewed majority class. Every family
below therefore reports the 1/K (or constant-answer) baseline next to accuracy,
and AUC wherever a class is rare.

  E1 pick_shape   drafts for one uncommitted stroke: which matches the intent?
  E2 pair_mate    one side is drawn: which existing stroke is its partner?
  E3 presence     a part is erased: does what remains still read as present?
  E4 spot_fault   one stroke was quietly redrawn wrong: which one?
  E5 next_stroke  the pen is at the end of a run: which stroke comes next?

The perturbations are the six ways a line actually goes wrong at the table:
bent the other way, straight where it should curve, too long, pushed off place,
flipped to the wrong side, kinked at a corner.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from .serialize import _feature_record
from .svggeom import (Drawing, Element, bbox_of, centroid, orientation_deg,
                      polyline_len, resample, turning_total)
from .traces import TRACE_FIXTURES, load, pen_travel, trace_ms

Point = tuple[float, float]
Polys = list[list[Point]]

FAMILIES = ("pick_shape", "pair_mate", "presence", "spot_fault", "next_stroke")
NONE_MATCH = "none-match"

# --------------------------------------------------------------------------- #
# a draft: a stroke made of points, with the same derived facts analyse() gives
# a real element, so `_feature_record` cannot tell them apart.
# --------------------------------------------------------------------------- #


@dataclass
class Draft:
    did: str
    tag: str
    polys: Polys
    length: float = 0.0
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    closed: bool = False
    turning: float = 0.0
    orientation: float = 0.0
    origin: str = ""

    def measure(self) -> "Draft":
        self.length = sum(polyline_len(p) for p in self.polys)
        self.bbox = bbox_of(self.polys)
        self.closed = any(len(p) > 3 and math.dist(p[0], p[-1]) < 1e-6
                          for p in self.polys)
        self.orientation = orientation_deg(self.polys)
        # same arc-length step the kernel uses, so turn_deg means one thing
        # across drafts and real strokes
        self.turning = turning_total(resample(self.polys))
        return self

    @property
    def record(self) -> dict[str, Any]:
        return _feature_record(self, self.did)


def _all(polys: Polys) -> list[Point]:
    return [p for poly in polys for p in poly]


def _densify(polys: Polys, step: float = 2.0) -> list[Point]:
    return [p for poly in resample(polys, step=step) for p in poly]


def shape_deviation(a: Polys, b: Polys) -> float:
    """Symmetric mean nearest-point distance in canvas points."""
    pa, pb = _densify(a), _densify(b)
    if not pa or not pb:
        return 0.0

    def near(src: list[Point], dst: list[Point]) -> float:
        return sum(min(math.dist(p, q) for q in dst) for p in src) / len(src)

    return round((near(pa, pb) + near(pb, pa)) / 2.0, 2)


# --------------------------------------------------------------------------- #
# perturbations: the six ways a drawn line is wrong
# --------------------------------------------------------------------------- #

def _reflect(p: Point, a: Point, b: Point) -> Point:
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = (dx * dx + dy * dy) or 1.0
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2
    return (2 * (a[0] + t * dx) - p[0], 2 * (a[1] + t * dy) - p[1])


def _scale_pts(polys: Polys, sx: float, sy: float | None = None) -> Polys:
    cx, cy = centroid(_all(polys))
    sy = sx if sy is None else sy
    return [[(cx + (x - cx) * sx, cy + (y - cy) * sy) for x, y in poly]
            for poly in polys]


def _rotate(polys: Polys, deg: float) -> Polys:
    pivot = polys[0][0]
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    return [[(pivot[0] + (x - pivot[0]) * ca - (y - pivot[1]) * sa,
              pivot[1] + (x - pivot[0]) * sa + (y - pivot[1]) * ca)
             for x, y in poly] for poly in polys]


def _mirror_x(polys: Polys) -> Polys:
    cx = centroid(_all(polys))[0]
    return [[(2 * cx - x, y) for x, y in poly] for poly in polys]


def _diag(polys: Polys) -> float:
    x0, y0, x1, y1 = bbox_of(polys)
    return math.hypot(x1 - x0, y1 - y0) or 1.0


# Every distortion is sized against the stroke's own extent. Fixed pixel amounts
# failed on the small marks: scaling a 20px mouth by 1.45 moves it ~1px, so the
# "wrong" draft was not a mistake anybody could see, let alone commit.
def _reach(polys: Polys, frac: float, floor: float, ceil: float) -> float:
    return max(floor, min(ceil, frac * _diag(polys)))


def _grow(polys: Polys, up: bool) -> Polys:
    need = _reach(polys, 0.3, 6.0, 26.0)
    if up:
        f = 1.0 + max(0.25, min(1.2, 2.0 * need / _diag(polys)))
    else:
        f = max(0.35, 1.0 - min(0.65, 2.0 * need / _diag(polys)))
    return _scale_pts(polys, f)


def _nudged(polys: Polys) -> Polys:
    d = _reach(polys, 0.35, 9.0, 30.0)
    return [[(x + d, y + d * 0.5) for x, y in poly] for poly in polys]


def _tilted(polys: Polys) -> Polys:
    move = _reach(polys, 0.25, 8.0, 30.0)
    deg = math.degrees(math.asin(min(0.5, move / _diag(polys))))
    return _rotate(polys, deg)


PERTURB: dict[str, Callable[[Polys], Polys]] = {
    # bend the other way about its own chord: a smile becomes a frown
    "flip_bulge": lambda ps: [[_reflect(p, poly[0], poly[-1]) for p in poly]
                              for poly in ps],
    # lose the curve entirely
    "straighten": lambda ps: [[poly[0], poly[-1]] for poly in ps],
    # right shape, wrong reach
    "overshoot": lambda ps: _grow(ps, True),
    "shrink": lambda ps: _grow(ps, False),
    # right shape, wrong side of the sheet
    "mirror_x": lambda ps: _mirror_x(ps),
    # slid off its anchor
    "shift": _nudged,
    # a corner put in where the line should run smooth
    "kink": lambda ps: [_kinked(poly) for poly in ps],
    # the free end lands elsewhere and the line is dragged after it
    "drift_end": lambda ps: [_drifted(poly) for poly in ps],
    "lean": _tilted,
}

PERTURB_NOTE = {
    "flip_bulge": "curvature reversed about its own chord",
    "straighten": "curve flattened to its chord",
    "overshoot": "scaled up about its centre",
    "shrink": "scaled down about its centre",
    "mirror_x": "flipped across its own vertical centre",
    "shift": "translated off its anchor",
    "kink": "a corner pushed into its midspan",
    "drift_end": "its free end moved and the line dragged after it",
    "lean": "rotated about its start",
}


def _kinked(poly: list[Point]) -> list[Point]:
    if len(poly) < 3:
        return poly
    i = len(poly) // 2
    ax, ay = poly[0]
    bx, by = poly[-1]
    dx, dy = bx - ax, by - ay
    l = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / l, dx / l
    out = list(poly)
    span = math.dist(poly[0], poly[-1]) or 1.0
    amp = max(6.0, min(20.0, 0.18 * span))
    for k in range(len(out)):
        w = math.sin(math.pi * k / max(1, len(out) - 1)) ** 2
        d = amp * (1.0 if k >= i else -1.0) * w
        out[k] = (out[k][0] + nx * d, out[k][1] + ny * d)
    return out


def _drifted(poly: list[Point]) -> list[Point]:
    if len(poly) < 2:
        return poly
    out = list(poly)
    n = len(out)
    ax, ay = out[0]
    span = math.dist(poly[0], poly[-1]) or 1.0
    reach = max(6.0, min(25.0, 0.3 * span))
    for k in range(n):
        w = (k / (n - 1)) ** 2
        vx, vy = out[k][0] - ax, out[k][1] - ay
        l = math.hypot(vx, vy) or 1.0
        out[k] = (out[k][0] + vx / l * reach * w, out[k][1] + vy / l * reach * w)
    return out


def _seed(*parts: Any) -> int:
    """`hash()` is salted per process, which would make every run draw a different
    candidate set: the shuffles have to be reproducible to be auditable."""
    return int(hashlib.md5("|".join(str(x) for x in parts).encode()).hexdigest()[:8], 16)


MIN_DEV = 2.5   # a perturbation that moves nothing is not a candidate
MAX_DEV = 120.0  # ... and one that shreds the stroke is not a drawing error
MAX_WRONG_DRAFTS = 6


def visibility_floor(diag: float) -> float:
    """How far a draft must move to be a mistake an eye could catch.

    An absolute threshold was wrong: 2px flattens the expression of a 20px mouth
    and vanishes on a 146px roof, so the floor has to ride on the stroke's own
    extent - and be capped, or nothing counts as misplaced on a big mark."""
    return max(2.0, 0.10 * diag)


def live_perturbations(e: Element, cap: int = MAX_WRONG_DRAFTS
                       ) -> list[tuple[str, float]]:
    """Which mistakes this particular stroke can carry.

    Authored per-stroke perturbation lists were a failure: on a nearly flat arc
    the curvature reversal moves the line 2.5px, so the 'wrong' draft was
    indistinguishable from the right one. The kernel picks the perturbations
    that actually move this stroke, and prefers the subtle ones - a gross
    distortion is not a decision an artist faces.
    """
    floor = visibility_floor(_diag(e.polys))
    out: list[tuple[str, float]] = []
    for kind, fn in PERTURB.items():
        trial = fn([list(p) for p in e.polys])
        dev = shape_deviation(e.polys, trial)
        if floor <= dev <= MAX_DEV:
            out.append((kind, dev))
    out.sort(key=lambda t: t[1])
    return out[:cap]


def make_drafts(e: Element, kinds: list[str], seed: int) -> list[Draft]:
    """The true stroke plus the given perturbations, each of which was already
    checked to move this stroke by a visible amount.

    Ids are renumbered after the shuffle: naming the true one `true`, or a wrong
    one `d-flip_bulge`, would put the answer key in the option labels.
    """
    out = [Draft("true", e.tag, [list(p) for p in e.polys], origin="true").measure()]
    for kind in kinds:
        d = Draft(kind, e.tag, PERTURB[kind]([list(p) for p in e.polys]),
                  origin=kind).measure()
        out.append(d)
    rng = random.Random(seed)
    rng.shuffle(out)
    for i, d in enumerate(out):
        d.did = f"d-{i + 1:02d}"
    return out


# --------------------------------------------------------------------------- #
# tasks
# --------------------------------------------------------------------------- #

@dataclass
class Task:
    key: str
    family: str
    fixture: str
    state: dict[str, Any]
    questions: dict[str, Any]
    truth: dict[str, str]
    meta: dict[str, Any] = field(default_factory=dict)


def _state_shell(drawing: Drawing, task_note: str) -> dict[str, Any]:
    return {
        "canvas": {"width": int(drawing.width), "height": int(drawing.height)},
        "coordinate_note": ("x grows rightward, y grows downward, in canvas points. "
                            "The picture is line art: every entry is one stroke the "
                            "pen laid down, no fills."),
        "view_note": "left and right name the viewer's sides.",
        "task_note": task_note,
    }


def _intent_q(intent: str, drafts: list[Draft], subject: str) -> dict[str, Any]:
    crit = {d.did: {"what": f"the draft at `state.drafts[{i}]` (id \"{d.did}\")",
                    "not_for": "any other draft offered here"}
            for i, d in enumerate(drafts)}
    crit[NONE_MATCH] = {"what": "every draft offered breaks the description",
                        "not_for": "a draft that satisfies it"}
    return {
        "type": "choice",
        "instructions": {
            "question": f"{subject} is to be drawn as follows: {intent} "
                        f"Which single draft is that mark?",
            "focus": "Test each draft against every clause of the description. A "
                     "draft that satisfies most clauses but breaks one is not it. "
                     "Where the description says a mark must sit relative to "
                     "another mark, read the coordinates of that other mark out of "
                     "`state.strokes`.",
        },
        "criteria": crit,
    }


# ---- E1 ------------------------------------------------------------------- #
# One uncommitted stroke per task: the true stroke is *removed* from the sheet
# so no draft can be matched against a given-away answer.
#
# The descriptions are authored here, in the language an author actually thinks
# in - what the mark is for and how it must sit - not a listing of its points.

SHAPE_TARGETS: list[dict[str, Any]] = [
    {"f": "trace_stick", "eid": "mouth",
     "intent": "the mouth of the figure, one open arc under the middle of the head, "
               "wide enough to read as a face but never reaching the head outline; "
               "it curves downward in the middle, so its two ends sit higher than "
               "its centre",},
    {"f": "trace_stick", "eid": "scarf",
     "intent": "a scarf drawn across the front of the shoulders below the head: it "
               "runs from the figure's left shoulder to the right, sags gently "
               "downward through the middle, and finishes at its right end with a "
               "small flick that drops",},
    {"f": "trace_stick", "eid": "hand-l",
     "intent": "the figure's left hand, a short two-segment mark hanging off the end "
               "of the left arm: the first segment runs down and away from the body, "
               "the second turns back underneath, and the whole mark is barely wider "
               "than the head",},
    {"f": "trace_stick", "eid": "hair-1",
     "intent": "one strand of hair at the top-left of the head, drawn as a short "
               "curve that lifts away from the skull toward the upper right, its "
               "upper end thinner and farther right than its lower end",},
    {"f": "trace_house_interleaved", "eid": "smoke-1",
     "intent": "a ribbon of smoke leaving the top of the chimney: it climbs, bends "
               "over to one side in its upper half and back the other way below, so "
               "the mark changes which way it curves partway up",},
    {"f": "trace_house_interleaved", "eid": "wall-crack",
     "intent": "a crack in the front wall, standing just left of the door: it starts "
               "low, jogs once to the side on the way up, and ends higher than it "
               "starts while staying inside the wall rectangle",},
    {"f": "trace_house_interleaved", "eid": "roof",
     "intent": "the roof of the house: a closed gable sitting on the top edge of the "
               "front wall, its peak near the middle of the wall's width and its two "
               "eaves reaching a little past the wall on either side",},
    {"f": "trace_house_interleaved", "eid": "grass-1",
     "intent": "a tuft of grass standing on the ground line just right of the door: "
               "two short strokes rising from one low point to a peak between them, "
               "so the mark is highest in its middle and open at the top",},
    {"f": "trace_cat_decor", "eid": "tail",
     "intent": "the cat's tail leaving its rear: it starts low near the body, sweeps "
               "out to the right and up, and the top of the mark curls back over, so "
               "the whole thing is much taller than it is wide",},
    {"f": "trace_cat_decor", "eid": "ear-left",
     "intent": "the cat's ear on the viewer's left: a closed triangle sitting on the "
               "upper-left of the head, its apex pointing up and slightly outward, "
               "no wider than a third of the head",},
    {"f": "trace_cat_decor", "eid": "fly-wing",
     "intent": "the wing of the fly hovering at the upper right of the sheet: a small "
               "arc held above its body, bowed upward, about as wide as the body it "
               "sits over",},
]


def build_pick_shape(seed0: int = 7001) -> list[Task]:
    tasks: list[Task] = []
    for n, spec in enumerate(SHAPE_TARGETS):
        d = load(spec["f"])
        e = d.by_id(spec["eid"])
        live = live_perturbations(e)
        if len(live) < 3:
            continue
        drafts = make_drafts(e, [k for k, _ in live], seed0 + n)
        others = [x for x in d.elements if x.eid != spec["eid"]]
        state = _state_shell(d, "one mark of this sheet is still undecided; "
                                 "`state.drafts` holds the candidate shapes for it")
        state["strokes"] = [_feature_record(x, x.eid) for x in others]
        state["drafts"] = [x.record for x in drafts]
        qid = f"pick_shape::{spec['f']}::{spec['eid']}"
        tasks.append(Task(
            key=qid, family="pick_shape", fixture=spec["f"], state=state,
            questions={qid: _intent_q(spec["intent"], drafts,
                                      f"The mark being drawn is `{spec['eid']}`")},
            truth={qid: next(x.did for x in drafts if x.origin == "true")},
            meta={"target": spec["eid"], "intent": spec["intent"],
                  "drafts": [{"did": x.did, "origin": x.origin,
                              "dev": shape_deviation(e.polys, x.polys),
                              "len": round(x.length, 1),
                              "turn": round(x.turning),
                              "bbox": [round(v) for v in x.bbox]} for x in drafts],
                  "k": len(drafts), "live": [k for k, _ in live],
                  "floor": round(visibility_floor(_diag(e.polys)), 2)}))
    return tasks


# ---- E2 ------------------------------------------------------------------- #
# Partner lookup: the left half exists, the assistant must point at the mark on
# the right that belongs with it. Distractors are same-kind marks from the other
# side, so only shape and placement separate them.

PAIR_SIDES = (("-left", "-right"), ("-l", "-r"))


def pair_partners(d: Drawing) -> list[tuple[Element, Element]]:
    out: list[tuple[Element, Element]] = []
    for e in d.elements:
        for suf_a, suf_b in PAIR_SIDES:
            if e.eid.endswith(suf_a):
                mate = next((x for x in d.elements
                             if x.eid == e.eid[:-len(suf_a)] + suf_b), None)
                if mate is not None:
                    out.append((e, mate))
    return out


def _partner_pool(d: Drawing, mate: Element, skip: Element,
                  cap: int = 5) -> list[Element]:
    """Marks similar enough in kind and reach to be mistaken for the partner -
    the confusable set is what makes this a judgment rather than a lookup.
    `skip` is the query stroke itself: it is on the wrong side by construction,
    and offering it would let a copy of the geometry pass as an answer."""
    peers = [x for x in d.elements if x is not skip
             if x.tag == mate.tag and mate.length / 3.0 <= x.length <= mate.length * 3.0]
    if len(peers) < 2:
        peers = [x for x in d.elements if x is not skip
                 if mate.length / 3.0 <= x.length <= mate.length * 3.0]
    out = [mate] + [x for x in peers if x is not mate]
    return out[:cap]


def build_pair_mate() -> list[Task]:
    tasks: list[Task] = []
    for name in TRACE_FIXTURES:
        d = load(name)
        for a, b in pair_partners(d):
            opts = _partner_pool(d, b, a)
            if len(opts) < 3:
                continue
            rng = random.Random(_seed("pair", name, a.eid))
            rng.shuffle(opts)
            # the query is shown without its id: `whisker-l1` -> `whisker-r1` is
            # a string analogy, not a reading of the drawing
            state = _state_shell(d, "the artist has drawn both sides of the subject "
                                     "and wants to know which marks pair up")
            state["mystery_note"] = ("`state.mystery` is one mark lifted off this "
                                     "sheet without its label; its geometry is "
                                     "unchanged")
            state["mystery"] = _feature_record(a, "mystery")
            # the query must not still be on the sheet under its own name
            state["strokes"] = [_feature_record(x, x.eid)
                               for x in d.elements if x is not a]
            qid = f"pair_mate::{name}::{a.eid}"
            crit = {x.eid: {"what": f"the stroke `{x.eid}` listed in `state.strokes`",
                            "not_for": "any other stroke listed here"}
                    for x in opts}
            crit[NONE_MATCH] = {"what": "no stroke in this state is its partner",
                                "not_for": "a stroke that is"}
            tasks.append(Task(
                key=qid, family="pair_mate", fixture=name, state=state,
                questions={qid: {
                    "type": "choice",
                    "instructions": {
                        "question": "`state.mystery` is one side of a paired part of "
                                    "the subject. Which single stroke in "
                                    "`state.strokes` is that same part drawn on the "
                                    "opposite side - the mark a rigger would move "
                                    "together with it?",
                        "focus": "A partner does the same job at roughly the same "
                                 "size and reach, mirrored across the middle of the "
                                 "subject. Decide what `state.mystery` depicts from "
                                 "where it sits and what it bounds, then look for the "
                                 "mark doing that job on the other side. A neighbouring "
                                 "mark of the opposite side that does a different job "
                                 "is not the partner.",
                    },
                    "criteria": crit}},
                truth={qid: b.eid},
                meta={"a": a.eid, "b": b.eid, "pool": [x.eid for x in opts],
                      "k": len(opts),
                      "travel_free": True}))
    return tasks


# ---- E3 ------------------------------------------------------------------- #
# Presence readback: erase one structural mark set and ask, part by part, what
# the sheet still reads as having. Truth for a word is exact - it is whether any
# stroke carrying that part survives - so the interesting quantity is how far
# the probabilities of the *surviving* siblings move when their anchor goes.

PRESENCE_ERASE = {
    # two parts go, so `false` is not a rounding error in the truth distribution
    "trace_stick": ["torso", "ground"],
    "trace_house_interleaved": ["wall", "roof"],
    "trace_cat_decor": ["body", "tail"],
}

PRESENCE_GLOSS = {
    "torso": "the trunk of the figure: the body the limbs and head attach to",
    "wall": "the front wall of the house: the big face the door and window sit in",
    "body": "the cat's body: the mass the legs, tail and head come off",
    "ground": "the ground: the line or surface the subject stands on",
    "roof": "the roof of the house: the covering above the walls",
    "tail": "the cat's tail: the limb sweeping out behind the body",
}


def part_words(d: Drawing) -> list[str]:
    return sorted({e.truth.get("part", "") for e in d.elements} - {"", "none"})


def build_presence() -> list[Task]:
    tasks: list[Task] = []
    for name in TRACE_FIXTURES:
        d = load(name)
        gone = PRESENCE_ERASE[name]
        for cond in ("intact", "erased"):
            kept = [e for e in d.elements
                    if not (cond == "erased" and e.truth.get("part") in gone)]
            state = _state_shell(d, "the sheet is work in progress; the artist wants "
                                     "to know what it already reads as having")
            state["vocabulary"] = part_words(d)
            state["strokes"] = [_feature_record(x, x.eid) for x in kept]
            qs: dict[str, Any] = {}
            truth: dict[str, str] = {}
            present = {e.truth.get("part", "") for e in kept}
            for w in part_words(d):
                qid = f"presence::{cond}::{name}::{w}"
                qs[qid] = {
                    "type": "noul",
                    "instructions": f"This sheet of line art contains at least one "
                                    f"mark of {PRESENCE_GLOSS.get(w, w)} (the parts "
                                    f"named in `state.vocabulary`), judged from what "
                                    f"is drawn here and nothing else.",
                    "criteria": {"true": "some stroke in `state.strokes` depicts it",
                                 "false": "nothing drawn here depicts it"},
                }
                truth[qid] = "true" if w in present else "false"
            tasks.append(Task(
                key=f"presence::{cond}::{name}", family="presence", fixture=name,
                state=state, questions=qs, truth=truth,
                meta={"cond": cond, "erased": gone, "n_strokes": len(kept)}))
    return tasks


# ---- E4 ------------------------------------------------------------------- #
# One stroke quietly redrawn wrong. Features are recomputed from the corrupted
# points, so the state stays self-consistent: the task is to notice that a mark
# no longer depicts what its name says, not to catch an arithmetic contradiction.

FAULT_KINDS = ("flip_bulge", "straighten", "overshoot", "mirror_x", "kink",
               "drift_end", "lean")
# which marks can carry which fault and still be a plausible mistake a hand makes
FAULT_MIN_LEN = 20.0


def build_spot_fault(seed0: int = 4401) -> list[Task]:
    tasks: list[Task] = []
    for name in TRACE_FIXTURES:
        d = load(name)
        cands = [e for e in d.elements if e.length >= FAULT_MIN_LEN]
        for kind in FAULT_KINDS:
            rng = random.Random(_seed("fault", seed0, name, kind))
            order = sorted(cands, key=lambda e: (rng.random(), e.eid))
            victim, new_polys, dev = None, None, 0.0
            for cand in order:
                trial = PERTURB[kind]([list(p) for p in cand.polys])
                dv = shape_deviation(cand.polys, trial)
                if MIN_DEV <= dv <= MAX_DEV:
                    victim, new_polys, dev = cand, trial, dv
                    break
            if victim is None:
                continue
            state = _state_shell(d, "a finished sheet that may carry one stroke "
                                     "redrawn out of step with what it is meant "
                                     "to depict")
            recs = []
            for x in d.elements:
                if x.eid == victim.eid:
                    dr = Draft(x.eid, x.tag, new_polys, origin="fault").measure()
                    recs.append(dr.record)
                else:
                    recs.append(_feature_record(x, x.eid))
            state["strokes"] = recs
            ids = [x.eid for x in d.elements]
            crit = {i: {"what": f"the stroke `{i}`", "not_for": "any other stroke"}
                    for i in ids}
            crit[NONE_MATCH] = {"what": "every stroke matches the name it carries",
                                "not_for": "a stroke that contradicts its name"}
            qs: dict[str, Any] = {
                f"spot_choice::{name}::{kind}": {
                    "type": "choice",
                    "instructions": {
                        "question": "At most one stroke on this sheet no longer "
                                    "depicts the thing its id names. Which one?",
                        "focus": "Compare each stroke's shape, reach and position "
                                 "with what its name has to be. Where two ids say "
                                 "left and right, read which side of the subject "
                                 "each mark is actually on.",
                    },
                    "criteria": crit}}
            truth: dict[str, str] = {f"spot_choice::{name}::{kind}": victim.eid}
            for sid in ids:
                qid = f"spot_noul::{name}::{kind}::{sid}"
                qs[qid] = {
                    "type": "noul",
                    "instructions": f"The stroke `{sid}` on this sheet no longer "
                                    f"depicts the thing its own id names.",
                    "criteria": {"true": "its shape, reach or side contradicts that "
                                         "name",
                                 "false": "it is consistent with what its id names"},
                }
                truth[qid] = "true" if sid == victim.eid else "false"
            tasks.append(Task(
                key=f"spot_fault::{name}::{kind}", family="spot_fault", fixture=name,
                state=state, questions=qs, truth=truth,
                meta={"victim": victim.eid, "kind": kind, "dev": dev,
                      "note": PERTURB_NOTE[kind], "n": len(ids)}))
    return tasks


# ---- E5 ------------------------------------------------------------------- #
# Sequencing. The prefix is what the assistant can see; candidates are the true
# next stroke plus nearer-to-the-pen-tip strokes, so the pen-travel rule has to
# be beaten rather than merely equalled. `shuffled_prefix` removes the working
# rhythm so the two readings can be told apart.

CHECKPOINTS = (5, 9, 13, 17)
K_NEXT = 5


def build_next_stroke() -> list[Task]:
    tasks: list[Task] = []
    for name in TRACE_FIXTURES:
        d = load(name)
        seq = sorted(d.elements, key=trace_ms)
        for i in CHECKPOINTS:
            if i + 1 >= len(seq):
                continue
            drawn, nxt = seq[:i], seq[i]
            rest = seq[i + 1:]
            tip = drawn[-1]
            by_travel = sorted(rest, key=lambda x: pen_travel(tip, x))
            near = [x for x in by_travel[:3] if x is not nxt]
            far = [x for x in by_travel[-2:]]
            opts, seen = [], set()
            for x in [nxt] + near + far:
                if x.eid not in seen:
                    seen.add(x.eid)
                    opts.append(x)
            if len(opts) > K_NEXT:
                opts = opts[:K_NEXT]
            if nxt not in opts:
                continue
            rng = random.Random(_seed("next", name, i))
            rng.shuffle(opts)
            for cond in ("seen_order", "shuffled_prefix"):
                pre = list(drawn) if cond == "seen_order" else \
                    sorted(drawn, key=lambda e: (round(e.centroid[1]), e.eid))
                state = _state_shell(d, "the artist is mid-session and has not "
                                         "decided what the pen draws next")
                if cond == "shuffled_prefix":
                    state["order_note"] = ("`state.drawn` is listed by position on "
                                           "the sheet, which says nothing about the "
                                           "order the marks were made in")
                state["drawn"] = [_feature_record(x, x.eid) for x in pre]
                state["pen_tip"] = {"inside_drawn": len(pre) - 1,
                                    "x": round(tip.polys[-1][-1][0]),
                                    "y": round(tip.polys[-1][-1][1])}
                state["pending"] = [_feature_record(x, x.eid) for x in opts]
                qid = f"next_stroke::{cond}::{name}::{i}"
                crit = {x.eid: {"what": f"the pending mark `{x.eid}`",
                                "not_for": "any other pending mark"}
                        for x in opts}
                crit[NONE_MATCH] = {"what": "none of the pending marks is what the "
                                            "pen does next", "not_for": "a mark "
                                            "that is"}
                tasks.append(Task(
                    key=qid, family="next_stroke", fixture=name, state=state,
                    questions={qid: {
                        "type": "choice",
                        "instructions": {
                            "question": "Given the marks already on the sheet and "
                                        "where the pen lifted off, which single "
                                        "pending mark is the one drawn next?",
                            "focus": "Work out what the drawing still needs in "
                                     "order to hold together, and what an artist "
                                     "would reach for next from where the pen is.",
                        },
                        "criteria": crit}},
                    truth={qid: nxt.eid},
                    meta={"cond": cond, "i": i, "next": nxt.eid,
                          "opts": [x.eid for x in opts],
                          "travel": {x.eid: round(pen_travel(tip, x), 1)
                                     for x in opts},
                          "truth_rank_by_travel": next(
                              k for k, x in enumerate(sorted(
                                  opts, key=lambda y: pen_travel(tip, y)))
                              if x is nxt)}))
    return tasks


# --------------------------------------------------------------------------- #

def build_tasks(families: tuple[str, ...] = FAMILIES) -> list[Task]:
    out: list[Task] = []
    if "pick_shape" in families:
        out += build_pick_shape()
    if "pair_mate" in families:
        out += build_pair_mate()
    if "presence" in families:
        out += build_presence()
    if "spot_fault" in families:
        out += build_spot_fault()
    if "next_stroke" in families:
        out += build_next_stroke()
    return out


def check_leaks(task: Task) -> list[str]:
    """The answer key must not ride along in the state."""
    problems: list[str] = []
    blob = repr(task.state)
    if "data-truth" in blob or "truth" in blob:
        problems.append("truth field")
    if "trace_ms" in blob:
        problems.append("pen times present")
    if task.family == "pick_shape":
        ids = {r["id"] for r in task.state["strokes"]}
        for r in task.state["drafts"]:
            if r["id"] in ids:
                problems.append(f"draft id {r['id']} also a drawn stroke")
        # the stroke being decided on must be absent from the sheet
        if task.meta["target"] in ids:
            problems.append("target stroke left in the sheet")
    return problems
