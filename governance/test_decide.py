"""Policy decision tests (Project 4, Step 4.3).  python -m pytest governance -q"""
import copy
import json
from datetime import datetime, timezone

import pytest

from governance import decide, score
from governance.record import Item

NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)
RISK = score.load_rules()
POLICY = decide.load_policy()


def item(t="oauth_grant", name="x", publisher=None, scopes=(), users=1, owner=None, **details):
    it = Item(t, f"{t}:test:{name}", name, publisher, list(scopes), users, None, None, owner, "test", details).to_dict()
    return {**it, "risk": score.score_item(it, RISK, NOW)}


def D(it, policy=POLICY, reviews=None):
    return decide.decide_item(it, policy, RISK, reviews or {})


def test_the_three_examples_from_the_step():
    basic = D(item(name="sso-only", publisher="QuickSign Ltd.", scopes=["openid", "profile", "email"]))
    mail = D(item(name="mailmerge", publisher="MergeWorks", scopes=["mail.read", "mail.send"]))
    cal = D(item(name="meetsync", publisher="MeetSync Inc.", scopes=["calendar.read"], users=3))
    assert (basic["decision"], basic["rule"]) == ("approve", "approve-vetted-basic-profile")
    assert (mail["decision"], mail["rule"]) == ("deny", "deny-unvetted-mail-or-file-write")
    assert cal["decision"] == "review" and cal["by"] == "nobody"  # not obvious either way -> a person
    sneaky = D(item(name="sso-plus", publisher="QuickSign Ltd.", scopes=["openid", "profile", "mail.read"]))
    assert sneaky["decision"] == "review"  # basic profile PLUS mail is not "only basic profile"


def test_known_bad_extension_is_denied_even_if_it_looks_fine():
    policy = copy.deepcopy(POLICY)
    policy["lists"]["known_bad_extensions"] = ["badid"]
    ext = item("browser_extension", "looks-fine", "Raymond Hill", ["storage"], extension_id="badid")
    assert D(ext)["decision"] == "approve"  # verified + low score, before it's on the list
    assert (D(ext, policy)["decision"], D(ext, policy)["rule"]) == ("deny", "deny-known-bad-extension")


def test_admins_always_go_to_a_person():
    admin = item("admin_role", "erin", "internal", ["group:break-glass"], owner="erin@lumenai.test")
    assert D(admin) == {"decision": "review", "by": "policy", "rule": "review-admin-roles",
                        "why": "admin access is always re-certified by a person"}


def test_risky_agents_of_leavers_and_nobody_are_suspended():
    leaver = item("internal_agent", "a", "internal", ["mail.read", "files.readwrite", "tool:shell_exec"], 0,
                  "dana@lumenai.test", human_in_the_loop=False)
    nobody = item("internal_agent", "b", "internal", ["mail.read", "files.readwrite", "tool:shell_exec"], 0, None)
    small = item("internal_agent", "c", "internal", ["chat.read"], 0, "dana@lumenai.test", human_in_the_loop=True)
    assert D(leaver)["rule"] == "deny-leaver-risky-agent"
    assert D(nobody)["rule"] == "deny-ownerless-risky-agent"
    assert D(small)["decision"] == "review"  # low risk, but its owner left: not auto-approved


def human(it, decision, reason="ok"):
    return {it["id"]: {"id": it["id"], "decision": decision, "reason": reason, "reviewer": "yogi",
                       "at": "2026-11-19T00:00:00Z", "signature": decide.signature(it, RISK)}}


def test_human_decision_sticks_until_the_item_changes():
    cal = item(name="meetsync", publisher="MeetSync Inc.", scopes=["calendar.read"], users=3)
    rev = human(cal, "approve")
    assert D(cal, reviews=rev)["by"] == "human"
    grown = item(name="meetsync", publisher="MeetSync Inc.", scopes=["calendar.read", "files.read"], users=3)
    again = D(grown, reviews=rev)
    assert again["decision"] == "review" and "changed since yogi's review" in again["why"]


def test_policy_deny_beats_an_old_human_approval():
    mm = item(name="mailmerge", publisher="MergeWorks", scopes=["mail.read"])
    assert D(mm, reviews=human(mm, "approve"))["decision"] == "deny"


def test_coverage_counts_only_real_policy_decisions():
    rows = [{"decision": {"decision": d, "by": b}} for d, b in
            [("approve", "policy"), ("deny", "policy"), ("review", "policy"), ("review", "nobody"), ("approve", "human")]]
    assert decide.coverage(rows) == {"total": 5, "policy": 2, "human": 1, "queue": 2, "policy_pct": 40.0}


def test_three_same_calls_make_a_draft_rule_that_works():
    agents = [item("internal_agent", f"reader-{i}", "internal", ["mail.read", "tool:email_read"], 0,
                   "sam@lumenai.test", human_in_the_loop=False, data=["customer_pii"]) for i in range(4)]
    by_id = {a["id"]: a for a in agents}
    reviews = {}
    for a in agents[:2]:
        reviews |= human(a, "approve", "read-only helper")
    assert decide.suggest(reviews, by_id, RISK) == []  # two isn't a pattern yet
    reviews |= human(agents[2], "approve", "read-only helper")
    [draft] = decide.suggest(reviews, by_id, RISK)
    assert draft["decision"] == "approve" and draft["when"]["has_owner"] is True and draft["when"]["owner_left"] is False
    policy = copy.deepcopy(POLICY)
    policy["rules"].append({k: v for k, v in draft.items() if not k.startswith("_")})
    assert agents[3]["risk"]["level"] == "medium" and D(agents[3])["decision"] == "review"
    assert D(agents[3], policy)["rule"] == draft["id"]  # the 4th one is now decided by policy


def test_typo_in_policy_is_an_error_not_a_silent_match():
    bad = {"rules": [{"id": "x", "decision": "approve", "why": "x", "when": {"publsher": ["verified"]}}]}
    with pytest.raises(ValueError, match="publsher"):
        D(item(name="a"), bad)


def test_cli_review_then_decide(tmp_path, capsys):
    inv = tmp_path / "inventory.jsonl"
    rows = [item(name="meetsync", publisher="MeetSync Inc.", scopes=["calendar.read"], users=3),
            item(name="mailmerge", publisher="MergeWorks", scopes=["mail.read"])]
    inv.write_text("\n".join(json.dumps({k: v for k, v in r.items() if k != "risk"}) for r in rows) + "\n")
    common = ["--inventory", str(inv), "--out", str(tmp_path / "d.jsonl"), "--reviews", str(tmp_path / "r.jsonl"),
              "--now", "2026-11-19"]
    assert decide.main(["decide", *common]) == 0
    assert "by policy alone:    1  (50.0%)" in capsys.readouterr().out
    assert decide.main(["review", "meetsync", "approve", "calendar only, vendor reviewed", "--by", "yogi", *common]) == 0
    rec = json.loads((tmp_path / "r.jsonl").read_text())
    assert rec["reviewer"] == "yogi" and rec["signature"] == "oauth_grant|verified|calendar.read"
    capsys.readouterr()
    decide.main(["decide", *common])
    out = capsys.readouterr().out
    assert "by a human:         1" in out and "review queue:       0" in out


def test_sideloaded_extension_is_denied():
    coupon = item("browser_extension", "coupon", None, ["tabs"], extension_id="unpacked:coupon", unpacked=True)
    assert D(coupon)["rule"] == "deny-sideloaded-extension"
