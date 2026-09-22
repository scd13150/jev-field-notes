import { test } from "node:test";
import assert from "node:assert/strict";
import { createWorld, stepWorld, hurtbox } from "../src/engine/engine.js";
import { ARENA, FIGHTER, DAMAGE_SCALE, MAX_JUGGLE, METER, CHIP } from "../src/engine/constants.js";
import { MOVES } from "../src/engine/moves.js";

const in0 = (o = {}) => ({ hold: o.hold || {}, press: o.press || [] });
const inX = (o = {}) => ({ hold: o.hold || {}, press: o.press || [] });

function closeFighters(world, gap = 60) {
  world.fighters[0].x = 400; world.fighters[1].x = 400 + gap;
}

test("world initialises two fighters with full HP", () => {
  const w = createWorld();
  assert.equal(w.fighters.length, 2);
  assert.equal(w.fighters[0].hp, FIGHTER.startHP);
  assert.equal(w.fighters[1].hp, FIGHTER.startHP);
});

test("a connected jab applies scaled damage and hitstop", () => {
  const w = createWorld();
  closeFighters(w, 58);
  w.fighters[0].facing = 1;
  stepWorld(w, [in0({ press: ["jab"] }), inX({})]);           // startup begins
  for (let i = 0; i < 8 && !w.over; i++) stepWorld(w, [in0(), inX({})]);
  assert.ok(w.fighters[1].hp < FIGHTER.startHP, "foe took damage");
  assert.equal(w.fighters[0].combo.hits, 1);
});

test("blocking a high attack prevents all but chip damage", () => {
  const w = createWorld();
  closeFighters(w, 58);
  w.fighters[0].facing = 1;
  for (let i = 0; i < 10 && !w.over; i++) {
    stepWorld(w, [i === 0 ? in0({ press: ["jab"] }) : in0(), inX({ hold: { block: true } })]);
  }
  const lost = FIGHTER.startHP - w.fighters[1].hp;
  assert.ok(lost > 0, "a blocked poke still costs health");
  assert.ok(lost < MOVES.jab.damage / 2, "but only chip, not the jab");
  assert.equal(w.fighters[0].combo.hits, 0, "a blocked hit scores no combo");
});

test("low sweep bypasses a standing block but is blocked crouching", () => {
  const w = createWorld();
  closeFighters(w, 62);
  w.fighters[0].facing = 1;
  for (let i = 0; i < 14 && !w.over; i++) {
    stepWorld(w, [i === 0 ? in0({ press: ["sweep"] }) : in0(), inX({ hold: { block: true } })]);
  }
  assert.ok(w.fighters[1].hp < FIGHTER.startHP - MOVES.sweep.damage / 2, "low hits a standing guard");

  const w2 = createWorld();
  closeFighters(w2, 62); w2.fighters[0].facing = 1;
  for (let i = 0; i < 14 && !w2.over; i++) {
    stepWorld(w2, [i === 0 ? in0({ press: ["sweep"] }) : in0(), inX({ hold: { block: true, down: true } })]);
  }
  const crouchLost = FIGHTER.startHP - w2.fighters[1].hp;
  assert.ok(crouchLost > 0 && crouchLost < MOVES.sweep.damage / 2, "crouch-block reduces the low to chip");
  assert.equal(w2.fighters[0].combo.hits, 0, "and never knocks down");
});

test("jab -> strong -> launcher cancel link builds a multi-hit combo and launches", () => {
  const w = createWorld();
  closeFighters(w, 56);
  w.fighters[0].facing = 1;
  const me = w.fighters[0], foe = w.fighters[1];

  // Adaptive driver: press the current link every frame and advance only when the
  // engine reports the hit landed — the cancel window's timing is the engine's
  // job, so the test verifies the skill graph, not a hand-tuned input frame.
  const route = ["jab", "strong", "launcher"];
  let step = 0;
  for (let i = 0; i < 140 && step < route.length && !w.over; i++) {
    stepWorld(w, [in0({ press: [route[step]] }), inX({})]);
    if (me.combo.hits >= step + 1) step++;
  }
  assert.ok(me.combo.hits >= 3 || w.comboLog.some(c => c.hits >= 3),
    "three linked strikes registered as one combo");
  assert.ok(foe.juggling || foe.hp < FIGHTER.startHP, "launcher connected");
});

