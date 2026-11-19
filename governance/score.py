"""Score every inventory item 0-100, with the reasons written down (Project 4, Step 4.2).

    python -m governance.score                          # reads out/inventory.jsonl, writes out/scored.jsonl
    python -m governance.score --top 25
    python -m governance.score --type oauth_grant              # top list for one item type
    python -m governance.score --explain free-pdf-converter   # full breakdown for one item (name or id)

All the numbers live in governance/risk.yaml. Each item gets
    risk = {"score": 0-100, "level": "low|medium|high|critical",
            "factors": [{"factor": ..., "points": ..., "why": ...}, ...]}
and the points in "factors" always add up to the score (capping is listed as its own line).
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml

HERE = Path(__file__).resolve().parent
RULES = HERE / "risk.yaml"
OUT = HERE / "out"


def load_rules(path: Path = RULES) -> dict:
    return yaml.safe_load(Path(path).read_text())


def _when(s: str | None) -> datetime | None:
    if not s:
        return None
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def scope_rule(scope: str, rules: dict) -> tuple[int, str]:
    table = rules["scopes"]
    if scope in table:
        return tuple(table[scope])
    for pattern, rule in table.items():
        if "*" in pattern and fnmatch.fnmatchcase(scope, pattern):
            return tuple(rule)
    return tuple(rules["default_scope_points"])


def level_for(score: int, rules: dict) -> str:
    for name, floor in sorted(rules["levels"].items(), key=lambda kv: -kv[1]):
        if score >= floor:
            return name
    return "low"


def score_item(item: dict, rules: dict, now: datetime) -> dict:
    t, d = item["item_type"], item.get("details") or {}
    F = rules["factors"]
    lines: list[dict] = []

    def add(factor, points, why):
        if points:
            lines.append({"factor": factor, "points": int(points), "why": why})

    def on(name):
        return t in F[name]["applies_to"]

    # 1. What it can do. Each scope is its own line; the cap is a negative line so the sum still adds up.
    scope_total = 0
    for s in item.get("scopes") or []:
        pts, why = scope_rule(s, rules)
        add(f"scope:{s}", pts, why)
        scope_total += pts
    if scope_total > rules["scope_cap"]:
        add("scope_cap", rules["scope_cap"] - scope_total, f"permissions capped at {rules['scope_cap']} points")

    # 2. Around it.
    if on("unverified_publisher"):
        pub = item.get("publisher")
        if not pub or pub.lower().startswith("unknown"):
            add("unverified_publisher", F["unverified_publisher"]["unknown_points"], f"publisher unknown ({pub or 'not given'})")
        elif pub not in F["unverified_publisher"]["verified_publishers"]:
            add("unverified_publisher", F["unverified_publisher"]["points"], f"publisher '{pub}' not reviewed by security")
    if on("many_users"):
        tier = max((x for x in F["many_users"]["tiers"] if item.get("users", 0) >= x["min"]),
                   key=lambda x: x["min"], default=None)
        if tier:
            add("many_users", tier["points"], f"used by {item['users']} people (≥{tier['min']})")
    if on("no_owner") and not item.get("owner"):
        add("no_owner", F["no_owner"]["points"], "nobody inside Lumen is accountable for it")
    if on("external_destination"):
        urls = list(d.get("callback_urls") or []) + ([d["url"]] if d.get("url") else [])
        outside = sorted(u for u in urls if not any(fnmatch.fnmatchcase(urlsplit(u).hostname or "", h)
                                                    for h in F["external_destination"]["internal_hosts"]))
        if outside:
            add("external_destination", F["external_destination"]["points"], "sends data outside Lumen: " + ", ".join(outside))
    if on("owner_left"):
        left = F["owner_left"]["former_employees"]
        if item.get("owner") in left:
            add("owner_left", F["owner_left"]["points"], f"owner {item['owner']} has left the company")
        elif d.get("creator_left_company") or d.get("creator") in left:
            add("owner_left", F["owner_left"]["points"], f"built by {d.get('creator')}, who has left the company")
    if on("unused_90_days") and (last := _when(item.get("last_used"))):
        days = (now - last).days
        if days >= F["unused_90_days"]["days"]:
            add("unused_90_days", F["unused_90_days"]["points"], f"not used in {days} days: access nobody needs")
    if on("not_reviewed") and (rev := _when(d.get("last_review"))):
        days = (now - rev).days
        if days >= F["not_reviewed"]["days"]:
            add("not_reviewed", F["not_reviewed"]["points"], f"last security review {days} days ago")
    if on("sensitive_data"):
        table = F["sensitive_data"]["data"]
        hits = {x: table[x] for x in d.get("data") or [] if x in table}
        if hits:
            pts = min(sum(hits.values()), F["sensitive_data"]["cap"])
            add("sensitive_data", pts, "touches " + ", ".join(sorted(hits)))
    if on("acts_without_human") and d.get("human_in_the_loop") is False:
        acting = sorted({s[5:] for s in item.get("scopes") or [] if s.startswith("tool:")}
                        & set(F["acts_without_human"]["acting_tools"]))
        if acting:
            add("acts_without_human", F["acts_without_human"]["points"],
                "acts with nobody approving: " + ", ".join(acting))

    total = sum(x["points"] for x in lines)
    if total > 100:
        add("total_cap", 100 - total, "score capped at 100")
        total = 100
    lines.sort(key=lambda x: -x["points"])
    return {"score": total, "level": level_for(total, rules), "factors": lines}


def score_all(items: list[dict], rules: dict, now: datetime) -> list[dict]:
    scored = [{**it, "risk": score_item(it, rules, now)} for it in items]
    return sorted(scored, key=lambda x: (-x["risk"]["score"], x["id"]))


def explain(item: dict) -> str:
    r = item["risk"]
    out = [f"{item['name']}  [{item['item_type']}]  score {r['score']}  ({r['level']})", f"  id: {item['id']}"]
    for f in r["factors"]:
        out.append(f"  {f['points']:+4}  {f['factor']:32} {f['why']}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", default=str(OUT / "inventory.jsonl"))
    ap.add_argument("--out", default=str(OUT / "scored.jsonl"))
    ap.add_argument("--rules", default=str(RULES))
    ap.add_argument("--now", help="score as of this date (YYYY-MM-DD), for repeatable results")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--explain", help="item name or id")
    ap.add_argument("--type", help="only show this item type in the top list (oauth_grant, chat_app, ...)")
    a = ap.parse_args(argv)
    now = _when(a.now) if a.now else datetime.now(timezone.utc)
    items = [json.loads(line) for line in Path(a.inventory).read_text().splitlines() if line.strip()]
    scored = score_all(items, load_rules(a.rules), now)

    if a.explain:
        hits = [s for s in scored if a.explain in (s["id"], s["name"]) or s["id"].endswith(":" + a.explain)]
        if not hits:
            print(f"no item named {a.explain}")
            return 1
        print("\n\n".join(explain(h) for h in hits))
        return 0

    with open(a.out, "w") as f:
        for s in scored:
            f.write(json.dumps(s, sort_keys=True) + "\n")
    levels = {}
    for s in scored:
        levels[s["risk"]["level"]] = levels.get(s["risk"]["level"], 0) + 1
    print(f"Scored {len(scored)} items -> {a.out}")
    print("  " + "  ".join(f"{k}: {levels.get(k, 0)}" for k in ("critical", "high", "medium", "low")))
    shown = [s for s in scored if not a.type or s["item_type"] == a.type]
    print(f"\nTop {a.top}{' ' + a.type if a.type else ''}:")
    for s in shown[:a.top]:
        reasons = "; ".join([f["why"] for f in s["risk"]["factors"] if f["points"] > 0][:3])
        print(f"  {s['risk']['score']:3}  {s['risk']['level']:8} {s['item_type']:17} {s['name'][:28]:28} {reasons}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
