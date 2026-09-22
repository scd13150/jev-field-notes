"""Scoring a fuzzy partition: accuracy is the least interesting of these.

The point of a soft partition is that the probabilities themselves are data, so
this module measures four things a hard classifier score would throw away:

  banding     does acting only on high-confidence answers beat acting always?
              (the docs' high / medium / low -> act / caution / abstain pattern)
  fuzziness   entropy of the distribution, and the top-1 minus top-2 margin
  calibration do 0.8-confidence answers land right about 80% of the time?
  structure   can the per-element probabilities be turned back into a grouping
              that matches the drawing's true partition (ARI / NMI)?
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Iterable, Sequence

# risk-scaled bands, per the Confidence page: the floor is where the model says
# "I don't know", so nothing is acted on below it
ACT_AT = 0.85
CAUTION_AT = 0.55

BAND_ACT = "act"
BAND_CAUTION = "caution"
BAND_ABSTAIN = "abstain"


def band(confidence: float | None) -> str:
    if confidence is None:
        return BAND_ABSTAIN
    if confidence >= ACT_AT:
        return BAND_ACT
    if confidence >= CAUTION_AT:
        return BAND_CAUTION
    return BAND_ABSTAIN


def entropy(probs: dict[str, float]) -> float:
    return -sum(p * math.log2(p) for p in probs.values() if p > 0)


def normalized_entropy(probs: dict[str, float]) -> float:
    """Uncertainty on [0,1] regardless of how many options the question had.

    Raw bits are not comparable between a 3-way and a 9-way choice, which is
    exactly the comparison the report makes.
    """
    k = len([p for p in probs.values() if p > 0])
    return entropy(probs) / math.log2(k) if k > 1 else 0.0


def brier(probs: dict[str, float], truth: str) -> float:
    """Mean squared error over the option set: the classic binary Brier for 2
    options, and comparable across a 4-way and a 9-way question."""
    keys = set(probs) | {truth}
    return sum((probs.get(k, 0.0) - (1.0 if k == truth else 0.0)) ** 2
               for k in keys) / len(keys)


def margin(probs: dict[str, float]) -> float:
    p = sorted(probs.values(), reverse=True)
    return (p[0] - p[1]) if len(p) > 1 else p[0]


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    def ranks(v: Sequence[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    if len(xs) < 3:
        return float("nan")
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else float("nan")


def auc(scores: Sequence[float], labels: Sequence[int]) -> float:
    """Probability that a positive outranks a negative; 0.5 with no overlap."""
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return float("nan")
    wins = sum(1.0 for p in pos for q in neg if p > q) + \
        0.5 * sum(1.0 for p in pos for q in neg if p == q)
    return wins / (len(pos) * len(neg))


def macro_f1(truth: Sequence[str], pred: Sequence[str]) -> float:
    labels = sorted(set(truth) | set(p for p in pred if p))
    if not labels:
        return float("nan")
    tot = 0.0
    for lab in labels:
        tp = sum(1 for t, p in zip(truth, pred) if t == lab and p == lab)
        fp = sum(1 for t, p in zip(truth, pred) if t != lab and p == lab)
        fn = sum(1 for t, p in zip(truth, pred) if t == lab and p != lab)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        tot += (2 * prec * rec / (prec + rec)) if prec + rec else 0.0
    return tot / len(labels)


def _contingency(a: Sequence[str], b: Sequence[str]):
    counts: Counter = Counter()
    ra: Counter = Counter()
    rb: Counter = Counter()
    for x, y in zip(a, b):
        counts[(x, y)] += 1
        ra[x] += 1
        rb[y] += 1
    return counts, ra, rb


def ari(a: Sequence[str], b: Sequence[str]) -> float:
    n = len(a)
    if n < 3:
        return float("nan")
    counts, ra, rb = _contingency(a, b)
    sum_comb = lambda c: sum(v * (v - 1) // 2 for v in c)  # noqa: E731
    s_ij = sum_comb(counts.values())
    s_i = sum_comb(ra.values())
    s_j = sum_comb(rb.values())
    expected = s_i * s_j / comb(n, 2)
    maxd = 0.5 * (s_i + s_j)
    den = maxd - expected
    return (s_ij - expected) / den if den else float("nan")


def comb(n: int, k: int) -> int:
    return math.comb(n, k)


def nmi(a: Sequence[str], b: Sequence[str]) -> float:
    n = len(a)
    if n < 3:
        return float("nan")
    counts, ra, rb = _contingency(a, b)
    h = lambda c: -sum((v / n) * math.log2(v / n) for v in c if v)  # noqa: E731
    hx, hy = h(ra.values()), h(rb.values())
    mi = sum((v / n) * math.log2((v * n) / (ra[x] * rb[y]))
             for (x, y), v in counts.items() if v)
    den = math.sqrt(hx * hy) if hx and hy else float("nan")
    return mi / den if den == den else float("nan")


def clusters_from_coassociation(pairs: Iterable[tuple[str, str, float]],
                                nodes: Sequence[str], cutoff: float = 0.5) -> dict[str, str]:
    """Single-linkage grouping from soft same-group probabilities."""
    parent = {n: n for n in nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, p in sorted(pairs, key=lambda t: -t[2]):
        if p < cutoff or a not in parent or b not in parent:
            continue
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    return {n: find(n) for n in nodes}


def same_group_prob(pa: dict[str, float], pb: dict[str, float]) -> float:
    """P(two elements share a group) from their independent soft assignments."""
    return sum(v * pb.get(k, 0.0) for k, v in pa.items())


def graded(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise a list of {truth, pred, confidence} comparisons."""
    scored = [r for r in results if r.get("truth") is not None and r.get("pred") is not None]
    if not scored:
        return {"n": 0}
    correct = [r["truth"] == r["pred"] for r in scored]
    out: dict[str, Any] = {
        "n": len(scored),
        "acc": round(sum(correct) / len(correct), 3),
        "macro_f1": round(macro_f1([r["truth"] for r in scored],
                                   [r["pred"] for r in scored]), 3),
    }
    conf = [r.get("confidence") for r in scored]
    known = [(r, c) for r, c in zip(scored, conf) if c is not None]
    if known:
        bands: dict[str, list[int]] = defaultdict(list)
        for r, c in known:
            bands[band(c)].append(1 if r["truth"] == r["pred"] else 0)
        out["mean_confidence"] = round(sum(c for _, c in known) / len(known), 3)
        for name in (BAND_ACT, BAND_CAUTION, BAND_ABSTAIN):
            v = bands.get(name, [])
            out[f"{name}_coverage"] = round(len(v) / len(known), 3)
            out[f"{name}_accuracy"] = round(sum(v) / len(v), 3) if v else None
        out["calibration"] = calibration_bins(known)
    if all("probabilities" in r for r in scored[:1]):
        out["mean_entropy"] = round(
            sum(entropy(r["probabilities"]) for r in scored) / len(scored), 3)
        out["mean_norm_entropy"] = round(
            sum(normalized_entropy(r["probabilities"]) for r in scored) / len(scored), 3)
        out["mean_brier"] = round(
            sum(brier(r["probabilities"], r["truth"]) for r in scored) / len(scored), 3)
        out["mean_margin"] = round(
            sum(margin(r["probabilities"]) for r in scored) / len(scored), 3)
    return out


def calibration_bins(known: list[tuple[dict[str, Any], float]], nb: int = 5) -> list[dict[str, Any]]:
    buckets: list[list[int]] = [[] for _ in range(nb)]
    for r, c in known:
        i = min(nb - 1, int(c * nb))
        buckets[i].append(1 if r["truth"] == r["pred"] else 0)
    return [{"bin": f"{i / nb:.1f}-{(i + 1) / nb:.1f}",
             "n": len(b),
             "empirical_accuracy": round(sum(b) / len(b), 2)} for i, b in enumerate(buckets) if b]
