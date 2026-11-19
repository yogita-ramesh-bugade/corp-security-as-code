"""JML engine service: receives HR webhooks and runs the reconciler (Project 3, Step 3.3).

  POST /webhook   verify signature -> drop duplicates -> reconcile -> 200
                  (503 if a system was down: HR retries, and the retry loop also finishes the job)
Background: retries pending events every 30 s; full nightly reconciliation every NIGHTLY_SECONDS.

CLI (inside the container):
  python app.py nightly                      reconcile everyone now and list orphan accounts
  python app.py assign-device <emp_id> <serial>   IT handed over a laptop: record + map it in Fleet
  python app.py grant <emp_id> <item> <days> <approver>   add requested access (until the bot exists)
  python app.py leaver-times                 time from termination to last access removed
  python app.py audit-verify                 check the audit log's hash chain
  python app.py inbox                        recent events and their status
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent), str(HERE.parent / "hr")]  # local runs; Docker copies them flat

import yaml  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from connectors import FileChat, FileTickets, FleetClient, HRClient, KeycloakAdmin  # noqa: E402
from core import Audit, Engine, Store, iso  # noqa: E402
from rules import load_rules  # noqa: E402
from signing import verify  # noqa: E402

DATA = Path(os.environ.get("DATA_DIR", "/data"))
DATA.mkdir(parents=True, exist_ok=True)
SECRET = os.environ.get("HR_WEBHOOK_SECRET", "")
NIGHTLY_SECONDS = int(os.environ.get("NIGHTLY_SECONDS", "86400"))
NON_HR = set(yaml.safe_load(Path(os.environ.get("NON_HR_ACCOUNTS", HERE / "non_hr_accounts.yaml")).read_text())
             ["accounts"])


def build_engine() -> Engine:
    rules = load_rules(Path(os.environ.get("ROLES_FILE", HERE.parent / "roles.yaml")), check_terraform=False)
    return Engine(
        rules=rules,
        hr=HRClient(os.environ.get("HR_URL", "http://hr:8100")),
        keycloak=KeycloakAdmin(os.environ.get("KC_URL", "http://keycloak.lumen.test:8081"), "lumen",
                               os.environ.get("KC_CLIENT_ID", "jml-engine"), os.environ.get("KC_CLIENT_SECRET", "")),
        chat=FileChat(DATA / "chat.json"),
        fleet=FleetClient(os.environ.get("FLEET_URL", ""), os.environ.get("FLEET_API_TOKEN", ""),
                          can_lock=os.environ.get("FLEET_CAN_LOCK", "false") == "true"),
        tickets=FileTickets(DATA / "tickets.jsonl"),
        store=Store(DATA / "engine.sqlite"),
        audit=Audit(DATA / "audit.jsonl"),
    )


ENGINE = build_engine()
app = FastAPI(title="Lumen JML engine", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.body()
    ok, why = verify(SECRET, body, request.headers.get("X-HR-Signature", ""))
    if not ok:
        ENGINE.audit.log(request.headers.get("X-HR-Event-Id", "?"), "webhook_rejected", "-", "denied", reason=why)
        return JSONResponse({"error": why}, status_code=401)
    result = ENGINE.receive(json.loads(body))
    return JSONResponse({"result": result}, status_code=503 if result == "pending" else 200)


def background() -> None:
    last_nightly = time.time()
    while True:
        time.sleep(30)
        try:
            ENGINE.retry_pending()
            if time.time() - last_nightly > NIGHTLY_SECONDS:
                last_nightly = time.time()
                print(json.dumps({"nightly": ENGINE.nightly(NON_HR)}), flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"background error: {e}", flush=True)


threading.Thread(target=background, daemon=True).start()


def cli(argv: list[str]) -> None:
    e = ENGINE
    if argv[:1] == ["nightly"]:
        print(json.dumps(e.nightly(NON_HR), indent=2))
    elif argv[:1] == ["assign-device"] and len(argv) == 3:
        emp = e.hr.get(argv[1])
        e.store.q("INSERT INTO devices (employee_id, device_type, serial, recorded_at) VALUES (?, ?, ?, ?) "
                  "ON CONFLICT(employee_id) DO UPDATE SET serial = excluded.serial", argv[1], "assigned", argv[2],
                  iso(datetime.now(timezone.utc)))
        e.reconcile(argv[1], "assign-device")
        print(f"{emp['email']} now owns {argv[2]} (Fleet mapping updated)")
    elif argv[:1] == ["grant"] and len(argv) == 5:
        item, days, approver = argv[2], int(argv[3]), argv[4]
        spec = e.rules["requestable"][item]
        if days > spec["max_days"]:
            sys.exit(f"{item} can be granted for at most {spec['max_days']} days")
        expires = iso(datetime.now(timezone.utc) + timedelta(days=days))
        e.store.q("INSERT INTO grants (employee_id, item, kind, approver, expires_at) VALUES (?, ?, ?, ?, ?)",
                  argv[1], item, spec["kind"], approver, expires)
        e.audit.log("manual-grant", "grant.add", argv[1], item=item, approver=approver, expires_at=expires)
        e.reconcile(argv[1], "manual-grant")
        print(f"granted {item} to {argv[1]} until {expires}")
    elif argv[:1] == ["leaver-times"]:
        rows = e.store.q("SELECT employee_id, started_at, completed_at, seconds FROM offboarding "
                         "WHERE completed_at IS NOT NULL ORDER BY completed_at")
        for r in rows:
            print(f"{r['employee_id']}: termination {r['started_at']} -> all access removed {r['completed_at']}"
                  f"  = {r['seconds']:.1f} s")
        print("No leavers yet." if not rows else f"Slowest: {max(r['seconds'] for r in rows):.1f} s (target < 300 s)")
    elif argv[:1] == ["audit-verify"]:
        print(e.audit.verify()[1])
    elif argv[:1] == ["inbox"]:
        for r in e.store.q("SELECT event_id, type, employee_id, status, attempts, last_error FROM inbox "
                           "ORDER BY received_at DESC LIMIT 15"):
            print(r)
    else:
        print(__doc__)


if __name__ == "__main__":
    cli(sys.argv[1:])
