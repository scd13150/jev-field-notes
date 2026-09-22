import { test } from "node:test";
import assert from "node:assert/strict";
import { createWorld, stepWorld } from "../src/engine/engine.js";
import { FIGHTER, METER } from "../src/engine/constants.js";
import { MOVES } from "../src/engine/moves.js";
import { JevBrain } from "../src/jev/brain.js";
import { makeMockDecider } from "../src/jev/mock.js";
import { compilePlan, executePlan } from "../src/jev/policy.js";
import { serializeState } from "../src/jev/state.js";

// Yield so the brain's async decider promise handlers run between frames.
const flush = () => new Promise((r) => setImmediate(r));

async function run(world, brains, frames) {
  for (let i = 0; i < frames && !world.over; i++) {
    const inputs = brains.map((b) => b.getInput(world));
    stepWorld(world, inputs);
    for (const b of brains) b.observe(world);
    if (i % 2 === 0) await flush();
  }
}

test("compilePlan keeps a shaky combo but de-risks a shaky heavy commitment", () => {
  // Running a combo string is cheap to attempt (the sequencer only continues
  // while links actually connect), so a low-confidence combo read is kept.
  const combo = compilePlan({ intent: { choice: "combo", confidence: 0.1 }, aggression: { score: 1 } });
  assert.equal(combo.strategy, "combo", "a committed string is worth running anyway");
  // A whiffed heavy, by contrast, is a real opening for the foe, so it degrades.
  const heavy = compilePlan({ intent: { choice: "heavy", confidence: 0.1 }, aggression: { score: 1 } });
  assert.notEqual(heavy.strategy, "heavy", "a shaky heavy is downgraded");
  const conf = compilePlan({ intent: { choice: "heavy", confidence: 0.9 }, aggression: { score: 1.7 } });
  assert.equal(conf.strategy, "heavy", "a confident read is kept");
});

test("compilePlan escalates to guard on a strong threat read", () => {
  const p = compilePlan({ intent: { choice: "space_control", confidence: 0.9 }, threat_now: { noul: 0.9 } });
  assert.ok(["block", "space_control"].includes(p.strategy));
});

test("executePlan guards when the engine sees a committed attack in range", () => {
  const w = createWorld();
  const me = w.fighters[0], foe = w.fighters[1];
  me.x = 440; foe.x = 480; me.facing = 1;
  foe.action = { move: "jab", moveDef: MOVES.jab, frame: 1, phase: "startup", hitConsumed: false };
  const plan = compilePlan({ intent: { choice: "poke", confidence: 0.9 }, threat_now: { noul: 0.8 } });
  const input = executePlan(plan, w, 0);
  assert.ok(input.hold.block, "guard engaged");
});

test("a poke is never thrown into a hitbox that is about to go live", () => {
  // Their jab has 4 startup frames left and ours needs 4: pressing is a trade, and
  // the trade is what a counter-hit is made of. Only a slow commitment — one with
  // more startup than our jab plus margin — may be interrupted.
  const w = createWorld();
  const me = w.fighters[0], foe = w.fighters[1];
  me.x = 440; foe.x = 480; me.facing = 1;
  foe.action = { move: "jab", moveDef: MOVES.jab, frame: 0, phase: "startup", hitConsumed: false };
  const plan = compilePlan({
    intent: { choice: "poke", confidence: 0.9 },
    counter_hit: { noul: 0.95 }, punish_window: { noul: 0.95 },
  });
  const input = executePlan(plan, w, 0);
  assert.ok(input.hold.block, "we guard the fast poke instead");
  assert.ok(!input.press.includes("jab"), "and press nothing");

  foe.action = { move: "sweep", moveDef: MOVES.sweep, frame: 0, phase: "startup", hitConsumed: false };
  const preempt = executePlan(plan, w, 0);
  assert.ok(!preempt.hold.block, "a 9-frame sweep is slow enough to be interrupted");
  assert.ok(preempt.press.length > 0, "so we press into its startup");
});

test("a grab in startup is jumped over, not guarded", () => {
  // Blocking is the reply that loses to a throw, and no strike of ours beats its 3
  // startup frames. A grab cannot catch a jumped foe, so the reflex leaves the
  // range rather than eating 120 damage politely.
  const w = createWorld();
  const me = w.fighters[0], foe = w.fighters[1];
  me.x = 440; foe.x = 470; me.facing = 1;
  foe.action = { move: "throw", moveDef: MOVES.throw, frame: 0, phase: "startup", hitConsumed: false };
  const plan = compilePlan({ intent: { choice: "block", confidence: 0.9 }, threat_now: { noul: 0.9 } });
  const input = executePlan(plan, w, 0);
  assert.ok(input.press.includes("jump"), "jump is the answer to a grab");
  assert.ok(!input.hold.block, "and the guard is not engaged");
});

