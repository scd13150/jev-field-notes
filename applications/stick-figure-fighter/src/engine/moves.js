// Skill (move) table. Frame data is in ticks at 60fps.
//
// This is the "combinable skills" surface the objective asks for: every move
// declares `cancelOn` (the events that open a cancel window) and `cancelInto`
// (the moves it can be linked into). The engine enforces these links, so combos
// are discovered through the skill graph rather than hardcoded strings.
//
// hitbox: offset from fighter center (x forward in facing direction, y up),
// plus w/h of the axis-aligned box. level 'high'|'low' vs crouch/block rules.
// type "grab" bypasses block but only catches a grounded foe. meterCost is spent
// by startMove; unblockable/meterGain are read by the engine's hit resolution.
//
// The stance game the table is built to support, and the answer to each guard:
//   standing block  covers highs and mids -> beat it with `sweep` (low)
//   crouch block    covers lows and ground strikes -> beat it with `airkick` (overhead)
//   either block    is beaten by `throw`, which is unblockable but whiffs on a
//                   jumped foe, and a whiffed grab is the punish window
// so every defensive habit has exactly one wrong answer.

import { METER } from "./constants.js";

export const MOVES = {
  jab: {
    name: "jab", type: "strike", level: "high",
    startup: 4, active: 3, recovery: 7,
    damage: 42, hitstun: 16, blockstun: 9,
    knockback: { x: 3.2, y: 0 },
    hitbox: { x: 44, y: 82, w: 52, h: 26 },
    // The jab is the safe poke, so it is also the one strike that can drop into a
    // grab: blocked jab -> tick throw is the price of holding down back. It also
    // super-cancels, which is how a meter bar gets spent on a confirmed hit.
    cancelOn: ["hit", "block"], cancelInto: ["strong", "launcher", "sweep", "fireball", "throw", "super"],
    meterGain: true,
  },
  strong: {
    name: "strong", type: "strike", level: "high",
    startup: 8, active: 4, recovery: 14,
    damage: 86, hitstun: 22, blockstun: 12,
    knockback: { x: 6.0, y: 0 },
    hitbox: { x: 56, y: 74, w: 66, h: 34 },
    // Both reliable pokes super-cancel, so a confirmed hit is what spends the bar
    // (the launcher deliberately does not: its own route is the jump-in juggle).
    // `sweep` and `throw` are the two answers a blocked heavy has to have. A pooled
    // probe over three matches found the blockstun window open inside grab range 26
    // times and the foe crouching in all 26 — the policy pressed the grab every one
    // of those frames and the engine refused it 26 times, because this list named
    // no grab. Whichever strike does the blocking is the strike that has to be able
    // to keep the promise; a link only the jab owns is a link the mid band never uses.
    cancelOn: ["hit", "block"], cancelInto: ["launcher", "fireball", "sweep", "throw", "super"],
    meterGain: true,
  },
  launcher: { // uppercut: launches into a juggle for air extensions
    name: "launcher", type: "strike", level: "high",
    startup: 7, active: 5, recovery: 26,
    damage: 78, hitstun: 26, blockstun: 14,
    knockback: { x: 2.5, y: 16 }, launch: true,
    hitbox: { x: 40, y: 96, w: 50, h: 82 },
    // Cancel on hit lets the launcher's long recovery be cut by a jump, so the
    // attacker rises INTO the juggle and extends with air attacks. This is what
    // makes the launcher->jump->airkick air combo reachable instead of a dead
    // `cancelInto` entry.
    cancelOn: ["hit"], cancelInto: ["jump"],
    meterGain: true,
  },
  sweep: { // low: must be blocked crouching; knocks down on hit
    name: "sweep", type: "strike", level: "low",
    startup: 9, active: 4, recovery: 22,
    damage: 70, hitstun: 24, blockstun: 12,
    knockback: { x: 4.0, y: 0 }, knockdown: true,
    hitbox: { x: 58, y: 10, w: 70, h: 26 },
    cancelOn: [], cancelInto: [],
    meterGain: true,
  },
  fireball: { // projectile: space control, clashable
    name: "fireball", type: "projectile", level: "high",
    startup: 12, active: 0, recovery: 22,
    damage: 55, hitstun: 20, blockstun: 12,
    knockback: { x: 5.0, y: 0 },
    projectile: { speed: 7.5, w: 30, h: 26, y: 70, life: 160 },
    cancelOn: [], cancelInto: [],
    meterGain: true,
  },
  airkick: { // air strike; extends juggled opponents (box reaches UP to the launched foe)
    name: "airkick", type: "strike", level: "high", air: true,
    // The overhead of the stance game: a crouching guard covers every low and
    // every ground strike, and this is the one attack it cannot cover. It is why
    // jumping in against a turtle is a real answer rather than a wasted hop.
    overhead: true,
    startup: 5, active: 6, recovery: 10,
    damage: 64, hitstun: 22, blockstun: 10,
    knockback: { x: 4.0, y: 4 },
    hitbox: { x: 42, y: 46, w: 58, h: 88 }, // above/forward of the airborne body, to meet a juggle
    juggleAdd: 2,
    cancelOn: [], cancelInto: [],
    meterGain: true,
  },
  throw: { // command grab: the answer to a foe who will not leave block
    name: "throw", type: "grab", level: "high",
    startup: 3, active: 4, recovery: 16,
    damage: 120, hitstun: 20, blockstun: 0,
    knockback: { x: 6, y: 0 }, knockdown: true,
    // Reach 98 (hitbox.x + w/2 + halfWidth) and a 5px/frame step-in. Both numbers are
    // the measured price of cancelling out of a block, not taste:
    //   - Holding guard buys ~30px of blockback in this engine, so a grab has to
    //     out-reach the strike that opens its window. At the old 74px it was the
    //     shortest-reaching attack on the table — shorter than jab (92), strong (111)
    //     and sweep (115) — while being the only move those three can cancel into it
    //     from. Every tick throw therefore pressed against a body already out of it.
    //   - The blockback does not even arrive until the freeze ends: a block sets
    //     hitstop and blockstun to ~12 frames each, so the guard's lock is consumed by
    //     the freeze and the deferred slide lands exactly while the grab's box comes
    //     out. Hence the step-in, which real command grabs have for the same reason.
    // Stay under the strong's reach: a blocked heavy should threaten a low, not an
    // unconditional 120-damage throw.
    hitbox: { x: 46, y: 60, w: 60, h: 80 },
    lunge: 5,
    unblockable: true,
    cancelOn: [], cancelInto: [],
    meterGain: false,
  },
  super: { // full-meter finisher; cancels off any hit, so it is the reward for poking well
    name: "super", type: "strike", level: "high",
    startup: 6, active: 8, recovery: 20,
    damage: 260, hitstun: 28, blockstun: 18,
    knockback: { x: 5, y: 0 },
    hitbox: { x: 60, y: 80, w: 90, h: 80 },
    meterCost: METER.superCost,
    cancelOn: ["hit"], cancelInto: [],
    meterGain: false,
  },
  // Movement / defensive actions (no hitbox).
  jump: { name: "jump", type: "movement", startup: 0, active: 0, recovery: 0 },
  dash: { name: "dash", type: "movement", startup: 0, active: 0, recovery: 0 },
  block: { name: "block", type: "defensive" },
  crouch: { name: "crouch", type: "defensive" },
};

export const STRIKE_ORDER = ["jab", "strong", "launcher", "sweep", "fireball", "airkick"];
