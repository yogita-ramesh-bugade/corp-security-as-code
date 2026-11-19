"""Mattermost collector: bots, OAuth apps, incoming/outgoing webhooks, slash commands and
personal access tokens. Mattermost Team Edition has no read-only admin role, so this needs a
system admin's token (lumenadmin); kept in ~/jml-secrets/governance.env, used read-only."""
from __future__ import annotations

import os

import httpx

from governance.record import Item, ms_to_iso


class Mattermost:
    def __init__(self, url=None, token=None):
        self.url = (url or os.environ.get("MM_URL", "http://chat.lumen.test:8065")).rstrip("/")
        self.h = {"Authorization": f"Bearer {token or os.environ.get('MM_ADMIN_TOKEN', '')}"}

        self.skipped: list[str] = []

    def get(self, path, **params):
        r = httpx.get(f"{self.url}/api/v4{path}", params={"per_page": 200, **params}, headers=self.h, timeout=15)
        r.raise_for_status()
        return r.json()

    def maybe(self, path, **params):
        """Lists from features that may be switched off (OAuth apps, webhooks): skip, don't fail."""
        try:
            return self.get(path, **params)
        except httpx.HTTPStatusError as e:
            self.skipped.append(f"{path} (HTTP {e.response.status_code if e.response is not None else '?'})")
            return []


def collect_chat_apps(mm: Mattermost) -> list[Item]:
    users = {u["id"]: u for u in mm.get("/users", per_page=200)}

    def who(uid):
        u = users.get(uid) or {}
        return u.get("email") or u.get("username")

    items = []
    for b in mm.maybe("/bots", include_deleted="false"):
        items.append(Item("chat_app", f"chat_app:mattermost:bot:{b['user_id']}", b.get("display_name") or b["username"],
                          who(b.get("owner_id")) or "unknown", ["bot:post", "bot:read_channels_it_is_in"], 1,
                          ms_to_iso(b.get("create_at")), ms_to_iso(b.get("update_at")), who(b.get("owner_id")),
                          "mattermost", {"kind": "bot", "username": b["username"]}))
    for a in mm.maybe("/oauth/apps"):
        items.append(Item("chat_app", f"chat_app:mattermost:oauth:{a['id']}", a["name"], a.get("homepage") or None,
                          ["oauth:act_as_user"] + (["trusted:no_consent_screen"] if a.get("is_trusted") else []),
                          0, ms_to_iso(a.get("create_at")), None, who(a.get("creator_id")), "mattermost",
                          {"kind": "oauth_app", "callback_urls": a.get("callback_urls", [])}))
    for h in mm.maybe("/hooks/incoming"):
        items.append(Item("chat_app", f"chat_app:mattermost:incoming:{h['id']}", h.get("display_name") or "incoming webhook",
                          None, ["post:" + h.get("channel_id", "?")] + (["post:any_channel"] if not h.get("channel_locked") else []),
                          0, ms_to_iso(h.get("create_at")), None, who(h.get("user_id")), "mattermost",
                          {"kind": "incoming_webhook", "description": h.get("description", "")}))
    for h in mm.maybe("/hooks/outgoing"):
        items.append(Item("chat_app", f"chat_app:mattermost:outgoing:{h['id']}", h.get("display_name") or "outgoing webhook",
                          None, ["read_messages:" + (h.get("channel_id") or "team-wide trigger words"), "send_to_url"],
                          0, ms_to_iso(h.get("create_at")), None, who(h.get("creator_id")), "mattermost",
                          {"kind": "outgoing_webhook", "callback_urls": h.get("callback_urls", []),
                           "trigger_words": h.get("trigger_words", [])}))
    for team in mm.get("/teams"):
        for c in mm.maybe("/commands", team_id=team["id"], custom_only="true"):
            items.append(Item("chat_app", f"chat_app:mattermost:command:{c['id']}", f"/{c['trigger']}", None,
                              ["receive_command_text", "send_to_url"], 0, ms_to_iso(c.get("create_at")), None,
                              who(c.get("creator_id")), "mattermost", {"kind": "slash_command", "url": c.get("url")}))
    for t in mm.maybe("/users/tokens"):
        items.append(Item("chat_app", f"chat_app:mattermost:token:{t['id']}",
                          f"token '{t.get('description', '')}' of {who(t.get('user_id'))}", None,
                          ["act_as:" + str(who(t.get("user_id")))], 1, None, None, who(t.get("user_id")), "mattermost",
                          {"kind": "personal_access_token", "active": t.get("is_active", True)}))
    return items