test("the guard reads height: an airkick over our head is not a threat", () => {
  const w = createWorld();
  const me = w.fighters[0], foe = w.fighters[1];
  me.x = 440; foe.x = 486; foe.facing = -1; me.facing = 1;
  foe.onGround = false; foe.y = 141; // jump apex
  foe.action = { move: "airkick", moveDef: MOVES.airkick, frame: 3, phase: "active", hitConsumed: false };
  const plan = compilePlan({ intent: { choice: "poke", confidence: 0.9 } });
  const input = executePlan(plan, w, 0);
  assert.ok(!input.hold.block, "a box 130px up cannot hit a standing body, so we do not freeze on it");

  foe.y = 40; // the same kick on the way down really is overhead
  assert.ok(executePlan(plan, w, 0).hold.block, "and the reflex guards once it can reach us");
});

test("an incoming shot is blocked or jumped over, depending on the room left", () => {
  const w = createWorld();
  const me = w.fighters[0], foe = w.fighters[1];
  me.x = 400; foe.x = 620; foe.facing = -1; me.facing = 1;
  const shot = (x) => ({ owner: 1, move: MOVES.fireball, x, y: 70, vx: -7.5, w: 30, h: 26, life: 100, consumed: false });
  const go = compilePlan({ intent: { choice: "combo", confidence: 0.9 }, aggression: { score: 1.6 } });
  const duck = compilePlan({ intent: { choice: "space_control", confidence: 0.9 }, aggression: { score: 0.2 } });

  w.projectiles.push(shot(520)); // 120px out: ~11 frames until it can touch us
  const locked = { move: "fireball", moveDef: MOVES.fireball, frame: 3, phase: "recovery", hitConsumed: false };

  foe.action = locked;
  assert.ok(executePlan(go, w, 0).press.includes("jump"), "a fighter who means to close jumps the fireball");
  assert.ok(executePlan(go, w, 0).hold.right, "and drifts forward on the way over, which is the whole point");

  w.projectiles.length = 0; w.projectiles.push(shot(430));
  assert.ok(executePlan(go, w, 0).hold.block, "with no room to rise there is nothing left but the guard");

  w.projectiles.length = 0; w.projectiles.push(shot(520));
  assert.ok(executePlan(duck, w, 0).hold.block, "a plan that is not walking in never gambles on the hop");

  foe.action = null; // they fired, recovered, and are now free to anti-air us
  assert.ok(executePlan(go, w, 0).hold.block, "hopping a shot from a foe who can still act is a free anti-air");

  w.projectiles.length = 0; w.projectiles.push(shot(300)); // behind us, travelling away
  assert.ok(!executePlan(go, w, 0).hold.block, "a shot that has passed is no longer a threat");
});

test("an empty grab is answered with the heaviest punish that fits the window", () => {
  // 14 frames of helplessness is the price of whiffing a throw, and the triangle
  // only exists if that price is actually collected: launcher (7f startup) beats
  // strong and jab on damage, so the window decides, not a mood.
  const w = createWorld();
  const me = w.fighters[0], foe = w.fighters[1];
  me.x = 440; foe.x = 470; me.facing = 1;
  foe.action = { move: "throw", moveDef: MOVES.throw, frame: 2, phase: "recovery", hitConsumed: false };
  const plan = compilePlan({ intent: { choice: "poke", confidence: 0.9 } });
  assert.deepEqual(executePlan(plan, w, 0).press, ["launcher"], "free frames buy the biggest move");

  foe.action = { move: "throw", moveDef: MOVES.throw, frame: 12, phase: "recovery", hitConsumed: false };
  const late = executePlan(plan, w, 0);
  assert.ok(late.press.includes("jab") || late.hold.right === true, "a 4-frame window only risks a jab or nothing");
  assert.ok(!late.press.includes("launcher"), "and never a launcher we would be caught in");

  // A hit they DID connect is not a whiff: their recovery is not ours to take.
  foe.action = { move: "throw", moveDef: MOVES.throw, frame: 2, phase: "recovery", hitConsumed: true };
  assert.equal(executePlan(plan, w, 0).press.includes("launcher"), false, "no punish claimed off a connected throw");
});

