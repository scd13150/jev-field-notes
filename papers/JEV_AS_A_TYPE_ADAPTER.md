# Jev as a Type Adapter

### Bridging natural-language meaning and deterministic software

**Model:** `jev-1.13.0` · **Endpoint:** `POST https://api.typesafe.ai/v1/systemone`
**All figures in this document were measured on the public API unless marked "published by TypeSafe".**

---

## 0. Thesis

Jev is usually introduced as "a small, very fast model." That description is misleading, and
believing it leads to the wrong conclusion — that Jev is a cheap substitute for a chat model, which
makes it look underqualified, because it does not count, does not generate, and does not look at
images.

Jev is better understood as one thing:

> **A type adapter between natural-language semantics and deterministic code. It turns questions of
> meaning into typed, probabilistic function calls that software can evaluate safely inside loops.**

Reframed that way, the engineering question stops being "what can it replace" and becomes "where is
the boundary, and what may legally cross it." This paper is about that boundary: the hole it fills,
the structures the hole was blocking, and the places it must never be used.

---

## 1. The hole: no feedback signal between language models and code

The recurring situation: a program needs to know something **semantic**, and all it holds is text.

```
"Did the protagonist actually appear in this shot, or is she only mentioned in the dialogue?"
"Which element on this page is the submit button?"
"Is the price quoted in this marketing copy the same as the price rendered in the checkout DOM?"
```

Code cannot answer these — it has no semantic comprehension. Handing them to a language model
produces a well-known shape of friction:

1. Ask the model for prose, or for JSON.
2. Parse the output — and write the repair-and-retry path for when the schema breaks.
3. Extract the conclusion from the text. The model said three sentences; which one is the verdict?
4. **And the critical one: you have no numeric signal for how much to trust this answer.**

Item 4 is not a detail. It determines the shape of the whole system. Without a signal, engineering
degrades into three heuristics:

- **Counting as a criterion** — "retry twice, then escalate to a human."
- **Keyword matching as a criterion** — instruct the model to end with `VERDICT: PASS`, then grep
  for it. This fails in an instructive way: `VERDICT: NEEDS WORK` also contains the token, and a
  script that greps for the word approves it.
- **Or dropping the check** — because every judgment is too expensive to run where it matters,
  the check becomes optional and then unused.

These are not laziness. They are what "no boundary" looks like in code. There is no threshold to
compare against, so the only available predicates are counts and string membership.

**This is the hole Jev fills.** It does not consume prose to produce prose. It consumes text or JSON
and returns types.

---

## 2. Mechanism: one request = one state + a set of judgments

```
POST https://api.typesafe.ai/v1/systemone
{ "state": <text or JSON>, "model": "jev-1.13.0", "questions": { ... } }
```

Three primitives, distinguished by the *shape* of the answer each one returns:

| Primitive | The question asked | Returns | Typical use |
| --- | --- | --- | --- |
| **Choice** | Which of these candidates is it? | The selected key + **the full probability distribution** + confidence | Dispatch, selection, routing |
| **Score** | Where does this fall on a scale? | Tier coordinate (may land between tiers) + distribution + confidence | Grading, ranking |
| **Noul** | What is the probability this statement is true? | 0.0–1.0, **no confidence metric** | Gatekeeping, detection, abstention |

The decisive property is that **the answer space is supplied by the caller**. A `Choice` question
returns one of the keys you listed; it cannot invent a category you never defined. The entire
parse–validate–repair layer therefore does not exist, because there is nothing to repair.

Two consequences that are easy to miss:

- **`Noul` has no confidence, and `Choice`/`Score` always have one.** They are not
  interchangeable, and there is no arithmetic identity between them —
  `P(x) ≠ 1 − P(not x)` across different primitives. Mixing thresholds between them is a bug that
  produces plausible-looking numbers.
- **`Choice` probability does not answer "is there a good option at all."** Its distribution always
  sums to 1 over the candidates you supplied, so a set of bad options still has a first-ranked
  member. "Is any of these right?" is a separate `Noul` question, and it has to be asked
  separately.

