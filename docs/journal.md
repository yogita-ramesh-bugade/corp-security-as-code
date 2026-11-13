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

## 2026-10-30 — Project 1A, Step 1.3: Windows VM

- **Did:** Built a Windows 11 Pro ARM64 VM in UTM with TPM 2.0, renamed it fleet-windows-lab, cloned a clean copy (windows-clean), built an arm64 fleetd MSI with scripts enabled, and installed it.
- **Did:** Built a Windows 11 Pro ARM64 VM in UTM with TPM 2.0, renamed it fleet-windows-lab, cloned a clean copy (windows-clean), and installed the fleetd MSI downloaded from Fleet's Add hosts screen (Workstation).
- **Broke (1):** Unsure whether to pick Workstation or Server in Fleet's Add hosts screen.
- **Fixed (1):** Workstation is for Windows 10/11 laptops and desktops; Server is only for Windows Server. A company laptop is a workstation.
- **Broke (2):** The Windows agent never enrolled (2026-11-02). Resolve-DnsName returned 100.113.48.55, my Mac's private Tailscale address, and Test-NetConnection to port 443 failed.
- **Cause (2):** The VM uses my Mac for DNS, and my Mac's Tailscale DNS answered with the private tailnet address, which the VM can't reach.
- **Fix attempted (2):** Turned off Tailscale DNS on the Mac (`tailscale set --accept-dns=false`) and flushed the DNS cache.
- **Broke (3):** My Mac's browser now shows ERR_CONNECTION_CLOSED for the public address.
- **Status:** In progress. Testing from my phone on cellular to tell "Mac can't loop back to its own Funnel" apart from "Funnel HTTPS not working."
- **Learned:** Windows on Apple Silicon needs ARM64 images and agents (--arch=arm64). Pro edition is required for BitLocker and MDM. The MSI contains the enroll secret, so it stays out of Git. Resolve-DnsName and Test-NetConnection separate "can I find it?" from "can I reach it?".

---

## 2026-11-03 — Project 1A, Step 1.4: Fleet configuration in Git (GitOps)

- **Did:** Backed up Fleet's config outside the repo, exported current settings with `fleetctl generate-gitops`, replaced the enroll secret with a placeholder (`$FLEET_GLOBAL_ENROLL_SECRET`, real value in ~/fleet-server/gitops.env, outside the repo), copied the files into fleet/, added a .gitignore for secrets and installers, and applied with `fleetctl gitops`.
- **Broke (1):** Dry run failed: environment variable FLEET_GLOBAL_ENROLL_SECRET not set.
- **Fixed (1):** Ran `source ~/fleet-server/gitops.env` in the same Terminal window. Each new window needs it.
- **Broke (2):** "fleet/default.yml: no such file or directory."
- **Fixed (2):** I was in ~/fleet-server instead of the repo; ran `cd ~/corp-security-as-code`.
- **Broke (3):** `git add .gitignore` failed: the file had never been created.
- **Fixed (3):** Created .gitignore (env files, installers, keys, backups), then confirmed with `git status` and `git diff --cached` that only YAML, logos and the placeholder secret were committed.
- **Tested:** Renamed the org to "Lumen AI DRIFT TEST" in the UI, then applied GitOps. [The name reverted to "Lumen AI".]
- **Learned:** GitOps resets anything missing from the YAML to defaults, so export and review before applying. Fleet's dry run validates files but doesn't show a field-by-field diff; compare with `fleetctl get config` to see drift. Secrets never live in Git: they're injected from the environment. The folder name in the prompt tells me where I am.

---

## 2026-11-03 — Project 1A, Step 1.4: Fleet configuration in Git (GitOps)

- **Did:** Backed up Fleet's config outside the repo (`fleetctl get config --yaml`), exported the current settings with `fleetctl generate-gitops`, replaced the enroll secret with a placeholder (`$FLEET_GLOBAL_ENROLL_SECRET`, real value in ~/fleet-server/gitops.env, outside the repo), copied the files into fleet/, added a .gitignore for secrets, installers, keys and backups, and applied with `fleetctl gitops`.
- **Broke (1):** "environment variable FLEET_GLOBAL_ENROLL_SECRET not set."
- **Fixed (1):** Ran `source ~/fleet-server/gitops.env`. Each new Terminal window needs it.
- **Broke (2):** "fleet/default.yml: no such file or directory."
- **Fixed (2):** I was in ~/fleet-server instead of the repo; ran `cd ~/corp-security-as-code`.
- **Broke (3):** `git add .gitignore` failed because the file had never been created.
- **Fixed (3):** Created .gitignore, then confirmed with `git status` and `git diff --cached` that only YAML, logos and the placeholder secret were committed.
- **Tested:** Renamed the org to "Lumen AI DRIFT TEST" in the UI, then applied GitOps. [The name reverted to "Lumen AI".]
- **Learned:** GitOps resets anything missing from the YAML to defaults, so export and review before applying. Fleet's dry run validates the files but doesn't show a field-by-field diff; `fleetctl get config` shows the live state. Secrets never live in Git; they're injected from the environment.

