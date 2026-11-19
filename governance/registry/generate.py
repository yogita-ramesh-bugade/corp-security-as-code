"""Generate the synthetic long tail: a few hundred small internal apps people built with AI tools.

Real companies have many of these: a script someone vibe-coded, a Slack summarizer, a
spreadsheet bot. Most are harmless; some quietly hold broad scopes, have no owner, or haven't
been reviewed in a year. Seeded, so every run produces the same set.

    python -m governance.registry.generate            # writes governance/registry/synthetic/*.yaml
    python -m governance.registry.generate --count 300 --seed 42
"""
from __future__ import annotations

import argparse
import random
import shutil
from datetime import date, timedelta
from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parent / "synthetic"
TEAMS = {"engineering": 0.35, "research": 0.2, "sales": 0.15, "finance": 0.08, "people": 0.07, "it": 0.1, "legal": 0.05}
VERBS = ["summarize", "triage", "draft", "sync", "export", "tag", "translate", "classify", "digest", "remind"]
OBJECTS = ["standup-notes", "tickets", "invoices", "pr-comments", "meeting-notes", "leads", "contracts",
           "survey-results", "oncall-pages", "expense-reports", "eval-results", "datasets", "release-notes"]
MODELS = ["claude-haiku (hosted API)", "claude-sonnet (hosted API)", "gpt-style hosted model",
          "llama-3.1-8b (local, Ollama)", "mistral-7b (local)", "unknown"]
TOOLS = ["chat_post", "chat_read", "drive_read", "drive_write", "email_send", "email_read", "repo_read",
         "repo_push", "ticket_read", "ticket_write", "crm_read", "web_fetch", "shell_exec", "db_query"]
SCOPES = {"chat_read": "chat.read", "chat_post": "chat.write", "drive_read": "files.read",
          "drive_write": "files.readwrite", "email_send": "mail.send", "email_read": "mail.read",
          "repo_read": "repo.read", "repo_push": "repo", "ticket_read": "tickets.read",
          "ticket_write": "tickets.write", "crm_read": "crm.read", "db_query": "db.read"}
DATA = ["internal_docs", "source_code", "customer_pii", "financials", "chat_history", "datasets", "public"]
PEOPLE = ["alice", "bob", "ivan", "tara", "omar", "maya", "dana", "priya", "sam", "lee"]
LEFT = {"dana", "priya", "lee"}  # former employees (Project 3 leavers)


def make(i: int, rng: random.Random, today: date) -> dict:
    team = rng.choices(list(TEAMS), weights=list(TEAMS.values()))[0]
    tools = rng.sample(TOOLS, k=rng.choices([1, 2, 3, 4, 5], weights=[30, 30, 20, 12, 8])[0])
    creator = rng.choice(PEOPLE)
    owner = None if rng.random() < 0.12 else f"{creator}@lumenai.test"  # ~12% never had an owner recorded
    created = today - timedelta(days=rng.randint(5, 600))
    reviewed = created + timedelta(days=rng.randint(0, max(0, (today - created).days)))
    if rng.random() < 0.4:
        reviewed = created  # never reviewed since creation
    return {
        "name": f"{rng.choice(VERBS)}-{rng.choice(OBJECTS)}-{i:03d}",
        "description": "AI-built internal helper (synthetic long tail).",
        "owner": owner,
        "creator": f"{creator}@lumenai.test",
        "creator_left_company": creator in LEFT,
        "team": team,
        "model": rng.choice(MODELS),
        "tools": tools,
        "mcp_servers": rng.sample(["gdrive-mcp", "mail-mcp", "github-mcp", "chat-mcp", "db-mcp", "browser-mcp"],
                                  k=rng.choice([0, 0, 1, 1, 2])),
        "oauth_scopes": sorted({SCOPES[t] for t in tools if t in SCOPES}),
        "data": sorted(set(rng.sample(DATA, k=rng.choice([1, 1, 2, 3])))),
        "human_in_the_loop": rng.random() < 0.55,
        "created": created.isoformat(),
        "last_review": reviewed.isoformat(),
        "synthetic": True,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--today", default="2026-11-19", help="fixed date so the output is reproducible")
    a = ap.parse_args()
    rng, today = random.Random(a.seed), date.fromisoformat(a.today)
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir()
    for i in range(1, a.count + 1):
        app = make(i, rng, today)
        (OUT / f"{app['name']}.yaml").write_text(yaml.safe_dump(app, sort_keys=False))
    print(f"wrote {a.count} synthetic apps to {OUT} (seed {a.seed})")


if __name__ == "__main__":
    main()
