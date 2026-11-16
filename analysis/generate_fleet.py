#!/usr/bin/env python3
"""Generate a synthetic macOS fleet and four weeks of program-execution events.

Used to plan a Santa monitor-to-lockdown rollout (Project 1B). Everything here is
SIMULATED; see analysis/README.md for every assumption.

Usage:
  python3 analysis/generate_fleet.py                 # defaults: 3000 devices, seed 42
  python3 analysis/generate_fleet.py --devices 500 --seed 7

Outputs (gitignored, regenerate any time):
  analysis/data/devices.csv
  analysis/data/execution_events.csv.gz
"""
import argparse
import csv
import gzip
import hashlib
import random
import string
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data"
WEEKS = 4

TEAMS = {  # team: share of devices
    "Engineering": 0.35,
    "Research": 0.15,
    "Sales": 0.20,
    "Finance": 0.10,
    "Support": 0.20,
}

# Apps every team member gets (company standard build). Real product names,
# but their Team IDs below are SYNTHETIC.
STANDARD = ["Google Chrome", "Slack", "Zoom", "1Password", "Microsoft Outlook",
            "Microsoft Teams", "Nudge", "Santa"]

TEAM_APPS = {
    "Engineering": ["Visual Studio Code", "Docker Desktop", "iTerm2", "Postman",
                    "JetBrains GoLand", "JetBrains PyCharm", "Wireshark", "GitHub Desktop"],
    "Research":    ["Visual Studio Code", "Docker Desktop", "RStudio", "Anaconda Navigator",
                    "Jupyter Desktop", "MATLAB", "Zotero"],
    "Sales":       ["Salesforce", "Gong", "Microsoft PowerPoint", "Calendly", "LinkedIn Sales"],
    "Finance":     ["Microsoft Excel", "NetSuite Connector", "Tableau", "DocuSign", "Expensify"],
    "Support":     ["Zendesk", "Intercom", "Loom", "Microsoft Word", "Snagit"],
}

# Probability a team member uses each kind of hard case
P_HOMEBREW = {"Engineering": 0.92, "Research": 0.70, "Sales": 0.05, "Finance": 0.03, "Support": 0.10}
P_DEVBUILD = {"Engineering": 0.65, "Research": 0.35, "Sales": 0.0, "Finance": 0.0, "Support": 0.02}

HOMEBREW = ["jq", "ripgrep", "fd", "wget", "htop", "tmux", "gh", "kubectl", "helm", "terraform",
            "awscli", "go", "node", "python@3.12", "rust", "cmake", "ffmpeg", "imagemagick",
            "git-lfs", "watch", "tree", "nmap", "redis", "postgresql@16", "openssl@3", "pyenv",
            "direnv", "fzf", "bat", "httpie", "yq", "shellcheck", "pre-commit", "tflint",
            "k9s", "minikube", "colima", "sops", "age", "duckdb"]

INTERNAL_TOOLS = {  # tool: teams that use it
    "lumen-vpn-helper": list(TEAMS),
    "lumen-cli": ["Engineering", "Research"],
    "lumen-deploy": ["Engineering"],
    "datasync-agent": ["Research", "Finance"],
    "ticket-macro-runner": ["Support"],
    "quote-builder": ["Sales"],
}

SUSPICIOUS = [  # (path, devices affected, runs per week)
    ("~/Downloads/Invoice_Viewer", 2, 1),
    ("/tmp/.cache/update_helper", 1, 30),
    ("~/Downloads/ChromeUpdate", 3, 1),
    ("~/Library/Application Support/.sysd/sysd", 1, 60),
    ("~/Downloads/zoom_installer_patch", 1, 2),
]


def sha(*parts):
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()


def team_id(rng):
    return "".join(rng.choice(string.ascii_uppercase + string.digits) for _ in range(10))


