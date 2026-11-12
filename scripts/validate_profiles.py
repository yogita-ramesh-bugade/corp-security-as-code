#!/usr/bin/env python3
"""Validate every macOS profile (.mobileconfig) and DDM declaration (.json) in the repo.

Fails (exit 1) if a file doesn't parse, is missing required keys, or reuses
another file's identifier or UUID. Run from the repo root:
  python3 scripts/validate_profiles.py
"""
import json
import plistlib
import sys
from pathlib import Path

SEARCH = [Path("fleet/profiles"), Path("browser/out/macos")]
errors, seen_ids, seen_uuids = [], {}, {}


def note(kind, value, path):
    table = seen_ids if kind == "identifier" else seen_uuids
    if value in table:
        errors.append(f"{path}: duplicate {kind} {value} (also in {table[value]})")
    table[value] = path


def check_profile(path):
    try:
        data = plistlib.loads(path.read_bytes())
    except Exception as exc:  # malformed XML, wrong encoding, etc.
        errors.append(f"{path}: not a valid plist ({exc})")
        return
    for key in ("PayloadIdentifier", "PayloadUUID", "PayloadType", "PayloadDisplayName", "PayloadContent"):
        if key not in data:
            errors.append(f"{path}: missing {key}")
    if data.get("PayloadType") != "Configuration":
        errors.append(f"{path}: top-level PayloadType must be 'Configuration'")
    note("identifier", data.get("PayloadIdentifier"), path)
    note("uuid", data.get("PayloadUUID"), path)
    for i, payload in enumerate(data.get("PayloadContent") or []):
        for key in ("PayloadType", "PayloadIdentifier", "PayloadUUID"):
            if key not in payload:
                errors.append(f"{path}: payload {i} missing {key}")
        note("uuid", payload.get("PayloadUUID"), path)


def check_declaration(path):
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        errors.append(f"{path}: not valid JSON ({exc})")
        return
    for key in ("Type", "Identifier", "Payload"):
        if key not in data:
            errors.append(f"{path}: missing {key}")
    note("identifier", data.get("Identifier"), path)


files = []
for root in SEARCH:
    if root.exists():
        files += sorted(root.rglob("*.mobileconfig"))
        files += sorted(p for p in root.rglob("*.json"))
for f in files:
    (check_profile if f.suffix == ".mobileconfig" else check_declaration)(f)

if errors:
    print("Profile validation FAILED:")
    print("\n".join(f"  - {e}" for e in errors))
    sys.exit(1)
print(f"Profile validation passed: {len(files)} files checked.")