test("launcher cancels into a jump and an air attack extends the juggle (4+ hit ceiling)", () => {
  const w = createWorld();
  closeFighters(w, 56);
  w.fighters[0].facing = 1;
  const me = w.fighters[0], foe = w.fighters[1];

  // Drive the grounded string adaptively, then when the launcher connects, jump
  // and airkick the launched foe. The engine owns every cancel window; this only
  // proves the launcher -> jump -> airkick link is now reachable at all.
  const grounded = ["jab", "strong", "launcher"];
  let step = 0;
  for (let i = 0; i < 200 && !w.over; i++) {
    let press = [];
    if (me.onGround) {
      if (step < grounded.length) press = [grounded[step]];
      else if (me.combo.hits >= 3 && me.action && me.action.cancelOpen) press = ["jump"];
    } else if (foe.juggling) {
      press = ["airkick"];
    }
    stepWorld(w, [in0({ press }), inX({})]);
    if (me.combo.hits >= step + 1) step++;
    if (me.bestCombo.hits >= 4 || w.comboLog.some((c) => c.hits >= 4)) break;
  }
  assert.ok(
    me.bestCombo.hits >= 4 || w.comboLog.some((c) => c.hits >= 4),
    `air extension should push the combo past 4 hits (best=${me.bestCombo.hits})`
  );
});

test("combo damage is scaled down, giving the combo ceiling a finite cap", () => {
  // The scaling table is the mechanical ceiling: strictly non-increasing after
  // the first two free hits, and the first hit always lands at full value.
  assert.equal(DAMAGE_SCALE[0], 1.0);
  assert.ok(DAMAGE_SCALE[1] >= DAMAGE_SCALE[2], "scaling only bites on later hits");
  for (let i = 1; i < DAMAGE_SCALE.length; i++) {
    assert.ok(DAMAGE_SCALE[i] <= DAMAGE_SCALE[i - 1], "scaling never increases");
  }
  assert.ok(DAMAGE_SCALE[DAMAGE_SCALE.length - 1] > 0, "even the longest hit is worth something");
  assert.ok(Number.isFinite(MAX_JUGGLE), "juggle extension is bounded");
});

test("KO ends the match with a winner", () => {
  const w = createWorld();
  w.fighters[1].hp = 30;
  closeFighters(w, 56); w.fighters[0].facing = 1;
  for (let i = 0; i < 60 && !w.over; i++) {
    stepWorld(w, [in0(i % 8 === 0 ? { press: ["strong"] } : {}), inX({})]);
  }
  assert.equal(w.over, true);
  assert.equal(w.winner, 0);
  assert.equal(w.fighters[1].hp, 0);
});

// --- chip, counter-hits, throws and meter spends -----------------------------

const chipOf = (move, projectile = false) =>
  Math.max(1, Math.round(move.damage * (projectile ? CHIP.projectileRatio : CHIP.strikeRatio)));

const eventsOf = (w, kind) => w.events.filter((e) => e.kind === kind);

// Press `move` and run until the engine says the attack resolved, so no test has
// to hand-count startup frames.
function landMove(w, attacker, victim, move, victimInput = inX({})) {
  attacker.facing = victim.x >= attacker.x ? 1 : -1;
  for (let i = 0; i < 40 && !w.over; i++) {
    const before = w.events.length;
    stepWorld(w, [i === 0 ? in0({ press: [move] }) : in0(), victimInput]);
    const fresh = w.events.slice(before);
    const done = fresh.find((e) => ["hit", "block", "throw"].includes(e.kind) && e.by === attacker.id);
    if (done) return done;
  }
  return null;
}

