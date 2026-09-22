// Policy: the bridge from JEV's raw judgments to engine inputs.
//
// Best practice honoured here — "keep policy explicit and raw judgments
// reusable"; "use probabilities/confidence to guide behaviour with thresholds
// evaluated on the user's data". compilePlan() stores the *judgments*; execute()
// contains all the *policy* (how a judgment turns into a button, what to do with
// low confidence, the coded reflexes). Changing a threshold never needs a new
// model call, and the same judgments could drive a different control scheme.
//
// The design goal this file serves: EXCITING, reliable offense. Once a strike
// connects, the fighter commits the whole route (jab -> strong -> launcher ->
// jump -> airkick) instead of bailing on a single imperfect reach check, and the
// guard reflex is demoted so it can never interrupt our own live combo. JEV
// supplies the *read* (is now the time to commit?); code supplies the *execution*
// of the skill string, which is what makes the combo ceiling actually reachable.

import { MOVES } from "../engine/moves.js";
import { FIGHTER, METER } from "../engine/constants.js";
import { attackBox, hurtbox, overlap } from "../engine/engine.js";

export const DEFAULT_THRESHOLDS = {
  threatBlock: 0.62,   // p(threat) that forces an immediate guard (raised: fewer false turtles)
  punishGo: 0.45,      // p(safe punish) that turns a poke into the full launcher route
  minIntentConf: 0.3,  // below this, downgrade risky intents
  maxAggression: 1.3,  // score (0..2) that unlocks the full launcher->air route
  midAggression: 0.4,  // score that unlocks the jab->strong link
  throwConf: 0.35,     // p(throw is right) needed to commit to a 19-frame grab
  superConf: 0.4,      // a shaky super read spends the whole bar, so it needs a real yes
};

function num(v, d = 0) { return typeof v === "number" && isFinite(v) ? v : d; }

export function compilePlan(answers, opts = {}) {
  const th = { ...DEFAULT_THRESHOLDS, ...(opts.thresholds || {}) };
  const a = answers || {};
  const intent = a.intent?.choice || "reset";
  let strategy = intent;
  const conf = num(a.intent?.confidence, 0.5);

  // Low-confidence risky calls degrade to safer, still-useful strategies.
  if (conf < th.minIntentConf) {
    if (strategy === "heavy") strategy = "poke";
    else if (strategy === "anti_air" || strategy === "space_control") strategy = "block";
    // NOTE: "combo" is NOT downgraded — a committed string is worth running even
    // on a shaky read, because the sequencer only continues while links actually
    // connect. Whiffing one extra jab is cheap; dropping a punish is the miss.
  }
  // The two meter/guard reads carry their own higher bar: a whiffed throw is a
  // free punish for the foe, and a whiffed super spends the entire bar.
  if (strategy === "throw" && conf < th.throwConf) strategy = "poke";
  if (strategy === "super" && conf < th.superConf) strategy = "combo";
  // A hard threat read overrides strategy toward defence even at moderate conf.
  const threat = num(a.threat_now?.noul, 0);
  const punish = num(a.punish_window?.noul, 0);
  const counter = num(a.counter_hit?.noul, 0);
  const aggression = num(a.aggression?.score, 1);

  if (threat >= th.threatBlock && (strategy === "reset" || strategy === "space_control")) strategy = "block";

  return {
    strategy, rawIntent: intent, conf, threat, punish, counter, aggression,
    // Which guard to hold is a bet made on the model's cadence, not a per-frame
    // lookup of the incoming move: read straight from the attack and no high/low
    // mixup could ever beat you.
    guardStance: a.guard_stance?.choice === "crouch" ? "crouch" : "stand",
    thresholds: th, tick: a.__tick ?? 0,
  };
}

const inReach = (me, foe, move) => {
  const m = MOVES[move];
  if (!m || !m.hitbox) return false;
  const cx = me.x + me.facing * m.hitbox.x;
  return Math.abs(cx - foe.x) <= (m.hitbox.w / 2 + FIGHTER.halfWidth);
};

// Horizontal + vertical closeness for the airborne juggle extension.
function airReach(me, foe) {
  const m = MOVES.airkick.hitbox;
  const cx = me.x + me.facing * m.x;
  const horiz = Math.abs(cx - foe.x) <= (m.w / 2 + FIGHTER.halfWidth);
  const vert = foe.y <= me.y + 70 && foe.y + FIGHTER.bodyHeight >= me.y - 30;
  return horiz && vert;
}

function moveToward(me, foe) { return foe.x >= me.x ? "right" : "left"; }
function moveAway(me, foe) { return foe.x >= me.x ? "left" : "right"; }

