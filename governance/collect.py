"""Run every collector and write one inventory (Project 4, Step 4.1).

    python -m governance.collect                    # all sources -> governance/out/inventory.jsonl
    python -m governance.collect --only registry    # one source (for testing)

Settings come from environment variables (see ~/jml-secrets/governance.env):
  KC_URL, KC_COLLECTOR_SECRET            Keycloak, read-only service account
  MM_URL, MM_ADMIN_TOKEN                 Mattermost
  FLEET_URL, FLEET_COLLECTOR_TOKEN       Fleet, observer_plus API-only account
first_seen for sources that don't report it (extensions, admins) is remembered across runs
in governance/out/seen.json: the first time the inventory saw the item.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from governance.collectors import fleet, keycloak, mattermost, registry
from governance.record import ITEM_TYPES, now_iso

OUT = Path(__file__).resolve().parent / "out"


def sources():
    kc, mm, fl = keycloak.Keycloak(), mattermost.Mattermost(), fleet.Fleet()
    return {
        "keycloak_oauth": lambda: keycloak.collect_oauth_grants(kc),
        "keycloak_admins": lambda: keycloak.collect_admin_roles(kc),
        "mattermost": lambda: mattermost.collect_chat_apps(mm),
        "fleet_extensions": lambda: fleet.collect_browser_extensions(fl),
        "fleet_admins": lambda: fleet.collect_fleet_admins(fl),
        "registry": lambda: registry.collect_internal_agents(),
    }, (fl, mm)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated source names")
    ap.add_argument("--out", default=str(OUT / "inventory.jsonl"))
    a = ap.parse_args(argv)
    srcs, (fl, mm) = sources()
    wanted = a.only.split(",") if a.only else list(srcs)
    OUT.mkdir(exist_ok=True)
    seen_file = OUT / "seen.json"
    seen = json.loads(seen_file.read_text()) if seen_file.exists() else {}
    items, failed = [], []
    for name in wanted:
        try:
            got = srcs[name]()
            items += got
            print(f"  {name:18} {len(got):4} items")
        except Exception as e:  # noqa: BLE001 - one broken source shouldn't hide the others
            failed.append(name)
            print(f"  {name:18} FAILED: {type(e).__name__}: {str(e)[:120]}")
    stamp = now_iso()
    with open(a.out, "w") as f:
        for it in items:
            seen.setdefault(it.id, stamp)
            if not it.first_seen:
                it.first_seen = seen[it.id]
            f.write(json.dumps({**it.to_dict(), "collected_at": stamp}, sort_keys=True) + "\n")
    seen_file.write_text(json.dumps(seen, indent=1))
    counts = Counter(i.item_type for i in items)
    print(f"\nWrote {len(items)} items to {a.out}")
    for t in ITEM_TYPES:
        print(f"  {t:18} {counts.get(t, 0):4}")
    if fl.skipped:
        print("  skipped hosts: " + ", ".join(fl.skipped))
    if mm.skipped:
        print("  skipped chat lists: " + ", ".join(mm.skipped))
    missing = [t for t in ITEM_TYPES if not counts.get(t)]
    if missing and not a.only:
        print(f"\nMISSING item types: {missing}")
    return 1 if failed or (missing and not a.only) else 0


if __name__ == "__main__":
    sys.exit(main())
