# Japanese variant — character-profile-driven judgment

The same `Jev → emotion vector → IndexTTS 2.5` path as
[`../emotion-controlled-tts`](../emotion-controlled-tts), organised differently: the character is a
**data file** rather than prompt text embedded in code, and the judgment is compiled into a full
three-phase synthesis schedule instead of a per-segment vector.

| File | Role |
| --- | --- |
| [`yuta_cognition.py`](yuta_cognition.py) | the character — core traits, battlefield context, and the three emotional phases with their base vectors, alphas and pacing |
| [`jev_evaluator.py`](jev_evaluator.py) | the client: builds the question bundle, calls Jev, and compiles answers into a TTS schedule |

## The question bundle

One request, four independent judgments, all reading the same state. The state is assembled from the
character file rather than hard-coded:

```python
state = {
    "character": {
        "name": profile["name"],
        "traits": profile["core_traits"],
        "battlefield_situation": context,
    },
    "turn_context": {
        "japanese_monologue_segment": segment_text,
        "dramatic_phase": phase_hint,
    },
}
```

| Key | Primitive | Asks |
| --- | --- | --- |
| `guilt_and_self_reproach` | Noul | Does the speaker express intense self-blame or self-loathing about his own decisions and the death of allies? |
| `fatal_resolve_and_wrath` | Noul | Does he show cold, unwavering resolve and a willingness to shoulder all sins to end the threat? |
| `domain_authority_and_focus` | Noul | Is he unleashing peak power, chanting with absolute authority and composure? |
| `dominant_emotion` | Choice | Which of three emotional categories dominates the **acoustic delivery**? |

Note what the questions actually target. The `Choice` question asks about *delivery*, not about the
character's feelings, and the three `Noul` questions are intensity readings that can all be high at
once. That is deliberate: the output is a vector, not a label, and a single categorical answer cannot
express "grieving and lethal and composed" — which is precisely the state this scene is in.

## Compiling judgments into a schedule

The phase's base vector is modulated by the probabilities, using the same division of labour as the
Chinese variant — Jev supplies intensity, code owns the coefficients:

```python
base_vec = list(rec["emo_vector"])
base_vec[1] = round(min(1.0, base_vec[1] * (0.8 + 0.4 * p_wrath)),  2)  # anger / lethal intent
base_vec[4] = round(min(1.0, base_vec[4] * (0.8 + 0.3 * p_guilt)),  2)  # disgust / self-loathing
base_vec[5] = round(min(1.0, base_vec[5] * (0.8 + 0.3 * p_guilt)),  2)  # depression / self-blame
base_vec[7] = round(min(1.0, base_vec[7] * (0.7 + 0.4 * p_domain)), 2)  # calm / authority
```

Each compiled segment carries its judgments **and** its parameters, so the produced audio can always
be traced back to the probabilities that shaped it:

```json
{
  "phase_id": 1,
  "jev_judgments": { "p_guilt": 0.95, "p_wrath": 0.25, "p_domain": 0.05,
                     "dominant_emotion": "melancholic_agony" },
  "tts_params":    { "emo_vector": [...], "emo_alpha": 1.0, "duration_factor": 0.95, ... }
}
```

That pairing is the part worth copying. Without it, an unexpected-sounding clip forces you to
re-derive whether the model or the mapping produced it.

## Two problems in the shipped code

Both are the kind that survive review because they look like defensive programming:

**1. `MODEL = "jev-latest"`.** The multipliers above were tuned against one model's output
distribution, and `jev-latest` is an alias that moves with releases — so the synthesizer's tuning can
drift with no code change. **Pin `jev-1.13.0`.** This is the same discipline the SVG probe in this
repository applies on purpose.

**2. A silent fallback to a constant.**

```python
except Exception:
    return self._fallback_ground_truth(phase_hint)
```

The fallback returns fixed probabilities keyed on the phase label. It keeps a synthesis run alive
when the network is down, which is the right instinct — but it emits a **warning to stdout**, and a
run that silently degraded produces audio that is indistinguishable downstream from a run where Jev
answered. In any measurement context this must be a hard failure, or the A/B you report may not have
used the model at all. Compare the ablation-hygiene rules in
[`../../papers/JEV_EMPIRICAL_BOUNDARY_ANALYSIS.md`](../../papers/JEV_EMPIRICAL_BOUNDARY_ANALYSIS.md)
§T12: prove the mechanism ran before trusting the number.

## Running it

```bash
export TYPESAFE_API_KEY=...
python jev_evaluator.py     # prints the compiled 3-phase schedule as JSON; no synthesis
```

This is a **plan compiler**, not a synthesizer: it produces the schedule that IndexTTS consumes. The
A/B audio that demonstrates the resulting sound was produced by the Chinese variant — see
[`../emotion-controlled-tts`](../emotion-controlled-tts) and
[`../../assets/audio`](../../assets/audio).

The reference voice for this variant is
[`../../assets/audio/reference_voice_10s.wav`](../../assets/audio/reference_voice_10s.wav). No rights
to it or to the character dialogue are claimed.
