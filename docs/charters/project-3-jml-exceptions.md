# Charter: Project 3, Joiner/Mover/Leaver Engine and Exception Bot

**Threats addressed:** S7 Leaver's access still works (16), S9 "Temporary" admin never removed (15). Also fixes the weakness "exceptions are granted over chat and never expire." See [threat-model.md](../threat-model.md).

## Problem

Lumen sets up new hires through IT tickets, which takes 2–3 days, and removes leavers' access by hand, which sometimes takes up to a week (S7). Nothing reviews or removes access when people change teams, so rights pile up, including admin rights granted "temporarily" (S9). Exceptions to security rules are agreed over chat and never expire, so they quietly turn into permanent holes. With about 80 joiners, 30 movers and 15 leavers a month, manual processes can't keep up.

## In scope

- A mock HR system that sends signed webhooks when people are hired, moved or terminated.
- Birthright access rules per role, stored in Git (`jml/roles.yaml`).
- A reconciliation engine that applies joiner, mover and leaver changes across Keycloak, Mattermost and Fleet, with an append-only audit log.
- A nightly reconciliation run that flags orphaned accounts.
- A Mattermost exception bot: request, approval routing, changes applied through pull requests or OPA data, reminders, and automatic expiry.
- A dashboard of open exceptions.

## Out of scope

- Real HR systems such as Workday; a mock is used.
- The SCIM standard for provisioning (Keycloak has no built-in outbound SCIM); Keycloak's admin API is used instead.
- A full access-request portal for non-birthright access; only security exceptions are handled.
- Real data transfer and device return logistics for leavers; these are simulated.

## Done means

1. A hire event creates the Keycloak user, birthright groups and chat account with no manual steps.
2. A termination event disables all accounts and revokes all sessions and OAuth consents within 5 minutes, and every action appears in the audit log.
3. All six edge-case tests pass: duplicate webhook, rehire, contractor converting to full-time, two moves in one week, termination during a move, and Keycloak failing midway.
4. The nightly run flags a deliberately planted orphan account.
5. An exception goes through the full loop: requested, approved, applied through a pull request, and automatically revoked at expiry.

## Metrics

- Time to access for joiners, from hire event to working login.
- Time to revoke for leavers, from termination event to last access removed.
- Orphaned accounts found by nightly reconciliation.
- Open exceptions, median exception length, and renewal rate.

## User impact

- **New hires:** access ready on day one instead of after 2–3 days.
- **Movers:** old-role access is removed. Alternative path: their new manager confirms any extra access they still need, instead of it simply disappearing.
- **Leavers:** access ends immediately. Risk: a wrong or early HR record could lock out the wrong person. Mitigation: every action is logged and reversible, and nightly reconciliation catches mismatches.
- **People needing exceptions:** a request through chat with a clear owner and deadline, and a reminder before expiry rather than a surprise.

## Tooling choice

| Need | Picked | Rejected | Why |
| --- | --- | --- | --- |
| Lifecycle automation | Custom Python reconciliation engine | Commercial identity governance (SailPoint, Okta Workflows); one script per event | Commercial tools are paid. Per-event scripts aren't safe to re-run; reconciliation always converges on the right state, even after a crash. |
| Chat platform | Mattermost (open source) | Slack | Slack's app-inventory admin APIs need paid Enterprise plans; Mattermost exposes them for free. |
| Web services | FastAPI | Flask | Built-in request validation and automatic API documentation. |
| HR data store | SQLite | PostgreSQL | A single file is enough for a mock HR system. |
