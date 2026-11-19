"""Evaluation tests (Project 4, Step 4.5). No model needed.  python -m pytest governance -q"""
import json

import pytest

from governance.eval import build_set, label, run_eval
from governance.triage import backends
from governance.triage.test_triage import CLEAN, QN


def row(t, human, model, system=None, injection=False):
    return {"item_type": t, "human": human, "model": model, "system": system or model, "injection": injection,
            "scanner": False, "name": "x", "score": 40, "rationale": "r"}


def test_upper_bound_shows_how_little_a_small_sample_proves():
    assert round(run_eval.wilson_upper(0, 5), 2) == 0.43
    assert round(run_eval.wilson_upper(0, 30), 2) == 0.11
    assert run_eval.wilson_upper(0, 0) == 1.0


def test_metrics_count_the_dangerous_error_against_your_denials():
    rows = [row("oauth_grant", "deny", "approve"), row("oauth_grant", "deny", "deny"),
            row("oauth_grant", "approve", "deny"), row("oauth_grant", "escalate", "approve"),
            row("oauth_grant", "deny", "approve", system="escalate", injection=True)]
    m, s = run_eval.metrics(rows, "model"), run_eval.metrics(rows, "system")
    assert (m["false_approves"], m["human_denies"], m["approve_unsafe"], m["false_denies"]) == (2, 3, 3, 1)
    assert m["injection_fooled"] == 1 and s["injection_fooled"] == 0 and s["false_approves"] == 1
    assert m["agreement"] == pytest.approx(0.2)


def test_handoff_is_strict():
    good = [row("chat_app", "deny", "deny")] * 12 + [row("chat_app", "approve", "approve")] * 8
    few = [row("browser_extension", "deny", "deny")] * 3 + [row("browser_extension", "approve", "approve")] * 5
    bad = good[:-1] + [row("oauth_grant", "deny", "approve")]
    by_type = {t: {f: run_eval.metrics([r for r in rs], f) for f in ("model", "system")}
               for t, rs in {"chat_app": good, "browser_extension": few, "oauth_grant": bad}.items()}
    rules = run_eval.handoff(by_type)
    assert rules["chat_app"].startswith("model approvals may skip review")
    assert "only 3 denials" in rules["browser_extension"] and "upper bound" in rules["browser_extension"]
    assert rules["oauth_grant"].startswith("human decides: after the guard, 1 false approve")


def test_labeling_needs_a_final_rubric_and_supports_undo(tmp_path):
    items = tmp_path / "items.jsonl"
    items.write_text("\n".join(json.dumps({**x, "eval": {"tags": []}}) for x in (QN, CLEAN)) + "\n")
    rubric, labels = tmp_path / "RUBRIC.md", tmp_path / "labels.jsonl"
    rubric.write_text("Status: DRAFT\n")
    args = ["--items", str(items), "--labels", str(labels), "--rubric", str(rubric)]
    with pytest.raises(SystemExit, match="isn't final"):
        label.main(args, inp=lambda _: "q")
    rubric.write_text("Status: FINAL\n")
    answers = iter(["x", "d tries to steer the review", "u", "d injection", "a narrow, reviewed vendor"])
    assert label.main(args, inp=lambda _: next(answers)) == 0
    got = label.current_labels(labels)
    assert got[QN["id"]]["human"] == "deny" and got[QN["id"]]["note"] == "injection"
    assert got[CLEAN["id"]]["human"] == "approve" and len(got[QN["id"]]["rubric"]) == 12


def test_eval_set_is_the_review_queue_plus_injections(tmp_path):
    dec = tmp_path / "decisions.jsonl"
    dec.write_text("\n".join(json.dumps(x) for x in (QN, CLEAN)) + "\n")
    a, b = build_set.build(dec), build_set.build(dec)
    assert [x["id"] for x in a] == [x["id"] for x in b]  # same seed -> same set
    inj = [x for x in a if "injection" in x["eval"]["tags"]]
    assert len(inj) == 21 and any(x["name"] == "QuickNotes AI" for x in inj)  # 20 written + QuickNotes
    assert all(x["decision"]["decision"] == "review" for x in a if x not in inj)
    assert {x["item_type"] for x in a} >= {"oauth_grant", "chat_app", "browser_extension", "internal_agent"}
    with pytest.raises(SystemExit, match="frozen"):
        out = tmp_path / "items.jsonl"
        out.write_text("x")
        build_set.main(["--decisions", str(dec), "--out", str(out)])


def test_run_eval_end_to_end_and_cache(tmp_path, monkeypatch):
    items = tmp_path / "items.jsonl"
    items.write_text("\n".join(json.dumps({**x, "eval": {"tags": t}}) for x, t in ((QN, ["injection"]), (CLEAN, []))) + "\n")
    labels = tmp_path / "labels.jsonl"
    labels.write_text(json.dumps({"id": QN["id"], "human": "deny"}) + "\n" + json.dumps({"id": CLEAN["id"], "human": "approve"}) + "\n")
    fixed = backends.FixedBackend({"decision": "approve", "risk_factors": [], "rationale": "fine", "confidence": 0.9})
    monkeypatch.setattr(run_eval, "get_backend", lambda name, model=None: fixed)
    monkeypatch.setattr(run_eval, "HERE", tmp_path)
    args = ["--items", str(items), "--labels", str(labels), "--report", str(tmp_path / "r.md")]
    assert run_eval.main(args) == 0 and len(fixed.calls) == 2
    text = (tmp_path / "r.md").read_text()
    assert "| oauth_grant | 2 | 50% | 1/1 (100%)" in text  # fooled by QuickNotes
    assert "injection fooled: 1/1 -> 0/1" in text  # the guard caught it
    assert "QuickNotes AI" in text.split("Every false approve")[1]
    assert run_eval.main(args) == 0 and len(fixed.calls) == 2  # cached: model not asked again


def test_undo_then_quit_leaves_the_item_unlabeled(tmp_path):
    items = tmp_path / "items.jsonl"
    items.write_text("\n".join(json.dumps({**x, "eval": {"tags": []}}) for x in (QN, CLEAN)) + "\n")
    (tmp_path / "R.md").write_text("Status: FINAL\n")
    answers = iter(["d", "u", "q"])
    label.main(["--items", str(items), "--labels", str(tmp_path / "l.jsonl"), "--rubric", str(tmp_path / "R.md")],
               inp=lambda _: next(answers))
    assert label.current_labels(tmp_path / "l.jsonl") == {}


def test_changing_the_prompt_invalidates_cached_answers(tmp_path, monkeypatch):
    items = tmp_path / "items.jsonl"
    items.write_text(json.dumps({**CLEAN, "eval": {"tags": []}}) + "\n")
    labels = tmp_path / "labels.jsonl"
    labels.write_text(json.dumps({"id": CLEAN["id"], "human": "approve"}) + "\n")
    fixed = backends.FixedBackend()
    monkeypatch.setattr(run_eval, "get_backend", lambda name, model=None: fixed)
    monkeypatch.setattr(run_eval, "HERE", tmp_path)
    args = ["--items", str(items), "--labels", str(labels), "--report", str(tmp_path / "r.md")]
    run_eval.main(args)
    from governance.triage import prompt
    monkeypatch.setattr(prompt, "SYSTEM", prompt.SYSTEM + "\n5. new rule")
    run_eval.main(args)
    assert len(fixed.calls) == 2  # asked again under the new prompt
