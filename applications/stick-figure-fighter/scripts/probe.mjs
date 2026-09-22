// Probe the TypeSafe JEV /v1/systemone endpoint to confirm the contract + latency.
// Run: TYPESAFE_API_KEY=... node scripts/probe.mjs
const KEY = process.env.TYPESAFE_API_KEY;
if (!KEY) { console.error("TYPESAFE_API_KEY not set"); process.exit(1); }

const body = {
  state: {
    self: { name: "Azure", hp: 70, facing: "right", state: "neutral", meter: 40 },
    foe:  { name: "Crimson", hp: 55, facing: "left", state: "attacking", attack: "heavy", airborne: false },
    distance: { unit: "foe_lengths", value: 1.4 },
  },
  model: "jev-latest",
  questions: {
    intent: {
      type: "choice",
      instructions: "Given `state`, pick Azure's single next high-level combat action.",
      criteria: {
        attack_poke: "A fast move to contest the close space",
        punish: "Foe is attacking; strike during their recovery",
        block: "Hold guard to absorb the incoming threat",
        retreat: "Create distance and reset",
        anti_air: "Foe may jump; intercept them",
      },
    },
    threat_now: {
      type: "noul",
      instructions: "Is Foe about to hit `state.self` within the next moment?",
      criteria: { true: "Their attack will connect soon", false: "No imminent hit" },
    },
    punish_window: {
      type: "noul",
      instructions: "Speculative: IF Foe's current attack whiffs or is blocked, is there a clear punish opening?",
      criteria: { true: "A safe punish exists", false: "Punishing is unsafe" },
    },
    aggression: {
      type: "score",
      instructions: "How aggressively should Azure press right now?",
      criteria: ["very cautious", "balanced", "highly aggressive"],
    },
  },
};

const t0 = Date.now();
const res = await fetch("https://api.typesafe.ai/v1/systemone", {
  method: "POST",
  headers: { Authorization: `Bearer ${KEY}`, "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
const ms = Date.now() - t0;
console.log("HTTP", res.status, "latency_ms", ms);
const text = await res.text();
console.log(text);
