// Production-stage sparring harness: TWO JEV-controlled stick figures fight
// headless — no human, no browser. This is the requested "制作阶段采用双 JEV 模型
// 操控的火柴人对战". Each fighter gets its own JevBrain with its own persona, and
// (optionally) its own model tag, so you can A/B two JEV styles/models directly
// and read out who combos better, who spaces better, and where the combat CEILING
// actually is (longest / highest-damage combo the brain reaches).
//
//   node scripts/spar.mjs --live --p1 rushdown --p2 zoner --seconds 45
//   node scripts/spar.mjs --mock --fast --p1 counter --p2 balanced --budget 60
//   node scripts/spar.mjs --mock --games 12            # pooled, across pairings
//
// One match is far too noisy to judge a policy change from — a single whiffed
// grab moves the counter-hit share by several points. `--games N` plays N
// matches, cycling the persona pairings, and reports the POOLED combat ledger so
// the triangle can be measured rather than admired.
//
// --live  uses the real TypeSafe JEV API (needs TYPESAFE_API_KEY) at true 60fps
//         wall-clock, so the near-real-time pipeline is exercised for real.
// --mock  uses the offline heuristic decider (free, instant) — for CI / smoke tests.
// Default: --live if a key is present, else --mock.

import { createWorld, stepWorld } from "../src/engine/engine.js";
import { FRAME_MS } from "../src/engine/constants.js";
import { JevBrain } from "../src/jev/brain.js";
import { makeMockDecider } from "../src/jev/mock.js";
import { PERSONAS } from "../src/jev/questions.js";

function arg(name, dflt) {
  const i = process.argv.indexOf("--" + name);
  return i >= 0 ? process.argv[i + 1] : dflt;
}
const has = (name) => process.argv.includes("--" + name);
const bool = (name, dflt) => (has(name) ? true : dflt);

const opts = {
  mock: bool("mock", false),
  live: bool("live", false),
  fast: bool("fast", false),
  p1: arg("p1", "rushdown"),
  p2: arg("p2", "counter"),
  model1: arg("model1", null),
  model2: arg("model2", null),
  seconds: Number(arg("seconds", 45)),
  budget: Number(arg("budget", 120)), // max JEV decisions per brain; lifted for mock runs below
  games: Math.max(1, Number(arg("games", 1))),
  json: arg("json", null),
};

if (!PERSONAS[opts.p1] || !PERSONAS[opts.p2]) {
  console.error(`personas must be one of: ${Object.keys(PERSONAS).join(", ")}`);
  process.exit(2);
}

// Every ordering is its own matchup: the same two styles attack-and-defend from
// opposite sides, so a persona that only wins going right is exposed.
const PAIRINGS = [
  ["rushdown", "counter"], ["counter", "rushdown"],
  ["rushdown", "zoner"], ["zoner", "rushdown"],
  ["zoner", "balanced"], ["balanced", "zoner"],
  ["balanced", "counter"], ["counter", "balanced"],
];

let useLive = opts.live || (!opts.mock && !!process.env.TYPESAFE_API_KEY);
if (opts.mock) useLive = false;

// The budget is a spend guard for live calls. Left on a mock run it decides results
// instead of protecting anything: eight matches were reported as draws at ~1400 ticks
// because both brains had spent their 120 judgments, not because the fighters ran out
// of clock — and a pooled ledger that measures who was still standing is worthless.
if (!useLive && !process.argv.includes("--budget")) opts.budget = Infinity;

let liveClient = null;
if (useLive) {
  const { makeJeClient } = await import("../src/jev/client.js");
  liveClient = makeJeClient();
}

function deciderFor(persona, modelTag) {
  if (!useLive) return makeMockDecider({ persona });
  return (state, questions) => liveClient({ state, questions, ...(modelTag ? { model: modelTag } : {}) });
}

