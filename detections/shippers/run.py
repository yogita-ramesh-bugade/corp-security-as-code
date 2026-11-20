"""Run all log shippers every 30 seconds (Project 4, Step 4.6).

    python -m detections.shippers.run            # keep running (leave it in its own Terminal tab)
    python -m detections.shippers.run --once     # one pass, then exit

Needs the same settings as the governance collector: source ~/jml-secrets/governance.env
(KC_URL, KC_COLLECTOR_SECRET, MM_URL, MM_ADMIN_TOKEN, FLEET_URL, FLEET_COLLECTOR_TOKEN).
Writes ~/lab-data/logs/{keycloak,fleet,mattermost}.jsonl for Filebeat.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime

from detections.shippers import fleet, keycloak, mattermost


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--every", type=int, default=30, help="seconds between passes")
    a = ap.parse_args(argv)
    shippers = {"keycloak": keycloak.make(), "fleet": fleet.make(), "mattermost": mattermost.make()}
    while True:
        parts = []
        for name, s in shippers.items():
            try:
                parts.append(f"{name} {s.poll()}")
                if getattr(s, "skipped", None):
                    parts[-1] += f" (skipped: {', '.join(s.skipped)})"
                    s.skipped.clear()
            except Exception as e:  # noqa: BLE001 - one broken source shouldn't stop the others
                parts.append(f"{name} FAILED {type(e).__name__}: {str(e)[:100]}")
        print(f"{datetime.now():%H:%M:%S}  " + "  |  ".join(parts), flush=True)
        if a.once:
            return 0
        time.sleep(a.every)


if __name__ == "__main__":
    raise SystemExit(main())
