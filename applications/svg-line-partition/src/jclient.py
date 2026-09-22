"""TypeSafe System One client: retries, disk cache, request batching.

HTTP contract as verified against the live service:
  POST https://api.typesafe.ai/v1/systemone
  Authorization: Bearer $TYPESAFE_API_KEY
  body {state, model, questions} -> {model, answers:{id: {...}}, usage}

Retries follow the docs' guidance for 429/529 (exponential backoff, honour
`retry-after`). The cache is what makes repeated probing cheap: one key per
(model, state, questions) so a re-run of the analysis costs nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
# pinned, not `jev-latest`: confidence thresholds tuned here must not move when
# the alias does (docs: Models -> Aliases)
DEFAULT_MODEL = "jev-1.13.0"


class JevError(RuntimeError):
    pass


@dataclass
class Call:
    answers: dict[str, Any]
    model: str
    input_tokens: int
    output_tokens: int
    seconds: float
    cached: bool
    question_count: int


@dataclass
class JevClient:
    model: str = DEFAULT_MODEL
    cache_dir: Path | None = None
    timeout: float = 180.0
    max_attempts: int = 6
    max_questions_per_call: int = 140
    calls: list[Call] = field(default_factory=list)
    key: str = field(default="", repr=False)

    def __post_init__(self):
        self.key = self.key or os.environ.get("TYPESAFE_API_KEY", "")
        if not self.key:
            raise JevError("TYPESAFE_API_KEY is not set")
        if self.cache_dir:
            Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    def _digest(self, state: Any, questions: dict[str, Any]) -> str:
        blob = json.dumps([self.model, state, questions], sort_keys=True,
                          separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]

    def ask(self, state: Any, questions: dict[str, Any], tag: str = "") -> dict[str, Any]:
        """Answer every question about one state; batching stays inside the
        token budget because questions over one state are independent."""
        ids = list(questions)
        chunks = [ids[i:i + self.max_questions_per_call] for i in
                  range(0, len(ids), self.max_questions_per_call)]
        out: dict[str, Any] = {}
        for n, chunk in enumerate(chunks):
            sub = {k: questions[k] for k in chunk}
            out.update(self._ask_one(state, sub, f"{tag}#b{n}"))
        return out

    def _ask_one(self, state: Any, questions: dict[str, Any], tag: str) -> dict[str, Any]:
        digest = self._digest(state, questions)
        path = Path(self.cache_dir) / f"{digest}.json" if self.cache_dir else None
        if path and path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            # the served latency was recorded when the answer was first fetched;
            # keeping it means a cached re-run still reports real API time,
            # while `wall` below stays the time this run actually waited.
            call = Call(payload["answers"], payload.get("model", "?"),
                        payload["usage"]["input_tokens"], payload["usage"]["output_tokens"],
                        float(payload.get("seconds", 0.0)), True, len(questions))
            self.calls.append(call)
            return payload["answers"]

        body = json.dumps({"state": state, "model": self.model,
                           "questions": questions}).encode("utf-8")
        wait = 1.0
        last = ""
        for attempt in range(self.max_attempts):
            req = urllib.request.Request(
                ENDPOINT, data=body, method="POST",
                headers={"Authorization": f"Bearer {self.key}",
                         "Content-Type": "application/json"})
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    raw = json.loads(r.read().decode("utf-8"))
                secs = time.time() - t0
                usage = raw.get("usage", {})
                call = Call(raw["answers"], raw.get("model", self.model),
                            usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                            secs, False, len(questions))
                self.calls.append(call)
                if path:
                    path.write_text(json.dumps(
                        {"tag": tag, "model": raw.get("model"), "usage": usage,
                         "answers": raw["answers"], "seconds": round(secs, 2),
                         "questions": len(questions)},
                        indent=1, ensure_ascii=False), encoding="utf-8")
                return raw["answers"]
            except urllib.error.HTTPError as exc:
                last = f"{exc.code} {exc.read()[:300]!r}"
                if exc.code in (429, 529) or exc.code >= 500:
                    retry_after = exc.headers.get("retry-after") if exc.headers else None
                    time.sleep(float(retry_after) if retry_after else wait)
                    wait = min(wait * 2.3, 40)
                    continue
                raise JevError(f"{tag}: HTTP {last}") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = repr(exc)
                time.sleep(wait)
                wait = min(wait * 2.3, 40)
                continue
        raise JevError(f"{tag}: exhausted retries after {self.max_attempts} attempts: {last}")


def estimate_tokens(*objs: Any) -> int:
    return sum(len(json.dumps(o, separators=(",", ":"))) for o in objs) // 4
