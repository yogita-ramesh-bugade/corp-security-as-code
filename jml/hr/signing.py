"""Webhook signatures shared by the mock HR system (sender) and its receivers (Step 3.2 engine).

Header format (the same idea Stripe and GitHub use):
    X-HR-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of "<t>.<raw body>">

- The HMAC proves the message came from someone who knows the shared secret (HR).
- Signing the timestamp too means an old captured message can't be replayed later:
  receivers reject anything older than MAX_AGE_SECONDS.
- Receivers must check the signature against the RAW body bytes, before parsing JSON.
"""
from __future__ import annotations

import hashlib
import hmac
import time

MAX_AGE_SECONDS = 300


def sign(secret: str, body: bytes, timestamp: int | None = None) -> str:
    t = int(time.time()) if timestamp is None else timestamp
    mac = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def verify(secret: str, body: bytes, header: str, now: int | None = None) -> tuple[bool, str]:
    """Return (ok, reason). Constant-time comparison; rejects old or malformed signatures."""
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        t, given = int(parts["t"]), parts["v1"]
    except (ValueError, KeyError):
        return False, "malformed signature header"
    now = int(time.time()) if now is None else now
    if abs(now - t) > MAX_AGE_SECONDS:
        return False, f"timestamp too old or in the future ({now - t}s)"
    expected = sign(secret, body, t).split("v1=", 1)[1]
    if not hmac.compare_digest(expected, given):
        return False, "signature does not match"
    return True, "ok"
