"""Decide inventory items by policy; leave the rest for a human (Project 4, Step 4.3).

    python -m governance.decide                     # decide all, write out/decisions.jsonl, print coverage
    python -m governance.decide --queue             # list what a human still has to look at
    python -m governance.decide review "MailMerge Pro" deny "mail access for a mail-merge tool; use the approved one"
    python -m governance.decide suggest             # same human call 3+ times -> a draft rule for policy.yaml

Order of a decision:
  1. a policy DENY rule      (always wins: a past human approval can't hide a known-bad item)
  2. a human decision        (governance/reviews/decisions.jsonl; only while the item's scopes are unchanged)
  3. the other policy rules  (review-always rules, then approve rules; first match wins)
  4. nothing matched         -> review queue
"""
from __future__ import annotations

import argparse
import fnmatch
import getpass
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

from governance import score

HERE = Path(__file__).resolve().parent
POLICY = HERE / "policy.yaml"
REVIEWS = HERE / "reviews" / "decisions.jsonl"
OUT = HERE / "out"
SUGGEST_AFTER = 3


def load_policy(path: Path = POLICY) -> dict:
    return yaml.safe_load(Path(path).read_text())


def publisher_status(item: dict, risk_rules: dict) -> str:
    pub = item.get("publisher")
    if pub == "internal":
        return "internal"
    if not pub or pub.lower().startswith("unknown"):
        return "unknown"
    return "verified" if pub in risk_rules["factors"]["unverified_publisher"]["verified_publishers"] else "unverified"


def signature(item: dict, risk_rules: dict) -> str:
    """What a human actually judged: the kind of item, who made it, and exactly what it can do."""
    return "|".join([item["item_type"], publisher_status(item, risk_rules), ",".join(sorted(item.get("scopes") or []))])


def _any(scope: str, patterns) -> bool:
    return any(fnmatch.fnmatchcase(scope, p) for p in patterns)


def matches(when: dict, item: dict, ctx: dict) -> bool:
    scopes = item.get("scopes") or []
    for key, want in when.items():
        if key == "type":
            ok = item["item_type"] in want
        elif key == "publisher":
            ok = ctx["publisher"] in want
        elif key == "scopes_any":
            ok = any(_any(s, want) for s in scopes)
        elif key == "scopes_only":
            ok = all(_any(s, want) for s in scopes)
        elif key == "extension_ids":
            ok = (item.get("details") or {}).get("extension_id") in (ctx["lists"].get(want) or [])
        elif key == "min_score":
            ok = ctx["score"] >= want
        elif key == "max_score":
            ok = ctx["score"] <= want
        elif key == "owner_left":
            ok = ctx["owner_left"] == want
        elif key == "has_owner":
            ok = bool(item.get("owner")) == want
        elif key == "details":
            ok = all((item.get("details") or {}).get(k) == v for k, v in want.items())
        else:
            raise ValueError(f"unknown condition '{key}' in policy.yaml")
        if not ok:
            return False
    return True


def load_reviews(path: Path = REVIEWS) -> dict[str, dict]:
    """Latest human decision per item id."""
    latest = {}
    if Path(path).exists():
        for line in Path(path).read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                latest[r["id"]] = r
    return latest


def decide_item(item: dict, policy: dict, risk_rules: dict, reviews: dict) -> dict:
    ctx = {"publisher": publisher_status(item, risk_rules), "score": item["risk"]["score"],
           "lists": policy.get("lists") or {},
           "owner_left": any(f["factor"] == "owner_left" for f in item["risk"]["factors"])}
    first = next((r for r in policy["rules"] if matches(r["when"], item, ctx)), None)
    if first and first["decision"] == "deny":
        return {"decision": "deny", "by": "policy", "rule": first["id"], "why": first["why"]}
    human = reviews.get(item["id"])
    note = None
    if human:
        if human["signature"] == signature(item, risk_rules):
            return {"decision": human["decision"], "by": "human", "rule": None,
                    "why": f"{human['reviewer']} on {human['at'][:10]}: {human['reason']}"}
        note = f"scopes or publisher changed since {human['reviewer']}'s review on {human['at'][:10]}"
    if first:
        return {"decision": first["decision"], "by": "policy", "rule": first["id"], "why": first["why"]}
    return {"decision": "review", "by": "nobody", "rule": None, "why": note or "no rule decides this"}


def coverage(decided: list[dict]) -> dict:
    total = len(decided)
    by_policy = sum(1 for d in decided if d["decision"]["by"] == "policy" and d["decision"]["decision"] != "review")
    by_human = sum(1 for d in decided if d["decision"]["by"] == "human")
    return {"total": total, "policy": by_policy, "human": by_human, "queue": total - by_policy - by_human,
            "policy_pct": round(100 * by_policy / total, 1) if total else 0.0}


