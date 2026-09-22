// The deterministic fight engine: a fixed-timestep simulation with a per-fighter
// action state machine, AABB hitbox/hurtbox collision, blocking stances, juggle
// and knockdown resolution, projectiles, combo damage scaling and a per-tick
// event stream.
//
// Design contract (TypeSafe best practice: code owns rules & execution, the
// model owns judgment). Every millisecond-level decision — frame data, hit
// detection, cancel windows, scaling — lives HERE in code. JEV only ever writes
// the `input` object for a fighter; it never touches physics. That is what lets
// a ~1.2s model round-trip still produce near-real-time *reaction*: the brain
// supplies a persistent intent, the engine executes and reflexes between calls.

import { ARENA, FIGHTER, DAMAGE_SCALE, MAX_JUGGLE, METER, CHIP, BLOCK_PUSH } from "./constants.js";
import { MOVES } from "./moves.js";

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

export function makeFighter(id, name, x, facing) {
  return {
    id, name,
    x, y: 0, vx: 0, vy: 0, facing,
    hp: FIGHTER.startHP, meter: 0,
    state: "neutral", // neutral|walk|crouch|block|attack|hitstun|blockstun|airborne|knockdown|ko
    onGround: true,
    action: null, // { move, moveDef, frame, phase, hitConsumed, cancelOpen }
    hitstun: 0, blockstun: 0, invuln: 0,
    hitstop: 0,
    dashTimer: 0, dashCooldown: 0, dashDir: 1,
    airAttackUsed: false,
    juggle: 0, juggling: false, // victim-side juggle bookkeeping
    knockdownTimer: 0,
    combo: { hits: 0, damage: 0, juggle: 0 }, // attacker-side running combo
    bestCombo: { hits: 0, damage: 0 }, // finalized record for stats
    totalDamageDealt: 0,
    burstUsed: false, // already spent the one burst allowed per hitstun episode?
    lastInput: { hold: {}, press: [] },
  };
}

export function createWorld(opts = {}) {
  const p1 = makeFighter(0, opts.p1Name || "Azure", ARENA.width * 0.32, 1);
  const p2 = makeFighter(1, opts.p2Name || "Crimson", ARENA.width * 0.68, -1);
  return {
    tick: 0,
    fighters: [p1, p2],
    projectiles: [],
    events: [], // per-tick events for the brain's interrupt triggers
    comboLog: [], // finalized combos {owner,hits,damage}
    over: false, winner: null,
    maxTicks: opts.maxTicks || 60 * 240, // 4 min hard cap
  };
}

function foeOf(world, f) { return world.fighters[1 - f.id]; }

function heightOf(f) {
  return f.state === "crouch" || (f.lastInput.hold.down && f.onGround && !f.action)
    ? FIGHTER.crouchHeight : FIGHTER.bodyHeight;
}

export function hurtbox(f) {
  const half = FIGHTER.halfWidth;
  const h = heightOf(f);
  return { left: f.x - half, right: f.x + half, bottom: f.y, top: f.y + h };
}

// Exported so the decision layer reads threats through exactly the geometry the
// simulation resolves with, rather than a second hand-written reach maths that can
// drift out of sync and make the guard reflex time itself against a lie.
export function attackBox(f) {
  if (!f.action) return null;
  const m = f.action.moveDef;
  if (!m.hitbox) return null;
  const cx = f.x + f.facing * m.hitbox.x;
  const cy = f.y + m.hitbox.y;
  return {
    left: cx - m.hitbox.w / 2, right: cx + m.hitbox.w / 2,
    bottom: cy - m.hitbox.h / 2, top: cy + m.hitbox.h / 2,
  };
}

const overlap = (a, b) => a && b && a.left < b.right && a.right > b.left && a.bottom < b.top && a.top > b.bottom;
export { overlap };

function pushEvent(world, ev) { world.events.push({ tick: world.tick, ...ev }); }

// --- action state machine ---------------------------------------------------

function actionableForNewMove(f) {
  if (f.hitstop > 0) return false;
  if (f.hitstun > 0 || f.blockstun > 0) return false;
  if (f.state === "ko" || f.state === "knockdown") return false;
  return true;
}

