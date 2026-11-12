#!/usr/bin/env bash
# Apply Fleet GitOps config. Usage: ./scripts/gitops.sh [--dry-run]
set -euo pipefail

ENV_FILE="$HOME/fleet-server/gitops.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE (holds FLEET_GLOBAL_ENROLL_SECRET)." >&2
  exit 1
fi
source "$ENV_FILE"

cd "$(dirname "$0")/.."
fleetctl gitops -f fleet/default.yml "$@"
