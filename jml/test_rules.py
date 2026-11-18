"""Checks for jml/roles.yaml (run in CI on every pull request).  cd jml && python -m pytest -q"""
import copy

import pytest

from rules import RulesError, birthright, load_rules, terraform_groups, validate

RULES = load_rules()  # fails the whole run if roles.yaml is invalid or uses unknown groups


def emp(dept, title="", kind="full_time", end_date=None):
    return {"email": "x@lumenai.test", "department": dept, "title": title, "employment_type": kind,
            "end_date": end_date}


def test_file_is_valid_and_matches_terraform():
    assert validate(RULES, terraform_groups()) == []


def test_engineer_birthright():
    b = birthright(RULES, emp("engineering", "ML Engineer"))
    assert b["keycloak_groups"] == ["all-staff", "engineering"]
    assert "eng" in b["chat_channels"] and "town-square" in b["chat_channels"]
    assert b["device"] == "macbook-pro"


def test_manager_title_adds_managers_in_any_department():
    for dept in ("engineering", "sales"):
        assert "managers" in birthright(RULES, emp(dept, "Engineering Manager"))["keycloak_groups"]


def test_sre_gets_oncall_channel():
    assert "eng-oncall" in birthright(RULES, emp("engineering", "Site Reliability Engineer"))["chat_channels"]


def test_it_staff_do_not_get_admin_rights_automatically():
    b = birthright(RULES, emp("it", "Systems Administrator"))
    assert "it" in b["keycloak_groups"]
    assert not set(b["keycloak_groups"]) & set(RULES["privileged_groups"])


def test_contractor_is_scoped_and_needs_end_date():
    with pytest.raises(RulesError):
        birthright(RULES, emp("engineering", "Engineer", "contractor"))
    b = birthright(RULES, emp("engineering", "Engineer", "contractor", end_date="2027-03-31"))
    assert "contractors" in b["keycloak_groups"] and "all-staff" not in b["keycloak_groups"]
    assert "announcements" not in b["chat_channels"]


def test_intern_gets_interns_group():
    assert "interns" in birthright(RULES, emp("research", "Research Intern", "intern"))["keycloak_groups"]


def test_unknown_department_is_an_error():
    with pytest.raises(RulesError):
        birthright(RULES, emp("marketing"))


def test_validator_rejects_privileged_birthright():
    bad = copy.deepcopy(RULES)
    bad["departments"]["it"]["keycloak_groups"].append("it-admins")
    assert any("never be birthright" in p for p in validate(bad))


def test_validator_rejects_unknown_group_and_missing_owner():
    bad = copy.deepcopy(RULES)
    bad["departments"]["sales"]["keycloak_groups"].append("made-up-group")
    del bad["departments"]["legal"]["owner"]
    problems = validate(bad, terraform_groups())
    assert any("not defined in Terraform" in p for p in problems)
    assert any("legal has no owner" in p for p in problems)


def test_every_privileged_group_is_requestable_with_expiry():
    for g in RULES["privileged_groups"]:
        assert RULES["requestable"][g]["max_days"] <= 90
