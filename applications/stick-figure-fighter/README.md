# Stick Figure — JEV Fighting

A stick-figure fighting game where the AI opponent is driven by **TypeSafe Jev**,
a System-One model that returns typed judgments and probabilities instead of text.
You control the blue fighter; a Jev brain controls the red one and reacts in
near-real-time. A headless **dual-JEV** mode pits two Jev brains against each
other — the production-stage way to tune and stress the combat system.

> Jev is used exactly the way the `typesafe-ai` skill prescribes: **code owns the
> workflow, rules and execution; the model only supplies the semantic judgment
> ordinary code cannot.** Every millisecond-level thing — physics, AABB hit
> detection, frame data, cancel windows, damage scaling — lives in the engine.
> Jev never touches a coordinate; it decides *what to attempt*.

## Quick start

```bash
npm test                              # 52 tests, no network, no key needed
node scripts/probe.mjs                # confirm the live JEV endpoint (needs the key)
node scripts/spar.mjs --mock --fast   # free headless dual-JEV battle + report
node server/server.js                 # play in the browser: http://127.0.0.1:8787
```

![Jev fighting the player: the stance triangle in motion](../../assets/images/fight_stance_triangle.gif)

A real round against the live API (`TYPESAFE_API_KEY` in the environment, key server-side only). The
red fighter is driven by Jev; the blue one is a scripted player. The HUD line under the arena reads
back the compiled strategy and the measured round-trip latency, so what the model decided is visible
next to what happened. Same run, from the probe: **322–1216 ms** per judgment, median **384 ms**.

The API key is read from the environment (`TYPESAFE_API_KEY`); copy
`.env.example` and export it, or set it in your shell. **The key stays on the
server** — the browser only ever calls `/api/jev`.

## The two surfaces

| Surface | What it is | JEV transport |
| --- | --- | --- |
| `server/server.js` + `public/` | the playable browser game (you vs JEV, or watch JEV vs JEV with `M`) | browser → `/api/jev` → server → Jev (key server-side) |
| `scripts/spar.mjs` | production-stage headless dual-JEV sparring + stats | Node → Jev directly (`--live`) or offline heuristic (`--mock`) |

Both run the **same** engine, state serializer, question bundle, policy and
`JevBrain`. Only the injected `decider(state, questions) -> answers` differs, so
what you tune in the browser behaves identically in headless sparring.

## How it is put together (the layers)

```
engine/   deterministic 60Hz sim: moves, AABB hit/hurt, block stances,
          cancel-window combos, juggle/knockdown, projectiles, damage scaling.
jev/
  state.js      world -> one fighter's VIEW (named fields the questions cite)
  questions.js  the bundle: 2 choice + 3 noul + 1 score, all independent
  policy.js     answers + confidence -> plan -> per-frame inputs + reflexes
  brain.js      the non-blocking pipeline that keeps reaction near-real-time
  client.js     Node Jev HTTP client (holds the key)      mock.js  offline twin
server/server.js  static host + /api/jev decision proxy
public/          canvas game loop + input + HUD
```

### Why "near-real-time" and how the loop achieves it

A live Jev round-trip is roughly **0.4–1.3 s** (the probe and the live spar log
real numbers). You cannot ask a model every frame at 60 fps. So the brain is a
**pipeline**, not a request/response:

```
every frame:  getInput(world)   // execute the CURRENT plan against LIVE state
              stepWorld(...)     // the deterministic sim advances
              observe(world)     // maybe fire ONE async Jev call (in-flight guard)
                                  //   -> when it resolves, swap in the new plan
```

The model supplies a **persistent intent** (e.g. "combo", "space_control", threat
0.8); the **coded policy + reflexes** act on it at frame rate between calls — an
instant guard when `threat_now` is high *and* the engine sees a committed attack
in range, combo-route advancement the moment a cancel window opens, air-extension
juggles when the foe is launched. The sim **never blocks on the network**, which
is what makes a slow model still feel responsive. Re-planning is trigger- and
TTL-based (got hit / foe committed / big spacing change / stale plan), with an
API-budget guard.

### The judgment bundle (skill's "compose, don't over-call")

One request, six independent judgments over the same state, run in parallel:

- **`intent` (choice)** — the single next strategy. Its options are worded so code
  maps each one deterministically to a move sequence.
