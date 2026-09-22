// Node-side TypeSafe JEV client. Uses the global fetch (Node >= 18), no SDK
// dependency, and speaks the exact /v1/systemone contract verified against the
// live API. The API key is read from the environment and NEVER leaves the server.

const ENDPOINT = "https://api.typesafe.ai/v1/systemone";

export function makeJeClient(env = process.env) {
  const key = env.TYPESAFE_API_KEY;
  const model = env.TYPESAFE_MODEL || "jev-latest";
  if (!key) throw new Error("TYPESAFE_API_KEY is not set");

  return async function systemOne({ state, questions, timeoutMs = 8000 }) {
    const ctrl = new AbortController();
    const to = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(ENDPOINT, {
        method: "POST",
        signal: ctrl.signal,
        headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
        body: JSON.stringify({ state, model, questions }),
      });
      if (!res.ok) {
        const body = await res.text().catch(() => "");
        throw new Error(`JEV ${res.status}: ${body.slice(0, 200)}`);
      }
      const json = await res.json();
      return json.answers || {};
    } finally {
      clearTimeout(to);
    }
  };
}

// A decider that builds the questions itself from a persona and forwards the
// snapshot. Reused by the server and the headless runner so both send the same
// bundle (keeps the dual-JEV comparison honest).
import { buildQuestions } from "./questions.js";

export function makeLiveDecider(client) {
  return (state, questions) => client({ state, questions });
}

export function personaDecider(client) {
  // server signature: ({state, persona}) -> answers  (questions built centrally)
  return async ({ state, persona }) => {
    const questions = buildQuestions(persona);
    return client({ state, questions });
  };
}
