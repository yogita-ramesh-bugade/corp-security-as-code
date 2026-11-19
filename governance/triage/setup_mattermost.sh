#!/bin/bash
# One-time Mattermost setup for LLM triage (Project 4, Step 4.4). Run from jml/.
# Creates the bot user governancebot, the channel ~governance-review (reviewers: lumenadmin,
# secops), and appends MM_TRIAGE_TOKEN, TRIAGE_SECRET, TRIAGE_ACTION_URL and REVIEWERS to
# ~/jml-secrets/governance.env. Uses its own bot, not the admin token.
set -euo pipefail
mm() { docker compose exec -T mattermost sh -c 'PATH="$PATH:/mm/mattermost/bin"; mmctl --local "$@"' mmctl "$@"; }

mm user create --email governancebot@lumenai.test --username governancebot --password "$(openssl rand -hex 16)Aa1#" >/dev/null || true
mm team users add lumen governancebot
mm channel create --team lumen --name governance-review --display-name "Governance review" >/dev/null || true
mm channel users add lumen:governance-review lumenadmin secops governancebot

TOKEN=$(mm token generate governancebot "governance triage" | cut -d: -f1)
[ ${#TOKEN} -ge 20 ] || { echo "could not read the bot token"; exit 1; }
printf 'MM_TRIAGE_TOKEN=%s\nTRIAGE_SECRET=%s\nTRIAGE_ACTION_URL=%s\nREVIEWERS=%s\n' \
  "$TOKEN" "$(openssl rand -hex 32)" "http://host.docker.internal:8300/mm/action" "lumenadmin,secops" \
  >> ~/jml-secrets/governance.env
echo "Done: governancebot, ~governance-review, settings appended to ~/jml-secrets/governance.env"