// One full match, headless. Returns everything the report needs so the harness
// can pool N of these without any module-level match state.
async function playMatch(p1, p2) {
  const world = createWorld({ p1Name: `JEV·${p1}`, p2Name: `JEV·${p2}`, maxTicks: opts.seconds * 60 + 30 });
  const highlights = [];
  function eventLogger(tag) {
    return (rec) => {
      if (rec.error) { highlights.push({ tick: rec.tick, kind: "error", who: tag, msg: rec.error }); return; }
      if (rec.plan && (rec.plan.strategy === "combo")) highlights.push({ tick: rec.tick, kind: "intent", who: tag, strat: rec.plan.strategy });
    };
  }
  // capture engine highlights (launches, big combos, the rock-paper-scissors plays, KO)
  function captureEngine(prevLen) {
    for (let i = prevLen; i < world.events.length; i++) {
      const ev = world.events[i];
      const nm = (id) => world.fighters[id].name;
      if (ev.kind === "launched") highlights.push({ tick: ev.tick, kind: "launch", by: nm(ev.by), on: nm(ev.on) });
      else if (ev.kind === "counter_hit") highlights.push({ tick: ev.tick, kind: "counter", by: nm(ev.by), on: nm(ev.on), move: ev.move });
      else if (ev.kind === "throw") highlights.push({ tick: ev.tick, kind: "throw", by: nm(ev.by), on: nm(ev.on), dmg: ev.dmg });
      else if (ev.kind === "burst") highlights.push({ tick: ev.tick, kind: "burst", by: nm(ev.by), on: nm(ev.on) });
      else if (ev.kind === "hit" && ev.move === "super") highlights.push({ tick: ev.tick, kind: "super", by: nm(ev.by), on: nm(ev.on), dmg: ev.dmg });
      else if (ev.kind === "hit" && ev.hits >= 3) highlights.push({ tick: ev.tick, kind: "combo", by: nm(ev.by), hits: ev.hits, dmg: ev.dmg });
      else if (ev.kind === "ko") highlights.push({ tick: ev.tick, kind: "KO", by: nm(ev.by), on: nm(ev.on) });
    }
  }

  const b1 = new JevBrain({ meId: 0, decider: deciderFor(p1, opts.model1), persona: p1, opts: { maxDecisions: opts.budget }, logger: eventLogger(world.fighters[0].name) });
  const b2 = new JevBrain({ meId: 1, decider: deciderFor(p2, opts.model2), persona: p2, opts: { maxDecisions: opts.budget }, logger: eventLogger(world.fighters[1].name) });

  function frame() {
    const prevLen = world.events.length;
    stepWorld(world, [b1.getInput(world), b2.getInput(world)]);
    b1.observe(world); b2.observe(world);
    captureEngine(prevLen);
  }

  function finished() {
    return world.over || (b1.fires >= opts.budget && b2.fires >= opts.budget && !b1.inFlight && !b2.inFlight);
  }

  if (useLive && !opts.fast) {
    console.log(`LIVE dual-JEV spar · ${world.fighters[0].name} vs ${world.fighters[1].name} · real-time 60fps · budget ${opts.budget}/brain`);
    await new Promise((done) => {
      const iv = setInterval(() => { frame(); if (finished()) { clearInterval(iv); done(); } }, FRAME_MS);
    });
  } else {
    // step as fast as possible, flushing microtasks so the async deciders land
    let n = 0;
    while (!finished() && n < world.maxTicks + 60) {
      frame();
      if (n % 2 === 0) await new Promise((r) => setImmediate(r));
      n++;
    }
    await new Promise((r) => setTimeout(r, 30));
  }

  const [a, b] = world.fighters;
  return {
    p1, p2, world, highlights,
    stats: { a: b1.stats(), b: b2.stats() },
    ledger: ledger(world.events),
    winner: world.winner,
    names: [a.name, b.name],
    hp: [a.hp, b.hp],
    dmg: [a.totalDamageDealt, b.totalDamageDealt],
    tick: world.tick,
    best: [maxCombo(world, 0), maxCombo(world, 1)],
  };
}

function maxCombo(world, fid) {
  return world.comboLog.filter((c) => c.owner === fid).reduce((m, c) => (c.damage > m.damage ? c : m), { hits: 0, damage: 0 });
}