test("a blocked strike chips a slice of its damage and reports it", () => {
  const w = createWorld();
  closeFighters(w, 58);
  const ev = landMove(w, w.fighters[0], w.fighters[1], "jab", inX({ hold: { block: true } }));
  assert.equal(ev.kind, "block");
  assert.equal(ev.chip, chipOf(MOVES.jab), "chip is the documented fraction of the move");
  assert.ok(ev.chip > 0 && ev.chip < MOVES.jab.damage / 2, "small, and far under the raw hit");
  assert.equal(w.fighters[1].hp, FIGHTER.startHP - ev.chip, "and it is the only HP cost of blocking");
});

test("a blocked projectile chips less than a blocked strike", () => {
  const w = createWorld();
  closeFighters(w, 120);
  const me = w.fighters[0];
  me.facing = 1;
  const before = w.events.length;
  for (let i = 0; i < 90 && !w.over; i++) {
    stepWorld(w, [i === 0 ? in0({ press: ["fireball"] }) : in0(), inX({ hold: { block: true } })]);
    const blocked = w.events.slice(before).find((e) => e.kind === "block" && e.by === me.id);
    if (blocked) {
      assert.equal(blocked.chip, chipOf(MOVES.fireball, true));
      assert.ok(blocked.chip < chipOf(MOVES.jab), "fireball chip is the cheaper chip");
      return;
    }
  }
  assert.fail("the fireball never reached a blocking foe");
});

test("chip alone can never KO a fighter who keeps blocking", () => {
  const w = createWorld();
  closeFighters(w, 58);
  const foe = w.fighters[1];
  foe.hp = 3;
  for (let i = 0; i < 400 && !w.over; i++) {
    stepWorld(w, [i % 12 === 0 ? in0({ press: ["jab"] }) : in0(), inX({ hold: { block: true } })]);
  }
  assert.equal(w.over, false, "a fully blocking foe survives any amount of chip");
  assert.ok(foe.hp >= 1, `hp floored at 1 (got ${foe.hp})`);
});

test("counter-hit pays bonus damage, bonus hitstun and an event", () => {
  const w = createWorld();
  closeFighters(w, 58);
  const me = w.fighters[0], foe = w.fighters[1];
  // The foe is mid-startup when our jab lands: the engine must read it as a
  // counter, not a normal hit.
  foe.action = { move: "strong", moveDef: MOVES.strong, frame: 1, phase: "startup", hitConsumed: false, cancelOpen: false };
  foe.state = "attack";
  const ev = landMove(w, me, foe, "jab");
  assert.equal(ev.kind, "hit");
  assert.equal(ev.counter, true, "the hit event says so");
  assert.equal(ev.dmg, Math.round(MOVES.jab.damage * 1.25), "25% over a plain jab");
  assert.ok(eventsOf(w, "counter_hit").length === 1, "a counter_hit event was emitted");
  assert.equal(eventsOf(w, "counter_hit")[0].victimMove, "strong", "and it names the move that got caught winding up");
  assert.equal(foe.hitstun, MOVES.jab.hitstun + 4, "and four extra frames of stun");
});

test("a plain hit on a winding-up-but-not-startup foe gets no bonus", () => {
  const w = createWorld();
  closeFighters(w, 58);
  const me = w.fighters[0], foe = w.fighters[1];
  foe.action = { move: "strong", moveDef: MOVES.strong, frame: 1, phase: "active", hitConsumed: true, cancelOpen: false };
  foe.state = "attack";
  const ev = landMove(w, me, foe, "jab");
  assert.equal(ev.counter, false, "no counter flag once their startup is spent");
  assert.equal(ev.dmg, MOVES.jab.damage);
});

