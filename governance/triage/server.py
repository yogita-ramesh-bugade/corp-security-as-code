"""Receives the Approve / Deny clicks from the Mattermost review channel (Project 4, Step 4.4).

    uvicorn governance.triage.server:app --host 127.0.0.1 --port 8300

A click is accepted only if:
  - the button's signature checks out (the HMAC was made by run.py with TRIAGE_SECRET),
  - the person clicking is a named reviewer (REVIEWERS, Mattermost usernames),
  - the item still looks the way it did when it was posted (same scopes and publisher).
Then it is recorded twice: as a human decision (reviews/decisions.jsonl, which policy uses)
and as a label next to the model's recommendation (reviews/triage_labels.jsonl).
"""
from __future__ import annotations

import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request

from governance import decide, score
from governance.triage.chat import Chat, safe, sign

HERE = Path(__file__).resolve().parent.parent
app = FastAPI(title="Governance review buttons")


def settings():
    return {
        "secret": os.environ.get("TRIAGE_SECRET", ""),
        "reviewers": {u.strip() for u in os.environ.get("REVIEWERS", "").split(",") if u.strip()},
        "decisions": Path(os.environ.get("DECISIONS_FILE", HERE / "out" / "decisions.jsonl")),
        "triage": Path(os.environ.get("TRIAGE_FILE", HERE / "out" / "triage.jsonl")),
        "reviews": Path(os.environ.get("REVIEWS_FILE", HERE / "reviews" / "decisions.jsonl")),
        "labels": Path(os.environ.get("LABELS_FILE", HERE / "reviews" / "triage_labels.jsonl")),
    }


CHAT = None


def chat():
    global CHAT
    CHAT = CHAT or Chat()
    return CHAT


def _latest(path: Path, item_id: str) -> dict | None:
    found = None
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and json.loads(line)["id"] == item_id:
                found = json.loads(line)
    return found


def handle(payload: dict, cfg: dict, username_of, now=None) -> dict:
    ctx = payload.get("context") or {}
    item_id, choice = str(ctx.get("item_id", "")), str(ctx.get("decision", ""))
    if not cfg["secret"] or choice not in ("approve", "deny"):
        return {"ephemeral_text": "This button isn't valid."}
    item = _latest(cfg["decisions"], item_id)
    if not item:
        return {"ephemeral_text": "That item is no longer in the inventory. Re-run collect, decide and triage."}
    rules = score.load_rules()
    if not hmac.compare_digest(str(ctx.get("sig", "")), sign(cfg["secret"], item_id, choice, decide.signature(item, rules))):
        return {"ephemeral_text": "This item changed since it was posted (or the button was forged). Re-run triage."}
    who = username_of(payload.get("user_id", ""))
    if who not in cfg["reviewers"]:
        return {"ephemeral_text": f"Only reviewers ({', '.join(sorted(cfg['reviewers']))}) can decide."}
    now = now or datetime.now(timezone.utc)
    tri = _latest(cfg["triage"], item_id) or {}
    model = tri.get("model") or {}
    reason = (f"via Mattermost; model ({tri.get('backend', '?')}) recommended {tri.get('recommendation', '?')}"
              f" at confidence {model.get('confidence', '?')}")
    decide.record_review(cfg["reviews"], item, choice, reason, who, now, rules)
    label = {"id": item_id, "name": item["name"], "item_type": item["item_type"], "score": item["risk"]["score"],
             "human": choice, "reviewer": who, "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
             "backend": tri.get("backend"), "model_decision": model.get("decision"),
             "recommendation": tri.get("recommendation"), "confidence": model.get("confidence"),
             "agreed": tri.get("recommendation") == choice, "injection": bool(tri.get("injection"))}
    cfg["labels"].parent.mkdir(parents=True, exist_ok=True)
    with open(cfg["labels"], "a") as f:
        f.write(json.dumps(label, sort_keys=True) + "\n")
    verdict = "Approved" if choice == "approve" else "Denied"
    return {"update": {"message": f"**{verdict}** by @{who} at {label['at']}: {safe(item['name'], 80)} "
                                  f"(model recommended {tri.get('recommendation', '?')})",
                       "props": {}}}


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/mm/action")
async def action(request: Request):
    return handle(await request.json(), settings(), lambda uid: chat().username(uid))
