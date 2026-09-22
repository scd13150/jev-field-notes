"""Run round four: plan, candidate grid, judgment, commit - then look at it.

    python -m src.run_jvdrawing --check                # offline, no calls, nothing sent
    python -m src.run_jvdrawing --input facts          # one request per mark -> drawwith/
    python -m src.run_jvdrawing --input both           # the two input conditions side by side

Nothing here asks Jev to invent a mark. Code enumerates the grid of realisations
of my recipe, offers a handful around my own, and Jev picks. Because the chosen
numbers feed the next mark's geometry, the face is placed by the head it chose,
which is placed by the back it chose.

`--input points` is the first pass: the candidates went in as point lists with a
sentence of note, and the returned distribution was close to a coin flip among
six. `--input facts` puts the arithmetic in the state instead - the knob values,
what code measured from each shape, how it sits against the marks already on the
page - splits the note into clauses, and asks one verification question per
clause per candidate alongside the pick. Same plan, same candidates, same
scoring; only what went in differs.

The pick stays a forced choice with no `none-match`: round three measured that an
open "is anything wrong here" frame made it accuse nobody in 78% of sheets, and
this loop needs a mark committed each time, not a shrug. Whether a seventh
candidate is wanted is asked as its own Noul instead, so it can be answered
without stalling the drawing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

from .drawloop import Draft, shape_deviation
from .jclient import JevClient, estimate_tokens
from .jvdrawing import AUDIT, BY_ID, CANVAS, CLAUSES, PAIRS, PHASES, PLAN, Mark
from .metrics import normalized_entropy
from .serialize import _feature_record
from .svggeom import (bbox_of, centroid, min_distance, polygon_area, polyline_len,
                      seg_intersect, segments_of)

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results" / "drawwith"
OFFER = 6                      # candidates per mark, my own realisation included


def _seed(*parts: Any) -> int:
    return int(hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()[:8], 16)


# --------------------------------------------------------------------------- #
# candidates
# --------------------------------------------------------------------------- #

def span(knob) -> float:
    return (max(knob.values) - min(knob.values)) or 1.0


def knob_gap(a: dict[str, float], b: dict[str, float], m: Mark) -> float:
    """How far two realisations of one recipe are, normalised per knob."""
    return round(sum(abs(a[k.name] - b[k.name]) / span(k) for k in m.knobs)
                 / len(m.knobs), 4)


def offered(m: Mark, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """My own realisation plus the nearest neighbours of it on the grid, shuffled
    and renamed, so `o-01` is not a hint about who authored it."""
    mine = m.params("mine")
    near = sorted((g for g in m.grid() if g != mine),
                  key=lambda g: (knob_gap(g, mine, m), _seed(m.mid, tuple(sorted(g.items())))))
    # spread the alternatives from nearest to furthest instead of offering six
    # hairlines off my own, which every chooser would score well on by accident
    step = max(1, len(near) // (OFFER - 1)) if OFFER > 1 else 1
    cells = [mine] + near[::step][:OFFER - 1]
    order = list(range(len(cells)))
    random.Random(_seed("offer", m.mid, len(ctx))).shuffle(order)
    out = []
    for i, pos in enumerate(sorted(order)):
        p = cells[pos]
        d = Draft(f"o-{i + 1:02d}", "path", m.recipe(ctx, **p)).measure()
        out.append({"cell": p, "draft": d, "is_mine": p == mine})
    return out


# --------------------------------------------------------------------------- #
# the loop, one mark at a time
# --------------------------------------------------------------------------- #
# One request per mark rather than one fan-out per phase: the geometry of the
# next candidate set is computed from the numbers just committed (the head is
# placed on the back that was picked), so each answer is needed to build the
# next state. That is the documented case for a second request, and it is what
# makes this one drawing rather than nineteen quizzes.

def pick_code(offers: list[dict[str, Any]], mode: str, mid: str) -> str:
    """The two code-only choosers, offered exactly what Jev is offered."""
    m = BY_ID[mid]
    if mode == "random":
        return random.Random(_seed("rnd", mid)).choice(offers)["draft"].did
    tame = m.params("middle")
    return min(offers, key=lambda o: knob_gap(o["cell"], tame, m))["draft"].did


# --------------------------------------------------------------------------- #
# what code already knows about one realisation
# --------------------------------------------------------------------------- #
# The first pass at this loop sent point lists and a sentence, and got back a
# nearly flat distribution over six candidates - which is not the model failing
# to have taste, it is the model being handed coordinates and told to invert
# them. Everything below is arithmetic that code can do exactly, so the judgment
# that is left over is the part that actually needs a reader.

PARTNER = {a: b for a, b in PAIRS} | {b: a for a, b in PAIRS}


def _shape(polys: list[list[tuple[float, float]]]) -> dict[str, Any]:
    x0, y0, x1, y1 = bbox_of(polys)
    cx, cy = centroid([p for poly in polys for p in poly])
    out: dict[str, Any] = {
        "bbox_pt": [round(v) for v in (x0, y0, x1, y1)],
        "width_pt": round(x1 - x0, 1),
        "height_pt": round(y1 - y0, 1),
        "aspect_w_over_h": round((x1 - x0) / max(0.5, y1 - y0), 2),
        "centre_pt": [round(cx, 1), round(cy, 1)],
        "ink_pt": round(sum(polyline_len(poly) for poly in polys), 1),
    }
    if len(polys) == 1:
        out["endpoints_pt"] = [[round(v, 1) for v in polys[0][0]],
                               [round(v, 1) for v in polys[0][-1]]]
        if math.dist(polys[0][0], polys[0][-1]) < 1e-6:
            # how much of the sheet a closed mark encloses: the difference between
            # a fat crescent and a sliver, which no bounding box will tell you
            out["area_pt"] = round(abs(polygon_area(polys[0])), 1)
    return out


def _rel(a: list[list[tuple[float, float]]],
         b: list[list[tuple[float, float]]]) -> dict[str, Any]:
    """How far, whether it crosses, and how far it pokes outside the other box."""
    ax0, ay0, ax1, ay1 = bbox_of(a)
    bx0, by0, bx1, by1 = bbox_of(b)
    out: dict[str, Any] = {"gap_pt": round(min_distance(a, b), 1)}
    if ax0 >= bx0 - .5 and ax1 <= bx1 + .5 and ay0 >= by0 - .5 and ay1 <= by1 + .5:
        out["bbox_inside"] = True
    else:
        poke = {"left": round(bx0 - ax0, 1), "right": round(ax1 - bx1, 1),
                "top": round(by0 - ay0, 1), "below": round(ay1 - by1, 1)}
        out["pokes_out_pt"] = {k: v for k, v in poke.items() if v > 0.5}
    if any(seg_intersect(p0, p1, q0, q1) for p0, p1 in segments_of(a)
           for q0, q1 in segments_of(b)):
        out["crosses"] = True
    return out


def _reference(ctx: dict[str, Any]) -> dict[str, Any]:
    """The surfaces the notes keep pointing at, stated once instead of six times."""
    ref: dict[str, Any] = {}
    if "shelf" in ctx:
        ends = ctx["shelf"][0]
        ref["sill"] = {"left_end_y_pt": round(ends[0][1], 1),
                       "right_end_y_pt": round(ends[-1][1], 1)}
    for eid in ("frame", "body", "head"):
        if eid in ctx:
            ref[eid] = _shape(ctx[eid])
    return ref


def _knobs_in_words(cell: dict[str, float]) -> str:
    return ", ".join(f"{k}={v:g}" for k, v in sorted(cell.items()))


def step(chooser: str, ctx: dict[str, Any], m: Mark,
         log: dict[str, Any], mode: str = "facts") -> dict[str, Any]:
    offs = offered(m, ctx)
    qid = f"{chooser}::{m.mid}"
    mine_id = next(o["draft"].did for o in offs if o["is_mine"])
    note = m.detail or m.brief

    if mode == "points":            # the first pass, kept so the two runs differ
        # only in what went in
        state: dict[str, Any] = {
            "canvas": {"width": CANVAS[0], "height": CANVAS[1]},
            "coordinate_note": ("x grows rightward, y grows downward, in canvas points. "
                                "Line art only: every entry is one mark the pen laid down."),
            "view_note": "left and right name the viewer's sides.",
            "task_note": ("a cartoonist is mid-drawing. `state.committed` holds the marks "
                          "already on the sheet; `state.candidates` holds `state.mark`'s "
                          "possible shapes, all of them drawable, and the artist's own note "
                          "about what the mark has to do."),
            "committed": [Draft(eid, "path", polys).measure().record
                          for eid, polys in ctx.items()],
            "mark": {"id": m.mid, "job": m.brief, "artist_note": note},
            "candidates": [o["draft"].record for o in offs],
        }
        crit = {o["draft"].did: {"what": f"candidate `{o['draft'].did}` in `state.candidates`",
                                 "not_for": "any other candidate in `state.candidates`"}
                for o in offs}
        questions: dict[str, Any] = {qid: {
            "type": "choice",
            "instructions": {
                "question": f"The next mark is {m.brief}. The artist's note for it: "
                            f"{note}. Which single candidate in "
                            f"`state.candidates` is that mark, given what is already "
                            f"committed?",
                "focus": "Satisfy every clause of the note, and keep the mark consistent "
                         "with where the committed marks already put the frame, the sill, "
                         "the body and the head. All the candidates are drawable, so pick "
                         "the one that fits best rather than declining to pick.",
            },
            "criteria": crit}}
        return {"state": state, "questions": questions, "offers": offs, "qid": qid,
                "mine_id": mine_id, "vq": [], "clauses": []}

    clauses = list(CLAUSES.get(m.mid, []))
    cands = []
    for cand in offs:
        polys = cand["draft"].polys
        # the four marks it actually sits next to, not every mark on the page
        near = sorted((min_distance(polys, p), eid) for eid, p in ctx.items())[:4]
        f: dict[str, Any] = {"id": cand["draft"].did,
                             "knobs": {k: round(v, 3) for k, v in cand["cell"].items()}}
        f.update(_shape(polys))
        f["placed_against"] = {eid: _rel(polys, ctx[eid]) for _, eid in near}
        cands.append(f)
    p = PARTNER.get(m.mid)
    pair: dict[str, Any] = {}
    if p and p in log:
        pair = {"mirror_partner_on_the_page": p, "partner_knobs": log[p]["cell"],
                "about_this_pair": "the same numbers as the partner's keep the two "
                                   "sides of the face the same size and shape"}
    elif p:
        pair = {"mirror_partner_comes_later": p,
                "about_this_pair": "the partner is drawn after this one with the same "
                                   "knob names; matching numbers keep the face symmetric"}
    state = {
        "canvas": {"width": CANVAS[0], "height": CANVAS[1]},
        "coordinate_note": ("x grows rightward and y grows downward, in canvas points, "
                            "so a larger y is lower on the sheet. Line art only: each "
                            "mark is one stroke the pen laid down."),
        "view_note": "left and right name the viewer's sides.",
        "task_note": ("a cartoonist is mid-drawing a cat asleep on a windowsill. "
                      "`state.sheet` holds what is already on the page; "
                      "`state.candidates` holds the possible shapes of `state.mark`, "
                      "each one the same mark drawn with different numbers."),
        "sheet": {"already_on_the_page": [
            {"id": eid, "job": BY_ID[eid].brief, **_shape(polys)}
            for eid, polys in ctx.items()],
            "reference": _reference(ctx)},
        "mark": {"id": m.mid, "job": m.brief, "artist_note": note,
                 "clauses": [{"id": f"c{i + 1}", "text": c} for i, c in enumerate(clauses)],
                 **({"mirror": pair} if pair else {})},
        "candidates": cands,
        "candidate_note": ("`knobs` are the numbers that made this candidate; the rest is "
                           "what code measured from the shape they produce. "
                           "`ink_pt` is how much pen the mark uses, `pokes_out_pt` how far "
                           "it stands outside another mark's box, `gap_pt` the shortest "
                           "distance to it. All candidates are drawable."),
    }
    crit = {o["draft"].did: {
        "what": f"candidate `{o['draft'].did}`, drawn with {_knobs_in_words(o['cell'])}",
        "not_for": "any other candidate, whose measured numbers differ from these"}
        for o in offs}
    questions = {qid: {
        "type": "choice",
        "instructions": {
            "question": f"The next mark is {m.brief}. The artist's note for it: {note}. "
                        f"Which single candidate in `state.candidates` is that mark, "
                        f"satisfying every entry in `state.mark.clauses` and fitting what "
                        f"`state.sheet` already has on it?",
            "focus": "A candidate that fails a clause is not the mark, however pretty. "
                     "Where no clause applies, choose the numbers that sit best with the "
                     "marks already drawn. All the candidates are drawable, so pick the "
                     "one that fits best rather than declining to pick.",
        },
        "criteria": crit}}
    vq: list[list[str]] = []
    for i, c in enumerate(clauses):
        row = []
        for o in offs:
            vid = o["draft"].did
            k = f"{chooser}::v::{m.mid}::c{i + 1}::{vid}"
            questions[k] = {"type": "noul",
                            "instructions": f"Look at candidate `{vid}` in "
                                            f"`state.candidates` on its own. Does it "
                                            f"satisfy clause c{i + 1} of the note?",
                            "criteria": {"true": f"`{vid}` does satisfy: {c}",
                                         "false": f"`{vid}` does not satisfy: {c}"}}
            row.append(k)
        vq.append(row)
    questions[f"{chooser}::none::{m.mid}"] = {
        "type": "noul",
        "instructions": "The artist's note asks for one specific mark. Is the mark it "
                        "asks for absent from `state.candidates` altogether - would a "
                        "seventh candidate be needed?",
        "criteria": {"true": "none of the six candidates is the mark the note asks for",
                     "false": "at least one of the six is the mark the note asks for"}}
    return {"state": state, "questions": questions, "offers": offs, "qid": qid,
            "mine_id": mine_id, "vq": vq, "clauses": clauses}


def draw_with(client: JevClient | None, chooser: str,
              mode: str = "facts") -> dict[str, Any]:
    """Run the whole figure once with the given chooser: 'jev', 'middle', 'random'."""
    ctx: dict[str, Any] = {}
    log: dict[str, Any] = {}
    tokens = 0
    for m in PLAN:
        st = step(chooser, ctx, m, log, mode)
        ans: dict[str, Any] = {}
        mark_tokens = 0
        if client is None:
            got = pick_code(st["offers"], chooser, m.mid)
        else:
            before = len(client.calls)
            ans = client.ask(st["state"], st["questions"], f"draw::{chooser}::{m.mid}")
            mark_tokens = sum(c.input_tokens for c in client.calls[before:])
            tokens += mark_tokens
            got = (ans.get(st["qid"]) or {}).get("choice")
        hit = next((o for o in st["offers"] if o["draft"].did == got), None)
        if hit is None:                       # unusable answer: fall back to my mark
            hit = next(o for o in st["offers"] if o["is_mine"])
        ctx[m.mid] = hit["draft"].polys
        probs = (ans.get(st["qid"]) or {}).get("probabilities") or {}
        ranked = sorted(probs.items(), key=lambda kv: -kv[1])
        where = [i for i, (d, _) in enumerate(ranked) if d == st["mine_id"]]
        margin = (round(ranked[0][1] - ranked[1][1], 3) if len(ranked) > 1 else None)
        # a candidate passes when it clears every clause; the pass set is what the
        # verification layer says, independent of the single pick above
        passes = []
        for j in range(len(st["offers"])):
            vals = [(ans.get(row[j]) or {}).get("noul") for row in st["vq"]]
            if vals and all(v is not None and v >= 0.5 for v in vals):
                passes.append(st["offers"][j]["draft"].did)
        log[m.mid] = {"chosen": hit["draft"].did, "cell": hit["cell"],
                      "is_mine": hit["is_mine"], "picked_mine": got == st["mine_id"],
                      "conf": (ans.get(st["qid"]) or {}).get("confidence"),
                      "probs": probs, "mine_rank": (where[0] + 1) if where else None,
                      "mine_prob": probs.get(st["mine_id"]), "margin": margin,
                      "clauses": len(st["vq"]),
                      "passes": passes, "mine_passes": st["mine_id"] in passes,
                      "choice_passes": hit["draft"].did in passes,
                      "none_match": (ans.get(f"{chooser}::none::{m.mid}") or {}).get("noul"),
                      "k": len(st["offers"]), "phase": m.phase, "grid": len(m.grid()),
                      "tokens": mark_tokens}
        if client is not None:
            (RESULTS / f"trace_{mode}_{chooser}_{m.mid}.json").write_text(json.dumps(
                {"state": st["state"], "questions": st["questions"], "answers": ans,
                 "mine": st["mine_id"], "tokens": mark_tokens},
                indent=1, ensure_ascii=False), encoding="utf-8")
    return {"chooser": chooser, "ctx": ctx, "log": log, "tokens": tokens}


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #

def score(run: dict[str, Any]) -> dict[str, Any]:
    """Agreement with the author, split by whether my note pinned that knob."""
    agree: dict[str, list[bool]] = {"pinned": [], "open": []}
    gaps: dict[str, list[float]] = {"pinned": [], "open": []}
    for mid, row in run["log"].items():
        for k in BY_ID[mid].knobs:
            band = "pinned" if k.pinned else "open"
            agree[band].append(row["cell"][k.name] == k.mine)
            gaps[band].append(abs(row["cell"][k.name] - k.mine) / span(k))
    out = {band: {"n": len(agree[band]),
                  "exact": round(sum(agree[band]) / len(agree[band]), 3)
                           if agree[band] else None,
                  "mean_gap": round(sum(gaps[band]) / len(gaps[band]), 3)
                           if gaps[band] else None}
           for band in ("pinned", "open")}
    sym = [run["log"][a]["cell"] == run["log"][b]["cell"]
           for a, b in PAIRS if a in run["log"] and b in run["log"]]
    out["mirrored_pairs_same_numbers"] = {"n": len(sym),
                                          "rate": round(sum(sym) / len(sym), 3)
                                          if sym else None}
    out["marks"] = len(run["log"])
    out["mean_confidence"] = round(sum(r["conf"] or 0 for r in run["log"].values())
                                   / max(1, len(run["log"])), 3)
    dist = [r for r in run["log"].values() if r.get("probs")]
    mean = lambda xs: (round(sum(xs) / len(xs), 3) if xs else None)  # noqa: E731
    out["distribution"] = {
        "n": len(dist),
        "mean_entropy": mean([normalized_entropy(r["probs"]) for r in dist]),
        "mean_rank_of_my_mark": mean([r["mine_rank"] for r in dist
                                      if r["mine_rank"]]),
        "my_mark_first": sum(1 for r in dist if r["mine_rank"] == 1),
        "mean_top1_minus_top2": mean([r["margin"] for r in dist if r["margin"] is not None]),
        "mean_p_of_my_mark": mean([r["mine_prob"] for r in dist
                                   if r["mine_prob"] is not None]),
        "none_of_the_six_above_half": sum(1 for r in run["log"].values()
                                          if (r.get("none_match") or 0) >= 0.5),
    }
    ver = [r for r in run["log"].values() if r.get("clauses")]
    out["verification"] = {
        "marks_with_clauses": len(ver),
        "mean_passers": mean([len(r["passes"]) for r in ver]),
        "my_mark_passes": mean([1.0 if r["mine_passes"] else 0.0 for r in ver]),
        "pick_passes": mean([1.0 if r["choice_passes"] else 0.0 for r in ver]),
        "passers_narrow_to_mine": mean([1.0 if (len(r["passes"]) == 1 and r["mine_passes"])
                                        else 0.0 for r in ver]),
    }
    return out


def svg(polys_by_id: dict[str, Any], title: str) -> str:
    body = []
    for eid, polys in polys_by_id.items():
        for poly in polys:
            d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in poly)
            body.append(f'<path d="{d}" data-mark="{eid}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS[0]}" '
            f'height="{CANVAS[1]}" viewBox="0 0 {CANVAS[0]} {CANVAS[1]}">'
            f'<title>{title}</title><rect width="100%" height="100%" fill="#fdfcf8"/>'
            f'<g fill="none" stroke="#1d1b18" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round">' + "".join(body) + "</g></svg>")


def audit(client: JevClient | None, runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Ask the same ten sentences of each finished sheet, with the stroke ids
    wiped (`e01`...) and no mark names anywhere. The names in the plan would answer
    these questions by themselves; anonymised, a gap between two sheets' answers
    is a claim about the geometry of the drawings rather than about the wording.

    The sheets differ only in numbers - same marks, same order - so this column
    asks whether the numbers change what the picture reads as at all.
    """
    out: dict[str, Any] = {}
    for name, run in runs.items():
        state = {
            "canvas": {"width": CANVAS[0], "height": CANVAS[1]},
            "coordinate_note": ("x grows rightward and y grows downward, in canvas "
                                "points, so a larger y is lower on the sheet."),
            "view_note": "left and right name the viewer's sides.",
            "task_note": "one finished line drawing, listed mark by mark",
            "marks": [{"id": f"e{i + 1:02d}", "closed": bool(Draft("", "path", polys)
                                                            .measure().closed),
                       **_shape(polys)}
                      for i, (_, polys) in enumerate(run["ctx"].items())],
            "marks_note": ("every mark is one stroke; `aspect_w_over_h` is width divided "
                           "by height, `ink_pt` how much pen the stroke uses, `centre_pt` "
                           "where it sits. Nothing is named: read the picture from shapes."),
        }
        questions = {f"a::{w}": {
            "type": "noul",
            "instructions": f"Is the following true of this sheet taken as one picture: {g}?",
            "criteria": {"true": "a reader of this sheet would agree",
                         "false": "a reader of this sheet would not agree"}}
            for w, g in AUDIT}
        if client is None:
            out[name] = {w: None for w, _ in AUDIT}
            continue
        before = len(client.calls)
        answers = client.ask(state, questions, f"audit::{name}")
        out[name] = {w: (answers.get(f"a::{w}") or {}).get("noul") for w, _ in AUDIT}
        out[name + "_tokens"] = sum(c.input_tokens for c in client.calls[before:])
    return out


