# Chinese originals

The Chinese source documents. Where an English version exists it is the one kept current; these are
the originals, and they are the authoritative record of what was written at the time.

**One exception, and it is deliberate.** `JEV_CAPABILITY_RECORD.redacted.md` has been sanitized: every
class, field, asset and script identifier is replaced with a stable neutral alias, the title is not
named, and the version strings are removed. The analysed work is adult-themed, so leaving its
identifiers in a public repository would both reveal its subject matter and make it trivially
identifiable. Aliases preserve the original spelling and length, so every count and structural claim
is unchanged — verified as **976 numeric tokens identical** to the pre-sanitization text, the only
differences being the removed engine and title version numbers. This is the only file in the
repository that is not verbatim, and its name says so.

| File | English version | Note |
| --- | --- | --- |
| [`JEV_AS_A_TYPE_ADAPTER.zh.md`](JEV_AS_A_TYPE_ADAPTER.zh.md) | [`../../papers/JEV_AS_A_TYPE_ADAPTER.md`](../../papers/JEV_AS_A_TYPE_ADAPTER.md) | Original write-up of Jev as a typed boundary between language and code. Verbatim |
| [`JEV_CAPABILITY_RECORD.redacted.md`](JEV_CAPABILITY_RECORD.redacted.md) | [`../../papers/JEV_EMPIRICAL_BOUNDARY_ANALYSIS.md`](../../papers/JEV_EMPIRICAL_BOUNDARY_ANALYSIS.md) | The full 512-line record: all twelve benchmarks, the error log, and §7, the number → artifact → reproduction-command index. **Identifiers sanitized** |
| [`AB_COMPARISON_EXPERIMENT.md`](AB_COMPARISON_EXPERIMENT.md) | [`../../applications/emotion-controlled-tts/README.md`](../../applications/emotion-controlled-tts/README.md) | The A/B TTS experiment report. Verbatim |

Why keep both: the Chinese record is the primary evidence, including the parts that are unflattering
to the conclusions drawn at the time. In `JEV_CAPABILITY_RECORD.redacted.md` §2.2 and §4, claims are recorded
that were later falsified, with the measurement that falsified them, so a reader can check the
reasoning rather than only its conclusion. That audit trail does not survive translation, so the
original stays.

The full four-round Chinese write-up of the SVG line-art probe is at
[`../../applications/svg-line-partition/docs/zh/README.md`](../../applications/svg-line-partition/docs/zh/README.md),
and the fighting-game engineering ledger at
[`../../applications/stick-figure-fighter/docs/zh/COMBAT_SYSTEM.md`](../../applications/stick-figure-fighter/docs/zh/COMBAT_SYSTEM.md).