function canStartMove(world, f, moveName) {
  const m = MOVES[moveName];
  if (!m) return false;
  if (m.meterCost && f.meter < m.meterCost) return false; // cannot pay for it
  const foe = foeOf(world, f);

  if (m.type === "movement" && moveName === "jump") {
    if (!f.onGround || !actionableForNewMove(f)) return false;
    if (!f.action) return true;
    // Cancel a move's recovery into a jump (launcher -> jump -> air juggle), but
    // only inside an open cancel window whose move lists jump as a link.
    return f.action.cancelOpen && (f.action.moveDef.cancelInto || []).includes("jump");
  }
  if (m.type === "movement" && moveName === "dash") {
    return f.onGround && actionableForNewMove(f) && f.dashCooldown <= 0 && !f.action;
  }
  if (m.air) {
    return !f.onGround && !f.airAttackUsed && f.hitstun === 0 && !f.action;
  }
  // grounded strike
  if (!f.onGround) return false;
  if (f.hitstun > 0 || f.blockstun > 0 || f.state === "knockdown" || f.state === "ko") return false;

  // A grab is a neutral-reset tool, not combo filler: it cannot be stuffed onto a
  // foe who is already stunned, nor used on one already on the floor.
  if (m.unblockable && (foe.hitstun > 0 || foe.state === "knockdown" || foe.state === "ko")) return false;

  if (f.action) {
    // cancel: must be inside the current move's cancel window
    const cur = f.action;
    const links = cur.moveDef.cancelInto || [];
    const canHere = cur.cancelOpen && links.includes(moveName);
    return canHere;
  }
  return actionableForNewMove(f);
}

function startMove(world, f, moveName) {
  const m = MOVES[moveName];
  if (m.meterCost) f.meter -= m.meterCost; // canStartMove already proved it is affordable
  if (moveName === "jump") {
    f.vy = FIGHTER.jumpVelocity; f.onGround = false; f.airAttackUsed = false;
    f.state = "airborne"; f.action = null;
    // The direction held at take-off decides the arc. Without it a jump is a
    // vertical hop, so "jump the fireball" and "jump in on the turtle" would both
    // dodge beautifully and land exactly where they started.
    const h = (f.lastInput && f.lastInput.hold) || {};
    f.vx = (h.left ? -1 : h.right ? 1 : 0) * FIGHTER.airSpeed;
    pushEvent(world, { kind: "jump", by: f.id });
    return;
  }
  if (moveName === "dash") {
    f.dashTimer = FIGHTER.dashFrames; f.dashCooldown = FIGHTER.dashCooldown;
    f.dashDir = f.facing;
    pushEvent(world, { kind: "dash", by: f.id });
    return;
  }
  if (!m.hitbox && m.type !== "projectile") return; // block/crouch handled elsewhere
  f.action = { move: moveName, moveDef: m, frame: 0, phase: "startup", hitConsumed: false, cancelOpen: false };
  f.state = "attack";
  pushEvent(world, { kind: "attack_start", by: f.id, move: moveName });
}

