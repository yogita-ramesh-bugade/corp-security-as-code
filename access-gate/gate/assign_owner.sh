#!/bin/bash
# Assign a device to a person in Fleet (human-device mapping, source "custom").
# The gate only gives a device level 1 or 3 when its assigned person is the one logging in.
# Uses YOUR Fleet admin login (fleetctl login), not the gate's read-only token.
#
# Usage:  ./assign_owner.sh <serial-or-uuid> <email>
# Example: ./assign_owner.sh ZR2JVG236J ivan@lumenai.test
set -euo pipefail
IDENT="$1"; EMAIL="$2"
URL=$(awk '/address:/ {print $2; exit}' ~/.fleet/config)
TOKEN=$(awk '/token:/ {print $2; exit}' ~/.fleet/config)

HOST_ID=$(curl -fsS -H "Authorization: Bearer $TOKEN" "$URL/api/v1/fleet/hosts/identifier/$IDENT?exclude_software=true" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["host"]["id"])')

curl -fsS -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"email\": \"$EMAIL\"}" "$URL/api/v1/fleet/hosts/$HOST_ID/device_mapping" >/dev/null

echo "Fleet host $HOST_ID ($IDENT) is now assigned to $EMAIL"
