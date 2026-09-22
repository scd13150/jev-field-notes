// Compact, fighter-relative state for JEV questions.
//
// Two design rules from TypeSafe practice:
//  1. JEV is NOT given raw pixel coordinates or its own identity. It gets a
//     fighter-relative, qualitative view (in-range / close / mid / far) because
//     System One models generalise over meaning, not numbers. The policy layer
//     holds the raw world and does the coordinate maths itself.
//  2. The state is an ORDER-INDEPENDENT BAG of observations. Any subset can be
//     present without breaking the rest, which is what makes partial/timeout
//     answers safe.
//
// All numbers are rounded and percentage-ised so the prompt is short and stable.

import { MOVES } from "../engine/moves.js";
import { ARENA, FIGHTER, METER } from "../engine/constants.js";

const round = (n) => Math.round(n);
const BODY_WIDTH = FIGHTER.halfWidth * 2;

const SPACING_BANDS = [
  { max: 60, label: "clamp" }, // overlapping, throw territory
  { max: 130, label: "close" }, // inside every ground poke
  { max: 230, label: "mid" }, // fireball range, dash-in range
  { max: 430, label: "far" }, // approach needed
  { max: Infinity, label: "unsafe" }, // full retreat / reposition
];

const band = (px) => (SPACING_BANDS.find((b) => px <= b.max) || SPACING_BANDS[SPACING_BANDS.length - 1]).label;

// Horizontal reach of a move's attack box against the foe's body, using the same
// maths the engine uses for collision (so `reach` never lies to JEV).
function reaches(me, foe, moveDef) {
  if (!moveDef || !moveDef.hitbox) return false;
  const cx = me.x + me.facing * moveDef.hitbox.x;
  return Math.abs(cx - foe.x) <= moveDef.hitbox.w / 2 + FIGHTER.halfWidth;
}

const heightOf = (f) => (f.state === "crouch" ? FIGHTER.crouchHeight : FIGHTER.bodyHeight);

// Is this fighter currently guarding something? Mirrors the engine's own
// isBlockingAgainst preconditions (grounded, not mid-attack, holding block).
function guarding(f) {
  if (!f.onGround || f.action || f.hitstun > 0 || f.state === "ko") return false;
  if (f.blockstun > 0) return true;
  return !!(f.lastInput && f.lastInput.hold && f.lastInput.hold.block);
}

// Which guard they are holding, because each one has a different wrong answer:
// a standing block eats lows, a crouching block eats overheads, and a foe still
// inside blockstun auto-blocks both — only a grab gets through that.
function guardStance(f) {
  if (!guarding(f)) return "none";
  if (f.blockstun > 0) return "stunned";
  const h = (f.lastInput && f.lastInput.hold) || {};
  return h.down ? "crouch" : "stand";
}

// The foe's live threat, computed by code (not judged): their attack box vs our
// body, plus how many frames of startup remain.
function threatOf(foe, me) {
  const a = foe.action;
  if (!a) return null;
  const m = a.moveDef || MOVES[a.move];
  if (!m) return null;
  const startupLeft = Math.max(0, (m.startup || 0) - a.frame);
  const horizontal = reaches(foe, me, m);
  const vertical = !m.hitbox ? false
    : (me.y + heightOf(me) > foe.y + m.hitbox.y - m.hitbox.h / 2) && (me.y < foe.y + m.hitbox.y + m.hitbox.h / 2);
  // Grabs have no vertical component: they catch a grounded, standing foe only.
  const canConnect = m.type === "grab"
    ? horizontal && me.onGround && me.state !== "knockdown"
    : horizontal && vertical;
  return { move: a.move, type: m.type, phase: a.phase, startupLeft, canConnect };
}

function fighterView(f) {
  return {
    name: f.name,
    hp_pct: round((f.hp / FIGHTER.startHP) * 100),
    meter_pct: round(f.meter),
    state: f.state,
    airborne: !f.onGround,
    action: f.action ? { move: f.action.move, phase: f.action.phase, cancelOpen: !!f.action.cancelOpen } : null,
    hitstun: f.hitstun,
    blockstun: f.blockstun,
    invuln: f.invuln,
    juggling: f.juggling,
    juggle: f.juggle,
    comboHits: f.combo.hits,
    guarding: guarding(f),
    canAct: f.hitstop === 0 && f.hitstun === 0 && f.blockstun === 0 && f.state !== "knockdown" && f.state !== "ko",
  };
}

