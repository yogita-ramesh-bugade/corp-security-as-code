# Lumen AI Threat Model

Based on the company described in [company.md](company.md). Lumen AI is fictional, and all data in this project is synthetic.

This is a living document: it is updated as projects are built and new risks are found.

## Contents

1. Assets: what we're protecting
2. Attacker stories
3. Scoring and ranking (added in Step 4)

---

## 1. Assets: what we're protecting

"Who or what can reach it" includes people *and* programs, because attackers usually arrive through programs.

### Identities and access

| Asset | Where it lives | Who or what can reach it |
| --- | --- | --- |
| Employee accounts (username, password, MFA) | Keycloak SSO | Each employee; ~10 Keycloak admins; anyone who phishes an employee |
| Login session tokens (cookies) | Browsers on laptops and personal computers | The employee; any browser extension; any malware on that computer; anyone using that computer |
| OAuth grants to outside apps | Servers of ~300 third-party vendors | Those vendors; anyone who breaches a vendor |
| AI agent credentials (API keys, OAuth tokens) | Agent config files, some in code | Agent owners (many unknown); anyone with access to that code; anyone who can feed the agent instructions |
| Admin rights | Keycloak, Fleet, cloud console, chat | ~60 admins, some granted "temporarily" and never removed |

### Devices

| Asset | Where it lives | Who or what can reach it |
| --- | --- | --- |
| Laptops (1,400 Mac, 400 Windows, 100 Linux, 100 Chromebook) | Homes, offices, cafes, airports, abroad | The employee; family members; thieves; border officials; every program the employee runs |
| Company and personal phones | With employees everywhere | The owner; anyone who unlocks it; apps installed on it |

### Data

| Asset | Where it lives | Who or what can reach it |
| --- | --- | --- |
| Customer data | Production cloud | ~120 engineers; production services; support tools |
| Source code and CI/CD secrets | Code hosting | ~1,000 engineers and researchers; CI pipelines; connected bots |
| AI model weights and training data | Research storage | ~300 researchers; training jobs |
| Email, calendars, documents | Email and documents suite | All employees; ~300 connected OAuth apps; people with delegated access |
| Chat history | Mattermost | All employees; bots; webhooks; integrations |
| Employee personal data | HR system | HR; managers; systems connected to HR |

### Control systems (crown jewels)

These can change everything else, so a compromise of any one is a compromise of the company.

| Asset | Where it lives | Who or what can reach it |
| --- | --- | --- |
| SSO admin console | Keycloak | ~10 IT admins; their laptops and sessions |
| Device management console | Fleet | IT and Security; can push software to every laptop |
| Production cloud admin | Cloud console | ~120 engineers with admin roles |
| Security tooling (SIEM, logs) | Elastic | Security team; log shippers on every system |

### What the "who can reach it" column tells us

1. **Personal computers can hold work session tokens**, so stealing a cookie from an unmanaged computer bypasses passwords and MFA.
2. **About 300 outside vendors can read email and documents.** Nobody chose them centrally, and nobody reviews them.
3. **AI agents hold real credentials, but many have no owner**, and anyone who can send them text may be able to steer them.
4. **Laptops travel everywhere** and run any program, so one bad download can reach everything the employee can.
5. **Control systems are reachable from ordinary admin laptops**, so an admin's laptop is as valuable as the console itself.
6. **Admin rights and access pile up**, because nothing removes them automatically.

---

## 2. Attacker stories

Template: **an attacker who has X can do Y because Z.** Z is the weakness a control must remove, and each Z matches a weakness in [company.md](company.md).

Technique IDs are from MITRE ATT&CK Enterprise (version: v20.0) and, for AI-specific risks, MITRE ATLAS.

### S1. Consent phishing
An attacker who **sends an employee a convincing "open this shared document" link** can **get them to approve a malicious OAuth app that reads their email and files** because **any employee can approve any outside app, and nobody reviews grants.**
- Asset: email and documents; OAuth grants
- ATT&CK: T1566.002 Spearphishing Link; T1528 Steal Application Access Token

