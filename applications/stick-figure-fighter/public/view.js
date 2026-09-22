// Presentation layer. The engine keeps the authoritative deterministic state;
// this file is ONLY about making it look and feel like a game: articulated
// stick-figure poses, an arena, and a particle/shake/floater FX system driven by
// the engine's per-tick event stream. Nothing here feeds back into gameplay.

import { MOVES } from "/src/engine/moves.js";
import { FIGHTER } from "/src/engine/constants.js";

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

// A drawable point: present and finite. NaN coordinates are the dangerous case,
// because NaN fails no `null` check but still poisons the canvas path.
function finitePoint(p) {
  return !!p && typeof p.x === "number" && isFinite(p.x)
            && typeof p.y === "number" && isFinite(p.y);
}

// A 2-bone "bone" from a->b with the joint pushed perpendicular by `bend`.
function bone(a, b, bend) {
  const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
  const dx = b.x - a.x, dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const nx = -dy / len, ny = dx / len;
  return { x: mx + nx * bend, y: my + ny * bend };
}

// fighter palette (index 0 = player blue, index 1 = JEV red)
const PAL = [
  { core: "#5fd6ff", glow: "#1b6fa0", accent: "#eaffff", name: "#8ee6ff" },
  { core: "#ff6070", glow: "#a02436", accent: "#fff0f0", name: "#ff97a2" },
];

export class View {
  constructor(canvas) {
    this.cv = canvas;
    this.ctx = canvas.getContext("2d");
    this.W = canvas.width; this.H = canvas.height;
    this.groundY = this.H - 66;
    this.parts = [];   // particles
    this.floats = [];  // floating texts
    this.popups = [];  // combo popups
    this.shake = 0; this.flash = 0; this.koTimer = 0; this.slow = 0;
    this.t = 0;
  }

  // ---- FX spawning (called from the game loop on each engine event) ---------
  onEvent(ev, world) {
    const gy = this.groundY;
    const pos = (fid, yOff = 60) => { const f = world.fighters[fid]; return { x: f.x, y: gy - f.y - yOff }; };
    if (ev.kind === "hit") {
      const p = pos(ev.on, 66); const c = PAL[1 - ev.by];
      this.burst(p.x, p.y, 10 + Math.min(16, ev.dmg / 6), c.core, 3.4);
      this.floats.push({ x: p.x, y: p.y - 10, vy: -0.9, life: 46, text: "-" + ev.dmg, color: "#fff", size: clamp(11 + ev.dmg / 12, 11, 22) });
      this.shake = Math.min(18, this.shake + 4 + ev.dmg / 22);
      this.flash = Math.max(this.flash, clamp(ev.dmg / 260, 0.12, 0.5));
      if (ev.hits >= 2) this.popups.push({ by: ev.by, hits: ev.hits, dmg: null, life: 40, t: this.t });
    } else if (ev.kind === "block") {
      const p = pos(ev.on, 60); this.burst(p.x, p.y, 8, "#bfe9ff", 2.2, true);
      this.shake = Math.min(10, this.shake + 2.2);
    } else if (ev.kind === "launched") {
      const p = pos(ev.on, 40); this.ring(p.x, p.y, PAL[1 - ev.by].core);
      this.burst(p.x, p.y, 16, "#ffd27a", 4);
      this.shake = Math.min(20, this.shake + 8);
    } else if (ev.kind === "knockdown") {
      const f = world.fighters[ev.by]; this.dust(f.x, this.groundY - f.y); this.shake = Math.min(16, this.shake + 5);
    } else if (ev.kind === "clash") {
      const a = world.projectiles[0]; if (a) this.burst(a.x, this.groundY - a.y, 14, "#ffcf6b", 3.6);
    } else if (ev.kind === "projectile") {
      const p = world.projectiles[world.projectiles.length - 1]; if (p) this.burst(p.x, this.groundY - p.y, 6, "#ff9a4d", 2.6);
    } else if (ev.kind === "ko") {
      this.koTimer = 90; this.slow = 40; this.shake = 26; this.flash = 0.85;
    }
  }

