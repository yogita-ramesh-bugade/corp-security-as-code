# Unit tests for access.rego. Run:  opa test access-gate/policy -v
#
# One test per scenario in the Step 2.4 table, plus edge cases that keep the policy honest.
# "No device certificate" never reaches OPA: Pomerium rejects it first (495). The
# no-device-facts tests below prove the policy would ALSO deny it (defense in depth).
package access_test

import rego.v1

import data.access

hour := (3600 * 1000) * 1000000

now := 1800000000000000000

healthy := {"disk_encrypted": "pass", "os_current": "pass", "firewall_on": "pass", "santa_lockdown": "pass"}

firewall_off := object.union(healthy, {"firewall_on": "fail"})

ivan := {"email": "ivan@lumenai.test", "groups": ["it-admins"]}

bob := {"email": "bob@lumenai.test", "groups": ["sales"]}

erin := {"email": "erin@lumenai.test", "groups": ["break-glass"]}

# Ivan's Mac, with whatever health and failure times a test needs
mac(policies, since) := {
	"serial": "ZR2JVG236J",
	"platform": "darwin",
	"owner_email": "ivan@lumenai.test",
	"policies": policies,
	"failing_since": since,
}

req(app, user, device) := {"app": app, "now_ns": now, "user": user, "device": device}

# ---- Scenario: no device certificate / no device facts ----------------------------

test_no_device_wiki_blocked if {
	d := access.decision with input as req("wiki", ivan, {})
	not d.allow
	"device_not_managed" in d.reasons
}

test_no_device_admin_blocked if {
	not access.allow with input as req("admin-console", ivan, {})
}

# ---- Scenario: managed device, wrong user ------------------------------------------

test_wrong_user_wiki_blocked if {
	d := access.decision with input as req("wiki", bob, mac(healthy, {}))
	not d.allow
	d.level == 0
	"device_not_assigned_to_you" in d.reasons
}

test_wrong_user_admin_blocked if {
	d := access.decision with input as req("admin-console", bob, mac(healthy, {}))
	not d.allow
	"device_not_assigned_to_you" in d.reasons
}

# ---- Scenario: correct user, firewall off (failing for 100 hours) ---------------------

test_firewall_off_wiki_allowed if {
	d := access.decision with input as req("wiki", ivan, mac(firewall_off, {"firewall_on": now - (100 * hour)}))
	d.allow
	d.level == 1
}

test_firewall_off_admin_blocked_with_remediation if {
	d := access.decision with input as req("admin-console", ivan, mac(firewall_off, {"firewall_on": now - (100 * hour)}))
	not d.allow
	d.level == 1
	"device_unhealthy" in d.reasons
	d.remediation == {"firewall_on"}
}

# ---- Scenario: correct user, failing for under 72 hours ------------------------------

test_grace_wiki_allowed if {
	access.allow with input as req("wiki", ivan, mac(firewall_off, {"firewall_on": now - (10 * hour)}))
}

test_grace_admin_allowed_with_warning if {
	d := access.decision with input as req("admin-console", ivan, mac(firewall_off, {"firewall_on": now - (10 * hour)}))
	d.allow
	d.level == 3
	count(d.warnings) == 1
}

test_grace_ends_at_72_hours if {
	not access.allow with input as req("admin-console", ivan, mac(firewall_off, {"firewall_on": now - (72 * hour)}))
}

test_grace_needs_every_failure_recent if {
	two := object.union(firewall_off, {"os_current": "fail"})
	since := {"firewall_on": now - (10 * hour), "os_current": now - (80 * hour)}
	not access.allow with input as req("admin-console", ivan, mac(two, since))
}

test_grace_unknown_start_time_is_not_grace if {
	not access.allow with input as req("admin-console", ivan, mac(firewall_off, {}))
}

# ---- Scenario: correct user, all checks passing --------------------------------------

test_healthy_wiki_allowed if {
	d := access.decision with input as req("wiki", ivan, mac(healthy, {}))
	d.allow
	d.level == 3
	count(d.warnings) == 0
}

test_healthy_admin_allowed if {
	d := access.decision with input as req("admin-console", ivan, mac(healthy, {}))
	d.allow
	count(d.alerts) == 0
}

# ---- Scenario: break-glass member ------------------------------------------------------

test_break_glass_wiki_allowed_with_alert if {
	d := access.decision with input as req("wiki", erin, mac(firewall_off, {}))
	d.allow
	some a in d.alerts
	a.type == "break_glass_access"
	a.user == "erin@lumenai.test"
}

