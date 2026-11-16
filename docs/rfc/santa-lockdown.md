# RFC: Moving Santa from Monitor to Lockdown on Lumen Macs

| | |
| --- | --- |
| **Status** | Draft, open for comments |
| **Author** | Corporate Security |
| **Reviewers** | IT, Engineering Productivity, one representative per department |
| **Related** | [Rollout readiness analysis](../../analysis/rollout_readiness.ipynb), [threat model](../threat-model.md) (S4, S13), [Project 1B charter](../charters/project-1b-allowlisting.md) |

> All numbers in this RFC come from the **simulated** 3,000-device fleet in `analysis/`. Before a real rollout, re-run the same notebook on each ring's own Monitor-mode data.

## 1. Summary

Santa runs on every Mac in **Monitor** mode today: it records programs that aren't on the approved list but blocks nothing. This RFC proposes switching to **Lockdown**, where only approved programs run, in three rings over about seven weeks, with a measurable gate before each step and a one-PR rollback.

**Why:** our top-ranked endpoint threats are an engineer running a malicious "setup" tool (S4, score 16) and a poisoned open-source package (S13, score 15). In Lockdown, unknown code simply doesn't run.

**Why carefully:** if we enforced today with only the standard-build rules, the analysis predicts **2,260 blocked programs per 100 Macs per week**. Engineers and researchers would be unable to work, and the control would be switched off within a day. This plan exists to prevent that.

## 2. What the analysis says

| After | Blocks per 100 Macs per week |
| --- | --- |
| Standard build rules only (today) | 2,260 |
| + 655 vendor rules (99% of signed use) | 812 |
| + transitive rules for compilers (developer builds) | 733 |
| + approved Homebrew catalog | 225 |
| + signed internal tools | 24 |
| + team-scoped rules for the long tail | 21 |
| + per-Mac pre-approval of signed apps seen in Monitor mode | **6** |

What's left is mostly rarely used signed apps that a person installs after enforcement starts: about **4.6 exception requests per 100 Macs per week**, plus a handful of intended blocks of programs running from Downloads, `/tmp` or hidden folders.

Key findings that shape this plan:

- **Homebrew tools are 62% of the breakage**, not self-compiled code (10%). The Homebrew catalog is the most important prerequisite.
- **One week of lag in the Homebrew catalog** after a version bump would cause 508 blocks per 100 Macs that week. Rules must be published before engineers can upgrade.
- **Hash rules don't last:** rules taken from week-1 file hashes matched only 42% of the same vendors' use four weeks later. We use Team ID and Signing ID rules, never hash rules, for signed software.
- **Engineering and Research feel ~85% of the breakage**, so the pilot must include them.
- **The long tail becomes exception load.** At 4.6 requests per 100 Macs per week, the gate in section 4 can't be met by human review alone; self-service approval for signed apps is a prerequisite.

## 3. Prerequisites (before any Mac enters Lockdown)

| # | Prerequisite | Owner | Done when |
| --- | --- | --- | --- |
| P1 | Vendor rules (`TEAMID`, or `SIGNINGID` for single-app vendors) from Monitor data, merged by PR into `santa/rules/` | Security | Rules cover ≥99% of signed executions in the ring |
| P2 | Transitive rules: `EnableTransitiveRules` on, compilers (`go`, `rustc`, `clang`) as `ALLOWLIST_COMPILER` | Security + Eng Productivity | A test binary built with each compiler runs in Lockdown |
| P3 | Approved Homebrew catalog: a sync job publishes `BINARY` rules for each approved tool's new bottle **before** it's released internally | Eng Productivity | Catalog lag on the last version bump = 0 days |
| P4 | Lumen's 6 internal tools signed with the company Developer ID (one `TEAMID` rule); temporary expiring exceptions until then | Tool owners | All 6 signed, or exceptions with expiry in place |
| P5 | Per-Mac pre-approval: signed apps each Mac already ran during ≥4 weeks of Monitor mode, excluding Downloads, `/tmp` and hidden folders | Security | Machine-specific rule files generated for every Mac in the ring |
| P6 | Exception bot (Project 3) live, with **self-service approval for signed, non-blocklisted apps** (unblocked in minutes, logged, reviewed weekly) and security review for unsigned ones | Security | Median time to unblock a signed app < 15 minutes in canary |
| P7 | Block message links to the request page (`EventDetailURL`), in plain language | Security | Message tested on a canary Mac |
| P8 | Rollback rehearsed (section 7) on a canary Mac | Security | Mac back in Monitor within 10 minutes of the revert merging |

