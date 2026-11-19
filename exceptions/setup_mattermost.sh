#!/bin/bash
# One-time Mattermost setup for the exception bot (Project 3, Step 3.4).
# Run from jml/ after `docker compose up -d mattermost` and once http://localhost:8065 loads.
# Creates: team "lumen"; users lumenadmin, omar, maya, secops (+ the bot user exceptionbot);
# a personal access token for the bot; and the /exception slash command.
# Appends MM_BOT_TOKEN and MM_SLASH_TOKEN to ~/jml-secrets/exceptions.env.
set -euo pipefail
PW="${LAB_CHAT_PASSWORD:?set LAB_CHAT_PASSWORD first: export LAB_CHAT_PASSWORD='something-12+chars'}"
mm() { docker compose exec -T mattermost sh -c 'PATH="$PATH:/mm/mattermost/bin"; mmctl --local "$@"' mmctl "$@"; }

mm team create --name lumen --display-name "Lumen AI" || true
mm user create --email admin@lumenai.test  --username lumenadmin --password "$PW" --system-admin || true
for u in omar maya secops; do
  mm user create --email "$u@lumenai.test" --username "$u" --password "$PW" || true
done
mm user create --email exceptionbot@lumenai.test --username exceptionbot --password "$PW-bot" || true
mm team users add lumen lumenadmin omar maya secops exceptionbot

BOT_TOKEN=$(mm --json token generate exceptionbot "exception bot" | python3 -c 'import sys,json; d=json.load(sys.stdin); d=d[0] if isinstance(d,list) else d; print(d["token"])')
SLASH_TOKEN=$(mm --json command create lumen --title "Exception" --trigger-word exception \
  --url http://exceptions:8200/mm/slash --creator lumenadmin --method P --autocomplete \
  --autocomplete-desc "Request a temporary security exception" \
  --autocomplete-hint "[binary <sha256> <machine-id> | waiver <check> <serial>]" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); d=d[0] if isinstance(d,list) else d; print(d["token"])')

printf 'MM_BOT_TOKEN=%s\nMM_SLASH_TOKEN=%s\n' "$BOT_TOKEN" "$SLASH_TOKEN" >> ~/jml-secrets/exceptions.env
echo "Done. Tokens saved to ~/jml-secrets/exceptions.env. Restart the bot: docker compose up -d exceptions"
