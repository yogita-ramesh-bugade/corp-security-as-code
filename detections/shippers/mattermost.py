"""Mattermost audit records -> ~/lab-data/logs/mattermost.jsonl (Project 4, Step 4.6).

Reads GET /api/v4/audits with the admin token already used by the governance collector. Every
audit record is shipped; a role change that gives someone system_admin also becomes an
admin_role_granted event. Mattermost's legacy audit text format isn't documented in detail, so
the role check looks for "system_admin" in the record's action and extra_info; verify against
your own logs (detections/tests has the shape this was written for).
"""
from __future__ import annotations

import time

from detections.shippers.common import Sink, admin_grant, from_ms, iso


class MattermostShipper:
    def __init__(self, mm, sink: Sink):
        self.mm, self.sink = mm, sink
        self._names: dict[str, str] = {}

    def name(self, user_id: str | None) -> str | None:
        if not user_id:
            return None
        if user_id not in self._names:
            try:
                self._names[user_id] = self.mm.get(f"/users/{user_id}")["username"]
            except Exception:  # noqa: BLE001
                self._names[user_id] = user_id
        return self._names[user_id]

    def poll(self) -> int:
        out = []
        for a in sorted(self.mm.get("/audits", per_page=200), key=lambda a: a["create_at"]):
            if self.sink.seen(f"mm:{a['id']}"):
                continue
            when, info = from_ms(a["create_at"]), a.get("extra_info") or ""
            actor = self.name(a.get("user_id"))
            out.append({"@timestamp": iso(when),
                        "event": {"dataset": "lumen.mattermost", "action": a.get("action"), "kind": "event"},
                        "user": {"name": actor}, "source": {"ip": a.get("ip_address")},
                        "mattermost": {"audit": {"id": a["id"], "extra_info": info, "session_id": a.get("session_id")}}})
            if "/roles" in (a.get("action") or "") and "system_admin" in info:
                target_id = (a.get("action") or "").split("/users/")[-1].split("/")[0]
                out.append(admin_grant(when, "mattermost", "system_admin", self.name(target_id), actor))
        self.sink.write(out)
        self.sink.save()
        return len(out)


def make(log_dir=None, state_dir=None):
    from governance.collectors.mattermost import Mattermost
    return MattermostShipper(Mattermost(), Sink("mattermost", log_dir, state_dir))


if __name__ == "__main__":
    s = make()
    while True:
        print(f"mattermost: {s.poll()} events", flush=True)
        time.sleep(30)
