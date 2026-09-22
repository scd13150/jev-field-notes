# Related work

Pointers only. Nothing in this repository is vendored from the projects below, and this repository
does not contain their code.

## Published by the same author

### st-Mind-Compass — an objective mind-state engine for SillyTavern

**Repository:** https://github.com/scd13150/st-Mind-Compass · AGPL-3.0

A SillyTavern extension that separates *language generation* from *mind-state adjudication*. The
host chat model keeps doing what it is good at — prose and characterisation — while Jev answers a
fixed bundle of typed questions asynchronously. Code then owns a deterministic two-track dynamics
engine with no model involvement at all:

| Layer | Owns |
| --- | --- |
| Jev | `boundary_violation`, `superficial_flattery`, `conversational_wit`, `emotional_validation`, `vulnerability_exposure` (Noul) · `inner_expression` (Choice over 28 GoEmotions labels) · `power_dynamic` (Score 0–4) |
| Code | first-order leaky-filter momentum, onion-model trust penetration, stage gating, affinity/defense arithmetic |
| Deterministic output | SillyTavern variables, `/expression-set` sprite changes, world-info injection, per-card persistence |

The design claim it tests is that a chat model asked to roleplay *and* track a relationship will
inflate the relationship, because the same generation that produces flattering prose can also produce
the flattering score. Moving the second job to a second, non-generative model is the fix, and the
"anti-sycophancy" behaviour falls out of it: cheap flattery is detectable as a typed judgment rather
than as a matter of the character's opinion.

Two details worth noting for anyone building on Jev in a browser:

- It is **zero-backend** — pure ES modules calling the REST API directly, so there is no local
  Python/Node/Docker requirement, and it is installed by pasting a Git URL into SillyTavern.
- The API key is never written to `settings.json` or exported with a character card. It goes to the
  host's own secret vault via `/api/secrets`, with a masked input. In an application where character
  cards are routinely shared as files, that is the difference between a key and a leak.

## Official and community resources

| Resource | Why it is listed |
| --- | --- |
| [TypeSafe documentation](https://docs.typesafe.ai/introduction) — API, SDKs, cookbooks, patterns | The source of the composition and speculative-fan-out patterns used throughout this repository |
| [Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13) | TypeSafe's own published failure modes. The probe in [`applications/svg-line-partition`](../applications/svg-line-partition) checks its observations against this page rather than presenting them as discoveries |
| [Jev 1.13 on the Playground](https://console.typesafe.ai/playground) | Where the question bundles here were iterated before being automated |
| [Workflow evals](https://evals.typesafe.ai) | Reference evaluation harnesses |
| [`awesome-jev`](https://github.com/AnotiaWang/awesome-jev) | The community directory. Its **Demos & Games** section is the relevant context for Application 1: structured-state game harnesses spanning Tetris, Pac-Man, chess, Mario, Doom, StarCraft, Civilization II, Pokémon Red and 2048 — the same shape as the fighting-game harness here, which is why that application is built the way it is |
| [`AbdelStark/jev-benchmarks`](https://github.com/AbdelStark/jev-benchmarks) | Independent latency and accuracy measurement; useful for calibrating the latency figures quoted in [`papers/JEV_AS_A_TYPE_ADAPTER.md`](../papers/JEV_AS_A_TYPE_ADAPTER.md) §8, which are one machine's numbers and are labelled as such |

## Not included, and why

Two local projects are deliberately **not** in this repository.

- One is an independent open-weights decision model that benchmarks itself against Jev, including
  comparisons where it comes out ahead on most axes. It is legitimate work and the comparisons are
  fair, but shipping it inside an application repository for the company that builds Jev would
  misrepresent the intent of this collection and invite the wrong reading of every measurement in it.
  It is published separately and is not a Jev application.
- The other is the same reasoning at a smaller scale: several smaller experiments use Jev as one
  component among many and would dilute the focus here. This repository is limited to work where Jev
  is the subject.
