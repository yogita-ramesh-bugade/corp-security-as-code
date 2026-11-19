"""Label the evaluation set yourself: the answer key (Project 4, Step 4.5).

    python -m governance.eval.label            # continue where you stopped
    python -m governance.eval.label --stats    # how many done, and your label mix

Keys: a = approve, d = deny, e = escalate, then Enter. Add a short note after the letter if you
want ("d unknown vendor wants mail"). s = skip for now, u = undo the last label, q = quit.
Each answer is saved immediately to governance/eval/labels.jsonl, so you can stop any time.

This tool never shows model output, and it won't start until RUBRIC.md says "Status: FINAL".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import textwrap
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ITEMS, LABELS, RUBRIC = HERE / "items.jsonl", HERE / "labels.jsonl", HERE / "RUBRIC.md"
KEYS = {"a": "approve", "d": "deny", "e": "escalate"}


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def current_labels(path: Path) -> dict[str, dict]:
    """Latest label per item; an 'undo' line removes the label before it."""
    out: dict[str, dict] = {}
    for row in load(path):
        if row.get("undo"):
            out.pop(row["id"], None)
        else:
            out[row["id"]] = row
    return out


def rubric_fingerprint(path: Path) -> str:
    text = path.read_text()
    if "Status: FINAL" not in text:
        raise SystemExit("RUBRIC.md isn't final yet. Read it, edit it until it says what you would decide, "
                         "then change 'Status: DRAFT' to 'Status: FINAL'.")
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def card(it: dict, n: int, total: int) -> str:
    d, r = it.get("details") or {}, it["risk"]
    lines = [f"\n[{n}/{total}]  {it['name']}   ({it['item_type']})",
             f"  publisher: {it.get('publisher') or 'unknown'}     owner: {it.get('owner') or 'nobody'}     users: {it.get('users')}",
             f"  scopes:    {', '.join(it.get('scopes') or []) or 'none'}",
             f"  risk:      {r['score']}/100 {r['level']}  <- " + "; ".join(
                 [f["why"] for f in r["factors"] if f["points"] > 0][:4]),
             f"  policy:    {it['decision']['decision']} ({it['decision']['why']})"]
    for k in ("kind", "model", "data", "human_in_the_loop", "callback_urls", "url", "unpacked", "holder_kind"):
        if k in d:
            lines.append(f"  {k + ':':10} {d[k]}")
    if d.get("description"):
        lines.append("  text:      " + "\n             ".join(textwrap.wrap(str(d["description"]), 90)))
    return "\n".join(lines)


def main(argv=None, inp=input) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", default=str(ITEMS))
    ap.add_argument("--labels", default=str(LABELS))
    ap.add_argument("--rubric", default=str(RUBRIC))
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args(argv)
    items, labels_path = load(Path(a.items)), Path(a.labels)
    done = current_labels(labels_path)
    if a.stats:
        c = Counter(v["human"] for v in done.values())
        print(f"{len(done)}/{len(items)} labeled: " + ", ".join(f"{k} {c[k]}" for k in ("approve", "deny", "escalate")))
        return 0
    fp = rubric_fingerprint(Path(a.rubric))
    history: list[str] = []
    todo = [it for it in items if it["id"] not in done]
    i = 0
    while i < len(todo):
        it = todo[i]
        print(card(it, len(done) + 1, len(items)))
        ans = inp("  a/d/e [note], s skip, u undo, q quit > ").strip()
        key, _, note = ans.partition(" ")
        key = key.lower()
        if key == "q":
            break
        if key == "s":
            i += 1
            continue
        if key == "u":
            if not history:
                print("  nothing to undo in this session")
                continue
            last = history.pop()
            with open(labels_path, "a") as f:
                f.write(json.dumps({"id": last, "undo": True}) + "\n")
            done.pop(last, None)
            todo.insert(i, next(x for x in items if x["id"] == last))
            continue
        if key not in KEYS:
            print("  use a, d or e (or s, u, q)")
            continue
        row = {"id": it["id"], "item_type": it["item_type"], "human": KEYS[key], "note": note.strip(),
               "rubric": fp, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        with open(labels_path, "a") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        done[it["id"]] = row
        history.append(it["id"])
        i += 1
    left = len(items) - len(done)
    print(f"\n{len(done)}/{len(items)} labeled" + (f", {left} to go" if left else ". All done."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