def build_catalog(rng):
    """Return {app_name: dict(team_id, signing_id, popularity)} for signed apps."""
    named = STANDARD + sorted({a for apps in TEAM_APPS.values() for a in apps})
    vendors = [team_id(rng) for _ in range(1600)]
    catalog = {}
    for i, name in enumerate(named):
        catalog[name] = {"team_id": vendors[i], "popularity": 0.0, "kind": "standard_or_team"}
    # ~300 common apps with Zipf-like popularity
    for i in range(300):
        catalog[f"CommonApp {i:03d}"] = {"team_id": vendors[100 + i // 3],
                                         "popularity": 0.30 / (1 + i) ** 0.8, "kind": "common"}
    # ~4000 long-tail apps from ~1200 vendors, each rare
    for i in range(4000):
        catalog[f"RareApp {i:04d}"] = {"team_id": vendors[400 + rng.randrange(1200)],
                                       "popularity": rng.uniform(0.0002, 0.003), "kind": "rare"}
    for name, app in catalog.items():
        bundle = "com." + name.lower().replace(" ", "").replace("@", "")
        app["signing_id"] = f"{app['team_id']}:{bundle}"
        app["path"] = f"/Applications/{name}.app/Contents/MacOS/{name.split()[0]}"
    return catalog


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--devices", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    catalog = build_catalog(rng)
    common = [n for n, a in catalog.items() if a["kind"] == "common"]
    rare = [n for n, a in catalog.items() if a["kind"] == "rare"]
    OUT.mkdir(exist_ok=True)

    # Devices
    devices = []
    for i in range(args.devices):
        team = rng.choices(list(TEAMS), weights=TEAMS.values())[0]
        devices.append({"device_id": f"LUM-MAC-{i:05d}", "user": f"user{i:05d}", "team": team})
    with open(OUT / "devices.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["device_id", "user", "team"])
        w.writeheader()
        w.writerows(devices)

    # Signed apps get a new version (new hash, same Team ID/Signing ID) ~12% of weeks
    version = {name: 1 for name in catalog}
    weekly_versions = []
    for _ in range(WEEKS):
        weekly_versions.append(dict(version))
        for name in version:
            if rng.random() < 0.25:
                version[name] += 1

    fields = ["week", "device_id", "user", "team", "category", "file_name", "path", "sha256",
              "signed", "team_id", "signing_id", "count"]
    stats = Counter()
    with gzip.open(OUT / "execution_events.csv.gz", "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()

        def emit(week, d, category, name, path, digest, signed, tid, sid, count):
            w.writerow({"week": week, "device_id": d["device_id"], "user": d["user"],
                        "team": d["team"], "category": category, "file_name": name,
                        "path": path, "sha256": digest, "signed": "yes" if signed else "no",
                        "team_id": tid, "signing_id": sid, "count": count})
            stats[category] += 1

        for d in devices:
            team = d["team"]
            home = f"/Users/{d['user']}"
            apps = set(STANDARD) | set(TEAM_APPS[team])
            apps |= {n for n in common if rng.random() < catalog[n]["popularity"] * 2.2}
            apps |= set(rng.sample(rare, k=min(len(rare), rng.choice([0, 1, 1, 2, 3, 4]))))
            brew = rng.sample(HOMEBREW, k=rng.randint(4, 18)) if rng.random() < P_HOMEBREW[team] else []
            devbuilds = ([f"{home}/go/bin/{rng.choice(['svc', 'tool', 'mock', 'gen', 'cli'])}-{j}"
                          for j in range(rng.randint(1, 3))] +
                         ([f"{home}/.cargo/bin/rs-util"] if rng.random() < 0.3 else []) +
                         ([f"{home}/src/project/target/debug/app"] if rng.random() < 0.3 else [])
                         if rng.random() < P_DEVBUILD[team] else [])
            internal = [t for t, teams in INTERNAL_TOOLS.items() if team in teams and rng.random() < 0.8]

            for week in range(1, WEEKS + 1):
                vers = weekly_versions[week - 1]
                for name in sorted(apps):
                    a = catalog[name]
                    if a["kind"] == "rare" and rng.random() < 0.5:
                        continue  # rare apps aren't used every week
                    emit(week, d, a["kind"] if a["kind"] != "standard_or_team" else "standard_app",
                         name, a["path"], sha(name, vers[name]), True, a["team_id"], a["signing_id"],
                         rng.randint(5, 60))
                for formula in brew:
                    # Homebrew bottles are ad-hoc signed: no Team ID, version bumps monthly
                    emit(week, d, "homebrew", formula, f"/opt/homebrew/bin/{formula}",
                         sha("brew", formula, 1 if week < 3 else 2), False, "", "", rng.randint(1, 40))
                for path in devbuilds:
                    # Self-compiled: unique per device AND rebuilt (new hash) every week
                    emit(week, d, "dev_build", path.rsplit("/", 1)[-1], path,
                         sha(d["device_id"], path, week), False, "", "", rng.randint(3, 80))
                for tool in internal:
                    # Unsigned internal tools: same hash fleet-wide, new release in week 3
                    emit(week, d, "internal_unsigned", tool, f"/usr/local/bin/{tool}",
                         sha("internal", tool, 1 if week < 3 else 2), False, "", "", rng.randint(1, 15))

        # A few genuinely suspicious binaries on random devices
        for path, n_devices, runs in SUSPICIOUS:
            for d in rng.sample(devices, n_devices):
                p = path.replace("~", f"/Users/{d['user']}")
                week = rng.randint(1, WEEKS)
                emit(week, d, "suspicious", p.rsplit("/", 1)[-1], p, sha("bad", path), False, "", "", runs)

    print(f"devices: {len(devices)}  ->  {OUT / 'devices.csv'}")
    print(f"event rows: {sum(stats.values())}  ->  {OUT / 'execution_events.csv.gz'}")
    for category, n in stats.most_common():
        print(f"  {category:18} {n:>8} rows")


if __name__ == "__main__":
    main()