  burst(x, y, n, color, spd, ring = false) {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2, s = spd * (0.4 + Math.random());
      this.parts.push({ x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s - 1, life: 18 + Math.random() * 22, color, sz: 1 + Math.random() * 2.4, grav: 0.22 });
    }
  }
  ring(x, y, color) { this.parts.push({ x, y, vx: 0, vy: 0, life: 20, color, sz: 4, ring: true }); }
  dust(x, y) { for (let i = 0; i < 10; i++) this.parts.push({ x: x + (Math.random() - 0.5) * 24, y, vx: (Math.random() - 0.5) * 2.4, vy: -Math.random() * 1.6, life: 24, color: "#6f7a95", sz: 2, grav: 0.08 }); }

  update() {
    this.t++;
    this.shake *= 0.86; if (this.shake < 0.2) this.shake = 0;
    this.flash *= 0.82; this.koTimer = Math.max(0, this.koTimer - 1); this.slow = Math.max(0, this.slow - 1);
    for (const p of this.parts) { p.x += p.vx; p.y += p.vy; p.vy += p.grav || 0; p.life--; }
    this.parts = this.parts.filter((p) => p.life > 0);
    for (const f of this.floats) { f.y += f.vy; f.vy *= 0.97; f.life--; }
    this.floats = this.floats.filter((f) => f.life > 0);
    this.popups = this.popups.filter((p) => this.t - p.t < 40);
  }

  // ---- scene ---------------------------------------------------------------
  draw(world) {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.W, this.H);
    this.drawArena(ctx);
    ctx.save();
    const sx = (Math.random() - 0.5) * this.shake, sy = (Math.random() - 0.5) * this.shake;
    ctx.translate(sx, sy);
    for (const p of world.projectiles) this.drawProjectile(ctx, p);
    this.drawFighter(ctx, world.fighters[0], PAL[0], world);
    this.drawFighter(ctx, world.fighters[1], PAL[1], world);
    this.drawParticles(ctx);
    ctx.restore();
    this.drawFloats(ctx);
    this.drawCombo(ctx, world);
    if (this.flash > 0.01) { ctx.fillStyle = `rgba(255,255,255,${this.flash})`; ctx.fillRect(0, 0, this.W, this.H); }
    this.vignette(ctx);
    if (world.over) this.drawKO(ctx, world);
  }

  drawArena(ctx) {
    const g = ctx.createLinearGradient(0, 0, 0, this.H);
    g.addColorStop(0, "#0c1226"); g.addColorStop(0.6, "#0a1020"); g.addColorStop(1, "#070b16");
    ctx.fillStyle = g; ctx.fillRect(0, 0, this.W, this.H);
    // backdrop arc glow
    const rg = ctx.createRadialGradient(this.W / 2, this.groundY - 40, 30, this.W / 2, this.groundY - 40, 460);
    rg.addColorStop(0, "rgba(70,90,160,0.18)"); rg.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = rg; ctx.fillRect(0, 0, this.W, this.H);
    // floor
    ctx.fillStyle = "#10182c"; ctx.fillRect(0, this.groundY, this.W, this.H - this.groundY);
    ctx.strokeStyle = "#2a3a5e"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(0, this.groundY); ctx.lineTo(this.W, this.groundY); ctx.stroke();
    // perspective floor lines + centre mark
    ctx.strokeStyle = "rgba(60,80,130,0.25)"; ctx.lineWidth = 1;
    for (let i = 1; i <= 6; i++) { const y = this.groundY + i * i * 1.6; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(this.W, y); ctx.stroke(); }
    ctx.strokeStyle = "rgba(120,150,220,0.25)"; ctx.beginPath(); ctx.moveTo(this.W / 2, this.groundY); ctx.lineTo(this.W / 2, this.H); ctx.stroke();
    ctx.fillStyle = "rgba(90,110,160,0.10)"; ctx.fillRect(0, this.groundY - 2, 44, this.H); ctx.fillRect(this.W - 44, this.groundY - 2, 44, this.H); // walls
  }

  drawProjectile(ctx, p) {
    const y = this.groundY - p.y;
    ctx.save(); ctx.shadowColor = "#ff9a3c"; ctx.shadowBlur = 18;
    const g = ctx.createRadialGradient(p.x, y, 1, p.x, y, p.w);
    g.addColorStop(0, "#fff2c2"); g.addColorStop(0.5, "#ffb24d"); g.addColorStop(1, "rgba(255,90,30,0)");
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(p.x, y, p.w, 0, 7); ctx.fill(); ctx.restore();
  }

  drawParticles(ctx) {
    for (const p of this.parts) {
      ctx.globalAlpha = clamp(p.life / 22, 0, 1);
      if (p.ring) { ctx.strokeStyle = p.color; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(p.x, p.y, (20 - p.life) * 3, 0, 7); ctx.stroke(); }
      else { ctx.fillStyle = p.color; ctx.beginPath(); ctx.arc(p.x, p.y, p.sz, 0, 7); ctx.fill(); }
    }
    ctx.globalAlpha = 1;
  }
  drawFloats(ctx) {
    ctx.textAlign = "center";
    for (const f of this.floats) { ctx.globalAlpha = clamp(f.life / 40, 0, 1); ctx.fillStyle = f.color; ctx.font = `bold ${f.size}px system-ui`; ctx.fillText(f.text, f.x, f.y); }
    ctx.globalAlpha = 1;
  }
  drawCombo(ctx, world) {
    for (const p of this.popups) {
      const age = (this.t - p.t) / 40, sc = 1 + Math.max(0, 0.5 - age) * 0.8;
      const f = world.fighters[p.by];
      const x = f.x, y = this.groundY - f.y - 150;
      ctx.save(); ctx.translate(x, y); ctx.scale(sc, sc); ctx.globalAlpha = clamp(1 - age * 0.6, 0, 1);
      ctx.textAlign = "center"; ctx.fillStyle = PAL[p.by].core; ctx.font = "bold 26px system-ui";
      ctx.fillText(`${p.hits} HIT${p.hits > 1 ? "S" : ""}`, 0, 0); ctx.restore();
    }
  }
  vignette(ctx) {
    const g = ctx.createRadialGradient(this.W / 2, this.H / 2, this.H * 0.4, this.W / 2, this.H / 2, this.H * 0.85);
    g.addColorStop(0, "rgba(0,0,0,0)"); g.addColorStop(1, "rgba(0,0,0,0.45)");
    ctx.fillStyle = g; ctx.fillRect(0, 0, this.W, this.H);
  }
  drawKO(ctx, world) {
    ctx.fillStyle = "rgba(4,6,14,0.55)"; ctx.fillRect(0, 0, this.W, this.H);
    ctx.textAlign = "center"; ctx.fillStyle = "#fff";
    const big = world.winner == null ? "DRAW" : (world.winner === 0 ? "YOU WIN" : "JEV WINS");
    ctx.font = "900 52px system-ui"; ctx.fillText(big, this.W / 2, this.H / 2 - 6);
    ctx.font = "14px system-ui"; ctx.fillStyle = "#9fb0d6"; ctx.fillText("press R to rematch", this.W / 2, this.H / 2 + 26);
  }

  // ---- the articulated stick figure ----------------------------------------
  drawFighter(ctx, f, pal, world) {
    const feetY = this.groundY - f.y, x = f.x, face = f.facing;
    // shadow scales with air height
    const air = clamp(f.y / 150, 0, 1);
    ctx.save(); ctx.globalAlpha = 0.4 * (1 - air); ctx.fillStyle = "#000";
    ctx.beginPath(); ctx.ellipse(x, this.groundY + 4, 26 * (1 - air * 0.5), 7 * (1 - air * 0.5), 0, 0, 7); ctx.fill(); ctx.restore();

    if (f.state === "hitstun" && world.tick % 6 < 3) ctx.globalAlpha = 0.55;
    if (f.invuln > 0 && world.tick % 8 < 4) ctx.globalAlpha = 0.5;

    const P = this.pose(f, face, world);
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    const seg = (a, b, bend, w) => { const j = bone(a, b, bend); this.stroke2(ctx, a, j, b, w); };

    // back limbs dimmer for depth
    ctx.strokeStyle = pal.glow;
    seg(P.hip, P.footB, P.bendLegB, 7); seg(P.shoulder, P.handB, P.bendArmB, 6);
    ctx.strokeStyle = pal.core;
    seg(P.hip, P.footF, P.bendLegF, 8); seg(P.shoulder, P.handF, P.bendArmF, 7);
    // torso + head
    this.stroke2(ctx, P.hip, P.chest, null, 9);
    ctx.strokeStyle = pal.core; this.stroke2(ctx, P.chest, { x: (P.handF.x + P.handB.x) / 2, y: P.chest.y - 2 }, null, 0);
    ctx.strokeStyle = pal.core; ctx.lineWidth = 9; ctx.beginPath(); ctx.moveTo(P.hip.x, P.hip.y); ctx.lineTo(P.chest.x, P.chest.y); ctx.lineTo(P.head.x, P.head.y + 11); ctx.stroke();
    // head
    ctx.save(); ctx.shadowColor = pal.glow; ctx.shadowBlur = 12; ctx.fillStyle = pal.core;
    ctx.beginPath(); ctx.arc(P.head.x, P.head.y, 12, 0, 7); ctx.fill(); ctx.restore();
    ctx.fillStyle = pal.accent; ctx.beginPath(); ctx.arc(P.head.x + face * 5, P.head.y - 1, 2.4, 0, 7); ctx.fill(); // eye toward foe
    ctx.globalAlpha = 1;
  }

  stroke2(ctx, a, j, b, w) {
    // A limb or torso point can be missing on a transitional frame. Without this
    // guard the line below throws and aborts drawFighter, which silently costs the
    // REST of that fighter's body and every fighter drawn after it.
    if (!finitePoint(a) || !finitePoint(b)) return;
    if (w) ctx.lineWidth = w;
    ctx.beginPath();
    if (j) { ctx.moveTo(a.x, a.y); ctx.lineTo(j.x, j.y); ctx.lineTo(b.x, b.y); }
    else { ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); }
    ctx.stroke();
  }

  pose(f, face, world) {
    const x = f.x, feetY = this.groundY - f.y;
    const L = { legU: 30, legL: 28, torso: 46, neck: 10, headR: 12, armU: 22, armL: 22 };
    let hip = { x, y: feetY - L.legU - L.legL };
    let lean = 0, armFwd = 6, both = false;
    const mv = f.action && f.action.moveDef;
    const phase = f.action && f.action.phase;

    if (f.state === "crouch") { hip.y += 20; }
    if (f.state === "walk") { const s = Math.sin(world.tick / 6); hip.x += s * 1.5; }
    if (f.state === "hitstun") { lean = -face * 0.5; }
    if (f.state === "knockdown" || f.state === "ko") {
      // lying flat
      const dir = -face;
      const hip2 = { x, y: this.groundY - 12 };
      const chest = { x: hip2.x + dir * 34, y: this.groundY - 12 };
      return {
        hip: hip2, chest, head: { x: chest.x + dir * 14, y: this.groundY - 12 },
        shoulder: { x: chest.x, y: this.groundY - 16 },
        footF: { x: hip2.x - dir * 20, y: this.groundY - 6 }, bendLegF: 4,
        footB: { x: hip2.x - dir * 26, y: this.groundY - 14 }, bendLegB: -4,
        handF: { x: chest.x + dir * 16, y: this.groundY - 2 }, bendArmF: 5,
        handB: { x: chest.x + dir * 20, y: this.groundY - 14 }, bendArmB: -5,
      };
    }

    // torso/chest/head from lean
    const chest = { x: hip.x + Math.sin(lean) * 8 * face, y: hip.y - L.torso };
    const head = { x: chest.x + Math.sin(lean) * 12 * face, y: chest.y - L.neck - 8 };
    const shoulder = { x: chest.x, y: chest.y + 4 };

    // default feet
    let footF = { x: x + face * 14, y: feetY }, footB = { x: x - face * 12, y: feetY };
    let bendLegF = -6, bendLegB = 6;
    if (f.state === "crouch") { footF = { x: x + face * 18, y: feetY }; footB = { x: x - face * 16, y: feetY }; }
    if (!f.onGround) { const t = Math.sin(world.tick / 5); footF = { x: x + face * 8, y: feetY + 22 }; footB = { x: x - face * 6, y: feetY + 30 }; bendLegF = -14; bendLegB = -10; }

    let handF = { x: x + face * (14 + armFwd), y: shoulder.y + 16 }, handB = { x: x + face * 2, y: shoulder.y + 18 };
    let bendArmF = -8, bendArmB = 8;

    if (f.state === "block") { handF = { x: x + face * 16, y: shoulder.y + 4 }; handB = { x: x + face * 15, y: shoulder.y + 14 }; bendArmF = -14; bendArmB = -10; }
    else if (mv && mv.hitbox) {
      const ext = phase === "active" ? 1 : phase === "startup" ? -0.25 : 0.5;
      const reach = clamp(mv.hitbox.x * 0.6, 20, 46);
      if (mv.name === "launcher") { handF = { x: x + face * (12 + 18 * ext), y: shoulder.y - 30 * ext }; bendArmF = -18; lean = face * 0.12; }
      else if (mv.name === "sweep") { footF = { x: x + face * (30 + reach * ext * 0.5), y: feetY + 4 }; hip.y += 22; handF = { x: x - face * 6, y: shoulder.y + 26 }; handB = { x: x - face * 18, y: shoulder.y + 20 }; }
      else if (mv.name === "fireball") { handF = { x: x + face * (16 + 10 * ext), y: shoulder.y + 10 }; handB = { x: x + face * 12, y: shoulder.y + 12 }; bendArmF = -10; bendArmB = -10; }
      else { handF = { x: x + face * (14 + reach * ext), y: shoulder.y + (mv.name === "strong" ? 10 : 6) }; bendArmF = ext > 0.6 ? 2 : -8; lean = face * 0.18 * ext; if (mv.name === "strong") { handB = { x: x + face * (reach * 0.5), y: shoulder.y + 12 }; bendArmB = -6; } }
    }
    const hipFinal = { x: hip.x, y: hip.y };
    return { hip: hipFinal, chest: { x: chest.x, y: chest.y }, head, shoulder, footF, footB, handF, handB, bendLegF, bendLegB, bendArmF, bendArmB };
  }
}