test("the state shows JEV the punish window in frames, not adjectives", () => {
  const w = createWorld();
  const me = w.fighters[0], foe = w.fighters[1];
  me.x = 440; foe.x = 470; me.facing = 1;
  foe.action = { move: "throw", moveDef: MOVES.throw, frame: 2, phase: "recovery", hitConsumed: false };
  const s = serializeState(w, 0);
  assert.equal(s.punish_frames, 14);
  assert.equal(s.reads.foe_whiffed, true, "they swung and missed");
  assert.equal(s.punishable, true, "and something reaches");
});

test("each guard gets the one answer it cannot cover", () => {
  const w = createWorld();
  const me = w.fighters[0], foe = w.fighters[1];
  me.x = 440; foe.x = 545; me.facing = 1; // mid band: sweep reaches, a grab does not
  const plan = compilePlan({ intent: { choice: "poke", confidence: 0.9 }, aggression: { score: 1.6 } });

  foe.lastInput = { hold: { block: true }, press: [] };
  assert.deepEqual(executePlan(plan, w, 0).press, ["sweep"], "a standing block eats the low");

  foe.lastInput = { hold: { block: true, down: true }, press: [] };
  assert.deepEqual(executePlan(plan, w, 0).press, ["jump"],
    "a crouch guard eats every ground strike, so the answer is the jump-in");

  // Mid-blockstun the guard stays up but its height cannot change, so the stance
  // they committed to on the first blocked hit is published for the rest of the
  // string — and the matching answer is free money, not a guess.
  foe.blockstun = 6;
  foe.lastInput = { hold: { block: true }, press: [] };
  assert.deepEqual(executePlan(plan, w, 0).press, ["sweep"], "a locked standing guard still eats the low");

  foe.lastInput = { hold: { block: true, down: true }, press: [] };
  assert.deepEqual(executePlan(plan, w, 0).press, ["jump"], "a locked crouch guard still eats everything but the overhead");

  // Point blank the two stances split. A standing guard is already transparent to
  // the low, so the risk-free sweep outranks the grab; a crouch covers the sweep, and
  // against that the grab is the answer that cannot be blocked at either height.
  foe.x = 486;
  foe.lastInput = { hold: { block: true }, press: [] };
  assert.deepEqual(executePlan(plan, w, 0).press, ["sweep"], "a standing guard inside grab range still eats the low");

  foe.lastInput = { hold: { block: true, down: true }, press: [] };
  assert.deepEqual(executePlan(plan, w, 0).press, ["throw"], "a crouch has no answer to being caught");
});

test("the cancel window a blocked strike opens takes the crack on record", () => {
  // Blockstun is a few frames wide, so this is the one part of the mixup no plan can
  // time: the window itself drives the press, and JEV supplies only how much risk it
  // is willing to take. A guard committed to standing has a free low in front of it.
  const w = createWorld();
  const me = w.fighters[0], foe = w.fighters[1];
  me.x = 440; foe.x = 470; me.facing = 1;
  me.action = { move: "jab", moveDef: MOVES.jab, frame: 1, phase: "active", hitConsumed: true, cancelOpen: true };
  foe.blockstun = 6; foe.state = "block";
  const poke = compilePlan({ intent: { choice: "poke", confidence: 0.9 }, aggression: { score: 1.2 } });

  foe.lastInput = { hold: { block: true }, press: [] };
  assert.deepEqual(executePlan(poke, w, 0).press, ["sweep"], "the low is the risk-free crack, so a poke plan takes it");

  // A crouch covers the sweep, and a hop is not a link the jab lists — so the window
  // declines it and the grab is what a plan that asked for one gets instead.
  foe.lastInput = { hold: { block: true, down: true }, press: [] };
  const grab = compilePlan({ intent: { choice: "throw", confidence: 0.9 }, aggression: { score: 1.2 } });
  assert.deepEqual(executePlan(grab, w, 0).press, ["throw"], "the unblockable answer comes out of the blocked strike");

  const timid = compilePlan({ intent: { choice: "poke", confidence: 0.9 }, aggression: { score: 0 } });
  assert.notEqual(executePlan(timid, w, 0).press[0], "throw",
    "while a plan with no aggression in it will not gamble on the grab's 16 empty frames");

  foe.blockstun = 0; foe.state = "neutral"; foe.lastInput = { hold: {}, press: [] };
  assert.ok(!["sweep", "throw"].includes(executePlan(poke, w, 0).press[0]),
    "and a foe who is not holding guard cannot be cracked — the read still has to be true");
});

