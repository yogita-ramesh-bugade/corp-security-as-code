"""Lab only: make test users approve fake third-party apps, the way a real person would.

Keycloak has no API to create a consent (on purpose), so this logs each test user in and
clicks "Yes" on the consent screen through the normal browser flow. Run once after
`terraform apply` created the apps:

    KC_URL=http://keycloak.lumen.test:8081 LAB_USER_PASSWORD='<TF_VAR_test_user_password>' \
        python -m governance.lab.seed_consents
"""
from __future__ import annotations

import html
import os
import re
from urllib.parse import urlencode

import httpx

PLAN = {  # who approves what (alice and bob fall for the risky ones, as real people do)
    "alice": ["meetsync", "mailmerge-pro", "free-pdf-converter", "ai-notes-assistant"],
    "bob": ["meetsync", "teampulse", "ai-notes-assistant", "free-pdf-converter", "quicknotes-ai"],
    "ivan": ["directorysync-admin", "cloudbackup-plus"],
    "tara": ["quicksign-docs", "ai-notes-assistant", "meetsync", "quicknotes-ai"],
}
SCOPES = {
    "meetsync": "calendar.read", "teampulse": "", "quicksign-docs": "files.read",
    "mailmerge-pro": "mail.read mail.send", "cloudbackup-plus": "files.readwrite offline_access",
    "ai-notes-assistant": "mail.read calendar.read files.read offline_access",
    "free-pdf-converter": "files.readwrite mail.read offline_access",
    "directorysync-admin": "admin.directory offline_access",
    "quicknotes-ai": "files.read calendar.read",
}
REDIRECT = "http://localhost:9/callback"


def form_action(page: str, form_id: str) -> str | None:
    m = re.search(rf'<form[^>]*id="{form_id}"[^>]*action="([^"]+)"', page) or \
        re.search(rf'<form[^>]*action="([^"]+)"[^>]*id="{form_id}"', page)
    return html.unescape(m.group(1)) if m else None


def consent(kc: str, user: str, password: str, client: str, session: httpx.Client, scope: str | None = None) -> str:
    scope = SCOPES[client] if scope is None else scope
    q = urlencode({"client_id": client, "response_type": "code", "redirect_uri": REDIRECT,
                   "scope": f"openid profile email {scope}".strip(), "state": "lab"})
    r = session.get(f"{kc}/realms/lumen/protocol/openid-connect/auth?{q}")
    if r.status_code == 200 and (action := form_action(r.text, "kc-form-login")):
        r = session.post(action, data={"username": user, "password": password, "credentialId": ""})
    for _ in range(4):
        if r.status_code in (302, 303) and r.headers.get("location", "").startswith(REDIRECT):
            return "consented"
        if r.status_code in (302, 303):
            r = session.get(r.headers["location"])
            continue
        m = re.search(r'<form[^>]*action="([^"]*login-actions/consent[^"]*)"', r.text)
        if m:  # the consent screen: send back its hidden fields plus "accept"
            hidden = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', r.text))
            action = html.unescape(m.group(1))
            r = session.post(action if action.startswith("http") else kc + action, data={**hidden, "accept": "Yes"})
            continue
        if "kc-form-login" in r.text:
            return "login failed (wrong password?)"
        return f"stopped at HTTP {r.status_code} (required actions pending?)"
    return "gave up"


def main() -> None:
    kc = os.environ.get("KC_URL", "http://keycloak.lumen.test:8081").rstrip("/")
    password = os.environ["LAB_USER_PASSWORD"]
    for user, apps in PLAN.items():
        with httpx.Client(follow_redirects=False, timeout=15) as s:  # one browser session per user
            for app in apps:
                print(f"{user:6} -> {app:22} {consent(kc, user, password, app, s)}")


if __name__ == "__main__":
    main()
