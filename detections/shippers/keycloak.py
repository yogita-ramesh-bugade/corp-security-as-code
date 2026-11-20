"""Keycloak user and admin events -> ~/lab-data/logs/keycloak.jsonl (Project 4, Step 4.6).

Reads the realm's event store (turned on in Terraform: keycloak_realm_events) with the read-only
governance-collector account (needs view-events). Adds what a detection needs but the raw event
doesn't carry:
  - consent events: the app's age (from the admin event that created it), whether it asks for
    high-risk scopes, its publisher;
  - logins: the user's groups (so break-glass sign-ins can be spotted);
  - admin events that add someone to it-admins/break-glass or give realm-management manage-*
    roles: an extra admin_role_granted event, marked inside or outside a change window.
Apps registered before event logging was on have no CREATE event, so they get no age and never
count as "new".
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone

from detections.shippers.common import Sink, admin_grant, from_ms, iso, parse

HIGH_RISK_SCOPES = {"mail.read", "mail.send", "files.readwrite", "admin.directory"}
PRIVILEGED_GROUPS = {"it-admins", "break-glass"}
PRIVILEGED_ROLE_PREFIXES = ("manage-", "realm-admin", "impersonation", "create-client")


class KeycloakShipper:
    def __init__(self, kc, sink: Sink, now=lambda: datetime.now(timezone.utc)):
        self.kc, self.sink, self.now = kc, sink, now
        self._users: dict[str, dict] = {}
        self._clients: dict[str, dict] = {}
        st = self.sink.state
        st.setdefault("client_created", {})

    # ------------------------------------------------------------ lookups (cached per run)
    def user(self, user_id: str | None) -> dict:
        if not user_id:
            return {}
        if user_id not in self._users:
            try:
                u = self.kc.get(f"/users/{user_id}")
                groups = [g["name"] for g in self.kc.get(f"/users/{user_id}/groups")]
                self._users[user_id] = {"username": u.get("username"), "groups": groups}
            except Exception:  # noqa: BLE001 - deleted users still have events
                self._users[user_id] = {"username": None, "groups": []}
        return self._users[user_id]

    def client(self, client_id: str | None) -> dict:
        if not client_id:
            return {}
        if client_id not in self._clients:
            found = self.kc.get("/clients", clientId=client_id)
            info = {"id": client_id}
            if found:
                c = found[0]
                scopes = {s["name"] for s in self.kc.get(f"/clients/{c['id']}/optional-client-scopes")} | \
                         {s["name"] for s in self.kc.get(f"/clients/{c['id']}/default-client-scopes")}
                first = (c.get("description") or "").split("\n", 1)[0]
                info.update(name=c.get("name"), risky_scopes=sorted(scopes & HIGH_RISK_SCOPES),
                            high_risk=bool(scopes & HIGH_RISK_SCOPES),
                            publisher=first.split("Publisher:", 1)[1].strip() if first.startswith("Publisher:") else None)
            created = self.sink.state["client_created"].get(client_id)
            if created:
                info["created"] = created
            self._clients[client_id] = info
        return self._clients[client_id]

    # ------------------------------------------------------------ normalize
    def user_event(self, e: dict) -> dict:
        when = from_ms(e["time"])
        u = self.user(e.get("userId"))
        details = e.get("details") or {}
        out = {"@timestamp": iso(when),
               "event": {"dataset": "lumen.keycloak", "action": e["type"], "kind": "event",
                         "outcome": "failure" if e.get("error") else "success"},
               "user": {"id": e.get("userId"), "name": details.get("username") or u.get("username")},
               "source": {"ip": e.get("ipAddress")},
               "keycloak": {"realm": e.get("realmId"), "details": details, "error": e.get("error"),
                            "user": {"groups": u.get("groups", [])}}}
        if e.get("clientId"):
            c = dict(self.client(e["clientId"]))
            created = c.pop("created", None)
            if created:
                c["age_hours"] = round((when - parse(created)).total_seconds() / 3600, 2)
            out["keycloak"]["client"] = c
        return out

    def admin_events(self, e: dict) -> list[dict]:
        when = from_ms(e["time"])
        auth = e.get("authDetails") or {}
        actor = self.user(auth.get("userId")).get("username") or auth.get("userId")
        rtype, op, path = e.get("resourceType"), e.get("operationType"), e.get("resourcePath") or ""
        try:
            rep = json.loads(e["representation"]) if e.get("representation") else None
        except ValueError:
            rep = None
        base = {"@timestamp": iso(when),
                "event": {"dataset": "lumen.keycloak", "action": f"admin_{rtype}_{op}".lower(), "kind": "event",
                          "outcome": "failure" if e.get("error") else "success"},
                "user": {"name": actor}, "source": {"ip": auth.get("ipAddress")},
                "keycloak": {"admin": {"resource_type": rtype, "operation": op, "resource_path": path}}}
        out = [base]
        # remember when apps are registered: that's what makes a client "new"
        if rtype == "CLIENT" and op == "CREATE" and isinstance(rep, dict) and rep.get("clientId"):
            self.sink.state["client_created"][rep["clientId"]] = iso(when)
            self._clients.pop(rep["clientId"], None)
        target_id = path.split("/")[1] if path.startswith("users/") and len(path.split("/")) > 1 else None
        target = self.user(target_id).get("username") if target_id else None
        if op == "CREATE" and rtype == "GROUP_MEMBERSHIP" and isinstance(rep, dict) and rep.get("name") in PRIVILEGED_GROUPS:
            out.append(admin_grant(when, "keycloak", f"group:{rep['name']}", target, actor))
        if op == "CREATE" and rtype == "CLIENT_ROLE_MAPPING" and isinstance(rep, list):
            for role in rep:
                if str(role.get("name", "")).startswith(PRIVILEGED_ROLE_PREFIXES):
                    out.append(admin_grant(when, "keycloak", f"realm-management:{role['name']}", target, actor))
        return out

    # ------------------------------------------------------------ poll
    @staticmethod
    def _key(prefix: str, e: dict) -> str:
        return prefix + (e.get("id") or hashlib.sha256(json.dumps(e, sort_keys=True).encode()).hexdigest()[:24])

    def poll(self) -> int:
        since = (self.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        admin = sorted(self.kc.get("/admin-events", dateFrom=since, max=5000), key=lambda e: e["time"])
        user = sorted(self.kc.get("/events", dateFrom=since, max=5000), key=lambda e: e["time"])
        out = []
        for e in admin:  # admin first: a client created a second before its first consent must be known
            if not self.sink.seen(self._key("a:", e)):
                out += self.admin_events(e)
        for e in user:
            if not self.sink.seen(self._key("u:", e)):
                out.append(self.user_event(e))
        out.sort(key=lambda x: x["@timestamp"])
        self.sink.write(out)
        self.sink.save()
        return len(out)


def make(log_dir=None, state_dir=None):
    from governance.collectors.keycloak import Keycloak
    return KeycloakShipper(Keycloak(), Sink("keycloak", log_dir, state_dir))


if __name__ == "__main__":
    s = make()
    while True:
        print(f"keycloak: {s.poll()} events", flush=True)
        time.sleep(30)