test("a fighter in blockstun keeps the guard and the stance they committed to", () => {
  const w = createWorld();
  const me = w.fighters[0], foe = w.fighters[1];
  me.x = 440; foe.x = 560; me.blockstun = 8; me.state = "block";
  foe.lastInput = { hold: {}, press: [] };
  const plan = compilePlan({ intent: { choice: "block", confidence: 0.9 }, guard_stance: { choice: "crouch" } });
  const s = executePlan(plan, w, 0);
  assert.ok(s.hold.block && s.hold.down,
    "the stance bet is held through the lockout instead of being re-guessed every frame");
});

test("a falling jump-in presses the overhead instead of landing harmlessly", () => {
  const w = createWorld();
  const me = w.fighters[0], foe = w.fighters[1];
  me.x = 440; foe.x = 480; me.facing = 1;
  me.onGround = false; me.y = 70; me.state = "airborne"; me.airAttackUsed = false;
  foe.lastInput = { hold: { block: true, down: true }, press: [] };
  const plan = compilePlan({ intent: { choice: "poke", confidence: 0.9 } });

  me.vy = 6; // still rising: the air attack stays in reserve
  assert.ok(!executePlan(plan, w, 0).press.includes("airkick"), "the hop does not swing on the way up");

  me.vy = -6; // falling, which is when the box comes down on top of them
  assert.deepEqual(executePlan(plan, w, 0).press, ["airkick"], "the overhead is the point of the hop");

  foe.lastInput = { hold: {}, press: [] };
  assert.ok(!executePlan(plan, w, 0).press.includes("airkick"),
    "and it is not dropped on a foe who is free to answer it — that is an anti-air, not a jump-in");
});

test("the guard stance is a bet from the plan, not a lookup of the incoming move", () => {
  const w = createWorld();
  const me = w.fighters[0], foe = w.fighters[1];
  me.x = 440; foe.x = 478; me.facing = 1;
  foe.action = { move: "sweep", moveDef: MOVES.sweep, frame: 2, phase: "startup", hitConsumed: false };

  const stand = compilePlan({ intent: { choice: "block", confidence: 0.9 } });
  assert.equal(stand.guardStance, "stand", "an answer that never arrived still yields a valid plan");
  const s = executePlan(stand, w, 0);
  assert.ok(s.hold.block && !s.hold.down, "a stand bet covers highs and eats the low — that is the mixup");

  const crouch = compilePlan({ intent: { choice: "block", confidence: 0.9 }, guard_stance: { choice: "crouch" } });
  const c = executePlan(crouch, w, 0);
  assert.ok(c.hold.block && c.hold.down, "the plan that called the low covers it");
});

test("serializeState exposes a fighter-relative view the questions can reference", () => {
  const w = createWorld();
  const s = serializeState(w, 1);
  assert.equal(s.self.name, "Crimson");
  assert.equal(s.foe.name, "Azure");
  assert.ok(typeof s.spacing.foe_lengths === "number");
  assert.ok("jab" in s.reach && "fireball" in s.reach);
});

test("the state advertises the new reads and reach so JEV can see the new rules", () => {
  const w = createWorld();
  w.fighters[0].x = 440; w.fighters[1].x = 470;
  const me = w.fighters[0], foe = w.fighters[1];
  me.meter = 100;
  foe.lastInput = { hold: { block: true }, press: [] };
  const s = serializeState(w, 0);
  assert.equal(s.reach.throw, true, "the grab is in range at 30px");
  assert.equal(s.reach.super, true, "so is the super");
  assert.equal(s.reads.foe_guarding, true, "their guard is readable");
  assert.equal(s.reads.self_can_super, true, "a full bar in range is a real option");
  assert.equal(s.reads.self_can_burst, false, "we are not stunned, so there is nothing to escape");

  foe.action = { move: "strong", moveDef: MOVES.strong, frame: 2, phase: "startup", hitConsumed: false, cancelOpen: false };
  const t = serializeState(w, 0);
  assert.equal(t.reads.foe_action_startup, true, "their startup is the counter-hit window");
  assert.equal(t.reads.foe_guarding, false, "and attacking out of block is not guarding");

  me.hitstun = 4; me.onGround = true;
  assert.equal(serializeState(w, 0).reads.self_can_burst, true, "stunned + affordable = burstable");
});

