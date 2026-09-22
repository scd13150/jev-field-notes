# Listening room

Six WAV files — three A/B pairs. Version **A** is IndexTTS 2.5 with no external emotion control
(`emo_vector = None`). Version **B** is the same text, the same reference voice and the same sampling
configuration with the Jev-derived 8-D emotion vector applied. Nothing else differs, so the
difference you hear is the judgment.

| File | Version | Length | What it is |
| --- | --- | --- | --- |
| `part1_self_reproach_A_no_emotion.wav` | A | 11.18 s | Self-reproach, baseline |
| `part1_self_reproach_B_with_jev_emotion.wav` | B | 13.57 s | Self-reproach, Jev-controlled |
| `part2_cold_resolve_A_no_emotion.wav` | A | 7.83 s | Cold resolve, baseline |
| `part2_cold_resolve_B_with_jev_emotion.wav` | B | 8.54 s | Cold resolve, Jev-controlled |
| `part3_domain_expansion_A_no_emotion.wav` | A | 3.31 s | Domain invocation, baseline |
| `part3_domain_expansion_B_with_jev_emotion.wav` | B | 2.52 s | Domain invocation, Jev-controlled |
| `reference_voice_10s.wav` | — | 10 s | The speaker reference used for every take |

All files are PCM 16-bit. The vectors, parameters, judgment keys and reproduction steps are in
[`../applications/emotion-controlled-tts`](../applications/emotion-controlled-tts).

## How to listen

GitHub does not render `<audio>` elements or play WAV files inline in a Markdown preview, so the
links above are direct file links — click through and the browser plays them, or open them in any
player. For a side-by-side comparison, download a pair and load both into one player.

## Provenance and rights

These are local experiment artifacts, published as evidence of a measured effect rather than as
content.

- The **reference voice** is a 10-second clip taken from a longer recording and used as the speaker
  prompt for every take. No rights to it are claimed and no licence is granted over it. If you are a
  rights holder and want it removed, open an issue and it will be deleted.
- The **dialogue** is transcribed from published material. It is included only because the emotion
  judgment is meaningless without the line it was made about. No rights are claimed.
- The **synthesized audio** was generated locally by IndexTTS 2.5 and is not a recording of any
  person.

If you intend to reuse anything in this directory, treat it as unlicensed and replace both the voice
reference and the text with material you own.
