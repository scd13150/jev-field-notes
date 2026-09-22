# Empirical Boundary Analysis of Jev 1.13

### A case study in Unity Mono binary analysis, and in finding the line between a model and a truth table

**Target:** a shipped commercial title — Unity (recent LTS), **Mono** backend, Windows x64
**Model:** `jev-1.13.0` (TypeSafe)
**Scale:** 8,000+ API calls · 17,156,453 input tokens · **$0.7206** net spend ($42/Btok, output
unbilled) · p50 **383 ms**, p90 **806 ms** · error rate **0.0%**

---

> **Note on identifiers.** Every class, field, asset and script identifier below has been replaced
> with a stable neutral alias, and the analysed title is not named. The originals are withheld to
> respect the source: the work is a commercial release, and reproducing its internal identifiers
> would publish its structure and make it trivially identifiable, which is not what this study is
> for. Aliases preserve the original spelling and **length**, so structural statements and every
> count remain exactly as measured — the aliasing changes names only, never a number. The numbers
> were verified invariant against the pre-sanitization text: 679 numeric tokens unchanged, the only
> differences being the removed engine and title version strings.

## 0. Why this study exists, and how to read it

Most published evaluations of a decision model use labels a human produced. That makes the result a
measure of agreement with an opinion, and it makes the interesting question unanswerable: when the
model and the annotator disagree, which one read the artifact correctly?

This study was built to avoid that. The subject is a shipped Unity Mono build, which means large
parts of it have **ground truth that is not an opinion**:

- **Instruction flow.** 3,959 method bodies and 82,765 IL instructions were walked
  deterministically, with all 3,322 branch targets resolved. What a numeric field *does in code* —
  gated by a branch, scaled by arithmetic, passed as an argument, returned, or never read — is a
  fact about bytes, not a judgment.
- **Byte layout.** 168 assemblies and 78,621 fields were re-modelled from ECMA-335 metadata and
  validated against 11 `SerializedFile` asset containers. A field size that is wrong by one byte
  shifts every following field, so "parses to exactly the object's end" is a strong proof rather
  than an approximation.
- **Object references.** 16,606 object references were resolved through their `fileID` → externals
  table and `path_id` → `m_Name` maps.

With those three sources, every Jev result in this paper can be scored against something that would
have been the same had Jev never been called. That is the point of the study, and it is why its
most valuable output is a list of places **not** to ask the model.

**Structural honesty note:** the 8,000-call ledger is a shared append-only log written by several
parallel analysis agents, so cross-run totals are a *trend*, not an attribution. A run's own cost
is the difference in its own statistics, and where a per-benchmark figure is quoted below it is the
cache-key sum for that benchmark.

---

## 1. Constraints that held for the entire study

- The game directory was **read-only throughout**. Nothing was ever written back to it.
- Scope was architectural understanding and de-obfuscation pipelines. **No DRM, licensing or
  payment-validation circumvention of any kind.**
- The API key existed only in the environment variable `TYPESAFE_API_KEY` — never printed, never
  logged, never committed. (It is also not in this repository.)
- The analysis was scope-limited with the operator up front to (1) architecture comprehension and
  (2) a reusable pipeline for other Unity Mono titles. Ink story extraction, save-game value
  mining and mod-injection points were explicitly **out of scope** and stayed out.

---

## 2. The operating principle, and the two times it was corrected

The principle was set before any analysis, after one early mistake: the first approach was to have
the model restate .NET metadata, which is an anti-pattern TypeSafe names directly — an assembly *is*
a fully typed table already.

> **Anything confirmable from bytes, tables or files is done in code. Jev is asked only questions
> that have no truth table.**

This is not a posture; it is the conclusion the measurements forced, and it was corrected twice by
measurement:

- **It was too permissive about "semantic."** A question can look semantic and still be answered
  from the identifier text. The name-ablation study (§4, T7) exists to detect exactly this, and it
  found the leakage was large.
- **It was too strict about "no truth table."** A question can look unanswerable by code and in fact
  be fully answerable by a cheap deterministic probe — the IL consumer probe computes 245 labels in
  8 seconds for $0. The rule should have been *"confirmable from bytes or cheaply computable"*.

The refined version, stated so that it can be falsified rather than agreed with:

> **Code owns bytes, tables, files, geometry and arithmetic. Jev is asked only where an answer
> remains genuinely ambiguous after all deterministic evidence is in the state — and any such
> question must first be compared against a constant baseline and a nearest-neighbour baseline.**

---

## 3. Deterministic results, for calibration of what "done" means

These numbers involve zero API calls. They are here because they define what the state can be
trusted to contain, and because two of them were found by the *deterministic* validation layer
rather than by the model.