test("a throw beats a blocking foe: full damage, knockdown, no combo credit", () => {
  const w = createWorld();
  closeFighters(w, 56);
  const me = w.fighters[0], foe = w.fighters[1];
  const ev = landMove(w, me, foe, "throw", inX({ hold: { block: true } }));
  assert.equal(ev.kind, "throw", "grabs bypass block instead of chipping it");
  assert.equal(ev.dmg, MOVES.throw.damage, "full damage, unscaled");
  assert.equal(foe.hp, FIGHTER.startHP - MOVES.throw.damage);
  assert.equal(foe.state, "knockdown", "thrown straight to the floor");
  assert.equal(me.combo.hits, 0, "a throw resets neutral, it is not combo filler");
  assert.equal(eventsOf(w, "block").length, 0, "and it never registers as a blocked poke");
});

test("a throw catches a foe winding up an attack, but whiffs on a jumped foe", () => {
  const w = createWorld();
  closeFighters(w, 56);
  const foe = w.fighters[1];
  foe.action = { move: "strong", moveDef: MOVES.strong, frame: 1, phase: "startup", hitConsumed: false, cancelOpen: false };
  foe.state = "attack";
  const ev = landMove(w, w.fighters[0], foe, "throw");
  assert.equal(ev.kind, "throw", "attacking through a grab attempt does not save you");

  const w2 = createWorld();
  closeFighters(w2, 56);
  const me2 = w2.fighters[0], foe2 = w2.fighters[1];
  for (let i = 0; i < 3; i++) stepWorld(w2, [in0({ press: ["throw"] }), inX({})]);
  // They leave the floor during our active frames: the grab is whiffed.
  foe2.onGround = false; foe2.y = 60; foe2.vy = 15; foe2.state = "airborne";
  for (let i = 0; i < 12 && !w2.over; i++) stepWorld(w2, [in0(), inX({})]);
  assert.equal(eventsOf(w2, "throw").length, 0, "nothing to grab up there");
  assert.ok(me2.combo.hits === 0 && foe2.hp === FIGHTER.startHP, "and the foe is untouched");
});

test("a grab cannot be used as combo filler or on a foe already down", () => {
  const w = createWorld();
  closeFighters(w, 56);
  const me = w.fighters[0], foe = w.fighters[1];
  foe.hitstun = 14;
  foe.state = "hitstun";
  for (let i = 0; i < 12 && !w.over; i++) stepWorld(w, [in0({ press: ["throw"] }), inX({})]);
  assert.notEqual(me.action?.move, "throw", "the engine refused the grab onto a stunned foe");
  assert.equal(eventsOf(w, "throw").length, 0);
  assert.equal(foe.hp, FIGHTER.startHP, "so a throw can never extend a combo");

  const w2 = createWorld();
  closeFighters(w2, 56);
  const foe2 = w2.fighters[1];
  foe2.state = "knockdown"; foe2.knockdownTimer = 40; foe2.onGround = true;
  for (let i = 0; i < 12 && !w2.over; i++) stepWorld(w2, [in0({ press: ["throw"] }), inX({})]);
  assert.equal(eventsOf(w2, "throw").length, 0, "and no free damage on a foe who is getting up");
});

test("burst spends 50 meter to cancel hitstun and push both fighters back", () => {
  const w = createWorld();
  closeFighters(w, 60);
  const me = w.fighters[0], foe = w.fighters[1];
  me.meter = METER.burstCost;
  me.hitstun = 12;
  me.state = "hitstun";
  foe.combo.hits = 3;
  const before = me.x;
  stepWorld(w, [in0({ press: ["burst"] }), inX({})]);
  assert.equal(me.hitstun, 0, "the stun is gone");
  assert.equal(me.meter, 0, "and paid for");
  assert.ok(me.invuln >= METER.burstInvuln - 1, `invulnerable for ${me.invuln} frames`);
  assert.equal(eventsOf(w, "burst").length, 1);
  assert.ok(Math.abs(me.x - before) >= METER.burstPush - 2, "the escape resets spacing");
  assert.ok(foe.combo.hits <= 1, "the combo that had us is broken");
});