// Their live threat, measured with the engine's own boxes. inReach() answers "can
// my fist touch them" from a horizontal centre-to-centre distance only: it ignores
// height, ignores crouching, and reports a jump-in overhead as a threat to a
// standing body it is flying over. Defence is a frame-accurate decision, so it
// asks the same question the collision solver asks instead.
function liveThreat(me, foe) {
  const a = foe.action;
  if (!a) return null;
  if (a.phase !== "startup" && a.phase !== "active") return null;
  if (!overlap(attackBox(foe), hurtbox(me))) return null;
  return {
    move: a.move, def: a.moveDef, phase: a.phase,
    startupLeft: Math.max(0, (a.moveDef.startup || 0) - a.frame),
  };
}

// A shot already in flight, read a reaction window ahead. Blocking is a hold, so
// the guard can be engaged early; 12 frames (~200ms) is roughly the shortest
// human-plus-reflex warning that still lets us answer a fireball at all.
const SHOT_LEAD = 12;
// Frames a jump needs to rise past the shot's box: the fireball sits at y 70 with
// height 26, so the feet must clear ~83px, which jumpVelocity/gravity reaches on
// frame 7. Anything with less warning than that has to be blocked, not hopped.
const SHOT_RISE = 8;
function incomingShot(world, me, foe) {
  for (const p of world.projectiles || []) {
    if (p.consumed || p.owner !== foe.id) continue;
    const closing = (me.x - p.x) * Math.sign(p.vx || 1);
    if (closing <= 0) continue; // it is behind us, or travelling away
    const box = (n) => ({
      left: p.x + p.vx * n - p.w / 2, right: p.x + p.vx * n + p.w / 2,
      bottom: p.y - p.h / 2, top: p.y + p.h / 2,
    });
    if (!overlap(box(0), hurtbox(me)) && !overlap(box(SHOT_LEAD), hurtbox(me))) continue;
    return {
      def: p.move,
      frames: Math.max(0, Math.round((closing - (p.w / 2 + FIGHTER.halfWidth)) / Math.abs(p.vx))),
    };
  }
  return null;
}

// The state a throw exists to punish: they are grounded, guarding something, and
// not already stunned (a grab is not combo filler, and the engine says so).
function foeTurtling(foe) {
  if (!foe.onGround || foe.action || foe.hitstun > 0) return false;
  if (foe.state === "knockdown" || foe.state === "ko") return false;
  return foe.blockstun > 0 || !!(foe.lastInput && foe.lastInput.hold && foe.lastInput.hold.block);
}
// Invulnerable frames (wake-up, just-burst) make a grab a pure whiff, and a
// 19-frame whiff is a free punish — so reach only for a body that can be caught.
//
// And "can be caught" is stricter than it looks. Every brain here has the same
// reflex, because it is the third side of the triangle: see a committed grab, leave
// the ground. A probe over three matches found 16 grabs started while *we* were free,
// at a foe who was crouching and grounded at the frame of the press, and all 16
// caught air — the foe was airborne at 20px by the time the box went active. A grab
// aimed at a free opponent is therefore not a guess with a chance in it, it is a
// 19-frame whiff handed over. The one grab that cannot be jumped is the one pressed
// into a guard that is locked in blockstun, so `blockstun > 0` is the requirement
// rather than a preference.
const grabLocked = (foe) => foeTurtling(foe) && foe.blockstun > 0;
const throwReady = (me, foe) =>
  me.blockstun === 0 && foe.invuln === 0 && grabLocked(foe) && inReach(me, foe, "throw");

// The stance a held guard is actually covering. During blockstun the engine ignores
// new movement input, so whatever direction is still held is the bet on record for
// the rest of the string — which is exactly why the mixup is a bet and not a reaction.
function guardIsCrouching(foe) {
  const h = (foe.lastInput && foe.lastInput.hold) || {};
  return !!h.down || foe.state === "crouch";
}

// Every guard has exactly one wrong answer, and code knows which guard is being
// held. A cautious plan declines the grab on purpose: 16 frames of empty recovery is
// the most expensive whiff we own, so `allowGrab` has to be earned by the plan.
function guardCrack(me, foe, allowGrab = true) {
  if (foe.invuln > 0 || !foeTurtling(foe)) return null;
  const grabbable = allowGrab && grabLocked(foe) && inReach(me, foe, "throw");
  if (guardIsCrouching(foe)) {
    // A crouch covers every ground strike, and a *locked* crouch is the one stance a
    // grab cannot be answered by. Free-standing, the crouch is exactly the foe who can
    // simply hop it, so the answer at that stance becomes the other one: get above them.
    if (grabbable) return "throw";
    return me.onGround && Math.abs(foe.x - me.x) < 130 ? "jump" : null;
  }
  // A standing guard is transparent to the low, and a sweep costs nothing against it,
  // so it outranks the grab: the risk-free answer is the one to take when both work.
  if (inReach(me, foe, "sweep")) return "sweep";
  return grabbable ? "throw" : null;
}