| Layer | State | Evidence that it is right, not merely running |
| --- | --- | --- |
| Code / IL | Complete | 168 assemblies / 78,621 fields / 562 real types; **4,016 of 4,016 method bodies walked to a terminator whose position exactly equals the declared code size** (which is how two silent desyncs were caught: a fat-header offset error and compressed-integer endianness) |
| Assets | Complete | All 11 `*_Data` SerializedFiles have `_enable_type_tree = False`, so layout was synthesised from the DLLs; predicted size correct for **1381/1381 = 100%**; of 5,229 objects, **4,658 exact**, 21 mismatch, 12 partial, 538 blocked |
| Values | Three layers joined | 562 IL constants (programmer defaults) ↔ 987 authored numeric fields (designer-tuned values; **27 exist only in the asset**) ↔ 25/246 save-file keys resolvable to real fields, with 13 uniquely named and the rest marked ambiguous rather than silently accepted |
| Semantics / architecture | Complete, re-validated | 60 behavioural clusters, 12 live axes, call edges at two granularities; behavioural clustering vs directory structure **NMI 0.5021** |

Three discovered serialization rules were *measured*, not assumed:

- A `UnityEngine.Object`-typed field is a 12-byte PPtr (265 objects had stalled on this type name).
- Delegates (`Func`/`Action`/`Predicate`) and plain interface fields do not participate in
  serialization. Reading `TMP_Text`'s `[SerializeField] protected ITextPreprocessor` as a PPtr
  shifted every following field — fixing it moved MISMATCH from **404 to 21**.
- Types using `[SerializeReference]` carry 8 extra bytes after their last declared field; the bytes
  were observed as `[2, 0]` and are published **raw and unnamed**, because what they point to is not
  proven.

The single largest correction in the study was a metadata table error: `0x1D` was read as MVAR
when ECMA-335 II.23.1.16 is a *sparse* table (`0x17` is unassigned, so `0x18`=I, `0x19`=U,
`0x1B`=FNPTR, `0x1C`=OBJECT, **`0x1D`=SZARRAY**, `0x1E`=MVAR). Every `T[]` field had been read as a
generic parameter, consuming the following bytes: **1,635 of 78,621 fields had the wrong type** —
`ScriptsCollection._scripts` came out as the string `m18` instead of `ScriptData[]`. It was
confirmed by checking the raw signature blob bytes directly, and after the fix the corrupt count went
**1,635 → 0**.

Two of these are worth carrying to any similar project:

- **A cache hit is not a cache correctness.** A run reported "562 hits, 0 calls" while feeding a
  dossier file generated *before* the metadata fix. The input was stale, the cache was honouring it,
  and the output looked healthy. Semantic-layer inputs now force a cache-attribution re-check.
- **A claim can rot.** Two passages in the generated report still asserted that asset balance data
  "requires a parser this pipeline does not have" while the parser existed. Both now read from a
  sidecar artifact (`out/authored_values.json`) instead of a hand-copied number. Numbers in reports
  must be generated, not transcribed, because transcription decays silently.

---

## 4. Benchmarks

Each entry states design, sample, result and reproduction. Every figure is read from the artifact
named, never typed in by hand.

### T1 — Repeated-measurement stability: probabilities stable, labels not

40 classes × 12 independent samples (state carried a uid nonce), 400 `Noul` points.

- Standard deviation: mean **0.0058**, p50 0.0043, p90 0.0162, p99 0.0281, max 0.0307.
- Flip rate across 0.5: **1.75%**. Token-by-token output identical 40/40, so this is the model's
  own non-determinism, not transport noise.
- Discrete labels are much less stable: role argmax agreed on only **95%** of samples; a ternary
  centrality bucket flipped on **7.5%**.

**Conclusion: continuous vectors can serve as a regression baseline; argmax labels cannot. A label
changing between runs is not evidence that the model's understanding changed.**

### T2 — Calibration and risk coverage: a threshold is bought with coverage

182 decision points (67 positive / 115 negative), drawn from real rules.

| Threshold | Accuracy | Auto-pass rate | MACE |
| --- | --- | --- | --- |
| 0.95 | **1.000** | 72.5% | 0.0 |
| 0.90 | 0.9879 | 90.66% | 0.011 |
| 0.30 / 0.10 | 0.989 | 100% | — |

**Conclusion: an axis is not "right or wrong," it is "wrong by this much at this pass rate."
Shipping any axis requires publishing its pass rate alongside it.**

### T3 — Embedding space: neither common heuristic can select a threshold

17 dimensions × 562 types.

- Silhouette rose **monotonically** from 0.3281 to 0.4976 as cluster count went 24 → 308. It is
  biased in this setting and cannot select a threshold.
- Resampling ARI stayed in 0.7779–0.9139 with **no peak**. Stability cannot select one either.
- At the shipped threshold of 0.72: 56 clusters, largest 52, 6 singletons, silhouette 0.3825, ARI
  0.8491 — and the cluster count swings within ±0.02.

**Conclusion: "60 subsystems" is one reading at a chosen resolution, not a discovered fact. A
report must publish the threshold as a parameter, with a sensitivity band.**

### T4 — Call edges: wide is not heavy