### S2. Stolen session cookie replayed
An attacker who **steals a session cookie from an employee's personal computer** can **sign in to company apps as that employee, skipping the password and MFA,** because **apps accept a valid session from any device.**
- Asset: session tokens
- ATT&CK: T1539 Steal Web Session Cookie; T1550.004 Use Alternate Authentication Material: Web Session Cookie

### S3. Malicious browser extension
An attacker who **publishes or buys a popular browser extension** can **read every internal page an employee opens** because **extensions are unrestricted on company laptops.**
- Asset: internal app data; session tokens
- ATT&CK: T1176 (browser extensions; recent ATT&CK versions file this under Software Extensions)

### S4. Unsigned tool from a "helpful" script
An attacker who **posts a setup script on a forum or in a fake README** can **run their own program on an engineer's laptop** because **any program can run; there is no allowlisting.**
- Asset: laptops; source code; CI/CD secrets
- ATT&CK: T1204.002 User Execution: Malicious File; T1059.004 Command and Scripting Interpreter: Unix Shell

### S5. Unpatched laptop exploited
An attacker who **knows a published vulnerability in an old OS or browser version** can **take over laptops that haven't updated** because **updates aren't enforced and nobody checks who's behind.**
- Asset: laptops
- ATT&CK: T1203 Exploitation for Client Execution

### S6. Laptop imaged at a border
An official or attacker who **has physical access to a laptop at a border or in a hotel room** can **copy its contents and its saved sessions** because **travelers take their everyday laptop, with full access, abroad.**
- Asset: laptops; session tokens; documents
- ATT&CK: no direct technique (physical access); recorded as a physical threat

### S7. Leaver's access still works
A **former employee, or anyone who obtains their credentials,** can **keep signing in for days after they leave** because **offboarding is manual and sometimes takes up to a week.**
- Asset: employee accounts; all data they could reach
- ATT&CK: T1078 Valid Accounts

### S8. Over-privileged AI agent
An attacker who **finds an agent's API key in a config file or code** can **use its broad, long-lived access to read data across systems** because **agents have no owner, no inventory and no scope review.**
- Asset: AI agent credentials; data the agent reaches
- ATT&CK: T1552.001 Unsecured Credentials: Credentials In Files

### S9. "Temporary" admin never removed
An attacker who **compromises any account that was once given admin rights "temporarily"** can **change settings or grant themselves more access** because **admin rights are never reviewed or automatically removed.**
- Asset: admin rights; control systems
- ATT&CK: T1078 Valid Accounts; T1098 Account Manipulation

### S10. Device management console abused
An attacker who **phishes an IT admin and takes over their session** can **push malware to every laptop at once through Fleet** because **the console is reachable from any device with a valid login.**
- Asset: device management console (crown jewel)
- ATT&CK: T1072 Software Deployment Tools

### S11. Prompt injection into an internal agent
An attacker who **plants hidden instructions in a document or ticket** can **make an internal AI agent leak data or take actions** because **agents read untrusted content and act with their full credentials.**
- Asset: AI agents; data they reach
- ATLAS: AML.T0051 LLM Prompt Injection

### S12. Chat bot quietly collecting messages
An attacker who **gets an employee to install a "productivity" chat bot or webhook** can **read channel messages, including shared secrets,** because **anyone can add bots and integrations, and nobody reviews them.**
- Asset: chat history
- ATT&CK: T1213 Data from Information Repositories

### S13. Poisoned open-source package
An attacker who **publishes a malicious package with a name similar to a popular one** can **run code on engineers' laptops and in CI pipelines when it's installed** because **any program can run on laptops, and nothing checks what engineers install.**
- Asset: laptops; source code; CI/CD secrets
- ATT&CK: T1195.001 Supply Chain Compromise: Compromise Software Dependencies and Development Tools

---

## 3. Scoring and ranking

To be completed in Project 0, Step 4.
