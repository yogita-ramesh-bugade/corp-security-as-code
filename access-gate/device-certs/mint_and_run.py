#!/usr/bin/env python3
"""Issue a Lumen device certificate to each Fleet host.

For every host Fleet knows about, this:
  1. reads its hardware serial from Fleet (falls back to Fleet's UUID if the VM has no serial),
  2. mints a ONE-TIME token from step-ca that is only valid for that serial (expires in 5 minutes),
  3. writes a per-device enrollment script into out/ (gitignored: it contains the token),
  4. with --run, asks Fleet to run that script on that host only.

The token can only ever produce a certificate for that one serial, and only once.

Usage (from access-gate/device-certs/):
  python3 mint_and_run.py                 # dry run: list hosts and write scripts
  python3 mint_and_run.py --run           # also run them through Fleet
  python3 mint_and_run.py --run --host fleet-ubuntu-lab   # one host only
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
OUT = HERE / "out"
ROOT = HERE / "ca" / "root_ca.crt"
PROVISIONER = "lumen-devices"
PASS_FILE = pathlib.Path("~/access-gate-secrets/step-provisioner-pass").expanduser()
# Which address each VM uses to reach the CA on this Mac (UTM puts VMs on two networks).
# Apple-virtualization VMs (the Mac VM) are on 192.168.64.x; QEMU VMs (Windows, Ubuntu) on 192.168.65.x.
CA_URL_BY_PLATFORM = {"darwin": "https://192.168.64.1:9000"}
CA_URL_DEFAULT = "https://192.168.65.1:9000"
JUNK_SERIALS = {"", "0", "none", "default string", "to be filled by o.e.m.", "not specified", "system serial number"}

PLATFORMS = {
    "darwin": ("enroll-macos.sh", ".sh"),
    "windows": ("enroll-windows.ps1", ".ps1"),
}
LINUX = ("enroll-linux.sh", ".sh")  # ubuntu, debian, rhel, ...


def fleet_hosts():
    raw = subprocess.run(["fleetctl", "get", "hosts", "--json"], check=True,
                         capture_output=True, text=True).stdout.strip()
    try:
        items = json.loads(raw)
        items = items if isinstance(items, list) else [items]
    except json.JSONDecodeError:
        items = [json.loads(line) for line in raw.splitlines() if line.strip().startswith("{")]
    return [i.get("spec", i) for i in items]


def mint_token(subject, ca_url):
    return subprocess.run(
        ["step", "ca", "token", subject, "--san", subject,
         "--provisioner", PROVISIONER, "--password-file", str(PASS_FILE),
         "--ca-url", ca_url, "--root", str(ROOT)],
        check=True, capture_output=True, text=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ca-url", help="override the CA address for every host")
    ap.add_argument("--host", help="only this hostname")
    ap.add_argument("--run", action="store_true", help="run the scripts through Fleet")
    args = ap.parse_args()

    for path in (ROOT, PASS_FILE):
        if not path.exists():
            sys.exit(f"Missing {path}. See Step 2.2 instructions.")
    root_pem = ROOT.read_text().strip()
    OUT.mkdir(exist_ok=True)

    hosts = fleet_hosts()
    if args.host:
        hosts = [h for h in hosts if h.get("hostname") == args.host]
    if not hosts:
        sys.exit("No matching hosts in Fleet.")

    for h in hosts:
        name, platform = h.get("hostname", "?"), h.get("platform", "")
        serial = (h.get("hardware_serial") or "").strip()
        subject = serial
        note = ""
        if serial.lower() in JUNK_SERIALS:
            subject, note = h["uuid"], "  (no hardware serial in this VM: using Fleet UUID)"
        template, ext = PLATFORMS.get(platform, LINUX)
        ca_url = args.ca_url or CA_URL_BY_PLATFORM.get(platform, CA_URL_DEFAULT)

        script = (TEMPLATES / template).read_text()
        script = (script.replace("__SERIAL__", subject)
                        .replace("__TOKEN__", mint_token(subject, ca_url))
                        .replace("__CA_URL__", ca_url)
                        .replace("__ROOT_PEM__", root_pem))
        out = OUT / f"{name}-enroll{ext}"
        out.write_text(script)
        os.chmod(out, 0o600)
        print(f"{name:28} {platform:10} subject={subject}  ca={ca_url}{note}\n    -> {out.relative_to(HERE)}")

        if args.run:
            r = subprocess.run(["fleetctl", "run-script", "--script-path", str(out),
                                "--host", h["uuid"]], capture_output=True, text=True)
            print("    " + (r.stdout + r.stderr).strip().replace("\n", "\n    "))
            out.unlink()  # token is spent; don't leave it lying around


if __name__ == "__main__":
    main()