test_break_glass_admin_allowed_with_alert if {
	d := access.decision with input as req("admin-console", erin, {})
	d.allow
	count(d.alerts) == 1
}

# ---- Edge cases -----------------------------------------------------------------------

test_missing_health_data_fails_closed if {
	no_santa_data := object.remove(healthy, ["santa_lockdown"])
	d := access.decision with input as req("admin-console", ivan, mac(no_santa_data, {}))
	not d.allow
	d.failing == {"santa_lockdown"}
}

test_santa_not_required_on_windows if {
	pc := {
		"serial": "115CE3BE",
		"platform": "windows",
		"owner_email": "ivan@lumenai.test",
		"policies": object.remove(healthy, ["santa_lockdown"]),
		"failing_since": {},
	}
	access.level == 3 with input as req("admin-console", ivan, pc)
}

test_admin_needs_it_admins_group if {
	alice := {"email": "alice@lumenai.test", "groups": ["engineering"]}
	alices_mac := object.union(mac(healthy, {}), {"owner_email": "alice@lumenai.test"})
	d := access.decision with input as req("admin-console", alice, alices_mac)
	not d.allow
	"missing_group" in d.reasons
}

test_email_match_ignores_case if {
	access.allow with input as req("wiki", {"email": "Ivan@LumenAI.test", "groups": []}, mac(healthy, {}))
}

test_unknown_app_denied if {
	not access.allow with input as req("payroll", ivan, mac(healthy, {}))
}

# ---- Scenario: traveling user (Step 2.6) ---------------------------------------------

ivan_abroad := {"email": "ivan@lumenai.test", "groups": ["it-admins", "traveling"]}

test_traveler_admin_blocked_even_when_healthy if {
	d := access.decision with input as req("admin-console", ivan_abroad, mac(healthy, {}))
	not d.allow
	d.level == 1
	d.device_level == 3
	"travel_mode" in d.reasons
	not "device_unhealthy" in d.reasons
}

test_traveler_wiki_allowed_with_travel_warning if {
	d := access.decision with input as req("wiki", ivan_abroad, mac(healthy, {}))
	d.allow
	d.level == 1
	some w in d.warnings
	startswith(w, "Travel mode is on")
}

test_traveler_on_someone_elses_device_still_blocked if {
	bob_abroad := {"email": "bob@lumenai.test", "groups": ["sales", "traveling"]}
	not access.allow with input as req("wiki", bob_abroad, mac(healthy, {}))
}

test_traveler_grace_does_not_lift_cap if {
	d := access.decision with input as req("admin-console", ivan_abroad, mac(firewall_off, {"firewall_on": now - (10 * hour)}))
	not d.allow
	d.level == 1
}

test_break_glass_overrides_travel_with_alert if {
	erin_abroad := {"email": "erin@lumenai.test", "groups": ["break-glass", "traveling"]}
	d := access.decision with input as req("admin-console", erin_abroad, {})
	d.allow
	count(d.alerts) == 1
}

test_back_home_admin_allowed_again if {
	access.allow with input as req("admin-console", ivan, mac(healthy, {}))
}

# ---- Exceptions: posture waivers (Step 3.4) --------------------------------------------

waiver(serial, check, expires) := [{"id": "EXC-0007", "serial": serial, "check": check, "expires_at": expires}]

# now = 1800000000 s = 2027-01-15T08:00:00Z
test_active_waiver_lets_device_through_with_warning if {
	d := access.decision with input as req("admin-console", ivan, mac(firewall_off, {"firewall_on": now - (100 * hour)}))
		with data.waivers as waiver("ZR2JVG236J", "firewall_on", "2027-01-20T00:00:00Z")
	d.allow
	d.waived == {"firewall_on"}
	some w in d.warnings
	contains(w, "EXC-0007")
}

test_expired_waiver_counts_again if {
	not access.allow with input as req("admin-console", ivan, mac(firewall_off, {"firewall_on": now - (100 * hour)}))
		with data.waivers as waiver("ZR2JVG236J", "firewall_on", "2027-01-01T00:00:00Z")
}

test_waiver_is_for_one_device_only if {
	not access.allow with input as req("admin-console", ivan, mac(firewall_off, {"firewall_on": now - (100 * hour)}))
		with data.waivers as waiver("OTHER-SERIAL", "firewall_on", "2027-01-20T00:00:00Z")
}

test_waiver_is_for_one_check_only if {
	not access.allow with input as req("admin-console", ivan, mac(firewall_off, {"firewall_on": now - (100 * hour)}))
		with data.waivers as waiver("ZR2JVG236J", "os_current", "2027-01-20T00:00:00Z")
}
