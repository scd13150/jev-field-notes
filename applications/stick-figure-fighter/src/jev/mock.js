// An offline heuristic decider that returns answers in the EXACT TypeSafe shape.
// Used by unit tests and `--mock` runs so the full brain->policy->engine pipeline
// can be exercised without spending API calls. The live path uses the real JEV
// client; both satisfy the same decider contract, so nothing else changes.
//
// It is deliberately RNG-free: the same state must always produce the same
// answers, so a seeded match replays identically and a test can pin a decision.

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

function pick(obj) {
  // argmax of a probabilities map
  let best = null, bp = -1;
  for (const [k, p] of Object.entries(obj)) if (p > bp) { bp = p; best = k; }
  return { choice: best, confidence: +clamp(0.4 + bp * 0.5, 0, 0.95).toFixed(2), probabilities: obj };
}

export function makeMockDecider({ persona = "balanced", latencyMs = 0 } = {}) {
  return async (state /* , questions */) => {
    if (latencyMs) await new Promise((r) => setTimeout(r, latencyMs));
    const me = state.self, foe = state.foe, sp = state.spacing, reach = state.reach;
    const reads = state.reads || {};
    const close = sp.foe_lengths < 2.8;
    const veryClose = sp.foe_lengths < 2.2;
    const foeCommitted = foe.action && (foe.action.phase === "startup" || foe.action.phase === "active");
    const foeRecovering = foe.action && foe.action.phase === "recovery";
    const foeAir = foe.airborne;
    const lowHp = me.hp_pct < 30;
    const fullBar = me.meter_pct >= 100;
    const halfBar = me.meter_pct >= 50;
    const beingComboed = foe.comboHits >= 2 || foe.juggling;

    // A shot in flight is a threat the melee read cannot see: `state.threat` is
    // built from body hitboxes, and a fireball owns none. Note what is NOT here —
    // a foe merely being in startup is not a threat. Treating it as one makes both
    // sides hold guard on sight of any commitment, and a pooled ledger showed that
    // equilibrium: counter share fell, and the press column became "(walk/hold)".
    const shotIncoming = state.incoming_shot_frames != null && state.incoming_shot_frames <= 12;
    let threat = shotIncoming
      ? clamp(0.55 + (veryClose ? 0.3 : 0), 0, 0.95) : 0.12;
    // `punishable` is code's honest yes/no on "a strike reaches them right now";
    // the judgment is whether the lockout is long enough to be worth committing.
    const lockedOut = reads.foe_whiffed || reads.foe_hitstunned || reads.foe_juggled;
    let punish = lockedOut && state.punishable ? 0.85 : foeRecovering && close ? 0.4 : 0.15;
    // A winding-up foe is the counter-hit case the engine pays for — but only if
    // their startup outlasts our jab's, otherwise the exchange is a trade and a
    // trade is not a win.
    let counter = reads.foe_action_startup
      ? (state.threat?.startupLeft >= 7 ? 0.82 : 0.25)
      : foeRecovering ? 0.7 : foeCommitted ? 0.35 : 0.5;

    const probs = {
      poke: reach.jab ? 0.5 : 0.1,
      combo: (reach.jab && (punish > 0.5 || counter > 0.6)) ? (persona === "rushdown" ? 0.7 : 0.4) : 0.08,
      heavy: reach.strong ? 0.35 : 0.1,
      // Rock-paper-scissors: their guard being up is the whole reason to grab.
      throw: (reach.throw && reads.foe_guarding) ? (persona === "rushdown" ? 0.92 : 0.72) : (reach.throw ? 0.12 : 0.02),
      super: (reads.self_can_super && fullBar) ? 0.88 : (fullBar && close ? 0.45 : 0.02),
      burst: (reads.self_can_burst && beingComboed) ? 0.9 : 0.02,
      // A defensive persona has to actually *hold* the guard, not just answer the
      // frame it lands on: nothing breaks a stance that is never held, and the
      // low/overhead/throw mixup only has a stage against a fighter who turtles.
      block: threat > 0.5 ? 0.6 : (persona === "counter" && close) ? 0.55 : 0.05,
      evade: lowHp && threat > 0.4 ? 0.4 : halfBar && beingComboed ? 0.1 : 0.05,
      anti_air: foeAir ? 0.6 : 0.02,
      space_control: persona === "zoner" && !close ? 0.5 : 0.05,
      reset: 0.1,
    };
    const intent = pick(probs);
    let aggression = (persona === "rushdown" ? 1.7 : persona === "zoner" ? 0.6 : 1.1)
      - (lowHp ? 0.4 : 0) + (punish > 0.5 ? 0.4 : 0) + (fullBar ? 0.3 : 0);
    if (probs.throw >= 0.7) aggression += 0.4; // grabs need the guts to walk into range
    if (reads.self_can_burst && beingComboed) aggression = clamp(aggression, 0, 2) * 0.5;
    // A stance is a bet made before the attack exists, so it can be wrong. This
    // one varies with spacing and style rather than reading the move on screen —
    // a guard that peeked would never be mixup'd, and the measurement would lie.
    const stance = !close || foeAir ? "stand" : persona === "counter" ? "crouch" : "stand";
    return {
      intent,
      guard_stance: {
        type: "choice", choice: stance, confidence: 0.6,
        probabilities: { stand: stance === "stand" ? 0.7 : 0.3, crouch: stance === "crouch" ? 0.7 : 0.3 },
      },
      threat_now: { type: "noul", noul: +threat.toFixed(2) },
      punish_window: { type: "noul", noul: +punish.toFixed(2) },
      counter_hit: { type: "noul", noul: +counter.toFixed(2) },
      aggression: {
        type: "score", score: +clamp(aggression, 0, 2).toFixed(2),
        legend: { 0: "hold back", 1: "moderate", 2: "maximal" }, confidence: 0.6,
      },
    };
  };
}