def record_review(path, item: dict, decision: str, reason: str, reviewer: str, now: datetime, risk_rules: dict) -> dict:
    """Append one human decision. Used by the CLI and by the Mattermost buttons (Step 4.4)."""
    if decision not in ("approve", "deny"):
        raise ValueError(decision)
    rec = {"id": item["id"], "name": item["name"], "decision": decision, "reason": reason, "reviewer": reviewer,
           "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "signature": signature(item, risk_rules)}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


def suggest(reviews: dict, items_by_id: dict, risk_rules: dict, after: int = SUGGEST_AFTER) -> list[dict]:
    """Group human calls by (decision, item type, publisher status). 3+ of the same -> a draft rule."""
    groups = defaultdict(list)
    for r in reviews.values():
        it = items_by_id.get(r["id"])
        if not it:
            continue
        groups[(r["decision"], it["item_type"], publisher_status(it, risk_rules))].append((r, it))
    drafts = []
    for (decision, t, pub), rows in sorted(groups.items()):
        if len(rows) < after:
            continue
        scopes = sorted({s for _, it in rows for s in it.get("scopes") or []})
        when = {"type": [t], "publisher": [pub]}
        owned = {bool(it.get("owner")) for _, it in rows}
        if len(owned) == 1:
            when["has_owner"] = owned.pop()
        left = {any(f["factor"] == "owner_left" for f in it["risk"]["factors"]) for _, it in rows}
        if len(left) == 1:
            when["owner_left"] = left.pop()
        if decision == "deny":
            common = sorted(set.intersection(*(set(it.get("scopes") or []) for _, it in rows)))
            when["scopes_any"] = common or scopes
        else:
            when["scopes_only"] = scopes
            when["max_score"] = max(it["risk"]["score"] for _, it in rows)
        drafts.append({"id": f"{decision}-{t}-{pub}-DRAFT", "decision": decision,
                       "why": "DRAFT from human reviews: " + "; ".join(sorted({r["reason"] for r, _ in rows}))[:200],
                       "when": when, "_based_on": sorted(it["name"] for _, it in rows)})
    return drafts


def _load_items(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def _find(items, key):
    hits = [i for i in items if key in (i["id"], i["name"]) or i["id"].endswith(":" + key)]
    if len(hits) != 1:
        raise SystemExit(f"'{key}' matches {len(hits)} items; use the full id")
    return hits[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", nargs="?", default="decide", choices=["decide", "review", "suggest"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--inventory", default=str(OUT / "inventory.jsonl"))
    ap.add_argument("--out", default=str(OUT / "decisions.jsonl"))
    ap.add_argument("--policy", default=str(POLICY))
    ap.add_argument("--reviews", default=str(REVIEWS))
    ap.add_argument("--now", help="YYYY-MM-DD, for repeatable scores")
    ap.add_argument("--queue", action="store_true", help="list the items a human still has to decide")
    ap.add_argument("--by", default=getpass.getuser(), help="reviewer name for 'review'")
    a = ap.parse_args(argv)

    now = score._when(a.now) if a.now else datetime.now(timezone.utc)
    risk_rules, policy = score.load_rules(), load_policy(a.policy)
    items = _load_items(a.inventory)
    reviews = load_reviews(a.reviews)
    scored = score.score_all(items, risk_rules, now)
    by_id = {i["id"]: i for i in scored}

    if a.command == "review":
        if len(a.args) != 3 or a.args[1] not in ("approve", "deny"):
            raise SystemExit('usage: review <name or id> approve|deny "reason"')
        it = _find(scored, a.args[0])
        record_review(a.reviews, it, a.args[1], a.args[2], a.by, now, risk_rules)
        print(f"recorded: {a.by} {a.args[1]}d {it['name']}")
        same = [d for d in suggest(load_reviews(a.reviews), by_id, risk_rules)
                if d["decision"] == a.args[1] and it["name"] in d["_based_on"]]
        if same:
            print(f"  you've made this call {len(same[0]['_based_on'])} times: run 'python -m governance.decide suggest'")
        return 0

    if a.command == "suggest":
        drafts = suggest(reviews, by_id, risk_rules)
        if not drafts:
            print(f"no human call repeated {SUGGEST_AFTER}+ times yet ({len(reviews)} reviews recorded)")
            return 0
        print("# Draft rules. Read them, tighten them, then paste into governance/policy.yaml (deny rules at the top).")
        for d in drafts:
            print(f"# based on: {', '.join(d.pop('_based_on'))}")
            print(yaml.safe_dump([d], sort_keys=False, width=120))
        return 0

    decided = [{**it, "decision": decide_item(it, policy, risk_rules, reviews)} for it in scored]
    with open(a.out, "w") as f:
        for d in decided:
            f.write(json.dumps(d, sort_keys=True) + "\n")
    c = coverage(decided)
    if a.queue:
        print(f"Review queue: {c['queue']} items (highest risk first)")
        for d in decided:
            if d["decision"]["decision"] == "review":
                top = "; ".join([f["why"] for f in d["risk"]["factors"] if f["points"] > 0][:2])
                print(f"  {d['risk']['score']:3} {d['item_type']:17} {d['name'][:30]:30} {d['decision']['why'][:40]:40} {top}")
        return 0
    print(f"Decided {c['total']} items -> {a.out}")
    print(f"  by policy alone: {c['policy']:4}  ({c['policy_pct']}%)")
    print(f"  by a human:      {c['human']:4}")
    print(f"  review queue:    {c['queue']:4}")
    rows = Counter((d["item_type"], d["decision"]["decision"]) for d in decided)
    print("\n  type               approve  deny  review")
    for t in sorted({d["item_type"] for d in decided}):
        print(f"  {t:18} {rows[(t, 'approve')]:7} {rows[(t, 'deny')]:5} {rows[(t, 'review')]:7}")
    rules = Counter(d["decision"]["rule"] for d in decided if d["decision"]["rule"])
    print("\n  rule hits:")
    for r, n in rules.most_common():
        print(f"    {n:4}  {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
