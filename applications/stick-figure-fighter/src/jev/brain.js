// The JEV brain: a transport-agnostic agent that turns a fighter into a
// near-real-time actor.
//
// The whole point of this file is the *pipeline*: the engine runs every frame
// (getInput -> step), while JEV runs on its own ~1.2s cadence in the background
// (observe -> async decide -> new plan). The sim never blocks on the network.
// The coded policy keeps reacting to live state between model calls, and a fresh
// judgment is folded in the moment it lands. That is what "near-real-time
// reaction" means here: continuous, pipelined, non-blocking — not a blocking
// ask-per-frame, which a 1.2s round trip could never do at 60fps.
//
// `decider(state, questions) -> Promise<answers>` is injected, so the exact same
// brain runs in the browser (decider = fetch /api/jev, key stays server-side) and
// in Node (decider = the JEV client) and in tests (decider = a fake).

import { serializeState } from "./state.js";
import { buildQuestions } from "./questions.js";
import { compilePlan, executePlan } from "./policy.js";

const nowMs = () => (typeof performance !== "undefined" ? performance.now() : Date.now());

export class JevBrain {
  constructor({ meId, decider, persona = "balanced", opts = {}, logger = null }) {
    this.meId = meId;
    this.foeId = 1 - meId;
    this.decider = decider;
    this.persona = persona;
    this.opts = opts;
    this.logger = logger;

    this.plan = null;
    this.inFlight = false;
    this.planAge = 9999;
    this.lastFireTick = -9999;
    this.lastDistance = null;
    this.fires = 0;
    this.errors = 0;
    this.latencySamples = [];
    this.rawLog = [];

    this.ttlFrames = opts.ttlFrames ?? 24;              // re-read at least this often
    this.minFramesBetween = opts.minFramesBetween ?? 12; // API-budget guard
    this.maxDecisions = opts.maxDecisions ?? Infinity;
  }

  // Called every frame BEFORE the engine step: execute the current plan against
  // live world state (plus coded reflexes). Never performs I/O.
  getInput(world) {
    if (!this.plan) return { hold: {}, press: [] };
    return executePlan(this.plan, world, this.meId);
  }

  _triggersFired(world) {
    const me = world.fighters[this.meId], foe = world.fighters[this.foeId];
    for (const ev of world.events) {
      if (ev.tick !== world.tick) continue;
      if (ev.kind === "hit" && ev.on === this.meId) return true;         // we got hit
      if (ev.kind === "launched" && ev.on === this.meId) return true;    // we got launched
      if (ev.kind === "attack_start" && ev.by === this.foeId) return true; // foe committed
      if (ev.kind === "projectile" && ev.by === this.foeId) return true; // foe fired
      if (ev.kind === "ko") return true;
    }
    // A big spacing swing (dash, jump-in, knockback) also reopens the window.
    const d = Math.abs(foe.x - me.x);
    if (this.lastDistance != null && Math.abs(d - this.lastDistance) > 36) return true;
    this.lastDistance = d;
    return false;
  }

  shouldReplan(world) {
    if (this.inFlight) return false;
    if (this.fires >= this.maxDecisions) return false;
    if (world.tick - this.lastFireTick < this.minFramesBetween) return false;
    if (this.plan == null) return true;
    if (this.planAge >= this.ttlFrames) return true;
    if (this._triggersFired(world)) return true;
    return false;
  }

  // Called every frame AFTER the engine step: age the plan and, if warranted,
  // fire a non-blocking decision. Attaching .then keeps the loop unblocked.
  observe(world) {
    this.planAge++;
    if (!this.shouldReplan(world)) return;
    this.inFlight = true;
    const snap = serializeState(world, this.meId);
    const questions = buildQuestions(this.persona);
    const t0 = nowMs();
    this.fires++;
    this.lastFireTick = world.tick;
    this.rawLog.push({ tick: world.tick, state: snap });
    Promise.resolve(this.decider(snap, questions))
      .then((answers) => {
        const lat = nowMs() - t0;
        this.latencySamples.push(lat);
        const plan = compilePlan({ ...(answers || {}), __tick: world.tick }, this.opts);
        this.plan = plan;
        this.rawLog[this.rawLog.length - 1].answers = answers;
        this.rawLog[this.rawLog.length - 1].plan = { strategy: plan.strategy, threat: plan.threat, aggression: plan.aggression, conf: plan.conf };
        if (this.logger) this.logger({ tick: world.tick, latencyMs: lat, persona: this.persona, answers, plan });
      })
      .catch((err) => {
        this.errors++;
        if (this.logger) this.logger({ tick: world.tick, error: String(err && err.message || err) });
      })
      .finally(() => {
        this.inFlight = false;
        this.planAge = 0;
      });
  }

  stats() {
    const s = this.latencySamples;
    const avg = s.length ? s.reduce((a, b) => a + b, 0) / s.length : 0;
    return {
      persona: this.persona, decisions: this.fires, errors: this.errors,
      avgLatencyMs: +avg.toFixed(0), maxLatencyMs: s.length ? +Math.max(...s).toFixed(0) : 0,
      lastStrategy: this.plan?.strategy || null,
    };
  }
}