function advanceAction(world, f) {
  const a = f.action;
  if (!a) return;
  const m = a.moveDef;
  // Cancel availability is a fact about the strike having connected, not about the
  // frame counter having advanced. Hitstop freezes both fighters for a dozen frames,
  // and computing this after the early return below left the window *shut* for the
  // whole freeze — which is precisely the window a player is mashing through. It made
  // the blocked-jab-into-low link unreachable in play, and the ledger showed not one
  // sweep attempted across eight matches.
  a.cancelOpen = a.hitConsumed && (m.cancelOn || []).length > 0;
  if (f.hitstop > 0) return; // action timing freezes with the impact
  a.frame++;
  if (a.phase === "startup" && a.frame > m.startup) { a.phase = "active"; a.frame = 1; }
  else if (a.phase === "active") {
    if (a.frame > m.active) {
      // The frame the box goes away without having touched anybody is the whiff,
      // and it is the frame the punishment window opens. Emitted rather than
      // re-derived so the decision layer sees a fact instead of frame data.
      if (!a.hitConsumed && m.hitbox) {
        pushEvent(world, { kind: "whiff", by: f.id, move: a.move, grab: m.type === "grab", recovery: m.recovery });
      }
      a.phase = "recovery"; a.frame = 1;
    }
  }
  else if (a.phase === "recovery" && a.frame > m.recovery) {
    f.action = null; f.state = f.onGround ? "neutral" : "airborne";
  }
  // A command grab walks itself into the body it is chasing, for its startup frames.
  // This is not flavour: a blocked strike freezes both fighters for ~12 frames and
  // defers the whole blockback to the frame the freeze releases, so the defender
  // leaves the guard with ~5px/frame of separation still unbuilt. A grab that stands
  // still therefore pressed against a body at 80px and measured its own whiff at 120 —
  // six attempts, zero catches, in one probe. Closes 15px over 3 startup frames, which
  // is the gap the slide costs; the reach of the box stays the honest number.
  if (m.lunge && a.phase === "startup") f.vx = f.facing * m.lunge;
  else if (m.lunge && a.phase === "active" && a.frame === 1) f.vx = 0;
  // Cancel window stays open from the moment the move connects until it whiffs
  // out of recovery, so linked combos are timed generously. Recomputed here so a
  // hit that landed this frame opens it without waiting for the next tick.
  a.cancelOpen = a.hitConsumed && (m.cancelOn || []).length > 0;
  // Projectile spawn at the end of startup.
  if (m.type === "projectile" && a.phase === "active" && a.frame === 1) {
    const p = m.projectile;
    world.projectiles.push({
      owner: f.id, move: m, x: f.x + f.facing * 40, y: f.y + p.y,
      vx: f.facing * p.speed, w: p.w, h: p.h, life: p.life, consumed: false,
    });
    pushEvent(world, { kind: "projectile", by: f.id });
  }
}

// --- input application ------------------------------------------------------

// Burst: a meter-bought escape from hitstun. It pays for itself by resetting
// spacing and granting wake-up invulnerability, but it kills the defender's own
// offence and it only works on the ground, so air extensions still resolve.
// Returns the foe for a successful burst, null when the request is refused.
function tryBurst(world, f) {
  if (!f.onGround || f.y > 0 || f.hitstun <= 0) return null;
  if (f.state === "ko" || f.state === "knockdown") return null;
  if (f.meter < METER.burstCost || f.burstUsed) return null;
  const atk = foeOf(world, f);
  f.meter -= METER.burstCost;
  f.hitstun = 0;
  f.invuln = METER.burstInvuln;
  f.vx = 0;
  f.state = "neutral";
  f.burstUsed = true;
  f.action = null;
  // A burst-out fighter is no longer "in the combo", so a knockdown queued by
  // the last hit is called off too.
  f.knockdownQueued = false;
  if (atk.combo.hits > 1) { atk.combo.hits = 0; atk.combo.damage = 0; }
  const push = METER.burstPush;
  for (const [d, dir] of [[f, 1], [atk, -1]]) {
    d.x = clamp(d.x + d.facing * push * dir, ARENA.wallPad, ARENA.width - ARENA.wallPad);
    d.vx = 0;
  }
  pushEvent(world, { kind: "burst", by: f.id, on: atk.id, cost: METER.burstCost });
  return atk;
}

