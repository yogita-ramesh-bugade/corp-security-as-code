# Lumen AI access policy (Project 2, Step 2.4)
#
# The posture gate collects FACTS (who the user is, which device, how healthy it is)
# and sends them here as `input`. This file holds the RULES. Changing who can reach
# what means editing this file and its tests, not the gate's code.
#
# input = {
#   "app":    "wiki" | "admin-console",
#   "now_ns": <current time, nanoseconds>            # passed in so tests are repeatable
#   "user":   {"email": "...", "groups": ["..."]},   # from Pomerium's signed token
#   "device": {                                      # from Fleet, looked up by certificate serial
#     "serial": "...", "platform": "darwin|windows|ubuntu|...",
#     "owner_email": "...",                          # Fleet human-device mapping
#     "policies": {"disk_encrypted": "pass|fail|missing", ...},
#     "failing_since": {"firewall_on": <ns>, ...}    # when the gate first saw each check failing
#   }
# }
package access

import rego.v1

# ---------------------------------------------------------------- levels per app

# 3 = your device, fully healthy (or failing for under 72 hours)
# 1 = your device, but failing a health check
# 0 = not your device, or no device facts at all
# Travel mode (group "traveling", Step 2.6) caps the level at 1 while abroad.
required_level := {"wiki": 1, "admin-console": 3}

# Group an app also requires (on top of the device level). The proxy checks this too;
# keeping it here means the policy is complete and testable on its own.
required_group := {"admin-console": "it-admins"}

grace_hours := 72

# ---------------------------------------------------------------- device facts

strict_checks := ["disk_encrypted", "os_current", "firewall_on", "santa_lockdown"]

# Santa only exists on macOS; every other check applies to every platform.
applies(check) if check != "santa_lockdown"

applies("santa_lockdown") if input.device.platform == "darwin"

bound if {
	input.device.owner_email != ""
	lower(input.device.owner_email) == lower(input.user.email)
}

# Fail closed: a check with no data ("missing") counts as failing, not passing.
failing contains check if {
	some check in strict_checks
	applies(check)
	object.get(input.device, ["policies", check], "missing") != "pass"
}

hours_failing(check) := (input.now_ns - input.device.failing_since[check]) / ((3600 * 1000) * 1000000)

# Grace: every failing check started failing less than 72 hours ago.
in_grace if {
	count(failing) > 0
	every check in failing {
		hours_failing(check) < grace_hours
	}
}

# ---------------------------------------------------------------- level

default device_level := 0

device_level := 3 if {
	bound
	count(failing) == 0
}

device_level := 3 if {
	bound
	in_grace
}

device_level := 1 if {
	bound
	count(failing) > 0
	not in_grace
}

# ---------------------------------------------------------------- travel mode

# While someone is abroad, their laptop may be inspected, copied or taken.
# Cap them at level 1: everyday apps keep working, admin consoles don't.
travel_cap := 1

traveling if "traveling" in input.user.groups

level := device_level if not traveling

level := min({device_level, travel_cap}) if traveling

# ---------------------------------------------------------------- break-glass

break_glass if "break-glass" in input.user.groups

# ---------------------------------------------------------------- allow

has_required_group if not required_group[input.app]

has_required_group if required_group[input.app] in input.user.groups

default allow := false

allow if {
	level >= required_level[input.app]
	has_required_group
}

# Break-glass members are always let in (emergencies, e.g. Fleet is down),
# and every single use raises an alert for the security team.
allow if break_glass

# ---------------------------------------------------------------- explanations

alerts contains {
	"type": "break_glass_access",
	"severity": "high",
	"user": input.user.email,
	"app": input.app,
	"device_serial": object.get(input.device, "serial", ""),
} if {
	break_glass
}

warnings contains "Travel mode is on: admin tools are unavailable until you're back and IT has re-checked your laptop." if {
	allow
	traveling
}

warnings contains msg if {
	allow
	in_grace
	some check in failing
	msg := sprintf("%s is failing. You have %d hours left to fix it before access is reduced.", [check, round(grace_hours - hours_failing(check))])
}

reasons contains "device_not_managed" if not input.device.serial

reasons contains "device_not_assigned_to_you" if {
	input.device.serial
	not bound
}

reasons contains "missing_group" if not has_required_group

reasons contains "device_unhealthy" if {
	bound
	device_level < required_level[input.app]
}

reasons contains "travel_mode" if {
	traveling
	level < required_level[input.app]
	device_level >= required_level[input.app]
}

reasons contains "unknown_app" if not required_level[input.app]

# Only the checks the user has to fix, and only when they are blocked because of them.
remediation contains check if {
	not allow
	"device_unhealthy" in reasons
	some check in failing
}

# One object for the gate to act on.
decision := {
	"allow": allow,
	"level": level,
	"device_level": device_level,
	"required_level": object.get(required_level, input.app, null),
	"reasons": reasons,
	"remediation": remediation,
	"warnings": warnings,
	"alerts": alerts,
	"failing": failing,
}
