# Lab Journal

Each entry: what I did, what broke, how I fixed it. Newest at the bottom.

---

## 2026-10-23 — Project plan and build guide

- **Did:** Turned a corporate security engineer job description into a portfolio plan, "Corp Security as Code": a threat model plus four connected projects covering endpoint hardening, device-trust access, joiner/mover/leaver automation, and SaaS and AI-agent governance. Wrote a step-by-step build guide using free and open-source tools.
- **Broke:** Nothing.
- **Learned:** Endpoint engineering (MDM, allowlisting) is the core of these roles, so Project 1 gets the most time.

---

## 2026-10-23 — Step 0.1: Repository

- **Did:** Created the public corp-security-as-code repo on GitHub, cloned it to my Mac, created the project folders, and wrote a two-sentence README.
- **Broke:** [Nothing / describe any problem, e.g. a sign-in prompt during git push]
- **Learned:** Git doesn't track empty folders, so each folder needs a placeholder .gitkeep file to show up on GitHub.

---

## 2026-10-23 — Step 0.2: Toolchain

- **Did:** Installed Homebrew, then Git, Python 3.12, pipx, Node.js, OPA and step with one brew command. Installed sigma-cli and ansible-core with pipx, fleetctl with npm, and Docker Desktop.
- **Broke:** When I copied the brew install command from the guide, only stray text ("sl") came through instead of the command.
- **Fixed:** Typed the full command manually: brew install git python@3.12 pipx node opa step.
- **Learned:** Always read a command before pressing Enter, and reopen Terminal after installs so it finds new programs.

---

## 2026-10-23 — Step 0.3: Stable HTTPS hostname

- **Did:** Compared Tailscale Funnel (free) with a Cloudflare domain and Tunnel (about $10/year) and chose Cloudflare. [Bought domain ____, created tunnel corp-lab routed to lab.____, tested from my phone on cellular: padlock OK / not finished yet]
- **Broke:** [Nothing / describe]
- **Learned:** Apple devices only talk to an MDM server over trusted HTTPS, so the server needs a permanent, trusted address. Tunnel credentials in ~/.cloudflared are secrets and never go in the repo.

---

## 2026-10-23 — Step 0.4: Lab journal

- **Did:** Started this journal.
- **Broke:** Nothing.
- **Learned:** Write down exact error messages; they become real interview stories.

---

## 2026-10-23 — Project 0, Step 1: Company profile

- **Did:** Wrote docs/company.md describing Lumen AI: 2,000 employees, 70% macOS fleet, Keycloak SSO, core systems, ~25 internal AI agents and ~300 connected OAuth apps. Chose its product (back-office AI agents) after comparing six real problem areas. [Personalized: changed ___ ] [Drew the environment sketch and saved it to docs/img/]
- **Broke:** Nothing.
- **Decided:** Kept Lumen's customer-facing product out of scope. A customer token vault would have created a top threat that none of my corporate security projects fixes, so scoping it out keeps every threat mapped to a project.
- **Learned:** Each weakness in "Current security state" maps to one project. In the sketch, agents and OAuth apps reach core systems directly, bypassing the SSO gate, which is the reason for Project 4.

---

## 2026-10-23 — Project 0, Step 2: Asset inventory

- **Did:** Listed Lumen AI's assets in four groups (identities, devices, data, control systems), with where each lives and who or what can reach it.
- **Broke:** Nothing.
- **Learned:** Listed Lumen's assets; biggest surprise was that about 300 outside apps can read company email, and nobody picked or reviews them and a stolen session cookie skips both the password and MFA, so a personal laptop can be a way in..

---

## 2026-10-28 — Project 0, Step 3: Attacker stories

- **Did:** Wrote 13 attacker stories in the form "an attacker who has X can do Y because Z," mapped to MITRE ATT&CK and ATLAS (AML.T0051 for prompt injection). Learned to navigate ATT&CK technique pages: description, procedure examples, mitigations, detection.
- **Broke:** My README was saved as README.txt, so GitHub showed it as raw text with the # symbols visible.
- **Fixed:** Renamed it with `git mv README.txt README.md`, because GitHub only formats Markdown files.
- **Learned:** The "because" part of each story is the weakness a control must remove. ATT&CK IDs can be renamed between versions, so I record the version I used.

---

## 2026-10-28 — Project 0, Step 3 (continued): S14, my own story

- **Did:** Researched and found T1490 Inhibit System Recovery on my own, and used it to write S14: backups deleted before ransomware, also tagged T1486 Data Encrypted for Impact. Added backups to the asset list.
- **Broke:** S14's "because" didn't match anything in company.md, since the company file never mentioned backups.
- **Fixed:** Added a backups weakness to company.md, so every story traces back to a stated weakness.
- **Learned:** Ransomware is a chain (delete backups, then encrypt), so tagging both techniques shows the whole attack. Defense: immutable backups, and backup admin rights separate from production admin rights.

---

## 2026-10-28 — Project 0, Step 4: Scoring and ranking

- **Did:** Scored 14 stories by likelihood × impact (1–5 each) using written definitions, ranked them, and checked that every project fixes at least one top-ranked threat (score 12 or more).
- **Revised:** Raised S7 leaver access (likelihood 3 → 4), S12 chat bots (impact 3 → 4) and S10 device management console (likelihood 2 → 3), each with a written reason.
- **Broke:** Nothing.
- **Learned:** Some threats aren't fully covered (S13, S11, S14). Writing down the gap and handing it to the right owner is better than claiming a project solves everything.

---

## 2026-10-28 — Project 0, Step 5: Charters (Project 0 complete)

- **Did:** Wrote one-page charters for Projects 1A, 1B, 2, 3 and 4 in docs/charters/, each linked to ranked threats, with yes/no "done" criteria, metrics, user impact and tooling trade-offs.
- **Broke:** Nothing.
- **Learned:** What's out of scope, and why, matters as much as what's in scope. "Done" has to be testable before the work starts.

---

## 2026-10-28 — Project 1A, Step 1.1: Fleet server (in progress)

- **Did:** Deployed Fleet with its official Docker Compose setup (Fleet, MySQL, Redis), free tier, in ~/fleet-server, outside the repo because .env holds secrets. Set FLEET_SERVER_TLS=false because Tailscale Funnel provides HTTPS. Saved the server private key in my password manager.
- **Broke (1):** `docker compose up` failed: port 6379 already in use.
- **Fixed (1):** `lsof -i :6379` showed a Homebrew Redis holding the port. Stopped it with `brew services stop redis`; all containers then started healthy.
- **Broke (2):** The public address shows DNS_PROBE_FINISHED_NXDOMAIN.
- **Status:** Still troubleshooting. Checking Tailscale connection, exact DNS name, and Funnel status.
- **Learned:** Fleet listens on port 1337, not 8080. Two programs can't use the same port. The .ts.net address only exists publicly while Tailscale is connected and Funnel is on.

---

## 2026-10-28 — Project 1A, Step 1.2: Apple MDM (APNs)

- **Did:** Downloaded a CSR from Fleet, created an APNs certificate at identity.apple.com, and uploaded it to Fleet. Apple MDM is on; certificate expires [date].
- **Broke:** [Nothing / describe]
- **Learned:** APNs only sends a "check in" ping; profiles travel directly between Fleet and the Mac. Renewal must use the same Apple ID, or every Mac must re-enroll.

