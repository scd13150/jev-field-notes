// Zero-dependency Node server.
//
//  - serves the browser game from /public
//  - POST /api/jev  -> forwards {state, persona} to TypeSafe with the SERVER-SIDE
//    API key and returns the answers. The key never reaches the browser, which is
//    the credential-handling guidance in the skill.
//  - GET  /api/config -> which personas exist + whether a real key is present.
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { buildQuestions, PERSONAS } from "../src/jev/questions.js";
import { makeJeClient } from "../src/jev/client.js";

const ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)), "..");
const PORT = Number(process.env.PORT || 8787);
const HAS_KEY = Boolean(process.env.TYPESAFE_API_KEY);
const client = HAS_KEY ? makeJeClient() : null;

const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };

function send(res, code, body, type = "application/json") {
  res.writeHead(code, { "Content-Type": type, "Access-Control-Allow-Origin": "*" });
  res.end(typeof body === "string" || Buffer.isBuffer(body) ? body : JSON.stringify(body));
}
function readJson(req) {
  return new Promise((res, rej) => {
    let data = "";
    req.on("data", (c) => { data += c; if (data.length > 1e6) rej(new Error("too big")); });
    req.on("end", () => { try { res(data ? JSON.parse(data) : {}); } catch (e) { rej(e); } });
    req.on("error", rej);
  });
}

async function serveStatic(res, urlPath) {
  let rel = urlPath === "/" ? "/public/index.html" : urlPath;
  rel = normalize(decodeURIComponent(rel)).replace(/^(\.\.[\/\\])+/, "");
  const file = join(ROOT, rel);
  if (!file.startsWith(ROOT)) return send(res, 403, { error: "forbidden" });
  try {
    const info = await stat(file);
    if (info.isDirectory()) throw new Error("dir");
    const buf = await readFile(file);
    send(res, 200, buf, MIME[extname(file)] || "application/octet-stream");
  } catch {
    send(res, 404, "not found", "text/plain");
  }
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
  try {
    if (req.method === "OPTIONS") return send(res, 204, "");
    if (url.pathname === "/api/config") {
      return send(res, 200, { has_key: HAS_KEY, model: process.env.TYPESAFE_MODEL || "jev-latest", personas: Object.keys(PERSONAS) });
    }
    if (url.pathname === "/api/jev" && req.method === "POST") {
      if (!client) return send(res, 503, { error: "no TYPESAFE_API_KEY on server" });
      const { state, persona } = await readJson(req);
      const questions = buildQuestions(persona || "balanced"); // built server-side so the prompt is centralised
      const answers = await client({ state, questions });
      return send(res, 200, { answers });
    }
    return serveStatic(res, url.pathname);
  } catch (err) {
    return send(res, 500, { error: String(err && err.message || err) });
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`stick-figure-jev server on http://127.0.0.1:${PORT}`);
  console.log(`  JEV key present: ${HAS_KEY ? "yes -> /api/jev is LIVE" : "NO -> browser falls back to the mock brain"}`);
  console.log(`  personas: ${Object.keys(PERSONAS).join(", ")}`);
});
