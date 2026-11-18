# RFC: Travel mode and mobile devices

| | |
| --- | --- |
| **Status** | Proposed |
| **Author** | Yogita Bugade (Security Engineering) |
| **Date** | 2026-11-18 |
| **Threats** | S6 Laptop imaged at a border; S2 Stolen session cookie replayed (see [threat-model.md](../threat-model.md)) |
| **Depends on** | Keycloak groups (Step 2.1), device certificates (2.2), posture gate + OPA (2.4), remediation page (2.5) |

## 1. Summary

When someone travels, Lumen temporarily lowers what their account can reach, and for high-risk destinations
gives them a loaner laptop that carries nothing worth taking. Travel is recorded in a reviewed file
(`access-gate/travel/trips.yaml`) with a start and end date. While a trip is active the person is in the Keycloak
group `traveling`, and the access policy caps them at **level 1**: everyday apps work, admin consoles don't. On
return they are signed out everywhere and their laptop is re-checked before full access comes back. For phones,
we recommend Lockdown Mode on high-risk trips and set out what IT can and can't see on company versus personal
phones.

## 2. Problem

At some borders officials can inspect or copy devices, and hotel rooms aren't safe places to leave a laptop
(S6). A laptop that's out of its owner's sight may come back with its disk copied, its session cookies taken (S2),
or something installed. Today, Lumen travelers take their everyday laptop, with full access, including admin
access for IT staff, and nothing changes when they cross a border. Phones carry company email and chat too, but
many are personal, and employees reasonably don't want IT to control or see their whole phone.

## 3. Goals and non-goals

**Goals**
- Reduce what a seized or copied laptop can reach while abroad, automatically, with a clear end date.
- Keep everyday work possible while traveling, with an explained path for emergencies.
- On return, make anything copied while abroad (sessions, cookies) useless, and re-check the device.
- Give phone guidance that protects company data without taking over personal phones.

**Non-goals**
- Forensics on returned devices (handled by incident response if tampering is suspected).
- Legal advice on border searches; Legal owns that guidance. This RFC covers technical controls only.
- Android specifics (Android Enterprise work profile is the equivalent of User Enrollment; a separate note).

## 4. Design

### 4.1 Destination tiers

| Tier | Who decides | What applies |
| --- | --- | --- |
| **Standard** | Default for all trips | Own laptop, **travel mode** (4.3), phone hygiene (4.5) |
| **High** | Security keeps a list, reviewed quarterly, based on government travel advisories and Legal's guidance on device searches | **Loaner laptop** (4.2) + travel mode + **loaner phone or Lockdown Mode** (4.5) |

The tier is a field in `trips.yaml`, so it's visible in review and in the audit trail.

### 4.2 Loaner laptops (high tier)

- **Before:** IT issues a loaner from a small pool: freshly imaged, enrolled in Fleet, FileVault/BitLocker on,
  Santa in Lockdown, a device certificate (Step 2.2), and only the apps the trip needs. No source code, no SSH
  keys, no local mail archive, no saved passwords. The person's everyday laptop stays locked in the office.
- **During:** The loaner is assigned to the traveler in Fleet (human-device mapping), so the posture gate treats it
  as theirs. Travel mode still applies.
- **On return:** The loaner goes straight to IT **without being connected to the corporate network**. IT revokes its
  device certificate, deletes it from Fleet, and erases it completely (Erase All Content and Settings on Mac;
  reset/re-image on Windows), then re-images it before it goes back into the pool.
- **If a device was taken out of sight** (held at a border, left in a hotel room and found disturbed): treat it as
  compromised. Don't reconnect it; IT re-images it, and the person rotates their password and reviews connected
  apps (Project 4's OAuth inventory).

### 4.3 Travel access tier

**How someone enters travel mode**

1. The traveler (or their manager) adds the trip to `access-gate/travel/trips.yaml` in a pull request:
   ```yaml
   - user: tara
     destination_tier: standard
     start: "2026-11-01"
     end: "2026-12-31"
   ```
2. On merge, `terraform apply` puts the user in the Keycloak group `traveling`, but only while today is between
   `start` and `end`. Terraform computes this from the plan's date (`plantimestamp()`), so after the end date the
   next apply removes the group by itself. A scheduled daily apply means nobody has to remember.
3. `access-gate/travel/session_reset.sh <user>` signs them out everywhere through Keycloak's admin API, so their
   next sign-in carries the `traveling` group.

**Why a reviewed file, not a click in Keycloak:** Terraform corrects drift (Step 2.1): a membership added by hand
in the admin console is removed on the next apply. Keeping trips in Git gives a review, an audit trail, and an
end date that enforces itself. In production, Project 3's joiner/mover/leaver engine can write the same record
from the travel-booking system.

**What the policy does** (`access-gate/policy/access.rego`)

```rego
travel_cap := 1

traveling if "traveling" in input.user.groups

level := device_level if not traveling

level := min({device_level, travel_cap}) if traveling
```

- The device is still checked normally (`device_level`); travel mode only **caps** the result.
- Wiki (needs level 1) keeps working, with a "Travel mode is on" warning. Admin console (needs level 3) is blocked
  with the reason `travel_mode`, and the remediation page says "The Admin Console is paused while you travel.
  Nothing is wrong with your laptop."
- The 72-hour grace period does not lift the cap.
- **Emergencies:** break-glass members are still allowed, and every use raises a high-severity alert, so
  "I need admin access from abroad" is possible but always seen and reviewed.

**Tests** (`access_test.rego`, run with `opa test access-gate/policy -v`): a healthy traveler is blocked from the
admin console with `travel_mode`, not `device_unhealthy`; the wiki still works with the travel warning; a traveler
on someone else's laptop is still blocked; grace doesn't lift the cap; break-glass overrides travel with an
alert; back home, admin access returns. Deliberately removing the cap makes 3 tests fail.

### 4.4 On return

1. The trip's end date passes (or a PR shortens it) and `terraform apply` removes `traveling`.
2. `session_reset.sh <user> <serial>` signs the user out of every Keycloak session and asks Fleet to re-check
   the laptop now (refetch).
3. The posture gate evaluates the laptop's fresh health results on the next request; if anything changed while
   abroad, the remediation page shows exactly what.
4. The user signs in again.

**Known gap:** Pomerium keeps its own session and only notices the Keycloak sign-out when it next refreshes the
user's token (at most 15 minutes, the realm's access token lifespan), and the gate caches decisions for 60 seconds.
Production should add Pomerium session revocation to the same step.