### Later GitOps lessons (2026-11-04)

- **Broke:** Installers built before GitOps applied the secret from gitops.env stopped enrolling ("enroll request: unauthenticated, or invalid token").
- **Learned:** Changing the enroll secret through GitOps rotates it: old installers stop working, enrolled devices keep working. Always build installers with `--enroll-secret="$FLEET_GLOBAL_ENROLL_SECRET"`.
- **Broke:** `git checkout fleet/default.yml` restored the last *committed* version and silently dropped uncommitted profile changes. I caught it by reading the file and the dry run before applying.
- **Learned:** Commit every working change immediately, and always read a dry run before applying.
- **Did:** Added scripts/gitops.sh, which loads the secret and runs `fleetctl gitops`, so I don't hit "variable not set" in new Terminal windows.
- **Did:** Updated deprecated keys: `controls.macos_settings.custom_settings` became `controls.apple_settings.configuration_profiles`. Tools change faster than guides, so read warnings.

---

## 2026-11-04 — Project 1A, Step 1.5: macOS baseline

- **Did:** Created firewall (with stealth mode), screen lock, and Gatekeeper (no override) profiles, plus a DDM passcode declaration, in fleet/profiles/macos/, and referenced them in default.yml under `controls.apple_settings.configuration_profiles` (renamed from the deprecated `macos_settings.custom_settings`).
- **Broke (1):** Profiles showed no status in Controls > OS settings (0 hosts).
- **Investigation:** Fleet's live MDM log showed SCEP (200), certificate association, Authenticate and SetBootstrapToken, but never TokenUpdate, reproduced on two VMs. `fleetctl get host` showed `connected_to_fleet: false`. The Mac's mdmclient log showed "asked for publicToken, got (null)" and "connectionStatusChange from apsd: NO". Ruled out network/tunnel (curl /mdm/apple/mdm: 400; Apple push reachable), the APNs certificate (valid to Oct 2027) and the profile files.
- **Root cause:** The macOS VM never obtains an APNs push token, so MDM enrollment can't complete and Fleet can't deliver profiles. A VM limitation, not a Fleet or configuration issue.
- **Fixed:** Installed the three profiles manually in the VM and added four Fleet policies using osquery's `managed_policies` table (firewall on, stealth mode, screen lock password, Gatekeeper). Result: 4/4 policies passing on fleet-macos-lab. The DDM passcode declaration can only be delivered by MDM, so it stays in Git for physical hardware.
- **Broke (2):** GitOps failed: "missing or invalid license."
- **Fixed (2):** `enable_disk_encryption` is Fleet Premium-only; commented it out with a note. FileVault decision: no FileVault profile without recovery-key escrow, because it risks unrecoverable devices.
- **Did:** Added Santa's system extension and Full Disk Access (PPPC) profiles from North Pole Security's official docs, with the network extension removed (verified with grep: 0 netd references; plutil OK). These payloads only take effect via MDM, so on the VM I'll approve Santa manually in Project 1B. [Six profiles now listed in Controls > OS settings.]
- **Learned:** Read an MDM enrollment step by step (SCEP → Authenticate → TokenUpdate) and use server and device logs as evidence. Some payloads (DDM, system extensions, PPPC) only work via MDM. Premium-only settings make GitOps reject the whole config. Verify config with grep and plutil instead of trusting a copy-paste.

---

## 2026-11-05 — Project 1A, Step 1.6: macOS patching with Nudge