test("burst is refused without meter, while airborne, and twice in one stun", () => {
  const w = createWorld();
  closeFighters(w, 60);
  const me = w.fighters[0];
  me.hitstun = 12; me.state = "hitstun"; me.meter = METER.burstCost - 1;
  stepWorld(w, [in0({ press: ["burst"] }), inX({})]);
  assert.equal(me.hitstun, 11, "broke: nothing happens, just the normal timer tick");
  assert.equal(me.meter, METER.burstCost - 1, "and nothing is charged");

  me.meter = 100; me.onGround = false; me.y = 50;
  stepWorld(w, [in0({ press: ["burst"] }), inX({})]);
  assert.ok(me.hitstun > 0, "an airborne fighter cannot burst");

  const w2 = createWorld();
  closeFighters(w2, 60);
  const a = w2.fighters[0];
  a.meter = 100; a.hitstun = 20; a.state = "hitstun";
  stepWorld(w2, [in0({ press: ["burst"] }), inX({})]);
  assert.equal(eventsOf(w2, "burst").length, 1);
  a.hitstun = 20; a.state = "hitstun";
  stepWorld(w2, [in0({ press: ["burst"] }), inX({})]);
  assert.equal(eventsOf(w2, "burst").length, 1, "one burst per stun episode");
});

test("a fighter who burst once can burst again the next time they are comboed", () => {
  const w = createWorld();
  closeFighters(w, 58);
  const me = w.fighters[0], foe = w.fighters[1];
  me.meter = 100;
  me.hitstun = 12; me.state = "hitstun"; foe.combo.hits = 3;
  stepWorld(w, [in0({ press: ["burst"] }), inX({})]);
  assert.equal(eventsOf(w, "burst").length, 1, "the first escape lands");

  for (let i = 0; i < 24 && !w.over; i++) stepWorld(w, [in0({}), inX({})]);
  assert.equal(me.invuln, 0, "the burst invulnerability has drained");
  for (let i = 0; i < 24 && me.hitstun === 0 && !w.over; i++) {
    stepWorld(w, [in0({}), inX({ press: ["jab"] })]);
  }
  assert.ok(me.hitstun > 0, "a fresh combo has us again");
  stepWorld(w, [in0({ press: ["burst"] }), inX({})]);
  assert.equal(eventsOf(w, "burst").length, 2,
    "burst re-arms per combo — it is not a once-per-match button");
});

test("super costs the whole bar and cannot be started without it", () => {
  const w = createWorld();
  closeFighters(w, 100);
  const me = w.fighters[0];
  me.meter = METER.superCost - 1;
  stepWorld(w, [in0({ press: ["super"] }), inX({})]);
  assert.notEqual(me.action?.move, "super", "not enough meter");
  assert.equal(me.meter, METER.superCost - 1, "and the bar is untouched");

  me.meter = METER.superCost;
  stepWorld(w, [in0({ press: ["super"] }), inX({})]);
  assert.equal(me.action.move, "super", "now it comes out");
  assert.equal(me.meter, 0, "exactly the previous value minus the cost");
});

test("super lands for fight-changing damage and chips when blocked", () => {
  const w = createWorld();
  closeFighters(w, 100);
  const me = w.fighters[0];
  me.meter = METER.superCost;
  const ev = landMove(w, me, w.fighters[1], "super");
  assert.equal(ev.kind, "hit");
  assert.equal(ev.dmg, MOVES.super.damage, "a clean super pays full first-hit damage");

  const w2 = createWorld();
  closeFighters(w2, 100);
  const me2 = w2.fighters[0];
  me2.meter = METER.superCost;
  const blocked = landMove(w2, me2, w2.fighters[1], "super", inX({ hold: { block: true } }));
  assert.equal(blocked.kind, "block", "it is still blockable");
  assert.equal(blocked.chip, chipOf(MOVES.super), "and it chips like any other strike");
});

