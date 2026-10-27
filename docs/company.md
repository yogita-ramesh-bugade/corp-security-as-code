# Lumen AI: Company Profile

> Fictional company for a security engineering lab. Any resemblance to a real organization is coincidental. All data in this project is synthetic.

## Overview

Lumen AI builds AI assistants for businesses. It has 2,000 employees and grows about 50% a year, which means roughly 80 new hires every month. Most people work hybrid; about 40% are fully remote. Offices are in New York and London, with sales staff traveling internationally every month.

## People and teams

| Team | Headcount | What they do | Main devices |
| --- | --- | --- | --- |
| Engineering | 700 | Build the product and infrastructure | macOS, some Linux |
| Research | 300 | Train and evaluate AI models | macOS, Linux |
| Sales and Marketing | 400 | Sell to customers, travel often | macOS, some Windows |
| Customer Support | 250 | Answer customer tickets | Chromebooks, macOS |
| Finance, HR and Legal | 150 | Run the business | Windows, macOS |
| Operations | 150 | Facilities, recruiting, procurement | macOS, Windows |
| IT and Security | 50 | Run devices, identity and security | macOS |

People movement each month: about 80 joiners, 30 people changing teams (movers), and 15 leavers.

## Devices

| Platform | Count | Share | Notes |
| --- | --- | --- | --- |
| macOS laptops | 1,400 | 70% | Default for most employees |
| Windows laptops | 400 | 20% | Finance, some sales and operations |
| Linux workstations | 100 | 5% | Engineers and researchers who request them |
| Chromebooks | 100 | 5% | Customer support |
| Company iPhones | 150 | n/a | Executives and on-call engineers |
| Personal phones (BYOD) | ~1,200 | n/a | Used for chat and email |

## Identity and access

- **Single sign-on (SSO):** Keycloak. Every employee logs in once to reach most apps.
- **Multi-factor authentication (MFA):** required for everyone, using an authenticator app.
- **Groups:** access is mostly given through Keycloak groups, such as `engineering` or `finance`.
- **Admins:** about 60 people hold admin rights in at least one system.

## Core systems

| System | What it's for | Who uses it | Data sensitivity |
| --- | --- | --- | --- |
| Keycloak SSO | Logs everyone in to everything | Everyone | Critical |
| Chat platform (Mattermost) | Daily communication, bots, integrations | Everyone | High |
| Email and documents suite | Email, calendars, shared files | Everyone | High |
| Code hosting | Source code and CI/CD pipelines | Engineering, Research | Critical |
| Production cloud console | Runs the product and customer data | ~120 engineers | Critical |
| HR system | Employee records, source of truth for who works here | HR, managers | High |
| Device management (Fleet) | Manages laptops and phones | IT and Security | Critical |
| Internal wiki | Documentation and how-tos | Everyone | Medium |

## Internal apps and AI agents

Employees have built 40+ internal apps, many generated with AI coding tools. About 25 AI agents run on behalf of employees: summarizing chats, triaging tickets, drafting code and querying internal data. Each agent holds OAuth tokens or API keys to one or more core systems. There is no central list of these apps and agents, and many have no clear owner.

## Third-party connections

Employees can approve outside apps that connect to email, documents and chat through OAuth. Around 300 such apps are connected today. Browser extensions are unrestricted.

## Current security state (the starting point)

- Laptops are enrolled in device management, but settings are applied inconsistently and changed by hand.
- Disk encryption is on for most Macs; Windows and Linux coverage is unknown.
- Any program can run on any laptop; there is no allowlisting.
- Apps can be reached from any device, including personal computers, as long as the person logs in.
- New-hire access is set up by IT tickets and takes 2–3 days. Removing leavers' access is manual and sometimes takes up to a week.
- Exceptions to security rules are granted over chat and never expire.
- Nobody reviews OAuth apps, chat bots or browser extensions.
- Logs from Keycloak and the chat platform go to a SIEM (Elastic), but few detections exist.
- Backups of production data are managed by the same admin accounts that run production, and nothing stops an admin from deleting them.

## Security team

The corporate security team has 5 engineers. They can't review everything by hand, so they rely on automation, clear policy, and good relationships with IT and engineering.