- **Did:** Created a com.github.macadmins.Nudge profile (minimum macOS 27.3, deadline 2026-11-19) and added it to Git and GitOps. Installed Nudge Suite (app + LaunchAgent) on the Mac VM, downloaded the profile from GitHub and installed it manually (the VM can't receive MDM profiles).
- **Broke (1):** Nudge didn't appear when launched, and its `-debug` flag printed nothing in Terminal.
- **Fixed (1):** Nudge logs to the unified log, not the terminal. `log stream --predicate 'subsystem == "com.github.macadmins.Nudge"' --level debug` showed it had loaded my settings and was "Delaying initial run by: 421" seconds, a built-in random delay so a whole fleet isn't prompted at once. After the wait, the reminder appeared.
- **Result (before deadline):** Polite reminder: Required OS 27.3, Current 27.2, 14 days remaining, Defer available, Deferred count 0.
- **Broke (2):** `-simulate-date` failed ("Failed to parse -simulated-date, returning current date"), and `open` briefly failed with error -600 right after `killall Nudge`.
- **Fixed (2):** Tested escalation by changing the VM clock instead; waited a few seconds before relaunching.
- **Result (past deadline):** Aggressive mode: background blurred, -1 days remaining in red, Defer removed. Closed it with Force Quit, then restored automatic date and time.
- **Proof in Fleet:** Added two policies: Nudge installed, and Nudge deadline configured. [Both passing on fleet-macos-lab.]
- **Learned:** Good patching is clear deadlines plus escalating reminders, not surprise restarts. Read an app's unified log when it seems to do nothing. In production, the required version tracks Apple's latest security release, with the deadline days or weeks out depending on severity.
![Nudge reminder](images/nudge-reminder.png)
![Nudge past deadline](images/nudge-past-deadline.png)

---

## 2026-11-05 — Project 1A, Step 1.7: Windows baseline

- **Did:** Wrote three PowerShell scripts in windows/scripts/: firewall on for all profiles plus SMBv1 off; four Defender ASR rules in audit mode (LSASS credential theft, Office child processes, Office executable content, Office code injection, with GUIDs verified against Microsoft's ASR reference); and BitLocker with the TPM plus a recovery password. Tracked them in GitOps under controls.scripts, and ran them on fleet-windows-lab [with `fleetctl run-script` / from Fleet's Run script action].
- **BitLocker, broke (1):** Get-Tpm failed with 0x80284001: the VM had no virtual TPM.
- **Fixed (1):** Enabled TPM 2.0 in UTM's VM settings. tpm.msc then showed "The TPM is ready for use."
- **BitLocker, broke (2):** "Bootable media detected" (0x80310030).
- **Fixed (2):** Ejected the Windows installer and guest-tools ISOs in UTM.
- **BitLocker, broke (3):** Enable-BitLocker: "Value does not fall within the expected range," because the protectors already existed from earlier attempts.
- **Fixed (3):** `manage-bde -on C: -UsedSpaceOnly -SkipHardwareTest`. Result: Used Space Only Encrypted, 100%, Protection On, XTS-AES 128 (kept from an earlier attempt; switching to 256 would need decrypting and re-encrypting).
- **Caught:** Only a TPM protector remained, with no recovery path. Added a recovery password with `manage-bde -protectors -add C: -RecoveryPassword` and stored it in my password manager. Production: escrow recovery keys centrally.
- **ASR:** All four rule IDs present in Get-MpPreference [each with action=2 (audit)].
- **Firewall/SMB:** [All profiles Enabled: True; EnableSMB1Protocol: False].
- **Broke (4):** GitOps failed: "yaml: line 154: mapping values are not allowed in this context."
- **Fixed (4):** The policy name "Windows - BitLocker on for C:" ended with a colon, which YAML reads as a new key. Quoted the name.
- **Proof in Fleet:** Three Windows policies (BitLocker on, firewall on, SMBv1 disabled): [results on fleet-windows-lab].
- **Learned:** ASR rules start in audit mode to measure breakage before blocking. Encryption without a recovery path is a trap, so always verify the protectors. BitLocker needs a TPM and no bootable media. In YAML, quote any text containing a colon. Copy-paste commands to avoid typos like `Enable-BitLocket`.

---

## 2026-11-06 — Project 1A, Step 1.8: Linux baseline (Ansible)

- **Did:** Installed openssh-server on fleet-ubuntu-lab, created an SSH key on my Mac (~/.ssh/lumen_lab, never committed) and copied it to the VM. Wrote linux/inventory.ini and linux/baseline.yml: unattended security updates, ufw deny-incoming with OpenSSH allowed *before* enabling, auditd running at boot, SSH hardening (no root login, no passwords) with `validate: sshd -t` before saving, and a read-only LUKS report.
- **Broke (1):** "Permission denied (publickey,password)."
- **Fixed (1):** The key was installed but has a passphrase, which Ansible can't type. Loaded it into the SSH agent with `ssh-add --apple-use-keychain ~/.ssh/lumen_lab`.
- **Broke (2):** "Timeout (12s) waiting for privilege escalation prompt."
- **Fixed (2):** Ubuntu 26.04 uses sudo-rs (0.2.13), whose password prompt Ansible doesn't recognise. Classic sudo is installed as /usr/bin/sudo.ws, so I set `ansible_become_exe=/usr/bin/sudo.ws` in the inventory. (I first checked sudo on my Mac by mistake; checking over SSH from the Mac showed the real target.)
- **Broke (3):** The `--check --diff` preview failed: "Could not find the requested service auditd."
- **Fixed (3):** Check mode only simulates package installs, so the service didn't exist yet. Added `when: not ansible_check_mode` to the service task, and ran the playbook for real.
- **Tidied:** Set `ansible_python_interpreter=/usr/bin/python3` to silence the interpreter-discovery warning.
- **Idempotence:** First real run changed=[N]; second run changed=[0].
- **Verified on the VM:** ufw [active, deny incoming, OpenSSH allowed]; auditd [active]; sshd -T shows permitrootlogin [no] and passwordauthentication [no]; auto-updates [on]; LUKS: [YES]. Password SSH from my Mac [refused: "Permission denied (publickey)"].
- **Fleet policies:** auditd running, unattended-upgrades installed, root disk encrypted: [results].
- **Learned:** Set up key auth before disabling passwords, and allow SSH before enabling the firewall, or you lock yourself out. Validate config before restarting a service. Dry runs have limits when later tasks depend on earlier changes. Check facts on the actual target, not the control machine. Idempotence (changed=0 on re-run) is what makes config-as-code safe to repeat.

---

## 2026-11-06 — Project 1A, Step 1.9: Compliance checks as osquery policies

- **Did:** Reviewed the 12 existing policies from Steps 1.5–1.8, then added six more through GitOps: macOS FileVault on, macOS OS at or above 27.3, Windows OS build at or above 26100, Windows firewall on for public and domain profiles, Windows ASR LSASS rule in audit or block, and Linux OS release 26 or later. Total: [18] policies.
- **Deferred:** Santa running, to Project 1B (Santa isn't installed yet, so the check would fail forever).
- **Verified first:** Confirmed the ASR registry path with `reg query "HKLM\SOFTWARE\Microsoft\Windows Defender\Windows Defender Exploit Guard\ASR\Rules"` before writing the check: [four rule IDs, value 0x2].
- **Break/fix test (Linux):** `sudo systemctl stop auditd` → "Linux - auditd running" turned No after a refetch → `sudo systemctl start auditd` → back to Yes.
- **Break/fix test (Windows):** `Set-NetFirewallProfile -Profile Private -Enabled False` → "Windows - Firewall on (private profile)" turned No → re-enabled → back to Yes.
- **Honest failures:** macOS FileVault [No; enforced FileVault is Premium-only / Yes after turning it on manually, recovery key in my password manager]. macOS OS at or above 27.3: No, because the VM runs 27.2, which matches Nudge's reminder.
- **Did:** Documented how each policy maps to a posture signal (disk_encrypted, os_current, firewall_on, endpoint_protection) in docs/posture-signals.md, as input for Project 2's access gate.
- **Broke:** [describe anything, or "Nothing"]
- **Learned:** Policies prove settings are in effect, not just sent; break/fix testing proves the checks actually detect change. A failing check that matches reality is the system working. Verify where a setting is stored before writing a check for it.

---

## 2026-11-11 — Project 1A, Step 1.10: Browser policy from one source

- **Did:** Wrote browser/policy.yaml as the single source of truth (block all extensions except an allowlist, enhanced Safe Browsing, built-in password manager off) and browser/render.py, which renders it to a Linux JSON file, a macOS com.google.Chrome profile and a Windows PowerShell registry script. Stable UUIDs keep the output identical between runs, and `render.py --check` fails if outputs are stale (for CI in Step 1.11).
- **Tracked in GitOps:** macOS profile under controls.apple_settings.configuration_profiles; Windows script under controls.scripts.
- **Applied:** macOS: profile installed manually from GitHub (the VM can't receive MDM profiles). Windows: `fleetctl run-script`. Linux: two new Ansible tasks create the Chrome and Chromium policy folders and copy the generated JSON into both.
- **Broke (1):** On macOS, the downloaded Chrome profile didn't appear under Device Management.
- **Fixed (1):** [The file hadn't been pushed to GitHub yet, so curl got a 404 / Ran `open lumen-chrome.mobileconfig` and found it under "Profile Downloaded"], then installed it.
- **Broke (2):** On Ubuntu, chrome://policy showed "No policies set."
- **Fixed (2):** The policy file wasn't in /etc/opt/chrome/policies/managed/ yet. Added the Chrome tasks to linux/baseline.yml, validated with `ansible-playbook --syntax-check`, ran the playbook, then fully restarted Chrome and reloaded policies.
- **Verified:** chrome://policy shows the same four policies (Source: Platform, Status: OK) on [macOS, Windows, Ubuntu]. Installing a non-allowlisted extension is blocked by the administrator [yes].
- **Learned:** One source of truth plus a generator means the three platforms can't drift apart. Each OS stores browser policy differently (JSON file, configuration profile, registry). Use `--syntax-check` to catch YAML indentation mistakes before running, and restart the browser to pick up new policy files.

---

## 2026-11-12 — Project 1A complete: Fleet baseline as code

### What I built
- **Fleet server** (Docker Compose: Fleet, MySQL, Redis) on my Mac, published over HTTPS with Tailscale Funnel at a stable *.ts.net address. Secrets kept outside the repo.
- **Three managed VMs** in UTM: fleet-macos-lab (macOS 27.2), fleet-windows-lab (Windows 11 Pro ARM64), fleet-ubuntu-lab (Ubuntu 26.04 LTS), all running the Fleet agent and online.
- **GitOps:** all Fleet configuration in fleet/default.yml, applied with `fleetctl gitops`; the enroll secret injected from an environment variable; scripts/gitops.sh helper; drift test reverted a UI change.
- **macOS baseline:** firewall + stealth mode, screen lock, Gatekeeper (no override), DDM passcode, Santa system extension + PPPC profiles, Nudge (minimum 27.3, deadline, escalation tested).
- **Windows baseline:** BitLocker (TPM + recovery password), four Defender ASR rules in audit mode, firewall on, SMBv1 off, delivered as Fleet scripts.
- **Linux baseline:** Ansible playbook: unattended security updates, ufw, auditd, SSH hardening, LUKS report. Idempotent (changed=0 on re-run).
- **Compliance policies:** about 19 osquery policies across all three platforms, break/fix tested, mapped to device posture signals for Project 2 (docs/posture-signals.md).
- **Browser policy from one source:** browser/policy.yaml rendered by browser/render.py to Linux JSON, a macOS profile and a Windows registry script.
- **CI pipeline:** GitHub Actions with offline validation (yamllint, profile validator, render --check, plain-English PR summary), then a Fleet dry run on PRs and apply on main, using an API-only robot account. main is protected (PR + passing checks).
- **Rollout rings:** ring-canary (Ubuntu), ring-pilot (macOS, Windows), ring-all labels; changes promoted by reviewed PRs.

### Biggest problems and how I solved them
- **macOS VM never received MDM profiles.** Traced the enrollment step by step: SCEP, Authenticate and SetBootstrapToken succeeded, but TokenUpdate never arrived (`connected_to_fleet: false`). The device log showed "asked for publicToken, got (null)": the VM can't obtain an APNs push token. Decision: install profiles manually and verify them with policies; MDM delivery needs physical hardware.
- **Agents not enrolling:** a VM resolving my Mac's private Tailscale IP (fixed with `tailscale set --accept-dns=false`); amd64 vs arm64 installers; old installers rejected after GitOps rotated the enroll secret ("invalid token").
- **Free vs Premium:** `enable_disk_encryption` and `labels_include_any` are Premium-only. CI caught the second before deployment; I moved ring scoping into the policy query.
- **BitLocker:** no virtual TPM, then installer ISO still attached, then only a TPM protector (no recovery path). Added a recovery password.
- **Ansible:** passphrase key (ssh-agent), Ubuntu's sudo-rs prompt (`ansible_become_exe=/usr/bin/sudo.ws`), check-mode limits.
- **A policy stuck at "---":** the device's orbit log showed "near ")": syntax error". My first fix left unbalanced brackets; replaced it with a bracket-free UNION query. Also found the 5-minute policy interval in .env never reached the container. [Policy now passing on fleet-ubuntu-lab.]

### What I learned
- Configuration as code only works if secrets stay out of Git and every change is reviewed and dry-run.
- "Sent" isn't "in effect": verify with policies, and test that checks detect breakage.
- Debug layer by layer (network, server, device) and trust logs over assumptions: server logs, device logs, and the exact committed text (`sed -n`, `cat -v`).
- Know the platform limits (VMs, licence tiers) and document the production design honestly.
- Rings and CI limit the blast radius: one device first, every change reviewed.

