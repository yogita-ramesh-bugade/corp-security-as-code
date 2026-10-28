# Charter: Project 2, Device-Trust Access Gate

**Threats addressed:** S2 Stolen session replayed (15), S10 Device management console abused (15), S5 Unpatched laptop exploited (12), S6 Laptop imaged at a border (8, travel add-on). See [threat-model.md](../threat-model.md).

## Problem

Lumen's apps accept a valid login from any device. A session cookie stolen from a personal computer works anywhere, skipping the password and MFA (S2). An attacker who takes over an IT admin's session can reach the device management console from their own machine (S10). An infected or out-of-date laptop gets the same access as a healthy one (S5). Access should depend on the person, the device, *and* the device's current health, and people on failing devices should be told how to fix them rather than simply blocked.

## In scope

- Keycloak (users, groups, OIDC client), managed with Terraform.
- A lab certificate authority (step-ca) issuing each device a certificate tied to its serial number.
- Pomerium in front of two demo apps, requiring a device certificate (mutual TLS).
- A posture gate that combines identity, device ownership and Fleet policy results, with decisions made by an OPA policy.
- Access levels: wiki at level 1, admin console at level 3. A 72-hour grace period, and break-glass access with alerts.
- A self-service remediation page.
- Travel add-on: a written plan and a policy rule capping travelers at level 1.

## Out of scope

- Hardware-bound device keys (Apple Managed Device Attestation). Documented as the production design; in the lab, certificates could be copied.
- Non-web access such as SSH or databases.
- Enforcing device trust on phones; covered in the travel and mobile plan only.
- High availability and production-grade operation of the components.

## Done means

1. A device without a certificate is refused by Pomerium for both demo apps.
2. All OPA unit tests pass, covering: wrong user, failing check, grace period, all checks passing, break-glass, and traveling user.
3. A correct user on a device failing a check reaches the wiki but sees a remediation page for the admin console, naming the failed check and how to fix it.
4. Every break-glass access raises an alert.
5. A non-security tester fixes a failing VM using only the remediation page, and their time is recorded.

## Metrics

- Time to remediate, from denial to access granted.
- Denials by failing check (which checks cause the most friction).
- Share of access allowed only because of the grace period.
- Delay added by the gate to each request, in milliseconds.

## User impact

- **Everyone:** apps work only from their assigned company device. Alternative path for personal devices: none for sensitive apps, which is intended; this is explained in the announcement.
- **People on failing devices:** a fix-it page with plain steps, plus a 72-hour grace period before access drops.
- **Emergencies:** break-glass access through a dedicated group, alerted every time it's used.
- **Travelers:** reduced access while abroad, a loaner laptop for high-risk trips, and a sign-out everywhere on return.

## Tooling choice

| Need | Picked | Rejected | Why |
| --- | --- | --- | --- |
| Identity-aware proxy | Pomerium (open-source core) | oauth2-proxy; commercial services such as Cloudflare Access or Zscaler | oauth2-proxy handles login but not device certificates. Commercial services are paid and hide the design. Pomerium is open source and supports mutual TLS. |
| Identity provider | Keycloak | Authentik | Both are capable; Keycloak is more widely deployed in enterprises and has a mature Terraform provider. |
| Access decisions | OPA (Rego) | Rules written directly in Python | Separate policy can be reviewed and unit-tested on its own, and changed without changing code. |
| Device certificates | step-ca | Certificates created by hand with OpenSSL | step-ca automates issuing and supports ACME, including the device attestation used in production. |
