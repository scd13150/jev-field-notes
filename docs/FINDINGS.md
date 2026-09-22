# Findings

Thirteen falsifiable behaviours measured on `jev-1.13.0`, each with the observation behind it and the
harness that produced it. Full derivations and the supporting tables are in
[`../papers/JEV_EMPIRICAL_BOUNDARY_ANALYSIS.md`](../papers/JEV_EMPIRICAL_BOUNDARY_ANALYSIS.md).

These are written as tests, not as opinions: each one could have come out the other way, and the ones
marked **cost** are the places where money was spent to learn something a free baseline already knew.

| # | Behaviour | The observation |
| --- | --- | --- |
| 1 | **When names are readable, it reads names.** | Masking identifiers cut two axes' discrimination by 60%+ (+0.67 → +0.24); deceptive names flipped the gap negative (−0.12). Name contribution measured at **+0.286 to +0.427**. |
| 2 | **Given incomplete evidence it answers the narrower question — and voids the axis.** | One axis was pointed at "reachable serialization sink in the call graph." The model correctly answered that narrower question and the axis fell from **+0.79 to +0.12**. Restoring the real save-file evidence returned it to +0.81. |
| 3 | **A question with no evidence in the artifact is unanswerable.** | After grounding, `player_visible` retained **+0.01** — its apparent +0.83 was the identifier. The honest response is a narrower claim, not a higher threshold. |
| 4 | **Enumerable things must not be asked of it.** | An assembly is a fully typed table. The byte/metadata layer made **0 calls**; deterministic validation caught 2 silent parse errors that would have poisoned every semantic input. |
| 5 | **Fine-grained grouping is not reproducible.** | After a metadata fix, only **67%** of previously co-clustered type pairs remained together (pair Jaccard 0.51). Axes were stable (12 live axes unchanged, NMI 0.4973 → 0.5021); members were not. |
| 6 | **A cache hit is not cache correctness.** | A run reported "562 hits, 0 calls" while feeding a dossier generated *before* the metadata fix. A stale input can pass through an entire layer looking healthy. |
| 7 | **It does not infer data flow; it decodes names.** | Truth from IL instruction flow: **0.588** vs a 0.42 majority baseline named, **0.302** masked — *below* a constant predictor. Arguments scored 0/80. The same labels cost $0 and 8 seconds from a deterministic probe. |
| 8 | **A tag is not a request identity.** | Counting by tag prefix reported 1,629 requests where the cache-key count was **1,470** — the tag string `arm:field:rep` collided across different states. Counting must be by cache key, or both spend and "what actually ran" drift silently. |
| 9 | **Confidence defends against noise, not against bias.** | A zero-shot routing arm spent **158/158** calls on a declared-but-never-used decoy slot at 0.65–0.84 confidence for **0.000** accuracy. Accuracy was 0.00 at *every* coverage level — selective prediction cannot rescue a systematic prior. |
| 10 | **Examples activate structural matching, but do not beat a lookup.** | 8 examples → 0.907, with **zero** loss when consumer names were masked (vote agreement 0.947, the only clean ablation in the study). The same 8 examples through knot-set Jaccard: **0.987, 0 calls.** |
| 11 | **On a population selected for being dirty, the action is predetermined.** | 23/23 conflict clusters judged "split," while a code-computed intra-cluster reference graph independently showed 0/23 were connected (378 members, **34 edges, 330 isolates**). Agreement with a constant predictor is not capability. |
| 12 | **Evidence moves the distribution, not necessarily the action.** | Adding the reference graph raised confidence in **22/23** units (mean +0.147, max +0.61) and tightened the rank correlation from −0.46 to −0.72 — while only **2** units changed tier and abstentions went 3 → 0. A saturated action list is *less* informative than one with more abstentions. |
| 13 | **Without truth, only a ranking and a public policy can ship — and a borrowed floor may release nothing.** | All 12 type-arm units sat below the borrowed 0.60 confidence floor (four at exactly 0.00, max 0.513) → zero auto-actions. Yet 11/12 held the same tier across three samples. Argmax vs nearest-tier routing agreed only **0.79**, so "one distribution, two routings" is itself a disagreement rate that must be published. |
| 14 | **It does not hold the evidence responsible for being true — reproduced in a second, unrelated domain.** | Permuting coordinates between elements in an SVG probe dropped region accuracy from 0.857 / 0.812 / 0.571 to **0.048 / 0.219 / 0.000** (all below their own majority baselines) while confidence moved only 0.868 / 0.782 / 0.701 → **0.842 / 0.788 / 0.638**. Same signature as #9, different domain: **a coherent falsehood in the state is consumed as eagerly as a truth.** The defence is upstream validation, never a threshold. |
| 15 | **A pruned shortlist can be worse than the full list.** | A separate browser-agent experiment cut a 20-candidate question down to **3** by predicate: the answer went from correct at **0.54** to `none_of_these` at 0.37 with the correct option reduced to 0.31. First-question hit rate fell **62.5% → 37.5%** (n=8; the predicate also introduced one outright wrong choice that had not been wrong without it). Same shape as #9 and #10 — the failure is in the option space, not the model — but here the *remedy you would reach for first* is what caused it. |
| 16 | **Inconsistent summary granularity between levels breaks a hierarchy.** | In the same experiment, segment-level summaries aggregated whole-subtree text while node-level summaries carried only the element's own text: the first question hit **5/8** (including confidence 0.98/0.99 where the target's own text was aggregated up), and the very next question — one level down, same page, same state — answered `none_of_these` in **all five** cases the first had got right. Target located **0/8**. Evidence that exists one level up may simply not exist one level down. |

