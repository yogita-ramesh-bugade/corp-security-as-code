"""The one record shape every collector produces (Project 4, Step 4.1).

Because OAuth grants, chat apps, browser extensions, admin roles and agents all become the
same kind of record, every later step (scoring, policy, LLM triage, detections) works on
all of them at once.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

ITEM_TYPES = ("oauth_grant", "chat_app", "browser_extension", "admin_role", "internal_agent")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Item:
    item_type: str                 # one of ITEM_TYPES
    id: str                        # stable, e.g. "oauth_grant:keycloak:free-pdf-converter"
    name: str
    publisher: str | None          # vendor / author / creator; None = unknown
    scopes: list[str]              # scopes, permissions or roles it holds
    users: int                     # how many people it touches (consents, installs, holders)
    first_seen: str | None         # earliest evidence we have (ISO time)
    last_used: str | None          # latest evidence of use, if the source tells us
    owner: str | None              # accountable person inside Lumen; None = nobody
    source: str                    # which system reported it
    details: dict = field(default_factory=dict)  # anything source-specific (who, where, extra fields)

    def __post_init__(self):
        if self.item_type not in ITEM_TYPES:
            raise ValueError(f"unknown item_type {self.item_type}")
        self.scopes = sorted(set(self.scopes))

    def to_dict(self) -> dict:
        return asdict(self)


def ms_to_iso(ms) -> str | None:
    """Keycloak and Mattermost give times as milliseconds since 1970."""
    if not ms:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