const matches = [];
for (let g = 0; g < opts.games; g++) {
  const [p1, p2] = opts.games > 1 ? PAIRINGS[g % PAIRINGS.length] : [opts.p1, opts.p2];
  matches.push(await playMatch(p1, p2));
}
await report(matches);

// --- the combat ledger -------------------------------------------------------
// The game-theoretic scoreboard, derived only from engine events. Each line is a
// falsifiable claim about whether the triangle actually functions in play — how
// often an attack got guarded, how often a whiff got paid for, whether a stance
// ever broke — so a change to the policy can be checked instead of admired.
function ledger(events) {
  const t = {
    attacks: 0, hits: 0, blocks: 0, counters: 0, throws: 0, bursts: 0,
    whiffs: 0, grabWhiffs: 0, whiffPunished: 0, superHits: 0, lows: 0, overheads: 0,
    launches: 0, maxComboHits: 0, counterBy: {},
    shots: 0, shotsEvaded: 0, jumpIns: 0, starts: {},
  };
  const exposed = []; // { id, until } — a whiff window still open on that fighter
  for (const ev of events) {
    if (ev.kind === "attack_start") {
      t.attacks++;
      // Attempts, not just outcomes: "0 lows" means something entirely different
      // when the low was never pressed than when it was pressed and blocked.
      t.starts[ev.move] = (t.starts[ev.move] || 0) + 1;
    }
    else if (ev.kind === "launched") t.launches++;
    else if (ev.kind === "throw") t.throws++;
    else if (ev.kind === "burst") t.bursts++;
    else if (ev.kind === "jump") t.jumpIns++;
    else if (ev.kind === "block") t.blocks++;
    else if (ev.kind === "projectile") t.shots++;
    else if (ev.kind === "shot_evaded") t.shotsEvaded++;
    else if (ev.kind === "counter_hit") {
      t.counters++;
      // What got intercepted, by what: "jab>into-strong" is a neutral-game loss
      // (we poked into a bigger startup), "airkick>into-launcher" is a jump-in the
      // foe was ready for. Counting only the winners would hide both.
      const k = `${ev.victimMove}>into-${ev.move}`;
      t.counterBy[k] = (t.counterBy[k] || 0) + 1;
    }
    else if (ev.kind === "whiff") {
      t.whiffs++;
      if (ev.grab) t.grabWhiffs++;
      exposed.push({ id: ev.by, until: ev.tick + (ev.recovery || 0) });
    } else if (ev.kind === "hit") {
      t.hits++;
      if (ev.move === "super") t.superHits++;
      if (ev.move === "sweep") t.lows++;
      if (ev.move === "airkick") t.overheads++;
      t.maxComboHits = Math.max(t.maxComboHits, ev.hits || 1);
      const open = exposed.findIndex((x) => x.id === ev.on && ev.tick <= x.until);
      if (open >= 0) { t.whiffPunished++; exposed.splice(open, 1); }
    }
  }
  return t;
}

function sumLedgers(list) {
  const out = {};
  for (const t of list) {
    for (const [k, v] of Object.entries(t)) {
      if (k === "maxComboHits") out[k] = Math.max(out[k] || 0, v);
      else if (k === "counterBy" || k === "starts") {
        const merged = out[k] || (out[k] = {});
        for (const [key, n] of Object.entries(v)) merged[key] = (merged[key] || 0) + n;
      } else out[k] = (out[k] || 0) + v;
    }
  }
  return out;
}

function pct(n, d) { return d ? `${((n / d) * 100).toFixed(1)}%` : "n/a"; }

