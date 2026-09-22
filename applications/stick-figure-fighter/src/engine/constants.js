// Pure tunables for the fight engine. No I/O, no globals — usable from Node and
// the browser identically so the simulation is deterministic across surfaces.

export const FPS = 60;
export const FRAME_MS = 1000 / FPS;

export const ARENA = {
  width: 900,
  groundY: 0, // fighter feet rest at y=0; jump height is positive up
  wallPad: 40, // fighters cannot leave [wallPad, width-wallPad]
};

export const FIGHTER = {
  halfWidth: 22, // hurtbox half-width on the ground
  bodyHeight: 120, // hurtbox top when standing
  crouchHeight: 66,
  walkSpeed: 3.4,
  backSpeed: 2.6,
  jumpVelocity: 15.2,
  gravity: 0.82,
  // Horizontal speed a jump carries, set by the direction held at take-off. With
  // ~37 airborne frames this is a ~170px arc: long enough to cross under a
  // fireball and land on a body, short enough that a hop is a commitment.
  airSpeed: 4.6,
  startHP: 1300, // ~25 landed strikes: a round long enough to have a neutral game
  dashSpeed: 9.5,
  dashFrames: 12,
  dashCooldown: 24,
  wakeInvuln: 18, // invulnerable frames after getting up from a knockdown
  cornerPushback: 6,
};

// Combo damage scaling. Each successive hit in a combo multiplies the raw
// damage by this table (index 0 = first hit). This is what gives combos a real
// ceiling: the more you chain, the less each extra hit is worth, so there is an
// optimal (and discoverable) max damage route rather than infinite scaling.
export const DAMAGE_SCALE = [
  1.0, 1.0, 0.8, 0.7, 0.6, 0.55, 0.5, 0.45, 0.4, 0.35, 0.3, 0.25, 0.2, 0.15, 0.1,
];

// Juggle points: launching a foe makes them airborne. Each air hit adds points;
// past MAX_JUGGLE the next hit causes a hard knockdown and ends the combo, so
// air extensions are bounded (explore the ceiling, but it is finite).
export const MAX_JUGGLE = 8;

// Gain is per hit that lands: a blocked poke builds almost nothing, a clean one
// builds a lot, so meter rewards pressure rather than volume. burstCost/superCost
// are the two ways to spend it.
//
// gainOnHitTaken is the whole comeback story. A fighter who is confirmed on
// builds nothing but defensive meter, and the escape (burst) costs 50 — so one
// full 4-hit route has to buy it, or being hit once means being hit forever.
// It is below the attacker's rate so pressure still outruns defence.
export const METER = {
  max: 100, gainOnHit: 24, gainOnHitTaken: 12, gainOnBlock: 6, gainOnWhiff: 0,
  burstCost: 50, burstInvuln: 15, burstPush: 30,
  superCost: 100,
};

// Chip damage while blocking. Blocking is safe but never free, so turtling loses
// a slow race against poke range. Projectiles chip at a lower rate (block a
// fireball forever and you still win the exchange, just not untouched). Chip
// always leaves you at 1 HP or above, so pure defence can never be KO'd out.
export const CHIP = { strikeRatio: 0.10, projectileRatio: 0.05 };

// Both fighters slide apart when a strike is guarded, as a ratio of the move's
// knockback. Without the attacker's share, a blocked string leaves them exactly
// where they started and pressure is a free re-walk; with it, holding guard buys
// real distance back and the neutral game restarts further out.
export const BLOCK_PUSH = { defenderRatio: 0.5, attackerRatio: 0.45 };
