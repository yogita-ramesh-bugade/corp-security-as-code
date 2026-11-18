"""Lumen AI mock HR system (Project 3, Step 3.1).

Plays the role of Workday: the official record of who works at Lumen. Every change is
written to SQLite AND to an outbox of events in the same transaction, then a background
worker delivers each event as a signed webhook, retrying until the receiver says 2xx.
(If HR saved the change but the webhook was lost, access would silently drift; the outbox
makes delivery "at least once", and the event ID lets the receiver drop duplicates.)

Endpoints (writes need the X-HR-Admin-Key header):
  POST /employees/hire                 -> employee.hired
  POST /employees/{id}/transfer        -> employee.moved      (department, title, manager, employment type)
  POST /employees/{id}/terminate       -> employee.terminated
  POST /employees/{id}/rehire          -> employee.hired      (with "rehire": true)
  GET  /employees, /employees/{id}     -> read
  GET  /events                         -> outbox with delivery status
  POST /events/{event_id}/redeliver    -> send an event again (to test duplicate handling)
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from signing import sign

DB_PATH = Path(os.environ.get("HR_DB", "/data/hr.sqlite"))
WEBHOOK_URL = os.environ.get("HR_WEBHOOK_URL", "")
WEBHOOK_SECRET = os.environ.get("HR_WEBHOOK_SECRET", "")
ADMIN_KEY = os.environ.get("HR_ADMIN_KEY", "")
RETRY_SECONDS = [2, 5, 15, 60, 300]  # back off, then keep trying every 5 minutes

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
Department = Literal["engineering", "research", "sales", "it", "finance", "people", "legal"]
EmploymentType = Literal["full_time", "contractor", "intern"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
  department TEXT NOT NULL, title TEXT NOT NULL, manager_email TEXT,
  employment_type TEXT NOT NULL, status TEXT NOT NULL,          -- active | terminated
  start_date TEXT NOT NULL, end_date TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, type TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL,
  delivered_at TEXT, attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
  last_error TEXT
);
"""

_lock = threading.Lock()


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


CONN = db()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r else None


# ---------------------------------------------------------------- models

class Hire(BaseModel):
    name: str
    email: str
    department: Department
    title: str
    manager_email: Optional[str] = None
    employment_type: EmploymentType = "full_time"
    start_date: date

    @field_validator("email", "manager_email")
    @classmethod
    def _email(cls, v):
        if v is not None and not EMAIL.match(v):
            raise ValueError("not an email address")
        return v.lower() if v else v


class Transfer(BaseModel):
    department: Optional[Department] = None
    title: Optional[str] = None
    manager_email: Optional[str] = None
    employment_type: Optional[EmploymentType] = None
    effective_date: date = Field(default_factory=date.today)


class Terminate(BaseModel):
    end_date: date
    reason: Literal["resigned", "dismissed", "contract_ended", "other"] = "other"


class Rehire(BaseModel):
    department: Department
    title: str
    manager_email: Optional[str] = None
    employment_type: EmploymentType = "full_time"
    start_date: date


# ---------------------------------------------------------------- outbox

def emit(conn: sqlite3.Connection, event_type: str, employee: dict, **extra) -> dict:
    """Queue an event in the SAME transaction as the HR change (transactional outbox)."""
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": event_type,
        "occurred_at": now_iso(),
        "data": {"employee": employee, **extra},
    }
    conn.execute("INSERT INTO events (id, type, body, created_at) VALUES (?, ?, ?, ?)",
                 (event["id"], event_type, json.dumps(event, sort_keys=True), event["occurred_at"]))
    return event


def deliver(event_id: str) -> None:
    with _lock:
        ev = row(CONN.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone())
    body = ev["body"].encode()
    error = None
    try:
        r = httpx.post(WEBHOOK_URL, content=body, timeout=10, headers={
            "Content-Type": "application/json",
            "X-HR-Event-Id": ev["id"],
            "X-HR-Event-Type": ev["type"],
            "X-HR-Signature": sign(WEBHOOK_SECRET, body),
        })
        if not 200 <= r.status_code < 300:
            error = f"HTTP {r.status_code}"
    except httpx.HTTPError as e:
        error = type(e).__name__
    with _lock:
        attempts = ev["attempts"] + 1
        if error is None:
            CONN.execute("UPDATE events SET delivered_at = ?, attempts = ?, last_error = NULL WHERE id = ?",
                         (now_iso(), attempts, ev["id"]))
        else:
            wait = RETRY_SECONDS[min(attempts - 1, len(RETRY_SECONDS) - 1)]
            CONN.execute("UPDATE events SET attempts = ?, last_error = ?, next_attempt = ? WHERE id = ?",
                         (attempts, error, time.time() + wait, ev["id"]))
        CONN.commit()


def delivery_worker() -> None:
    while True:
        if WEBHOOK_URL:
            with _lock:
                due = [r["id"] for r in CONN.execute(
                    "SELECT id FROM events WHERE delivered_at IS NULL AND next_attempt <= ? ORDER BY created_at",
                    (time.time(),))]
            for event_id in due:
                deliver(event_id)
        time.sleep(1)


# ---------------------------------------------------------------- API