test("meter builds from hits that land, not from pokes that get blocked", () => {
  // Walk back in between pokes so the wall of jabs keeps reaching: this is about
  // what the two outcomes pay, not about spacing. Hitstop makes a jab-and-recover
  // cycle ~36 frames, hence the long window.
  const driver = (i) => in0(i % 40 === 0 ? { press: ["jab"] } : { hold: { right: true } });
  const w = createWorld();
  closeFighters(w, 58);
  const me = w.fighters[0], foe = w.fighters[1];
  for (let i = 0; i < 600 && !w.over; i++) stepWorld(w, [driver(i), inX({ hold: { block: true } })]);
  const blocked = eventsOf(w, "block").length;
  assert.ok(blocked >= 8, "many pokes were blocked");
  assert.equal(foe.hp, FIGHTER.startHP - blocked * chipOf(MOVES.jab), "chip added up, one slice at a time");
  assert.ok(me.meter < METER.superCost, "a wall of blocked pokes does not buy a super");

  const w2 = createWorld();
  closeFighters(w2, 58);
  const me2 = w2.fighters[0];
  for (let i = 0; i < 600 && !w2.over; i++) stepWorld(w2, [driver(i), inX({})]);
  assert.ok(eventsOf(w2, "hit").length >= 8, "the same pressure landed");
  assert.ok(!w2.over, "and the foe was not KO'd by it either");
  assert.ok(me2.meter >= METER.superCost, `clean hits build a bar (meter ${me2.meter})`);
});

test("eating a full route banks enough meter to burst out of the next confirm", () => {
  // The comeback rule, and the reason a confirmed poke is not a death sentence:
  // the defender earns meter from every clean hit they take, so one 4-hit route
  // buys the 50-meter escape for the next one.
  const w = createWorld();
  closeFighters(w, 58);
  const atk = w.fighters[0], def = w.fighters[1];
  const driver = (i) => in0(i % 40 === 0 ? { press: ["jab"] } : { hold: { right: true } });
  for (let i = 0; i < 600 && def.meter < METER.burstCost && !w.over; i++) {
    stepWorld(w, [driver(i), inX({})]);
  }
  assert.ok(eventsOf(w, "hit").length >= 4, "several clean hits landed");
  assert.ok(def.meter >= METER.burstCost, `defence paid for itself (meter ${def.meter})`);
  assert.ok(atk.meter >= def.meter, "but the attacker still leads the race");

  def.hitstun = 10; def.state = "hitstun"; def.burstUsed = false; atk.combo.hits = 3;
  stepWorld(w, [in0({}), inX({ press: ["burst"] })]);
  assert.equal(eventsOf(w, "burst").length, 1, "and the meter is spendable on an escape");
});

test("a swing that misses is reported as a whiff, marking the punish window", () => {
  const w = createWorld();
  closeFighters(w, 300); // out of every range: the jab cannot land
  stepWorld(w, [in0({ press: ["jab"] }), inX({})]);
  for (let i = 0; i < 12 && !eventsOf(w, "whiff").length; i++) stepWorld(w, [in0(), inX({})]);
  const ev = eventsOf(w, "whiff")[0];
  assert.ok(ev, "the missed swing is announced");
  assert.equal(ev.by, 0);
  assert.equal(ev.move, "jab");
  assert.equal(ev.grab, false, "a strike is not a grab");
  assert.equal(ev.recovery, MOVES.jab.recovery, "and the report carries how long they are locked");

  const w2 = createWorld();
  closeFighters(w2, 58);
  landMove(w2, w2.fighters[0], w2.fighters[1], "jab");
  assert.equal(eventsOf(w2, "whiff").length, 0, "a swing that connected is not a whiff");
});

