"""Round 2: does the drawing trace (the order the pen moved in) buy anything?

    python -m src.run_traces --check          # offline, no calls, no key needed
    python -m src.run_traces                  # the whole 3 x 5 grid
    python -m src.run_traces --only trace_cat_decor/order_named

The ablated variable here is not how the geometry is written out but **how the
making of the picture is conveyed**: five states of one drawing, from a list that
is the pen path and carries times, through times without a pen path, to a list
that says nothing about when anything was drawn, to a list carrying a *false*
pen path.

Two code comparators run beside the model on every condition, so a number here
can be read as "better than what?":

* `geometric_rule_part` - containment in a closed outline, plus a 6-point
  proximity fallback, plus the small hand-written outline -> part table;
* `pen_run` - the contiguity bet, cut wherever the pen travels more than
  PEN_JUMP points, scored under each condition's own sequence.

`--check` refuses to let the experiment out of the door unless the fixtures hold
together: tilings that tile, strictly increasing pen times, a truth value for
every stroke on every dimension, both classes present in every pairwise
relation, and an answer key that stays out of all five states.
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
from . import traces as TR
from .jclient import JevClient, estimate_tokens
from .run_probe import baselines

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results" / "traces"

CHOICE_FAMILIES = ("part", "layer", "region", "motion")
PAIR_FAMILIES = ("p_same_part", "p_same_motion", "p_adjacent", "p_after")
ELEMENT_NOUL = ("loose_decor",)
SCORE_FAMILIES = ("g_moving_parts", TR.DECOR_SHARE)

# the state does carry a sequence under order_scrambled too - a wrong one - so
# "readable" is not the same question as "true", and this truth says only whether
# a sequence can be read off at all
ORDER_UNREADABLE = ("order_none",)

# which recorded fact makes each pairwise question true or false
PAIR_KEY = {"p_same_part": "same_part", "p_same_motion": "same_motion",
            "p_adjacent": "adjacent", "p_after": "a_after_b"}


def split_qid(qid: str) -> tuple[str, str | None, str | None, str | None]:
    fam, _, rest = qid.partition("::")
    if "|" in rest:
        a, _, b = rest.partition("|")
        return fam, None, a, b
    return fam, rest or None, None, None


# --------------------------------------------------------------------------- #
# whole-drawing truth, computed the same way every time so the question and the
# score cannot drift apart
# --------------------------------------------------------------------------- #

def count_bin(n: int) -> int:
    return 0 if n <= 1 else 1 if n <= 3 else 2 if n <= 6 else 3


def decor_bin(share: float) -> int:
    if share == 0:
        return 0
    if share < 0.25:
        return 1
    if share <= 0.6:
        return 2
    if share < 0.9:
        return 3
    return 4


def gestalt_truth(drawing: TR.Drawing, condition: str) -> dict[str, Any]:
    truth = TR.truth_of(drawing)
    pieces = {v["motion"] for v in truth.values()} - {TR.MOTION_FALLBACK}
    decor_len = sum(e.length for e in drawing.elements
                    if truth[e.eid]["layer"] == "decor")
    total_len = sum(e.length for e in drawing.elements) or 1.0
    return {
        "g_order_readable": 0 if condition in ORDER_UNREADABLE else 1,
        "g_moving_parts": count_bin(len(pieces)),
        "g_moving_parts_count": len(pieces),
        TR.DECOR_SHARE: decor_bin(decor_len / total_len),
        "decor_share_len": round(decor_len / total_len, 3),
    }


# --------------------------------------------------------------------------- #
# one run
# --------------------------------------------------------------------------- #

def run_one(client: JevClient, name: str, condition: str) -> dict[str, Any]:
    d = TR.load(name)
    state = TR.serialize(d, condition)
    pairs = TR.pair_candidates(d)
    questions = TR.build_questions(d, state, pairs, condition)
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
        "truth": TR.truth_of(d),
        "id_map": TR.state_ids(d, condition),
        "pairs": [{"a": a, "b": b, "state_a": TR._ids(d, condition)[a],
                   "state_b": TR._ids(d, condition)[b], **facts}
                  for a, b, facts in pairs],
        "gestalt_truth": gestalt_truth(d, condition),
        "comparators": {
            "geom_part": TR.geometric_rule_part(d, "part"),
            "geom_motion": TR.geometric_rule_part(d, "motion"),
            "pen_run_part": TR.pen_run(d, condition, "part"),
            "pen_run_motion": TR.pen_run(d, condition, "motion"),
        },
        "pen_travel": TR.travel_separation(d),
    }
    out = RESULTS / "raw"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}__{condition}.json").write_text(
        json.dumps(dump, indent=1, ensure_ascii=False), encoding="utf-8")
    return dump


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #

def comparator_accuracy(dump: dict[str, Any]) -> dict[str, Any]:
    d = TR.load(dump["fixture"])
    truth = TR.truth_of(d)
    out: dict[str, Any] = {}
    for key, field in (("geom_part", "part"), ("geom_motion", "motion"),
                       ("pen_run_part", "part"), ("pen_run_motion", "motion")):
        got = dump["comparators"][key]
        t = [truth[e.eid][field] for e in d.elements if e.eid in got]
        p = [got[e.eid] for e in d.elements if e.eid in got]
        out[key] = {"n": len(p),
                    "acc": round(sum(x == y for x, y in zip(t, p)) / len(p), 3),
                    "macro_f1": round(M.macro_f1(t, p), 3),
                    "n_none": sum(1 for v in p if v == "none"),
                    **baselines(t)}
    return out


def grouping(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    """Fold the per-element soft assignments back into a partition and score it.

    The live2d question is not which label each stroke gets but whether the
    strokes end up in the same handful of drawers - so the marginals are turned
    into P(same part) for every pair, single-linked at 0.5, and the resulting
    partition is scored against the authored one.
    """
    usable = [r for r in rows if r.get("probabilities") and r.get("eid")]
    if len(usable) < 4:
        return {}
    nodes = [r["eid"] for r in usable]
    probs = {r["eid"]: r["probabilities"] for r in usable}
    pairs = [(a, b, M.same_group_prob(probs[a], probs[b]))
             for i, a in enumerate(nodes) for b in nodes[i + 1:]]
    pred = M.clusters_from_coassociation(pairs, nodes, cutoff=0.5)
    truth_map = {r["eid"]: r["truth"] for r in usable}
    a = [truth_map[n] for n in nodes]
    b = [pred[n] for n in nodes]
    members: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        members[pred[n]].append(n)
    clusters = list(members.values())
    return {"ari": round(M.ari(a, b), 3), "nmi": round(M.nmi(a, b), 3),
            "n_clusters_pred": len(set(b)), "n_parts_truth": len(set(a)),
            "n_multi": sum(1 for c in clusters if len(c) > 1),
            "n_mixed": sum(1 for c in clusters if len({truth_map[n] for n in c}) > 1)}


def summarise(dump: dict[str, Any]) -> dict[str, Any]:
    answers, truth = dump["answers"], dump["truth"]
    gt = dump["gestalt_truth"]
    pair_facts = {(p["a"], p["b"]): p for p in dump["pairs"]}
    rows: dict[str, list[dict[str, Any]]] = {f: [] for f in
                                             list(CHOICE_FAMILIES) + list(PAIR_FAMILIES)
                                             + list(ELEMENT_NOUL) + ["gestalt"]}
    for qid, ans in answers.items():
        fam, eid, a, b = split_qid(qid)
        if fam not in rows:
            continue
        if fam in CHOICE_FAMILIES:
            t = truth.get(eid or "", {}).get(fam)
            rows[fam].append({"eid": eid, "truth": t or None,
                              "pred": ans.get("choice"),
                              "confidence": ans.get("confidence"),
                              "probabilities": ans.get("probabilities")})
        elif fam in ELEMENT_NOUL:
            t = truth.get(eid or "", {}).get("loose_decor")
            rows["loose_decor"].append({"eid": eid, "truth": t,
                                        "pred": 1 if (ans.get("noul") or 0) >= 0.5 else 0,
                                        "noul": ans.get("noul")})
        elif fam in PAIR_FAMILIES:
            facts = pair_facts.get((a, b))
            if facts is None:
                continue
            label = {fam: facts[PAIR_KEY[fam]]}[fam]
            rows[fam].append({"pair": f"{a}|{b}", "truth": int(bool(label)),
                              "pred": 1 if (ans.get("noul") or 0) >= 0.5 else 0,
                              "noul": ans.get("noul"), "why": facts["why"],
                              "gap_steps": facts["gap_steps"]})
        else:
            pass

    summary: dict[str, Any] = {
        "fixture": dump["fixture"], "condition": dump["condition"],
        "model": dump["model_reported"],
        "n_elements": dump["n_elements"], "n_questions": dump["n_questions"],
        "input_tokens": dump["input_tokens"], "output_tokens": dump["output_tokens"],
        "wall_seconds": dump["wall_seconds"], "api_seconds": dump["api_seconds"],
        "fresh_calls": dump["fresh_calls"], "n_calls": dump["calls"],
        "seconds": dump["api_seconds"],
        "pen_travel": dump["pen_travel"],
        "comparators": comparator_accuracy(dump),
    }

    for fam in CHOICE_FAMILIES:
        if not rows[fam]:
            continue
        scored = [r for r in rows[fam] if r["truth"] is not None]
        summary[fam] = {**M.graded(rows[fam]),
                        **baselines(r["truth"] for r in scored)}
        summary[fam]["conf_on_wrong"] = _mean([r["confidence"] for r in scored
                                               if r["truth"] != r["pred"]
                                               and r["confidence"] is not None])
        summary[fam]["conf_on_right"] = _mean([r["confidence"] for r in scored
                                               if r["truth"] == r["pred"]
                                               and r["confidence"] is not None])
        if fam in ("part", "motion"):
            summary[fam].update(grouping(scored, fam))

    for fam in list(ELEMENT_NOUL) + list(PAIR_FAMILIES):
        got = rows[fam]
        if not got:
            continue
        pos = sum(r["truth"] for r in got)
        # recall and precision, not just accuracy: for the decorative-open-stroke
        # question a constant "false" already scores high, so the useful number is
        # how many of the real ones it endorses and how many of those are right.
        picked = [r for r in got if r["pred"]]
        summary[fam] = {
            "n": len(got), "positives": pos,
            "acc": round(sum(r["truth"] == r["pred"] for r in got) / len(got), 3),
            "baseline": round(max(pos, len(got) - pos) / len(got), 3),
            "recall": round(sum(r["truth"] for r in picked) / pos, 3) if pos else None,
            "precision": round(sum(r["truth"] for r in picked) / len(picked), 3)
            if picked else None,
            "auc": round(M.auc([r["noul"] for r in got], [r["truth"] for r in got]), 3)
            if len({r["truth"] for r in got}) > 1 else None,
            "mean_noul_pos": _mean([r["noul"] for r in got if r["truth"]]),
            "mean_noul_neg": _mean([r["noul"] for r in got if not r["truth"]]),
            "mean_noul": _mean([r["noul"] for r in got]),
            "mean_dev_from_half": _mean([abs((r["noul"] or 0.5) - 0.5) for r in got]),
        }

    summary["part_vs_pairwise"] = part_vs_pairwise(rows)

    gestalt_rows = _gestalt_rows(answers, gt)
    summary["gestalt"] = {
        "n": len(gestalt_rows),
        "items": [{**r, "ok": r["truth"] == r["pred"]} for r in gestalt_rows],
        "order_readable": next((r["noul"] for r in gestalt_rows
                                if r["q"] == "g_order_readable"), None),
    }
    return summary


def part_vs_pairwise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Two routes to one fact, scored separately.

    The labelled per-element assignment implies a same-part answer for every
    pair; the pairwise question is asked with no vocabulary at all. A pipeline
    can only use one of them, so the report keeps both accuracies and the rate at
    which the two routes contradict each other on the same pair.
    """
    pred = {r["eid"]: r["pred"] for r in rows["part"] if r.get("eid")}
    cons = []
    for r in rows["p_same_part"]:
        a, _, b = r["pair"].partition("|")
        if a not in pred or b not in pred:
            continue
        pa, pb = pred[a], pred[b]
        implied = int(pa == pb and pa not in (None, "", "none"))
        cons.append({"pair": r["pair"], "truth": r["truth"],
                     "implied": implied, "pairwise": r["pred"]})
    if not cons:
        return {}
    n = len(cons)
    return {"n": n,
            "agreement": round(sum(c["implied"] == c["pairwise"] for c in cons) / n, 3),
            "from_choices_acc": round(sum(c["truth"] == c["implied"] for c in cons) / n, 3),
            "pairwise_acc": round(sum(c["truth"] == c["pairwise"] for c in cons) / n, 3),
            "contradictions": [c["pair"] for c in cons
                               if c["implied"] != c["pairwise"]]}