That second point was verified the hard way: in a nine-option routing task with one plausible
decoy, the zero-shot arm placed **158 of 158 calls** on the decoy at 0.65–0.84 confidence for
**0.000** accuracy. See
[`JEV_EMPIRICAL_BOUNDARY_ANALYSIS.md`](JEV_EMPIRICAL_BOUNDARY_ANALYSIS.md) §T11.

---

## 3. Expressiveness beyond a classifier

The common underestimate is to read `Choice` as "pick one of six." The fields are richer than that:
`instructions` and `criteria` values may themselves be structured JSON.

```json
"criteria": {
  "billing": {
    "what":  "charges, invoices, refunds, subscriptions",
    "not_for": "shipping status, account login",
    "examples": ["I was charged twice", "Where is my refund?"]
  }
}
```

- **`Choice` options can carry negative definitions and examples** — i.e. you can write the
  boundaries of a type, not just its name.
- **`Score` tiers can carry `signals[]`**, which turns a score into a readable rubric rather than an
  opaque number.
- **An option's value can be a subtree** — you can lay out a classification tree so the model sees
  what is inside a branch before choosing, and let code walk the tree.
- **A shared field shape** `field = {name, type, unit, description}` can drive `Noul` validation,
  `Choice` selection and `Score` grading from one definition.

And a request can carry **dozens to hundreds of questions in parallel over the same state**. The
marginal cost of an added question is close to the tokens of the question itself. TypeSafe's
published measurement for 13 questions batched into one request is **11.5× cheaper and 9.6× faster
than 13 separate calls, with unchanged answers**.

That enables a programming style that is initially counter-intuitive, **speculative fan-out**: do
not first decide whether a question needs asking. Ask the **entire plausible intent space** once,
then discard the branches code does not use. Ask what should be done to the light *before* knowing
whether the user wants to control the light.

---

## 4. Structures the hole was blocking

This is the substantive part of "what Jev does." It is not that an existing flow gets faster. It is
that three structures which were previously unavailable become implementable.

### 4.1 Localization instead of a conclusion

Before: one review produces a prose report ending in "pass / needs work."
After: twenty shots each get a float. **This is the first time it is possible to say "shot 4 has a
problem" rather than "this episode has a problem"** — and therefore the first time code can act on
the answer, because "shot 4" is a value that indexes something.

### 4.2 Self-converging loops

With a numeric value, the loop becomes "re-run only the items below threshold, until they pass or
until two consecutive rounds are unchanged." The previous "retry at most twice, then hand it to a
human" existed precisely because there was no signal for *is this round more certain than the last
one*. A threshold is what converts a retry counter into a convergence criterion.

### 4.3 Abstention as a first-class result

Confidence (`Choice` / `Score`) and probability (`Noul`) allow the system to say **"I am not sure
about this one — do not process it automatically."**

| Band | Action |
| --- | --- |
| High confidence | Execute autonomously |
| Medium confidence | Execute, flag for review |
| Low confidence | **Do not execute**; escalate to a human |

This is structurally impossible with prose: prose has no threshold. The practical payoff is
triage — a hundred variants do not need a human to read a hundred of anything, only the ones the
machine marked.

The measured form of this is in the boundary paper: routing on confidence routed 24 items to
`trust_and_keep`, 6 to `escalate_to_human_review`, and every escalation could be traced to the
specific question that caused it. **A probability only becomes a product once it is wired to an
action.**

### 4.4 Distributions as values, not just a winner

TypeSafe publishes that `jev-1.13` is highly consistent — semantically similar inputs produce
quantitatively similar outputs. This means a fixed question set produces a **probability vector
that can be used as an embedding**: similarity, deduplication, nearest neighbour, or as features
for a downstream model. Reading only the argmax throws away the most informative part of the
answer.

With one measured caveat that changes how such a vector may be used: across 12 independent samples
of 40 classes, the standard deviation of a `Noul` probability was **0.0058 mean**, but the discrete
argmax label agreed only **95%** of the time and a ternary `centrality` bucket flipped on **7.5%**
of samples. **Probability vectors are usable as a regression baseline; argmax labels are not
reproducible enough to be one.** Two runs disagreeing on a label is not evidence that the model's
understanding changed.

