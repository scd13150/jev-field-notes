# Can Jev partition a drawing? A capability-ceiling probe on SVG line art

**Model: `jev-1.13.0`, pinned deliberately** — the thresholds in this study were tuned against this
version, and pinning is what stops the alias `jev-latest` from moving them underneath the results.
Every response in `results/` records `"model_reported": "jev-1.13.0"`.

Four rounds · ~2.18 M input tokens · **≈ $0.09** total · text-only input (no vision) · baselines are
majority class plus hand-written geometric rules, never another model.

---

## The question

Jev reads text. A drawing is geometry. So the interesting question is not "can it see" — it cannot —
but **how much of a drawing's structure survives being turned into text, and which parts survive
because the model understood them versus because the text happened to spell them out?**

That reframes the input serialization as the independent variable rather than an implementation
detail. The first round runs the *same questions* over the same drawings with the geometry written
five different ways:

| Condition | What the state contains | What it isolates |
| --- | --- | --- |
| `raw_paths` | original `d` strings | the naive baseline |
| `features_anon` | anonymous ids (`e-01…`) + full geometric features | **does it read coordinates?** |
| `features_named` | element names, no coordinates | **is it only guessing from names?** |
| `named_nogeo` | names only | name-only ceiling |
| `scrambled` | geometric features **randomly permuted between elements** | **false-evidence control** |

That last row is the one that matters. Handing the model coordinates that are internally
inconsistent — real-looking numbers attached to the wrong objects — is the only way to separate
"it inferred this from the geometry" from "it produced a plausible answer with the same cadence."

## What it gets right

| Dimension | Result | Depends on |
| --- | --- | --- |
| Containment / paint order | hit rate **1.00**, AUC **1.00**, with positives at 29% and 49% — not winnable by answering one side constantly | coordinates (paint order does not even need them; it reads list position) |
| Grouping / attribution | ARI **0.94–1.00** when the `<g>` tree is named, versus **0.00–0.69** from geometry alone | the artist's own grouping, or an explicit label |
| Extent (`Score`) | Spearman **0.93–0.96**; absolute tier hit only 0.43–0.76 | coordinates |
| Touching / crossing / same-object | AUC 0.81–0.95 carries information, but hit rate against baseline is −0.02 to +0.07 | class skew — do not read hit rates here |

## What it gets wrong, and why that is the useful part

### 1. It does not hold the evidence responsible for being true

This is the finding worth carrying into any pipeline. Region classification (nine-grid placement)
was run with real coordinates and then with permuted coordinates:

| Drawing | Real coords: hit | Real coords: confidence | Permuted: hit | Permuted: confidence | Its own majority baseline |
| --- | --- | --- | --- | --- | --- |
| `abstract_nesting` | 0.857 | 0.868 | **0.048** | **0.842** | 0.286 |
| `house_scene` | 0.812 | 0.782 | 0.219 | 0.788 | 0.250 |
| `kick_figure` | 0.571 | 0.701 | **0.000** | 0.638 | 0.357 |

Accuracy collapses below every drawing's own majority baseline while **confidence barely moves.**
The model has no capacity to suspect that the coordinates contradict each other. State says it, so
it infers it.

The converse is also measured and is the reassuring half: given names with *no* geometry
(`named_nogeo`), region confidence is only 0.35–0.42 with high-confidence coverage 0.00–0.07. **When
there is nothing to read, it does not bluff.**

> **Confidence measures whether there are usable clues in this state. It does not measure whether the
> clues are true.**

Consequence for a real system: the upstream serializer must guarantee its own correctness. This
project makes that a hard gate before any call — a geometry kernel plus parsing assertions in
`src/selftest.py` (circle area within ±1.2%, a known nesting depth of exactly 4, family detection,
`mullion ⊂ window-frame`, `door ⊂ wall`, group-truth inheritance, corner statistics).

### 2. Two reasonable definitions of "layer" fight each other

`nesting_layer` (how many closed outlines enclose this element) is pure geometry. `scene_layer`
(far / mid / near) is an artist's convention. Give both names *and* coordinates and `nesting_layer`
scores 0.594 on `house_scene` — **below** the 0.844 you get by always answering "one layer," and its
macro-F1 exactly equals the constant answer (0.229 vs 0.229). On `kick_figure` macro-F1 0.271 is
below the constant's 0.481.

The names pull it toward semantic depth ("a wall is background, so it belongs on an outer layer"),
so it stops answering the question that was asked. On the purely abstract drawing, where no semantic
reading exists, named macro-F1 (0.532) beats the constant (0.191) by a wide margin.

