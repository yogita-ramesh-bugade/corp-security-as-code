"""Triage the review queue with a model; optionally post it to Mattermost (Project 4, Step 4.4).

    python -m governance.decide                                  # first: refresh out/decisions.jsonl
    python -m governance.triage.run --limit 5                    # ask the model, print, write out/triage.jsonl
    python -m governance.triage.run --only "QuickNotes AI"       # one item
    python -m governance.triage.run --limit 5 --post             # also post to ~governance-review
    python -m governance.triage.run --only "QuickNotes AI" --naive   # the unsafe prompt, for comparison (never posted)
    python -m governance.triage.run --backend fixed --post --limit 1  # try the chat flow without a model

Settings (in ~/jml-secrets/governance.env): MM_URL, MM_TRIAGE_TOKEN, TRIAGE_SECRET, TRIAGE_ACTION_URL;
optional OLLAMA_URL (http://localhost:11434), OLLAMA_MODEL (llama3.1).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from governance import decide, score
from governance.triage.backends import get_backend
from governance.triage.chat import Chat, attachment
from governance.triage.triage import triage_item

OUT = Path(__file__).resolve().parent.parent / "out"


def queue(decisions_path: Path, only: str | None) -> list[dict]:
    rows = [json.loads(line) for line in Path(decisions_path).read_text().splitlines() if line.strip()]
    if only:
        return [r for r in rows if only in (r["name"], r["id"]) or r["id"].endswith(":" + only)]
    return [r for r in rows if r["decision"]["decision"] == "review"]  # already highest risk first


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decisions", default=str(OUT / "decisions.jsonl"))
    ap.add_argument("--out", default=str(OUT / "triage.jsonl"))
    ap.add_argument("--backend", default="ollama")
    ap.add_argument("--model", help="model name for the backend (default llama3.1)")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--only", help="triage one item by name or id (even if policy already decided it)")
    ap.add_argument("--post", action="store_true", help="post each result to the Mattermost review channel")
    ap.add_argument("--naive", action="store_true", help="unsafe prompt, for comparison only; never posted")
    a = ap.parse_args(argv)
    if a.post and a.naive:
        raise SystemExit("--naive results are for comparison only and are never posted")
    if a.naive and a.out == str(OUT / "triage.jsonl"):
        a.out = str(OUT / "triage_naive.jsonl")  # keep them away from the file the buttons read

    items = queue(a.decisions, a.only)[: a.limit]
    if not items:
        print("nothing to triage (run python -m governance.decide first, or check --only)")
        return 1
    backend = get_backend(a.backend, a.model)
    chat = None
    if a.post:
        chat = Chat()
        secret, action_url = os.environ["TRIAGE_SECRET"], os.environ["TRIAGE_ACTION_URL"]
    risk_rules = score.load_rules()

    print(f"{'score':>5}  {'model':8} {'conf':>4}  {'final':8} {'inj':3}  name")
    with open(a.out, "a") as f:
        for it in items:
            tri = triage_item(it, backend, naive=a.naive)
            if chat:
                tri["post_id"] = chat.post(attachment(it, tri, action_url, secret, decide.signature(it, risk_rules)))
            f.write(json.dumps(tri, sort_keys=True) + "\n")
            m = tri["model"]
            print(f"{tri['score']:5}  {m['decision']:8} {m['confidence']:4}  {tri['recommendation']:8} "
                  f"{'YES' if tri['injection'] else '-':3}  {it['name'][:40]}")
            for note in tri["guard_notes"]:
                print(f"         ! {note}")
            print(f"         {m['rationale'][:160]}")
    print(f"\nWrote {len(items)} results to {a.out}" + (" and posted them to ~governance-review" if chat else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
