"""Edit Santa rule files (santa/rules/*.toml) for exceptions, as plain text so comments survive.

A machine's own file (santa/rules/<machine-id>.toml) REPLACES global.toml for that Mac in Moroz,
so the first exception for a machine starts its file as a copy of global.toml.

Granting adds a marked block:
    # exception EXC-0001 | requester ... | approver ... | expires 2026-12-01T10:00:00Z
    [[rules]]
    rule_type = "BINARY"
    policy = "ALLOWLIST"
    ...
    # end EXC-0001

Revoking swaps that block for a REMOVE rule. Santa deletes a rule it already has only when the
server sends REMOVE; simply dropping the rule from the file would leave it on the Mac.
"""
from __future__ import annotations

import re

SHA256 = re.compile(r"^[0-9a-f]{64}$")


def grant_block(exc_id: str, sha256: str, requester: str, approver: str, expires_at: str) -> str:
    if not SHA256.match(sha256):
        raise ValueError("not a SHA-256 hash")
    return (f"\n# exception {exc_id} | requester {requester} | approver {approver} | expires {expires_at}\n"
            f"[[rules]]\n"
            f'rule_type = "BINARY"\n'
            f'policy = "ALLOWLIST"\n'
            f'identifier = "{sha256}"\n'
            f'custom_msg = "Allowed by exception {exc_id} until {expires_at}"\n'
            f"# end {exc_id}\n")


def add_exception(current: str | None, global_toml: str, block: str) -> str:
    base = current if current is not None else (
        "# Per-machine Santa config, started from global.toml by the exception bot.\n" + global_toml)
    return base.rstrip("\n") + "\n" + block


def revoke_exception(current: str, exc_id: str, sha256: str, revoked_at: str) -> str:
    pattern = re.compile(rf"\n# exception {re.escape(exc_id)} \|.*?# end {re.escape(exc_id)}\n", re.S)
    if not pattern.search(current):
        raise KeyError(f"{exc_id} not found in rule file")
    removal = (f"\n# revoked {exc_id} at {revoked_at}: REMOVE tells Santa to delete the rule it has.\n"
               f"# Safe to delete this block once every Mac has synced (e.g. after 30 days).\n"
               f"[[rules]]\n"
               f'rule_type = "BINARY"\n'
               f'policy = "REMOVE"\n'
               f'identifier = "{sha256}"\n'
               f"# end revoked {exc_id}\n")
    return pattern.sub(lambda _m: removal, current, count=1)
