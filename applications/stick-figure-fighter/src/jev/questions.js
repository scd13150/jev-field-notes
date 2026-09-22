// The question bundle sent to Jev in a single /v1/systemone request.
//
// TypeSafe composition rule: ask independent questions over the SAME state
// together — they run in parallel and cannot see each other's answers. So the
// intent choice, the threat/punish/counter noul flags and the aggression score
// are all answered from one snapshot. Each is one narrow, coherent judgment;
// speculative questions state their premise ("IF ...") explicitly, and code
// consumes only the answers relevant to the branch it is about to take.
//
// `persona` only rephrases the intent judgment (style bias); it never changes the
// primitive structure, so raw judgments stay reusable and comparable across the
// two JEV brains in the dual-JEV production mode.

export const PERSONAS = {
  balanced: "a well-rounded fighter who balances pressure and defense",
  rushdown: "an aggressive rushdown fighter who loves to get inside and combo",
  zoner: "a patient zoner who controls space with fireballs and punishes greed",
  counter: "a defensive counter-fighter who baits, blocks, and punishes whiffs",
};

export function buildQuestions(personaKey = "balanced") {
  const persona = PERSONAS[personaKey] || PERSONAS.balanced;
  return {
    // CHOICE — the single next high-level strategy. The options are written so
    // code can map each one deterministically to a move sequence below.
    intent: {
      type: "choice",
      instructions:
        `You are ${persona}. Given \`state\`, choose \`self.name\`'s single best next strategy against \`foe.name\`. Be decisive: offense wins fights. Use \`reads.foe_recovering\`, \`reads.foe_whiffed\`, \`reads.foe_hitstunned\` and \`reads.foe_juggled\` — when the foe cannot act, commit to the combo instead of poking or guarding. \`reads.foe_guard_stance\` names which guard they hold and therefore which attack is the wrong one for them: \`stand\` is beaten by the low \`sweep\`, \`crouch\` is beaten by the jump-in overhead, \`stunned\` (still in blockstun) and any turtle is beaten by \`throw\`. Spend a full bar (\`reads.self_can_super\`) when it is in range, and burst (\`reads.self_can_burst\`) when you are being comboed. Weigh \`foe.action.phase\`, \`spacing\`, and which of your moves currently land per \`reach\`.`,
      criteria: {
        poke: "A fast jab to contest space or open a combo",
        combo: "Commit to the full string (jab, heavy, launcher, then jump into the air juggle) — a punish window or launched foe makes this free damage",
        heavy: "Land a big standalone strong/fireball for damage without a full combo",
        throw: "Short-range command grab that beats a blocking foe — the only answer to a foe inside blockstun, and safe against a crouch guard (`reach.throw`)",
        super: "Spend the whole meter bar on the super for a fight-changing hit (`reads.self_can_super`)",
        burst: "Out of a combo — spend 50 meter to escape; use when being juggled or heavily comboed (`reads.self_can_burst`)",
        block: "Guard an imminent threat that cannot be beaten to the frame",
        evade: "Retreat or dash away to reset spacing and avoid pressure",
        anti_air: "The foe is airborne or jumping — intercept with a launcher or air attack",
        space_control: "Keep them out at mid distance (fireball / stay just out of range)",
        reset: "Genuinely neutral — no read either way, footsie at the edge of range",
      },
    },
    // CHOICE (defensive) — the stance to hold, decided under the same latency as
    // everything else. This is deliberately NOT a lookup of the move on screen: a
    // guard that could read the attack height before choosing would never be
    // mixup'd, and the high/low game would not exist. It is a bet on what is
    // coming, refreshed only when a new judgment lands.
    guard_stance: {
      type: "choice",
      instructions:
        "You must commit to a guard stance for the next moment against `foe`. Stand guard stops everything except a low sweep; crouch guard stops lows and every ground strike but is beaten by a jump-in overhead. Decide what `foe` is most likely to attack with NEXT, given how they have been approaching — do not assume you already know which move is coming. A foe who keeps stepping in is usually worth a low; a foe who hops in is worth standing.",
      criteria: {
        stand: "Cover highs and mids: they will poke or jump in",
        crouch: "Cover lows: they will sweep, and are not jumping in",
      },
    },
    // NOUL flags — independent yes/no reads the execution layer reacts to.
    threat_now: {
      type: "noul",
      instructions:
        "Based on `state`, will `foe` hit `self` within the next moment unless something changes, AND can `self` not simply block it? A committed melee attack inside `reach` is the usual case (`reads.foe_committing`); `state.incoming_shot_frames` is the other — the frames until one of their fireballs arrives, null when nothing is in flight, and a shot in flight is a threat even though no hitbox of theirs is live.",
      criteria: { true: "Their attack is close enough and already committed to connect", false: "No imminent hit, or we act first" },
    },
    punish_window: {
      type: "noul",
      instructions:
        "Speculative: IF `foe`'s current action is a whiff (`reads.foe_whiffed`, with `punish_frames` more frames they cannot act), or they are already hit/juggled (`reads.foe_hitstunned`, `reads.foe_juggled`), is there a SAFE punish `self` can start now that beats their recovery? Judge how much of the punish is affordable from `punish_frames` and `reach`.",
      criteria: { true: "A punish is in range and will beat their recovery", false: "Punishing is unsafe or out of range" },
    },
    counter_hit: {
      type: "noul",
      instructions:
        "Speculative: IF `self` starts an attack on the next input, does it land BEFORE `foe`'s hitbox goes active? `reads.foe_action_startup` means their move is still winding up, and the engine pays a real counter-hit bonus for interrupting it (+25% damage, +4 hitstun frames). A trade — both boxes live — is NOT a win, and getting hit during our own startup costs us the whole exchange.",
      criteria: { true: "We interrupt them and take no damage", false: "We get countered, traded, or punished" },
    },
    // SCORE — graded intensity code uses to pick safe vs full-commit variants.
    aggression: {
      type: "score",
      instructions:
        "How boldly should `self` commit to offense right now? Reward a punish or launched foe (`reads`) with maximal; only hold back when genuinely threatened.",
      criteria: [
        "hold back: defend or reset, do not commit",
        "moderate: apply light pressure, safe pokes only",
        "maximal: fully commit to the highest-damage combo available",
      ],
    },
  };
}