function printLedger(t) {
  const defenses = t.blocks + t.hits;
  const top = Object.entries(t.counterBy || {}).sort((a, b) => b[1] - a[1]).slice(0, 4)
    .map(([k, n]) => `${k}:${n}`).join("  ");
  console.log("-- combat ledger --");
  console.log(`  attack started   : ${t.attacks}   landed ${t.hits}   guarded ${t.blocks}   whiffed ${t.whiffs}`);
  console.log(`  defence share    : ${pct(t.blocks, defenses)} of attacks that reached a body were guarded (target >=22%)`);
  console.log(`  counter-hit share: ${pct(t.counters, t.hits)} of landed hits were intercepts (target 8-12%) ${top}`);
  console.log(`  whiff punish     : ${t.whiffPunished}/${t.whiffs} whiffs punished (${pct(t.whiffPunished, t.whiffs)}), of ${t.grabWhiffs} empty grabs`);
  console.log(`  throw / burst    : ${t.throws} grabs landed, ${t.bursts} meter escapes`);
  console.log(`  stance breaks    : ${t.lows} lows through a guard, ${t.overheads} overheads, ${t.launches} launches`);
  console.log(`  space control    : ${t.shots} fireballs, ${t.shotsEvaded} never touched anybody; ${t.jumpIns} jumps`);
  console.log(`  super            : ${t.superHits} full-meter finishes`);
  console.log(`  combo ceiling    : ${t.maxComboHits} hits in one string`);
  console.log(`  moves attempted  : ${Object.entries(t.starts || {}).sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k} ${n}`).join("  ")}`);
}

async function report(matches) {
  const pooled = sumLedgers(matches.map((m) => m.ledger));
  const avgTick = Math.round(matches.reduce((s, m) => s + m.tick, 0) / matches.length);
  const last = matches[matches.length - 1];

  console.log(`\n===== DUAL-JEV SPARRING REPORT · ${matches.length} match(es) · ${useLive ? "live" : "mock"} =====`);
  for (const m of matches) {
    console.log(`  ${m.names[0]} ${m.hp[0]} vs ${m.names[1]} ${m.hp[1]}  ticks=${m.tick}  dmg ${m.dmg[0]}-${m.dmg[1]}  ${m.winner == null ? "draw / time" : m.names[m.winner] + " wins"}`);
  }
  console.log(`  average round length: ${avgTick} ticks (${(avgTick / 60).toFixed(0)}s of a ${(opts.seconds).toFixed(0)}s clock)`);
  if (matches.length === 1) {
    const m = matches[0];
    console.log(`  best combo  : ${m.names[0]} ${m.best[0].hits} hits/${m.best[0].damage}dmg | ${m.names[1]} ${m.best[1].hits} hits/${m.best[1].damage}dmg`);
    const j = (s) => `${s.decisions} (${useLive ? "live" : "mock"}${s.errors ? ", " + s.errors + " err" : ""}) avg ${s.avgLatencyMs}ms max ${s.maxLatencyMs}ms`;
    console.log(`  JEV calls   : ${j(m.stats.a)}  vs  ${j(m.stats.b)}`);
  } else {
    const wins = {};
    for (const m of matches) wins[m.winner == null ? "draw" : m.names[m.winner]] = (wins[m.winner == null ? "draw" : m.names[m.winner]] || 0) + 1;
    console.log(`  outcomes    : ${JSON.stringify(wins)}`);
    const errs = matches.reduce((s, m) => s + m.stats.a.errors + m.stats.b.errors, 0);
    const calls = matches.reduce((s, m) => s + m.stats.a.decisions + m.stats.b.decisions, 0);
    const lat = matches.flatMap((m) => [m.stats.a, m.stats.b]).filter((s) => s.decisions);
    console.log(`  JEV calls   : ${calls} total${errs ? `, ${errs} err` : ""} avg ${Math.round(lat.reduce((s, x) => s + x.avgLatencyMs, 0) / lat.length)}ms`);
  }
  printLedger(pooled);
  if (matches.length === 1) {
    console.log(`-- highlights (last 14) --`);
    for (const h of last.highlights.slice(-14)) console.log(`  t${String(h.tick).padStart(4)} ${JSON.stringify(h)}`);
  }
  console.log("====================================");
  if (opts.json) {
    const { writeFile } = await import("node:fs/promises");
    await writeFile(opts.json, JSON.stringify({
      games: matches.length,
      ledger: pooled,
      avgTick,
      matches: matches.map((m) => ({
        p1: m.p1, p2: m.p2, tick: m.tick, winner: m.winner, hp: m.hp, damage: m.dmg,
        ledger: m.ledger, bestCombo: m.best, stats: m.stats, highlights: m.highlights,
      })),
    }, null, 2));
    console.log(`wrote ${opts.json}`);
  }
}