The widest cross-cluster edge reproduced across **126 call sites** but covered only **6 distinct
type pairs**; property-accessor share was 0.0 (zero accessor call sites); generated-code leakage
count 0.

**Conclusion: ranking by call-site count alone misreports concentrated fan-out as broad coupling.
The edge table therefore reports both "widest" and "heaviest."**

### T5 — Routing: turning abstention into an action

30 cases, confidence floor 0.6, action chosen by score routing rather than argmax.

- Score routing produced `trust_and_keep` 24, `escalate_to_human_review` 6, `flag_for_rename` 0.
- It disagreed with the argmax route on **2 cases**; the confidence gate additionally triggered
  **14 escalations, all 14 localizable to a specific question**.
- Before the change, the same call reported only argmax class counts — no action, no middle band,
  and a confidence value that was computed and discarded.

**Conclusion: a probability becomes a product only when it is wired to an action. "I don't know"
must land on a concrete next step.**

### T6 — Field-level semantics

- `e1`: 27 anchor fields × 4 axes — 116 calls / 130 hits / $0.0103 in one configuration, 130 calls /
  0 hits / $0.0117 in the other.
- `e2`: unlabelled vocabulary induction (87 calls / $0.0079) — cluster 0 resolved to `save_load` at
  0.88 confidence; a `none_of_these` option captured the ungroupable interface cluster
  (`IAudioService`, `IDialog…`).
- `e3`: two natural-language questions evaluated for retention (76 calls / $0.0024) —
  `lit_reveals_responsibility` **rejected**, `lit_names_domain_object` **kept** (positive 0.33–0.87
  vs negative 0.02–0.06).

**Conclusion: field granularity still discriminates, but the vocabulary must be proposed by the
model and then curated by a human; applying namespace labels directly misassigns interface
clusters.**

### T7 — Name ablation: the study's most important result

27 anchor fields × 4 axes × 3 conditions: true names preserved, names masked (`Class_NN.field_NN`),
names replaced with deceptive ones. Cost **351 calls / 617,392 tokens / $0.0259**.

| Axis | Gap: named | masked | deceptively named | after grounding (named / masked / wrong) |
| --- | --- | --- | --- | --- |
| `designer_constant` | +0.67 | **+0.24** | **−0.12** | +0.72 / +0.72 / +0.71 |
| `player_visible` | +0.79 | **+0.27** | **−0.44** | +0.01 / +0.01 / +0.00 |
| `normalized_ratio` | +0.79 | +0.58 | −0.43 | +0.64 / +0.55 / +0.37 |
| `persistent_progress` | +0.85 | +0.80 | +0.72 | +0.81 / +0.81 / +0.79 |

- Name contribution for `designer_constant` was **0.427**. Of 30 field-axis points, **17** crossed
  above their masked value once a deceptive name was attached.
- `persistent_progress` lost only +0.05 and barely moved under a wrong name — **genuine behavioural
  grounding**.
- **A question pointed at incomplete evidence is worse than no pointer.** One axis was redirected to
  "is this field reachable to a serialization sink in the call graph," but `GameSaveData` hands the
  entire object graph to `JsonConvert` and no method touches the field individually. The model
  correctly answered the narrower question and the axis collapsed from +0.79 to **+0.12**. Adding
  the real save-file evidence restored it to **+0.81 with no dependence on the name**.
- **Some questions have no evidence in the artifact at all.** After grounding, `player_visible` kept
  only +0.01 — leaderboard values are rendered by the platform overlay, and there is no UI sink inside
  `Assembly-CSharp`. Its +0.83 "apparent understanding" was the name. **The honest response is to
  narrow the claim, not to raise the threshold.**

**Conclusion: gap size is not evidence of grounding. Masking identifiers is a cheap test ($0.026)
for the source of a semantic claim, and it is the only boundary between "the model understood this
number" and "the model read the word `Score`."**

### T8 — Abstention as intelligence

Of the 60 most central types, 21 were judged "the name is broader than the responsibility," including
`ICurrentStageDataProvider` (score 1.12, confidence **0.00**), `ICurrentChecklistProvider` (1.08,
**0.00**) and `ICurrentActorProvider` (0.98, **0.00**) — precisely the `*Provider` naming pattern
that had been independently flagged as suspicious.

**Conclusion: in reverse engineering, "I cannot tell what this type does" is a hook location. It is
an artifact, not a failure.**

### T9 — Reproducibility after the metadata fix

After repairing 1,635 broken field types, the whole semantic layer was recomputed:

- **Unchanged:** the set of 12 live axes, role entropy 2.41 → 2.407, all 5 known-positive controls
  ≥ 0.80, NMI 0.4973 → **0.5021**.
- **Changed:** 56 → 60 clusters; naming conflicts 21 → 23; of 984 pairs that had been co-clustered
  before the fix, only **658 (67%)** still were — pair Jaccard **0.51**.

