"""Tests for the mock HR system. Run:  cd jml/hr && python -m pytest -q"""
import os
import tempfile
import time

os.environ["HR_DB"] = os.path.join(tempfile.mkdtemp(), "hr.sqlite")
os.environ["HR_ADMIN_KEY"] = "test-admin-key"
os.environ["HR_WEBHOOK_SECRET"] = "test-secret"
os.environ["HR_WEBHOOK_URL"] = ""  # no delivery in tests; we read the outbox instead

import json  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import app as hr  # noqa: E402
from signing import sign, verify  # noqa: E402

client = TestClient(hr.app)
ADMIN = {"X-HR-Admin-Key": "test-admin-key"}
ALICE = {"name": "Alice Ng", "email": "Alice@lumenai.test", "department": "engineering",
         "title": "Engineer", "manager_email": "mgr@lumenai.test", "start_date": "2026-12-01"}


def last_event():
    r = hr.CONN.execute("SELECT body FROM events ORDER BY rowid DESC LIMIT 1").fetchone()
    return json.loads(r["body"])


def test_writes_need_admin_key():
    assert client.post("/employees/hire", json=ALICE).status_code == 401


def test_hire_transfer_terminate_rehire_emit_events():
    r = client.post("/employees/hire", json=ALICE, headers=ADMIN)
    assert r.status_code == 201
    emp = r.json()["employee"]
    assert emp["email"] == "alice@lumenai.test" and emp["status"] == "active"
    ev = last_event()
    assert ev["type"] == "employee.hired" and ev["id"].startswith("evt_") and ev["data"]["rehire"] is False

    r = client.post(f"/employees/{emp['id']}/transfer", json={"department": "research", "title": "Researcher"},
                    headers=ADMIN)
    assert r.json()["changes"]["department"] == {"from": "engineering", "to": "research"}
    assert last_event()["type"] == "employee.moved"

    r = client.post(f"/employees/{emp['id']}/terminate", json={"end_date": "2027-01-31", "reason": "resigned"},
                    headers=ADMIN)
    assert r.json()["employee"]["status"] == "terminated"
    assert last_event()["type"] == "employee.terminated"
    assert client.post(f"/employees/{emp['id']}/terminate", json={"end_date": "2027-01-31"},
                       headers=ADMIN).status_code == 409

    r = client.post(f"/employees/{emp['id']}/rehire", headers=ADMIN, json={
        "department": "engineering", "title": "Senior Engineer", "start_date": "2027-06-01"})
    assert r.json()["employee"]["status"] == "active" and last_event()["data"]["rehire"] is True


def test_duplicate_email_rejected():
    client.post("/employees/hire", json={**ALICE, "email": "bob@lumenai.test", "name": "Bob"}, headers=ADMIN)
    r = client.post("/employees/hire", json={**ALICE, "email": "bob@lumenai.test", "name": "Bob"}, headers=ADMIN)
    assert r.status_code == 409


def test_every_event_id_is_unique():
    ids = [r["id"] for r in hr.CONN.execute("SELECT id FROM events")]
    assert len(ids) == len(set(ids)) > 0


def test_signature_roundtrip_and_tampering():
    body = b'{"type":"employee.hired"}'
    header = sign("s3cret", body)
    assert verify("s3cret", body, header) == (True, "ok")
    assert verify("s3cret", body + b" ", header)[0] is False          # body changed
    assert verify("wrong", body, header)[0] is False                    # wrong secret
    assert verify("s3cret", body, "garbage")[0] is False                # malformed
    old = sign("s3cret", body, timestamp=int(time.time()) - 3600)
    assert verify("s3cret", body, old)[0] is False                      # replayed an hour later


def test_contractor_needs_end_date_and_conversion_clears_it():
    c = {**ALICE, "email": "cara@lumenai.test", "name": "Cara", "employment_type": "contractor"}
    assert client.post("/employees/hire", json=c, headers=ADMIN).status_code == 422
    r = client.post("/employees/hire", json={**c, "end_date": "2027-03-31"}, headers=ADMIN)
    emp = r.json()["employee"]
    assert emp["end_date"] == "2027-03-31"
    r = client.post(f"/employees/{emp['id']}/transfer", json={"employment_type": "full_time"}, headers=ADMIN)
    assert r.json()["employee"]["end_date"] is None
    assert r.json()["changes"]["end_date"] == {"from": "2027-03-31", "to": None}
