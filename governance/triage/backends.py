"""Model backends for triage (Project 4, Step 4.4).

The triage code only talks to `Backend.complete(system, user, schema) -> dict`. Ollama is the
first implementation; a Claude backend later only has to implement the same method, and
`python -m governance.triage.run --backend claude` can run side by side with the local model.
"""
from __future__ import annotations

import json
import os

import httpx

# What the model must answer. Ollama enforces this through its `format` field; we still
# validate the result ourselves (validate_recommendation), because a schema is a strong hint to
# the model, not a guarantee about what reaches our code.
SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["approve", "deny", "escalate"]},
        "risk_factors": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "rationale": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["decision", "risk_factors", "rationale", "confidence"],
}


class Backend:
    name = "base"

    def complete(self, system: str, user: str, schema: dict) -> dict:
        raise NotImplementedError


class OllamaBackend(Backend):
    """Local model through Ollama's /api/chat with structured output (format = JSON schema)."""

    def __init__(self, model: str | None = None, url: str | None = None, timeout: float = 180):
        self.model = model or os.environ.get("OLLAMA_MODEL", "llama3.1")
        self.url = (url or os.environ.get("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        self.timeout = timeout
        self.name = f"ollama:{self.model}"

    def complete(self, system: str, user: str, schema: dict) -> dict:
        r = httpx.post(f"{self.url}/api/chat", timeout=self.timeout, json={
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            "options": {"temperature": 0},  # same item -> same answer, as far as the model allows
        })
        r.raise_for_status()
        return json.loads(r.json()["message"]["content"])


class FixedBackend(Backend):
    """Always gives the same answer. For tests and for trying the Mattermost flow without a model."""

    def __init__(self, answer: dict | None = None):
        self.answer = answer or {"decision": "escalate", "risk_factors": ["no model: fixed answer"],
                                 "rationale": "Fixed backend; no model was asked.", "confidence": 0.0}
        self.name = "fixed"
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, schema: dict) -> dict:
        self.calls.append((system, user))
        return dict(self.answer)


def get_backend(name: str, model: str | None = None) -> Backend:
    if name == "ollama":
        return OllamaBackend(model)
    if name == "fixed":
        return FixedBackend()
    raise SystemExit(f"unknown backend '{name}' (have: ollama, fixed; a claude backend can be added in backends.py)")


def validate_recommendation(raw) -> tuple[dict | None, str | None]:
    """Check the model's answer against SCHEMA. Returns (clean answer, None) or (None, problem)."""
    if not isinstance(raw, dict):
        return None, "answer is not a JSON object"
    missing = [k for k in SCHEMA["required"] if k not in raw]
    if missing:
        return None, f"missing {missing}"
    if raw["decision"] not in SCHEMA["properties"]["decision"]["enum"]:
        return None, f"decision {raw['decision']!r} is not approve/deny/escalate"
    if not isinstance(raw["risk_factors"], list) or not all(isinstance(x, str) for x in raw["risk_factors"]):
        return None, "risk_factors is not a list of text"
    if not isinstance(raw["rationale"], str):
        return None, "rationale is not text"
    try:
        conf = float(raw["confidence"])
    except (TypeError, ValueError):
        return None, "confidence is not a number"
    if not 0 <= conf <= 1:
        return None, f"confidence {conf} is outside 0..1"
    return {"decision": raw["decision"], "risk_factors": [x[:120] for x in raw["risk_factors"][:6]],
            "rationale": raw["rationale"][:500], "confidence": round(conf, 2)}, None
