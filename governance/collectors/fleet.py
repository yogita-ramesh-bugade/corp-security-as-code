"""Fleet collectors: browser extensions (osquery chrome_extensions, with permissions) and
Fleet users with admin rights.

Uses an API-only Fleet account with the global role observer (free tier; observer_plus needs
Fleet Premium). Observers can't run ad-hoc SQL, only saved queries marked observer_can_run, so
the extensions query lives in Fleet as "governance-browser-extensions"
(governance/lab/fleet-query.yml, applied once by an admin). The collector can't change
anything. Live queries only reach online hosts; offline hosts are listed in the run summary.
"""
from __future__ import annotations

import os

import httpx

from governance.record import Item

EXTENSIONS_SQL = (
    "SELECT u.username AS os_user, ce.name, ce.identifier, ce.version, ce.author, ce.permissions, "
    "ce.optional_permissions, ce.from_webstore, ce.browser_type "
    "FROM users u CROSS JOIN chrome_extensions ce USING (uid);"
)


QUERY_NAME = "governance-browser-extensions"


class Fleet:
    def __init__(self, url=None, token=None):
        self.url = (url or os.environ.get("FLEET_URL", "")).rstrip("/")
        self.h = {"Authorization": f"Bearer {token or os.environ.get('FLEET_COLLECTOR_TOKEN', '')}"}
        self.skipped: list[str] = []

    def get(self, path, **params):
        r = httpx.get(f"{self.url}/api/v1/fleet{path}", params=params, headers=self.h, timeout=20)
        r.raise_for_status()
        return r.json()

    def saved_query_id(self, name=QUERY_NAME):
        for q in self.get("/queries", query=name).get("queries") or []:
            if q["name"] == name:
                return q["id"]
        raise RuntimeError(f"saved query '{name}' not found: fleetctl apply -f governance/lab/fleet-query.yml")

    def run_saved(self, query_id, host_ids):
        """Run a saved query live on several hosts: {host_id: {"rows": [...], "error": ...}}."""
        r = httpx.post(f"{self.url}/api/v1/fleet/queries/{query_id}/run", json={"host_ids": host_ids},
                       headers=self.h, timeout=90)
        r.raise_for_status()
        return {res["host_id"]: res for res in r.json().get("results") or []}


def _split(perms):
    return [p.strip() for p in (perms or "").split(",") if p.strip()]


def collect_browser_extensions(fleet: Fleet) -> list[Item]:
    found: dict[str, dict] = {}
    qid = fleet.saved_query_id()
    online = []
    for host in fleet.get("/hosts", per_page=500)["hosts"]:
        if host.get("status") != "online":
            fleet.skipped.append(f"{host['hostname']} (offline)")
        else:
            online.append(host)
    results = fleet.run_saved(qid, [h["id"] for h in online]) if online else {}
    for host in online:
        res = results.get(host["id"])
        if res is None or res.get("error"):
            fleet.skipped.append(f"{host['hostname']} ({res.get('error') if res else 'no answer'})")
            continue
        for row in res.get("rows") or []:
            e = found.setdefault(row["identifier"], {"row": row, "installs": set(), "perms": set()})
            e["installs"].add(f"{host['hostname']}:{row.get('os_user')}")
            e["perms"] |= set(_split(row.get("permissions")))
    return [Item("browser_extension", f"browser_extension:chrome:{ext_id}", e["row"]["name"],
                 e["row"].get("author") or None, list(e["perms"]), len(e["installs"]), None, None, None, "fleet",
                 {"extension_id": ext_id, "version": e["row"].get("version"),
                  "from_webstore": e["row"].get("from_webstore"), "installed_on": sorted(e["installs"]),
                  "optional_permissions": _split(e["row"].get("optional_permissions"))})
            for ext_id, e in found.items()]


def collect_fleet_admins(fleet: Fleet) -> list[Item]:
    items = []
    for u in fleet.get("/users")["users"]:
        role = u.get("global_role")
        if role not in ("admin", "maintainer", "gitops"):
            continue
        items.append(Item("admin_role", f"admin_role:fleet:{u['email']}", u["name"] or u["email"], "internal",
                          [f"fleet:{role}"], 1, u.get("created_at"), None,
                          None if u.get("api_only") else u["email"], "fleet",
                          {"holder_kind": "api_only" if u.get("api_only") else "person"}))
    return items