export function applyInput(world, fighterId, input) {
  const f = world.fighters[fighterId];
  if (!f || f.state === "ko") { if (f) f.lastInput = input; return; }
  const foe = foeOf(world, f);
  f.lastInput = input;
  const hold = input.hold || {};
  const press = input.press || [];

  // Auto-face the opponent whenever neutral-ish and grounded.
  if (f.onGround && !f.action && f.hitstun === 0 && f.blockstun === 0) {
    f.facing = foe.x >= f.x ? 1 : -1;
  }

  // Burst is the one thing you may do *out of hitstun*, so it is handled before
  // the free/disabled dispatch below rather than as an ordinary move press.
  if (press.includes("burst")) {
    const atk = tryBurst(world, f);
    if (atk) {
      atk.hitstop = 0; // otherwise the freeze drags on and the escape telegraphs
      atk.action = null; // stop an active hitbox from re-grabbing on the next tick
      // The escape already uses this tick's input; keep only the defensive and
      // movement intent, and re-arm an attack press for the frame after it.
      const held = hold.block ? ["block"] : hold.down ? ["down"] : [];
      f.lastInput = {
        hold: { ...hold, burst: true, block: false, down: false },
        press: [...held, ...press.filter((p) => p !== "burst")],
      };
    }
  }

  // Movement / stance (only meaningful when grounded and free).
  const free = f.onGround && !f.action && f.hitstun === 0 && f.blockstun === 0 && f.state !== "knockdown";
  if (free) {
    // Attacks first: presses take precedence over movement.
    let acted = false;
    for (const mv of press) {
      if (canStartMove(world, f, mv)) { startMove(world, f, mv); acted = true; break; }
    }
    if (!acted) {
      if (hold.block) { f.state = hold.down ? "crouch" : "block"; f.vx = 0; }
      else if (hold.down) { f.state = "crouch"; f.vx = 0; }
      else {
        const dir = hold.left ? -1 : hold.right ? 1 : 0;
        if (dir !== 0) {
          // walking forward toward foe is faster than retreating
          const towardFoe = (foe.x >= f.x && dir === 1) || (foe.x < f.x && dir === -1);
          f.vx = dir * (towardFoe ? FIGHTER.walkSpeed : FIGHTER.backSpeed);
          f.state = "walk";
        } else { f.vx = 0; f.state = "neutral"; }
      }
      // allow jump/dash presses even without attack
      for (const mv of press) if (mv === "jump" || mv === "dash") { if (canStartMove(world, f, mv)) startMove(world, f, mv); }
    }
  } else {
    // Not free: this is the cancel/air case. canStartMove() is the authority for
    // grounded cancel links (f.action set, window open) and air attacks.
    if (!f.onGround) {
      for (const mv of press) if (canStartMove(world, f, mv)) { startMove(world, f, mv); break; }
    } else if (f.action) {
      for (const mv of press) if (canStartMove(world, f, mv)) { startMove(world, f, mv); break; }
    }
  }
}

// --- physics + collision ----------------------------------------------------

function stepPhysics(world, f) {
  if (f.hitstop > 0) return; // frozen by the timers loop this tick

  // dash burst overrides walk velocity
  if (f.dashTimer > 0) { f.vx = f.dashDir * FIGHTER.dashSpeed; f.dashTimer--; if (f.dashTimer === 0) f.vx = 0; }
  else if (f.onGround && (f.hitstun > 0 || f.blockstun > 0)) {
    f.vx *= 0.85; if (Math.abs(f.vx) < 0.2) f.vx = 0;
  }

  f.x += f.vx;
  if (!f.onGround || f.juggling || f.y > 0) {
    f.vy -= FIGHTER.gravity;
    f.y += f.vy;
    if (f.y <= 0) {
      f.y = 0; f.vy = 0;
      if (f.juggling) { f.juggling = false; f.airAttackUsed = false; beginKnockdown(world, f, 26); }
      else if (f.state === "airborne") { f.state = "neutral"; f.airAttackUsed = false; f.onGround = true; f.vx = 0; }
    } else {
      f.onGround = false;
      if (f.juggling) f.state = "airborne";
    }
  }
  f.x = clamp(f.x, ARENA.wallPad, ARENA.width - ARENA.wallPad);
}

function beginKnockdown(world, f, frames) {
  f.state = "knockdown"; f.knockdownTimer = frames; f.onGround = true; f.juggle = 0; f.action = null;
  pushEvent(world, { kind: "knockdown", by: f.id });
}

// Meter the attacker banks from one clean hit. A defender who has already burst
// out of this combo builds their attacker nothing: meter tracks pressure that
// actually stuck.
function meterForCleanHit(def, move) {
  return (def.burstUsed || move.meterGain === false) ? 0 : METER.gainOnHit;
}

