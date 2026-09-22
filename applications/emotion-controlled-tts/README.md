# Jev → emotion vector → parametric speech

Turning a model's reading of a character's mental state into an audible change in a synthesizer.

**Engine:** IndexTTS 2.5 (local, BF16, CUDA) · **Model:** `TYPESAFE_API_KEY` against
`https://api.typesafe.ai/v1/systemone`

The synthesizer does not understand dialogue. It can shape a vocal envelope if you hand it
parameters, and the hard part is deciding *which* parameters — that is a semantic judgment about a
character, which is exactly what Jev produces. This directory is the whole path from one to the
other, and the A/B samples that let you hear whether it worked.

---

## The samples

Six files, three A/B pairs, in [`../../assets/audio`](../../assets/audio). Version **A** is IndexTTS
2.5 with no external emotion control (`emo_vector = None`). Version **B** is the same text, same
reference voice, same sampling parameters, with the Jev-derived vector applied. Nothing else differs.

| # | Phase | Text (ZH) | Vector B (8-D) | Pace | A | B |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Self-reproach / self-loathing | 全都是借口……说什么不能留在主战场帮忙，固执己见的不让真希学姐去杀&lt;羂\|JVAN4&gt;索，自以为是的满足一己私欲，放任伙伴无意义死去…… | `[0.0, 0.30, 0.70, 0.10, 0.75, 0.85, 0.0, 0.15]` | 0.95× | [▶](../../assets/audio/part1_self_reproach_A_no_emotion.wav) | [▶](../../assets/audio/part1_self_reproach_B_with_jev_emotion.wav) |
| 2 | Cold resolve | 是我想亲手&lt;了\|LIAO3&gt;结&lt;羂\|JVAN4&gt;索的私心，造成了现在的状况。我的错，就由我来终结！ | `[0.0, 0.85, 0.10, 0.0, 0.20, 0.20, 0.0, 0.65]` | 1.05× | [▶](../../assets/audio/part2_cold_resolve_A_no_emotion.wav) | [▶](../../assets/audio/part2_cold_resolve_B_with_jev_emotion.wav) |
| 3 | Domain invocation | 领域展开……！&lt;真\|ZHEN1&gt;&lt;赝\|YAN4&gt;相爱。 | `[0.0, 0.92, 0.0, 0.0, 0.0, 0.0, 0.0, 0.70]` | 0.88× | [▶](../../assets/audio/part3_domain_expansion_A_no_emotion.wav) | [▶](../../assets/audio/part3_domain_expansion_B_with_jev_emotion.wav) |

Vector layout is fixed by the engine:
`[joy, anger, sorrow, fear, disgust, depression, surprise, calm]`.
Version B is generated with `emo_alpha = 1.2`; version A with `emo_alpha = 1.0` and no vector.

| # | What changes audibly |
| --- | --- |
| 1 | Delivery drops and thins into breath. Reads as exhaled, self-directed contempt rather than narration. |
| 2 | Vocal folds tighten, consonants harden; the final clause lands as a verdict instead of a statement. |
| 3 | The line slows below baseline and the chant flattens — authority carried by restraint, not volume. |

> Provenance: the reference voice (`../../assets/audio/reference_voice_10s.wav`) is a 10-second clip
> used as a local experiment. No rights to it or to the character dialogue are claimed.

---

## The pipeline

```
dialogue + character profile
        │
        ▼
  Jev /v1/systemone ── one request, four judgments ──┐
        │                                            │
        │  guilt_and_self_reproach      (Noul)       │
        │  fatal_resolve_and_wrath      (Noul)       │
        │  domain_authority_and_focus   (Noul)       │
        │  dominant_emotion             (Choice)     │
        │                                            │
        ▼                                            │
  compiled plan (code) ◄─────────────────────────────┘
        │  8-D emotion vector, emo_alpha, duration_factor
        ▼
  IndexTTS 2.5  ──►  audio
```

The judgments are deliberately **overlapping rather than one label**: three independent `Noul`
readings of intensity plus one `Choice` for the dominant colour. Code — not the model — decides how a
probability becomes a coefficient.

## How a probability becomes a vector

The base vector for each dramatic phase is authored as part of the character's profile. Jev's
probabilities then scale the axes that phase implicates:

```python
base_vec[1] = round(min(1.0, base_vec[1] * (0.8 + 0.4 * p_wrath)),  2)  # anger / lethal intent
base_vec[4] = round(min(1.0, base_vec[4] * (0.8 + 0.3 * p_guilt)),  2)  # disgust / self-loathing
base_vec[5] = round(min(1.0, base_vec[5] * (0.8 + 0.3 * p_guilt)),  2)  # depression / self-blame
base_vec[7] = round(min(1.0, base_vec[7] * (0.7 + 0.4 * p_domain)), 2)  # calm / authority
```

