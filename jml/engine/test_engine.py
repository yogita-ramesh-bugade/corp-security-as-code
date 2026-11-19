"""The ugly cases (Step 3.3 check). Run:  cd jml/engine && python -m pytest -v

Every outside system is a fake that keeps state in memory and can be told to fail on a
given call, so "Keycloak dies halfway" is a one-line setup.
"""
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent), str(HERE.parent / "hr")]

from core import Audit, Engine, Store, iso  # noqa: E402
from rules import load_rules  # noqa: E402

RULES = load_rules(check_terraform=False)


class Clock:
    def __init__(self):
        self.now = datetime(2026, 12, 1, 9, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


class FakeHR:
    def __init__(self, clock):
        self.people, self.clock, self.n = {}, clock, 0

    def get(self, emp_id):
        return dict(self.people[emp_id])

    def list_all(self):
        return [dict(p) for p in self.people.values()]

    def _event(self, kind, emp, **extra):
        return {"id": f"evt_{uuid.uuid4().hex}", "type": kind, "occurred_at": iso(self.clock()),
                "data": {"employee": dict(emp), **extra}}

    def hire(self, name, dept, title, kind="full_time", end_date=None, manager="mgr@lumenai.test"):
        self.n += 1
        emp = {"id": f"E{self.n:04d}", "name": name, "email": f"{name.split()[0].lower()}@lumenai.test",
               "department": dept, "title": title, "manager_email": manager, "employment_type": kind,
               "status": "active", "start_date": "2026-12-01", "end_date": end_date}
        self.people[emp["id"]] = emp
        return self._event("employee.hired", emp, rehire=False)

    def move(self, emp_id, **changes):
        before = self.people[emp_id]
        if changes.get("employment_type") == "full_time":
            changes["end_date"] = None
        diff = {k: {"from": before[k], "to": v} for k, v in changes.items() if before[k] != v}
        before.update(changes)
        return self._event("employee.moved", before, changes=diff)

    def terminate(self, emp_id):
        self.people[emp_id].update(status="terminated", end_date=self.clock().date().isoformat())
        return self._event("employee.terminated", self.people[emp_id], reason="resigned")

    def rehire(self, emp_id, dept, title):
        self.people[emp_id].update(status="active", end_date=None, department=dept, title=title)
        return self._event("employee.hired", self.people[emp_id], rehire=True)


class Down(Exception):
    pass


class FakeKeycloak:
    def __init__(self):
        self.users, self.calls, self.fail_at, self.n = {}, [], None, 0

    def _call(self, name):
        self.n += 1
        if self.fail_at is not None and self.n >= self.fail_at:
            raise Down("keycloak unreachable")
        self.calls.append(name)

    def find_user(self, username):
        self._call("find_user")
        u = self.users.get(username)
        return {"id": username, "username": username, "enabled": u["enabled"]} if u else None

    def list_users(self):
        return [{"username": k, "enabled": v["enabled"]} for k, v in self.users.items()]

    def create_user(self, username, email, first, last, attrs, actions):
        self._call("create_user")
        self.users[username] = {"enabled": True, "groups": set(), "actions": actions, "sessions": 0,
                                "consents": [], "credentials": []}

    def set_enabled(self, uid, enabled):
        self._call("set_enabled")
        self.users[uid]["enabled"] = enabled

    def set_required_actions(self, uid, actions):
        self._call("set_required_actions")
        self.users[uid]["actions"] = actions

    def credentials(self, uid):
        return [{"id": c} for c in self.users[uid]["credentials"]]

    def delete_credential(self, uid, cid):
        self._call("delete_credential")
        self.users[uid]["credentials"].remove(cid)

    def user_groups(self, uid):
        self._call("user_groups")
        return sorted(self.users[uid]["groups"])

    def add_group(self, uid, g):
        self._call("add_group")
        self.users[uid]["groups"].add(g)

    def remove_group(self, uid, g):
        self._call("remove_group")
        self.users[uid]["groups"].discard(g)

    def sessions(self, uid):
        return [1] * self.users[uid]["sessions"]

    def logout(self, uid):
        self._call("logout")
        self.users[uid]["sessions"] = 0

    def consents(self, uid):
        return [{"clientId": c} for c in self.users[uid]["consents"]]

    def revoke_consent(self, uid, client):
        self._call("revoke_consent")
        self.users[uid]["consents"].remove(client)


class FakeChat:
    def __init__(self):
        self.users, self.dms = {}, []

    def ensure_user(self, u, email, name):
        if self.users.get(u, {}).get("active"):
            return False
        self.users.setdefault(u, {"channels": set(), "tokens": 0})["active"] = True
        return True

    def is_active(self, u):
        return self.users.get(u, {}).get("active", False)

    def channels(self, u):
        return sorted(self.users[u]["channels"])

    def join(self, u, c):
        self.users[u]["channels"].add(c)

    def leave(self, u, c):
        self.users[u]["channels"].discard(c)

    def deactivate(self, u):
        self.users[u]["active"] = False

    def revoke_tokens(self, u):
        n = self.users.get(u, {}).get("tokens", 0)
        if n:
            self.users[u]["tokens"] = 0
        return n

    def send_dm(self, to, text):
        self.dms.append((to, text))


class FakeFleet:
    def __init__(self):
        self.owners, self.locked = {}, []

    def owner(self, s):
        return self.owners.get(s)

    def set_owner(self, s, e):
        self.owners[s] = e

    def can_lock(self):
        return False

    def lock(self, s):
        self.locked.append(s)


class FakeTickets:
    def __init__(self):
        self.items = []

    def file(self, title, **f):
        self.items.append((title, f))
        return f"IT-{len(self.items)}"


@pytest.fixture
def env():
    d = Path(tempfile.mkdtemp())
    clock = Clock()
    e = Engine(RULES, FakeHR(clock), FakeKeycloak(), FakeChat(), FakeFleet(), FakeTickets(),
               Store(d / "e.sqlite"), Audit(d / "audit.jsonl", clock), clock)
    return e


def groups(e, username):
    return e.kc.users[username]["groups"]


def actions(e, name):
    return [x for x in e.audit.entries() if x["action"] == name]


# ---------------------------------------------------------------- joiner / leaver basics

def test_joiner_gets_birthright_and_must_set_password_and_mfa(env):
    assert env.receive(env.hr.hire("Dana Lee", "engineering", "ML Engineer")) == "done"
    assert groups(env, "dana") == {"all-staff", "engineering"}
    assert env.kc.users["dana"]["actions"] == ["UPDATE_PASSWORD", "CONFIGURE_TOTP"]
    assert "eng" in env.chat.users["dana"]["channels"]
    assert actions(env, "device.record")[0]["detail"]["device_type"] == "macbook-pro"


def test_leaver_removes_everything_within_five_minutes(env):
    ev = env.hr.hire("Lee Park", "sales", "Account Executive")
    env.receive(ev)
    env.kc.users["lee"].update(sessions=2, consents=["pomerium", "some-oauth-app"])
    env.chat.users["lee"]["tokens"] = 3
    env.clock.advance(days=30)
    term = env.hr.terminate("E0001")
    env.clock.advance(seconds=4)  # webhook delivery + processing time
    assert env.receive(term) == "done"
    u = env.kc.users["lee"]
    assert not u["enabled"] and u["sessions"] == 0 and u["consents"] == [] and u["groups"] == set()
    assert not env.chat.users["lee"]["active"] and env.chat.users["lee"]["tokens"] == 0
    assert any("laptop" in t[0] for t in env.tickets.items)
    assert actions(env, "files.handoff")[0]["detail"]["to"] == "mgr@lumenai.test"
    secs = actions(env, "leaver.complete")[0]["detail"]["seconds_since_termination"]
    assert secs < 300
    # disabling sign-in is the very first change made
    first_change = [a["action"] for a in env.audit.entries() if a["event_id"] == term["id"]][0]
    assert first_change == "keycloak.disable_user"


# ---------------------------------------------------------------- the six ugly cases

def test_1_same_webhook_twice_nothing_happens_twice(env):
    ev = env.hr.hire("Dana Lee", "engineering", "ML Engineer")
    assert env.receive(ev) == "done"
    calls_after_first = list(env.kc.calls)
    entries_after_first = len(env.audit.entries())
    assert env.receive(ev) == "duplicate"
    assert env.kc.calls == calls_after_first  # Keycloak not touched at all the second time
    assert [a["action"] for a in env.audit.entries()[entries_after_first:]] == ["duplicate_ignored"]


def test_2_rehire_after_leaving(env):
    env.receive(env.hr.hire("Sam Roy", "engineering", "Engineer"))
    env.kc.users["sam"]["credentials"] = ["old-password", "old-totp"]
    env.receive(env.hr.terminate("E0001"))
    assert not env.kc.users["sam"]["enabled"]
    env.clock.advance(days=200)
    assert env.receive(env.hr.rehire("E0001", "research", "Researcher")) == "done"
    u = env.kc.users["sam"]
    assert u["enabled"] and u["credentials"] == []  # old password and MFA don't come back
    assert u["actions"] == ["UPDATE_PASSWORD", "CONFIGURE_TOTP"]
    assert u["groups"] == {"all-staff", "research"}  # new role, nothing from the old one
    assert env.chat.users["sam"]["active"]


def test_3_contractor_converts_to_full_time(env):
    env.receive(env.hr.hire("Cara Diaz", "engineering", "Engineer", "contractor", end_date="2027-03-31"))
    assert groups(env, "cara") == {"contractors", "engineering"}
    assert "announcements" not in env.chat.users["cara"]["channels"]
    env.receive(env.hr.move("E0001", employment_type="full_time"))
    assert groups(env, "cara") == {"all-staff", "engineering"}
    assert "announcements" in env.chat.users["cara"]["channels"]


def test_4_two_team_changes_in_one_week(env):
    env.receive(env.hr.hire("Max Bell", "engineering", "Engineer"))
    env.clock.advance(days=2)
    env.receive(env.hr.move("E0001", department="research", title="Researcher"))
    env.clock.advance(days=3)
    env.receive(env.hr.move("E0001", department="sales", title="Sales Engineer"))
    assert groups(env, "max") == {"all-staff", "sales", "engineering-readonly"}
    assert "research" not in env.chat.users["max"]["channels"]
    assert {"sales", "eng"} <= env.chat.users["max"]["channels"]


def test_5_termination_while_a_move_is_half_applied(env):
    env.receive(env.hr.hire("Ana Cruz", "engineering", "Engineer"))
    move = env.hr.move("E0001", department="research", title="Researcher")
    env.kc.fail_at = env.kc.n + 4  # find, user_groups, add "research" succeed; then Keycloak dies
    assert env.receive(move) == "pending"
    assert {"engineering", "research"} <= groups(env, "ana")  # half-applied: old group not removed yet
    env.kc.fail_at = None
    term = env.hr.terminate("E0001")
    assert env.receive(term) == "done"
    assert env.retry_pending() == 1  # the stuck move now runs, sees HR says "terminated", adds nothing
    u = env.kc.users["ana"]
    assert not u["enabled"] and u["groups"] == set()


def test_6_keycloak_down_halfway_next_run_finishes(env):
    ev = env.hr.hire("Ola Ade", "engineering", "Engineering Manager")
    env.kc.fail_at = 4  # dies after creating the user and adding one group
    assert env.receive(ev) == "pending"
    assert env.kc.users["ola"]["groups"] != {"all-staff", "engineering", "managers"}
    env.kc.fail_at = None
    assert env.retry_pending() == 1
    assert groups(env, "ola") == {"all-staff", "engineering", "managers"}
    assert env.kc.calls.count("create_user") == 1  # no duplicate account
    assert env.kc.calls.count("add_group") == 3     # each group added exactly once


# ---------------------------------------------------------------- mover, nightly, audit

def test_mover_keeps_requested_access_and_asks_new_manager(env):
    env.receive(env.hr.hire("Ivo Tan", "it", "Systems Administrator"))
    env.store.q("INSERT INTO grants (employee_id, item, kind, approver, expires_at) VALUES (?,?,?,?,?)",
                "E0001", "it-admins", "keycloak_group", "it-director@lumenai.test", iso(env.clock() + timedelta(days=60)))
    env.reconcile("E0001")
    assert "it-admins" in groups(env, "ivo")
    env.receive(env.hr.move("E0001", department="engineering", title="Engineer", manager_email="lead@lumenai.test"))
    assert "it-admins" in groups(env, "ivo") and "it" not in groups(env, "ivo")
    to, text = env.chat.dms[-1]
    assert to == "lead@lumenai.test" and "it-admins" in text


def test_expired_grant_is_removed(env):
    env.receive(env.hr.hire("Ivo Tan", "it", "Systems Administrator"))
    env.store.q("INSERT INTO grants (employee_id, item, kind, approver, expires_at) VALUES (?,?,?,?,?)",
                "E0001", "it-admins", "keycloak_group", "x", iso(env.clock() + timedelta(days=1)))
    env.reconcile("E0001")
    env.clock.advance(days=2)
    env.nightly(set())
    assert "it-admins" not in groups(env, "ivo")


def test_nightly_flags_orphans_and_ends_expired_contracts(env):
    env.receive(env.hr.hire("Cara Diaz", "engineering", "Engineer", "contractor", end_date="2026-12-15"))
    env.kc.users["ghost"] = {"enabled": True, "groups": set(), "actions": [], "sessions": 0, "consents": [],
                             "credentials": []}
    env.kc.users["alice"] = dict(env.kc.users["ghost"])
    env.clock.advance(days=20)  # contract ended, HR never sent a termination
    result = env.nightly({"alice"})
    assert result["orphans"] == ["ghost"]  # alice is on the allow-list
    assert not env.kc.users["cara"]["enabled"]  # contract end date enforced anyway


def test_audit_log_is_tamper_evident(env):
    env.receive(env.hr.hire("Dana Lee", "engineering", "ML Engineer"))
    assert env.audit.verify()[0]
    lines = env.audit.path.read_text().splitlines()
    lines[1] = lines[1].replace("all-staff", "it-admins")
    env.audit.path.write_text("\n".join(lines) + "\n")
    ok, why = env.audit.verify()
    assert not ok and "line 3" in why


def test_every_action_has_event_target_result_time(env):
    env.receive(env.hr.hire("Dana Lee", "engineering", "ML Engineer"))
    for a in env.audit.entries():
        assert {"event_id", "action", "target", "result", "time"} <= set(a)


# ---------------------------------------------------------------- the webhook endpoint

def test_webhook_rejects_unsigned_and_drops_duplicates(monkeypatch):
    d = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", d)
    monkeypatch.setenv("HR_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("NIGHTLY_SECONDS", "999999")
    import importlib

    from fastapi.testclient import TestClient
    from signing import sign
    app_mod = importlib.import_module("app")
    clock = Clock()
    app_mod.ENGINE = Engine(RULES, FakeHR(clock), FakeKeycloak(), FakeChat(), FakeFleet(), FakeTickets(),
                            Store(Path(d) / "t.sqlite"), Audit(Path(d) / "a.jsonl", clock), clock)
    app_mod.SECRET = "s3cret"
    client = TestClient(app_mod.app)
    body = json.dumps(app_mod.ENGINE.hr.hire("Dana Lee", "engineering", "ML Engineer")).encode()
    assert client.post("/webhook", content=body, headers={"X-HR-Signature": "t=1,v1=bad"}).status_code == 401
    h = {"X-HR-Signature": sign("s3cret", body)}
    assert client.post("/webhook", content=body, headers=h).json() == {"result": "done"}
    assert client.post("/webhook", content=body, headers=h).json() == {"result": "duplicate"}