def _gestalt_rows(answers: dict[str, Any], gt: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for qid, ans in answers.items():
        if qid == "g_order_readable":
            rows.append({"q": qid, "truth": gt["g_order_readable"],
                         "pred": 1 if (ans.get("noul") or 0) >= 0.5 else 0,
                         "noul": ans.get("noul")})
        elif qid in SCORE_FAMILIES:
            probs = ans.get("probabilities") or {}
            top = max(probs, key=probs.get) if probs else None
            rows.append({"q": qid, "truth": gt[qid], "score": ans.get("score"),
                         "pred": (int(top) if top is not None else None),
                         "confidence": ans.get("confidence")})
    return rows


def _mean(vals: list[float]) -> float | None:
    vals = [v for v in vals if v is not None]
    return round(statistics.fmean(vals), 3) if vals else None


# --------------------------------------------------------------------------- #
# offline gate: the fixtures and the states have to hold before any call is made
# --------------------------------------------------------------------------- #

def check() -> int:
    problems: list[str] = []
    for name in TR.TRACE_FIXTURES:
        d = TR.load(name)
        truth = TR.truth_of(d)
        n = len(d.elements)
        print(f"\n== {name}: {n} strokes, {d.width:.0f}x{d.height:.0f}, "
              f"groups={set(e.group_path for e in d.elements)}")
        bad = TR.check_tiling(name)
        print(f"   tiling: {'ok' if not bad else bad[:3]}")
        problems += [f"{name}: tiling {b}" for b in bad]

        ts = [truth[e.eid]["trace_ms"] for e in d.elements]
        inc = all(b > a for a, b in zip(ts, ts[1:]))
        print(f"   pen times strictly increase in document order: {inc}")
        if not inc:
            problems.append(f"{name}: pen times not increasing")
        nofield = [f"{e.eid}.{k}" for e in d.elements
                   for k in ("part", "layer", "motion", "region")
                   if not truth[e.eid][k]]
        print(f"   missing truth fields: {nofield or 'none'}")
        problems += [f"{name}: missing {x}" for x in nofield]
        known = {"backdrop", "body", "detail", "decor", "guide"}
        strange = sorted({truth[e.eid]["layer"] for e in d.elements} - known)
        if strange:
            problems.append(f"{name}: layer outside the vocabulary {strange}")
        print(f"   layer vocabulary holds: {not strange}")
        open_decor = sum(truth[e.eid]["loose_decor"] for e in d.elements)
        print(f"   open decorative strokes: {open_decor}")
        if not open_decor:
            problems.append(f"{name}: no decorative open stroke to test")

        pairs = TR.pair_candidates(d)
        pos = {fam: sum(1 for _, _, f in pairs if f[PAIR_KEY[fam]])
               for fam in PAIR_FAMILIES}
        print("   pairs: " + " ".join(f"{fam}={pos[fam]}" for fam in PAIR_FAMILIES)
              + f" of {len(pairs)}")
        for fam in PAIR_FAMILIES:
            if not (2 <= pos[fam] <= len(pairs) - 2):
                problems.append(f"{name}: {fam} is nearly single-class "
                                f"({pos[fam]}/{len(pairs)})")
        dirs = pos["p_after"]
        if not (len(pairs) // 3 <= dirs <= 2 * len(pairs) // 3):
            problems.append(f"{name}: p_after orientation unbalanced ({dirs}/{len(pairs)})")

        for cond in TR.CONDITIONS:
            st = TR.serialize(d, cond)
            q = TR.build_questions(d, st, pairs, cond)
            leaks = TR.leak_check(st, cond, d)
            tk = estimate_tokens(st) + estimate_tokens(q)
            seq = [e["id"] for e in st["elements"]]
            has_t = "trace_ms" in st["elements"][0]
            print(f"   {cond:16s} q={len(q):3d} est_tok={tk:5d} times={'y' if has_t else 'n'} "
                  f"leak={leaks or '-'} first={seq[0]}")
            if leaks:
                problems.append(f"{name}/{cond}: leak {leaks}")
            listed = TR._sequence(d, cond)
            times = [truth[e]["trace_ms"] for e in listed]
            if cond == "order_scrambled" and times == sorted(times):
                problems.append(f"{name}/{cond}: the fake trace is the real one")
            if cond in ("order_named", "order_list") and times != sorted(times):
                problems.append(f"{name}/{cond}: listed order and times disagree")
            if cond == "times_only" and sorted(e["id"] for e in st["elements"]) != \
                    [e["id"] for e in st["elements"]]:
                problems.append(f"{name}/{cond}: ids do not follow the listed order")
        pt = TR.travel_separation(d)
        print(f"   pen travel as a same-part test: auc={pt['auc']} "
              f"median same={pt['median_same']} diff={pt['median_diff']} "
              f"(n {pt['n_same_runs']}/{pt['n_breaks']})")
        geo = TR.geometric_rule_part(d, "part")
        run = TR.pen_run(d, "order_named", "part")
        print(f"   rules: containment {sum(geo[e.eid] == truth[e.eid]['part'] for e in d.elements) / n:.3f}"
              f"  pen-run(contiguous order) {sum(run[e.eid] == truth[e.eid]['part'] for e in d.elements) / n:.3f}"
              f"  majority class {max(Counter(truth[e.eid]['part'] for e in d.elements).values()) / n:.3f}")
    print("\n" + ("CHECK FAILED:\n  " + "\n  ".join(problems) if problems
                  else "check passed: no calls made, nothing sent"))
    return 1 if problems else 0


# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="validate fixtures, states and comparators offline")
    ap.add_argument("--only", action="append", default=[],
                    help="fixture/condition, repeatable; default is the whole grid")
    ap.add_argument("--model", default=None)
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()

    if args.check:
        return check()

    combos: list[tuple[str, str]] = [(f, c) for f in TR.TRACE_FIXTURES
                                     for c in TR.CONDITIONS]
    if args.only:
        want = {tuple(o.split("/")) for o in args.only}
        combos = [cb for cb in combos if cb in want]
        unknown = want - set(combos)
        if unknown:
            raise SystemExit(f"unknown combinations: {sorted(unknown)}")

    client = JevClient(cache_dir=RESULTS / "cache",
                       **({"model": args.model} if args.model else {}))

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
            print(f"{name}/{condition}: {dump['n_questions']} judgments in "
                  f"{time.time() - t:.1f}s, {dump['input_tokens']} in-tokens")
        s = summarise(dump)
        done[(name, condition)] = s
        print("   " + json.dumps({k: (v.get("acc") if isinstance(v, dict) else v)
                                  for k, v in s.items()
                                  if k in CHOICE_FAMILIES + PAIR_FAMILIES + ("loose_decor",)}))

    ran = set(combos)
    summaries = [done[cb] for cb in combos] + [row for cb, row in prior.items()
                                               if cb not in ran and cb in done]
    if len(summaries) > len(combos):
        print(f"\n--only run: kept {len(summaries) - len(combos)} rows from the previous "
              "summary, so summary.json still covers the whole grid")
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "summary.json").write_text(json.dumps(summaries, indent=1),
                                          encoding="utf-8")
    print(f"\ncalls made this run: {sum(1 for c in client.calls if not c.cached)}, "
          f"served from cache: {sum(1 for c in client.calls if c.cached)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