## 4. Rings and gates

| Ring | Who | Size (approx.) | Duration |
| --- | --- | --- | --- |
| **Canary** | IT and Security | 50 Macs | 2 weeks |
| **Pilot** | One volunteer team per department: an Engineering squad, a Research group, and a Sales, Finance and Support team | 300 Macs (10%), at least 100 from Engineering + Research | 2 weeks |
| **Everyone** | All remaining Macs, in two waves: Sales, Finance and Support first, then Engineering and Research one week later | 2,650 Macs | 2 weeks, then steady state |

Each ring stays in Monitor mode for **at least 4 weeks** before it's enforced, so P5 has enough history.

**Gate to move to the next ring.** All of the following, for **two consecutive weeks**:

| Metric | Definition | Threshold |
| --- | --- | --- |
| Appealed blocks needing review | Blocks that turn into an exception request a security engineer must review (unsigned code, or signed apps that fail self-service) | **< 1 per 100 Macs per week** |
| Time to unblock | From request to approved, for self-service signed apps | Median < 15 minutes |
| Business-critical blocks | Blocks of a tool someone needs to do their job, not resolved within 4 business hours | **0** |
| Homebrew catalog lag | Days between an approved tool's release and its rules being published | **0** |
| Rollbacks | Macs reverted to Monitor | 0, or the cause is fixed and re-tested |
| Intended blocks | Programs blocked from Downloads, `/tmp` or hidden folders | Reviewed by Security; each one is an investigation, not a failure |

**If a gate fails:** the ring stays where it is (it does **not** roll back unless people are blocked from working), the cause is fixed, and the two-week clock restarts.

## 5. Communications