- **`guard_stance` (choice)** — which height to bet the guard on. Deliberately *not*
  a lookup of the move on screen: a guard that could read the attack height before
  choosing could never be mixup'd, so this is a bet refreshed at model cadence, and
  the coded reflex is what holds it through the frames the bet is live.
- **`threat_now` (noul)** — drives the immediate-guard reflex.
- **`punish_window` (noul, speculative: "IF the foe's action is a whiff/block…")** —
  turns a poke into a committed combo only when a safe punish exists.
- **`counter_hit` (noul, speculative)** — informs neutral footsies.
- **`aggression` (score)** — picks safe-poke vs full-launcher route length.

`policy.js` uses probabilities and confidence: a low-confidence risky `intent`
degrades to a safer one, and a strong `threat_now` overrides toward defence.
Changing a threshold never re-runs inference.

### Combinable skills + collision that "explores the ceiling" (探寻上限)

Skills declare `cancelInto` links (`jab→strong→launcher→…`); the engine opens a
cancel window only when the previous move **connected**, so combos are discovered
through the skill graph. The graph is also what makes the stance game playable
rather than decorative: `jab` and `strong` each list `sweep` (the low) and `throw`
(the grab) as links out of a *blocked* strike, which is the tick throw. **Damage
scaling** and a **bounded juggle** make the combo a real ceiling, not infinite: the
mock pool's measured number is **5 hits in one string**, with per-hit damage decaying
as scaling bites. The headless report prints each side's **best combo (hits/damage)**
— the number you tune the AI toward.

## Controls

`A`/`D` move · `W` jump · `S` crouch · `Space` block · `J` jab · `K` strong ·
`U` launcher · `I` sweep · `O` fireball · `H` air-kick · `T` throw · `G` super ·
`B` burst. `R` rematch · `M` toggle you-vs-JEV / JEV-vs-JEV. Chain
`jab → strong → launcher`, then `jump` + `H` to juggle.

## The stance triangle

Every defensive habit has exactly one wrong answer, and the engine enforces all
three arms:

| They are… | The answer | Why it cannot be covered |
| --- | --- | --- |
| blocking standing | `I` sweep (low) | a stand guard covers highs and mids only |
| blocking crouched | `H` air-kick (overhead) | a crouch covers lows and every ground strike |
| holding guard at all, in grab range | `T` throw | unblockable — and it is the only move that a *crouch* cannot answer |
| throwing a fireball | `W` toward them | the shot passes under a jumping body |
| committed to a grab | `W` | a grab only catches a grounded foe |

Because blockstun keeps the guard up but cannot change its height, the stance is
a **bet placed before** the strike lands, and the cancel window a blocked strike
opens is where the bet gets collected: `jab`/`strong` → `sweep` (the low) or →
`throw` (the tick throw). That window is a few frames wide, so it is driven by
coded reflexes, not by a model call — see the next section.

## What code does vs what JEV does (the line, and why)

A live Jev round-trip is ~0.4–1.3 s, so **anything that has to land inside a
handful of frames is code**: the guard stance, the blockstun hold, the cancel
window's low-or-grab choice, the falling overhead, the whiff punish, burst. JEV
supplies the things that are genuinely semantic and slow-moving — *which* strategy
this foe is worth committing to, how much aggression to spend, whether a threat is
real. Concretely, `policy.js` owns these engine-derived reflexes:

- **Guard through blockstun** — the stance they committed to is held, and the
  answer to it (`sweep` at a stand, `throw` at a lock) is picked from geometry the
  engine also uses (`attackBox`), so the reflex never times itself against a
  hand-written approximation.
- **The cancel window drives the press.** `advanceAction` opens the window when the
  strike *connects*, not when the frame counter passes a threshold, so a blocked
  jab can actually link into the low through the hitstop freeze.
- **A grab is only ever pressed into a locked guard.** Every brain here has the same
  hop-the-grab reflex, so a grab aimed at a free opponent is a 19-frame whiff handed
  over, not a guess with a chance in it. `grabLocked` makes that a rule.
- **The overhead is pressed on the way down**, and only at a foe who cannot answer
  those frames (stunned, recovering, or guarding).

## Measuring the fight

The ledger is how a claim about the combat gets checked rather than admired. The
mock pool is deterministic, so a policy change moves these numbers or it did
nothing — and `--games 64` is the sample size, because a single match swings the
counter-hit share by several points:

```bash
node scripts/spar.mjs --mock --games 64 --seconds 45
```

```
  attack started   : 3064   landed 1624   guarded 440   whiffed 464
  defence share    : 21.3% of attacks that reached a body were guarded (target >=22%)
  counter-hit share: 9.4% of landed hits were intercepts (target 8-12%)
                     strong>into-strong:80  super>into-jab:64  strong>into-fireball:8
  whiff punish     : 312/464 whiffs punished (67.2%), of 0 empty grabs
  throw / burst    : 32 grabs landed, 160 meter escapes
  stance breaks    : 168 lows through a guard, 176 overheads, 144 launches
  space control    : 224 fireballs, 120 never touched anybody; 280 jumps
  combo ceiling    : 5 hits in one string
  outcomes         : 16 wins for each of the four personas
```

Every line was once the bug. Lows and overheads sat at exactly 0 until the
blockstun/stance rules were fixed; the grab arm printed 0 catches across sixteen
matches until the move graph let `strong` cancel into a throw, the grab was given
reach its own blockback steals (98px + a 5px/frame step-in), and it stopped being
pressed at opponents free to jump it. 32 landed on 32 attempted is not luck — it
is the tick throw working on a foe who cannot answer it, which is what makes the
other side of the triangle real: the counterplay is to stop turtling at grab
range, not to react to the grab. The targets print inline so the next change can
be *falsified* by the next run.

## Tuning the AI headless (production stage)

```bash
# real Jev driving both fighters, 45s, up to ~40 decisions per brain:
node scripts/spar.mjs --live --p1 rushdown --p2 zoner  --seconds 45 --budget 40
# A/B two model tags (dual-model) and dump JSON:
node scripts/spar.mjs --live --p1 counter --p2 rushdown --model1 jev-latest --model2 jev-1.13.0 --json spar-ab.json
# free + instant, for CI / quick mechanic checks:
node scripts/spar.mjs --mock --fast --p1 rushdown --p2 counter
```

Personas (`balanced`, `rushdown`, `zoner`, `counter`) only rephrase the intent
judgment — the primitive structure is identical, so the two brains' raw
judgments stay directly comparable.

## Tests

`npm test` runs 52 cases, no key and no browser. The engine half is where the
combat rules are pinned, because each of them was found by measurement and is
invisible to a casual look: a high cannot be blocked crouching and a low cannot be
blocked standing; **blockstun keeps a guard up but does not change what that guard
covers**; **a blocked strike's cancel window is open through the hitstop freeze**;
a blocked strike's window is close enough to catch a grab (the tick throw); a
crouching body is met by the overhead, not by the ground strikes it covers; a shot
that flies past is announced the way a whiffed punch is; damage scaling and the
juggle bound cap a combo. The JEV half covers low-confidence de-risking, the
threat-guard reflex, the stance bet coming from the plan rather than a lookup of
the incoming move, the fighter-relative state, and two brains driving a full
async dual-JEV match against the offline mock decider.

## Notes / honest limits

- The live browser feel can only be *confirmed* in a real browser; here it is
  exercised through the shared, unit-tested modules and a live server proxy.
- Jev reads a snapshot of derived facts; it is calibrated but the *domain* (this
  move set) is yours to validate — the spar report is the measuring stick.
- **Defence reads 21.3% against a >=22% floor.** It is left there rather than
  tuned up: the lever is raising the mock's block probability, which feeds the
  very turtling the low/overhead/grab arms measure, so a greener number would be
  bought by weakening the thing under test.
- **A tick throw converts on every attempt (32/32), by construction** — it is only
  ever pressed into a guard that is locked in blockstun, and a locked guard cannot
  answer it. That is the correct rule, but it means the counterplay lives in the
  *decision* to keep holding guard at grab range, which the persona heuristics do
  not model yet. A human with a real reaction time is the check on it.
- The largest remaining counter leak is `super > into jab` (64 in the pool): the
  super has 6 frames of startup and cancels off any hit, so it intercepts a poke it
  was not aimed at. Tightening it is a frame-data conversation, not a policy one.
- Not built: rounds / best-of-3, air block, corner reward, whiff-cancel baiting, a
  frame-advantage signal for JEV to read, a second character kit, and netplay. The
  engine is built so adding a move is just a row in `moves.js`.
