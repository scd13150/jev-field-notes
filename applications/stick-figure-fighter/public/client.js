// Browser client: runs the SAME deterministic engine the tests run, at a fixed
// 60Hz timestep on requestAnimationFrame. The player drives fighter 0; fighter 1
// is driven by a JevBrain. That brain's decider is a fetch to /api/jev (the
// server holds the API key); with no key or a failed fetch it falls back to the
// offline mock decider so the game is always playable. Presentation is fully
// separated into view.js — gameplay state never depends on it.

import { createWorld, stepWorld } from "/src/engine/engine.js";
import { ARENA } from "/src/engine/constants.js";
import { JevBrain } from "/src/jev/brain.js";
import { makeMockDecider } from "/src/jev/mock.js";
import { View } from "/public/view.js";

const canvas = document.getElementById("stage");
const W = ARENA.width, H = 340;
canvas.width = W; canvas.height = H;
let view = new View(canvas);

const els = {
  hp1: document.getElementById("hp1"), hp2: document.getElementById("hp2"),
  m1: document.getElementById("m1"), m2: document.getElementById("m2"),
  strat: document.getElementById("je-strat"), lat: document.getElementById("je-lat"),
  mode: document.getElementById("mode-badge"),
};

// --- keyboard input (edge-detect presses, track holds) ----------------------
const held = new Set();
let pressed = [];
const KEY = {
  ArrowLeft: "left", KeyA: "left", ArrowRight: "right", KeyD: "right",
  ArrowDown: "down", KeyS: "down", Space: "block", ShiftLeft: "block",
  ArrowUp: "jump", KeyW: "jump",
  KeyJ: "jab", KeyK: "strong", KeyU: "launcher", KeyI: "sweep", KeyO: "fireball", KeyH: "airkick",
  KeyT: "throw", KeyG: "super", KeyB: "burst",
};
addEventListener("keydown", (e) => {
  if (e.code === "KeyR" || e.code === "KeyM") { handleMeta(e.code); return; }
  const a = KEY[e.code]; if (!a) return;
  e.preventDefault();
  if (!held.has(a)) pressed.push(a);
  held.add(a);
});
addEventListener("keyup", (e) => { const a = KEY[e.code]; if (a) held.delete(a); });

function playerInput() {
  const hold = {};
  if (held.has("left")) hold.left = true;
  if (held.has("right")) hold.right = true;
  if (held.has("down")) hold.down = true;
  if (held.has("block")) hold.block = true;
  const press = pressed.filter((a) => a === "jump"
    || ["jab", "strong", "launcher", "sweep", "fireball", "airkick", "throw", "super", "burst"].includes(a));
  pressed = [];
  return { hold, press };
}

// --- world + brains ---------------------------------------------------------
let world = createWorld({ p1Name: "YOU", p2Name: "JEV" });
let evSeen = 0;
const state = { live: false, mode: "pve", persona: "balanced" };

function liveDecider(stateSnap, questions) {
  return fetch("/api/jev", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ state: stateSnap, persona: state.persona }),
  }).then((r) => { if (!r.ok) throw new Error("jev " + r.status); return r.json(); })
    .then((j) => j.answers);
}

let brainFoe = null, brainSelf = null;
function makeBrains() {
  const foeDecider = state.live ? liveDecider : makeMockDecider({ persona: state.persona });
  brainFoe = new JevBrain({ meId: 1, decider: foeDecider, persona: state.persona });
  if (state.mode === "jev2") {
    const selfDecider = state.live ? liveDecider : makeMockDecider({ persona: "rushdown" });
    brainSelf = new JevBrain({ meId: 0, decider: selfDecider, persona: "rushdown" });
  } else brainSelf = null;
}
makeBrains();

async function detectLive() {
  try { const c = await (await fetch("/api/config")).json(); state.live = !!c.has_key; }
  catch { state.live = false; }
  els.mode.textContent = state.live ? "JEV · LIVE" : "JEV · MOCK (no key)";
  els.mode.classList.toggle("live", state.live);
  makeBrains();
}
detectLive();

// --- one deterministic 60Hz substep + fx drain ------------------------------
function substep() {
  if (world.over) return;
  const i0 = brainSelf ? brainSelf.getInput(world) : playerInput();
  const i1 = brainFoe.getInput(world);
  stepWorld(world, [i0, i1]);
  if (brainSelf) brainSelf.observe(world);
  brainFoe.observe(world);
}
function drainFx() {
  while (evSeen < world.events.length) { view.onEvent(world.events[evSeen], world); evSeen++; }
}

// --- fixed timestep loop ----------------------------------------------------
let last = performance.now(), acc = 0; const STEP = 1000 / 60;
function frame(now) {
  acc += Math.min(now - last, 100); last = now;
  while (acc >= STEP) { substep(); acc -= STEP; }
  drainFx(); view.update(); view.draw(world); hud();
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// --- HUD (DOM) --------------------------------------------------------------
function bar(el, pct) { if (el) el.style.width = Math.max(0, Math.min(100, pct)) + "%"; }
function hud() {
  const [a, b] = world.fighters;
  bar(els.hp1, a.hp / 1000 * 100); bar(els.hp2, b.hp / 1000 * 100);
  bar(els.m1, a.meter); bar(els.m2, b.meter);
  const s = brainFoe.stats();
  els.strat.textContent = `${state.persona} → ${s.lastStrategy || "…"}`;
  els.lat.textContent = s.decisions ? `${s.avgLatencyMs}ms · ${s.decisions} calls` : "…";
}

// --- rematch / mode ---------------------------------------------------------
function rematch() {
  world = createWorld({ p1Name: "YOU", p2Name: "JEV" });
  evSeen = 0; view = new View(canvas); makeBrains();
}
function handleMeta(code) {
  if (code === "KeyR" && world.over) rematch();
  if (code === "KeyM") { state.mode = state.mode === "pve" ? "jev2" : "pve"; rematch(); }
}
document.getElementById("persona").onchange = (e) => { state.persona = e.target.value; makeBrains(); };
document.getElementById("reset").onclick = () => rematch();
document.getElementById("modebtn").onclick = () => handleMeta("KeyM");

// debug/test hook: drive frames without relying on rAF (throttled in a hidden
// tab) so rendering can be verified programmatically.
globalThis.__game = {
  pump(n = 1) { for (let k = 0; k < n; k++) substep(); drainFx(); view.update(); view.draw(world); hud(); return { tick: world.tick, hp0: world.fighters[0].hp, hp1: world.fighters[1].hp, over: world.over }; },
  state() { return { tick: world.tick, x0: Math.round(world.fighters[0].x), x1: Math.round(world.fighters[1].x), live: state.live, mode: state.mode, w: canvas.width, h: canvas.height }; },
  canvas, get view() { return view; },
};
