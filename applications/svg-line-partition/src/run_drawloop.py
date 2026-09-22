"""Run round three: the in-loop judgments, and the baselines that go with them.

    python -m src.run_drawloop --check    # offline gate, no calls, nothing sent
    python -m src.run_drawloop            # the grid -> results/drawloop/{raw,summary.json}

The prose read of the summary lives in results/drawloop/report.md.

Every choice family is scored against `1/K` for its own K, because the answer key
here is manufactured and therefore balanced by construction - unlike rounds one
and two, a constant answer cannot score well by accident.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator

from . import drawloop as DL
from .jclient import JevClient, estimate_tokens
from .metrics import ACT_AT, CAUTION_AT, auc, band

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results" / "drawloop"


# --------------------------------------------------------------------------- #
# offline gate
# --------------------------------------------------------------------------- #

def check() -> int:
    problems: list[str] = []
    tasks = DL.build_tasks()
    print(f"{len(tasks)} states, {sum(len(t.questions) for t in tasks)} questions")
    for fam in DL.FAMILIES:
        sub = [t for t in tasks if t.family == fam]
        print(f"\n== {fam}: {len(sub)} states")
        if not sub:
            problems.append(f"{fam}: no tasks built")
            continue
        ks: Counter = Counter()
        slots: Counter = Counter()
        npos = nneg = 0
        for t in sub:
            for leak in DL.check_leaks(t):
                problems.append(f"{t.key}: leak {leak}")
            tok = estimate_tokens(t.state) + estimate_tokens(t.questions)
            if tok > 40000:
                problems.append(f"{t.key}: state too large ({tok} est tokens)")
            for qid, q in t.questions.items():
                truth = t.truth[qid]
                if q["type"] == "choice":
                    opts = [k for k in q["criteria"] if k != DL.NONE_MATCH]
                    ks[len(opts)] += 1
                    if truth not in opts:
                        problems.append(f"{qid}: answer key {truth} not on offer")
                    if len(opts) < 3:
                        problems.append(f"{qid}: only {len(opts)} options")
                    if qid.startswith("pick_shape"):
                        slots[int(truth.split("-")[1]) - 1] += 1
                elif truth not in ("true", "false"):
                    problems.append(f"{qid}: bad noul truth {truth}")
                if q["type"] == "noul":
                    npos += truth == "true"
                    nneg += truth == "false"
            if t.family == "pick_shape":
                bad = [d for d in t.meta["drafts"] if d["origin"] != "true"]
                if len(bad) < 3:
                    problems.append(f"{t.key}: only {len(bad)} live wrong drafts")
                for d in bad:
                    if d["dev"] < t.meta["floor"]:
                        problems.append(f"{t.key}: {d['origin']} dev {d['dev']} is under "
                                        f"this stroke's visibility floor {t.meta['floor']}")
        print(f"   options per question: {dict(sorted(ks.items())) or '-'}")
        if slots:
            print(f"   answer-key slot balance: {dict(sorted(slots.items()))}")
            if max(slots.values()) - min(slots.values()) > 3:
                problems.append(f"{fam}: key sits in one slot too often {slots}")
        if npos or nneg:
            print(f"   noul: true {npos} / false {nneg}")
            if min(npos, nneg) < 3:
                problems.append(f"{fam}: noul class too thin ({npos}/{nneg})")
        if fam == "spot_fault":
            kinds = {t.meta["kind"] for t in sub}
            print(f"   error kinds covered: {sorted(kinds)}")
            if len(kinds) < 5:
                problems.append(f"{fam}: only {len(kinds)} error kinds reached")

    ns = [t for t in tasks if t.family == "next_stroke"]
    first = sum(1 for t in ns if t.meta["truth_rank_by_travel"] == 0)
    print(f"\nnext_stroke: the pen-travel rule alone puts the true next mark first in "
          f"{first}/{len(ns)} states, so it has to beat {first / max(1, len(ns)):.3f}")
    for t in tasks:
        if t.family == "next_stroke" and t.meta["truth_rank_by_travel"] > 1:
            print(f"   note {t.key}: truth is travel-rank "
                  f"{t.meta['truth_rank_by_travel']}, unreachable for that rule")
    print("\n" + ("CHECK FAILED:\n  " + "\n  ".join(problems) if problems
                  else "check passed: no calls made, nothing sent"))
    return 1 if problems else 0


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #

def run(client: JevClient, only: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    tasks = [t for t in DL.build_tasks()
             if not only or any(o in t.key for o in only)]
    for i, t in enumerate(tasks, 1):
        before = len(client.calls)
        t0 = time.time()
        answers = client.ask(t.state, t.questions, tag=t.key)
        secs, used = time.time() - t0, client.calls[before:]
        first = next(iter(t.truth))
        a0 = answers.get(first) or {}
        got = a0.get("choice") if a0.get("type") == "choice" else a0.get("noul")
        print(f"[{i:3d}/{len(tasks):3d}] {t.family:11s} {t.key[:46]:46s} "
              f"q={len(t.questions):3d} {secs:5.1f}s {got} vs {t.truth[first]}")
        out.append({"key": t.key, "family": t.family, "fixture": t.fixture,
                    "wall_seconds": round(secs, 2),
                    "fresh_calls": sum(1 for c in used if not c.cached),
                    "input_tokens": sum(c.input_tokens for c in used),
                    "api_seconds": round(sum(c.seconds for c in used), 2),
                    "n_questions": len(t.questions),
                    "state_tokens_estimate": estimate_tokens(t.state),
                    "model_reported": used[0].model if used else client.model,
                    "state": t.state, "questions": t.questions, "answers": answers,
                    "truth": t.truth, "meta": t.meta})
    return out


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #

def _mean(v: list[float]) -> float | None:
    return round(sum(v) / len(v), 3) if v else None


def rows_of(dump: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for qid, truth in dump["truth"].items():
        a = dump["answers"].get(qid) or {}
        if a.get("type") == "choice" and not qid.startswith("spot_noul"):
            probs = a.get("probabilities") or {}
            yield {"qid": qid, "kind": "choice", "truth": truth,
                   "pred": a.get("choice"), "conf": a.get("confidence"),
                   "probs": probs,
                   "k": sum(1 for o in probs if o != DL.NONE_MATCH)}
        elif a.get("type") == "noul":
            yield {"qid": qid, "kind": "noul", "truth": truth, "p": a.get("noul")}


def agg_choice(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [r for r in rows if r["kind"] == "choice"]
    if not rows:
        return {"n": 0}
    hit = [r["pred"] == r["truth"] for r in rows]
    hi = [r for r in rows if (r["conf"] or 0) >= ACT_AT]
    lo = [r for r in rows if (r["conf"] or 0) < CAUTION_AT]
    return {
        "n": len(rows),
        "acc": round(sum(hit) / len(hit), 3),
        "random_1_over_k": _mean([1.0 / max(1, r["k"]) for r in rows]),
        "mean_k": _mean([float(r["k"]) for r in rows]),
        "lift_over_random": round(sum(hit) / len(hit)
                                  - _mean([1.0 / max(1, r["k"]) for r in rows]), 3),
        "none_match_rate": round(sum(1 for r in rows if r["pred"] == DL.NONE_MATCH)
                                 / len(rows), 3),
        "mean_confidence": _mean([r["conf"] for r in rows if r["conf"] is not None]),
        "act_band_n": len(hi),
        "act_band_acc": round(sum(1 for r in hi if r["pred"] == r["truth"]) / len(hi), 3)
        if hi else None,
        "below_caution_n": len(lo),
        "mean_brier": _mean([
            sum((r["probs"].get(o, 0.0) - (1.0 if o == r["truth"] else 0.0)) ** 2
                for o in set(r["probs"]) | {r["truth"]})
            / len(set(r["probs"]) | {r["truth"]}) for r in rows]),
    }


def agg_noul(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [r for r in rows if r["kind"] == "noul" and r.get("p") is not None]
    pos = [r["p"] for r in rows if r["truth"] == "true"]
    neg = [r["p"] for r in rows if r["truth"] == "false"]
    allp, lab = pos + neg, [1] * len(pos) + [0] * len(neg)
    out: dict[str, Any] = {"n": len(allp), "n_pos": len(pos), "n_neg": len(neg),
                           "mean_p_pos": _mean(pos), "mean_p_neg": _mean(neg),
                           "constant_answer_baseline": round(
                               max(len(pos), len(neg)) / len(allp), 3) if allp else None}
    if allp:
        pred = [1 if p >= 0.5 else 0 for p in allp]
        out["accuracy"] = round(sum(p == y for p, y in zip(pred, lab)) / len(lab), 3)
        out["recall_at_0.5"] = round(sum(1 for p in pos if p >= 0.5) / len(pos), 3) if pos else None
        out["precision_at_0.5"] = (round(sum(1 for p in pos if p >= 0.5)
                                         / sum(1 for p in allp if p >= 0.5), 3)
                                   if pos and any(p >= 0.5 for p in allp) else None)
        out["abstained_0.4_0.6"] = round(sum(1 for p in allp if 0.4 <= p <= 0.6)
                                         / len(allp), 3)
    out["auc"] = round(auc(allp, lab), 3) if pos and neg else None
    return out


def summarise(dumps: list[dict[str, Any]]) -> dict[str, Any]:
    fam: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in dumps:
        fam[d["family"]].append(d)
    out: dict[str, Any] = {"totals": {
        "states": len(dumps),
        "questions": sum(d["n_questions"] for d in dumps),
        "input_tokens": sum(d["input_tokens"] for d in dumps),
        "api_seconds": round(sum(d["api_seconds"] for d in dumps), 1),
        "fresh_calls": sum(d["fresh_calls"] for d in dumps),
        "model": dumps[0]["model_reported"] if dumps else None}}

    for name in ("pick_shape", "pair_mate"):
        sub = fam.get(name, [])
        rows = [r for d in sub for r in rows_of(d)]
        e = {"states": len(sub), "agg": agg_choice(rows)}
        if name == "pick_shape":
            # how tempting each manufactured error is, read off the distributions
            tempt: dict[str, list[float]] = defaultdict(list)
            for d in sub:
                origin = {x["did"]: x["origin"] for x in d["meta"]["drafts"]}
                for r in rows_of(d):
                    if r["kind"] != "choice":
                        continue
                    for did, p in r["probs"].items():
                        o = origin.get(did)
                        if o and o != "true":
                            tempt[o].append(p)
            e["temptation_by_error"] = {
                o: {"n": len(v), "mean_prob_given": _mean(v), "max": max(v)}
                for o, v in sorted(tempt.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))}
            e["per_state"] = {
                d["key"]: {"truth": d["truth"][next(iter(d["truth"]))],
                           "pred": (d["answers"].get(next(iter(d["truth"]))) or {}).get("choice"),
                           "conf": (d["answers"].get(next(iter(d["truth"]))) or {}).get("confidence"),
                           "target": d["meta"]["target"],
                           "drafts": d["meta"]["drafts"]}
                for d in sub}
        out[name] = e

    sub = fam.get("next_stroke", [])
    if sub:
        e: dict[str, Any] = {"states": len(sub),
                             "agg": agg_choice([r for d in sub for r in rows_of(d)]),
                             "by_condition": {}}
        for cond in ("seen_order", "shuffled_prefix"):
            s = [d for d in sub if d["meta"]["cond"] == cond]
            rows = [r for d in s for r in rows_of(d)]
            e["by_condition"][cond] = {
                "states": len(s), "agg": agg_choice(rows),
                "pen_travel_rule_acc": round(
                    sum(1 for d in s if d["meta"]["truth_rank_by_travel"] == 0)
                    / max(1, len(s)), 3)}
        e["per_state"] = {d["key"]: {"truth": d["truth"][next(iter(d["truth"]))],
                                     "pred": (d["answers"].get(next(iter(d["truth"]))) or {}).get("choice"),
                                     "travel": d["meta"]["travel"],
                                     "truth_travel_rank": d["meta"]["truth_rank_by_travel"]}
                          for d in sub}
        out["next_stroke"] = e

    sub = fam.get("spot_fault", [])
    if sub:
        rows = [r for d in sub for r in rows_of(d)]
        e = {"states": len(sub),
             "choice": agg_choice([r for r in rows if r["qid"].startswith("spot_choice")]),
             "noul": agg_noul([r for r in rows if r["qid"].startswith("spot_noul")]),
             "by_error_kind": {}}
        for d in sub:
            kind = d["meta"]["kind"]
            b = e["by_error_kind"].setdefault(kind, {"note": d["meta"]["note"],
                                                     "n": 0, "dev": [], "fault_p": [],
                                                     "clean_p": [], "choice_hit": [],
                                                     "victims": []})
            b["n"] += 1
            b["dev"].append(d["meta"]["dev"])
            b["victims"].append(d["meta"]["victim"])
            rr = list(rows_of(d))
            b["fault_p"] += [x["p"] for x in rr
                             if x["kind"] == "noul" and x["truth"] == "true"]
            b["clean_p"] += [x["p"] for x in rr
                             if x["kind"] == "noul" and x["truth"] == "false"]
            ck = f"spot_choice::{d['fixture']}::{kind}"
            b["choice_hit"].append(1 if next((x["pred"] == x["truth"] for x in rr
                                              if x["qid"] == ck), False) else 0)
        for b in e["by_error_kind"].values():
            b["mean_dev"] = _mean(b["dev"])
            b["mean_p_fault"] = _mean(b["fault_p"])
            b["mean_p_clean"] = _mean(b["clean_p"])
            b["choice_acc"] = _mean([float(x) for x in b["choice_hit"]])
            for k in ("dev", "fault_p", "clean_p", "choice_hit"):
                b.pop(k, None)
        out["spot_fault"] = e

    sub = fam.get("presence", [])
    if sub:
        by_fix: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for d in sub:
            by_fix[d["fixture"]][d["meta"]["cond"]] = d
        e = {"states": len(sub),
             "noul_after_erase": agg_noul([r for d in sub
                                           if d["meta"]["cond"] == "erased"
                                           for r in rows_of(d)]),
             "noul_intact": agg_noul([r for d in sub
                                      if d["meta"]["cond"] == "intact"
                                      for r in rows_of(d)]),
             "per_fixture": {}}
        for name, pair in by_fix.items():
            if "intact" not in pair or "erased" not in pair:
                continue
            gi = {k.rsplit("::", 1)[1]: (v or {}).get("noul")
                  for k, v in pair["intact"]["answers"].items()}
            ge = {k.rsplit("::", 1)[1]: (v or {}).get("noul")
                  for k, v in pair["erased"]["answers"].items()}
            te = {k.rsplit("::", 1)[1]: v for k, v in pair["erased"]["truth"].items()}
            words = {w: {"p_intact": gi.get(w), "p_erased": ge.get(w),
                         "delta": round((ge.get(w) or 0) - (gi.get(w) or 0), 3),
                         "truth_after": te.get(w)}
                     for w in sorted(set(gi) | set(ge))}
            e["per_fixture"][name] = {
                "erased": pair["erased"]["meta"]["erased"],
                "mean_delta_removed": _mean([v["delta"] for v in words.values()
                                             if v["truth_after"] == "false"]),
                "mean_delta_survivors": _mean([v["delta"] for v in words.values()
                                               if v["truth_after"] == "true"]),
                "words": words}
        out["presence"] = e
    return out


# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--only", action="append", default=[],
                    help="substring of a state key, repeatable")
    args = ap.parse_args()
    if args.check:
        return check()

    client = JevClient(cache_dir=ROOT / "results" / "cache")
    dumps = run(client, args.only)
    summary = summarise(dumps)
    (RESULTS / "raw").mkdir(parents=True, exist_ok=True)
    for d in dumps:
        # windows refuses ':' in a filename and the question keys are namespaced
        name = d["key"].replace("::", "__").replace("/", "-")
        (RESULTS / "raw" / f"{name}.json").write_text(
            json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    (RESULTS / "summary.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")

    t = summary["totals"]
    print(f"\n{t['states']} states / {t['questions']} questions / "
          f"{t['input_tokens']} in-tokens / {t['api_seconds']}s API / "
          f"{t['fresh_calls']} fresh calls / model {t['model']}")
    for name in DL.FAMILIES:
        e = summary.get(name)
        if not e:
            continue
        a = e.get("agg") or e.get("choice") or {}
        print(f"  {name:12s} acc={a.get('acc')} vs 1/K={a.get('random_1_over_k')} "
              f"none={a.get('none_match_rate')} conf={a.get('mean_confidence')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