# --------------------------------------------------------------------------- #
# offline gate
# --------------------------------------------------------------------------- #

def check(mode: str = "facts") -> int:
    problems: list[str] = []
    ctx: dict[str, Any] = {}
    log: dict[str, Any] = {}
    for m in PLAN:
        st = step("jev", ctx, m, log, mode)
        tok = estimate_tokens(st["state"]) + estimate_tokens(st["questions"])
        offs = st["offers"]
        ks = sorted(k.name for k in m.knobs if k.pinned)
        clauses = st["clauses"]
        print(f"   {m.mid:11s} {m.phase:10s} k={len(offs)} grid={len(m.grid()):3d} "
              f"tok={tok:5d} clauses={len(clauses)} pinned={ks or '-'} "
              f"mine_offered={any(o['is_mine'] for o in offs)}")
        if not any(o["is_mine"] for o in offs):
            problems.append(f"{m.mid}: my own realisation is not on offer")
        if len(offs) < 3:
            problems.append(f"{m.mid}: only {len(offs)} candidates")
        # a clause that quotes a number is the answer written twice, so the notes
        # have to stay in words and leave the arithmetic to the state
        if mode == "facts":
            if any(any(ch.isdigit() for ch in c) for c in clauses):
                problems.append(f"{m.mid}: a clause contains a number")
            if bool(clauses) != bool(ks):
                problems.append(f"{m.mid}: clauses {len(clauses)} vs pinned knobs {len(ks)}")
            if any("points" in c for c in st["state"]["candidates"]):
                problems.append(f"{m.mid}: a candidate still carries raw points")
            if len(st["questions"]) != 1 + len(clauses) * len(offs) + 1:
                problems.append(f"{m.mid}: fan-out is {len(st['questions'])} questions, "
                                f"expected choice + {len(clauses)}x{len(offs)} + none")
        for i, o in enumerate(offs):
            xs = [p[0] for poly in o["draft"].polys for p in poly]
            ys = [p[1] for poly in o["draft"].polys for p in poly]
            if min(xs) < -2 or min(ys) < -2 or max(xs) > CANVAS[0] + 2 or max(ys) > CANVAS[1] + 2:
                problems.append(f"{m.mid}/{o['draft'].did}: leaves the canvas")
            for q in offs[i + 1:]:
                if shape_deviation(o["draft"].polys, q["draft"].polys) < 0.5:
                    problems.append(f"{m.mid}: {o['draft'].did} and {q['draft'].did} "
                                    f"are the same shape twice")
        if tok > 30000:
            problems.append(f"{m.mid}: state too large ({tok})")
        ctx[m.mid] = m.recipe(ctx, **m.params("mine"))
        log[m.mid] = {"cell": m.params("mine")}
    pinned = sum(1 for m in PLAN for k in m.knobs if k.pinned)
    total = sum(len(m.knobs) for m in PLAN)
    off_mine = sum(1 for m in PLAN for k in m.knobs
                   if k.mine == k.values[len(k.values) // 2])
    silent = [m.mid for m in PLAN if not m.detail]
    print(f"\nknobs: {total} total, {pinned} pinned by a note, {total - pinned} open")
    print(f"marks with no note at all (pure taste): {silent or 'none'}")
    print(f"'tame middle' equals my authored value on {off_mine}/{total} knobs "
          f"- the middle chooser has to beat that to be worth anything")
    for a, b in PAIRS:
        if not (BY_ID[a].knobs and BY_ID[b].knobs):
            problems.append(f"pair {a}/{b} has no knobs to compare")
        if [k.name for k in BY_ID[a].knobs] != [k.name for k in BY_ID[b].knobs]:
            problems.append(f"pair {a}/{b} is not the same recipe shape")
    print("\n" + ("CHECK FAILED:\n  " + "\n  ".join(problems) if problems
                  else "check passed: no calls made, nothing sent"))
    return 1 if problems else 0


# --------------------------------------------------------------------------- #

def mine_ctx() -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    for m in PLAN:
        ctx[m.mid] = m.recipe(ctx, **m.params("mine"))
    return ctx


def report(mode: str, runs: dict[str, Any], aud: dict[str, Any],
           summary: dict[str, Any]) -> None:
    print(f"\n=== input condition: {mode}")
    print(json.dumps(summary["score"], indent=1, ensure_ascii=False))
    print(f"\n{'sentence asked of the sheet':32s}" + "".join(f"{n:>9s}" for n in runs))
    for w, _ in AUDIT:
        print(f"  {w:30s}" + "".join(f"{str(aud.get(n, {}).get(w)):>9s}" for n in runs))
    print(f"{summary['totals']['tokens']} input tokens; a cached re-run reports real "
          f"API time but costs nothing")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--no-calls", action="store_true",
                    help="run the code choosers only, and render")
    ap.add_argument("--input", default="facts", choices=["points", "facts", "both"],
                    help="what goes into the state: measured facts and a clause "
                         "fan-out, or the first pass's raw point lists")
    args = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    modes = ["points", "facts"] if args.input == "both" else [args.input]
    if args.check:
        ctx = mine_ctx()
        (RESULTS / "mine.svg").write_text(svg(ctx, "mine"), encoding="utf-8")
        rc = 0
        for mode in modes:
            print(f"\n== input condition: {mode}")
            rc |= check(mode)
        return rc

    client = None if args.no_calls else JevClient(cache_dir=ROOT / "results" / "cache")
    # the two code choosers never see the state, so they are the same two runs in
    # either input condition; only jev is drawn twice
    code = {n: draw_with(None, n) for n in ("middle", "random")}
    for mode in modes:
        runs = dict(code)
        if client is not None:
            runs["jev"] = draw_with(client, "jev", mode)
        runs["mine"] = {"ctx": mine_ctx(), "log": {}, "tokens": 0}
        for name, run in runs.items():
            (RESULTS / f"{mode}_{name}.svg").write_text(
                svg(run["ctx"], f"{mode} / {name}"), encoding="utf-8")
        (RESULTS / f"{mode}_compare.html").write_text(
            "<meta charset=utf-8><body style='background:#e8e6e1;font:13px system-ui;"
            "display:flex;gap:14px;padding:14px;flex-wrap:wrap'>"
            + "".join(f"<figure style='margin:0'><figcaption>{mode} / {n}</figcaption>"
                      f"<img src='{mode}_{n}.svg' style='background:#fdfcf8;"
                      f"border:1px solid #999'></figure>"
                      for n in ["mine", "jev", "middle", "random"] if n in runs) + "</body>",
            encoding="utf-8")
        aud = audit(client, runs)
        summary = {"input_condition": mode,
                   "totals": {"marks": len(PLAN), "phases": len(PHASES),
                              "knobs": sum(len(m.knobs) for m in PLAN),
                              "tokens": sum(r["tokens"] for r in runs.values())
                              + sum(v for k, v in aud.items()
                                    if k.endswith("_tokens") and isinstance(v, int))},
                   "score": {n: score(r) for n, r in runs.items() if n != "mine"},
                   "audit": {k: v for k, v in aud.items() if not k.endswith("_tokens")},
                   "log": {n: r["log"] for n, r in runs.items()}}
        (RESULTS / f"summary_{mode}.json").write_text(
            json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
        report(mode, runs, aud, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
