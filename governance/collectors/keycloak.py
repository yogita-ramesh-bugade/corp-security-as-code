"""Keycloak collectors: OAuth grants (user consents to third-party apps) and admin roles.

Signs in as the read-only `governance-collector` service account (view-users, view-clients,
view-realm and query-* roles in realm lumen only).
"""
from __future__ import annotations

import os
import time

import httpx

from governance.record import Item, ms_to_iso

PRIVILEGED_GROUPS = {"it-admins", "break-glass"}


class Keycloak:
    def __init__(self, url=None, realm="lumen", client_id="governance-collector", secret=None):
        self.url = (url or os.environ.get("KC_URL", "http://keycloak.lumen.test:8081")).rstrip("/")
        self.realm, self.client_id = realm, client_id
        self.secret = secret if secret is not None else os.environ.get("KC_COLLECTOR_SECRET", "")
        self._tok, self._exp = None, 0.0

    def get(self, path, **params):
        if not self._tok or time.time() > self._exp - 30:
            r = httpx.post(f"{self.url}/realms/{self.realm}/protocol/openid-connect/token", timeout=10, data={
                "grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.secret})
            r.raise_for_status()
            self._tok, self._exp = r.json()["access_token"], time.time() + r.json()["expires_in"]
        r = httpx.get(f"{self.url}/admin/realms/{self.realm}{path}", params=params, timeout=15,
                      headers={"Authorization": f"Bearer {self._tok}"})
        r.raise_for_status()
        return r.json()


def collect_oauth_grants(kc: Keycloak) -> list[Item]:
    clients = {c["clientId"]: c for c in kc.get("/clients", max=1000)}
    grants: dict[str, dict] = {}
    for u in kc.get("/users", max=10000, briefRepresentation="true"):
        for c in kc.get(f"/users/{u['id']}/consents"):
            g = grants.setdefault(c["clientId"], {"users": [], "scopes": set(), "first": [], "last": []})
            g["users"].append(u["username"])
            g["scopes"] |= set(c.get("grantedClientScopes") or [])
            g["first"].append(c.get("createdDate"))
            g["last"].append(c.get("lastUpdatedDate"))
    items = []
    for client_id, g in grants.items():
        c = clients.get(client_id, {})
        # Description: first line "Publisher: <name>", then the app's own text (written by the publisher).
        first, _, about = (c.get("description") or "").partition("\n")
        publisher = first.split("Publisher:", 1)[1].strip() if first.startswith("Publisher:") else None
        items.append(Item(
            item_type="oauth_grant", id=f"oauth_grant:keycloak:{client_id}", name=c.get("name") or client_id,
            publisher=publisher, scopes=list(g["scopes"]), users=len(g["users"]),
            first_seen=ms_to_iso(min(x for x in g["first"] if x) if any(g["first"]) else None),
            last_used=ms_to_iso(max(x for x in g["last"] if x) if any(g["last"]) else None),
            owner=None,  # a third-party app consented to by employees has no internal owner by default
            source="keycloak", details={"client_id": client_id, "consented_by": sorted(g["users"]),
                                         "description": about.strip()}))
    return items


def collect_admin_roles(kc: Keycloak) -> list[Item]:
    """People and service accounts holding admin-level access in Keycloak."""
    holders: dict[str, dict] = {}

    def add(username, role, kind):
        h = holders.setdefault(username, {"roles": set(), "kind": kind})
        h["roles"].add(role)

    for g in kc.get("/groups", max=1000, briefRepresentation="true"):
        if g["name"] in PRIVILEGED_GROUPS:
            for m in kc.get(f"/groups/{g['id']}/members", max=1000, briefRepresentation="true"):
                add(m["username"], f"group:{g['name']}", "person")
    rm = next(c for c in kc.get("/clients", clientId="realm-management"))
    for role in kc.get(f"/clients/{rm['id']}/roles"):
        if not role["name"].startswith(("manage-", "realm-admin", "create-client", "impersonation")):
            continue  # view-*/query-* are read-only
        for u in kc.get(f"/clients/{rm['id']}/roles/{role['name']}/users", max=1000):
            kind = "service_account" if u["username"].startswith("service-account-") else "person"
            add(u["username"], f"realm-management:{role['name']}", kind)
    return [Item(item_type="admin_role", id=f"admin_role:keycloak:{name}", name=name,
                 publisher="internal", scopes=sorted(h["roles"]), users=1, first_seen=None, last_used=None,
                 owner=None if h["kind"] == "service_account" else f"{name}@lumenai.test",
                 source="keycloak", details={"holder_kind": h["kind"]})
            for name, h in holders.items()]
