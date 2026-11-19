"""Internal apps and AI agents, from the YAML registry (governance/registry/agents and /synthetic)."""
from __future__ import annotations

from pathlib import Path

import yaml

from governance.record import Item

REGISTRY = Path(__file__).resolve().parent.parent / "registry"
REQUIRED = ("name", "owner", "model", "tools", "oauth_scopes", "data", "last_review")


def collect_internal_agents(root: Path = REGISTRY) -> list[Item]:
    items = []
    for f in sorted([*(root / "agents").glob("*.yaml"), *(root / "synthetic").glob("*.yaml")]):
        a = yaml.safe_load(f.read_text())
        missing = [k for k in REQUIRED if k not in a]
        if missing:
            raise ValueError(f"{f.name} is missing {missing}")
        scopes = list(a.get("oauth_scopes") or []) + [f"tool:{t}" for t in a.get("tools") or []] + \
                 [f"mcp:{m}" for m in a.get("mcp_servers") or []]
        items.append(Item(
            item_type="internal_agent", id=f"internal_agent:registry:{a['name']}", name=a["name"],
            publisher="internal", scopes=scopes, users=0, first_seen=str(a.get("created") or "") or None,
            last_used=None, owner=a.get("owner"), source="registry",
            details={"model": a.get("model"), "data": a.get("data", []), "team": a.get("team"),
                     "human_in_the_loop": a.get("human_in_the_loop"), "last_review": str(a["last_review"]),
                     "creator": a.get("creator"), "creator_left_company": a.get("creator_left_company", False),
                     "synthetic": a.get("synthetic", False), "file": f"{f.parent.name}/{f.name}"}))
    return items
