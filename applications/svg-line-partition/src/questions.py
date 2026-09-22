"""The judgment set: a fuzzy partition of a line drawing's initial conditions.

Design follows the TypeSafe practice, not a guess at it:

* one narrow snap judgment per question, combined in code afterwards;
* every question names its target with a backticked path into the state;
* Choice criteria carry `what` / `not_for` because the labels are confusable
  (a fence picket is both texture and outline);
* Score levels describe concrete situations and never numbers, because a level
  is judged on its own without seeing its neighbours;
* everything that shares a state is asked in one request, including the
  speculative questions whose answers only matter on some branches.

Two separate readings of "hierarchy" are asked side by side on purpose:
`scene_layer` (what a viewer reads as depth) and `nesting_layer` (how many
closed strokes contain this one). Only code can tell them apart afterwards.
"""

from __future__ import annotations

from typing import Any

from .serialize import vocabulary
from .svggeom import Drawing, Element

LAYERS = {
    "frame": {
        "what": "a mark that bounds the sheet itself rather than depicting anything",
        "not_for": "the farthest thing in the scene, or the surface things stand on",
    },
    "far": {
        "what": "part of the distant plane: things the rest of the drawing is arranged in front of",
        "not_for": "a large object close to the viewer, or the border of the sheet",
    },
    "mid": {
        "what": "the middle distance: ground or setting that main subjects rest against",
        "not_for": "sky or horizon material, and the subjects the eye lands on",
    },
    "near": {
        "what": "a main subject or object the drawing is about, drawn over other strokes",
        "not_for": "background, ground plane, or the sheet border",
    },
}

ROLES = {
    "object_outline": {
        "what": "a stroke that encloses or traces the silhouette of one object",
        "not_for": "a detail inside another outline, a repeated mark, or the ground",
    },
    "interior_detail": {
        "what": "a stroke that only makes sense inside a bigger outline of the same object",
        "not_for": "the outer boundary of anything, and repeated filler marks",
    },
    "repeated_texture": {
        "what": "one of several near-identical short strokes doing the same job",
        "not_for": "a unique boundary line, even a busy one",
    },
    "ground_plane_line": {
        "what": "a long stroke that establishes the surface or horizon things sit on",
        "not_for": "the outline of a single object, or the sheet border",
    },
    "border_frame": {
        "what": "a stroke whose only job is to bound the whole picture area",
        "not_for": "an edge of an object that happens to be long",
    },
}

REGIONS = {
    "top-left": "the upper-left ninth of the canvas",
    "top": "the upper middle ninth",
    "top-right": "the upper-right ninth",
    "left": "the middle-left ninth",
    "centre": "the very middle ninth",
    "right": "the middle-right ninth",
    "bottom-left": "the lower-left ninth",
    "bottom": "the lower middle ninth",
    "bottom-right": "the lower-right ninth",
    "spans-multiple": "too long or too large to be placed in a single ninth",
}

EXTENT_LEVELS = [
    "a small mark, barely a few points across",
    "a short local stroke, readable only near it",
    "a mid-sized stroke, one part of an object",
    "a large stroke that defines the extent of an object",
    "a stroke that runs across most of the whole picture",
]

STRUCTURE_LEVELS = [
    "erasing it changes nothing about what the drawing reads as",
    "a small decoration disappears, every object is still complete",
    "one object loses a part but is still recognisable",
    "a whole object disappears from the drawing",
    "the drawing loses its ground line or its border and falls apart",
]

NESTING_LEVELS = {
    "outside": "no closed stroke of the drawing contains it at all",
    "one": "exactly one closed stroke contains it",
    "two": "exactly two closed strokes contain it",
    "three-or-more": "three or more closed strokes contain it",
}


def _ref(index: dict[str, int], eid: str) -> str:
    """Point one question at one element of the serialized state."""
    return f"`state.elements[{index[eid]}]` (the element whose id is \"{eid}\")"


def element_index(state: dict[str, Any]) -> dict[str, int]:
    return {el["id"]: i for i, el in enumerate(state["elements"])}


