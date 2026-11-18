#!/bin/bash
# Sign a user out everywhere (Keycloak admin API) and ask Fleet to re-check their laptop.
# Run it when travel mode STARTS (so their next login carries the "traveling" group)
# and when it ENDS (so anything copied while abroad, like session cookies, stops working).
#
# Usage:   ./session_reset.sh <keycloak-username> [device-serial]
# Example: ./session_reset.sh tara ZR2JVG236J
# Needs:   ~/access-gate-secrets/terraform.env (Keycloak admin) and `fleetctl login` (Fleet admin)
set -euo pipefail
USERNAME="$1"; SERIAL="${2:-}"
KC=${KC_URL:-http://keycloak.lumen.test:8081}
source ~/access-gate-secrets/terraform.env

json() { python3 -c "import sys, json; print(json.load(sys.stdin)$1)"; }

TOKEN=$(curl -fsS -d client_id=admin-cli -d grant_type=password \
  --data-urlencode "username=$KEYCLOAK_USER" --data-urlencode "password=$KEYCLOAK_PASSWORD" \
  "$KC/realms/master/protocol/openid-connect/token" | json '["access_token"]')
USER_ID=$(curl -fsS -H "Authorization: Bearer $TOKEN" \
  "$KC/admin/realms/lumen/users?username=$USERNAME&exact=true" | json '[0]["id"]')

SESSIONS=$(curl -fsS -H "Authorization: Bearer $TOKEN" "$KC/admin/realms/lumen/users/$USER_ID/sessions" | json '.__len__()')
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" "$KC/admin/realms/lumen/users/$USER_ID/logout"
echo "Keycloak: signed $USERNAME out of $SESSIONS session(s)."

if [ -n "$SERIAL" ]; then
  URL=$(awk '/address:/ {print $2; exit}' ~/.fleet/config)
  FT=$(awk '/token:/ {print $2; exit}' ~/.fleet/config)
  HOST_ID=$(curl -fsS -H "Authorization: Bearer $FT" "$URL/api/v1/fleet/hosts/identifier/$SERIAL?exclude_software=true" | json '["host"]["id"]')
  curl -fsS -X POST -H "Authorization: Bearer $FT" "$URL/api/v1/fleet/hosts/$HOST_ID/refetch" >/dev/null
  echo "Fleet: asked host $HOST_ID ($SERIAL) to re-report its health."
fi
echo "Pomerium drops the old session at its next token refresh (within 15 minutes). Ask $USERNAME to sign in again."