**Conclusion: the headline finding (behaviour ≠ folder) was not an artifact of that bug and can be
cited. But *which two types share a cluster* varies with the input version, so any claim that depends
on individual members must be re-tested after a correction.**

### T10 — External ground truth from instruction flow

This is the one benchmark whose labels came from neither a human nor the model. `load_bearing_probe.py`
walked 3,959 method bodies and 82,765 IL instructions (all 3,322 branch targets resolved) and, for
each inspector-visible numeric field, found its nearest consumer: a comparison or conditional branch
means *gate*, arithmetic means *scale*, a call argument means *argument*, a return means *returned*,
and nothing within 40 instructions means *inert*.

Census: 184 persistable types / 247 numeric and boolean knobs, distributed as **103 gate / 47 scale /
80 argument / 14 returned / 1 inert** (2 undecidable rows dropped → 245 scored).

**A planned binary question was rejected rather than dressed up.** The original design asked whether
designer-modified values are "load-bearing"; the census answered **246/247 are read by code**, leaving
one negative case. A 27/27 positive class can be passed by answering "yes" always. The benchmark was
replaced with a five-way role classification, and the baseline therefore becomes the majority class
(0.42), not chance (0.2).

Cost: 245 rows × 2 arms × 3 repetitions = **1,470 requests / 1,210,002 input tokens / $0.05082 /
0 errors**.

| Arm | top-1 (majority vote) | per-sample | mean p(true) | 3-sample agreement | vs 0.42 baseline |
| --- | --- | --- | --- | --- | --- |
| named (true name + sibling fields) | **0.588** (144/245) | 0.578 | 0.504 | 0.971 | exact two-sided binomial **p ≈ 0** |
| anon (`Class_NN.field_NN`) | 0.302 | 0.302 | 0.324 | 0.895 | significantly **below** baseline (p = 0.0002) |

- **Name contribution: +0.286.** Masked, it is 0.12 *worse than always answering "gate"* — it does
  not merely get dumber, it **systematically answers "gate" for non-gate fields** (argument 0/80,
  scales 0.043). This is stronger than T7: T7 halved a gap; here masking fell below a trivial baseline.
- Per class (named): gates 0.806, argument 0.500, scales 0.447, returned 0/14, never_used 0/1. The
  main confusion is argument ↔ scale, which is one chain's two ends.
- **Confidence is usable and monotone.** Truncating by top probability: coverage 100% → 0.59,
  60% → 0.69, 40% → 0.76, **20% → 0.82**. "Listen to it only when it is sure" genuinely buys
  accuracy here, and the threshold is a free post-processing parameter.
- **A label defect that is disclosed, not hidden:** 7 of the 14 `returned` rows were stably answered
  "gate." The probe sees one method body, so accessors like `get_MaxZoom` and `IsDataValid` are
  labelled "returned" while the code that compares them lives one hop away at the call site.
  Crediting by caller role moves 0.588 → **0.616**. Both numbers are recorded in
  `accessor_artifact`; only **0.588** is reported externally.
- The `never_used` class has one member. **0/1 is not evidence and is not cited.**

**Conclusion: with no truth table available and only names and types visible, Jev's judgment about
what a number does in code is significantly better than the majority-class baseline — but +0.286 of
that advantage comes from the name, and without names it is worse than a constant predictor. It is a
decoder of naming convention, not an interpreter of IL semantics. To infer IL semantics, run the
probe: zero calls, eight seconds.**

### T11 — Reverse routing: give eight examples, can it learn which file belongs to which slot?

The idea: derive a known→unknown mapping. Known = each file's own structure plus the TextAsset slots
declared in the assembly. Unknown = which field actually references it. The truth is not
human-labelled: `ink_wiring.py` resolved 16,606 PPtrs through their externals and name tables to get
every story file's referrer.

**First, what came free — and this is the real architectural result:**

- All **158/158** ink files are referenced (zero dead files), by only 5 classes and **8 declared
  slots**: `ActorAppearData.AppearTermsInk` (79), `ActorData.PersistentTermsInk` (36),
  `ContextSceneScope._scriptDatas` (23), `ActorAppearData.AppearScript` (15),
  `StageData.StageStartDialogue` (12), `StageData.StageStartMessages` (11),
  `InteractivePhraseController._inkFile` (6), `StageData.StageEndDialogue` (3). A ninth slot,
  `ScriptData.ScriptAsset`, is declared but never holds ink — and it becomes the trap below.
- The named Ink↔C# interface is remarkably narrow: of 1,012 knots, only **4** names appear in the
  assembly's string constants (`greeting_terms`, `idle_terms`, `questions`, `snapshot`), each
  across 79/79/79/32 files. The whole corpus contains 1 external function (`GetUserName`),
  1 global variable (`userName`) and 0 list definitions.
- **So "find the wiring by knot name" is a dead end** (the inventory is only 20% decidable, and every
  decidable case lands in the same cluster). The wiring is in the PPtrs, not the names.
