"""Serialize a parsed drawing into the text states Jev is given.

Jev takes text only, so an SVG has to be written out as coordinates and
measurements. Which writing you use decides what the model can possibly know,
so this module offers several deliberately different ones and a leak check that
proves no answer key rides along.

Conditions
  features_named  computed low-level geometry + real ids + the <g> tree
  features_anon   the same geometry, anonymous ids, no groups, no names
  named_nogeo     ids, tags and group names only, every number removed
  raw_paths       the literal authored attributes (d="M...", cx=...) and ids
  scrambled       real ids and names, geometry taken from other elements

Only *low-level* facts go in: coordinates, length, bbox, closed, turning.
Derived notions (enclosure depth, region cell, layer, role, grouping) are what
the questions ask for, so they stay out of the state.
"""

from __future__ import annotations

import copy
import random
from typing import Any

from .svggeom import Drawing, Element

CONDITIONS = (
    "features_named",
    "features_anon",
    "named_nogeo",
    "raw_paths",
    "scrambled",
)

# words that belong to the answer key; never allowed in a serialized state
LEAK_TOKENS = (
    "data-truth",
    "encloser",
    "repeated_texture",
    "ground_plane_line",
    "border_frame",
    "interior_detail",
    "object_outline",
    "top-left",
    "bottom-right",
    "family-",
    "spans-multiple",
    # opaque cluster labels used by the abstract fixture: element ids there are
    # n-01..n-21, so any of these appearing in a state means a leak
    "g-frame", "g-nest", "g-twin", "g-cross", "g-hatch", "g-rings",
    "g-wavy", "g-bracket", "g-bump", "g-base",
)


def _skeleton(e: Element, max_pts: int = 8) -> list[list[int]]:
    """A few corner points per subpath: enough to place a stroke, small enough
    to keep the state cheap."""
    out = []
    for poly in e.polys:
        if len(poly) <= max_pts:
            pts = list(poly)
        else:
            idx = sorted({round(i * (len(poly) - 1) / (max_pts - 1)) for i in range(max_pts)})
            pts = [poly[i] for i in idx]
        out.append([[int(round(x)), int(round(y))] for x, y in pts])
    return out


def _feature_record(e: Element, eid: str) -> dict[str, Any]:
    x0, y0, x1, y1 = e.bbox
    return {
        "id": eid,
        "kind": e.tag,
        "points": _skeleton(e),
        "stroke_length": int(round(e.length)),
        "bbox": [int(round(v)) for v in (x0, y0, x1, y1)],
        "closed": bool(e.closed),
        "turn_deg": int(round(e.turning)),
        "orientation_deg": int(round(e.orientation)),
    }


def _raw_record(e: Element, eid: str) -> dict[str, Any]:
    keep = {k: v for k, v in e.attrs.items() if k not in ("id", "data-truth")}
    keep.pop("style", None)
    keep.pop("transform-origin", None)
    out: dict[str, Any] = {"id": eid, "kind": e.tag}
    if "transform" in keep:
        out["transform"] = keep.pop("transform")
    out.update({k: v for k, v in keep.items() if k != "fill"})
    return out


def _anon(drawing: Drawing) -> dict[str, str]:
    return {e.eid: f"e{i + 1:02d}" for i, e in enumerate(drawing.elements)}


def state_ids(drawing: Drawing, condition: str) -> dict[str, str]:
    """Map the id the model sees back to the fixture element it came from."""
    ids = _anon(drawing) if condition == "features_anon" else \
        {e.eid: e.eid for e in drawing.elements}
    return {v: k for k, v in ids.items()}


def _group_tree(drawing: Drawing, ids: dict[str, str]) -> dict[str, Any]:
    """The authored <g> nesting: one notion of hierarchy, independent of space."""
    root: dict[str, Any] = {"name": "canvas", "children": [], "elements": []}
    index: dict[tuple[str, ...], dict[str, Any]] = {(): root}
    for e in drawing.elements:
        chain: tuple[str, ...] = ()
        for part in e.group_path:
            parent = index[chain]
            chain = chain + (part,)
            if chain not in index:
                node: dict[str, Any] = {"name": part, "children": [], "elements": []}
                index[chain] = node
                parent["children"].append(node)
        index[chain]["elements"].append(ids[e.eid])
    return root


