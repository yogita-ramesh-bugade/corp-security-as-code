"""Load and check jml/roles.yaml, and work out a person's birthright access.

    from rules import load_rules, birthright
    rules = load_rules()
    birthright(rules, {"department": "engineering", "title": "Engineering Manager",
                       "employment_type": "full_time"})
    -> {"keycloak_groups": [...], "chat_channels": [...], "device": "macbook-pro"}

The engine (Step 3.3) calls birthright() for every person and makes reality match it.
`python rules.py` checks the file and prints what each department gets.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROLES_FILE = HERE / "roles.yaml"
TERRAFORM_MAIN = HERE.parent / "access-gate" / "terraform" / "main.tf"
HR_DEPARTMENTS = {"engineering", "research", "sales", "it", "finance", "people", "legal"}  # jml/hr/app.py
EMPLOYMENT_TYPES = {"full_time", "contractor", "intern"}


class RulesError(ValueError):
    pass


def terraform_groups(path: Path = TERRAFORM_MAIN) -> set[str]:
    """Group names in the `groups = { ... }` map of the Keycloak Terraform."""
    text = path.read_text()
    block = re.search(r"\bgroups\s*=\s*\{(.*?)\n\s*\}", text, re.S)
    if not block:
        raise RulesError(f"no groups map found in {path}")
    return set(re.findall(r'"([a-z0-9-]+)"\s*=', block.group(1)))


def _all_groups(rules: dict) -> set[str]:
    groups = set(rules["everyone"].get("keycloak_groups", []))
    for d in rules["departments"].values():
        groups |= set(d.get("keycloak_groups", []))
    for t in rules.get("titles", []):
        groups |= set(t.get("keycloak_groups", []))
    for e in rules["employment_types"].values():
        groups |= set(e.get("add_keycloak_groups", [])) | set(e.get("remove_keycloak_groups", []))
    return groups


def validate(rules: dict, known_groups: set[str] | None = None) -> list[str]:
    """Return a list of problems (empty = OK)."""
    problems = []
    depts = set(rules.get("departments", {}))
    if missing := HR_DEPARTMENTS - depts:
        problems.append(f"HR departments with no birthright entry: {sorted(missing)}")
    if extra := depts - HR_DEPARTMENTS:
        problems.append(f"departments HR doesn't have: {sorted(extra)}")
    for name, d in rules.get("departments", {}).items():
        if not d.get("owner"):
            problems.append(f"department {name} has no owner")
        if d.get("device") not in rules.get("devices", {}):
            problems.append(f"department {name} uses unknown device {d.get('device')!r}")
    if set(rules.get("employment_types", {})) != EMPLOYMENT_TYPES:
        problems.append(f"employment_types must be exactly {sorted(EMPLOYMENT_TYPES)}")

    birthright_groups = _all_groups(rules) - {g for e in rules["employment_types"].values()
                                              for g in e.get("remove_keycloak_groups", [])}
    if bad := birthright_groups & set(rules.get("privileged_groups", [])):
        problems.append(f"privileged groups must never be birthright: {sorted(bad)}")
    if known_groups is not None and (unknown := _all_groups(rules) - known_groups):
        problems.append(f"groups not defined in Terraform: {sorted(unknown)}")

    for name, r in rules.get("requestable", {}).items():
        for field in ("kind", "approver", "max_days", "description"):
            if not r.get(field):
                problems.append(f"requestable {name} is missing {field}")
        if not isinstance(r.get("max_days"), int) or not 1 <= r["max_days"] <= 365:
            problems.append(f"requestable {name}: max_days must be 1-365")
    for p in rules.get("privileged_groups", []):
        if p not in rules.get("requestable", {}):
            problems.append(f"privileged group {p} has no requestable entry (no way to get it)")
    return problems


def load_rules(path: Path = ROLES_FILE, check_terraform: bool = True) -> dict:
    rules = yaml.safe_load(path.read_text())
    known = terraform_groups() if check_terraform and TERRAFORM_MAIN.exists() else None
    if problems := validate(rules, known):
        raise RulesError("roles.yaml problems:\n  - " + "\n  - ".join(problems))
    return rules


def birthright(rules: dict, employee: dict) -> dict:
    dept = employee["department"]
    if dept not in rules["departments"]:
        raise RulesError(f"no birthright rule for department {dept!r}")
    d = rules["departments"][dept]
    groups = set(rules["everyone"].get("keycloak_groups", [])) | set(d.get("keycloak_groups", []))
    channels = set(rules["everyone"].get("chat_channels", [])) | set(d.get("chat_channels", []))

    title = (employee.get("title") or "").lower()
    for t in rules.get("titles", []):
        if fnmatch.fnmatch(dept, t["department"]) and fnmatch.fnmatch(title, t["title"].lower()):
            groups |= set(t.get("keycloak_groups", []))
            channels |= set(t.get("chat_channels", []))

    e = rules["employment_types"][employee.get("employment_type", "full_time")]
    if e.get("requires_end_date") and not employee.get("end_date"):
        raise RulesError(f"{employee.get('email', 'employee')}: {employee.get('employment_type')} needs an end date")
    groups = (groups | set(e.get("add_keycloak_groups", []))) - set(e.get("remove_keycloak_groups", []))
    channels -= set(e.get("remove_chat_channels", []))

    return {"keycloak_groups": sorted(groups), "chat_channels": sorted(channels), "device": d["device"]}


if __name__ == "__main__":
    r = load_rules()
    print("roles.yaml OK\n")
    for dept in sorted(r["departments"]):
        b = birthright(r, {"department": dept, "title": "", "employment_type": "full_time"})
        print(f"{dept:12} groups={','.join(b['keycloak_groups']):32} channels={','.join(b['chat_channels'])}"
              f"  device={b['device']}")
