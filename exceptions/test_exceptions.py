"""Full exception loop with fakes. Run:  cd exceptions && python -m pytest -v"""
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

import santa_rules
from clients import Tickets, WaiverFile
from service import ExceptionService

HERE = Path(__file__).resolve().parent
CFG = yaml.safe_load((HERE / "types.yaml").read_text())
SHA = "a" * 64
MACHINE = "25D83DC7-A8EC-52C5-BBB4-85145D5FD8CF"
GLOBAL = 'client_mode = "MONITOR"\n\n[[rules]]\nrule_type = "TEAMID"\npolicy = "ALLOWLIST"\nidentifier = "EQHXZ8M8AV"\n'


class Clock:
    def __init__(self):
        self.now = datetime(2026, 12, 1, 9, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


class FakeMM:
    users = {"u-omar": "omar@lumenai.test", "u-maya": "maya@lumenai.test", "u-sec": "secops@lumenai.test"}

    def __init__(self):
        self.dms, self.dialogs = [], []

    def user(self, uid):
        return {"id": uid, "email": self.users[uid]}

    def user_by_email(self, email):
        uid = next((k for k, v in self.users.items() if v == email), None)
        return {"id": uid} if uid else None

    def dm(self, uid, message, attachments=None):
        self.dms.append({"to": uid, "message": message, "attachments": attachments})

    def open_dialog(self, trigger, url, dialog):
        self.dialogs.append(dialog)


class FakeGH:
    def __init__(self, auto_merge=True):
        self.main = {"santa/rules/global.toml": GLOBAL}
        self.prs, self.auto_merge = {}, auto_merge

    def read(self, path, ref="main"):
        files = self.main if ref == "main" else self.prs[ref]["files"]
        return files.get(path), ("sha" if path in files else None)

    def change_file_pr(self, path, content, branch, title, body):
        n = len(self.prs) + 1
        self.prs[n] = {"path": path, "content": content, "title": title, "merged": False}
        return n

    def try_merge(self, n):
        if self.auto_merge:
            self.merge(n)
        return self.auto_merge

    def merge(self, n):
        self.main[self.prs[n]["path"]] = self.prs[n]["content"]
        self.prs[n]["merged"] = True

    def is_merged(self, n):
        return self.prs[n]["merged"]


class FakeDeploy:
    def __init__(self):
        self.pulls = 0

    def pull(self):
        self.pulls += 1
        return "pulled"


class FakeHR:
    def by_email(self, email):
        return {"omar@lumenai.test": {"manager_email": "maya@lumenai.test"}}.get(email)


def make(auto_merge=True):
    d = Path(tempfile.mkdtemp())
    clock = Clock()
    svc = ExceptionService(CFG, d / "x.sqlite", FakeMM(), FakeGH(auto_merge), FakeDeploy(), FakeHR(),
                           WaiverFile(d / "waivers.json"), Tickets(d / "t.jsonl"), secret="test-secret",
                           bot_url="http://bot", security_approvers=["secops@lumenai.test"], slash_token="tok",
                           audit_path=d / "audit.jsonl", clock=clock)
    return svc, clock


def open_form(svc, user="u-omar", text=f"binary {SHA} {MACHINE}"):
    svc.slash({"token": "tok", "user_id": user, "trigger_id": "t", "text": text})
    return svc.mm.dialogs[-1]


def submit(svc, dialog, user="u-omar", **overrides):
    defaults = {e["name"]: e.get("default", "") for e in dialog["elements"]}
    sub = {**defaults, "justification": "Need the vendor CLI to debug a customer issue this week.",
           "minutes": "10", **overrides}
    return svc.submit({"user_id": user, "state": dialog["state"], "submission": sub, "cancelled": False})


def click(svc, user, decision="approve"):
    approver_dm = [d for d in svc.mm.dms if d["attachments"]][-1]
    btn = next(a for a in approver_dm["attachments"][0]["actions"] if a["id"] == decision)
    return svc.action({"user_id": user, "context": btn["integration"]["context"]})


# ---------------------------------------------------------------- the full loop

def test_full_loop_binary_blocked_requested_approved_runs_then_expires():
    svc, clock = make()
    dialog = open_form(svc)
    assert {e["name"]: e.get("default") for e in dialog["elements"]}["target"] == SHA  # prefilled from block page
    assert submit(svc, dialog) == {}
    req = svc.get("EXC-0001")
    assert req["status"] == "pending" and req["approver_email"] == "maya@lumenai.test"  # manager from HR

    resp = click(svc, "u-maya")
    assert "Approved by you" in resp["update"]["message"]
    rule_file = svc.gh.main[f"santa/rules/{MACHINE}.toml"]
    assert 'policy = "ALLOWLIST"' in rule_file and SHA in rule_file and "expires 2026-12-01T09:10:00Z" in rule_file
    assert rule_file.startswith("# Per-machine") and "EQHXZ8M8AV" in rule_file  # started from global.toml
    assert svc.get("EXC-0001")["status"] == "active" and svc.deploy.pulls == 1

    clock.now += timedelta(minutes=6)
    assert svc.tick()["reminded"] == 1  # reminder before the end
    clock.now += timedelta(minutes=5)
    assert svc.tick()["expired"] == 1
    rule_file = svc.gh.main[f"santa/rules/{MACHINE}.toml"]
    assert f'policy = "ALLOWLIST"\nidentifier = "{SHA}"' not in rule_file
    assert f'policy = "REMOVE"\nidentifier = "{SHA}"' in rule_file
    assert 'identifier = "EQHXZ8M8AV"' in rule_file  # the normal rules are untouched
    assert svc.get("EXC-0001")["status"] == "expired" and svc.deploy.pulls == 2
    assert any("expired and was removed" in d["message"] for d in svc.mm.dms if d["to"] == "u-omar")
    assert any("expired and was removed" in d["message"] for d in svc.mm.dms if d["to"] == "u-maya")


def test_grant_waits_for_merge_when_bot_cannot_merge():
    svc, clock = make(auto_merge=False)
    submit(svc, open_form(svc))
    click(svc, "u-maya")
    assert svc.get("EXC-0001")["status"] == "approved"  # PR open, not active yet
    svc.gh.merge(1)  # a human merges it
    assert svc.tick()["activated"] == 1 and svc.get("EXC-0001")["status"] == "active"


# ---------------------------------------------------------------- who may decide

def test_only_the_named_approver_can_decide():
    svc, _ = make()
    submit(svc, open_form(svc))
    assert "Only the named approver" in click(svc, "u-sec")["ephemeral_text"]
    assert "Only the named approver" in click(svc, "u-omar")["ephemeral_text"]  # requester can't self-approve
    assert svc.get("EXC-0001")["status"] == "pending"


def test_forged_button_context_is_rejected():
    svc, _ = make()
    submit(svc, open_form(svc))
    forged = {"exc_id": "EXC-0001", "decision": "approve", "sig": "0" * 64}
    assert "Only the named approver" in svc.action({"user_id": "u-maya", "context": forged})["ephemeral_text"]


def test_high_risk_goes_to_security_not_manager():
    svc, _ = make()
    submit(svc, open_form(svc, text=""), type="local_admin", device="C02XYZ123", target="Install a driver", minutes="1440")
    assert svc.get("EXC-0001")["approver_email"] == "secops@lumenai.test"


def test_no_manager_in_hr_falls_back_to_security():
    svc, _ = make()
    svc.mm.users["u-x"] = "nobody@lumenai.test"
    submit(svc, open_form(svc, user="u-x"), user="u-x")
    assert svc.get("EXC-0001")["approver_email"] == "secops@lumenai.test"


def test_deny_notifies_requester_and_changes_nothing():
    svc, _ = make()
    submit(svc, open_form(svc))
    click(svc, "u-maya", "deny")
    assert svc.get("EXC-0001")["status"] == "denied" and len(svc.gh.prs) == 0
    assert "denied" in svc.mm.dms[-1]["message"]


def test_cannot_decide_twice():
    svc, _ = make()
    submit(svc, open_form(svc))
    click(svc, "u-maya")
    assert "already decided" in click(svc, "u-maya")["ephemeral_text"]


# ---------------------------------------------------------------- the form

def test_validation_errors():
    svc, _ = make()
    d = open_form(svc, text="")
    r = submit(svc, d, type="allow_binary", device="../../etc/passwd", target="not-a-hash", justification="pls")
    assert set(r["errors"]) == {"device", "target", "justification"}
    r = submit(svc, d, type="local_admin", device="C02XYZ123", target="x", minutes="43200")
    assert "at most 7 days" in r["errors"]["minutes"]


def test_form_state_must_belong_to_submitter_and_be_fresh():
    svc, clock = make()
    d = open_form(svc)
    assert "error" in submit(svc, d, user="u-maya")  # someone else's form
    clock.now += timedelta(minutes=20)
    assert "error" in submit(svc, d)  # expired


def test_bad_slash_token_rejected():
    svc, _ = make()
    assert svc.slash({"token": "wrong", "user_id": "u-omar", "trigger_id": "t"})["text"] == "Invalid command token."


# ---------------------------------------------------------------- posture waiver, renewals, dashboard

def test_posture_waiver_written_then_removed():
    svc, clock = make()
    submit(svc, open_form(svc, text="waiver firewall_on ZR2JVG236J"), minutes="1440")
    click(svc, "u-maya")
    w = json.loads(svc.waivers.path.read_text())["waivers"]
    assert w == [{"id": "EXC-0001", "serial": "ZR2JVG236J", "check": "firewall_on", "expires_at": "2026-12-02T09:00:00Z",
                  "requester": "omar@lumenai.test", "approver": "maya@lumenai.test"}]
    clock.now += timedelta(days=2)
    svc.tick()
    assert json.loads(svc.waivers.path.read_text())["waivers"] == []


def test_renewals_counted_on_dashboard():
    svc, clock = make()
    for _ in range(3):
        submit(svc, open_form(svc))
        click(svc, "u-maya")
        clock.now += timedelta(minutes=11)
        svc.tick()
    d = svc.dashboard()
    assert d["renewals"] == 2 and svc.get("EXC-0003")["renewal_of"] == "EXC-0002"
    assert [r["renewals"] for r in d["closed"] if r["id"] == "EXC-0003"] == [2]


def test_dashboard_open_by_type():
    svc, _ = make()
    submit(svc, open_form(svc))
    submit(svc, open_form(svc, text="waiver os_current ZR2JVG236J"), minutes="1440")
    assert svc.dashboard()["by_type"] == {"allow_binary": 1, "posture_waiver": 1}


def test_revoke_rewrites_only_its_own_block():
    f = santa_rules.add_exception(None, GLOBAL, santa_rules.grant_block("EXC-0001", SHA, "a", "b", "T1"))
    f = santa_rules.add_exception(f, GLOBAL, santa_rules.grant_block("EXC-0002", "b" * 64, "a", "b", "T2"))
    f = santa_rules.revoke_exception(f, "EXC-0001", SHA, "now")
    assert f.count('policy = "ALLOWLIST"\nidentifier = "' + "b" * 64) == 1
    assert 'policy = "REMOVE"\nidentifier = "' + SHA in f
    with pytest.raises(KeyError):
        santa_rules.revoke_exception(f, "EXC-0009", SHA, "now")