- The four non-overlapping knot vocabularies are a file-type fingerprint — classifying a story file
  degenerates into set-similarity lookup.

Jev's three arms (truth = the set of referrers; choosing any one counts as correct; majority-class
constant baseline = 0.52):

| Arm | Accuracy | vs baseline | Rows sharing vocabulary (124) | Rows with none (26) | 3-sample agreement |
| --- | --- | --- | --- | --- | --- |
| zero (9 slots, no examples) | **0.000** (0/158) | p ≈ 0, **below** baseline | 0.00 | 0.00 | 1.000 |
| few (+8 examples) | 0.907 (136/150) | p ≈ 0 | 0.992 | **0.500** | 0.982 |
| anon_few (slots shuffled to `Class_NN.Slot_MN`, same 8 examples) | 0.907 (136/150) | p ≈ 0 | 1.000 | **0.462** | 0.987 |
| — control: **deterministic 1-NN** (knot-set Jaccard, same 8 examples, 0 calls) | **0.987** (2 errors) | — | — | — | — |

- **The zero-shot arm placed 158/158 votes on the trap slot** `ScriptData.ScriptAsset`, and
  confidently (top probability 0.65–0.84, mean p(true) 0.026) — for **0.000** accuracy. This is the
  cleanest instance in the study of **bias, not noise**: coverage truncation cannot rescue it, since
  accuracy is 0.00 at every coverage level. **Selective prediction defends against noise, not against
  systematic prior.**
- The `few` and `anon` arms agreed on **0.947** of votes and scored identically, so **name
  contribution = 0.000.** This is the study's only ablation that lost nothing — it really was matching
  structure to examples. (The shuffled numbering had to be done properly: the first version numbered
  slots alphabetically, from which the model could recover identity.)
- **But the free 1-NN baseline is higher (0.987 vs 0.907)**, and on the 26 rows sharing no vocabulary
  with the truth, Jev scored 0.50/0.46 — **exactly the constant baseline**. Its routing ability equals
  nearest-neighbour lookup plus lexical matching; the part beyond lookup is zero.
- Cost: **1,374 calls / 4,312,326 input tokens / $0.18112** (including a first full round with a
  scoring bug and a 450-call re-run). **Conclusion: that $0.18 should not have been spent** — the
  same task is done by a table lookup at $0 and 8 points higher accuracy.