Messages go out from **Lumen AI Security** in Slack (#announcements and each team's channel) and by email. Dates below are for the Everyone ring; Canary and Pilot get the same messages a week earlier, with "you're in an early group" added.

| When | Message | Audience |
| --- | --- | --- |
| T−14 days | Announcement | Everyone in the ring |
| T−14 days | Engineering and Research details | Engineering, Research |
| T−7 days | Reminder | Everyone in the ring |
| T (enforcement day) | It's live | Everyone in the ring |
| T+7 days | Follow-up | Everyone in the ring |

### T−14: Announcement

> **Subject: In two weeks, only approved apps will run on Lumen Macs**
>
> Hi everyone,
>
> On **[date]**, we're turning on a protection on Lumen Macs called **app allowlisting**: only approved apps and tools will be able to run. It stops malware and fake installers before they can do anything, which is one of the most common ways companies get breached.
>
> **For most of you, nothing will change.** For the last few weeks, Santa (already on your Mac) has been quietly recording which apps you use, and we've approved them. Your everyday apps, like Chrome, Slack, Zoom, Office and your team's tools, will keep working.
>
> **If something you need is blocked,** you'll see a message with a **"Request access"** button. Most signed apps are approved automatically within minutes. Anything else goes to the Security team, who respond within 4 business hours.
>
> Questions? See the FAQ at **go/santa**, or ask in **#ask-security**.
>
> Thanks for helping keep Lumen safe,
> Lumen AI Security

### T−14: Engineering and Research details

> **Subject: Allowlisting and your developer tools: what you need to know**
>
> Hi Engineering and Research,
>
> Allowlisting reaches your Macs on **[date]**. We've worked with Engineering Productivity so your workflow keeps working:
>
> - **Homebrew:** the [N] approved tools in **go/brew-catalog** keep working, including after upgrades. Need a tool that isn't listed? Request it there; most are added the same day.
> - **Code you build yourself** with `go`, `cargo`/`rustc` or `clang` runs automatically, because programs those compilers produce are trusted.
> - **Lumen's internal tools** (`lumen-cli`, `lumen-deploy` and the rest) are now signed and will keep working.
> - **Not covered:** binaries downloaded straight from the internet (release archives, `curl | sh` installers). Request them, or ask us to add them to the catalog.
>
> Please try your usual workflow before **[date − 3 days]** and tell us in **#ask-security** if anything looks off. We'd much rather fix it before enforcement than after.
>
> Lumen AI Security

### T−7: Reminder

> **Subject: One week until app allowlisting**
>
> A reminder that only approved apps will run on Lumen Macs from **[date]**.
>
> - Nothing to do if you only use your usual apps.
> - If you use an unusual tool, **open it once this week**, so Santa records it and we can approve it in advance.
> - If something is blocked after [date], click **"Request access"** in the message.
>
> FAQ: **go/santa**. Questions: **#ask-security**.

### T: It's live

> **Subject: App allowlisting is now on**
>
> App allowlisting is now active on your Mac. Your approved apps work as usual.
>
> **If something is blocked:** click **"Request access"** in the message. Signed apps are usually approved in minutes; everything else within 4 business hours. If a block stops you from doing your job, post in **#ask-security** and tag **@security-oncall**, and we'll help straight away.
>
> Thank you for your patience while we roll this out.

### T+7: Follow-up

> **Subject: App allowlisting: first week results**
>
> Thank you! In the first week:
>
> - **[N]** apps were requested, and **[N]%** were approved within 15 minutes.
> - **[N]** programs were blocked from running out of Downloads or temporary folders, the kind of thing allowlisting exists to stop.
>
> If anything is still bothering you, tell us in **#ask-security**. We read every message.

## 6. FAQ for employees

**What is changing?**
Your Mac will only run apps that Lumen has approved. Before, any program could run.

**Why?**
Many attacks start with someone running a program that looks harmless, like a fake installer or a "helpful" script. If it isn't approved, it can't run.

**Will my apps stop working?**
Almost certainly not. Santa has watched which apps you use for several weeks, and we've approved them in advance.

**What happens if something is blocked?**
You'll see a message naming the app, with a **"Request access"** button. Signed apps from known developers are usually approved automatically within minutes.

**How long does approval take?**
Signed apps: usually minutes. Anything else: within 4 business hours. If you're blocked from doing your job, post in #ask-security and tag @security-oncall.

**Can I install new apps?**
Yes. The first time you open a new app, request it if it's blocked. Apps from the App Store and well-known developers are approved quickly.

**I'm a developer. Will my builds and Homebrew tools work?**
Yes. Programs you compile with `go`, `cargo`/`rustc` or `clang` are trusted automatically, and approved Homebrew tools keep working after upgrades. See go/brew-catalog for the list.

**Can Security see what I do on my Mac?**
Santa records the name, location and signature of programs that run, so it can decide whether to allow them. It doesn't read your files, messages or browsing.

**What if I'm traveling or offline?**
Your Mac keeps its approved list offline. Requests need an internet connection.

**What if allowlisting breaks something important?**
We can switch your Mac back to Monitor mode within minutes while we fix it. Tell us in #ask-security.

## 7. Rollback

**Rolling back is one pull request:** revert the PR that set the ring to Lockdown, which sets `client_mode = "MONITOR"` for that ring in `santa/rules/` (or `ClientMode` back to `1` in the Santa profile). After the revert merges:

1. Moroz serves Monitor mode at the next sync. Santa syncs every 10 minutes, so all Macs in the ring are back in Monitor within **10 minutes**. Security can force it sooner with `santactl sync`.
2. Nothing is blocked; Santa keeps recording, so we keep the data to fix the cause.
3. Security posts in #ask-security that the ring is temporarily in Monitor mode, and why.

**Who can roll back:** any Security engineer, without waiting for approval, when people are blocked from working. The revert PR is reviewed afterwards.

**When to roll back:** a business-critical tool is blocked and can't be approved within 4 business hours, or blocks affect more than 5% of a ring at once.

## 8. Risks

| Risk | Mitigation |
| --- | --- |
| Self-service approval becomes a rubber stamp | Only for signed apps whose developer isn't on the blocklist; every approval logged and reviewed weekly; unsigned code always needs Security |
| Homebrew catalog lag after a version bump | Publish rules before internal release; alert when lag > 0; P3 is a gate metric |
| Users give up instead of requesting (hidden breakage) | Watch blocks with no request in the follow-up surveys; ask pilot teams directly |
| Malware placed where users can write, such as `/opt/homebrew` | No path-based allowlisting; Homebrew tools are approved by exact hash |
| Interpreted scripts (Python, shell) aren't covered | Santa evaluates the interpreter, not the script; covered by other controls (EDR, file-change monitoring) and noted as out of scope |
| Synthetic numbers differ from reality | Re-run the analysis on each ring's real Monitor data before enforcing it |

## 9. Open questions

- Which tools count as business-critical for the 4-hour rule? Each department nominates up to 10.
- Who owns the Homebrew catalog after launch: Security or Engineering Productivity?
- Should self-service approvals expire after 90 days if unused, to keep the rule set small?
