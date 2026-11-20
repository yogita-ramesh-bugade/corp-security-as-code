"""Shared helpers for the log shippers (Project 4, Step 4.6).

Shippers poll each system's API, turn what they find into one JSON line per event with the
same field names everywhere (ECS-style: @timestamp, event.dataset, event.action, user.name, ...),
and append to ~/lab-data/logs/<source>.jsonl. Filebeat tails those files into Elasticsearch.
Each shipper remembers what it already sent in ~/lab-data/shipper-state/<source>.json.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

HERE = Path(__file__).resolve().parent.parent
LOG_DIR = Path(os.environ.get("LAB_LOG_DIR", Path.home() / "lab-data" / "logs"))
STATE_DIR = Path(os.environ.get("LAB_STATE_DIR", Path.home() / "lab-data" / "shipper-state"))
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def from_ms(ms) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, timezone.utc)


def parse(s: str) -> datetime:
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def in_change_window(when: datetime, path: Path = HERE / "change_windows.yaml") -> bool:
    cfg = yaml.safe_load(Path(path).read_text())
    local = when.astimezone(ZoneInfo(cfg["timezone"]))
    hhmm = local.strftime("%H:%M")
    return any(DAYS[local.weekday()] in w["days"] and w["start"] <= hhmm < w["end"] for w in cfg["windows"])


def admin_grant(when: datetime, system: str, role: str, target: str | None, actor: str | None, **extra) -> dict:
    """The one shape every system's admin grant becomes, so one Sigma rule covers them all."""
    return {"@timestamp": iso(when),
            "event": {"dataset": f"lumen.{system}", "action": "admin_role_granted", "kind": "event",
                      "category": ["iam"], "type": ["admin", "change"]},
            "user": {"name": actor, "target": {"name": target}},
            "lumen": {"admin": {"system": system, "role": role}, "change_window": in_change_window(when)},
            **extra}


class Sink:
    """Appends events to the log file; remembers state between runs."""

    def __init__(self, source: str, log_dir: Path | None = None, state_dir: Path | None = None):
        self.log = Path(log_dir or LOG_DIR) / f"{source}.jsonl"
        self.state_file = Path(state_dir or STATE_DIR) / f"{source}.json"
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        self.written = 0

    def write(self, events: list[dict]) -> None:
        with open(self.log, "a") as f:
            for e in events:
                f.write(json.dumps(e, sort_keys=True) + "\n")
        self.written += len(events)

    def save(self) -> None:
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state))
        tmp.replace(self.state_file)

    def seen(self, key: str, limit: int = 20000) -> bool:
        """True if this event id was already shipped; otherwise remember it."""
        ids = self.state.setdefault("seen", [])
        if key in ids:
            return True
        ids.append(key)
        del ids[:-limit]
        return False
