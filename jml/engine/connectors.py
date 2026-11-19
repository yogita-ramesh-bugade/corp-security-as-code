"""Connectors from the engine to real systems. Each has a fake twin in test_engine.py."""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

import httpx


class HRClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def get(self, emp_id: str) -> dict:
        r = httpx.get(f"{self.base}/employees/{emp_id}", timeout=10)
        r.raise_for_status()
        return r.json()

    def list_all(self) -> list[dict]:
        r = httpx.get(f"{self.base}/employees", timeout=10)
        r.raise_for_status()
        return r.json()


class KeycloakAdmin:
    """Keycloak admin REST API, as the engine's own service account (client credentials).
    The account can manage users and read groups in realm `lumen` only; nothing else."""

    def __init__(self, base_url: str, realm: str, client_id: str, client_secret: str):
        self.base, self.realm = base_url.rstrip("/"), realm
        self.client_id, self.client_secret = client_id, client_secret
        self._token, self._exp, self._groups = None, 0.0, None

    def _h(self) -> dict:
        if not self._token or time.time() > self._exp - 30:
            r = httpx.post(f"{self.base}/realms/{self.realm}/protocol/openid-connect/token", timeout=10,
                           data={"grant_type": "client_credentials", "client_id": self.client_id,
                                 "client_secret": self.client_secret})
            r.raise_for_status()
            self._token, self._exp = r.json()["access_token"], time.time() + r.json()["expires_in"]
        return {"Authorization": f"Bearer {self._token}"}

    def _req(self, method: str, path: str, **kw) -> httpx.Response:
        r = httpx.request(method, f"{self.base}/admin/realms/{self.realm}{path}", headers=self._h(), timeout=10, **kw)
        r.raise_for_status()
        return r

    def _group_ids(self) -> dict:
        if self._groups is None:
            self._groups = {g["name"]: g["id"] for g in
                            self._req("GET", "/groups", params={"max": 1000, "briefRepresentation": "true"}).json()}
        return self._groups

    def find_user(self, username):
        users = self._req("GET", "/users", params={"username": username, "exact": "true"}).json()
        return users[0] if users else None

    def list_users(self):
        return self._req("GET", "/users", params={"max": 10000}).json()

    def create_user(self, username, email, first, last, attributes, required_actions):
        self._req("POST", "/users", json={"username": username, "email": email, "firstName": first,
                                          "lastName": last, "enabled": True, "emailVerified": True,
                                          "attributes": attributes, "requiredActions": required_actions})

    def set_enabled(self, uid, enabled):
        self._req("PUT", f"/users/{uid}", json={"enabled": enabled})

    def set_required_actions(self, uid, actions):
        self._req("PUT", f"/users/{uid}", json={"requiredActions": actions})

    def credentials(self, uid):
        return self._req("GET", f"/users/{uid}/credentials").json()

    def delete_credential(self, uid, cred_id):
        self._req("DELETE", f"/users/{uid}/credentials/{cred_id}")

    def user_groups(self, uid):
        return [g["name"] for g in self._req("GET", f"/users/{uid}/groups").json()]

    def add_group(self, uid, name):
        self._req("PUT", f"/users/{uid}/groups/{self._group_ids()[name]}")

    def remove_group(self, uid, name):
        self._req("DELETE", f"/users/{uid}/groups/{self._group_ids()[name]}")

    def sessions(self, uid):
        return self._req("GET", f"/users/{uid}/sessions").json()

    def logout(self, uid):
        self._req("POST", f"/users/{uid}/logout")

    def consents(self, uid):
        return self._req("GET", f"/users/{uid}/consents").json()

    def revoke_consent(self, uid, client_id):
        self._req("DELETE", f"/users/{uid}/consents/{client_id}")


class FileChat:
    """Chat stand-in until Mattermost arrives (Step 3.4): keeps accounts, channels, tokens and
    direct messages in a JSON file so every action is visible and testable."""

    def __init__(self, path: Path):
        self.path, self.lock = Path(path), threading.Lock()

    def _load(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {"users": {}, "messages": []}

    def _save(self, s):
        self.path.write_text(json.dumps(s, indent=1))

    def ensure_user(self, username, email, name) -> bool:
        with self.lock:
            s = self._load()
            u = s["users"].get(username)
            if u and u["active"]:
                return False
            s["users"][username] = {**(u or {"channels": [], "tokens": []}), "email": email, "name": name, "active": True}
            self._save(s)
            return True

    def is_active(self, username):
        return self._load()["users"].get(username, {}).get("active", False)

    def channels(self, username):
        return self._load()["users"].get(username, {}).get("channels", [])

    def _edit(self, username, fn):
        with self.lock:
            s = self._load()
            fn(s["users"][username])
            self._save(s)

    def join(self, username, ch):
        self._edit(username, lambda u: u["channels"].append(ch))

    def leave(self, username, ch):
        self._edit(username, lambda u: u["channels"].remove(ch))

    def deactivate(self, username):
        self._edit(username, lambda u: u.update(active=False))

    def revoke_tokens(self, username) -> int:
        u = self._load()["users"].get(username)
        if not u or not u.get("tokens"):
            return 0
        n = len(u["tokens"])
        self._edit(username, lambda x: x.update(tokens=[]))
        return n

    def send_dm(self, to_email, text):
        with self.lock:
            s = self._load()
            s["messages"].append({"to": to_email, "text": text, "time": time.strftime("%Y-%m-%dT%H:%M:%SZ")})
            self._save(s)


class FleetClient:
    """Fleet human-device mapping. Locking needs Fleet Premium, so the free tier files a ticket."""

    def __init__(self, url: str, token: str, can_lock: bool = False):
        self.url, self.token, self._can_lock = url.rstrip("/"), token, can_lock

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"}

    def _host(self, serial):
        r = httpx.get(f"{self.url}/api/v1/fleet/hosts/identifier/{serial}", headers=self._h(), timeout=10,
                      params={"exclude_software": "true"})
        r.raise_for_status()
        return r.json()["host"]

    def owner(self, serial):
        for u in self._host(serial).get("end_users") or []:
            for e in u.get("other_emails") or []:
                if e.get("source") == "custom":
                    return e["email"]
        return None

    def set_owner(self, serial, email):
        host_id = self._host(serial)["id"]
        httpx.put(f"{self.url}/api/v1/fleet/hosts/{host_id}/device_mapping", headers=self._h(), timeout=10,
                  json={"email": email}).raise_for_status()

    def can_lock(self):
        return self._can_lock

    def lock(self, serial):
        host_id = self._host(serial)["id"]
        httpx.post(f"{self.url}/api/v1/fleet/hosts/{host_id}/lock", headers=self._h(), timeout=30).raise_for_status()


class FileTickets:
    """Stand-in for the IT ticket queue."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def file(self, title, **fields) -> str:
        tid = f"IT-{uuid.uuid4().hex[:6].upper()}"
        with open(self.path, "a") as f:
            f.write(json.dumps({"id": tid, "title": title, **fields, "time": time.strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n")
        return tid