### 4.5 Phones

**Before any trip:** update the phone, remove work apps you won't need, and know how to reach IT without the
phone (printed number).

**High-tier trips:** carry a loaner phone with only work chat and email, or, on your own iPhone, turn on
**Lockdown Mode** (Settings > Privacy & Security > Lockdown Mode). It sharply reduces the attack surface used
by targeted spyware: many message attachment types are blocked, some web technologies are disabled, and
incoming FaceTime calls from unknown people are blocked. Two practical notes:
- While Lockdown Mode is on, configuration profiles can't be installed and the phone **can't enroll** in device
  management. **Enroll before turning it on**; a phone already enrolled stays managed.
- Some websites and attachments won't work. Turn it off after the trip if the restrictions get in the way.

### 4.6 Company-owned versus personal phones

| | Company-owned phone, **Automated Device Enrollment** (supervised) | Personal phone, **User Enrollment** |
| --- | --- | --- |
| Who owns it | Lumen | The employee |
| Erase the phone | Yes, the whole device | **No.** Only work data: removing enrollment deletes the work accounts, apps and data, and personal data is untouched |
| See installed apps | All apps | **Only work (managed) apps** |
| Serial number, UDID, IMEI, phone number | Yes | **No.** A random enrollment ID that changes if the phone re-enrolls |
| Location | Only after IT puts it in Lost Mode | **No** (Lost Mode not available) |
| Read photos, messages, browsing | No (device management can't read personal content) | No |
| Passcode rules | Full policy (length, complexity, auto-lock) | Can require a passcode (6+ characters, no simple ones), not complex rules |
| Restrictions and settings | Full set, including supervised-only ones; employee can't remove management | Limited set; employee can unenroll at any time |
| VPN | Device-wide | **Per-app only**, for work apps |
| Apps | Install and remove any app silently | Install work apps; can't take over personal apps |
| Hardware-bound device certificate (Step 2.2) | Yes, attested with serial | No serial in the attestation, so it can't be tied to a specific phone |
| Activation Lock | IT can manage and bypass it | No |
| Managed Apple Account | Optional | Required (separate from the employee's personal Apple Account) |

**Recommendation:** company-owned (ADE) phones for IT admins, executives and high-tier travelers; User Enrollment
for everyone else who wants work email and chat on their own phone. Work data is kept on a separate encrypted
volume, which IT can remove without touching anything personal.

**Lab:** optionally enroll a *spare* iPhone or iPad in Fleet as a personal device to see User Enrollment for
yourself. **Never enroll a main personal phone in a lab server.**

## 5. User impact

| Who | What changes | Alternative path |
| --- | --- | --- |
| Every traveler | Admin consoles paused while abroad; everyday apps work, with a banner | Request an exception; break-glass for real emergencies (alerted) |
| High-tier travelers | Carry a loaner laptop (and phone) | Loaners are pre-set with the apps the trip needs; book via IT 5 working days ahead |
| Returning travelers | Signed out once; sign in again | The remediation page explains any device issue found on return |
| Phone users | Choice of company phone or User Enrollment | Personal phones keep full privacy: IT sees only work apps |

## 6. Rollout

1. **Pilot:** IT staff on their next trips (they're the people whose access matters most and who can give
   technical feedback).
2. **All travelers** after 4 weeks if: no trip where a needed everyday app was blocked, and no break-glass use for
   convenience.
3. Daily scheduled `terraform apply` for trip expiry before the general rollout.
4. **Rollback:** set `travel_cap := 3` (one-line PR) to disable the cap while keeping the record of trips.

## 7. Metrics

- Trips registered versus trips booked (coverage).
- Break-glass uses while traveling (each one reviewed).
- Time from return to full access (sign-out + device re-check + new sign-in).
- Loaners re-imaged within 1 working day of return.
- Exception requests citing travel mode (signals whether level 1 is too strict).

## 8. Risks and open questions

- **Unregistered trips:** travel mode only works for trips in the file. A booking-system feed (Project 3) closes
  this gap; until then, managers confirm trips in the PR.
- **Sign-in from abroad without a registered trip:** a future rule could raise an alert when the sign-in location
  doesn't match any active trip.
- **Pomerium session lag** (up to 15 minutes) after sign-out, see 4.4.
- **Lockdown Mode compatibility** with work apps needs testing before it's recommended company-wide.

## Sources

- [Apple: About Lockdown Mode](https://support.apple.com/en-in/HT212650)
- [Microsoft: Apple User Enrollment in Intune, supported actions](https://learn.microsoft.com/sl-SI/mem/intune/enrollment/ios-user-enrollment-supported-actions)
- [Hexnode: Apple User Enrollment for iOS devices](https://www.hexnode.com/mobile-device-management/help/apple-user-enrollment-for-ios-devices.md)
- [Apple Platform Deployment: Managed Device Attestation](https://support.apple.com/guide/deployment/dep28afbde6a)
