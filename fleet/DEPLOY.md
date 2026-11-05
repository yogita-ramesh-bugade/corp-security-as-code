# Fleet server deployment (lab)

- Fleet's official Docker Compose deployment (Fleet + MySQL + Redis), free tier.
- Runs on a Mac with Docker Desktop. The Fleet image is amd64-only, so it runs under emulation on Apple Silicon.
- Fleet listens on HTTP port 1337 (FLEET_SERVER_TLS=false). A Cloudflare Tunnel provides public HTTPS at lab.<domain>.
- Secrets (.env, server private key, tunnel credentials) are kept outside this repo.
- Fleet web address is set to the public HTTPS URL, which devices need for enrollment and MDM.
- Apple MDM turned on with an APNs certificate from Apple's Push Certificates Portal (personal Apple ID; renews yearly, reminder set two weeks before expiry).
- macOS baseline (firewall, stealth mode, screen lock, Gatekeeper) is verified with 4 Fleet policies: all passing on fleet-macos-lab. Profiles were installed manually because the VM can't obtain an APNs push token; MDM delivery is ready in Git for physical hardware.
- FileVault: enforced disk encryption with key escrow is a Fleet Premium feature, so it isn't enforced in this lab. A FileVault profile without key escrow was deliberately not used, because it risks unrecoverable devices.
