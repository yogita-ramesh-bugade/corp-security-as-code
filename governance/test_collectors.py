"""Collector tests with fake Mattermost and Fleet API answers.  python -m pytest governance -q"""
import json

import httpx
import pytest

from governance import collect
from governance.collectors import fleet, mattermost, registry
from governance.record import ITEM_TYPES, Item


class Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)


MM = {
    "/users": [{"id": "u1", "username": "lumenadmin", "email": "admin@lumenai.test"},
               {"id": "u2", "username": "bob", "email": "bob@lumenai.test"}],
    "/bots": [{"user_id": "b1", "username": "standup-bot", "display_name": "Standup Bot", "owner_id": "u2",
               "create_at": 1763500000000, "update_at": 1763600000000}],
    "/oauth/apps": [{"id": "o1", "name": "Productivity Sync", "homepage": "https://prod-sync.example",
                     "is_trusted": True, "create_at": 1763500000000, "creator_id": "u2"}],
    "/hooks/incoming": [{"id": "i1", "display_name": "CI alerts", "channel_id": "c1", "channel_locked": False,
                         "user_id": "u1", "create_at": 1763500000000}],
    "/hooks/outgoing": [{"id": "g1", "display_name": "Meeting notes bot", "channel_id": "", "creator_id": "u2",
                         "callback_urls": ["https://notes-ai.example/hook"], "trigger_words": ["meeting"]}],
    "/teams": [{"id": "t1", "name": "lumen"}],
    "/commands": [{"id": "c9", "trigger": "exception", "url": "http://exceptions:8200/mm/slash", "creator_id": "u1"}],
    "/users/tokens": [{"id": "k1", "user_id": "u2", "description": "my script", "is_active": True}],
}


def fake_get(url, params=None, headers=None, timeout=None):
    if "/api/v4" in url:
        return Resp(MM[url.split("/api/v4", 1)[1]])
    path = url.split("/api/v1/fleet", 1)[1]
    if path == "/hosts":
        return Resp({"hosts": [{"id": 1, "hostname": "fleet-macos-lab", "status": "online"},
                               {"id": 2, "hostname": "fleet-windows-lab", "status": "online"},
                               {"id": 3, "hostname": "fleet-ubuntu-lab", "status": "offline"}]})
    if path == "/queries":
        return Resp({"queries": [{"id": 7, "name": "governance-browser-extensions"}]})
    if path == "/users":
        return Resp({"users": [{"email": "admin@lumenai.test", "name": "Yogita", "global_role": "admin", "api_only": False},
                               {"email": "gate@lumenai.test", "name": "gate", "global_role": "observer", "api_only": True},
                               {"email": "ci@lumenai.test", "name": "gitops", "global_role": "gitops", "api_only": True}]})
    raise AssertionError(url)


ROWS = {1: [{"os_user": "ivan", "name": "uBlock Origin", "identifier": "cjpalhdlnbpafiamejdnhcphjbkeiagm",
             "version": "1.6", "author": "Raymond Hill", "permissions": "storage, tabs, webRequest", "from_webstore": "1"},
            {"os_user": "ivan", "name": "Free VPN Pro", "identifier": "zzzbadextension00000000000000000",
             "version": "3.1", "author": "", "permissions": "<all_urls>, cookies, webRequest", "from_webstore": "0"}],
        2: [{"os_user": "bob", "name": "uBlock Origin", "identifier": "cjpalhdlnbpafiamejdnhcphjbkeiagm",
             "version": "1.6", "author": "Raymond Hill", "permissions": "storage, tabs", "from_webstore": "1"}]}


def fake_post(url, json=None, headers=None, timeout=None, data=None):
    assert url.endswith("/api/v1/fleet/queries/7/run"), url  # saved query only: observers can't send ad-hoc SQL
    assert json == {"host_ids": [1, 2]}  # online hosts only
    return Resp({"query_id": 7, "targeted_host_count": 2, "responded_host_count": 2,
                 "results": [{"host_id": h, "rows": ROWS[h], "error": None} for h in json["host_ids"]]})


@pytest.fixture(autouse=True)
def patch(monkeypatch):
    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)


def test_mattermost_finds_every_kind_of_chat_app():
    items = mattermost.collect_chat_apps(mattermost.Mattermost("http://mm", "t"))
    kinds = sorted(i.details["kind"] for i in items)
    assert kinds == ["bot", "incoming_webhook", "oauth_app", "outgoing_webhook", "personal_access_token", "slash_command"]
    trusted = next(i for i in items if i.details["kind"] == "oauth_app")
    assert "trusted:no_consent_screen" in trusted.scopes and trusted.owner == "bob@lumenai.test"
    assert all(i.item_type == "chat_app" for i in items)


def test_extensions_merge_across_hosts_and_skip_offline():
    f = fleet.Fleet("http://fleet", "t")
    items = {i.name: i for i in fleet.collect_browser_extensions(f)}
    assert items["uBlock Origin"].users == 2 and items["uBlock Origin"].publisher == "Raymond Hill"
    assert "<all_urls>" in items["Free VPN Pro"].scopes and items["Free VPN Pro"].publisher is None
    assert f.skipped == ["fleet-ubuntu-lab (offline)"]


def test_fleet_admins_exclude_observers():
    items = fleet.collect_fleet_admins(fleet.Fleet("http://fleet", "t"))
    assert sorted(i.scopes[0] for i in items) == ["fleet:admin", "fleet:gitops"]
    assert next(i for i in items if "gitops" in i.scopes[0]).owner is None  # API-only: no human owner


def test_registry_has_hand_written_agents():
    names = {i.name: i for i in registry.collect_internal_agents()}
    fin = names["finance-report-agent"]
    assert fin.owner is None and "mail.send" in fin.scopes and "tool:email_send" in fin.scopes


def test_record_shape_is_the_same_for_every_type():
    keys = None
    for t in ITEM_TYPES:
        d = Item(t, f"{t}:x", "x", None, ["b", "a", "a"], 0, None, None, None, "test").to_dict()
        assert d["scopes"] == ["a", "b"]
        keys = keys or set(d)
        assert set(d) == keys
    with pytest.raises(ValueError):
        Item("printer", "x", "x", None, [], 0, None, None, None, "test")


def test_collect_writes_one_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(collect, "OUT", tmp_path)
    from governance.collectors import keycloak
    monkeypatch.setattr(keycloak, "collect_oauth_grants", lambda kc: [
        Item("oauth_grant", "oauth_grant:keycloak:free-pdf-converter", "Free PDF Converter", None,
             ["files.readwrite"], 2, None, None, None, "keycloak")])
    monkeypatch.setattr(keycloak, "collect_admin_roles", lambda kc: [])
    out = tmp_path / "inventory.jsonl"
    assert collect.main(["--out", str(out)]) == 0
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert {r["item_type"] for r in rows} == set(ITEM_TYPES)
    assert all(r["first_seen"] for r in rows)  # filled from seen.json when the source has none
