# Stick Figure Fighter · Combat System Summary

> This is the English version of the engineering ledger for the fighting game stick-figure-jev: its design, implementation, measurements, and known weaknesses, module by module, section by section.
> The Chinese original lives at `zh/COMBAT_SYSTEM.md`; this file is the engineering-side source of record.
> Every figure below comes from measured harness output, not from estimates.

Table of Contents

1. [Goals and Acceptance Constraints](#1-goals-and-acceptance-constraints)
2. [Layered Architecture and Dependency Direction](#2-layered-architecture-and-dependency-direction)
3. [Engine Layer: World, Geometry, Frame Data](#3-engine-layer-world-geometry-frame-data)
4. [Engine Layer: Defense, Hits, Combos, Throws, Projectiles](#4-engine-layer-defense-hits-combos-throws-projectiles)
5. [JEV Decision Layer: State, Questions, Policy, Brain](#5-jev-decision-layer-state-questions-policy-brain)
6. [Presentation Layer and Input](#6-presentation-layer-and-input)
7. [Measurement: Ledger Metrics and Results](#7-measurement-ledger-metrics-and-results)
8. [Root-Cause Chain: Closing the Rock-Paper-Scissors Loop](#8-root-cause-chain-closing-the-rock-paper-scissors-loop)
9. [Test Inventory](#9-test-inventory)
10. [Known Weaknesses and Deferred Work](#10-known-weaknesses-and-deferred-work)
11. [Runbook](#11-runbook)
12. [Conclusion Correction Log](#12-conclusion-correction-log)

---

## 1. Goals and Acceptance Constraints

Original requirements, checked one by one against where the work actually landed:

| Requirement | Landing point | Status |
| --- | --- | --- |
| Player controls a stick figure vs a JEV stick figure, with quasi-realtime reaction | `public/` + the `JevBrain` pipeline (non-blocking, per-frame plan execution) | Done; the browser view is only verified at the structural level, see §11 |
| Implementation follows `typesafe-ai` best practices | Rules and execution stay in code, semantic judgment goes to the model; one request bundles 6 independent judgments; threshold changes never trigger a re-run of inference | Done, see §5 |
| Pairing moves with collision mechanics, to probe the combo ceiling | `MOVES[].cancelOn/cancelInto` move graph + AABB tests + `DAMAGE_SCALE`/`MAX_JUGGLE` caps | Done; measured ceiling is 5 hits |
| Keys live only in local environment variables | `TYPESAFE_API_KEY` is read only by `server/server.js` and `src/jev/client.js` (Node side); the browser only calls `/api/jev` | Done |
| Two JEV models drive the two stick figures during production | `scripts/spar.mjs` headless two-brain matches + pooled ledger; `--model1/--model2` support two model labels for A/B | Done |

Core redirect, in the user's own words: **"the most important thing, the stick figure fight, doesn't work — it's not a presentation problem, what about the move combos and the exciting fights, where are Jev's mind-game choices"** — so this entire round went into mind-game decisions and combo reachability. None of it went into subjective visual polish.

---

## 2. Layered Architecture and Dependency Direction

```
src/engine/constants.js   pure tunables (no I/O, no globals, one copy for Node and browser)
src/engine/moves.js       move table: frame data + move graph (cancelOn/cancelInto)
src/engine/engine.js      fixed-step 60Hz simulation: geometry, hits, defense, hitstun, knockdown, projectiles, resources
src/jev/state.js          world -> an order-independent observation bag for one viewpoint
src/jev/questions.js      question pack: 2 choice + 3 noul + 1 score
src/jev/policy.js         answers -> plan (compilePlan); plan + live world -> per-frame inputs (executePlan)
src/jev/brain.js          non-blocking pipeline: getInput / stepWorld / observe + replanning triggers
src/jev/client.js         Node-side JEV HTTP client (holds the key)
src/jev/mock.js           offline twin decider (free, deterministic, used by CI and tuning)
server/server.js          static hosting + /api/jev decision proxy + /api/config
public/client.js view.js  canvas game loop, input mapping, HUD, pose rendering
scripts/spar.mjs          headless two-JEV pooled matches + combat ledger
scripts/probe.mjs         online endpoint connectivity probe
test/engine.test.mjs      32 engine rule cases
test/jev.test.mjs         20 decision-layer rule cases
```

Dependencies point one way only: `jev/*` depends on `engine/*`, and `engine/*` never depends back on any decision code.
`policy.js` reuses the engine's own geometry functions via
`import { attackBox, hurtbox, overlap } from "../engine/engine.js"` instead of writing a second distance formula. That is deliberate: **there is exactly one source of truth for hit geometry**, otherwise the reflex would be swinging at a lie.

`src/engine/index.js` and `src/jev/index.js` are nothing but re-export barrels.

---

## 3. Engine Layer: World, Geometry, Frame Data

### 3.1 Fixed-Step Loop and Determinism

`stepWorld(world, inputs)` runs these in order every tick: timers (including the hitstop freeze) → input → intent → action advance → physics → body pushing → hit/projectile resolution → event emission. Fixed step, pure functions, no globals — so the same input sequence necessarily reproduces the same match. Running the mock pool of 64 matches twice and getting byte-identical output is the verification of that property.

`world.events` is the **only** source of match narrative: `attack_start / hit / block / whiff / throw / launched / counter_hit / projectile / shot_evaded / burst / jump / dash / ko`. The ledger derives its metrics from the event stream alone and never back-infers them from frame data, so that "we changed one policy" can be falsified rather than explained away.

### 3.2 Arena and Body Geometry

| Parameter | Value | Meaning |
| --- | --- | --- |
| `ARENA.width` | 900 | Stage width |
| `ARENA.wallPad` | 40 | Wall boundary inset |
| `FIGHTER.halfWidth` | 22 | Half-width of the standing hurtbox |
| `FIGHTER.bodyHeight` | 120 | Standing hurtbox height |
| `FIGHTER.crouchHeight` | 66 | Crouching hurtbox height |
| `FIGHTER.startHP` | 1300 | ≈25 clean hits, enough to guarantee a neutral phase |
| `walkSpeed / backSpeed` | 3.4 / 2.6 | Walking forward is faster than walking back |
| `dashSpeed / dashFrames / dashCooldown` | 9.5 / 12 / 24 | |
| `jumpVelocity / gravity / airSpeed` | 15.2 / 0.82 / 4.6 | ≈37 frames airborne, ≈170px arc |
| `wakeInvuln` | 18 | Wake-up invulnerability frames (the natural endpoint of throws and combos) |

`attackBox()` is centered at `f.x + facing * hitbox.x` with `hitbox.w/h` as width and height; the upper bound of `hurtbox()` switches between standing and crouching via `heightOf()`. **The horizontal distance at which a move can actually hit a body** is `hitbox.x + w/2 + 22`, which this document calls "reach". The full table follows (computed from the current frame data, not copied by hand):

| Move | Reach (px) | Notes |
| --- | --- | --- |
| launcher | 87 | High-rising uppercut, short |
| jab | 92 | Safe poke |
| airkick | 93 | Overhead from the air |
| **throw** | **98** | Changed from 74 this round, see §8 |
| strong | 111 | The workhorse mid-to-long-range poke |
| sweep | 115 | Low |
| super | 127 | Full-meter finisher |

### 3.3 Move Table (Frame Data, 60fps)

| Move | Type / height | Startup | Active | Recovery | Damage | Hitstun | Blockstun | Knockback | Cancels on → into |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| jab | strike / high | 4 | 3 | 7 | 42 | 16 | 9 | 3.2 | hit,block → strong, launcher, sweep, fireball, **throw**, super |
| strong | strike / high | 8 | 4 | 14 | 86 | 22 | 12 | 6.0 | hit,block → launcher, fireball, **sweep**, **throw**, super |
| launcher | strike / high | 7 | 5 | 26 | 78 | 26 | 14 | 2.5 / +16 launch | hit → jump |
| sweep | strike / **low** | 9 | 4 | 22 | 70 | 24 | 12 | 4.0 (knockdown) | — |
| fireball | projectile / high | 12 | — | 22 | 55 | 20 | 12 | 5.0 | — (shot speed 7.5, lifetime 160) |
| airkick | air strike / **overhead** | 5 | 6 | 10 | 64 | 22 | 10 | 4.0 / 4.0 | — (juggleAdd 2) |
| throw | **grab** / unblockable | 3 | 4 | 16 | 120 | 20 | 0 | 6.0 (knockdown) | — (`lunge: 5`) |
| super | strike / high | 6 | 8 | 20 | 260 | 28 | 18 | 5.0 | hit → — (costs 100 meter) |

The move graph is the **sole authority on combos**: any link not listed in `cancelInto` is rejected outright by the engine, and the code never forces an illegal cancel. The header comment in the table spells out the one wrong answer each of the three guards can give.

---

## 4. Engine Layer: Defense, Hits, Combos, Throws, Projectiles

### 4.1 Blocking Rules, `isBlockingAgainst`

```
must be grounded; not in hitstun / attack / knockdown / ko;
guarding = blockstun > 0 || hold.block;           // armor keeps the guard up
facing the attacker;
low      -> blocked only while crouching;
overhead -> blocked only while not crouching;
otherwise -> stand and crouch blocking follow the height rule above
```

The key ruling this round: **blockstun keeps the guard raised, but does not change the height that guard covers.** Previously everything was auto-blocked during blockstun with no height check, which pinned lows at a constant zero in live play. After the fix, the crouch/stand choice becomes a **bet** you have to place before you get hit, and high/low mixing becomes possible at all.

Supporting numbers: `CHIP.strikeRatio = 0.10` and `CHIP.projectileRatio = 0.05`, with a 1 HP floor on chip damage — turtling is safe but not free, and pure defense never gets chipped to death.

### 4.2 Effective Armor Frames (a derived property discovered this round)

On block, `atk.hitstop = def.hitstop = stop` (12 for strikes, 10 for projectiles), and the timer loop `continue`s through hitstop, so **blockstun and the action's frame counter freeze together**. That makes "how many frames the opponent still cannot move after the thaw" work out as:

| Blocked move | blockstun | Freeze | Effective armor frames after the thaw |
| --- | --- | --- | --- |
| jab | 9 | 12 | **0** (actually minus 3) |
| strong | 12 | 12 | **0** |
| sweep | 12 | 12 | **0** |
| airkick | 10 | 12 | **0** |
| fireball | 12 | 10 | 2 |
| launcher | 14 | 12 | 2 |
| super | 18 | 12 | 6 |

This table is the precondition for the throw fix: **once a poke is blocked, the entire "frame lock" is spent inside the freeze, and the opponent is free the instant it thaws** — and the pushback displacement is only cashed out after the thaw, all at once. Any mechanic that hopes "the opponent cannot move during armor" has to cross that displacement on its own.

### 4.3 Hit Resolution

- Counter hit (`def.action.phase === "startup"` and not blocked): damage ×1.25, hitstun +4 frames, and a `counter_hit` event is emitted (carrying `victimMove`, so the ledger can say what got intercepted by what).
- Combo damage scales down per hit via `DAMAGE_SCALE` (15 steps, 1.0 → 0.15), and `MAX_JUGGLE = 8` caps the airborne extension; past the cap the victim takes a hard knockdown and the combo ends. **The ceiling is reachable but finite**: 5 hits measured.
- A mid-combo hit does not push the victim away (only the first hit, a launch, or a knockdown pushes), which is the precondition for "the move graph can actually link."
- Knockback and mutual pushing: `BLOCK_PUSH = { defender 0.5, attacker 0.45 }` — on a block **both** fighters get pushed apart, so blocking really does buy back distance; this is also the direct cause of the whiffed throws in §8.

### 4.4 Cancel Window, `advanceAction`

`a.cancelOpen = a.hitConsumed && cancelOn.length > 0`, and that line sits **above the early return for hitstop**. It used to sit below it, which meant the window was shut for the whole freeze — and the freeze is exactly the handful of frames during which the player or the AI mashes. After that one fix, `blocked jab → sweep` showed up in live play for the first time.

### 4.5 Throws and `lunge`

`throw` now carries `hitbox {x:46,y:60,w:60,h:80}` (reach 98) plus `lunge: 5`. During the `startup` of the action the engine sets `f.vx = facing * lunge` every frame, then zeroes it on the first `active` frame: 15px of forward movement across the 3 startup frames. Reasoning in §8 item 4. The throw is still `unblockable`, only grabs grounded opponents, deals 120 damage, causes an immediate knockdown, does not count toward combos, and does not build meter (`meterGain: false`).

### 4.6 Projectiles and Neutral

The projectile spawns at the end of startup, travels at speed 7.5, lives 160 frames, and can clash with other projectiles; blocking it chips 0.05. If a projectile goes its whole life without touching anybody, the engine emits `shot_evaded` — the same fact as a whiff, structurally: **a piece of space control that goes unanswered is a mistake**, and the ledger counts "224 fireballs, 120 that touched nobody" on that basis.

### 4.7 Resources and Counterplay

`METER = { max 100, gainOnHit 24, gainOnHitTaken 12, gainOnBlock 6, burstCost 50, superCost 100, burstInvuln 15, burstPush 30 }`. Taking a hit also builds meter, which is the quantitative expression of the comeback narrative: eating a full 4-hit route has to buy you exactly one burst, or else "get comboed once = get comboed forever." A burst only works on the ground, during hitstun, and with meter available; it clears any queued knockdown, pushes both fighters 30px apart, and interrupts the opponent's combo counter when it is at 2 or more hits.

---

## 5. JEV Decision Layer: State, Questions, Policy, Brain

### 5.1 `state.js` — What the Model Gets to See

Two hard rules:

1. **No pixel coordinates, no self-identity.** What it gets are semantic observations relative to the fighter: `spacing` bucketed into `clamp(≤60) / close(≤130) / mid(≤230) / far(≤430) / unsafe`, plus `hp_pct`, `meter_pct`, `clock.ticks_remaining_pct`, and for `self/foe` each of `state / action{move,phase,cancelOpen} / hitstun / blockstun / invuln / juggling / guarding`. System One generalizes over meaning, not over numbers.
2. **The observation bag is order-independent**, and a missing subset does not affect the rest — that is the precondition for "partial answers and timed-out answers are safe."

The `reach` dictionary computes, with the engine's own geometry, whether each move can connect right now; `reads` are derived facts rather than frame data: `foe_recovering / foe_committing / foe_hitstunned / foe_juggled / self_mid_combo / self_cancel_open / foe_action_startup / foe_whiffed(punish_frames ≥ 6) / foe_guarding / foe_guard_stance / self_can_burst / self_can_super`, plus `incoming_shot_frames` and `punish_frames`.

### 5.2 `questions.js` — One Request, 6 Independent Judgments

| Judgment | Primitive | Purpose |
| --- | --- | --- |
| `intent` | choice (11 options) | The single next strategy; the option wording guarantees a deterministic mapping in code |
| `guard_stance` | choice (stand/crouch) | **Bets** on the height of the next block; deliberately forbids "look at the move, then choose" |
| `threat_now` | noul | Triggers the hard-defense reflex; an incoming projectile counts too |
| `punish_window` | noul (speculative: "IF the opponent whiffed / got ...") | Decides whether a poke escalates into a full route |
| `counter_hit` | noul (speculative) | Neutral: can I interrupt first (explicitly says "a trade is not a win") |
| `aggression` | score(0..2) | Picks the safe version or the full route |

Independence is the point: all of them are asked in parallel within a single call and the answers cannot see each other; a persona only rewrites the wording of `intent`, never the primitive structure, so the raw judgments of the two brains are directly comparable.

### 5.3 `policy.js` — compilePlan (store judgments) + executePlan (per-frame execution)

`compilePlan` only downgrades and overrides, with all thresholds collected in `DEFAULT_THRESHOLDS`:

```
threatBlock 0.62 · punishGo 0.45 · minIntentConf 0.3 · maxAggression 1.3
midAggression 0.4 · throwConf 0.35 · superConf 0.4
```

- Low confidence downgrades `heavy → poke` and `anti_air/space_control → block`; **`combo` is never downgraded** (one extra jab is cheap, missing a whiff punish is the actual mistake).
- `throw`/`super` have their own higher confidence gates (a throw that whiffs for 16 frames is free, a whiffed super is the entire meter bar).
- A strong threat reading rewrites `reset/space_control` straight into `block`.

`executePlan` runs every frame as a numbered reflex pipeline (the order is the priority):

| Stage | Content | Why it has to be code |
| --- | --- | --- |
| 1 | Established combo driver: `comboRoute` = full `[jab,strong,launcher,jump]` / mid `[jab,strong]` / conservative `[jab]`; only fires the next link inside a real window; at full meter it closes with `superEnder` | Cancel windows exist frame by frame |
| 1b | burst counterplay | 50 meter for one escape; 3 frames late and it is meaningless |
| 1c | Hold the guard and the committed height during our own blockstun | These are not free frames |
| 2 | Hard reflex defense (only when we are free and no combo is live) | — |
| 2a | Whiff punish: `PUNISH_ORDER = [launcher, strong, jab]`, and if the window is shorter than that move's total frames it downgrades to a lighter one | The counter window is only `punish_frames` frames long |
| 2b | `airkick` on the falling half of a jump-in (descending, and the opponent cannot answer during those frames: stun/recovery/turtling) | 5 startup frames plus ~9px of fall per frame means kicking at the apex necessarily whiffs |
| 2c | Fire the "wrong answer" into the window that the blocked hit opened: crouch block → `throw`, stand block → `sweep`, out of range → `jump` | The window is a few frames wide; any ~0.4s plan is too late to be timed |
| 3 | Policy execution: `combo/poke/heavy/throw/super/burst/block/evade/anti_air/space_control/reset` | — |

`guardCrack(me, foe, allowGrab)` is the single entry point for all three guards; `grabLocked(foe) = foeTurtling(foe) && foe.blockstun > 0` restricts throws to "only into the frame lock." So `case "throw"` is no longer "walk over and grab" but "manufacture a frame lock with the cheapest move, then let the window branches collect."

Projectile response: `SHOT_LEAD = 12` and `SHOT_RISE = 8` decide "jump it if there is time, raise the guard if there is not."

### 5.4 `brain.js` — The Whole Secret of Quasi-Realtime Reaction

```
every frame: getInput(world)   // fires moves from the current plan against the live world, never any I/O
             stepWorld(...)
             observe(world)    // fires one async JEV call only when conditions are met (in-flight lock)
```

Replan gates: no call while `inFlight`; no call while `fires >= maxDecisions`; no call within `minFramesBetween = 12` frames of the last one; call when `plan == null` or `planAge >= ttlFrames = 24`; call on triggering events — getting hit, getting launched, the opponent attacking, the opponent firing a projectile, KO, and **spacing changing by more than 36px in a single frame**. The plan is swapped only once the answer returns, and the latency sample plus `rawLog` (state snapshot + answer + compiled result) are recorded. That is the mechanism behind "a slow model still feels responsive": **the model supplies persistent intent, the code executes it frame by frame.**

### 5.5 `mock.js` and the Key Boundary

`makeMockDecider({persona})` is an offline twin with the same shape and the same types as the real JEV (choice/noul/score + confidence), which makes CI, tuning, and reproduction completely free and deterministic. Its threat reading deliberately treats only an incoming projectile as a threat (0.55~0.85 at `≤12` frames, 0.12 otherwise); the comment spells out why close-range standoffs do not count as threats — that would converge on a mutual-guard deadlock. The key appears only in `server/server.js` (`HAS_KEY = Boolean(process.env.TYPESAFE_API_KEY)`) and in the Node client; `/api/jev` builds the question pack server-side, so the browser gets neither the prompt nor the key; `/api/config` answers only `has_key`.

---

## 6. Presentation Layer and Input

`public/client.js`: key map `KeyA/D` movement, `KeyW` jump, `KeyS` crouch, `Space` guard, `KeyJ` jab, `KeyK` strong, `KeyU` launcher, `KeyI` sweep, `KeyO` fireball, `KeyH` airkick, `KeyT` throw, `KeyG` super, `KeyB` burst; `R` restarts, `M` toggles human-vs-AI / two-JEV spectator mode. On startup it does `GET /api/config`, and if `has_key:false` it attaches the mock decider automatically, so the game is always playable.

`public/view.js`: poses are derived generically from `f.action.moveDef` + `phase` + `state` (there is no switch branching on move names), so adding a move requires no rendering changes; `knockdown/ko` get dedicated lying poses. Health bars, meter bars, hit particles, and event flashes are all driven by `world.events`, the same source as the ledger.

---

## 7. Measurement: Ledger Metrics and Results

`ledger(events)` in `spar.mjs` consumes the event stream and nothing else, printing pooled results (`--games 64`). Two refinements in how the metrics are defined: **attempts and hits are counted separately** ("lows: 0" means something entirely different depending on whether the button was never pressed or it was pressed and always blocked); and **counter-hits are recorded as `victim move > into - interceptor move`** (recording only the winners would hide both kinds of mistake, "I reached out and got countered" and "my jump-in got prepped for").

Current measurements (`node scripts/spar.mjs --mock --games 64 --seconds 45`, deterministic, two runs byte-identical):

```
  attack started   : 3064   landed 1624   guarded 440   whiffed 464
  defence share    : 21.3%  (target >=22%)
  counter-hit share: 9.4%   (target 8-12%)  strong>into-strong:80  super>into-jab:64  strong>into-fireball:8
  whiff punish     : 312/464 (67.2%), of 0 empty grabs
  throw / burst    : 32 grabs landed, 160 meter escapes
  stance breaks    : 168 lows through a guard, 176 overheads, 144 launches
  space control    : 224 fireballs, 120 never touched anybody; 280 jumps
  super            : 80 full-meter finishes
  combo ceiling    : 5 hits in one string
  moves attempted  : strong 1256  jab 584  super 336  sweep 296  fireball 224  airkick 176  launcher 160  throw 32
  outcomes         : rushdown 16 / counter 16 / zoner 16 / balanced 16
  average round    : 1393 ticks（about 23 seconds out of the 45-second clock）
```

Reading it item by item: all three guard-break edges are **non-zero** (168 lows / 176 overheads / 32 throws), but they are not comparable in magnitude — the throw is still the thinnest edge, see §10 for why; for throws, `throw 32 attempted → 32 landed → 0 empty grabs`, meaning "press it and it lands," so the bottleneck is the number of attempts, not the quality of the hits; the 9.4% counter-hit share sits inside the target band; the four persona records are perfectly symmetric, which says no single style dominates; and a 23-second average round is neither a blowout nor two fighters pawing at each other.

What these numbers used to look like: lows **0**, overheads **0**, throws **0 landed / 0 successes across 16 matches**, and 4 of 8 matches recorded as "draws" (which was really the mock decision budget cutting matches short).

---

## 8. Root-Cause Chain: Closing the Rock-Paper-Scissors Loop

"The triangle is missing one side" was not one bug. It was eight bugs stacked on top of each other. Each one comes with the observation that measured it.

| # | Symptom | Measured cause | Fix | Evidence |
| --- | --- | --- | --- | --- |
| 1 | Lows pinned at 0 in live play | Blockstun auto-blocked unconditionally and never checked height, so every low got blocked "in passing" | `isBlockingAgainst` now decides by height; armor keeps the guard up without changing coverage | 0 before; 168 low hits across the pooled 64 matches after (§7 ledger) |
| 2 | The stand/crouch bet did not exist | The guard dropped the instant our blockstun ended, so the bet was never cashed | Stage 1c: keep the guard and the committed height for the duration of the frame lock | Engine test "armor keeps the guard but does not change coverage height" + decision test "hold the committed guard and height through blockstun" |
| 3 | `jab→sweep` never appeared | `cancelOpen` was computed **after** the early hitstop return, so the window was shut for the whole freeze | Moved that line above the return (and recomputed at the end) | Engine test "the window from the blocked hit survives the freeze and can still cancel"; sweep attempts 296 |
| 4 | No mixup option at mid range | `strong.cancelInto` had neither a low nor a throw | Added `sweep` and `throw` | Probe: 26 frames of "window open + opponent crouch-blocking + throw pressed" were rejected by the engine 26 times; afterwards the window collapsed from 26 frames into 2 real windows |
| 5 | Throws whiffed 100% of the time (geometry) | `throw` had the shortest reach in the table (74px), while every move that could cancel into it was longer (jab 92 / strong 111 / sweep 115), and the block itself gives away about 30px of pushback | Reach changed to 98 (still shorter than strong) | Hit distance after the move still went 80→120, which led to #6 |
| 6 | After the fix, all 6 still whiffed at 120px | Effective armor frames were 0 (§4.2): the freeze burned the armor, and the deferred pushback landed exactly as the throw's box came out | Added `lunge: 5` (15px of forward movement over 3 startup frames) | Probe output became `throw-start@d80 → GRAB-LANDED@d83` |
| 7 | All 16 "throw while we are free" attempts grabbed air | Every brain has a "jump when you see a throw" reflex, so the opponent was grounded at the input and already 20px in the air by the active frame | `grabLocked`: throws are only allowed into a blockstun frame lock; `case "throw"` now manufactures the lock first | `0 empty grabs`, throws 32/32 |
| 8 | 8 matches recorded as draws | The mock also ate `budget 120`, and the budget cut matches off at about tick 1400, polluting every metric | `Infinity` when running mock without an explicit `--budget` | After the fix, average round length and win/loss records are normal |

Conclusion: every side of the triangle now has a non-zero, reproducible success path pinned down by tests; the throw edge was the last to close, and it needed **frame data (reach/forward pressure) + the move graph (strong cancels into throw) + the policy gate (only into the frame lock)** to hold at the same time.

---

## 9. Test Inventory

`npm test` = 52 cases (`node --test` reports wrong results on this machine's Node, so it has to go through npm).

**32 engine cases**: world initialization and HP; clean-hit damage + freeze; blocking a high costs chip only; a low goes through a stand block / is stopped by a crouch block; `jab→strong→launcher` cancels through three links and launches; launcher cancels into jump + airborne extension (4+ cap); damage scaling floor; KO terminates; chip ratios on block (strike/projectile); pure defense cannot be chipped to death; counter-hit bonus damage/hitstun/event; no counter bonus outside startup; throw breaks the guard (full damage + knockdown + no combo count); a throw catches a startup but not a jump; a throw cannot fill a combo / cannot hit a downed opponent; burst spends 50, clears hitstun, and pushes both fighters apart; the three ways burst is refused; burst can be used again; super costs full meter and cannot come out without it; super damage and chip on block; meter accrues only from clean hits; eating one full route buys exactly the next burst; a whiff is recorded as a punish window; a whiffed throw reports itself as a whiffed throw; a jump-in overhead breaks a crouch block / is stopped by a stand block; a block pushes the attacker out of range too; a jump carries its direction at takeoff; **armor keeps the guard but does not change coverage height**; **the window from the blocked hit survives the freeze and can still cancel**; **that window is wide enough to connect a throw**; an unanswered projectile is announced.

**20 decision-layer cases**: low confidence keeps combo and downgrades heavy; a strong threat escalates to block; the engine only hard-defends against a confirmed hit; it does not reach out in front of an about-to-be-active hitbox; **a throw in startup gets jumped rather than guarded**; defense reads height (an airkick overhead is not a threat); an incoming projectile is answered by guarding or jumping according to the space left; a whiff opens a window that gets the heaviest feasible punish; the state presents the punish window in frames rather than adjectives; **each guard is given the one answer it cannot stop** (stand→low, crouch→jump-in, locked stand→low, locked crouch→close throw); **the cancel window records the crack**; **the committed guard and height are held through blockstun**; **a descending jump-in throws out an overhead instead of landing in place**; the guard height is a planned bet rather than a table lookup; the fighter-relative viewpoint of `serializeState`; the state exposes the new reads and reach; the policy only attacks when it pays (including "do not throw at a free opponent, do throw at a locked one"); a full-meter finish does not cash out on the first hit; the JEV brain can pressure a passive opponent (the pipeline works end to end); two brains decide simultaneously and their latency is recorded.

---

## 10. Known Weaknesses and Deferred Work

- **The 21.3% defense share sits just under the ≥22% target**, and it is deliberately left alone: the only lever is raising the mock's guard probability, which feeds exactly the turtling behavior this ledger measures — buying a green light by weakening the thing under test.
- **The 32/32 tick-throw conversion rate is an artifact of construction** (throws only go into a frame lock, and a frame lock cannot answer). The rule itself is right, but it means the counterplay lives inside the decision "do I keep guarding while in throw range," and the persona heuristics do not model it yet. A human with real reaction time is its external test.
- **The largest counter-hit leak, `super > into jab` (64 times)**: super has only 6 startup frames and can cancel off any hit, so it intercepts pokes that were not aimed at it. Tightening it is a frame-data question, not a policy question.
- The throw edge is still the smallest in magnitude (32 times over 64 matches vs 168 lows). Its ceiling comes from the number of "mid-range pokes blocked within 98px," which is on the aggression side of the plan, not a missing rule.
- Not implemented yet: rounds / best-of-three, air blocking, corner rewards, whiff-cancel baits, frame-advantage signals for the JEV to read, a second character's movelist, meter contention between burst(50) and super(100), and netplay.
- Presentation gaps (the user explicitly excluded these from this round): no animation transitions, no camera, no sound, no hit-stop presentation.

---

## 11. Runbook

```bash
cd stick-figure-jev
export TYPESAFE_API_KEY=...            # read only by the Node side
npm test                               # 52 cases, offline, free
node scripts/probe.mjs                 # online endpoint connectivity (spends a little budget)
node scripts/spar.mjs --mock --games 64 --seconds 45   # ledger, deterministic
node scripts/spar.mjs --mock --fast --p1 rushdown --p2 counter
node scripts/spar.mjs --live --p1 counter --p2 rushdown --model1 jev-latest --model2 jev-1.13.0 --json spar-ab.json
node server/server.js                  # http://127.0.0.1:8787 (PORT overrides)
```

- `--fast` only affects the pacing of **live spectating** (`spar.mjs` inserts the delay only under `if (useLive && !opts.fast)`); it has no effect on results, the ledger, or determinism, and under `--mock` it makes no difference either way.

- `spar` defaults to `budget 120` per brain; under mock without an explicit `--budget` it is set to `Infinity` (see §8 item 8).
- With no key, the server reports `has_key:false`, the browser attaches the mock brain automatically, and **you can use that for zero-budget verification**.
- Current state of browser verification: page load, both fighters initializing (x=288 / x=612), `mode:pve`, `live:false`, a 900×340 canvas, and no console errors are all confirmed; **a screenshot confirming the picture was not possible** — this environment's in-app browser has no visible viewport, rAF pauses while the tab is hidden, and the canvas has not produced a single drawn pixel. So "the stick figures are visible" was **not visually verified** this round and needs your confirmation in an open window.
- `.gitignore` already covers `node_modules/`, `.env`, `*.log`, `spar-*.json`. The whole directory is still **untracked, not in git**, with no version safety net.

---

## 12. Conclusion Correction Log

An engineering record has to keep the claims that were overturned, otherwise whoever picks this up next will go change the code for the wrong reason:

1. The "defense reflex distance bug" was once described as **the mirrored distance check being written backwards**. Wrong. Once the fighter auto-faces the opponent, that explanation does not hold; the real defect was **a missing height check**. The code comment has been changed, and §8#1 is authoritative.
2. It was once reported that "the throw has already landed 16 times." Wrong — a line of grep output read backwards (it actually said `0 grabs landed`). §7's `throw 32 attempted / 32 landed / 0 empty grabs` is authoritative.
3. Probe output was once described from reasoning, along with a claim that two changes would be made (dropping the `cancelOpen` requirement in 2c, and zeroing the defender's hitstop to extend armor). **Neither was implemented**; 2c still requires `me.action.cancelOpen` in the code. The only things that actually landed are the #1–#8 entries in the §8 table.
4. It was once asserted that "pushback is why throws whiff," and that was falsified with a byte-identical ledger run. That falsification was invalid: at the time every throw request was being rejected by a **missing move graph upstream**, so of course changing the reach showed no difference. The lesson is written into the `moves.js` comment — tuning a downstream parameter while the chain is cut upstream does not constitute evidence.
5. The document once said "5 judgments (1 choice + 3 noul + 1 score)." It is actually **6 (2 choice + 3 noul + 1 score)**; `guard_stance` was added later, and both the README and this document have been corrected.
