"""Exception bot logic (Project 3, Step 3.4): request -> approve -> apply as code -> remind -> expire.

Mattermost doesn't sign the dialog submissions and button clicks it forwards, so the bot signs
its own: the dialog `state` and every button's `context` carry an HMAC tied to the expected
user. A forged "Approve" sent straight to the bot fails the check.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import santa_rules

MACHINE_ID = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")
SERIAL = re.compile(r"^[A-Za-z0-9-]{4,64}$")
OPEN = ("pending", "approved", "active", "expiring")

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
  id TEXT PRIMARY KEY, type TEXT, requester_email TEXT, requester_mm TEXT, device TEXT, target TEXT,
  justification TEXT, minutes INTEGER, approver_email TEXT, approver_mm TEXT,
  status TEXT,   -- pending | denied | approved (applying) | active | expiring (removal PR open) | expired
  created_at TEXT, decided_at TEXT, activated_at TEXT, expires_at TEXT, reminded INTEGER DEFAULT 0,
  grant_pr INTEGER, revoke_pr INTEGER, renewal_of TEXT, last_error TEXT);
"""


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class ExceptionService:
    def __init__(self, config, db_path, mm, gh, deploy, hr, waivers, tickets, *, secret, bot_url,
                 security_approvers, slash_token, audit_path, clock=lambda: datetime.now(timezone.utc)):
        self.cfg, self.mm, self.gh, self.deploy, self.hr = config, mm, gh, deploy, hr
        self.waivers, self.tickets, self.secret = waivers, tickets, secret.encode()
        self.bot_url, self.security, self.slash_token = bot_url.rstrip("/"), security_approvers, slash_token
        self.audit_path, self.clock, self.lock = Path(audit_path), clock, threading.RLock()
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ---------------------------------------------------------------- helpers
    def q(self, sql, *args):
        with self.lock:
            rows = [dict(r) for r in self.db.execute(sql, args)]
            self.db.commit()
            return rows

    def get(self, exc_id):
        rows = self.q("SELECT * FROM requests WHERE id = ?", exc_id)
        return rows[0] if rows else None

    def set(self, exc_id, **fields):
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.q(f"UPDATE requests SET {cols} WHERE id = ?", *fields.values(), exc_id)

    def audit(self, exc_id, action, **detail):
        with open(self.audit_path, "a") as f:
            f.write(json.dumps({"time": iso(self.clock()), "exception": exc_id, "action": action, **detail}) + "\n")

    def sign(self, *parts):
        return hmac.new(self.secret, "|".join(parts).encode(), hashlib.sha256).hexdigest()

    def checks_out(self, sig, *parts):
        return hmac.compare_digest(sig or "", self.sign(*parts))

    # ---------------------------------------------------------------- 1. /exception
    def slash(self, form: dict) -> dict:
        if not hmac.compare_digest(form.get("token", ""), self.slash_token):
            return {"response_type": "ephemeral", "text": "Invalid command token."}
        args = (form.get("text") or "").split()
        pre = {"type": "", "device": "", "target": ""}
        if args[:1] == ["binary"] and len(args) >= 3:
            pre = {"type": "allow_binary", "target": args[1].lower(), "device": args[2]}
        elif args[:1] == ["waiver"] and len(args) >= 3:
            pre = {"type": "posture_waiver", "target": args[1], "device": args[2]}
        expires = iso(self.clock() + timedelta(minutes=15))
        state = json.dumps({"user": form["user_id"], "exp": expires, "sig": self.sign(form["user_id"], expires)})
        types = self.cfg["types"]
        dialog = {
            "callback_id": "exception_request", "title": "Request a security exception", "submit_label": "Request",
            "introduction_text": "Exceptions are temporary, need an approver, and are removed automatically.",
            "state": state, "notify_on_cancel": False,
            "elements": [
                {"display_name": "Type", "name": "type", "type": "select", "default": pre["type"],
                 "options": [{"text": f"{t['label']} ({t['risk']} risk, max {t['max_days']} days)", "value": k}
                             for k, t in types.items()]},
                {"display_name": "Device", "name": "device", "type": "text", "default": pre["device"],
                 "help_text": "Santa machine ID for apps; laptop serial for waivers and admin rights"},
                {"display_name": "What exactly", "name": "target", "type": "text", "default": pre["target"],
                 "max_length": 200, "help_text": "App: SHA-256 of the file. Waiver: the check name. Admin: what for."},
                {"display_name": "Why you need it", "name": "justification", "type": "textarea", "min_length": 20,
                 "max_length": 1000, "help_text": "Your approver sees this."},
                {"display_name": "For how long", "name": "minutes", "type": "select",
                 "options": [{"text": d["label"], "value": str(d["minutes"])} for d in self.cfg["durations"]]},
            ]}
        self.mm.open_dialog(form["trigger_id"], f"{self.bot_url}/mm/dialog", dialog)
        return {"response_type": "ephemeral", "text": "Opening the exception form..."}

    # ---------------------------------------------------------------- 2. form submitted
    def validate(self, s: dict) -> dict:
        errors, t = {}, self.cfg["types"].get(s.get("type"))
        if not t:
            return {"type": "Choose a type."}
        try:
            minutes = int(s.get("minutes") or 0)
        except ValueError:
            minutes = 0
        if minutes not in [d["minutes"] for d in self.cfg["durations"]]:
            errors["minutes"] = "Choose a duration."
        elif minutes > t["max_days"] * 1440:
            errors["minutes"] = f"{t['label']} can last at most {t['max_days']} days."
        device, target = (s.get("device") or "").strip(), (s.get("target") or "").strip()
        if t["apply"] == "santa_rule":
            if not MACHINE_ID.match(device):
                errors["device"] = "Use the Santa machine ID shown on the block page (8-4-4-4-12 characters)."
            if not santa_rules.SHA256.match(target.lower()):
                errors["target"] = "Use the 64-character SHA-256 shown on the block page."
        else:
            if not SERIAL.match(device):
                errors["device"] = "Use the laptop's serial number."
            if t["apply"] == "opa_waiver" and target not in self.cfg["posture_checks"]:
                errors["target"] = "One of: " + ", ".join(self.cfg["posture_checks"])
        if len((s.get("justification") or "").strip()) < 20:
            errors["justification"] = "Say why, in at least 20 characters."
        return errors

    def submit(self, payload: dict) -> dict:
        if payload.get("cancelled"):
            return {}
        try:
            st = json.loads(payload.get("state") or "{}")
        except ValueError:
            st = {}
        if (st.get("user") != payload.get("user_id") or not self.checks_out(st.get("sig"), st.get("user", ""), st.get("exp", ""))
                or parse(st["exp"]) < self.clock()):
            return {"error": "This form expired or wasn't opened by you. Run /exception again."}
        s = payload["submission"]
        if errors := self.validate(s):
            return {"errors": errors}
        t = self.cfg["types"][s["type"]]
        requester = self.mm.user(payload["user_id"])
        email = requester["email"].lower()
        target = s["target"].strip().lower() if t["apply"] == "santa_rule" else s["target"].strip()
        device = s["device"].strip().upper() if t["apply"] == "santa_rule" else s["device"].strip()

        approver_email = None
        if t["approver"] == "manager":
            emp = self.hr.by_email(email)
            approver_email = (emp or {}).get("manager_email")
        if not approver_email or approver_email.lower() == email:
            approver_email = next((a for a in self.security if a.lower() != email), None)
        approver = self.mm.user_by_email(approver_email) if approver_email else None
        if not approver:
            return {"error": "No approver could be found in chat. Contact the security team."}

        with self.lock:
            n = self.q("SELECT COUNT(*) AS n FROM requests")[0]["n"] + 1
            exc_id = f"EXC-{n:04d}"
            prev = self.q("SELECT id FROM requests WHERE requester_email = ? AND type = ? AND target = ? AND device = ? "
                          "AND status IN ('active', 'expiring', 'expired') ORDER BY created_at DESC LIMIT 1",
                          email, s["type"], target, device)
            self.q("INSERT INTO requests (id, type, requester_email, requester_mm, device, target, justification, "
                   "minutes, approver_email, approver_mm, status, created_at, renewal_of) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?, 'pending', ?, ?)",
                   exc_id, s["type"], email, payload["user_id"], device, target, s["justification"].strip(),
                   int(s["minutes"]), approver_email, approver["id"], iso(self.clock()), prev[0]["id"] if prev else None)
        req = self.get(exc_id)
        self.audit(exc_id, "requested", requester=email, approver=approver_email, type=s["type"])
        self.mm.dm(approver["id"], self.summary(req, f"**{email}** asks for an exception. You're the approver."),
                   attachments=[{"actions": [self.button(req, "approve", "Approve", "good"),
                                             self.button(req, "deny", "Deny", "danger")]}])
        self.mm.dm(payload["user_id"], f"Request **{exc_id}** sent to {approver_email} for approval."
                   + (f" (Renewal of {req['renewal_of']}.)" if req["renewal_of"] else ""))
        return {}

    def summary(self, r, headline):
        t = self.cfg["types"][r["type"]]
        dur = next(d["label"] for d in self.cfg["durations"] if d["minutes"] == r["minutes"])
        renewal = f"\n| Renewal of | {r['renewal_of']} |" if r["renewal_of"] else ""
        return (f"{headline}\n\n| | |\n|---|---|\n| Request | {r['id']} |\n| Type | {t['label']} ({t['risk']} risk) |\n"
                f"| Device | `{r['device']}` |\n| What | `{r['target']}` |\n| For | {dur} |{renewal}\n"
                f"| Why | {r['justification']} |")

    def button(self, req, decision, label, style):
        return {"id": decision, "name": label, "style": style, "type": "button",
                "integration": {"url": f"{self.bot_url}/mm/action",
                                "context": {"exc_id": req["id"], "decision": decision,
                                            "sig": self.sign(req["id"], decision, req["approver_mm"])}}}

    # ---------------------------------------------------------------- 3. approver clicks
    def action(self, payload: dict) -> dict:
        ctx, clicker = payload.get("context") or {}, payload.get("user_id", "")
        req = self.get(ctx.get("exc_id", ""))
        if not req or not self.checks_out(ctx.get("sig"), req["id"], ctx.get("decision", ""), clicker):
            return {"ephemeral_text": "Only the named approver can decide this request."}
        if clicker == req["requester_mm"]:
            return {"ephemeral_text": "You can't approve your own request."}
        if req["status"] != "pending":
            return {"ephemeral_text": f"{req['id']} was already decided ({req['status']})."}
        now = self.clock()
        if ctx["decision"] == "deny":
            self.set(req["id"], status="denied", decided_at=iso(now))
            self.audit(req["id"], "denied", by=req["approver_email"])
            self.mm.dm(req["requester_mm"], f"Your request **{req['id']}** was denied by {req['approver_email']}.")
            return {"update": {"message": self.summary(req, f"Denied by you at {iso(now)}."), "props": {}}}
        expires = now + timedelta(minutes=req["minutes"])
        self.set(req["id"], status="approved", decided_at=iso(now), expires_at=iso(expires))
        self.audit(req["id"], "approved", by=req["approver_email"], expires_at=iso(expires))
        result = self.apply(self.get(req["id"]))
        return {"update": {"message": self.summary(req, f"Approved by you. {result}"), "props": {}}}

    # ---------------------------------------------------------------- 4. apply as code
    def apply(self, req) -> str:
        t = self.cfg["types"][req["type"]]
        try:
            if t["apply"] == "santa_rule":
                path = f"santa/rules/{req['device']}.toml"
                current, _ = self.gh.read(path)
                global_toml, _ = self.gh.read("santa/rules/global.toml")
                block = santa_rules.grant_block(req["id"], req["target"], req["requester_email"],
                                                req["approver_email"], req["expires_at"])
                pr = self.gh.change_file_pr(
                    path, santa_rules.add_exception(current, global_toml, block), f"exception/{req['id'].lower()}-grant",
                    f"Exception {req['id']}: allow {req['target'][:12]}... on {req['device'][:8]} until {req['expires_at']}",
                    f"Approved in chat by {req['approver_email']} for {req['requester_email']}.\n\n"
                    f"Justification: {req['justification']}\n\nRemoved automatically at {req['expires_at']}.")
                self.set(req["id"], grant_pr=pr, last_error=None)
                self.audit(req["id"], "grant_pr_opened", pr=pr)
                if self.gh.try_merge(pr):
                    return self.activate(req["id"], f"PR #{pr} merged.")
                return f"PR #{pr} opened; it becomes active when merged."
            if t["apply"] == "opa_waiver":
                self.waivers.add({"id": req["id"], "serial": req["device"], "check": req["target"],
                                  "expires_at": req["expires_at"], "requester": req["requester_email"],
                                  "approver": req["approver_email"]})
                return self.activate(req["id"], "Waiver written to the access policy data.")
            self.tickets.file(f"Grant temporary local admin on {req['device']} to {req['requester_email']} "
                              f"until {req['expires_at']} ({req['id']})", exception=req["id"])
            return self.activate(req["id"], "IT ticket filed.")
        except Exception as e:  # noqa: BLE001 - retried by the next tick
            self.set(req["id"], last_error=f"{type(e).__name__}: {e}"[:300])
            self.audit(req["id"], "apply_failed", error=str(e)[:300])
            return "Applying failed; it will be retried automatically."

    def activate(self, exc_id, note) -> str:
        req = self.get(exc_id)
        if req["type"] == "allow_binary":
            note += f" Deploy: {self.deploy.pull()}."
        self.set(exc_id, status="active", activated_at=iso(self.clock()))
        self.audit(exc_id, "active", note=note)
        extra = " On the Mac, run `sudo santactl sync` (or wait for the next sync)." if req["type"] == "allow_binary" else ""
        self.mm.dm(req["requester_mm"], f"**{exc_id}** approved by {req['approver_email']} and active until "
                                        f"**{req['expires_at']}**. {note}{extra}")
        return note

    # ---------------------------------------------------------------- 5. daily job
    def tick(self) -> dict:
        now, done = self.clock(), {"activated": 0, "reminded": 0, "expired": 0}
        for r in self.q("SELECT * FROM requests WHERE status = 'approved'"):
            if r["grant_pr"] and self.gh.is_merged(r["grant_pr"]):
                self.activate(r["id"], f"PR #{r['grant_pr']} merged.")
                done["activated"] += 1
            elif not r["grant_pr"] or r["last_error"]:
                self.apply(r)
        for r in self.q("SELECT * FROM requests WHERE status = 'active'"):
            expires = parse(r["expires_at"])
            lead = min(timedelta(days=3), timedelta(minutes=r["minutes"]) / 2)
            if not r["reminded"] and now >= expires - lead and now < expires:
                self.mm.dm(r["requester_mm"], f"Reminder: **{r['id']}** expires at **{r['expires_at']}**. "
                                              f"If you still need it, request it again with /exception (counted as a renewal).")
                self.set(r["id"], reminded=1)
                self.audit(r["id"], "reminded")
                done["reminded"] += 1
            if now >= expires:
                self.revoke(r)
                done["expired"] += 1
        for r in self.q("SELECT * FROM requests WHERE status = 'expiring'"):
            if self.gh.is_merged(r["revoke_pr"]):
                self.finish_expiry(r, f"Removal PR #{r['revoke_pr']} merged.")
        return done

    def revoke(self, r):
        t = self.cfg["types"][r["type"]]
        try:
            if t["apply"] == "santa_rule":
                path = f"santa/rules/{r['device']}.toml"
                current, _ = self.gh.read(path)
                pr = self.gh.change_file_pr(path, santa_rules.revoke_exception(current, r["id"], r["target"], iso(self.clock())),
                                            f"exception/{r['id'].lower()}-expire", f"Expire exception {r['id']}",
                                            f"{r['id']} reached its end date ({r['expires_at']}). Removes the allow rule.")
                self.set(r["id"], status="expiring", revoke_pr=pr)
                self.audit(r["id"], "revoke_pr_opened", pr=pr)
                if self.gh.try_merge(pr):
                    self.finish_expiry(self.get(r["id"]), f"Removal PR #{pr} merged.")
            elif t["apply"] == "opa_waiver":
                self.waivers.remove(r["id"])
                self.finish_expiry(r, "Waiver removed from the access policy data.")
            else:
                self.tickets.file(f"REMOVE local admin on {r['device']} from {r['requester_email']} ({r['id']} expired)",
                                  exception=r["id"])
                self.finish_expiry(r, "IT ticket filed to remove admin rights.")
        except Exception as e:  # noqa: BLE001 - next tick tries again
            self.set(r["id"], last_error=f"{type(e).__name__}: {e}"[:300])
            self.audit(r["id"], "revoke_failed", error=str(e)[:300])

    def finish_expiry(self, r, note):
        if r["type"] == "allow_binary":
            note += f" Deploy: {self.deploy.pull()}."
        self.set(r["id"], status="expired")
        self.audit(r["id"], "expired", note=note)
        msg = f"**{r['id']}** expired and was removed automatically. {note}"
        self.mm.dm(r["requester_mm"], msg)
        self.mm.dm(r["approver_mm"], msg)

    # ---------------------------------------------------------------- 6. dashboard
    def dashboard(self) -> dict:
        now, rows = self.clock(), self.q("SELECT * FROM requests ORDER BY created_at DESC")
        open_rows = [r for r in rows if r["status"] in OPEN]
        for r in rows:
            r["age_hours"] = round((now - parse(r["created_at"])).total_seconds() / 3600, 1)
            r["renewals"] = self._renewals(r, rows)
        by_type = {}
        for r in open_rows:
            by_type[r["type"]] = by_type.get(r["type"], 0) + 1
        return {"open": open_rows, "closed": [r for r in rows if r["status"] not in OPEN][:20], "by_type": by_type,
                "total": len(rows), "renewals": sum(1 for r in rows if r["renewal_of"]),
                "denied": sum(1 for r in rows if r["status"] == "denied")}

    @staticmethod
    def _renewals(r, rows):
        by_id, n, cur = {x["id"]: x for x in rows}, 0, r
        while cur and cur["renewal_of"]:
            n, cur = n + 1, by_id.get(cur["renewal_of"])
        return n
