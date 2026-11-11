#!/usr/bin/env python3
"""Render browser/policy.yaml into Chrome policy files for Linux, macOS and Windows.

Usage:
  python3 browser/render.py          # write files to browser/out/
  python3 browser/render.py --check  # exit 1 if browser/out/ is stale (for CI)
"""
import json
import plistlib
import sys
import uuid
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "policy.yaml"
OUT = HERE / "out"
NAMESPACE = uuid.UUID("6f1d2a8e-5b3c-4e7a-9c0d-1a2b3c4d5e6f")  # fixed, so UUIDs are stable


def load_policies():
    data = yaml.safe_load(SOURCE.read_text())
    policies = data.get("policies") or {}
    if not isinstance(policies, dict) or not policies:
        sys.exit("policy.yaml: 'policies' must be a non-empty mapping")
    for name, value in policies.items():
        if not isinstance(value, (bool, int, str, list)):
            sys.exit(f"policy.yaml: {name} has unsupported type {type(value).__name__}")
    return policies


def render_linux(p):
    return json.dumps(p, indent=2, sort_keys=True) + "\n"


def render_macos(p):
    stable = lambda label: str(uuid.uuid5(NAMESPACE, label)).upper()
    payload = {
        "PayloadType": "com.google.Chrome",
        "PayloadIdentifier": "com.lumenai.chrome.settings",
        "PayloadUUID": stable("chrome-settings"),
        "PayloadVersion": 1,
        "PayloadDisplayName": "Chrome settings",
        **p,
    }
    profile = {
        "PayloadContent": [payload],
        "PayloadDisplayName": "Lumen AI - Chrome",
        "PayloadDescription": "Chrome browser policy, generated from browser/policy.yaml.",
        "PayloadIdentifier": "com.lumenai.chrome",
        "PayloadOrganization": "Lumen AI",
        "PayloadScope": "System",
        "PayloadType": "Configuration",
        "PayloadUUID": stable("chrome-profile"),
        "PayloadVersion": 1,
    }
    return plistlib.dumps(profile, sort_keys=True).decode()


def render_windows(p):
    base = r"HKLM:\SOFTWARE\Policies\Google\Chrome"
    lines = [
        "# Lumen AI - Chrome policy for Windows. Generated from browser/policy.yaml; do not edit by hand.",
        "$ErrorActionPreference = 'Stop'",
        f"$base = '{base}'",
        "New-Item -Path $base -Force | Out-Null",
    ]
    for name, value in sorted(p.items()):
        if isinstance(value, list):
            lines.append(f"Remove-Item -Path \"$base\\{name}\" -Recurse -Force -ErrorAction SilentlyContinue")
            lines.append(f"New-Item -Path \"$base\\{name}\" -Force | Out-Null")
            for i, item in enumerate(value, start=1):
                lines.append(f"New-ItemProperty -Path \"$base\\{name}\" -Name '{i}' -Value '{item}' -PropertyType String -Force | Out-Null")
        elif isinstance(value, bool):
            lines.append(f"New-ItemProperty -Path $base -Name '{name}' -Value {int(value)} -PropertyType DWord -Force | Out-Null")
        elif isinstance(value, int):
            lines.append(f"New-ItemProperty -Path $base -Name '{name}' -Value {value} -PropertyType DWord -Force | Out-Null")
        else:
            lines.append(f"New-ItemProperty -Path $base -Name '{name}' -Value '{value}' -PropertyType String -Force | Out-Null")
    lines.append("Write-Output 'Chrome policy applied. Check chrome://policy'")
    return "\n".join(lines) + "\n"


def main():
    p = load_policies()
    targets = {
        OUT / "linux" / "lumen-chrome.json": render_linux(p),
        OUT / "macos" / "lumen-chrome.mobileconfig": render_macos(p),
        OUT / "windows" / "lumen-chrome.ps1": render_windows(p),
    }
    if "--check" in sys.argv:
        stale = [str(path.relative_to(HERE.parent)) for path, text in targets.items()
                 if not path.exists() or path.read_text() != text]
        if stale:
            print("Out of date (run python3 browser/render.py):", *stale, sep="\n  ")
            sys.exit(1)
        print("Browser policy files are up to date.")
        return
    for path, text in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print("wrote", path.relative_to(HERE.parent))


if __name__ == "__main__":
    main()
