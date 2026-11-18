"""Lumen AI posture gate (Project 2, Step 2.4).

Pomerium sends every request here instead of straight to the app. For each request the gate:
  1. verifies Pomerium's signed identity token (X-Pomerium-Jwt-Assertion) against
     Pomerium's published signing keys (JWKS),
  2. reads the device serial Pomerium took from the device certificate (X-Lumen-Device-Serial),
  3. looks the device up in Fleet: health-check results and the user it's assigned to,
  4. asks OPA for a decision (cached for CACHE_SECONDS), then either forwards the request
     to the real app or shows a "blocked" page with what to fix.

Facts live here; rules live in access-gate/policy/access.rego.

Lab helpers (run inside the container):
  python app.py inspect <serial> [--email you@lumenai.test] [--app admin-console]
  python app.py backdate <serial> <check> <hours>     # pretend a check started failing earlier
"""
from __future__ import annotations

import html
import json
import os
import sys
import threading
import time
from pathlib import Path

import httpx
import jwt
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from starlette.concurrency import run_in_threadpool

# ---------------------------------------------------------------- configuration

FLEET_URL = os.environ.get("FLEET_URL", "").rstrip("/")
FLEET_API_TOKEN = os.environ.get("FLEET_API_TOKEN", "")
OPA_URL = os.environ.get("OPA_URL", "http://opa:8181").rstrip("/")
JWKS_URL = os.environ.get("JWKS_URL", "https://auth.lumen.test:4443/.well-known/pomerium/jwks.json")
CA_BUNDLE = os.environ.get("CA_BUNDLE", "/ca/lumen-ca-bundle.pem")
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
CACHE_SECONDS = int(os.environ.get("CACHE_SECONDS", "60"))
CHECKS = yaml.safe_load(Path(os.environ.get("CHECKS_FILE", Path(__file__).with_name("checks.yaml"))).read_text())["checks"]

# app name (set by Pomerium in X-Lumen-App) -> where the real app lives, and the
# audience Pomerium puts in that route's identity token
APPS = {
    "wiki": {"upstream": os.environ.get("UPSTREAM_WIKI", "http://wiki:80"), "audience": "wiki.lumen.test"},
    "admin-console": {"upstream": os.environ.get("UPSTREAM_ADMIN", "http://admin-console:80"), "audience": "admin.lumen.test"},
}

REASON_TEXT = {
    "device_not_managed": "This device isn't enrolled in Lumen's device management.",
    "device_not_assigned_to_you": "This device isn't assigned to you.",
    "missing_group": "Your account doesn't have the role this app requires.",
    "device_unhealthy": "This device is failing a security check this app requires.",
    "unknown_app": "This app isn't configured in the access policy.",
}

DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "failing_since.json"
_state_lock = threading.Lock()
_cache: dict[tuple, tuple[float, dict]] = {}
_jwks: dict = {"fetched": 0.0, "keys": None}


def log_event(kind: str, event: dict) -> None:
    """Append one JSON line per decision/alert (Project 4 ships these to the SIEM)."""
    line = json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "kind": kind, **event})
    print(line, flush=True)
    with open(DATA_DIR / f"{kind}s.jsonl", "a") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------- 1. identity

def _tls_verify():
    return CA_BUNDLE if Path(CA_BUNDLE).exists() else True


def signing_keys(force: bool = False) -> jwt.PyJWKSet:
    if force or _jwks["keys"] is None or time.time() - _jwks["fetched"] > 300:
        r = httpx.get(JWKS_URL, verify=_tls_verify(), timeout=5)
        r.raise_for_status()
        _jwks.update(keys=jwt.PyJWKSet.from_dict(r.json()), fetched=time.time())
    return _jwks["keys"]


def verify_identity(token: str, audience: str) -> dict:
    """Return the token's claims, or raise if it isn't a valid Pomerium token for this app."""
    kid = jwt.get_unverified_header(token).get("kid")
    for force in (False, True):  # refetch once in case Pomerium rotated its key
        keys = signing_keys(force)
        key = next((k for k in keys.keys if k.key_id == kid), None)
        if key:
            return jwt.decode(token, key.key, algorithms=["ES256"], audience=audience,
                              issuer=audience, leeway=30)
    raise jwt.InvalidTokenError(f"unknown signing key {kid}")


# ---------------------------------------------------------------- 3. device facts

def fleet_get(path: str, **params) -> httpx.Response:
    return httpx.get(f"{FLEET_URL}{path}", params=params, timeout=10,
                     headers={"Authorization": f"Bearer {FLEET_API_TOKEN}"})