**It is judging — just with a different but equally defensible concept of "layer."** Once concepts
collide, giving names is *worse* than giving geometry alone (`features_anon` macro-F1 0.534 >
`features_named` 0.229). Two conclusions: define the concept inside the question, and treat a
name-added arm as a possible regression rather than an upgrade.

### 3. `Score` can rank but cannot bin

`extent` reaches Spearman 0.93–0.96 while absolute tier hit is only 0.43–0.76, and under coordinate
permutation the ordering **inverts** (−0.58 to −0.03). Use it to compare and threshold. Do not read
the tier number as a measurement — which is exactly what the primitive's documentation says, now
confirmed on our own data.

### 4. Reading order is not using order

Round 2 assigned parts to objects at **1.000** (10–11 classes). But the true stroke order alone was
worth **+0.003** — the information was legible and carried no weight. Round 3 asked it to guess the
next stroke while the pen was still moving: **0.083 against a random baseline of 0.204.** Worse than
chance. Legibility is not the same capability as use.

### 5. These failures line up with the vendor's own published jaggedness

The behaviours above are the ones TypeSafe documents for 1.13 (literal reading, concept collisions,
count-type judgments pinned by their definition). Nothing here contradicts the manufacturer's
guidance, which is the outcome you want from an independent probe: either the documented limits
reproduce, or you have found something new. Section 5 of the Chinese README maps each observed
failure to the corresponding published item.

## The two rules this project ended on

1. **Hard facts stay in code.** Coordinates, bounding boxes, arc lengths, corner angles, containment,
   intersection, spacing, family detection — all deterministic, all free.
2. **Anything that is an artist's convention must be named in the state**, because it cannot be
   derived from geometry. And a flat probability distribution should be blamed on the state before
   it is blamed on the model: in round 4, changing *only the input encoding* moved entropy from
   0.772 to 0.554 and the top1−top2 margin from 0.267 to 0.485. The first version's "confidence is
   only 0.35" was an input-encoding failure, not a capability ceiling.

## Honest limits

- There is **no artifact that got better**. The project measures a ceiling; it does not improve one,
  and the README says so directly. Round 4's executor side is the weakest part: "the identity of the
  drawing lives in the plan, and the 36 numbers only decide proportion and placement."
- The raw traces under `results/` fully disclose the prompt and question design. That is intentional
  — it is what makes the numbers checkable — but it is intellectual property, not credentials: no
  key, no Authorization header, and no personal data appears anywhere in them.
- Three to six synthetic SVG fixtures authored for this project; `line-atelier` and `Astra` are cited
  as references only, and nothing from them is vendored.

## Running it

```bash
python -m src.selftest        # offline parsing + geometry assertions, no key, no network
python -m src.run_probe       # round 1: the five serialization conditions
python -m src.run_traces      # round 2: drawing traces (machine redraw / live2d)
python -m src.run_drawloop    # round 3: judgment while the pen is still moving
python -m src.run_jvdrawing   # round 4: let it draw, and price the input side
python -m src.analyze         # metrics + baselines
python -m src.make_viewer     # results/viewer.html
```

`TYPESAFE_API_KEY` is read from the environment only and raises if empty. There is **no mock model
here** — new answers require a key and spend money. Re-runs are free for already-answered questions
because every response is cached on disk.

Outputs: [`results/report.md`](results/report.md), [`results/summary.json`](results/summary.json),
[`results/viewer.html`](results/viewer.html), plus per-round reports
([round 2](results/round2_traces_report.md), [round 3](results/round3_drawloop_report.md),
[round 4](results/round4_drawwith_report.md)).

> **Note on the committed reports.** The results files here are the complete originals. The
> per-call response cache (`results/cache/`, 236 entries) and the raw request/response dumps are
> deliberately **not** committed — they disclose the full prompt design at volume and are
> regenerable. The practical consequence: re-running `src.analyze` on a fresh clone regenerates the
> report from what is present and will produce a **shorter** file, because the cached round-1 and
> round-4 answers are absent. That is not a discrepancy to chase — `selftest` and the code baselines
> are fully offline, and reproducing the Jev figures requires a key and a paid run. Treat the
> committed reports as the record and regeneration as a rebuild.

The full four-round write-up, including the six cross-round facts and the reference-project analysis,
is preserved in Chinese at [`docs/zh/README.md`](docs/zh/README.md).