function applyHit(world, atk, def, move, viaProjectile) {
  const blocking = !move.unblockable && isBlockingAgainst(def, move, atk);
  const comboIndex = clamp(atk.combo.hits, 0, DAMAGE_SCALE.length - 1);
  // Counter-hit: the defender's own move is still winding up, so the intercept
  // wins the exchange outright — more damage, and enough plus frames that the
  // hit confirms into the cancel window instead of into a fresh neutral.
  const counter = !blocking && !!def.action && def.action.phase === "startup";
  // Read their move now: the clean-hit path below clears `def.action`.
  const victimMove = counter ? def.action.move : null;
  const scaled = Math.round(move.damage * DAMAGE_SCALE[comboIndex] * (counter ? 1.25 : 1));
  const stop = viaProjectile ? 10 : 12;

  if (blocking) {
    // Chip: a blocked string costs health but never enough to KO, so turtling is
    // safe without being free. Both sides build a little meter defending.
    const chip = Math.max(1, Math.round(move.damage * (viaProjectile ? CHIP.projectileRatio : CHIP.strikeRatio)));
    def.blockstun = move.blockstun || 10;
    def.state = "block";
    const kb = move.knockback?.x || 3;
    def.vx = atk.facing * kb * BLOCK_PUSH.defenderRatio;
    atk.vx = -atk.facing * kb * BLOCK_PUSH.attackerRatio;
    atk.meter = clamp(atk.meter + (move.meterGain === false ? 0 : METER.gainOnBlock), 0, METER.max);
    def.meter = clamp(def.meter + METER.gainOnBlock, 0, METER.max);
    atk.hitstop = def.hitstop = stop;
    if (atk.action) atk.action.hitConsumed = true;
    const beforeChip = def.hp;
    def.hp = Math.max(1, def.hp - chip); // clamps at 1: chip alone can never KO
    pushEvent(world, { kind: "block", by: atk.id, on: def.id, move: move.name, chip: beforeChip - def.hp });
    return;
  }

  // clean hit
  // A burst sets hitstun to 0 directly, so it never passes through the timers
  // loop's "stun drained" branch — the flag is re-armed here instead, on entering
  // a *fresh* stun. Mid-combo hits leave it set, which is what keeps one burst
  // per combo.
  if (def.hitstun === 0) def.burstUsed = false;
  def.hp = clamp(def.hp - scaled, 0, FIGHTER.startHP);
  atk.totalDamageDealt += scaled;
  def.hitstun = (move.hitstun || 16) + (counter ? 4 : 0);
  def.state = "hitstun";
  def.action = null;
  def.hitstop = atk.hitstop = stop;
  atk.meter = clamp(atk.meter + meterForCleanHit(def, move), 0, METER.max);
  def.meter = clamp(def.meter + METER.gainOnHitTaken, 0, METER.max);

  // knockback + launch/juggle.
  // Mid-combo hits deliberately do NOT push the victim away — only the opener,
  // a launcher or a knockdown sends them moving. This is what makes skill links
  // connect without the attacker having to re-close distance every hit, and it
  // is the reason the combo ceiling is reachable but still finite.
  const kb = move.knockback || { x: 3, y: 0 };
  const opener = atk.combo.hits === 0;
  if (opener || move.launch || move.knockdown) def.vx = atk.facing * kb.x;
  else def.vx = 0;
  if (move.launch) {
    def.vy = kb.y; def.y += 1; def.onGround = false; def.juggling = true; def.juggle += move.juggleAdd || 1;
    def.state = "airborne";
    pushEvent(world, { kind: "launched", by: atk.id, on: def.id });
  } else if (move.knockdown) {
    // grounded knockdown begins after hitstun drains -> queue via short hitstun
    if (!def.burstUsed) def.knockdownQueued = true;
  }

  // combo bookkeeping on attacker
  atk.combo.hits += 1;
  atk.combo.damage += scaled;
  if (move.juggleAdd) atk.combo.juggle += move.juggleAdd;

  // juggle ceiling: too many air points -> hard knockdown ends the route
  if (def.juggling && def.juggle >= MAX_JUGGLE) {
    def.vy = 6; def.juggle = 0;
    pushEvent(world, { kind: "juggle_end", by: atk.id, on: def.id });
  }

  if (atk.action) atk.action.hitConsumed = true;
  // The pair is the interesting fact, not the winner alone: "our jab lost to their
  // strong" is a neutral-game read, "our airkick lost to their launcher" is a
  // jump-in the foe was ready for.
  if (counter) pushEvent(world, { kind: "counter_hit", by: atk.id, on: def.id, move: move.name, victimMove });
  pushEvent(world, { kind: "hit", by: atk.id, on: def.id, move: move.name, dmg: scaled, hits: atk.combo.hits, juggle: def.juggle, counter });

  if (def.hp <= 0) { def.state = "ko"; world.over = true; world.winner = atk.id; pushEvent(world, { kind: "ko", by: atk.id, on: def.id }); }
}