def _mirror(facts: dict[str, Any]) -> dict[str, Any]:
    """Facts seen from the other end of the pair: `a` and `b` exchange roles."""
    return {**facts,
            "why": facts["why"] + " (handed over the other way round)",
            "a_order": facts["b_order"], "b_order": facts["a_order"],
            "a_painted_after_b": facts["b_painted_after_b"],
            "a_encloses_b": facts["b_encloses_a"],
            "b_encloses_a": facts["a_encloses_b"],
            "a_direct_front_of_b": facts["b_direct_front_of_a"],
            "b_direct_front_of_a": facts["a_direct_front_of_b"]}


def pair_candidates(drawing: Drawing) -> list[tuple[str, str, dict[str, Any]]]:
    """Pick element pairs that make a relation question answerable either way:
    each pair carries its oracle facts, positives and hard negatives alike."""
    from .svggeom import min_distance, segments_of, seg_intersect

    els = drawing.elements
    by_id = {e.eid: e for e in els}
    order = {e.eid: i for i, e in enumerate(els)}
    out: list[tuple[str, str, dict[str, Any]]] = []
    seen: set[frozenset[str]] = set()
    CAP = 24
    # distances once: the selection below asks for them rule after rule
    gap_of = {(a.eid, b.eid): min_distance(a.polys, b.polys)
              for i, a in enumerate(els) for b in els[i + 1:]}

    def gap(a: Element, b: Element) -> float:
        return gap_of.get((a.eid, b.eid), gap_of.get((b.eid, a.eid), 1e9))

    def add(a: Element, b: Element, why: str):
        key = frozenset((a.eid, b.eid))
        if a is b or key in seen or len(seen) >= CAP:
            return
        seen.add(key)
        crosses = any(seg_intersect(s0, s1, t0, t1)
                      for s0, s1 in segments_of(a.polys)
                      for t0, t1 in segments_of(b.polys))
        oa, ob = a.orientation, b.orientation
        par = (abs(oa - ob) % 180)
        par = min(par, 180 - par)
        out.append((a.eid, b.eid, {
            "why": why,
            "gap": round(gap(a, b), 1),
            "crosses": crosses,
            "parallel_deg": round(par, 1),
            "a_order": order[a.eid],
            "b_order": order[b.eid],
            # SVG paint order is document order: the later element is on top
            "a_painted_after_b": order[a.eid] > order[b.eid],
            "b_painted_after_b": order[b.eid] > order[a.eid],
            "a_encloses_b": a.eid in b.enclosers,
            "b_encloses_a": b.eid in a.enclosers,
            "same_object": bool(a.group and a.group == b.group),
            "a_direct_front_of_b": b.behind == a.eid,
            "b_direct_front_of_a": a.behind == b.eid,
            "any_occlusion_cue": bool(a.behind or b.behind),
        }))

    def take(why: str, keep, budget: int):
        """Fill a quota per relation kind instead of letting one kind eat the list:
        an earlier flat cap left the house scene with zero same-object pairs, so
        that relation had no positives to find at all."""
        start = len(out)
        for i, a in enumerate(els):
            for b in els[i + 1:]:
                if len(out) - start >= budget or len(out) >= CAP:
                    return
                if keep(a, b):
                    add(a, b, why)

    def encloses(a, b):
        return b.eid in a.enclosers or a.eid in b.enclosers

    def cue(a, b):
        return bool(b.behind == a.eid or a.behind == b.eid)

    # the authored break-in-stroke pairs are the only real depth-cue evidence in
    # these drawings and they are scarce, so they get first claim on the list
    take("occlusion cue", cue, 4)
    take("containment", encloses, 8)
    take("contact", lambda a, b: gap(a, b) < 5, 6)
    take("same-object near",
         lambda a, b: 5 <= gap(a, b) < 14 and a.group == b.group, 4)
    take("near different objects",
         lambda a, b: gap(a, b) < 60 and a.group != b.group, 3)
    # deliberate far-apart negative controls
    far = sorted(gap_of, key=lambda k: -gap_of[k])
    for a_eid, b_eid in far[:3]:
        add(by_id[a_eid], by_id[b_eid], "far apart")

    # Every candidate above lists the earlier element first, which silently makes
    # the directional facts one-class: "is the first painted after the second?"
    # could be passed by always answering no. Handing every other pair over the
    # other way round turns the ordering and containment questions into real
    # two-class tests. Fixed by position, so the grid stays reproducible.
    picked = [(b, a, _mirror(f)) if i % 2 else (a, b, f)
              for i, (a, b, f) in enumerate(out)]
    # "is the first the one in front?" is only answerable one way round, and a
    # blind half-flip can land every rare cue pair on the same side and erase the
    # positives: ask cue pairs in both directions instead of guessing a parity.
    have = {(a, b) for a, b, _ in picked}
    extra: list[tuple[str, str, dict[str, Any]]] = []
    for a, b, f in out:
        if not (f["a_direct_front_of_b"] or f["b_direct_front_of_a"]):
            continue
        for pair in ((a, b, f), (b, a, _mirror(f))):
            if (pair[0], pair[1]) not in have:
                have.add((pair[0], pair[1]))
                extra.append(pair)
    return picked + extra