// The full route for this much commitment. Index == current combo.hits, so
// route[0] is the opener and route[hits] is the next link to press.
function comboRoute(agg, punish, th) {
  const bold = agg >= th.maxAggression || punish >= th.punishGo;
  if (bold) return ["jab", "strong", "launcher", "jump"];
  if (agg >= th.midAggression) return ["jab", "strong"];
  return ["jab"];
}

// The committed sequencer. Given a live combo, return the single next press that
// continues it (or null). It only acts inside a real cancel window, so the engine
// remains the authority on what links — code never forces an illegal cancel.
function committedNext(me, foe, route) {
  if (!me.onGround) {
    // Airborne leg: we jumped to chase a launched foe — strike while falling.
    if (foe.juggling && !me.airAttackUsed && !me.action) return "airkick";
    return null;
  }
  if (!me.action || !me.action.cancelOpen) return null; // window not open yet
  const next = route[me.combo.hits];
  if (!next) return superEnder(me, foe); // nothing left to link: cash the bar in
  if (!(me.action.moveDef.cancelInto || []).includes(next)) return superEnder(me, foe);
  if (next === "jump") return "jump";
  if (inReach(me, foe, next)) return next;
  // Link out of range this frame: end with the super rather than drop the read.
  return superEnder(me, foe);
}

// Super-cancel: once a route has nothing further to link, a whole bar is the
// ender. Spending it on a *confirmed* hit is the point — a super thrown from raw
// neutral gets blocked for a slice of chip, and a whiffed one is a free punish.
function superEnder(me, foe) {
  if (!me.action || me.meter < METER.superCost) return null;
  if (!(me.action.moveDef.cancelInto || []).includes("super")) return null;
  return inReach(me, foe, "super") ? "super" : null;
}

// How many frames of their recovery we need left to land a punish: our move's
// startup, plus the couple of frames the engine takes to advance the action.
// Ordered by damage so the biggest free hit is the one we take.
const PUNISH_ORDER = ["launcher", "strong", "jab"];

function whiffWindow(foe) {
  const a = foe.action;
  if (!a || a.phase !== "recovery" || a.hitConsumed) return 0;
  return Math.max(0, (a.moveDef?.recovery || 0) - a.frame);
}

function hardPunish(me, foe, window) {
  for (const mv of PUNISH_ORDER) {
    if (window >= MOVES[mv].startup + 2 && inReach(me, foe, mv)) return mv;
  }
  return null;
}