@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=delivery_worker, daemon=True).start()
    yield


app = FastAPI(title="Lumen mock HR", version="1.0", lifespan=lifespan)


def require_admin(x_hr_admin_key: str = Header("")) -> None:
    if not ADMIN_KEY or x_hr_admin_key != ADMIN_KEY:
        raise HTTPException(401, "missing or wrong X-HR-Admin-Key")


def get_employee(conn, emp_id: str) -> dict:
    e = row(conn.execute("SELECT * FROM employees WHERE id = ?", (emp_id,)).fetchone())
    if not e:
        raise HTTPException(404, "no such employee")
    return e


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/employees/hire", status_code=201, dependencies=[Depends(require_admin)])
def hire(h: Hire):
    with _lock:
        if CONN.execute("SELECT 1 FROM employees WHERE email = ?", (h.email,)).fetchone():
            raise HTTPException(409, "email already exists; use /rehire for a former employee")
        n = CONN.execute("SELECT COUNT(*) FROM employees").fetchone()[0] + 1
        emp = {"id": f"E{n:04d}", "name": h.name, "email": h.email, "department": h.department,
               "title": h.title, "manager_email": h.manager_email, "employment_type": h.employment_type,
               "status": "active", "start_date": h.start_date.isoformat(), "end_date": None}
        CONN.execute("INSERT INTO employees VALUES (:id, :name, :email, :department, :title, :manager_email, "
                     ":employment_type, :status, :start_date, :end_date)", emp)
        event = emit(CONN, "employee.hired", emp, rehire=False)
        CONN.commit()
    return {"employee": emp, "event_id": event["id"]}


@app.post("/employees/{emp_id}/transfer", dependencies=[Depends(require_admin)])
def transfer(emp_id: str, t: Transfer):
    with _lock:
        before = get_employee(CONN, emp_id)
        if before["status"] != "active":
            raise HTTPException(409, "only active employees can be transferred")
        updates = {k: v for k, v in t.model_dump(exclude={"effective_date"}).items() if v is not None}
        changes = {k: {"from": before[k], "to": v} for k, v in updates.items() if before[k] != v}
        if not changes:
            raise HTTPException(400, "nothing changes")
        for k, v in updates.items():
            CONN.execute(f"UPDATE employees SET {k} = ? WHERE id = ?", (v, emp_id))  # k is from the model, not user text
        after = get_employee(CONN, emp_id)
        event = emit(CONN, "employee.moved", after, changes=changes, effective_date=t.effective_date.isoformat())
        CONN.commit()
    return {"employee": after, "changes": changes, "event_id": event["id"]}


@app.post("/employees/{emp_id}/terminate", dependencies=[Depends(require_admin)])
def terminate(emp_id: str, t: Terminate):
    with _lock:
        e = get_employee(CONN, emp_id)
        if e["status"] == "terminated":
            raise HTTPException(409, "already terminated")
        CONN.execute("UPDATE employees SET status = 'terminated', end_date = ? WHERE id = ?",
                     (t.end_date.isoformat(), emp_id))
        e = get_employee(CONN, emp_id)
        event = emit(CONN, "employee.terminated", e, reason=t.reason)
        CONN.commit()
    return {"employee": e, "event_id": event["id"]}


@app.post("/employees/{emp_id}/rehire", dependencies=[Depends(require_admin)])
def rehire(emp_id: str, r: Rehire):
    with _lock:
        e = get_employee(CONN, emp_id)
        if e["status"] != "terminated":
            raise HTTPException(409, "only former employees can be rehired")
        CONN.execute("UPDATE employees SET status = 'active', end_date = NULL, department = ?, title = ?, "
                     "manager_email = ?, employment_type = ?, start_date = ? WHERE id = ?",
                     (r.department, r.title, r.manager_email, r.employment_type, r.start_date.isoformat(), emp_id))
        e = get_employee(CONN, emp_id)
        event = emit(CONN, "employee.hired", e, rehire=True)
        CONN.commit()
    return {"employee": e, "event_id": event["id"]}


@app.get("/employees")
def list_employees(status: Optional[str] = None):
    with _lock:
        q, args = "SELECT * FROM employees", ()
        if status:
            q, args = q + " WHERE status = ?", (status,)
        return [dict(r) for r in CONN.execute(q + " ORDER BY id", args)]


@app.get("/employees/{emp_id}")
def read_employee(emp_id: str):
    with _lock:
        return get_employee(CONN, emp_id)


@app.get("/events")
def list_events(limit: int = 20):
    with _lock:
        rows = CONN.execute("SELECT id, type, created_at, delivered_at, attempts, last_error FROM events "
                            "ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]


@app.post("/events/{event_id}/redeliver", dependencies=[Depends(require_admin)])
def redeliver(event_id: str):
    """Send the same event (same ID) again. Receivers must recognise and ignore the duplicate."""
    with _lock:
        if not CONN.execute("SELECT 1 FROM events WHERE id = ?", (event_id,)).fetchone():
            raise HTTPException(404, "no such event")
        CONN.execute("UPDATE events SET delivered_at = NULL, next_attempt = 0 WHERE id = ?", (event_id,))
        CONN.commit()
    return {"queued": event_id}
