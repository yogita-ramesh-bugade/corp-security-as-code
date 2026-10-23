# Lumen AI Threat Model

Based on the company described in [company.md](company.md).

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

## What the "who can reach it" column tells us

1. **Personal computers can hold work session tokens**, so stealing a cookie from an unmanaged computer bypasses passwords and MFA.
2. **About 300 outside vendors can read email and documents.** Nobody chose them centrally, and nobody reviews them.
3. **AI agents hold real credentials, but many have no owner**, and anyone who can send them text may be able to steer them.
4. **Laptops travel everywhere** and run any program, so one bad download can reach everything the employee can.
5. **Control systems are reachable from ordinary admin laptops**, so an admin's laptop is as valuable as the console itself.
6. **Admin rights and access pile up**, because nothing removes them automatically.