// Frame-by-frame execution of the plan against the LIVE world. This is what
// makes the fighter feel responsive at 60fps despite a ~1.2s model cadence.
export function executePlan(plan, world, meId) {
  const me = world.fighters[meId];
  const foe = world.fighters[1 - meId];
  const th = plan.thresholds || DEFAULT_THRESHOLDS;
  const hold = {};
  const press = [];
  if (me.state === "ko" || foe.state === "ko") return { hold, press };

  const route = comboRoute(plan.aggression, plan.punish, th);

  // ---- 1. committed combo sequencer: overrides everything while a string lives
  if (me.combo.hits > 0 || (!me.onGround && foe.juggling)) {
    const next = committedNext(me, foe, route);
    if (next) press.push(next);
    // Keep walking forward only if grounded, free, and the foe has left range.
    else if (me.onGround && !me.action && !inReach(me, foe, route[0])) hold[moveToward(me, foe)] = true;
    return { hold, press };
  }

  // ---- 1b. burst: the meter-bought escape. Deliberately a coded reflex rather
  // than a strategy branch, because the decision has to land on the frame we are
  // still stunned — but it is spent only on real combos, never on a single poke.
  if (me.onGround && me.hitstun > 0 && me.meter >= METER.burstCost) {
    const comboed = foe.combo.hits >= 2 || foe.juggling;
    if (plan.strategy === "burst" || comboed) press.push("burst");
    else hold[moveAway(me, foe)] = true; // ride out the stun with the stick back
    return { hold, press };
  }

  // ---- 1c. blockstun is a lockout, not a free frame: the engine will not let us
  // start anything until it expires, and the guard's height is read from the
  // direction still held. Dropping the stick the moment the first hit is blocked
  // would hand the rest of the string away for nothing, so the stance chosen on
  // the block is held for the whole window — and that committed stance is what the
  // foe's sweep or overhead is aimed at.
  if (me.onGround && me.blockstun > 0) {
    hold.block = true;
    if (plan.guardStance === "crouch") hold.down = true;
    return { hold, press };
  }

  // ---- 2. hard reflex guard — but ONLY when we are free and have no live
  // offense, so it can never cut a combo or a committed punish short.
  const free = me.onGround && me.hitstun === 0 && !me.action;
  const threat = liveThreat(me, foe);
  const shot = incomingShot(world, me, foe);
  const incoming = threat || shot;

  // ---- 2a. the whiff punish: the edge that makes attacking beat throwing. A
  // missed grab leaves 16 frames of nothing and a missed sweep 22; unless those
  // frames cost damage, a whiff is a free reposition and throws are always safe.
  const window = whiffWindow(foe);
  if (free && window && !shot) {
    const mv = hardPunish(me, foe, window);
    if (mv) press.push(mv);
    else if (window >= 10) hold[moveToward(me, foe)] = true; // close in while they are locked out
    if (press.length || Object.keys(hold).length) return { hold, press };
  }

  if (free && (incoming || plan.threat >= th.threatBlock)) {
    if (threat && threat.def.type === "grab") {
      // A grab is unblockable, so the guard is the one reply that loses to it — and
      // its 3 frames of startup beat any strike we own. Jumping is what a grab
      // whiffs against, and the 16 recovery frames it leaves are the prize.
      if (threat.startupLeft > 0) press.push("jump");
      else hold[moveAway(me, foe)] = true;
      return { hold, press };
    }
    if (shot && !threat) {
      // A block only postpones a shot; the hop wins the exchange — the rise clears
      // the box and the forward arc lands us on the shooter's 22 recovery frames.
      // That is only true while they are still locked inside the fireball
      // animation: hopping at a foe who is already free hands them an anti-air,
      // which is exactly how a zoner is supposed to beat a jumper.
      const lockedIn = !!foe.action && foe.action.moveDef.type === "projectile";
      if (lockedIn && plan.aggression >= 1.0 && shot.frames >= SHOT_RISE) {
        press.push("jump");
        hold[moveToward(me, foe)] = true;
        return { hold, press };
      }
      hold.block = true;
      if (plan.guardStance === "crouch") hold.down = true;
      return { hold, press };
    }
    // Beating them to the frame is only safe while their attack still has more
    // startup than our jab needs to arrive: a poke into a hitbox about to go live
    // is a trade we lose, and losing it pays them a counter-hit.
    const startupLeft = threat ? threat.startupLeft : 0;
    const beatsTheirStartup = startupLeft > MOVES.jab.startup + 2;
    const canPreempt = beatsTheirStartup && (plan.punish >= th.punishGo || plan.counter >= 0.6)
      && (inReach(me, foe, "strong") || inReach(me, foe, "jab"));
    if (!canPreempt) {
      // Guarding a turtling foe achieves nothing: their guard already answers
      // whatever we could poke with. Crack the stance instead.
      const crack = guardCrack(me, foe, plan.aggression >= th.midAggression);
      if (crack && plan.aggression >= th.midAggression) press.push(crack);
      else {
        hold.block = true;
        if (plan.guardStance === "crouch") hold.down = true;
      }
      return { hold, press };
    }
  }

  // ---- 2b. the jump-in falls: `airkick` is the one attack flagged as an
  // overhead, so a hop over a turtle — or over a fireball — has to convert rather
  // than land short of the body it jumped for. It is pressed on the way *down*
  // (with 5 startup frames and ~9px of fall per frame, swinging at the apex leaves
  // the box gone before the feet get near them) and only against a foe who cannot
  // spend those frames hitting us: stunned, recovering, or already holding guard,
  // which is the stance the overhead exists to break. Dropping an airkick on a
  // free opponent is the one jump-in the engine punishes, and the ledger counted
  // 17 of them before this line existed.
  const falling = me.vy < 0 && me.y > 0 && me.y < FIGHTER.bodyHeight;
  const cantAnswer = foe.hitstun > 0 || foe.juggling || foe.blockstun > 0
    || (foe.action && foe.action.phase === "recovery") || foeTurtling(foe);
  if (!me.onGround && !me.action && !me.airAttackUsed && falling && cantAnswer && airReach(me, foe)) {
    press.push("airkick");
    return { hold, press };
  }

  // ---- 2c. the follow-up out of a blocked strike — the cancel window it opens
  // while the defender is still locked in blockstun. That window is a few frames
  // wide, far shorter than the model cadence, so the window drives the press and JEV
  // supplies only how much risk it will take. Inside it, grabbing a foe who is frozen
  // mid-block is not a gamble: they can neither block a grab nor walk out of one, so
  // the whiff risk the plan normally pays for is zero.
  const crack = me.action && me.action.cancelOpen && plan.aggression >= th.midAggression
    ? guardCrack(me, foe, plan.strategy === "throw" || foe.blockstun > 0) : null;
  // Only a link the move graph actually lists can come out of the window, which is
  // the engine's rule and the policy's honesty check in one: pressing a hop off a
  // blocked jab looks right on paper and is a wasted frame in play.
  if (crack && (me.action.moveDef.cancelInto || []).includes(crack)) {
    press.push(crack);
    return { hold, press };
  }

  // ---- 3. strategy execution (opening a string / neutral game)
  switch (plan.strategy) {
    case "combo": {
      const opener = "jab";
      // A turtling foe turns our opener into the one thing their guard cannot
      // answer: the low, the overhead, or the grab.
      const crack = guardCrack(me, foe, plan.aggression >= th.midAggression);
      if (crack) press.push(crack);
      else if (inReach(me, foe, opener)) press.push(opener);
      else hold[moveToward(me, foe)] = true;
      break;
    }
    case "poke": {
      const crack = guardCrack(me, foe, plan.aggression >= th.midAggression);
      if (crack) press.push(crack);
      else if (inReach(me, foe, "jab")) press.push("jab");
      else if (inReach(me, foe, "strong") && plan.aggression >= th.midAggression) press.push("strong");
      else hold[moveToward(me, foe)] = true;
      break;
    }
    case "heavy": {
      // A big poke at a fighter who is already guarding is a blocked poke: the
      // committed stance is the cheaper way to spend the same frames.
      const crack = guardCrack(me, foe, false);
      if (crack === "sweep") press.push("sweep");
      else if (inReach(me, foe, "strong")) press.push("strong");
      else if (!inReach(me, foe, "strong") && Math.abs(foe.x - me.x) > 150) press.push("fireball");
      else hold[moveToward(me, foe)] = true;
      break;
    }
    case "throw": {
      // The grab itself only ever comes out of a locked guard — see `grabLocked` — so
      // what this strategy actually buys is the lock: touch them with the cheapest
      // strike, and let the cancel-window branch spend the blockstun on the grab.
      if (throwReady(me, foe)) press.push("throw");
      else if (inReach(me, foe, "jab") && !me.action) press.push("jab");
      else hold[moveToward(me, foe)] = true;
      break;
    }
    case "super": {
      if (me.meter >= METER.superCost && inReach(me, foe, "super") && !me.action) press.push("super");
      else if (me.meter >= METER.superCost) hold[moveToward(me, foe)] = true;
      else if (inReach(me, foe, "jab")) press.push("jab"); // bar is gone: keep poking
      else hold[moveToward(me, foe)] = true;
      break;
    }
    case "burst": {
      // Reached only when we are NOT stunned (the reflex above handles the real
      // case), so this is the "I asked to escape and already did" fallback.
      if (me.hitstun > 0 && me.meter >= METER.burstCost) press.push("burst");
      else hold[moveAway(me, foe)] = true;
      break;
    }
    case "block": {
      hold.block = true;
      if (plan.guardStance === "crouch") hold.down = true;
      break;
    }
    case "evade": {
      hold[moveAway(me, foe)] = true;
      break;
    }
    case "anti_air": {
      if (!foe.onGround) {
        if (!me.onGround && !me.airAttackUsed && airReach(me, foe)) press.push("airkick");
        else if (inReach(me, foe, "launcher")) press.push("launcher");
        else if (inReach(me, foe, "strong")) press.push("strong");
        else hold.block = true;
      } else hold[moveAway(me, foe)] = true;
      break;
    }
    case "space_control": {
      const far = Math.abs(foe.x - me.x) > 150;
      if (far) press.push("fireball");
      else if (inReach(me, foe, "jab")) press.push("jab");
      else hold[moveAway(me, foe)] = true;
      break;
    }
    case "reset":
    default: {
      // neutral footsies: sit at the edge of jab range, poke on a good counter read.
      const d = Math.abs(foe.x - me.x);
      const jabReach = MOVES.jab.hitbox.x + FIGHTER.halfWidth * 2;
      if (d > jabReach + 24) hold[moveToward(me, foe)] = true;
      else if (d < jabReach - 16) hold[moveAway(me, foe)] = true;
      else if (plan.counter >= th.punishGo && inReach(me, foe, "jab")) press.push("jab");
      break;
    }
  }
  return { hold, press };
}