One real bug surfaced here: the scorer failed to translate the truth labels into anonymous aliases for
the anon arm, so **correct routes were scored zero** — which is where the first version's `anon
acc = 0.000` came from.

**Conclusion: importance routing on the ink side is a problem code had already closed (158/158 owned,
8 slots, 4 vocabularies). Jev is neither more accurate than the lookup there, nor safe in front of a
confident decoy — while also demonstrating that examples do activate structural matching without
consumer names (zero loss under masking, 0.947 agreement). That capability is simply dominated by a
Jaccard function.**

### T12 — "Rename or split?": a judgment with no truth, and three errors caught in the making

The candidates were the only objects in the project that code cannot adjudicate and no truth table
covers: 23 cross-namespace conflict clusters from `map.json` plus 12 types from `audit.json` with
`argmax_level ≥ 1`. The artifact is therefore positioned as a **proposal list with a public policy**,
not a measurement. 35 units × 2 arms (`full` / `no_folder`) × 3 samples = 210 calls, 5.8 s, $0.01531.
The three `Score` tiers *are* the three actions (leave / rename / split), so routing uses nearest tier
rather than a fitted threshold.

**Error 1 — the ablation leaked a channel, which would have invalidated the whole comparison.** The
first `no_folder` arm deleted only the `namespace` field, but every member signature and field
declaration carries fully qualified type names
(`void .ctor(BastionSystem.Core.BastionEventType,bool)`) — **the entire folder tree was still in
the state.** The fix strips dot-qualified names too, and **proves the strip before spending money**:
search the ablated JSON for `ns + "."` for all 106 namespaces and abort on a hit. (Naive substring
matching produces false positives — `ActorsDatabase` contains a namespace word. That is not a leak.)

**Error 2 — two arms shared one tier mapping, inverting a derived metric.** The `no_folder` arm has a
two-tier ladder (tier 1 = "not one module"); the `full` arm has three (tier 2). A single `split_of()`
mapped both through the three-tier path and reported **22/23 flips** where the truth was **2/23**. The
raw routes and per-call distributions were all correct; only the derived metric was wrong.

**Error 3 — the state omitted the decisive evidence.** Cluster entries listed member names and
signatures but not whether members reference each other — which is exactly the evidence for "is this
one module," and it is computable by code for free. `link_graph()` was added: for **all** members of
each cluster, count intra-cluster `depends_on ∪ used_by` edges, connected components and isolated
members, and write that fact table into the artifact alongside the judgment.

**The architectural result that came free, and is worth more than the list itself** — 23 conflict
clusters, computed by code, zero calls:

| Intra-cluster reference graph | Count |
| --- | --- |
| Total members | 378 types |
| Intra-cluster reference edges | **34** |
| Members with **no** reference inside their own cluster | **330** |
| Largest connected component | 6/16, 5/20, 4/22, 4/13 |
| Clusters where the largest component is ≥ half the members | **0/23** |

That is, **`map.json`'s clusters are "embedding looks similar" groups, not call-connected modules**, so
"is this cluster one module" is the wrong question for these objects (the answer is always "split"),
and `graph_rule` is a **constant predictor that cannot serve as a baseline** — the same shape of
lesson as T11: measure for degeneracy before spending.

Two-condition comparison:

| Condition | `full` actions | mean conf full / no_folder | Cohesion flips | conf ↔ edge count | score ↔ edge count | Abstentions (< floor) |
| --- | --- | --- | --- | --- | --- | --- |
| v1, no graph | 22 split / 1 rename | 0.763 / 0.669 | **2/23** | −0.464 | −0.466 | 3/23 |
| v2, graph given | 23 split | 0.910 / 0.978 | **0/23** | **−0.716** | **−0.727** | 0/23 |

- **Given the evidence, it used it:** 22 of 23 units rose in confidence (mean **+0.147**, max +0.61),
  2 units actually changed tier, and the direction matched the evidence (more intra-cluster edges →
  less confident about splitting; Spearman −0.72). With n=23 and edge count collinear with component
  share, this is **directional evidence, not a significance result**.
- **But the routed actions did not move at all** (22 → 23 all "split"), and abstentions fell 3 → 0. A
  list where everything is directly executable carries zero information. On a population selected
  *because* it is dirty, the action is predetermined by the selection; **only the distribution
  survives.**
- Cohesion judgments did **not** come from directory histograms (21/23 in v1 and 23/23 in v2 agreed
  across both arms), which is precisely what the `no_folder` arm was asking. The type arm flipped
  6 of 12 — naming judgments do consume namespaces.
- Agreement with the purely mechanical folder rule (purity < 0.25 split / < 0.40 rename / else leave)
  was **0.478 (11/23)**. The 12 units where Jev overrules the rule are listed in the artifact. This is
  the round's only information beyond the script — and with no truth available, it can only be a
  **review queue**.
- The type arm was identical across runs (cache hits). All 12 have mean confidence below the borrowed
  0.60 floor (4 exactly 0.00, max 0.513), so **under the published policy not one is auto-executed**;
  yet 11 of 12 landed in the same tier across all three samples — here **repetition agreement is a
  better gate than the borrowed floor.** Across the whole test, argmax and nearest-tier routing agreed
  only 0.79 — meaning "one distribution, two routings" is itself a disagreement rate that must be
  published.

**Conclusion: this round proved no new capability; it proved three other things.** (a) Asking whether
a similarity cluster is a module is the wrong question — the right evidence is the 34-edge graph, and
it was already sitting in the artifact for free. (b) When evidence enters the state, the distribution
moves in the right direction, but whether it is allowed to *decide* depends on a truth table that does
not exist. (c) Whether an ablation is clean and whether a metric is aligned must be asserted by code,
never by the author's word — and two of this round's three errors were the author's own code failing
to catch them.

---

### Addendum — a separate experiment: option-space pruning and summary granularity

**This addendum is not part of the study above and its results are not pooled with it.** It comes
from a different project with a different workload, sample size and author: an experimental CDP
browser controller that indexed a live page into a tree and asked Jev to walk it down to a target
element (55 requests / 282,370 input tokens / **$0.0119**, model pinned to `jev-1.13.0`, ground-truth
selectors used only for scoring and never placed in the state). It is included because its two
findings point in the same direction as T11 and the SVG probe, from a third domain — and because one
of them argues against a documented TypeSafe recommendation.

**Option-space pruning degraded the answer.** On `ithome-search`, a 20-candidate question produced
the correct choice `seg#2` at confidence 0.54. The same question with a predicate reducing the pool
to **3 candidates** returned: `none_of_these` 0.37, *view-all* 0.31, correct answer 0.31 — and
selected `none`. Across the run, first-question hit rate was **62.5% (5/8) without predicates and
37.5% (3/8) with them**; in the eight cases the predicate *added one outright wrong choice* that was
not wrong without it. Of nine predicate applications, four genuinely narrowed the view, five were
discarded by an empty-set / below-K-minimum fallback ("half a predicate is not worth writing"), and
one narrowed the correct answer out. Where narrowing worked, accuracy did not change.

So pruning is not merely neutral here — it moved probability mass onto the exit option. That runs
against the intuition that fewer options make the choice easier, and it is consistent with TypeSafe's
own SDK guidance to send the **full** candidate list rather than a shortlist. The distinction worth
keeping: *a full list with good per-entry evidence* and *a pruned shortlist with the same per-entry
evidence* are not interchangeable, and this workload measured the second as worse.

