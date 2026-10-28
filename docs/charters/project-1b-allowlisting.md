# Charter: Project 1B, Allowlisting and Enforcement Rollout

**Threats addressed:** S4 Unsigned tool from a script (16), S13 Poisoned open-source package (15, partial). See [threat-model.md](../threat-model.md).

## Problem

Any program can run on any Lumen laptop. An engineer who runs a malicious setup script (S4) or installs a poisoned package (S13) gives an attacker a foothold with access to source code and CI secrets. Allowlisting stops unknown programs from running, but it's one of the most disruptive controls a company can deploy: done carelessly, it breaks people's tools and gets switched off. The real problem is turning it on *without* that happening.

## In scope

- Santa on macOS in monitor mode, with a Moroz sync server and rules stored in Git.
- Windows App Control (WDAC) in audit mode, with audit events exported.
- A synthetic 3,000-device fleet with four weeks of execution events, with every assumption documented.
- A readiness analysis: rule coverage, projected blocks per 100 devices per week by team, breakage classes, and an alternative path for each class.
- A rollout RFC with rings, gates, communications, FAQ and rollback.
- Lockdown on the canary VM, with a custom block message linking to the exception process.

## Out of scope

- Enforcing WDAC; Windows stays in audit mode in this lab.
- Allowlisting on Linux.
- Package and dependency controls (internal package mirror, pinning, scanning). These are needed to fully address S13, and are recommended to the engineering and infrastructure teams.
- A self-service approval interface beyond Project 3's exception bot.

## Done means

1. Santa in monitor mode syncs with Moroz, and execution events from the macOS VM arrive at the server.
2. WDAC audit mode on the Windows VM records event 3076 for an unsigned test tool, and the events are exported for analysis.
3. The readiness notebook reports coverage, projected blocks per 100 devices per week by team, the breakage classes, and an alternative path for each class.
4. The analysis identifies a rule set under which projected blocked-and-appealed events are below 1 per 100 devices per week.
5. On the canary VM in lockdown, an unknown binary is blocked with the custom message and exception link, while allowlisted apps run normally.

## Metrics

- Coverage: percentage of executions allowed by current rules.
- Projected blocks per 100 devices per week, overall and by team.
- Reduction in projected blocks from transitive (compiler) rules.
- Rule mix: share of Team ID and Signing ID rules versus hash rules (hash rules break on every update, so a lower share is better).

## User impact

- **Most affected: engineers.** Self-built tools and package installs are the largest breakage class. Alternative paths: transitive rules allow programs built by approved compilers; internal tools get signed; temporary exceptions are available through Project 3.
- **Teams using rare apps:** per-team rules, added through reviewed pull requests.
- **Everyone:** an announcement 14 days before enforcement, a reminder at 7 days, a plain-language FAQ, and a block message that links to help rather than a dead end.
- **Safety net:** canary and pilot rings with numeric gates; rollback to monitor mode is a single pull request.

## Tooling choice

| Need | Picked | Rejected | Why |
| --- | --- | --- | --- |
| macOS allowlisting | Santa (North Pole Security) | Gatekeeper alone; commercial tools such as Airlock or ThreatLocker | Gatekeeper can't allow or deny specific apps precisely. Commercial tools are paid. Santa is open source, mature, supports Team ID and Signing ID rules, and has transitive rules. |
| Santa sync server | Moroz | Rudolph; North Pole Workshop | Rudolph needs AWS (ongoing cost); Workshop is commercial. Moroz is simple and free for a lab. |
| Windows allowlisting | App Control for Business (WDAC) | AppLocker | Built in to Windows, and Microsoft directs new deployments to App Control. |
| Fleet-scale data | Synthetic generator | Real fleet data | Real data isn't available and must never be used; assumptions are documented instead. |
