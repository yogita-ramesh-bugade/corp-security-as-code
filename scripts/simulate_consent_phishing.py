"""Lab only: simulate a consent-phishing wave in Keycloak (Project 4, Step 4.6).

    source ~/access-gate-secrets/terraform.env          # KEYCLOAK_USER / KEYCLOAK_PASSWORD (master admin)
    python scripts/simulate_consent_phishing.py         # new risky app + 10 users approve it
    python scripts/simulate_consent_phishing.py --cleanup   # delete the sim apps and users

What it does, the way a real attack would look in the logs:
  1. registers a brand-new app "Free AI Mail Assistant" (unknown publisher, asks for mail.read
     and files.readwrite), as client sim-phish-<time>, in realm lumen;
  2. makes sure 10 test users sim-user-01..10 exist (random passwords, never printed);
  3. signs each one in and clicks "Yes" on the consent screen, a few seconds apart.
Keycloak then records one admin event (client created) and 10 GRANT_CONSENT events. The shipper
picks them up within 30 s, Filebeat ships them, and Kibana should raise:
  - "OAuth consent to a newly registered high-risk app" (once per consent), and
  - "Many users approving the same new app within an hour" (once) within about 5 minutes.
It only touches objects named sim-*, in realm lumen.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from governance.lab.seed_consents import consent  # noqa: E402

REALM = "lumen"
SCOPES = ["mail.read", "files.readwrite"]


class Admin:
    def __init__(self, url, user, password):
        self.url = url.rstrip("/")
        r = httpx.post(f"{self.url}/realms/master/protocol/openid-connect/token", timeout=15,
                       data={"grant_type": "password", "client_id": "admin-cli", "username": user, "password": password})
        r.raise_for_status()
        self.h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    def r(self, method, path, ok=(200, 201, 204), **kw):
        resp = httpx.request(method, f"{self.url}/admin/realms/{REALM}{path}", headers=self.h, timeout=15, **kw)
        if resp.status_code not in ok:
            raise RuntimeError(f"{method} {path}: HTTP {resp.status_code} {resp.text[:200]}")
        return resp

    def get(self, path, **params):
        return self.r("GET", path, params=params).json()


def create_app(a: Admin, client_id: str) -> None:
    a.r("POST", "/clients", json={
        "clientId": client_id, "name": "Free AI Mail Assistant", "enabled": True,
        "description": "Publisher: unknown (ai-mail-free.example)\nFree AI that reads and answers your email for you!",
        "protocol": "openid-connect", "publicClient": False, "standardFlowEnabled": True, "consentRequired": True,
        "redirectUris": ["http://localhost:9/callback"]})
    cid = a.get("/clients", clientId=client_id)[0]["id"]
    scope_ids = {s["name"]: s["id"] for s in a.get("/client-scopes")}
    for s in SCOPES:
        a.r("PUT", f"/clients/{cid}/optional-client-scopes/{scope_ids[s]}")


def ensure_user(a: Admin, n: int, password: str) -> str:
    name = f"sim-user-{n:02d}"
    rep = {"username": name, "email": f"{name}@lumenai.test", "firstName": "Sim", "lastName": f"User {n:02d}",
           "enabled": True, "emailVerified": True}
    a.r("POST", "/users", ok=(201, 409), json=rep)
    uid = a.get("/users", username=name, exact="true")[0]["id"]
    a.r("PUT", f"/users/{uid}/reset-password", json={"type": "password", "value": password, "temporary": False})
    return name


def cleanup(a: Admin) -> None:
    for c in a.get("/clients", max=1000):
        if c["clientId"].startswith("sim-phish-"):
            a.r("DELETE", f"/clients/{c['id']}")
            print(f"deleted app {c['clientId']}")
    for u in a.get("/users", search="sim-user-", max=100):
        if u["username"].startswith("sim-user-"):
            a.r("DELETE", f"/users/{u['id']}")
            print(f"deleted user {u['username']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=10)
    ap.add_argument("--gap", type=float, default=3.0, help="seconds between consents")
    ap.add_argument("--cleanup", action="store_true")
    a = ap.parse_args(argv)
    kc = os.environ.get("KC_URL", "http://keycloak.lumen.test:8081")
    admin = Admin(kc, os.environ["KEYCLOAK_USER"], os.environ["KEYCLOAK_PASSWORD"])
    if a.cleanup:
        cleanup(admin)
        return 0
    client_id = f"sim-phish-{datetime.now(timezone.utc):%Y%m%d%H%M}"
    create_app(admin, client_id)
    print(f"{datetime.now():%H:%M:%S}  registered {client_id} (asks for {', '.join(SCOPES)})")
    password = secrets.token_urlsafe(18)
    ok = 0
    for n in range(1, a.users + 1):
        user = ensure_user(admin, n, password)
        with httpx.Client(follow_redirects=False, timeout=15) as s:
            result = consent(kc, user, password, client_id, s, scope=" ".join(SCOPES))
        ok += result == "consented"
        print(f"{datetime.now():%H:%M:%S}  {user} -> {client_id}: {result}")
        time.sleep(a.gap)
    print(f"\n{ok}/{a.users} consented. Watch Kibana > Security > Alerts for the next 5 minutes.")
    print("Clean up afterwards: python scripts/simulate_consent_phishing.py --cleanup")
    return 0 if ok == a.users else 1


if __name__ == "__main__":
    sys.exit(main())
