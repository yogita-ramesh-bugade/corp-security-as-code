"""Mattermost review channel: post queued items with the model's recommendation and buttons.

Everything shown is made safe for chat first: item text and even the model's rationale (which
may repeat injected text) can't @-mention people, add links or break out of the table.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re

import httpx

COLORS = {"approve": "#3db887", "deny": "#d24b4e", "escalate": "#e0a030"}


class Chat:
    def __init__(self, url=None, token=None, team="lumen", channel="governance-review"):
        self.url = (url or os.environ.get("MM_URL", "http://chat.lumen.test:8065")).rstrip("/")
        self.h = {"Authorization": f"Bearer {token or os.environ.get('MM_TRIAGE_TOKEN', '')}"}
        self.team, self.channel, self._cid = team, channel, None

    def _r(self, method, path, **kw):
        r = httpx.request(method, f"{self.url}/api/v4{path}", headers=self.h, timeout=15, **kw)
        r.raise_for_status()
        return r.json() if r.content else {}

    def channel_id(self):
        if not self._cid:
            self._cid = self._r("GET", f"/teams/name/{self.team}/channels/name/{self.channel}")["id"]
        return self._cid

    def post(self, attachment: dict) -> str:
        return self._r("POST", "/posts", json={"channel_id": self.channel_id(), "message": "",
                                               "props": {"attachments": [attachment]}})["id"]

    def username(self, user_id: str) -> str:
        return self._r("GET", f"/users/{user_id}")["username"]


def sign(secret: str, *parts: str) -> str:
    return hmac.new(secret.encode(), "|".join(parts).encode(), hashlib.sha256).hexdigest()


def safe(text, limit=300) -> str:
    """One line of untrusted text, safe inside a Mattermost markdown table."""
    s = str(text if text is not None else "")
    s = s.replace("@", "@\u200b")                     # no @channel / @all / @someone pings
    s = re.sub(r"[`|\[\]<>*_~#]", " ", s)              # no code, table breaks, links, formatting
    s = re.sub(r"https?://", "hxxp://", s)             # links shown, not clickable
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit] + ("…" if len(s) > limit else "")


def attachment(item: dict, tri: dict, action_url: str, secret: str, signature: str) -> dict:
    m = tri["model"]
    desc = (item.get("details") or {}).get("description")
    rows = [
        ("Type", item["item_type"]), ("Publisher", item.get("publisher") or "unknown"),
        ("Owner", item.get("owner") or "nobody"), ("Users", item.get("users")),
        ("Scopes", ", ".join(item.get("scopes") or []) or "none"),
        ("Risk score", f"{item['risk']['score']}/100 ({item['risk']['level']})"),
        ("Policy", item["decision"]["why"]),
    ]
    text = "| | |\n|---|---|\n" + "\n".join(f"| {k} | {safe(v)} |" for k, v in rows)
    text += (f"\n\n**Model ({safe(tri['backend'], 40)}) recommends: {tri['recommendation'].upper()}** "
             f"(model said {m['decision']}, confidence {m['confidence']})\n> {safe(m['rationale'], 500)}")
    if m["risk_factors"]:
        text += "\n" + "\n".join(f"- {safe(f, 120)}" for f in m["risk_factors"])
    for note in tri["guard_notes"]:
        text += f"\n\n:warning: {safe(note, 200)}"
    if desc:
        text += f"\n\n**Publisher's description (untrusted):** {safe(desc, 400)}"
    text += "\n\n_The model only recommends. Your click is the decision._"

    def button(decision, label, style):
        return {"id": decision, "name": label, "style": style, "type": "button",
                "integration": {"url": action_url, "context": {
                    "item_id": item["id"], "decision": decision, "sig": sign(secret, item["id"], decision, signature)}}}

    return {"fallback": f"Review: {safe(item['name'], 80)}", "color": COLORS[tri["recommendation"]],
            "title": f"Review: {safe(item['name'], 80)}", "text": text,
            "actions": [button("approve", "Approve", "good"), button("deny", "Deny", "danger")]}
