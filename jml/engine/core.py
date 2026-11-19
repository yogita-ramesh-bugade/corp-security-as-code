"""Joiner/mover/leaver engine: reconciliation core (Project 3, Step 3.3).

Every HR event is only a TRIGGER. The engine always asks HR for the person's CURRENT record,
works out what access they should have (roles.yaml + approved requests), reads what they
actually have, and fixes only the difference. So:
  - the same event twice changes nothing the second time,
  - a crash halfway is fixed by simply running again,
  - if a termination arrives while a move is half-done, HR's latest record wins.

Systems are reached through small connector objects (connectors.py for the real ones,
the tests use fakes), so every ugly case can be tested by making a fake fail on cue.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

from rules import birthright


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- audit log

class Audit:
    """Append-only JSON-lines log. Each line carries the hash of the line before it, so an
    edited or deleted line breaks the chain and `verify()` says where."""

    def __init__(self, path: Path, clock=utcnow):
        self.path, self.clock, self._lock = Path(path), clock, threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hash(self) -> str:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return "0" * 64
        last = self.path.read_text().rstrip("\n").rsplit("\n", 1)[-1]
        return hashlib.sha256(last.encode()).hexdigest()

    def log(self, event_id: str, action: str, target: str, result: str = "ok", **detail) -> dict:
        with self._lock:
            entry = {"time": iso(self.clock()), "event_id": event_id, "action": action, "target": target,
                     "result": result, **({"detail": detail} if detail else {}), "prev": self._last_hash()}
            with open(self.path, "a") as f:
                f.write(json.dumps(entry, sort_keys=True) + "\n")
            return entry

    def entries(self) -> list[dict]:
        return [json.loads(line) for line in self.path.read_text().splitlines()] if self.path.exists() else []

    def verify(self) -> tuple[bool, str]:
        prev = "0" * 64
        for n, line in enumerate(self.path.read_text().splitlines() if self.path.exists() else [], 1):
            if json.loads(line)["prev"] != prev:
                return False, f"chain broken at line {n}"
            prev = hashlib.sha256(line.encode()).hexdigest()
        return True, "audit log intact"


# ---------------------------------------------------------------- engine database

SCHEMA = """
CREATE TABLE IF NOT EXISTS inbox (
  event_id TEXT PRIMARY KEY, type TEXT, employee_id TEXT, occurred_at TEXT, body TEXT,
  status TEXT NOT NULL,              -- pending | done | rejected
  attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, received_at TEXT, done_at TEXT);
CREATE TABLE IF NOT EXISTS grants (  -- requested access beyond birthright (filled by the exception bot, 3.4)
  id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT, item TEXT, kind TEXT, approver TEXT,
  expires_at TEXT, review_due TEXT, status TEXT NOT NULL DEFAULT 'active');
CREATE TABLE IF NOT EXISTS devices (employee_id TEXT PRIMARY KEY, device_type TEXT, serial TEXT, recorded_at TEXT);
CREATE TABLE IF NOT EXISTS offboarding (employee_id TEXT PRIMARY KEY, terminated_event TEXT, started_at TEXT,
  ticket_filed INTEGER DEFAULT 0, handoff_done INTEGER DEFAULT 0, completed_at TEXT, seconds REAL);