**Abstraction granularity broke the pipeline, not the model.** Summaries at the *segment* level
aggregated the text of the whole subtree beneath them; summaries at the *node* level carried only the
text that element draws itself, plus a count (`holds: reachable 34 / drawn: no text`). Consequence:
the first question (pick the segment) hit **5/8**, including confidence **0.98 / 0.99** on the one
case where the target's own text was aggregated up. The second question (pick the node inside it)
then answered `none_of_these` at 0.57–0.81 in **all five** cases where the segment had been correct —
the target node was located **0/8** overall. The clearest instance: a button that draws the word
"Star" itself, where the segment summary captured "Star" and the intermediate node was an empty
container, so the evidence that existed one level up did not exist one level down.

**The option cap binds, not the character cap.** Across 24 sampled pages, 0% hit the character or 32k
limit first and **100% hit the 255-option cap first**; 4.2% have more than 255 siblings at some
level (max 528). Relatedly, one `Noul` question per entry costs roughly 520 characters per entry —
401 entries would need 209,000 characters against about 10,000 accepted — which makes `Choice` the
only workable primitive for indexing. That is a clean design constraint, and it is the opposite of
what a `Noul`-per-item design assumes.

Stated limits, all from the report's own caveats and not softened here: **n = 8 cases**, one run per
condition, single temperature sample (though one identical request sent 12 times returned the same
answer all 12 times, median 369 ms / P95 910 ms); **3 of the 8 cases had a structural minimum of
8–13 questions against an observation window capped at 6, and those three are not counted against the
model**; and the implementation was internally inconsistent in a way that partly explains the
predicate result — predicates were evaluated against untruncated text while summaries exposed only
the first 200 characters, so a predicate could hit an entry Jev could not see. That is a bug in the
harness, and it means the pruning finding is **suggestive rather than conclusive**.

The tool itself did not reach its design goal and is not published. The measurement is what is worth
keeping.

---

## 5. Measured boundaries

Each of these is a measurement, not an impression.

| | Boundary | Evidence |
| --- | --- | --- |
| **B1** | When names are readable, it reads names. | T7: two axes lost 60%+ of discrimination under masking; deceptive names flipped them negative. |
| **B2** | Given incomplete evidence, it answers the narrower question correctly — and thereby voids an axis. | T7: +0.79 → +0.12. |
| **B3** | A question with no evidence in the artifact is unanswerable. | T7: `player_visible` grounded to +0.01. |
| **B4** | Enumerable things should not be asked of it. | Metadata, signatures, attributes and inheritance are free exact tables; the byte layer made **0 calls**, and IL validation caught 2 silent parse errors that would have polluted every semantic input. |
| **B5** | Fine-grained grouping has limited reproducibility. | T9: 67% pair retention, Jaccard 0.51. Axes stable, members not. |
| **B6** | A cache hit is not cache correctness. | §3: a zero-call run can carry a stale dossier through an entire layer. |
| **B7** | It does not infer data flow; it decodes names. | T10: same 245 rows, 0.588 → 0.302 under masking, **below** the always-"gate" 0.42; arguments 0/80. |
| **B8** | A tag is not a request identity. | T10: counting by tag prefix gave 1,629 requests instead of 1,470, because the tag string `arm:field:rep` collided across different states. **Counting must be by cache key**, or both the spend and the description of what ran silently drift. |
| **B9** | Confidence defends against noise, not against bias. | T11 zero-shot: 158/158 votes on a never-referenced decoy, top probability 0.65–0.84, agreement 1.000, accuracy 0.000. **When an option set contains a plausible-sounding generic decoy, the model will stably commit to it, confidently.** |
| **B10** | Examples activate structural matching, but structural matching ≠ beating a lookup. | T11: 0.907 with 8 examples and zero loss under name masking (0.947 agreement) — yet the same 8 examples through knot-set Jaccard give **0.987 at zero calls.** Every "give it a few examples" task must be compared against a nearest-neighbour baseline first. |
| **B11** | On a population selected for being dirty, the action is predetermined. | T12: 23/23 conflict clusters judged "split," while the code-computed intra-cluster graph independently said 0/23 are connected. Any "agreement rate" against a constant predictor is meaningless here. **Test for degeneracy before spending.** |
| **B12** | Evidence in the state moves the distribution, not necessarily the action. | T12: 22/23 units rose in confidence (mean +0.147, max +0.61), rank correlation tightened −0.46 → −0.72, but only 2 units changed tier. Whether evidence was read must be judged from the distribution, not the route. Conversely, a saturated action list (23/23, zero abstentions) is *less* informative than one with more abstentions. |
| **B13** | With no truth, only rankings and a public policy can be published — and a borrowed floor may release nothing. | T12 type arm: all 12 below the 0.60 floor (four exactly 0.00, max 0.513) → zero auto-actions; but 11/12 same-tier across samples. Argmax vs nearest-tier routing agreed only 0.79. |
| **B14** | **It does not hold the evidence responsible for being true — and this is confirmed by a second, independent probe.** | A separate study on SVG line art ([`../applications/svg-line-partition`](../applications/svg-line-partition)) permuted the coordinates between elements. Region classification fell from 0.857 / 0.812 / 0.571 to **0.048 / 0.219 / 0.000** — below each drawing's own majority baseline — while confidence moved from 0.868 / 0.782 / 0.701 to **0.842 / 0.788 / 0.638**. B9 and B14 are the same failure seen twice, in unrelated domains, with the same signature: **a coherent falsehood in the state is consumed as eagerly as a truth.** The defence is upstream validation, never a threshold. |

