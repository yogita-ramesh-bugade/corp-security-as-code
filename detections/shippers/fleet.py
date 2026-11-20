"""Fleet policy results and activities -> ~/lab-data/logs/fleet.jsonl (Project 4, Step 4.6).

  - Policy results: Fleet only reports each policy's current pass/fail, so this shipper keeps the
    last result per laptop and check (mapped with the posture gate's own checks.yaml) and logs a
    posture_check_changed event when it flips. The first sighting is logged as
    posture_check_observed (no previous result, so it can't trigger the pass->fail rule).
  - Activities (Fleet's audit feed): every entry is shipped; a user getting the global role
    admin, maintainer or gitops also becomes an admin_role_granted event.
Uses the read-only observer token (FLEET_COLLECTOR_TOKEN). If observers can't read
activities in your Fleet version, that part is skipped and reported.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from detections.shippers.common import Sink, admin_grant, iso, parse

CHECKS_FILE = Path(__file__).resolve().parents[2] / "access-gate" / "gate" / "checks.yaml"
WATCHED = ("disk_encrypted", "os_current", "firewall_on", "santa_lockdown")
ADMIN_ROLES = {"admin", "maintainer", "gitops"}


def load_checks(path: Path = CHECKS_FILE) -> dict[str, list[str]]:
    checks = yaml.safe_load(Path(path).read_text())["checks"]
    return {name: [w.lower() for w in spec["match"]] for name, spec in checks.items() if name in WATCHED}


def check_results(policies: list[dict], checks: dict) -> dict[str, str]:
    """Same mapping as the posture gate: any matching policy failing = fail; all passing = pass."""
    out = {}
    for check, words in checks.items():
        hits = [p.get("response") for p in policies if any(w in p.get("name", "").lower() for w in words)]
        out[check] = "fail" if "fail" in hits else "pass" if hits and all(h == "pass" for h in hits) else "missing"
    return out


class FleetShipper:
    def __init__(self, fleet, sink: Sink, checks=None, now=lambda: datetime.now(timezone.utc)):
        self.fleet, self.sink, self.now = fleet, sink, now
        self.checks = checks or load_checks()
        self.skipped: list[str] = []

    def posture(self) -> list[dict]:
        out, last = [], self.sink.state.setdefault("posture", {})
        for h in self.fleet.get("/hosts", per_page=500)["hosts"]:
            host = self.fleet.get(f"/hosts/{h['id']}")["host"]
            results = check_results(host.get("policies") or [], self.checks)
            key = host.get("hardware_serial") or str(host["id"])
            prev = last.setdefault(key, {})
            for check, now_result in results.items():
                before = prev.get(check)
                if before == now_result:
                    continue
                prev[check] = now_result
                out.append({"@timestamp": iso(self.now()),
                            "event": {"dataset": "lumen.fleet", "kind": "state",
                                      "action": "posture_check_changed" if before else "posture_check_observed"},
                            "host": {"name": host.get("hostname"), "id": str(host["id"]), "serial": key,
                                     "os": {"platform": host.get("platform")}},
                            "lumen": {"posture": {"check": check, "previous": before, "current": now_result}}})
        return out

    def activities(self) -> list[dict]:
        try:
            acts = self.fleet.get("/activities", per_page=100, order_key="created_at", order_direction="desc")
        except Exception as e:  # noqa: BLE001
            self.skipped.append(f"activities ({type(e).__name__}: {str(e)[:80]})")
            return []
        out = []
        for a in sorted(acts.get("activities") or [], key=lambda a: a["created_at"]):
            if self.sink.seen(f"act:{a['id']}"):
                continue
            when, d = parse(a["created_at"]), a.get("details") or {}
            out.append({"@timestamp": iso(when),
                        "event": {"dataset": "lumen.fleet", "action": f"fleet_{a['type']}", "kind": "event"},
                        "user": {"name": a.get("actor_email") or a.get("actor_full_name")},
                        "fleet": {"activity": {"id": a["id"], "type": a["type"], "details": d}}})
            if a["type"] == "changed_user_global_role" and d.get("role") in ADMIN_ROLES:
                out.append(admin_grant(when, "fleet", f"fleet:{d['role']}", d.get("user_email"),
                                       a.get("actor_email") or a.get("actor_full_name")))
        return out

    def poll(self) -> int:
        out = self.posture() + self.activities()
        out.sort(key=lambda x: x["@timestamp"])
        self.sink.write(out)
        self.sink.save()
        return len(out)


def make(log_dir=None, state_dir=None):
    from governance.collectors.fleet import Fleet
    return FleetShipper(Fleet(), Sink("fleet", log_dir, state_dir))


if __name__ == "__main__":
    s = make()
    while True:
        print(f"fleet: {s.poll()} events {s.skipped or ''}", flush=True)
        time.sleep(30)