CREATE TABLE IF NOT EXISTS notified (event_id TEXT PRIMARY KEY);
"""


class Store:
    def __init__(self, path):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.lock = threading.RLock()

    def q(self, sql, *args):
        with self.lock:
            rows = [dict(r) for r in self.conn.execute(sql, args)]
            self.conn.commit()
            return rows


# ---------------------------------------------------------------- the engine

class Engine:
    def __init__(self, rules, hr, keycloak, chat, fleet, tickets, store: Store, audit: Audit, clock=utcnow):
        self.rules, self.hr, self.kc, self.chat, self.fleet, self.tickets = rules, hr, keycloak, chat, fleet, tickets
        self.store, self.audit, self.clock = store, audit, clock
        req = rules.get("requestable", {})
        # The engine only ever touches groups/channels that roles.yaml knows about.
        self.managed_groups = {g for g in self._rule_values("keycloak_groups")} | {
            k for k, v in req.items() if v["kind"] == "keycloak_group"}
        self.managed_channels = {c for c in self._rule_values("chat_channels")} | {
            k for k, v in req.items() if v["kind"] == "chat_channel"}

    def _rule_values(self, key):
        r = self.rules
        sources = [r["everyone"], *r["departments"].values(), *r.get("titles", [])]
        out = {v for s in sources for v in s.get(key, [])}
        for e in r["employment_types"].values():
            out |= set(e.get(f"add_{key}", []))
        return out

    # ---- inbox: what happens to each webhook ----------------------------------------
    def receive(self, event: dict) -> str:
        """Record a verified event. Returns 'duplicate' if this event ID was already handled."""
        existing = self.store.q("SELECT status FROM inbox WHERE event_id = ?", event["id"])
        if existing and existing[0]["status"] in ("done", "rejected"):
            self.audit.log(event["id"], "duplicate_ignored", event["data"]["employee"]["id"])
            return "duplicate"
        if not existing:
            self.store.q("INSERT INTO inbox (event_id, type, employee_id, occurred_at, body, status, received_at) "
                         "VALUES (?, ?, ?, ?, ?, 'pending', ?)", event["id"], event["type"],
                         event["data"]["employee"]["id"], event["occurred_at"], json.dumps(event), iso(self.clock()))
        return self.process(event["id"])

    def process(self, event_id: str) -> str:
        row = self.store.q("SELECT * FROM inbox WHERE event_id = ?", event_id)[0]
        event = json.loads(row["body"])
        try:
            self.reconcile(row["employee_id"], event_id, event)
            if event["type"] == "employee.moved":
                self.notify_new_manager(event)
        except Exception as e:  # noqa: BLE001 - leave it pending; the retry run finishes the job
            self.store.q("UPDATE inbox SET attempts = attempts + 1, last_error = ? WHERE event_id = ?",
                         f"{type(e).__name__}: {e}", event_id)
            self.audit.log(event_id, "reconcile", row["employee_id"], "error", error=f"{type(e).__name__}: {e}")
            return "pending"
        self.store.q("UPDATE inbox SET status = 'done', done_at = ?, attempts = attempts + 1, last_error = NULL "
                     "WHERE event_id = ?", iso(self.clock()), event_id)
        return "done"

    def retry_pending(self) -> int:
        ids = [r["event_id"] for r in self.store.q("SELECT event_id FROM inbox WHERE status = 'pending' "
                                                   "ORDER BY occurred_at")]
        return sum(self.process(i) == "done" for i in ids)

    # ---- desired state ----------------------------------------------------------------
    def active_grants(self, emp_id: str) -> list[dict]:
        now = iso(self.clock())
        return self.store.q("SELECT * FROM grants WHERE employee_id = ? AND status = 'active' AND expires_at > ?",
                            emp_id, now)

    def desired(self, emp: dict) -> dict:
        today = self.clock().date().isoformat()
        active = emp["status"] == "active" and (not emp.get("end_date") or emp["end_date"] >= today)
        if not active:
            return {"active": False}
        b = birthright(self.rules, emp)
        grants = self.active_grants(emp["id"])
        return {"active": True, "device": b["device"],
                "groups": set(b["keycloak_groups"]) | {g["item"] for g in grants if g["kind"] == "keycloak_group"},
                "channels": set(b["chat_channels"]) | {g["item"] for g in grants if g["kind"] == "chat_channel"}}

    # ---- reconcile one person -----------------------------------------------------------
    def reconcile(self, emp_id: str, event_id: str = "nightly", event: dict | None = None) -> None:
        emp = self.hr.get(emp_id)
        want = self.desired(emp)
        username = emp["email"].split("@")[0]
        if want["active"]:
            self._joiner_or_mover(emp, username, want, event_id)
        else:
            self._leaver(emp, username, event_id, event)

    def _joiner_or_mover(self, emp, username, want, ev):
        first, _, last = emp["name"].partition(" ")
        user = self.kc.find_user(username)
        if user is None:
            self.kc.create_user(username, emp["email"], first, last or first, {"employee_id": [emp["id"]]},
                                ["UPDATE_PASSWORD", "CONFIGURE_TOTP"])
            self.audit.log(ev, "keycloak.create_user", username, required_actions="set password, set up MFA")
            user = self.kc.find_user(username)
        elif not user["enabled"]:  # rehire: fresh start, old password and MFA don't come back
            for cred in self.kc.credentials(user["id"]):
                self.kc.delete_credential(user["id"], cred["id"])
            self.kc.set_required_actions(user["id"], ["UPDATE_PASSWORD", "CONFIGURE_TOTP"])
            self.kc.set_enabled(user["id"], True)
            self.audit.log(ev, "keycloak.reenable_user", username, note="rehire: old credentials removed")
        self.store.q("DELETE FROM offboarding WHERE employee_id = ?", emp["id"])

        have = set(self.kc.user_groups(user["id"])) & self.managed_groups
        for g in sorted(want["groups"] - have):
            self.kc.add_group(user["id"], g)
            self.audit.log(ev, "keycloak.add_group", username, group=g)
        for g in sorted(have - want["groups"]):
            self.kc.remove_group(user["id"], g)
            self.audit.log(ev, "keycloak.remove_group", username, group=g)

        if self.chat.ensure_user(username, emp["email"], emp["name"]):
            self.audit.log(ev, "chat.create_or_reactivate", username)
        have_ch = set(self.chat.channels(username)) & self.managed_channels
        for c in sorted(want["channels"] - have_ch):
            self.chat.join(username, c)
            self.audit.log(ev, "chat.join", username, channel=c)
        for c in sorted(have_ch - want["channels"]):
            self.chat.leave(username, c)
            self.audit.log(ev, "chat.leave", username, channel=c)

        dev = self.store.q("SELECT * FROM devices WHERE employee_id = ?", emp["id"])
        if not dev:
            self.store.q("INSERT INTO devices (employee_id, device_type, recorded_at) VALUES (?, ?, ?)",
                         emp["id"], want["device"], iso(self.clock()))
            self.audit.log(ev, "device.record", username, device_type=want["device"],
                           note="IT ships it; `engine assign-device` maps the serial in Fleet")
        elif dev[0]["serial"]:
            if self.fleet.owner(dev[0]["serial"]) != emp["email"]:
                self.fleet.set_owner(dev[0]["serial"], emp["email"])
                self.audit.log(ev, "fleet.map_device", username, serial=dev[0]["serial"])

    def _leaver(self, emp, username, ev, event):
        if not self.store.q("SELECT 1 FROM offboarding WHERE employee_id = ?", emp["id"]):
            started = (event or {}).get("occurred_at") or iso(self.clock())
            self.store.q("INSERT INTO offboarding (employee_id, terminated_event, started_at) VALUES (?, ?, ?)",
                         emp["id"], ev, started)
        user = self.kc.find_user(username)
        if user:
            if user["enabled"]:  # first and most important: no new sign-ins
                self.kc.set_enabled(user["id"], False)
                self.audit.log(ev, "keycloak.disable_user", username)
            if self.kc.sessions(user["id"]):
                self.kc.logout(user["id"])
                self.audit.log(ev, "keycloak.end_sessions", username)
            for c in self.kc.consents(user["id"]):
                self.kc.revoke_consent(user["id"], c["clientId"])
                self.audit.log(ev, "keycloak.revoke_consent", username, client=c["clientId"])
            for g in sorted(set(self.kc.user_groups(user["id"])) & self.managed_groups):
                self.kc.remove_group(user["id"], g)
                self.audit.log(ev, "keycloak.remove_group", username, group=g)
        if self.chat.is_active(username):
            self.chat.deactivate(username)
            self.audit.log(ev, "chat.deactivate", username)
        if n := self.chat.revoke_tokens(username):
            self.audit.log(ev, "chat.revoke_tokens", username, count=n)

        off = self.store.q("SELECT * FROM offboarding WHERE employee_id = ?", emp["id"])[0]
        dev = self.store.q("SELECT * FROM devices WHERE employee_id = ?", emp["id"])
        if not off["ticket_filed"]:
            serial = dev[0]["serial"] if dev else None
            if serial and self.fleet.can_lock():
                self.fleet.lock(serial)
                self.audit.log(ev, "fleet.lock_device", username, serial=serial)
            else:
                t = self.tickets.file(f"Collect and wipe laptop of {emp['name']} ({emp['email']})",
                                      serial=serial, reason="Fleet tier can't lock devices" if serial else "no serial on record")
                self.audit.log(ev, "ticket.device_return", username, ticket=t, serial=serial)
            self.store.q("UPDATE offboarding SET ticket_filed = 1 WHERE employee_id = ?", emp["id"])
        if not off["handoff_done"]:
            to = emp.get("manager_email") or "it-director@lumenai.test"
            self.tickets.file(f"SIMULATED: transfer files of {emp['email']} to {to}", kind="file_handoff")
            self.audit.log(ev, "files.handoff", username, to=to, simulated=True)
            self.store.q("UPDATE offboarding SET handoff_done = 1 WHERE employee_id = ?", emp["id"])
        for g in self.store.q("SELECT id FROM grants WHERE employee_id = ? AND status = 'active'", emp["id"]):
            self.store.q("UPDATE grants SET status = 'revoked_leaver' WHERE id = ?", g["id"])

        off = self.store.q("SELECT * FROM offboarding WHERE employee_id = ?", emp["id"])[0]
        if not off["completed_at"]:
            started = datetime.strptime(off["started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            secs = (self.clock() - started).total_seconds()
            self.store.q("UPDATE offboarding SET completed_at = ?, seconds = ? WHERE employee_id = ?",
                         iso(self.clock()), secs, emp["id"])
            self.audit.log(ev, "leaver.complete", username, seconds_since_termination=round(secs, 1))

    # ---- mover: ask the new manager about kept requested access ---------------------------
    def notify_new_manager(self, event: dict) -> None:
        if self.store.q("SELECT 1 FROM notified WHERE event_id = ?", event["id"]):
            return
        changes = event["data"].get("changes", {})
        emp = event["data"]["employee"]
        grants = self.active_grants(emp["id"])
        if grants and ("department" in changes or "manager_email" in changes) and emp.get("manager_email"):
            due = iso(datetime.fromtimestamp(self.clock().timestamp() + 7 * 86400, timezone.utc))
            items = ", ".join(f"{g['item']} (until {g['expires_at'][:10]})" for g in grants)
            self.chat.send_dm(emp["manager_email"],
                              f"{emp['name']} moved to your team and still has requested access: {items}. "
                              f"Please confirm or remove each by {due[:10]}; unconfirmed access is removed then.")
            for g in grants:
                self.store.q("UPDATE grants SET review_due = ? WHERE id = ?", due, g["id"])
            self.audit.log(event["id"], "mover.manager_review_requested", emp["email"].split("@")[0],
                           manager=emp["manager_email"], grants=[g["item"] for g in grants])
        self.store.q("INSERT INTO notified (event_id) VALUES (?)", event["id"])

    # ---- nightly reconciliation -----------------------------------------------------------
    def nightly(self, non_hr_accounts: set[str]) -> dict:
        """Reconcile everyone HR knows; flag accounts with no active employee behind them."""
        people = self.hr.list_all()
        by_username = {p["email"].split("@")[0]: p for p in people}
        fixed = 0
        for p in people:
            try:
                self.reconcile(p["id"], "nightly")
                fixed += 1
            except Exception as e:  # noqa: BLE001
                self.audit.log("nightly", "reconcile", p["id"], "error", error=str(e))
        orphans = []
        for u in self.kc.list_users():
            p = by_username.get(u["username"])
            if u["username"] in non_hr_accounts:
                continue
            if p is None or (u["enabled"] and self.desired(p)["active"] is False):
                orphans.append(u["username"])
                self.audit.log("nightly", "orphan_flagged", u["username"], "flagged",
                               reason="no HR record" if p is None else "enabled but not an active employee")
        self.retry_pending()
        return {"reconciled": fixed, "orphans": orphans}