// A caught opponent is thrown, not hit: full damage with no combo scaling, no
// combo credit (the throw resets neutral), and the knockdown starts immediately
// because there is no hitstun to wait out.
function applyThrow(world, atk, def, move) {
  def.hp = clamp(def.hp - move.damage, 0, FIGHTER.startHP);
  atk.totalDamageDealt += move.damage;
  def.action = null;
  def.hitstun = 0;
  def.vx = atk.facing * (move.knockback?.x || 6);
  def.hitstop = 8;
  beginKnockdown(world, def, 26);
  pushEvent(world, { kind: "throw", by: atk.id, on: def.id, move: move.name, dmg: move.damage });
  if (def.hp <= 0) { def.state = "ko"; world.over = true; world.winner = atk.id; pushEvent(world, { kind: "ko", by: atk.id, on: def.id }); }
}

function isBlockingAgainst(def, move, atk) {
  if (!def.onGround) return false;
  if (def.hitstun > 0 || def.state === "attack" || def.state === "knockdown" || def.state === "ko") return false;
  const h = def.lastInput.hold || {};
  // Blockstun keeps the guard up; it does not change what that guard *covers*. A
  // fighter frozen mid-block is still holding the direction they held, so the low
  // that follows a blocked high catches them standing. Auto-blocking every height
  // inside blockstun was what made `sweep` a dead move — the pooled ledger showed
  // 0 lows and not a single sweep attempted, and a mixup with one half missing is
  // not a triangle.
  const guarding = def.blockstun > 0 || !!h.block;
  if (!guarding) return false;
  // must face the attacker
  const facingAttacker = (atk.x >= def.x && def.facing === 1) || (atk.x < def.x && def.facing === -1);
  if (!facingAttacker) return false;
  const crouching = !!h.down || def.state === "crouch";
  if (move.level === "low") return crouching; // low must be blocked crouching
  if (move.overhead) return !crouching; // and an overhead must be blocked standing
  return true;
}

function resolveHits(world) {
  for (const atk of world.fighters) {
    if (!atk.action || atk.action.phase !== "active" || atk.action.hitConsumed) continue;
    const move = atk.action.moveDef;
    if (move.type === "projectile") continue; // projectile resolves separately
    const box = attackBox(atk);
    const def = foeOf(world, atk);
    if (def.invuln > 0 || def.state === "ko") continue;
    if (!overlap(box, hurtbox(def))) continue;
    if (move.type === "grab") {
      // Grounded only, and never on a knocked-down foe: block is exactly what the
      // grab exists to punish, while jumping is its answer.
      if (def.onGround && def.state !== "knockdown") {
        atk.action.hitConsumed = true;
        applyThrow(world, atk, def, move);
      }
      continue;
    }
    applyHit(world, atk, def, move, false);
  }

  // projectiles
  for (const p of world.projectiles) {
    if (p.consumed) continue;
    const target = world.fighters[1 - p.owner];
    if (target.invuln > 0 || target.state === "ko") continue;
    const pbox = { left: p.x - p.w / 2, right: p.x + p.w / 2, bottom: p.y - p.h / 2, top: p.y + p.h / 2 };
    if (overlap(pbox, hurtbox(target))) {
      const owner = world.fighters[p.owner];
      applyHit(world, owner, target, p.move, true);
      p.consumed = true;
    }
  }
  // projectile clash
  for (let i = 0; i < world.projectiles.length; i++) {
    for (let j = i + 1; j < world.projectiles.length; j++) {
      const a = world.projectiles[i], b = world.projectiles[j];
      if (a.owner === b.owner || a.consumed || b.consumed) continue;
      const ab = { left: a.x - a.w / 2, right: a.x + a.w / 2, bottom: a.y - a.h / 2, top: a.y + a.h / 2 };
      const bb = { left: b.x - b.w / 2, right: b.x + b.w / 2, bottom: b.y - b.h / 2, top: b.y + b.h / 2 };
      if (overlap(ab, bb)) { a.consumed = b.consumed = true; pushEvent(world, { kind: "clash" }); }
    }
  }
}