def owner_email(host: dict) -> str:
    for user in host.get("end_users") or []:
        for e in user.get("other_emails") or []:
            if e.get("source") == "custom" and e.get("email"):
                return e["email"]
        if user.get("idp_username"):
            return user["idp_username"]
    r = fleet_get(f"/api/v1/fleet/hosts/{host['id']}/device_mapping")  # older Fleet versions
    if r.status_code == 200:
        for m in r.json().get("device_mapping") or []:
            if m.get("email"):
                return m["email"]
    return ""


def check_results(policies: list[dict]) -> tuple[dict, dict]:
    """Map Fleet policy results onto our four checks. Returns (results, matched policy names)."""
    results, matched = {}, {}
    for check, spec in CHECKS.items():
        words = [w.lower() for w in spec["match"]]
        hits = [p for p in policies if any(w in p.get("name", "").lower() for w in words)]
        matched[check] = [f"{p['name']} = {p.get('response') or 'no result yet'}" for p in hits]
        responses = [p.get("response") for p in hits]
        if any(r == "fail" for r in responses):
            results[check] = "fail"
        elif hits and all(r == "pass" for r in responses):
            results[check] = "pass"
        else:
            results[check] = "missing"
    return results, matched


def update_failing_since(serial: str, results: dict, now_ns: int) -> dict:
    """Remember when the gate first saw each check failing (Fleet only reports the current result)."""
    with _state_lock:
        state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
        device = state.setdefault(serial, {})
        for check, result in results.items():
            if result == "pass":
                device.pop(check, None)
            else:
                device.setdefault(check, now_ns)
        STATE_FILE.write_text(json.dumps(state, indent=1))
        return dict(device)


def device_facts(serial: str, now_ns: int) -> tuple[dict, dict]:
    if not serial:
        return {}, {}
    r = fleet_get(f"/api/v1/fleet/hosts/identifier/{serial}", exclude_software="true")
    if r.status_code == 404:
        return {}, {}
    r.raise_for_status()
    host = r.json()["host"]
    results, matched = check_results(host.get("policies") or [])
    facts = {
        "serial": serial,
        "hostname": host.get("hostname", ""),
        "platform": host.get("platform", ""),
        "owner_email": owner_email(host),
        "policies": results,
        "failing_since": update_failing_since(serial, results, now_ns),
    }
    return facts, matched


# ---------------------------------------------------------------- 4. decision

def decide(app_name: str, claims: dict, serial: str) -> dict:
    key = (claims.get("email", ""), serial, app_name)
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    now_ns = time.time_ns()
    device, _ = device_facts(serial, now_ns)
    opa_input = {
        "app": app_name,
        "now_ns": now_ns,
        "user": {"email": claims.get("email", ""), "groups": claims.get("groups") or []},
        "device": device,
    }
    r = httpx.post(f"{OPA_URL}/v1/data/access/decision", json={"input": opa_input}, timeout=5)
    r.raise_for_status()
    decision = r.json().get("result") or {"allow": False, "reasons": ["policy_error"]}
    decision["device"] = device
    _cache[key] = (time.time() + CACHE_SECONDS, decision)

    log_event("decision", {"user": opa_input["user"]["email"], "app": app_name, "serial": serial,
                           "allow": decision.get("allow"), "level": decision.get("level"),
                           "reasons": decision.get("reasons"), "warnings": decision.get("warnings")})
    for alert in decision.get("alerts") or []:
        log_event("alert", alert)
    return decision


# ---------------------------------------------------------------- web app

app = FastAPI(title="Lumen posture gate", docs_url=None, redoc_url=None, openapi_url=None)
HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade",
              "proxy-authorization", "proxy-authenticate", "host", "content-length", "content-encoding"}


@app.get("/_gate/health")
def health():
    return {"status": "ok"}


