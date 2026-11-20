"""Detection tests (Project 4, Step 4.6): every rule fires on its "fire" samples and stays quiet
on its "quiet" samples, the shippers produce logs the rules actually match, and every rule
converts to a Kibana rule.  python -m pytest detections -q"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from detections import deploy, sigma_eval
from detections.shippers import common, fleet, keycloak, mattermost

HERE = Path(__file__).resolve().parent
PIPE = sigma_eval.Pipeline()
RULES = sigma_eval.load_rules()
TESTS = {p.stem: yaml.safe_load(p.read_text()) for p in (HERE / "tests").glob("*.yml")}


def fires(stem: str, events: list[dict]) -> bool:
    docs = RULES[stem]
    corr = [d for d in docs if "correlation" in d]
    if corr:
        base = next(d for d in docs if d.get("name") == corr[0]["correlation"]["rules"][0])
        return bool(sigma_eval.correlation_fires(corr[0], base, events, PIPE))
    return any(sigma_eval.match_rule(docs[0], e, PIPE) for e in events)


def test_every_rule_has_samples_and_every_sample_file_has_a_rule():
    assert set(RULES) == set(TESTS)


@pytest.mark.parametrize("stem", sorted(RULES))
def test_rule_fires_on_bad_and_stays_quiet_on_good(stem):
    t = TESTS[stem]
    if any("correlation" in d for d in RULES[stem]):
        assert fires(stem, t["fire"]), "the batch should trigger"
        assert not fires(stem, t["quiet"]), "the batch should not trigger"
    else:
        for e in t["fire"]:
            assert fires(stem, [e]), f"should fire: {json.dumps(e)[:150]}"
        for e in t["quiet"]:
            assert not fires(stem, [e]), f"should stay quiet: {json.dumps(e)[:150]}"


def test_every_rule_field_is_mapped():
    for stem, docs in RULES.items():
        for d in docs:
            for name, sel in (d.get("detection") or {}).items():
                if name != "condition":
                    for key in sel:
                        assert key.split("|")[0] in PIPE.mapping, f"{stem}: {key} missing from pipeline.yml"


def test_conversion_gives_kibana_rules():
    rules = {r["_source_file"]: r for r in deploy.build_rules()}
    assert len(rules) == 5  # the correlation's base rule doesn't alert on its own
    q = rules["keycloak_consent_new_risky_client.yml"]["query"]
    assert q.startswith("event.dataset:lumen.keycloak AND") and "keycloak.details.consent:consent_granted" in q
    t = rules["consent_phishing.yml"]
    assert t["type"] == "threshold" and t["from"] == "now-60m"
    assert t["threshold"] == {"field": ["keycloak.client.id"], "value": 1,
                              "cardinality": [{"field": "user.name", "value": 5}]}
    assert all(r["index"] == ["lumen-logs-*"] and r["interval"] == "1m" for r in rules.values())


# ------------------------------------------------------------------ shippers -> rules, end to end

NOW = datetime(2026, 11, 19, 15, 30, tzinfo=timezone.utc)  # a Thursday, 10:30 in New York


def ms(dt):
    return int(dt.timestamp() * 1000)


class FakeKC:
    def __init__(self):
        self.clients = [{"id": "c-old", "clientId": "mailmerge-pro", "description": "Publisher: MergeWorks\nBulk mail"}]
        self.scopes = {"c-old": ["mail.read", "mail.send"], "c-new": ["mail.read", "files.readwrite"]}
        self.admin, self.events = [], []
        self.users = {f"u{i}": f"sim-user-{i:02d}" for i in range(1, 11)} | {"u-erin": "erin", "u-admin": "admin"}
        self.groups = {"u-erin": ["break-glass"]}

    def get(self, path, **params):
        if path == "/clients":
            cs = self.clients if "clientId" not in params else [c for c in self.clients if c["clientId"] == params["clientId"]]
            return cs
        if path.endswith("/optional-client-scopes"):
            return [{"name": s} for s in self.scopes[path.split("/")[2]]]
        if path.endswith("/default-client-scopes"):
            return [{"name": "profile"}]
        if path == "/admin-events":
            return self.admin
        if path == "/events":
            return self.events
        if path.endswith("/groups"):
            return [{"name": g} for g in self.groups.get(path.split("/")[2], [])]
        if path.startswith("/users/"):
            return {"username": self.users[path.split("/")[2]]}
        raise AssertionError(path)


def kc_shipper(tmp_path, kc, now=NOW):
    return keycloak.KeycloakShipper(kc, common.Sink("keycloak", tmp_path / "logs", tmp_path / "state"), now=lambda: now)


def logged(tmp_path, source):
    return [json.loads(line) for line in (tmp_path / "logs" / f"{source}.jsonl").read_text().splitlines()]


def test_consent_phishing_from_raw_keycloak_events(tmp_path):
    kc = FakeKC()
    s = kc_shipper(tmp_path, kc)
    s.poll()  # mailmerge-pro was registered before logging started: no age, never "new"
    created = NOW - timedelta(minutes=20)
    kc.clients.append({"id": "c-new", "clientId": "sim-phish-1", "description": "Publisher: unknown (x.example)\nFree AI"})
    kc.admin = [{"id": "a1", "time": ms(created), "operationType": "CREATE", "resourceType": "CLIENT",
                 "resourcePath": "clients/c-new", "representation": json.dumps({"clientId": "sim-phish-1"}),
                 "authDetails": {"userId": "u-admin"}}]
    # what Keycloak really logs for a consent during sign-in (seen in the lab): LOGIN + details.consent
    kc.events = [{"id": f"e{i}", "time": ms(created + timedelta(minutes=2 + i)), "type": "LOGIN",
                  "clientId": "sim-phish-1", "userId": f"u{i}", "details": {"consent": "consent_granted"}}
                 for i in range(1, 11)]
    kc.events.append({"id": "old", "time": ms(created), "type": "LOGIN", "clientId": "mailmerge-pro",
                      "userId": "u1", "details": {"consent": "consent_granted"}})
    s.poll()
    logs = logged(tmp_path, "keycloak")
    consents = [e for e in logs if (e.get("keycloak") or {}).get("details", {}).get("consent") == "consent_granted"]
    new = [e for e in consents if e["keycloak"]["client"]["id"] == "sim-phish-1"]
    assert new[0]["keycloak"]["client"]["age_hours"] == pytest.approx(0.05, abs=0.01)
    assert new[0]["keycloak"]["client"]["publisher"] == "unknown (x.example)"
    assert all(fires("keycloak_consent_new_risky_client", [e]) for e in new)
    old = next(e for e in consents if e["keycloak"]["client"]["id"] == "mailmerge-pro")
    assert "age_hours" not in old["keycloak"]["client"] and not fires("keycloak_consent_new_risky_client", [old])
    assert fires("consent_phishing", logs)
    s.poll()  # nothing new: nothing written twice
    assert len(logged(tmp_path, "keycloak")) == len(logs)


def test_keycloak_admin_grant_at_night_and_break_glass_login(tmp_path):
    kc = FakeKC()
    sunday_night = datetime(2026, 11, 22, 7, 13, tzinfo=timezone.utc)  # 02:13 in New York
    kc.admin = [{"id": "g1", "time": ms(sunday_night), "operationType": "CREATE", "resourceType": "GROUP_MEMBERSHIP",
                 "resourcePath": "users/u3/groups/g-it", "representation": json.dumps({"name": "it-admins"}),
                 "authDetails": {"userId": "u-admin"}}]
    kc.events = [{"id": "l1", "time": ms(sunday_night), "type": "LOGIN", "clientId": "mailmerge-pro", "userId": "u-erin",
                  "details": {"username": "erin"}}]
    kc_shipper(tmp_path, kc).poll()
    logs = logged(tmp_path, "keycloak")
    grant = next(e for e in logs if e["event"]["action"] == "admin_role_granted")
    assert grant["user"] == {"name": "admin", "target": {"name": "sim-user-03"}}
    assert grant["lumen"] == {"admin": {"system": "keycloak", "role": "group:it-admins"}, "change_window": False}
    assert fires("admin_role_outside_change_window", [grant])
    assert fires("break_glass_access", [e for e in logs if e["event"]["action"] == "LOGIN"])


def test_change_window_follows_new_york_time():
    assert common.in_change_window(datetime(2026, 11, 24, 20, 0, tzinfo=timezone.utc))      # Tue 15:00 EST
    assert not common.in_change_window(datetime(2026, 11, 24, 22, 0, tzinfo=timezone.utc))  # Tue 17:00 EST
    assert common.in_change_window(datetime(2026, 7, 7, 19, 30, tzinfo=timezone.utc))       # Tue 15:30 EDT
    assert not common.in_change_window(datetime(2026, 11, 25, 20, 0, tzinfo=timezone.utc))  # Wednesday


class FakeFleet:
    def __init__(self):
        self.santa = "pass"
        self.acts = []

    def get(self, path, **params):
        if path == "/hosts":
            return {"hosts": [{"id": 1}]}
        if path == "/hosts/1":
            return {"host": {"id": 1, "hostname": "fleet-macos-lab", "hardware_serial": "Z1", "platform": "darwin",
                             "policies": [{"name": "Santa in Lockdown mode", "response": self.santa},
                                          {"name": "FileVault on", "response": "pass"}]}}
        if path == "/activities":
            return {"activities": self.acts}
        raise AssertionError(path)


def test_santa_flip_from_pass_to_fail(tmp_path):
    f = FakeFleet()
    s = fleet.FleetShipper(f, common.Sink("fleet", tmp_path / "logs", tmp_path / "state"), now=lambda: NOW)
    s.poll()
    first = logged(tmp_path, "fleet")
    assert {e["event"]["action"] for e in first} == {"posture_check_observed"}
    assert not fires("posture_check_regression", first)
    f.santa = "fail"
    s.poll()
    flips = logged(tmp_path, "fleet")[len(first):]
    assert [e["lumen"]["posture"] for e in flips] == [{"check": "santa_lockdown", "previous": "pass", "current": "fail"}]
    assert fires("posture_check_regression", flips)


def test_fleet_role_change_in_a_change_window_is_quiet(tmp_path):
    f = FakeFleet()
    f.acts = [{"id": 7, "created_at": "2026-11-24T20:00:00Z", "type": "changed_user_global_role",
               "actor_email": "admin@lumenai.test", "details": {"user_email": "ivan@lumenai.test", "role": "maintainer"}},
              {"id": 8, "created_at": "2026-11-24T20:01:00Z", "type": "changed_user_global_role",
               "actor_email": "admin@lumenai.test", "details": {"user_email": "maya@lumenai.test", "role": "observer"}}]
    out = fleet.FleetShipper(f, common.Sink("fleet", tmp_path / "logs", tmp_path / "state"), now=lambda: NOW).activities()
    grants = [e for e in out if e["event"]["action"] == "admin_role_granted"]
    assert len(grants) == 1 and grants[0]["lumen"]["change_window"] is True  # observer isn't an admin role
    assert not fires("admin_role_outside_change_window", grants)


def test_mattermost_system_admin_grant(tmp_path):
    class MM:
        def get(self, path, **params):
            if path == "/audits":
                return [{"id": "x1", "create_at": ms(datetime(2026, 11, 22, 7, 0, tzinfo=timezone.utc)),
                         "user_id": "a", "action": "/api/v4/users/b/roles", "extra_info": "roles=system_user system_admin"}]
            return {"username": {"a": "lumenadmin", "b": "omar"}[path.split("/")[2]]}
    mattermost.MattermostShipper(MM(), common.Sink("mattermost", tmp_path / "logs", tmp_path / "state")).poll()
    grant = next(e for e in logged(tmp_path, "mattermost") if e["event"]["action"] == "admin_role_granted")
    assert grant["user"]["target"]["name"] == "omar" and fires("admin_role_outside_change_window", [grant])


def test_simulation_only_touches_sim_objects():
    import importlib.util
    spec = importlib.util.spec_from_file_location("sim", HERE.parent / "scripts" / "simulate_consent_phishing.py")
    sim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sim)

    class FakeAdmin:
        def __init__(self):
            self.calls = []

        def r(self, method, path, ok=None, **kw):
            self.calls.append((method, path, kw.get("json")))

        def get(self, path, **params):
            return {"/clients": [{"id": "1", "clientId": "sim-phish-202611191500"}, {"id": "2", "clientId": "meetsync"}],
                    "/users": [{"id": "u1", "username": "sim-user-01"}, {"id": "u2", "username": "alice"}],
                    "/client-scopes": [{"name": "mail.read", "id": "s1"}, {"name": "files.readwrite", "id": "s2"}]}[path]

    a = FakeAdmin()
    sim.create_app(a, "sim-phish-202611191500")
    body = a.calls[0][2]
    assert body["consentRequired"] and body["description"].startswith("Publisher: unknown")
    assert [c[1] for c in a.calls[1:]] == ["/clients/1/optional-client-scopes/s1", "/clients/1/optional-client-scopes/s2"]
    a.calls.clear()
    sim.cleanup(a)
    assert a.calls == [("DELETE", "/clients/1", None), ("DELETE", "/users/u1", None)]  # never meetsync or alice