---

## 5a. A second, independent probe

B14 comes from a separate four-round study whose subject was not binaries but drawings
([`../applications/svg-line-partition`](../applications/svg-line-partition), model pinned to
`jev-1.13.0`, ~$0.09). It is cited here because it reproduces B9's shape in a domain with nothing in
common with IL metadata, which is what moves a single observation toward a property of the model.

That probe's design is worth noting for a different reason: its independent variable is the
**serialization of the state**, not the question. The same questions ran over the same artifacts with
the geometry written five ways, including a `scrambled` arm carrying internally inconsistent
coordinates — the equivalent, for geometry, of T7's name masking and T11's decoy slot. Where the
questions are fixed, the way the state spells out its own evidence is the variable that actually
moves the answers, in both directions: naming helped on an abstract drawing and *hurt* on a
semantically readable one (0.594 against a 0.844 constant on `nesting_layer`).

---

## 6. The division of labour this study settled on

Reusable as-is:

1. **Code confirms bytes, tables and files; Jev is asked only judgments with no truth table.** T10
   prices this: the deterministic probe produced 245 labels in 8 seconds for $0; Jev spent $0.051 to
   reach 0.588, of which +0.286 came from names.
2. **Every new axis passes three gates: positives, positive-vs-negative gap, and name ablation.** All
   three must pass before it ships.
3. **Use probabilities as a regression baseline; never use argmax labels as one.** Compare runs on the
   distribution.
4. **Publish every threshold as a parameter with a ±0.02 sensitivity band.** Do not claim to have
   "discovered N modules."
5. **Abstention is an artifact.** Confidence 0.00 plus a located question is the next investigation
   list.
6. **After any change to semantic-layer inputs, force a cache-attribution re-check.** Do not read "all
   hits" as "all correct."
7. **Account per run from that run's own statistics.** Aggregate by cache key, never by tag — B8.
8. **Read report numbers from sidecar artifacts.** Hand-written numbers rot; this project rotted twice.
9. **Any "give it examples" judgment gets a deterministic nearest-neighbour baseline first** (T11:
   0.987 vs 0.907, at zero cost). The baseline is not decoration; it decides whether the pipeline
   should exist.
10. **Be careful about decoys in an option set.** A declared-but-unused option made the zero-shot arm
    158/158 wrong *and confident* (B9). Either put the decoy in the examples too, or score decoy hits
     as their own row.
11. **Ablate the truth along with the input.** Labels for a masked arm must be translated into the
     same anonymous ids before scoring, or correct judgments are scored as zero (T11's first version).
12. **Prove the ablation is clean with code.** "I deleted that field" is not proof: the first
    `no_folder` arm still shipped the whole tree inside qualified names. Search the ablated payload
    for every namespace and abort on a hit.
13. **Self-check every derived metric against its own definition.** Two arms with different tier
    ladders sharing one mapping turned 2/23 into 22/23. For any cross-arm metric, hand-compute one
    example that should flip and one that should not.
14. **Before asking "is this a module," compute the reference graph.** Similarity clusters, namespace
    spread and embedding distance are not module evidence — 378 members, 34 intra-cluster edges.
15. **Caveats that live in a generated report must live in the generator.** Re-running a report
    generator silently deleted a hand-added provenance section from the output file (of 408 lines,
    that section was the only non-generated one). **Diff before re-running a generator**; anything
    derivable from file mtimes should be computed, not transcribed.

---

## 7. Reproduction

The original artifact index, mapping every number in this paper to the file that produced it and the
command that regenerates it, is preserved verbatim in the Chinese source record
([`../assets/zh/JEV_CAPABILITY_RECORD.redacted.md`](../assets/zh/JEV_CAPABILITY_RECORD.redacted.md), §7). It is kept in
full because the mapping from claim to artifact is the part most worth checking, and the commands
reference a private working tree.

What *is* reproducible from this repository without the private artifacts:

- The TypeSafe-side contract — one request, parallel independent judgments over a shared state, code
  owning every threshold — in
  [`../applications/stick-figure-fighter/src/jev`](../applications/stick-figure-fighter/src/jev),
  including a same-shaped offline twin so that every measurement harness runs for free.
- The measurement discipline the benchmarks above depend on: derive metrics only from the engine's
  event stream, never from the state that produced them
  ([`../applications/stick-figure-fighter/scripts/spar.mjs`](../applications/stick-figure-fighter/scripts/spar.mjs)).
