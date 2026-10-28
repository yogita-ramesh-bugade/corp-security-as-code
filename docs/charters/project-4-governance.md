# Charter: Project 4, SaaS and Agent Governance with LLM Triage

**Threats addressed:** S1 Consent phishing (16), S9 "Temporary" admin never removed (15, inventory and detection), S10 Device management console abused (15, detection), S3 Malicious browser extension (12), S8 Over-privileged AI agent (12), S11 Prompt injection into an agent (12, partial), S12 Chat bot collecting messages (12). See [threat-model.md](../threat-model.md).

## Problem

About 300 outside apps are connected to Lumen's email and documents, and nobody chose or reviews them (S1). Chat bots, browser extensions, admin roles and about 25 AI agents with real credentials are equally unreviewed (S3, S8, S9, S12). Reviewing everything by hand would create a long queue that people work around. Lumen needs a complete inventory, automatic decisions for routine cases, a faster review for the rest, and alerts when attacks happen.

## In scope

- Collectors for OAuth grants (Keycloak), chat apps and tokens (Mattermost), browser extensions (osquery via Fleet), admin roles, and a registry of internal apps and AI agents, including a synthetic long tail.
- Risk scores with listed reasons.
- Policy rules that auto-approve and auto-deny routine items.
- A local LLM (Llama 3.1 via Ollama) recommending decisions for the review queue, with item content treated as untrusted data.
- An evaluation against about 200 items labeled by hand, including prompt-injection cases, and an RFC setting model-versus-human handoff rules.
- Sigma detections in Elastic for consent phishing, posture drift, admin changes outside a change window, and break-glass use.

## Out of scope

- Real Google Workspace, Microsoft 365 or Slack tenants; these are simulated with Keycloak and Mattermost.
- Blocking apps at the moment of consent; this project reviews and revokes after consent.
- Preventing prompt injection inside each agent (S11 gap; recommended to agent owners).
- Fine-tuning or training a model.
- Incident response after an alert fires.

## Done means

1. One command produces a single inventory containing all five item types.
2. Every inventory item has a risk score with the factors that produced it.
3. Policy rules decide a reported share of items automatically, and every remaining item appears in the review channel with a model recommendation and approve/deny buttons.
4. The evaluation reports agreement, false-approve rate per item type and injection success rate, and the RFC states which decisions the model may support and which stay human.
5. The consent-phishing simulation triggers an alert in Kibana within 5 minutes, and every Sigma rule passes its positive and negative tests in CI.

## Metrics

- Share of items decided by policy alone.
- Time from an item entering the queue to a decision.
- Model agreement with human labels, and false-approve rate per item type.
- Share of prompt-injection test items that fooled the model.
- Time from simulated attack to alert.

## User impact

- **Employees connecting apps:** routine requests are decided immediately; others get a faster review. Alternative path when denied: a list of approved apps that do the same job.
- **Agent owners:** must register each agent with an owner and scopes, and accept periodic review.
- **Reviewers:** a shorter queue, with a recommendation and reasons attached to each item.
- **Risk:** a wrong denial blocks a legitimate tool. Mitigation: every decision can be appealed to a human.

## Tooling choice

| Need | Picked | Rejected | Why |
| --- | --- | --- | --- |
| Triage model | Llama 3.1 via Ollama, run locally | Hosted API only | Free, and data stays on the machine. The design keeps the model swappable, so a hosted model such as Claude can be compared later. |
| Decision approach | Rules first, LLM for the rest | LLM for everything | Rules are predictable and auditable; the model is used only where rules can't decide, and never acts on its own. |
| Detection format | Sigma | Elastic queries written directly | Sigma rules are portable to other SIEMs and are a shared industry format. |
| SIEM | Elastic (free Basic licence) | Splunk | Splunk's free option is limited; Elastic is free to self-host and matches prior experience. |
