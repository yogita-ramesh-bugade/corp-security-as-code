#!/bin/bash
# Lab only: give the chat-app collector realistic things to find (Project 4, Step 4.1):
#   - "Meeting notes bot": an outgoing webhook that sends every message containing "meeting"
#     to an outside URL (the S12 story: a chat bot quietly collecting messages)
#   - "CI alerts": an incoming webhook that can post into Town Square
#   - a personal access token for omar ("my script")
# Needs MM_ADMIN_TOKEN (lumenadmin) in the environment: source ~/jml-secrets/governance.env
set -euo pipefail
MM=${MM_URL:-http://chat.lumen.test:8065}
H=(-H "Authorization: Bearer $MM_ADMIN_TOKEN" -H "Content-Type: application/json")
json() { python3 -c "import sys, json; print(json.load(sys.stdin)$1)"; }

TEAM=$(curl -fsS "${H[@]}" "$MM/api/v4/teams/name/lumen" | json '["id"]')
TOWN=$(curl -fsS "${H[@]}" "$MM/api/v4/teams/$TEAM/channels/name/town-square" | json '["id"]')
curl -fsS "${H[@]}" -X POST "$MM/api/v4/hooks/outgoing" -d "{\"team_id\":\"$TEAM\",\"display_name\":\"Meeting notes bot\",
  \"description\":\"Summarizes meetings (installed by an employee)\",\"trigger_words\":[\"meeting\"],
  \"callback_urls\":[\"https://notes-ai.example/hook\"],\"content_type\":\"application/json\"}" >/dev/null && echo "outgoing webhook: Meeting notes bot"
curl -fsS "${H[@]}" -X POST "$MM/api/v4/hooks/incoming" -d "{\"channel_id\":\"$TOWN\",\"display_name\":\"CI alerts\",
  \"description\":\"Build notifications\"}" >/dev/null && echo "incoming webhook: CI alerts"
cd ~/corp-security-as-code/jml
docker compose exec -T mattermost sh -c 'PATH="$PATH:/mm/mattermost/bin"; mmctl --local token generate omar "my script"' >/dev/null && echo "token: omar / my script"
