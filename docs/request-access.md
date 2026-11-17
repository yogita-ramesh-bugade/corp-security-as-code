# Request access to a blocked app

> **Placeholder.** This page stands in for the exception bot built in Project 3. In the lab, requests are handled by hand.

Santa blocked an app on your Mac because it isn't approved yet. That's expected for new or unusual apps, and it's quick to fix.

## What to do

1. **Copy the details from this page's address bar.** The link that brought you here includes:
   - `sha`: the app's fingerprint
   - `machine`: your Mac's ID
   - `user`: your username
2. **Post them in #ask-security**, with one sentence on what the app is and why you need it.
3. **Wait for approval.** Signed apps from known developers are usually approved within minutes; anything else within 4 business hours.

**Blocked from doing your job right now?** Say so in your message and tag @security-oncall, and we'll help straight away.

## What happens next

Security reviews the request, adds a rule through a reviewed pull request in `santa/rules/`, and your Mac picks it up at its next sync (within 10 minutes).

## Why apps get blocked

Only approved apps run on Lumen Macs. It stops malware and fake installers before they can do anything. See the [rollout plan](rfc/santa-lockdown.md) for the full background.