def build_questions(drawing: Drawing, state: dict[str, Any],
                    pairs: list[tuple[str, str, dict[str, Any]]]) -> dict[str, Any]:
    """One question map for one (fixture, condition)."""
    idx = element_index(state)
    vocab = vocabulary(drawing)
    eids = [el["id"] for el in state["elements"]]
    # state elements keep fixture order, so this maps fixture ids to whatever
    # id the model sees (anonymised under features_anon)
    to_state = {e.eid: el["id"] for e, el in zip(drawing.elements, state["elements"])}
    qs: dict[str, Any] = {}

    for eid in eids:
        r = _ref(idx, eid)

        qs[f"scene_layer::{eid}"] = {
            "type": "choice",
            "instructions": {
                "question": f"Which depth plane of the depicted scene does {r} belong to?",
                "focus": "Judge where the stroke sits in the drawn world's depth, "
                         "using its position, size and what it surrounds.",
            },
            "criteria": dict(LAYERS),
        }
        qs[f"nesting_layer::{eid}"] = {
            "type": "choice",
            "instructions": f"Count only from the numbers in this state: how many closed elements of "
                            f"the drawing fully contain {r}?",
            "criteria": dict(NESTING_LEVELS),
        }
        qs[f"role::{eid}"] = {
            "type": "choice",
            "instructions": {
                "question": f"What job does {r} do in the drawing?",
                "focus": "The drawing is made of strokes only; ask what this stroke is for.",
            },
            "criteria": dict(ROLES),
        }
        qs[f"region::{eid}"] = {
            "type": "choice",
            "instructions": f"Which ninth of the canvas does {r} mainly occupy?",
            "criteria": dict(REGIONS),
        }
        qs[f"extent::{eid}"] = {
            "type": "score",
            "instructions": f"How much of the picture does {r} cover, judged by how far "
                            f"the stroke actually runs?",
            "criteria": list(EXTENT_LEVELS),
        }
        qs[f"structural_weight::{eid}"] = {
            "type": "score",
            "instructions": f"If {r} were erased, how much of the drawing's structure would be lost?",
            "criteria": list(STRUCTURE_LEVELS),
        }
        if len(vocab["objects"]) > 2:
            crit: dict[str, Any] = {}
            for obj in vocab["objects"]:
                crit[obj] = (f"the stroke belongs to {obj}" if obj != "none" else
                             "the stroke belongs to none of these groups")
            qs[f"group::{eid}"] = {
                "type": "choice",
                "instructions": {
                    "question": f"Which single thing in the drawing is {r} a part of?",
                    "focus": "Group by what the strokes make together, not by where they are.",
                },
                "criteria": crit,
            }

    for a, b, facts in pairs:
        sa, sb = to_state[a], to_state[b]
        ra, rb = _ref(idx, sa), _ref(idx, sb)
        qs[f"rel_same_object::{a}|{b}"] = {
            "type": "noul",
            "instructions": f"Do {ra} and {rb} belong to the same single thing in the drawing?",
            "criteria": {"true": "they are strokes of one object",
                         "false": "they belong to different things, or one is the sheet border"},
        }
        qs[f"rel_encloses::{a}|{b}"] = {
            "type": "noul",
            "instructions": f"Does {ra} fully contain {rb} inside its outline?",
            "criteria": {"true": "every point of the other stroke lies within it",
                         "false": "the other stroke is outside it or only crosses it"},
        }
        qs[f"rel_touches::{a}|{b}"] = {
            "type": "noul",
            "instructions": f"Do {ra} and {rb} meet or touch, with no visible gap between them?",
            "criteria": {"true": "they meet at a point or overlap",
                         "false": "there is a clear gap of white between them"},
        }
        qs[f"rel_crosses::{a}|{b}"] = {
            "type": "noul",
            "instructions": f"Do {ra} and {rb} cross each other's path?",
        }
        qs[f"rel_parallel::{a}|{b}"] = {
            "type": "noul",
            "instructions": f"Are {ra} and {rb} running in the same direction, parallel to each other?",
        }
        if facts["any_occlusion_cue"] or facts["crosses"]:
            qs[f"rel_in_front::{a}|{b}"] = {
                "type": "noul",
                "instructions": f"In {ra} crossing or meeting {rb}, is {ra} the one drawn in front?",
                "criteria": {"true": "the first stroke reads as continuous over the second",
                             "false": "the first is interrupted, or nothing says which is in front"},
            }
        if facts["crosses"]:
            qs[f"rel_depth_cue::{a}|{b}"] = {
                "type": "noul",
                "instructions": f"Does the state give any evidence at all about whether {ra} or {rb} "
                                f"is in front of the other?",
                "criteria": {"true": "a break, overlap or layering cue distinguishes them",
                             "false": "both strokes are unbroken, so the drawing is silent about depth"},
            }
        # speculative evidence check: code can use this to refuse to act on a
        # relation answer the state cannot support
        qs[f"rel_evidence::{a}|{b}"] = {
            "type": "noul",
            "instructions": f"Can the question of whether {ra} and {rb} touch, cross or run parallel "
                            f"be settled from this state at all?",
            "criteria": {
                "true": "the state carries the coordinates or measurements that decide it",
                "false": "the state names the strokes but carries no geometry to decide it",
            },
        }
        # SVG paints in document order, so the array position decides on top
        qs[f"rel_paint_order::{a}|{b}"] = {
            "type": "noul",
            "instructions": f"Listed in `state.elements` in the order a drawing program would paint "
                            f"them, is {ra} painted after {rb}, so that it lies on top of it?",
            "criteria": {"true": "the first one comes later in the list",
                         "false": "the first one comes earlier in the list"},
        }

    qs["gestalt_contains_figure"] = {
        "type": "noul",
        "instructions": "Does `state.elements` depict a person, animal or human-like figure?",
    }
    qs["gestalt_layer_count"] = {
        "type": "score",
        "instructions": "How many distinct depth planes does this drawing set up?",
        "criteria": [
            "one flat plane, no depth at all",
            "two planes, subjects against a background",
            "three planes, near, middle and far",
            "four or more planes with a border or extreme distance too",
        ],
    }
    qs["gestalt_axis"] = {
        "type": "choice",
        "instructions": "Which direction do most of the strokes in `state.elements` run?",
        "criteria": {
            "horizontal": "mostly left-to-right strokes",
            "vertical": "mostly up-and-down strokes",
            "diagonal": "mostly slanted strokes",
            "curved": "mostly curves, circles and arcs",
            "mixed": "no direction dominates",
        },
    }
    qs["gestalt_focal_region"] = {
        "type": "choice",
        "instructions": "Where does the eye land first in this drawing?",
        "criteria": {k: v for k, v in REGIONS.items() if k != "spans-multiple"},
    }
    return qs