test("policy turns the new intents into presses, and only when they pay", () => {
  const w = createWorld();
  w.fighters[0].x = 440; w.fighters[1].x = 470; w.fighters[0].facing = 1;
  const me = w.fighters[0], foe = w.fighters[1];
  foe.lastInput = { hold: { block: true }, press: [] };

  const throwPlan = compilePlan({ intent: { choice: "throw", confidence: 0.9 }, aggression: { score: 1.6 } });
  // A guard that is free to leave the ground is a guard that will: every brain here
  // has the hop-the-grab reflex, so the throw plan spends a free turtle by poking to
  // lock them, and only spends the lock on the grab.
  assert.ok(!executePlan(throwPlan, w, 0).press.includes("throw"),
    "no grab at a foe who is guarding but free to jump it");
  foe.blockstun = 8;
  assert.ok(executePlan(throwPlan, w, 0).press.includes("throw"), "a locked turtle gets caught");
  foe.blockstun = 0;

  // Same intent, no guard up: walking in is right, and the engine would refuse a
  // throw on a knocked-down foe anyway.
  foe.lastInput = { hold: {}, press: [] };
  const noGuard = executePlan(throwPlan, w, 0);
  assert.ok(!noGuard.press.includes("throw"), "no throw without something to beat");
  assert.ok(noGuard.hold.right === true || noGuard.press.includes("jab"), "it closes the gap or pokes instead");

  foe.lastInput = { hold: { block: true }, press: [] };
  me.meter = METER.superCost;
  const superPlan = compilePlan({ intent: { choice: "super", confidence: 0.9 }, aggression: { score: 1.8 } });
  assert.ok(executePlan(superPlan, w, 0).press.includes("super"), "a full bar gets spent in range");
  me.meter = 40;
  assert.ok(!executePlan(superPlan, w, 0).press.includes("super"), "an empty-ish bar does not");
  me.meter = 100;
  assert.ok(!executePlan(compilePlan({ intent: { choice: "super", confidence: 0.1 } }), w, 0).press.includes("super"),
    "a shaky super read is downgraded, not fired");

  // Burst is a reflex: it fires off the read that we are genuinely comboed.
  const w2 = createWorld();
  const a = w2.fighters[0], b = w2.fighters[1];
  a.meter = 60; a.hitstun = 8; a.state = "hitstun"; b.combo.hits = 3;
  assert.ok(executePlan(compilePlan({ intent: { choice: "burst", confidence: 0.9 } }), w2, 0).press.includes("burst"),
    "burst while being comboed");
  b.combo.hits = 1;
  assert.ok(!executePlan(compilePlan({ intent: { choice: "poke" } }), w2, 0).press.includes("burst"),
    "but never to escape a single poke");
});

test("a full bar ends the route instead of cutting it short on the first hit", () => {
  const w = createWorld();
  w.fighters[0].x = 400; w.fighters[1].x = 456;
  const me = w.fighters[0], foe = w.fighters[1];
  me.meter = METER.superCost;
  me.combo = { hits: 1, damage: 42, juggle: 0 };
  me.action = { move: "jab", moveDef: MOVES.jab, frame: 1, phase: "recovery", hitConsumed: true, cancelOpen: true };
  foe.hitstun = 14; // the jab confirmed, so a super cancel would technically be legal now

  const plan = compilePlan({ intent: { choice: "combo", confidence: 0.9 }, aggression: { score: 1.8 } });
  assert.deepEqual(executePlan(plan, w, 0).press, ["strong"],
    "the string keeps linking — cashing the bar on hit one would halve the combo ceiling");
});

test("a JEV rushdown brain walks in and damages a passive opponent (pipeline works)", async () => {
  const w = createWorld({ p2Name: "Dummy" });
  const brain = new JevBrain({ meId: 0, decider: makeMockDecider({ persona: "rushdown" }), persona: "rushdown" });
  const dummy = { getInput: () => ({ hold: {}, press: [] }), observe: () => {} };
  await run(w, [brain, dummy], 360); // 6s of frames with real async decisions interleaved
  assert.ok(brain.stats().decisions > 3, "brain issued multiple JEV decisions");
  assert.ok(w.fighters[1].hp < FIGHTER.startHP, "the JEV fighter dealt damage");
});

test("dual-JEV: two brains both decide and fight, recording latency", async () => {
  const w = createWorld();
  const b0 = new JevBrain({ meId: 0, decider: makeMockDecider({ persona: "rushdown" }), persona: "rushdown" });
  const b1 = new JevBrain({ meId: 1, decider: makeMockDecider({ persona: "zoner" }), persona: "zoner" });
  await run(w, [b0, b1], 480);
  assert.ok(b0.stats().decisions > 2 && b1.stats().decisions > 2, "both JEV brains ran");
  assert.equal(b0.errors + b1.errors, 0, "no decision errors");
  assert.ok(w.tick > 100);
});
