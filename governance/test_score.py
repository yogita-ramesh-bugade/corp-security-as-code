"""Risk scoring tests (Project 4, Step 4.2).  python -m pytest governance -q"""
import copy
import json
from datetime import datetime, timezone

import pytest

from governance import score
from governance.record import Item

NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)
RULES = score.load_rules()


def item(t="oauth_grant", name="x", publisher=None, scopes=(), users=1, last_used=None, owner=None, **details):
    return Item(t, f"{t}:test:{name}", name, publisher, list(scopes), users, None, last_used, owner, "test",
                details).to_dict()


def S(it, rules=RULES):
    return score.score_item(it, rules, NOW)


PDF = item(name="free-pdf-converter", publisher="unknown (pdf-tools-free.example)",
           scopes=["files.readwrite", "mail.read", "offline_access"], users=2)
MEETSYNC = item(name="meetsync", publisher="MeetSync Inc.", scopes=["calendar.read"], users=3)


def test_every_point_has_a_reason_and_they_add_up():
    for it in (PDF, MEETSYNC, item("internal_agent", "big", "internal",
                                   ["mail.read", "mail.send", "files.readwrite", "admin.directory", "tool:shell_exec"],
                                   0, None, None, data=["customer_pii", "financials"], human_in_the_loop=False,
                                   last_review="2024-01-01", creator="dana@lumenai.test")):
        r = S(it)
        assert sum(f["points"] for f in r["factors"]) == r["score"]
        assert all(f["why"] for f in r["factors"])
        assert 0 <= r["score"] <= 100


def test_risky_unknown_app_outranks_a_reviewed_calendar_app():
    pdf, meet = S(PDF), S(MEETSYNC)
    assert pdf["score"] > meet["score"]
    assert pdf["level"] == "critical" and meet["level"] in ("low", "medium")
    whys = " | ".join(f["why"] for f in pdf["factors"])
    assert "read all of the user's email" in whys and "publisher unknown" in whys and "accountable" in whys
    assert not any(f["factor"] == "unverified_publisher" for f in meet["factors"])  # MeetSync Inc. is reviewed


def test_unused_for_90_days_counts_only_when_we_know():
    old = S(item(name="a", publisher="MeetSync Inc.", last_used="2026-08-01T00:00:00Z"))
    recent = S(item(name="b", publisher="MeetSync Inc.", last_used="2026-11-10T00:00:00Z"))
    unknown = S(item(name="c", publisher="MeetSync Inc."))
    assert any(f["factor"] == "unused_90_days" and "110 days" in f["why"] for f in old["factors"])
    assert not any(f["factor"] == "unused_90_days" for f in recent["factors"] + unknown["factors"])


def test_caps_show_up_as_their_own_lines():
    many = item("browser_extension", "kitchen-sink", None,
                ["<all_urls>", "debugger", "nativeMessaging", "cookies", "management", "history"], 500)
    r = S(many)
    cap = next(f for f in r["factors"] if f["factor"] == "scope_cap")
    assert cap["points"] < 0 and r["score"] == 100
    assert any(f["factor"] == "total_cap" for f in r["factors"])


def test_changing_risk_yaml_changes_the_score():
    rules = copy.deepcopy(RULES)
    rules["scopes"]["mail.read"] = [1, "tuned down"]
    assert S(PDF, rules)["score"] == S(PDF)["score"] - 19
    rules["factors"]["unverified_publisher"]["verified_publishers"].append("MergeWorks")
    mm = item(name="mailmerge", publisher="MergeWorks", scopes=["mail.send"])
    assert S(mm, rules)["score"] == S(mm)["score"] - 15


def test_agent_factors_leaver_review_data_and_no_human():
    agent = item("internal_agent", "digest", "internal", ["mail.send", "tool:email_send"], 0,
                 None, "priya@lumenai.test", data=["customer_pii"], human_in_the_loop=False, last_review="2025-01-01")
    got = {f["factor"]: f for f in S(agent)["factors"]}
    assert "priya@lumenai.test has left" in got["owner_left"]["why"]
    assert got["not_reviewed"]["points"] == 10 and got["sensitive_data"]["points"] == 15
    assert "email_send" in got["acts_without_human"]["why"]
    assert "scope:tool:email_send" not in got  # mail.send already counted that power once
    assert "no_owner" not in got  # it has an owner; the owner left, which is its own factor


def test_chat_app_sending_outside_lumen():
    out = S(item("chat_app", "notes", "internal", ["read_messages:team-wide trigger words", "send_to_url"], 0,
                 owner="bob@lumenai.test", callback_urls=["https://notes-ai.example/hook"]))
    inside = S(item("chat_app", "exception", "internal", ["receive_command_text", "send_to_url"], 0,
                    owner="admin@lumenai.test", url="http://exceptions:8200/mm/slash"))
    assert any(f["factor"] == "external_destination" and "notes-ai.example" in f["why"] for f in out["factors"])
    assert not any(f["factor"] == "external_destination" for f in inside["factors"])
    assert out["level"] == "high" and inside["level"] == "low"


def test_cli_writes_sorted_scores_and_explains(tmp_path, capsys):
    inv = tmp_path / "inventory.jsonl"
    inv.write_text("\n".join(json.dumps(x) for x in (MEETSYNC, PDF)) + "\n")
    out = tmp_path / "scored.jsonl"
    assert score.main(["--inventory", str(inv), "--out", str(out), "--now", "2026-11-19"]) == 0
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert [r["name"] for r in rows] == ["free-pdf-converter", "meetsync"]
    pts = [f["points"] for f in rows[0]["risk"]["factors"]]
    assert pts == sorted(pts, reverse=True)  # biggest reason first
    capsys.readouterr()
    assert score.main(["--inventory", str(inv), "--now", "2026-11-19", "--explain", "free-pdf-converter"]) == 0
    assert "+20  scope:mail.read" in capsys.readouterr().out
    assert score.main(["--inventory", str(inv), "--explain", "nope"]) == 1


@pytest.mark.parametrize("bad", [{"levels": {"low": 0}}, {}])
def test_level_for_handles_short_tables(bad):
    assert score.level_for(5, {**RULES, **bad}) == "low"