test("a whiffed grab announces itself as a whiffed grab", () => {
  const w = createWorld();
  closeFighters(w, 300);
  w.fighters[0].meter = 0;
  stepWorld(w, [in0({ press: ["throw"] }), inX({})]);
  for (let i = 0; i < 14 && !eventsOf(w, "whiff").length; i++) stepWorld(w, [in0(), inX({})]);
  const ev = eventsOf(w, "whiff")[0];
  assert.ok(ev, "the empty grab is reported");
  assert.equal(ev.grab, true, "flagged as a grab, because that is the free-punish case");
  assert.equal(ev.recovery, MOVES.throw.recovery);
});

// Run a live airkick into a guarding foe held in one stance.
function jumpInOn(foeHold) {
  const w = createWorld();
  const me = w.fighters[0], foe = w.fighters[1];
  me.x = 440; foe.x = 482; me.facing = 1;
  me.onGround = false; me.y = 20; me.vy = 0; me.state = "airborne";
  me.action = { move: "airkick", moveDef: MOVES.airkick, frame: 1, phase: "active", hitConsumed: false };
  for (let i = 0; i < 5; i++) stepWorld(w, [in0(), inX({ hold: foeHold })]);
  return w;
}

test("the jump-in overhead beats a crouch guard and is blocked standing", () => {
  const crouching = jumpInOn({ block: true, down: true });
  assert.ok(eventsOf(crouching, "hit").length >= 1, "the overhead lands through a crouching guard");
  assert.equal(eventsOf(crouching, "block").length, 0, "which cannot cover the one attack from above");

  const standing = jumpInOn({ block: true });
  assert.ok(eventsOf(standing, "block").length >= 1, "a standing block does cover it");
  assert.equal(eventsOf(standing, "hit").length, 0);
});

test("a blocked strike pushes the attacker out of range as well", () => {
  const w = createWorld();
  closeFighters(w, 58);
  const me = w.fighters[0], foe = w.fighters[1];
  const x0 = me.x, d0 = Math.abs(foe.x - me.x);
  landMove(w, me, foe, "strong", inX({ hold: { block: true } }));
  for (let i = 0; i < 16; i++) stepWorld(w, [in0(), inX({ hold: { block: true } })]);
  assert.ok(me.x < x0 - 2, `the attacker slides back (${(x0 - me.x).toFixed(1)}px)`);
  assert.ok(Math.abs(foe.x - me.x) > d0, "so guard buys real distance back");
});

test("a jump carries the direction held at take-off", () => {
  const w = createWorld();
  closeFighters(w, 200);
  const me = w.fighters[0];
  const x0 = me.x;
  for (let i = 0; i < 60; i++) stepWorld(w, [in0({ hold: { right: true }, press: i === 0 ? ["jump"] : [] }), inX()]);
  assert.ok(me.onGround, "the hop ends");
  assert.ok(me.x > x0 + 100, `a jump-in arc crossed ${Math.round(me.x - x0)}px of ground`);

  const w2 = createWorld();
  closeFighters(w2, 200);
  const me2 = w2.fighters[0];
  const y0 = me2.x;
  for (let i = 0; i < 60; i++) stepWorld(w2, [in0({ press: i === 0 ? ["jump"] : [] }), inX()]);
  assert.ok(Math.abs(me2.x - y0) < 1, "with nothing held it is a vertical hop, not a drift");
});

