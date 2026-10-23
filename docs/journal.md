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
