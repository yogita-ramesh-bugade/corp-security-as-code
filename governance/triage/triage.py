"""Triage one queued item: ask the model, check its answer, apply code guards (Project 4, Step 4.4).

The result is a RECOMMENDATION only. Nothing here changes access or writes a decision; the
reviewer's click in Mattermost (server.py) is what gets recorded.
"""
from __future__ import annotations

from governance.record import now_iso
from governance.triage import prompt
from governance.triage.backends import SCHEMA, Backend, validate_recommendation

APPROVE_LIMIT = 60  # the model may not recommend approve at or above this risk score


def guard(model: dict, item: dict, injection: list[str]) -> tuple[str, list[str]]:
    """Code-level rules on top of the model. Returns (recommendation, notes)."""
    rec, notes = model["decision"], []
    if injection:
        notes.append("item text contains instruction-like text aimed at reviewers (possible prompt injection)")
        if rec == "approve":
            rec = "escalate"
            notes.append("model said approve despite injection-like text: changed to escalate")
    if rec == "approve" and item["risk"]["score"] >= APPROVE_LIMIT:
        rec = "escalate"
        notes.append(f"model said approve for a {item['risk']['level']}-risk item (score {item['risk']['score']}): "
                     "changed to escalate")
    return rec, notes


def triage_item(item: dict, backend: Backend, naive: bool = False) -> dict:
    system, user, nonce = prompt.build_naive(item) if naive else prompt.build(item)
    injection = prompt.scan_for_injection(item)
    try:
        raw = backend.complete(system, user, SCHEMA)
        model, problem = validate_recommendation(raw)
    except Exception as e:  # noqa: BLE001 - a broken model answer must not stop the queue
        model, problem = None, f"{type(e).__name__}: {str(e)[:150]}"
    if model is None:
        model = {"decision": "escalate", "risk_factors": [], "rationale": f"Model answer unusable ({problem}).",
                 "confidence": 0.0}
    rec, notes = guard(model, item, injection) if not naive else (model["decision"], [])
    if problem:
        notes.append(f"model answer rejected: {problem}")
    return {"id": item["id"], "name": item["name"], "item_type": item["item_type"], "score": item["risk"]["score"],
            "level": item["risk"]["level"], "backend": backend.name, "naive": naive, "model": model,
            "recommendation": rec, "guard_notes": notes, "injection": injection, "at": now_iso()}