def blocked_page(status: int, title: str, decision: dict | None = None, detail: str = "") -> HTMLResponse:
    items = ""
    if decision:
        for reason in sorted(decision.get("reasons") or []):
            items += f"<li>{html.escape(REASON_TEXT.get(reason, reason))}</li>"
        fixes = "".join(f"<li><b>{html.escape(c)}</b>: {html.escape(CHECKS.get(c, {}).get('fix', ''))}</li>"
                        for c in sorted(decision.get("remediation") or []))
        if fixes:
            items += f"</ul><h2>How to fix it</h2><ul>{fixes}"
    device = (decision or {}).get("device") or {}
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:640px;margin:48px auto;padding:0 16px;color:#1d1d1f}}
h1{{color:#b42318}}.meta{{color:#666;font-size:14px}}</style></head><body>
<h1>{html.escape(title)}</h1><ul>{items}</ul>{f'<p>{html.escape(detail)}</p>' if detail else ''}
<p class="meta">Device: {html.escape(device.get('serial', 'unknown'))} &middot; Access level {(decision or {}).get('level', 0)}
of {(decision or {}).get('required_level', '?')} required. Once fixed, try again in about a minute.</p>
<p class="meta">Need an exception? <a href="https://github.com/yogita-ramesh-bugade/corp-security-as-code/blob/main/docs/request-access.md">Request access</a></p>
</body></html>"""
    return HTMLResponse(page, status_code=status)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def gate(path: str, request: Request):
    app_name = request.headers.get("x-lumen-app", "")
    target = APPS.get(app_name)
    if not target:
        return blocked_page(403, "Access blocked", detail="Unknown app.")

    # 1. who
    try:
        claims = await run_in_threadpool(verify_identity, request.headers.get("x-pomerium-jwt-assertion", ""), target["audience"])
    except Exception as e:  # noqa: BLE001 - any failure means "not proven"
        log_event("decision", {"app": app_name, "allow": False, "reasons": ["invalid_identity_token"], "error": str(e)})
        return blocked_page(401, "Access blocked", detail="Your sign-in couldn't be verified. Reload the page to sign in again.")

    # 2. which device  3. its health  4. the rules
    serial = request.headers.get("x-lumen-device-serial", "")
    try:
        decision = await run_in_threadpool(decide, app_name, claims, serial)
    except Exception as e:  # noqa: BLE001 - fail closed if Fleet or OPA is down
        log_event("decision", {"user": claims.get("email"), "app": app_name, "allow": False,
                               "reasons": ["gate_error"], "error": str(e)})
        return blocked_page(503, "Access temporarily unavailable",
                            detail="The access check couldn't reach device management. Break-glass accounts still work.")

    if not decision.get("allow"):
        return blocked_page(403, "Access blocked", decision)

    # allowed: forward to the real app
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
    headers["X-Lumen-Access-Level"] = str(decision.get("level"))
    async with httpx.AsyncClient(timeout=30) as client:
        upstream = await client.request(request.method, f"{target['upstream']}/{path}",
                                        params=request.query_params, headers=headers,
                                        content=await request.body())
    body = upstream.content
    out_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in HOP_BY_HOP}
    warnings = decision.get("warnings") or []
    if warnings:
        out_headers["X-Lumen-Warning"] = " | ".join(warnings)[:500]
        ctype = upstream.headers.get("content-type", "")
        if ctype.startswith("text/html"):
            banner = ("<div style='background:#fef0c7;padding:12px;font-family:system-ui'><b>Warning:</b> "
                      + html.escape(" ".join(warnings)) + "</div>").encode()
            body = body.replace(b"<body>", b"<body>" + banner, 1) if b"<body>" in body else banner + body
        elif ctype.startswith("text/"):
            body = ("WARNING: " + " ".join(warnings) + "\n\n").encode() + body
    return Response(body, status_code=upstream.status_code, headers=out_headers)


# ---------------------------------------------------------------- lab helpers

def _cli(argv: list[str]) -> None:
    if len(argv) >= 2 and argv[0] == "inspect":
        serial = argv[1]
        email = argv[argv.index("--email") + 1] if "--email" in argv else None
        app_name = argv[argv.index("--app") + 1] if "--app" in argv else "admin-console"
        facts, matched = device_facts(serial, time.time_ns())
        print(json.dumps({"device": facts, "matched_fleet_policies": matched}, indent=2))
        if email:
            groups = argv[argv.index("--groups") + 1].split(",") if "--groups" in argv else []
            r = httpx.post(f"{OPA_URL}/v1/data/access/decision", json={"input": {
                "app": app_name, "now_ns": time.time_ns(),
                "user": {"email": email, "groups": groups}, "device": facts}})
            print(json.dumps({"opa_decision": r.json().get("result")}, indent=2))
    elif len(argv) == 4 and argv[0] == "backdate":
        serial, check, hours = argv[1], argv[2], float(argv[3])
        with _state_lock:
            state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
            state.setdefault(serial, {})[check] = time.time_ns() - int(hours * 3600 * 1e9)
            STATE_FILE.write_text(json.dumps(state, indent=1))
        print(f"{serial}: {check} now counts as failing for {hours} hours")
    else:
        print(__doc__)


if __name__ == "__main__":
    _cli(sys.argv[1:])