This is the repository's central division of labour in miniature. Jev answers *how much* of each
reading is present; the multipliers, the floor and ceiling, the rounding, and which axis each
probability is allowed to touch are all explicit constants in code. **A model upgrade re-runs the
judgments; it does not silently re-tune the synthesizer.**

Every threshold is a parameter you can print, argue with, and change without re-running inference.

## Two variants in this repository

| Variant | Directory | Judgment | Output plan |
| --- | --- | --- | --- |
| Chinese, 3-phase, A/B with baseline | [`../emotion-controlled-tts`](../emotion-controlled-tts) | 3 × Noul + 1 × Choice per segment | vector + `emo_alpha` + duration factor |
| Japanese, character-profile driven | [`../emotion-controlled-tts-ja`](../emotion-controlled-tts-ja) | 3 × Noul + 1 × Choice over a character profile | full 3-phase TTS schedule |

The Japanese variant reads its character context from
[`../emotion-controlled-tts-ja/yuta_cognition.py`](../emotion-controlled-tts-ja/yuta_cognition.py),
which keeps the profile as data rather than as prompt text embedded in code — so a different
character is a different file, not a different script.

## Falling back is part of the design

[`../emotion-controlled-tts-ja/jev_evaluator.py`](../emotion-controlled-tts-ja/jev_evaluator.py)
catches a failed call and substitutes a local prior keyed on the dramatic phase, so a synthesis run
never dies because the network did:

```python
except Exception as e:
    print(f"[Jev API degraded] remote call failed ({e}); using local prior.")
    return self._fallback_ground_truth(phase_hint)
```

Two notes on that, in opposite directions. It is the right shape — a judgment source is a
dependency, and a dependency that can take down the whole run is a bad one. But the fallback is a
**constant** keyed on a phase label, so a run that silently falls back produces audio that is
indistinguishable downstream from a run where Jev answered. **Log it and fail loudly in any
measurement context**, or the A/B you are reporting may not have used the model at all. This is the
same failure family as the ablation errors in
[`../../papers/JEV_EMPIRICAL_BOUNDARY_ANALYSIS.md`](../../papers/JEV_EMPIRICAL_BOUNDARY_ANALYSIS.md)
§T12: verify the mechanism ran before trusting the number.

## Model version

Both shipped clients read `MODEL = "jev-latest"`. That is the default in the SDK and it is the wrong
choice for this use: the multipliers above were tuned against a specific model's output distribution,
and `jev-latest` will move that distribution without a code change. **Pin `jev-1.13.0`** and diff the
generated vectors before adopting a new version — the guidance is in
[`../../papers/JEV_AS_A_TYPE_ADAPTER.md`](../../papers/JEV_AS_A_TYPE_ADAPTER.md) §7, and the SVG probe
in this repository is pinned for exactly this reason.

---

## Reproducing

```bash
export TYPESAFE_API_KEY=...
pip install soundfile torch

# Chinese A/B — needs IndexTTS 2.5 checked out locally; set INDEX_TTS_DIR in run_experiment.py
python run_experiment.py

# Japanese 3-phase plan only (prints the compiled schedule; no synthesis)
python ../emotion-controlled-tts-ja/jev_evaluator.py
```

`run_experiment.py` writes both versions of all three segments into `audio/`. It releases the CUDA
cache between segments, which matters: without it a long batch degrades into memory thrash.

### IndexTTS 2.5 pitfalls that cost real time

These are properties of the engine, documented here because they silently corrupt output rather than
raising:

1. **`ü` is spelled `V`, not `U`, in the pinyin vocabulary.** The grapheme must be written
   `<羂|JVAN4>`; `JUAN4` is discarded by the vocabulary and read incorrectly.
2. **Polyphonic characters need explicit tone marking.** `<了|LIAO3>结` prevents the model from
   reading 了 as the particle `le`.
3. **`的` must be forced to the neutral tone.** Otherwise the word segmenter may assign `dì`, and it
   surfaces as an audible mispronunciation on a very common character.
4. **The 40-character hard cut is a low-VRAM mode.** `tts.low_vram = False` removes it; leaving it on
   truncates long lines on an 8 GB card.

Items 1–3 are model-input contract issues, not tuning: there is no parameter that fixes them, only
correct text. Item 4 is a configuration trap that looks like a text problem.
