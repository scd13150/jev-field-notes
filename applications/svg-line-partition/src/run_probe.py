"""Run the probe: one Jev request family per (fixture, serialization condition).

    python -m src.run_probe --only house_scene/features_named
    python -m src.run_probe                      # the full grid

Each run dumps state, questions, answers, oracle truth and token/latency usage
to results/raw/. Nothing is recomputed from the API afterwards; analyze.py reads
those dumps, so re-thinking the scoring costs no calls.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from . import metrics as M
from .jclient import JevClient, estimate_tokens
from .questions import build_questions, pair_candidates
from .serialize import CONDITIONS, state_ids, truth_of, serialize
from .svggeom import Drawing, load_svg

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "fixtures"
RESULTS = ROOT / "results"

CHOICE_FAMILIES = ("scene_layer", "nesting_layer", "role", "region", "group")
SCORE_FAMILIES = ("extent", "structural_weight")
NOUL_FAMILIES = ("rel_same_object", "rel_encloses", "rel_touches", "rel_crosses",
                 "rel_parallel", "rel_in_front", "rel_in_front_undef",
                 "rel_depth_cue", "rel_evidence", "rel_paint_order")


def fixtures() -> list[str]:
    return sorted(p.stem for p in FIXTURE_DIR.glob("*.svg"))


ANIMATE = {"head", "torso", "arm", "leg", "bird", "person", "figure", "animal", "cat", "dog"}


def gestalt_truth(d: Drawing) -> dict[str, Any]:
    """Oracle answers for the whole-drawing questions, from the same facts."""
    diag = (d.width ** 2 + d.height ** 2) ** 0.5
    layers = {e.layer for e in d.elements} - {"", "frame"}
    straight = sum(e.length for e in d.elements if e.turning < 20)
    total = sum(e.length for e in d.elements) or 1.0
    if straight / total > 0.6:
        weights = {"horizontal": 0.0, "vertical": 0.0, "diagonal": 0.0}
        for e in d.elements:
            if e.turning >= 20:
                continue
            o = e.orientation
            near = lambda t: min(abs(o - t) % 180, 180 - abs(o - t) % 180)  # noqa: E731
            for name, target in (("horizontal", 0), ("vertical", 90), ("diagonal", 45)):
                if near(target) < 22:
                    weights[name] += e.length
        axis = max(weights, key=weights.get)
        if max(weights.values()) / total < 0.45:
            axis = "mixed"
    else:
        axis = "curved"
    best = max(d.elements,
               key=lambda e: e.length / (1 + min_distance_2(e, d, diag)))
    # Animate content is read off the authored object labels, not the file name:
    # a house scene that contains two bird strokes counts, an abstract sheet does not.
    objects = {v["object"] for v in truth_of(d).values()}
    return {
        "gestalt_contains_figure": int(bool(objects & ANIMATE)),
        "gestalt_layer_count": len(layers),
        "gestalt_axis": axis,
        "gestalt_focal_region": best.region,
    }


def min_distance_2(e, d: Drawing, diag: float) -> float:
    cx, cy = e.centroid
    return ((cx - d.width / 2) ** 2 + (cy - d.height / 2) ** 2) ** 0.5


def split_qid(qid: str) -> tuple[str, str | None, str | None, str | None]:
    """'rel_touches::a|b' -> ('rel_touches', None, 'a', 'b'); 'role::x' -> ('role','x',None,None)"""
    fam, _, rest = qid.partition("::")
    if "|" in rest:
        a, _, b = rest.partition("|")
        return fam, None, a, b
    return fam, rest or None, None, None


def run_one(client: JevClient, name: str, condition: str) -> dict[str, Any]:
    d = load_svg(str(FIXTURE_DIR / f"{name}.svg"))
    state = serialize(d, condition)
    pairs = pair_candidates(d)
    questions = build_questions(d, state, pairs)
    truth = truth_of(d)
    before = len(client.calls)
    t0 = time.time()
    answers = client.ask(state, questions, tag=f"{name}/{condition}")
    secs = time.time() - t0
    used = client.calls[before:]
    fresh = [c for c in used if not c.cached] or used
    dump = {
        "fixture": name,
        "condition": condition,
        "model_reported": fresh[0].model if fresh else client.model,
        "wall_seconds": round(secs, 2),
        "fresh_calls": sum(1 for c in used if not c.cached),
        "input_tokens": sum(c.input_tokens for c in used),
        "output_tokens": sum(c.output_tokens for c in used),
        "api_seconds": round(sum(c.seconds for c in used), 2),
        "calls": len(used),
        "state_tokens_estimate": estimate_tokens(state),
        "question_tokens_estimate": estimate_tokens(questions),
        "n_elements": len(d.elements),
        "n_questions": len(questions),
        "state": state,
        "questions": questions,
        "answers": answers,
        "truth": truth,
        "id_map": state_ids(d, condition),
        "pairs": [{"a": a, "b": b, "state_a": a, "state_b": b, **facts}
                  for a, b, facts in pairs],
        "gestalt_truth": gestalt_truth(d),
    }
    out = RESULTS / "raw"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}__{condition}.json").write_text(
        json.dumps(dump, indent=1, ensure_ascii=False), encoding="utf-8")
    return dump


def summarise(dump: dict[str, Any]) -> dict[str, Any]:
    """Score one run against its own oracle."""
    answers, truth, ids = dump["answers"], dump["truth"], dump["id_map"]
    fam_rows: dict[str, list[dict[str, Any]]] = {f: [] for f in
                                                 list(CHOICE_FAMILIES) + list(SCORE_FAMILIES)
                                                 + list(NOUL_FAMILIES) + ["gestalt"]}
    for qid, ans in answers.items():
        fam, eid, a, b = split_qid(qid)
        qname = fam                              # the question's own name
        if fam.startswith("gestalt"):
            fam = "gestalt"                      # whole-drawing ids carry no element suffix
        if fam not in fam_rows:
            continue
        orig = ids.get(eid or "", eid) if eid else None
        if fam in CHOICE_FAMILIES:
            t = None
            if orig and orig in truth:
                key = {"scene_layer": "layer", "nesting_layer": "nesting",
                       "role": "role", "region": "region",
                       "group": "object"}[fam]
                t = truth[orig][key] if fam != "group" else truth[orig]["object"]
                if fam == "group" and t == "none" and not any(
                        v["object"] != "none" for v in truth.values()):
                    continue  # no identifiable vocabulary to score against
            fam_rows[fam].append({"eid": orig, "truth": t, "pred": ans.get("choice"),
                                  "confidence": ans.get("confidence"),
                                  "probabilities": ans.get("probabilities")})
        elif fam in SCORE_FAMILIES:
            key = "extent_bin" if fam == "extent" else "structure_bin"
            t = truth[orig][key] if orig in truth else None
            probs = ans.get("probabilities") or {}
            top = max(probs, key=probs.get) if probs else None
            fam_rows[fam].append({"eid": orig, "truth": t,
                                  "pred": int(top) if top is not None else None,
                                  "score": ans.get("score"),
                                  "confidence": ans.get("confidence"),
                                  "probabilities": {k: v for k, v in probs.items()}})
        else:
            if fam.startswith("rel_"):
                facts = next((p for p in dump["pairs"] if p["a"] == a and p["b"] == b), None)
                if facts is None:
                    continue
                attr = {"rel_same_object": "same_object", "rel_encloses": "a_encloses_b",
                        "rel_touches": None, "rel_crosses": "crosses",
                        "rel_parallel": None, "rel_in_front": "a_direct_front_of_b",
                        "rel_depth_cue": "any_occlusion_cue", "rel_evidence": None,
                        "rel_paint_order": "a_painted_after_b"}[fam]
                if fam == "rel_touches":
                    label = 1 if facts["gap"] < 1.0 else 0
                elif fam == "rel_parallel":
                    label = 1 if facts["parallel_deg"] < 8 else 0
                elif fam == "rel_evidence":
                    # does the state carry geometry for this at all?
                    label = 0 if dump["condition"] == "named_nogeo" else 1
                elif fam == "rel_in_front" and not facts["any_occlusion_cue"]:
                    # the drawing gives no break cue; does it fall back on the
                    # only ordering the file really carries, paint order?
                    fam_rows["rel_in_front_undef"].append({
                        "pair": f"{a}|{b}",
                        "truth": 1 if facts["a_painted_after_b"] else 0,
                        "pred": 1 if ans.get("noul", 0) >= 0.5 else 0,
                        "noul": ans.get("noul"), "why": facts["why"]})
                    continue
                else:
                    label = 1 if facts[attr] else 0
                fam_rows[fam].append({"pair": f"{a}|{b}", "truth": label,
                                      "pred": 1 if ans.get("noul", 0) >= 0.5 else 0,
                                      "noul": ans.get("noul"),
                                      "why": facts["why"]})
            else:
                gt = dump["gestalt_truth"].get(qname)
                if qname == "gestalt_contains_figure":
                    fam_rows["gestalt"].append({"q": qname, "truth": gt,
                                               "pred": 1 if ans.get("noul", 0) >= 0.5 else 0,
                                               "noul": ans.get("noul")})
                elif ans.get("choice") is not None:
                    fam_rows["gestalt"].append({"q": qname, "truth": gt,
                                               "pred": ans.get("choice"),
                                               "confidence": ans.get("confidence")})
                else:
                    probs = ans.get("probabilities") or {}
                    fam_rows["gestalt"].append({"q": qname, "truth": gt,
                                               "score": ans.get("score"),
                                               "pred": (int(max(probs, key=probs.get)) + 1)
                                               if probs else None,
                                               "confidence": ans.get("confidence")})

    summary: dict[str, Any] = {"fixture": dump["fixture"], "condition": dump["condition"],
                              "model": dump["model_reported"],
                              "n_elements": dump["n_elements"],
                              "n_questions": dump["n_questions"],
                              "input_tokens": dump["input_tokens"],
                              "output_tokens": dump["output_tokens"],
                              "wall_seconds": dump["wall_seconds"],
                              "api_seconds": dump["api_seconds"],
                              "fresh_calls": dump["fresh_calls"],
                              "n_calls": dump["calls"],
                              "seconds": dump["api_seconds"]}
    for fam, rows in fam_rows.items():
        if not rows:
            continue
        if fam == "gestalt":
            summary[fam] = {"n": len(rows),
                            "items": [{k: r.get(k) for k in ("q", "truth", "pred",
                                                             "confidence", "noul", "score")}
                                      for r in rows]}
        elif fam.startswith("rel_"):
            noul_rows = [r for r in rows if "noul" in r]
            if not noul_rows:
                continue
            pos = sum(r["truth"] for r in noul_rows)
            summary[fam] = {
                "n": len(noul_rows),
                "acc": round(sum(r["truth"] == r["pred"] for r in noul_rows) / len(noul_rows), 3),
                "auc": round(M.auc([r["noul"] for r in noul_rows],
                                   [r["truth"] for r in noul_rows]), 3)
                if len({r["truth"] for r in noul_rows}) > 1 else None,
                "mean_dev_from_half": round(statistics.mean(
                    abs(r["noul"] - 0.5) for r in noul_rows), 3),
                "positives": pos,
                "baseline": round(max(pos, len(noul_rows) - pos) / len(noul_rows), 3),
            }
        elif fam in SCORE_FAMILIES:
            ok = [r for r in rows if r["truth"] is not None]
            summary[fam] = {**M.graded(rows),
                            "spearman": round(M.spearman([r["score"] for r in ok],
                                                         [r["truth"] for r in ok]), 3)
                            if ok else None,
                            **baselines(r["truth"] for r in ok)}
        else:
            summary[fam] = M.graded(rows)
            summary[fam].update(baselines(r["truth"] for r in rows if r["truth"] is not None))
            if fam == "group":
                summary[fam].update(grouping(rows, dump))
    return summary


def baselines(truths) -> dict[str, Any]:
    """What a caller gets for free: always naming the commonest class, and uniform guessing.

    Accuracy only means something against these; on a skewed partition a
    constant answer can score high without resolving anything. The constant
    answer's macro-F1 is `(2/K)·p/(1+p)` for the majority class of prevalence p
    over K true classes, which is the floor the reported macro-F1 must clear.
    """
    vals = [t for t in truths if t is not None]
    if not vals:
        return {}
    counts = Counter(vals)
    k = len(counts)
    prev = max(counts.values()) / len(vals)
    return {"baseline": round(prev, 3),
            "chance": round(1 / k, 3), "n_classes": k,
            "f1_baseline": round((2 / k) * prev / (1 + prev), 3)}


def grouping(rows: list[dict[str, Any]], dump: dict[str, Any]) -> dict[str, Any]:
    """Turn per-element soft assignments back into a partition and score it."""
    usable = [r for r in rows if r["probabilities"] and r["eid"]]
    if len(usable) < 4:
        return {}
    nodes = [r["eid"] for r in usable]
    probs = {r["eid"]: r["probabilities"] for r in usable}
    pairs = [(a, b, M.same_group_prob(probs[a], probs[b]))
             for i, a in enumerate(nodes) for b in nodes[i + 1:]]
    pred = M.clusters_from_coassociation(pairs, nodes, cutoff=0.5)
    truth_map = {r["eid"]: dump["truth"][r["eid"]]["object"] for r in usable}
    a = [truth_map[n] for n in nodes]
    b = [pred[n] for n in nodes]
    members: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        members[pred[n]].append(n)
    clusters = list(members.values())
    return {"ari": round(M.ari(a, b), 3), "nmi": round(M.nmi(a, b), 3),
            "n_clusters_pred": len(set(b)), "n_objects_truth": len(set(a)),
            # over-splitting and mixing are different failures, and they need
            # different fixes: one is a missing merge, the other a wrong merge.
            "n_multi": sum(1 for c in clusters if len(c) > 1),
            "n_mixed": sum(1 for c in clusters if len({truth_map[n] for n in c}) > 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=[],
                    help="fixture/condition, repeatable; default is the whole grid")
    ap.add_argument("--model", default=None)
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()

    combos: list[tuple[str, str]] = []
    for f in fixtures():
        for c in CONDITIONS:
            combos.append((f, c))
    if args.only:
        want = {tuple(o.split("/")) for o in args.only}
        combos = [cb for cb in combos if cb in want]

    client = JevClient(cache_dir=ROOT / "results" / "cache",
                       **({"model": args.model} if args.model else {}))
    # A --only run must not shrink summary.json to one row: keep the rows for the
    # combinations this run did not touch, then write the grid back in full.
    prior: dict[tuple[str, str], dict] = {}
    if (RESULTS / "summary.json").exists():
        try:
            for row in json.loads((RESULTS / "summary.json").read_text(encoding="utf-8")):
                prior[(row["fixture"], row["condition"])] = row
        except (json.JSONDecodeError, KeyError):
            prior = {}
    done: dict[tuple[str, str], dict] = dict(prior)
    for name, condition in combos:
        path = RESULTS / "raw" / f"{name}__{condition}.json"
        if args.summary_only and path.exists():
            dump = json.loads(path.read_text(encoding="utf-8"))
        else:
            t = time.time()
            dump = run_one(client, name, condition)
            print(f"{name}/{condition}: {dump['n_questions']} questions in "
                  f"{time.time() - t:.1f}s, {dump['input_tokens']} in-tokens")
        s = summarise(dump)
        done[(name, condition)] = s
        print("   " + json.dumps({k: (v.get("acc") if isinstance(v, dict) else v)
                                  for k, v in s.items() if k in
                                  ("scene_layer", "nesting_layer", "role", "region",
                                   "group", "extent", "structural_weight")}))

    ran = set(combos)
    summaries = [done[cb] for cb in combos] + \
                [row for cb, row in prior.items() if cb not in ran and cb in done]
    if len(summaries) > len(combos):  # a partial run: keep the grid's own order first
        print(f"\n--only run: kept {len(summaries) - len(combos)} rows from the "
              f"previous summary, so summary.json still covers the whole grid")
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "summary.json").write_text(json.dumps(summaries, indent=1), encoding="utf-8")
    print(f"\ncalls made this run: {sum(1 for c in client.calls if not c.cached)}, "
          f"served from cache: {sum(1 for c in client.calls if c.cached)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