### 4.5 Jev can supervise other models

The object of judgment need not be data. It can be another model's output: a prompt, an extraction
result, a reasoning trace, tool-call arguments, a reply. Detect injection, detect hallucination,
detect a malformed tool call, detect policy violation.

Because one judgment costs a fraction of the call being supervised, **this supervision can afford
to sit permanently in the loop** — which is the condition that makes it useful. A guardrail you
cannot run on every request is not a guardrail.

---

## 5. When to use it: five conditions, all required

1. The question is **semantic** — not arithmetic, not format compliance.
2. The evidence is **available in text** (or an upstream step already converts the non-text input
   into text).
3. The judgment **repeats many times** — per shot, per asset, per variant, per request.
4. **An executor exists** — the answer changes something concrete: a field, a branch, a blocked
   release.
5. It must run **reproducibly while no human or coding agent is present**.

Conditions 3 and 5 are the ones most often missed. **A one-off judgment is better served by a
coding agent that can see the whole picture** — that agent has more context and higher quality.
Jev's advantage appears only when the judgment must be re-run after you have left, and must return
the same answer.

Condition 4 deserves its own rule: **a judgment with no executor is decoration.** A discriminator
that returns the same answer for four different inputs is equivalent to a constant in the source
file — zero cost, zero latency. Routing a model call through it is self-congratulation. This failure
mode is common enough that it should be checked for explicitly: build the constant baseline first,
and if Jev does not beat it, delete the call.

---

## 6. When not to use it

| Do not | Why |
| --- | --- |
| Use it to compute anything | Counting, date comparison, duration accumulation, any regex-checkable string test (e.g. "does this field contain a ★"). **Mechanically decidable questions belong in code.** |
| Interpolate `Score` values into a precise quantity | Explicitly prohibited by TypeSafe: the numbers between tiers are not calibrated. `Score` is for thresholding only. |
| Use it to generate text, code or explanation | It is not a generative model, and chaining `Choice` to force generation is slow and poor. The pattern is **LLM generates → Jev types**. It replaces the parsing layer, not the model layer. |
| Feed it images, audio or video | It reads text only. Pixel-level judgments require an upstream step producing description, OCR or DOM text. |
| Dump unrelated context into the state | Larger states degrade accuracy (context rot), and they make errors unattributable. Retrieve and filter first. |
| Ask single-shot questions that need global creative context | See §5, conditions 3 and 5. |
| Use a `Noul` threshold to gate a `Choice`, or vice versa | There is no arithmetic identity between the primitives. `P(x) ≠ 1 − P(not x)`. |
| Use `Choice` alone to answer "is there a suitable option at all" | A `Choice` distribution always sums to 1; it will rank a bad option first. Pair it with an admission `Noul`. |

---

## 7. Failure modes that cost real money

**It is measurably weaker on Chinese and other non-English inputs.** On the same real Chinese
material, with the same English question set and only the state language changed: **3/3 correct in
English, 1/3 in Chinese**. The useful part is that the two wrong answers carried confidences of
**0.31 and 0.53**, while all three correct answers were **≥ 0.82**. A threshold near 0.6 would have
automatically withheld both errors.
→ Practice: **keep an English mirror field for judgment** (the original remains authoritative for
the artifact), and **route on confidence bands**. Writing the *questions* in Chinese is untested;
do not assume it works.

**High confidence is not correctness, and the answer may not be to the question you asked.** A
measured counterexample: the rule was stated explicitly — "the only criterion is whether the
segment name contains ★; do not re-select based on visual quality" — and `inspect` pointed only at
that field, whose value contained no ★. The model returned **0.96 for "yes."** It read the visual
content, decided the shot *looked like* a protagonist moment, and let that meaning override the
mechanical rule it had been given.
→ TypeSafe's first-listed failure mode, "reads too literally," is **bidirectional**: given the
opportunity, it also over-interprets. Boundaries need human spot-checking; a threshold does not
mean you can stop looking.

