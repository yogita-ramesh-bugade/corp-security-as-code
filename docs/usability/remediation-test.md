# Usability test: the remediation page (Project 2, Step 2.5)

**Question:** Can someone with no security background fix a blocked laptop using only the page?
**Metric:** time-to-remediate, from the first "Access blocked" to the app opening. The gate measures it
automatically (`docker compose exec gate python app.py stats`); a stopwatch is the backup.

## Setup (before the tester arrives)

1. Mac VM, assigned to ivan. Make the firewall fail:
   - System Settings > General > Device Management: remove the Lumen firewall profile (it locks the firewall on).
   - System Settings > Network > Firewall: switch it **off**.
   - Fleet: open fleet-macos-lab > **Refetch**; wait until `app.py inspect` shows `"firewall_on": "fail"`.
   - Skip the 72-hour grace for the test: `docker compose exec gate python app.py backdate ZR2JVG236J firewall_on 100`
2. Chrome on the Mac VM: signed in as ivan, on the blocked admin page. Close every other window.
3. Have a stopwatch ready. Don't help, point or hint. If they ask, say: "Do what you'd do if I weren't here."

## Script (read this to the tester)

> "You're a new employee. You tried to open the Admin Console and got this page. Please get into the
> Admin Console. Think out loud as you go: say what you're looking for and what's confusing.
> There are no wrong answers; I'm testing the page, not you."

Start the stopwatch when they start reading.

## Record

| | Tester 1 |
| --- | --- |
| Background (job, no names) | |
| Time to remediate (stopwatch) | |
| Time to remediate (`app.py stats`) | |
| Asked for help? When? | |
| Where they hesitated or misread (quote them) | |
| Clicked "Request an exception" instead of fixing? | |
| Rating 1-5: "How easy was that?" | |
| One thing they'd change | |

## After the test

1. Fix every confusing word in `access-gate/gate/checks.yaml` (wording lives there, not in code), rebuild the gate,
   and note each change below.
2. Put the firewall profile back (double-click `fleet/profiles/macos/lumen-firewall.mobileconfig`, then install it
   in System Settings > General > Device Management) and confirm the gate allows ivan again.
3. Report the median time-to-remediate in the RFC.

## Changes made after testing

| What confused them | What I changed |
| --- | --- |
| | |