function finalizeCombo(world, attacker) {
  if (attacker.combo.hits > 0) {
    const foe = foeOf(world, attacker);
    // combo ends once the victim can act again
    if (foe.hitstun === 0 && !foe.juggling && foe.state !== "knockdown" && foe.y <= 0) {
      if (attacker.combo.hits > attacker.bestCombo.hits ||
        (attacker.combo.hits === attacker.bestCombo.hits && attacker.combo.damage > attacker.bestCombo.damage)) {
        attacker.bestCombo = { hits: attacker.combo.hits, damage: attacker.combo.damage };
      }
      world.comboLog.push({ owner: attacker.id, hits: attacker.combo.hits, damage: attacker.combo.damage, tick: world.tick });
      attacker.combo = { hits: 0, damage: 0, juggle: 0 };
    }
  }
}

// --- main step --------------------------------------------------------------

export function stepWorld(world, inputs = []) {
  if (world.over) return world;

  // timers — hitstop freezes the whole state machine so frame advantage is
  // preserved and cancel links land inside the defender's hitstun.
  for (const f of world.fighters) {
    if (f.hitstop > 0) { f.hitstop--; continue; }
    if (f.hitstun > 0) {
      f.hitstun--;
      if (f.hitstun === 0 && f.state === "hitstun") f.state = f.onGround ? "neutral" : "airborne";
    }
    if (f.blockstun > 0) { f.blockstun--; if (f.blockstun === 0 && f.state === "block") f.state = "neutral"; }
    if (f.invuln > 0) f.invuln--;
    if (f.dashCooldown > 0) f.dashCooldown--;
    if (f.state === "knockdown") {
      f.knockdownTimer--;
      if (f.knockdownTimer <= 0) { f.state = "neutral"; f.invuln = FIGHTER.wakeInvuln; f.vx = 0; }
    }
    if (f.knockdownQueued && f.hitstun === 0 && f.onGround) { f.knockdownQueued = false; beginKnockdown(world, f, 26); }
  }

  // inputs -> intents
  applyInput(world, 0, inputs[0] || { hold: {}, press: [] });
  applyInput(world, 1, inputs[1] || { hold: {}, press: [] });

  // advance actions
  for (const f of world.fighters) advanceAction(world, f);

  // physics
  for (const f of world.fighters) stepPhysics(world, f);

  // body pushback (no full overlap)
  const [a, b] = world.fighters;
  if (a.onGround && b.onGround && Math.abs(a.x - b.x) < FIGHTER.halfWidth * 2) {
    const push = (FIGHTER.halfWidth * 2 - Math.abs(a.x - b.x)) / 2;
    const dir = a.x <= b.x ? -1 : 1;
    a.x = clamp(a.x + dir * push, ARENA.wallPad, ARENA.width - ARENA.wallPad);
    b.x = clamp(b.x - dir * push, ARENA.wallPad, ARENA.width - ARENA.wallPad);
  }

  // projectiles move + expire
  for (const p of world.projectiles) {
    if (p.consumed) continue;
    p.x += p.vx; p.life--;
    const escaped = p.x < -20 || p.x > ARENA.width + 20; // past the wall, never coming back
    if (p.life <= 0 || escaped) {
      p.consumed = true;
      if (escaped) {
        // A shot that flew by without touching anybody got answered — jumped,
        // out-walked or out-ranged — and its owner has nothing to show for the
        // recovery frames they spent on it. Reported as a fact so the decision
        // layer and the ledger can price it like any other lockout.
        pushEvent(world, { kind: "shot_evaded", by: p.owner, move: p.move.name, recovery: p.move.recovery });
      }
    }
  }
  world.projectiles = world.projectiles.filter(p => !p.consumed && p.x > -50 && p.x < ARENA.width + 50);

  // collision
  resolveHits(world);

  // combo lifecycle
  finalizeCombo(world, a); finalizeCombo(world, b);

  // whiff event for the brain (attack finished without landing)
  for (const f of world.fighters) { /* handled via attack_start + absence of hit; brain diffs */ }

  world.tick++;
  if (world.tick >= world.maxTicks) {
    world.over = true;
    world.winner = a.hp === b.hp ? null : (a.hp > b.hp ? 0 : 1);
  }
  return world;
}