// A projectile belongs to nobody's hitbox: it is a separate object travelling
// across the arena, so the melee geometry above cannot see it and reports a
// fireball-bearing foe as "no threat". Code measures the real fact — frames until
// it can touch us — so JEV judges "block, jump, or let it pass" on data instead
// of a guess. Same maths the guard reflex uses, from the same world.
function incomingShotOf(world, me, foe) {
  let soonest = null;
  for (const p of world.projectiles || []) {
    if (p.consumed || p.owner !== foe.id) continue;
    const closing = (me.x - p.x) * Math.sign(p.vx || 1);
    if (closing <= 0) continue; // behind us, or travelling away
    const frames = Math.max(0, Math.round((closing - (p.w / 2 + FIGHTER.halfWidth)) / Math.abs(p.vx)));
    if (soonest === null || frames < soonest) soonest = frames;
  }
  return soonest === null ? null : { frames_until_contact: soonest };
}

export function serializeState(world, meId) {
  const me = world.fighters[meId];
  const foe = world.fighters[1 - meId];
  const distancePx = round(Math.abs(foe.x - me.x));
  const threat = threatOf(foe, me);
  const shot = incomingShotOf(world, me, foe);
  const approach = threat && threat.canConnect
    ? (threat.phase === "startup" && threat.startupLeft > 5 ? "telegraphed" : "incoming")
    : "none";

  // Whiff punish: the foe is locked in recovery of something that cannot hit us.
  const foeRecovering = !!foe.action && foe.action.phase === "recovery";
  const whiffed = foeRecovering && !foe.action.hitConsumed;
  const punishFrames = whiffed ? Math.max(0, (foe.action.moveDef?.recovery || 0) - foe.action.frame) : 0;
  const punishable = ["jab", "strong", "launcher", "sweep"].some((k) => reaches(me, foe, MOVES[k]));

  return {
    clock: { ticks_remaining_pct: round((1 - world.tick / world.maxTicks) * 100) },
    self: fighterView(me),
    foe: fighterView(foe),
    spacing: {
      band: band(distancePx),
      // Gap expressed in body-widths (1.0 = bodies touching): the unit JEV and the
      // mock heuristics both reason in.
      foe_lengths: +(distancePx / BODY_WIDTH).toFixed(2),
      distance_px: distancePx,
      cornered: me.x < ARENA.wallPad + 60 || me.x > ARENA.width - ARENA.wallPad - 60,
    },
    threat,
    // Frames before the foe's fireball can touch us (null when nothing is in
    // flight). Separate from `threat` because that one is a body-hitbox read.
    incoming_shot_frames: shot,
    approach,
    // `reach` is the honest yes/no on each option; `reads` are the situation
    // tags the question set references.
    reach: {
      jab: reaches(me, foe, MOVES.jab),
      strong: reaches(me, foe, MOVES.strong),
      launcher: reaches(me, foe, MOVES.launcher),
      sweep: reaches(me, foe, MOVES.sweep),
      fireball: reaches(me, foe, MOVES.fireball),
      airkick: reaches(me, foe, MOVES.airkick),
      throw: reaches(me, foe, MOVES.throw),
      super: reaches(me, foe, MOVES.super),
    },
    reads: {
      foe_recovering: foeRecovering && !threat?.canConnect,
      foe_committing: !!foe.action && foe.action.phase === "startup" && foe.action.frame >= 2,
      foe_hitstunned: foe.hitstun > 0,
      foe_juggled: foe.juggling,
      self_mid_combo: me.combo.hits > 0 && foe.hitstun > 0,
      self_cancel_open: !!me.action && !!me.action.cancelOpen,
      // Their move exists and is still winding up: a clean hit lands as an
      // engine-rewarded counter-hit (+25% damage, +4 frames of hitstun).
      foe_action_startup: !!foe.action && foe.action.phase === "startup",
      // They swung and missed: for `punish_frames` more they cannot act, which is
      // the only window in which a heavy punish is genuinely free.
      foe_whiffed: punishFrames >= 6,
      foe_guarding: guarding(foe),
      foe_guard_stance: guardStance(foe),
      self_can_burst: me.onGround && me.hitstun > 0 && !me.burstUsed && me.meter >= METER.burstCost,
      self_can_super: me.meter >= METER.superCost && reaches(me, foe, MOVES.super),
    },
    punishable,
    punish_frames: punishFrames,
  };
}
