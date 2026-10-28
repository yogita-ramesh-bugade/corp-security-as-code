# Charter: Project 1A, Fleet Baseline as Code

**Threats addressed:** S3 Malicious browser extension (12), S5 Unpatched laptop exploited (12). Foundation for S2, S4 and S10, which later projects address. See [threat-model.md](../threat-model.md).

## Problem

Lumen's laptops are enrolled in device management, but settings are applied by hand and inconsistently. Encryption coverage on Windows and Linux is unknown, updates aren't enforced (S5), and browser extensions are unrestricted (S3). Nobody can prove which laptops are actually secure. Every later control depends on knowing each device's state, so this comes first.

## In scope

- Fleet server, with macOS, Windows and Linux VMs enrolled.
- All Fleet settings stored in Git and applied with `fleetctl gitops`.
- Baselines: disk encryption, firewall, screen lock, Gatekeeper (macOS), attack surface reduction rules in audit mode (Windows), SSH hardening and automatic updates (Linux).
- macOS update deadlines with Nudge.
- Chrome policy (extension allowlist, Safe Browsing, password manager off) rendered from one source file for all three OSes.
- osquery compliance policies for every baseline item.
- CI pipeline with validation, plain-English policy diffs, and canary, pilot and all rollout rings.

## Out of scope

- ChromeOS device management (needs a paid Chrome Enterprise Upgrade); ChromeOS is covered through browser policy only.
- Automated Device Enrollment (needs Apple Business Manager); manual enrollment is used instead.
- Mobile devices (planned in the Project 2 travel add-on).
- Endpoint detection and response (EDR) and general software distribution.
- Real production scale; the lab has three VMs.

## Done means

1. All three VMs show online in Fleet and answer a live query.
2. Every Fleet setting is applied from Git, and a change made in the Fleet UI is reverted by the next `fleetctl gitops` run.
3. Each VM passes every baseline policy, and a deliberately broken setting turns its policy to failing within one hour.
4. A pull request containing an invalid profile fails CI, and a valid one, once merged, changes only devices in `ring-canary`.
5. `chrome://policy` shows identical values on all three VMs, generated from `browser/policy.yaml`.

## Metrics

- Percentage of hosts passing each baseline policy (Fleet policy results).
- Time from pull request merge to the setting appearing on a canary device.
- Number of broken changes caught by CI before reaching any device.
- Number of drift reverts, meaning UI changes undone by GitOps.

## User impact

- **Everyone:** screen lock and firewall settings can't be turned off. This is announced in advance, and the reasons are explained.
- **Mac users:** Nudge reminders before an update deadline. Alternative path: install at a convenient time before the deadline instead of facing a forced restart.
- **Extension users:** unapproved extensions are blocked. Alternative path: an approved list, plus a request process (Project 4).
- **Safety net:** rollout rings limit any mistake to canary devices, and rollback is a single revert pull request.

## Tooling choice

| Need | Picked | Rejected | Why |
| --- | --- | --- | --- |
| Device management | Fleet (open source) | Jamf, Intune, Kandji | Paid licences, and their configuration can't be published publicly. Fleet covers macOS, Windows and Linux, supports GitOps, and includes osquery. |
| Apple-only MDM alternative | n/a | MicroMDM / NanoMDM | Apple-only, and more assembly needed for a multi-OS lab. |
| macOS updates | Nudge | Forced update deadlines only | Nudge gives clear, escalating reminders instead of surprise restarts. Declarative update enforcement is noted as the production complement. |
| Linux configuration | Ansible | Chef, Puppet | Agentless and simpler for a few machines. |
| CI | GitHub Actions | Self-hosted Jenkins | Free for public repos, with nothing to run. |