def build_state(drawing: Drawing, condition: str) -> dict[str, Any]:
    """Return the `state` object for one request under one condition."""
    d = copy.deepcopy(drawing)
    ids = {e.eid: e.eid for e in d.elements}
    show_geo = condition in ("features_named", "features_anon", "scrambled")
    show_raw = condition == "raw_paths"
    show_names = condition in ("features_named", "named_nogeo", "raw_paths", "scrambled")

    if condition == "features_anon":
        ids = _anon(d)

    if condition == "scrambled":
        # permute the geometry between elements; identities and names stay put
        rng = random.Random(20260920)
        records = [_feature_record(e, ids[e.eid]) for e in d.elements]
        bodies = [({k: v for k, v in r.items() if k != "id"}) for r in records]
        rng.shuffle(bodies)
        elements = [dict({"id": rec["id"]}, **body) for rec, body in zip(records, bodies)]
    else:
        elements = []
        for e in d.elements:
            if show_geo:
                elements.append(_feature_record(e, ids[e.eid]))
            elif show_raw:
                elements.append(_raw_record(e, ids[e.eid]))
            else:  # named_nogeo
                elements.append({"id": ids[e.eid], "kind": e.tag})

    state: dict[str, Any] = {
        "canvas": {"width": int(d.width), "height": int(d.height)},
        "coordinate_note": "x grows rightward, y grows downward, units are canvas "
                           "points; a line drawing where every element is a stroke "
                           "with no fill",
    }
    if condition in ("features_named", "named_nogeo", "scrambled") and show_names:
        state["groups"] = _group_tree(d, ids)
    elif condition == "raw_paths":
        state["groups"] = _group_tree(d, ids)
    state["elements"] = elements
    if not show_names:
        state["note"] = "element ids are arbitrary labels and carry no meaning"
    return state


def vocabulary(drawing: Drawing) -> dict[str, list[str]]:
    """Answer-set vocabulary taken from the fixture, for Choice criteria."""
    objects = sorted({e.object_ for e in drawing.elements if e.object_})
    return {
        "layers": ["frame", "far", "mid", "near"],
        "roles": ["object_outline", "interior_detail", "repeated_texture",
                  "ground_plane_line", "border_frame"],
        "regions": ["top-left", "top", "top-right", "left", "centre", "right",
                    "bottom-left", "bottom", "bottom-right", "spans-multiple"],
        "objects": objects + ["none"],
    }


def extent_bin(ratio: float) -> int:
    """Key for the graded extent Score: stroke length over canvas diagonal."""
    for i, hi in enumerate((0.06, 0.18, 0.42, 0.80)):
        if ratio <= hi:
            return i
    return 4


def structure_bin(raw: int) -> int:
    """Key for the structural-weight Score, from the additive rule below."""
    return min(4, raw)


def _structure_raw(e: Element, encloses_others: bool) -> int:
    """+2 border or ground line, +1 not part of a repeated family,
    +2 other closed strokes sit inside it. Documented, so the target is exact."""
    s = 0
    if e.role in ("border_frame", "ground_plane_line"):
        s += 2
    if not e.family:
        s += 1
    if encloses_others:
        s += 2
    return s


def truth_of(drawing: Drawing) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    diag = (drawing.width ** 2 + drawing.height ** 2) ** 0.5
    contains: set[str] = set()
    for e in drawing.elements:
        contains.update(e.enclosers)
    for e in drawing.elements:
        cells = {region_of_cell(e, drawing, cx, cy)
                 for cx, cy in [(0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75),
                                (0.5, 0.5)]}
        span = len(cells) > 2
        ratio = e.length / diag if diag else 0.0
        out[e.eid] = {
            "layer": e.layer,
            "role": e.role,
            "object": e.object_ or "none",
            "region": "spans-multiple" if span else e.region,
            "depth": e.enclosure_depth,
            "nesting": {0: "outside", 1: "one", 2: "two"}.get(e.enclosure_depth,
                                                              "three-or-more"),
            "behind": e.behind,
            "family": e.family,
            "extent": round(ratio, 3),
            "extent_bin": extent_bin(ratio),
            "structure_bin": structure_bin(_structure_raw(e, e.eid in contains)),
            "group_depth": e.depth,
        }
    return out


def region_of_cell(e: Element, drawing: Drawing, fx: float, fy: float) -> str:
    x = e.bbox[0] + (e.bbox[2] - e.bbox[0]) * fx
    y = e.bbox[1] + (e.bbox[3] - e.bbox[1]) * fy
    from .svggeom import region_of
    return region_of((x, y), drawing.width, drawing.height)


def leak_check(state: dict[str, Any]) -> list[str]:
    """Prove no oracle-derived answer key rides along in a request.

    Fixture element and group *names* are visible on purpose under the naming
    conditions - that is the variable the ablation measures. Every fact the
    geometry oracle derived is withheld.
    """
    blob = repr(state)
    leaks = [tok for tok in LEAK_TOKENS if tok in blob]
    for key in ("enclosers", "region", "layer", "role", "family", "truth",
                "object_", "enclosure_depth", "behind"):
        if f"'{key}'" in blob or f'"{key}"' in blob:
            leaks.append(f"field:{key}")
    return sorted(set(leaks))


def serialize(drawing: Drawing, condition: str) -> dict[str, Any]:
    state = build_state(drawing, condition)
    leaks = leak_check(state)
    if leaks:
        raise AssertionError(f"{condition}: answer key leaked into state: {leaks}")
    return state