test("blockstun keeps a guard up but does not change what it covers", () => {
  // A fighter frozen mid-block is still holding the direction they held, so the low
  // that follows a blocked high catches them standing. Treating blockstun as a
  // height-blind auto-block is what made `sweep` a dead move in play.
  const w = createWorld();
  closeFighters(w, 62);
  const me = w.fighters[0], foe = w.fighters[1];
  me.facing = 1;
  foe.blockstun = 20; foe.state = "block"; // long enough to still be locked when the sweep lands
  for (let i = 0; i < 18 && !w.over; i++) {
    stepWorld(w, [i === 0 ? in0({ press: ["sweep"] }) : in0(), inX({ hold: { block: true } })]);
  }
  assert.ok(foe.hp <= FIGHTER.startHP - MOVES.sweep.damage / 2,
    "the sweep goes through a locked standing guard");

  const w2 = createWorld();
  closeFighters(w2, 62); w2.fighters[0].facing = 1;
  const foe2 = w2.fighters[1];
  foe2.blockstun = 20; foe2.state = "block";
  for (let i = 0; i < 18 && !w2.over; i++) {
    stepWorld(w2, [i === 0 ? in0({ press: ["sweep"] }) : in0(), inX({ hold: { block: true, down: true } })]);
  }
  const lost = FIGHTER.startHP - foe2.hp;
  assert.ok(lost > 0 && lost < MOVES.sweep.damage / 2, "while a locked crouch guard still eats it");
});

test("a blocked jab opens its cancel window through hitstop, so the low can follow", () => {
  // Hitstop freezes the action counters, and the cancel window used to be computed
  // after that freeze — which shut the window for the dozen frames a player is
  // actually mashing in. The blocked jab -> sweep link is the high/low mixup, so a
  // closed window meant the low half of it never happened in a match.
  const w = createWorld();
  closeFighters(w, 56);
  const me = w.fighters[0], foe = w.fighters[1];
  me.facing = 1;
  for (let i = 0; i < 45 && !w.over; i++) {
    const press = i === 0 ? ["jab"]
      : (me.action && me.action.move === "jab" && me.action.cancelOpen) ? ["sweep"] : [];
    stepWorld(w, [in0({ press }), inX({ hold: { block: true } })]);
  }
  assert.ok(w.events.some((e) => e.kind === "attack_start" && e.move === "sweep"),
    "the sweep came out of the blocked jab");
  const chipOfJab = Math.max(1, Math.round(MOVES.jab.damage * CHIP.strikeRatio));
  assert.ok(foe.hp <= FIGHTER.startHP - chipOfJab - MOVES.sweep.damage,
    "and it went through the standing guard it was aimed at");
});

test("a blocked strike's window is close enough to catch a grab", () => {
  // The tick throw is the price of holding guard and the third side of the stance
  // triangle. It needed three things this engine did not have: the cancel window open
  // through the hitstop freeze, a grab reach longer than the ~30px of blockback a
  // guarded strike buys, and a step-in — because a block sets hitstop and blockstun to
  // the same ~12 frames, so the guard's lock is spent *inside* the freeze and the
  // deferred slide lands while the grab's own box is coming out.
  const w = createWorld();
  closeFighters(w, 90);
  const me = w.fighters[0], foe = w.fighters[1];
  me.facing = 1;
  for (let i = 0; i < 60 && !w.over; i++) {
    const press = i === 0 ? ["jab"]
      : (me.action && me.action.move === "jab" && me.action.cancelOpen) ? ["throw"] : [];
    stepWorld(w, [in0({ press }), inX({ hold: { block: true } })]);
  }
  assert.ok(w.events.some((e) => e.kind === "throw"),
    "the grab came out of the blocked jab and caught them standing");
  assert.ok(foe.hp <= FIGHTER.startHP - MOVES.throw.damage, "and a catch costs full throw damage");
});

test("a shot that flies past without touching anybody is announced", () => {
  const w = createWorld();
  w.projectiles.push({
    owner: 0, move: MOVES.fireball, x: ARENA.width - 10, y: 70,
    vx: 7.5, w: 30, h: 26, life: 100, consumed: false,
  });
  for (let i = 0; i < 20; i++) stepWorld(w, [in0(), inX()]);
  const ev = w.events.find((e) => e.kind === "shot_evaded");
  assert.ok(ev, "the engine reports an unanswered fireball, the way it reports a whiffed punch");
  assert.equal(ev.by, 0);
  assert.equal(ev.recovery, MOVES.fireball.recovery);
});