## What follows from these, in code

1. **Three gates before an axis ships:** a positive case, a positive-vs-negative gap, and a name
   ablation. All three, or it does not ship.
2. **Probabilities are a regression baseline; argmax labels are not.** Compare runs on the
   distribution, never on the winner.
3. **Publish thresholds as parameters with a sensitivity band** (±0.02 in the clustering case, where
   the cluster count swings inside it). Never report a threshold's output as a discovery.
4. **Wire every probability to an action, or delete the call.** A judgment with no executor is a
   constant with extra steps and a latency bill.
5. **Build the constant baseline and the nearest-neighbour baseline first.** If Jev does not beat
   them, the pipeline should not exist. This one rule would have saved the $0.18 routing study and
   the $0.051 role study outright.
6. **Put a decoy option in the examples, or score decoy hits on their own row.** A plausible generic
   option is a confidence-proof trap.
7. **Ablate the truth labels with the input.** Score anonymous arms against translated anonymous ids,
   or every correct answer is scored as zero.
8. **Prove ablation cleanliness with code.** Search the ablated payload for every known identifier and
   abort on a hit. "I deleted that field" is not evidence — qualified names in signatures shipped the
   entire folder tree through a supposedly folder-free arm.
9. **Hand-check every cross-arm derived metric** against one example that should flip and one that
   should not. Two arms with different tier ladders sharing one mapping turned a 2/23 result into a
   reported 22/23, with all raw data correct.
10. **Generate numbers, never transcribe them.** Two hand-copied figures in the report rotted into
    falsehoods. Read from sidecar artifacts, and compute version facts from file mtimes.
11. **Diff before re-running a generator.** Re-running one silently deleted the only hand-written
    section from a 408-line output file.
12. **Automate for a weaker language, not just English.** On the same material with only the state
    language changed: **3/3 correct in English, 1/3 in Chinese** — and both errors carried confidence
    **0.31 and 0.53**, while every correct answer was ≥ 0.82. A ~0.6 threshold would have withheld
    both errors automatically. Keep an English mirror field for judgment; treat the original as
    authoritative for the artifact.
13. **Pin the model version.** `jev-latest` is an alias that drifts across releases. Treat a model
    upgrade as a compiler upgrade: full re-run plus diff.
14. **Measure for degeneracy before spending.** If a constant predictor scores as well as the model,
    the question was wrong (§11 above), and no amount of threshold tuning fixes a wrong question.
15. **Do not assume a shortlist helps — measure that too.** A separate experiment (addendum in
    [Paper 2](../papers/JEV_EMPIRICAL_BOUNDARY_ANALYSIS.md)) cut a 20-candidate question to 3 by
    predicate, and the answer went from correct at 0.54 to `none_of_these` at 0.37 with the correct
    option at 0.31. First-question hit rate fell **62.5% → 37.5%**. This is the mirror image of rule
    10: a shortlist *feels* like it should make the choice easier, and on the one workload that
    measured it, it moved probability mass onto the exit option instead. Send the full list with good
    per-entry evidence, or prove the shortlist beats it.
16. **Keep summary granularity consistent across the levels of a hierarchy.** Summaries that aggregate
    a whole subtree and summaries that carry only an element's own text are not interchangeable: the
    first question in that same experiment hit **5/8**, and the very next question — one level down,
    same page, same state — answered `none_of_these` in **all five** of the cases the first had got
    right. Target located **0/8**. The pipeline broke on the difference between the two summary
    levels, not on the model.