**Pin the model version as a dependency.** `jev-latest` is an alias that drifts with releases, so
answers can change with no code change. Production should specify `jev-1.13.0`, and a model upgrade
should be treated like a compiler upgrade: full re-run plus a diff.

**State content can argue for itself.** By default the state is not treated as hostile input. If
the object of judgment is a fetched web page, a user comment, or another model's output, injection
and persuasion are real risks.

**Transient failures are normal, not exceptional.** SSL connection drops were observed in practice,
along with rate limiting (429 / 529). Retry and backoff are the caller's responsibility.

---

## 8. Measured numbers (public network, one machine)

| Item | Value |
| --- | --- |
| Price | **$42/Btok input** (= $0.042/Mtok), **output free** |
| Small state, 1 question (~280 tokens) | **p50 769 ms / p90 1380 ms** |
| 4 questions, ~1000 tokens | ~790 ms per call |
| Real workload: 5 shots × 3 judgments = 15 questions | **1.2 s, 4,313 tokens, $0.00018** |
| Reproducibility: same input, 15 runs | Labels stable 15/15; **confidence drifted ±0.12** |
| Context budget | 64k tokens per request; state + longest question 32k |

**Latency caveat.** TypeSafe advertises "real-time, 150 ms." That figure was not reachable on this
machine — the measured figure is roughly 5× that. The practical consequence is a design constraint,
not a complaint: it can do **step-level** judgment (per save, per asset, per variant) and cannot do
keystroke-level or frame-level judgment. The fighting-game application in this repository is built
entirely around that constraint — see §9 and
[`applications/stick-figure-fighter`](../applications/stick-figure-fighter).

Billing detail: the $42/Btok rate is per input token, and output is not charged. In practice the
dominant cost is the state, which is why "retrieve and filter the state before asking" is a cost
optimization as much as an accuracy one.

---

## 9. Minimal working shape

```python
import os, json, urllib.request

def judge(state, questions, model="jev-1.13.0"):
    body = json.dumps({"state": state, "model": model, "questions": questions}).encode()
    req = urllib.request.Request(
        "https://api.typesafe.ai/v1/systemone", data=body, method="POST",
        headers={"Authorization": "Bearer " + os.environ["TYPESAFE_API_KEY"],
                 "Content-Type": "application/json"})
    # exponential backoff: 429 / 529 / transient disconnect are all normal
    ...
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

shots = {...}                      # your state: prepared by code, never hand-copied
questions = {
    "core_visible_%d" % i: {       # one question per instance, all asked in one request
        "type": "noul",
        "instructions": {
            "question": f"In shots[{i}].visual, is the core subject physically present in frame?",
            "rule": "Being mentioned in audio or dialogue does not count.",
            "inspect": f"shots[{i}].visual"},
    } for i in shots
}

ans = judge(state, questions)["answers"]
# everything below is code's job: thresholds, aggregation, localization, write-back, gating
bad = [i for i in shots if ans["core_visible_%d" % i]["noul"] < 0.5]
```

**Note the division of labour.** Jev answers only "did the subject appear in this shot." How high
the threshold is, which items get re-run, where results are written, and whether a release is
blocked are all code. Policy is always explicit; the model supplies judgment only.

The frame-level application of this rule is in
[`applications/stick-figure-fighter/src/jev`](../applications/stick-figure-fighter/src/jev):
because a live round trip is 0.4–1.3 s, the model supplies a persistent intent and code executes it
against live state at 60 Hz, with every millisecond-scale decision — guard height, cancel windows,
whiff punishes — owned by deterministic code.

---

## 10. Conclusion

Treat Jev as "a small model" and the question becomes what it can replace; it will be found
underqualified at every turn, because it does not do arithmetic, does not generate, and does not see
images.

Treat it as a **boundary type** and the picture is clear. It makes *meaning* a value that code can
legally consume, cheap enough to place a boundary everywhere, and reliable enough to report how
much it trusts itself.

The price is that it will sometimes confuse *what you asked* with *what it understood*, and it
sounds certain when it does. That is why it is a boundary, not a judge.
